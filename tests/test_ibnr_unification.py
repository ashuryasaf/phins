"""
One IBNR basis, sourced from the audited underwriting config (items D and G).

Before this change PHINS carried three unrelated IBNR/loss-ratio constants:
``ReserveConfig.ibnr_pct = 0.10`` (share of expected claims), the
``reserves_reporting_service`` pair ``0.65 × 0.15`` (share of premium) and the
Monte Carlo engine's own copies. They now live on ``UnderwritingConfig`` as
``ibnr_pct``, ``ibnr_reporting_factor`` and ``loss_ratio_assumption`` and are
changed only through ``ActuarialTablesStore.update_config`` (audited,
append-only ``config_history``, restorable).

The characterisation tests below pin that the defaults reproduce the previous
figures to the cent, so nothing moves until an actuary saves a new assumption.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
import requests

from accounting_engine import reset_accounting_engine
from services.actuarial_service import (
    IBNR_BASIS_SHARE_OF_EXPECTED_CLAIMS,
    ActuarialTablesStore,
    PortfolioSimulator,
    ReserveCalculator,
    SimulationParams,
    _coerce_reserve_config,
    claims_reporting_lag_report,
    ibnr_provision,
)
from services.reserves_reporting_service import ReservesReportingService

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PHINS_ACTUARIAL_STATE_PATH", str(tmp_path / "act.json"))
    return ActuarialTablesStore()


def _policies_and_bills():
    reset_accounting_engine()
    policies = {
        "POL-IB": {
            "id": "POL-IB",
            "annual_premium": 1200.0,
            "risk_premium_annual": 900.0,
            "savings_premium_annual": 300.0,
            "pricing_source": "pricing_kernel",
        }
    }
    bills = {"BILL-IB": {"id": "BILL-IB", "policy_id": "POL-IB", "status": "paid", "amount_paid": 1000.0}}
    return policies, bills


# --- shared provision function ------------------------------------------------

def test_ibnr_provision_labels_basis_and_clamps():
    out = ibnr_provision(1000.0, 0.10, expected_claims_source="in_force_expected_claims")
    assert out == {
        "ibnr": 100.0,
        "ibnr_pct": 0.10,
        "expected_claims": 1000.0,
        "expected_claims_source": "in_force_expected_claims",
        "basis": IBNR_BASIS_SHARE_OF_EXPECTED_CLAIMS,
    }
    assert ibnr_provision(1000.0, 1.7, expected_claims_source="x")["ibnr_pct"] == 1.0
    assert ibnr_provision(1000.0, -0.2, expected_claims_source="x")["ibnr"] == 0.0


# --- audited config fields ----------------------------------------------------

def test_config_defaults_equal_previous_constants(store):
    cfg = store.config
    assert (cfg.ibnr_pct, cfg.ibnr_reporting_factor, cfg.loss_ratio_assumption) == (0.10, 0.15, 0.65)
    defaults = store.get_default_config()
    assert (defaults["ibnr_pct"], defaults["ibnr_reporting_factor"], defaults["loss_ratio_assumption"]) == (0.10, 0.15, 0.65)


def test_ibnr_pct_changes_only_via_audited_update_and_is_restorable(store):
    v0 = store.config.config_version
    result = store.update_config({"ibnr_pct": 12, "change_reason": "claims-lag calibration"}, "actuary")
    assert result["success"] is True
    assert store.config.ibnr_pct == pytest.approx(0.12)  # percentage input auto-converted
    v1 = store.config.config_version
    assert v1 != v0

    entry = store.get_audit_log()[-1]
    assert entry["action"] == "update_config"
    assert entry["details"]["change_reason"] == "claims-lag calibration"
    assert entry["details"]["old_config"]["ibnr_pct"] == pytest.approx(0.10)
    assert entry["details"]["new_config"]["ibnr_pct"] == pytest.approx(0.12)
    assert store.config_history[-1]["config"]["ibnr_pct"] == pytest.approx(0.12)

    # Clamped, fraction input accepted too.
    store.update_config({"ibnr_reporting_factor": 0.2, "loss_ratio_assumption": 250}, "actuary")
    assert store.config.ibnr_reporting_factor == pytest.approx(0.2)
    assert store.config.loss_ratio_assumption == pytest.approx(2.0)

    v2 = store.config.config_version
    # Restore the first saved revision (ibnr_pct 0.12, factor/LR still at defaults).
    restored = store.restore_config_version(v1, "actuary")
    assert restored["success"] is True
    assert store.config.ibnr_pct == pytest.approx(0.12)
    assert store.config.ibnr_reporting_factor == pytest.approx(0.15)
    assert store.config.loss_ratio_assumption == pytest.approx(0.65)
    # Forward-moving revision: the restore never reuses an old label.
    assert store.config.config_version not in {v0, v1, v2}
    assert store.get_audit_log()[-1]["action"] == "restore_config"


def test_reserve_config_defaults_ibnr_from_store_and_payload_overrides(store):
    assert _coerce_reserve_config(None, store).ibnr_pct == pytest.approx(0.10)
    store.update_config({"ibnr_pct": 0.14, "change_reason": "test"}, "actuary")
    assert _coerce_reserve_config(None, store).ibnr_pct == pytest.approx(0.14)
    assert _coerce_reserve_config({}, store).ibnr_pct == pytest.approx(0.14)
    # Per-projection override still wins, percent or fraction.
    assert _coerce_reserve_config({"ibnr_pct": 8}, store).ibnr_pct == pytest.approx(0.08)
    assert _coerce_reserve_config({"ibnr_pct": 0.05}, store).ibnr_pct == pytest.approx(0.05)


def test_reserve_projection_reports_ibnr_basis(store):
    sim = PortfolioSimulator(store).generate_portfolio(SimulationParams(
        customer_count=60, age_min=25, age_max=55, age_mean=40.0, age_std=8.0,
        coverage_min=100_000, coverage_max=300_000, coverage_median=200_000,
        policy_term_mode="fixed", policy_term_fixed=10, savings_allocation_pct=0.0))
    proj = ReserveCalculator(store).project(sim, _coerce_reserve_config({"projection_years": 3}, store))
    basis = proj["ibnr_basis"]
    assert basis["basis"] == IBNR_BASIS_SHARE_OF_EXPECTED_CLAIMS
    assert basis["expected_claims_source"] == "in_force_expected_claims"
    assert basis["ibnr_pct"] == pytest.approx(0.10)
    assert basis["config_default_ibnr_pct"] == pytest.approx(0.10)
    for row in proj["yearly_projection"]:
        assert row["ibnr_provision"] == pytest.approx(0.10 * row["in_force_expected_claims"], abs=0.02)


# --- reserves_reporting characterisation --------------------------------------

def test_reserves_reporting_ibnr_unchanged_at_defaults_with_and_without_store(store):
    policies, bills = _policies_and_bills()
    without = ReservesReportingService(policies=policies, claims={}, bills=bills)
    s0 = without.calculate_reserve_summary()
    # Previous formula: gross risk reserve × 0.65 × 0.15, cent-quantised.
    expected = (s0.gross_risk_reserve * Decimal("0.65") * Decimal("0.15")).quantize(Decimal("0.01"))
    assert s0.gross_risk_reserve > 0
    assert s0.claims_reserve_ibnr == expected
    assert without.ibnr_assumptions_used["source"] == "service_defaults"
    assert without.ibnr_assumptions_used["basis"] == IBNR_BASIS_SHARE_OF_EXPECTED_CLAIMS

    policies, bills = _policies_and_bills()
    with_store = ReservesReportingService(policies=policies, claims={}, bills=bills, actuarial_service=store)
    s1 = with_store.calculate_reserve_summary()
    assert s1.claims_reserve_ibnr == expected
    assert with_store.ibnr_assumptions_used["source"] == f"actuarial_config:{store.config.config_version}"
    assert with_store.ibnr_assumptions_used["loss_ratio_assumption"] == pytest.approx(0.65)
    assert with_store.ibnr_assumptions_used["ibnr_reporting_factor"] == pytest.approx(0.15)

    report = with_store.generate_full_report()
    cr = report["claims_reserves"]
    assert cr["ibnr_methodology"] == "Annual Premium × Loss Ratio (65%) × IBNR Factor (15%)"
    assert cr["ibnr_assumptions"]["source"].startswith("actuarial_config:")
    assert report["status"]["loss_performance_target_pct"] == pytest.approx(65.0)


def test_reserves_reporting_follows_audited_assumption_change(store):
    store.update_config({"loss_ratio_assumption": 0.70, "ibnr_reporting_factor": 0.20,
                         "change_reason": "monte_carlo_evaluation move=act_lr_assumption"}, "actuary")
    policies, bills = _policies_and_bills()
    svc = ReservesReportingService(policies=policies, claims={}, bills=bills, actuarial_service=store)
    summary = svc.calculate_reserve_summary()
    expected = (summary.gross_risk_reserve * Decimal("0.70") * Decimal("0.20")).quantize(Decimal("0.01"))
    assert summary.claims_reserve_ibnr == expected
    report = svc.generate_full_report()
    assert report["claims_reserves"]["ibnr_methodology"] == "Annual Premium × Loss Ratio (70%) × IBNR Factor (20%)"
    assert report["status"]["loss_performance_target_pct"] == pytest.approx(70.0)
    # Loss-ratio recommendation threshold follows the same assumption.
    assert all("target 65%" not in r for r in report["status"]["recommendations"])


# --- observed claims lag → implied IBNR ---------------------------------------

def _claims(lags_days, base="2026-01-10"):
    t0 = datetime.fromisoformat(base)
    out = {}
    for i, lag in enumerate(lags_days):
        incident = t0 + timedelta(days=i)
        out[f"CLM-{i}"] = {
            "incident_date": incident.date().isoformat(),
            "reported_date": (incident + timedelta(days=lag)).date().isoformat(),
            "status": "approved",
        }
    return out


def test_claims_lag_report_insufficient_data_proposes_nothing(store):
    claims = _claims([10, 20, 30])
    claims["CLM-nodates"] = {"status": "pending"}
    claims["CLM-negative"] = {"incident_date": "2026-03-01", "reported_date": "2026-02-01"}
    report = claims_reporting_lag_report(claims, store)
    assert report["read_only"] is True
    assert report["sample_size"] == 3
    assert report["claims_without_both_dates"] == 2
    assert report["insufficient_data"] is True
    assert "proposed_ibnr_pct" not in report
    assert report["lag_days"]["p50"] == 20.0
    # E[min(lag,365)]/365 = 20/365
    assert report["implied_ibnr_pct_of_annual_claims"] == pytest.approx(20 / 365, abs=1e-4)
    assert report["current_config"]["ibnr_pct"] == pytest.approx(0.10)
    assert report["current_vs_implied"]["current_ibnr_pct_covers_implied"] is True

    empty = claims_reporting_lag_report({}, store)
    assert empty["sample_size"] == 0 and empty["lag_days"] is None
    assert empty["implied_ibnr_pct_of_annual_claims"] is None


def test_claims_lag_report_proposes_from_observed_lags(store):
    # 40 claims with a 73-day lag: implied share exactly 0.2 (> current 0.10).
    report = claims_reporting_lag_report(_claims([73] * 40), store)
    assert report["insufficient_data"] is False
    assert report["implied_ibnr_pct_of_annual_claims"] == pytest.approx(0.2, abs=1e-4)
    assert report["current_vs_implied"]["current_ibnr_pct_covers_implied"] is False
    assert report["proposed_ibnr_pct"] == pytest.approx(0.20)
    assert report["adjust_via"].startswith("POST /api/actuarial/config")
    # Nothing was written to the config by producing the report.
    assert store.config.ibnr_pct == pytest.approx(0.10)
    assert len(store.config_history) <= 1


class TestClaimsLagRoute:
    def test_requires_privileged_role(self):
        resp = requests.get(f"{BASE_URL}/api/actuarial/claims-lag")
        assert resp.status_code == 403
        assert set(resp.json()) == {"error"}

    def test_admin_gets_read_only_report(self):
        login = requests.post(f"{BASE_URL}/api/login", json={"username": "admin", "password": "admin123"})
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        resp = requests.get(f"{BASE_URL}/api/actuarial/claims-lag", headers=headers, timeout=30)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        lag = body["claims_lag"]
        assert lag["read_only"] is True
        assert {"sample_size", "insufficient_data", "current_config", "basis", "adjust_via"} <= set(lag)
        assert {"ibnr_pct", "ibnr_reporting_factor", "loss_ratio_assumption"} <= set(lag["current_config"])
