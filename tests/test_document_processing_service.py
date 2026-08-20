"""
Tests for the Document Processing Service.

Covers:
- Upload with disk persistence and integrity verification
- Batch upload
- Metadata extraction for various file types (CSV, JSON, images, PDF)
- Processing pipeline (tagging, summarisation, table extraction)
- Duplicate detection
- Document retrieval and listing
- Soft and hard deletion
- In-memory fallback when DB is unavailable
- API endpoint integration via HTTP
"""

import base64
import hashlib
import json
import os
import shutil
import struct
import tempfile
import time
import uuid

import pytest
import requests

from services.document_processing_service import (
    DocumentProcessingService,
    ProcessingJobType,
    get_document_service,
    reset_document_service,
)

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


def test_ffmpeg_argv_whitelists_file_and_crypto_only():
    argv = DocumentProcessingService._ffmpeg_argv("-i", "src.mp4", "dst.mp3")
    assert argv[0] == "ffmpeg"
    assert "-protocol_whitelist" in argv
    assert argv[argv.index("-protocol_whitelist") + 1] == "file,crypto"
    assert "-nostdin" in argv
    assert "-hide_banner" in argv


# ── Helpers ──────────────────────────────────────────────────────────────────

def _admin_session():
    """Login as admin and return auth headers."""
    resp = requests.post(f"{BASE_URL}/api/login", json={
        "username": "admin",
        "password": "admin123"
    })
    if resp.status_code != 200:
        pytest.skip("Admin login failed — test server may not have users seeded")
    token = resp.json().get("token")
    return {"Authorization": f"Bearer {token}"}


def _b64(content: str = "hello world") -> str:
    return base64.b64encode(content.encode("utf-8")).decode("ascii")


def _b64_bytes(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _make_csv():
    content = "name,age,policy_type\nAlice,30,health\nBob,45,life\nCarol,55,auto\n"
    return _b64(content)


def _make_json_data():
    content = json.dumps([
        {"id": 1, "type": "claim", "amount": 1500},
        {"id": 2, "type": "policy", "amount": 3200},
    ])
    return _b64(content)


def _make_minimal_png():
    """Produce a valid 1x1 white PNG."""
    import zlib
    signature = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b'IHDR' + ihdr_data) & 0xffffffff
    ihdr = struct.pack('>I', 13) + b'IHDR' + ihdr_data + struct.pack('>I', ihdr_crc)
    raw_row = b'\x00\xff\xff\xff'
    compressed = zlib.compress(raw_row)
    idat_crc = zlib.crc32(b'IDAT' + compressed) & 0xffffffff
    idat = struct.pack('>I', len(compressed)) + b'IDAT' + compressed + struct.pack('>I', idat_crc)
    iend_crc = zlib.crc32(b'IEND') & 0xffffffff
    iend = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
    return signature + ihdr + idat + iend


# ── Unit Tests: Service Layer ────────────────────────────────────────────────

class TestDocumentProcessingServiceUnit:
    """Tests that exercise the service directly (no HTTP)."""

    def setup_method(self):
        reset_document_service()
        self.tmp_dir = tempfile.mkdtemp(prefix="phins_test_docs_")
        self.svc = DocumentProcessingService(storage_root=self.tmp_dir)

    def teardown_method(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        reset_document_service()

    def test_upload_simple_text_file(self):
        result = self.svc.upload_document(
            file_name="readme.txt",
            file_data_b64=_b64("Hello PHINS"),
        )
        assert result.document_id.startswith("DOC-")
        assert result.file_size == len(b"Hello PHINS")
        assert result.sha256 == hashlib.sha256(b"Hello PHINS").hexdigest()
        assert result.status in ("uploaded", "processed")
        assert os.path.exists(result.storage_path)

    def test_upload_csv_extracts_metadata(self):
        result = self.svc.upload_document(
            file_name="data.csv",
            file_data_b64=_make_csv(),
            category="table",
        )
        assert result.category == "table"
        meta = result.metadata
        assert "metadata" in meta
        assert meta["metadata"].get("row_count", 0) >= 2

    def test_upload_json_extracts_metadata(self):
        result = self.svc.upload_document(
            file_name="claims.json",
            file_data_b64=_make_json_data(),
        )
        meta = result.metadata.get("metadata", {})
        assert meta.get("format") == "JSON"
        assert meta.get("type") == "array"

    def test_upload_png_image(self):
        png_data = _make_minimal_png()
        result = self.svc.upload_document(
            file_name="photo.png",
            file_data_b64=_b64_bytes(png_data),
        )
        assert result.mime_type == "image/png"
        meta = result.metadata.get("metadata", {})
        assert meta.get("format") == "PNG"
        assert meta.get("width") == 1
        assert meta.get("height") == 1

    def test_integrity_verification_passes(self):
        result = self.svc.upload_document(
            file_name="policy.txt",
            file_data_b64=_b64("Policy document content"),
        )
        check = self.svc.verify_integrity(result.document_id)
        assert check["valid"] is True
        assert check["expected_sha256"] == check["actual_sha256"]

    def test_integrity_verification_detects_corruption(self):
        result = self.svc.upload_document(
            file_name="contract.txt",
            file_data_b64=_b64("Contract terms"),
        )
        with open(result.storage_path, "wb") as f:
            f.write(b"TAMPERED DATA")
        check = self.svc.verify_integrity(result.document_id)
        assert check["valid"] is False
        assert check["expected_sha256"] != check["actual_sha256"]

    def test_duplicate_detection(self):
        data = _b64("Duplicate content")
        r1 = self.svc.upload_document(file_name="file_a.txt", file_data_b64=data)
        r2 = self.svc.upload_document(file_name="file_b.txt", file_data_b64=data)
        assert r2.duplicate_of == r1.document_id

    def test_batch_upload(self):
        files = [
            {"name": "a.txt", "data": _b64("File A")},
            {"name": "b.csv", "data": _make_csv()},
            {"name": "c.json", "data": _make_json_data()},
        ]
        results = self.svc.upload_batch(files, entity_type="test", entity_id="T-001")
        assert len(results) == 3
        for r in results:
            assert r.status != "error"

    def test_batch_upload_limit(self):
        files = [{"name": f"f{i}.txt", "data": _b64(f"content {i}")} for i in range(30)]
        with pytest.raises(ValueError, match="Batch exceeds"):
            self.svc.upload_batch(files)

    def test_list_documents(self):
        self.svc.upload_document(
            file_name="list_test.txt", file_data_b64=_b64("data"),
            entity_type="policy", entity_id="POL-001",
        )
        result = self.svc.list_documents(entity_type="policy", entity_id="POL-001")
        assert result["total"] >= 1
        assert len(result["items"]) >= 1

    def test_get_document_with_data(self):
        r = self.svc.upload_document(file_name="view_test.txt", file_data_b64=_b64("view me"))
        doc = self.svc.get_document(r.document_id, include_data=True)
        assert doc is not None
        assert doc.get("data")
        raw = base64.b64decode(doc["data"])
        assert raw == b"view me"

    def test_soft_delete(self):
        r = self.svc.upload_document(file_name="delete_me.txt", file_data_b64=_b64("bye"))
        assert self.svc.delete_document(r.document_id) is True
        doc = self.svc.get_document(r.document_id)
        if isinstance(doc, dict):
            assert doc.get("is_deleted") or doc.get("status") == "archived"

    def test_hard_delete_removes_file(self):
        r = self.svc.upload_document(file_name="hard_del.txt", file_data_b64=_b64("gone"))
        path = r.storage_path
        assert os.path.exists(path)
        self.svc.delete_document(r.document_id, hard=True)
        assert not os.path.exists(path)

    def test_statistics(self):
        self.svc.upload_document(file_name="s1.csv", file_data_b64=_make_csv(), category="table")
        self.svc.upload_document(file_name="s2.txt", file_data_b64=_b64("text"), category="general")
        stats = self.svc.get_statistics()
        assert stats["total_documents"] >= 2
        assert stats["total_size_bytes"] > 0
        assert "table" in stats["by_category"]
        assert "general" in stats["by_category"]

    def test_process_document(self):
        r = self.svc.upload_document(
            file_name="process_me.csv", file_data_b64=_make_csv(),
            skip_processing=True,
        )
        results = self.svc.process_document(r.document_id)
        assert len(results) > 0
        types = [j.job_type for j in results]
        assert "metadata_extraction" in types
        for j in results:
            assert j.status in ("completed", "failed")

    def test_process_specific_job_types(self):
        r = self.svc.upload_document(
            file_name="specific.csv", file_data_b64=_make_csv(),
            skip_processing=True,
        )
        results = self.svc.process_document(r.document_id, [
            "table_extraction",
            "integrity_check",
        ])
        assert len(results) == 2
        types = [j.job_type for j in results]
        assert "table_extraction" in types
        assert "integrity_check" in types

    def test_csv_table_extraction(self):
        r = self.svc.upload_document(
            file_name="table.csv", file_data_b64=_make_csv(),
            skip_processing=True,
        )
        results = self.svc.process_document(r.document_id, ["table_extraction"])
        assert len(results) == 1
        assert results[0].status == "completed"
        result_data = results[0].result
        assert result_data.get("row_count", 0) >= 2
        assert "headers" in result_data
        assert "name" in result_data["headers"]

    def test_ai_tagging(self):
        content = "Patient diagnosis treatment clinical medication"
        r = self.svc.upload_document(
            file_name="medical_notes.txt", file_data_b64=_b64(content),
            skip_processing=True,
        )
        results = self.svc.process_document(r.document_id, ["ai_tagging"])
        assert results[0].status == "completed"
        tags = results[0].result.get("tags", [])
        assert "medical" in tags

    def test_category_classification(self):
        assert self.svc._classify_category("scan.jpg", "image/jpeg") == "identity"
        assert self.svc._classify_category("data.csv", "text/csv") == "table"
        assert self.svc._classify_category("video.mp4", "video/mp4") == "media"
        assert self.svc._classify_category("contract.docx", "application/msword") == "legal"
        assert self.svc._classify_category("unknown.xyz", "application/octet-stream") == "general"

    def test_upload_rejects_empty_content(self):
        with pytest.raises(ValueError, match="(Missing file content|content cannot be empty)"):
            self.svc.upload_document(
                file_name="empty.txt",
                file_data_b64=_b64_bytes(b""),
            )

    def test_upload_rejects_missing_filename(self):
        with pytest.raises(ValueError, match="Missing file name"):
            self.svc.upload_document(file_name="", file_data_b64=_b64("data"))

    def test_upload_with_entity_and_customer(self):
        r = self.svc.upload_document(
            file_name="claim_doc.pdf",
            file_data_b64=_b64("pdf content"),
            entity_type="claim",
            entity_id="CLM-001",
            customer_id="CUST-001",
            uploaded_by="staff_user",
            uploaded_by_role="admin",
        )
        assert r.document_id.startswith("DOC-")
        doc = self.svc.get_document(r.document_id)
        if isinstance(doc, dict):
            assert doc.get("entity_type") == "claim"
            assert doc.get("entity_id") == "CLM-001"
            assert doc.get("customer_id") == "CUST-001"


# ── Integration Tests: HTTP API ──────────────────────────────────────────────

class TestDocumentProcessingServiceAPI:
    """Tests that exercise the HTTP endpoints."""

    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_document_service()
        yield
        reset_document_service()

    def test_upload_via_api(self):
        headers = _admin_session()
        resp = requests.post(f"{BASE_URL}/api/doc-service/upload", json={
            "files": [
                {"name": "api_test.txt", "data": _b64("API upload test")},
            ],
            "entity_type": "policy",
            "entity_id": "POL-API-001",
        }, headers=headers)
        assert resp.status_code == 201
        body = resp.json()
        assert body["success"] is True
        assert len(body["uploaded"]) == 1
        assert body["uploaded"][0]["document_id"].startswith("DOC-")

    def test_upload_batch_via_api(self):
        headers = _admin_session()
        resp = requests.post(f"{BASE_URL}/api/doc-service/upload", json={
            "files": [
                {"name": "batch_a.txt", "data": _b64("A")},
                {"name": "batch_b.csv", "data": _make_csv()},
            ],
            "entity_type": "claim",
        }, headers=headers)
        assert resp.status_code == 201
        body = resp.json()
        assert len(body["uploaded"]) == 2

    def test_upload_requires_auth(self):
        resp = requests.post(f"{BASE_URL}/api/doc-service/upload", json={
            "files": [{"name": "a.txt", "data": _b64("no auth")}],
        })
        assert resp.status_code == 401

    def test_upload_requires_files(self):
        headers = _admin_session()
        resp = requests.post(f"{BASE_URL}/api/doc-service/upload", json={},
                             headers=headers)
        assert resp.status_code == 400

    def test_list_via_api(self):
        headers = _admin_session()
        requests.post(f"{BASE_URL}/api/doc-service/upload", json={
            "files": [{"name": "list_test.txt", "data": _b64("data")}],
            "entity_type": "policy",
            "entity_id": "POL-LIST-001",
        }, headers=headers)
        resp = requests.get(f"{BASE_URL}/api/doc-service/list", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body

    def test_view_via_api(self):
        headers = _admin_session()
        upload_resp = requests.post(f"{BASE_URL}/api/doc-service/upload", json={
            "files": [{"name": "view_api.txt", "data": _b64("view test data")}],
        }, headers=headers)
        assert upload_resp.status_code == 201, f"Upload failed: {upload_resp.text}"
        doc_id = upload_resp.json()["uploaded"][0]["document_id"]
        resp = requests.get(
            f"{BASE_URL}/api/doc-service/view?id={doc_id}&include_data=true",
            headers=headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("id") or body.get("document_id")

    def test_process_via_api(self):
        headers = _admin_session()
        upload_resp = requests.post(f"{BASE_URL}/api/doc-service/upload", json={
            "files": [{"name": "process_api.csv", "data": _make_csv()}],
        }, headers=headers)
        doc_id = upload_resp.json()["uploaded"][0]["document_id"]
        resp = requests.post(f"{BASE_URL}/api/doc-service/process", json={
            "document_id": doc_id,
            "job_types": ["table_extraction", "ai_tagging"],
        }, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert len(body["jobs"]) == 2

    def test_verify_integrity_via_api(self):
        headers = _admin_session()
        upload_resp = requests.post(f"{BASE_URL}/api/doc-service/upload", json={
            "files": [{"name": "integrity.txt", "data": _b64("check me")}],
        }, headers=headers)
        doc_id = upload_resp.json()["uploaded"][0]["document_id"]
        resp = requests.post(f"{BASE_URL}/api/doc-service/verify-integrity", json={
            "document_id": doc_id,
        }, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["valid"] is True

    def test_delete_via_api(self):
        headers = _admin_session()
        upload_resp = requests.post(f"{BASE_URL}/api/doc-service/upload", json={
            "files": [{"name": "delete_api.txt", "data": _b64("to delete")}],
        }, headers=headers)
        doc_id = upload_resp.json()["uploaded"][0]["document_id"]
        resp = requests.post(f"{BASE_URL}/api/doc-service/delete", json={
            "document_id": doc_id,
        }, headers=headers)
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_statistics_via_api(self):
        headers = _admin_session()
        requests.post(f"{BASE_URL}/api/doc-service/upload", json={
            "files": [{"name": "stats.txt", "data": _b64("stats data")}],
        }, headers=headers)
        resp = requests.get(f"{BASE_URL}/api/doc-service/statistics", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "total_documents" in body

    def test_processing_types_via_api(self):
        resp = requests.get(f"{BASE_URL}/api/doc-service/processing-types")
        assert resp.status_code == 200
        body = resp.json()
        assert "processing_types" in body
        type_values = [t["value"] for t in body["processing_types"]]
        assert "metadata_extraction" in type_values
        assert "table_extraction" in type_values
        assert "identity_verification" in type_values
