"""Classic apply.html quotes and issues from the actuarial kernel.

Chat submissions (application_channel=chat) keep the flag-gated flat path.
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


def test_chat_calculate_premium_stays_flat_without_flag(monkeypatch):
    monkeypatch.delenv("PHINS_KERNEL_BILLING_ENABLED", raising=False)
    chat = dict(CLASSIC_PAYLOAD, application_channel="chat")
    billed = calculate_premium(chat)
    assert billed["pricing_source"] == "flat_formula"
    kernel = price_application_with_kernel(chat)
    assert kernel
    assert billed["monthly"] != pytest.approx(kernel["monthly"])


def test_unlabeled_calculate_premium_stays_flat(monkeypatch):
    monkeypatch.delenv("PHINS_KERNEL_BILLING_ENABLED", raising=False)
    unlabeled = dict(CLASSIC_PAYLOAD)
    unlabeled.pop("application_channel")
    billed = calculate_premium(unlabeled)
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
