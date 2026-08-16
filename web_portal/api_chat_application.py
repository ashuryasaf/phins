"""
HTTP dispatchers for the chat-style New Policy Application ("Phin" flow).

Wired through ``web_portal/server.py`` exactly like the other extension API
modules. The conversational state machine lives in
``services.chat_application_service``; this layer adds:

- OTP creation + delivery (reuses ``services.otp_security_service`` and the
  delivery/demo-exposure helpers from ``web_portal.api_extensions``)
- invitation-code validation against the platform's admin / customer /
  agent / supplier invitation stores (referral attribution for the BI journey)
- hash-chained ledger writes for every chat turn and journey stage
- final submission through the *existing* ``POST /api/policies/create``
  backbone via an internal loopback request, so policy, underwriting,
  billing, wallet, and pipeline behavior stay identical to the classic form
- staff-facing funnel + journey endpoints that expose the A-Z pipeline
  (invited -> started -> stopped -> continued -> quoted -> submitted ->
  underwritten -> approved -> billed -> paid -> claimed -> ...) for the
  BI center.

Routes
------
POST ``/api/chat-application/start``                 (public)
POST ``/api/chat-application/resume``                (public, code+email)
POST ``/api/chat-application/<id>/message``          (public, session-scoped)
POST ``/api/chat-application/<id>/otp/request``      (public)
POST ``/api/chat-application/<id>/otp/verify``       (public)
POST ``/api/chat-application/<id>/media``            (public, verified only)
POST ``/api/chat-application/<id>/pause``            (public)
POST ``/api/chat-application/<id>/finalize``         (public, verified only)
GET  ``/api/chat-application/<id>``                  (resume code or staff)
GET  ``/api/chat-application/<id>/journey``          (resume code or staff)
GET  ``/api/chat-application/admin/funnel``          (staff only)

When actuarial rules block automated submit (ADL decline / ineligible quote),
the API opens a durable ``UNDERWRITING_APPLICATIONS`` row
(``source=chat_adl_referral``) so underwriters see name / email / phone on
``/underwriter-dashboard.html`` even though no policy was created.

Error responses use the platform's ``{"error": "..."}`` convention.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("phins.chat_application.api")

_STAFF_ROLES = {"admin", "underwriter", "actuary", "analyst", "accountant"}

_ID_RE = re.compile(r"^/api/chat-application/(CHAPP-[A-Z0-9-]+)(/[a-z/]+)?$")

# Per-IP session starts within a rolling hour (basic abuse guard - the OTP
# service has its own rate limits for verification attempts).
_MAX_STARTS_PER_IP_PER_HOUR = 30
_start_tracker: Dict[str, list] = {}


def _service():
    from services.chat_application_service import get_chat_application_service
    return get_chat_application_service()


def _effective_client_ip(socket_ip: str, handler: Any) -> str:
    """Resolve the real applicant IP behind a reverse proxy.

    In production the server sits behind an edge proxy (Railway/Render), so
    ``self.client_address`` is the proxy's private/loopback address for every
    visitor. Rate limits keyed on that shared address would lock the whole
    site after a handful of OTP requests (10/hour/IP in production). When the
    socket peer is a private/loopback hop, trust the address the trusted edge
    appended to ``X-Forwarded-For`` - the *last* (rightmost) entry, which is
    the peer the edge actually observed. A caller can prepend arbitrary
    leftmost hops (``$proxy_add_x_forwarded_for`` preserves them), so the first
    hop is client-controlled and must never be trusted for rate limiting; a
    direct public connection keeps its socket address.
    """
    try:
        peer = ipaddress.ip_address(str(socket_ip or "").strip())
        if not (peer.is_private or peer.is_loopback):
            return socket_ip
    except ValueError:
        return socket_ip
    headers = getattr(handler, "headers", None)
    if not headers:
        return socket_ip
    hops = [h.strip() for h in str(headers.get("X-Forwarded-For") or "").split(",")]
    last_hop = next((h for h in reversed(hops) if h), "")
    if last_hop:
        try:
            ipaddress.ip_address(last_hop)
            return last_hop
        except ValueError:
            pass
    real_ip = str(headers.get("X-Real-IP") or "").strip()
    if real_ip:
        try:
            ipaddress.ip_address(real_ip)
            return real_ip
        except ValueError:
            pass
    return socket_ip


def _is_staff(session: Optional[Dict[str, Any]]) -> bool:
    return bool(session) and str(session.get("role") or "").lower() in _STAFF_ROLES


def _write_ledger_events(events) -> None:
    """Append chat/journey events to the platform's hash-chained ledger.

    Fail-open: the conversation must never break because ledger persistence
    hiccuped, but failures are logged loudly for operators.
    """
    if not events:
        return
    try:
        from web_portal import server as portal
    except ImportError:  # pragma: no cover - flat layout fallback
        import server as portal  # type: ignore
    for event in events:
        try:
            portal.platform_event_ledger.append_event(
                event_type=event["event_type"],
                entity_type=event.get("entity_type", "policy_application"),
                entity_id=event.get("entity_id", ""),
                customer_id=event.get("customer_id"),
                actor=event.get("actor", "system"),
                amount=float(event.get("amount", 0.0)),
                status=event.get("status", "recorded"),
                source_system="chat_policy_application",
                payload=event.get("payload") or {},
                entry_id=event.get("entry_id"),
                ledger_type="event",
            )
        except Exception as exc:
            logger.warning("Chat application ledger write failed (%s): %s",
                           event.get("event_type"), exc)


def _pop_and_write_events(result: Dict[str, Any]) -> Dict[str, Any]:
    events = result.pop("ledger_events", None)
    _write_ledger_events(events)
    return result


def _portal_module():
    try:
        from web_portal import server as portal
    except ImportError:  # pragma: no cover - flat layout fallback
        import server as portal  # type: ignore
    return portal


def _find_or_create_referral_customer(portal, contact: Dict[str, Any]) -> str:
    """Resolve a CUSTOMERS id for staff contact without provisioning a login."""
    email = str(contact.get("email") or "").strip().lower()
    phone = str(contact.get("phone") or "").strip()
    name = str(contact.get("name") or "").strip() or "Chat applicant"
    if email:
        for cust_id, cust in list(getattr(portal, "CUSTOMERS", {}).items()):
            if str((cust or {}).get("email") or "").strip().lower() == email:
                # Refresh contact fields so underwriters see the latest phone/name.
                if phone and not cust.get("phone"):
                    cust["phone"] = phone
                if name and (not cust.get("name") or cust.get("name") == "Unknown"):
                    cust["name"] = name
                cust["updated_date"] = datetime.now(timezone.utc).isoformat()
                portal.CUSTOMERS[cust_id] = cust
                return str(cust_id)
    customer_id = f"CUST-CHATREF-{uuid.uuid4().hex[:10].upper()}"
    now = datetime.now(timezone.utc).isoformat()
    portal.CUSTOMERS[customer_id] = {
        "id": customer_id,
        "name": name,
        "email": email,
        "phone": phone,
        "created_date": now,
        "updated_date": now,
        "source": "chat_adl_referral",
        "status": "lead",
    }
    return customer_id


def _ensure_senior_uw_queue(application_id: str) -> Optional[Dict[str, Any]]:
    """Open (or refresh) a durable underwriting row for a blocked chat file.

    Chat sessions are in-memory; admin/underwriter dashboards read
    ``UNDERWRITING_APPLICATIONS``. Without this bridge, a senior-review
    message is shown to the applicant and nobody on staff can see contact
    details.
    """
    svc = _service()
    snap = svc.senior_referral_snapshot(application_id)
    if not snap:
        return None
    portal = _portal_module()
    contact = snap.get("contact") or {}
    quote = snap.get("quote") or {}
    assessment = snap.get("assessment") or {}
    answers = snap.get("answers") or {}

    existing_id = snap.get("existing_underwriting_id")
    suffix = str(application_id).replace("CHAPP-", "")[:24]
    uw_id = existing_id or f"UW-CHATREF-{suffix}"

    existing = portal.UNDERWRITING_APPLICATIONS.get(uw_id)
    if existing and str(existing.get("status") or "").lower() in ("approved", "rejected"):
        return existing

    customer_id = (existing or {}).get("customer_id") or _find_or_create_referral_customer(
        portal, contact
    )
    now = datetime.now(timezone.utc).isoformat()
    risk = str(
        assessment.get("risk_category")
        or assessment.get("risk_assessment")
        or "high"
    ).lower()
    record = {
        "id": uw_id,
        "status": "pending",
        "source": "chat_adl_referral",
        "application_channel": "chat",
        "chat_application_id": application_id,
        "resume_code": snap.get("resume_code"),
        "recommendation_type": "refer_senior_uw",
        "referral_reason": (
            quote.get("decline_reason")
            or "adl_senior_review_required"
        ),
        "customer_id": customer_id,
        "customer_name": contact.get("name") or "Chat applicant",
        "customer_email": contact.get("email") or "",
        "customer_phone": contact.get("phone") or "",
        "policy_id": None,
        "policy_status": "not_created",
        "policy_type": "life",
        "coverage_amount": quote.get("coverage_amount") or answers.get("coverage_amount") or 0,
        "coverage_years": quote.get("coverage_years") or answers.get("coverage_years"),
        "monthly_premium": quote.get("monthly") or 0,
        "annual_premium": quote.get("annual") or 0,
        "risk_assessment": risk,
        "risk_score": risk,
        "adl_level": quote.get("adl_level") or assessment.get("adl_level"),
        "disability_excluded": bool(quote.get("disability_excluded")),
        "adl_declined": bool(quote.get("adl_declined")),
        "eligible": quote.get("eligible"),
        "questionnaire": {
            "daily_function": answers.get("daily_function"),
            "dob": answers.get("dob"),
            "gender": answers.get("gender"),
            "occupation": answers.get("occupation"),
            "tobacco": answers.get("tobacco"),
            "medical_conditions": answers.get("medical_conditions"),
            "conditions_list": answers.get("conditions_list"),
            "medications": answers.get("medications"),
            "hazardous": answers.get("hazardous"),
            "family_history": answers.get("family_history"),
            "savings_addon": answers.get("savings_addon"),
        },
        "assessment": assessment,
        "quote_summary": quote,
        "media": snap.get("media") or [],
        "email_verified": bool(snap.get("email_verified")),
        "contact_priority": "high",
        "notes": (
            "Automated chat submit blocked by actuarial ADL / eligibility rules. "
            "Senior underwriter must contact the applicant before a policy can be issued."
        ),
        "submitted_date": (existing or {}).get("submitted_date") or now,
        "created_date": (existing or {}).get("created_date") or now,
        "updated_date": now,
        "created_by": "chat_policy_application",
    }
    portal.UNDERWRITING_APPLICATIONS[uw_id] = record

    # Point any vault-backed chat media at the underwriting id so Details /
    # file viewers can find attachments without a policy submission.
    try:
        files = getattr(portal, "UNDERWRITING_FILES", None)
        if isinstance(files, dict):
            for item in snap.get("media") or []:
                doc_id = item.get("persistent_doc_id") or item.get("sha256")
                if not doc_id:
                    continue
                file_id = f"UWF-{uw_id}-{str(doc_id)[:16]}"
                if file_id in files:
                    continue
                files[file_id] = {
                    "id": file_id,
                    "application_id": uw_id,
                    "chat_application_id": application_id,
                    "name": item.get("name"),
                    "type": item.get("mime_type"),
                    "size": item.get("size"),
                    "sha256": item.get("sha256"),
                    "kind": item.get("kind"),
                    "persistent_doc_id": item.get("persistent_doc_id"),
                    "storage_path": item.get("storage_path"),
                    "uploaded_at": now,
                    "source": "chat_adl_referral",
                }
    except Exception as exc:
        logger.warning("Senior referral media link failed for %s: %s", application_id, exc)

    outcome = svc.mark_senior_referred(application_id, underwriting_id=uw_id)
    _pop_and_write_events(outcome)
    return record


def _maybe_queue_senior_referral(application_id: str, result: Dict[str, Any]) -> None:
    """If a quote/result requires senior review, open the staff queue row."""
    quote = result.get("quote") or {}
    if not (quote.get("adl_declined") or quote.get("eligible") is False
            or result.get("needs_senior_referral")):
        return
    try:
        referral = _ensure_senior_uw_queue(application_id)
    except Exception as exc:
        logger.warning("Senior UW queue failed for %s: %s", application_id, exc)
        return
    if referral:
        result["senior_referral"] = {
            "underwriting_id": referral.get("id"),
            "status": referral.get("status"),
            "customer_email": referral.get("customer_email"),
            "customer_phone": referral.get("customer_phone"),
        }


def _validate_invite_code(code: str) -> Optional[Dict[str, Any]]:
    """Best-effort referral attribution across the four invitation systems."""
    code = str(code or "").strip().upper()
    if not code:
        return None
    try:
        from web_portal import server as portal
    except ImportError:  # pragma: no cover
        import server as portal  # type: ignore

    def _active(inv: Dict[str, Any]) -> bool:
        if not inv:
            return False
        if str(inv.get("status") or "active").lower() not in ("active", "sent", "approved"):
            return False
        if inv.get("max_uses") and inv.get("used_count", 0) >= inv["max_uses"]:
            return False
        return True

    try:
        inv = portal.INVITATION_CODES.get(code)
        if _active(inv):
            return {"code": code, "type": "admin",
                    "referrer_id": inv.get("created_by")}
        inv = portal.CUSTOMER_INVITATIONS.get(code)
        if _active(inv):
            return {"code": code, "type": "customer",
                    "referrer_id": inv.get("creator_customer_id")}
    except Exception as exc:
        logger.debug("Platform invitation lookup failed: %s", exc)

    try:  # agent ecosystem invitations (AGI-...)
        from services.agent_ecosystem_service import INVITATIONS as AGENT_INVITATIONS
        for inv in AGENT_INVITATIONS.values():
            if str(inv.get("code") or "").upper() == code and _active(inv):
                return {"code": code, "type": "agent",
                        "referrer_id": inv.get("agent_id")}
    except Exception as exc:
        logger.debug("Agent invitation lookup failed: %s", exc)

    try:  # supplier / supply-chain invitations (PHINS-SUP-...)
        for inv in getattr(portal, "SUPPLIER_INVITATIONS", {}).values():
            if str(inv.get("code") or "").upper() == code and _active(inv):
                return {"code": code, "type": "supplier",
                        "referrer_id": inv.get("referrer_id") or inv.get("created_by")}
    except Exception as exc:
        logger.debug("Supplier invitation lookup failed: %s", exc)
    return None


def _rate_limit_start(client_ip: str) -> bool:
    import time
    now = time.time()
    window = _start_tracker.setdefault(client_ip or "unknown", [])
    window[:] = [t for t in window if now - t < 3600]
    if len(window) >= _MAX_STARTS_PER_IP_PER_HOUR:
        return False
    window.append(now)
    return True


# ---------------------------------------------------------------------------
# OTP helpers (reuse the platform OTP service + delivery from api_extensions)
# ---------------------------------------------------------------------------

_OTP_UNAVAILABLE_MESSAGE = (
    "Our verification service is temporarily unavailable. Your progress is "
    "saved under your resume code - please try again in a few minutes, or "
    "use the classic application form at /apply.html."
)


def _otp_delivery_ready() -> Tuple[bool, str]:
    """Pre-flight: can this deployment actually deliver an OTP email?

    Production refuses demo-code exposure (correctly), so when no email
    provider is configured (``active provider == 'noop'``) every OTP request
    is doomed. Detecting that before minting a verification keeps the OTP
    service's per-IP counters and the session state clean.
    """
    try:
        from web_portal.api_extensions import _demo_otp_exposure_allowed
    except ImportError:  # pragma: no cover
        from api_extensions import _demo_otp_exposure_allowed  # type: ignore
    if _demo_otp_exposure_allowed():
        return True, "demo_exposure"
    try:
        from services.notification_service import get_active_email_provider_type
        provider = get_active_email_provider_type()
    except Exception as exc:  # pragma: no cover - diagnostics must fail open
        logger.warning("OTP delivery pre-flight failed: %s", exc)
        return True, "unknown"
    if provider in ("noop", "mock"):
        return False, provider
    return True, provider


def _handle_otp_request(application_id: str, client_ip: str,
                        user_agent: str) -> Tuple[int, Dict[str, Any]]:
    svc = _service()
    email = svc.contact_email(application_id)
    if not email:
        return 409, {"error": "I need your email before I can send a verification code."}

    ready, provider = _otp_delivery_ready()
    if not ready:
        logger.error(
            "Chat application OTP blocked: no email provider configured "
            "(active provider '%s'). Set EMAIL_PROVIDER plus its credentials "
            "(e.g. INFOBIP_API_KEY+INFOBIP_BASE_URL, SENDGRID_API_KEY, "
            "MAILGUN_API_KEY, RESEND_API_KEY, or SMTP_HOST + SMTP_USERNAME + "
            "SMTP_PASSWORD). Disable PHINS_TEST_MODE / "
            "PHINS_USE_MOCK_NOTIFICATIONS in production.", provider)
        return 503, {"error": _OTP_UNAVAILABLE_MESSAGE,
                     "error_code": "OTP_DELIVERY_UNAVAILABLE",
                     "retryable": True}

    from services.otp_security_service import OTPPurpose, get_otp_security_service
    otp_service = get_otp_security_service()
    result = otp_service.create_otp_verification(
        user_type="applicant",
        user_id=application_id,
        email=email,
        purpose=OTPPurpose.EMAIL_VERIFICATION,
        ip_address=client_ip,
        user_agent=user_agent,
        delivery_channel="email",
    )
    if not result.success:
        return 429 if result.error_code == "RATE_LIMITED" else 400, {
            "error": result.message or "Could not create verification code",
            "error_code": result.error_code,
        }

    data = result.data or {}
    otp_code = data.get("otp_code")
    verification_id = data.get("verification_id")
    svc.note_otp_requested(application_id, verification_id)

    try:
        from web_portal.api_extensions import (
            _demo_otp_exposure_allowed,
            _send_otp_via_channel,
        )
    except ImportError:  # pragma: no cover
        from api_extensions import (  # type: ignore
            _demo_otp_exposure_allowed,
            _send_otp_via_channel,
        )

    delivered, delivery_error = _send_otp_via_channel(
        "email", otp_code, int(data.get("expires_in_seconds") or 300),
        "email_verification", email=email, ip_address=client_ip,
    )

    response: Dict[str, Any] = {
        "success": True,
        "verification_id": verification_id,
        "masked_email": data.get("masked_email"),
        "expires_in_seconds": data.get("expires_in_seconds"),
        "notification_sent": bool(delivered),
    }
    if _demo_otp_exposure_allowed():
        response["demo_otp_code"] = otp_code
    elif not delivered:
        logger.error("Chat application OTP delivery failed: %s", delivery_error)
        return 503, {"error": _OTP_UNAVAILABLE_MESSAGE,
                     "error_code": "OTP_DELIVERY_FAILED",
                     "retryable": True}

    _write_ledger_events([{
        "event_type": "chat.otp_requested",
        "entity_id": application_id,
        "customer_id": email,
        "actor": "applicant",
        "payload": {"application_id": application_id,
                    "masked_email": data.get("masked_email"),
                    "delivered": bool(delivered)},
    }])
    return 200, response


def _handle_otp_verify(application_id: str, body: Dict[str, Any],
                       client_ip: str) -> Tuple[int, Dict[str, Any]]:
    svc = _service()
    otp_code = str(body.get("otp_code") or "").strip()
    verification_id = str(body.get("verification_id") or
                          svc.pending_verification_id(application_id) or "").strip()
    if not otp_code or not verification_id:
        return 400, {"error": "verification_id and otp_code are required"}

    from services.otp_security_service import OTPPurpose, get_otp_security_service
    otp_service = get_otp_security_service()
    result = otp_service.verify_otp(verification_id, otp_code, ip_address=client_ip)
    if not result.success:
        status = 429 if result.error_code == "MAX_ATTEMPTS" else 400
        return status, {"error": result.message or "Verification failed",
                        "error_code": result.error_code}

    consume = otp_service.consume_verification(
        verification_id,
        expected_email=svc.contact_email(application_id),
        expected_purpose=OTPPurpose.EMAIL_VERIFICATION,
        ip_address=client_ip,
        expected_user_type="applicant",
    )
    if not consume.success:
        return 400, {"error": consume.message or "Verification could not be consumed",
                     "error_code": consume.error_code}

    outcome = svc.mark_email_verified(application_id)
    if not outcome.get("ok"):
        return outcome.get("status_code", 400), {"error": outcome.get("error")}
    _pop_and_write_events(outcome)
    outcome.pop("ok", None)
    return 200, {"success": True, **outcome}


# ---------------------------------------------------------------------------
# Finalize: submit through the existing policy-creation backbone
# ---------------------------------------------------------------------------

def _loopback_policy_create(handler, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """POST the composed application to this server's own /api/policies/create.

    Running the submission through the real route (instead of duplicating
    ~400 lines of policy/underwriting/billing/wallet wiring) keeps the chat
    flow byte-for-byte consistent with the classic form and preserves every
    downstream ledger/BI hook that route already fires.
    """
    try:
        port = handler.server.server_address[1]
    except Exception:
        import os
        port = int(os.environ.get("PORT") or os.environ.get("TEST_PORT") or 8000)
    url = f"http://127.0.0.1:{port}/api/policies/create"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json",
                 "User-Agent": "phins-chat-application/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {"error": f"Policy creation failed with status {exc.code}"}
    except Exception as exc:
        logger.error("Chat application loopback submission failed: %s", exc)
        return 502, {"error": "Could not reach the policy creation service"}


def _handle_finalize(application_id: str, handler) -> Tuple[int, Dict[str, Any]]:
    svc = _service()
    prep = svc.prepare_finalize(application_id)
    if not prep.get("ok"):
        response: Dict[str, Any] = {"error": prep.get("error")}
        if prep.get("submission"):
            response["submission"] = prep["submission"]
        # ADL / eligibility blocks must still land on the underwriter queue
        # with contact details — otherwise the applicant is told a senior
        # underwriter will reach out, and staff have nothing to work from.
        if prep.get("needs_senior_referral") or (
            "senior underwriter" in str(prep.get("error") or "").lower()
        ):
            try:
                referral = _ensure_senior_uw_queue(application_id)
            except Exception as exc:
                logger.warning(
                    "Senior UW queue on blocked finalize failed for %s: %s",
                    application_id, exc,
                )
                referral = None
            if referral:
                response["senior_referral"] = {
                    "underwriting_id": referral.get("id"),
                    "status": referral.get("status"),
                    "customer_email": referral.get("customer_email"),
                    "customer_phone": referral.get("customer_phone"),
                }
                response["underwriting_id"] = referral.get("id")
        return prep.get("status_code", 400), response

    payload = prep["payload"]
    checksum = prep["checksum"]
    status, created = _loopback_policy_create(handler, payload)
    if status not in (200, 201):
        # Release the in-flight guard so the applicant can retry submission.
        svc.clear_finalizing(application_id)
        return status if status >= 400 else 502, {
            "error": created.get("error") or "Application submission failed"}

    policy = created.get("policy") or {}
    underwriting = created.get("underwriting") or {}
    customer = created.get("customer") or {}
    outcome = svc.mark_submitted(
        application_id,
        policy_id=str(policy.get("id") or ""),
        underwriting_id=str(underwriting.get("id") or ""),
        customer_id=customer.get("id"),
        checksum=checksum,
    )
    if not outcome.get("ok"):
        return outcome.get("status_code", 409), {
            "error": outcome.get("error"),
            "submission": outcome.get("submission")}
    _pop_and_write_events(outcome)

    # Single-use claim code so the applicant can open "Track my application"
    # and finish account setup with just a password (see
    # services/application_claim_service.py for the takeover guards).
    claim: Dict[str, Any] = {}
    try:
        from services.application_claim_service import get_application_claim_service

        state = svc.get_state(application_id, staff=True)
        contact = state.get("contact") or {}
        claim = get_application_claim_service().issue(
            application_id=application_id,
            customer_id=str(customer.get("id") or ""),
            email=str(contact.get("email") or ""),
            policy_id=str(policy.get("id") or ""),
            underwriting_id=str(underwriting.get("id") or ""),
            customer_name=str(contact.get("name") or ""),
            phone=str(contact.get("phone") or ""),
            summary={
                "coverage_amount": (state.get("quote") or {}).get("coverage_amount"),
                "coverage_years": (state.get("quote") or {}).get("coverage_years"),
                "monthly_premium": policy.get("monthly_premium"),
                "annual_premium": policy.get("annual_premium"),
                "policy_status": policy.get("status"),
                "underwriting_status": underwriting.get("status"),
            },
        )
    except Exception as exc:
        logger.warning("Claim code issue failed for %s: %s", application_id, exc)

    response = {
        "success": True,
        "application_id": application_id,
        "submission": outcome.get("submission"),
        "messages": outcome.get("messages") or [],
        "policy": {"id": policy.get("id"), "status": policy.get("status"),
                   "annual_premium": policy.get("annual_premium"),
                   "monthly_premium": policy.get("monthly_premium")},
        "underwriting": {"id": underwriting.get("id"),
                         "status": underwriting.get("status")},
        "customer": {"id": customer.get("id")},
        "provisioned_login": created.get("provisioned_login"),
        "payload_checksum": checksum,
    }
    if claim.get("ok"):
        response["claim"] = {
            "claim_code": claim["claim_code"],
            "expires_at": claim["expires_at"],
            "track_url": f"/track-application.html?code={claim['claim_code']}",
        }
    return 201, response


# ---------------------------------------------------------------------------
# Journey (A-Z pipeline view for BI)
# ---------------------------------------------------------------------------

_JOURNEY_LEDGER_TYPES = (
    "journey.", "chat.", "policy_", "billing_", "bill_", "payment",
    "claim", "premium", "wallet", "marketplace", "invitation",
)


def _handle_journey(application_id: str) -> Tuple[int, Dict[str, Any]]:
    svc = _service()
    base = svc.journey_for(application_id)
    if base is None:
        return 404, {"error": "Application not found"}

    ledger_events = []
    try:
        try:
            from web_portal import server as portal
        except ImportError:  # pragma: no cover
            import server as portal  # type: ignore
        customer_id = (base.get("submission") or {}).get("customer_id") or base.get("customer_id")
        for entry in list(portal.TRANSACTION_LEDGER.values()):
            etype = str(entry.get("event_type") or entry.get("type") or "")
            related = (
                entry.get("entity_id") == application_id
                or (entry.get("payload") or {}).get("application_id") == application_id
                or (customer_id and entry.get("customer_id") == customer_id)
            )
            if related and any(etype.startswith(p) for p in _JOURNEY_LEDGER_TYPES):
                ledger_events.append({
                    "id": entry.get("id"),
                    "event_type": etype,
                    "entity_type": entry.get("entity_type"),
                    "entity_id": entry.get("entity_id"),
                    "customer_id": entry.get("customer_id"),
                    "actor": entry.get("actor"),
                    "amount": entry.get("amount"),
                    "status": entry.get("status"),
                    "timestamp": entry.get("timestamp"),
                    "sequence_no": entry.get("sequence_no"),
                    "entry_hash": entry.get("entry_hash"),
                })
        ledger_events.sort(key=lambda e: (e.get("sequence_no") or 0,
                                          str(e.get("timestamp") or "")))
    except Exception as exc:
        logger.warning("Chat application journey ledger scan failed: %s", exc)

    return 200, {**base, "ledger_events": ledger_events,
                 "ledger_event_count": len(ledger_events)}


# ---------------------------------------------------------------------------
# Dispatchers
# ---------------------------------------------------------------------------

def dispatch_get(path: str, session: Optional[Dict[str, Any]],
                 query_params: Dict[str, Any],
                 client_ip: str) -> Optional[Tuple[int, Dict[str, Any]]]:
    if not path.startswith("/api/chat-application"):
        return None

    if path == "/api/chat-application/admin/funnel":
        if not _is_staff(session):
            return 403, {"error": "Staff access required"}
        snapshot = _service().funnel_snapshot()
        # Ops visibility: the OTP gate is the funnel's hardest dependency, so
        # surface whether this deployment can actually deliver codes.
        ready, provider = _otp_delivery_ready()
        snapshot["otp_delivery"] = {"ready": ready, "email_provider": provider}
        return 200, snapshot

    match = _ID_RE.match(path)
    if not match:
        return 404, {"error": "Not found"}
    application_id, tail = match.group(1), (match.group(2) or "")

    def _qp(name: str) -> Optional[str]:
        value = query_params.get(name)
        if isinstance(value, list):
            return value[0] if value else None
        return value

    svc = _service()
    staff = _is_staff(session)
    if not svc.authorize_access(application_id, _qp("resume_code"), staff):
        return 403, {"error": "A valid resume code (or staff session) is required"}

    if tail == "/journey":
        return _handle_journey(application_id)
    if tail == "":
        state = svc.get_state(application_id, staff=staff)
        if not state.get("ok"):
            return state.get("status_code", 404), {"error": state.get("error")}
        state.pop("ok", None)
        return 200, state
    return 404, {"error": "Not found"}


def dispatch_post(path: str, session: Optional[Dict[str, Any]],
                  body_data: Dict[str, Any], client_ip: str,
                  user_agent: str = "",
                  handler: Any = None) -> Optional[Tuple[int, Dict[str, Any]]]:
    if not path.startswith("/api/chat-application"):
        return None
    body = body_data or {}
    svc = _service()
    # Behind the production edge proxy every visitor shares one socket IP;
    # key rate limits on the forwarded applicant address instead.
    client_ip = _effective_client_ip(client_ip, handler)

    if path == "/api/chat-application/start":
        if not _rate_limit_start(client_ip):
            return 429, {"error": "Too many new applications from this address. Please try again later."}
        invite = _validate_invite_code(body.get("invite_code") or body.get("ref") or "")
        started_by = "applicant"
        if _is_staff(session):
            started_by = f"{session.get('role')}:{session.get('username')}"
        result = svc.start_session(
            channel=str(body.get("channel") or "web_chat")[:40],
            invite=invite,
            started_by=started_by,
        )
        _pop_and_write_events(result)
        result.pop("ok", None)
        if body.get("invite_code") and not invite:
            result["invite_note"] = "Invitation code not recognized - continuing without referral."
        return 201, result

    if path == "/api/chat-application/resume":
        result = svc.resume_session(str(body.get("resume_code") or ""),
                                    str(body.get("email") or ""))
        if not result.get("ok"):
            return result.get("status_code", 404), {"error": result.get("error")}
        _pop_and_write_events(result)
        result.pop("ok", None)
        if result.get("otp_required"):
            application_id = result["application_id"]
            status, otp_response = _handle_otp_request(application_id, client_ip, user_agent)
            if status != 200:
                # The session was already flipped to pending_reverify; roll
                # that back so a failed code delivery neither bricks the
                # session nor lets a later resume skip the OTP re-challenge.
                svc.abort_reverify(application_id)
                return status, otp_response
            result["otp"] = otp_response
        return 200, result

    match = _ID_RE.match(path)
    if not match:
        return 404, {"error": "Not found"}
    application_id, tail = match.group(1), (match.group(2) or "")

    # Every id-scoped mutation (advance answers, attach media, request/verify
    # OTP, pause, finalize) must prove possession of the resume code (or be a
    # staff session). Application ids are low-entropy, so without this an
    # enumerated id would be enough to drive someone else's application.
    if not svc.authorize_access(application_id, body.get("resume_code"), _is_staff(session)):
        return 403, {"error": "A valid resume code (or staff session) is required"}

    if tail == "/message":
        result = svc.submit_answer(application_id, body.get("value"),
                                   step_id=body.get("step"))
        _pop_and_write_events(result)
        _maybe_queue_senior_referral(application_id, result)
        status_code = 200 if result.pop("ok", False) else result.pop("status_code", 400)
        if status_code >= 400 and "error" not in result:
            result["error"] = "Invalid answer"
        return status_code, result

    if tail == "/otp/request":
        return _handle_otp_request(application_id, client_ip, user_agent)

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
        _pop_and_write_events(result)
        status_code = 200 if result.pop("ok", False) else result.pop("status_code", 400)
        return status_code, result

    if tail == "/pause":
        result = svc.pause_session(application_id)
        _pop_and_write_events(result)
        status_code = 200 if result.pop("ok", False) else result.pop("status_code", 400)
        return status_code, result

    if tail == "/finalize":
        return _handle_finalize(application_id, handler)

    return 404, {"error": "Not found"}
