"""U7 — agent commission clawback (AE6 hash-chained reversal on lapse)."""

from __future__ import annotations

from pathlib import Path

import pytest

from services import agent_ecosystem_service as svc
from services.erp.integrity_scorecard import compute_integrity_scorecard
from services.jobs import commission_clawback_job


@pytest.fixture(autouse=True)
def _reset_ecosystem():
    svc.reset_agent_ecosystem()
    yield
    svc.reset_agent_ecosystem()


def _affiliated_agent(customer_id: str = "CUST-CLAW", rate: float = 0.10):
    agent = svc.create_agent("agent-claw", default_rate=rate, created_by="admin")
    _, inv = svc.create_invitation(agent["id"], "customer", proposed_rate=rate)
    svc.approve_invitation(inv["code"], rate, "admin")
    ok, _ = svc.redeem_invitation(inv["code"], "customer", customer_id)
    assert ok
    return agent


def test_policy_id_from_source_event():
    assert svc.policy_id_from_source_event("policy:POL-1") == "POL-1"
    assert svc.policy_id_from_source_event("policy:POL-1:2025-01-01") == "POL-1"
    assert svc.policy_id_from_source_event("order:ORD-1") is None
    assert svc.policy_id_from_source_event("") is None


def test_accrue_lapse_clawback_ledger_intact():
    agent = _affiliated_agent()
    policies = {
        "POL-CLAW": {
            "id": "POL-CLAW",
            "customer_id": "CUST-CLAW",
            "annual_premium": 1000,
            "status": "active",
        }
    }
    assert svc.recompute_commissions(policies) == 1
    comms = svc.list_commissions(agent_id=agent["id"])
    assert len(comms) == 1 and comms[0]["status"] == "accrued"
    cid = comms[0]["id"]

    policies["POL-CLAW"]["status"] = "lapsed"
    ok, out = svc.apply_clawback(cid, reason="policy_lapsed", policy_id="POL-CLAW", actor="test")
    assert ok and out["status"] == "reversed"
    assert out["clawback_policy_id"] == "POL-CLAW"
    assert svc.verify_ledger_integrity() is True

    ledger = svc.get_ledger(agent_id=agent["id"], limit=50)
    claw_events = [e for e in ledger if e.get("event_type") == svc.CLAWBACK_EVENT]
    assert len(claw_events) == 1
    assert claw_events[0]["amount"] == -100.0
    assert claw_events[0]["payload"]["commission_id"] == cid
    assert claw_events[0]["payload"]["policy_id"] == "POL-CLAW"


def test_double_clawback_is_idempotent():
    agent = _affiliated_agent("CUST-IDEM")
    policies = {
        "POL-IDEM": {
            "id": "POL-IDEM",
            "customer_id": "CUST-IDEM",
            "annual_premium": 500,
            "status": "cancelled",
        }
    }
    # Accrue while still active, then cancel.
    policies["POL-IDEM"]["status"] = "active"
    svc.recompute_commissions(policies)
    cid = svc.list_commissions(agent_id=agent["id"])[0]["id"]
    policies["POL-IDEM"]["status"] = "cancelled"

    ok1, out1 = svc.apply_clawback(cid, policy_id="POL-IDEM", actor="test")
    ok2, out2 = svc.apply_clawback(cid, policy_id="POL-IDEM", actor="test")
    assert ok1 and ok2
    assert out2.get("already_clawed_back") is True
    claw_events = [
        e for e in svc.get_ledger(agent_id=agent["id"], limit=50)
        if e.get("event_type") == svc.CLAWBACK_EVENT
    ]
    assert len(claw_events) == 1


def test_scan_claws_lapsed_and_reports_coverage():
    agent = _affiliated_agent("CUST-SCAN")
    policies = {
        "POL-SCAN": {
            "id": "POL-SCAN",
            "customer_id": "CUST-SCAN",
            "annual_premium": 2000,
            "status": "active",
        }
    }
    svc.recompute_commissions(policies)
    assert svc.clawback_coverage(policies)["ok"] is True  # still active

    policies["POL-SCAN"]["status"] = "expired"
    gap = svc.clawback_coverage(policies)
    assert gap["ok"] is False and gap["gap_count"] == 1

    result = svc.clawback_for_policies(policies, actor="scan-test")
    assert result["clawed"] == 1
    assert result["ledger_intact"] is True
    assert result["coverage"]["ok"] is True
    assert result["coverage"]["covered_count"] == 1

    # Second scan is a no-op (never double-clawback).
    again = svc.clawback_for_policies(policies, actor="scan-test")
    assert again["clawed"] == 0 and again["already"] == 1


def test_overdue_bill_alone_does_not_auto_claw_active_policy():
    """A late premium on an active policy must not reverse initial-term accrual."""
    agent = _affiliated_agent("CUST-OVER")
    policies = {
        "POL-OVER": {
            "id": "POL-OVER",
            "customer_id": "CUST-OVER",
            "annual_premium": 800,
            "status": "active",
        }
    }
    svc.recompute_commissions(policies)
    cid = svc.list_commissions(agent_id=agent["id"])[0]["id"]
    bills = {
        "BILL-1": {
            "id": "BILL-1",
            "policy_id": "POL-OVER",
            "status": "overdue",
            "amount": 66.67,
        }
    }
    result = svc.clawback_for_policies(policies, bills, actor="test")
    assert result["clawed"] == 0
    assert svc.COMMISSIONS[cid]["status"] == "accrued"
    # Explicit admin clawback still works for unpaid premium.
    ok, out = svc.apply_clawback(
        cid, reason="unpaid_premium_overdue", policy_id="POL-OVER", actor="admin",
    )
    assert ok and out["status"] == "reversed"
    summary = svc.income_summary(agent["id"])
    assert summary["clawed_back_total"] == 80.0
    assert summary["lifetime_total"] == 0.0


def test_payable_unsweep_then_clawback():
    agent = _affiliated_agent("CUST-PAY")
    policies = {
        "POL-PAY": {
            "id": "POL-PAY",
            "customer_id": "CUST-PAY",
            "annual_premium": 1000,
            "status": "active",
        }
    }
    svc.recompute_commissions(policies)
    run = svc.run_payouts(agent_id=agent["id"], created_by="admin")
    assert run["created"] == 1
    pay = run["payouts"][0]
    assert pay["status"] == "calculated"
    cid = pay["commission_ids"][0]
    assert svc.COMMISSIONS[cid]["status"] == "payable"

    policies["POL-PAY"]["status"] = "lapsed"
    ok, out = svc.apply_clawback(cid, policy_id="POL-PAY", actor="test")
    assert ok and out["status"] == "reversed"
    assert out.get("payout_id") in (None, "")
    # Empty calculated shell left behind with zero gross.
    leftover = svc.get_payout(pay["id"])
    assert leftover is not None
    assert leftover["commission_ids"] == []
    assert leftover["gross_amount"] == 0.0
    assert svc.verify_ledger_integrity() is True


def test_payable_persist_failure_restores_prior_status(monkeypatch):
    """DB-off hydrate is a no-op; rollback must still undo a failed payable claw."""
    agent = _affiliated_agent("CUST-FAIL")
    policies = {
        "POL-FAIL": {
            "id": "POL-FAIL",
            "customer_id": "CUST-FAIL",
            "annual_premium": 1000,
            "status": "active",
        }
    }
    svc.recompute_commissions(policies)
    run = svc.run_payouts(agent_id=agent["id"], created_by="admin")
    pay_id = run["payouts"][0]["id"]
    cid = run["payouts"][0]["commission_ids"][0]
    policies["POL-FAIL"]["status"] = "lapsed"

    monkeypatch.setattr(svc, "_persist_records", lambda _items: False)
    ok, err = svc.apply_clawback(cid, policy_id="POL-FAIL", actor="test")
    assert ok is False
    assert "persisted" in str(err).lower()
    assert svc.COMMISSIONS[cid]["status"] == "payable"
    assert svc.COMMISSIONS[cid]["payout_id"] == pay_id
    pay = svc.get_payout(pay_id)
    assert cid in pay["commission_ids"]
    assert pay["gross_amount"] == 100.0
    # Retry must not hit already_clawed_back — the write can be attempted again.
    monkeypatch.setattr(svc, "_persist_records", lambda _items: True)
    ok2, out2 = svc.apply_clawback(cid, policy_id="POL-FAIL", actor="test")
    assert ok2 and out2["status"] == "reversed"
    assert out2.get("already_clawed_back") is not True


def test_integrity_flags_clawback_gap_then_clears():
    agent = _affiliated_agent("CUST-INT")
    customers = {"CUST-INT": {"id": "CUST-INT", "name": "Ira", "referring_agent_id": agent["id"]}}
    policies = {
        "POL-INT": {
            "id": "POL-INT",
            "customer_id": "CUST-INT",
            "annual_premium": 1000,
            "status": "active",
        }
    }
    svc.recompute_commissions(policies)
    policies["POL-INT"]["status"] = "lapsed"
    audit = svc.connection_integrity(customers=customers, policies=policies)
    codes = [i["code"] for i in audit["issues"]]
    assert "commission_clawback_gap" in codes
    assert audit["clawback_coverage"]["ok"] is False

    svc.clawback_for_policies(policies, actor="test")
    audit2 = svc.connection_integrity(customers=customers, policies=policies)
    codes2 = [i["code"] for i in audit2["issues"]]
    assert "commission_clawback_gap" not in codes2
    assert audit2["clawback_coverage"]["ok"] is True
    assert audit2["ok"] is True


def test_job_run_once_and_register():
    agent = _affiliated_agent("CUST-JOB")
    policies = {
        "POL-JOB": {
            "id": "POL-JOB",
            "customer_id": "CUST-JOB",
            "annual_premium": 1200,
            "status": "active",
        }
    }
    svc.recompute_commissions(policies)
    policies["POL-JOB"]["status"] = "inactive"
    result = commission_clawback_job.run_once(policies=policies, bills={}, actor="job-test")
    assert result["clawed"] == 1
    assert result["coverage"]["ok"] is True

    from services.agent_job_queue import AgentJobQueue
    queue = AgentJobQueue(poll_interval=0.01)
    commission_clawback_job.register(queue)
    assert commission_clawback_job.JOB_TYPE in queue.handlers()


def test_scorecard_u7_landed_on_this_checkout():
    report = compute_integrity_scorecard()
    by_id = {u["unit_id"]: u for u in report["units"]}
    assert by_id["U7"]["status"] == "landed", by_id["U7"]
    # P1 complete → claimed 82.
    assert report["claimed_score"] == 82
    p1 = next(b for b in report["bands"] if b["id"] == "P1")
    assert p1["claimed"] is True


def test_scorecard_u7_partial_without_tests(tmp_path: Path):
    job = tmp_path / "services" / "jobs"
    job.mkdir(parents=True)
    (job / "commission_clawback_job.py").write_text("# stub\n", encoding="utf-8")
    report = compute_integrity_scorecard(repo_root=str(tmp_path))
    by_id = {u["unit_id"]: u for u in report["units"]}
    assert by_id["U7"]["status"] == "partial"
