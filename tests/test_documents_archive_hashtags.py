"""Platform document archive + process hashtag coverage."""

from __future__ import annotations

import base64
import json
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal
from services.customer_document_vault_service import (
    CustomerDocumentVault,
    infer_process_hashtag,
)


class _ServerThread(threading.Thread):
    def __init__(self, port: int) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self) -> None:  # type: ignore[override]
        self.httpd.serve_forever()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _get(url: str, token: str | None = None):
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        body = e.read().decode("utf-8") or "{}"
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, {"_raw": body}


def _inject_session(token: str, username: str, role: str, customer_id: str = "") -> None:
    portal.SESSIONS[token] = {
        "username": username,
        "role": role,
        "customer_id": customer_id,
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    if username not in portal.USERS:
        portal.USERS[username] = {"role": role, "username": username}


def test_infer_process_hashtag_taxonomy():
    assert infer_process_hashtag(document_type="id") == "identity"
    assert infer_process_hashtag(document_type="medical") == "medical"
    assert infer_process_hashtag(document_type="risk_assessment") == "risk_assessment"
    assert infer_process_hashtag(entity_type="claim") == "claim"
    assert infer_process_hashtag(entity_type="billing") == "billing"
    assert infer_process_hashtag(entity_type="underwriting") == "underwriting"
    assert infer_process_hashtag(name="Lab Results.pdf") == "medical"
    assert infer_process_hashtag(name="passport-scan.png") == "identity"


def test_platform_archive_api_staff_only_with_hashtags():
    port = 8431
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    # Prime port-scoped state (can clear SESSIONS/stores) before seeding.
    try:
        urlopen(base + "/api/health", timeout=5).read()
    except Exception:
        pass

    owner = "CUST-ARCH-1"
    portal.POLICY_DOCUMENTS["DOC-ARCH-ID"] = {
        "id": "DOC-ARCH-ID",
        "name": "passport.pdf",
        "type": "application/pdf",
        "size": 4,
        "data": base64.b64encode(b"PASS").decode(),
        "document_type": "id",
        "entity_type": "customer",
        "entity_id": owner,
        "uploaded_by_customer": owner,
        "uploaded_at": datetime.now().isoformat(),
    }
    portal.UNDERWRITING_APPLICATIONS["UW-ARCH-1"] = {
        "id": "UW-ARCH-1",
        "customer_id": owner,
    }
    portal.UNDERWRITING_FILES["UW-FILE-ARCH-1"] = {
        "id": "UW-FILE-ARCH-1",
        "name": "medical_lab.pdf",
        "type": "application/pdf",
        "size": 4,
        "data": base64.b64encode(b"LAB!").decode(),
        "application_id": "UW-ARCH-1",
        "customer_id": owner,
        "uploaded_at": datetime.now().isoformat(),
    }
    portal.CLAIMS["CLM-ARCH-1"] = {"id": "CLM-ARCH-1", "customer_id": owner}
    portal.CLAIM_FILES["FILE-CLM-ARCH-1"] = {
        "id": "FILE-CLM-ARCH-1",
        "name": "claim_bill.pdf",
        "type": "application/pdf",
        "size": 4,
        "data": base64.b64encode(b"CLM!").decode(),
        "claim_id": "CLM-ARCH-1",
        "customer_id": owner,
        "uploaded_at": datetime.now().isoformat(),
    }

    cust_tok = "phins_test-arch-cust"
    admin_tok = "phins_test-arch-admin"
    uw_tok = "phins_test-arch-uw"
    _inject_session(cust_tok, "arch_cust", "customer", owner)
    _inject_session(admin_tok, "arch_admin", "admin", "")
    _inject_session(uw_tok, "arch_uw", "underwriter", "")

    status, body = _get(base + "/api/documents/archive")
    assert status == 401

    status, body = _get(base + "/api/documents/archive", cust_tok)
    assert status == 403

    status, body = _get(base + "/api/documents/archive", admin_tok)
    assert status == 200, body
    assert body["vault_type"] == "platform_document_archive"
    assert body["total"] >= 3, body
    tags = {d.get("process_hashtag") for d in body["documents"]}
    assert "identity" in tags, tags
    assert ("underwriting" in tags or "medical" in tags), tags
    assert "claim" in tags, tags

    status, body = _get(
        base + "/api/documents/archive?process_hashtag=identity", uw_tok
    )
    assert status == 200, body
    assert body["total"] >= 1
    assert all(d.get("process_hashtag") == "identity" for d in body["documents"])

    srv.stop()


def test_vault_unit_platform_archive_preserves_bytes():
    raw = b"HISTORIC"
    b64 = base64.b64encode(raw).decode()
    policy_documents = {
        "DOC-1": {
            "id": "DOC-1",
            "name": "old_id.pdf",
            "type": "application/pdf",
            "size": len(raw),
            "data": b64,
            "document_type": "id",
            "uploaded_by_customer": "CUST-1",
            "entity_type": "customer",
            "entity_id": "CUST-1",
        }
    }
    vault = CustomerDocumentVault(policy_documents=policy_documents)
    result = vault.get_platform_archive()
    assert result["success"] is True
    assert result["documents"][0]["process_tag"] == "#identity"
    assert policy_documents["DOC-1"]["data"] == b64
