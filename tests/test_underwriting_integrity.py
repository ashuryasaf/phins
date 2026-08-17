"""Underwriting integrity pipeline: contradictions, reject history, contracts."""

from __future__ import annotations

import json

from services.underwriting_integrity_service import (
    apply_premium_adjustment,
    archive_rejected_application,
    build_disclosure_prompt,
    build_policy_contract,
    collect_application_media,
    detect_claim_statement_contradictions,
    detect_statement_contradictions,
    find_prior_customer_records,
)


def test_detect_smoking_contradiction_vs_prior_application():
    current = {"tobacco": "no", "occupation": "Engineer", "medications": "none"}
    prior = [{
        "id": "UW-OLD-1",
        "status": "approved",
        "questionnaire_responses": {"tobacco": "yes", "occupation": "Engineer"},
    }]
    findings = detect_statement_contradictions(current, prior)
    fields = {f["field"] for f in findings}
    assert "smoking_status" in fields


def test_claim_narrative_flags_smoker_vs_nonsmoker_statement():
    current = {"tobacco": "no", "medications": "none"}
    claims = [{
        "id": "CLM-1",
        "status": "paid",
        "description": "Applicant is a long-term smoker with respiratory issues",
    }]
    findings = detect_claim_statement_contradictions(current, claims)
    assert any(f["field"] == "smoking_status" for f in findings)


def test_disclosure_prompt_modes():
    open_mode = build_disclosure_prompt([])
    assert open_mode["mode"] == "open_disclosure"
    assert "confidentiality" in open_mode["prompt"].lower()

    contradiction = build_disclosure_prompt([{
        "field": "smoking_status",
        "label": "Smoking",
        "current": "no",
        "previous": "yes",
        "previous_application_id": "UW-1",
    }])
    assert contradiction["mode"] == "contradiction"
    assert "differences" in contradiction["prompt"].lower()


def test_premium_adjustment_preserves_actuarial_base():
    policy = {"monthly_premium": 100.0, "annual_premium": 1200.0}
    app: dict = {}
    result = apply_premium_adjustment(
        policy=policy, app=app, adjustment=15, risk_factor_note="Medical loading",
    )
    assert policy["actuarial_monthly_premium"] == 100.0
    assert policy["monthly_premium"] == 115.0
    assert result["loading"] == 0.15
    assert app["premium_adjustment"] == 15
    assert app["underwriting_risk_factors"]
    assert app["underwriting_risk_factors"][0]["category"] == "underwriting"


def test_archive_rejected_keeps_history_and_leaves_queue():
    app = {
        "id": "UW-1",
        "status": "pending",
        "customer_id": "CUST-1",
        "customer_email": "a@example.com",
    }
    customer = {"id": "CUST-1"}
    entry = archive_rejected_application(
        app, reason="High risk", rejected_by="uw1", customer=customer,
    )
    assert app["status"] == "rejected"
    assert app["active_queue"] is False
    assert app["decision_history"][-1]["reason"] == "High risk"
    assert customer["application_history"][-1]["id"] == "UW-1"
    assert entry["status"] == "rejected"


def test_collect_media_links_chat_and_uw_files():
    app = {
        "id": "UW-CHATREF-1",
        "chat_application_id": "CHAPP-1",
        "media": [{"sha256": "abc", "name": "voice.webm", "kind": "voice"}],
    }
    files = {
        "UWF-1": {
            "application_id": "UW-CHATREF-1",
            "sha256": "def",
            "name": "lab.pdf",
            "kind": "document",
        },
        "UWF-other": {"application_id": "UW-OTHER", "sha256": "zzz"},
    }
    items = collect_application_media(app=app, underwriting_files=files)
    sha = {i["sha256"] for i in items}
    assert sha == {"abc", "def"}


def test_policy_contract_includes_declarations_billing_and_seal():
    policy = {
        "id": "POL-1",
        "type": "phins_unified",
        "coverage_amount": 500000,
        "monthly_premium": 120,
        "annual_premium": 1440,
        "actuarial_monthly_premium": 100,
        "actuarial_annual_premium": 1200,
        "underwriting_loading": 0.2,
    }
    customer = {"id": "CUST-1", "name": "Dana Levi", "email": "dana@example.com",
                "phone": "+1-555-0100"}
    app = {
        "id": "UW-1",
        "questionnaire_responses": {
            "tobacco": "no",
            "occupation": "Architect",
            "medications": "none",
            "prior_disclosure": "none",
            "signature_name": "Dana Levi",
            "signature_at": "2026-08-16T12:00:00+00:00",
        },
        "payment_setup": {"card_last4": "4444", "billing_frequency": "monthly"},
        "signature_name": "Dana Levi",
    }
    bill = {"id": "BILL-1", "due_date": "2026-09-16", "billing_frequency": "monthly"}
    media = [{"kind": "voice", "name": "note.webm", "sha256": "deadbeef" * 4}]
    contract = build_policy_contract(
        policy=policy, customer=customer, app=app, bill=bill, media=media,
        invite_or_login_code="PHINS-PORTAL-TEST",
    )
    assert contract["integrity_hash"]
    assert "PHINS" in contract["html"]
    assert "data:image/svg+xml;base64," in contract["html"]
    assert "Space Grotesk" in contract["html"]
    assert "logo-mark" in contract["html"]
    assert "Dana Levi" in contract["html"]
    assert "4444" in contract["html"]
    assert "Architect" in contract["html"]
    assert "deadbeef" in contract["html"]
    assert contract["payload"]["integrity_hash"] == contract["integrity_hash"]
    # issued_at differs — hashes differ; ensure structure stays sealed
    again = build_policy_contract(
        policy=policy, customer=customer, app=app, bill=bill, media=media,
        invite_or_login_code="PHINS-PORTAL-TEST",
    )
    assert again["payload"]["policy_id"] == "POL-1"
    assert "PHINS-PORTAL-TEST" in contract["html"]


def test_find_prior_records_by_email():
    apps = {
        "UW-A": {"id": "UW-A", "customer_email": "x@ex.com", "status": "approved"},
        "UW-B": {"id": "UW-B", "customer_email": "other@ex.com"},
    }
    prior = find_prior_customer_records(
        email="x@ex.com",
        customer_id=None,
        underwriting_apps=apps,
        policies={},
        claims={},
    )
    assert len(prior["applications"]) == 1
    assert prior["applications"][0]["id"] == "UW-A"


def _api_post(path, payload, token=None):
    import os
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    base = os.environ["TEST_BASE_URL"]
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(base + path, data=data, headers=headers, method="POST")
    try:
        with urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode()), resp.status
    except HTTPError as exc:
        body = exc.read().decode()
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"error": body}
        return parsed, exc.code


def test_approve_applies_loading_issues_contract_and_reject_archives():
    """End-to-end: UW fine-tune + contract on approve; reject leaves history."""
    login, status = _api_post("/api/login", {
        "username": "admin", "password": "admin123", "captcha_fallback": True,
    })
    assert status == 200, login
    token = login["token"]

    created, status = _api_post("/api/policies/create", {
        "customer_name": "Integrity Tester",
        "customer_email": "integrity.uw@example.com",
        "customer_phone": "+1-555-0200",
        "type": "phins_unified",
        "coverage_amount": 250000,
        "age": 40,
        "term_years": 20,
        "risk_score": "medium",
        "questionnaire": {
            "tobacco": "no", "occupation": "Analyst", "medications": "none",
            "prior_disclosure": "none", "signature_name": "Integrity Tester",
        },
        "signature": {"name": "Integrity Tester", "signed_at": "2026-08-16T00:00:00Z",
                      "method": "typed_legal_name", "mandatory": True},
        "prior_disclosure": {"mode": "open_disclosure", "text": "none",
                             "confidentiality_waiver": True},
        "payment": {
            "card_number": "4111111111111111", "cvv": "123",
            "expiry_month": "12", "expiry_year": "2030",
            "cardholder_name": "INTEGRITY TESTER",
            "billing_frequency": "monthly", "auto_pay": True,
        },
    }, token)
    assert status in (200, 201), created
    uw_id = created["underwriting"]["id"]
    actuarial_monthly = float(created["policy"]["monthly_premium"])

    approved, status = _api_post("/api/underwriting/approve", {
        "id": uw_id,
        "approved_by": "underwriter",
        "premium_adjustment": 20,
        "notes": "Family history loading",
    }, token)
    assert status == 200, approved
    assert approved["success"] is True
    assert approved["policy"]["status"] == "active"
    assert approved["policy"]["actuarial_monthly_premium"] == actuarial_monthly
    assert approved["policy"]["monthly_premium"] == round(actuarial_monthly * 1.2, 2)
    assert approved.get("contract", {}).get("integrity_hash")
    assert "PHINS" in (approved["policy"].get("policy_contract") or {}).get("html", "")
    assert approved["application"]["premium_adjustment"] == 20
    factors = approved["application"].get("underwriting_risk_factors") or []
    assert any(f.get("category") == "underwriting" for f in factors)

    created2, status = _api_post("/api/policies/create", {
        "customer_name": "Integrity Tester",
        "customer_email": "integrity.uw@example.com",
        "type": "phins_unified",
        "coverage_amount": 100000,
        "age": 40,
        "risk_score": "high",
        "questionnaire": {"tobacco": "yes"},
        "payment": {
            "card_number": "4111111111111111", "cvv": "123",
            "expiry_month": "12", "expiry_year": "2030",
            "cardholder_name": "INTEGRITY TESTER",
            "billing_frequency": "monthly", "auto_pay": True,
        },
    }, token)
    assert status in (200, 201), created2
    uw2 = created2["underwriting"]["id"]
    rejected, status = _api_post("/api/underwriting/reject", {
        "id": uw2,
        "reason": "Material misrepresentation",
        "approved_by": "underwriter",
    }, token)
    assert status == 200, rejected
    assert rejected["application"]["status"] == "rejected"
    assert rejected["application"]["active_queue"] is False
    assert rejected["application"]["decision_history"]
    assert rejected["active_queue"] is False
