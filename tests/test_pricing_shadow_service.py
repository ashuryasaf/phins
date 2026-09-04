"""Shadow dual-run: kernel snapshot beside flat premiums, fail-open."""

from __future__ import annotations

import os

import pytest

from services.pricing_shadow_service import (
    build_shadow_snapshot,
    is_kernel_billing_enabled,
    is_shadow_enabled,
    map_policy_type_to_product,
    record_shadow_snapshot,
    reset_shadow_store_for_tests,
)


@pytest.fixture(autouse=True)
def _clean_shadow(monkeypatch, tmp_path):
    reset_shadow_store_for_tests()
    monkeypatch.setenv("PHINS_PRICING_SHADOW_ENABLED", "1")
    monkeypatch.setenv("PHINS_ACTUARIAL_STATE_PATH", str(tmp_path / "act.json"))
    yield
    reset_shadow_store_for_tests()


def test_map_policy_types():
    assert map_policy_type_to_product("life") == "phins_pure_risk_adjustable"
    assert map_policy_type_to_product("auto") is None


def test_build_shadow_snapshot_preserves_flat_and_records_kernel():
    policy = {
        "id": "POL-TEST-1",
        "customer_id": "CUST-1",
        "type": "life",
        "coverage_amount": 500000,
        "age": 35,
        "term_years": 20,
        "adl_level": 5,
        "annual_premium": 1725.0,
        "monthly_premium": 143.75,
    }
    flat = {"annual": 1725.0, "monthly": 143.75, "quarterly": 418.31}
    snap = build_shadow_snapshot(policy, flat)
    assert snap is not None
    assert snap["flat_annual"] == 1725.0
    # Kernel uses age-banded PV pricing (life + disability); may be above or
    # below the legacy flat life-only $0.25/1000 quote — both must be recorded.
    assert snap["kernel_annual"] > 0
    assert snap["flat_annual"] > 0
    assert "delta_annual" in snap
    assert snap["delta_annual"] == pytest.approx(
        round(snap["kernel_annual"] - snap["flat_annual"], 2)
    )
    assert snap["product_id"] == "phins_pure_risk_adjustable"
    assert snap["integrity_hash"]
    assert snap["disability_share_used"] == pytest.approx(0.25)
    assert len(snap["payload_sha256"]) == 64


def test_extract_age_defaults_match_flat_and_preserve_zero():
    from services.pricing_shadow_service import extract_application_pricing_inputs

    missing = extract_application_pricing_inputs({"type": "life", "coverage_amount": 100000})
    assert missing["age"] == 30  # matches calculate_premium default
    zero = extract_application_pricing_inputs(
        {"type": "life", "coverage_amount": 100000, "age": 0}
    )
    assert zero["age"] == 0


def test_kernel_billing_default_off(monkeypatch):
    monkeypatch.delenv("PHINS_KERNEL_BILLING_ENABLED", raising=False)
    monkeypatch.delenv("PHINS_TEST_MODE", raising=False)
    assert is_kernel_billing_enabled() is False
    monkeypatch.setenv("PHINS_KERNEL_BILLING_ENABLED", "1")
    assert is_kernel_billing_enabled() is True


def test_every_channel_uses_kernel_unless_flag_forces_flat(monkeypatch):
    from services.pricing_shadow_service import should_use_kernel_billing

    monkeypatch.delenv("PHINS_KERNEL_BILLING_ENABLED", raising=False)
    assert should_use_kernel_billing({"application_channel": "classic"}) is True
    assert should_use_kernel_billing({"application_channel": "chat"}) is True
    assert should_use_kernel_billing({}) is True
    monkeypatch.setenv("PHINS_KERNEL_BILLING_ENABLED", "0")
    assert should_use_kernel_billing({"application_channel": "classic"}) is False
    assert should_use_kernel_billing({"application_channel": "chat"}) is False


def test_extract_age_from_customer_dob():
    from services.pricing_shadow_service import extract_application_pricing_inputs

    inputs = extract_application_pricing_inputs({
        "type": "phins_unified",
        "coverage_amount": 500000,
        "customer_dob": "1990-05-14",
    })
    assert inputs["age"] >= 35


def test_record_respects_flag_off(monkeypatch):
    monkeypatch.setenv("PHINS_PRICING_SHADOW_ENABLED", "0")
    assert is_shadow_enabled() is False
    snap = record_shadow_snapshot(
        {"id": "P1", "type": "life", "coverage_amount": 100000, "age": 40},
        {"annual": 100.0, "monthly": 10.0},
    )
    assert snap is None


def test_unmapped_type_skips():
    assert build_shadow_snapshot({"id": "P", "type": "auto", "coverage_amount": 1, "age": 30}, {"annual": 1}) is None
