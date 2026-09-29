"""Durability of uploaded application and claim documents.

File bytes are labeled with the SHA-256 of the payload itself (a data-URL
prefix is not part of the file). The platform archive shows each role the
documents that role is responsible for, and the risk viewer lists every
application that should be on the book.
"""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timedelta

import requests

import web_portal.server as portal
from services.customer_document_vault_service import (
    CustomerDocumentVault,
    decode_document_bytes,
    fingerprint_upload,
)

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
RAW = b"PHINS durable evidence"
RAW_SHA = hashlib.sha256(RAW).hexdigest()
DATA_URL = "data:text/plain;base64," + base64.b64encode(RAW).decode("ascii")


def test_data_url_fingerprint_is_the_file_not_the_wrapper():
    assert decode_document_bytes(DATA_URL) == RAW
    assert fingerprint_upload(DATA_URL) == RAW_SHA
    # A pointer-only record keeps the digest that was sealed with the bytes.
    assert fingerprint_upload(None, f"sha256:{RAW_SHA}") == RAW_SHA
    naive = hashlib.sha256(base64.b64decode(DATA_URL, validate=False)).hexdigest()
    assert naive != RAW_SHA


def test_canonical_upload_strips_data_url_and_records_real_hash():
    sealed = portal.canonical_upload_bytes({
        "name": "evidence.txt",
        "data": DATA_URL,
        "size": 999,
    })
    assert sealed["has_bytes"] is True
    assert sealed["sha256"] == RAW_SHA
    assert base64.b64decode(sealed["data_b64"]) == RAW
    assert sealed["size"] == len(RAW)


def test_archive_scope_follows_role_hierarchy():
    medical = {
        "id": "DOC-MED",
        "name": "lab.pdf",
        "type": "application/pdf",
        "size": len(RAW),
        "data": base64.b64encode(RAW).decode("ascii"),
        "document_type": "medical",
        "uploaded_by_customer": "CUST-SCOPE",
        "entity_type": "customer",
        "entity_id": "CUST-SCOPE",
    }
    invoice = {
        "id": "DOC-BILL",
        "name": "premium-invoice.pdf",
        "type": "application/pdf",
        "size": 4,
        "data": base64.b64encode(b"bill").decode("ascii"),
        "document_type": "billing",
        "uploaded_by_customer": "CUST-SCOPE",
        "entity_type": "billing",
        "entity_id": "BILL-1",
    }
    vault = CustomerDocumentVault(policy_documents={"DOC-MED": medical, "DOC-BILL": invoice})

    admin = vault.get_platform_archive(viewer_role="admin")
    assert {d["id"] for d in admin["documents"]} >= {"DOC-MED", "DOC-BILL"}
    assert admin["archive_scope"] == ["*"]

    claims = vault.get_platform_archive(viewer_role="claims")
    claim_ids = {d["id"] for d in claims["documents"]}
    assert "DOC-MED" in claim_ids
    assert "DOC-BILL" not in claim_ids

    accountant = vault.get_platform_archive(viewer_role="accountant")
    accountant_ids = {d["id"] for d in accountant["documents"]}
    assert "DOC-BILL" in accountant_ids
    assert "DOC-MED" not in accountant_ids

    underwriting_file = {
        "id": "UW-FILE-1",
        "name": "passport-scan.png",
        "type": "image/png",
        "size": len(RAW),
        "data": DATA_URL,
        "sha256": "0" * 64,
        "application_id": "UW-1",
        "customer_id": "CUST-SCOPE",
    }
    labeled = CustomerDocumentVault(
        underwriting_files={"UW-FILE-1": underwriting_file},
        underwriting_applications={"UW-1": {"id": "UW-1", "customer_id": "CUST-SCOPE"}},
    ).get_platform_archive(viewer_role="underwriter")
    match = next(d for d in labeled["documents"] if d["id"] == "UW-FILE-1")
    assert match["sha256"] == RAW_SHA


def _admin_token() -> str:
    resp = requests.post(
        f"{BASE_URL}/api/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def _session(token: str, role: str, customer_id: str = "") -> None:
    portal.SESSIONS[token] = {
        "username": f"{role}-durability",
        "role": role,
        "customer_id": customer_id,
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }


def test_risk_catalog_lists_real_applications_without_invented_scores():
    token = _admin_token()
    portal.CUSTOMERS["CUST-DUR-1"] = {
        "id": "CUST-DUR-1",
        "name": "Dora Durable",
        "email": "dora@example.com",
    }
    portal.UNDERWRITING_APPLICATIONS["UW-DUR-1"] = {
        "id": "UW-DUR-1",
        "customer_id": "CUST-DUR-1",
        "policy_type": "life",
        "coverage_amount": 150000,
        "status": "pending",
        "created_date": "2026-03-01T00:00:00",
        "application_channel": "classic",
        "documents": [{
            "name": "id.txt",
            "type": "identity",
            "sha256": RAW_SHA,
            "source": "application",
        }],
    }
    portal.CUSTOMERS["CUST-TESTSIM-HIDE"] = {"id": "CUST-TESTSIM-HIDE", "name": "Sandbox"}
    portal.UNDERWRITING_APPLICATIONS["UW-TESTSIM-HIDE"] = {
        "id": "UW-TESTSIM-HIDE",
        "customer_id": "CUST-TESTSIM-HIDE",
        "status": "pending",
    }

    resp = requests.get(
        f"{BASE_URL}/api/risk-assessment/list",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    row = next(item for item in body["reports"] if item["application_id"] == "UW-DUR-1")
    assert row["customer_name"] == "Dora Durable"
    assert row["has_report"] is True
    assert row["channel"] == "classic"
    assert row["risk_score"] is None
    assert row["document_hashes"][0]["sha256"] == RAW_SHA
    assert all(item["application_id"] != "UW-TESTSIM-HIDE" for item in body["reports"])

    customer = "phins_test-durability-customer"
    _session(customer, "customer", "CUST-DUR-1")
    denied = requests.get(
        f"{BASE_URL}/api/risk-assessment/list",
        headers={"Authorization": f"Bearer {customer}"},
    )
    assert denied.status_code == 403


def test_policy_create_seals_data_url_bytes_with_real_hash():
    token = _admin_token()
    resp = requests.post(
        f"{BASE_URL}/api/policies/create",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "customer_name": "Hash Applicant",
            "customer_email": "hash.applicant@example.com",
            "type": "life",
            "coverage_amount": 100000,
            "age": 40,
            "files": [{
                "name": "evidence.txt",
                "type": "text/plain",
                "size": len(RAW),
                "data": DATA_URL,
                "kind": "document",
            }],
            "files_count": 1,
        },
    )
    assert resp.status_code in (200, 201), resp.text
    uw_id = resp.json()["underwriting"]["id"]
    stored = [
        item for item in portal.UNDERWRITING_FILES.values()
        if item.get("application_id") == uw_id
    ]
    assert len(stored) == 1, stored
    entry = stored[0]
    assert entry["sha256"] == RAW_SHA
    assert base64.b64decode(entry["data"]) == RAW
    assert entry.get("persistent_doc_id")
    app = portal.UNDERWRITING_APPLICATIONS[uw_id]
    assert app["documents"][0]["sha256"] == RAW_SHA

    report = requests.get(
        f"{BASE_URL}/api/risk-assessment/report",
        params={"application_id": uw_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert report.status_code == 200, report.text
    docs = report.json()["documents"]
    assert any(doc.get("sha256") == RAW_SHA for doc in docs)
