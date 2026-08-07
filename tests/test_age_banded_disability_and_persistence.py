"""Age-banded life step-down + D=life post-65 + durable actuarial persistence."""

from __future__ import annotations

import pytest

from services.actuarial_service import (
    ActuarialTablesStore,
    get_contract_specification,
)
from services.actuarial_persistence import load_actuarial_store
from services.pricing_kernel import (
    PricingConfig,
    PricingCustomer,
    get_product,
    price_policy,
    pricing_config_from_underwriting,
    table_set_from_store,
)


@pytest.fixture()
def fresh_store(tmp_path, monkeypatch):
    state = tmp_path / "actuarial_store_state.json"
    monkeypatch.setenv("PHINS_ACTUARIAL_STATE_PATH", str(state))
    store = ActuarialTablesStore()
    return store, state


def test_issue_age_65_life_steps_to_quarter_disability_equals_life(fresh_store):
    """Opposite of prior D-step-up: at 65 life→$125k and D stays = life $125k."""
    store, _ = fresh_store
    tables = table_set_from_store(store)
    cfg = pricing_config_from_underwriting(store.config)
    product = get_product("phins_pure_risk_adjustable")
    cust = PricingCustomer(age=65, coverage=500_000, term_years=10, adl_level=5)
    comps = price_policy(cust, product, tables, cfg)
    assert comps.life_share_used == pytest.approx(0.25)
    assert comps.life_sum_used == pytest.approx(125_000.0)
    assert comps.disability_share_used == pytest.approx(1.0)
    assert comps.disability_sum_used == pytest.approx(125_000.0)
    assert comps.disability_premium_annual > 0.0


def test_issue_age_35_full_life_and_one_to_four(fresh_store):
    store, _ = fresh_store
    tables = table_set_from_store(store)
    cfg = pricing_config_from_underwriting(store.config)
    product = get_product("phins_pure_risk_adjustable")
    cust = PricingCustomer(age=35, coverage=500_000, term_years=20, adl_level=5)
    comps = price_policy(cust, product, tables, cfg)
    assert comps.life_share_used == pytest.approx(1.0)
    assert comps.life_sum_used == pytest.approx(500_000.0)
    assert comps.disability_share_used == pytest.approx(0.25)
    assert comps.disability_sum_used == pytest.approx(125_000.0)


def test_dashboard_config_update_persists_life_and_disability_bands(fresh_store):
    store, state_path = fresh_store
    result = store.update_config(
        {
            "disability_share_of_life": 0.20,
            "disability_share_of_life_post65": 1.0,
            "life_share_of_coverage": 1.0,
            "life_share_of_coverage_post65": 0.25,
        },
        user="pytest",
    )
    assert result["success"] is True
    assert state_path.exists()
    assert store.config.disability_share_of_life == pytest.approx(0.20)
    assert store.config.life_share_of_coverage_post65 == pytest.approx(0.25)
    assert store.config.config_version != "cfg_v1"

    restored = ActuarialTablesStore()
    assert load_actuarial_store(restored, str(state_path)) is True
    assert restored.config.disability_share_of_life == pytest.approx(0.20)
    assert restored.config.disability_share_of_life_post65 == pytest.approx(1.0)
    assert restored.config.life_share_of_coverage_post65 == pytest.approx(0.25)
    assert restored.config.config_version == store.config.config_version


def test_adjustable_post65_life_share_changes_sums(fresh_store):
    store, _ = fresh_store
    tables = table_set_from_store(store)
    product = get_product("phins_pure_risk_adjustable")
    cust = PricingCustomer(age=70, coverage=500_000, term_years=10, adl_level=5)

    cfg_quarter = PricingConfig(
        disability_share_of_life=0.25,
        disability_share_of_life_post65=1.0,
        life_share_of_coverage=1.0,
        life_share_of_coverage_post65=0.25,
        disability_band_age=65,
        version="t1",
    )
    cfg_half_life = PricingConfig(
        disability_share_of_life=0.25,
        disability_share_of_life_post65=1.0,
        life_share_of_coverage=1.0,
        life_share_of_coverage_post65=0.5,
        disability_band_age=65,
        version="t2",
    )
    quarter = price_policy(cust, product, tables, cfg_quarter)
    half = price_policy(cust, product, tables, cfg_half_life)
    assert quarter.life_sum_used == pytest.approx(125_000.0)
    assert quarter.disability_sum_used == pytest.approx(125_000.0)
    assert half.life_sum_used == pytest.approx(250_000.0)
    assert half.disability_sum_used == pytest.approx(250_000.0)
    assert half.pv_mortality_claims > quarter.pv_mortality_claims
    assert quarter.integrity_hash != half.integrity_hash


def test_contract_spec_exposes_life_and_disability_bands():
    spec = get_contract_specification()
    ratios = spec.get("contract_ratios") or {}
    assert "disability_share_of_life_post65" in ratios
    assert "life_share_of_coverage_post65" in ratios
    assert ratios.get("life_share_of_coverage_post65") == pytest.approx(0.25)
    assert ratios.get("example_post65_life") == pytest.approx(125_000.0)
    assert ratios.get("example_post65_disability") == pytest.approx(125_000.0)
    assert ratios.get("disability_to_life_ratio_post65_display") in ("1:1", "1.0000") or ratios.get(
        "disability_share_of_life_post65"
    ) == pytest.approx(1.0)


def test_bare_pricing_config_keeps_legacy_hybrid_cutoff(fresh_store):
    """FRS / bare PricingConfig must not silently adopt Draft 3.1 post-65 shares."""
    store, _ = fresh_store
    tables = table_set_from_store(store)
    cfg = PricingConfig()  # both post65 shares default to None
    assert cfg.life_share_of_coverage_post65 is None
    assert cfg.disability_share_of_life_post65 is None
    product = get_product("phins_hybrid_savings")
    senior = price_policy(
        PricingCustomer(age=65, coverage=500_000, term_years=10, adl_level=5),
        product,
        tables,
        cfg,
    )
    # Legacy: full life cover, disability cut off at product.disability_cutoff_age.
    assert senior.life_sum_used == pytest.approx(500_000.0)
    assert senior.disability_sum_used == pytest.approx(0.0)
    assert senior.disability_premium_annual == pytest.approx(0.0)
