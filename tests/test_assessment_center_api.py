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


class TestDashboardSurfaces:
    """The legacy upload path must surface the assessment summary so the user
    sees post-upload progress without leaving documents.html."""

    def test_documents_upload_returns_assessment_summary(self):
        headers = _admin_session()
        text = "Customer ID 123456782. Diagnosis: diabetes. Premium: 1,200 USD."
        resp = requests.post(
            f"{BASE_URL}/api/documents/upload",
            json={
                "files": [{"name": "intake.txt", "type": "text/plain", "data": _b64(text)}],
                "entity_type": "customer",
                "entity_id": "CUST-DASH-1",
                "customer_id": "CUST-DASH-1",
                "document_type": "id",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["uploaded"], body
        first = body["uploaded"][0]
        # The Assessment Center has run and the summary must be visible to UI.
        assert isinstance(first.get("assessment_summary"), dict)
        assert first["assessment_summary"].get("facts_extracted", 0) > 0

    def test_documents_list_includes_assessment_summary(self):
        headers = _admin_session()
        text = "Customer ID 123456782. BP: 145/92. BMI: 32."
        upload = requests.post(
            f"{BASE_URL}/api/documents/upload",
            json={
                "files": [{"name": "list.txt", "type": "text/plain", "data": _b64(text)}],
                "entity_type": "customer",
                "entity_id": "CUST-DASH-2",
                "customer_id": "CUST-DASH-2",
                "document_type": "medical",
            },
            headers=headers,
        )
        assert upload.status_code == 201, upload.text
        listing = requests.get(f"{BASE_URL}/api/documents/list", headers=headers)
        assert listing.status_code == 200
        docs = listing.json().get("documents", [])
        assert docs, listing.text
        with_summary = [d for d in docs if d.get("assessment_summary")
                        and d["assessment_summary"].get("facts_extracted", 0) > 0]
        assert with_summary, "expected at least one document with an assessment summary"

    def test_admin_customers_endpoint_lists_assessed_customers(self):
        headers = _admin_session()
        text = "ID 123456782. Diagnosis: cancer."
        requests.post(
            f"{BASE_URL}/api/assessment-center/upload",
            json={
                "file_name": "seed.txt",
                "file_data_b64": _b64(text),
                "mime_type": "text/plain",
                "customer_id": "CUST-DASH-LIST",
            },
            headers=headers,
        )
        resp = requests.get(f"{BASE_URL}/api/assessment-center/customers", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ids = [it["customer_id"] for it in body.get("items", [])]
        assert "CUST-DASH-LIST" in ids
        row = next(it for it in body["items"] if it["customer_id"] == "CUST-DASH-LIST")
        assert row["fact_count"] >= 1
        assert "risk_level" in row

    def test_backfill_status_and_run_via_api(self):
        headers = _admin_session()
        # Seed a legacy upload that stores in the doc service without running
        # the Assessment Center (skip_processing=True via the doc-service API).
        seed_text = "ID 123456782. Diagnosis: hypertension. Medication: lisinopril."
        upload = requests.post(
            f"{BASE_URL}/api/doc-service/upload",
            json={
                "files": [{"name": "legacy.txt", "type": "text/plain", "data": _b64(seed_text)}],
                "entity_type": "customer",
                "entity_id": "CUST-BACKFILL",
                "customer_id": "CUST-BACKFILL",
            },
            headers=headers,
        )
        assert upload.status_code == 201, upload.text

        status = requests.get(
            f"{BASE_URL}/api/assessment-center/backfill-status",
            headers=headers,
        )
        assert status.status_code == 200
        before = status.json()
        assert "total_documents" in before

        run = requests.post(
            f"{BASE_URL}/api/assessment-center/backfill",
            json={"force": True, "include_legacy": True},
            headers=headers,
        )
        assert run.status_code == 200, run.text
        body = run.json()
        result = body.get("result") or {}
        assert result.get("scanned", 0) >= 1
        assert "bridge" in body

        status_after = requests.get(
            f"{BASE_URL}/api/assessment-center/backfill-status",
            headers=headers,
        )
        assert status_after.status_code == 200
        after = status_after.json()
        # After a forced run, the with_facts count must not decrease.
        assert after.get("with_facts", 0) >= before.get("with_facts", 0)

    def test_backfill_requires_admin(self):
        # An unauthenticated POST is rejected with 401, not 200.
        resp = requests.post(f"{BASE_URL}/api/assessment-center/backfill", json={})
        assert resp.status_code == 401

    def test_describe_data_endpoint_returns_categories(self):
        headers = _admin_session()
        # Three different document types in one customer profile
        for name, doc_type, text in (
            ("id.txt", "id", "Customer Jane Doe. Israeli ID 123456782. Address: 1 Allenby St."),
            ("med.txt", "medical", "Diagnosis: diabetes. Medication: metformin. BMI: 32."),
            ("fin.txt", "financial", "Account balance: 25000. IBAN: GB82WEST12345698765432."),
        ):
            up = requests.post(
                f"{BASE_URL}/api/assessment-center/upload",
                json={"file_name": name, "file_data_b64": _b64(text),
                      "mime_type": "text/plain", "customer_id": "CUST-API-DESC",
                      "category": doc_type},
                headers=headers,
            )
            assert up.status_code == 201, up.text
        desc = requests.get(
            f"{BASE_URL}/api/assessment-center/customer/CUST-API-DESC/describe",
            headers=headers,
        )
        assert desc.status_code == 200, desc.text
        body = desc.json()
        cats = {s["category"] for s in body.get("sections", [])}
        assert "Identity" in cats
        assert "Medical" in cats

    def test_analysis_endpoint_runs_each_type(self):
        headers = _admin_session()
        requests.post(
            f"{BASE_URL}/api/assessment-center/upload",
            json={"file_name": "all.txt",
                  "file_data_b64": _b64("ID 123456782. Diagnosis: cancer. Premium: 1000. Balance: 5000."),
                  "mime_type": "text/plain", "customer_id": "CUST-API-DISP"},
            headers=headers,
        )
        for analysis_type in ("describe_data", "risk_assessment", "bi_summary", "customer_360"):
            res = requests.post(
                f"{BASE_URL}/api/assessment-center/analysis",
                json={"customer_id": "CUST-API-DISP", "analysis_type": analysis_type},
                headers=headers,
            )
            assert res.status_code == 200, f"{analysis_type}: {res.text}"
            payload = res.json()
            assert "download" in payload
            assert "headers" in payload["download"]

    def test_export_file_endpoint_returns_binary(self):
        headers = _admin_session()
        requests.post(
            f"{BASE_URL}/api/assessment-center/upload",
            json={"file_name": "exp.txt",
                  "file_data_b64": _b64("ID 123456782. Diagnosis: diabetes. Premium: 1500."),
                  "mime_type": "text/plain", "customer_id": "CUST-API-EXP"},
            headers=headers,
        )
        for fmt, expect_mime, expect_prefix in (
            ("csv", "text/csv", b"category"),
            ("xlsx", "spreadsheetml.sheet", b"PK"),
            ("pdf", "application/pdf", b"%PDF"),
        ):
            res = requests.post(
                f"{BASE_URL}/api/assessment-center/export-file",
                json={"customer_id": "CUST-API-EXP", "analysis_type": "describe_data", "format": fmt},
                headers=headers,
            )
            assert res.status_code == 200, f"{fmt}: {res.text}"
            assert expect_mime in res.headers.get("Content-Type", "")
            disp = res.headers.get("Content-Disposition", "")
            assert "attachment" in disp
            assert res.content[:max(2, len(expect_prefix))].startswith(expect_prefix[:2]) or expect_prefix in res.content[:200]

    def test_health_endpoint_is_public_and_fast(self):
        # The health probe must work without an auth token and report the
        # fact-store directory so operators can spot ephemeral configs in
        # Railway logs.
        resp = requests.get(f"{BASE_URL}/api/assessment-center/health")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body.get("ok") is True
        assert "fact_store_dir" in body
        assert "customers_in_memory" in body

    def test_export_error_returns_valid_json(self):
        # An unsupported format used to build the error JSON via string
        # concatenation; this asserts the response is now real JSON.
        headers = _admin_session()
        requests.post(
            f"{BASE_URL}/api/assessment-center/upload",
            json={"file_name": "exp.txt",
                  "file_data_b64": _b64("ID 123456782."),
                  "mime_type": "text/plain", "customer_id": "CUST-EXP-ERR"},
            headers=headers,
        )
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/export-file",
            json={"customer_id": "CUST-EXP-ERR",
                  "analysis_type": "describe_data", "format": "wat"},
            headers=headers,
        )
        assert resp.status_code == 400
        # Must parse as JSON and carry an "error" field.
        body = resp.json()
        assert "error" in body

    def test_assessment_center_page_is_served(self):
        # The dashboards rely on /assessment-center.html being reachable as a
        # static file. A regression where the file is missing would make every
        # nav link silently 404.
        resp = requests.get(f"{BASE_URL}/assessment-center.html")
        assert resp.status_code == 200
        body = resp.text
        # The unified workbench replaces the old "Assessment Center" page; the
        # page must still expose the new analysis endpoints regardless of the
        # title we pick.
        assert "Assessment Workbench" in body or "Assessment Center" in body
        assert "/api/assessment-center/analysis" in body
        assert "/api/assessment-center/export-file" in body
