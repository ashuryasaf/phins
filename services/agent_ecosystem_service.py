"""
Agent / Broker ecosystem service ("AgentOS").

Implements the agent layer the investor deck promises:
  * agent profiles (role='agent')
  * invitations for customers / suppliers / sub-agents, with a commission rate
    that an admin LOCKS in advance
  * affiliations with hierarchy integrity (at most one active affiliation per
    principal — no double commission)
  * idempotent, hash-chained commission accrual on revenue events — once per
    policy for the initial term and once per renewal term (§C), keyed on
    ``(affiliation_id, source_event_id, period)``
  * payout runs (``agent_payouts``): sweep accrued commissions into a run,
    settle it (commissions -> paid) and anchor it on the platform ledger
  * agent income summaries, a PII-minimized "customer outline" and a
    subtree-scoped broker funnel

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
import secrets
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from services.hydrated_store import (
    DEFAULT_TTL, HYDRATE_TTL_ENV, RefreshCoalescer, _env_float, db_mode_enabled,
)

# ---------------------------------------------------------------------------
# Module state (authoritative in-memory working store)
# ---------------------------------------------------------------------------
_LOCK = threading.RLock()

AGENTS: Dict[str, Dict[str, Any]] = {}            # agent_id -> agent dict
AGENT_BY_USER: Dict[str, str] = {}                # username -> agent_id
INVITATIONS: Dict[str, Dict[str, Any]] = {}       # code -> invitation dict
AFFILIATIONS: Dict[str, Dict[str, Any]] = {}      # affiliation_id -> dict
COMMISSIONS: Dict[str, Dict[str, Any]] = {}       # commission_id -> dict
PAYOUTS: Dict[str, Dict[str, Any]] = {}           # payout_id -> dict (§C payout runs)
COMMISSION_LEDGER: List[Dict[str, Any]] = []      # append-only, hash-chained
_ACTIVE_AFFIL: Dict[Tuple[str, str], str] = {}    # (principal_type, principal_id) -> affiliation_id
_ACCRUED_KEYS: set = set()                         # (source_event_id, affiliation_id, period)

INITIAL_TERM = ""                                  # ``period`` of the once-per-policy accrual
PAYOUT_STATUSES = ("calculated", "settled")

_GENESIS_HASH = "0" * 64
# Refresh-on-read coalescing. In DB mode the durable tables are the source of
# truth; the in-memory dicts are a short-lived per-instance cache that is
# re-pulled from the database. This keeps multiple app instances consistent
# (an agent/invitation/affiliation/suspension created on one instance becomes
# visible on the others) instead of each instance reading a stale snapshot it
# loaded once at startup. Writes force a fresh pull before deciding.
# The TTL gate itself is the shared ``RefreshCoalescer`` (A4,
# ``services/hydrated_store.py``); ``_last_hydrate`` is kept as the module-level
# mirror callers/tests reset to force an immediate refresh.
_last_hydrate = 0.0
_HYDRATE = RefreshCoalescer(_env_float(HYDRATE_TTL_ENV, DEFAULT_TTL))
_HYDRATE_TTL = _HYDRATE.ttl

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
    return db_mode_enabled()


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
    # Public registration validates codes after .upper(); keep new codes
    # in that form so AGI- tokens survive the shared invitation surface.
    raw = secrets.token_urlsafe(9).upper().replace("-", "")
    return f"AGI-{raw[:12]}"


def _find_invitation(code: Optional[str]) -> Optional[Dict[str, Any]]:
    """Look up an invitation by code, case-insensitively."""
    if not code:
        return None
    inv = INVITATIONS.get(code)
    if inv:
        return inv
    needle = str(code).upper()
    for stored, rec in INVITATIONS.items():
        if str(stored).upper() == needle:
            return rec
    return None


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
                "payout": (db.agent_payouts, "id"),
            }[kind]
            payload = dict(record)
            if kind == "invitation":
                payload = dict(payload)
                payload["used_by"] = json.dumps(payload.get("used_by", []))
            elif kind == "payout":
                payload["commission_ids"] = json.dumps(list(payload.get("commission_ids") or []))
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
    payouts: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Build a fresh hash chain from the given durable state and return it.

    The commission ledger is not itself a durable table; after a restart (or a
    refresh-on-read full cache replace) we reconstruct an internally consistent
    chain from the loaded invitations, affiliations, commissions and payout runs
    so the ledger view, KPI counts and integrity check reflect the full
    persisted event history — accruals, payouts and the invitation/affiliation
    lifecycle events that are otherwise only appended in memory (and would be
    silently dropped on each refresh). New events continue the chain.

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
                "period": comm.get("period") or INITIAL_TERM,
            },
        })
    for pay in (payouts or {}).values():
        events.append({
            "event_type": "agent.payout.calculated",
            "agent_id": pay.get("agent_id"),
            "amount": round(float(pay.get("gross_amount") or 0.0), 2),
            "timestamp": pay.get("created_at") or _now_iso(),
            "payload": _payout_ledger_payload(pay),
        })
        if pay.get("status") == "settled" and pay.get("settled_at"):
            events.append({
                "event_type": "agent.payout.settled",
                "agent_id": pay.get("agent_id"),
                "amount": round(float(pay.get("gross_amount") or 0.0), 2),
                "timestamp": pay.get("settled_at"),
                "payload": {**_payout_ledger_payload(pay),
                            "external_payout_reference": pay.get("external_payout_reference"),
                            "platform_ledger_entry_id": pay.get("platform_ledger_entry_id")},
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
    if not force and _last_hydrate and not _HYDRATE.due():
        return
    try:
        with _db() as db:
            agents = [a.to_dict() for a in db.agents.list_all()]
            invitations = [i.to_dict() for i in db.agent_invitations.get_all()]
            affiliations = [a.to_dict() for a in db.agent_affiliations.get_all()]
            commissions = [c.to_dict() for c in db.agent_commissions.get_all()]
            payouts = [p.to_dict() for p in db.agent_payouts.get_all()]
        # Build the replacement state (including the rebuilt ledger) in local
        # structures first. Only after all fallible work succeeds do we clear and
        # repopulate the live cache, so a mid-refresh failure can never leave the
        # service serving an emptied or partially loaded ecosystem.
        new_agents: Dict[str, Dict[str, Any]] = {}
        new_agent_by_user: Dict[str, str] = {}
        new_invitations: Dict[str, Dict[str, Any]] = {}
        new_affiliations: Dict[str, Dict[str, Any]] = {}
        new_commissions: Dict[str, Dict[str, Any]] = {}
        new_payouts: Dict[str, Dict[str, Any]] = {}
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
            d["period"] = d.get("period") or INITIAL_TERM
            new_commissions[d["id"]] = d
            new_accrued_keys.add((d["source_event_id"], d["affiliation_id"], d["period"]))
        for d in payouts:
            new_payouts[d["id"]] = d
        new_ledger = _build_commission_ledger(
            new_invitations, new_affiliations, new_commissions, new_payouts)
        # Commit atomically (under the caller's lock) so reads reflect exactly the
        # current durable state, including removals/status changes. Only fast,
        # non-raising clear()/update() swaps remain, so reads never observe a
        # cleared cache.
        AGENTS.clear(); AGENTS.update(new_agents)
        AGENT_BY_USER.clear(); AGENT_BY_USER.update(new_agent_by_user)
        INVITATIONS.clear(); INVITATIONS.update(new_invitations)
        AFFILIATIONS.clear(); AFFILIATIONS.update(new_affiliations)
        COMMISSIONS.clear(); COMMISSIONS.update(new_commissions)
        PAYOUTS.clear(); PAYOUTS.update(new_payouts)
        _ACTIVE_AFFIL.clear(); _ACTIVE_AFFIL.update(new_active_affil)
        _ACCRUED_KEYS.clear(); _ACCRUED_KEYS.update(new_accrued_keys)
        COMMISSION_LEDGER[:] = new_ledger
        _last_hydrate = now
        _HYDRATE.mark()
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
        PAYOUTS.clear()
        COMMISSION_LEDGER.clear()
        _ACTIVE_AFFIL.clear()
        _ACCRUED_KEYS.clear()
        global _last_hydrate
        _last_hydrate = 0.0
        _HYDRATE.reset()


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
        inv = _find_invitation(code)
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
        inv = _find_invitation(code)
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
        inv = _find_invitation(code)
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
        inv = _find_invitation(code)
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
        inv = _find_invitation(code)
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
                      currency: str = "USD", basis: str = "premium",
                      period: str = INITIAL_TERM) -> Optional[Dict[str, Any]]:
    """Accrue a commission for a revenue event, if the principal is affiliated.

    Idempotent on ``(source_event_id, affiliation_id, period)``. Returns the
    commission dict or None when there is no active affiliation / nothing to
    accrue. The event's ``basis`` must match the affiliation's locked
    ``commission_basis`` (a premium event does not accrue against a GMV /
    one-time affiliation, etc.). ``period`` is ``INITIAL_TERM`` for the
    once-per-event accrual and a renewal-term label for recurring accruals;
    callers embed the period in ``source_event_id`` (see ``accrue_for_policy``)
    so the durable two-column unique key stays sufficient.
    """
    period = str(period or INITIAL_TERM)
    with _LOCK:
        aff = get_active_affiliation(principal_type, principal_id)
        if not aff:
            return None
        agent = AGENTS.get(aff["agent_id"])
        if agent and agent.get("status") == "suspended":
            return None  # suspended agents do not accrue new commissions
        if (aff.get("commission_basis") or "premium") != basis:
            return None  # event basis does not match the locked affiliation basis
        key = (source_event_id, aff["id"], period)
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
            existing["period"] = existing.get("period") or INITIAL_TERM
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
                     "source_event_id": source_event_id,
                     "period": existing["period"]},
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
                                "base_amount": base, "rate": rate, "source_event_id": source_event_id,
                                "period": period})
        comm = {
            "id": comm_id,
            "agent_id": aff["agent_id"],
            "affiliation_id": aff["id"],
            "source_event_id": source_event_id,
            "source_type": source_type,
            "period": period,
            "base_amount": base,
            "rate": rate,
            "amount": amount,
            "currency": currency,
            "status": "accrued",
            "ledger_entry_id": entry["id"],
            "payout_id": None,
            "paid_at": None,
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
            reconciled["period"] = reconciled.get("period") or INITIAL_TERM
            COMMISSIONS[reconciled["id"]] = reconciled
            _ledger_append(
                "agent.commission.accrued", reconciled["agent_id"],
                reconciled.get("amount") or 0.0,
                {"commission_id": reconciled["id"], "affiliation_id": aff["id"],
                 "principal_type": principal_type, "principal_id": principal_id,
                 "base_amount": reconciled.get("base_amount"),
                 "rate": reconciled.get("rate"),
                 "source_event_id": source_event_id,
                 "period": reconciled["period"]},
                mirror=False)
        else:
            # No durable row exists (transient failure, not a duplicate); allow a
            # later call to re-accrue rather than stranding the event as accrued.
            _ACCRUED_KEYS.discard(key)
        return None


# ---------------------------------------------------------------------------
# Renewal terms (§C per-renewal recurring commission)
# ---------------------------------------------------------------------------
def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse an ISO-ish timestamp (with or without time/``Z``) or return None."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1]
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text[:10])
        except ValueError:
            return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _policy_term_start(policy: Dict[str, Any]) -> Optional[datetime]:
    """The policy's initial-term start; None when no date is recorded."""
    for field in ("start_date", "effective_date", "issuance_date",
                  "created_date", "created_at", "application_date"):
        parsed = _parse_dt(policy.get(field))
        if parsed is not None:
            # Terms roll on the anniversary *date*; the time of day the policy
            # was issued must not shift a same-day renewal into the prior term.
            return parsed.replace(hour=0, minute=0, second=0, microsecond=0)
    return None


def _add_years(moment: datetime, years: int) -> datetime:
    try:
        return moment.replace(year=moment.year + years)
    except ValueError:  # Feb 29 -> Feb 28 on a non-leap year
        return moment.replace(year=moment.year + years, day=28)


def _term_index(term_start: datetime, moment: datetime) -> int:
    """Whole policy years elapsed between the term start and ``moment`` (0 = initial term)."""
    if moment < term_start:
        return 0
    n = moment.year - term_start.year
    if _add_years(term_start, n) > moment:
        n -= 1
    return max(0, n)


def renewal_period_for_bill(policy: Dict[str, Any], bill: Dict[str, Any]) -> Optional[str]:
    """Renewal-term label (``YYYY-MM-DD`` term start) a paid bill belongs to.

    Returns None when the bill falls inside the policy's initial term (already
    covered by the once-per-policy accrual) or when the policy carries no start
    date at all — undeterminable terms never accrue, so a missing date can only
    under-count, never double-count.
    """
    if not isinstance(policy, dict) or not isinstance(bill, dict):
        return None
    term_start = _policy_term_start(policy)
    if term_start is None:
        return None
    moment = None
    for field in ("billing_period_start", "due_date", "paid_date", "created_date"):
        moment = _parse_dt(bill.get(field))
        if moment is not None:
            break
    if moment is None:
        return None
    n = _term_index(term_start, moment)
    if n < 1:
        return None
    return _add_years(term_start, n).strftime("%Y-%m-%d")


def _policy_drives_commission(policy: Dict[str, Any]) -> bool:
    """A policy contributes to the premium basis only when active/approved.

    Shared by ``accrue_for_policy`` (accrual gate) and ``network_customers``
    (dashboard premium basis) so the displayed basis matches what actually
    accrues commission. A missing/blank status is treated as eligible.
    """
    status = (policy.get("status") or "").lower().replace(" ", "_")
    return not status or status in ("active", "approved")


def accrue_for_policy(policy: Dict[str, Any],
                      period: str = INITIAL_TERM) -> Optional[Dict[str, Any]]:
    """Accrue commission from a policy's annual premium (premium basis).

    ``period=INITIAL_TERM`` accrues once per policy (``source_event_id =
    policy:{id}``). A renewal term label (see ``renewal_period_for_bill``)
    accrues once more for that term (``source_event_id = policy:{id}:{period}``,
    ``source_type = policy_renewal``) — recurring while the policy stays active,
    never twice for the same term.
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
    period = str(period or INITIAL_TERM)
    if period == INITIAL_TERM:
        return accrue_commission("customer", customer_id, premium,
                                 source_event_id=f"policy:{pid}", source_type="policy_premium",
                                 basis="premium")
    return accrue_commission("customer", customer_id, premium,
                             source_event_id=f"policy:{pid}:{period}",
                             source_type="policy_renewal", basis="premium", period=period)


def accrue_for_paid_bill(bill: Dict[str, Any],
                         policy: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Billing hook: a *paid* premium bill drives the policy's term accrual.

    Every paid bill first guarantees the once-per-policy (initial-term) accrual
    exists; the first paid bill of each later term additionally accrues that
    renewal (the remaining bills of the same term hit the idempotency key).
    Unpaid bills and bills without a resolvable policy never accrue. Returns the
    newly created commission, if any.
    """
    if not isinstance(bill, dict) or not isinstance(policy, dict):
        return None
    if (bill.get("status") or "").lower() != "paid":
        return None
    if bill.get("policy_id") and policy.get("id") and bill.get("policy_id") != policy.get("id"):
        return None
    initial = accrue_for_policy(policy)
    period = renewal_period_for_bill(policy, bill)
    if period is None:
        return initial
    return accrue_for_policy(policy, period=period) or initial


def recompute_commissions(policies: Dict[str, Any],
                          bills: Optional[Dict[str, Any]] = None) -> int:
    """Idempotently scan policies (and paid bills) and accrue commissions.

    Policies drive the initial-term accrual; paid bills drive per-renewal
    accruals (§C). Returns the number of NEW commission rows created.
    """
    with _LOCK:
        _hydrate_from_db(force=True)
        created = 0
        if not policies:
            return 0
        for policy in list(policies.values()):
            before = len(COMMISSIONS)
            accrue_for_policy(policy)
            created += max(0, len(COMMISSIONS) - before)
        for bill in list((bills or {}).values()):
            if not isinstance(bill, dict):
                continue
            policy = policies.get(bill.get("policy_id"))
            if not isinstance(policy, dict):
                continue
            before = len(COMMISSIONS)
            accrue_for_paid_bill(bill, policy)
            created += max(0, len(COMMISSIONS) - before)
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

        pays = [p for p in PAYOUTS.values() if p["agent_id"] == agent_id]

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
            "renewal_total": round(sum(c["amount"] for c in comms
                                       if (c.get("period") or INITIAL_TERM) != INITIAL_TERM), 2),
            "counts": {
                "affiliated_customers": len([a for a in affs if a["principal_type"] == "customer"]),
                "affiliated_suppliers": len([a for a in affs if a["principal_type"] == "supplier"]),
                "sub_agents": len([a for a in affs if a["principal_type"] == "agent"]),
                "invitations_pending_approval": len([i for i in invs if i["status"] == "pending_approval"]),
                "invitations_active": len([i for i in invs if i["status"] in ("approved", "sent")]),
                "commission_events": len(comms),
                "renewal_events": len([c for c in comms
                                       if (c.get("period") or INITIAL_TERM) != INITIAL_TERM]),
                "payouts_calculated": len([p for p in pays if p["status"] == "calculated"]),
                "payouts_settled": len([p for p in pays if p["status"] == "settled"]),
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
            aff_comms = [c for c in COMMISSIONS.values() if c["affiliation_id"] == aff["id"]]
            accrued = round(sum(c["amount"] for c in aff_comms), 2)
            initial_accrued, renewal_accrued, renewal_periods = _split_terms(aff_comms)
            rate = float(aff.get("commission_rate") or 0.0)
            expected = round(premium_basis * rate, 2)
            referring = cust.get("referring_agent_id")
            rows.append({
                "customer_id": cid,
                "name": cust.get("name") or cust.get("first_name") or "Affiliated customer",
                "status": "active" if aff["status"] == "active" else aff["status"],
                "policy_count": len(cust_policies),
                "premium_basis": premium_basis,
                "commission_rate": aff["commission_rate"],
                "expected_commission": expected,
                "accrued_commission": accrued,
                "initial_term_commission": initial_accrued,
                "renewal_commission": renewal_accrued,
                "renewal_periods": renewal_periods,
                # The locked-rate check compares the initial-term accrual with
                # premium_basis × rate; renewal terms add on top (recurring).
                "commission_consistent": _money_eq(expected, initial_accrued),
                "referring_agent_id": referring,
                "referral_consistent": referring == aff["agent_id"],
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
            "renewal_events": len([c for c in comms
                                   if (c.get("period") or INITIAL_TERM) != INITIAL_TERM]),
            "payouts_calculated": len([p for p in PAYOUTS.values() if p["status"] == "calculated"]),
            "payouts_settled": len([p for p in PAYOUTS.values() if p["status"] == "settled"]),
            "payouts_settled_total": round(sum(float(p.get("gross_amount") or 0.0)
                                                for p in PAYOUTS.values()
                                                if p["status"] == "settled"), 2),
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


# ---------------------------------------------------------------------------
# Payout runs (§C ``agent_payouts``): calculated -> settled
# ---------------------------------------------------------------------------
def _commissions_hash(commission_ids: List[str]) -> str:
    """Content address of the exact accrual set a payout run settles."""
    return hashlib.sha256("\n".join(sorted(str(c) for c in commission_ids)).encode("utf-8")).hexdigest()


def _payout_ledger_payload(pay: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "payout_id": pay.get("id"),
        "agent_id": pay.get("agent_id"),
        "commission_count": pay.get("commission_count"),
        "commissions_hash": pay.get("commissions_hash"),
        "gross_amount": pay.get("gross_amount"),
        "currency": pay.get("currency"),
        "period_start": pay.get("period_start"),
        "period_end": pay.get("period_end"),
        "idempotency_key": pay.get("idempotency_key"),
    }


def _platform_ledger_fallback() -> Any:
    """The portal's platform event ledger when the server module is loaded (DB mode)."""
    if not _db_enabled():
        return None
    try:
        from web_portal.server import platform_event_ledger
        return platform_event_ledger
    except Exception:
        return None


def _find_payout_by_key(idempotency_key: Optional[str]) -> Optional[Dict[str, Any]]:
    if not idempotency_key:
        return None
    for pay in PAYOUTS.values():
        if pay.get("idempotency_key") == idempotency_key:
            return pay
    return None


def run_payouts(agent_id: Optional[str] = None, *, created_by: str = "admin",
                idempotency_key: Optional[str] = None) -> Dict[str, Any]:
    """Sweep ``accrued`` commissions into one payout run per agent.

    Idempotent three ways: (1) a caller ``idempotency_key`` seen before returns
    the run it created without touching anything; (2) swept commissions move
    to ``payable`` so a repeated run finds nothing new; (3) each run is content
    addressed by ``commissions_hash``. Commission amounts are copied, never
    edited. Suspended agents are skipped (their accruals stay ``accrued`` for
    admin review). Returns ``{"payouts": [...], "created": n, "reused": bool}``.
    """
    idempotency_key = (str(idempotency_key).strip() or None) if idempotency_key else None
    with _LOCK:
        _hydrate_from_db(force=True)
        existing = _find_payout_by_key(idempotency_key)
        if existing is not None:
            return {"payouts": [dict(existing)], "created": 0, "reused": True,
                    "skipped_agents": [], "ledger_intact": verify_ledger_integrity()}

        by_agent: Dict[str, List[Dict[str, Any]]] = {}
        for comm in COMMISSIONS.values():
            if comm.get("status") != "accrued" or comm.get("payout_id"):
                continue
            if agent_id and comm.get("agent_id") != agent_id:
                continue
            by_agent.setdefault(comm["agent_id"], []).append(comm)

        payouts: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        for aid in sorted(by_agent):
            comms = sorted(by_agent[aid], key=lambda c: (c.get("created_at") or "", c["id"]))
            agent = AGENTS.get(aid)
            if agent is None or agent.get("status") == "suspended":
                skipped.append({"agent_id": aid, "reason": "agent_suspended" if agent else "unknown_agent",
                                "commission_count": len(comms)})
                continue
            ids = [c["id"] for c in comms]
            gross = round(sum(float(c.get("amount") or 0.0) for c in comms), 2)
            if gross <= 0:
                skipped.append({"agent_id": aid, "reason": "zero_amount", "commission_count": len(comms)})
                continue
            now = _now_iso()
            pay = {
                "id": _gen_id("APAY"),
                "agent_id": aid,
                "status": "calculated",
                "currency": comms[0].get("currency") or "USD",
                "gross_amount": gross,
                "commission_count": len(ids),
                "commission_ids": ids,
                "commissions_hash": _commissions_hash(ids),
                # Only the first run created for a request carries the caller key.
                "idempotency_key": idempotency_key if not payouts else None,
                "period_start": comms[0].get("created_at"),
                "period_end": comms[-1].get("created_at"),
                "created_by": created_by,
                "settled_by": None,
                "settled_at": None,
                "external_payout_reference": None,
                "ledger_entry_id": None,
                "platform_ledger_entry_id": None,
                "platform_entry_hash": None,
                "created_at": now,
                "updated_at": now,
            }
            entry = _ledger_append("agent.payout.calculated", aid, gross, _payout_ledger_payload(pay))
            pay["ledger_entry_id"] = entry["id"]
            PAYOUTS[pay["id"]] = pay
            for comm in comms:
                comm["status"] = "payable"
                comm["payout_id"] = pay["id"]
                comm["updated_at"] = now
                _persist("commission", comm)
            _persist("payout", pay)
            payouts.append(dict(pay))
        return {"payouts": payouts, "created": len(payouts), "reused": False,
                "skipped_agents": skipped, "ledger_intact": verify_ledger_integrity()}


def _verify_payout_set(pay: Dict[str, Any]) -> Optional[str]:
    """Return a reason string when a payout run's swept set is not settleable."""
    ids = list(pay.get("commission_ids") or [])
    if not ids:
        return "payout has no commissions"
    if _commissions_hash(ids) != pay.get("commissions_hash"):
        return "commissions_hash does not match the swept commission ids"
    total = 0.0
    for cid in ids:
        comm = COMMISSIONS.get(cid)
        if comm is None:
            return f"commission {cid} not found"
        if comm.get("agent_id") != pay.get("agent_id"):
            return f"commission {cid} belongs to a different agent"
        if comm.get("payout_id") != pay.get("id"):
            return f"commission {cid} is not linked to this payout"
        if comm.get("status") != "payable":
            return f"commission {cid} is {comm.get('status')}, expected payable"
        row_expected = round(float(comm.get("base_amount") or 0.0) * float(comm.get("rate") or 0.0), 2)
        if not _money_eq(row_expected, comm.get("amount")):
            return f"commission {cid} amount does not equal base_amount × rate"
        total += float(comm.get("amount") or 0.0)
    if not _money_eq(total, pay.get("gross_amount")):
        return "gross_amount does not equal the sum of swept commissions"
    if not verify_ledger_integrity():
        return "commission ledger hash chain is broken"
    return None


def settle_payout(payout_id: str, *, settled_by: str = "admin",
                   external_payout_reference: Optional[str] = None,
                   platform_ledger: Any = None) -> Tuple[bool, Any]:
    """Settle a ``calculated`` payout run: commissions -> ``paid``, run -> ``settled``.

    Ledger-anchored and fail-closed: the swept set is re-verified (existence,
    ownership, linkage, ``payable`` status, per-row arithmetic, run total, hash
    chain) and the platform-ledger anchor is written *before* any status moves;
    if the anchor write raises, nothing changes. Idempotent: settling an
    already-settled run returns it unchanged (``already_settled``). Like
    ``supplier_settlement_service.execute_settlement_run`` this records the
    external payout reference; it never calls a payment rail itself.
    """
    with _LOCK:
        _hydrate_from_db(force=True)
        pay = PAYOUTS.get(payout_id)
        if pay is None:
            return False, "Payout not found"
        if pay.get("status") == "settled":
            return True, {**pay, "already_settled": True}
        if pay.get("status") != "calculated":
            return False, f"Payout is {pay.get('status')}; only calculated runs can be settled"
        problem = _verify_payout_set(pay)
        if problem:
            return False, f"Payout integrity check failed: {problem}"

        now = _now_iso()
        ledger = platform_ledger if platform_ledger is not None else _platform_ledger_fallback()
        anchor_id = anchor_hash = None
        if ledger is not None:
            # Deterministic entry id: append_event is idempotent on it, so a
            # retried settlement re-uses the same anchor instead of a duplicate.
            anchored = ledger.append_event(
                event_type="agent.payout.settled",
                entity_type="agent_payout",
                entity_id=pay["id"],
                actor=settled_by,
                amount=float(pay.get("gross_amount") or 0.0),
                currency=pay.get("currency") or "USD",
                payload={**_payout_ledger_payload(pay),
                         "external_payout_reference": external_payout_reference,
                         "settled_by": settled_by},
                entry_id=f"AGPAY-{pay['id']}",
            )
            anchor_id = anchored.get("id")
            anchor_hash = anchored.get("entry_hash")

        pay["status"] = "settled"
        pay["settled_by"] = settled_by
        pay["settled_at"] = now
        pay["external_payout_reference"] = external_payout_reference
        pay["platform_ledger_entry_id"] = anchor_id
        pay["platform_entry_hash"] = anchor_hash
        pay["updated_at"] = now
        _ledger_append("agent.payout.settled", pay["agent_id"], pay["gross_amount"],
                       {**_payout_ledger_payload(pay),
                        "external_payout_reference": external_payout_reference,
                        "platform_ledger_entry_id": anchor_id},
                       mirror=False)
        for cid in pay["commission_ids"]:
            comm = COMMISSIONS[cid]
            comm["status"] = "paid"
            comm["paid_at"] = now
            comm["updated_at"] = now
            _persist("commission", comm)
        _persist("payout", pay)
        return True, dict(pay)


def list_payouts(agent_id: Optional[str] = None,
                 status: Optional[str] = None) -> List[Dict[str, Any]]:
    with _LOCK:
        _hydrate_from_db()
        items = list(PAYOUTS.values())
        if agent_id:
            items = [p for p in items if p["agent_id"] == agent_id]
        if status:
            items = [p for p in items if p["status"] == status]
        return sorted((dict(p) for p in items), key=lambda p: p.get("created_at", ""), reverse=True)


def get_payout(payout_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        _hydrate_from_db()
        pay = PAYOUTS.get(payout_id)
        return dict(pay) if pay else None


# ---------------------------------------------------------------------------
# Broker funnel (§C): invitations -> affiliations -> policies -> premium -> payout
# ---------------------------------------------------------------------------
def _pct(num: int, den: int) -> float:
    return round(num / den * 100.0, 2) if den else 0.0


def _subtree_customer_ids(agent_id: str) -> List[str]:
    return [a["principal_id"] for a in AFFILIATIONS.values()
            if a["agent_id"] == agent_id and a["principal_type"] == "customer"
            and a["status"] == "active"]


def _subtree_bi(customer_ids: List[str], customers: Dict[str, Any], policies: Dict[str, Any],
                health_wallets: Optional[Dict[str, Any]], investment_accounts: Optional[Dict[str, Any]],
                transaction_ledger: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """BI customer analytics restricted to the agent's affiliated customers.

    Aggregates only: the per-customer ``top_customers`` block is dropped so the
    funnel never exposes another principal's balances (PII-minimized like the
    customer outline).
    """
    try:
        from services.bi_analytics_service import get_bi_analytics_service
    except Exception:
        return None
    ids = set(customer_ids)
    sub_customers = {cid: c for cid, c in (customers or {}).items() if cid in ids}
    sub_policies = {pid: p for pid, p in (policies or {}).items()
                    if isinstance(p, dict) and p.get("customer_id") in ids}
    sub_wallets = {cid: w for cid, w in (health_wallets or {}).items() if cid in ids}
    sub_investments = {cid: a for cid, a in (investment_accounts or {}).items() if cid in ids}
    sub_tx = {tid: tx for tid, tx in (transaction_ledger or {}).items()
              if isinstance(tx, dict) and tx.get("customer_id") in ids}
    try:
        analytics = get_bi_analytics_service().get_customer_analytics(
            sub_customers, sub_wallets, sub_investments, sub_tx, sub_policies)
    except Exception:
        return None
    return {k: v for k, v in (analytics or {}).items() if k != "top_customers"}


def agent_funnel(agent_id: str, customers: Dict[str, Any], policies: Dict[str, Any],
                 bills: Optional[Dict[str, Any]] = None,
                 health_wallets: Optional[Dict[str, Any]] = None,
                 investment_accounts: Optional[Dict[str, Any]] = None,
                 transaction_ledger: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Conversion funnel for one agent, computed only from that agent's subtree.

    Stages: invitations created -> approved -> redeemed -> affiliated customers
    -> customers with active policies -> customers paying premium -> customers
    renewed, plus money totals (accrued / payable / paid). Cross-agent isolation:
    every stage filters on this agent's invitations, affiliations and
    commissions; the BI block runs over the subtree only.
    """
    with _LOCK:
        _hydrate_from_db()
        invs = [i for i in INVITATIONS.values() if i["agent_id"] == agent_id]
        approved = [i for i in invs if i["status"] in ("approved", "sent", "accepted")]
        redeemed = [i for i in invs if int(i.get("used_count") or 0) > 0 or i["status"] == "accepted"]
        customer_ids = _subtree_customer_ids(agent_id)
        cust_set = set(customer_ids)
        active_policies = [p for p in (policies or {}).values()
                           if isinstance(p, dict) and p.get("customer_id") in cust_set
                           and _policy_drives_commission(p)]
        with_policy = {p["customer_id"] for p in active_policies}
        paying = {b.get("customer_id") for b in (bills or {}).values()
                  if isinstance(b, dict) and b.get("customer_id") in cust_set
                  and (b.get("status") or "").lower() == "paid"}
        comms = [c for c in COMMISSIONS.values() if c["agent_id"] == agent_id]
        aff_by_id = {a["id"]: a for a in AFFILIATIONS.values() if a["agent_id"] == agent_id}
        renewed = {aff_by_id[c["affiliation_id"]]["principal_id"] for c in comms
                   if (c.get("period") or INITIAL_TERM) != INITIAL_TERM
                   and c["affiliation_id"] in aff_by_id}
        pays = [p for p in PAYOUTS.values() if p["agent_id"] == agent_id]

        def total(status: Optional[str] = None) -> float:
            return round(sum(float(c.get("amount") or 0.0) for c in comms
                             if status is None or c["status"] == status), 2)

        premium_basis = round(sum(float(p.get("annual_premium") or p.get("premium") or 0)
                                  for p in active_policies), 2)
        stages = [
            {"stage": "invitations_created", "count": len(invs)},
            {"stage": "invitations_approved", "count": len(approved)},
            {"stage": "invitations_redeemed", "count": len(redeemed)},
            {"stage": "affiliated_customers", "count": len(customer_ids)},
            {"stage": "customers_with_policy", "count": len(with_policy)},
            {"stage": "customers_paying", "count": len(paying & with_policy)},
            {"stage": "customers_renewed", "count": len(renewed)},
        ]
        for idx, stage in enumerate(stages):
            prev = stages[idx - 1]["count"] if idx else stage["count"]
            stage["conversion_pct"] = _pct(stage["count"], prev) if idx else 100.0
        return {
            "agent_id": agent_id,
            "currency": "USD",
            "stages": stages,
            "invitations": {
                "created": len(invs),
                "pending_approval": len([i for i in invs if i["status"] == "pending_approval"]),
                "approved": len(approved),
                "rejected": len([i for i in invs if i["status"] == "rejected"]),
                "redeemed": len(redeemed),
            },
            "network": {
                "affiliated_customers": len(customer_ids),
                "customers_with_policy": len(with_policy),
                "customers_paying": len(paying & with_policy),
                "customers_renewed": len(renewed),
                "active_policies": len(active_policies),
                "premium_basis": premium_basis,
            },
            "commission": {
                "accrued_total": total("accrued"),
                "payable_total": total("payable"),
                "paid_total": total("paid"),
                "lifetime_total": total(),
                "renewal_total": round(sum(float(c.get("amount") or 0.0) for c in comms
                                           if (c.get("period") or INITIAL_TERM) != INITIAL_TERM), 2),
                "events": len(comms),
            },
            "payouts": {
                "calculated": len([p for p in pays if p["status"] == "calculated"]),
                "settled": len([p for p in pays if p["status"] == "settled"]),
                "settled_total": round(sum(float(p.get("gross_amount") or 0.0)
                                            for p in pays if p["status"] == "settled"), 2),
            },
            "bi": _subtree_bi(customer_ids, customers or {}, policies or {},
                              health_wallets, investment_accounts, transaction_ledger),
        }


def _money_eq(left: Any, right: Any, tolerance: float = 0.015) -> bool:
    """Compare currency amounts with a 1.5-cent tolerance."""
    try:
        return abs(float(left or 0.0) - float(right or 0.0)) < tolerance
    except (TypeError, ValueError):
        return False


def _split_terms(comms: List[Dict[str, Any]]) -> Tuple[float, float, int]:
    """(initial-term accrued, renewal accrued, distinct renewal periods) for one affiliation."""
    initial = renewal = 0.0
    periods: set = set()
    for c in comms:
        period = c.get("period") or INITIAL_TERM
        amount = float(c.get("amount") or 0.0)
        if period == INITIAL_TERM:
            initial += amount
        else:
            renewal += amount
            periods.add(period)
    return round(initial, 2), round(renewal, 2), len(periods)


def _rate_eq(left: Any, right: Any) -> bool:
    """Compare locked commission rates at the same precision as ``normalize_rate``."""
    try:
        return round(float(left or 0.0), 6) == round(float(right or 0.0), 6)
    except (TypeError, ValueError):
        return False


def _principal_record(customers: Optional[Dict[str, Any]],
                      suppliers: Optional[Dict[str, Any]],
                      principal_type: str, principal_id: str) -> Dict[str, Any]:
    if principal_type == "customer":
        return ((customers or {}).get(principal_id) or {})
    if principal_type == "supplier":
        return ((suppliers or {}).get(principal_id) or {})
    return {}


def connection_integrity(customers: Optional[Dict[str, Any]] = None,
                         policies: Optional[Dict[str, Any]] = None,
                         suppliers: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Audit agent↔principal affiliation, referral FK, and commission consistency.

    Read-only. Flags (never silently repairs) any break in the locked-rate
    chain: one active affiliation per principal, ``referring_agent_id`` matching
    that affiliation, invitation rate snapshot matching the affiliation, and
    accrued commission matching ``premium_basis × locked_rate``.
    """
    with _LOCK:
        _hydrate_from_db()
        issues: List[Dict[str, Any]] = []
        connections: List[Dict[str, Any]] = []
        customers = customers or {}
        policies = policies or {}
        suppliers = suppliers or {}

        def _issue(severity: str, code: str, message: str, **extra: Any) -> None:
            row = {"severity": severity, "code": code, "message": message}
            row.update(extra)
            issues.append(row)

        # 1) At most one active affiliation per principal.
        active_keys: Dict[Tuple[str, str], List[str]] = {}
        for aff in AFFILIATIONS.values():
            if aff.get("status") != "active":
                continue
            key = (aff.get("principal_type"), aff.get("principal_id"))
            active_keys.setdefault(key, []).append(aff.get("id"))
        for (ptype, pid), ids in active_keys.items():
            if len(ids) > 1:
                _issue("error", "duplicate_active_affiliation",
                       "Principal has more than one active affiliation",
                       principal_type=ptype, principal_id=pid, affiliation_ids=ids)

        # 2) Per-affiliation locked-rate + referral + commission checks.
        for aff in AFFILIATIONS.values():
            ptype = aff.get("principal_type")
            pid = aff.get("principal_id")
            rec = _principal_record(customers, suppliers, ptype, pid)
            referring = rec.get("referring_agent_id")
            rate = float(aff.get("commission_rate") or 0.0)
            inv = _find_invitation(aff.get("source_invitation_code") or "")
            invitation_rate = inv.get("commission_rate") if inv else None
            rate_locked_ok = True
            if inv is not None and invitation_rate is not None:
                rate_locked_ok = _rate_eq(rate, invitation_rate)
                if not rate_locked_ok:
                    _issue("error", "rate_lock_drift",
                           "Affiliation rate does not match the invitation locked rate",
                           affiliation_id=aff.get("id"), agent_id=aff.get("agent_id"),
                           principal_type=ptype, principal_id=pid,
                           affiliation_rate=rate, invitation_rate=invitation_rate,
                           invitation_code=aff.get("source_invitation_code"))

            if aff.get("agent_id") not in AGENTS:
                _issue("error", "unknown_agent",
                       "Affiliation points at an unknown agent",
                       affiliation_id=aff.get("id"), agent_id=aff.get("agent_id"),
                       principal_type=ptype, principal_id=pid)

            if ptype in ("customer", "supplier"):
                if not rec:
                    _issue("warning", "missing_principal_record",
                           "Affiliated principal is not in the live register",
                           affiliation_id=aff.get("id"), agent_id=aff.get("agent_id"),
                           principal_type=ptype, principal_id=pid)
                elif referring != aff.get("agent_id"):
                    if not referring:
                        _issue("error", "missing_referring_agent",
                               "Active affiliation has no referring_agent_id on the principal",
                               affiliation_id=aff.get("id"), agent_id=aff.get("agent_id"),
                               principal_type=ptype, principal_id=pid)
                    else:
                        _issue("error", "referring_agent_mismatch",
                               "Principal referring_agent_id does not match the active affiliation",
                               affiliation_id=aff.get("id"), agent_id=aff.get("agent_id"),
                               referring_agent_id=referring,
                               principal_type=ptype, principal_id=pid)

            aff_comms = [c for c in COMMISSIONS.values() if c.get("affiliation_id") == aff.get("id")]
            for comm in aff_comms:
                if comm.get("agent_id") != aff.get("agent_id"):
                    _issue("error", "commission_agent_mismatch",
                           "Commission agent_id does not match the affiliation",
                           affiliation_id=aff.get("id"), commission_id=comm.get("id"),
                           agent_id=aff.get("agent_id"), commission_agent_id=comm.get("agent_id"))
                if not _rate_eq(comm.get("rate"), rate):
                    _issue("error", "commission_rate_drift",
                           "Commission rate does not match the locked affiliation rate",
                           affiliation_id=aff.get("id"), commission_id=comm.get("id"),
                           agent_id=aff.get("agent_id"),
                           affiliation_rate=rate, commission_rate=comm.get("rate"))
                # Every row (initial or renewal) must equal its own base × rate.
                row_expected = round(float(comm.get("base_amount") or 0.0) * float(comm.get("rate") or 0.0), 2)
                if not _money_eq(row_expected, comm.get("amount")):
                    _issue("error", "commission_amount_mismatch",
                           "Commission amount does not equal base_amount × rate",
                           affiliation_id=aff.get("id"), commission_id=comm.get("id"),
                           agent_id=aff.get("agent_id"), period=comm.get("period") or INITIAL_TERM,
                           expected=row_expected, amount=comm.get("amount"))
                pay_id = comm.get("payout_id")
                if pay_id and pay_id not in PAYOUTS:
                    _issue("error", "commission_orphan_payout",
                           "Commission references a payout run that does not exist",
                           affiliation_id=aff.get("id"), commission_id=comm.get("id"),
                           agent_id=aff.get("agent_id"), payout_id=pay_id)
                elif comm.get("status") in ("payable", "paid") and not pay_id:
                    _issue("error", "commission_status_without_payout",
                           "Commission is payable/paid but was never swept into a payout run",
                           affiliation_id=aff.get("id"), commission_id=comm.get("id"),
                           agent_id=aff.get("agent_id"), status=comm.get("status"))

            premium_basis = 0.0
            policy_count = 0
            if ptype == "customer":
                cust_policies = [p for p in policies.values()
                                 if p.get("customer_id") == pid and _policy_drives_commission(p)]
                policy_count = len(cust_policies)
                premium_basis = round(sum(
                    float(p.get("annual_premium") or p.get("premium") or 0)
                    for p in cust_policies), 2)
            accrued = round(sum(float(c.get("amount") or 0) for c in aff_comms), 2)
            initial_accrued, renewal_accrued, renewal_periods = _split_terms(aff_comms)
            is_premium = (aff.get("commission_basis") or "premium") == "premium"
            expected = round(premium_basis * rate, 2) if is_premium else initial_accrued
            # Locked-rate consistency is judged on the initial term; renewal terms
            # are recurring add-ons validated row-by-row above.
            commission_ok = _money_eq(expected, initial_accrued)
            if aff.get("status") == "active" and ptype == "customer" and not commission_ok:
                agent = AGENTS.get(aff.get("agent_id") or "")
                if initial_accrued > expected + 0.015:
                    _issue("error", "commission_overage",
                           "Initial-term accrued commission exceeds premium_basis × locked rate",
                           affiliation_id=aff.get("id"), agent_id=aff.get("agent_id"),
                           principal_id=pid, expected=expected, accrued=initial_accrued)
                elif agent and agent.get("status") == "suspended":
                    _issue("warning", "suspended_agent_shortfall",
                           "Suspended agent has not accrued the full expected commission",
                           affiliation_id=aff.get("id"), agent_id=aff.get("agent_id"),
                           principal_id=pid, expected=expected, accrued=initial_accrued)
                else:
                    _issue("warning", "commission_shortfall",
                           "Initial-term accrued commission is below premium_basis × locked rate",
                           affiliation_id=aff.get("id"), agent_id=aff.get("agent_id"),
                           principal_id=pid, expected=expected, accrued=initial_accrued)

            if ptype == "customer":
                connections.append({
                    "affiliation_id": aff.get("id"),
                    "agent_id": aff.get("agent_id"),
                    "customer_id": pid,
                    "customer_name": rec.get("name") or rec.get("first_name") or "Affiliated customer",
                    "status": aff.get("status"),
                    "invitation_code": aff.get("source_invitation_code"),
                    "locked_rate": rate,
                    "invitation_rate": invitation_rate,
                    "rate_locked_consistent": rate_locked_ok,
                    "policy_count": policy_count,
                    "premium_basis": premium_basis,
                    "expected_commission": expected,
                    "accrued_commission": accrued,
                    "initial_term_commission": initial_accrued,
                    "renewal_commission": renewal_accrued,
                    "renewal_periods": renewal_periods,
                    "commission_consistent": commission_ok,
                    "referring_agent_id": referring,
                    "referral_consistent": referring == aff.get("agent_id"),
                })

        # 2b) Payout runs: every swept commission must exist, belong to the run's
        # agent, carry the run's id, and the run total must equal their sum.
        for pay in PAYOUTS.values():
            ids = list(pay.get("commission_ids") or [])
            total = 0.0
            for cid in ids:
                comm = COMMISSIONS.get(cid)
                if comm is None:
                    _issue("error", "payout_missing_commission",
                           "Payout run references a commission that does not exist",
                           payout_id=pay.get("id"), agent_id=pay.get("agent_id"), commission_id=cid)
                    continue
                total += float(comm.get("amount") or 0.0)
                if comm.get("agent_id") != pay.get("agent_id"):
                    _issue("error", "payout_agent_mismatch",
                           "Payout run sweeps a commission of a different agent",
                           payout_id=pay.get("id"), agent_id=pay.get("agent_id"),
                           commission_id=cid, commission_agent_id=comm.get("agent_id"))
                if comm.get("payout_id") != pay.get("id"):
                    _issue("error", "payout_link_drift",
                           "Swept commission does not point back at its payout run",
                           payout_id=pay.get("id"), commission_id=cid,
                           commission_payout_id=comm.get("payout_id"))
                expected_status = "paid" if pay.get("status") == "settled" else "payable"
                if comm.get("status") != expected_status:
                    _issue("error", "payout_status_drift",
                           "Swept commission status does not match its payout run status",
                           payout_id=pay.get("id"), commission_id=cid,
                           payout_status=pay.get("status"), commission_status=comm.get("status"))
            if not _money_eq(total, pay.get("gross_amount")):
                _issue("error", "payout_total_mismatch",
                       "Payout run gross_amount does not equal the sum of swept commissions",
                       payout_id=pay.get("id"), agent_id=pay.get("agent_id"),
                       gross_amount=pay.get("gross_amount"), commissions_total=round(total, 2))
            if _commissions_hash(ids) != pay.get("commissions_hash"):
                _issue("error", "payout_hash_mismatch",
                       "Payout run commissions_hash does not match its commission ids",
                       payout_id=pay.get("id"), agent_id=pay.get("agent_id"))

        # 3) Orphan referring_agent_id (principal claims an agent with no affiliation).
        for cid, rec in customers.items():
            if not isinstance(rec, dict):
                continue
            referring = rec.get("referring_agent_id")
            if not referring:
                continue
            key = ("customer", cid)
            aid = _ACTIVE_AFFIL.get(key)
            aff = AFFILIATIONS.get(aid) if aid else None
            if not aff:
                _issue("error", "orphan_referring_agent",
                       "Customer referring_agent_id has no matching active affiliation",
                       principal_type="customer", principal_id=cid,
                       referring_agent_id=referring)
        for sid, rec in suppliers.items():
            if not isinstance(rec, dict):
                continue
            referring = rec.get("referring_agent_id")
            if not referring:
                continue
            key = ("supplier", sid)
            aid = _ACTIVE_AFFIL.get(key)
            aff = AFFILIATIONS.get(aid) if aid else None
            if not aff:
                _issue("error", "orphan_referring_agent",
                       "Supplier referring_agent_id has no matching active affiliation",
                       principal_type="supplier", principal_id=sid,
                       referring_agent_id=referring)

        errors = len([i for i in issues if i["severity"] == "error"])
        warnings = len([i for i in issues if i["severity"] == "warning"])
        connections.sort(key=lambda r: (r.get("agent_id") or "", r.get("customer_id") or ""))
        return {
            "ok": errors == 0 and verify_ledger_integrity(),
            "ledger_intact": verify_ledger_integrity(),
            "checked": {
                "affiliations": len(AFFILIATIONS),
                "customers": len(customers),
                "suppliers": len(suppliers),
                "commissions": len(COMMISSIONS),
                "payouts": len(PAYOUTS),
                "connections": len(connections),
            },
            "issue_counts": {"error": errors, "warning": warnings, "total": len(issues)},
            "issues": issues,
            "connections": connections,
            "currency": "USD",
        }


def repair_referring_links(customers: Optional[Dict[str, Any]] = None,
                           suppliers: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Fill missing ``referring_agent_id`` from active affiliations.

    Conservative: never overwrites a conflicting FK (those stay as integrity
    errors for an operator to resolve). Mutates the in-memory principal
    records in place and mirrors to durable tables when DB mode is on.
    """
    with _LOCK:
        _hydrate_from_db(force=True)
        repaired: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        customers = customers or {}
        suppliers = suppliers or {}

        for aff in AFFILIATIONS.values():
            if aff.get("status") != "active":
                continue
            ptype = aff.get("principal_type")
            pid = aff.get("principal_id")
            agent_id = aff.get("agent_id")
            rec = _principal_record(customers, suppliers, ptype, pid)
            if not rec or not agent_id:
                continue
            current = rec.get("referring_agent_id")
            if current == agent_id:
                continue
            if current:
                skipped.append({
                    "principal_type": ptype, "principal_id": pid,
                    "affiliation_id": aff.get("id"),
                    "agent_id": agent_id, "referring_agent_id": current,
                    "reason": "conflicting referring_agent_id left unchanged",
                })
                continue
            rec["referring_agent_id"] = agent_id
            persist_referring_agent(ptype, pid, agent_id)
            repaired.append({
                "principal_type": ptype, "principal_id": pid,
                "affiliation_id": aff.get("id"), "agent_id": agent_id,
            })

        return {
            "repaired": len(repaired),
            "skipped": len(skipped),
            "items": repaired,
            "conflicts": skipped,
        }
