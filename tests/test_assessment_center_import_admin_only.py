"""
Regression test for the admin gating on /api/assessment-center/import.

The Assessment Center import endpoint accepts a pre-built ``pack`` object
that injects arbitrary facts (identity numbers, medical conditions,
insurance, savings, ...) into the recipient customer's 360. Before this
fix any authenticated customer could import a pack scoped to their own
customer_id and inflate or fabricate the signals downstream BI / actuarial
/ risk endpoints consume. This test pins the new admin-only gate.
"""

from __future__ import annotations

import requests

import web_portal.server as portal


BASE_URL = "http://localhost:8000"


def _ensure_admin_user():
    if "admin" in portal.USERS:
        return
    pw = portal.hash_password("admin123")
    portal.USERS["admin"] = {**pw, "role": "admin", "name": "Admin User"}


def _mark_test_port_initialized(port: int = 8000) -> None:
    init_set = getattr(portal, "_TEST_PORTS_INITIALIZED", None)
    if isinstance(init_set, set):
        init_set.add(port)


def _admin_token() -> str:
    _ensure_admin_user()
    token = "phins_acimport-admin-token"
    portal.SESSIONS[token] = {
        "username": "admin",
        "role": "admin",
        "customer_id": None,
        "expires": "2099-01-01T00:00:00",
    }
    _mark_test_port_initialized()
    return token


def _customer_token() -> str:
    portal.USERS["customer-import@example.com"] = {
        **portal.hash_password("does-not-matter"),
        "role": "customer",
        "name": "Test Customer",
        "customer_id": "CUST-IMPORT-001",
    }
    token = "phins_acimport-customer-token"
    portal.SESSIONS[token] = {
        "username": "customer-import@example.com",
        "role": "customer",
        "customer_id": "CUST-IMPORT-001",
        "expires": "2099-01-01T00:00:00",
    }
    _mark_test_port_initialized()
    return token


def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _round_trip_pack() -> dict:
    """Build a real export pack via the admin path, return it for re-import."""
    admin = _hdr(_admin_token())
    upload = requests.post(
        f"{BASE_URL}/api/assessment-center/external-facts",
        json={
            "customer_id": "CUST-IMPORT-001",
            "source": "test",
            "fact_type": "external_policy",
            "records": [{"policy_id": "EX-1", "product_type": "pension"}],
        },
        headers=admin,
    )
    assert upload.status_code == 200, upload.text
    export = requests.get(
        f"{BASE_URL}/api/assessment-center/customer/CUST-IMPORT-001/export",
        headers=admin,
    )
    assert export.status_code == 200, export.text
    return export.json()


class TestImportEndpointIsAdminOnly:
    def test_customer_role_rejected(self):
        pack = _round_trip_pack()
        customer = _hdr(_customer_token())
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/import",
            json={"pack": pack},
            headers=customer,
        )
        assert resp.status_code == 403, resp.text
        body = resp.json()
        assert "admin" in (body.get("error") or "").lower()

    def test_unauthenticated_rejected(self):
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/import",
            json={"pack": {"customer_id": "CUST-X"}},
        )
        assert resp.status_code == 401

    def test_admin_can_still_import(self):
        pack = _round_trip_pack()
        admin = _hdr(_admin_token())
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/import",
            json={"pack": pack},
            headers=admin,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("integrity_ok") is True
