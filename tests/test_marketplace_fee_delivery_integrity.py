"""Platform fee book identity, pre-dispatch tracking, and GMV accrual."""

from __future__ import annotations

import os

import pytest


def test_fee_schedule_honours_supplier_locked_percent():
    from services.supply_chain_ecosystem_service import FeeSchedule

    schedule = FeeSchedule()
    calc = schedule.calculate_commission(
        amount=100.0,
        supplier_type="pharmacy",
        rate_override=20.0,
    )
    assert calc["base_rate_pct"] == 20.0
    assert calc["commission"] == 20.0
    assert calc["supplier_payout"] == 80.0


def test_calculate_order_fees_uses_supplier_commission_rate():
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService

    svc = SupplyChainEcosystemService()
    svc.suppliers["SUP-FEE-1"] = {
        "id": "SUP-FEE-1",
        "supplier_type": "pharmacy",
        "commission_rate": 12.0,
        "created_date": "2026-01-01T00:00:00+00:00",
        "total_revenue": 0,
        "status": "approved",
    }
    calc = svc.calculate_order_fees("SUP-FEE-1", 200.0)
    assert calc["base_rate_pct"] == 12.0
    assert calc["commission"] == 24.0
    assert calc["supplier_payout"] == 176.0


def test_one_percent_lock_is_not_inflated_to_one_hundred():
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService

    svc = SupplyChainEcosystemService()
    svc.suppliers["SUP-FEE-1PCT"] = {
        "id": "SUP-FEE-1PCT",
        "supplier_type": "pharmacy",
        "commission_rate": 1.0,
        "created_date": "2026-01-01T00:00:00+00:00",
        "total_revenue": 0,
        "status": "approved",
    }
    calc = svc.calculate_order_fees("SUP-FEE-1PCT", 200.0)
    assert calc["base_rate_pct"] == 1.0
    assert calc["commission"] == 2.0

    svc.suppliers["SUP-FEE-FRAC"] = {
        "id": "SUP-FEE-FRAC",
        "supplier_type": "pharmacy",
        "commission_rate": 0.08,
        "created_date": "2026-01-01T00:00:00+00:00",
        "total_revenue": 0,
        "status": "approved",
    }
    frac = svc.calculate_order_fees("SUP-FEE-FRAC", 200.0)
    assert frac["base_rate_pct"] == 8.0
    assert frac["commission"] == 16.0


def test_supplier_order_money_totals_reads_commission_or_platform_fee():
    import web_portal.server as portal

    rows = [
        {"total_amount": 100, "commission": 11, "supplier_payout": 89},
        {"total_amount": 50, "platform_fee": 5, "supplier_payout": 45},
    ]
    totals = portal.supplier_order_money_totals(rows)
    assert totals["order_value"] == 150.0
    assert totals["platform_fees"] == 16.0
    assert totals["supplier_payouts"] == 134.0


def test_pre_dispatch_notice_uses_phins_origin_and_is_idempotent(monkeypatch):
    import services.notification_service as ns
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService

    monkeypatch.setenv("PHINS_TEST_MODE", "false")
    monkeypatch.setenv("BASE_URL", "https://phins-portal-production.up.railway.app")
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    monkeypatch.delenv("TEST_BASE_URL", raising=False)

    svc = SupplyChainEcosystemService()
    order_id = "ORD-DISPATCH-1"
    svc.orders[order_id] = {
        "id": order_id,
        "supplier_id": "SUP-1",
        "customer_id": "CUST-1",
        "item_name": "Rx pack",
        "status": "processing",
        "delivery_method": "courier_delivery",
        "total_amount": 40.0,
        "commission": 4.0,
        "supplier_payout": 36.0,
        "delivery_plan": {
            "requested_location": {
                "city": "Tel Aviv",
                "country": "IL",
                "latitude": 32.08,
                "longitude": 34.78,
            },
            "recommended_method": {
                "method": "courier_delivery",
                "label": "Courier delivery",
                "eta_days": 1,
            },
            "distance_km": 3.2,
        },
        "estimated_delivery": "2026-11-29T12:00:00+00:00",
        "delivery_email_log": [],
    }
    monkeypatch.setattr(
        SupplyChainEcosystemService,
        "_resolve_customer_contact",
        staticmethod(lambda _cid: ("customer@example.com", "Pat")),
    )

    class _Result:
        success = True
        notification_id = "NOTIF-D1"
        error_code = None

    sends = {"n": 0}

    def _deliver(request):
        sends["n"] += 1
        assert "https://www.phins.ai/delivery-tracking.html" in (request.content or "")
        assert "railway.app" not in (request.content or "")
        return _Result()

    monkeypatch.setattr(ns, "deliver_notification", _deliver)
    monkeypatch.setattr(SupplyChainEcosystemService, "_record_ledger_entry", lambda *a, **k: None)

    first = svc.notify_customer_before_dispatch(order_id=order_id, actor="supplier-demo")
    second = svc.notify_customer_before_dispatch(order_id=order_id, actor="supplier-demo")
    assert first["success"] is True
    assert first["delivery_tracking_url"].startswith("https://www.phins.ai/delivery-tracking.html")
    assert "railway.app" not in first["delivery_tracking_url"]
    assert first["customer_email"]["sent"] is True
    assert second["customer_email"]["error"] == "already_sent"
    assert sends["n"] == 1

    public = svc.get_public_delivery_tracking(
        order_id=order_id,
        token=svc.orders[order_id]["delivery_tracking_token"],
    )
    assert public["destination"]["city"] == "Tel Aviv"
    assert public["status"] == "processing"

    # Wrong token must not mint a capability secret.
    before = dict(svc.orders[order_id])
    with pytest.raises(ValueError, match="Invalid tracking token"):
        svc.get_public_delivery_tracking(order_id=order_id, token="wrong-token")
    assert svc.orders[order_id].get("delivery_tracking_token") == before.get("delivery_tracking_token")

    svc.orders[order_id]["tracking_url"] = "javascript:alert(1)"
    public2 = svc.get_public_delivery_tracking(
        order_id=order_id,
        token=svc.orders[order_id]["delivery_tracking_token"],
    )
    assert public2["carrier_tracking_url"] == ""


def test_dispatch_status_sends_pre_dispatch_notice(monkeypatch):
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService

    svc = SupplyChainEcosystemService()
    order_id = "ORD-DISPATCH-2"
    svc.orders[order_id] = {
        "id": order_id,
        "supplier_id": "SUP-1",
        "customer_id": "CUST-1",
        "item_name": "Device",
        "status": "processing",
        "delivery_method": "pickup_counter",
        "total_amount": 10.0,
        "commission": 1.0,
        "supplier_payout": 9.0,
        "delivery_plan": {
            "recommended_method": {"method": "pickup_counter", "label": "Pickup"},
        },
    }
    monkeypatch.setattr(
        SupplyChainEcosystemService,
        "notify_customer_before_dispatch",
        lambda self, **kwargs: {
            "success": True,
            "delivery_tracking_url": "https://www.phins.ai/delivery-tracking.html?order_id=x&token=y",
            "customer_email": {"sent": True},
        },
    )
    monkeypatch.setattr(SupplyChainEcosystemService, "_record_ledger_entry", lambda *a, **k: None)
    result = svc.update_order_status(order_id, "in_transit", updated_by="supplier-demo")
    assert result["success"] is True
    assert result["order"]["status"] == "in_transit"
    assert result["pre_dispatch_notice"]["success"] is True


def test_complete_order_accrues_gmv_commission(monkeypatch):
    from services import agent_ecosystem_service as agent_svc
    from services.supply_chain_ecosystem_service import SupplyChainEcosystemService

    captured = {}

    def _accrue(principal_type, principal_id, base_amount, source_event_id,
                source_type="policy_premium", currency="USD", basis="premium",
                period="initial"):
        captured.update({
            "principal_type": principal_type,
            "principal_id": principal_id,
            "base_amount": base_amount,
            "source_event_id": source_event_id,
            "basis": basis,
            "source_type": source_type,
        })
        return {"id": "COMM-GMV-1", "amount": round(base_amount * 0.1, 2)}

    monkeypatch.setattr(agent_svc, "accrue_commission", _accrue)

    svc = SupplyChainEcosystemService()
    order_id = "ORD-GMV-1"
    svc.orders[order_id] = {
        "id": order_id,
        "supplier_id": "SUP-1",
        "customer_id": "CUST-GMV",
        "item_name": "Service",
        "status": "delivered",
        "total_amount": 100.0,
        "commission": 11.0,
        "supplier_payout": 89.0,
        "settlement_status": "customer_approved",
        "requires_customer_settlement_approval": True,
    }
    svc.suppliers["SUP-1"] = {"id": "SUP-1", "total_orders": 0, "completed_orders": 0,
                              "total_revenue": 0, "total_commission_paid": 0}
    monkeypatch.setattr(SupplyChainEcosystemService, "_record_ledger_entry", lambda *a, **k: None)
    result = svc.complete_order(order_id, "admin")
    assert result["success"] is True
    assert captured["basis"] == "gmv"
    assert captured["base_amount"] == 100.0
    assert captured["source_event_id"] == "order:ORD-GMV-1"
    assert result["agent_gmv_commission"]["id"] == "COMM-GMV-1"


def test_connection_integrity_gmv_basis_uses_marketplace_orders():
    from services import agent_ecosystem_service as agent_svc

    agent_svc.reset_agent_ecosystem()
    try:
        agent_svc.AGENTS["AGT-GMV"] = {"id": "AGT-GMV", "status": "active", "name": "Gmv Agent"}
        agent_svc.AFFILIATIONS["AFF-GMV"] = {
            "id": "AFF-GMV",
            "agent_id": "AGT-GMV",
            "principal_type": "customer",
            "principal_id": "CUST-GMV",
            "status": "active",
            "commission_rate": 0.10,
            "commission_basis": "gmv",
            "source_invitation_code": None,
        }
        customers = {"CUST-GMV": {"id": "CUST-GMV", "name": "Pat", "referring_agent_id": "AGT-GMV"}}
        orders = {
            "ORD-1": {
                "id": "ORD-1",
                "customer_id": "CUST-GMV",
                "status": "completed",
                "settlement_status": "pending_admin_payout",
                "total_amount": 200.0,
            }
        }
        report = agent_svc.connection_integrity(
            customers=customers,
            policies={},
            suppliers={},
            marketplace_orders=orders,
        )
        rows = [c for c in report.get("connections") or [] if c.get("customer_id") == "CUST-GMV"]
        assert rows
        assert rows[0]["commission_basis"] == "gmv"
        assert rows[0]["gmv_basis"] == 200.0
        assert rows[0]["expected_commission"] == 20.0
        # No accrued commission yet → shortfall warning, not silent pass.
        assert rows[0]["commission_consistent"] is False
    finally:
        agent_svc.reset_agent_ecosystem()
