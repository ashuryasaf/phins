"""Admin dashboard "Total Revenue" vs Sales Division "Monthly Premium".

The dashboard figure is the *annual* run-rate of *active*, non-suspended
policies; the Sales Division report summed ``monthly_premium`` over *every*
policy attached to a listed customer. ``reconcile_premium_run_rate`` computes
both from one policy set and bridges them to the cent, flagging any data that
breaks the ``monthly_premium == round(annual_premium / 12, 2)`` identity.
"""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import web_portal.server as portal
from services.financial_unification_service import (
    money,
    money_float,
    reconcile_premium_run_rate,
)


BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


# --------------------------------------------------------------------------
# Pure service tests
# --------------------------------------------------------------------------

def _policy(pid, cust, status, annual, monthly="auto"):
    if monthly == "auto":
        monthly = round(annual / 12, 2)
    return {
        "id": pid,
        "customer_id": cust,
        "status": status,
        "annual_premium": annual,
        "monthly_premium": monthly,
    }


def test_dashboard_revenue_is_annual_active_only_and_report_is_monthly_all_statuses():
    policies = [
        _policy("P1", "C1", "active", 1200.0),
        _policy("P2", "C1", "active", 2400.0),
        _policy("P3", "C2", "pending_underwriting", 600.0),
        _policy("P4", "C2", "cancelled", 120.0),
    ]
    r = reconcile_premium_run_rate(
        policies, known_customer_ids={"C1", "C2"}, expected_total_revenue=3600.0
    )

    assert r["dashboard"]["total_revenue"] == 3600.0
    assert r["dashboard"]["monthly_premium_income"] == 300.0
    assert r["dashboard"]["active_policies"] == 2

    sr = r["sales_report"]
    assert sr["active"]["monthly_premium"] == 300.0
    assert sr["pipeline"]["monthly_premium"] == 60.0  # 50 + 10
    assert sr["all_statuses"]["monthly_premium"] == 360.0
    assert sr["all_statuses"]["count"] == 4
    assert sr["by_status"]["pending_underwriting"]["count"] == 1
    assert sr["by_status"]["cancelled"]["annual_premium"] == 120.0

    # The bridge walks from the report figure to the dashboard figure exactly.
    steps = {b["step"]: b["amount"] for b in r["bridge"]}
    assert steps["sales_report_monthly_premium_all_statuses"] == 360.0
    assert steps["less_pipeline_policies_not_active"] == -60.0
    assert steps["active_monthly_premium_dashboard_universe"] == 300.0
    assert steps["times_12_annualize"] == 3600.0
    assert steps["plus_rounding_drift"] == 0.0
    assert steps["dashboard_total_revenue"] == 3600.0
    assert r["is_consistent"] is True


def test_suspended_customers_are_excluded_from_both_views():
    policies = [
        _policy("P1", "C1", "active", 1200.0),
        _policy("P-SUSP", "CUST-TEST-100", "active", 99999.0),
    ]
    r = reconcile_premium_run_rate(
        policies,
        exclude_customer=lambda cid: cid == "CUST-TEST-100",
        known_customer_ids={"C1", "CUST-TEST-100"},
    )
    assert r["dashboard"]["total_revenue"] == 1200.0
    assert r["sales_report"]["all_statuses"]["monthly_premium"] == 100.0
    excluded = r["excluded_from_sales_report"]["suspended_customers"]
    assert excluded["count"] == 1
    assert excluded["annual_premium"] == 99999.0


def test_orphaned_active_policy_counted_by_dashboard_but_not_report():
    policies = [
        _policy("P1", "C1", "active", 1200.0),
        _policy("P-ORPHAN", "CUST-GONE", "active", 600.0),
    ]
    r = reconcile_premium_run_rate(policies, known_customer_ids={"C1"})

    assert r["dashboard"]["total_revenue"] == 1800.0
    assert r["sales_report"]["all_statuses"]["monthly_premium"] == 100.0
    assert r["excluded_from_sales_report"]["orphaned_active"]["monthly_premium"] == 50.0
    assert r["integrity"]["orphaned_policies"] == ["P-ORPHAN"]
    steps = {b["step"]: b["amount"] for b in r["bridge"]}
    assert steps["plus_active_policies_without_customer_record"] == 50.0
    assert steps["active_monthly_premium_dashboard_universe"] == 150.0
    check = next(c for c in r["checks"] if c["check"] == "no_active_policies_without_customer_record")
    assert check["ok"] is False
    assert r["is_consistent"] is False


def test_missing_monthly_premium_is_derived_and_reported_not_silently_zeroed():
    policies = [_policy("P-NULL", "C1", "active", 1552.50, monthly=None)]
    r = reconcile_premium_run_rate(policies, known_customer_ids={"C1"})

    assert r["sales_report"]["active"]["monthly_premium"] == 129.38
    assert r["integrity"]["missing_monthly_premium"] == ["P-NULL"]
    check = next(c for c in r["checks"] if c["check"] == "monthly_premium_present_on_every_policy")
    assert check["ok"] is False
    assert r["is_consistent"] is False


def test_monthly_annual_mismatch_is_flagged_with_expected_value():
    policies = [
        _policy("P-OK", "C1", "active", 1552.50),           # 129.38 (rounding only)
        _policy("P-BAD", "C1", "active", 1200.0, monthly=500.0),  # dashboard-entered 500/mo
    ]
    r = reconcile_premium_run_rate(policies, known_customer_ids={"C1"})

    mismatches = r["integrity"]["monthly_annual_mismatch"]
    assert [m["policy_id"] for m in mismatches] == ["P-BAD"]
    assert mismatches[0]["expected_monthly"] == 100.0
    assert mismatches[0]["difference"] == 400.0
    assert r["is_consistent"] is False


def test_cent_rounding_of_monthly_premium_is_within_allowance():
    # 1552.50 / 12 = 129.375 -> 129.38; x12 = 1552.56 (6 cents of drift).
    policies = [_policy("P1", "C1", "active", 1552.50)]
    r = reconcile_premium_run_rate(policies, known_customer_ids={"C1"}, expected_total_revenue=1552.50)
    steps = {b["step"]: b["amount"] for b in r["bridge"]}
    assert steps["times_12_annualize"] == 1552.56
    assert steps["plus_rounding_drift"] == -0.06
    assert steps["dashboard_total_revenue"] == 1552.50
    assert r["is_consistent"] is True


def test_expected_total_revenue_mismatch_fails_tie_out():
    policies = [_policy("P1", "C1", "active", 1200.0)]
    r = reconcile_premium_run_rate(policies, expected_total_revenue=1300.0)
    check = next(c for c in r["checks"] if c["check"] == "active_annual_premium_equals_dashboard_total_revenue")
    assert check["ok"] is False
    assert check["difference"] == -100.0
    assert r["is_consistent"] is False


# --------------------------------------------------------------------------
# HTTP endpoint tests (embedded server from root conftest.py)
# --------------------------------------------------------------------------

def _ensure_admin_user():
    if "admin" not in portal.USERS:
        pw = portal.hash_password("admin123")
        portal.USERS["admin"] = {**pw, "role": "admin", "name": "Admin User"}


def _mark_test_port_initialized() -> None:
    init_set = getattr(portal, "_TEST_PORTS_INITIALIZED", None)
    port = int(os.environ.get("TEST_PORT", "8000"))
    if isinstance(init_set, set):
        init_set.add(port)


def _session(token: str, role: str, customer_id=None, username="admin") -> str:
    _ensure_admin_user()
    portal.SESSIONS[token] = {
        "username": username,
        "role": role,
        "customer_id": customer_id,
        "expires": "2099-01-01T00:00:00",
    }
    _mark_test_port_initialized()
    return token


def _get(path, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with urlopen(Request(BASE_URL + path, headers=headers), timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


def _post(path, payload, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(BASE_URL + path, data=json.dumps(payload).encode("utf-8"), headers=headers)
    try:
        with urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "{}")


@pytest.fixture
def seeded_book():
    ids = {
        "customers": ["CUST-RECON-A", "CUST-RECON-B"],
        "policies": ["POL-RECON-ACT-1", "POL-RECON-ACT-2", "POL-RECON-PEND", "POL-RECON-ORPHAN"],
    }
    portal.CUSTOMERS["CUST-RECON-A"] = {"id": "CUST-RECON-A", "name": "Recon A", "email": "a@recon.test"}
    portal.CUSTOMERS["CUST-RECON-B"] = {"id": "CUST-RECON-B", "name": "Recon B", "email": "b@recon.test"}
    portal.POLICIES["POL-RECON-ACT-1"] = _policy("POL-RECON-ACT-1", "CUST-RECON-A", "active", 1200.0)
    portal.POLICIES["POL-RECON-ACT-2"] = _policy("POL-RECON-ACT-2", "CUST-RECON-B", "active", 2400.0)
    portal.POLICIES["POL-RECON-PEND"] = _policy("POL-RECON-PEND", "CUST-RECON-B", "pending_underwriting", 600.0)
    portal.POLICIES["POL-RECON-ORPHAN"] = _policy("POL-RECON-ORPHAN", "CUST-RECON-MISSING", "active", 120.0)
    try:
        yield ids
    finally:
        for pid in ids["policies"]:
            portal.POLICIES.pop(pid, None)
        for cid in ids["customers"]:
            portal.CUSTOMERS.pop(cid, None)


def test_endpoint_requires_admin_role():
    status, body = _get("/api/admin/premium-reconciliation")
    assert status == 403
    assert "error" in body

    cust_token = _session("phins_recon-customer", "customer", "CUST-RECON-A", username="a@recon.test")
    try:
        status, body = _get("/api/admin/premium-reconciliation", cust_token)
        assert status == 403
        assert "error" in body
    finally:
        portal.SESSIONS.pop(cust_token, None)


def test_endpoint_ties_dashboard_total_revenue_to_sales_report(seeded_book):
    token = _session("phins_recon-admin", "admin")
    try:
        status, dash = _get("/api/bi/dashboard", token)
        assert status == 200
        status, recon = _get("/api/admin/premium-reconciliation", token)
        assert status == 200
        assert recon["success"] is True

        # Same policy universe, same number: the reconciliation must reproduce
        # the dashboard figure exactly.
        assert recon["dashboard"]["total_revenue"] == dash["total_revenue"]
        tie = next(c for c in recon["checks"]
                   if c["check"] == "active_annual_premium_equals_dashboard_total_revenue")
        assert tie["ok"] is True

        # What the Sales Division "Generate Report" sees is the customer list.
        status, cust = _get("/api/admin/customers", token)
        assert status == 200
        report_monthly = round(sum(
            float(p.get("monthly_premium") or 0)
            for c in cust["customers"] for p in c.get("policies", [])
        ), 2)
        assert recon["sales_report"]["all_statuses"]["monthly_premium"] == report_monthly

        # The bridge explains the whole gap between the two figures.
        steps = {b["step"]: b["amount"] for b in recon["bridge"]}
        assert steps["sales_report_monthly_premium_all_statuses"] == report_monthly
        assert steps["dashboard_total_revenue"] == dash["total_revenue"]
        walked = round(
            steps["sales_report_monthly_premium_all_statuses"]
            + steps["less_pipeline_policies_not_active"]
            + steps["plus_active_policies_without_customer_record"], 2)
        assert walked == steps["active_monthly_premium_dashboard_universe"]
        assert round(walked * 12 + steps["plus_rounding_drift"], 2) == steps["dashboard_total_revenue"]

        # Seeded pending and orphaned rows are surfaced, not absorbed.
        assert recon["sales_report"]["by_status"]["pending_underwriting"]["count"] >= 1
        assert "POL-RECON-ORPHAN" in recon["integrity"]["orphaned_policies"]
    finally:
        portal.SESSIONS.pop(token, None)


def test_policy_create_keeps_monthly_and_annual_premium_as_one_identity():
    cust_id = "CUST-RECON-CREATE"
    portal.CUSTOMERS[cust_id] = {"id": cust_id, "name": "Recon Create", "email": "c@recon.test"}
    token = _session("phins_recon-create", "customer", cust_id, username="c@recon.test")
    created = []
    try:
        status, body = _post("/api/policy/create", {
            "customer_id": cust_id,
            "type": "life",
            "coverage_amount": 250000,
            "monthly_premium": 500,
            "status": "draft",
        }, token)
        assert status == 200, body
        created.append(body["policy_id"])
        pol = portal.POLICIES[body["policy_id"]]
        assert pol["monthly_premium"] == 500.0
        assert pol["annual_premium"] == 6000.0

        status, body = _post("/api/policy/create", {
            "customer_id": cust_id,
            "type": "life",
            "coverage_amount": 250000,
            "status": "draft",
        }, token)
        assert status == 200, body
        created.append(body["policy_id"])
        pol = portal.POLICIES[body["policy_id"]]
        expected_monthly = money_float(money(pol["annual_premium"]) / 12)
        assert abs(pol["monthly_premium"] - expected_monthly) <= 0.01
        # And the reconciliation itself accepts the pair (no mismatch flagged).
        r = reconcile_premium_run_rate([pol], known_customer_ids={cust_id})
        assert r["integrity"]["monthly_annual_mismatch"] == []
    finally:
        for pid in created:
            portal.POLICIES.pop(pid, None)
        portal.CUSTOMERS.pop(cust_id, None)
        portal.SESSIONS.pop(token, None)
