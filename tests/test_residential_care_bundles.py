"""Health-wallet residential care bundles.

The card price is the ledger amount. Expense loading, profit, and the
discounted rate decompose that total; they are not added on top. A client
cannot rename the bundle or pay a different figure.
"""

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
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


def test_live_approved_offer_still_charges_the_catalog_price():
    """An approved, portal-active offer on a catalog SKU cannot set the price."""
    customer_id = "CUST-RES-CARE-LIVE"
    price = portal.residential_care_by_id("res-home")["price"]
    supplier_id = "SUP-RES-LIVE"
    _prime_port()
    _fund(customer_id, 20000)
    try:
        with portal.STATE_LOCK:
            portal.SUPPLIERS[supplier_id] = {
                "id": supplier_id,
                "company_name": "Live Residential Supplier",
                "supplier_type": "healthcare_provider",
                "status": "approved",
                "portal_active": True,
            }
            portal.SUPPLIER_OFFERS["res-home"] = {
                "id": "res-home",
                "supplier_id": supplier_id,
                "name": "Cheap Home Bundle",
                "price": 100.00,
                "category": "residential",
                "item_type": "service",
                "active": True,
            }
        offer_price, offer_body = _post("/api/health-wallet/purchase", {
            "customer_id": customer_id,
            "product_id": "res-home",
            "amount": 100.00,
            "quantity": 1,
            "payment_method": "health_wallet",
        })
        assert offer_price == 400, offer_body
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
        assert status == 200, body
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
        portal.HEALTH_WALLETS.pop(customer_id, None)


def test_catalog_sku_cannot_be_published_as_a_supplier_offer():
    from services.supply_chain_ecosystem_service import (
        SupplyChainEcosystemService,
        SupplierStatus,
    )

    service = SupplyChainEcosystemService(suppliers_store={
        "SUP-1": {
            "id": "SUP-1",
            "status": SupplierStatus.APPROVED.value,
            "company_name": "Clinic",
        },
    })
    with pytest.raises(ValueError, match="reserved"):
        service.upsert_offer("SUP-1", {
            "id": "res-home",
            "name": "Home",
            "category": "residential",
            "item_type": "service",
            "price": 100,
        }, actor="t")
    assert "res-home" not in service.offers

    _prime_port()
    token = "phins_catalog-lock"
    portal.SESSIONS[token] = {
        "username": "admin-catalog-lock",
        "user_id": "admin-catalog-lock",
        "role": "admin",
        "customer_id": None,
        "expires": "2099-01-01T00:00:00",
    }
    base = os.environ["TEST_BASE_URL"].rstrip("/")
    data = json.dumps({
        "id": "res-extra",
        "supplier_id": "SUP-1",
        "name": "Extra",
        "category": "residential",
        "item_type": "service",
        "price": 50,
    }).encode("utf-8")
    req = Request(
        base + "/api/supplier/offers/upsert",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urlopen(req) as resp:
            status, body = resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        status, body = exc.code, json.loads(exc.read().decode("utf-8"))
    assert status == 400, body
    assert "reserved" in body["error"].lower()
    assert "res-extra" not in portal.SUPPLIER_OFFERS


def test_term_quotes_discount_the_list_without_stacking():
    home = portal.residential_care_by_id("res-home")
    extra = portal.residential_care_by_id("res-extra")
    full = portal.residential_care_by_id("res-full")
    one = portal.residential_care_quote(home, 1, None)
    assert one["ok"] is True
    assert one["catalog_amount"] == 8400.00
    assert one["term_discount_pct"] == 0.0
    assert one["list_amount"] == one["catalog_amount"] + one["term_discount_amount"]
    five = portal.residential_care_quote(home, 5, "monthly")
    assert five["catalog_amount"] == 42000.00
    assert five["automatic"] is False

    six = portal.residential_care_quote(home, 6, "months")
    assert six["automatic"] is True
    assert six["term_discount_pct"] == 0.20
    assert six["list_amount"] == 50400.00
    assert six["term_discount_amount"] == 10080.00
    assert six["catalog_amount"] == 40320.00
    assert six["terms_url"] == "/terms-of-use.html#residential-care"
    _plan_identity(portal.pricing_plan_for_catalog_total(six["catalog_amount"]), six["catalog_amount"])

    extra_nine = portal.residential_care_quote(extra, 9, "monthly")
    assert extra_nine["list_amount"] == 97200.00
    assert extra_nine["catalog_amount"] == 77760.00
    assert round(extra_nine["catalog_amount"] + extra_nine["term_discount_amount"], 2) == extra_nine["list_amount"]

    monthly_year = portal.residential_care_quote(full, 12, "monthly")
    annual = portal.residential_care_quote(full, 12, "annual accommodation")
    assert monthly_year["catalog_amount"] == 139200.00
    assert monthly_year["term_discount_pct"] == 0.20
    assert annual["ok"] is True
    assert annual["service_term"] == "annual"
    assert annual["list_amount"] == 174000.00
    assert annual["term_discount_amount"] == 52200.00
    assert annual["catalog_amount"] == 121800.00
    assert annual["catalog_amount"] != round(annual["list_amount"] * 0.8 * 0.7, 2)
    _plan_identity(
        portal.pricing_plan_for_catalog_total(annual["catalog_amount"]),
        annual["catalog_amount"],
        exact_rates=False,
    )

    for bundle in (home, extra, full):
        for months in range(1, portal.RESIDENTIAL_CARE_MAX_PERIODS + 1):
            quote = portal.residential_care_quote(bundle, months, "monthly")
            assert quote["ok"] is True
            assert round(quote["unit_price"] * quote["quantity"], 2) == quote["list_amount"]
            assert round(quote["catalog_amount"] + quote["term_discount_amount"], 2) == quote["list_amount"]
            if months >= 6:
                assert quote["term_discount_pct"] == 0.20
                assert quote["catalog_amount"] == round(quote["list_amount"] * 0.8, 2)
            else:
                assert quote["catalog_amount"] == quote["list_amount"]

    refused = portal.residential_care_quote(home, 12, "annual")
    assert refused["ok"] is False
    assert refused["error"] == "Annual accommodation applies only to the Full Accommodation Bundle"
    short_annual = portal.residential_care_quote(full, 6, "annual")
    assert short_annual["ok"] is False
    assert short_annual["expected_quantity"] == 12
    assert short_annual["catalog_amount"] == 121800.00
    unknown = portal.residential_care_quote(full, 1, "weekly")
    assert unknown["ok"] is False
    assert unknown["error"] == "Unknown residential service term"
    too_many = portal.residential_care_quote(full, 37, "monthly")
    assert too_many["error"] == "Quantity exceeds the residential care limit"

    monthly_offers = [item for item in full["term_offers"] if item["service_term"] == "monthly"]
    annual_offer = next(item for item in full["term_offers"] if item["service_term"] == "annual")
    assert [item["discount_pct"] for item in monthly_offers] == [0.0, 0.20]
    assert monthly_offers[1]["automatic"] is True
    assert annual_offer["catalog_amount"] == 121800.00
    assert full["demo_video_url"] == "/marketplace/residential-demo.mp4"
    assert home["term_offers"][-1]["sample_catalog_amount"] == 40320.00


def test_extended_and_annual_terms_post_the_discounted_catalog_amount():
    customer_id = "CUST-RES-CARE-TERM"
    _prime_port()
    _fund(customer_id, 50000)
    ledger_before = set(portal.TRANSACTION_LEDGER)
    purchases_before = set(portal.MEDICAL_PURCHASES)
    try:
        listed, listed_body = _post("/api/health-wallet/purchase", {
            "customer_id": customer_id,
            "product_id": "res-home",
            "amount": 50400.00,
            "quantity": 6,
            "payment_method": "health_wallet",
        })
        assert listed == 400
        assert listed_body["error"] == "Catalog price mismatch"
        assert listed_body["catalog_amount"] == 40320.00
        assert listed_body["list_amount"] == 50400.00
        assert listed_body["term_discount_pct"] == 0.20
        assert listed_body["terms_url"] == "/terms-of-use.html#residential-care"
        assert portal.HEALTH_WALLETS[customer_id]["balance"] == 50000.00
        assert _medical_rows(customer_id, ledger_before) == []
        assert set(portal.MEDICAL_PURCHASES) == purchases_before

        status, body = _post("/api/health-wallet/purchase", {
            "customer_id": customer_id,
            "product_id": "res-home",
            "amount": 40320.00,
            "quantity": 6,
            "service_term": "monthly",
            "payment_method": "health_wallet",
        })
        assert status == 200, body
        purchase = body["purchase"]
        assert purchase["amount"] == 40320.00
        assert purchase["quantity"] == 6
        assert purchase["service_term"] == "monthly"
        assert purchase["list_amount"] == 50400.00
        assert purchase["term_discount_pct"] == 0.20
        assert purchase["term_discount_amount"] == 10080.00
        assert purchase["catalog_amount"] == 40320.00
        assert body["new_balance"] == round(50000.00 - 40320.00, 2)
        assert body["pricing_plan"]["final_customer_amount"] == 40320.00
        _plan_identity(body["pricing_plan"], 40320.00)
        posted = _medical_rows(customer_id, ledger_before)
        assert len(posted) == 1
        assert posted[0]["amount"] == 40320.00
        assert posted[0]["metadata"]["term_discount_pct"] == 0.20
        assert posted[0]["metadata"]["list_amount"] == 50400.00
        assert posted[0]["metadata"]["catalog_amount"] == 40320.00
        token = portal.NFT_LEDGER[purchase["nft_token_id"]]
        assert affiliate_issues(token, posted[0]) == []

        monthly_rate, monthly_body = _post("/api/health-wallet/purchase", {
            "customer_id": customer_id,
            "product_id": "res-full",
            "amount": 121800.00,
            "quantity": 12,
            "service_term": "monthly",
            "payment_method": "health_wallet",
        })
        assert monthly_rate == 400
        assert monthly_body["catalog_amount"] == 139200.00
        assert portal.HEALTH_WALLETS[customer_id]["balance"] == round(50000.00 - 40320.00, 2)

        not_accommodation, not_body = _post("/api/health-wallet/purchase", {
            "customer_id": customer_id,
            "product_id": "res-extra",
            "amount": 77760.00,
            "quantity": 12,
            "service_term": "annual",
            "payment_method": "health_wallet",
        })
        assert not_accommodation == 400
        assert not_body["error"] == "Annual accommodation applies only to the Full Accommodation Bundle"
        assert "catalog_amount" not in not_body
        assert len(_medical_rows(customer_id, ledger_before)) == 1

        stacked, stacked_body = _post("/api/health-wallet/purchase", {
            "customer_id": customer_id,
            "product_id": "res-full",
            "amount": 139200.00,
            "quantity": 12,
            "service_term": "annual",
            "payment_method": "credit_card",
        })
        assert stacked == 400
        assert stacked_body["catalog_amount"] == 121800.00
        assert stacked_body["term_discount_pct"] == 0.30

        card, card_body = _post("/api/health-wallet/purchase", {
            "customer_id": customer_id,
            "product_id": "res-full",
            "amount": 121800.00,
            "quantity": 12,
            "service_term": "Annual Accommodation",
            "payment_method": "credit_card",
        })
        assert card == 200, card_body
        assert card_body["purchase"]["amount"] == 121800.00
        assert card_body["purchase"]["service_term"] == "annual"
        assert card_body["purchase"]["term_discount_pct"] == 0.30
        assert card_body["purchase"]["external_payment_amount"] == 121800.00
        assert card_body["purchase"]["wallet_deduction"] == 0
        assert card_body["purchase"]["terms_url"] == "/terms-of-use.html#residential-care"
        assert portal.HEALTH_WALLETS[customer_id]["balance"] == round(50000.00 - 40320.00, 2)
        assert len(_medical_rows(customer_id, ledger_before)) == 2
        wallet_purchases = [
            tx for tx in portal.HEALTH_WALLETS[customer_id]["transactions"]
            if tx.get("type") == "purchase"
        ]
        assert len(wallet_purchases) == 1
        assert wallet_purchases[0]["amount"] == -40320.00
    finally:
        portal.HEALTH_WALLETS.pop(customer_id, None)


def test_demo_video_and_terms_link_are_published_with_the_catalog():
    catalog, status = _get("/api/medical-products?category=residential")
    assert status == 200
    rows = {item["id"]: item for item in catalog["products"]}
    assert rows["res-full"]["term_offers"][-1]["label"] == "Annual accommodation"
    assert rows["res-full"]["term_offers"][-1]["catalog_amount"] == 121800.00
    assert rows["res-home"]["extended_discount_pct"] == 0.20
    assert rows["res-home"]["terms_url"] == "/terms-of-use.html#residential-care"
    assert all(item["demo_video_url"] == "/marketplace/residential-demo.mp4" for item in rows.values())

    base = os.environ["TEST_BASE_URL"].rstrip("/")
    with urlopen(base + "/marketplace/residential-demo.mp4") as resp:
        header = resp.read(12)
        assert resp.status == 200
        assert "video/mp4" in resp.headers.get("Content-Type", "")
    assert b"ftyp" in header

    dashboard = open(
        os.path.join(ROOT, "web_portal", "static", "dashboard.html"),
        encoding="utf-8",
    ).read()
    terms = open(
        os.path.join(ROOT, "web_portal", "static", "terms-of-use.html"),
        encoding="utf-8",
    ).read()
    hebrew = json.load(open(os.path.join(ROOT, "web_portal", "static", "locales", "he.json"), encoding="utf-8"))
    assert "openResidentialDemo" in dashboard
    assert "const product = isResidentialCatalog(indexed) ? indexed : null;" in dashboard
    assert "['res-home', 'res-extra', 'res-full'].every(id => isResidentialCatalog(marketplaceOfferIndex[id]))" in dashboard
    assert "Play service demo" in dashboard
    assert "/terms-of-use.html#residential-care" in dashboard
    assert 'id="residential-care"' in terms
    assert "20% reduction" in terms
    assert "30% off the twelve-month catalog list" in terms
    assert hebrew["strings"]["Terms of Service"]
    assert hebrew["strings"]["Play service demo"]
    assert hebrew["strings"]["Annual accommodation · 30% off"]

    legal, legal_status = _get("/api/legal/terms-of-use")
    assert legal_status == 200
    assert "Health Care Residential Solutions" in legal["sections"]


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
