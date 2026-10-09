"""Health-wallet marketplace visuals and browse integrity.

Catalog illustrations are static files. Supplier photos stay on the offer
media pipeline. Wallet tabs that share a canonical category stay distinct,
and location filters use registered supplier fields only.
"""

import json
import os
from urllib.request import urlopen

import web_portal.server as portal


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARKETPLACE_DIR = os.path.join(ROOT, "web_portal", "static", "marketplace")

CATALOG_IMAGES = [
    "gp-consult.jpg",
    "specialist-consult.jpg",
    "telehealth.jpg",
    "physical-therapy.jpg",
    "mental-health.jpg",
    "wheelchair.jpg",
    "walking-cane.jpg",
    "bp-monitor.jpg",
    "glucose-kit.jpg",
    "hospital-bed.jpg",
    "shower-chair.jpg",
    "walker.jpg",
    "medical-alert.jpg",
    "incontinence-briefs.jpg",
    "bed-pads.jpg",
    "nitrile-gloves.jpg",
    "wound-care.jpg",
    "body-wash.jpg",
    "barrier-cream.jpg",
    "bathing-wipes.jpg",
    "prescription.jpg",
    "insulin-supplies.jpg",
    "first-aid.jpg",
    "face-masks.jpg",
    "sanitizer.jpg",
    "home-aide.jpg",
    "meal-delivery.jpg",
    "medical-transport.jpg",
    "home-safety.jpg",
    "housekeeping.jpg",
    "legal-consult.jpg",
    "ai-search.jpg",
    "residential-solutions.jpg",
    "residential-home.jpg",
    "residential-extra.jpg",
    "residential-full.jpg",
]


def test_catalog_illustrations_exist_and_are_wired():
    missing = [name for name in CATALOG_IMAGES if not os.path.isfile(os.path.join(MARKETPLACE_DIR, name))]
    assert missing == []

    dashboard = open(os.path.join(ROOT, "web_portal", "static", "dashboard.html"), encoding="utf-8").read()
    assert 'class="phins-wallet-actions"' in dashboard
    assert "renderMarketplaceCard" in dashboard
    assert "/marketplace/wheelchair.jpg" in dashboard
    assert "/marketplace/gp-consult.jpg" in dashboard
    assert "Demo catalog" in dashboard
    assert "min_radius_km" in dashboard
    for name in ("Book Consultation", "Medical Devices", "Daily Supplies", "Pharmacy", "Home Care", "Health Care Residential Solutions", "AI Search Offers"):
        assert name in dashboard
    assert "/marketplace/residential-solutions.jpg" in dashboard
    assert "res-home" in dashboard


def test_supplier_listing_accepts_media_before_save():
    portal_html = open(os.path.join(ROOT, "web_portal", "static", "supplier-portal.html"), encoding="utf-8").read()
    assert "pendingOfferMedia" in portal_html
    assert "postOfferMediaFile" in portal_html
    assert "Queued. This file uploads when you save the offer." in portal_html
    assert 'value="consultation"' in portal_html
    assert 'value="homecare"' in portal_html

    legacy = open(os.path.join(ROOT, "web_portal", "static", "supplier-dashboard.js"), encoding="utf-8").read()
    assert "/api/supplier/offers/media/upload" in legacy
    assert "media upload failed" in legacy


def test_wallet_browse_keeps_sibling_categories_distinct():
    assert portal.offer_matches_wallet_browse("homecare", "consultation") is False
    assert portal.offer_matches_wallet_browse("consultation", "consultation") is True
    assert portal.offer_matches_wallet_browse("medical_services", "consultation") is True
    assert portal.offer_matches_wallet_browse("supplies", "devices") is False
    assert portal.offer_matches_wallet_browse("devices", "devices") is True
    assert portal.offer_matches_wallet_browse("equipment", "devices") is True
    assert portal.offer_matches_wallet_browse("pharmacy", "medication") is True
    assert portal.infer_wallet_browse_bucket("home_care") == "homecare"
    assert portal.infer_wallet_browse_bucket("medical_services") == ""
    # Tab-specific values the alias table does not fold still land on their tab.
    assert portal.offer_matches_wallet_browse("telehealth", "consultation") is True
    assert portal.offer_matches_wallet_browse("telehealth", "homecare") is False
    assert portal.offer_matches_wallet_browse("home_care", "homecare") is True
    assert portal.offer_matches_wallet_browse("daily_supplies", "supplies") is True
    assert portal.offer_matches_wallet_browse("daily_supplies", "devices") is False
    assert portal.offer_matches_wallet_browse("residential", "homecare") is False
    assert portal.offer_matches_wallet_browse("residential", "residential") is True
    assert portal.offer_matches_wallet_browse("home_bundle", "residential") is True
    assert portal.offer_matches_wallet_browse("full_accommodation", "consultation") is False
    assert portal.normalize_marketplace_category("residential") == "residential"


def _get_json(path: str):
    base = os.environ["TEST_BASE_URL"].rstrip("/")
    with urlopen(base + path) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.status


def test_offerings_keep_wallet_tabs_prices_and_registered_location():
    supplier_id = "SUP-VISUAL-TEST"
    consultation_id = "OFF-VISUAL-CONSULT"
    homecare_id = "OFF-VISUAL-HOME"
    with portal.STATE_LOCK:
        previous_supplier = portal.SUPPLIERS.get(supplier_id)
        previous_consult = portal.SUPPLIER_OFFERS.get(consultation_id)
        previous_home = portal.SUPPLIER_OFFERS.get(homecare_id)
        portal.SUPPLIERS[supplier_id] = {
            "id": supplier_id,
            "company_name": "Visual Clinic",
            "status": "approved",
            "portal_active": True,
            "supplier_type": "clinic",
            "city": "Tel Aviv",
            "country": "Israel",
            "service_radius_km": 15,
            "average_rating": 4.5,
            "total_reviews": 2,
        }
        portal.SUPPLIER_OFFERS[consultation_id] = {
            "id": consultation_id,
            "supplier_id": supplier_id,
            "name": "Visual GP Visit",
            "category": "consultation",
            "item_type": "service",
            "price": 80.0,
            "currency": "USD",
            "active": True,
            "wallet_compatible": ["health"],
            "media": [{
                "id": "MED-VISUAL",
                "type": "image",
                "url": f"/media-files/supplier-offers/{consultation_id}/photo.jpg",
                "sha256": "abc",
            }],
        }
        portal.SUPPLIER_OFFERS[homecare_id] = {
            "id": homecare_id,
            "supplier_id": supplier_id,
            "name": "Visual Home Aide",
            "category": "homecare",
            "item_type": "service",
            "price": 120.0,
            "currency": "USD",
            "active": True,
            "wallet_compatible": ["health"],
            "media": [],
        }
    try:
        consultation, status = _get_json(
            "/api/marketplace/offerings?category=consultation&supplier_type=healthcare_provider&type=service&wallet=health"
        )
        assert status == 200
        ids = {item["id"] for item in consultation["items"]}
        assert consultation_id in ids
        assert homecare_id not in ids
        row = next(item for item in consultation["items"] if item["id"] == consultation_id)
        assert row["price"] == 80.0
        assert row["browse_bucket"] == "consultation"
        assert row["supplier_city"] == "Tel Aviv"
        assert row["supplier_type"] == "clinic"
        assert row["media"][0]["sha256"] == "abc"
        assert "latitude" not in row

        home, _ = _get_json(
            "/api/marketplace/offerings?category=homecare&supplier_type=healthcare_provider&type=service&wallet=health"
        )
        home_ids = {item["id"] for item in home["items"]}
        assert homecare_id in home_ids
        assert consultation_id not in home_ids

        by_city, _ = _get_json("/api/marketplace/offerings?wallet=health&city=tel%20aviv")
        assert consultation_id in {item["id"] for item in by_city["items"]}
        other_city, _ = _get_json("/api/marketplace/offerings?wallet=health&city=haifa")
        assert consultation_id not in {item["id"] for item in other_city["items"]}

        too_wide, _ = _get_json("/api/marketplace/offerings?wallet=health&min_radius_km=40")
        assert consultation_id not in {item["id"] for item in too_wide["items"]}
        covered, _ = _get_json("/api/marketplace/offerings?wallet=health&min_radius_km=10")
        assert consultation_id in {item["id"] for item in covered["items"]}

        catalog, status = _get_json("/api/medical-products?category=devices")
        assert status == 200
        wheelchair = next(item for item in catalog["products"] if item["id"] == "dev-1")
        assert wheelchair["price"] == 450
        assert wheelchair["image_url"] == "/marketplace/wheelchair.jpg"
    finally:
        with portal.STATE_LOCK:
            if previous_supplier is None:
                portal.SUPPLIERS.pop(supplier_id, None)
            else:
                portal.SUPPLIERS[supplier_id] = previous_supplier
            if previous_consult is None:
                portal.SUPPLIER_OFFERS.pop(consultation_id, None)
            else:
                portal.SUPPLIER_OFFERS[consultation_id] = previous_consult
            if previous_home is None:
                portal.SUPPLIER_OFFERS.pop(homecare_id, None)
            else:
                portal.SUPPLIER_OFFERS[homecare_id] = previous_home


def test_supplier_type_groups_cover_ecosystem_types_without_collapsing_exact_matches():
    assert portal.supplier_type_matches("clinic", "healthcare_provider") is True
    assert portal.supplier_type_matches("hospital", "healthcare_provider") is True
    assert portal.supplier_type_matches("equipment", "equipment_supplier") is True
    assert portal.supplier_type_matches("pharmacy", "pharmacy") is True
    assert portal.supplier_type_matches("pharmacy", "legal_service") is False
    assert portal.supplier_type_matches("clinic", "clinic") is True
    assert portal.supplier_type_matches("doctor", "clinic") is False
