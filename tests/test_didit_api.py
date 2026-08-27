"""HTTP-level tests for Didit standalone identity routes."""

from __future__ import annotations

import base64
import os

import pytest
import requests

from services.didit_service import DiditResult, DiditService, set_didit_service_for_tests

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")
MIN_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
)


def _admin_session():
    resp = requests.post(f"{BASE_URL}/api/login", json={
        "username": "admin",
        "password": "admin123",
    })
    if resp.status_code != 200:
        pytest.skip("Admin login failed - test server may not have users seeded")
    token = resp.json().get("token")
    return {"Authorization": f"Bearer {token}"}


def _b64(data: bytes = MIN_JPEG) -> str:
    return base64.b64encode(data).decode("ascii")


class _FakeDidit(DiditService):
    def __init__(self, result: DiditResult):
        super().__init__(api_key="test-key", enabled=True)
        self._result = result
        self.calls = []

    def id_verification(self, **kwargs):
        self.calls.append(("id-verification", kwargs))
        return self._result

    def aml(self, **kwargs):
        self.calls.append(("aml", kwargs))
        return self._result


def test_status_requires_authentication():
    resp = requests.get(f"{BASE_URL}/api/didit/status")
    assert resp.status_code == 401
    assert resp.json()["error"] == "Authentication required"


def test_status_lists_standalone_endpoints():
    headers = _admin_session()
    resp = requests.get(f"{BASE_URL}/api/didit/status", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert "id-verification" in body["endpoints"]
    assert "aml" in body["endpoints"]
    assert "kyb/search" in body["endpoints"]
    assert "base_url" in body


def test_id_verification_requires_front_image():
    headers = _admin_session()
    resp = requests.post(
        f"{BASE_URL}/api/didit/id-verification",
        json={"vendor_data": "CUST-1"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "front_image" in resp.json()["error"]


def test_id_verification_success_path_uses_service(monkeypatch):
    fake = _FakeDidit(DiditResult(
        ok=True,
        status_code=200,
        request_id="sess-1",
        payload={
            "request_id": "sess-1",
            "id_verification": {
                "status": "Approved",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "document_number": "AB123",
                "warnings": [],
            },
        },
        error=None,
        endpoint="id-verification",
        approved=True,
    ))
    set_didit_service_for_tests(fake)
    try:
        headers = _admin_session()
        resp = requests.post(
            f"{BASE_URL}/api/didit/id-verification",
            json={
                "front_image": _b64(),
                "vendor_data": "CUST-99",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["ok"] is True
        assert body["approved"] is True
        assert body["request_id"] == "sess-1"
        assert body["id_verification"]["document_number"] == "AB123"
        assert fake.calls[0][0] == "id-verification"
        assert fake.calls[0][1]["vendor_data"] == "CUST-99"
    finally:
        set_didit_service_for_tests(None)


def test_aml_missing_name_and_service_error():
    headers = _admin_session()
    missing = requests.post(
        f"{BASE_URL}/api/didit/aml",
        json={"nationality": "US"},
        headers=headers,
    )
    assert missing.status_code == 400
    assert "full_name" in missing.json()["error"]

    fake = _FakeDidit(DiditResult(
        ok=False,
        status_code=502,
        request_id=None,
        payload={"detail": "You do not have permission to perform this action."},
        error="You do not have permission to perform this action.",
        endpoint="aml",
    ))
    set_didit_service_for_tests(fake)
    try:
        resp = requests.post(
            f"{BASE_URL}/api/didit/aml",
            json={"full_name": "Jane Doe", "entity_type": "person"},
            headers=headers,
        )
        assert resp.status_code == 502
        assert "error" in resp.json()
    finally:
        set_didit_service_for_tests(None)


def test_health_includes_didit_flag():
    resp = requests.get(f"{BASE_URL}/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "didit" in body
    assert "configured" in body["didit"]
    assert "enabled" in body["didit"]
