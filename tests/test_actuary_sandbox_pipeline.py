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
import json
import urllib.error
from urllib.request import Request, urlopen

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import web_portal.server as portal


def _reset_sandbox_state():
    portal.SANDBOX_PUSHED_CUSTOMERS.clear()


# ---------------------------------------------------------------------------
# HTTP helpers for the live push-to-pipeline endpoint (embedded server is
# started by the repository-level conftest on TEST_PORT).
# ---------------------------------------------------------------------------

def _base_url() -> str:
    return os.environ.get("TEST_BASE_URL") or "http://127.0.0.1:8000"


def _post_json(path: str, payload: dict, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(
        _base_url() + path,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(req) as resp:
        return json.loads(resp.read() or b"{}"), resp.status


@pytest.fixture
def admin_token() -> str:
    body, status = _post_json("/api/login", {"username": "admin", "password": "admin123"})
    assert status == 200, body
    return body["token"]


def _purge_pushed():
    """Remove everything the push endpoint may have created so the live
    tests leave the shared in-memory portal state pristine."""
    for cid in list(portal.SANDBOX_PUSHED_CUSTOMERS):
        for store, field in (
            (portal.POLICIES, "customer_id"),
            (portal.CLAIMS, "customer_id"),
            (portal.BILLING, "customer_id"),
        ):
            for k, v in list(store.items()):
                if v.get(field) == cid:
                    del store[k]
        portal.CUSTOMERS.pop(cid, None)
        portal.SUSPENDED_TEST_ACCOUNTS.discard(cid)
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

    # Add a protected customer to SANDBOX_PUSHED_CUSTOMERS to verify the
    # PROTECTED_CUSTOMERS safety guard prevents its purge.
    protected_id = "CUST-ASAF-001"
    portal.CUSTOMERS[protected_id] = {"id": protected_id, "name": "Protected Real"}
    portal.SANDBOX_PUSHED_CUSTOMERS.add(protected_id)

    try:
        # Mirror the cleanup branch exactly, including the PROTECTED_CUSTOMERS filter.
        PROTECTED_CUSTOMERS = {
            'CUST-ASAF-001',
            'CUST-EFRAT-001',
            'CUST-SHOSH-001',
            'CUST-ASI-001',
        }
        purge_ids = {cid for cid in portal.SANDBOX_PUSHED_CUSTOMERS if cid not in PROTECTED_CUSTOMERS}
        for sandbox_id in list(purge_ids):
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
        # Protected customer must survive even though it was in SANDBOX_PUSHED_CUSTOMERS.
        assert protected_id in portal.CUSTOMERS
    finally:
        portal.CUSTOMERS.pop("CUST-CONTROL-1", None)
        portal.CUSTOMERS.pop(protected_id, None)
        portal.SANDBOX_PUSHED_CUSTOMERS.discard(protected_id)
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


def test_actuary_dashboard_wires_contract_aware_sandbox_features():
    """The optimized sandbox must price against the Contract Being Priced
    and expose the monthly cash-flow projection."""
    from pathlib import Path
    html_path = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "actuary-dashboard.html"
    content = html_path.read_text(encoding="utf-8")
    # Contract-aware claim causes (death + permanent disability only).
    assert "Death — natural or accidental" in content
    assert "Permanent total disability (3+ ADL)" in content
    # Monthly projection tab + seeding hooks.
    assert "seedSandboxProjection" in content
    assert "sandbox-projection-body" in content
    assert "Monthly Projection" in content
    assert "disability_share_of_life" in content
    # Simulation parameters are consumed (age dist, coverage dist, savings).
    assert "age_distribution" in content
    assert "coverage_distribution" in content
    assert "savings_rate" in content


def test_actuary_dashboard_wires_100k_cap_and_5yr_forecast():
    """The optimized sandbox supports up to 100,000 materialized accounts and
    a 60-month (5-year) adjustable forecast with charts and 10% growth."""
    from pathlib import Path
    html_path = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "actuary-dashboard.html"
    content = html_path.read_text(encoding="utf-8")
    # 100,000 materialization cap.
    assert "SANDBOX_HARD_CAP = 100000" in content
    # 60-month / 5-year horizon.
    assert "months: 60" in content
    # Adjustable controls (growth defaulting to 10%, premium, loss ratio, horizon).
    assert 'id="sandbox-forecast-growth"' in content
    assert 'id="sandbox-forecast-premium"' in content
    assert 'id="sandbox-forecast-lossratio"' in content
    assert 'id="sandbox-forecast-horizon"' in content
    assert "recomputeSandboxForecast" in content
    # Three adjustable charts (cash flow, accumulated, capacity).
    assert 'id="sandbox-proj-chart-cashflow"' in content
    assert 'id="sandbox-proj-chart-accum"' in content
    assert 'id="sandbox-proj-chart-capacity"' in content
    assert "sandboxRenderForecastCharts" in content
    # Contract age-trigger handling: disability ceiling is contract-driven and
    # the accepted age band is carried so an age-55 cohort claims accordingly.
    assert "disability_max_age" in content
    assert "disability_eligible: age < disabilityMaxAge" in content
    assert "age_min: acceptedAgeMin" in content


def test_actuary_dashboard_renders_sandbox_stats_single_pass():
    """The large-book performance fix consolidates renderSandbox's per-tab
    filter/reduce scans into one pass per array so a 100k book does not stall
    the lifecycle tick. The duplicate filter passes must be gone."""
    from pathlib import Path
    html_path = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "actuary-dashboard.html"
    content = html_path.read_text(encoding="utf-8")
    # Single-pass markers introduced by the consolidation.
    assert "counts already tallied in the single pass above" in content
    # The old repeated full-array scans for the same metric must be gone.
    assert "customers.filter(c => c.uw_status === 'approved').length" not in content
    assert "claims.filter(c => c.status === 'pending').length" not in content
    assert "bills.filter(b => b.status === 'outstanding').length" not in content
    # Shrinking the forecast horizon clamps elapsed months.
    assert "proj.monthsElapsed = Math.min(proj.monthsElapsed, horizon)" in content


def test_actuary_dashboard_wires_sandbox_export_downloads():
    """The sandbox insight tabs expose client-side CSV / Excel / PDF exports,
    all generated from the in-memory book (no server round-trip)."""
    from pathlib import Path
    html_path = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "actuary-dashboard.html"
    content = html_path.read_text(encoding="utf-8")
    # Buttons + handlers.
    assert "exportSandboxCSV" in content
    assert "exportSandboxExcel" in content
    assert "exportSandboxAssessmentPDF" in content
    # Shared roll-up + per-month lifecycle accumulation that the PDF outlines.
    assert "sandboxComputeInsights" in content
    assert "realizedSeries" in content
    # Excel multi-sheet (SpreadsheetML) + CSV mime types.
    assert "application/vnd.ms-excel" in content
    assert "urn:schemas-microsoft-com:office:spreadsheet" in content
    assert "text/csv" in content
    # PDF AI assessment uses jsPDF (loaded from the CSP-allowed jsdelivr CDN)
    # and surfaces the claim-type distribution outline.
    assert "jspdf" in content
    assert "Claim Type Distribution" in content
    assert "Random Lifecycle" in content


# ---------------------------------------------------------------------------
# Live HTTP push-to-pipeline tests (the "Push to Pipeline" event)
# ---------------------------------------------------------------------------

def _sandbox_push_payload():
    """A representative contract-aware sandbox slice as the dashboard posts it.

    Mortality claim → full sum insured L; disability claim → L × 0.25
    (the 1:4 contract ratio). Both reference a pushed, policy-backed
    customer so the push has no dangling references."""
    coverage = 500_000.0
    return {
        "simulation_id": "SIM-TESTPUSH-0001",
        "customers": [
            {
                "id": "CUST-TESTSIM-900001",
                "name": "Sandbox Mortality",
                "age": 70,
                "uw_status": "approved",
                "coverage_amount": coverage,
                "annual_premium": 4800,
                "monthly_premium": 400,
                "risk_premium": 3000,
                "savings_premium": 600,
                "savings_rate": 0.2,
                "disability_share_of_life": 0.25,
                "term_years": 10,
                "risk_score": 40,
            },
            {
                "id": "CUST-TESTSIM-900002",
                "name": "Sandbox Disability",
                "age": 45,
                "uw_status": "approved",
                "coverage_amount": coverage,
                "annual_premium": 3600,
                "monthly_premium": 300,
                "term_years": 20,
                "risk_score": 30,
            },
        ],
        "policies": [
            {
                "id": "POL-TESTSIM-900001",
                "customer_id": "CUST-TESTSIM-900001",
                "type": "phins_pure_risk_adjustable",
                "coverage_amount": coverage,
                "annual_premium": 4800,
                "monthly_premium": 400,
                "risk_premium": 3000,
                "savings_premium": 600,
                "savings_rate": 0.2,
                "disability_share_of_life": 0.25,
                "status": "active",
                "term_years": 10,
            },
            {
                "id": "POL-TESTSIM-900002",
                "customer_id": "CUST-TESTSIM-900002",
                "type": "phins_pure_risk_adjustable",
                "coverage_amount": coverage,
                "annual_premium": 3600,
                "monthly_premium": 300,
                "status": "active",
                "term_years": 20,
            },
        ],
        "claims": [
            {
                "id": "CLM-TESTSIM-900001",
                "customer_id": "CUST-TESTSIM-900001",
                "policy_id": "POL-TESTSIM-900001",
                "type": "mortality",
                "cause": "Death — natural or accidental",
                "amount": coverage,
                "approved_amount": coverage,
                "paid_amount": coverage,
                "status": "paid",
                "reported_at": "2026-05-01T00:00:00",
            },
            {
                "id": "CLM-TESTSIM-900002",
                "customer_id": "CUST-TESTSIM-900002",
                "policy_id": "POL-TESTSIM-900002",
                "type": "disability",
                "cause": "Permanent total disability (3+ ADL)",
                "amount": coverage * 0.25,
                "status": "pending",
                "reported_at": "2026-05-02T00:00:00",
            },
        ],
        "bills": [
            {
                "id": "BILL-TESTSIM-900001-001",
                "customer_id": "CUST-TESTSIM-900001",
                "policy_id": "POL-TESTSIM-900001",
                "amount": 400,
                "amount_paid": 400,
                "status": "paid",
            },
            {
                "id": "BILL-TESTSIM-900002-001",
                "customer_id": "CUST-TESTSIM-900002",
                "policy_id": "POL-TESTSIM-900002",
                "amount": 300,
                "amount_paid": 0,
                "status": "outstanding",
            },
        ],
    }


def test_push_to_pipeline_materializes_contract_aware_records(admin_token):
    """End-to-end: the push endpoint materializes the sandbox slice,
    preserving the contract-aware cause of claim and the savings breakdown,
    auto-suspending the accounts, and keeping referential integrity."""
    _purge_pushed()
    payload = _sandbox_push_payload()
    try:
        body, status = _post_json("/api/admin/sandbox/push-to-pipeline", payload, admin_token)
        assert status == 200, body
        assert body["success"] is True
        created = body["created"]
        assert created == {"customers": 2, "policies": 2, "claims": 2, "bills": 2}, created

        # Customers materialized + auto-suspended (hidden from admin BI).
        for cid in ("CUST-TESTSIM-900001", "CUST-TESTSIM-900002"):
            assert cid in portal.CUSTOMERS
            assert portal.is_suspended_account(cid) is True
            assert cid in portal.SANDBOX_PUSHED_CUSTOMERS

        # Contract being priced: cause of claim is preserved verbatim and the
        # mortality benefit equals the full sum insured while disability is
        # the L × 0.25 contract ratio.
        mort = portal.CLAIMS["CLM-TESTSIM-900001"]
        dis = portal.CLAIMS["CLM-TESTSIM-900002"]
        assert mort["cause"] == "Death — natural or accidental"
        assert mort["type"] == "mortality"
        assert mort["amount"] == 500_000.0
        assert mort["paid_amount"] == 500_000.0
        assert dis["cause"] == "Permanent total disability (3+ ADL)"
        assert dis["type"] == "disability"
        assert dis["amount"] == 125_000.0

        # Savings breakdown carried onto the policy.
        pol = portal.POLICIES["POL-TESTSIM-900001"]
        assert pol["savings_premium"] == 600.0
        assert pol["savings_rate"] == 0.2
        assert pol["disability_share_of_life"] == 0.25

        # Referential integrity: every pushed claim/bill resolves to a pushed
        # customer AND a pushed policy (no dangling references).
        for store in (portal.CLAIMS, portal.BILLING):
            for rec in store.values():
                if "TESTSIM-9000" in rec.get("customer_id", ""):
                    assert rec["customer_id"] in portal.CUSTOMERS
                    assert rec["policy_id"] in portal.POLICIES
    finally:
        _purge_pushed()


def test_push_to_pipeline_rejects_non_testsim_namespace(admin_token):
    """Data integrity: only the CUST-TESTSIM-* namespace may be materialized;
    a stray real-looking id must be ignored, never created."""
    _purge_pushed()
    payload = {
        "simulation_id": "SIM-TESTPUSH-0002",
        "customers": [
            {"id": "CUST-REAL-123456", "name": "Real Person", "uw_status": "approved"},
            {"id": "CUST-TESTSIM-900050", "name": "Sandbox Ok", "uw_status": "approved",
             "coverage_amount": 100000, "annual_premium": 1200, "monthly_premium": 100},
        ],
        "policies": [],
        "claims": [],
        "bills": [],
    }
    try:
        body, status = _post_json("/api/admin/sandbox/push-to-pipeline", payload, admin_token)
        assert status == 200, body
        assert body["created"]["customers"] == 1
        assert "CUST-TESTSIM-900050" in portal.CUSTOMERS
        assert "CUST-REAL-123456" not in portal.CUSTOMERS
    finally:
        _purge_pushed()


def test_push_to_pipeline_requires_non_empty_customers(admin_token):
    """An empty push must be a 400, never a silent no-op success."""
    _purge_pushed()
    try:
        _post_json(
            "/api/admin/sandbox/push-to-pipeline",
            {"simulation_id": "SIM-X", "customers": [], "policies": [], "claims": [], "bills": []},
            admin_token,
        )
        raise AssertionError("expected HTTP 400 for empty customers")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
    finally:
        _purge_pushed()


def test_push_to_pipeline_requires_authentication():
    """Anonymous and bogus-token pushes must be refused (403)."""
    for token in (None, "phins_bogus_token"):
        try:
            _post_json(
                "/api/admin/sandbox/push-to-pipeline",
                _sandbox_push_payload(),
                token,
            )
            raise AssertionError("expected HTTP 401/403 for unauthorized push")
        except urllib.error.HTTPError as exc:
            assert exc.code in (401, 403), exc.code


# ---------------------------------------------------------------------------
# Live end-to-end: push -> present on admin -> Clean Demo Data purge
# ---------------------------------------------------------------------------

def _get_json(path: str, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(_base_url() + path, headers=headers)
    with urlopen(req) as resp:
        return json.loads(resp.read() or b"{}"), resp.status


def test_cleanup_demo_data_purges_pushed_sandbox_end_to_end(admin_token):
    """Full lifecycle: push a sandbox slice, see it presented on the admin
    suspended/test-accounts surface, then Clean Demo Data must delete the
    entire record graph and both registries."""
    _purge_pushed()
    try:
        body, status = _post_json(
            "/api/admin/sandbox/push-to-pipeline", _sandbox_push_payload(), admin_token)
        assert status == 200 and body["success"] is True

        # Presented on admin: flagged as sandbox, with record counts.
        listing, status = _get_json("/api/admin/suspended-accounts", admin_token)
        assert status == 200 and listing["success"] is True
        by_id = {a["customer_id"]: a for a in listing["suspended_accounts"]}
        assert "CUST-TESTSIM-900001" in by_id
        entry = by_id["CUST-TESTSIM-900001"]
        assert entry["sandbox"] is True
        assert entry["policies_count"] == 1
        assert entry["claims_count"] == 1
        assert entry["bills_count"] == 1
        assert listing["sandbox_accounts"] >= 2

        # Clean Demo Data purges the full graph.
        result, status = _get_json("/api/admin/cleanup-demo-data", admin_token)
        assert status == 200 and result["success"] is True
        counts = result["results"]
        assert counts["sandbox_customers_deleted"] >= 2
        assert counts["sandbox_policies_deleted"] >= 2
        assert counts["sandbox_claims_deleted"] >= 2
        assert counts["sandbox_bills_deleted"] >= 2

        for cid in ("CUST-TESTSIM-900001", "CUST-TESTSIM-900002"):
            assert cid not in portal.CUSTOMERS
            assert cid not in portal.SANDBOX_PUSHED_CUSTOMERS
            assert cid not in portal.SUSPENDED_TEST_ACCOUNTS
        for store in (portal.POLICIES, portal.CLAIMS, portal.BILLING):
            assert not any("TESTSIM-9000" in str(k) for k in store.keys())
    finally:
        _purge_pushed()


def test_cleanup_demo_data_recovers_orphaned_testsim_records(admin_token):
    """If the SANDBOX_PUSHED_CUSTOMERS registry is lost (e.g. a restart
    before the ledger flushed), Clean Demo Data must still fully purge
    TESTSIM-namespace records instead of leaving them suspended forever."""
    _purge_pushed()
    cid = "CUST-TESTSIM-910001"
    portal.CUSTOMERS[cid] = {
        "id": cid, "name": "Orphaned Sandbox", "email": f"{cid.lower()}@sandbox.phins.test",
        "source": "actuary_sandbox",
    }
    portal.POLICIES["POL-TESTSIM-910001"] = {
        "id": "POL-TESTSIM-910001", "customer_id": cid, "type": "sandbox_life",
        "coverage_amount": 100000.0, "annual_premium": 1200.0, "status": "active",
    }
    portal.CLAIMS["CLM-TESTSIM-910001"] = {
        "id": "CLM-TESTSIM-910001", "customer_id": cid,
        "policy_id": "POL-TESTSIM-910001", "amount": 1000.0, "status": "pending",
        "description": "sandbox/test claim from actuarial dashboard",
    }
    portal.BILLING["BILL-TESTSIM-910001"] = {
        "id": "BILL-TESTSIM-910001", "customer_id": cid,
        "policy_id": "POL-TESTSIM-910001", "amount": 100.0, "status": "outstanding",
        "description": "sandbox/test bill from actuarial dashboard",
    }
    # Simulate the lost registry: the customer is NOT in the pushed set.
    portal.SANDBOX_PUSHED_CUSTOMERS.discard(cid)
    try:
        result, status = _get_json("/api/admin/cleanup-demo-data", admin_token)
        assert status == 200 and result["success"] is True
        assert result["results"]["sandbox_customers_deleted"] >= 1

        assert cid not in portal.CUSTOMERS
        assert "POL-TESTSIM-910001" not in portal.POLICIES
        assert "CLM-TESTSIM-910001" not in portal.CLAIMS
        assert "BILL-TESTSIM-910001" not in portal.BILLING
        assert cid not in portal.SUSPENDED_TEST_ACCOUNTS
    finally:
        portal.CUSTOMERS.pop(cid, None)
        portal.POLICIES.pop("POL-TESTSIM-910001", None)
        portal.CLAIMS.pop("CLM-TESTSIM-910001", None)
        portal.BILLING.pop("BILL-TESTSIM-910001", None)
        portal.SUSPENDED_TEST_ACCOUNTS.discard(cid)
        _purge_pushed()


def test_cleanup_demo_data_counts_demo_bills_and_preserves_real_text(admin_token):
    """demo_bills_removed must actually count removed demo bills, and the
    word-boundary matcher must NOT delete real records whose text merely
    contains 'test' inside another word ('Latest premium installment')."""
    _purge_pushed()
    portal.CUSTOMERS["CUST-DEMOSEED-1"] = {"id": "CUST-DEMOSEED-1", "name": "Demo Seed"}
    portal.CUSTOMERS["CUST-REALSEED-1"] = {"id": "CUST-REALSEED-1", "name": "Real Seed"}
    portal.BILLING["BILL-DEMOSEED-1"] = {
        "id": "BILL-DEMOSEED-1", "customer_id": "CUST-DEMOSEED-1",
        "amount": 50.0, "status": "outstanding", "description": "demo bill seeded for cleanup",
    }
    portal.BILLING["BILL-REALSEED-1"] = {
        "id": "BILL-REALSEED-1", "customer_id": "CUST-REALSEED-1",
        "amount": 75.0, "status": "outstanding", "description": "Latest premium installment",
    }
    portal.CLAIMS["CLM-REALSEED-1"] = {
        "id": "CLM-REALSEED-1", "customer_id": "CUST-REALSEED-1",
        "amount": 500.0, "status": "pending", "description": "Contested claim under review",
    }
    try:
        result, status = _get_json("/api/admin/cleanup-demo-data", admin_token)
        assert status == 200 and result["success"] is True
        assert result["results"]["demo_bills_removed"] >= 1

        assert "BILL-DEMOSEED-1" not in portal.BILLING
        # Word-boundary safety: 'Latest' / 'Contested' are NOT demo markers.
        assert "BILL-REALSEED-1" in portal.BILLING
        assert "CLM-REALSEED-1" in portal.CLAIMS
    finally:
        for store, key in (
            (portal.CUSTOMERS, "CUST-DEMOSEED-1"),
            (portal.CUSTOMERS, "CUST-REALSEED-1"),
            (portal.BILLING, "BILL-DEMOSEED-1"),
            (portal.BILLING, "BILL-REALSEED-1"),
            (portal.CLAIMS, "CLM-REALSEED-1"),
        ):
            store.pop(key, None)


def test_looks_like_demo_text_uses_word_boundaries():
    assert portal.looks_like_demo_text("test claim") is True
    assert portal.looks_like_demo_text("sandbox/test bill from actuarial dashboard") is True
    assert portal.looks_like_demo_text("DEMO deposit") is True
    assert portal.looks_like_demo_text("Sample payout") is True
    # Whole words only — these must never be treated as demo markers.
    assert portal.looks_like_demo_text("Latest premium installment") is False
    assert portal.looks_like_demo_text("Contested claim under review") is False
    assert portal.looks_like_demo_text("Attestation document") is False
    assert portal.looks_like_demo_text("") is False
    assert portal.looks_like_demo_text(None) is False


# ---------------------------------------------------------------------------
# Static integrity: admin test-data surface + actuary dashboard mock removal
# ---------------------------------------------------------------------------

def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_admin_dashboard_presents_test_data_panel():
    """Admin must be able to PRESENT pipeline test data (suspended/sandbox
    accounts) and see the sandbox purge counts after Clean Demo Data."""
    path = os.path.join(_repo_root(), "web_portal", "static", "admin.html")
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    assert "toggleTestDataPanel" in content
    assert 'id="test-data-panel"' in content
    assert "/api/admin/suspended-accounts" in content
    assert "sandbox_customers_deleted" in content
    assert "sandbox_bills_deleted" in content
    # The confirm dialog must disclose the sandbox purge.
    assert "FULLY DELETE actuarial sandbox (TESTSIM) customers" in content


def test_actuary_dashboard_overview_has_no_hardcoded_stats():
    """Overview stat tiles must start as neutral placeholders (filled from
    /api/actuarial/tables + /api/actuarial/config), never fake numbers."""
    path = os.path.join(_repo_root(), "web_portal", "static", "actuary-dashboard.html")
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    assert 'id="stat-version">—<' in content
    assert 'id="stat-decline">—<' in content
    assert 'id="stat-expense">—<' in content
    assert 'id="stat-profit">—<' in content
    # Reinsurance overview stats are loaded from the live BI API on init
    # (once at definition, once in the init loader).
    assert content.count("loadReinsuranceOverview();") >= 2
    # The annual-report cap table must not fabricate a shareholder.
    assert "Enable Holdings" not in content
