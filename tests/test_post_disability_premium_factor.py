"""Post-disability claim interaction + premium factor (defaults preserve combined)."""

from __future__ import annotations

import os

import pytest

from services.actuarial_service import (
    get_actuarial_store,
    get_contract_specification,
    resolve_disability_claim_outcome,
)
from services.pricing_kernel import (
    PricingCustomer,
    get_product,
    price_policy,
    pricing_config_from_underwriting,
    table_set_from_store,
)


@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    monkeypatch.setenv("PHINS_ACTUARIAL_STATE_PATH", str(tmp_path / "act.json"))
    import services.actuarial_service as a

    a._actuarial_store = None
    yield
    a._actuarial_store = None


def test_default_post_disability_keeps_combined_premium():
    """Default factor 1.0 → ongoing premium equals pre-claim combined."""
    store = get_actuarial_store()
    assert store.config.post_disability_premium_factor == pytest.approx(1.0)
    assert store.config.post_disability_life_share_of_face == pytest.approx(0.75)
    assert store.config.pre65_disability_continues_policy is True
    assert store.config.post65_claims_mutually_exclusive is True

    combined = 172.50
    out = resolve_disability_claim_outcome(500_000, 50, combined, store.config)
    assert out["mode"] == "acceleration_pre65"
    assert out["disability_paid"] == pytest.approx(125_000.0)
    assert out["remaining_life_sum"] == pytest.approx(375_000.0)
    assert out["policy_continues"] is True
    assert out["ongoing_premium"] == pytest.approx(combined)
    assert out["premium_unchanged_vs_combined"] is True
    assert out["data_integrity"]["ongoing_premium_equals_factor_times_combined"]
    assert out["data_integrity"]["pre65_remaining_is_face_times_share"]
    assert out["data_integrity"]["default_premium_factor_is_unity_preserving_combined"]


def test_post65_mutually_exclusive_ends_policy():
    store = get_actuarial_store()
    out = resolve_disability_claim_outcome(500_000, 70, 104.06, store.config)
    assert out["mode"] == "mutually_exclusive_post65"
    assert out["disability_paid"] == pytest.approx(125_000.0)
    assert out["remaining_life_sum"] == 0.0
    assert out["policy_continues"] is False
    assert out["ongoing_premium"] == 0.0


def test_adjustable_premium_factor_changes_ongoing_only():
    store = get_actuarial_store()
    # 75% of combined after disability
    result = store.update_config({"post_disability_premium_factor": 0.75}, user="test")
    assert result["success"]
    assert store.config.post_disability_premium_factor == pytest.approx(0.75)

    combined = 200.0
    out = resolve_disability_claim_outcome(500_000, 40, combined, store.config)
    assert out["ongoing_premium"] == pytest.approx(150.0)
    assert out["premium_unchanged_vs_combined"] is False
    assert out["data_integrity"]["default_premium_factor_is_unity_preserving_combined"] is False

    # Healthy-life quote PV still uses mutually exclusive — unchanged by factor
    tables = table_set_from_store(store)
    cfg = pricing_config_from_underwriting(store.config)
    assert cfg.post_disability_premium_factor == pytest.approx(0.75)
    assert cfg.claim_model.value == "mutually_exclusive"
    product = get_product("phins_pure_risk_adjustable")
    priced = price_policy(
        PricingCustomer(age=40, coverage=500_000, term_years=10, adl_level=5),
        product,
        tables,
        cfg,
    )
    assert priced.annual_premium > 0
    assert priced.post_disability_premium_factor == pytest.approx(0.75)
    assert priced.integrity_hash


def test_contract_specification_surfaces_claim_interaction():
    spec = get_contract_specification()
    ci = spec["claim_interaction"]
    assert ci["post_disability_premium_factor"] == pytest.approx(1.0)
    assert ci["post_disability_life_share_of_face"] == pytest.approx(0.75)
    assert ci["pre65_disability_continues_policy"] is True
    assert ci["post65_claims_mutually_exclusive"] is True
    assert "100.0% of combined" in ci["post_disability_premium_factor_display"]
    assert ci["example_pre65"]["remaining_life"] == pytest.approx(375_000.0)


def test_percent_input_normalizes_to_factor():
    store = get_actuarial_store()
    store.update_config({"post_disability_premium_factor": 100}, user="test")
    assert store.config.post_disability_premium_factor == pytest.approx(1.0)
    store.update_config({"post_disability_premium_factor": 80}, user="test")
    assert store.config.post_disability_premium_factor == pytest.approx(0.80)


def test_pre65_continuation_off_terminates_policy():
    store = get_actuarial_store()
    store.update_config({"pre65_disability_continues_policy": False}, user="test")
    out = resolve_disability_claim_outcome(500_000, 50, 172.50, store.config)
    assert out["mode"] == "single_claim_pre65"
    assert out["policy_continues"] is False
    assert out["ongoing_premium"] == 0.0
    assert out["remaining_life_sum"] == 0.0


def test_post65_non_exclusive_continues_at_post65_life_sum():
    store = get_actuarial_store()
    store.update_config({"post65_claims_mutually_exclusive": False}, user="test")
    out = resolve_disability_claim_outcome(500_000, 70, 104.06, store.config)
    assert out["mode"] == "continuation_post65"
    assert out["policy_continues"] is True
    assert out["remaining_life_sum"] == pytest.approx(125_000.0)
    assert out["ongoing_premium"] == pytest.approx(104.06)
