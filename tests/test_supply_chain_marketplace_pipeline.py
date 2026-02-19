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
        self.httpd.server_close()


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
        portal.SUPPLIER_INVITATIONS.clear()
        portal.SUPPLY_CHAIN_LEDGER.clear()
        portal.HEALTH_WALLETS.clear()
        portal.MEDICAL_PURCHASES.clear()
        portal.TRANSACTION_LEDGER.clear()
        portal.NFT_LEDGER.clear()
    if getattr(portal, "supply_chain_service", None):
        portal.supply_chain_service.pending_settlements.clear()
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

