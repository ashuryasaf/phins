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

Error responses use the platform's ``{"error": "..."}`` convention.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
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

def _handle_otp_request(application_id: str, client_ip: str,
                        user_agent: str) -> Tuple[int, Dict[str, Any]]:
    svc = _service()
    email = svc.contact_email(application_id)
    if not email:
        return 409, {"error": "I need your email before I can send a verification code."}

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
        return 503, {"error": "We couldn't deliver your verification code right now. Please try again.",
                     "error_code": "OTP_DELIVERY_FAILED"}

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
        response = {"error": prep.get("error")}
        if prep.get("submission"):
            response["submission"] = prep["submission"]
        return prep.get("status_code", 400), response

    payload = prep["payload"]
    checksum = prep["checksum"]
    status, created = _loopback_policy_create(handler, payload)
    if status not in (200, 201):
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
    _pop_and_write_events(outcome)
    return 201, {
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
        return 200, _service().funnel_snapshot()

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
                return status, otp_response
            result["otp"] = otp_response
        return 200, result

    match = _ID_RE.match(path)
    if not match:
        return 404, {"error": "Not found"}
    application_id, tail = match.group(1), (match.group(2) or "")

    if tail == "/message":
        result = svc.submit_answer(application_id, body.get("value"),
                                   step_id=body.get("step"))
        _pop_and_write_events(result)
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
