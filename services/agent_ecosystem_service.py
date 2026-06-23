"""
Agent / Broker ecosystem service ("AgentOS").

Implements the agent layer the investor deck promises:
  * agent profiles (role='agent')
  * invitations for customers / suppliers / sub-agents, with a commission rate
    that an admin LOCKS in advance
  * affiliations with hierarchy integrity (at most one active affiliation per
    principal — no double commission)
  * idempotent, hash-chained commission accrual on revenue events
  * agent income summaries and a PII-minimized "customer outline"

Storage model:
  The authoritative working store is in-memory (module-level dicts) plus an
  append-only, hash-chained commission ledger. This guarantees deterministic
  behaviour in both runtime modes the platform supports (in-memory portal and
  DB-backed). When ``USE_DATABASE`` is enabled the service additionally performs
  best-effort write-through to the durable tables (see
  ``database/repositories/agent_repository.py``) and hydrates from them once on
  first use, so agent data survives restarts.

Design: docs/agent_ecosystem_design.md, docs/uml/agent_ecosystem.puml.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Module state (authoritative in-memory working store)
# ---------------------------------------------------------------------------
_LOCK = threading.RLock()

AGENTS: Dict[str, Dict[str, Any]] = {}            # agent_id -> agent dict
AGENT_BY_USER: Dict[str, str] = {}                # username -> agent_id
INVITATIONS: Dict[str, Dict[str, Any]] = {}       # code -> invitation dict
AFFILIATIONS: Dict[str, Dict[str, Any]] = {}      # affiliation_id -> dict
COMMISSIONS: Dict[str, Dict[str, Any]] = {}       # commission_id -> dict
COMMISSION_LEDGER: List[Dict[str, Any]] = []      # append-only, hash-chained
_ACTIVE_AFFIL: Dict[Tuple[str, str], str] = {}    # (principal_type, principal_id) -> affiliation_id
_ACCRUED_KEYS: set = set()                         # (source_event_id, affiliation_id)

_GENESIS_HASH = "0" * 64
# Refresh-on-read coalescing. In DB mode the durable tables are the source of
# truth; the in-memory dicts are a short-lived per-instance cache that is
# re-pulled from the database. This keeps multiple app instances consistent
# (an agent/invitation/affiliation/suspension created on one instance becomes
# visible on the others) instead of each instance reading a stale snapshot it
# loaded once at startup. Writes force a fresh pull before deciding.
_last_hydrate = 0.0
try:
    _HYDRATE_TTL = float(os.environ.get("PHINS_AGENT_HYDRATE_TTL", "1.5"))
except (TypeError, ValueError):
    _HYDRATE_TTL = 1.5

VALID_INVITEE_TYPES = ("customer", "supplier", "agent")
VALID_BASES = ("premium", "gmv", "one_time")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _db_enabled() -> bool:
    """Best-effort durability is on only when the platform runs DB-backed.

    Defers to the portal's *effective* runtime mode when the server module is
    already loaded: ``web_portal/server.py`` can disable database mode at
    runtime after a connection failure while leaving the ``USE_DATABASE`` env
    var unchanged. Reading the env var alone would desync agent persistence
    from the in-memory store the rest of the request path actually serves
    (commissions/affiliations diverging from accrual data). Falls back to the
    env var only when the portal module is not loaded (e.g. isolated unit use).
    """
    portal = sys.modules.get("web_portal.server")
    if portal is not None:
        return bool(getattr(portal, "USE_DATABASE", False)
                    and getattr(portal, "database_enabled", False))
    return os.environ.get("USE_DATABASE", "true").lower() not in ("false", "0", "no")


def normalize_rate(value: Any, default: float = 0.0) -> float:
    """Normalize a commission rate to a 0..1 fraction.

    Accepts fractions (0.25) or whole-number percentages (25 -> 0.25, 1 -> 0.01).
    The admin/agent portals send commission inputs as percents (e.g. ``1`` for
    1%), so any value of 1 or more is treated as a percent; sub-1 values are
    treated as already-fractional rates. Clamped to [0, 1].
    """
    try:
        r = float(value)
    except (TypeError, ValueError):
        return default
    if r >= 1.0:
        r = r / 100.0
    if r < 0:
        r = 0.0
    if r > 1.0:
        r = 1.0
    return round(r, 6)


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(5).upper()}"


def _gen_code() -> str:
    return f"AGI-{secrets.token_urlsafe(9)}"


def _canonical(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _ledger_append(event_type: str, agent_id: str, amount: float,
                   payload: Dict[str, Any], mirror: bool = True) -> Dict[str, Any]:
    """Append an immutable, hash-chained ledger entry. Returns the entry.

    ``mirror`` controls the best-effort write into the platform-wide ledger; it
    is disabled when recording a commission another instance already accrued and
    mirrored, so the shared ledger is not duplicated cross-instance.
    """
    prev_hash = COMMISSION_LEDGER[-1]["entry_hash"] if COMMISSION_LEDGER else _GENESIS_HASH
    seq = len(COMMISSION_LEDGER) + 1
    body = {
        "sequence_no": seq,
        "event_type": event_type,
        "agent_id": agent_id,
        "amount": round(float(amount or 0.0), 2),
        "timestamp": _now_iso(),
        "payload": payload,
    }
    entry_hash = hashlib.sha256((prev_hash + _canonical(body)).encode("utf-8")).hexdigest()
    entry = {**body, "id": f"AGLEDGER-{seq:08d}", "previous_hash": prev_hash, "entry_hash": entry_hash}
    COMMISSION_LEDGER.append(entry)
    # Best-effort mirror into the platform-wide hash-chained ledger.
    if mirror and _db_enabled():
        try:
            from web_portal.server import platform_event_ledger
            platform_event_ledger.append_event(
                event_type=event_type,
                entity_type="agent_commission",
                entity_id=payload.get("commission_id") or agent_id,
                actor=agent_id,
                amount=body["amount"],
                payload=payload,
            )
        except Exception:
            pass
    return entry


def verify_ledger_integrity() -> bool:
    """Recompute the hash chain and confirm it is intact (used by tests/admin).

    Holds ``_LOCK`` so the chain cannot be rebuilt by a concurrent hydrate (the
    portal runs on ``ThreadingHTTPServer``) while it is being walked, which would
    otherwise yield spurious "tampered" or misleading "intact" results. ``_LOCK``
    is reentrant, so callers that already hold it (e.g. ``community_overview``)
    are unaffected.
    """
    with _LOCK:
        prev = _GENESIS_HASH
        for entry in COMMISSION_LEDGER:
            body = {
                "sequence_no": entry["sequence_no"],
                "event_type": entry["event_type"],
                "agent_id": entry["agent_id"],
                "amount": entry["amount"],
                "timestamp": entry["timestamp"],
                "payload": entry["payload"],
            }
            expected = hashlib.sha256((prev + _canonical(body)).encode("utf-8")).hexdigest()
            if expected != entry["entry_hash"] or entry["previous_hash"] != prev:
                return False
            prev = entry["entry_hash"]
        return True


# ---------------------------------------------------------------------------
# Best-effort DB persistence (write-through). No-ops when DB disabled.
# ---------------------------------------------------------------------------
def _db():
    from database.manager import DatabaseManager
    return DatabaseManager()


def _persist(kind: str, record: Dict[str, Any]) -> bool:
    """Best-effort durable write-through. Returns True on success (or when DB is
    disabled and there is nothing to persist), False when the durable write
    fails so callers can reconcile in-memory state (e.g. a lost unique-key race).
    """
    if not _db_enabled():
        return True
    try:
        with _db() as db:
            repo, pk = {
                "agent": (db.agents, "id"),
                "invitation": (db.agent_invitations, "code"),
                "affiliation": (db.agent_affiliations, "id"),
                "commission": (db.agent_commissions, "id"),
            }[kind]
            payload = dict(record)
            if kind == "invitation":
                payload = dict(payload)
                payload["used_by"] = json.dumps(payload.get("used_by", []))
            # The in-memory dicts carry ISO-string timestamps, but DateTime
            # columns (e.g. agents.created_date/updated_date) reject strings on
            # SQLite. Drop string-valued datetime fields so the column defaults
            # (default/onupdate=datetime.utcnow) populate them durably.
            try:
                from sqlalchemy import DateTime as _SADateTime
                for _col in repo.model_class.__table__.columns:  # type: ignore[attr-defined]
                    if isinstance(_col.type, _SADateTime) and isinstance(payload.get(_col.name), str):
                        payload.pop(_col.name, None)
            except Exception:
                pass
            key = payload.get(pk)
            if key is not None and repo.get_by_id(key) is not None:
                repo.update(key, **payload)
            else:
                repo.create(**payload)
        return True
    except Exception:
        # Durability is best-effort; the in-memory store remains authoritative.
        return False


def _find_persisted_commission(source_event_id: str,
                               affiliation_id: str) -> Optional[Dict[str, Any]]:
    """Look up a durable commission for an event, if any. No-op when DB disabled.

    Used for cross-instance idempotency: another app instance may have accrued
    and written through this revenue event before this instance's in-memory
    ``_ACCRUED_KEYS`` learned about it.
    """
    if not _db_enabled():
        return None
    try:
        with _db() as db:
            row = db.agent_commissions.get_for_event(source_event_id, affiliation_id)
            return row.to_dict() if row is not None else None
    except Exception:
        return None


def _build_commission_ledger(
    invitations: Dict[str, Dict[str, Any]],
    affiliations: Dict[str, Dict[str, Any]],
    commissions: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build a fresh hash chain from the given durable state and return it.

    The commission ledger is not itself a durable table; after a restart (or a
    refresh-on-read full cache replace) we reconstruct an internally consistent
    chain from the loaded invitations, affiliations and commissions so the
    ledger view, KPI counts and integrity check reflect the full persisted event
    history — both accruals and the invitation/affiliation lifecycle events that
    are otherwise only appended in memory (and would be silently dropped on each
    refresh). New events continue the chain.

    Pure: it does not mutate any shared state, so the caller can swap the result
    into ``COMMISSION_LEDGER`` only once the full refresh has succeeded.
    """
    # Collect every reconstructable event with its timestamp; a stable sort by
    # timestamp keeps each invitation's created event before its later
    # approval/rejection event.
    events: List[Dict[str, Any]] = []
    for inv in invitations.values():
        events.append({
            "event_type": "agent.invitation.created",
            "agent_id": inv.get("agent_id"),
            "amount": 0.0,
            "timestamp": inv.get("created_at") or _now_iso(),
            "payload": {"code": inv.get("code"),
                        "invitee_type": inv.get("invitee_type"),
                        "proposed_rate": inv.get("proposed_rate")},
        })
        if inv.get("status") in ("approved", "sent", "accepted") and inv.get("approved_at"):
            events.append({
                "event_type": "agent.invitation.approved",
                "agent_id": inv.get("agent_id"),
                "amount": 0.0,
                "timestamp": inv.get("approved_at"),
                "payload": {"code": inv.get("code"),
                            "commission_rate": inv.get("commission_rate"),
                            "approved_by": inv.get("approved_by")},
            })
        elif inv.get("status") == "rejected":
            events.append({
                "event_type": "agent.invitation.rejected",
                "agent_id": inv.get("agent_id"),
                "amount": 0.0,
                "timestamp": inv.get("approved_at") or inv.get("created_at") or _now_iso(),
                "payload": {"code": inv.get("code"),
                            "rejected_by": inv.get("approved_by")},
            })
    for aff in affiliations.values():
        events.append({
            "event_type": "agent.affiliation.created",
            "agent_id": aff.get("agent_id"),
            "amount": 0.0,
            "timestamp": aff.get("effective_from") or _now_iso(),
            "payload": {"affiliation_id": aff.get("id"),
                        "principal_type": aff.get("principal_type"),
                        "principal_id": aff.get("principal_id"),
                        "commission_rate": aff.get("commission_rate")},
        })
    for comm in commissions.values():
        aff = affiliations.get(comm.get("affiliation_id")) or {}
        events.append({
            "event_type": "agent.commission.accrued",
            "agent_id": comm.get("agent_id"),
            "amount": round(float(comm.get("amount") or 0.0), 2),
            "timestamp": comm.get("created_at") or _now_iso(),
            "payload": {
                "commission_id": comm.get("id"),
                "affiliation_id": comm.get("affiliation_id"),
                "principal_type": aff.get("principal_type"),
                "principal_id": aff.get("principal_id"),
                "base_amount": comm.get("base_amount"),
                "rate": comm.get("rate"),
                "source_event_id": comm.get("source_event_id"),
            },
        })

    events.sort(key=lambda e: e["timestamp"] or "")
    ledger: List[Dict[str, Any]] = []
    for ev in events:
        prev_hash = ledger[-1]["entry_hash"] if ledger else _GENESIS_HASH
        seq = len(ledger) + 1
        body = {
            "sequence_no": seq,
            "event_type": ev["event_type"],
            "agent_id": ev["agent_id"],
            "amount": ev["amount"],
            "timestamp": ev["timestamp"],
            "payload": ev["payload"],
        }
        entry_hash = hashlib.sha256((prev_hash + _canonical(body)).encode("utf-8")).hexdigest()
        ledger.append({**body, "id": f"AGLEDGER-{seq:08d}",
                       "previous_hash": prev_hash, "entry_hash": entry_hash})
    return ledger


def _hydrate_from_db(force: bool = False) -> None:
    """Refresh the in-memory cache from the durable tables (DB mode only).

    Full-replace semantics so peer instances' writes — new agents, approvals,
    affiliations, suspensions, rate changes — become visible rather than a
    stale once-at-startup snapshot. Read paths coalesce refreshes to at most one
    every ``_HYDRATE_TTL`` seconds; write/decision paths pass ``force=True`` to
    always act on the freshest state. No-op when DB is disabled (in-memory mode).
    """
    global _last_hydrate
    if not _db_enabled():
        return
    now = time.monotonic()
    if not force and (now - _last_hydrate) < _HYDRATE_TTL:
        return
    try:
        with _db() as db:
            agents = [a.to_dict() for a in db.agents.list_all()]
            invitations = [i.to_dict() for i in db.agent_invitations.get_all()]
            affiliations = [a.to_dict() for a in db.agent_affiliations.get_all()]
            commissions = [c.to_dict() for c in db.agent_commissions.get_all()]
        # Build the replacement state (including the rebuilt ledger) in local
        # structures first. Only after all fallible work succeeds do we clear and
        # repopulate the live cache, so a mid-refresh failure can never leave the
        # service serving an emptied or partially loaded ecosystem.
        new_agents: Dict[str, Dict[str, Any]] = {}
        new_agent_by_user: Dict[str, str] = {}
        new_invitations: Dict[str, Dict[str, Any]] = {}
        new_affiliations: Dict[str, Dict[str, Any]] = {}
        new_commissions: Dict[str, Dict[str, Any]] = {}
        new_active_affil: Dict[Tuple[str, str], str] = {}
        new_accrued_keys: set = set()
        for d in agents:
            new_agents[d["id"]] = d
            new_agent_by_user[d["user_username"]] = d["id"]
        for d in invitations:
            new_invitations[d["code"]] = d
        for d in affiliations:
            new_affiliations[d["id"]] = d
            if d["status"] == "active":
                new_active_affil[(d["principal_type"], d["principal_id"])] = d["id"]
        for d in commissions:
            new_commissions[d["id"]] = d
            new_accrued_keys.add((d["source_event_id"], d["affiliation_id"]))
        new_ledger = _build_commission_ledger(
            new_invitations, new_affiliations, new_commissions)
        # Commit atomically (under the caller's lock) so reads reflect exactly the
        # current durable state, including removals/status changes. Only fast,
        # non-raising clear()/update() swaps remain, so reads never observe a
        # cleared cache.
        AGENTS.clear(); AGENTS.update(new_agents)
        AGENT_BY_USER.clear(); AGENT_BY_USER.update(new_agent_by_user)
        INVITATIONS.clear(); INVITATIONS.update(new_invitations)
        AFFILIATIONS.clear(); AFFILIATIONS.update(new_affiliations)
        COMMISSIONS.clear(); COMMISSIONS.update(new_commissions)
        _ACTIVE_AFFIL.clear(); _ACTIVE_AFFIL.update(new_active_affil)
        _ACCRUED_KEYS.clear(); _ACCRUED_KEYS.update(new_accrued_keys)
        COMMISSION_LEDGER[:] = new_ledger
        _last_hydrate = now
    except Exception:
        # Durability/refresh is best-effort; keep serving the current cache and
        # retry on the next call instead of failing the request.
        pass


# ---------------------------------------------------------------------------
# Lifecycle / seeding
# ---------------------------------------------------------------------------
def reset_agent_ecosystem() -> None:
    """Clear all in-memory state (used by tests for isolation)."""
    with _LOCK:
        AGENTS.clear()
        AGENT_BY_USER.clear()
        INVITATIONS.clear()
        AFFILIATIONS.clear()
        COMMISSIONS.clear()
        COMMISSION_LEDGER.clear()
        _ACTIVE_AFFIL.clear()
        _ACCRUED_KEYS.clear()
        global _last_hydrate
        _last_hydrate = 0.0


def ensure_demo_agent() -> Dict[str, Any]:
    """Ensure a demo agent profile exists for username 'agent' (AGT-DEMO-001)."""
    with _LOCK:
        _hydrate_from_db(force=True)
        existing = AGENT_BY_USER.get("agent")
        if existing:
            return AGENTS[existing]
        return _create_agent_locked(
            username="agent", display_name="Demo Agent",
            email="agent@phins.ai", default_rate=0.10, created_by="system",
            agent_id="AGT-DEMO-001",
        )


# ---------------------------------------------------------------------------
# Agent profiles
# ---------------------------------------------------------------------------
def _create_agent_locked(username: str, display_name: str, email: str,
                         default_rate: float, created_by: str,
                         agent_id: Optional[str] = None,
                         parent_agent_id: Optional[str] = None) -> Dict[str, Any]:
    agent_id = agent_id or _gen_id("AGT")
    agent = {
        "id": agent_id,
        "user_username": username,
        "display_name": display_name or username,
        "email": email,
        "status": "active",
        "default_commission_rate": normalize_rate(default_rate, 0.0),
        "parent_agent_id": parent_agent_id,
        "created_by": created_by,
        "created_date": _now_iso(),
        "updated_date": _now_iso(),
    }
    AGENTS[agent_id] = agent
    AGENT_BY_USER[username] = agent_id
    _persist("agent", agent)
    return agent


def create_agent(username: str, display_name: str = "", email: str = "",
                 default_rate: Any = 0.0, created_by: str = "admin",
                 parent_agent_id: Optional[str] = None) -> Dict[str, Any]:
    with _LOCK:
        _hydrate_from_db(force=True)
        if username in AGENT_BY_USER:
            return AGENTS[AGENT_BY_USER[username]]
        return _create_agent_locked(
            username=username, display_name=display_name, email=email,
            default_rate=default_rate, created_by=created_by, parent_agent_id=parent_agent_id,
        )


def get_agent_by_username(username: Optional[str]) -> Optional[Dict[str, Any]]:
    if not username:
        return None
    with _LOCK:
        _hydrate_from_db()
        aid = AGENT_BY_USER.get(username)
        return AGENTS.get(aid) if aid else None


def get_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        _hydrate_from_db()
        return AGENTS.get(agent_id)


def list_agents() -> List[Dict[str, Any]]:
    with _LOCK:
        _hydrate_from_db()
        return sorted(AGENTS.values(), key=lambda a: a.get("created_date", ""))


def update_agent(agent_id: str, status: Optional[str] = None,
                 default_rate: Any = None) -> Optional[Dict[str, Any]]:
    with _LOCK:
        _hydrate_from_db(force=True)
        agent = AGENTS.get(agent_id)
        if not agent:
            return None
        if status in ("active", "suspended", "pending"):
            agent["status"] = status
        if default_rate is not None:
            agent["default_commission_rate"] = normalize_rate(default_rate, agent["default_commission_rate"])
        agent["updated_date"] = _now_iso()
        _persist("agent", agent)
        return agent


# ---------------------------------------------------------------------------
# Invitations (commission locked by admin in advance)
# ---------------------------------------------------------------------------
def create_invitation(agent_id: str, invitee_type: str, invitee_email: str = "",
                      invitee_phone: str = "", proposed_rate: Any = None,
                      commission_basis: str = "premium", expires_days: int = 30,
                      notes: str = "") -> Tuple[bool, Any]:
    with _LOCK:
        _hydrate_from_db(force=True)
        agent = AGENTS.get(agent_id)
        if not agent:
            return False, "Agent not found"
        if agent.get("status") != "active":
            return False, "Agent is not active"
        invitee_type = (invitee_type or "").lower()
        if invitee_type not in VALID_INVITEE_TYPES:
            return False, f"invitee_type must be one of {VALID_INVITEE_TYPES}"
        basis = (commission_basis or "premium").lower()
        if basis not in VALID_BASES:
            return False, f"commission_basis must be one of {VALID_BASES}"
        prop = normalize_rate(proposed_rate, agent.get("default_commission_rate", 0.0))
        code = _gen_code()
        inv = {
            "code": code,
            "agent_id": agent_id,
            "invitee_type": invitee_type,
            "invitee_email": invitee_email,
            "invitee_phone": invitee_phone,
            "proposed_rate": prop,
            "commission_rate": None,  # locked by admin on approval
            "commission_basis": basis,
            "status": "pending_approval",
            "approved_by": None,
            "approved_at": None,
            "created_at": _now_iso(),
            "expires_at": (datetime.utcnow() + timedelta(days=int(expires_days or 30))).isoformat(),
            "max_uses": 1,
            "used_count": 0,
            "used_by": [],
            "notes": notes,
        }
        INVITATIONS[code] = inv
        _persist("invitation", inv)
        _ledger_append("agent.invitation.created", agent_id, 0.0,
                       {"code": code, "invitee_type": invitee_type, "proposed_rate": prop})
        return True, inv


def list_invitations(agent_id: Optional[str] = None,
                     status: Optional[str] = None) -> List[Dict[str, Any]]:
    with _LOCK:
        _hydrate_from_db()
        items = list(INVITATIONS.values())
        if agent_id:
            items = [i for i in items if i["agent_id"] == agent_id]
        if status:
            items = [i for i in items if i["status"] == status]
        return sorted(items, key=lambda i: i.get("created_at", ""), reverse=True)


def approve_invitation(code: str, commission_rate: Any, admin: str) -> Tuple[bool, Any]:
    with _LOCK:
        _hydrate_from_db(force=True)
        inv = INVITATIONS.get(code)
        if not inv:
            return False, "Invitation not found"
        if inv["status"] != "pending_approval":
            return False, f"Cannot approve invitation in status '{inv['status']}'"
        inv["commission_rate"] = normalize_rate(commission_rate, inv.get("proposed_rate", 0.0))
        inv["status"] = "approved"
        inv["approved_by"] = admin
        inv["approved_at"] = _now_iso()
        _persist("invitation", inv)
        _ledger_append("agent.invitation.approved", inv["agent_id"], 0.0,
                       {"code": code, "commission_rate": inv["commission_rate"], "approved_by": admin})
        return True, inv


def reject_invitation(code: str, admin: str, reason: str = "") -> Tuple[bool, Any]:
    with _LOCK:
        _hydrate_from_db(force=True)
        inv = INVITATIONS.get(code)
        if not inv:
            return False, "Invitation not found"
        if inv["status"] != "pending_approval":
            return False, f"Cannot reject invitation in status '{inv['status']}'"
        inv["status"] = "rejected"
        inv["approved_by"] = admin
        inv["notes"] = (inv.get("notes") or "") + f" [rejected: {reason}]"
        _persist("invitation", inv)
        _ledger_append("agent.invitation.rejected", inv["agent_id"], 0.0,
                       {"code": code, "rejected_by": admin})
        return True, inv


def validate_invitation(code: str) -> Dict[str, Any]:
    """Public validation used by registration flows."""
    with _LOCK:
        _hydrate_from_db()
        inv = INVITATIONS.get(code)
        if not inv:
            return {"valid": False, "error": "Invalid invitation code"}
        if inv["status"] not in ("approved", "sent"):
            return {"valid": False, "error": "Invitation is not active"}
        if inv.get("expires_at") and inv["expires_at"] < _now_iso():
            return {"valid": False, "error": "Invitation has expired"}
        if inv["used_count"] >= inv["max_uses"]:
            return {"valid": False, "error": "Invitation already used"}
        return {
            "valid": True,
            "invitee_type": inv["invitee_type"],
            "agent_id": inv["agent_id"],
            "commission_basis": inv["commission_basis"],
        }


def redeem_invitation(code: str, principal_type: str, principal_id: str) -> Tuple[bool, Any]:
    """Redeem an approved invitation, creating a locked-rate affiliation.

    Hierarchy integrity: a principal may have at most ONE active affiliation.
    """
    with _LOCK:
        _hydrate_from_db(force=True)
        inv = INVITATIONS.get(code)
        if not inv:
            return False, "Invalid invitation code"
        if inv["status"] not in ("approved", "sent"):
            return False, "Invitation is not active"
        if inv.get("expires_at") and inv["expires_at"] < _now_iso():
            return False, "Invitation has expired"
        if inv.get("commission_rate") is None:
            return False, "Invitation has no admin-approved commission rate"
        if inv["used_count"] >= inv["max_uses"]:
            return False, "Invitation already used"
        agent = AGENTS.get(inv["agent_id"])
        if not agent or agent.get("status") != "active":
            return False, "Agent is not active"
        principal_type = (principal_type or "").lower()
        if principal_type != inv["invitee_type"]:
            return False, f"Invitation is for '{inv['invitee_type']}', not '{principal_type}'"

        key = (principal_type, principal_id)
        if key in _ACTIVE_AFFIL:
            return False, "Principal already has an active agent affiliation"

        aff_id = _gen_id("AFF")
        aff = {
            "id": aff_id,
            "agent_id": inv["agent_id"],
            "principal_type": principal_type,
            "principal_id": principal_id,
            "source_invitation_code": code,
            "commission_rate": inv["commission_rate"],  # LOCKED snapshot
            "commission_basis": inv["commission_basis"],
            "status": "active",
            "effective_from": _now_iso(),
            "effective_to": None,
        }
        AFFILIATIONS[aff_id] = aff
        _ACTIVE_AFFIL[key] = aff_id
        inv["used_count"] += 1
        inv["used_by"] = list(inv.get("used_by", [])) + [principal_id]
        if inv["used_count"] >= inv["max_uses"]:
            inv["status"] = "accepted"
        _persist("affiliation", aff)
        _persist("invitation", inv)
        _ledger_append("agent.affiliation.created", inv["agent_id"], 0.0,
                       {"affiliation_id": aff_id, "principal_type": principal_type,
                        "principal_id": principal_id, "commission_rate": aff["commission_rate"]})
        return True, aff


def mark_invitation_sent(code: str) -> None:
    with _LOCK:
        inv = INVITATIONS.get(code)
        if inv and inv["status"] == "approved":
            inv["status"] = "sent"
            _persist("invitation", inv)


def get_active_affiliation(principal_type: str, principal_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        _hydrate_from_db()
        aid = _ACTIVE_AFFIL.get((principal_type, principal_id))
        return AFFILIATIONS.get(aid) if aid else None


def list_affiliations(agent_id: str) -> List[Dict[str, Any]]:
    with _LOCK:
        _hydrate_from_db()
        return [a for a in AFFILIATIONS.values() if a["agent_id"] == agent_id]


def persist_referring_agent(principal_type: str, principal_id: str, agent_id: str) -> None:
    """Best-effort durable write of the referring-agent FK on the principal.

    The in-memory portal record is updated by the API layer; this mirrors the
    "referred by" linkage to the durable ``customers``/``suppliers`` tables so
    it survives outside the portal memory store. No-op when DB is disabled.
    """
    if not _db_enabled():
        return
    ptype = (principal_type or "").lower()
    if ptype not in ("customer", "supplier"):
        return
    try:
        with _db() as db:
            repo = db.customers if ptype == "customer" else db.suppliers
            if repo.get_by_id(principal_id) is not None:
                repo.update(principal_id, referring_agent_id=agent_id)
    except Exception:
        # Durability is best-effort; the in-memory linkage remains authoritative.
        pass


# ---------------------------------------------------------------------------
# Commission accrual (idempotent, ledger-backed)
# ---------------------------------------------------------------------------
def accrue_commission(principal_type: str, principal_id: str, base_amount: float,
                      source_event_id: str, source_type: str = "policy_premium",
                      currency: str = "USD", basis: str = "premium") -> Optional[Dict[str, Any]]:
    """Accrue a commission for a revenue event, if the principal is affiliated.

    Idempotent on (source_event_id, affiliation_id). Returns the commission dict
    or None when there is no active affiliation / nothing to accrue. The event's
    ``basis`` must match the affiliation's locked ``commission_basis`` (a
    premium event does not accrue against a GMV / one-time affiliation, etc.).
    """
    with _LOCK:
        aff = get_active_affiliation(principal_type, principal_id)
        if not aff:
            return None
        agent = AGENTS.get(aff["agent_id"])
        if agent and agent.get("status") == "suspended":
            return None  # suspended agents do not accrue new commissions
        if (aff.get("commission_basis") or "premium") != basis:
            return None  # event basis does not match the locked affiliation basis
        key = (source_event_id, aff["id"])
        if key in _ACCRUED_KEYS:
            return None  # already accrued — idempotent
        # Cross-instance idempotency: a peer instance may have already accrued
        # and persisted this revenue event before our in-memory _ACCRUED_KEYS
        # caught up. Reconcile from the durable store instead of appending a
        # second ledger entry / commission row for one revenue event. The unique
        # (source_event_id, affiliation_id) constraint backstops the simultaneous
        # race at write-through time.
        existing = _find_persisted_commission(source_event_id, aff["id"])
        if existing is not None:
            if existing["id"] not in COMMISSIONS:
                COMMISSIONS[existing["id"]] = existing
                # Record the reconciled accrual on this instance's ledger so the
                # local ledger stays complete relative to COMMISSIONS. The peer
                # that persisted it already mirrored to the platform ledger.
                _ledger_append(
                    "agent.commission.accrued", existing["agent_id"],
                    existing.get("amount") or 0.0,
                    {"commission_id": existing["id"], "affiliation_id": aff["id"],
                     "principal_type": principal_type, "principal_id": principal_id,
                     "base_amount": existing.get("base_amount"),
                     "rate": existing.get("rate"),
                     "source_event_id": source_event_id},
                    mirror=False)
            _ACCRUED_KEYS.add(key)
            return None
        base = round(float(base_amount or 0.0), 2)
        if base <= 0:
            return None
        rate = float(aff.get("commission_rate") or 0.0)
        amount = round(base * rate, 2)
        comm_id = _gen_id("COMM")
        entry = _ledger_append("agent.commission.accrued", aff["agent_id"], amount,
                               {"commission_id": comm_id, "affiliation_id": aff["id"],
                                "principal_type": principal_type, "principal_id": principal_id,
                                "base_amount": base, "rate": rate, "source_event_id": source_event_id})
        comm = {
            "id": comm_id,
            "agent_id": aff["agent_id"],
            "affiliation_id": aff["id"],
            "source_event_id": source_event_id,
            "source_type": source_type,
            "base_amount": base,
            "rate": rate,
            "amount": amount,
            "currency": currency,
            "status": "accrued",
            "ledger_entry_id": entry["id"],
            "created_at": _now_iso(),
        }
        COMMISSIONS[comm_id] = comm
        _ACCRUED_KEYS.add(key)
        if _persist("commission", comm):
            return comm
        # The durable write failed (e.g. a peer instance won the unique
        # (source_event_id, affiliation_id) race). Roll back this instance's
        # in-memory accrual so income totals do not double-count against the DB.
        COMMISSIONS.pop(comm_id, None)
        if COMMISSION_LEDGER and COMMISSION_LEDGER[-1]["id"] == entry["id"]:
            COMMISSION_LEDGER.pop()
        reconciled = _find_persisted_commission(source_event_id, aff["id"])
        if reconciled is not None:
            COMMISSIONS[reconciled["id"]] = reconciled
            _ledger_append(
                "agent.commission.accrued", reconciled["agent_id"],
                reconciled.get("amount") or 0.0,
                {"commission_id": reconciled["id"], "affiliation_id": aff["id"],
                 "principal_type": principal_type, "principal_id": principal_id,
                 "base_amount": reconciled.get("base_amount"),
                 "rate": reconciled.get("rate"),
                 "source_event_id": source_event_id},
                mirror=False)
        else:
            # No durable row exists (transient failure, not a duplicate); allow a
            # later call to re-accrue rather than stranding the event as accrued.
            _ACCRUED_KEYS.discard(key)
        return None


def _policy_drives_commission(policy: Dict[str, Any]) -> bool:
    """A policy contributes to the premium basis only when active/approved.

    Shared by ``accrue_for_policy`` (accrual gate) and ``network_customers``
    (dashboard premium basis) so the displayed basis matches what actually
    accrues commission. A missing/blank status is treated as eligible.
    """
    status = (policy.get("status") or "").lower().replace(" ", "_")
    return not status or status in ("active", "approved")


def accrue_for_policy(policy: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Accrue commission from a policy's annual premium (premium basis).

    v1 accrues once per policy (source_event_id = policy:{id}); recurring
    per-renewal accrual is a follow-up keyed by billing period.
    """
    if not isinstance(policy, dict):
        return None
    customer_id = policy.get("customer_id")
    pid = policy.get("id")
    if not customer_id or not pid:
        return None
    if not _policy_drives_commission(policy):
        return None  # only active/approved policies generate premium-basis commission
    premium = policy.get("annual_premium") or policy.get("premium") or 0
    try:
        premium = float(premium)
    except (TypeError, ValueError):
        premium = 0.0
    return accrue_commission("customer", customer_id, premium,
                             source_event_id=f"policy:{pid}", source_type="policy_premium",
                             basis="premium")


def recompute_commissions(policies: Dict[str, Any]) -> int:
    """Idempotently scan policies and accrue commissions for affiliated customers.

    Returns the number of NEW commission rows created.
    """
    with _LOCK:
        _hydrate_from_db(force=True)
        created = 0
        if not policies:
            return 0
        for policy in list(policies.values()):
            before = len(COMMISSIONS)
            accrue_for_policy(policy)
            if len(COMMISSIONS) > before:
                created += 1
    return created


def list_commissions(agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
    with _LOCK:
        _hydrate_from_db()
        items = list(COMMISSIONS.values())
        if agent_id:
            items = [c for c in items if c["agent_id"] == agent_id]
        return sorted(items, key=lambda c: c.get("created_at", ""), reverse=True)


# ---------------------------------------------------------------------------
# Dashboards (agent-scoped, PII-minimized)
# ---------------------------------------------------------------------------
def income_summary(agent_id: str) -> Dict[str, Any]:
    with _LOCK:
        _hydrate_from_db()
        comms = [c for c in COMMISSIONS.values() if c["agent_id"] == agent_id]
        affs = [a for a in AFFILIATIONS.values() if a["agent_id"] == agent_id and a["status"] == "active"]
        invs = [i for i in INVITATIONS.values() if i["agent_id"] == agent_id]

        def total(status: Optional[str] = None) -> float:
            return round(sum(c["amount"] for c in comms
                             if status is None or c["status"] == status), 2)

        return {
            "agent_id": agent_id,
            "currency": "USD",
            "accrued_total": total("accrued"),
            "payable_total": total("payable"),
            "paid_total": total("paid"),
            "lifetime_total": total(),
            "counts": {
                "affiliated_customers": len([a for a in affs if a["principal_type"] == "customer"]),
                "affiliated_suppliers": len([a for a in affs if a["principal_type"] == "supplier"]),
                "sub_agents": len([a for a in affs if a["principal_type"] == "agent"]),
                "invitations_pending_approval": len([i for i in invs if i["status"] == "pending_approval"]),
                "invitations_active": len([i for i in invs if i["status"] in ("approved", "sent")]),
                "commission_events": len(comms),
            },
        }


def network_customers(agent_id: str, customers: Dict[str, Any],
                      policies: Dict[str, Any], page: int = 1,
                      page_size: int = 50) -> Dict[str, Any]:
    """PII-minimized outline of the agent's affiliated customers.

    Returns only name, status, policy count, premium basis and accrued
    commission — never full PII/medical data (cross-tenant safety).
    """
    with _LOCK:
        _hydrate_from_db()
        affs = [a for a in AFFILIATIONS.values()
                if a["agent_id"] == agent_id and a["principal_type"] == "customer"]
        rows: List[Dict[str, Any]] = []
        for aff in affs:
            cid = aff["principal_id"]
            cust = (customers or {}).get(cid) or {}
            cust_policies = [p for p in (policies or {}).values()
                             if p.get("customer_id") == cid and _policy_drives_commission(p)]
            premium_basis = round(sum(float(p.get("annual_premium") or p.get("premium") or 0) for p in cust_policies), 2)
            accrued = round(sum(c["amount"] for c in COMMISSIONS.values()
                                if c["affiliation_id"] == aff["id"]), 2)
            rows.append({
                "customer_id": cid,
                "name": cust.get("name") or cust.get("first_name") or "Affiliated customer",
                "status": "active" if aff["status"] == "active" else aff["status"],
                "policy_count": len(cust_policies),
                "premium_basis": premium_basis,
                "commission_rate": aff["commission_rate"],
                "accrued_commission": accrued,
                "affiliation_id": aff["id"],
            })
        rows.sort(key=lambda r: r["accrued_commission"], reverse=True)
        total = len(rows)
        page = max(1, int(page or 1))
        page_size = max(1, min(int(page_size or 50), 200))
        start = (page - 1) * page_size
        return {
            "items": rows[start:start + page_size],
            "page": page,
            "page_size": page_size,
            "total": total,
        }


def community_overview() -> Dict[str, Any]:
    """Aggregate, admin-facing view of the whole agent community.

    Read-only; includes a live hash-chain integrity check so admins can confirm
    the commission ledger has not been tampered with.
    """
    with _LOCK:
        _hydrate_from_db()
        agents = list(AGENTS.values())
        affs = [a for a in AFFILIATIONS.values() if a["status"] == "active"]
        invs = list(INVITATIONS.values())
        comms = list(COMMISSIONS.values())

        def ctotal(status: Optional[str] = None) -> float:
            return round(sum(c["amount"] for c in comms
                             if status is None or c["status"] == status), 2)

        return {
            "agents_total": len(agents),
            "agents_active": len([a for a in agents if a.get("status") == "active"]),
            "agents_suspended": len([a for a in agents if a.get("status") == "suspended"]),
            "affiliated_customers": len([a for a in affs if a["principal_type"] == "customer"]),
            "affiliated_suppliers": len([a for a in affs if a["principal_type"] == "supplier"]),
            "sub_agents": len([a for a in affs if a["principal_type"] == "agent"]),
            "invitations_total": len(invs),
            "invitations_pending_approval": len([i for i in invs if i["status"] == "pending_approval"]),
            "invitations_active": len([i for i in invs if i["status"] in ("approved", "sent")]),
            "commission_accrued_total": ctotal("accrued"),
            "commission_payable_total": ctotal("payable"),
            "commission_paid_total": ctotal("paid"),
            "commission_lifetime_total": ctotal(),
            "commission_events": len(comms),
            "ledger_entries": len(COMMISSION_LEDGER),
            "ledger_intact": verify_ledger_integrity(),
            "currency": "USD",
        }


def get_ledger(agent_id: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    with _LOCK:
        _hydrate_from_db()
        items = COMMISSION_LEDGER
        if agent_id:
            items = [e for e in items if e["agent_id"] == agent_id]
        return list(items[-limit:])
