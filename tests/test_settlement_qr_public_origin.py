"""Settlement QR / approval links must stay on phins.ai, never Railway."""

from __future__ import annotations


def test_public_base_url_never_emits_railway(monkeypatch):
    from services.supply_chain_ecosystem_service import (
        SupplyChainEcosystemService,
        _PUBLIC_SETTLEMENT_ORIGIN,
    )

    # Simulate production: Railway BASE_URL must fall back to phins.ai.
    monkeypatch.setenv("PHINS_TEST_MODE", "false")
    monkeypatch.setenv(
        "BASE_URL",
        "https://phins-portal-production.up.railway.app",
    )
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    monkeypatch.delenv("TEST_BASE_URL", raising=False)
    assert SupplyChainEcosystemService._get_public_base_url() == _PUBLIC_SETTLEMENT_ORIGIN

    monkeypatch.setenv("BASE_URL", "https://www.phins.ai/")
    assert SupplyChainEcosystemService._get_public_base_url() == "https://www.phins.ai"

    monkeypatch.setenv("BASE_URL", "https://phins.ai")
    assert SupplyChainEcosystemService._get_public_base_url() == "https://phins.ai"

    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    origin = SupplyChainEcosystemService._get_public_base_url()
    assert "railway.app" not in origin
    assert origin == _PUBLIC_SETTLEMENT_ORIGIN


def test_ensure_artifacts_rewrites_stored_railway_url(monkeypatch):
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService

    monkeypatch.setenv("PHINS_TEST_MODE", "false")
    monkeypatch.setenv("BASE_URL", "https://phins-portal-production.up.railway.app")
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    monkeypatch.delenv("TEST_BASE_URL", raising=False)
    svc = SupplyChainEcosystemService()
    order = {
        "id": "ORD-REWRITE-1",
        "settlement_qr_token": "tok_abc12345",
        "settlement_code": "SET-TOKABC12",
        "settlement_approval_url": (
            "https://phins-portal-production.up.railway.app/settlement-approval.html"
            "?order_id=ORD-REWRITE-1&token=tok_abc12345"
        ),
        "settlement_request": {
            "settlement_approval_url": (
                "https://phins-portal-production.up.railway.app/settlement-approval.html"
                "?order_id=ORD-REWRITE-1&token=tok_abc12345"
            ),
        },
    }
    artifacts = svc._ensure_settlement_artifacts(order)
    assert "railway.app" not in artifacts["settlement_approval_url"]
    assert artifacts["settlement_approval_url"].startswith("https://www.phins.ai/")
    assert "settlement-approval.html" in artifacts["settlement_approval_url"]
    assert "token=tok_abc12345" in artifacts["settlement_approval_url"]
    assert order["settlement_approval_url"] == artifacts["settlement_approval_url"]
    assert "railway.app" not in order["settlement_request"]["settlement_approval_url"]
    assert artifacts["settlement_code"] == "SET-TOKABC12"


def test_email_customer_settlement_approval_uses_template(monkeypatch):
    import services.notification_service as ns
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService

    svc = SupplyChainEcosystemService()
    order = {
        "id": "ORD-EMAIL-1",
        "customer_id": "CUST-EMAIL-1",
        "item_name": 'Pack <script>alert(1)</script>',
        "settlement_notifications": [],
        "settlement_email_log": [],
    }
    artifacts = {
        "settlement_code": "SET-EMAIL01",
        "settlement_approval_url": (
            "https://www.phins.ai/settlement-approval.html"
            "?order_id=ORD-EMAIL-1&token=tok"
        ),
        "settlement_qr_image_url": "https://api.qrserver.com/v1/create-qr-code/?size=220x220&data=x",
    }

    monkeypatch.setattr(
        SupplyChainEcosystemService,
        "_resolve_customer_contact",
        staticmethod(lambda _cid: ("customer@example.com", 'Pat <b>Customer</b>')),
    )

    class _Result:
        success = True
        notification_id = "NOTIF-TEST"
        error_code = None

    captured = {}

    def _deliver(request):
        captured["request"] = request
        return _Result()

    monkeypatch.setattr(ns, "deliver_notification", _deliver)
    record = svc._email_customer_settlement_approval(
        order,
        artifacts=artifacts,
        actor="supplier-demo",
    )

    assert record["sent"] is True
    assert captured["request"].recipient == "customer@example.com"
    assert "https://www.phins.ai/" in captured["request"].content
    assert "<script>" in captured["request"].content  # plain body keeps raw text
    assert captured["request"].html_content
    assert "<script>" not in captured["request"].html_content
    assert "&lt;script&gt;" in captured["request"].html_content
    assert "&lt;b&gt;Customer&lt;/b&gt;" in captured["request"].html_content
    assert order["settlement_email_log"][-1]["sent"] is True


def test_mint_false_does_not_invent_token_for_code_only_row():
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService

    svc = SupplyChainEcosystemService()
    order = {
        "id": "ORD-CODE-ONLY",
        "settlement_code": "SET-ONLYCODE",
    }
    artifacts = svc._ensure_settlement_artifacts(order, mint=False)
    assert artifacts["settlement_qr_token"] == ""
    assert order.get("settlement_qr_token") in (None, "")
    assert artifacts["settlement_code"] == "SET-ONLYCODE"


def test_recover_token_from_stored_railway_url(monkeypatch):
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService

    monkeypatch.setenv("PHINS_TEST_MODE", "false")
    monkeypatch.setenv("BASE_URL", "https://phins-portal-production.up.railway.app")
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    monkeypatch.delenv("TEST_BASE_URL", raising=False)

    svc = SupplyChainEcosystemService()
    order = {
        "id": "ORD-RECOVER-1",
        "settlement_code": "SET-RECOVER1",
        "settlement_approval_url": (
            "https://phins-portal-production.up.railway.app/settlement-approval.html"
            "?order_id=ORD-RECOVER-1&token=old_token_value"
        ),
    }
    artifacts = svc._ensure_settlement_artifacts(order, mint=False)
    assert artifacts["settlement_qr_token"] == "old_token_value"
    assert "token=old_token_value" in artifacts["settlement_approval_url"]
    assert artifacts["settlement_approval_url"].startswith("https://www.phins.ai/")


def test_request_settlement_approval_url_is_phins_origin(monkeypatch):
    """request-settlement / Show QR must not emit a Railway approval URL."""
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService
    import pytest

    monkeypatch.setenv("PHINS_TEST_MODE", "false")
    monkeypatch.setenv(
        "BASE_URL",
        "https://phins-portal-production.up.railway.app",
    )
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    monkeypatch.delenv("TEST_BASE_URL", raising=False)

    svc = SupplyChainEcosystemService()
    order_id = "ORD-ORIGIN-UNIT-1"
    svc.orders[order_id] = {
        "id": order_id,
        "supplier_id": "SUP-ORIGIN-1",
        "customer_id": "CUST-ORIGIN-1",
        "item_name": "Unit pack",
        "status": "processing",
        "payment_status": "paid",
        "fulfillment_kind": "delivery",
        "total_amount": 40.0,
        "commission": 4.0,
        "supplier_payout": 36.0,
        "settlement_status": "pending_supplier_request",
    }

    def _skip_email(self, order, *, artifacts, actor="supplier"):
        return {"sent": False, "error": "skipped"}

    monkeypatch.setattr(
        SupplyChainEcosystemService,
        "_email_customer_settlement_approval",
        _skip_email,
    )
    monkeypatch.setattr(
        SupplyChainEcosystemService,
        "_notify_settlement_participants",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        SupplyChainEcosystemService,
        "_record_ledger_entry",
        lambda *a, **k: None,
    )

    with pytest.raises(ValueError, match="Request approval first"):
        svc.share_settlement_qr(order_id=order_id, actor="supplier-demo")

    result = svc.request_settlement_release(
        order_id=order_id,
        actor="supplier-demo",
        data={"notes": "handover"},
    )
    assert result["success"] is True
    url = result["settlement_approval_url"]
    assert "railway.app" not in url
    assert url.startswith("https://www.phins.ai/settlement-approval.html")
    assert result["order"].get("settlement_status") == "awaiting_customer_approval"
    assert "settlement_qr_token" not in result
    assert result["order"].get("settlement_qr_token") is None
    assert svc.orders[order_id]["settlement_status"] == "awaiting_customer_approval"

    shared = svc.share_settlement_qr(order_id=order_id, actor="supplier-demo")
    assert shared["success"] is True
    assert "railway.app" not in shared["settlement_approval_url"]
    assert shared["settlement_approval_url"].startswith(
        "https://www.phins.ai/settlement-approval.html"
    )
    assert "settlement_qr_token" not in shared
    assert "settlement_qr_token" not in (shared.get("order") or {})
