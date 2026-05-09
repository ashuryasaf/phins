"""Customer Document Vault ("Durable Object") test suite.

Covers the new ``services/customer_document_vault_service.py`` module plus the
two HTTP endpoints (``/api/durable-objects/documents`` and
``/api/durable-objects/summary``) and the ``/durable-objects`` shortcut
redirect exposed by ``web_portal/server.py``.

Each test uses its own embedded ``HTTPServer`` on a unique port so it runs in
parallel with the other suites that rely on the root ``conftest.py`` server.
"""

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
from services.customer_document_vault_service import CustomerDocumentVault


# ── Test scaffolding ──────────────────────────────────────────────────────────


class _ServerThread(threading.Thread):
    def __init__(self, port: int) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self) -> None:  # type: ignore[override]
        self.httpd.serve_forever()

    def stop(self) -> None:
        self.httpd.shutdown()


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


def _get(url: str, token: str | None = None, *, allow_redirects: bool = False):
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req) as resp:
            ctype = resp.headers.get("Content-Type", "")
            body = resp.read()
            if "application/json" in ctype:
                return resp.status, json.loads(body.decode("utf-8")), dict(resp.headers)
            return resp.status, body, dict(resp.headers)
    except HTTPError as e:
        if e.code in (301, 302) and not allow_redirects:
            return e.code, None, dict(e.headers)
        body = e.read().decode("utf-8") or "{}"
        try:
            return e.code, json.loads(body), dict(e.headers)
        except ValueError:
            return e.code, {"_raw": body}, dict(e.headers)


def _init_port(base: str) -> None:
    """Prime port-scoped state initialization (clears in-memory dicts)."""
    try:
        _get(base + "/api/documents/list")
    except Exception:
        pass


def _inject_session(token: str, username: str, role: str, customer_id: str = "") -> None:
    portal.SESSIONS[token] = {
        "username": username,
        "role": role,
        "customer_id": customer_id,
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    if username not in portal.USERS:
        portal.USERS[username] = {"role": role, "username": username}


# ── Pure unit tests for the service ──────────────────────────────────────────


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def test_vault_aggregates_across_all_stores_for_one_customer():
    """The vault must surface docs from every store, scoped to the customer."""
    policy_documents = {
        "DOC-1": {
            "id": "DOC-1",
            "name": "id_card.pdf",
            "type": "application/pdf",
            "size": 4,
            "data": _b64("ID01"),
            "uploaded_by_customer": "CUST-100",
            "entity_type": "customer",
            "entity_id": "CUST-100",
            "document_type": "id",
            "uploaded_at": "2026-01-01T10:00:00",
        },
        "DOC-2": {
            "id": "DOC-2",
            "name": "other_customer.pdf",
            "type": "application/pdf",
            "size": 4,
            "data": _b64("OTHR"),
            "uploaded_by_customer": "CUST-200",
            "entity_type": "general",
        },
    }
    claim_files = {
        "FILE-CLM-100-001": {
            "id": "FILE-CLM-100-001",
            "name": "receipt.jpg",
            "type": "image/jpeg",
            "size": 4,
            "data": _b64("RCPT"),
            "claim_id": "CLM-100",
            "customer_id": "CUST-100",
            "uploaded_at": "2026-01-02T11:00:00",
        },
    }
    underwriting_files = {
        "UW-FILE-UW-100-001": {
            "id": "UW-FILE-UW-100-001",
            "name": "medical.pdf",
            "type": "application/pdf",
            "size": 4,
            "data": _b64("MEDS"),
            "application_id": "UW-100",
            "customer_id": "CUST-100",
            "uploaded_at": "2026-01-03T12:00:00",
        },
    }

    vault = CustomerDocumentVault(
        policy_documents=policy_documents,
        claim_files=claim_files,
        underwriting_files=underwriting_files,
        claims={"CLM-100": {"customer_id": "CUST-100"}},
        underwriting_applications={"UW-100": {"customer_id": "CUST-100"}},
    )

    result = vault.get_vault("CUST-100")
    assert result["success"] is True
    assert result["customer_id"] == "CUST-100"
    names = sorted(d["name"] for d in result["documents"])
    assert names == ["id_card.pdf", "medical.pdf", "receipt.jpg"]
    assert result["summary"]["document_count"] == 3
    assert "claim" in result["summary"]["by_entity_type"]
    assert "underwriting" in result["summary"]["by_entity_type"]
    assert "customer" in result["summary"]["by_entity_type"]
    sources = result["summary"]["by_source"]
    assert sources.get(CustomerDocumentVault.SOURCE_GENERAL, 0) == 1
    assert sources.get(CustomerDocumentVault.SOURCE_CLAIM, 0) == 1
    assert sources.get(CustomerDocumentVault.SOURCE_UNDERWRITING, 0) == 1


def test_vault_resolves_owner_via_linked_entities():
    """When a doc lacks customer_id, the resolver follows policy/claim/underwriting links."""
    policy_documents = {
        "DOC-LINK-1": {
            "id": "DOC-LINK-1",
            "name": "policy_doc.pdf",
            "size": 1,
            "data": _b64("X"),
            "entity_type": "policy",
            "entity_id": "POL-555",
            # uploaded_by_customer intentionally missing
        },
    }
    vault = CustomerDocumentVault(
        policy_documents=policy_documents,
        policies={"POL-555": {"customer_id": "CUST-777"}},
    )
    result = vault.get_vault("CUST-777")
    assert result["summary"]["document_count"] == 1
    assert result["documents"][0]["uploaded_by_customer"] == "CUST-777"


def test_backfill_assigns_missing_customer_attribution():
    """Backfill should fill uploaded_by_customer/customer_id deterministically and idempotently."""
    policy_documents = {
        "DOC-BF-1": {
            "id": "DOC-BF-1",
            "name": "policy.pdf",
            "size": 1,
            "data": _b64("Y"),
            "entity_type": "policy",
            "entity_id": "POL-9",
        },
    }
    claim_files = {
        "FILE-CLM-9-001": {
            "id": "FILE-CLM-9-001",
            "name": "claim.png",
            "size": 1,
            "data": _b64("Z"),
            "claim_id": "CLM-9",
        },
    }
    underwriting_files = {
        "UW-FILE-UW-9-001": {
            "id": "UW-FILE-UW-9-001",
            "name": "uw.pdf",
            "size": 1,
            "data": _b64("Q"),
            "application_id": "UW-9",
        },
    }

    vault = CustomerDocumentVault(
        policy_documents=policy_documents,
        claim_files=claim_files,
        underwriting_files=underwriting_files,
        policies={"POL-9": {"customer_id": "CUST-9"}},
        claims={"CLM-9": {"customer_id": "CUST-9"}},
        underwriting_applications={"UW-9": {"customer_id": "CUST-9"}},
    )
    counts = vault.backfill_customer_attribution()
    assert counts["policy_documents"] == 1
    assert counts["claim_files"] == 1
    assert counts["underwriting_files"] == 1
    assert policy_documents["DOC-BF-1"]["uploaded_by_customer"] == "CUST-9"
    assert claim_files["FILE-CLM-9-001"]["customer_id"] == "CUST-9"
    assert underwriting_files["UW-FILE-UW-9-001"]["customer_id"] == "CUST-9"

    # Second invocation must be a no-op.
    counts2 = vault.backfill_customer_attribution()
    assert counts2 == {"policy_documents": 0, "claim_files": 0, "underwriting_files": 0}


def test_dedupe_collapses_same_sha256_and_lists_sources():
    """Identical content uploaded through two paths surfaces once with both sources."""
    payload = _b64("DUPLICATE")
    # Both records reference identical bytes; the vault hashes each on read so
    # they end up with the same SHA-256 even though we don't pre-compute it.
    policy_documents = {
        "DOC-DUP-1": {
            "id": "DOC-DUP-1",
            "name": "dup.pdf",
            "size": 9,
            "data": payload,
            "uploaded_by_customer": "CUST-1",
            "entity_type": "general",
            "uploaded_at": "2026-02-02T10:00:00",
        },
    }
    underwriting_files = {
        "UW-FILE-UW-1-001": {
            "id": "UW-FILE-UW-1-001",
            "name": "dup.pdf",
            "size": 9,
            "data": payload,
            "application_id": "UW-1",
            "customer_id": "CUST-1",
            "uploaded_at": "2026-01-01T10:00:00",
        },
    }

    vault = CustomerDocumentVault(
        policy_documents=policy_documents,
        underwriting_files=underwriting_files,
        underwriting_applications={"UW-1": {"customer_id": "CUST-1"}},
    )
    result = vault.get_vault("CUST-1")
    assert result["summary"]["document_count"] == 1
    doc = result["documents"][0]
    assert sorted(doc["sources"]) == sorted(
        [CustomerDocumentVault.SOURCE_GENERAL, CustomerDocumentVault.SOURCE_UNDERWRITING]
    )


def test_other_customers_documents_are_excluded():
    policy_documents = {
        "DOC-A": {"id": "DOC-A", "name": "a.pdf", "size": 1, "data": _b64("A"), "uploaded_by_customer": "CUST-A"},
        "DOC-B": {"id": "DOC-B", "name": "b.pdf", "size": 1, "data": _b64("B"), "uploaded_by_customer": "CUST-B"},
    }
    vault = CustomerDocumentVault(policy_documents=policy_documents)
    result = vault.get_vault("CUST-A")
    assert [d["name"] for d in result["documents"]] == ["a.pdf"]


def test_integrity_status_reporting_distinguishes_verified_from_unverified():
    """``ok`` must only be reported when the persistent store actually re-hashed.

    Without this guarantee the UI's green ✅ OK badge would mislead users into
    thinking integrity was checked for in-memory-only records (claim /
    underwriting attachments, or general docs uploaded while the persistent
    service was offline).
    """

    class _StubPersistent:
        """Minimal persistent-store stub modelling verify_integrity outcomes."""

        def __init__(self, outcomes):
            self._outcomes = outcomes

        def list_documents(self, **_kwargs):
            return {"items": []}

        def verify_integrity(self, doc_id):
            return self._outcomes[doc_id]

    # ── Case 1: no persistent service at all -> unverified, never ok.
    vault_no_svc = CustomerDocumentVault(
        policy_documents={
            "DOC-NO-PERSIST": {
                "id": "DOC-NO-PERSIST",
                "name": "x.pdf",
                "size": 1,
                "data": _b64("X"),
                "uploaded_by_customer": "CUST-INT",
                # explicitly no persistent_doc_id
            }
        }
    )
    result = vault_no_svc.get_vault("CUST-INT")
    assert result["documents"][0]["integrity_status"] == "unverified"

    # ── Case 2: persistent service present but record has no persistent_doc_id
    # -> still unverified (we cannot honestly re-hash anything).
    vault_no_id = CustomerDocumentVault(
        policy_documents={
            "DOC-NO-ID": {
                "id": "DOC-NO-ID",
                "name": "y.pdf",
                "size": 1,
                "data": _b64("Y"),
                "uploaded_by_customer": "CUST-INT",
            }
        },
        document_service=_StubPersistent({}),
    )
    assert vault_no_id.get_vault("CUST-INT")["documents"][0]["integrity_status"] == "unverified"

    # ── Case 3: persistent service confirms valid SHA -> ok.
    vault_ok = CustomerDocumentVault(
        policy_documents={
            "DOC-OK": {
                "id": "DOC-OK",
                "name": "z.pdf",
                "size": 1,
                "data": _b64("Z"),
                "uploaded_by_customer": "CUST-INT",
                "persistent_doc_id": "PERSIST-OK",
            }
        },
        document_service=_StubPersistent({
            "PERSIST-OK": {"valid": True, "expected_sha256": "abc", "actual_sha256": "abc"},
        }),
    )
    assert vault_ok.get_vault("CUST-INT")["documents"][0]["integrity_status"] == "ok"

    # ── Case 4: persistent service reports mismatch -> mismatch.
    vault_bad = CustomerDocumentVault(
        policy_documents={
            "DOC-BAD": {
                "id": "DOC-BAD",
                "name": "w.pdf",
                "size": 1,
                "data": _b64("W"),
                "uploaded_by_customer": "CUST-INT",
                "persistent_doc_id": "PERSIST-BAD",
            }
        },
        document_service=_StubPersistent({
            "PERSIST-BAD": {"valid": False, "error": "checksum mismatch"},
        }),
    )
    assert vault_bad.get_vault("CUST-INT")["documents"][0]["integrity_status"] == "mismatch"

    # ── Case 5: persistent service reports file missing on disk -> missing.
    vault_missing = CustomerDocumentVault(
        policy_documents={
            "DOC-MISSING": {
                "id": "DOC-MISSING",
                "name": "v.pdf",
                "size": 1,
                "data": _b64("V"),
                "uploaded_by_customer": "CUST-INT",
                "persistent_doc_id": "PERSIST-MISSING",
            }
        },
        document_service=_StubPersistent({
            "PERSIST-MISSING": {"valid": False, "error": "File not found on disk"},
        }),
    )
    assert vault_missing.get_vault("CUST-INT")["documents"][0]["integrity_status"] == "missing"


# ── HTTP integration tests ───────────────────────────────────────────────────


def test_durable_objects_endpoint_customer_sees_only_own_vault():
    port = 8410
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    tok_a = "phins_test-vault-custA-token"
    tok_b = "phins_test-vault-custB-token"
    _inject_session(tok_a, "vaultA", "customer", "CUST-VLT-A")
    _inject_session(tok_b, "vaultB", "customer", "CUST-VLT-B")

    payload = base64.b64encode(b"vault data").decode()
    status, resp = _post(
        base + "/api/documents/upload",
        {
            "files": [{"name": "vault_a.pdf", "type": "application/pdf", "size": 10, "data": payload}],
            "entity_type": "general",
            "document_type": "general",
        },
        tok_a,
    )
    assert status == 201, resp
    _post(
        base + "/api/documents/upload",
        {
            "files": [{"name": "vault_b.pdf", "type": "application/pdf", "size": 10, "data": payload}],
            "entity_type": "general",
            "document_type": "general",
        },
        tok_b,
    )

    status, body, _ = _get(base + "/api/durable-objects/documents", tok_a)
    assert status == 200, body
    assert body["success"] is True
    assert body["customer_id"] == "CUST-VLT-A"
    names = [d["name"] for d in body["documents"]]
    assert "vault_a.pdf" in names
    assert "vault_b.pdf" not in names

    # Customer A trying to spoof another customer_id is silently scoped to self.
    status, body, _ = _get(
        base + "/api/durable-objects/documents?customer_id=CUST-VLT-B", tok_a
    )
    assert status == 200
    assert body["customer_id"] == "CUST-VLT-A"
    names = [d["name"] for d in body["documents"]]
    assert "vault_b.pdf" not in names

    srv.stop()


def test_durable_objects_endpoint_admin_can_target_any_customer():
    port = 8411
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    tok_cust = "phins_test-vault-custC-token"
    tok_admin = "phins_test-vault-admin-token"
    _inject_session(tok_cust, "vaultC", "customer", "CUST-VLT-C")
    _inject_session(tok_admin, "vault_admin", "admin", "")

    payload = base64.b64encode(b"admin vault data").decode()
    _post(
        base + "/api/documents/upload",
        {
            "files": [{"name": "admin_view.pdf", "type": "application/pdf", "size": 16, "data": payload}],
            "entity_type": "general",
            "document_type": "id",
        },
        tok_cust,
    )

    status, body, _ = _get(
        base + "/api/durable-objects/documents?customer_id=CUST-VLT-C", tok_admin
    )
    assert status == 200
    assert body["is_admin"] is True
    assert body["customer_id"] == "CUST-VLT-C"
    assert any(d["name"] == "admin_view.pdf" for d in body["documents"])
    assert body["summary"]["document_count"] >= 1

    # Summary endpoint shape is BI-friendly.
    status, body, _ = _get(
        base + "/api/durable-objects/summary?customer_id=CUST-VLT-C", tok_admin
    )
    assert status == 200
    assert body["success"] is True
    assert body["customer_id"] == "CUST-VLT-C"
    assert body["summary"]["document_count"] >= 1

    srv.stop()


def test_durable_objects_requires_authentication():
    port = 8412
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    status, body, _ = _get(base + "/api/durable-objects/documents")
    assert status == 401, body

    srv.stop()


def test_durable_objects_friendly_url_redirects_to_documents_html():
    """The /durable-objects shortcut must 302 to the documents page deep-link."""
    import http.client

    port = 8413
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    _init_port(f"http://127.0.0.1:{port}")

    # urlopen would follow the redirect transparently; use http.client so we
    # can inspect the 302 status line directly.
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", "/durable-objects")
        resp = conn.getresponse()
        resp.read()
        assert resp.status == 302
        assert resp.getheader("Location") == "/documents.html#durable-objects"
    finally:
        conn.close()
        srv.stop()


def test_durable_objects_aggregates_claim_and_underwriting_uploads():
    """End-to-end: a customer's claim file shows up in their durable vault."""
    port = 8414
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    tok = "phins_test-vault-claim-token"
    customer_id = "CUST-VLT-CLAIM"
    _inject_session(tok, "vault_claim_user", "customer", customer_id)

    # Inject a claim and a claim file directly so we don't need to drive the
    # full claim filing flow (which has many side effects in this codebase).
    portal.CLAIMS["CLM-VLT-CLAIM-1"] = {
        "id": "CLM-VLT-CLAIM-1",
        "customer_id": customer_id,
        "policy_id": "POL-DUMMY",
        "type": "medical",
    }
    portal.CLAIM_FILES["FILE-CLM-VLT-CLAIM-1-001"] = {
        "id": "FILE-CLM-VLT-CLAIM-1-001",
        "name": "claim_attachment.png",
        "type": "image/png",
        "size": 4,
        "data": base64.b64encode(b"PNG!").decode(),
        "claim_id": "CLM-VLT-CLAIM-1",
        "customer_id": customer_id,
        "uploaded_at": datetime.now().isoformat(),
    }

    portal.UNDERWRITING_APPLICATIONS["UW-VLT-CLAIM-1"] = {
        "id": "UW-VLT-CLAIM-1",
        "customer_id": customer_id,
    }
    portal.UNDERWRITING_FILES["UW-FILE-UW-VLT-CLAIM-1-001"] = {
        "id": "UW-FILE-UW-VLT-CLAIM-1-001",
        "name": "underwriting_attachment.pdf",
        "type": "application/pdf",
        "size": 4,
        "data": base64.b64encode(b"PDF!").decode(),
        "application_id": "UW-VLT-CLAIM-1",
        "customer_id": customer_id,
        "uploaded_at": datetime.now().isoformat(),
    }

    status, body, _ = _get(base + "/api/durable-objects/documents", tok)
    assert status == 200, body
    names = {d["name"] for d in body["documents"]}
    assert "claim_attachment.png" in names
    assert "underwriting_attachment.pdf" in names

    # Both sources should be reflected in the summary.
    sources = body["summary"]["by_source"]
    assert sources.get(CustomerDocumentVault.SOURCE_CLAIM, 0) >= 1
    assert sources.get(CustomerDocumentVault.SOURCE_UNDERWRITING, 0) >= 1

    # Every "Open" link the vault hands back must point at a handler that
    # actually exists so clicking it does not 404.
    docs_by_name = {d["name"]: d for d in body["documents"]}
    claim_view = docs_by_name["claim_attachment.png"]["view_url"]
    uw_view = docs_by_name["underwriting_attachment.pdf"]["view_url"]
    assert claim_view.startswith("/api/claims/files/view?id=")
    assert uw_view.startswith("/api/underwriting/files/view?id=")

    status, body, _ = _get(base + claim_view, tok)
    assert status == 200, body
    assert body["success"] is True
    assert body["name"] == "claim_attachment.png"
    assert body["data"]  # base64 payload returned
    assert body["customer_id"] == customer_id

    status, body, _ = _get(base + uw_view, tok)
    assert status == 200, body
    assert body["success"] is True
    assert body["name"] == "underwriting_attachment.pdf"
    assert body["data"]
    assert body["customer_id"] == customer_id

    srv.stop()


def test_claim_and_underwriting_view_endpoints_enforce_ownership():
    """Customers must not be able to read another customer's claim/UW attachments."""
    port = 8415
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    owner_token = "phins_test-attach-owner-token"
    intruder_token = "phins_test-attach-intruder-token"
    admin_token = "phins_test-attach-admin-token"
    _inject_session(owner_token, "attach_owner", "customer", "CUST-ATT-OWNER")
    _inject_session(intruder_token, "attach_intruder", "customer", "CUST-ATT-INTRUDER")
    _inject_session(admin_token, "attach_admin", "admin", "")

    portal.CLAIMS["CLM-ATT-OWNER-1"] = {
        "id": "CLM-ATT-OWNER-1",
        "customer_id": "CUST-ATT-OWNER",
        "policy_id": "POL-X",
    }
    portal.CLAIM_FILES["FILE-CLM-ATT-OWNER-1-001"] = {
        "id": "FILE-CLM-ATT-OWNER-1-001",
        "name": "private.pdf",
        "type": "application/pdf",
        "size": 4,
        "data": base64.b64encode(b"PRIV").decode(),
        "claim_id": "CLM-ATT-OWNER-1",
        "customer_id": "CUST-ATT-OWNER",
        "uploaded_at": datetime.now().isoformat(),
    }
    portal.UNDERWRITING_APPLICATIONS["UW-ATT-OWNER-1"] = {
        "id": "UW-ATT-OWNER-1",
        "customer_id": "CUST-ATT-OWNER",
    }
    portal.UNDERWRITING_FILES["UW-FILE-UW-ATT-OWNER-1-001"] = {
        "id": "UW-FILE-UW-ATT-OWNER-1-001",
        "name": "uw_private.pdf",
        "type": "application/pdf",
        "size": 4,
        "data": base64.b64encode(b"UWPR").decode(),
        "application_id": "UW-ATT-OWNER-1",
        "customer_id": "CUST-ATT-OWNER",
        "uploaded_at": datetime.now().isoformat(),
    }

    claim_url = "/api/claims/files/view?id=FILE-CLM-ATT-OWNER-1-001"
    uw_url = "/api/underwriting/files/view?id=UW-FILE-UW-ATT-OWNER-1-001"

    # Owner: 200
    status, body, _ = _get(base + claim_url, owner_token)
    assert status == 200, body
    assert body["data"]
    status, body, _ = _get(base + uw_url, owner_token)
    assert status == 200, body
    assert body["data"]

    # Intruder: 403
    status, body, _ = _get(base + claim_url, intruder_token)
    assert status == 403, body
    status, body, _ = _get(base + uw_url, intruder_token)
    assert status == 403, body

    # Admin: 200
    status, body, _ = _get(base + claim_url, admin_token)
    assert status == 200, body
    status, body, _ = _get(base + uw_url, admin_token)
    assert status == 200, body

    # Unknown id: 404
    status, body, _ = _get(base + "/api/claims/files/view?id=NOPE", owner_token)
    assert status == 404, body
    status, body, _ = _get(base + "/api/underwriting/files/view?id=NOPE", owner_token)
    assert status == 404, body

    # Missing id: 400
    status, body, _ = _get(base + "/api/claims/files/view", owner_token)
    assert status == 400, body

    # Unauthenticated: 401
    status, body, _ = _get(base + claim_url)
    assert status == 401, body

    srv.stop()
