"""
Security regression tests for the Assessment Center document-ownership checks.

These tests pin the fix that prevents one customer from running the Assessment
Center extraction pipeline on another customer's document via:

    POST /api/assessment-center/scan      (document_id from request body)
    POST /api/assessment-center/analysis  (document_ids in request body)
    POST /api/assessment-center/export-file (document_ids in request body)
    GET  /api/assessment-center/customer/<id>/describe?document_ids=...

Before the fix, ``assess_document`` would happily extract identity numbers,
medical conditions, and other PII from any document the caller named, and
return those facts in the response. After the fix, non-admin callers must own
the document; admins still bypass.
"""

from __future__ import annotations

import base64

import requests

import web_portal.server as portal
from web_portal import api_assessment_center as ac_api


BASE_URL = "http://localhost:8000"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _ensure_admin_user():
    if "admin" in portal.USERS:
        return
    pw = portal.hash_password("admin123")
    portal.USERS["admin"] = {**pw, "role": "admin", "name": "Admin User"}


def _mark_test_port_initialized(port: int = 8000) -> None:
    """Stop the dispatcher's per-port state wipe from clearing our seeded sessions.

    The conftest's ``pytest_runtest_setup`` hook clears
    ``_TEST_PORTS_INITIALIZED`` at the start of every test, so the next HTTP
    request on port 8000 calls ``_ensure_test_port_state`` which clears
    ``SESSIONS``. We add the port back to the set after seeding so the test's
    first request keeps the seeded session intact.
    """
    init_set = getattr(portal, "_TEST_PORTS_INITIALIZED", None)
    if isinstance(init_set, set):
        init_set.add(port)


def _admin_session_token() -> str:
    """Mint a deterministic admin session that the dispatcher will accept."""
    _ensure_admin_user()
    token = "phins_acscan-admin-token"
    portal.SESSIONS[token] = {
        "username": "admin",
        "role": "admin",
        "customer_id": None,
        "expires": "2099-01-01T00:00:00",
    }
    _mark_test_port_initialized()
    return token


def _customer_session_token(customer_id: str, username: str) -> str:
    """Mint a deterministic customer-role session bound to ``customer_id``."""
    portal.USERS[username] = {
        **portal.hash_password("does-not-matter"),
        "role": "customer",
        "name": "Test Customer",
        "customer_id": customer_id,
    }
    token = f"phins_acscan-{customer_id}-token"
    portal.SESSIONS[token] = {
        "username": username,
        "role": "customer",
        "customer_id": customer_id,
        "expires": "2099-01-01T00:00:00",
    }
    _mark_test_port_initialized()
    return token


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _seed_victim_document(victim_customer_id: str, *, sensitive_text: str) -> str:
    """Upload a document attributed to ``victim_customer_id`` and return its id.

    The upload uses the admin session because the test only cares that the
    document is correctly owned by the victim - not whether it was the victim
    that uploaded it.
    """
    admin = _headers(_admin_session_token())
    resp = requests.post(
        f"{BASE_URL}/api/assessment-center/upload",
        json={
            "file_name": "victim_intake.txt",
            "file_data_b64": _b64(sensitive_text),
            "mime_type": "text/plain",
            "customer_id": victim_customer_id,
            "category": "general",
        },
        headers=admin,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # The upload pipeline echoes back at least one fact whose source_document_id
    # is the freshly-stored document.
    facts = body.get("facts") or []
    doc_ids = {f.get("source_document_id") for f in facts if f.get("source_document_id")}
    assert doc_ids, f"upload did not produce any document-bound facts: {body}"
    return next(iter(doc_ids))


# ── Tests ────────────────────────────────────────────────────────────────────


class TestScanDocumentOwnership:
    """``/api/assessment-center/scan`` must reject foreign document_ids."""

    def test_customer_cannot_scan_another_customers_document(self):
        sensitive = (
            "Patient: Jane Victim. ID 123456782. "
            "Diagnosis: diabetes. Medication: metformin. BMI: 32."
        )
        victim_doc_id = _seed_victim_document(
            "CUST-VICTIM-001", sensitive_text=sensitive,
        )

        attacker = _headers(_customer_session_token(
            "CUST-ATTACKER-001", "attacker@example.com",
        ))
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/scan",
            json={
                "document_id": victim_doc_id,
                "customer_id": "CUST-ATTACKER-001",
            },
            headers=attacker,
        )

        # The endpoint must NOT return the extracted facts. Any 4xx is fine
        # but the response body must not leak the victim's PII fields.
        assert resp.status_code in (403, 404), resp.text
        body = resp.json()
        assert "facts" not in body, body
        for marker in ("123456782", "metformin", "diabetes", "Jane Victim"):
            assert marker not in resp.text, (
                f"Sensitive marker {marker!r} leaked in scan response: {resp.text}"
            )

    def test_unknown_document_id_is_rejected(self):
        attacker = _headers(_customer_session_token(
            "CUST-ATTACKER-002", "attacker2@example.com",
        ))
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/scan",
            json={
                "document_id": "DOC-DOES-NOT-EXIST-XYZ",
                "customer_id": "CUST-ATTACKER-002",
            },
            headers=attacker,
        )
        # Either 403 (not accessible) or 404 (not found) - both mean "no
        # extracted facts in the body".
        assert resp.status_code in (403, 404), resp.text
        body = resp.json()
        assert "facts" not in body

    def test_owner_can_still_scan_own_document(self):
        owner_id = "CUST-OWNER-001"
        owner = _headers(_customer_session_token(owner_id, "owner@example.com"))
        # Owner uploads their own document, then re-scans it.
        upload = requests.post(
            f"{BASE_URL}/api/assessment-center/upload",
            json={
                "file_name": "self.txt",
                "file_data_b64": _b64("Customer ID 123456782. Diagnosis: diabetes."),
                "mime_type": "text/plain",
                "customer_id": owner_id,
                "category": "general",
            },
            headers=owner,
        )
        assert upload.status_code == 201, upload.text
        upload_body = upload.json()
        doc_id = next(
            (f.get("source_document_id") for f in upload_body.get("facts") or []
             if f.get("source_document_id")),
            None,
        )
        assert doc_id, upload_body

        scan = requests.post(
            f"{BASE_URL}/api/assessment-center/scan",
            json={"document_id": doc_id, "customer_id": owner_id},
            headers=owner,
        )
        assert scan.status_code == 200, scan.text
        assert scan.json().get("customer_id") == owner_id

    def test_admin_can_still_scan_any_document(self):
        sensitive = "ID 987654321. Diagnosis: hypertension."
        victim_doc_id = _seed_victim_document(
            "CUST-VICTIM-002", sensitive_text=sensitive,
        )
        admin = _headers(_admin_session_token())
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/scan",
            json={
                "document_id": victim_doc_id,
                "customer_id": "CUST-VICTIM-002",
            },
            headers=admin,
        )
        assert resp.status_code == 200, resp.text


class TestAnalysisDocumentOwnership:
    """``/api/assessment-center/analysis`` must reject foreign document_ids."""

    def test_customer_cannot_supply_foreign_document_ids(self):
        victim_doc_id = _seed_victim_document(
            "CUST-VICTIM-003", sensitive_text="ID 123456782. Diagnosis: cancer.",
        )
        attacker = _headers(_customer_session_token(
            "CUST-ATTACKER-003", "attacker3@example.com",
        ))
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/analysis",
            json={
                "customer_id": "CUST-ATTACKER-003",
                "analysis_type": "describe_data",
                "document_ids": [victim_doc_id],
            },
            headers=attacker,
        )
        assert resp.status_code in (403, 404), resp.text


class TestExportFileDocumentOwnership:
    """``/api/assessment-center/export-file`` must reject foreign document_ids."""

    def test_customer_cannot_export_foreign_document_ids(self):
        victim_doc_id = _seed_victim_document(
            "CUST-VICTIM-004", sensitive_text="ID 123456782. Diagnosis: cancer.",
        )
        attacker = _headers(_customer_session_token(
            "CUST-ATTACKER-004", "attacker4@example.com",
        ))
        resp = requests.post(
            f"{BASE_URL}/api/assessment-center/export-file",
            json={
                "customer_id": "CUST-ATTACKER-004",
                "analysis_type": "describe_data",
                "format": "csv",
                "document_ids": [victim_doc_id],
            },
            headers=attacker,
        )
        assert resp.status_code in (403, 404), resp.text


class TestDescribeGetDocumentOwnership:
    """``GET .../describe?document_ids=...`` must reject foreign document_ids."""

    def test_customer_cannot_describe_foreign_document_ids(self):
        victim_doc_id = _seed_victim_document(
            "CUST-VICTIM-005", sensitive_text="ID 123456782. Diagnosis: asthma.",
        )
        attacker_id = "CUST-ATTACKER-005"
        attacker = _headers(_customer_session_token(
            attacker_id, "attacker5@example.com",
        ))
        resp = requests.get(
            f"{BASE_URL}/api/assessment-center/customer/{attacker_id}/describe",
            params={"document_ids": victim_doc_id},
            headers=attacker,
        )
        assert resp.status_code in (403, 404), resp.text


# ── Helper-level test (pure function, no HTTP) ──────────────────────────────


class TestEnsureDocumentsOwnedByHelper:
    """Direct unit test of the ownership helper to lock its behavior."""

    def test_admin_role_bypasses_ownership_check(self):
        # The helper must be a no-op for admin roles regardless of input.
        ok, err = ac_api._ensure_documents_owned_by(
            ac_api._service(),
            customer_id="CUST-DOES-NOT-MATTER",
            document_ids=["any-id"],
            role="admin",
        )
        # Admins bypass even if the doc id is gibberish.
        assert ok is True
        assert err is None

    def test_empty_document_ids_is_ok(self):
        ok, err = ac_api._ensure_documents_owned_by(
            ac_api._service(),
            customer_id="CUST-X",
            document_ids=None,
            role="customer",
        )
        assert ok is True and err is None

        ok, err = ac_api._ensure_documents_owned_by(
            ac_api._service(),
            customer_id="CUST-X",
            document_ids=[],
            role="customer",
        )
        assert ok is True and err is None
