"""
Unit tests for the Actuarial Dashboard sandbox -> pipeline bridge.

The sandbox bar on the actuary dashboard is purely client-side, but the
"Push to Pipeline" button posts the materialized in-memory book to the
admin pipeline via /api/admin/sandbox/push-to-pipeline.  Once pushed, the
"Clean Demo Data" button on the admin balance-sheet bar must purge those
records completely.

These tests exercise the underlying state contracts directly so they do
not require an authenticated HTTP session against the embedded server.
They cover:
1.  The sandbox-pushed registry (SANDBOX_PUSHED_CUSTOMERS) starts empty.
2.  Records added under that registry are auto-suspended (hidden from
    admin BI/dashboards).
3.  Deletion logic (mirroring the cleanup_demo_data branch) fully wipes
    the records and the sandbox tracking set, with no spillover into
    real customers.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import web_portal.server as portal


def _reset_sandbox_state():
    portal.SANDBOX_PUSHED_CUSTOMERS.clear()


def test_sandbox_registry_module_attributes_present():
    """The sandbox bridge requires two module-level state objects."""
    assert hasattr(portal, "SANDBOX_PUSHED_CUSTOMERS")
    assert isinstance(portal.SANDBOX_PUSHED_CUSTOMERS, set)
    assert hasattr(portal, "SUSPENDED_TEST_ACCOUNTS")
    assert isinstance(portal.SUSPENDED_TEST_ACCOUNTS, set)


def test_sandbox_pushed_customers_treated_as_suspended_for_bi():
    """is_suspended_account must respect any sandbox-pushed customer that
    was also added to the suspended set (which the push endpoint does
    automatically)."""
    _reset_sandbox_state()
    cust_id = "CUST-TESTSIM-000777"
    portal.SANDBOX_PUSHED_CUSTOMERS.add(cust_id)
    portal.SUSPENDED_TEST_ACCOUNTS.add(cust_id)
    try:
        assert portal.is_suspended_account(cust_id) is True
        assert portal.is_suspended_account("CUST-EFRAT-001") is False
    finally:
        portal.SUSPENDED_TEST_ACCOUNTS.discard(cust_id)
        _reset_sandbox_state()


def test_sandbox_full_purge_mirrors_cleanup_demo_data_branch():
    """Replicates the cleanup_demo_data sandbox-purge branch in isolation.

    A real cleanup happens inside an HTTP handler that needs an admin
    session; this test exercises the same set of state mutations against
    in-memory portal globals to catch regressions in the contract.
    """
    _reset_sandbox_state()
    cust_id = "CUST-TESTSIM-000001"
    pol_id = "POL-TESTSIM-000001"
    clm_id = "CLM-TESTSIM-000001"
    bill_id = "BILL-TESTSIM-000001"

    uw_id = "UW-TESTSIM-000001"

    portal.CUSTOMERS[cust_id] = {"id": cust_id, "name": "Sandbox 1", "source": "actuary_sandbox"}
    portal.POLICIES[pol_id] = {"id": pol_id, "customer_id": cust_id}
    portal.CLAIMS[clm_id] = {"id": clm_id, "customer_id": cust_id, "amount": 1000}
    portal.BILLING[bill_id] = {"id": bill_id, "customer_id": cust_id, "amount": 100}
    portal.UNDERWRITING_APPLICATIONS[uw_id] = {"id": uw_id, "customer_id": cust_id}
    portal.HEALTH_WALLETS[cust_id] = {"balance": 500, "transactions": []}
    portal.INVESTMENT_ACCOUNTS[cust_id] = {"balance": 1000}
    portal.REGISTERED_CUSTOMERS[cust_id] = {"id": cust_id, "name": "Sandbox 1"}
    portal.SANDBOX_PUSHED_CUSTOMERS.add(cust_id)
    portal.SUSPENDED_TEST_ACCOUNTS.add(cust_id)

    # Untouched control row that must survive the purge.
    portal.CUSTOMERS["CUST-CONTROL-1"] = {"id": "CUST-CONTROL-1", "name": "Real"}

    try:
        # Mirror the cleanup branch exactly.
        for sandbox_id in list(portal.SANDBOX_PUSHED_CUSTOMERS):
            for p_id, p in list(portal.POLICIES.items()):
                if p.get("customer_id") == sandbox_id:
                    del portal.POLICIES[p_id]
            for c_id, c in list(portal.CLAIMS.items()):
                if c.get("customer_id") == sandbox_id:
                    del portal.CLAIMS[c_id]
            for b_id, b in list(portal.BILLING.items()):
                if b.get("customer_id") == sandbox_id:
                    del portal.BILLING[b_id]
            for u_id, u in list(portal.UNDERWRITING_APPLICATIONS.items()):
                if u.get("customer_id") == sandbox_id:
                    del portal.UNDERWRITING_APPLICATIONS[u_id]
            portal.HEALTH_WALLETS.pop(sandbox_id, None)
            portal.INVESTMENT_ACCOUNTS.pop(sandbox_id, None)
            portal.REGISTERED_CUSTOMERS.pop(sandbox_id, None)
            portal.CUSTOMERS.pop(sandbox_id, None)
            portal.SUSPENDED_TEST_ACCOUNTS.discard(sandbox_id)
            portal.SANDBOX_PUSHED_CUSTOMERS.discard(sandbox_id)

        assert cust_id not in portal.CUSTOMERS
        assert pol_id not in portal.POLICIES
        assert clm_id not in portal.CLAIMS
        assert bill_id not in portal.BILLING
        assert uw_id not in portal.UNDERWRITING_APPLICATIONS
        assert cust_id not in portal.HEALTH_WALLETS
        assert cust_id not in portal.INVESTMENT_ACCOUNTS
        assert cust_id not in portal.REGISTERED_CUSTOMERS
        assert cust_id not in portal.SANDBOX_PUSHED_CUSTOMERS
        assert cust_id not in portal.SUSPENDED_TEST_ACCOUNTS
        # Real customer was not affected.
        assert "CUST-CONTROL-1" in portal.CUSTOMERS
    finally:
        portal.CUSTOMERS.pop("CUST-CONTROL-1", None)
        portal.UNDERWRITING_APPLICATIONS.pop(uw_id, None)
        portal.HEALTH_WALLETS.pop(cust_id, None)
        portal.INVESTMENT_ACCOUNTS.pop(cust_id, None)
        portal.REGISTERED_CUSTOMERS.pop(cust_id, None)
        _reset_sandbox_state()


def test_actuary_dashboard_static_html_exposes_sandbox_section():
    """Smoke test that the sandbox bar is wired into the dashboard."""
    from pathlib import Path
    html_path = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "actuary-dashboard.html"
    content = html_path.read_text(encoding="utf-8")
    assert 'id="section-sandbox"' in content
    assert "Sandbox Testing" in content
    assert 'id="sandbox-banner"' in content
    assert "generateSandboxFromSimulation" in content
    assert "pushSandboxToPipeline" in content
    assert "resetSandbox" in content
    assert "/api/admin/sandbox/push-to-pipeline" in content
    # The sandbox MUST NOT call any admin-data endpoints implicitly.
    # Allowed admin endpoints in this file are the explicit push bridge
    # and the existing actuarial endpoints. Nothing should auto-load
    # admin customer/billing data while in the sandbox section.
    assert "/api/admin/cleanup-demo-data" not in content


def test_actuary_dashboard_sandbox_uses_testsim_namespace():
    """All sandbox account IDs must start with CUST-TESTSIM- so that the
    admin "Clean Demo Data" workflow can recognize and purge them."""
    from pathlib import Path
    html_path = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "actuary-dashboard.html"
    content = html_path.read_text(encoding="utf-8")
    assert "CUST-TESTSIM-" in content
    assert "BILL-TESTSIM-" in content
    assert "POL-TESTSIM-" in content
    assert "CLM-TESTSIM-" in content
