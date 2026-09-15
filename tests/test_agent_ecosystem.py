"""
Tests for the agent/broker ecosystem ("AgentOS").

Covers:
  * service logic: admin-locked commission, single-active-affiliation integrity,
    idempotent ledger-backed accrual, income summary, PII-minimized outline
  * agent↔customer referral/commission consistency audit + conservative repair
  * HTTP API: agent + admin role scope, invitation lifecycle, recompute
  * registration with an approved AGI- code creating a locked affiliation
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
    assert row["expected_commission"] == 200.0
    assert row["commission_consistent"] is True
    assert row["referral_consistent"] is False  # customer record has no referring_agent_id yet
    # PII must NOT leak into the agent-facing outline
    assert "dob" not in row and "address" not in row and "email" not in row


def test_connection_integrity_and_referral_repair():
    agent = svc.create_agent("agent", default_rate=0.1, created_by="admin")
    _, inv = svc.create_invitation(agent["id"], "customer", proposed_rate=0.1)
    svc.approve_invitation(inv["code"], 0.10, "admin")
    svc.redeem_invitation(inv["code"], "customer", "CUST-INT")
    customers = {"CUST-INT": {"id": "CUST-INT", "name": "Ira"}}
    policies = {"POL-INT": {"id": "POL-INT", "customer_id": "CUST-INT",
                            "annual_premium": 1000, "status": "active"}}
    svc.recompute_commissions(policies)

    audit = svc.connection_integrity(customers, policies)
    assert audit["ledger_intact"] is True
    assert any(i["code"] == "missing_referring_agent" for i in audit["issues"])
    conn = next(c for c in audit["connections"] if c["customer_id"] == "CUST-INT")
    assert conn["expected_commission"] == 100.0
    assert conn["accrued_commission"] == 100.0
    assert conn["commission_consistent"] is True
    assert conn["referral_consistent"] is False

    repaired = svc.repair_referring_links(customers)
    assert repaired["repaired"] == 1
    assert customers["CUST-INT"]["referring_agent_id"] == agent["id"]
    audit2 = svc.connection_integrity(customers, policies)
    assert audit2["ok"] is True
    assert audit2["issue_counts"]["error"] == 0

    customers["CUST-INT"]["referring_agent_id"] = "AGT-OTHER"
    skipped = svc.repair_referring_links(customers)
    assert skipped["repaired"] == 0 and skipped["skipped"] == 1
    assert customers["CUST-INT"]["referring_agent_id"] == "AGT-OTHER"
    audit3 = svc.connection_integrity(customers, policies)
    assert any(i["code"] == "referring_agent_mismatch" for i in audit3["issues"])


def test_default_rate_change_does_not_move_locked_affiliation():
    agent = svc.create_agent("agent", default_rate=0.10, created_by="admin")
    _, inv = svc.create_invitation(agent["id"], "customer", proposed_rate=0.10)
    svc.approve_invitation(inv["code"], 0.10, "admin")
    svc.redeem_invitation(inv["code"], "customer", "CUST-LOCK")
    svc.update_agent(agent["id"], default_rate=0.25)
    customers = {"CUST-LOCK": {"id": "CUST-LOCK", "name": "Locked",
                               "referring_agent_id": agent["id"]}}
    policies = {"POL-LOCK": {"id": "POL-LOCK", "customer_id": "CUST-LOCK",
                             "annual_premium": 1000, "status": "active"}}
    svc.recompute_commissions(policies)
    outline = svc.network_customers(agent["id"], customers, policies)
    row = outline["items"][0]
    assert row["commission_rate"] == 0.10
    assert row["expected_commission"] == 100.0
    assert row["accrued_commission"] == 100.0
    assert row["commission_consistent"] is True
    assert row["referral_consistent"] is True


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


def test_http_admin_reset_agent_password():
    admin_token, _ = _login("admin", "admin123")
    agent_token, _ = _login("agent", "agent123")
    # provision the demo agent profile and resolve its id
    me, _ = _get("/api/agent/me", token=agent_token)
    aid = me["agent"]["id"]

    # auto-generated password
    body, status = _post("/api/admin/agents/reset-password", {"agent_id": aid}, token=admin_token)
    assert status == 200 and body["success"] is True
    assert body.get("temporary_password") and len(body["temporary_password"]) >= 8

    # explicit new password → agent can then log in with it
    body, status = _post("/api/admin/agents/reset-password",
                         {"agent_id": aid, "new_password": "BrandNewPass1"}, token=admin_token)
    assert status == 200 and "temporary_password" not in body
    relogin, st = _post("/api/login", {"username": "agent", "password": "BrandNewPass1"})
    assert st == 200 and relogin["role"] == "agent"

    # non-admin cannot reset
    _, st = _post("/api/admin/agents/reset-password", {"agent_id": aid}, token=agent_token)
    assert st == 403

    # cannot reset a non-agent account (no agent profile) via this endpoint
    _, st = _post("/api/admin/agents/reset-password", {"username": "admin"}, token=admin_token)
    assert st == 404


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


def test_http_admin_integrity_and_repair():
    admin_token, _ = _login("admin", "admin123")
    agent_token, _ = _login("agent", "agent123")

    body, _ = _post("/api/agent/invitations",
                    {"invitee_type": "customer", "proposed_rate": 0.2}, token=agent_token)
    code = body["invitation"]["code"]
    _post("/api/admin/agent-invitations/approve",
          {"code": code, "commission_rate": 0.1}, token=admin_token)
    portal.CUSTOMERS["CUST-INT-1"] = {"id": "CUST-INT-1", "name": "Integrity Customer"}
    portal.POLICIES["POL-INT-1"] = {
        "id": "POL-INT-1", "customer_id": "CUST-INT-1",
        "annual_premium": 1000, "status": "active",
    }
    body, status = _post("/api/admin/agent-invitations/redeem",
                         {"code": code, "principal_type": "customer",
                          "principal_id": "CUST-INT-1"}, token=admin_token)
    assert status == 200, body
    assert portal.CUSTOMERS["CUST-INT-1"].get("referring_agent_id")

    audit, status = _get("/api/admin/agents/integrity", token=admin_token)
    assert status == 200 and audit["ledger_intact"] is True
    assert audit["ok"] is True
    conn = next(c for c in audit["connections"] if c["customer_id"] == "CUST-INT-1")
    assert conn["referral_consistent"] is True
    assert conn["commission_consistent"] is True
    assert conn["expected_commission"] == 100.0
    assert conn["locked_rate"] == 0.1

    # missing FK is restored without touching a conflicting one
    portal.CUSTOMERS["CUST-INT-1"].pop("referring_agent_id", None)
    repaired, status = _post("/api/admin/agents/repair-referrals", {}, token=admin_token)
    assert status == 200 and repaired["repaired"] >= 1
    assert portal.CUSTOMERS["CUST-INT-1"].get("referring_agent_id")

    _, st = _get("/api/admin/agents/integrity", token=agent_token)
    assert st == 403


def test_register_with_agent_invitation_creates_affiliation():
    agent = svc.create_agent("agent", default_rate=0.1, created_by="admin")
    _, inv = svc.create_invitation(agent["id"], "customer", proposed_rate=0.1)
    svc.approve_invitation(inv["code"], 0.12, "admin")

    valid, status = _get(f"/api/invitations/validate?code={inv['code'].upper()}")
    assert status == 200 and valid.get("valid") is True, valid
    assert valid.get("type") == "agent"
    assert valid.get("referrer_id") == agent["id"]

    body, status = _post("/api/register", {
        "name": "Agent Referred",
        "email": "agentref-integrity@example.com",
        "password": "secure123456",
        "invitation_code": inv["code"],
    })
    assert status == 201, body
    cid = body["customer_id"]
    assert portal.CUSTOMERS[cid]["referring_agent_id"] == agent["id"]
    aff = svc.get_active_affiliation("customer", cid)
    assert aff is not None
    assert aff["agent_id"] == agent["id"]
    assert aff["commission_rate"] == 0.12


# ---------------------------------------------------------------------------
# §C — per-renewal recurring commission (keyed on affiliation, event, period)
# ---------------------------------------------------------------------------
def _affiliate(customer_id, rate=0.10, username="agent"):
    agent = svc.get_agent_by_username(username) or svc.create_agent(
        username, "Agent", default_rate=rate, created_by="admin")
    _, inv = svc.create_invitation(agent["id"], "customer", proposed_rate=rate)
    svc.approve_invitation(inv["code"], rate, "admin")
    ok, aff = svc.redeem_invitation(inv["code"], "customer", customer_id)
    assert ok, aff
    return agent, aff


def _bill(bill_id, policy_id, customer_id, period_start, status="paid", amount=100.0):
    return {"id": bill_id, "policy_id": policy_id, "customer_id": customer_id,
            "amount": amount, "amount_paid": amount if status == "paid" else 0.0,
            "status": status, "billing_period_start": period_start,
            "due_date": period_start, "paid_date": period_start if status == "paid" else None}


class _FakePlatformLedger:
    """Minimal stand-in for PlatformEventLedgerService: idempotent on entry_id."""

    def __init__(self):
        self.transaction_ledger = {}
        self.calls = 0

    def append_event(self, **kw):
        self.calls += 1
        entry_id = kw["entry_id"]
        if entry_id in self.transaction_ledger:
            return self.transaction_ledger[entry_id]
        entry = {"id": entry_id, "entry_hash": f"hash-{entry_id}", **kw}
        self.transaction_ledger[entry_id] = entry
        return entry


def test_renewal_accrues_once_per_term_never_twice():
    agent, aff = _affiliate("CUST-REN")
    policies = {"POL-REN": {"id": "POL-REN", "customer_id": "CUST-REN", "annual_premium": 1200,
                            "status": "active", "start_date": "2024-03-15T00:00:00"}}
    bills = {
        # initial term (covered by the once-per-policy accrual)
        "B-1": _bill("B-1", "POL-REN", "CUST-REN", "2024-04-01T00:00:00"),
        "B-2": _bill("B-2", "POL-REN", "CUST-REN", "2025-03-14T00:00:00"),
        # second term: two paid bills -> ONE renewal accrual
        "B-3": _bill("B-3", "POL-REN", "CUST-REN", "2025-03-15T00:00:00"),
        "B-4": _bill("B-4", "POL-REN", "CUST-REN", "2025-09-01T00:00:00"),
        # third term: unpaid bill must not accrue
        "B-5": _bill("B-5", "POL-REN", "CUST-REN", "2026-03-15T00:00:00", status="outstanding"),
    }
    created1 = svc.recompute_commissions(policies, bills)
    created2 = svc.recompute_commissions(policies, bills)
    assert created1 == 2 and created2 == 0  # initial + one renewal, idempotent

    comms = {c["source_event_id"]: c for c in svc.list_commissions(agent_id=agent["id"])}
    assert set(comms) == {"policy:POL-REN", "policy:POL-REN:2025-03-15"}
    assert comms["policy:POL-REN"]["period"] == svc.INITIAL_TERM
    renewal = comms["policy:POL-REN:2025-03-15"]
    assert renewal["period"] == "2025-03-15" and renewal["source_type"] == "policy_renewal"
    assert renewal["amount"] == 120.0  # annual premium × locked rate, per term
    assert (renewal["source_event_id"], aff["id"], "2025-03-15") in svc._ACCRUED_KEYS

    # the unpaid third-term bill accrues only once it is actually paid
    bills["B-5"]["status"] = "paid"
    assert svc.recompute_commissions(policies, bills) == 1
    assert svc.recompute_commissions(policies, bills) == 0
    summary = svc.income_summary(agent["id"])
    assert summary["lifetime_total"] == 360.0 and summary["renewal_total"] == 240.0
    assert summary["counts"]["renewal_events"] == 2
    assert svc.verify_ledger_integrity() is True


def test_renewal_never_accrues_without_a_policy_start_date_or_paid_status():
    agent, _ = _affiliate("CUST-NOSTART")
    policies = {"POL-NS": {"id": "POL-NS", "customer_id": "CUST-NOSTART",
                           "annual_premium": 1000, "status": "active"}}  # no dates at all
    bills = {"B": _bill("B", "POL-NS", "CUST-NOSTART", "2030-01-01T00:00:00")}
    assert svc.recompute_commissions(policies, bills) == 1  # only the initial term
    assert svc.renewal_period_for_bill(policies["POL-NS"], bills["B"]) is None
    # an unpaid bill in a later term of a dated policy is ignored by the hook
    policy = {"id": "POL-D", "customer_id": "CUST-NOSTART", "annual_premium": 1000,
              "status": "active", "start_date": "2020-01-01"}
    assert svc.accrue_for_paid_bill(_bill("X", "POL-D", "CUST-NOSTART", "2022-06-01", status="outstanding"), policy) is None
    # a bill for a different policy id than the one passed is refused
    assert svc.accrue_for_paid_bill(_bill("Y", "POL-OTHER", "CUST-NOSTART", "2022-06-01"), policy) is None
    assert svc.income_summary(agent["id"])["lifetime_total"] == 100.0


def test_renewal_terms_follow_policy_anniversary_not_calendar_year():
    policy = {"id": "P", "customer_id": "C", "start_date": "2024-02-29T10:00:00"}
    assert svc.renewal_period_for_bill(policy, {"billing_period_start": "2025-02-27"}) is None
    assert svc.renewal_period_for_bill(policy, {"billing_period_start": "2025-02-28"}) == "2025-02-28"
    assert svc.renewal_period_for_bill(policy, {"billing_period_start": "2026-01-01"}) == "2025-02-28"
    assert svc.renewal_period_for_bill(policy, {"billing_period_start": "2028-03-01"}) == "2028-02-29"
    assert svc.renewal_period_for_bill(policy, {"due_date": "2023-01-01"}) is None  # before start


def test_integrity_treats_renewals_as_recurring_add_ons():
    agent, _ = _affiliate("CUST-INTREN")
    customers = {"CUST-INTREN": {"id": "CUST-INTREN", "name": "R", "referring_agent_id": agent["id"]}}
    policies = {"POL-IR": {"id": "POL-IR", "customer_id": "CUST-INTREN", "annual_premium": 1000,
                           "status": "active", "start_date": "2023-01-01"}}
    bills = {"B": _bill("B", "POL-IR", "CUST-INTREN", "2024-01-01")}
    svc.recompute_commissions(policies, bills)
    audit = svc.connection_integrity(customers, policies)
    assert audit["ok"] is True and audit["issue_counts"]["error"] == 0, audit["issues"]
    conn = audit["connections"][0]
    assert conn["expected_commission"] == 100.0
    assert conn["initial_term_commission"] == 100.0
    assert conn["renewal_commission"] == 100.0 and conn["renewal_periods"] == 1
    assert conn["accrued_commission"] == 200.0
    assert conn["commission_consistent"] is True
    outline = svc.network_customers(agent["id"], customers, policies)["items"][0]
    assert outline["commission_consistent"] is True and outline["renewal_periods"] == 1

    # a tampered renewal row is caught row-by-row
    renewal = next(c for c in svc.COMMISSIONS.values() if c["period"])
    renewal["amount"] = 999.0
    audit2 = svc.connection_integrity(customers, policies)
    assert any(i["code"] == "commission_amount_mismatch" for i in audit2["issues"])


def test_billing_hook_on_premium_payment_accrues_renewal_term():
    """The shared premium-payment flow drives per-renewal accrual for paid bills."""
    agent, _ = _affiliate("CUST-PAYHOOK")
    portal.CUSTOMERS["CUST-PAYHOOK"] = {"id": "CUST-PAYHOOK", "name": "Hook", "referring_agent_id": agent["id"]}
    portal.POLICIES["POL-HOOK"] = {"id": "POL-HOOK", "customer_id": "CUST-PAYHOOK", "annual_premium": 1200,
                                   "status": "active", "start_date": "2020-05-01T00:00:00"}
    portal.BILLING["BILL-HOOK-1"] = _bill("BILL-HOOK-1", "POL-HOOK", "CUST-PAYHOOK",
                                          "2021-05-01T00:00:00", status="outstanding")
    portal.process_customer_premium_payment("CUST-PAYHOOK", 100.0, "card", policy_id="POL-HOOK",
                                            specific_bill_ids=["BILL-HOOK-1"], allocate_to_investments=False)
    assert portal.BILLING["BILL-HOOK-1"]["status"] == "paid"
    comms = {c["source_event_id"]: c for c in svc.list_commissions(agent_id=agent["id"])}
    assert "policy:POL-HOOK" in comms  # initial term guaranteed by the hook
    assert comms["policy:POL-HOOK:2021-05-01"]["amount"] == 120.0
    # paying again in the same term does not re-accrue
    portal.BILLING["BILL-HOOK-2"] = _bill("BILL-HOOK-2", "POL-HOOK", "CUST-PAYHOOK",
                                          "2021-11-01T00:00:00", status="outstanding")
    portal.process_customer_premium_payment("CUST-PAYHOOK", 100.0, "card", policy_id="POL-HOOK",
                                            specific_bill_ids=["BILL-HOOK-2"], allocate_to_investments=False)
    assert len(svc.list_commissions(agent_id=agent["id"])) == 2


# ---------------------------------------------------------------------------
# §C — payout runs (agent_payouts): idempotent, fail-closed, ledger-anchored
# ---------------------------------------------------------------------------
def test_payout_run_is_idempotent_and_settlement_is_ledger_anchored():
    agent, _ = _affiliate("CUST-PAY")
    policies = {"POL-PAY": {"id": "POL-PAY", "customer_id": "CUST-PAY", "annual_premium": 1000,
                            "status": "active", "start_date": "2022-01-01"}}
    bills = {"B": _bill("B", "POL-PAY", "CUST-PAY", "2023-01-01")}
    svc.recompute_commissions(policies, bills)
    assert svc.income_summary(agent["id"])["accrued_total"] == 200.0

    run = svc.run_payouts(created_by="admin", idempotency_key="run-1")
    assert run["created"] == 1 and run["reused"] is False and run["ledger_intact"] is True
    pay = run["payouts"][0]
    assert pay["status"] == "calculated" and pay["gross_amount"] == 200.0 and pay["commission_count"] == 2
    assert pay["commissions_hash"] == svc._commissions_hash(pay["commission_ids"])
    assert all(svc.COMMISSIONS[c]["status"] == "payable" and svc.COMMISSIONS[c]["payout_id"] == pay["id"]
               for c in pay["commission_ids"])
    summary = svc.income_summary(agent["id"])
    assert summary["accrued_total"] == 0 and summary["payable_total"] == 200.0

    # same idempotency key -> the same run, nothing new; no key -> nothing accrued left
    again = svc.run_payouts(created_by="admin", idempotency_key="run-1")
    assert again["reused"] is True and again["created"] == 0 and again["payouts"][0]["id"] == pay["id"]
    assert svc.run_payouts(created_by="admin")["created"] == 0
    assert len(svc.list_payouts(agent_id=agent["id"])) == 1

    ledger = _FakePlatformLedger()
    ok, settled = svc.settle_payout(pay["id"], settled_by="admin",
                                      external_payout_reference="WIRE-77", platform_ledger=ledger)
    assert ok, settled
    assert settled["status"] == "settled" and settled["external_payout_reference"] == "WIRE-77"
    assert settled["platform_ledger_entry_id"] == f"AGPAY-{pay['id']}"
    anchor = ledger.transaction_ledger[f"AGPAY-{pay['id']}"]
    assert anchor["event_type"] == "agent.payout.settled" and anchor["amount"] == 200.0
    assert anchor["payload"]["commissions_hash"] == pay["commissions_hash"]
    assert all(svc.COMMISSIONS[c]["status"] == "paid" and svc.COMMISSIONS[c]["paid_at"]
               for c in pay["commission_ids"])
    assert svc.income_summary(agent["id"])["paid_total"] == 200.0

    # settling twice is a no-op that returns the same run (no second anchor)
    ok2, twice = svc.settle_payout(pay["id"], settled_by="admin", platform_ledger=ledger)
    assert ok2 and twice["already_settled"] is True and ledger.calls == 1
    events = [e["event_type"] for e in svc.get_ledger(agent_id=agent["id"])]
    assert events.count("agent.payout.calculated") == 1 and events.count("agent.payout.settled") == 1
    assert svc.verify_ledger_integrity() is True
    audit = svc.connection_integrity({"CUST-PAY": {"id": "CUST-PAY", "referring_agent_id": agent["id"]}}, policies)
    assert audit["ok"] is True and audit["checked"]["payouts"] == 1, audit["issues"]


def test_payout_settle_fails_closed_when_swept_set_is_tampered():
    agent, _ = _affiliate("CUST-TAMPER")
    svc.recompute_commissions({"POL-T": {"id": "POL-T", "customer_id": "CUST-TAMPER",
                                         "annual_premium": 1000, "status": "active"}})
    pay = svc.run_payouts(created_by="admin")["payouts"][0]
    comm = svc.COMMISSIONS[pay["commission_ids"][0]]
    comm["amount"] = 5000.0  # tamper after the sweep
    ledger = _FakePlatformLedger()
    ok, err = svc.settle_payout(pay["id"], settled_by="admin", platform_ledger=ledger)
    assert ok is False and "integrity check failed" in err
    assert ledger.calls == 0  # nothing anchored, nothing moved
    assert svc.get_payout(pay["id"])["status"] == "calculated" and comm["status"] == "payable"
    audit = svc.connection_integrity({}, {})
    assert any(i["code"] == "payout_total_mismatch" for i in audit["issues"])
    assert any(i["code"] == "commission_amount_mismatch" for i in audit["issues"])
    # unknown / wrong-state runs are refused too
    assert svc.settle_payout("APAY-NOPE", settled_by="admin")[0] is False


def test_payout_settle_fails_closed_when_anchor_write_fails():
    agent, _ = _affiliate("CUST-ANCHOR")
    svc.recompute_commissions({"POL-A": {"id": "POL-A", "customer_id": "CUST-ANCHOR",
                                         "annual_premium": 500, "status": "active"}})
    pay = svc.run_payouts(created_by="admin")["payouts"][0]

    class _Broken:
        def append_event(self, **kw):
            raise RuntimeError("ledger down")

    with pytest.raises(RuntimeError):
        svc.settle_payout(pay["id"], settled_by="admin", platform_ledger=_Broken())
    assert svc.get_payout(pay["id"])["status"] == "calculated"
    assert all(svc.COMMISSIONS[c]["status"] == "payable" for c in pay["commission_ids"])
    assert svc.verify_ledger_integrity() is True


def test_payout_run_skips_suspended_agents_and_scopes_by_agent():
    a1, _ = _affiliate("CUST-S1", username="agent")
    a2, _ = _affiliate("CUST-S2", username="agent2")
    svc.recompute_commissions({
        "P1": {"id": "P1", "customer_id": "CUST-S1", "annual_premium": 1000, "status": "active"},
        "P2": {"id": "P2", "customer_id": "CUST-S2", "annual_premium": 2000, "status": "active"},
    })
    svc.update_agent(a2["id"], status="suspended")
    run = svc.run_payouts(created_by="admin")
    assert run["created"] == 1 and run["payouts"][0]["agent_id"] == a1["id"]
    assert run["skipped_agents"] == [{"agent_id": a2["id"], "reason": "agent_suspended", "commission_count": 1}]
    assert svc.income_summary(a2["id"])["accrued_total"] == 200.0  # untouched, still accrued
    svc.update_agent(a2["id"], status="active")
    scoped = svc.run_payouts(agent_id=a2["id"], created_by="admin")
    assert scoped["created"] == 1 and scoped["payouts"][0]["gross_amount"] == 200.0
    assert [p["agent_id"] for p in svc.list_payouts(status="calculated")].count(a1["id"]) == 1


# ---------------------------------------------------------------------------
# §C — broker funnel: agent subtree only
# ---------------------------------------------------------------------------
def test_funnel_is_scoped_to_the_agents_own_subtree():
    a1, _ = _affiliate("CUST-F1", username="agent")
    _affiliate("CUST-F2", username="agent")
    a2, _ = _affiliate("CUST-G1", username="agent2")
    svc.create_invitation(a1["id"], "customer", proposed_rate=0.1)  # pending, never approved
    customers = {
        "CUST-F1": {"id": "CUST-F1", "name": "F1", "dob": "1970-01-01", "email": "f1@x"},
        "CUST-F2": {"id": "CUST-F2", "name": "F2"},
        "CUST-G1": {"id": "CUST-G1", "name": "G1"},
    }
    policies = {
        "PF1": {"id": "PF1", "customer_id": "CUST-F1", "annual_premium": 1000, "status": "active", "start_date": "2022-01-01"},
        "PG1": {"id": "PG1", "customer_id": "CUST-G1", "annual_premium": 9000, "status": "active", "start_date": "2022-01-01"},
    }
    bills = {
        "BF": _bill("BF", "PF1", "CUST-F1", "2023-02-01"),   # renewal for agent 1
        "BG": _bill("BG", "PG1", "CUST-G1", "2023-02-01"),   # renewal for agent 2
    }
    svc.recompute_commissions(policies, bills)
    wallets = {"CUST-F1": {"balance": 50.0}, "CUST-G1": {"balance": 9999.0}}
    tx = {"T1": {"customer_id": "CUST-G1", "amount": 9999.0}}

    f1 = svc.agent_funnel(a1["id"], customers, policies, bills, health_wallets=wallets,
                          investment_accounts={}, transaction_ledger=tx)
    stages = {s["stage"]: s["count"] for s in f1["stages"]}
    assert stages == {"invitations_created": 3, "invitations_approved": 2, "invitations_redeemed": 2,
                      "affiliated_customers": 2, "customers_with_policy": 1,
                      "customers_paying": 1, "customers_renewed": 1}
    assert f1["invitations"]["pending_approval"] == 1
    assert f1["network"]["premium_basis"] == 1000.0
    assert f1["commission"]["lifetime_total"] == 200.0 and f1["commission"]["renewal_total"] == 100.0
    # BI block is subtree-only and aggregate-only (no per-customer rows, no PII)
    assert f1["bi"]["summary"]["total_customers"] == 2
    assert f1["bi"]["wallet_analytics"]["total_balance"] == 50.0
    assert f1["bi"]["transaction_analytics"]["total_transactions"] == 0
    assert "top_customers" not in f1["bi"]
    assert "dob" not in json.dumps(f1) and "f1@x" not in json.dumps(f1)

    f2 = svc.agent_funnel(a2["id"], customers, policies, bills, health_wallets=wallets,
                          investment_accounts={}, transaction_ledger=tx)
    assert {s["stage"]: s["count"] for s in f2["stages"]}["affiliated_customers"] == 1
    assert f2["network"]["premium_basis"] == 9000.0 and f2["commission"]["lifetime_total"] == 1800.0
    assert f2["bi"]["wallet_analytics"]["total_balance"] == 9999.0

    # conversion percentages are relative to the previous stage
    conv = {s["stage"]: s["conversion_pct"] for s in f1["stages"]}
    assert conv["invitations_approved"] == 66.67 and conv["customers_with_policy"] == 50.0


def test_http_funnel_and_payout_routes_with_role_scope():
    admin_token, _ = _login("admin", "admin123")
    agent_token, _ = _login("agent", "agent123")
    me, _ = _get("/api/agent/me", token=agent_token)
    aid = me["agent"]["id"]

    body, _ = _post("/api/agent/invitations", {"invitee_type": "customer", "proposed_rate": 0.1}, token=agent_token)
    code = body["invitation"]["code"]
    _post("/api/admin/agent-invitations/approve", {"code": code, "commission_rate": 0.1}, token=admin_token)
    portal.CUSTOMERS["CUST-HF-1"] = {"id": "CUST-HF-1", "name": "Funnel Customer", "dob": "1980-01-01"}
    portal.POLICIES["POL-HF-1"] = {"id": "POL-HF-1", "customer_id": "CUST-HF-1", "annual_premium": 1000,
                                   "status": "active", "start_date": "2021-06-01"}
    portal.BILLING["BILL-HF-1"] = _bill("BILL-HF-1", "POL-HF-1", "CUST-HF-1", "2022-06-01")
    _post("/api/admin/agent-invitations/redeem",
          {"code": code, "principal_type": "customer", "principal_id": "CUST-HF-1"}, token=admin_token)

    # agent funnel: subtree, PII-free, renewal picked up from the paid bill book
    funnel, status = _get("/api/agent/funnel", token=agent_token)
    assert status == 200, funnel
    stages = {s["stage"]: s["count"] for s in funnel["stages"]}
    assert stages["affiliated_customers"] == 1 and stages["customers_renewed"] == 1
    assert funnel["commission"]["lifetime_total"] == 200.0 and "dob" not in json.dumps(funnel)
    assert funnel["payouts"] == {"calculated": 0, "settled": 0, "settled_total": 0.0}

    # role scope: agents cannot run or list admin payouts; admin cannot use agent routes
    assert _post("/api/admin/agents/payouts/run", {}, token=agent_token)[1] == 403
    assert _get("/api/admin/agents/payouts", token=agent_token)[1] == 403
    assert _get("/api/agent/funnel", token=admin_token)[1] == 403
    assert _get("/api/admin/agents/funnel", token=admin_token)[1] == 400  # agent_id required
    assert _get("/api/admin/agents/funnel?agent_id=AGT-NOPE", token=admin_token)[1] == 404
    assert _get("/api/admin/agents/payouts?status=bogus", token=admin_token)[1] == 400

    # admin sweeps accrued commissions (idempotent on the caller key)
    run, status = _post("/api/admin/agents/payouts/run", {"idempotency_key": "http-run-1"}, token=admin_token)
    assert status == 200 and run["created"] == 1, run
    pay = run["payouts"][0]
    assert pay["agent_id"] == aid and pay["gross_amount"] == 200.0 and pay["status"] == "calculated"
    rerun, _ = _post("/api/admin/agents/payouts/run", {"idempotency_key": "http-run-1"}, token=admin_token)
    assert rerun["reused"] is True and rerun["created"] == 0 and rerun["payouts"][0]["id"] == pay["id"]
    mine, _ = _get("/api/agent/payouts", token=agent_token)
    assert [p["id"] for p in mine["items"]] == [pay["id"]]
    admin_funnel, _ = _get(f"/api/admin/agents/funnel?agent_id={aid}", token=admin_token)
    assert admin_funnel["payouts"]["calculated"] == 1

    # settle: anchored on the portal's platform event ledger, idempotent on retry
    assert _post("/api/admin/agents/payouts/settle", {}, token=admin_token)[1] == 400
    assert _post("/api/admin/agents/payouts/settle", {"payout_id": "APAY-NOPE"}, token=admin_token)[1] == 404
    done, status = _post("/api/admin/agents/payouts/settle",
                         {"payout_id": pay["id"], "external_payout_reference": "WIRE-HTTP"}, token=admin_token)
    assert status == 200 and done["ledger_intact"] is True, done
    assert done["payout"]["status"] == "settled"
    anchor_id = done["payout"]["platform_ledger_entry_id"]
    assert anchor_id == f"AGPAY-{pay['id']}"
    anchor = portal.platform_event_ledger.transaction_ledger[anchor_id]
    assert anchor["event_type"] == "agent.payout.settled" and anchor["entry_hash"] == done["payout"]["platform_entry_hash"]
    again, status = _post("/api/admin/agents/payouts/settle", {"payout_id": pay["id"]}, token=admin_token)
    assert status == 200 and again["payout"]["already_settled"] is True
    listed, _ = _get("/api/admin/agents/payouts?status=settled", token=admin_token)
    assert [p["id"] for p in listed["items"]] == [pay["id"]]
    summary, _ = _get("/api/agent/income/summary", token=agent_token)
    assert summary["paid_total"] == 200.0 and summary["counts"]["payouts_settled"] == 1
    overview, _ = _get("/api/admin/agents/overview", token=admin_token)
    assert overview["payouts_settled"] >= 1 and overview["ledger_intact"] is True
    audit, _ = _get("/api/admin/agents/integrity", token=admin_token)
    assert audit["ledger_intact"] is True and audit["checked"]["payouts"] >= 1

    # run + settle in one call anchors immediately
    portal.BILLING["BILL-HF-2"] = _bill("BILL-HF-2", "POL-HF-1", "CUST-HF-1", "2023-06-01")
    combo, status = _post("/api/admin/agents/payouts/run",
                          {"settle": True, "external_payout_reference": "WIRE-COMBO"}, token=admin_token)
    assert status == 200 and combo["created"] == 1 and combo["settled"] == 1, combo
    assert combo["payouts"][0]["status"] == "settled" and combo["payouts"][0]["gross_amount"] == 100.0


# ---------------------------------------------------------------------------
# Persistence hardening: DB source-of-truth, restart durability, cross-instance
# ---------------------------------------------------------------------------
def _wipe_inmemory_cache():
    """Simulate a fresh process/instance: drop the in-memory cache only (not DB)."""
    svc.AGENTS.clear(); svc.AGENT_BY_USER.clear(); svc.INVITATIONS.clear()
    svc.AFFILIATIONS.clear(); svc.COMMISSIONS.clear(); svc.PAYOUTS.clear()
    svc.COMMISSION_LEDGER.clear()
    svc._ACTIVE_AFFIL.clear(); svc._ACCRUED_KEYS.clear()
    svc._last_hydrate = 0.0


def test_db_mode_renewals_and_payouts_survive_restart(monkeypatch):
    from database import init_database
    from database.manager import DatabaseManager
    monkeypatch.setattr(svc, "_db_enabled", lambda: True)
    init_database()
    svc.reset_agent_ecosystem()

    agent = svc.create_agent("dbpayagent", "DB Pay Agent", default_rate=10, created_by="admin")
    _, inv = svc.create_invitation(agent["id"], "customer", proposed_rate=10)
    svc.approve_invitation(inv["code"], 10, "admin")
    assert svc.redeem_invitation(inv["code"], "customer", "CUST-DBPAY")[0]
    policies = {"POL-DBPAY": {"id": "POL-DBPAY", "customer_id": "CUST-DBPAY", "annual_premium": 1000,
                              "status": "active", "start_date": "2022-01-01"}}
    bills = {"B": _bill("B", "POL-DBPAY", "CUST-DBPAY", "2023-01-01")}
    assert svc.recompute_commissions(policies, bills) == 2
    run = svc.run_payouts(created_by="admin", idempotency_key="db-run")
    pay = run["payouts"][0]
    ok, _ = svc.settle_payout(pay["id"], settled_by="admin", external_payout_reference="WIRE-DB",
                               platform_ledger=_FakePlatformLedger())
    assert ok

    with DatabaseManager() as db:
        rows = {r.source_event_id: r.to_dict() for r in db.agent_commissions.list_by_agent(agent["id"])}
        assert rows["policy:POL-DBPAY:2023-01-01"]["period"] == "2023-01-01"
        assert all(r["status"] == "paid" and r["payout_id"] == pay["id"] for r in rows.values())
        durable = db.agent_payouts.get_by_idempotency_key("db-run").to_dict()
        assert durable["status"] == "settled" and sorted(durable["commission_ids"]) == sorted(pay["commission_ids"])
        assert durable["platform_ledger_entry_id"] == f"AGPAY-{pay['id']}"

    _wipe_inmemory_cache()
    # A fresh instance sees the settled run, paid commissions and both renewal
    # and payout events on the rebuilt hash chain.
    assert svc.income_summary(agent["id"])["paid_total"] == 200.0
    assert svc.get_payout(pay["id"])["status"] == "settled"
    assert svc.recompute_commissions(policies, bills) == 0  # no re-accrual after restart
    assert svc.run_payouts(created_by="admin", idempotency_key="db-run")["reused"] is True
    assert svc.run_payouts(created_by="admin")["created"] == 0
    events = [e["event_type"] for e in svc.COMMISSION_LEDGER]
    assert "agent.payout.calculated" in events and "agent.payout.settled" in events
    assert svc.verify_ledger_integrity() is True
    audit = svc.connection_integrity({"CUST-DBPAY": {"id": "CUST-DBPAY", "referring_agent_id": agent["id"]}}, policies)
    assert audit["ok"] is True, audit["issues"]


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


def test_db_mode_payout_run_and_settlement_never_half_persist(monkeypatch):
    """A failed durable write leaves no money row stranded under a missing run."""
    from database import init_database
    from database.manager import DatabaseManager
    monkeypatch.setattr(svc, "_db_enabled", lambda: True)
    init_database()
    svc.reset_agent_ecosystem()

    agent = svc.create_agent("halfagent", "Half Agent", default_rate=10, created_by="admin")
    _, inv = svc.create_invitation(agent["id"], "customer", proposed_rate=10)
    svc.approve_invitation(inv["code"], 10, "admin")
    assert svc.redeem_invitation(inv["code"], "customer", "CUST-HALF")[0]
    svc.recompute_commissions({"POL-HALF": {"id": "POL-HALF", "customer_id": "CUST-HALF",
                                            "annual_premium": 1000, "status": "active"}})

    # The sweep cannot persist: commissions stay accrued and re-sweepable.
    monkeypatch.setattr(svc, "_persist_records", lambda items: False)
    run = svc.run_payouts(created_by="admin")
    assert run["created"] == 0
    assert run["skipped_agents"] == [{"agent_id": agent["id"], "reason": "persist_failed",
                                      "commission_count": 1}]
    assert svc.income_summary(agent["id"])["accrued_total"] == 100.0
    with DatabaseManager() as db:
        assert db.agent_payouts.list_by_agent(agent["id"]) == []
        assert all(r.status == "accrued" and not r.payout_id
                   for r in db.agent_commissions.list_by_agent(agent["id"]))

    monkeypatch.undo()
    monkeypatch.setattr(svc, "_db_enabled", lambda: True)
    pay = svc.run_payouts(created_by="admin")["payouts"][0]

    # The settlement cannot persist: the run stays calculated, nothing is paid.
    ledger = _FakePlatformLedger()
    monkeypatch.setattr(svc, "_persist_records", lambda items: False)
    ok, err = svc.settle_payout(pay["id"], settled_by="admin", platform_ledger=ledger)
    assert ok is False and "persist" in err
    assert svc.get_payout(pay["id"])["status"] == "calculated"
    assert all(svc.COMMISSIONS[c]["status"] == "payable" for c in pay["commission_ids"])
    assert svc.verify_ledger_integrity() is True

    # Retrying settles cleanly and re-uses the idempotent anchor.
    monkeypatch.undo()
    monkeypatch.setattr(svc, "_db_enabled", lambda: True)
    ok, settled = svc.settle_payout(pay["id"], settled_by="admin", platform_ledger=ledger)
    assert ok and settled["status"] == "settled"
    assert list(ledger.transaction_ledger) == [f"AGPAY-{pay['id']}"]  # one anchor, re-used
    with DatabaseManager() as db:
        assert db.agent_payouts.get_by_id(pay["id"]).status == "settled"
        assert all(r.status == "paid" for r in db.agent_commissions.list_by_agent(agent["id"]))


def test_db_mode_concurrent_payout_runs_cannot_double_pay(monkeypatch):
    """The same accrual set is never swept into a second run by a peer instance."""
    from database import init_database
    from database.manager import DatabaseManager
    monkeypatch.setattr(svc, "_db_enabled", lambda: True)
    init_database()
    svc.reset_agent_ecosystem()

    agent = svc.create_agent("raceagent", "Race Agent", default_rate=10, created_by="admin")
    _, inv = svc.create_invitation(agent["id"], "customer", proposed_rate=10)
    svc.approve_invitation(inv["code"], 10, "admin")
    assert svc.redeem_invitation(inv["code"], "customer", "CUST-RACE")[0]
    svc.recompute_commissions({"POL-RACE": {"id": "POL-RACE", "customer_id": "CUST-RACE",
                                            "annual_premium": 1000, "status": "active"}})
    peer_run = svc.run_payouts(created_by="peer")["payouts"][0]

    # A peer instance wrote that run; this instance's cache is stale (its refresh
    # is failing) and still believes the accruals are free to sweep.
    monkeypatch.setattr(svc, "_hydrate_from_db", lambda force=False: None)
    svc.PAYOUTS.pop(peer_run["id"], None)
    for cid in peer_run["commission_ids"]:
        svc.COMMISSIONS[cid].update({"status": "accrued", "payout_id": None})
    again = svc.run_payouts(created_by="admin")
    assert again["created"] == 0
    assert again["skipped_agents"] == [{"agent_id": agent["id"], "reason": "already_swept",
                                        "payout_id": peer_run["id"], "commission_count": 1}]

    # Even without that read, the durable unique key refuses the duplicate run.
    duplicate = {**peer_run, "id": "APAY-DUPLICATE"}
    assert svc._persist_records([("payout", duplicate)]) is False
    with DatabaseManager() as db:
        assert [p.id for p in db.agent_payouts.list_by_agent(agent["id"])] == [peer_run["id"]]

    # A caller key another instance used is found durably, not re-run.
    with DatabaseManager() as db:
        db.agent_payouts.update(peer_run["id"], idempotency_key="race-key")
    svc.PAYOUTS.clear()
    reused = svc.run_payouts(created_by="admin", idempotency_key="race-key")
    assert reused["reused"] is True and reused["payouts"][0]["id"] == peer_run["id"]


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
