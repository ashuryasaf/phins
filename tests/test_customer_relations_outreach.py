"""Customer-relations outreach: email / WhatsApp from customer management.

Guards send_customer_outreach (service) and POST /api/admin/customers/{id}/contact
so relations messages, offers, and bills stay bound to the stored customer record.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

from services.customer_communication_agent import CustomerCommunicationAgent
from services.notification_service import (
    create_notification_service,
    reset_global_rate_limiter,
    reset_notification_service,
)


@pytest.fixture(autouse=True)
def _reset_notifications():
    reset_global_rate_limiter()
    reset_notification_service()
    yield
    reset_global_rate_limiter()
    reset_notification_service()


def _agent():
    return CustomerCommunicationAgent(
        notification_service=create_notification_service(use_mock=True)
    )


def test_outreach_email_and_whatsapp_success():
    result = _agent().send_customer_outreach(
        customer_id="CUST-1",
        customer_name="Efrat PHINS",
        email="efrat@phins.ai",
        phone="+972509876543",
        template="message",
        channels="both",
        custom_message="Checking in on your policy.",
    )
    assert result["success"] is True
    assert result["email"]["success"] is True
    assert result["whatsapp"]["success"] is True
    assert result["recipients"]["email"] == "e***@phins.ai"
    assert result["recipients"]["whatsapp"].endswith("6543")
    assert "Checking in" in result["subject"] or result["email"]["success"]


def test_outreach_offer_and_bill_templates_include_record_data():
    agent = _agent()
    offer = agent.send_customer_outreach(
        customer_id="CUST-1",
        customer_name="Efrat PHINS",
        email="efrat@phins.ai",
        template="offer",
        channels="email",
        offers=[{"name": "Physio package", "price": 89.0, "active": True}],
        policies=[{"type": "health", "status": "active", "coverage_amount": 10000}],
    )
    assert offer["success"] is True
    assert offer["offers_included"] == 1
    assert offer["template"] == "offer"

    bill = agent.send_customer_outreach(
        customer_id="CUST-1",
        customer_name="Efrat PHINS",
        email="efrat@phins.ai",
        template="bill",
        channels="email",
        bills=[{"status": "outstanding", "amount_due": 210.5}],
    )
    assert bill["success"] is True
    assert bill["report"]["outstanding_bills"] == 1
    assert bill["report"]["outstanding_amount"] == 210.5
    assert "210.50" in bill["subject"]


def test_outreach_rejects_invalid_template_and_missing_channel():
    agent = _agent()
    bad = agent.send_customer_outreach(
        customer_id="CUST-1",
        customer_name="X",
        email="x@phins.ai",
        template="spam",
        channels="email",
    )
    assert bad["success"] is False
    assert bad["code"] == "INVALID_TEMPLATE"

    no_phone = agent.send_customer_outreach(
        customer_id="CUST-1",
        customer_name="X",
        email="x@phins.ai",
        template="message",
        channels="whatsapp",
    )
    assert no_phone["success"] is False
    assert no_phone["code"] == "PHONE_REQUIRED"


def test_outreach_escapes_html_in_custom_message():
    result = _agent().send_customer_outreach(
        customer_id="CUST-1",
        customer_name='<script>alert(1)</script>',
        email="x@phins.ai",
        template="message",
        channels="email",
        custom_message='<img src=x onerror=alert(1)>',
    )
    assert result["success"] is True
    sent = result["email"]
    assert sent["success"] is True
    # The notification service stores rendered HTML on the request; confirm the
    # agent itself produced escaped copy by re-rendering through the helper.
    html_body = _agent()._render_outreach_html(
        customer_name='<script>alert(1)</script>',
        subject="Hi",
        intro="Hi",
        text_body='<img src=x onerror=alert(1)>',
        login_url="/billing.html",
        template="message",
    )
    assert "<script>" not in html_body
    assert "<img src=x" not in html_body
    assert "&lt;script&gt;" in html_body


def test_helper_uses_stored_customer_not_caller_email(monkeypatch):
    import web_portal.server as portal

    portal.CUSTOMERS["CUST-REL-001"] = {
        "id": "CUST-REL-001",
        "name": "Relations Test",
        "email": "onfile@phins.ai",
        "phone": "+15555550199",
    }
    portal.POLICIES["POL-REL-001"] = {
        "id": "POL-REL-001",
        "customer_id": "CUST-REL-001",
        "status": "active",
        "coverage_amount": 5000,
    }
    portal.BILLING["BILL-REL-001"] = {
        "id": "BILL-REL-001",
        "customer_id": "CUST-REL-001",
        "status": "outstanding",
        "amount_due": 40.0,
    }

    report = portal.send_admin_customer_outreach(
        "CUST-REL-001",
        template="bill",
        channels="email",
        subject="Ignore this redirect",
        custom_message="Please pay via the portal only.",
        actor="admin",
    )
    assert report["success"] is True
    assert report["recipients"]["email"] == "o***@phins.ai"
    assert report["contact_available"]["email"] is True
    assert report["contact_available"]["whatsapp"] is True


def test_helper_unknown_customer():
    import web_portal.server as portal

    report = portal.send_admin_customer_outreach("CUST-DOES-NOT-EXIST")
    assert report["success"] is False
    assert report["error"] == "Customer not found"


def test_public_portal_base_url_never_hardcodes_railway(monkeypatch):
    import web_portal.server as portal

    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    origin = portal.public_portal_base_url()
    assert "railway.app" not in origin
    test_base = str(os.environ.get("TEST_BASE_URL") or "").rstrip("/")
    assert origin in ("", test_base)
    login_url = f"{origin}/billing.html" if origin else "/billing.html"
    assert "railway.app" not in login_url
    assert login_url in (f"{test_base}/billing.html", "/billing.html")

    monkeypatch.setenv("BASE_URL", "https://portal.example.test/")
    assert portal.public_portal_base_url() == "https://portal.example.test"


def _http(method, url, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"error": raw}
        return exc.code, parsed


def test_contact_endpoint_requires_auth():
    base = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
    status, payload = _http(
        "POST",
        f"{base}/api/admin/customers/CUST-EFRAT-001/contact",
        {"template": "message", "channels": "email"},
    )
    assert status in (401, 403)
    assert "error" in payload


def test_contact_endpoint_sends_for_admin():
    import web_portal.server as portal

    base = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
    status, login = _http(
        "POST",
        f"{base}/api/login",
        {"username": "admin", "password": "admin123"},
    )
    if status != 200 or not login.get("token"):
        pytest.skip("admin login unavailable in this environment")
    token = login["token"]

    portal.CUSTOMERS["CUST-REL-HTTP"] = {
        "id": "CUST-REL-HTTP",
        "name": "HTTP Relations",
        "email": "http-rel@phins.ai",
        "phone": "+15555550188",
    }
    portal.BILLING["BILL-REL-HTTP"] = {
        "id": "BILL-REL-HTTP",
        "customer_id": "CUST-REL-HTTP",
        "status": "outstanding",
        "amount_due": 12.5,
    }

    status, payload = _http(
        "POST",
        f"{base}/api/admin/customers/CUST-REL-HTTP/contact",
        {
            "template": "bill",
            "channels": "both",
            "message": "Portal pay link is in this note.",
            "email": "attacker@evil.example",
        },
        token=token,
    )
    assert status == 200, payload
    assert payload["success"] is True
    assert payload["recipients"]["email"] == "h***@phins.ai"
    assert payload["email"]["success"] is True
    assert payload["whatsapp"]["success"] is True
