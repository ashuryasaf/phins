"""
HTTP-level tests for the Assessment Center API extensions.

The pytest harness in :mod:`conftest` boots the embedded portal server on
``127.0.0.1:8000`` so these tests exercise the real dispatcher wiring.
"""

from __future__ import annotations

import base64
import os

import pytest
import requests

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


def _admin_session():
    resp = requests.post(f"{BASE_URL}/api/login", json={
        "username": "admin",
        "password": "admin123",
    })
    if resp.status_code != 200:
        pytest.skip("Admin login failed - test server may not have users seeded")
    token = resp.json().get("token")
    return {"Authorization": f"Bearer {token}"}


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


# ── Tests ────────────────────────────────────────────────────────────────────

class TestUploadEndpointRegistry:
    def test_returns_unauthenticated(self):
        # Registry requires auth to avoid leaking internal route structure.
        resp = requests.get(f"{BASE_URL}/api/assessment-center/upload-endpoints")
        assert resp.status_code == 401

    def test_registry_lists_assessment_center_route(self):
        headers = _admin_session()
        resp = requests.get(
            f"{BASE_URL}/api/assessment-center/upload-endpoints",
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "endpoints" in body
        paths = {e["path"] for e in body["endpoints"]}
        assert "/api/assessment-center/upload" in paths
        assert "/api/doc-service/upload" in paths
        assert "/api/mislaka/policies" in paths


class TestUploadAndAssess:
    def test_upload_extracts_facts_and_builds_360(self):
        headers = _admin_session()
        text = (
            "Customer: John Doe. ID 123456782. "
            "Diagnosis: diabetes. Medication: metformin. "
            "Premium: 1,250.00 USD. BMI: 32."
        )
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/upload",
            json={
                "file_name": "intake.txt",
                "file_data_b64": _b64(text),
                "mime_type": "text/plain",
                "customer_id": "CUST-API-1",
                "category": "general",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["customer_id"] == "CUST-API-1"
        assert body["summary"]["facts_extracted"] > 0
        types = body["summary"]["by_type"]
        assert "identity" in types
        assert "medical_condition" in types

        profile_resp = requests.get(
            f"{BASE_URL}/api/assessment-center/customer/CUST-API-1/profile",
            headers=headers,
        )
        assert profile_resp.status_code == 200
        profile = profile_resp.json()
        assert profile["customer_id"] == "CUST-API-1"
        assert any(entry["value"] == "123456782" for entry in profile["identity"]["id_numbers"])
        assert "diabetes" in profile["medical"]["conditions"]
        assert "metformin" in profile["medical"]["medications"]

    def test_risk_indicators_via_api(self):
        headers = _admin_session()
        text = "Diagnosis: stage 4 cancer. BMI: 36. Document classification: VERY HIGH RISK."
        requests.post(
            f"{BASE_URL}/api/assessment-center/upload",
            json={
                "file_name": "risk.txt",
                "file_data_b64": _b64(text),
                "mime_type": "text/plain",
                "customer_id": "CUST-API-RISK",
            },
            headers=headers,
        )
        resp = requests.get(
            f"{BASE_URL}/api/assessment-center/customer/CUST-API-RISK/risk-indicators",
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["risk_score"] > 0.5
        assert body["risk_level"] in ("high", "very_high")

    def test_charts_payload_shape(self):
        headers = _admin_session()
        text = "Diagnosis: diabetes. Sum insured: 100000. Pension balance: 25000."
        requests.post(
            f"{BASE_URL}/api/assessment-center/upload",
            json={
                "file_name": "charts.txt",
                "file_data_b64": _b64(text),
                "mime_type": "text/plain",
                "customer_id": "CUST-API-CHART",
            },
            headers=headers,
        )
        resp = requests.get(
            f"{BASE_URL}/api/assessment-center/customer/CUST-API-CHART/charts",
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "charts" in body
        for series in (
            "risk_breakdown",
            "condition_distribution",
            "external_sources",
            "savings_distribution",
            "coverage_distribution",
        ):
            assert series in body["charts"]


class TestExternalFactsApi:
    def test_external_facts_ingested_without_aggregation(self):
        headers = _admin_session()
        rows = [
            {"policy_id": "EX-1", "product_type": "pension", "accumulated_value": 25000.0},
            {"policy_id": "EX-2", "product_type": "life_insurance", "accumulated_value": 10000.0},
        ]
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/external-facts",
            json={
                "customer_id": "CUST-API-EXT",
                "source": "mislaka",
                "fact_type": "external_policy",
                "records": rows,
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["summary"]["facts_extracted"] == 2

        profile = requests.get(
            f"{BASE_URL}/api/assessment-center/customer/CUST-API-EXT/profile",
            headers=headers,
        ).json()
        # External facts are surfaced verbatim, never collapsed into a single
        # aggregate by the dashboard layer.
        assert "mislaka" in profile["external_sources"]
        assert len(profile["external_sources"]["mislaka"]) == 2


class TestExportImport:
    def test_round_trip_via_api(self):
        headers = _admin_session()
        text = "ID 123456782. Diagnosis: cancer. Premium: 500.0."
        upload = requests.post(
            f"{BASE_URL}/api/assessment-center/upload",
            json={
                "file_name": "pack.txt",
                "file_data_b64": _b64(text),
                "mime_type": "text/plain",
                "customer_id": "CUST-API-PACK",
            },
            headers=headers,
        )
        assert upload.status_code == 201

        export = requests.get(
            f"{BASE_URL}/api/assessment-center/customer/CUST-API-PACK/export",
            headers=headers,
        )
        assert export.status_code == 200
        pack = export.json()
        assert pack["sha256"]
        assert pack["facts"]

        import_resp = requests.post(
            f"{BASE_URL}/api/assessment-center/import",
            json={"pack": pack},
            headers=headers,
        )
        assert import_resp.status_code == 200
        report = import_resp.json()
        assert report["integrity_ok"] is True
        assert report["imported_facts"] >= 1


class TestAccessControl:
    def test_unauthenticated_upload_blocked(self):
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/upload",
            json={"file_name": "x.txt", "file_data_b64": _b64("x")},
        )
        assert resp.status_code == 401

    def test_missing_payload_returns_400(self):
        headers = _admin_session()
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/upload",
            json={},
            headers=headers,
        )
        assert resp.status_code == 400
