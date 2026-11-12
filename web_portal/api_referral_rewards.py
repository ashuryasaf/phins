"""HTTP surface for the referral acquisition-reward chain.

Routes (dispatched from ``web_portal/server.py``):

  GET  /api/customer/referral-rewards              own book (customer, agent, supplier)
  POST /api/customer/referral-rewards/accept       {reward_id, allocation?}
  POST /api/customer/referral-rewards/accept-all   {allocation?}
  GET  /api/customer/professional-requests         own agent/supplier requests
  POST /api/customer/professional-requests         {role, supplier_type?, company_name?, note?}
  POST /api/customer/role-switch                   {role: customer|agent|supplier}
  POST /api/professional-inquiry/session           exchange the email token for a short cookie
  GET  /api/professional-inquiry                   prefilled form (cookie or email token)
  POST /api/professional-inquiry/otp/request       email a code before a new identity is recorded
  POST /api/professional-inquiry/otp/verify        confirm that code
  POST /api/professional-inquiry                   submit that form onto the same request
  GET  /api/admin/supplier-agent-pipeline          fee and reward report (admin, accountant, actuary)
  POST /api/admin/supplier-agent-pipeline/seal     ledger the current report (admin)
  GET  /api/admin/referral-rewards                 book, plan, integrity (admin, accountant, actuary)
  POST /api/admin/referral-rewards/config          admin program patch
  POST /api/admin/referral-rewards/plan            fee basis and layer amounts (admin or actuary)
  POST /api/admin/referral-rewards/hold            {hold_months} admin or actuary
  POST /api/admin/referral-rewards/recompute       backfill joins and rewards
  POST /api/admin/professional-requests/review     {id, decision, note?}

Amounts and checksums live in ``services.referral_reward_service``. Handlers
only check the session and pass the caller's own customer id.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from services import referral_reward_service as rewards
from services.referral_reward_service import RewardError

ADMIN_ROLES = {"admin"}
BOOK_ROLES = {"admin", "accountant", "actuary"}
HOLD_ROLES = {"admin", "actuary"}
OWN_ROLES = {"customer", "agent", "supplier"}

Result = Optional[Tuple[int, Dict[str, Any]]]


def _portal():
    return sys.modules.get("web_portal.server") or sys.modules.get("server")


def _role(session: Optional[Dict[str, Any]]) -> str:
    return str((session or {}).get("role") or "").lower()


def _customer_id(session: Optional[Dict[str, Any]]) -> str:
    return str((session or {}).get("customer_id") or "").strip()


def _own(session: Optional[Dict[str, Any]]) -> Result:
    if not session:
        return 401, {"error": "Authentication required"}
    if _role(session) not in OWN_ROLES or not _customer_id(session):
        return 403, {"error": "Forbidden"}
    return None


def _admin(session: Optional[Dict[str, Any]]) -> Result:
    if not session:
        return 401, {"error": "Authentication required"}
    if _role(session) not in ADMIN_ROLES:
        return 403, {"error": "Forbidden"}
    return None


def _book(session: Optional[Dict[str, Any]]) -> Result:
    if not session:
        return 401, {"error": "Authentication required"}
    if _role(session) not in BOOK_ROLES:
        return 403, {"error": "Forbidden"}
    return None


def _hold(session: Optional[Dict[str, Any]]) -> Result:
    if not session:
        return 401, {"error": "Authentication required"}
    if _role(session) not in HOLD_ROLES:
        return 403, {"error": "Forbidden"}
    return None


def _call(fn, *args, **kwargs) -> Tuple[int, Dict[str, Any]]:
    try:
        payload = fn(*args, **kwargs)
    except RewardError as exc:
        return exc.status, exc.to_dict()
    if not isinstance(payload, dict):
        payload = {"result": payload}
    return 200, payload


def _mint(session: Dict[str, Any], role: str, username: str,
          supplier_id: Optional[str] = None) -> Dict[str, Any]:
    portal = _portal()
    if portal is None:
        raise RewardError("Portal session store is unavailable", status=503, code="portal_unavailable")
    customer_id = _customer_id(session)
    timeout = int(getattr(portal, "SESSION_TIMEOUT", 3600) or 3600)
    expires = datetime.now() + timedelta(seconds=timeout)
    token, token_jti = portal._mint_auth_token(username, role, customer_id or None, expires)
    payload = {
        "username": username,
        "expires": expires.isoformat(),
        "customer_id": customer_id,
        "role": role,
        "ip_address": session.get("ip_address"),
        "jti": token_jti,
    }
    if supplier_id:
        payload["supplier_id"] = supplier_id
    lock = getattr(portal, "STATE_LOCK", None)
    sessions = getattr(portal, "SESSIONS", None)
    if not isinstance(sessions, dict):
        raise RewardError("Portal session store is unavailable", status=503, code="portal_unavailable")
    if lock is not None:
        with lock:
            sessions[token] = payload
    else:
        sessions[token] = payload
    persist = getattr(portal, "_persist_session_to_db", None)
    if callable(persist):
        persist(token, payload)
    return {
        "token": token,
        "role": role,
        "customer_id": customer_id,
        "supplier_id": supplier_id,
        "expires": payload["expires"],
    }


def _switch(session: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    role = str((body or {}).get("role") or "").strip().lower()
    if role not in ("customer", "agent", "supplier"):
        raise RewardError("Role must be customer, agent, or supplier")
    customer_id = _customer_id(session)
    portal = _portal()
    customers = getattr(portal, "CUSTOMERS", {}) if portal else {}
    rec = customers.get(customer_id) if hasattr(customers, "get") else None
    email = str((rec or {}).get("email") or "").strip()
    if role == "customer":
        username = email or str(session.get("username") or customer_id)
        return _mint(session, "customer", username)
    if role == "agent":
        grant = rewards.grant_for(customer_id, "agent")
        if not grant or not grant.get("agent_id"):
            raise RewardError("The agent role is not open for this customer", status=403, code="role_closed")
        username = str(grant.get("login_username") or email or customer_id)
        return _mint(session, "agent", username)
    grant = rewards.supplier_access(customer_id)
    supplier_id = str((grant or {}).get("supplier_id") or "")
    if not supplier_id:
        raise RewardError("The supplier role is not open for this customer", status=403, code="role_closed")
    return _mint(session, "supplier", supplier_id, supplier_id=supplier_id)


def _inquiry_cookie_jar(cookies: Any) -> Dict[str, str]:
    if isinstance(cookies, dict):
        return {str(key): str(value) for key, value in cookies.items() if value}
    text = str(cookies or "").strip()
    if not text:
        return {}
    return {rewards.INQUIRY_SESSION_COOKIE: text}


def _inquiry_credential(explicit: Any, cookies: Any = None, request_id: Any = "") -> str:
    """The token this call names wins. A cookie is only the fallback for its own inquiry.

    Supplier and agent inquiries can both be open. Each one has its own
    HttpOnly cookie. An explicit email token or session secret is that
    call's inquiry, and another inquiry's cookie must not replace it.
    """
    named = str(explicit or "").strip()
    if named:
        return named
    jar = _inquiry_cookie_jar(cookies)
    request_key = str(request_id or "").strip()
    if request_key:
        return str(jar.get(rewards.inquiry_cookie_name(request_key)) or "").strip()
    prefix = rewards.INQUIRY_SESSION_COOKIE + "_"
    found = [value for key, value in jar.items() if key.startswith(prefix) and value]
    if len(found) == 1:
        return found[0]
    return ""


def _inquiry_otp_request(token: str, client_ip: str, user_agent: str) -> Tuple[int, Dict[str, Any]]:
    """Send a code to the same address as the inquiry email. The body cannot redirect it."""
    try:
        context = rewards.inquiry_otp_context(token)
    except rewards.RewardError as exc:
        return exc.status, exc.to_dict()
    email = str(context.get("email") or "").strip()
    if not email:
        return 409, {"error": "This customer has no email on file for a verification code."}
    try:
        from web_portal.api_chat_application import _otp_delivery_ready
    except ImportError:
        from api_chat_application import _otp_delivery_ready  # type: ignore
    ready, provider = _otp_delivery_ready("email")
    if not ready:
        return 503, {
            "error": "A verification code cannot be sent right now.",
            "error_code": "OTP_DELIVERY_UNAVAILABLE",
            "retryable": True,
        }
    from services.otp_security_service import OTPPurpose, get_otp_security_service
    otp_service = get_otp_security_service()
    result = otp_service.create_otp_verification(
        user_type="applicant",
        user_id=str(context.get("request_id") or ""),
        email=email,
        purpose=OTPPurpose.EMAIL_VERIFICATION,
        ip_address=client_ip or None,
        user_agent=user_agent or None,
        delivery_channel="email",
    )
    if not result.success:
        status = 429 if result.error_code == "RATE_LIMITED" else 400
        return status, {"error": result.message or "Could not create verification code", "error_code": result.error_code}
    data = result.data or {}
    verification_id = str(data.get("verification_id") or "")
    rewards.remember_identity_otp(token, verification_id)
    try:
        from web_portal.api_extensions import _demo_otp_exposure_allowed, _send_otp_via_channel
    except ImportError:
        from api_extensions import _demo_otp_exposure_allowed, _send_otp_via_channel  # type: ignore
    delivered, _delivery_error = _send_otp_via_channel(
        "email",
        data.get("otp_code"),
        int(data.get("expires_in_seconds") or 300),
        OTPPurpose.EMAIL_VERIFICATION.value,
        email=email,
        ip_address=client_ip or None,
        verification_id=verification_id,
    )
    response: Dict[str, Any] = {
        "success": True,
        "verification_id": verification_id,
        "delivery_channel": "email",
        "masked_email": data.get("masked_email"),
        "expires_in_seconds": data.get("expires_in_seconds"),
        "notification_sent": bool(delivered),
    }
    if _demo_otp_exposure_allowed() and not otp_service.has_external_pin(verification_id):
        response["demo_otp_code"] = data.get("otp_code")
    elif not delivered:
        return 503, {
            "error": "A verification code cannot be sent right now.",
            "error_code": "OTP_DELIVERY_FAILED",
            "retryable": True,
        }
    if delivered:
        masked = str(response.get("masked_email") or "your email")
        # The code is already emailed. A transcript write that fails
        # (expired session, concurrent submit) must not hide verification_id.
        try:
            noted = rewards.note_inquiry_delivery(
                token,
                f"I sent a 6-digit code to {masked}. Type it in this chat.",
            )
        except Exception:
            noted = None
        if isinstance(noted, dict):
            response["chat"] = noted.get("chat")
    return 200, response


def _inquiry_otp_verify(token: str, body: Dict[str, Any], client_ip: str) -> Tuple[int, Dict[str, Any]]:
    otp_code = str(body.get("otp_code") or "").strip()
    verification_id = str(body.get("verification_id") or "").strip()
    if not otp_code or not verification_id:
        return 400, {"error": "verification_id and otp_code are required"}
    try:
        context = rewards.inquiry_otp_context(token)
    except rewards.RewardError as exc:
        return exc.status, exc.to_dict()
    from services.otp_security_service import OTPPurpose, get_otp_security_service
    otp_service = get_otp_security_service()
    result = otp_service.verify_otp(verification_id, otp_code, ip_address=client_ip or None)
    if not result.success:
        status = 429 if result.error_code == "MAX_ATTEMPTS" else 400
        return status, {"error": result.message or "Verification failed", "error_code": result.error_code}
    consume = otp_service.consume_verification(
        verification_id,
        expected_email=str(context.get("email") or ""),
        expected_purpose=OTPPurpose.EMAIL_VERIFICATION,
        ip_address=client_ip or None,
        expected_user_type="applicant",
    )
    if not consume.success:
        return 400, {"error": consume.message or "Verification could not be consumed", "error_code": consume.error_code}
    try:
        confirmed = rewards.confirm_identity_otp(token, verification_id)
    except rewards.RewardError as exc:
        return exc.status, exc.to_dict()
    return 200, {"success": True, **confirmed}


def _query_value(query: Dict[str, Any], key: str) -> str:
    value = (query or {}).get(key)
    if isinstance(value, list):
        value = value[0] if value else ""
    return str(value or "").strip()


def dispatch_get(path: str, session: Optional[Dict[str, Any]], query: Dict[str, Any],
                 inquiry_cookie: Any = None) -> Result:
    if path == "/api/professional-inquiry":
        token = _inquiry_credential(
            _query_value(query, "t") or _query_value(query, "token"),
            inquiry_cookie,
            _query_value(query, "r") or _query_value(query, "request_id"),
        )
        if not token:
            return 400, {"error": "token is required"}
        return _call(rewards.inquiry_prefill, token)
    if path == "/api/admin/supplier-agent-pipeline":
        denied = _book(session)
        if denied:
            return denied
        audience = _query_value(query, "audience") or "supplier"
        return _call(rewards.pipeline_report, audience)
    if path == "/api/customer/referral-rewards":
        denied = _own(session)
        if denied:
            return denied
        return _call(rewards.customer_dashboard, _customer_id(session))
    if path == "/api/customer/professional-requests":
        denied = _own(session)
        if denied:
            return denied
        return _call(rewards.professional_status, _customer_id(session))
    if path == "/api/admin/referral-rewards":
        denied = _book(session)
        if denied:
            return denied
        status, summary = _call(rewards.book_summary)
        if status != 200:
            return status, summary
        summary["recent_rewards"] = rewards.recent_rewards(20)
        summary["requests"] = rewards.list_requests()
        summary["affiliated_plan"] = summary.get("affiliated_plan") or rewards.affiliated_cac_plan()
        return 200, summary
    return None


def dispatch_post(path: str, session: Optional[Dict[str, Any]], body: Dict[str, Any],
                  inquiry_cookie: Any = None, client_ip: str = "", user_agent: str = "",
                  public_origin: str = "") -> Result:
    body = body if isinstance(body, dict) else {}
    if path == "/api/customer/referral-rewards/accept":
        denied = _own(session)
        if denied:
            return denied
        reward_id = str(body.get("reward_id") or "").strip()
        if not reward_id:
            return 400, {"error": "reward_id is required"}
        return _call(rewards.accept_reward, reward_id, _customer_id(session), body.get("allocation"))
    if path == "/api/customer/referral-rewards/accept-all":
        denied = _own(session)
        if denied:
            return denied
        return _call(rewards.accept_all, _customer_id(session), body.get("allocation"))
    if path == "/api/customer/professional-requests":
        denied = _own(session)
        if denied:
            return denied
        return _call(
            rewards.request_professional,
            _customer_id(session),
            str(body.get("role") or ""),
            str(session.get("username") or ""),
            str(body.get("supplier_type") or ""),
            str(body.get("company_name") or ""),
            str(body.get("note") or ""),
            str(public_origin or ""),
        )
    if path == "/api/customer/role-switch":
        denied = _own(session)
        if denied:
            return denied
        return _call(_switch, session, body)
    if path == "/api/admin/referral-rewards/config":
        denied = _admin(session)
        if denied:
            return denied
        return _call(rewards.update_config, body, str(session.get("username") or "admin"))
    if path == "/api/admin/referral-rewards/plan":
        denied = _hold(session)
        if denied:
            return denied
        return _call(rewards.update_plan, body, str(session.get("username") or "actuary"))
    if path == "/api/admin/referral-rewards/hold":
        denied = _hold(session)
        if denied:
            return denied
        return _call(rewards.set_hold_months, body.get("hold_months"), str(session.get("username") or "actuary"))
    if path == "/api/admin/referral-rewards/recompute":
        denied = _admin(session)
        if denied:
            return denied
        return _call(rewards.recompute)
    if path == "/api/professional-inquiry/session":
        token = str(body.get("token") or body.get("t") or "").strip()
        if not token:
            return 400, {"error": "token is required"}
        return _call(rewards.open_inquiry_session, token)
    if path == "/api/professional-inquiry/otp/request":
        token = _inquiry_credential(
            body.get("token") or body.get("t"), inquiry_cookie, body.get("request_id") or body.get("r"),
        )
        if not token:
            return 400, {"error": "token is required"}
        return _inquiry_otp_request(token, client_ip, user_agent)
    if path == "/api/professional-inquiry/otp/verify":
        token = _inquiry_credential(
            body.get("token") or body.get("t"), inquiry_cookie, body.get("request_id") or body.get("r"),
        )
        if not token:
            return 400, {"error": "token is required"}
        return _inquiry_otp_verify(token, body, client_ip)
    if path == "/api/professional-inquiry/chat":
        token = _inquiry_credential(
            body.get("token") or body.get("t"), inquiry_cookie, body.get("request_id") or body.get("r"),
        )
        if not token:
            return 400, {"error": "token is required"}
        return _call(rewards.advance_inquiry_chat, token, body.get("step"), body.get("value"))
    if path == "/api/professional-inquiry/media":
        token = _inquiry_credential(
            body.get("token") or body.get("t"), inquiry_cookie, body.get("request_id") or body.get("r"),
        )
        if not token:
            return 400, {"error": "token is required"}
        return _call(
            rewards.attach_inquiry_media,
            token,
            str(body.get("kind") or ""),
            str(body.get("name") or ""),
            str(body.get("mime_type") or ""),
            str(body.get("data_b64") or ""),
        )
    if path == "/api/professional-inquiry":
        token = _inquiry_credential(
            body.get("token") or body.get("t"), inquiry_cookie, body.get("request_id") or body.get("r"),
        )
        if not token:
            return 400, {"error": "token is required"}
        return _call(rewards.submit_inquiry, token, body)
    if path == "/api/admin/supplier-agent-pipeline/seal":
        denied = _admin(session)
        if denied:
            return denied
        return _call(rewards.seal_pipeline_statements, str(body.get("supplier_id") or ""))
    if path == "/api/admin/professional-requests/review":
        denied = _admin(session)
        if denied:
            return denied
        request_id = str(body.get("id") or body.get("request_id") or "").strip()
        if not request_id:
            return 400, {"error": "id is required"}
        return _call(
            rewards.review_professional,
            request_id,
            str(body.get("decision") or ""),
            str(session.get("username") or "admin"),
            str(body.get("note") or ""),
        )
    return None
