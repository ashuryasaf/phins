"""
Supply-chain marketplace integration tests.

Validates the end-to-end pipeline:
invitation -> supplier registration -> admin approval -> offer publishing
-> customer purchase via wallet/card -> ledger integrity.
"""

import json
import threading
import time
from http.server import HTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import web_portal.server as portal


class ServerThread(threading.Thread):
    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


def _post(url: str, payload: dict, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
    with urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.status


def _get(url: str, token: str | None = None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.status


def _reset_supply_chain_state():
    with portal.STATE_LOCK:
        portal.SUPPLIERS.clear()
        portal.SUPPLIER_OFFERS.clear()
        portal.SUPPLIER_ORDERS.clear()
        portal.SUPPLIER_INVITATIONS.clear()
        portal.SUPPLY_CHAIN_LEDGER.clear()
        portal.HEALTH_WALLETS.clear()
        portal.MEDICAL_PURCHASES.clear()
        portal.TRANSACTION_LEDGER.clear()
        portal.NFT_LEDGER.clear()
    if getattr(portal, "supply_chain_service", None):
        portal.supply_chain_service.orders.clear()
        portal.supply_chain_service.pending_settlements.clear()
        portal.supply_chain_service.settlement_history.clear()
        portal.supply_chain_service.ledger_chain.clear()


def test_supply_chain_invitation_to_purchase_pipeline_with_ledger_integrity():
    _reset_supply_chain_state()

    port = 8161
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.5)
    base = f"http://127.0.0.1:{port}"

    try:
        # Admin login (test mode legacy password allowed).
        admin_login, status = _post(
            f"{base}/api/login",
            {"username": "admin", "password": "admin123"},
        )
        assert status == 200
        admin_token = admin_login["token"]

        # 1) Generate invitation code for suppliers.
        inv, status = _post(
            f"{base}/api/supply-chain/invitations",
            {
                "supplier_type": "pharmacy",
                "max_uses": 2,
                "expires_days": 30,
                "notes": "integration test invitation",
            },
            token=admin_token,
        )
        assert status == 201
        invitation_code = (inv.get("invitation") or {}).get("code")
        assert invitation_code

        # 2) Supplier registers using invitation code.
        reg, status = _post(
            f"{base}/api/supply-chain/register",
            {
                "invitation_code": invitation_code,
                "company_name": "Prime Medications Ltd",
                "contact_email": "prime-med@example.com",
                "contact_name": "Prime Contact",
                "supplier_type": "pharmacy",
                "password": "PrimePass123!",
                "business_registration_number": "REG-PRIME-100",
                "license_number": "LIC-PRIME-2026",
                "description": "Medication supplier for insured customers",
            },
        )
        assert status == 201
        supplier_id = reg.get("supplier_id")
        assert supplier_id

        # 3) Admin approves supplier account.
        approved, status = _post(
            f"{base}/api/supply-chain/suppliers/{supplier_id}/approve",
            {"notes": "Approved for marketplace"},
            token=admin_token,
        )
        assert status == 200
        assert approved.get("status") == "approved"

        # 4) Supplier logs in and creates a rich offer.
        supplier_login, status = _post(
            f"{base}/api/supplier/login",
            {"email": "prime-med@example.com", "password": "PrimePass123!"},
        )
        assert status == 200
        supplier_token = supplier_login["token"]

        offer_res, status = _post(
            f"{base}/api/supplier/offers/upsert",
            {
                "name": "Insured Medication Bundle",
                "description": "Monthly medication package for chronic conditions",
                "item_type": "product",
                "category": "medication",
                "price": 80.0,
                "currency": "USD",
                "wallet_compatible": ["health"],
                "delivery_config": {"mode": "delivery", "eta_days": 2, "fee": 6.5},
                "billing_config": {
                    "billing_cycle": "one_time",
                    "billing_terms": "Net 15",
                    "invoice_supported": True,
                    "tax_rate_pct": 0.0,
                },
            },
            token=supplier_token,
        )
        assert status in (200, 201)
        offer_id = offer_res.get("id")
        assert offer_id

        # 5) Customer-facing offerings endpoint returns categorized data.
        offerings, status = _get(f"{base}/api/marketplace/offerings?category=medication&wallet=health")
        assert status == 200
        assert offerings.get("success") is True
        assert any(item.get("id") == offer_id for item in offerings.get("items", []))
        assert "category_groups" in offerings

        # 6) Fund wallet and buy using wallet payment.
        _, status = _post(
            f"{base}/api/health-wallet/deposit",
            {"customer_id": "CUST-PIPE-001", "amount": 500.0, "payment_method": "card_on_file"},
        )
        assert status == 200

        wallet_purchase, status = _post(
            f"{base}/api/health-wallet/purchase",
            {
                "customer_id": "CUST-PIPE-001",
                "product_id": offer_id,
                "offer_id": offer_id,
                "product_name": "Insured Medication Bundle",
                "amount": 80.0,
                "quantity": 2,
                "payment_method": "health_wallet",
                "category": "medication",
                "allow_credit_fallback": False,
            },
        )
        assert status == 200
        assert wallet_purchase.get("success") is True
        assert wallet_purchase.get("pricing_plan", {}).get("expense_loading_amount", 0) > 0
        assert wallet_purchase.get("pricing_plan", {}).get("profit_margin_amount", 0) > 0
        assert wallet_purchase.get("purchase", {}).get("wallet_deduction", 0) > 0

        # 7) Buy using card path (no wallet deduction expected).
        card_purchase, status = _post(
            f"{base}/api/health-wallet/purchase",
            {
                "customer_id": "CUST-PIPE-001",
                "product_id": offer_id,
                "offer_id": offer_id,
                "product_name": "Insured Medication Bundle",
                "amount": 80.0,
                "quantity": 1,
                "payment_method": "credit_card",
                "category": "medication",
            },
        )
        assert status == 200
        assert card_purchase.get("success") is True
        assert card_purchase.get("purchase", {}).get("external_payment_amount", 0) > 0
        assert card_purchase.get("purchase", {}).get("external_payment_method") in ("credit_card", "card")

        # 8) Purchase history is available and ledger-linked.
        purchases, status = _get(
            f"{base}/api/health-wallet/purchases?customer_id=CUST-PIPE-001",
            token=admin_token,
        )
        assert status == 200
        rows = purchases.get("purchases", [])
        assert len(rows) >= 2
        assert any((p.get("offer_id") == offer_id or p.get("product_id") == offer_id) for p in rows)
        assert all(p.get("ledger_tx_id") for p in rows[:2])

        # 9) Supply-chain ledger remains verifiable.
        integrity, status = _get(f"{base}/api/supply-chain/ledger/verify", token=admin_token)
        assert status == 200
        assert integrity.get("total_entries", 0) > 0
        assert integrity.get("integrity_score", 0) >= 99

    except HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise AssertionError(f"Unexpected HTTPError {e.code}: {body}") from e
    finally:
        srv.stop()


def test_supplier_orders_endpoint_returns_supply_chain_orders_with_expected_fields():
    _reset_supply_chain_state()

    port = 8162
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.5)
    base = f"http://127.0.0.1:{port}"

    try:
        admin_login, status = _post(
            f"{base}/api/login",
            {"username": "admin", "password": "admin123"},
        )
        assert status == 200
        admin_token = admin_login["token"]

        inv, status = _post(
            f"{base}/api/supply-chain/invitations",
            {
                "supplier_type": "pharmacy",
                "max_uses": 1,
                "expires_days": 30,
                "notes": "supplier orders endpoint test",
            },
            token=admin_token,
        )
        assert status == 201
        invitation_code = (inv.get("invitation") or {}).get("code")
        assert invitation_code

        reg, status = _post(
            f"{base}/api/supply-chain/register",
            {
                "invitation_code": invitation_code,
                "company_name": "Visible Orders Pharmacy",
                "contact_email": "visible-orders@example.com",
                "contact_name": "Visible Orders Contact",
                "supplier_type": "pharmacy",
                "password": "VisibleOrders123!",
            },
        )
        assert status == 201
        supplier_id = reg.get("supplier_id")
        assert supplier_id

        approved, status = _post(
            f"{base}/api/supply-chain/suppliers/{supplier_id}/approve",
            {"notes": "Approved for supplier order endpoint test"},
            token=admin_token,
        )
        assert status == 200
        assert approved.get("status") == "approved"

        supplier_login, status = _post(
            f"{base}/api/supplier/login",
            {"email": "visible-orders@example.com", "password": "VisibleOrders123!"},
        )
        assert status == 200
        supplier_token = supplier_login["token"]

        offer_res, status = _post(
            f"{base}/api/supplier/offers/upsert",
            {
                "name": "Supplier Orders Medication Kit",
                "description": "Order visibility regression coverage",
                "item_type": "product",
                "category": "medication",
                "price": 55.0,
                "currency": "USD",
                "wallet_compatible": ["health"],
            },
            token=supplier_token,
        )
        assert status in (200, 201)
        offer_id = offer_res.get("id")
        assert offer_id

        _, status = _post(
            f"{base}/api/health-wallet/deposit",
            {"customer_id": "CUST-SUP-ORD-001", "amount": 250.0, "payment_method": "card_on_file"},
        )
        assert status == 200

        purchase, status = _post(
            f"{base}/api/health-wallet/purchase",
            {
                "customer_id": "CUST-SUP-ORD-001",
                "offer_id": offer_id,
                "product_id": offer_id,
                "product_name": "Supplier Orders Medication Kit",
                "amount": 55.0,
                "quantity": 2,
                "payment_method": "health_wallet",
                "category": "medication",
                "allow_credit_fallback": False,
            },
        )
        assert status == 200
        assert purchase.get("success") is True

        supplier_orders, status = _get(f"{base}/api/supplier/orders", token=supplier_token)
        assert status == 200
        items = supplier_orders.get("items", [])
        assert len(items) == 1

        order = items[0]
        assert order.get("supplier_id") == supplier_id
        assert order.get("customer_id") == "CUST-SUP-ORD-001"
        assert order.get("offer_id") == offer_id
        assert order.get("item_name") == "Supplier Orders Medication Kit"
        assert order.get("quantity") == 2
        assert order.get("total_amount", 0) > 0
        assert order.get("supplier_payout", 0) > 0
        assert order.get("created_date")
        assert order.get("status") == "completed"
        assert order.get("payment_status") == "paid"

        confirm_result, status = _post(
            f"{base}/api/supplier/orders/update-status",
            {
                "transaction_id": order["id"],
                "status": "completed",
            },
            token=supplier_token,
        )
        assert status == 200
        assert confirm_result.get("success") is True
        assert confirm_result.get("order", {}).get("id") == order["id"]
        assert confirm_result.get("order", {}).get("status") == "completed"

    except HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise AssertionError(f"Unexpected HTTPError {e.code}: {body}") from e
    finally:
        srv.stop()


def test_marketplace_order_parity_across_customer_admin_and_settlement_views():
    _reset_supply_chain_state()

    port = 8163
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.5)
    base = f"http://127.0.0.1:{port}"

    try:
        admin_login, status = _post(
            f"{base}/api/login",
            {"username": "admin", "password": "admin123"},
        )
        assert status == 200
        admin_token = admin_login["token"]

        invitation, status = _post(
            f"{base}/api/supply-chain/invitations",
            {
                "supplier_type": "pharmacy",
                "max_uses": 1,
                "expires_days": 30,
                "notes": "parity test invitation",
            },
            token=admin_token,
        )
        assert status == 201
        invitation_code = (invitation.get("invitation") or {}).get("code")
        assert invitation_code

        supplier_reg, status = _post(
            f"{base}/api/supply-chain/register",
            {
                "invitation_code": invitation_code,
                "company_name": "Parity Pharmacy",
                "contact_email": "parity-pharmacy@example.com",
                "contact_name": "Parity Contact",
                "supplier_type": "pharmacy",
                "password": "ParityPass123!",
            },
        )
        assert status == 201
        supplier_id = supplier_reg.get("supplier_id")
        assert supplier_id

        _, status = _post(
            f"{base}/api/supply-chain/suppliers/{supplier_id}/approve",
            {"notes": "Approved for parity test"},
            token=admin_token,
        )
        assert status == 200

        supplier_login, status = _post(
            f"{base}/api/supplier/login",
            {"email": "parity-pharmacy@example.com", "password": "ParityPass123!"},
        )
        assert status == 200
        supplier_token = supplier_login["token"]

        offer_res, status = _post(
            f"{base}/api/supplier/offers/upsert",
            {
                "name": "Parity Refill Pack",
                "description": "Cross-dashboard parity coverage",
                "item_type": "product",
                "category": "medication",
                "price": 42.0,
                "currency": "USD",
                "wallet_compatible": ["health"],
            },
            token=supplier_token,
        )
        assert status in (200, 201)
        offer_id = offer_res.get("id")
        assert offer_id

        customer_id = "CUST-PARITY-001"
        with portal.STATE_LOCK:
            portal.CUSTOMERS[customer_id] = {
                "id": customer_id,
                "name": "Parity Customer",
                "email": "parity-customer@example.com",
            }

        _, status = _post(
            f"{base}/api/health-wallet/deposit",
            {"customer_id": customer_id, "amount": 200.0, "payment_method": "card_on_file"},
        )
        assert status == 200

        purchase_result, status = _post(
            f"{base}/api/health-wallet/purchase",
            {
                "customer_id": customer_id,
                "offer_id": offer_id,
                "product_id": offer_id,
                "product_name": "Parity Refill Pack",
                "amount": 42.0,
                "quantity": 2,
                "payment_method": "health_wallet",
                "category": "medication",
                "allow_credit_fallback": False,
            },
        )
        assert status == 200
        assert purchase_result.get("success") is True

        supplier_orders, status = _get(f"{base}/api/supplier/orders", token=supplier_token)
        assert status == 200
        supplier_items = supplier_orders.get("items", [])
        assert len(supplier_items) == 1
        order = supplier_items[0]
        assert order.get("customer_name") == "Parity Customer"
        assert order.get("supplier_name") == "Parity Pharmacy"
        assert order.get("platform_fee", 0) > 0
        assert order.get("supplier_payout", 0) > 0

        customer_history, status = _get(
            f"{base}/api/health-wallet/purchases?customer_id={customer_id}",
            token=admin_token,
        )
        assert status == 200
        purchases = customer_history.get("purchases", [])
        assert len(purchases) == 1
        purchase = purchases[0]
        assert purchase.get("order_id") == order.get("id")
        assert purchase.get("supplier_name") == "Parity Pharmacy"
        assert purchase.get("provider_name") == "Parity Pharmacy"
        assert purchase.get("customer_name") == "Parity Customer"
        assert purchase.get("wallet_paid", 0) > 0
        assert purchase.get("platform_fee", 0) > 0
        assert purchase.get("supplier_payout", 0) > 0
        assert purchase.get("can_cancel") is False
        assert purchase.get("can_refund") is False

        admin_orders, status = _get(f"{base}/api/admin/suppliers/orders", token=admin_token)
        assert status == 200
        admin_items = admin_orders.get("items", [])
        assert len(admin_items) == 1
        admin_order = admin_items[0]
        assert admin_order.get("customer_name") == "Parity Customer"
        assert admin_order.get("supplier_name") == "Parity Pharmacy"
        assert admin_order.get("platform_fee", 0) > 0
        assert admin_order.get("supplier_payout", 0) > 0

        settlements, status = _get(f"{base}/api/supply-chain/settlements", token=supplier_token)
        assert status == 200
        assert settlements.get("supplier_id") == supplier_id
        assert settlements.get("pending_orders") == 1
        assert settlements.get("pending_amount", 0) > 0

        stats, status = _get(
            f"{base}/api/supply-chain/suppliers/{supplier_id}/statistics",
            token=supplier_token,
        )
        assert status == 200
        assert stats.get("company_name") == "Parity Pharmacy"
        assert stats.get("pending_settlement", 0) > 0

        pnl, status = _get(
            f"{base}/api/supply-chain/suppliers/{supplier_id}/pnl",
            token=supplier_token,
        )
        assert status == 200
        assert pnl.get("success") is True
        assert pnl.get("supplier_name") == "Parity Pharmacy"
        assert pnl.get("report", {}).get("gross_sales", 0) == admin_order.get("total_amount", 0)
        assert pnl.get("report", {}).get("payment_processing_fees", 0) == round(
            admin_order.get("total_amount", 0) * 0.025, 2
        )
        assert pnl.get("report", {}).get("net_payout", 0) == admin_order.get("supplier_payout", 0)
        assert pnl.get("report", {}).get("pending_settlement", 0) == settlements.get("pending_amount", 0)

        performance, status = _get(f"{base}/api/supplier/performance", token=supplier_token)
        assert status == 200
        assert performance.get("success") is True
        assert performance.get("pnl", {}).get("report", {}).get("pending_settlement", 0) == settlements.get("pending_amount", 0)

        settlement_run, status = _post(
            f"{base}/api/supply-chain/settlements/{supplier_id}/process",
            {},
            token=admin_token,
        )
        assert status == 200
        assert settlement_run.get("success") is True
        assert settlement_run.get("amount", 0) == admin_order.get("supplier_payout", 0)

        settlements_after, status = _get(f"{base}/api/supply-chain/settlements", token=supplier_token)
        assert status == 200
        assert settlements_after.get("pending_orders") == 0
        assert settlements_after.get("pending_amount", 0) == 0

        pnl_after, status = _get(
            f"{base}/api/supply-chain/suppliers/{supplier_id}/pnl",
            token=supplier_token,
        )
        assert status == 200
        assert pnl_after.get("report", {}).get("pending_settlement", 0) == 0
        assert pnl_after.get("report", {}).get("settled_amount", 0) == settlement_run.get("amount", 0)

    except HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise AssertionError(f"Unexpected HTTPError {e.code}: {body}") from e
    finally:
        srv.stop()


def test_marketplace_cancel_and_refund_endpoints_update_customer_and_admin_views():
    _reset_supply_chain_state()

    port = 8164
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.5)
    base = f"http://127.0.0.1:{port}"

    try:
        admin_login, status = _post(
            f"{base}/api/login",
            {"username": "admin", "password": "admin123"},
        )
        assert status == 200
        admin_token = admin_login["token"]

        invitation, status = _post(
            f"{base}/api/supply-chain/invitations",
            {
                "supplier_type": "pharmacy",
                "max_uses": 1,
                "expires_days": 30,
                "notes": "cancel refund parity",
            },
            token=admin_token,
        )
        assert status == 201
        invitation_code = (invitation.get("invitation") or {}).get("code")
        assert invitation_code

        supplier_reg, status = _post(
            f"{base}/api/supply-chain/register",
            {
                "invitation_code": invitation_code,
                "company_name": "Refund Pharmacy",
                "contact_email": "refund-pharmacy@example.com",
                "contact_name": "Refund Contact",
                "supplier_type": "pharmacy",
                "password": "RefundPass123!",
            },
        )
        assert status == 201
        supplier_id = supplier_reg.get("supplier_id")
        assert supplier_id

        _, status = _post(
            f"{base}/api/supply-chain/suppliers/{supplier_id}/approve",
            {"notes": "Approved for refund test"},
            token=admin_token,
        )
        assert status == 200

        supplier_login, status = _post(
            f"{base}/api/supplier/login",
            {"email": "refund-pharmacy@example.com", "password": "RefundPass123!"},
        )
        assert status == 200

        offer_res, status = _post(
            f"{base}/api/supplier/offers/upsert",
            {
                "name": "Refundable Refill Pack",
                "description": "Refund flow coverage",
                "item_type": "product",
                "category": "medication",
                "price": 30.0,
                "currency": "USD",
                "wallet_compatible": ["health"],
            },
            token=supplier_login["token"],
        )
        assert status in (200, 201)
        offer_id = offer_res.get("id")
        assert offer_id

        customer_id = "CUST-REFUND-001"
        with portal.STATE_LOCK:
            portal.CUSTOMERS[customer_id] = {
                "id": customer_id,
                "name": "Refund Customer",
                "email": "refund-customer@example.com",
            }

        _, status = _post(
            f"{base}/api/health-wallet/deposit",
            {"customer_id": customer_id, "amount": 200.0, "payment_method": "card_on_file"},
        )
        assert status == 200

        purchase_result, status = _post(
            f"{base}/api/health-wallet/purchase",
            {
                "customer_id": customer_id,
                "offer_id": offer_id,
                "product_id": offer_id,
                "product_name": "Refundable Refill Pack",
                "amount": 30.0,
                "quantity": 1,
                "payment_method": "health_wallet",
                "category": "medication",
                "allow_credit_fallback": False,
            },
        )
        assert status == 200
        assert purchase_result.get("success") is True
        purchase_id = purchase_result.get("purchase", {}).get("id")
        assert purchase_id

        history_before, status = _get(
            f"{base}/api/health-wallet/purchases?customer_id={customer_id}",
            token=admin_token,
        )
        assert status == 200
        before_rows = history_before.get("purchases", [])
        assert len(before_rows) == 1
        assert before_rows[0].get("status") == "completed"

        refund_result, status = _post(
            f"{base}/api/marketplace/orders/refund",
            {"purchase_id": purchase_id, "customer_id": customer_id},
            token=admin_token,
        )
        assert status == 200
        assert refund_result.get("success") is True

        history_after, status = _get(
            f"{base}/api/health-wallet/purchases?customer_id={customer_id}",
            token=admin_token,
        )
        assert status == 200
        after_rows = history_after.get("purchases", [])
        assert len(after_rows) == 1
        assert after_rows[0].get("status") == "refunded"
        assert after_rows[0].get("refunded_amount", 0) > 0
        assert after_rows[0].get("can_refund") is False

        admin_orders, status = _get(f"{base}/api/admin/suppliers/orders", token=admin_token)
        assert status == 200
        admin_items = admin_orders.get("items", [])
        assert len(admin_items) == 1
        assert admin_items[0].get("status") == "refunded"
        assert admin_items[0].get("customer_name") == "Refund Customer"

    except HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise AssertionError(f"Unexpected HTTPError {e.code}: {body}") from e
    finally:
        srv.stop()


def test_location_aware_delivery_options_and_validation_flow():
    _reset_supply_chain_state()

    port = 8165
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.5)
    base = f"http://127.0.0.1:{port}"

    try:
        admin_login, status = _post(
            f"{base}/api/login",
            {"username": "admin", "password": "admin123"},
        )
        assert status == 200
        admin_token = admin_login["token"]

        invitation, status = _post(
            f"{base}/api/supply-chain/invitations",
            {
                "supplier_type": "clinic",
                "max_uses": 1,
                "expires_days": 30,
                "notes": "delivery validation flow",
            },
            token=admin_token,
        )
        assert status == 201
        invitation_code = (invitation.get("invitation") or {}).get("code")
        assert invitation_code

        supplier_reg, status = _post(
            f"{base}/api/supply-chain/register",
            {
                "invitation_code": invitation_code,
                "company_name": "Geo Care Clinic",
                "contact_email": "geo-care@example.com",
                "contact_name": "Geo Care",
                "supplier_type": "clinic",
                "password": "GeoCare123!",
                "address": "1 Supplier Way",
                "city": "Tel Aviv",
                "country": "Israel",
                "latitude": 32.0853,
                "longitude": 34.7818,
                "service_radius_km": 25,
            },
        )
        assert status == 201
        supplier_id = supplier_reg.get("supplier_id")
        assert supplier_id

        _, status = _post(
            f"{base}/api/supply-chain/suppliers/{supplier_id}/approve",
            {"notes": "Approved for delivery validation test"},
            token=admin_token,
        )
        assert status == 200

        supplier_login, status = _post(
            f"{base}/api/supplier/login",
            {"email": "geo-care@example.com", "password": "GeoCare123!"},
        )
        assert status == 200
        supplier_token = supplier_login["token"]

        offer_res, status = _post(
            f"{base}/api/supplier/offers/upsert",
            {
                "name": "At-Home Nurse Visit",
                "description": "Location-aware care visit",
                "item_type": "service",
                "category": "home_care",
                "price": 120.0,
                "currency": "USD",
                "wallet_compatible": ["health"],
                "delivery_config": {
                    "mode": "on_site",
                    "eta_days": 0,
                    "fee": 10.0,
                    "service_radius_km": 30,
                },
            },
            token=supplier_token,
        )
        assert status in (200, 201)
        offer_id = offer_res.get("id")
        assert offer_id

        _, status = _post(
            f"{base}/api/health-wallet/deposit",
            {"customer_id": "CUST-GEO-001", "amount": 500.0, "payment_method": "card_on_file"},
        )
        assert status == 200

        options, status = _post(
            f"{base}/api/supply-chain/orders/delivery-options",
            {
                "supplier_id": supplier_id,
                "offer_id": offer_id,
                "quantity": 1,
                "delivery_location": {
                    "latitude": 32.0900,
                    "longitude": 34.7900,
                    "address": "99 Patient Street",
                    "city": "Tel Aviv",
                    "country": "Israel",
                },
            },
            token=admin_token,
        )
        assert status == 200
        plan = options.get("delivery_plan", {})
        assert plan.get("distance_km", 999) < 25
        assert plan.get("recommended_method", {}).get("method") == "on_site_visit"
        assert any(method.get("method") == "telehealth_video" for method in plan.get("possible_methods", []))

        order_result, status = _post(
            f"{base}/api/supply-chain/orders",
            {
                "customer_id": "CUST-GEO-001",
                "supplier_id": supplier_id,
                "offer_id": offer_id,
                "quantity": 1,
                "payment_method": "health_wallet",
                "delivery_location": {
                    "latitude": 32.0900,
                    "longitude": 34.7900,
                    "address": "99 Patient Street",
                    "city": "Tel Aviv",
                    "country": "Israel",
                },
                "delivery_address": {
                    "latitude": 32.0900,
                    "longitude": 34.7900,
                    "address": "99 Patient Street",
                    "city": "Tel Aviv",
                    "country": "Israel",
                },
            },
            token=admin_token,
        )
        assert status == 201
        order = order_result.get("order", {})
        order_id = order.get("id")
        assert order_id
        assert order.get("delivery_plan", {}).get("recommended_method", {}).get("method") == "on_site_visit"
        validation_code = order.get("delivery_validation_code")
        assert validation_code

        _, status = _post(
            f"{base}/api/supplier/orders/update-status",
            {"transaction_id": order_id, "status": "confirmed"},
            token=supplier_token,
        )
        assert status == 200
        _, status = _post(
            f"{base}/api/supplier/orders/update-status",
            {"transaction_id": order_id, "status": "processing"},
            token=supplier_token,
        )
        assert status == 200
        _, status = _post(
            f"{base}/api/supplier/orders/update-status",
            {"transaction_id": order_id, "status": "delivered"},
            token=supplier_token,
        )
        assert status == 200

        validation, status = _post(
            f"{base}/api/supply-chain/orders/{order_id}/delivery-validation",
            {
                "delivery_method": "on_site_visit",
                "validation_code": validation_code,
                "proof_type": "geo_checkin",
                "proof_url": "https://example.com/proof/geo-checkin",
                "delivery_location": {
                    "latitude": 32.0900,
                    "longitude": 34.7900,
                    "address": "99 Patient Street",
                    "city": "Tel Aviv",
                    "country": "Israel",
                },
            },
            token=supplier_token,
        )
        assert status == 200
        assert validation.get("success") is True
        assert validation.get("order", {}).get("status") == "completed"
        assert validation.get("validation", {}).get("validated") is True
        assert validation.get("validation", {}).get("method") == "geo_checkin"

    except HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise AssertionError(f"Unexpected HTTPError {e.code}: {body}") from e
    finally:
        srv.stop()

