"""
Loss-ratio and reserve *bases* are labelled next to the numbers they describe.

Remediation items B and C (docs/monte_carlo_remediation_assessment.md): PHINS
had two "annual expected claims" definitions and two unrelated quantities
named ``reserve_requirement``. These tests pin the additive labels and the new
year-1 figure, and assert that the pre-existing keys are numerically unchanged.
"""

from __future__ import annotations

import pytest

from services import kpi_definitions as kpi
from services.actuarial_service import (
    LOSS_RATIO_BASIS_LIFETIME_ANNUALISED,
    LOSS_RATIO_BASIS_YEAR1,
    RESERVE_REQUIREMENT_BASIS,
    RESERVE_REQUIREMENT_MULTIPLE,
    PortfolioSimulator,
    SimulationParams,
    calculate_reinsurance_program,
)
from services import pricing_kernel as pk
from services.actuarial_service import ActuarialTablesStore


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Fresh store with default tables/config, isolated from other tests' promotions."""
    monkeypatch.setenv("PHINS_ACTUARIAL_STATE_PATH", str(tmp_path / "act.json"))
    return ActuarialTablesStore()


def _sim(store, term: int = 10, n: int = 80):
    return PortfolioSimulator(store).generate_portfolio(SimulationParams(
        customer_count=n, age_min=25, age_max=55, coverage_min=100_000, coverage_max=300_000,
        coverage_median=200_000, policy_term_mode="fixed", policy_term_fixed=term))


def test_risk_metrics_carry_both_loss_ratio_bases_and_reserve_basis(store):
    rm = _sim(store)["risk_metrics"]
    assert rm["loss_ratio_basis"] == LOSS_RATIO_BASIS_LIFETIME_ANNUALISED == "lifetime_annualised"
    assert rm["loss_ratio_year1_basis"] == LOSS_RATIO_BASIS_YEAR1 == "year1_attained_age"
    assert rm["reserve_requirement_basis"] == RESERVE_REQUIREMENT_BASIS == "pv_full_term_x1.5"
    assert rm["reserve_requirement_multiple"] == RESERVE_REQUIREMENT_MULTIPLE == 1.5
    # Both bases are documented in the canonical KPI module.
    assert rm["loss_ratio_basis"] in kpi.LOSS_RATIO_BASES
    assert rm["loss_ratio_year1_basis"] in kpi.LOSS_RATIO_BASES
    assert "paid_claims" in kpi.LOSS_RATIO_BASES


def test_existing_keys_are_numerically_unchanged(store):
    """Additive change: the legacy figures keep their formulas."""
    rm = _sim(store)["risk_metrics"]
    assert rm["reserve_requirement"] == pytest.approx(round(rm["total_expected_claims"] * 1.5, 2), abs=0.02)
    assert rm["annual_expected_claims"] == pytest.approx(rm["total_expected_claims"] / rm["avg_term_years"], rel=0.02)
    assert rm["loss_ratio_on_risk"] == pytest.approx(
        round(rm["annual_expected_claims"] / rm["total_risk_premium"] * 100, 2), abs=0.5)
    assert rm["loss_ratio_year1_on_risk"] == pytest.approx(
        round(rm["expected_claims_year1"] / rm["total_risk_premium"] * 100, 2), abs=0.5)


def test_year1_loss_ratio_is_below_lifetime_annualised_for_an_ageing_book(store):
    """Year-1 claims at current ages are cheaper than the level-annualised lifetime
    figure, because the latter averages in older attained ages."""
    rm = _sim(store, term=20, n=120)["risk_metrics"]
    assert rm["expected_claims_year1"] > 0
    assert rm["loss_ratio_year1"] > 0
    assert rm["loss_ratio_year1"] < rm["loss_ratio"]
    assert rm["loss_ratio_year1_on_risk"] >= rm["loss_ratio_year1"]


def test_kernel_year1_expected_claims_is_undiscounted_first_year_cost(store):
    config = pk.pricing_config_from_underwriting(store.config)
    product = pk.get_product("phins_pure_risk_adjustable")
    tables = pk.table_set_from_store(store)
    cust = pk.PricingCustomer(age=40, coverage=200_000, term_years=10, adl_level=1)
    comp = pk.price_policy(cust, product, tables, config)
    assert comp.expected_claims_year1 > 0
    # Year-1 cost cannot exceed the full-term PV grossed up by one year of discount.
    assert comp.expected_claims_year1 <= comp.pv_total_risk_claims * (1 + config.discount_rate) + 0.01
    # The integrity hash is built from an explicit key list; the new field does not enter it.
    assert "expected_claims_year1" not in comp.integrity_hash
    assert comp.as_dict()["expected_claims_year1"] == comp.expected_claims_year1


def test_reinsurance_program_states_its_loss_ratio_basis(store):
    sim = _sim(store)
    prog = calculate_reinsurance_program(sim, store)
    rm = sim["risk_metrics"]
    assert prog["loss_ratio_basis"] == rm["loss_ratio_basis"]
    assert prog["loss_ratio_pct"] == pytest.approx(rm["loss_ratio"], abs=0.01)
    assert prog["loss_ratio_year1_pct"] == rm["loss_ratio_year1"]
    assert prog["reserve_requirement_basis"] == RESERVE_REQUIREMENT_BASIS
    # reserve_relief still derives from the (labelled) reserve_requirement.
    share = prog["protected_claims_pct"] / 100.0
    assert prog["reserve_relief_estimate"] == pytest.approx(rm["reserve_requirement"] * share, rel=1e-6, abs=0.02)


def test_financial_reporting_capital_indication_is_labelled_distinctly():
    from services.financial_reporting_service import FinancialReportingService
    policies = {"POL1": {"status": "active", "coverage": 100_000, "annual_premium": 1_200, "policy_type": "life"}}
    svc = FinancialReportingService(policies=policies, claims={}, billing={}, customers={}, underwriting={})
    summary = svc.generate_portfolio_report()["summary"]
    assert summary["reserve_requirement"] == pytest.approx(
        summary["total_coverage"] * 0.05 + summary["total_savings_liability"], abs=0.01)
    assert summary["reserve_requirement_basis"] == "coverage_x0.05_plus_savings_liability"
    assert "Capital indication" in summary["reserve_requirement_label"]
