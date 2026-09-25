"""HTTP adapter for the claims chat (Phin, claims agent).

Mirrors `/api/chat-application`: resume-code (or staff / owning-customer)
authorization, the same OTP service, and a loopback into `POST /api/claims/create`
so ledger, files, and assessment ingestion stay on the claims pipeline.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("phins.claims_chat.api")

_STAFF_ROLES = {
    "admin", "underwriter", "actuary", "analyst", "accountant",
    "claims", "claims_adjuster", "claims_agent", "claims_manager", "adjuster",
}
_OTP_CHANNELS = ("email", "sms", "whatsapp")
_ID_RE = re.compile(r"^/api/claims-chat/(CLCHAT-[A-Z0-9]+)(/[a-z/]+)?$")
_OTP_UNAVAILABLE = (
    "I can't send a verification code from this server right now. "
    "Please try again shortly."
)
_STARTS: Dict[str, list] = {}


def _service():
    from services.claims_chat_service import get_claims_chat_service
    return get_claims_chat_service()


def _portal():
    try:
        from web_portal import server as portal
    except ImportError:  # pragma: no cover
        import server as portal  # type: ignore
    return portal


def _is_staff(session: Optional[Dict[str, Any]]) -> bool:
    return bool(session) and str(session.get("role") or "").lower() in _STAFF_ROLES


def _role(session: Optional[Dict[str, Any]]) -> str:
    return str((session or {}).get("role") or "").lower()


def _write_ledger_events(events) -> None:
    if not events:
        return
    portal = _portal()
    ledger = getattr(portal, "platform_event_ledger", None)
    if ledger is None:
        return
    for event in events:
        try:
            ledger.append_event(
                event_type=event["event_type"],
                entity_type=event.get("entity_type", "claims_chat"),
                entity_id=event.get("entity_id", ""),
                customer_id=event.get("customer_id"),
                actor=event.get("actor", "system"),
                amount=float(event.get("amount", 0.0)),
                status=event.get("status", "recorded"),
                source_system="claims_chat",
                payload=event.get("payload") or {},
                entry_id=event.get("entry_id"),
                ledger_type="event",
            )
        except Exception as exc:
            logger.warning("Claims chat ledger write failed (%s): %s", event.get("event_type"), exc)


def _pop_events(result: Dict[str, Any]) -> Dict[str, Any]:
    _write_ledger_events(result.pop("ledger_events", None))
    return result


def _rate_limit(client_ip: str) -> bool:
    now = time.time()
    window = [t for t in _STARTS.get(client_ip, []) if now - t < 600]
    if len(window) >= 30:
        _STARTS[client_ip] = window
        return False
    window.append(now)
    _STARTS[client_ip] = window
    return True


def _customer_context(customer_id: str) -> Optional[Dict[str, Any]]:
    from services.claims_chat_service import active_policies_for, profile_from_customer
    portal = _portal()
    customers = getattr(portal, "CUSTOMERS", {}) or {}
    record = customers.get(customer_id)
    if not isinstance(record, dict):
        return None
    return {
        "profile": profile_from_customer(record),
        "policies": active_policies_for(customer_id, getattr(portal, "POLICIES", {}) or {}),
    }


def _authorize(application_id: str, body: Dict[str, Any], session: Optional[Dict[str, Any]]) -> bool:
    svc = _service()
    return svc.authorize(
        application_id,
        (body or {}).get("resume_code"),
        staff=_is_staff(session),
        customer_id=(session or {}).get("customer_id"),
    )


def _otp_delivery_ready(channel: str) -> bool:
    try:
        from web_portal.api_extensions import _demo_otp_exposure_allowed
    except ImportError:  # pragma: no cover
        from api_extensions import _demo_otp_exposure_allowed  # type: ignore
    if _demo_otp_exposure_allowed():
        return True
    try:
        from services.notification_service import (
            get_active_email_provider_type,
            get_active_sms_provider_type,
        )
    except Exception:
        return True
    if channel == "email":
        return get_active_email_provider_type() not in ("noop", "mock")
    if channel == "sms":
        return get_active_sms_provider_type() not in ("noop", "mock")
    try:
        from web_portal.api_extensions import _whatsapp_provider_configured
    except ImportError:
        from api_extensions import _whatsapp_provider_configured  # type: ignore
    ready, _provider = _whatsapp_provider_configured()
    return ready


def _handle_otp_request(application_id: str, client_ip: str, user_agent: str,
                        body: Optional[Dict[str, Any]]) -> Tuple[int, Dict[str, Any]]:
    svc = _service()
    email = svc.verification_email(application_id)
    if not email:
        return 409, {"error": "I need your email before I can send a verification code."}
    requested = str((body or {}).get("delivery_channel") or "email").strip().lower()
    if requested not in _OTP_CHANNELS:
        return 400, {"error": "Choose Email, SMS, or WhatsApp.", "error_code": "UNSUPPORTED_CHANNEL"}
    phone = svc.verification_phone(application_id) if requested in ("sms", "whatsapp") else None
    if requested in ("sms", "whatsapp") and not phone:
        return 409, {"error": "I need your phone before I can send a text or WhatsApp code.",
                     "error_code": "MISSING_PHONE"}
    if not _otp_delivery_ready(requested):
        return 503, {"error": _OTP_UNAVAILABLE, "error_code": "OTP_DELIVERY_UNAVAILABLE", "retryable": True}

    from services.otp_security_service import OTPPurpose, get_otp_security_service
    purpose = OTPPurpose.PHONE_VERIFICATION if requested in ("sms", "whatsapp") else OTPPurpose.EMAIL_VERIFICATION
    otp_service = get_otp_security_service()
    result = otp_service.create_otp_verification(
        user_type="claimant",
        user_id=application_id,
        email=email,
        purpose=purpose,
        ip_address=client_ip,
        user_agent=user_agent,
        delivery_channel=requested,
        phone=phone,
    )
    if not result.success:
        status = 429 if result.error_code == "RATE_LIMITED" else 400
        return status, {"error": result.message or "Could not create a verification code",
                        "error_code": result.error_code}
    data = result.data or {}
    noted = svc.note_otp_requested(application_id, data.get("verification_id"), channel=requested)
    if not noted.get("ok"):
        return noted.get("status_code", 409), {"error": noted.get("error")}
    try:
        from web_portal.api_extensions import _demo_otp_exposure_allowed, _send_otp_via_channel
    except ImportError:  # pragma: no cover
        from api_extensions import _demo_otp_exposure_allowed, _send_otp_via_channel  # type: ignore
    delivered, delivery_error = _send_otp_via_channel(
        requested, data.get("otp_code"), int(data.get("expires_in_seconds") or 300),
        purpose.value, email=email, phone=phone, ip_address=client_ip,
        verification_id=data.get("verification_id"),
    )
    response = {
        "success": True,
        "verification_id": data.get("verification_id"),
        "delivery_channel": requested,
        "masked_email": data.get("masked_email"),
        "masked_phone": data.get("masked_phone"),
        "expires_in_seconds": data.get("expires_in_seconds"),
        "notification_sent": bool(delivered),
        "otp_channels": list(_OTP_CHANNELS),
    }
    if _demo_otp_exposure_allowed() and not otp_service.has_external_pin(data.get("verification_id")):
        response["demo_otp_code"] = data.get("otp_code")
    elif not delivered:
        logger.error("Claims chat OTP delivery failed (%s): %s", requested, delivery_error)
        return 503, {"error": _OTP_UNAVAILABLE, "error_code": "OTP_DELIVERY_FAILED", "retryable": True}
    _write_ledger_events([{
        "event_type": "claims_chat.otp_requested",
        "entity_type": "claims_chat",
        "entity_id": application_id,
        "customer_id": email,
        "actor": "claimant",
        "payload": {"application_id": application_id, "delivery_channel": requested,
                    "masked_email": data.get("masked_email"), "delivered": bool(delivered)},
    }])
    return 200, response


def _handle_otp_verify(application_id: str, body: Dict[str, Any], client_ip: str) -> Tuple[int, Dict[str, Any]]:
    svc = _service()
    otp_code = str(body.get("otp_code") or "").strip()
    verification_id = str(body.get("verification_id") or svc.pending_verification_id(application_id) or "").strip()
    if not otp_code or not verification_id:
        return 400, {"error": "verification_id and otp_code are required"}
    from services.otp_security_service import OTPPurpose, get_otp_security_service
    otp_service = get_otp_security_service()
    result = otp_service.verify_otp(verification_id, otp_code, ip_address=client_ip)
    if not result.success:
        status = 429 if result.error_code == "MAX_ATTEMPTS" else 400
        return status, {"error": result.message or "Verification failed", "error_code": result.error_code}
    channel = str((result.data or {}).get("delivery_channel") or "email").strip().lower()
    purpose = OTPPurpose.PHONE_VERIFICATION if channel in ("sms", "whatsapp") else OTPPurpose.EMAIL_VERIFICATION
    consume = otp_service.consume_verification(
        verification_id,
        expected_email=svc.verification_email(application_id),
        expected_purpose=purpose,
        ip_address=client_ip,
        expected_user_type="claimant",
        expected_phone=svc.verification_phone(application_id) if channel in ("sms", "whatsapp") else None,
    )
    if not consume.success:
        return 400, {"error": consume.message or "Verification could not be consumed",
                     "error_code": consume.error_code}
    outcome = svc.mark_identity_verified(application_id, channel=channel)
    if not outcome.get("ok"):
        return outcome.get("status_code", 400), {"error": outcome.get("error")}
    _pop_events(outcome)
    outcome.pop("ok", None)
    return 200, {"success": True, **outcome}


def _loopback_claim_create(handler, payload: Dict[str, Any], token: Optional[str]) -> Tuple[int, Dict[str, Any]]:
    try:
        port = handler.server.server_address[1]
    except Exception:
        import os
        port = int(os.environ.get("PORT") or os.environ.get("TEST_PORT") or 8000)
    url = f"http://127.0.0.1:{port}/api/claims/create"
    headers = {"Content-Type": "application/json", "User-Agent": "phins-claims-chat/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {"error": f"Claim creation failed with status {exc.code}"}
    except Exception as exc:
        logger.error("Claims chat loopback failed: %s", exc)
        return 502, {"error": "Could not reach the claim filing service"}


def _reconcile_identity(customer_id: str, national_id: str, nationality: str, actor: str) -> Dict[str, Any]:
    from services.customer_identity_service import reconcile_pipeline_identity
    portal = _portal()
    mirrors = []
    registered = getattr(portal, "REGISTERED_CUSTOMERS", None)
    if isinstance(registered, dict):
        mirrors.append(registered)
    return reconcile_pipeline_identity(
        portal.CUSTOMERS, customer_id, national_id, nationality,
        source="claims", actor=actor or "claims_chat",
        mirrors=mirrors,
        audit=getattr(portal, "audit", None),
        ledger=getattr(portal, "platform_event_ledger", None),
    )


def _notify(facts: Dict[str, Any], claim_id: str, checksum: str) -> Dict[str, Any]:
    try:
        from services.secure_notification_pipeline import (
            NotificationChannel,
            NotificationPriority,
            PushNotificationRequest,
            PushNotificationType,
            get_secure_notification_pipeline,
        )
        amount = facts.get("claimed_amount")
        message = (
            f"Claim {claim_id} was filed and is pending review. "
            f"Policy {facts.get('policy_id')}. Type {facts.get('type')}. "
            f"Incident {facts.get('incident_date')} at {facts.get('incident_location')}. "
            f"Amount USD {amount}. Checksum {str(checksum)[:16]}."
        )
        result = get_secure_notification_pipeline().send_push_notification(PushNotificationRequest(
            notification_type=PushNotificationType.CLAIM_SUBMITTED,
            customer_id=str(facts.get("customer_id") or ""),
            title=f"Claim {claim_id} submitted",
            message=message,
            data={
                "claim_id": claim_id,
                "policy_id": facts.get("policy_id"),
                "type": facts.get("type"),
                "claimed_amount": amount,
                "incident_date": facts.get("incident_date"),
                "incident_location": facts.get("incident_location"),
                "status": "pending",
                "payload_sha256": checksum,
            },
            channels=[NotificationChannel.EMAIL, NotificationChannel.SMS],
            email=facts.get("contact_email"),
            phone=facts.get("contact_phone"),
            priority=NotificationPriority.HIGH,
            reference_id=claim_id,
        ))
        return {
            "notification_id": result.notification_id,
            "notification_status": "sent" if result.success else "failed",
            "notification_error": result.error_message,
        }
    except Exception as exc:
        logger.warning("Claims chat notification failed: %s", exc)
        return {"notification_id": None, "notification_status": "failed", "notification_error": str(exc)[:200]}


def _run_claims_bot(claim_id: str) -> Dict[str, Any]:
    portal = _portal()
    try:
        from services.claims_bot_service import init_claims_bot_service
        bot = init_claims_bot_service(
            customers=portal.CUSTOMERS,
            policies=portal.POLICIES,
            claims=portal.CLAIMS,
            underwriting=getattr(portal, "UNDERWRITING_APPLICATIONS", {}),
            audit_service=getattr(portal, "audit", None),
        )
        report = bot.generate_probability_report(claim_id)
        if report is None:
            return {"status": "unavailable"}
        recommendation = getattr(report.recommendation, "value", str(report.recommendation))
        return {
            "status": "recorded",
            "fraud_probability": round(float(report.fraud_probability), 4),
            "authenticity_probability": round(float(report.authenticity_probability), 4),
            "risk_level": getattr(report, "risk_level", None),
            "recommendation": recommendation,
            "advisory_only": True,
        }
    except Exception as exc:
        logger.warning("Claims bot pipeline failed for %s: %s", claim_id, exc)
        return {"status": "unavailable", "error": str(exc)[:200]}


def _stamp_processing_file(claim: Dict[str, Any], record_html: str, record_sha: str) -> None:
    import base64
    portal = _portal()
    claim_id = claim.get("id")
    if not claim_id:
        return
    raw = record_html.encode("utf-8")
    file_id = f"FILE-{claim_id}-PROC"
    meta = {
        "id": file_id,
        "name": "claim-processing-record.html",
        "type": "text/html",
        "size": len(raw),
        "uploaded_at": claim.get("filed_date"),
        "note": f"sha256:{record_sha}",
    }
    files = list(claim.get("files") or [])
    files.append(meta)
    claim["files"] = files
    claim["files_count"] = len(files)
    portal.CLAIM_FILES[file_id] = {
        **meta,
        "claim_id": claim_id,
        "customer_id": claim.get("customer_id"),
        "data": base64.b64encode(raw).decode("ascii"),
    }
    try:
        portal.ingest_claim_file_to_assessment(file_id, portal.CLAIM_FILES[file_id])
    except Exception as exc:
        logger.warning("Processing record ingest failed: %s", exc)


def _handle_finalize(application_id: str, handler, token: Optional[str],
                     actor: str) -> Tuple[int, Dict[str, Any]]:
    svc = _service()
    prep = svc.prepare_finalize(application_id)
    if not prep.get("ok"):
        return prep.get("status_code", 400), {"error": prep.get("error")}
    if prep.get("already_submitted"):
        return 200, {
            "success": True,
            "duplicate": True,
            "claim": {"id": (prep.get("submission") or {}).get("claim_id")},
            "submission": prep.get("submission"),
            "document_html": prep.get("document_html"),
            "document_sha256": prep.get("document_sha256"),
            "processing": prep.get("processing"),
            "messages": [],
            "integrity": {"verified": True, "idempotent": True},
        }
    try:
        identity = _reconcile_identity(
            prep["customer_id"], prep["national_id"], prep["nationality"], actor)
    except Exception as exc:
        svc.clear_finalizing(application_id)
        logger.warning("Claims chat identity reconcile failed: %s", exc)
        return 503, {"error": "Identity could not be recorded.", "code": "identity_unavailable"}
    outcome = identity.get("outcome")
    if outcome == "mismatch":
        svc.clear_finalizing(application_id)
        return 409, {"error": identity.get("error") or "Identity does not match the account.",
                     "code": "identity_mismatch"}
    if outcome not in ("captured", "consistent") or not identity.get("reference"):
        svc.clear_finalizing(application_id)
        return 409, {"error": identity.get("error") or "A matching identity is required to file this claim.",
                     "code": identity.get("code") or "identity_required"}
    sealed = svc.seal(application_id, identity["reference"])
    if not sealed.get("ok"):
        svc.clear_finalizing(application_id)
        return sealed.get("status_code", 500), {"error": sealed.get("error")}
    facts = sealed["facts"]
    payload = {
        "customer_id": facts["customer_id"],
        "policy_id": facts["policy_id"],
        "type": facts["type"],
        "description": facts["description"],
        "claimed_amount": float(facts["claimed_amount"]),
        "incident_date": facts["incident_date"],
        "provider": facts["provider"],
        "payment_destination": "health_wallet",
        "files": svc.submission_files(application_id),
        "files_count": len(svc.submission_files(application_id)),
    }
    status, created = _loopback_claim_create(handler, payload, token)
    if status not in (200, 201) or not created.get("id"):
        svc.clear_finalizing(application_id)
        return status if status >= 400 else 502, {
            "error": created.get("error") or "Claim filing did not return a claim id."}
    portal = _portal()
    problems = svc.verify_stored_claim(application_id, created, getattr(portal, "CLAIM_FILES", {}))
    if problems:
        svc.clear_finalizing(application_id)
        logger.error("Claims chat integrity failure for %s: %s", created.get("id"), problems)
        return 409, {"error": "Claim intake failed integrity verification.",
                     "code": "integrity_mismatch", "claim_id": created.get("id")}
    svc.remember_claim(application_id, created["id"])
    notice = _notify(facts, created["id"], sealed["checksum"])
    pipeline = _run_claims_bot(created["id"])
    processing = {
        "claim_id": created["id"],
        "notification_id": notice.get("notification_id"),
        "notification_status": notice.get("notification_status"),
        "pipeline": pipeline,
        "identity_outcome": outcome,
    }
    attached = svc.attach_processing(application_id, processing)
    _stamp_processing_file(created, attached["record_html"], attached["record_sha256"])
    created["incident_location"] = facts.get("incident_location")
    created["claims_chat_id"] = application_id
    created["payload_sha256"] = sealed["checksum"]
    created["document_sha256"] = sealed["document_sha256"]
    created["claims_chat_pipeline"] = pipeline
    created["notification_id"] = notice.get("notification_id")
    live = portal.CLAIMS.get(created["id"])
    if isinstance(live, dict):
        live.update({
            "incident_location": facts.get("incident_location"),
            "claims_chat_id": application_id,
            "payload_sha256": sealed["checksum"],
            "document_sha256": sealed["document_sha256"],
            "claims_chat_pipeline": pipeline,
            "notification_id": notice.get("notification_id"),
        })
    marked = svc.mark_submitted(application_id, created["id"])
    _pop_events(marked)
    return 201, {
        "success": True,
        "claim": {
            "id": created["id"],
            "status": created.get("status"),
            "policy_id": created.get("policy_id"),
            "customer_id": created.get("customer_id"),
            "type": created.get("type"),
            "claimed_amount": created.get("claimed_amount"),
            "nft_token_id": created.get("nft_token_id"),
            "ledger_tx_id": created.get("ledger_tx_id"),
        },
        "submission": marked.get("submission"),
        "messages": marked.get("messages") or [],
        "document_html": sealed["document_html"],
        "document_sha256": sealed["document_sha256"],
        "processing": attached["processing"],
        "processing_html": attached["record_html"],
        "integrity": {
            "verified": True,
            "payload_sha256": sealed["checksum"],
            "document_sha256": sealed["document_sha256"],
            "identity_outcome": outcome,
            "media_count": len(facts.get("media") or []),
        },
    }


def dispatch_get(path: str, session: Optional[Dict[str, Any]],
                 query: Dict[str, Any]) -> Optional[Tuple[int, Dict[str, Any]]]:
    if not path.startswith("/api/claims-chat"):
        return None
    match = _ID_RE.match(path)
    if not match:
        return 404, {"error": "Not found"}
    application_id, tail = match.group(1), (match.group(2) or "")
    resume = ""
    raw = (query or {}).get("resume_code") or ""
    if isinstance(raw, list):
        resume = raw[0] if raw else ""
    else:
        resume = str(raw)
    if not _service().authorize(
        application_id, resume, staff=_is_staff(session),
        customer_id=(session or {}).get("customer_id"),
    ):
        return 403, {"error": "A valid resume code (or staff session) is required"}
    state = _service().public_state(application_id)
    if state is None:
        return 404, {"error": "Claim chat not found"}
    if tail in ("", "/"):
        return 200, state
    if tail == "/document":
        if not state.get("document_html"):
            return 409, {"error": "The notice of loss is available after the claim is filed."}
        return 200, {
            "document_html": state["document_html"],
            "document_sha256": state.get("document_sha256"),
            "claim_id": (state.get("submission") or {}).get("claim_id"),
            "processing": state.get("processing"),
        }
    return 404, {"error": "Not found"}


def dispatch_post(path: str, session: Optional[Dict[str, Any]],
                  body_data: Dict[str, Any], client_ip: str,
                  user_agent: str = "", handler: Any = None,
                  auth_token: Optional[str] = None) -> Optional[Tuple[int, Dict[str, Any]]]:
    if not path.startswith("/api/claims-chat"):
        return None
    body = body_data or {}
    svc = _service()
    if path == "/api/claims-chat/start":
        channel = str(body.get("channel") or "web_chat")[:40]
        # Public page /file-a-claim.html posts channel=external and must not
        # attach a signed-in customer, even if a portal token is also sent.
        if channel == "external":
            if not _rate_limit(client_ip):
                return 429, {"error": "Too many new claim files from this address. Please try again later."}
            result = svc.start_session(
                role="external", username="guest", customer_id=None, channel="external")
            _pop_events(result)
            result.pop("ok", None)
            return 201, result
        if not session:
            return 401, {"error": "Sign in to file a claim."}
        if not _rate_limit(client_ip):
            return 429, {"error": "Too many new claim files from this address. Please try again later."}
        role = _role(session)
        if role == "customer":
            customer_id = session.get("customer_id")
            if not customer_id:
                return 400, {"error": "customer_id unavailable"}
            ctx = _customer_context(str(customer_id))
            if not ctx:
                return 404, {"error": "Customer record not found"}
            result = svc.start_session(
                role="customer", username=str(session.get("username") or customer_id),
                customer_id=str(customer_id), profile=ctx["profile"], policies=ctx["policies"],
                channel=str(body.get("channel") or "web_chat")[:40])
        elif _is_staff(session):
            result = svc.start_session(
                role=role, username=str(session.get("username") or role),
                customer_id=None, channel=str(body.get("channel") or "web_chat")[:40])
        else:
            return 403, {"error": "Claims filing access required"}
        _pop_events(result)
        result.pop("ok", None)
        return 201, result

    if path == "/api/claims-chat/resume":
        result = svc.resume_session(str(body.get("resume_code") or ""), str(body.get("email") or ""))
        if not result.get("ok"):
            return result.get("status_code", 404), {"error": result.get("error")}
        _pop_events(result)
        result.pop("ok", None)
        if result.get("otp_required"):
            status, otp_response = _handle_otp_request(
                result["application_id"], client_ip, user_agent, body)
            if status != 200:
                svc.abort_reverify(result["application_id"])
                return status, otp_response
            result["otp"] = otp_response
        return 200, result

    match = _ID_RE.match(path)
    if not match:
        return 404, {"error": "Not found"}
    application_id, tail = match.group(1), (match.group(2) or "")
    if not _authorize(application_id, body, session):
        return 403, {"error": "A valid resume code (or staff session) is required"}

    if tail == "/message":
        result = svc.submit_answer(application_id, body.get("value"), step_id=body.get("step"))
        _pop_events(result)
        status_code = 200 if result.pop("ok", False) else result.pop("status_code", 400)
        if status_code >= 400 and "error" not in result:
            result["error"] = "Invalid answer"
        return status_code, result
    if tail == "/otp/request":
        return _handle_otp_request(application_id, client_ip, user_agent, body)
    if tail == "/otp/verify":
        return _handle_otp_verify(application_id, body, client_ip)
    if tail == "/media":
        result = svc.attach_media(
            application_id,
            kind=str(body.get("kind") or ""),
            name=str(body.get("name") or ""),
            mime_type=str(body.get("mime_type") or body.get("type") or ""),
            data_b64=str(body.get("data_b64") or body.get("data") or ""),
            duration_seconds=body.get("duration_seconds"),
        )
        _pop_events(result)
        status_code = 200 if result.pop("ok", False) else result.pop("status_code", 400)
        return status_code, result
    if tail == "/pause":
        result = svc.pause_session(application_id)
        _pop_events(result)
        status_code = 200 if result.pop("ok", False) else result.pop("status_code", 400)
        return status_code, result
    if tail == "/finalize":
        actor = str((session or {}).get("username") or "claims_chat")
        try:
            return _handle_finalize(application_id, handler, auth_token, actor)
        except Exception as exc:
            svc.clear_finalizing(application_id)
            logger.exception("Claims chat finalize failed: %s", exc)
            return 500, {"error": "Claim filing failed."}
    return 404, {"error": "Not found"}
