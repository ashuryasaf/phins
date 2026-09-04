"""Classic apply and chat issuance both bill from the actuarial kernel.

Flat formula remains only as a fail-open fallback or when
``PHINS_KERNEL_BILLING_ENABLED=0``.
"""

from __future__ import annotations

import json
from urllib.request import Request, urlopen

import pytest

from services.pricing_shadow_service import price_application_with_kernel
from web_portal.server import calculate_premium


def _base_url():
    import os
    return os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")


def _post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        _base_url() + path,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


CLASSIC_PAYLOAD = {
    "type": "phins_unified",
    "application_channel": "classic",
    "coverage_amount": 500000,
    "coverage_years": 20,
    "term_years": 20,
    "age": 36,
    "customer_dob": "1990-05-14",
    "gender": "female",
    "smoking_status": "nonsmoker",
    "risk_score": "low",
    "adl_level": 5,
    "questionnaire": {"tobacco": "no", "gender": "female"},
}


def test_classic_calculate_premium_matches_kernel(monkeypatch):
    monkeypatch.delenv("PHINS_KERNEL_BILLING_ENABLED", raising=False)
    kernel = price_application_with_kernel(CLASSIC_PAYLOAD)
    billed = calculate_premium(CLASSIC_PAYLOAD)
    assert kernel and kernel["pricing_source"] == "pricing_kernel"
    assert billed["pricing_source"] == "pricing_kernel"
    assert billed["monthly"] == pytest.approx(kernel["monthly"])
    assert billed["annual"] == pytest.approx(kernel["annual"])
    assert billed["integrity_hash"] == kernel["integrity_hash"]


def test_chat_calculate_premium_uses_kernel(monkeypatch):
    monkeypatch.delenv("PHINS_KERNEL_BILLING_ENABLED", raising=False)
    chat = dict(CLASSIC_PAYLOAD, application_channel="chat")
    billed = calculate_premium(chat)
    kernel = price_application_with_kernel(chat)
    assert kernel and kernel["pricing_source"] == "pricing_kernel"
    assert billed["pricing_source"] == "pricing_kernel"
    assert billed["monthly"] == pytest.approx(kernel["monthly"])
    assert billed["annual"] == pytest.approx(kernel["annual"])
    assert billed["integrity_hash"] == kernel["integrity_hash"]


def test_unlabeled_calculate_premium_uses_kernel(monkeypatch):
    monkeypatch.delenv("PHINS_KERNEL_BILLING_ENABLED", raising=False)
    unlabeled = dict(CLASSIC_PAYLOAD)
    unlabeled.pop("application_channel")
    billed = calculate_premium(unlabeled)
    kernel = price_application_with_kernel(unlabeled)
    assert billed["pricing_source"] == "pricing_kernel"
    assert billed["monthly"] == pytest.approx(kernel["monthly"])


def test_explicit_flag_off_forces_flat_formula(monkeypatch):
    monkeypatch.setenv("PHINS_KERNEL_BILLING_ENABLED", "0")
    billed = calculate_premium(CLASSIC_PAYLOAD)
    assert billed["pricing_source"] == "flat_formula"


def test_policies_quote_returns_kernel_for_apply_form():
    status, body = _post("/api/policies/quote", CLASSIC_PAYLOAD)
    assert status == 200
    assert body["pricing_source"] == "pricing_kernel"
    assert body["monthly"] > 0
    assert body["annual"] > 0
    assert body["tables_version"]
    assert body["integrity_hash"]
    kernel = price_application_with_kernel(CLASSIC_PAYLOAD)
    assert body["monthly"] == pytest.approx(kernel["monthly"])
    assert body["annual"] == pytest.approx(kernel["annual"])


def test_explicit_zero_savings_rate_stays_pure_risk():
    kernel = price_application_with_kernel({
        **CLASSIC_PAYLOAD,
        "savings_rate": 0,
        "savings_formula": "risk_premium_markup",
        "phins_allocation": {"savings_pct": 75},
    })
    assert kernel["savings_premium_annual"] == 0
    assert kernel["product_id"] == "phins_pure_risk_adjustable"


def test_balanced_savings_addon_is_half_of_risk_and_matches_create():
    payload = {
        **CLASSIC_PAYLOAD,
        "savings_rate": 0.5,
        "savings_formula": "risk_premium_markup",
    }
    quote_status, quote = _post("/api/policies/quote", payload)
    assert quote_status == 200
    assert quote["pricing_source"] == "pricing_kernel"
    assert quote["product_id"] == "phins_hybrid_savings"
    assert quote["savings_premium_annual"] == pytest.approx(
        quote["risk_premium_annual"] * 0.5, rel=1e-3
    )
    assert quote["annual"] > quote["risk_premium_annual"]
    create_status, created = _post("/api/policies/create", {
        **payload,
        "customer_name": "Jordan Hale",
        "customer_email": "apply-kernel-savings@example.com",
    })
    assert create_status in (200, 201)
    policy = created["policy"]
    assert policy["monthly_premium"] == pytest.approx(quote["monthly"])
    assert policy["annual_premium"] == pytest.approx(quote["annual"])
    assert policy.get("product_id") == "phins_hybrid_savings"


def test_classic_quote_without_adl_uses_assessment_default():
    omitted = dict(CLASSIC_PAYLOAD)
    omitted.pop("adl_level", None)
    status, body = _post("/api/policies/quote", omitted)
    assert status == 200
    defaulted = calculate_premium(omitted)
    assessed = calculate_premium(CLASSIC_PAYLOAD)
    assert body["pricing_source"] == "pricing_kernel"
    assert defaulted["adl_level"] == 5
    assert defaulted["monthly"] == pytest.approx(assessed["monthly"])
    assert body["monthly"] == pytest.approx(assessed["monthly"])


def test_quote_uses_adl_one_and_returns_live_store_multipliers():
    independent = dict(CLASSIC_PAYLOAD, adl_level=1)
    average = dict(CLASSIC_PAYLOAD, adl_level=5)
    status_one, quote_one = _post("/api/policies/quote", independent)
    status_five, quote_five = _post("/api/policies/quote", average)
    assert status_one == 200 and status_five == 200
    assert quote_one["pricing_source"] == "pricing_kernel"
    assert quote_one["adl_level"] == 1
    assert quote_five["adl_level"] == 5
    assert quote_one["adl_mortality_multiplier"] > 0
    assert quote_one["adl_disability_multiplier"] > 0
    assert quote_one["gender_used"] == "female"
    assert quote_one["smoking_status_used"] == "nonsmoker"
    assert quote_one["monthly"] < quote_five["monthly"]
    billed = calculate_premium(independent)
    assert billed["adl_level"] == 1
    assert billed["adl_mortality_multiplier"] == pytest.approx(
        quote_one["adl_mortality_multiplier"]
    )


def test_public_create_forces_classic_billing_channel():
    # A caller cannot post application_channel=chat (or 'web'/unknown) to
    # /api/policies/create to flip off the kernel path; the endpoint fixes the
    # billing channel server-side, so the issued premium is the kernel amount.
    status, created = _post("/api/policies/create", {
        **CLASSIC_PAYLOAD,
        "application_channel": "chat",
        "customer_name": "Jordan Hale",
        "customer_email": "apply-kernel-channel@example.com",
    })
    assert status in (200, 201)
    policy = created["policy"]
    assert policy["pricing_source"] == "pricing_kernel"
    quote_status, quote = _post("/api/policies/quote", CLASSIC_PAYLOAD)
    assert quote_status == 200
    assert policy["monthly_premium"] == pytest.approx(quote["monthly"])


def test_live_actuary_store_edits_change_classic_quote():
    from services.actuarial_service import get_actuarial_store

    store = get_actuarial_store()
    payload = dict(CLASSIC_PAYLOAD, adl_level=1)
    before = calculate_premium(payload)
    original = float(store.config.female_mortality_factor)
    store.config.female_mortality_factor = original * 1.5
    try:
        after = calculate_premium(payload)
        assert after["pricing_source"] == "pricing_kernel"
        assert after["monthly"] > before["monthly"]
        assert after["annual"] > before["annual"]
    finally:
        store.config.female_mortality_factor = original


def test_classic_create_issues_the_quoted_kernel_amount():
    status, created = _post("/api/policies/create", {
        **CLASSIC_PAYLOAD,
        "customer_name": "Jordan Hale",
        "customer_email": "apply-kernel-quote@example.com",
    })
    assert status in (200, 201)
    policy = created["policy"]
    quote_status, quote = _post("/api/policies/quote", CLASSIC_PAYLOAD)
    assert quote_status == 200
    assert policy["pricing_source"] == "pricing_kernel"
    assert policy["monthly_premium"] == pytest.approx(quote["monthly"])
    assert policy["annual_premium"] == pytest.approx(quote["annual"])
    assert policy.get("integrity_hash") == quote.get("integrity_hash")
