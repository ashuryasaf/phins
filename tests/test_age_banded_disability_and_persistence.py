"""Age-banded L:D (1:4 / 1:1) + durable actuarial config persistence."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from services.actuarial_service import (
    ActuarialTablesStore,
    UnderwritingConfig,
    get_actuarial_store,
    get_contract_specification,
)
from services.actuarial_persistence import load_actuarial_store, persist_actuarial_store
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


def test_issue_age_65_uses_one_to_one_disability_sum(fresh_store):
    store, _ = fresh_store
    tables = table_set_from_store(store)
    cfg = pricing_config_from_underwriting(store.config)
    product = get_product("phins_pure_risk_adjustable")
    cust = PricingCustomer(age=65, coverage=500_000, term_years=10, adl_level=5)
    comps = price_policy(cust, product, tables, cfg)
    assert comps.disability_share_used == pytest.approx(1.0)
    assert comps.disability_sum_used == pytest.approx(500_000.0)
    assert comps.disability_premium_annual > 0.0


def test_issue_age_35_stays_one_to_four(fresh_store):
    store, _ = fresh_store
    tables = table_set_from_store(store)
    cfg = pricing_config_from_underwriting(store.config)
    product = get_product("phins_pure_risk_adjustable")
    cust = PricingCustomer(age=35, coverage=500_000, term_years=20, adl_level=5)
    comps = price_policy(cust, product, tables, cfg)
    assert comps.disability_share_used == pytest.approx(0.25)
    assert comps.disability_sum_used == pytest.approx(125_000.0)


def test_dashboard_config_update_persists_and_reloads(fresh_store):
    store, state_path = fresh_store
    result = store.update_config(
        {"disability_share_of_life": 0.20, "disability_share_of_life_post65": 1.0},
        user="pytest",
    )
    assert result["success"] is True
    assert state_path.exists()
    assert store.config.disability_share_of_life == pytest.approx(0.20)
    assert store.config.config_version != "cfg_v1"

    restored = ActuarialTablesStore()
    assert load_actuarial_store(restored, str(state_path)) is True
    assert restored.config.disability_share_of_life == pytest.approx(0.20)
    assert restored.config.disability_share_of_life_post65 == pytest.approx(1.0)
    assert restored.config.config_version == store.config.config_version


def test_adjustable_post65_share_changes_price(fresh_store):
    store, _ = fresh_store
    tables = table_set_from_store(store)
    product = get_product("phins_pure_risk_adjustable")
    cust = PricingCustomer(age=70, coverage=500_000, term_years=10, adl_level=5)

    cfg_full = PricingConfig(
        disability_share_of_life=0.25,
        disability_share_of_life_post65=1.0,
        disability_band_age=65,
        version="t1",
    )
    cfg_half = PricingConfig(
        disability_share_of_life=0.25,
        disability_share_of_life_post65=0.5,
        disability_band_age=65,
        version="t2",
    )
    full = price_policy(cust, product, tables, cfg_full)
    half = price_policy(cust, product, tables, cfg_half)
    assert full.disability_sum_used == pytest.approx(500_000.0)
    assert half.disability_sum_used == pytest.approx(250_000.0)
    assert full.pv_disability_claims > half.pv_disability_claims
    assert full.integrity_hash != half.integrity_hash


def test_contract_spec_exposes_age_bands():
    # Uses global store; bands should be present even if defaults.
    spec = get_contract_specification()
    ratios = spec.get("contract_ratios") or {}
    assert "disability_share_of_life_post65" in ratios
    assert ratios.get("disability_to_life_ratio_post65_display") in ("1:1", "1.0000") or ratios.get(
        "disability_share_of_life_post65"
    ) == pytest.approx(1.0)
