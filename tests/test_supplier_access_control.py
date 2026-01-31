"""
Supplier access control tests
=============================

Validates that supplier-scoped endpoints do not leak cross-supplier data.

This specifically guards against the common failure mode where suppliers are not
present in the `USERS` dict (staff users), so endpoint logic must use the session's
embedded role to scope correctly.
"""

import json
import threading
import time
from http.server import HTTPServer
from urllib.request import urlopen, Request
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
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers=headers)
    with urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.status


def _get(url: str, token: str | None = None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.status


def _reset_supplier_state():
    # Keep dict objects but clear contents (service keeps references).
    with portal.STATE_LOCK:
        portal.SUPPLIERS.clear()
        portal.SUPPLIER_OFFERS.clear()


def test_supplier_offer_isolation_list_upsert_delete():
    _reset_supplier_state()

    port = 8160
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.5)
    base = f"http://127.0.0.1:{port}"

    try:
        # Admin login via legacy password (enabled in PHINS_TEST_MODE).
        admin_login, status = _post(
            f"{base}/api/login",
            {"username": "admin", "password": "admin123"},
        )
        assert status == 200
        admin_token = admin_login["token"]

        # Register two suppliers
        s1_reg, status = _post(
            f"{base}/api/supplier/register",
            {
                "company_name": "Supplier One",
                "contact_email": "supplier1@example.com",
                "contact_name": "Supplier One Contact",
                "supplier_type": "delivery",
                "password": "SupOnePass123!",
            },
        )
        assert status == 200
        supplier1_id = s1_reg.get("supplier_id") or s1_reg.get("id")
        assert supplier1_id

        s2_reg, status = _post(
            f"{base}/api/supplier/register",
            {
                "company_name": "Supplier Two",
                "contact_email": "supplier2@example.com",
                "contact_name": "Supplier Two Contact",
                "supplier_type": "delivery",
                "password": "SupTwoPass123!",
            },
        )
        assert status == 200
        supplier2_id = s2_reg.get("supplier_id") or s2_reg.get("id")
        assert supplier2_id

        # Approve both suppliers
        _, status = _post(
            f"{base}/api/admin/suppliers/{supplier1_id}/approve",
            {"notes": "test approve"},
            token=admin_token,
        )
        assert status == 200
        _, status = _post(
            f"{base}/api/admin/suppliers/{supplier2_id}/approve",
            {"notes": "test approve"},
            token=admin_token,
        )
        assert status == 200

        # Supplier logins
        s1_login, status = _post(
            f"{base}/api/supplier/login",
            {"email": "supplier1@example.com", "password": "SupOnePass123!"},
        )
        assert status == 200
        s1_token = s1_login["token"]

        s2_login, status = _post(
            f"{base}/api/supplier/login",
            {"email": "supplier2@example.com", "password": "SupTwoPass123!"},
        )
        assert status == 200
        s2_token = s2_login["token"]

        # Create one offer each (supplier-scoped; supplier must not set supplier_id arbitrarily)
        r, status = _post(
            f"{base}/api/supplier/offers/upsert",
            {"category": "delivery", "name": "S1 Delivery", "price": 10.0},
            token=s1_token,
        )
        assert status in (200, 201)
        offer1_id = r["id"]

        r, status = _post(
            f"{base}/api/supplier/offers/upsert",
            {"category": "delivery", "name": "S2 Delivery", "price": 12.0},
            token=s2_token,
        )
        assert status in (200, 201)
        offer2_id = r["id"]

        # Supplier1 must see only their own offers
        s1_offers, status = _get(f"{base}/api/supplier/offers", token=s1_token)
        assert status == 200
        items1 = s1_offers.get("items", [])
        assert {o.get("id") for o in items1} == {offer1_id}
        assert all(o.get("supplier_id") == supplier1_id for o in items1)

        # Supplier2 must see only their own offers
        s2_offers, status = _get(f"{base}/api/supplier/offers", token=s2_token)
        assert status == 200
        items2 = s2_offers.get("items", [])
        assert {o.get("id") for o in items2} == {offer2_id}
        assert all(o.get("supplier_id") == supplier2_id for o in items2)

        # Supplier1 must NOT be able to delete supplier2's offer
        try:
            _post(
                f"{base}/api/supplier/offers/delete",
                {"id": offer2_id},
                token=s1_token,
            )
            assert False, "Expected HTTPError(403) when deleting other supplier's offer"
        except HTTPError as e:
            assert e.code == 403

    finally:
        srv.stop()

