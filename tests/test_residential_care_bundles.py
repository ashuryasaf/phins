"""Health-wallet residential care bundles.

The card price is the ledger amount. Expense loading, profit, and the
discounted rate decompose that total; they are not added on top. A client
cannot rename the bundle or pay a different figure.
"""

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image

import web_portal.server as portal
from services.nft_ledger import affiliate_issues


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _post(path, payload):
    base = os.environ["TEST_BASE_URL"].rstrip("/")
    data = json.dumps(payload).encode("utf-8")
    req = Request(
        base + path,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _get(path):
    base = os.environ["TEST_BASE_URL"].rstrip("/")
    with urlopen(base + path) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.status


def _plan_identity(plan, total, exact_rates=True):
    components = round(
        plan["base_amount"]
        + plan["expense_loading_amount"]
        + plan["profit_margin_amount"]
        - plan["discounted_rate_amount"],
        2,
    )
    assert components == plan["final_customer_amount"] == total
    assert plan["expense_loading_pct"] == portal.DEFAULT_WALLET_EXPENSE_LOADING_PCT
    assert plan["profit_margin_pct"] == portal.DEFAULT_WALLET_PROFIT_MARGIN_PCT
    if exact_rates:
        assert plan["discounted_rate_pct"] == portal.DEFAULT_WALLET_DISCOUNTED_RATE_PCT
    else:
        assert abs(plan["discounted_rate_pct"] - portal.DEFAULT_WALLET_DISCOUNTED_RATE_PCT) < 0.0001
    assert plan["price_source"] == "residential_catalog"


def _prime_port():
    """First request of a test clears in-memory wallets. Do it before seeding."""
    _get("/api/medical-products?category=residential")


def _fund(customer_id, amount):
    status, body = _post("/api/health-wallet/deposit", {
        "customer_id": customer_id,
        "amount": amount,
        "payment_method": "card_on_file",
    })
    assert status == 200, body
    return body


def _medical_rows(customer_id, known_ids):
    return [
        tx for tx_id, tx in portal.TRANSACTION_LEDGER.items()
        if tx_id not in known_ids
        and tx.get("customer_id") == customer_id
        and tx.get("type") == "medical_purchase"
    ]


def test_catalog_prices_decompose_onto_the_same_total():
    catalog = portal.residential_care_catalog()
    assert [row["id"] for row in catalog] == ["res-home", "res-extra", "res-full"]
    assert [row["name"] for row in catalog] == [
        "Home Bundle",
        "Extra Bundle",
        "Full Accommodation Bundle",
    ]
    assert [row["price"] for row in catalog] == [8400.00, 10800.00, 14500.00]
    for row in catalog:
        assert row["category"] == "residential"
        assert row["price_source"] == "residential_catalog"
        assert row["service_period"] == "monthly"
        assert row["image_url"].startswith("/marketplace/residential-")
        _plan_identity(portal.pricing_plan_for_catalog_total(row["price"]), row["price"])
        _plan_identity(
            portal.pricing_plan_for_catalog_total(round(row["price"] * 2, 2)),
            round(row["price"] * 2, 2),
        )
    year_total = round(14500.00 * portal.RESIDENTIAL_CARE_MAX_PERIODS, 2)
    _plan_identity(
        portal.pricing_plan_for_catalog_total(year_total),
        year_total,
        exact_rates=False,
    )


def test_catalog_images_are_photographs_and_listed_on_the_wallet():
    dashboard = open(
        os.path.join(ROOT, "web_portal", "static", "dashboard.html"),
        encoding="utf-8",
    ).read()
    portal_html = open(
        os.path.join(ROOT, "web_portal", "static", "supplier-portal.html"),
        encoding="utf-8",
    ).read()
    hebrew = json.load(open(os.path.join(ROOT, "web_portal", "static", "locales", "he.json"), encoding="utf-8"))
    assert hebrew["strings"]["Health Care Residential Solutions"]
    assert hebrew["strings"]["Home Bundle"]
    assert hebrew["strings"]["Full Accommodation Bundle"]
    assert 'showMedicalCategory(\'residential\')' in dashboard
    assert 'value="residential"' in portal_html

    for name in (
        "residential-solutions.jpg",
        "residential-home.jpg",
        "residential-extra.jpg",
        "residential-full.jpg",
    ):
        path = os.path.join(ROOT, "web_portal", "static", "marketplace", name)
        with open(path, "rb") as handle:
            assert handle.read(3) == b"\xff\xd8\xff"
        image = Image.open(path)
        assert image.format == "JPEG"
        assert image.size == (1152, 864)


def test_medical_products_api_serves_the_three_bundles():
    catalog, status = _get("/api/medical-products?category=residential")
    assert status == 200
    rows = {item["id"]: item for item in catalog["products"]}
    assert set(rows) == {"res-home", "res-extra", "res-full"}
    assert rows["res-home"]["price"] == 8400
    assert rows["res-extra"]["name"] == "Extra Bundle"
    assert "away from home" in rows["res-extra"]["description"]
    assert "Medicare" in rows["res-full"]["description"]
    assert rows["res-full"]["image_url"] == "/marketplace/residential-full.jpg"
    assert all(item["category"] == "residential" for item in rows.values())

    home, _ = _get("/api/medical-products?category=homecare")
    assert "res-home" not in {item["id"] for item in home["products"]}


def test_residential_purchase_posts_the_card_price_once():
    customer_id = "CUST-RES-CARE-1"
    bundle = portal.residential_care_by_id("res-home")
    price = bundle["price"]
    _prime_port()
    _fund(customer_id, 20000)
    ledger_before = set(portal.TRANSACTION_LEDGER)
    nft_before = set(portal.NFT_LEDGER)
    purchases_before = set(portal.MEDICAL_PURCHASES)
    try:
        mismatch, mismatch_body = _post("/api/health-wallet/purchase", {
            "customer_id": customer_id,
            "product_id": "res-home",
            "product_name": "Home Bundle discounted",
            "amount": 1,
            "quantity": 1,
            "category": "homecare",
            "provider": "Someone Else",
            "payment_method": "health_wallet",
            "expense_loading_pct": 0,
            "profit_margin_pct": 0,
            "discounted_rate_pct": 0,
        })
        assert mismatch == 400
        assert mismatch_body["error"] == "Catalog price mismatch"
        assert mismatch_body["catalog_amount"] == price
        assert portal.HEALTH_WALLETS[customer_id]["balance"] == 20000.00
        assert _medical_rows(customer_id, ledger_before) == []
        assert set(portal.MEDICAL_PURCHASES) == purchases_before

        short, short_body = _post("/api/health-wallet/purchase", {
            "customer_id": customer_id,
            "product_id": "res-full",
            "product_name": "Full Accommodation Bundle",
            "amount": 29000,
            "quantity": 2,
            "category": "residential",
            "payment_method": "health_wallet",
        })
        assert short == 400
        assert short_body["error"] == "Insufficient balance"
        assert portal.HEALTH_WALLETS[customer_id]["balance"] == 20000.00
        assert _medical_rows(customer_id, ledger_before) == []

        status, body = _post("/api/health-wallet/purchase", {
            "customer_id": customer_id,
            "product_id": "res-home",
            "product_name": "Not the catalog name",
            "amount": price,
            "quantity": 1,
            "category": "homecare",
            "provider": "Someone Else",
            "payment_method": "health_wallet",
            "expense_loading_pct": 0,
            "profit_margin_pct": 0,
            "discounted_rate_pct": 0,
        })
        assert status == 200, body
        assert body["ledger_recorded"] is True
        purchase = body["purchase"]
        assert purchase["product_name"] == "Home Bundle"
        assert purchase["category"] == "residential"
        assert purchase["provider"] == "PHINS Residential Care"
        assert purchase["amount"] == price
        assert purchase["bundle_code"] == "home"
        assert purchase["price_source"] == "residential_catalog"
        assert purchase["catalog_unit_price"] == price
        assert body["new_balance"] == round(20000.00 - price, 2)
        assert portal.HEALTH_WALLETS[customer_id]["balance"] == round(20000.00 - price, 2)

        plan = body["pricing_plan"]
        _plan_identity(plan, price)
        wallet_txns = [
            tx for tx in portal.HEALTH_WALLETS[customer_id]["transactions"]
            if tx.get("type") == "purchase"
        ]
        assert len(wallet_txns) == 1
        assert wallet_txns[0]["amount"] == -price
        assert wallet_txns[0]["product_name"] == "Home Bundle"
        assert wallet_txns[0]["ledger_tx_id"] == purchase["ledger_tx_id"]

        posted = _medical_rows(customer_id, ledger_before)
        assert [tx["id"] for tx in posted] == [purchase["ledger_tx_id"]]
        ledger_tx = posted[0]
        assert ledger_tx["amount"] == price
        assert ledger_tx["customer_id"] == customer_id
        assert ledger_tx["metadata"]["bundle_code"] == "home"
        assert ledger_tx["metadata"]["price_source"] == "residential_catalog"
        assert ledger_tx["metadata"]["catalog_unit_price"] == price
        assert ledger_tx["nft_token_id"] == purchase["nft_token_id"]
        token = portal.NFT_LEDGER[purchase["nft_token_id"]]
        assert affiliate_issues(token, ledger_tx) == []
        assert purchase["nft_token_id"] in (set(portal.NFT_LEDGER) - nft_before)

        two, two_body = _post("/api/health-wallet/purchase", {
            "customer_id": customer_id,
            "product_id": "res-extra",
            "amount": 10800,
            "quantity": 2,
            "payment_method": "health_wallet",
        })
        assert two == 400
        assert two_body["catalog_amount"] == 21600.00
        assert portal.HEALTH_WALLETS[customer_id]["balance"] == round(20000.00 - price, 2)
        assert len(_medical_rows(customer_id, ledger_before)) == 1
    finally:
        portal.HEALTH_WALLETS.pop(customer_id, None)


def test_two_periods_and_card_payment_keep_one_ledger_amount():
    customer_id = "CUST-RES-CARE-2"
    _prime_port()
    _fund(customer_id, 30000)
    ledger_before = set(portal.TRANSACTION_LEDGER)
    try:
        status, body = _post("/api/health-wallet/purchase", {
            "customer_id": customer_id,
            "product_id": "res-extra",
            "amount": 21600.00,
            "quantity": 2,
            "payment_method": "wallet",
        })
        assert status == 200, body
        assert body["purchase"]["amount"] == 21600.00
        assert body["purchase"]["quantity"] == 2
        assert body["purchase"]["bundle_code"] == "extra"
        assert body["new_balance"] == round(30000.00 - 21600.00, 2)
        assert len(_medical_rows(customer_id, ledger_before)) == 1
        _plan_identity(body["pricing_plan"], 21600.00)

        card, card_body = _post("/api/health-wallet/purchase", {
            "customer_id": customer_id,
            "product_id": "res-full",
            "amount": 14500,
            "quantity": 1,
            "payment_method": "credit_card",
        })
        assert card == 200, card_body
        assert card_body["purchase"]["amount"] == 14500.00
        assert card_body["purchase"]["external_payment_amount"] == 14500.00
        assert card_body["purchase"]["wallet_deduction"] == 0
        assert portal.HEALTH_WALLETS[customer_id]["balance"] == round(30000.00 - 21600.00, 2)
        purchases = [
            tx for tx in portal.HEALTH_WALLETS[customer_id]["transactions"]
            if tx.get("type") == "purchase"
        ]
        assert len(purchases) == 1
        assert len(_medical_rows(customer_id, ledger_before)) == 2
    finally:
        portal.HEALTH_WALLETS.pop(customer_id, None)


def test_offer_rows_the_marketplace_hides_keep_the_catalog_price():
    """A stale row cannot unlock the price of a card the wallet still shows."""
    customer_id = "CUST-RES-CARE-STALE"
    price = portal.residential_care_by_id("res-home")["price"]
    _prime_port()
    _fund(customer_id, 20000)
    hidden_rows = {
        "SUP-RES-INACTIVE-OFFER": ({"active": False}, {"status": "approved", "portal_active": True}),
        "SUP-RES-UNAPPROVED": ({"active": True}, {"status": "pending", "portal_active": True}),
        "SUP-RES-PORTAL-OFF": ({"active": True}, {"status": "approved", "portal_active": False}),
    }
    try:
        for supplier_id, (offer_flags, supplier_flags) in hidden_rows.items():
            with portal.STATE_LOCK:
                portal.SUPPLIERS[supplier_id] = {
                    "id": supplier_id,
                    "company_name": "Stale Residential Supplier",
                    "supplier_type": "healthcare_provider",
                    **supplier_flags,
                }
                portal.SUPPLIER_OFFERS["res-home"] = {
                    "id": "res-home",
                    "supplier_id": supplier_id,
                    "name": "Discount Home Bundle",
                    "price": 100.00,
                    "category": "residential",
                    "item_type": "service",
                    **offer_flags,
                }
            try:
                offer_price, offer_body = _post("/api/health-wallet/purchase", {
                    "customer_id": customer_id,
                    "product_id": "res-home",
                    "amount": 100.00,
                    "quantity": 1,
                    "payment_method": "health_wallet",
                })
                assert offer_price == 400, (supplier_id, offer_body)
                assert offer_body["error"] == "Catalog price mismatch"
                assert offer_body["catalog_amount"] == price
                assert portal.HEALTH_WALLETS[customer_id]["balance"] == 20000.00

                status, body = _post("/api/health-wallet/purchase", {
                    "customer_id": customer_id,
                    "product_id": "res-home",
                    "amount": price,
                    "quantity": 1,
                    "payment_method": "health_wallet",
                })
                assert status == 200, (supplier_id, body)
                assert body["purchase"]["amount"] == price
                assert body["purchase"]["product_name"] == "Home Bundle"
                assert body["purchase"]["price_source"] == "residential_catalog"
                assert body["purchase"].get("order_id") is None
                assert body["new_balance"] == round(20000.00 - price, 2)
                _plan_identity(body["pricing_plan"], price)
            finally:
                with portal.STATE_LOCK:
                    portal.SUPPLIER_OFFERS.pop("res-home", None)
                    portal.SUPPLIERS.pop(supplier_id, None)
                portal.HEALTH_WALLETS[customer_id]["balance"] = 20000.00
    finally:
        portal.HEALTH_WALLETS.pop(customer_id, None)


def test_other_catalog_purchases_still_use_the_wallet_pricing_plan():
    customer_id = "CUST-RES-CARE-OTHER"
    _prime_port()
    _fund(customer_id, 500)
    try:
        expected = portal.build_purchase_pricing_plan(25.0, {})
        status, body = _post("/api/health-wallet/purchase", {
            "customer_id": customer_id,
            "product_id": "PROD-LEGACY-25",
            "product_name": "Standard Wheelchair",
            "amount": 25,
            "category": "devices",
            "payment_method": "health_wallet",
        })
        assert status == 200, body
        assert body["purchase"]["amount"] == expected["final_customer_amount"]
        assert body["purchase"].get("price_source") is None
        assert "bundle_code" not in body["purchase"]
    finally:
        portal.HEALTH_WALLETS.pop(customer_id, None)
