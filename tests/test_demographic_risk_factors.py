"""Demographic risk factors (smoking / sex / ethnicity) in the pricing kernel."""

from __future__ import annotations

import pytest

from services.actuarial_service import ActuarialTablesStore, get_contract_specification
from services.actuarial_persistence import load_actuarial_store
from services.pricing_kernel import (
    PricingConfig,
    PricingCustomer,
    get_product,
    price_policy,
    pricing_config_from_underwriting,
    resolve_demographic_rate_factors,
    table_set_from_store,
)


@pytest.fixture()
def store_tables(tmp_path, monkeypatch):
    state = tmp_path / "actuarial_store_state.json"
    monkeypatch.setenv("PHINS_ACTUARIAL_STATE_PATH", str(state))
    store = ActuarialTablesStore()
    return store, table_set_from_store(store), state


def _price(tables, cfg, **cust_kw):
    product = get_product("phins_pure_risk_adjustable")
    cust = PricingCustomer(
        age=cust_kw.get("age", 40),
        coverage=500_000,
        term_years=10,
        adl_level=5,
        gender=cust_kw.get("gender"),
        smoking_status=cust_kw.get("smoking_status"),
        ethnicity=cust_kw.get("ethnicity"),
    )
    return price_policy(cust, product, tables, cfg)


def test_defaults_are_neutral_when_attributes_unset(store_tables):
    store, tables, _ = store_tables
    cfg = pricing_config_from_underwriting(store.config, savings_rate=0.0)
    base = _price(tables, cfg)
    demo = resolve_demographic_rate_factors(
        PricingCustomer(age=40, coverage=500_000, term_years=10), cfg
    )
    assert demo["mortality_factor"] == pytest.approx(1.0)
    assert demo["disability_factor"] == pytest.approx(1.0)
    assert base.demographic_mortality_factor == pytest.approx(1.0)
    assert base.integrity_checks.get("demographic_factors_non_negative") is True


def test_smoker_mortality_factor_raises_life_premium_only_when_set(store_tables):
    store, tables, _ = store_tables
    cfg = pricing_config_from_underwriting(store.config, savings_rate=0.0)
    cfg.smoker_mortality_factor = 2.0
    cfg.smoker_disability_factor = 1.0
    nonsmoker = _price(tables, cfg, smoking_status="never")
    smoker = _price(tables, cfg, smoking_status="current")
    assert smoker.mortality_premium_annual > nonsmoker.mortality_premium_annual
    assert smoker.demographic_mortality_factor == pytest.approx(2.0)
    assert smoker.smoking_status_used == "smoker"
    assert smoker.integrity_hash != nonsmoker.integrity_hash


def test_sex_and_ethnicity_compose_independently(store_tables):
    _, tables, _ = store_tables
    cfg = PricingConfig(
        savings_rate=0.0,
        male_mortality_factor=1.2,
        female_mortality_factor=0.9,
        ethnicity_mortality_factors={
            "caucasian": 1.0,
            "african": 1.1,
            "hispanic": 1.0,
            "asian": 1.0,
            "other": 1.0,
        },
        ethnicity_disability_factors={
            "caucasian": 1.0,
            "african": 1.05,
            "hispanic": 1.0,
            "asian": 1.0,
            "other": 1.0,
        },
        smoker_disability_factor=1.5,
        disability_share_of_life=0.25,
        disability_share_of_life_post65=1.0,
    )
    male_af = _price(
        tables, cfg, gender="male", ethnicity="african", smoking_status="current"
    )
    assert male_af.demographic_mortality_factor == pytest.approx(1.2 * 1.1)  # sex × eth
    assert male_af.demographic_disability_factor == pytest.approx(1.5 * 1.05)
    assert male_af.gender_used == "male"
    assert male_af.ethnicity_used == "african"


def test_dashboard_update_persists_demographic_factors(store_tables):
    store, _, state = store_tables
    result = store.update_config(
        {
            "smoker_mortality_factor": 1.75,
            "smoker_disability_factor": 1.4,
            "female_mortality_factor": 0.85,
            "ethnicity_mortality_factors": {"asian": 0.95, "african": 1.1},
        },
        user="pytest",
    )
    assert result["success"] is True
    assert store.config.smoker_mortality_factor == pytest.approx(1.75)
    assert store.config.ethnicity_mortality_factors["asian"] == pytest.approx(0.95)

    restored = ActuarialTablesStore()
    assert load_actuarial_store(restored, str(state)) is True
    assert restored.config.smoker_mortality_factor == pytest.approx(1.75)
    assert restored.config.female_mortality_factor == pytest.approx(0.85)
    assert restored.config.ethnicity_mortality_factors["african"] == pytest.approx(1.1)


def test_partial_ethnicity_update_merges_not_resets(store_tables):
    """Omitted ethnicity keys must keep previously tuned multipliers."""
    store, _, _ = store_tables
    store.update_config(
        {"ethnicity_mortality_factors": {"asian": 0.9, "african": 1.2}},
        user="pytest",
    )
    store.update_config(
        {"ethnicity_mortality_factors": {"asian": 0.95}},
        user="pytest",
    )
    factors = store.config.ethnicity_mortality_factors
    assert factors["asian"] == pytest.approx(0.95)
    assert factors["african"] == pytest.approx(1.2)
    assert factors["caucasian"] == pytest.approx(1.0)


def test_contract_spec_exposes_demographic_factors():
    spec = get_contract_specification()
    demo = spec.get("demographic_risk_factors") or {}
    assert demo.get("integrity_hashed") is True
    assert "smoker_mortality_factor" in demo
    assert "ethnicity_mortality_factors" in demo
