"""Application / claim scoped document access with RBAC + integrity.

Covers:
* ``CustomerDocumentVault.get_entity_documents``
* ``GET /api/entity-documents`` (+ underwriting/claims aliases)
* Auth hierarchy: admin / underwriter / claims / owning customer
* Cross-customer isolation
* Index reconciliation without mutating file bytes
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from datetime import datetime
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal
from services.customer_document_vault_service import CustomerDocumentVault


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


def _post(url: str, payload: dict, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
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
    from datetime import timedelta

    portal.SESSIONS[token] = {
        "username": username,
        "role": role,
        "customer_id": customer_id,
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    if username not in portal.USERS:
        portal.USERS[username] = {"role": role, "username": username}


def _init_port(base: str) -> None:
    # Touch health so any lazy init runs.
    try:
        urlopen(base + "/api/health", timeout=5).read()
    except Exception:
        pass


def _seed_application_with_file(
    *,
    app_id: str,
    customer_id: str,
    file_id: str,
    payload: bytes = b"UW-DOC-BYTES",
    files_count_drift: int | None = None,
) -> str:
    b64 = base64.b64encode(payload).decode()
    sha = hashlib.sha256(payload).hexdigest()
    portal.UNDERWRITING_APPLICATIONS[app_id] = {
        "id": app_id,
        "customer_id": customer_id,
        "files": [],
        "files_count": files_count_drift if files_count_drift is not None else 0,
    }
    portal.UNDERWRITING_FILES[file_id] = {
        "id": file_id,
        "name": "id_scan.pdf",
        "type": "application/pdf",
        "size": len(payload),
        "data": b64,
        "sha256": sha,
        "application_id": app_id,
        "customer_id": customer_id,
        "uploaded_at": datetime.now().isoformat(),
        "uploaded_by": "customer",
    }
    return sha


def test_vault_get_entity_documents_reconciles_index():
    app_id = "UW-ENT-RECON-1"
    customer_id = "CUST-ENT-RECON"
    file_id = "UW-FILE-UW-ENT-RECON-1-001"
    payload = b"reconcile-me"
    sha = _seed_application_with_file(
        app_id=app_id,
        customer_id=customer_id,
        file_id=file_id,
        payload=payload,
        files_count_drift=0,  # drift vs live store
    )

    vault = CustomerDocumentVault(
        underwriting_files=portal.UNDERWRITING_FILES,
        underwriting_applications=portal.UNDERWRITING_APPLICATIONS,
        policy_documents={},
        claim_files={},
        claims={},
    )
    result = vault.get_entity_documents("underwriting", app_id)
    assert result["success"] is True
    assert result["customer_id"] == customer_id
    assert result["total"] == 1
    assert result["documents"][0]["sha256"] == sha
    assert result["documents"][0]["integrity_status"] == "ok"
    assert result["consistency"]["drift_detected"] is True
    assert result["consistency"]["reconciled"] is True
    assert portal.UNDERWRITING_APPLICATIONS[app_id]["files_count"] == 1
    assert portal.UNDERWRITING_APPLICATIONS[app_id]["files"][0]["id"] == file_id
    # Bytes untouched
    assert portal.UNDERWRITING_FILES[file_id]["data"] == base64.b64encode(payload).decode()


def test_entity_documents_excludes_cross_customer_general_docs():
    app_id = "UW-ENT-XCUST-1"
    owner = "CUST-ENT-XCUST-OWNER"
    intruder = "CUST-ENT-XCUST-INTRUDER"
    file_id = "UW-FILE-UW-ENT-XCUST-1-001"
    _seed_application_with_file(app_id=app_id, customer_id=owner, file_id=file_id)

    policy_documents = {
        # Legitimately affiliated general doc without an explicit owner.
        "DOC-UNOWNED": {
            "id": "DOC-UNOWNED",
            "name": "unowned.pdf",
            "entity_type": "underwriting",
            "entity_id": app_id,
            "size": 10,
        },
        # Mis-affiliated doc stamped with a different customer's ownership.
        "DOC-CROSS": {
            "id": "DOC-CROSS",
            "name": "intruder.pdf",
            "entity_type": "underwriting",
            "entity_id": app_id,
            "size": 20,
            "uploaded_by_customer": intruder,
        },
    }

    vault = CustomerDocumentVault(
        underwriting_files=portal.UNDERWRITING_FILES,
        underwriting_applications=portal.UNDERWRITING_APPLICATIONS,
        policy_documents=policy_documents,
        claim_files={},
        claims={},
    )
    result = vault.get_entity_documents("underwriting", app_id)
    assert result["success"] is True
    names = {doc["name"] for doc in result["documents"]}
    assert "unowned.pdf" in names
    assert "intruder.pdf" not in names


def test_entity_documents_api_rbac_hierarchy():
    port = 8421
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    app_id = "UW-ENT-RBAC-1"
    owner = "CUST-ENT-OWNER"
    other = "CUST-ENT-OTHER"
    file_id = "UW-FILE-UW-ENT-RBAC-1-001"
    _seed_application_with_file(app_id=app_id, customer_id=owner, file_id=file_id)

    owner_tok = "phins_test-ent-owner"
    other_tok = "phins_test-ent-other"
    admin_tok = "phins_test-ent-admin"
    uw_tok = "phins_test-ent-uw"
    claims_tok = "phins_test-ent-claims"
    _inject_session(owner_tok, "owner", "customer", owner)
    _inject_session(other_tok, "intruder", "customer", other)
    _inject_session(admin_tok, "admin", "admin", "")
    _inject_session(uw_tok, "uw", "underwriter", "")
    _inject_session(claims_tok, "cl", "claims", "")

    url = f"{base}/api/underwriting/documents?application_id={app_id}"

    status, body = _get(url)  # no auth
    assert status == 401, body

    status, body = _get(url, other_tok)
    assert status == 403, body

    for tok, role in (
        (owner_tok, "customer"),
        (admin_tok, "admin"),
        (uw_tok, "underwriter"),
        (claims_tok, "claims"),
    ):
        status, body = _get(url, tok)
        assert status == 200, (role, body)
        assert body["success"] is True
        assert body["entity_id"] == app_id
        assert body["total"] >= 1
        assert body["documents"][0]["name"] == "id_scan.pdf"
        assert body["documents"][0]["view_url"].startswith(
            "/api/underwriting/files/view?id="
        )

    # Alias path
    status, body = _get(
        f"{base}/api/entity-documents?entity_type=underwriting&entity_id={app_id}",
        admin_tok,
    )
    assert status == 200, body
    assert body["vault_type"] == "entity_document_bundle"

    # Owner can open the file; intruder cannot
    view = f"{base}/api/underwriting/files/view?id={file_id}"
    status, body = _get(view, owner_tok)
    assert status == 200, body
    assert body["data"]
    status, body = _get(view, other_tok)
    assert status == 403, body

    srv.stop()


def test_underwriting_files_post_requires_auth_and_sets_customer_id():
    port = 8422
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    app_id = "UW-ENT-POST-1"
    owner = "CUST-ENT-POST"
    portal.UNDERWRITING_APPLICATIONS[app_id] = {
        "id": app_id,
        "customer_id": owner,
        "files": [],
        "files_count": 0,
    }

    # Unauthenticated list must fail (was previously open).
    status, body = _post(
        base + "/api/underwriting/files",
        {"application_id": app_id, "action": "list"},
    )
    assert status == 401, body

    owner_tok = "phins_test-ent-post-owner"
    _inject_session(owner_tok, "owner2", "customer", owner)

    raw = b"hello-upload"
    status, body = _post(
        base + "/api/underwriting/files",
        {
            "application_id": app_id,
            "action": "upload",
            "files": [
                {
                    "name": "lab.pdf",
                    "type": "application/pdf",
                    "size": len(raw),
                    "data": base64.b64encode(raw).decode(),
                }
            ],
        },
        owner_tok,
    )
    assert status == 200, body
    assert body["success"] is True
    assert body["customer_id"] == owner
    assert body["files"]
    new_id = body["files"][0]["id"]
    stored = portal.UNDERWRITING_FILES[new_id]
    assert stored["customer_id"] == owner
    assert stored["sha256"] == hashlib.sha256(raw).hexdigest()
    assert portal.UNDERWRITING_APPLICATIONS[app_id]["files_count"] >= 1

    srv.stop()


def test_claim_entity_documents_access():
    port = 8423
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    claim_id = "CLM-ENT-1"
    owner = "CUST-CLM-ENT"
    file_id = "FILE-CLM-ENT-1-001"
    raw = b"claim-bytes"
    portal.CLAIMS[claim_id] = {
        "id": claim_id,
        "customer_id": owner,
        "files": [],
        "files_count": 99,  # intentional drift
    }
    portal.CLAIM_FILES[file_id] = {
        "id": file_id,
        "name": "bill.pdf",
        "type": "application/pdf",
        "size": len(raw),
        "data": base64.b64encode(raw).decode(),
        "claim_id": claim_id,
        "customer_id": owner,
        "uploaded_at": datetime.now().isoformat(),
    }

    admin_tok = "phins_test-ent-clm-admin"
    _inject_session(admin_tok, "admin2", "admin", "")

    status, body = _get(
        f"{base}/api/claims/documents?claim_id={claim_id}", admin_tok
    )
    assert status == 200, body
    assert body["total"] == 1
    assert body["documents"][0]["name"] == "bill.pdf"
    assert body["consistency"]["reconciled"] is True
    assert portal.CLAIMS[claim_id]["files_count"] == 1

    srv.stop()
