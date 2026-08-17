"""Sealed policy contract PDF: AES-256 lock with card last4 + portal access."""

from __future__ import annotations

import base64
import json
import os
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from pypdf import PdfReader
from reportlab.pdfgen import canvas

from services.underwriting_integrity_service import (
    build_encrypted_policy_contract_pdf,
    build_policy_contract,
    encrypt_pdf_with_password,
    resolve_card_last4,
)


def _base() -> str:
    return os.environ.get("TEST_BASE_URL", "http://localhost:8000").rstrip("/")


def _request(method: str, path: str, data=None, token=None, raw=False):
    url = _base() + path
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=180) as resp:
            payload = resp.read()
            if raw:
                return resp.status, payload, dict(resp.headers)
            return resp.status, json.loads(payload.decode("utf-8"))
    except HTTPError as exc:
        raw_body = exc.read()
        if raw:
            return exc.code, raw_body, dict(exc.headers)
        try:
            return exc.code, json.loads(raw_body.decode("utf-8"))
        except Exception:
            return exc.code, {"error": raw_body.decode("utf-8", errors="replace")}


def _tiny_pdf_bytes(text: str = "PHINS sealed") -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, text)
    c.save()
    return buf.getvalue()


def test_resolve_card_last4_from_nested_payment_setup():
    last4 = resolve_card_last4(
        app={"payment_setup": {"card_last4": "4444"}},
        policy={"billing": {"payment_method": {"card_last4": "9999"}}},
    )
    assert last4 == "4444"


def test_encrypt_pdf_requires_card_last4_password():
    plain = _tiny_pdf_bytes("integrity")
    enc = encrypt_pdf_with_password(plain, user_password="4444")
    reader = PdfReader(BytesIO(enc))
    assert reader.is_encrypted
    assert reader.decrypt("9999") == 0
    assert reader.decrypt("4444") == 1
    assert "integrity" in (reader.pages[0].extract_text() or "")


def test_build_encrypted_policy_contract_pdf_uses_html_render(monkeypatch):
    contract = build_policy_contract(
        policy={
            "id": "POL-PDF-1",
            "type": "phins_unified",
            "coverage_amount": 100000,
            "monthly_premium": 50,
            "annual_premium": 600,
            "actuarial_monthly_premium": 50,
            "actuarial_annual_premium": 600,
        },
        customer={"id": "CUST-1", "name": "Pat Lee", "email": "pat@example.com"},
        app={
            "id": "UW-1",
            "payment_setup": {"card_last4": "1234", "billing_frequency": "monthly"},
            "questionnaire_responses": {"occupation": "Engineer", "tobacco": "no"},
            "signature_name": "Pat Lee",
        },
    )
    assert "PHINS" in contract["html"]
    monkeypatch.setattr(
        "services.underwriting_integrity_service.html_to_pdf_bytes",
        lambda html, timeout_seconds=90: _tiny_pdf_bytes("SEALED-DESIGN"),
    )
    result = build_encrypted_policy_contract_pdf(contract=contract, card_last4="1234")
    assert result["ok"] is True
    assert result["encryption"] == "AES-256"
    assert result["password_hint"] == "last_4_digits_of_payment_card_on_file"
    assert "password" not in result
    reader = PdfReader(BytesIO(result["pdf_bytes"]))
    assert reader.is_encrypted
    assert reader.decrypt("1234") == 1
    assert "SEALED-DESIGN" in (reader.pages[0].extract_text() or "")


def test_portal_contract_pdf_download_hierarchy_and_encryption(monkeypatch):
    monkeypatch.setenv("PHINS_CONTRACT_PDF_BACKEND", "reportlab")

    status, login = _request("POST", "/api/login", {
        "username": "admin", "password": "admin123", "captcha_fallback": True,
    })
    assert status == 200, login
    admin_token = login["token"]

    status, created = _request("POST", "/api/policies/create", {
        "customer_name": "PDF Lock Customer",
        "customer_email": "pdf.lock@example.com",
        "customer_phone": "+1-555-0444",
        "type": "phins_unified",
        "coverage_amount": 200000,
        "age": 35,
        "term_years": 20,
        "risk_score": "medium",
        "questionnaire": {"tobacco": "no", "occupation": "Designer"},
        "signature": {"name": "PDF Lock Customer", "signed_at": "2026-08-17T00:00:00Z"},
        "payment": {
            "card_number": "5555555555554444",
            "cvv": "123",
            "expiry_month": "11",
            "expiry_year": "2031",
            "cardholder_name": "PDF LOCK CUSTOMER",
            "billing_frequency": "monthly",
            "auto_pay": True,
        },
    }, token=admin_token)
    assert status in (200, 201), created
    policy_id = created["policy"]["id"]
    uw_id = created["underwriting"]["id"]

    status, approved = _request("POST", "/api/underwriting/approve", {
        "id": uw_id,
        "approved_by": "admin",
        "premium_adjustment": 0,
    }, token=admin_token)
    assert status == 200, approved
    assert approved["success"] is True
    pdf_info = ((approved.get("pipeline_completed") or {}).get("policy_contract") or {})
    assert pdf_info.get("pdf_encrypted") is True
    assert pdf_info.get("download_url") == f"/api/policies/{policy_id}/contract.pdf"
    assert pdf_info.get("password_ready") is True
    dumped = json.dumps(approved)
    assert '"password":' not in dumped
    assert "5555555555554444" not in dumped
    assert pdf_info.get("password_hint") == "last_4_digits_of_payment_card_on_file"

    status, meta = _request(
        "GET", f"/api/policies/{policy_id}/contract", token=admin_token
    )
    assert status == 200, meta
    assert meta["available"] is True
    assert meta["encryption"] == "AES-256"
    assert meta["password_hint"] == "last_4_digits_of_payment_card_on_file"
    assert meta["password_ready"] is True

    status, pdf_bytes, headers = _request(
        "GET", f"/api/policies/{policy_id}/contract.pdf", token=admin_token, raw=True
    )
    assert status == 200, pdf_bytes[:200]
    assert headers.get("Content-Type", "").startswith("application/pdf")
    enc_hdr = headers.get("X-Phins-Encryption") or headers.get("X-PHINS-Encryption") or ""
    assert "AES-256" in enc_hdr
    reader = PdfReader(BytesIO(pdf_bytes))
    assert reader.is_encrypted
    assert reader.decrypt("0000") == 0
    assert reader.decrypt("4444") == 1
    text = reader.pages[0].extract_text() or ""
    assert "PHINS" in text

    # Customer cannot download another customer's policy
    status, other = _request("POST", "/api/policies/create", {
        "customer_name": "Other Person",
        "customer_email": "other.pdf@example.com",
        "type": "life",
        "coverage_amount": 50000,
        "age": 30,
        "payment": {
            "card_number": "4111111111111111",
            "cvv": "111",
            "expiry_month": "10",
            "expiry_year": "2030",
            "cardholder_name": "OTHER",
            "billing_frequency": "monthly",
        },
    }, token=admin_token)
    assert status in (200, 201)
    other_pol = other["policy"]["id"]
    provisioned = created.get("provisioned_login") or {}
    cust_user = provisioned.get("username")
    cust_pass = provisioned.get("password") or provisioned.get("temporary_password")
    if cust_user and cust_pass:
        status, cust_login = _request("POST", "/api/login", {
            "username": cust_user, "password": cust_pass, "captcha_fallback": True,
        })
        if status == 200:
            cust_token = cust_login["token"]
            status, own_pdf, _ = _request(
                "GET", f"/api/policies/{policy_id}/contract.pdf",
                token=cust_token, raw=True,
            )
            assert status == 200
            status, denied, _ = _request(
                "GET", f"/api/policies/{other_pol}/contract.pdf",
                token=cust_token, raw=True,
            )
            assert status in (403, 409)
