"""HTTP surface for the customer identity master (personal ID + nationality).

Routes (dispatched from ``web_portal/server.py``):

  GET  /api/identity/countries?q=isr          public   nationality autocomplete
  GET  /api/identity/rules?nationality=IL     public   ID format hint per nationality
  GET  /api/customer/identity                 session  own status (staff: ?customer_id=)
  POST /api/customer/identity                 customer one-time capture {national_id, nationality}
  GET  /api/admin/customers/identity          staff    status for ?customer_id=
  POST /api/admin/customers/identity          admin    audited correction {customer_id, national_id,
                                                        nationality, reason}
  GET  /api/admin/customers/identity/report   admin    rollout completion counters

Responses never contain the plaintext ID; ``services.customer_identity_service``
is the only writer and owns validation, uniqueness, encryption and anchoring.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, Optional, Tuple

from services import customer_identity_service as identity

STAFF_ROLES = {"admin", "underwriter", "claims", "accountant", "actuary", "media", "manager"}
ADMIN_ROLES = {"admin"}

Result = Optional[Tuple[int, Dict[str, Any]]]


def _portal():
    """The already-imported server module (never import it here: circular)."""
    return sys.modules.get("web_portal.server") or sys.modules.get("server")


def _stores() -> Tuple[Dict[str, Any], Tuple[Dict[str, Any], ...], Any, Any]:
    portal = _portal()
    customers = getattr(portal, "CUSTOMERS", None)
    if customers is None:
        customers = {}
    mirrors = tuple(
        m for m in (getattr(portal, "REGISTERED_CUSTOMERS", None),)
        if isinstance(m, dict) and m is not customers
    )
    return customers, mirrors, getattr(portal, "audit", None), getattr(portal, "platform_event_ledger", None)


def _role(session: Optional[Dict[str, Any]]) -> str:
    return str((session or {}).get("role") or "").lower()


def _customer_record(customer_id: str) -> Optional[Dict[str, Any]]:
    customers, mirrors, _, _ = _stores()
    rec = None
    try:
        rec = customers.get(customer_id) if hasattr(customers, "get") else None
    except Exception:
        rec = None
    if not isinstance(rec, dict):
        for mirror in mirrors:
            candidate = mirror.get(customer_id)
            if isinstance(candidate, dict):
                rec = candidate
                break
    return rec if isinstance(rec, dict) else None


def login_identity_flags(customer_id: Optional[str]) -> Dict[str, Any]:
    """Flags merged into /api/login and /api/session/validate for customers."""
    rec = _customer_record(str(customer_id)) if customer_id else None
    status = identity.identity_status(rec)
    return {"identity_required": bool(status["required"]), "identity": status}


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------
def dispatch_get(path: str, session: Optional[Dict[str, Any]], query: Dict[str, Any]) -> Result:
    def _q(name: str) -> str:
        value = query.get(name) if isinstance(query, dict) else None
        if isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        return str(value or "").strip()

    if path == "/api/identity/countries":
        try:
            limit = int(_q("limit") or 12)
        except ValueError:
            limit = 12
        items = identity.countries_autocomplete(_q("q"), limit=limit)
        return 200, {"items": items, "total": len(items)}

    if path == "/api/identity/rules":
        code = identity.resolve_nationality(_q("nationality"))
        if not code:
            return 400, {"error": "nationality is required (country name or ISO code)",
                         "code": "nationality_invalid"}
        rule = identity.id_rule_for(code)
        rule["nationality_name"] = identity.nationality_name(code)
        return 200, rule

    if path == "/api/customer/identity":
        if not session:
            return 401, {"error": "Authentication required"}
        role = _role(session)
        requested = _q("customer_id")
        if role == "customer":
            customer_id = str(session.get("customer_id") or "")
            if requested and requested != customer_id:
                return 403, {"error": "Forbidden"}
        elif role in STAFF_ROLES:
            customer_id = requested
            if not customer_id:
                return 400, {"error": "customer_id is required"}
        else:
            return 403, {"error": "Forbidden"}
        if not customer_id:
            return 400, {"error": "customer_id unavailable"}
        rec = _customer_record(customer_id)
        if rec is None:
            return 404, {"error": "Customer not found"}
        status = identity.identity_status(rec)
        status["customer_id"] = customer_id
        status["strict_mode"] = identity.strict_mode()
        return 200, status

    if path == "/api/admin/customers/identity":
        if not session:
            return 401, {"error": "Authentication required"}
        if _role(session) not in STAFF_ROLES:
            return 403, {"error": "Forbidden"}
        customer_id = _q("customer_id")
        if not customer_id:
            return 400, {"error": "customer_id is required"}
        rec = _customer_record(customer_id)
        if rec is None:
            return 404, {"error": "Customer not found"}
        status = identity.identity_status(rec)
        status["customer_id"] = customer_id
        status["history"] = identity._history(rec)
        return 200, status

    if path == "/api/admin/customers/identity/report":
        if not session:
            return 401, {"error": "Authentication required"}
        if _role(session) not in ADMIN_ROLES:
            return 403, {"error": "Forbidden"}
        customers, _, _, _ = _stores()
        return 200, identity.completion_report(customers)

    return None


# ---------------------------------------------------------------------------
# POST
# ---------------------------------------------------------------------------
def dispatch_post(path: str, session: Optional[Dict[str, Any]], body: Dict[str, Any]) -> Result:
    body = body if isinstance(body, dict) else {}

    if path == "/api/customer/identity":
        if not session:
            return 401, {"error": "Authentication required"}
        if _role(session) != "customer":
            return 403, {"error": "Customers only; staff use /api/admin/customers/identity"}
        customer_id = str(session.get("customer_id") or "")
        if not customer_id:
            return 400, {"error": "customer_id unavailable"}
        customers, mirrors, audit, ledger = _stores()
        try:
            status = identity.set_identity(
                customers, customer_id, body.get("national_id"), body.get("nationality"),
                source="login_prompt", actor=str(session.get("username") or customer_id),
                mirrors=mirrors, audit=audit, ledger=ledger,
            )
        except identity.IdentityError as exc:
            return exc.status, exc.to_dict()
        status["customer_id"] = customer_id
        return 200, status

    if path == "/api/admin/customers/identity":
        if not session:
            return 401, {"error": "Authentication required"}
        if _role(session) not in ADMIN_ROLES:
            return 403, {"error": "Forbidden"}
        customer_id = str(body.get("customer_id") or "").strip()
        if not customer_id:
            return 400, {"error": "customer_id is required"}
        customers, mirrors, audit, ledger = _stores()
        try:
            status = identity.set_identity(
                customers, customer_id, body.get("national_id"), body.get("nationality"),
                source="admin", actor=str(session.get("username") or "admin"),
                allow_override=True, reason=str(body.get("reason") or ""),
                mirrors=mirrors, audit=audit, ledger=ledger,
            )
        except identity.IdentityError as exc:
            return exc.status, exc.to_dict()
        status["customer_id"] = customer_id
        return 200, status

    return None
