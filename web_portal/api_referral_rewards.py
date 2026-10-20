"""HTTP surface for the referral acquisition-reward chain.

Routes (dispatched from ``web_portal/server.py``):

  GET  /api/customer/referral-rewards              own book (customer, agent, supplier)
  POST /api/customer/referral-rewards/accept       {reward_id, allocation?}
  POST /api/customer/referral-rewards/accept-all   {allocation?}
  GET  /api/customer/professional-requests         own agent/supplier requests
  POST /api/customer/professional-requests         {role, supplier_type?, company_name?, note?}
  POST /api/customer/role-switch                   {role: customer|agent|supplier}
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
    grant = rewards.grant_for(customer_id, "supplier")
    supplier_id = str((grant or {}).get("supplier_id") or "")
    if not supplier_id:
        raise RewardError("The supplier role is not open for this customer", status=403, code="role_closed")
    return _mint(session, "supplier", supplier_id, supplier_id=supplier_id)


def dispatch_get(path: str, session: Optional[Dict[str, Any]], query: Dict[str, Any]) -> Result:
    del query
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


def dispatch_post(path: str, session: Optional[Dict[str, Any]], body: Dict[str, Any]) -> Result:
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
