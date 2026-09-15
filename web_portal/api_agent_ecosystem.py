"""
HTTP API for the agent/broker ecosystem ("AgentOS").

Stateless dispatcher used by ``web_portal/server.py``. Business logic lives in
``services/agent_ecosystem_service.py``; this module only validates requests,
enforces role scope, and shapes JSON responses.

Conventions (AGENTS.md):
  * JSON errors as ``{"error": "..."}``
  * paginated responses as ``{"items": [], "page": 1, "page_size": 50, "total": 0}``

Routes
------
Agent (role=agent, scoped to own subtree):
  GET  /api/agent/me
  GET  /api/agent/income/summary
  GET  /api/agent/network/customers
  GET  /api/agent/invitations
  GET  /api/agent/ledger
  GET  /api/agent/funnel            (§C broker funnel, subtree only)
  GET  /api/agent/payouts           (§C own payout runs)
  POST /api/agent/invitations

Admin (role=admin) — Agents Management:
  GET  /api/admin/agents
  GET  /api/admin/agent-invitations
  GET  /api/admin/agents/commissions
  GET  /api/admin/agents/integrity
  GET  /api/admin/agents/funnel?agent_id=
  GET  /api/admin/agents/payouts?agent_id=&status=
  POST /api/admin/agents
  POST /api/admin/agents/update
  POST /api/admin/agents/recompute-commissions
  POST /api/admin/agents/repair-referrals
  POST /api/admin/agents/payouts/run      {agent_id?, idempotency_key?, settle?, external_payout_reference?}
  POST /api/admin/agents/payouts/settle  {payout_id, external_payout_reference?}
  POST /api/admin/agent-invitations/approve
  POST /api/admin/agent-invitations/reject
  POST /api/admin/agent-invitations/redeem

``data_sources`` (from server.py): customers, policies, suppliers, bills
(paid bills drive per-renewal accrual), health_wallets / investment_accounts /
transaction_ledger (subtree BI for the funnel) and platform_ledger (payout
anchor). Every key is optional; the module degrades to policy-only accrual.

Public:
  GET  /api/agent-invitations/validate?code=...
"""

from typing import Any, Dict, Optional, Tuple

try:
    from services import agent_ecosystem_service as svc
except Exception:  # pragma: no cover - fallback when run as a script
    import services.agent_ecosystem_service as svc  # type: ignore


def _first(qs: Dict[str, Any], key: str, default: Any = None) -> Any:
    v = qs.get(key) if qs else None
    if isinstance(v, list):
        return v[0] if v else default
    return v if v is not None else default


def _deny(msg: str = "Unauthorized") -> Tuple[int, Dict[str, Any]]:
    return 403, {"error": msg}


def _recompute(data_sources: Dict[str, Any]) -> int:
    """Idempotent accrual from the policy book plus paid bills (renewal terms)."""
    return svc.recompute_commissions(data_sources.get("policies", {}) or {},
                                     data_sources.get("bills") or {})


def _funnel(agent_id: str, data_sources: Dict[str, Any]) -> Dict[str, Any]:
    return svc.agent_funnel(
        agent_id,
        data_sources.get("customers", {}) or {},
        data_sources.get("policies", {}) or {},
        bills=data_sources.get("bills") or {},
        health_wallets=data_sources.get("health_wallets") or {},
        investment_accounts=data_sources.get("investment_accounts") or {},
        transaction_ledger=data_sources.get("transaction_ledger") or {},
    )


def _resolve_agent(ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Resolve the agent profile for the session; auto-provision the demo agent."""
    username = ctx.get("username")
    agent = svc.get_agent_by_username(username)
    if not agent and username == "agent":
        agent = svc.ensure_demo_agent()
    return agent


# ---------------------------------------------------------------------------
# GET
# ---------------------------------------------------------------------------
def handle_get(path: str, qs: Dict[str, Any], ctx: Dict[str, Any],
               data_sources: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    role = (ctx.get("role") or "").lower()

    # ----- public -----
    if path == "/api/agent-invitations/validate":
        code = _first(qs, "code")
        if not code:
            return 400, {"error": "code is required"}
        return 200, svc.validate_invitation(code)

    # ----- agent-scoped -----
    if path.startswith("/api/agent/"):
        if role != "agent":
            return _deny("Agent access required")
        agent = _resolve_agent(ctx)
        if not agent:
            return 404, {"error": "No agent profile for this account"}
        aid = agent["id"]
        if path == "/api/agent/me":
            _recompute(data_sources)
            return 200, {"agent": agent, "summary": svc.income_summary(aid)}
        if path == "/api/agent/income/summary":
            # Revenue hook (v1): the policy/premium book drives accrual, applied
            # idempotently here so the dashboard reflects current realized premium.
            _recompute(data_sources)
            return 200, svc.income_summary(aid)
        if path == "/api/agent/network/customers":
            _recompute(data_sources)
            page = int(_first(qs, "page", 1) or 1)
            page_size = int(_first(qs, "page_size", 50) or 50)
            return 200, svc.network_customers(
                aid, data_sources.get("customers", {}), data_sources.get("policies", {}),
                page=page, page_size=page_size)
        if path == "/api/agent/invitations":
            return 200, {"items": svc.list_invitations(agent_id=aid)}
        if path == "/api/agent/ledger":
            return 200, {"items": svc.get_ledger(agent_id=aid)}
        if path == "/api/agent/funnel":
            _recompute(data_sources)
            return 200, _funnel(aid, data_sources)
        if path == "/api/agent/payouts":
            status = _first(qs, "status")
            return 200, {"items": svc.list_payouts(agent_id=aid, status=status)}
        return 404, {"error": "Unknown agent endpoint"}

    # ----- admin-scoped -----
    if path.startswith("/api/admin/agent"):
        if role != "admin":
            return _deny("Admin access required")
        if path == "/api/admin/agents":
            return 200, {"items": svc.list_agents()}
        if path == "/api/admin/agent-invitations":
            status = _first(qs, "status")
            return 200, {"items": svc.list_invitations(status=status)}
        if path == "/api/admin/agents/commissions":
            _recompute(data_sources)
            agent_id = _first(qs, "agent_id")
            return 200, {"items": svc.list_commissions(agent_id=agent_id)}
        if path == "/api/admin/agents/overview":
            _recompute(data_sources)
            return 200, svc.community_overview()
        if path == "/api/admin/agents/affiliations":
            agent_id = _first(qs, "agent_id")
            if not agent_id:
                return 400, {"error": "agent_id is required"}
            return 200, {"items": svc.list_affiliations(agent_id)}
        if path == "/api/admin/agents/network":
            _recompute(data_sources)
            agent_id = _first(qs, "agent_id")
            if not agent_id:
                return 400, {"error": "agent_id is required"}
            page = int(_first(qs, "page", 1) or 1)
            page_size = int(_first(qs, "page_size", 50) or 50)
            return 200, svc.network_customers(
                agent_id, data_sources.get("customers", {}), data_sources.get("policies", {}),
                page=page, page_size=page_size)
        if path == "/api/admin/agents/ledger":
            agent_id = _first(qs, "agent_id")
            return 200, {"items": svc.get_ledger(agent_id=agent_id),
                         "ledger_intact": svc.verify_ledger_integrity()}
        if path == "/api/admin/agents/integrity":
            _recompute(data_sources)
            return 200, svc.connection_integrity(
                customers=data_sources.get("customers", {}),
                policies=data_sources.get("policies", {}),
                suppliers=data_sources.get("suppliers", {}),
            )
        if path == "/api/admin/agents/funnel":
            agent_id = _first(qs, "agent_id")
            if not agent_id:
                return 400, {"error": "agent_id is required"}
            if not svc.get_agent(agent_id):
                return 404, {"error": "Agent not found"}
            _recompute(data_sources)
            return 200, _funnel(agent_id, data_sources)
        if path == "/api/admin/agents/payouts":
            agent_id = _first(qs, "agent_id")
            status = _first(qs, "status")
            if status and status not in svc.PAYOUT_STATUSES:
                return 400, {"error": f"status must be one of {', '.join(svc.PAYOUT_STATUSES)}"}
            return 200, {"items": svc.list_payouts(agent_id=agent_id, status=status)}
        return 404, {"error": "Unknown admin agent endpoint"}

    return 404, {"error": "Unknown endpoint"}


# ---------------------------------------------------------------------------
# POST
# ---------------------------------------------------------------------------
def handle_post(path: str, qs: Dict[str, Any], ctx: Dict[str, Any],
                body: Dict[str, Any], data_sources: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    role = (ctx.get("role") or "").lower()
    body = body if isinstance(body, dict) else {}

    # ----- agent-scoped -----
    if path == "/api/agent/invitations":
        if role != "agent":
            return _deny("Agent access required")
        agent = _resolve_agent(ctx)
        if not agent:
            return 404, {"error": "No agent profile for this account"}
        ok, result = svc.create_invitation(
            agent_id=agent["id"],
            invitee_type=body.get("invitee_type", ""),
            invitee_email=body.get("invitee_email", ""),
            invitee_phone=body.get("invitee_phone", ""),
            proposed_rate=body.get("proposed_rate"),
            commission_basis=body.get("commission_basis", "premium"),
            notes=body.get("notes", ""),
        )
        return (201, {"invitation": result}) if ok else (400, {"error": result})

    # ----- admin-scoped -----
    if path.startswith("/api/admin/agent"):
        if role != "admin":
            return _deny("Admin access required")
        admin = ctx.get("username") or "admin"

        if path == "/api/admin/agents":
            username = body.get("username")
            if not username:
                return 400, {"error": "username is required"}
            agent = svc.create_agent(
                username=username,
                display_name=body.get("display_name", ""),
                email=body.get("email", ""),
                default_rate=body.get("default_rate", body.get("default_commission_rate", 0.0)),
                created_by=admin,
                parent_agent_id=body.get("parent_agent_id"),
            )
            return 201, {"agent": agent}

        if path == "/api/admin/agents/update":
            agent_id = body.get("agent_id")
            if not agent_id:
                return 400, {"error": "agent_id is required"}
            agent = svc.update_agent(agent_id, status=body.get("status"),
                                     default_rate=body.get("default_rate"))
            return (200, {"agent": agent}) if agent else (404, {"error": "Agent not found"})

        if path == "/api/admin/agents/recompute-commissions":
            created = _recompute(data_sources)
            return 200, {"created": created, "ledger_intact": svc.verify_ledger_integrity()}

        if path == "/api/admin/agents/payouts/run":
            agent_id = body.get("agent_id") or None
            if agent_id and not svc.get_agent(agent_id):
                return 404, {"error": "Agent not found"}
            idem = body.get("idempotency_key")
            if idem is not None and not isinstance(idem, str):
                return 400, {"error": "idempotency_key must be a string"}
            if idem and len(idem) > 120:
                return 400, {"error": "idempotency_key too long (max 120)"}
            # Sweep the latest accruals first so the run reflects the current book.
            _recompute(data_sources)
            result = svc.run_payouts(agent_id=agent_id, created_by=admin, idempotency_key=idem)
            if body.get("settle") and not result.get("reused"):
                reference = body.get("external_payout_reference")
                settled = []
                for pay in result["payouts"]:
                    ok, out = svc.settle_payout(
                        pay["id"], settled_by=admin, external_payout_reference=reference,
                        platform_ledger=data_sources.get("platform_ledger"))
                    if not ok:
                        result["error_detail"] = out
                        break
                    settled.append(out)
                result["payouts"] = settled + result["payouts"][len(settled):]
                result["settled"] = len(settled)
            return 200, result

        if path == "/api/admin/agents/payouts/settle":
            payout_id = body.get("payout_id")
            if not payout_id:
                return 400, {"error": "payout_id is required"}
            reference = body.get("external_payout_reference")
            if reference is not None and not isinstance(reference, str):
                return 400, {"error": "external_payout_reference must be a string"}
            ok, result = svc.settle_payout(
                payout_id, settled_by=admin, external_payout_reference=reference or None,
                platform_ledger=data_sources.get("platform_ledger"))
            if ok:
                return 200, {"payout": result, "ledger_intact": svc.verify_ledger_integrity()}
            return (404 if result == "Payout not found" else 409), {"error": result}

        if path == "/api/admin/agents/repair-referrals":
            result = svc.repair_referring_links(
                customers=data_sources.get("customers", {}),
                suppliers=data_sources.get("suppliers", {}),
            )
            audit = svc.connection_integrity(
                customers=data_sources.get("customers", {}),
                policies=data_sources.get("policies", {}),
                suppliers=data_sources.get("suppliers", {}),
            )
            result["integrity"] = {
                "ok": audit.get("ok"),
                "ledger_intact": audit.get("ledger_intact"),
                "issue_counts": audit.get("issue_counts"),
            }
            return 200, result

        if path == "/api/admin/agent-invitations/approve":
            code = body.get("code")
            if not code:
                return 400, {"error": "code is required"}
            ok, result = svc.approve_invitation(code, body.get("commission_rate"), admin)
            return (200, {"invitation": result}) if ok else (400, {"error": result})

        if path == "/api/admin/agent-invitations/reject":
            code = body.get("code")
            if not code:
                return 400, {"error": "code is required"}
            ok, result = svc.reject_invitation(code, admin, body.get("reason", ""))
            return (200, {"invitation": result}) if ok else (400, {"error": result})

        if path == "/api/admin/agent-invitations/redeem":
            code = body.get("code")
            principal_type = (body.get("principal_type") or "").lower()
            principal_id = body.get("principal_id")
            if not (code and principal_type and principal_id):
                return 400, {"error": "code, principal_type and principal_id are required"}
            ok, result = svc.redeem_invitation(code, principal_type, principal_id)
            if ok:
                # Surface "referred by" linkage on the in-memory principal record
                # and mirror it to the durable customers/suppliers tables.
                src_key = "customers" if principal_type == "customer" else (
                    "suppliers" if principal_type == "supplier" else None)
                if src_key:
                    rec = (data_sources.get(src_key) or {}).get(principal_id)
                    if isinstance(rec, dict):
                        rec["referring_agent_id"] = result["agent_id"]
                svc.persist_referring_agent(principal_type, principal_id, result["agent_id"])
                return 200, {"affiliation": result}
            return 400, {"error": result}

        return 404, {"error": "Unknown admin agent endpoint"}

    return 404, {"error": "Unknown endpoint"}
