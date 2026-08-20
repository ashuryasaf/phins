"""
End-to-end tests for the score → decision loop closure (phase 1).

Covers:
- underwriting approve/reject snapshots the shared risk score as a durable
  assessment record + on-application snapshot,
- claims approve/reject/pay snapshots the claims bot fraud score,
- the admin pipeline risk gate (no more blind auto-approval),
- claim file ingestion through the Assessment Center,
- the Assessment Center security scan on uploads,
- the /api/assessment-center/records API with role scoping.
"""

from __future__ import annotations

import base64
import os

import pytest
import requests

import web_portal.server as portal
from services.assessment_record_service import get_assessment_record_service

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")
TEST_PORT = int(os.environ.get("TEST_PORT", "8000"))


def _admin_headers():
    resp = requests.post(f"{BASE_URL}/api/login", json={
        "username": "admin", "password": "admin123",
    })
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _pin_test_state():
    """Prevent the per-port test wipe from clearing directly-seeded state."""
    init_set = getattr(portal, "_TEST_PORTS_INITIALIZED", None)
    if isinstance(init_set, set):
        init_set.add(TEST_PORT)


def _create_application(headers) -> tuple:
    resp = requests.post(f"{BASE_URL}/api/policies/create", json={
        "customer_name": "Loop Test Customer",
        "customer_email": "loop.test@example.com",
        "type": "life",
        "coverage_amount": 300000,
        "risk_score": "medium",
        "age": 35,
    }, headers=headers)
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    return body["customer"]["id"], body["policy"]["id"], body["underwriting"]["id"]


class TestUnderwritingDecisionLoop:
    def test_approve_snapshots_assessment_record(self):
        headers = _admin_headers()
        cust_id, pol_id, uw_id = _create_application(headers)

        resp = requests.post(f"{BASE_URL}/api/underwriting/approve",
                             json={"id": uw_id}, headers=headers)
        assert resp.status_code == 200, resp.text
        app = resp.json()["application"]

        snapshot = app.get("risk_assessment_snapshot")
        assert snapshot, "approval must attach a risk assessment snapshot"
        assert snapshot["decision"] == "approved"
        assert snapshot["record_id"].startswith("ASMT-")
        assert 0.0 <= snapshot["score"] <= 1.0

        record = get_assessment_record_service().get_record(snapshot["record_id"])
        assert record is not None
        assert record["subject_type"] == "underwriting_application"
        assert record["subject_id"] == uw_id
        assert record["assessment_type"] == "underwriting_risk"
        assert record["decision"] == "approved"
        assert record["payload_sha256"]
        assert get_assessment_record_service().verify_record(
            snapshot["record_id"]) is True

    def test_reject_snapshots_assessment_record(self):
        headers = _admin_headers()
        cust_id, pol_id, uw_id = _create_application(headers)

        resp = requests.post(f"{BASE_URL}/api/underwriting/reject",
                             json={"id": uw_id, "reason": "test"}, headers=headers)
        assert resp.status_code == 200, resp.text

        latest = get_assessment_record_service().latest_for_subject(
            "underwriting_application", uw_id)
        assert latest is not None
        assert latest["decision"] == "rejected"
        # A clean 35-year-old applicant scores auto-approvable, so a human
        # rejection is a (valuable) disagreement label.
        assert latest["decision_aligned"] is False

    def test_records_api_lists_decision(self):
        headers = _admin_headers()
        cust_id, pol_id, uw_id = _create_application(headers)
        requests.post(f"{BASE_URL}/api/underwriting/approve",
                      json={"id": uw_id}, headers=headers)

        resp = requests.get(
            f"{BASE_URL}/api/assessment-center/records",
            params={"subject_id": uw_id},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body.keys()) == {"items", "page", "page_size", "total"}
        assert body["total"] >= 1
        assert body["items"][0]["subject_id"] == uw_id

    def test_records_api_requires_auth_and_scopes_customers(self):
        # Unauthenticated → 401
        resp = requests.get(f"{BASE_URL}/api/assessment-center/records")
        assert resp.status_code == 401

        # Customer sessions may not read another customer's records.
        _pin_test_state()
        token = "phins_loop-test-customer-token"
        portal.SESSIONS[token] = {
            "username": "cust1", "role": "customer",
            "customer_id": "CUST-LOOP-OWN", "expires": "2099-01-01T00:00:00",
        }
        resp = requests.get(
            f"{BASE_URL}/api/assessment-center/records",
            params={"customer_id": "CUST-SOMEONE-ELSE"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403
        assert "error" in resp.json()

        # Own records are allowed (empty list is fine).
        resp = requests.get(
            f"{BASE_URL}/api/assessment-center/records",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["items"] == []


class TestPipelineRiskGate:
    def test_low_risk_application_still_auto_approves(self):
        _pin_test_state()
        cust_id, pol_id, app_id = "CUST-GATE-LOW", "POL-GATE-LOW", "UW-GATE-LOW"
        portal.CUSTOMERS[cust_id] = {"id": cust_id, "name": "Gate Low"}
        portal.POLICIES[pol_id] = {
            "id": pol_id, "customer_id": cust_id, "monthly_premium": 100.0,
            "status": "pending_underwriting",
        }
        portal.UNDERWRITING_APPLICATIONS[app_id] = {
            "id": app_id, "policy_id": pol_id, "customer_id": cust_id,
            "status": "pending",
        }

        result = portal.run_pipeline_for_customer(cust_id, auto_advance=True)
        assert result["success"] is True
        assert portal.UNDERWRITING_APPLICATIONS[app_id]["status"] == "approved"
        assert portal.POLICIES[pol_id]["status"] == "active"
        assert result["new_stage"] == "active"

        latest = get_assessment_record_service().latest_for_subject(
            "underwriting_application", app_id)
        assert latest is not None
        assert latest["decision"] == "auto_approved"
        assert latest["decision_aligned"] is True

    def test_high_risk_application_is_referred_not_approved(self):
        _pin_test_state()
        cust_id, pol_id, app_id = "CUST-GATE-HI", "POL-GATE-HI", "UW-GATE-HI"
        portal.CUSTOMERS[cust_id] = {"id": cust_id, "name": "Gate High"}
        portal.POLICIES[pol_id] = {
            "id": pol_id, "customer_id": cust_id, "monthly_premium": 100.0,
            "status": "pending_underwriting",
        }
        portal.UNDERWRITING_APPLICATIONS[app_id] = {
            "id": app_id, "policy_id": pol_id, "customer_id": cust_id,
            "status": "pending", "age": 72, "smoking_status": "current",
            "medical_conditions": [
                {"condition": "Heart Disease", "risk_impact": 0.30,
                 "loading_percentage": 30, "severity": "severe"},
            ],
        }

        result = portal.run_pipeline_for_customer(cust_id, auto_advance=True)
        assert result["success"] is True

        app = portal.UNDERWRITING_APPLICATIONS[app_id]
        assert app["status"] == "referred", (
            "blind auto-approval must be gated by the risk engine"
        )
        assert "Risk gate" in app["referral_reason"]
        # Policy must NOT have been activated.
        assert portal.POLICIES[pol_id]["status"] == "pending_underwriting"
        assert any("Referred application" in a for a in result["actions_taken"])

        latest = get_assessment_record_service().latest_for_subject(
            "underwriting_application", app_id)
        assert latest is not None
        assert latest["decision"] == "referred"


class TestClaimsDecisionLoop:
    def _create_claim(self, headers, with_file=False):
        cust_id, pol_id, uw_id = _create_application(headers)
        requests.post(f"{BASE_URL}/api/underwriting/approve",
                      json={"id": uw_id}, headers=headers)
        payload = {
            "policy_id": pol_id,
            "customer_id": cust_id,
            "type": "medical",
            "description": "Hospital visit for observation",
            "claimed_amount": 800.0,
        }
        if with_file:
            payload["files"] = [{
                "name": "discharge_note.txt",
                "type": "text/plain",
                "size": 64,
                "data": _b64(
                    "Discharge summary. Diagnosis: hypertension. "
                    "Medication: lisinopril."
                ),
            }]
        resp = requests.post(f"{BASE_URL}/api/claims/create",
                             json=payload, headers=headers)
        assert resp.status_code == 201, resp.text
        return resp.json()

    def test_approve_snapshots_fraud_assessment(self):
        headers = _admin_headers()
        claim = self._create_claim(headers)

        resp = requests.post(f"{BASE_URL}/api/claims/approve",
                             json={"id": claim["id"]}, headers=headers)
        assert resp.status_code == 200, resp.text
        approved = resp.json()["claim"]

        snapshot = approved.get("fraud_assessment_snapshot")
        assert snapshot, "claim approval must attach a fraud assessment snapshot"
        assert snapshot["decision"] == "approved"
        assert 0.0 <= snapshot["fraud_probability"] <= 1.0
        assert snapshot["risk_level"] in ("low", "medium", "high", "critical")

        record = get_assessment_record_service().get_record(snapshot["record_id"])
        assert record is not None
        assert record["assessment_type"] == "claims_fraud"
        assert record["subject_id"] == claim["id"]
        assert record["decision"] == "approved"

    def test_pay_attaches_decision_to_same_record(self):
        headers = _admin_headers()
        claim = self._create_claim(headers)
        requests.post(f"{BASE_URL}/api/claims/approve",
                      json={"id": claim["id"]}, headers=headers)
        record_id = portal.CLAIMS[claim["id"]]["fraud_assessment_snapshot"]["record_id"]

        resp = requests.post(f"{BASE_URL}/api/claims/pay",
                             json={"id": claim["id"]}, headers=headers)
        assert resp.status_code == 200, resp.text

        record = get_assessment_record_service().get_record(record_id)
        assert record["decision"] == "paid"

    def test_reject_snapshots_fraud_assessment(self):
        headers = _admin_headers()
        claim = self._create_claim(headers)

        resp = requests.post(
            f"{BASE_URL}/api/claims/reject",
            json={"id": claim["id"], "reason": "insufficient documentation"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

        latest = get_assessment_record_service().latest_for_subject(
            "claim", claim["id"])
        assert latest is not None
        assert latest["decision"] == "rejected"

    def test_claim_file_is_ingested_into_assessment_center(self):
        headers = _admin_headers()
        claim = self._create_claim(headers, with_file=True)

        file_ids = [f["id"] for f in claim.get("files", [])]
        assert file_ids
        stored = portal.CLAIM_FILES[file_ids[0]]
        assert stored.get("persistent_doc_id"), (
            "claim attachments must flow through the document pipeline"
        )
        assert stored.get("assessed_facts", 0) > 0

        # The mined medical fact must reach the customer's fact store.
        from services.assessment_center_service import get_assessment_center
        facts = get_assessment_center().get_facts(claim["customer_id"])
        assert any(f.get("fact_type") == "medical_condition" for f in facts)

    def test_dangerous_claim_file_is_flagged_not_ingested(self):
        headers = _admin_headers()
        cust_id, pol_id, uw_id = _create_application(headers)
        requests.post(f"{BASE_URL}/api/underwriting/approve",
                      json={"id": uw_id}, headers=headers)

        exe_payload = base64.b64encode(b"MZ\x90\x00evil-payload").decode("ascii")
        resp = requests.post(f"{BASE_URL}/api/claims/create", json={
            "policy_id": pol_id,
            "customer_id": cust_id,
            "type": "medical",
            "description": "claim with dangerous attachment",
            "claimed_amount": 100.0,
            "files": [{"name": "report.exe", "type": "application/octet-stream",
                       "size": 16, "data": exe_payload}],
        }, headers=headers)
        # Claim creation itself is preserved…
        assert resp.status_code == 201, resp.text
        claim = resp.json()
        file_id = claim["files"][0]["id"]
        stored = portal.CLAIM_FILES[file_id]
        # …but the dangerous file is flagged and never ingested.
        assert stored.get("security_flag")
        assert not stored.get("persistent_doc_id")


class TestAssessmentUploadScan:
    def test_executable_upload_is_rejected(self):
        headers = _admin_headers()
        exe_payload = base64.b64encode(b"MZ\x90\x00fake-windows-exe").decode("ascii")
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/upload",
            json={
                "file_name": "innocent.pdf",
                "file_data_b64": exe_payload,
                "mime_type": "application/pdf",
                "customer_id": "CUST-SCAN-1",
            },
            headers=headers,
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["error"] == "File rejected by security scan"
        assert "executable_header" in body["details"]

    def test_dangerous_extension_is_rejected(self):
        headers = _admin_headers()
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/upload",
            json={
                "file_name": "script.ps1",
                "file_data_b64": _b64("Write-Host 'hi'"),
                "customer_id": "CUST-SCAN-2",
            },
            headers=headers,
        )
        assert resp.status_code == 400
        assert "dangerous_extension" in resp.json()["details"]

    def test_scanner_import_error_rejects_upload(self, monkeypatch):
        import builtins
        import web_portal.api_assessment_center as ac

        real_import = builtins.__import__

        def _blocked(name, *args, **kwargs):
            if name == "security.file_scanner":
                raise ImportError("scanner missing")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _blocked)
        assert ac._security_scan_upload(
            _b64("hello"), "intake.txt", "text/plain", "127.0.0.1"
        ) == "security_scanner_unavailable"

    def test_scanner_exception_rejects_upload(self, monkeypatch):
        import web_portal.api_assessment_center as ac

        def _boom(*_a, **_k):
            raise RuntimeError("scanner crashed")

        monkeypatch.setattr("security.file_scanner.scan_base64_payload", _boom)
        assert ac._security_scan_upload(
            _b64("hello"), "intake.txt", "text/plain", "127.0.0.1"
        ) == "security_scan_failed"

        headers = _admin_headers()
        monkeypatch.setattr(ac, "_security_scan_upload", lambda *a, **k: "security_scan_failed")
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/upload",
            json={
                "file_name": "intake.txt",
                "file_data_b64": _b64("hello"),
                "mime_type": "text/plain",
                "customer_id": "CUST-SCAN-EXC",
            },
            headers=headers,
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "File rejected by security scan"

    def test_clean_upload_still_works(self):
        headers = _admin_headers()
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/upload",
            json={
                "file_name": "notes.txt",
                "file_data_b64": _b64("Customer notes. Diagnosis: diabetes."),
                "mime_type": "text/plain",
                "customer_id": "CUST-SCAN-3",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
