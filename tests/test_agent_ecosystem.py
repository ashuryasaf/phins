"""
Tests for the agent/broker ecosystem ("AgentOS").

Covers:
  * service logic: admin-locked commission, single-active-affiliation integrity,
    idempotent ledger-backed accrual, income summary, PII-minimized outline
  * HTTP API: agent + admin role scope, invitation lifecycle, recompute
  * DB repositories: durable schema round-trips
"""

import json
import os

import pytest

from urllib.request import urlopen, Request
from urllib.error import HTTPError

import web_portal.server as portal
from services import agent_ecosystem_service as svc


BASE = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _post(path, payload, token=None):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(BASE + path, data=data, headers=headers)
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except HTTPError as e:
        return json.loads(e.read().decode("utf-8")), e.code


def _get(path, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(BASE + path, headers=headers)
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except HTTPError as e:
        return json.loads(e.read().decode("utf-8")), e.code


def _login(username, password):
    body, status = _post("/api/login", {"username": username, "password": password})
    assert status == 200, f"login failed for {username}: {body}"
    return body["token"], body.get("role")


@pytest.fixture(autouse=True)
def _reset():
    svc.reset_agent_ecosystem()
    yield
    svc.reset_agent_ecosystem()


# ---------------------------------------------------------------------------
# service-level logic
# ---------------------------------------------------------------------------
def test_invitation_requires_admin_locked_rate_before_redeem():
    agent = svc.create_agent("agent", "Demo Agent", default_rate=0.10, created_by="admin")
    ok, inv = svc.create_invitation(agent["id"], "customer", "lead@example.com", proposed_rate=0.2)
    assert ok and inv["status"] == "pending_approval"
    assert inv["commission_rate"] is None  # not yet locked

    # cannot redeem before approval
    ok2, err = svc.redeem_invitation(inv["code"], "customer", "CUST-1")
    assert ok2 is False

    # admin locks rate in advance
    ok3, inv2 = svc.approve_invitation(inv["code"], 0.15, admin="admin")
    assert ok3 and inv2["commission_rate"] == 0.15 and inv2["status"] == "approved"

    ok4, aff = svc.redeem_invitation(inv["code"], "customer", "CUST-1")
    assert ok4 and aff["commission_rate"] == 0.15  # locked snapshot


def test_percentage_rates_are_normalized():
    assert svc.normalize_rate(25) == 0.25
    assert svc.normalize_rate(0.25) == 0.25
    assert svc.normalize_rate(1) == 0.01  # 1% percent input, not a 100% fraction
    assert svc.normalize_rate(150) == 1.0
    assert svc.normalize_rate(-5) == 0.0


def test_single_active_affiliation_per_principal():
    agent = svc.create_agent("agent", default_rate=0.1, created_by="admin")
    _, inv1 = svc.create_invitation(agent["id"], "customer", proposed_rate=0.1)
    svc.approve_invitation(inv1["code"], 0.1, "admin")
    ok, _ = svc.redeem_invitation(inv1["code"], "customer", "CUST-9")
    assert ok

    # a second invitation cannot create a 2nd active affiliation for same principal
    _, inv2 = svc.create_invitation(agent["id"], "customer", proposed_rate=0.2)
    svc.approve_invitation(inv2["code"], 0.2, "admin")
    ok2, err = svc.redeem_invitation(inv2["code"], "customer", "CUST-9")
    assert ok2 is False and "active" in err.lower()


def test_commission_accrual_is_idempotent_and_ledger_intact():
    agent = svc.create_agent("agent", default_rate=0.1, created_by="admin")
    _, inv = svc.create_invitation(agent["id"], "customer", proposed_rate=0.1)
    svc.approve_invitation(inv["code"], 0.10, "admin")
    svc.redeem_invitation(inv["code"], "customer", "CUST-7")

    policies = {"POL-1": {"id": "POL-1", "customer_id": "CUST-7", "annual_premium": 1000}}
    created1 = svc.recompute_commissions(policies)
    created2 = svc.recompute_commissions(policies)  # idempotent
    assert created1 == 1 and created2 == 0

    comms = svc.list_commissions(agent_id=agent["id"])
    assert len(comms) == 1
    assert comms[0]["amount"] == 100.0  # 1000 * 0.10
    assert svc.verify_ledger_integrity() is True


def test_no_commission_without_affiliation():
    svc.create_agent("agent", default_rate=0.1, created_by="admin")
    policies = {"POL-X": {"id": "POL-X", "customer_id": "CUST-UNAFFILIATED", "annual_premium": 5000}}
    assert svc.recompute_commissions(policies) == 0


def test_income_summary_and_pii_minimized_outline():
    agent = svc.create_agent("agent", default_rate=0.1, created_by="admin")
    _, inv = svc.create_invitation(agent["id"], "customer", proposed_rate=0.1)
    svc.approve_invitation(inv["code"], 0.10, "admin")
    svc.redeem_invitation(inv["code"], "customer", "CUST-5")

    customers = {"CUST-5": {"id": "CUST-5", "name": "Dana Levi", "dob": "1980-01-01",
                            "address": "secret st", "email": "dana@example.com"}}
    policies = {"POL-5": {"id": "POL-5", "customer_id": "CUST-5", "annual_premium": 2000}}
    svc.recompute_commissions(policies)

    summary = svc.income_summary(agent["id"])
    assert summary["accrued_total"] == 200.0
    assert summary["counts"]["affiliated_customers"] == 1

    outline = svc.network_customers(agent["id"], customers, policies)
    assert outline["total"] == 1
    row = outline["items"][0]
    assert row["customer_id"] == "CUST-5"
    assert row["accrued_commission"] == 200.0
    # PII must NOT leak into the agent-facing outline
    assert "dob" not in row and "address" not in row and "email" not in row


# ---------------------------------------------------------------------------
# HTTP API + role scope
# ---------------------------------------------------------------------------
def test_http_agent_invitation_admin_approval_and_income_flow():
    agent_token, agent_role = _login("agent", "agent123")
    assert agent_role == "agent"
    admin_token, _ = _login("admin", "admin123")

    # agent creates an invitation -> pending approval
    body, status = _post("/api/agent/invitations", {
        "invitee_type": "customer", "invitee_email": "prospect@example.com",
        "proposed_rate": 0.2,
    }, token=agent_token)
    assert status == 201, body
    code = body["invitation"]["code"]
    assert body["invitation"]["status"] == "pending_approval"

    # agent must NOT be able to use admin endpoints
    _, st_forbidden = _get("/api/admin/agents", token=agent_token)
    assert st_forbidden == 403

    # admin approves and locks the commission rate in advance
    body, status = _post("/api/admin/agent-invitations/approve",
                         {"code": code, "commission_rate": 0.15}, token=admin_token)
    assert status == 200 and body["invitation"]["commission_rate"] == 0.15

    # set up an affiliated customer + policy in the in-memory portal store
    portal.CUSTOMERS["CUST-HTTP-1"] = {"id": "CUST-HTTP-1", "name": "HTTP Customer"}
    portal.POLICIES["POL-HTTP-1"] = {"id": "POL-HTTP-1", "customer_id": "CUST-HTTP-1",
                                     "annual_premium": 1200, "status": "active"}

    # admin redeems on behalf -> affiliation + referring_agent_id linkage
    body, status = _post("/api/admin/agent-invitations/redeem",
                         {"code": code, "principal_type": "customer",
                          "principal_id": "CUST-HTTP-1"}, token=admin_token)
    assert status == 200, body
    assert portal.CUSTOMERS["CUST-HTTP-1"].get("referring_agent_id")

    # admin recomputes commissions from the policy book
    body, status = _post("/api/admin/agents/recompute-commissions", {}, token=admin_token)
    assert status == 200 and body["created"] >= 1 and body["ledger_intact"] is True

    # agent income summary reflects the accrued commission (1200 * 0.15 = 180)
    body, status = _get("/api/agent/income/summary", token=agent_token)
    assert status == 200 and body["accrued_total"] == 180.0


def test_http_validate_invitation_public():
    agent = svc.create_agent("agent", default_rate=0.1, created_by="admin")
    _, inv = svc.create_invitation(agent["id"], "customer", proposed_rate=0.1)
    # before approval -> not active
    body, status = _get(f"/api/agent-invitations/validate?code={inv['code']}")
    assert status == 200 and body["valid"] is False
    svc.approve_invitation(inv["code"], 0.1, "admin")
    body, status = _get(f"/api/agent-invitations/validate?code={inv['code']}")
    assert status == 200 and body["valid"] is True


def test_http_requires_auth():
    _, status = _get("/api/agent/income/summary")
    assert status in (401, 403)


def test_community_overview_aggregate_and_integrity():
    agent = svc.create_agent("agent", default_rate=0.1, created_by="admin")
    _, inv = svc.create_invitation(agent["id"], "customer", proposed_rate=0.1)
    svc.approve_invitation(inv["code"], 0.10, "admin")
    svc.redeem_invitation(inv["code"], "customer", "CUST-OV")
    svc.recompute_commissions({"POL-OV": {"id": "POL-OV", "customer_id": "CUST-OV", "annual_premium": 1000}})

    o = svc.community_overview()
    assert o["agents_total"] >= 1
    assert o["affiliated_customers"] == 1
    assert o["commission_lifetime_total"] == 100.0
    assert o["ledger_intact"] is True


def test_http_admin_community_endpoints():
    admin_token, _ = _login("admin", "admin123")
    agent_token, _ = _login("agent", "agent123")

    # agent creates + admin approves + redeems, then recompute
    body, _ = _post("/api/agent/invitations",
                    {"invitee_type": "customer", "proposed_rate": 0.2}, token=agent_token)
    code = body["invitation"]["code"]
    _post("/api/admin/agent-invitations/approve", {"code": code, "commission_rate": 0.1}, token=admin_token)
    portal.CUSTOMERS["CUST-COMM-1"] = {"id": "CUST-COMM-1", "name": "Comm Customer"}
    portal.POLICIES["POL-COMM-1"] = {"id": "POL-COMM-1", "customer_id": "CUST-COMM-1", "annual_premium": 1000}
    _post("/api/admin/agent-invitations/redeem",
          {"code": code, "principal_type": "customer", "principal_id": "CUST-COMM-1"}, token=admin_token)

    # overview reflects the community and confirms ledger integrity
    ov, status = _get("/api/admin/agents/overview", token=admin_token)
    assert status == 200 and ov["agents_total"] >= 1 and ov["ledger_intact"] is True
    assert ov["commission_lifetime_total"] >= 100.0

    # per-agent network (admin drill) + ledger audit are admin-only
    me, _ = _get("/api/agent/me", token=agent_token)
    aid = me["agent"]["id"]
    net, status = _get(f"/api/admin/agents/network?agent_id={aid}", token=admin_token)
    assert status == 200 and net["total"] >= 1
    led, status = _get("/api/admin/agents/ledger", token=admin_token)
    assert status == 200 and led["ledger_intact"] is True and len(led["items"]) >= 1

    # an agent cannot reach the admin community endpoints
    _, st = _get("/api/admin/agents/overview", token=agent_token)
    assert st == 403


# ---------------------------------------------------------------------------
# Persistence hardening: DB source-of-truth, restart durability, cross-instance
# ---------------------------------------------------------------------------
def _wipe_inmemory_cache():
    """Simulate a fresh process/instance: drop the in-memory cache only (not DB)."""
    svc.AGENTS.clear(); svc.AGENT_BY_USER.clear(); svc.INVITATIONS.clear()
    svc.AFFILIATIONS.clear(); svc.COMMISSIONS.clear(); svc.COMMISSION_LEDGER.clear()
    svc._ACTIVE_AFFIL.clear(); svc._ACCRUED_KEYS.clear()
    svc._last_hydrate = 0.0


def test_db_mode_durability_survives_restart(monkeypatch):
    from database import init_database
    monkeypatch.setattr(svc, "_db_enabled", lambda: True)
    init_database()
    svc.reset_agent_ecosystem()

    agent = svc.create_agent("dbagent", "DB Agent", default_rate=10, created_by="admin")
    ok, inv = svc.create_invitation(agent["id"], "customer", proposed_rate=20)
    assert ok
    svc.approve_invitation(inv["code"], 15, "admin")  # lock 15%
    ok, _ = svc.redeem_invitation(inv["code"], "customer", "CUST-DUR-1")
    assert ok
    svc.recompute_commissions({"POL-DUR": {"id": "POL-DUR", "customer_id": "CUST-DUR-1",
                                           "annual_premium": 1000, "status": "active"}})
    assert svc.income_summary(agent["id"])["accrued_total"] == 150.0  # 1000 * 0.15

    # Simulate a restart / brand-new instance: only the in-memory cache is wiped.
    _wipe_inmemory_cache()

    # Reads re-pull from the durable tables — the data survived.
    assert any(a["id"] == agent["id"] for a in svc.list_agents())
    assert svc.income_summary(agent["id"])["accrued_total"] == 150.0
    assert svc.verify_ledger_integrity() is True

    # Idempotent: recompute after "restart" does not double-accrue.
    created = svc.recompute_commissions({"POL-DUR": {"id": "POL-DUR", "customer_id": "CUST-DUR-1",
                                                     "annual_premium": 1000, "status": "active"}})
    assert created == 0
    assert svc.income_summary(agent["id"])["accrued_total"] == 150.0


def test_db_mode_hydration_preserves_lifecycle_events(monkeypatch):
    """Invitation/affiliation lifecycle events must survive refresh-on-read.

    Regression: a refresh-on-read full cache replace rebuilds the ledger from
    durable state. The rebuild must reconstruct the non-accrual lifecycle events
    (invitation created/approved, affiliation created) and not just accruals,
    otherwise periodic hydration silently erases audit history.
    """
    from database import init_database
    monkeypatch.setattr(svc, "_db_enabled", lambda: True)
    init_database()
    svc.reset_agent_ecosystem()

    agent = svc.create_agent("lifeagent", "Life Agent", default_rate=10, created_by="admin")
    ok, inv = svc.create_invitation(agent["id"], "customer", proposed_rate=20)
    assert ok
    svc.approve_invitation(inv["code"], 15, "admin")
    ok, _ = svc.redeem_invitation(inv["code"], "customer", "CUST-LIFE-1")
    assert ok

    # Simulate a fresh instance / TTL-elapsed read: only the cache is wiped.
    _wipe_inmemory_cache()
    svc._hydrate_from_db(force=True)

    event_types = {e["event_type"] for e in svc.COMMISSION_LEDGER}
    assert "agent.invitation.created" in event_types
    assert "agent.invitation.approved" in event_types
    assert "agent.affiliation.created" in event_types
    assert svc.verify_ledger_integrity() is True


def test_db_mode_cross_instance_visibility(monkeypatch):
    from database import init_database
    from database.manager import DatabaseManager
    monkeypatch.setattr(svc, "_db_enabled", lambda: True)
    init_database()
    svc.reset_agent_ecosystem()

    # A peer instance writes a new agent straight to the shared database.
    with DatabaseManager() as db:
        db.agents.create(id="AGT-PEER", user_username="peeragent", display_name="Peer Agent",
                         status="active", default_commission_rate=0.05, created_by="admin")

    # This instance (cold cache) sees the peer's agent via refresh-on-read.
    peer = svc.get_agent_by_username("peeragent")
    assert peer is not None and peer["id"] == "AGT-PEER"

    # A peer suspends the agent; a forced refresh on the next decision reflects it.
    with DatabaseManager() as db:
        db.agents.update("AGT-PEER", status="suspended")
    svc._last_hydrate = 0.0  # allow immediate refresh (bypass TTL coalescing)
    ok, err = svc.create_invitation("AGT-PEER", "customer", proposed_rate=10)
    assert ok is False and "not active" in err.lower()


# ---------------------------------------------------------------------------
# DB repositories (durable schema round-trip)
# ---------------------------------------------------------------------------
def test_db_repositories_round_trip():
    from database import init_database
    from database.manager import DatabaseManager

    init_database()
    with DatabaseManager() as db:
        agent = db.agents.create(id="AGT-DBTEST", user_username="dbagent",
                                 display_name="DB Agent", status="active",
                                 default_commission_rate=0.12, created_by="admin")
        assert agent is not None
        fetched = db.agents.get_by_username("dbagent")
        assert fetched is not None and fetched.id == "AGT-DBTEST"

        inv = db.agent_invitations.create(code="AGI-DBTEST", agent_id="AGT-DBTEST",
                                          invitee_type="customer", status="approved",
                                          commission_rate=0.12, created_at="now")
        assert inv is not None
        assert len(db.agent_invitations.list_by_status("approved")) >= 1
