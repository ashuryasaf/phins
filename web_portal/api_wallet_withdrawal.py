"""HTTP surface for health-wallet withdrawals and the retention desk.

Routes (dispatched from ``web_portal/server.py``):

  Customer (own wallet only)
  GET  /api/customer/wallet-withdrawals                     own requests + the open one
  POST /api/customer/wallet-withdrawals                     start, or return the open request
  GET  /api/customer/wallet-withdrawals/{id}                chat state
  POST /api/customer/wallet-withdrawals/{id}/answer         {step, value}
  POST /api/customer/wallet-withdrawals/{id}/upload         {kind, data}
  GET  /api/customer/wallet-withdrawals/{id}/photo-source   preview + proposed portrait box
  POST /api/customer/wallet-withdrawals/{id}/photo          {box}
  POST /api/customer/wallet-withdrawals/{id}/sign           {signer_name, image_data}
  POST /api/customer/wallet-withdrawals/{id}/file           hold + anchor + wallet NFT
  POST /api/customer/wallet-withdrawals/{id}/cancel         {reason?}
  POST /api/customer/wallet-withdrawals/{id}/offer          {offer_id, decision: accept|decline}
  GET  /api/customer/wallet-withdrawals/{id}/document       {html}

  Staff
  GET  /api/admin/wallet-withdrawals[?status=held|all|...]  retention board
  GET  /api/admin/wallet-withdrawals/{id}
  POST /api/admin/wallet-withdrawals/{id}/retention         {method, note?, message?, keep_amount?, days?}
  POST /api/admin/wallet-withdrawals/{id}/release           {reference?}   admin, accountant
  POST /api/admin/wallet-withdrawals/{id}/decline           {reason}       admin, accountant
  GET  /api/admin/wallet-withdrawals/{id}/document          {html}
  GET  /api/admin/wallet-withdrawals/{id}/bank              admin, accountant (audited)

Amounts, holds, and seals live in ``services.wallet_withdrawal_service``.
Handlers check the session and pass the caller's own customer id.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Tuple

from services import wallet_withdrawal_service as withdrawals
from services.wallet_withdrawal_service import (
    PAYOUT_ROLES,
    RETENTION_ROLES,
    WithdrawalError,
)

CUSTOMER_PREFIX = "/api/customer/wallet-withdrawals"
ADMIN_PREFIX = "/api/admin/wallet-withdrawals"
API_PREFIXES = (CUSTOMER_PREFIX, ADMIN_PREFIX)

Result = Optional[Tuple[int, Dict[str, Any]]]


def _portal():
    return sys.modules.get("web_portal.server") or sys.modules.get("server")


def _role(session: Optional[Dict[str, Any]]) -> str:
    return str((session or {}).get("role") or "").lower()


def _customer_id(session: Optional[Dict[str, Any]]) -> str:
    return str((session or {}).get("customer_id") or "").strip()


def _actor(session: Optional[Dict[str, Any]]) -> str:
    return str((session or {}).get("username") or (session or {}).get("user_id") or "staff")


def _own(session: Optional[Dict[str, Any]]) -> Result:
    if not session:
        return 401, {"error": "Authentication required"}
    if _role(session) != "customer" or not _customer_id(session):
        return 403, {"error": "Only the customer can use their own wallet"}
    return None


def _staff(session: Optional[Dict[str, Any]], roles) -> Result:
    if not session:
        return 401, {"error": "Authentication required"}
    if _role(session) not in roles:
        return 403, {"error": "Unauthorized"}
    return None


def _fail(exc: WithdrawalError) -> Tuple[int, Dict[str, Any]]:
    return exc.status, {"error": str(exc), "code": exc.code}


def _parts(path: str, prefix: str) -> List[str]:
    rest = path[len(prefix):].strip("/")
    return [part for part in rest.split("/") if part] if rest else []


def _audit(action: str, session: Optional[Dict[str, Any]], withdrawal_id: str, details: Dict[str, Any]) -> None:
    portal = _portal()
    audit = getattr(portal, "audit", None) if portal else None
    try:
        if audit is not None and hasattr(audit, "log"):
            audit.log(actor=_actor(session), action=action, entity="wallet_withdrawal",
                      entity_id=withdrawal_id, details=details)
    except Exception:
        pass


def dispatch_get(path: str, session: Optional[Dict[str, Any]], qs: Dict[str, List[str]]) -> Result:
    path = path.rstrip("/")
    try:
        if path == CUSTOMER_PREFIX or path.startswith(CUSTOMER_PREFIX + "/"):
            denied = _own(session)
            if denied:
                return denied
            customer_id = _customer_id(session)
            parts = _parts(path, CUSTOMER_PREFIX)
            if not parts:
                items = withdrawals.list_requests(customer_id)
                open_item = next((row for row in items if row["status"] in withdrawals.OPEN_STATUSES), None)
                return 200, {
                    "items": items,
                    "open": open_item,
                    "retention_days": withdrawals.retention_days(),
                    "min_amount": withdrawals.MIN_AMOUNT,
                }
            if len(parts) == 1:
                return 200, {"withdrawal": withdrawals.get_request(customer_id, parts[0])}
            if len(parts) == 2 and parts[1] == "photo-source":
                return 200, withdrawals.photo_source(customer_id, parts[0])
            if len(parts) == 2 and parts[1] == "document":
                return 200, {"html": withdrawals.render_document_for_customer(customer_id, parts[0])}
            return 404, {"error": "Not found"}
        if path == ADMIN_PREFIX or path.startswith(ADMIN_PREFIX + "/"):
            denied = _staff(session, RETENTION_ROLES)
            if denied:
                return denied
            parts = _parts(path, ADMIN_PREFIX)
            if not parts:
                status = str((qs.get("status") or ["held"])[0] or "held").strip().lower()
                if status not in ("held", "all", "reversed", "declined", "paid_out"):
                    return 400, {"error": "Unknown status"}
                board = withdrawals.retention_board(status)
                board["can_pay_out"] = _role(session) in PAYOUT_ROLES
                return 200, board
            if len(parts) == 1:
                return 200, {"withdrawal": withdrawals.get_for_staff(parts[0])}
            if len(parts) == 2 and parts[1] == "document":
                return 200, {"html": withdrawals.render_document(parts[0])}
            if len(parts) == 2 and parts[1] == "bank":
                denied = _staff(session, PAYOUT_ROLES)
                if denied:
                    return denied
                details = withdrawals.bank_details(parts[0])
                _audit("wallet_withdrawal.bank_read", session, parts[0], {"account_last4": details["bank"]["account_last4"]})
                return 200, details
            return 404, {"error": "Not found"}
    except WithdrawalError as exc:
        return _fail(exc)
    return None


def dispatch_post(path: str, session: Optional[Dict[str, Any]], body: Dict[str, Any],
                  client_ip: str = "") -> Result:
    path = path.rstrip("/")
    try:
        if path == CUSTOMER_PREFIX or path.startswith(CUSTOMER_PREFIX + "/"):
            denied = _own(session)
            if denied:
                return denied
            customer_id = _customer_id(session)
            parts = _parts(path, CUSTOMER_PREFIX)
            if not parts:
                view = withdrawals.open_request(customer_id, str((session or {}).get("username") or ""))
                return 200, {"withdrawal": view}
            if len(parts) != 2:
                return 404, {"error": "Not found"}
            withdrawal_id, action = parts
            if action == "answer":
                view = withdrawals.answer(customer_id, withdrawal_id, body.get("step"), body.get("value"))
            elif action == "upload":
                view = withdrawals.attach_document(
                    customer_id, withdrawal_id, body.get("kind"), body.get("mime_type"), body.get("data"),
                )
            elif action == "photo":
                view = withdrawals.confirm_photo(customer_id, withdrawal_id, body.get("box"))
            elif action == "sign":
                view = withdrawals.sign(customer_id, withdrawal_id, body.get("signer_name"), body.get("image_data"))
            elif action == "file":
                if body.get("confirm") is not True:
                    return 400, {"error": "Confirm the withdrawal to file it", "code": "confirm_required"}
                view = withdrawals.file_request(customer_id, withdrawal_id, client_ip=client_ip, session=session)
                _audit("wallet_withdrawal.filed", session, withdrawal_id,
                       {"amount": view.get("amount"), "nft_token_id": view.get("nft_token_id")})
            elif action == "cancel":
                view = withdrawals.cancel(customer_id, withdrawal_id, str(body.get("reason") or ""))
                _audit("wallet_withdrawal.cancelled", session, withdrawal_id, {"status": view.get("status")})
            elif action == "offer":
                decision = str(body.get("decision") or "").strip().lower()
                if decision == "accept":
                    view = withdrawals.accept_offer(customer_id, withdrawal_id, str(body.get("offer_id") or ""))
                    _audit("wallet_withdrawal.offer_accepted", session, withdrawal_id, {"status": view.get("status")})
                elif decision == "decline":
                    view = withdrawals.decline_offer(customer_id, withdrawal_id, str(body.get("offer_id") or ""))
                else:
                    return 400, {"error": "decision must be accept or decline"}
            else:
                return 404, {"error": "Not found"}
            return 200, {"withdrawal": view}
        if path.startswith(ADMIN_PREFIX + "/"):
            parts = _parts(path, ADMIN_PREFIX)
            if len(parts) != 2:
                return 404, {"error": "Not found"}
            withdrawal_id, action = parts
            if action == "retention":
                denied = _staff(session, RETENTION_ROLES)
                if denied:
                    return denied
                view = withdrawals.record_retention(
                    withdrawal_id, actor=_actor(session), role=_role(session),
                    method=str(body.get("method") or ""), note=str(body.get("note") or ""),
                    keep_amount=body.get("keep_amount"), days=body.get("days"),
                    message=str(body.get("message") or ""), channels=str(body.get("channels") or "both"),
                )
                _audit("wallet_withdrawal.retention", session, withdrawal_id, {"method": body.get("method")})
            elif action == "release":
                denied = _staff(session, PAYOUT_ROLES)
                if denied:
                    return denied
                try:
                    from services.erp.money_gate import (
                        MoneyGateError, authorize_money_move, http_refuse,
                    )
                    # Pass the live portal journal explicitly so break-glass
                    # does not depend on a second module-name lookup.
                    platform_ledger = None
                    try:
                        import sys
                        portal = sys.modules.get("web_portal.server") or sys.modules.get("server")
                        if portal is not None:
                            platform_ledger = getattr(portal, "platform_event_ledger", None)
                    except Exception:
                        platform_ledger = None
                    authorize_money_move(
                        "wallet_withdrawal.release",
                        break_glass=bool(body.get("break_glass")),
                        break_glass_reason=str(body.get("break_glass_reason") or ""),
                        actor=_actor(session),
                        role=_role(session),
                        platform_ledger=platform_ledger,
                    )
                except MoneyGateError as gate_exc:
                    return 409, http_refuse(gate_exc)
                view = withdrawals.release(
                    withdrawal_id, actor=_actor(session), role=_role(session),
                    reference=str(body.get("reference") or ""),
                )
                _audit("wallet_withdrawal.released", session, withdrawal_id, {"amount": view.get("amount")})
            elif action == "decline":
                denied = _staff(session, PAYOUT_ROLES)
                if denied:
                    return denied
                view = withdrawals.decline(
                    withdrawal_id, actor=_actor(session), role=_role(session),
                    reason=str(body.get("reason") or ""),
                )
                _audit("wallet_withdrawal.declined", session, withdrawal_id, {"amount": view.get("requested_amount")})
            else:
                return 404, {"error": "Not found"}
            return 200, {"withdrawal": view}
    except WithdrawalError as exc:
        return _fail(exc)
    return None
