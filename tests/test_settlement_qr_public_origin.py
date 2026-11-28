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


def test_show_qr_skips_repeat_email_for_same_url(monkeypatch):
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService

    svc = SupplyChainEcosystemService()
    order = {
        "id": "ORD-REPEAT-1",
        "customer_id": "CUST-REPEAT-1",
        "item_name": "Repeat pack",
        "settlement_notifications": [],
        "settlement_email_log": [],
    }
    artifacts = {
        "settlement_code": "SET-REPEAT1",
        "settlement_approval_url": (
            "https://www.phins.ai/settlement-approval.html"
            "?order_id=ORD-REPEAT-1&token=tok"
        ),
        "settlement_qr_image_url": "https://api.qrserver.com/v1/create-qr-code/?size=220x220&data=x",
    }
    monkeypatch.setattr(
        SupplyChainEcosystemService,
        "_resolve_customer_contact",
        staticmethod(lambda _cid: ("customer@example.com", "Pat")),
    )

    class _Result:
        success = True
        notification_id = "NOTIF-1"
        error_code = None

    sends = {"n": 0}

    def _deliver(request):
        sends["n"] += 1
        return _Result()

    import services.notification_service as ns
    monkeypatch.setattr(ns, "deliver_notification", _deliver)

    first = svc._email_customer_settlement_approval(order, artifacts=artifacts, actor="s")
    second = svc._email_customer_settlement_approval(order, artifacts=artifacts, actor="s")
    forced = svc._email_customer_settlement_approval(
        order, artifacts=artifacts, actor="s", force=True,
    )
    assert first["sent"] is True
    assert second.get("skipped") is True
    assert second["error"] == "already_sent"
    assert forced["sent"] is True
    assert sends["n"] == 2


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

    def _skip_email(self, order, *, artifacts, actor="supplier", force=False):
        return {"sent": False, "error": "skipped", "forced": force}

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


def test_ensure_artifacts_keeps_token_from_stored_url(monkeypatch):
    """A legacy row with only the Railway URL must not rotate the token."""
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService

    monkeypatch.setenv("PHINS_TEST_MODE", "false")
    monkeypatch.setenv("BASE_URL", "https://phins-portal-production.up.railway.app")
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    monkeypatch.delenv("TEST_BASE_URL", raising=False)
    svc = SupplyChainEcosystemService()
    legacy_url = (
        "https://phins-portal-production.up.railway.app/settlement-approval.html"
        "?order_id=ORD-LEGACY-1&token=oldtoken_value"
    )
    order = {
        "id": "ORD-LEGACY-1",
        "settlement_code": "SET-OLDTOKE",
        "settlement_approval_url": legacy_url,
    }
    artifacts = svc._ensure_settlement_artifacts(order)
    assert artifacts["settlement_qr_token"] == "oldtoken_value"
    assert order["settlement_qr_token"] == "oldtoken_value"
    assert "token=oldtoken_value" in artifacts["settlement_approval_url"]
    assert artifacts["settlement_approval_url"].startswith("https://www.phins.ai/")
    assert "railway.app" not in artifacts["settlement_approval_url"]
    assert artifacts["settlement_code"] == "SET-OLDTOKE"
    assert svc._is_settlement_token_valid(order, "oldtoken_value") is True

    again = svc._ensure_settlement_artifacts(order)
    assert again["settlement_qr_token"] == "oldtoken_value"


def test_ensure_artifacts_reads_token_from_nested_request(monkeypatch):
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService

    monkeypatch.setenv("PHINS_TEST_MODE", "false")
    monkeypatch.setenv("BASE_URL", "https://phins-portal-production.up.railway.app")
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    monkeypatch.delenv("TEST_BASE_URL", raising=False)
    svc = SupplyChainEcosystemService()
    order = {
        "id": "ORD-NESTED-1",
        "settlement_request": {
            "settlement_approval_url": (
                "https://phins-portal-production.up.railway.app/settlement-approval.html"
                "?order_id=ORD-NESTED-1&token=nested_token_1"
            ),
        },
    }
    artifacts = svc._ensure_settlement_artifacts(order)
    assert artifacts["settlement_qr_token"] == "nested_token_1"
    assert "token=nested_token_1" in order["settlement_request"]["settlement_approval_url"]
    assert "railway.app" not in order["settlement_request"]["settlement_approval_url"]


def test_ensure_artifacts_prefers_explicit_token_field(monkeypatch):
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService

    monkeypatch.setenv("PHINS_TEST_MODE", "false")
    monkeypatch.setenv("BASE_URL", "https://example.up.railway.app")
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    monkeypatch.delenv("TEST_BASE_URL", raising=False)
    svc = SupplyChainEcosystemService()
    order = {
        "id": "ORD-FIELD-1",
        "settlement_qr_token": "field_token",
        "settlement_approval_url": (
            "https://phins-portal-production.up.railway.app/settlement-approval.html"
            "?order_id=ORD-FIELD-1&token=url_token"
        ),
    }
    artifacts = svc._ensure_settlement_artifacts(order)
    assert artifacts["settlement_qr_token"] == "field_token"
    assert "token=field_token" in artifacts["settlement_approval_url"]


def test_repeat_show_qr_does_not_email_again(monkeypatch):
    import services.notification_service as ns
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService

    monkeypatch.setenv("PHINS_TEST_MODE", "false")
    monkeypatch.setenv("BASE_URL", "https://www.phins.ai")
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    monkeypatch.delenv("TEST_BASE_URL", raising=False)

    svc = SupplyChainEcosystemService()
    order_id = "ORD-QR-ONCE"
    svc.orders[order_id] = {
        "id": order_id,
        "supplier_id": "SUP-1",
        "customer_id": "CUST-1",
        "item_name": "Pack",
        "settlement_status": "awaiting_customer_approval",
        "settlement_qr_token": "tok_stable",
        "settlement_code": "SET-TOKSTABL",
        "settlement_messages": [],
        "settlement_notifications": [],
        "settlement_email_log": [],
    }
    monkeypatch.setattr(
        SupplyChainEcosystemService,
        "_resolve_customer_contact",
        staticmethod(lambda _cid: ("customer@example.com", "Pat")),
    )

    class _Result:
        success = True
        notification_id = "NOTIF-ONCE"
        error_code = None

    calls = {"n": 0}

    def _deliver(request):
        calls["n"] += 1
        assert "Approve or dispute" in (request.subject or "")
        assert "https://www.phins.ai/" in (request.content or "")
        return _Result()

    monkeypatch.setattr(ns, "deliver_notification", _deliver)
    first = svc.share_settlement_qr(order_id=order_id, actor="supplier-demo")
    second = svc.share_settlement_qr(order_id=order_id, actor="supplier-demo")

    assert calls["n"] == 1
    assert first["customer_email"]["sent"] is True
    assert second["customer_email"].get("skipped") is True
    assert second["customer_email"]["error"] == "already_sent"
    assert second["customer_email"]["sent"] is False
    assert "settlement_qr_token" not in second
    assert second["settlement_approval_url"] == first["settlement_approval_url"]
    sent = [row for row in svc.orders[order_id]["settlement_email_log"] if row.get("sent")]
    assert len(sent) == 1


def test_show_qr_skips_email_when_same_token_was_sent_on_old_origin(monkeypatch):
    import services.notification_service as ns
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService

    monkeypatch.setenv("PHINS_TEST_MODE", "false")
    monkeypatch.setenv("BASE_URL", "https://phins-portal-production.up.railway.app")
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    monkeypatch.delenv("TEST_BASE_URL", raising=False)

    svc = SupplyChainEcosystemService()
    order_id = "ORD-QR-REWRITE"
    railway_url = (
        "https://phins-portal-production.up.railway.app/settlement-approval.html"
        f"?order_id={order_id}&token=tok_same"
    )
    svc.orders[order_id] = {
        "id": order_id,
        "supplier_id": "SUP-1",
        "customer_id": "CUST-1",
        "item_name": "Pack",
        "settlement_status": "awaiting_customer_approval",
        "settlement_approval_url": railway_url,
        "settlement_messages": [],
        "settlement_notifications": [],
        "settlement_email_log": [
            {
                "sent": True,
                "approval_url": railway_url,
                "customer_id": "CUST-1",
            }
        ],
    }
    calls = {"n": 0}

    def _deliver(_request):
        calls["n"] += 1
        raise AssertionError("should not re-send after host rewrite")

    monkeypatch.setattr(ns, "deliver_notification", _deliver)
    shared = svc.share_settlement_qr(order_id=order_id, actor="supplier-demo")
    assert calls["n"] == 0
    assert shared["customer_email"]["error"] == "already_sent"
    assert shared["customer_email"].get("skipped") is True
    assert "settlement_qr_token" not in shared
    assert shared["settlement_approval_url"].startswith(
        "https://www.phins.ai/settlement-approval.html"
    )
    assert "token=tok_same" in shared["settlement_approval_url"]
    assert svc.orders[order_id]["settlement_qr_token"] == "tok_same"


def test_failed_settlement_email_is_retried_on_next_show_qr(monkeypatch):
    import services.notification_service as ns
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService

    monkeypatch.setenv("PHINS_TEST_MODE", "false")
    monkeypatch.setenv("BASE_URL", "https://www.phins.ai")
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    monkeypatch.delenv("TEST_BASE_URL", raising=False)

    svc = SupplyChainEcosystemService()
    order_id = "ORD-QR-RETRY"
    svc.orders[order_id] = {
        "id": order_id,
        "supplier_id": "SUP-1",
        "customer_id": "CUST-1",
        "item_name": "Pack",
        "settlement_status": "awaiting_customer_approval",
        "settlement_qr_token": "tok_retry",
        "settlement_code": "SET-TOKRETRY",
        "settlement_messages": [],
        "settlement_notifications": [],
        "settlement_email_log": [],
    }
    monkeypatch.setattr(
        SupplyChainEcosystemService,
        "_resolve_customer_contact",
        staticmethod(lambda _cid: ("customer@example.com", "Pat")),
    )

    class _Result:
        def __init__(self, success):
            self.success = success
            self.notification_id = "NOTIF-RETRY" if success else ""
            self.error_code = None if success else "SEND_FAILED"

    calls = {"n": 0}

    def _deliver(_request):
        calls["n"] += 1
        return _Result(calls["n"] > 1)

    monkeypatch.setattr(ns, "deliver_notification", _deliver)
    first = svc.share_settlement_qr(order_id=order_id, actor="supplier-demo")
    second = svc.share_settlement_qr(order_id=order_id, actor="supplier-demo")
    assert calls["n"] == 2
    assert first["customer_email"]["sent"] is False
    assert second["customer_email"]["sent"] is True
