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
  POST /api/agent/invitations

Admin (role=admin) — Agents Management:
  GET  /api/admin/agents
  GET  /api/admin/agent-invitations
  GET  /api/admin/agents/commissions
  POST /api/admin/agents
  POST /api/admin/agents/update
  POST /api/admin/agents/recompute-commissions
  POST /api/admin/agent-invitations/approve
  POST /api/admin/agent-invitations/reject
  POST /api/admin/agent-invitations/redeem

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
            svc.recompute_commissions(data_sources.get("policies", {}))
            return 200, {"agent": agent, "summary": svc.income_summary(aid)}
        if path == "/api/agent/income/summary":
            # Revenue hook (v1): the policy/premium book drives accrual, applied
            # idempotently here so the dashboard reflects current realized premium.
            svc.recompute_commissions(data_sources.get("policies", {}))
            return 200, svc.income_summary(aid)
        if path == "/api/agent/network/customers":
            svc.recompute_commissions(data_sources.get("policies", {}))
            page = int(_first(qs, "page", 1) or 1)
            page_size = int(_first(qs, "page_size", 50) or 50)
            return 200, svc.network_customers(
                aid, data_sources.get("customers", {}), data_sources.get("policies", {}),
                page=page, page_size=page_size)
        if path == "/api/agent/invitations":
            return 200, {"items": svc.list_invitations(agent_id=aid)}
        if path == "/api/agent/ledger":
            return 200, {"items": svc.get_ledger(agent_id=aid)}
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
            svc.recompute_commissions(data_sources.get("policies", {}))
            agent_id = _first(qs, "agent_id")
            return 200, {"items": svc.list_commissions(agent_id=agent_id)}
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
            created = svc.recompute_commissions(data_sources.get("policies", {}))
            return 200, {"created": created, "ledger_intact": svc.verify_ledger_integrity()}

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
