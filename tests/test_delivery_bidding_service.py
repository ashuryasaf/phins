import pytest

from services.delivery_bidding_service import DeliveryBiddingService
from services.supply_chain_ecosystem_service import init_supply_chain_service


def test_delivery_bidding_flow():
    suppliers = {
        "SUP-DEL-001": {
            "id": "SUP-DEL-001",
            "company_name": "QuickShip",
            "supplier_type": "delivery",
            "status": "approved",
            "portal_active": True,
            "average_rating": 4.6,
            "on_time_delivery_rate": 96.0,
            "service_areas": ["New York", "NYC"],
        },
        "SUP-OTHER-001": {
            "id": "SUP-OTHER-001",
            "company_name": "Other Services",
            "supplier_type": "pharmacy",
            "status": "approved",
            "portal_active": True,
            "service_areas": ["New York"],
        },
    }
    health_wallets = {"CUST-001": {"balance": 120.0, "transactions": []}}
    transaction_ledger = {}
    nft_ledger = {}

    def record_transaction(customer_id, tx_type, amount, description, metadata=None):
        tx_id = f"TX-{len(transaction_ledger) + 1:04d}"
        tx = {
            "id": tx_id,
            "customer_id": customer_id,
            "tx_type": tx_type,
            "amount": amount,
            "description": description,
            "metadata": metadata or {},
        }
        transaction_ledger[tx_id] = tx
        return tx

    supply_chain_service = init_supply_chain_service(
        suppliers=suppliers,
        invitations={},
        offers={},
        orders={},
        ledger={},
        health_wallets=health_wallets,
        billing={},
        nft_ledger=nft_ledger,
        transaction_ledger=transaction_ledger,
        record_transaction_func=record_transaction,
    )

    service = DeliveryBiddingService(
        requests_store={},
        bids_store={},
        suppliers_store=suppliers,
        health_wallets=health_wallets,
        transaction_ledger=transaction_ledger,
        supply_chain_service=supply_chain_service,
        record_transaction_func=record_transaction,
    )

    request = service.create_request(
        customer_id="CUST-001",
        order_id="ORD-100",
        preferences={"priority": "speed", "target_eta_minutes": 90},
        location={"city": "New York", "radius_km": 30},
        max_bid_amount=30.0,
    )
    assert request["status"] in ["bidding", "pending_suppliers"]
    assert "SUP-DEL-001" in request["eligible_suppliers"]
    assert "SUP-OTHER-001" not in request["eligible_suppliers"]

    bid = service.submit_bid(
        request_id=request["request_id"],
        supplier_id="SUP-DEL-001",
        amount=25.0,
        eta_minutes=60,
        notes="Fast delivery",
    )
    assert bid["status"] == "submitted"

    with pytest.raises(ValueError):
        service.submit_bid(
            request_id=request["request_id"],
            supplier_id="SUP-OTHER-001",
            amount=20.0,
            eta_minutes=70,
        )

    award = service.award_bid(
        request_id=request["request_id"],
        bid_id=bid["bid_id"],
        awarded_by="CUST-001",
    )
    assert award["request"]["status"] == "awarded"
    assert health_wallets["CUST-001"]["reserved"] == pytest.approx(25.0)

    acceptance = service.accept_assignment(
        request_id=request["request_id"],
        supplier_id="SUP-DEL-001",
    )
    assert acceptance["request"]["status"] == "accepted"

    delivery = service.mark_delivered(
        request_id=request["request_id"],
        supplier_id="SUP-DEL-001",
    )
    assert delivery["request"]["status"] == "delivered"
    assert health_wallets["CUST-001"]["balance"] == pytest.approx(95.0)
    assert health_wallets["CUST-001"]["reserved"] == pytest.approx(0.0)
    assert any(tx.get("tx_type") == "delivery_payment" for tx in transaction_ledger.values())

    integrity = service.validate_integrity()
    assert integrity["integrity_status"] == "HEALTHY"
