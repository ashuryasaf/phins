"""Admin durability agent: archive census plus an isolated pipeline probe.

The probe is a reserved text file. It is deleted before the test returns,
and a sibling document's bytes stay as they were.
"""

from __future__ import annotations

import base64
import hashlib
import os

import requests

from services.customer_document_vault_service import CustomerDocumentVault
from services.document_durability_agent import (
    LAUNCH_DATE,
    PROBE_SHA256,
    PROBE_TEXT,
    build_census,
    media_kind,
    process_bucket,
    reap_own_probes,
    run_durability_test,
    run_pipeline_probe,
)
from services.document_processing_service import DocumentProcessingService

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")


def _record(**overrides):
    row = {
        "id": "DOC-1",
        "name": "note.txt",
        "type": "text/plain",
        "size": 4,
        "sha256": "abc",
        "entity_type": "claim",
        "process_hashtag": "claim",
        "uploaded_at": "2026-01-15T00:00:00",
        "has_data": True,
        "integrity_status": "ok",
    }
    row.update(overrides)
    return row


def test_media_and_process_buckets():
    assert media_kind(_record(name="call.wav", type="audio/wav")) == "voice"
    assert media_kind(_record(name="scene.mp4", type="video/mp4")) == "video"
    assert media_kind(_record(name="id.png", type="image/png")) == "image"
    assert media_kind(_record()) == "document"
    assert process_bucket(_record(entity_type="claims_chat")) == "claims_chat"
    assert process_bucket(_record(entity_type="chat_application")) == "apply_chat"
    assert process_bucket(_record(entity_type="policy")) == "policy_documents"
    assert process_bucket(_record(entity_type="claim")) == "claims"
    assert process_bucket(_record(entity_type="", process_hashtag="claim")) == "claims"


def test_census_splits_launch_window_and_stored_bytes():
    records = [
        _record(id="C1", name="claim.pdf", type="application/pdf"),
        _record(id="C2", name="statement.wav", type="audio/wav", integrity_status="missing", has_data=False),
        _record(id="C3", name="walkthrough.mp4", type="video/mp4", integrity_status="ok"),
        _record(
            id="OLD",
            name="legacy.txt",
            uploaded_at="2025-11-01T00:00:00",
            entity_type="policy",
            process_hashtag="general",
        ),
        _record(id="BARE", name="nodate.txt", uploaded_at="", has_data=True, integrity_status="unverified"),
        _record(
            id="PROBE",
            name="phins-durability-probe.txt",
            entity_type="durability_probe",
            document_type="durability_probe",
        ),
    ]
    from services.document_durability_agent import _split_launch

    since, undated, before = _split_launch(records)
    assert [row["id"] for row in since] == ["C1", "C2", "C3", "PROBE"]
    assert [row["id"] for row in undated] == ["BARE"]
    assert [row["id"] for row in before] == ["OLD"]
    assert LAUNCH_DATE == "2025-12-01"

    book = build_census(since)
    claims = next(row for row in book["rows"] if row["process"] == "claims")
    assert claims["uploaded"] == 3
    assert claims["by_media"] == {"document": 1, "voice": 1, "video": 1, "image": 0}
    assert claims["stored"] == 2
    assert claims["stored_by_media"]["voice"] == 0
    assert claims["stored_by_media"]["document"] == 1
    assert claims["stored_by_media"]["video"] == 1
    assert book["archive_consistent"] is False
    assert book["issues"][0]["id"] == "C2"
    assert build_census([records[-1]])["totals"]["uploaded"] == 0


def test_probe_round_trip_does_not_touch_sibling_bytes(tmp_path):
    svc = DocumentProcessingService(storage_root=str(tmp_path))
    sibling_raw = b"customer evidence stays"
    sibling = svc.upload_document(
        file_name="sibling.txt",
        file_data_b64=base64.b64encode(sibling_raw).decode("ascii"),
        mime_type="text/plain",
        entity_type="claim",
        entity_id="CLM-KEEP",
        customer_id="CUST-KEEP",
        skip_processing=True,
    )
    before = open(sibling.storage_path, "rb").read()
    before_sha = hashlib.sha256(before).hexdigest()

    report = run_pipeline_probe(svc, actor="admin")

    assert report["passed"] is True
    assert report["probe_removed"] is True
    assert report["probe_document_id"] is None
    assert report["siblings_checked"] == 1
    assert open(sibling.storage_path, "rb").read() == before
    assert svc.verify_integrity(sibling.document_id)["actual_sha256"] == before_sha
    assert svc.list_documents(entity_type="durability_probe")["total"] == 0
    assert svc.get_document(sibling.document_id)["customer_id"] == "CUST-KEEP"


def test_failed_probe_is_still_removed(tmp_path):
    class RejectDisk(DocumentProcessingService):
        def verify_integrity(self, doc_id):
            return {"valid": False, "actual_sha256": "0" * 64, "expected_sha256": PROBE_SHA256}

    svc = RejectDisk(storage_root=str(tmp_path))
    report = run_pipeline_probe(svc, actor="admin")
    assert report["passed"] is False
    assert report["probe_removed"] is True
    assert svc.list_documents(entity_type="durability_probe")["total"] == 0
    assert list(tmp_path.rglob("*")) == [] or all(
        path.is_dir() for path in tmp_path.rglob("*")
    )


def test_reap_removes_only_the_known_probe(tmp_path):
    svc = DocumentProcessingService(storage_root=str(tmp_path))
    own = svc.upload_document(
        file_name="phins-durability-probe.txt",
        file_data_b64=base64.b64encode(PROBE_TEXT).decode("ascii"),
        mime_type="text/plain",
        entity_type="durability_probe",
        document_type="durability_probe",
        skip_processing=True,
    )
    foreign = svc.upload_document(
        file_name="not-the-probe.txt",
        file_data_b64=base64.b64encode(b"different bytes").decode("ascii"),
        mime_type="text/plain",
        entity_type="durability_probe",
        document_type="durability_probe",
        skip_processing=True,
    )
    claimed = svc.upload_document(
        file_name="phins-durability-probe.txt",
        file_data_b64=base64.b64encode(PROBE_TEXT).decode("ascii"),
        mime_type="text/plain",
        entity_type="durability_probe",
        document_type="durability_probe",
        customer_id="CUST-1",
        skip_processing=True,
    )
    customer = svc.upload_document(
        file_name="real.txt",
        file_data_b64=base64.b64encode(b"real").decode("ascii"),
        mime_type="text/plain",
        entity_type="claim",
        customer_id="CUST-1",
        skip_processing=True,
    )
    result = reap_own_probes(svc)
    assert own.document_id in result["reaped"]
    assert foreign.document_id in result["foreign"]
    assert claimed.document_id in result["foreign"]
    assert svc.get_document(own.document_id) is None
    assert svc.get_document(foreign.document_id) is not None
    assert svc.get_document(claimed.document_id) is not None
    assert svc.get_document(customer.document_id)["sha256_checksum"] == hashlib.sha256(b"real").hexdigest()
    svc.delete_document(foreign.document_id, hard=True)
    svc.delete_document(claimed.document_id, hard=True)
    svc.delete_document(customer.document_id, hard=True)


def test_archive_hides_the_probe_lane():
    raw = base64.b64encode(b"visible").decode("ascii")
    vault = CustomerDocumentVault(policy_documents={
        "DOC-REAL": {
            "id": "DOC-REAL",
            "name": "policy.txt",
            "type": "text/plain",
            "size": 7,
            "data": raw,
            "uploaded_by_customer": "CUST-1",
            "entity_type": "policy",
            "document_type": "general",
        },
        "DOC-PROBE": {
            "id": "DOC-PROBE",
            "name": "phins-durability-probe.txt",
            "type": "text/plain",
            "size": len(PROBE_TEXT),
            "data": base64.b64encode(PROBE_TEXT).decode("ascii"),
            "entity_type": "durability_probe",
            "document_type": "durability_probe",
        },
        # A customer file cannot be hidden by claiming the reserved lane.
        "DOC-CLAIMED": {
            "id": "DOC-CLAIMED",
            "name": "receipt.txt",
            "type": "text/plain",
            "size": 8,
            "data": base64.b64encode(b"claimed!").decode("ascii"),
            "entity_type": "durability_probe",
            "document_type": "durability_probe",
            "uploaded_by_customer": "CUST-1",
        },
    })
    archive = vault.get_platform_archive(viewer_role="admin", verify_integrity=False)
    ids = {row["id"] for row in archive["documents"]}
    assert "DOC-REAL" in ids
    assert "DOC-CLAIMED" in ids
    assert "DOC-PROBE" not in ids
    customer = vault.get_vault("CUST-1", verify_integrity=False)
    assert {row["id"] for row in customer["documents"]} == {"DOC-REAL", "DOC-CLAIMED"}


def _admin_token() -> str:
    resp = requests.post(
        f"{BASE_URL}/api/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def test_http_durability_agent_is_admin_only_and_removes_the_probe():
    from services.document_processing_service import get_document_service

    token = _admin_token()
    headers = {"Authorization": f"Bearer {token}"}
    ready = requests.get(f"{BASE_URL}/api/documents/durability-test", headers=headers)
    assert ready.status_code == 200, ready.text
    assert ready.json()["ready"] is True
    assert ready.json()["writes_customer_documents"] is False

    anon = requests.post(f"{BASE_URL}/api/documents/durability-test", json={})
    assert anon.status_code == 401

    claims = requests.post(
        f"{BASE_URL}/api/login",
        json={"username": "claims_adjuster", "password": "claims123"},
    )
    assert claims.status_code == 200, claims.text
    denied = requests.post(
        f"{BASE_URL}/api/documents/durability-test",
        headers={"Authorization": f"Bearer {claims.json()['token']}"},
        json={"file_data_b64": base64.b64encode(b"ignore me").decode("ascii")},
    )
    assert denied.status_code == 403

    svc = get_document_service()
    sibling = svc.upload_document(
        file_name="keep-me.txt",
        file_data_b64=base64.b64encode(b"keep-me").decode("ascii"),
        mime_type="text/plain",
        entity_type="claim",
        entity_id="CLM-HTTP",
        customer_id="CUST-HTTP",
        skip_processing=True,
    )
    try:
        resp = requests.post(
            f"{BASE_URL}/api/documents/durability-test",
            headers=headers,
            json={"files": [{"name": "evil.pdf", "data": "aaaa"}]},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["agent_id"] == "document_durability"
        assert body["writes_customer_documents"] is False
        assert body["pipeline"]["passed"] is True
        assert body["pipeline"]["probe_removed"] is True
        assert body["pipeline"]["probe_sha256"] == PROBE_SHA256
        assert body["census"]["launch_date"] == LAUNCH_DATE
        assert svc.get_document(sibling.document_id)["sha256_checksum"] == hashlib.sha256(b"keep-me").hexdigest()
        assert svc.list_documents(entity_type="durability_probe")["total"] == 0
        assert svc.verify_integrity(sibling.document_id)["valid"] is True
    finally:
        svc.delete_document(sibling.document_id, hard=True)


def test_run_reports_inconsistent_archive_without_rewriting_it(tmp_path):
    svc = DocumentProcessingService(storage_root=str(tmp_path))
    vault = CustomerDocumentVault(policy_documents={
        "DOC-GAP": {
            "id": "DOC-GAP",
            "name": "gone.pdf",
            "type": "application/pdf",
            "size": 3,
            "sha256": "f" * 64,
            "uploaded_by_customer": "CUST-1",
            "entity_type": "claim",
            "document_type": "claim",
            "uploaded_at": "2026-02-01T00:00:00",
            "persistent_doc_id": "DOC-MISSING",
        }
    })
    vault._document_service = svc
    report = run_durability_test(vault=vault, doc_service=svc, actor="admin")
    assert report["pipeline"]["passed"] is True
    assert report["pipeline"]["probe_removed"] is True
    assert report["archive_consistent"] is False
    assert report["passed"] is False
    claims = report["census"]["since_launch"]["rows"]
    assert claims and claims[0]["process"] == "claims"
    assert claims[0]["stored"] == 0
    assert svc.list_documents(entity_type="durability_probe")["total"] == 0
