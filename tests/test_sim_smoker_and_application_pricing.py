"""Simulation smoker mix + application-driven kernel pricing."""

from __future__ import annotations

import pytest

from services.actuarial_service import ActuarialTablesStore, PortfolioSimulator, SimulationParams
from services.pricing_shadow_service import (
    extract_application_pricing_inputs,
    is_kernel_billing_enabled,
    price_application_with_kernel,
)


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PHINS_ACTUARIAL_STATE_PATH", str(tmp_path / "act.json"))
    return ActuarialTablesStore()


def test_extract_application_maps_tobacco_and_gender():
    payload = {
        "type": "phins_unified",
        "coverage_amount": 500000,
        "age": 40,
        "coverage_years": 20,
        "gender": "female",
        "questionnaire": {"smoke": "yes"},
        "ethnicity": "asian",
    }
    inputs = extract_application_pricing_inputs(payload)
    assert inputs["smoking_status"] == "smoker"
    assert inputs["gender"] == "female"
    assert inputs["ethnicity"] == "asian"
    assert inputs["term_years"] == 20


def test_kernel_prices_smoker_higher_when_factor_tuned(isolated_store, monkeypatch):
    monkeypatch.delenv("PHINS_TEST_MODE", raising=False)
    monkeypatch.setenv("PHINS_KERNEL_BILLING_ENABLED", "1")
    isolated_store.update_config(
        {"smoker_mortality_factor": 2.0, "smoker_disability_factor": 1.5},
        user="pytest",
    )
    # Point get_actuarial_store at this store
    import services.actuarial_service as asvc
    monkeypatch.setattr(asvc, "get_actuarial_store", lambda: isolated_store)

    base = {
        "type": "life",
        "coverage_amount": 500000,
        "age": 40,
        "term_years": 10,
        "adl_level": 5,
        "gender": "male",
        "ethnicity": "caucasian",
    }
    nonsmoker = price_application_with_kernel({**base, "smoking_status": "nonsmoker"})
    smoker = price_application_with_kernel({**base, "smoking_status": "smoker"})
    assert nonsmoker and smoker
    assert smoker["annual"] > nonsmoker["annual"]
    assert smoker["smoking_status_used"] == "smoker"
    assert smoker["integrity_hash"] != nonsmoker["integrity_hash"]
    assert smoker["pricing_source"] == "pricing_kernel"


def test_simulation_respects_smoker_pct_and_pricing_factors(isolated_store, monkeypatch):
    isolated_store.update_config(
        {"smoker_mortality_factor": 2.0, "smoker_disability_factor": 2.0},
        user="pytest",
    )
    sim = PortfolioSimulator(isolated_store)
    params = SimulationParams(
        customer_count=400,
        age_min=30,
        age_max=40,
        age_distribution="uniform",
        smoker_pct=100.0,
        former_smoker_pct=0.0,
        male_pct=50.0,
        female_pct=50.0,
        savings_rate=0.0,
        product_id="phins_pure_risk_adjustable",
    )
    # Force deterministic age path via uniform
    result = sim.generate_portfolio(params)
    dem = result.get("demographics") or {}
    smoking = dem.get("smoking") or {}
    # All accepted customers should be smokers when smoker_pct=100
    assert smoking.get("smoker", 0) >= smoking.get("nonsmoker", 0)
    assert smoking.get("smoker", 0) > 0

    params_none = SimulationParams(
        customer_count=400,
        age_min=30,
        age_max=40,
        age_distribution="uniform",
        smoker_pct=0.0,
        former_smoker_pct=0.0,
        savings_rate=0.0,
        product_id="phins_pure_risk_adjustable",
    )
    result_none = sim.generate_portfolio(params_none)
    # All-smoker portfolio should collect more premium than all-nonsmoker when factor=2
    smoker_prem = float(result["portfolio_summary"]["total_annual_premium"])
    nonsmoker_prem = float(result_none["portfolio_summary"]["total_annual_premium"])
    assert smoker_prem > nonsmoker_prem


def test_kernel_billing_off_under_test_mode(monkeypatch):
    monkeypatch.setenv("PHINS_TEST_MODE", "1")
    monkeypatch.delenv("PHINS_KERNEL_BILLING_ENABLED", raising=False)
    assert is_kernel_billing_enabled() is False
