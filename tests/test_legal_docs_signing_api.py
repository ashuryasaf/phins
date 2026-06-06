"""
Integration tests for the legal/corporate/funding document signing API.

These exercise the ledger-anchored signature endpoints end-to-end against the
embedded web portal server started by the root ``conftest.py``:

    POST /api/legal-docs/sign      → anchor a signature into the hash chain
    POST /api/legal-docs/verify    → confirm hash match + chain integrity
    GET  /api/legal-docs/registry  → list anchored signatures for a document

Data-integrity guarantees asserted here:
- a valid signature returns a 64-hex entry hash + sequence number,
- re-posting the same signature is idempotent (no duplicate, chain stays valid),
- verify detects tampered/unknown hashes,
- bad input returns the ``{"error": ...}`` shape,
- the platform event ledger chain remains valid after signing.
"""

import os
import re
import uuid

import requests

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _doc_id():
    return "LGL-TERM-SHEET-TEST-" + uuid.uuid4().hex[:10].upper()


def _admin_token():
    # Voiding a signature requires an authenticated PHINS session (test-mode
    # legacy password allowed). Anchoring a signature stays session-optional.
    r = requests.post(
        f"{BASE_URL}/api/login",
        json={"username": "admin", "password": "admin123"},
        timeout=10,
    )
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _hash(seed="a"):
    # deterministic 64-hex string for the test (not a real digest)
    return (seed * 64)[:64].replace(seed, "0" if seed == "z" else seed)


def test_sign_returns_ledger_receipt():
    doc_id = _doc_id()
    payload = {
        "docType": "term-sheet",
        "docInstanceId": doc_id,
        "context": "investor",
        "role": "Investor",
        "signerName": "Test Investor LP",
        "signerTitle": "Managing Partner",
        "signedAt": "2026-06-06T12:00:00Z",
        "documentHash": "a" * 64,
        "signatureMethod": "type",
    }
    r = requests.post(f"{BASE_URL}/api/legal-docs/sign", json=payload, timeout=10)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["event"] == "legal_document_signed"
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert HEX64.match(data["entry_hash"])
    assert data["document_hash"] == "a" * 64


def test_sign_is_idempotent_and_chain_valid():
    doc_id = _doc_id()
    payload = {
        "docType": "founder-agreement",
        "docInstanceId": doc_id,
        "role": "Founder",
        "signerName": "Asaf Ashury",
        "documentHash": "b" * 64,
    }
    r1 = requests.post(f"{BASE_URL}/api/legal-docs/sign", json=payload, timeout=10)
    r2 = requests.post(f"{BASE_URL}/api/legal-docs/sign", json=payload, timeout=10)
    assert r1.status_code == 200 and r2.status_code == 200
    d1, d2 = r1.json(), r2.json()
    # Idempotent: same deterministic entry id + hash, no duplicate entry.
    assert d1["entry_id"] == d2["entry_id"]
    assert d1["entry_hash"] == d2["entry_hash"]

    # Verify reports chain integrity intact.
    v = requests.post(
        f"{BASE_URL}/api/legal-docs/verify",
        json={"docInstanceId": doc_id, "documentHash": "b" * 64},
        timeout=10,
    )
    assert v.status_code == 200
    vd = v.json()
    assert vd["verified"] is True
    assert vd["chain_valid"] is True


def test_registry_lists_signatures():
    doc_id = _doc_id()
    for role, signer in [("Investor", "Acme Ventures"), ("Company", "PHINS Insurance, Inc.")]:
        requests.post(
            f"{BASE_URL}/api/legal-docs/sign",
            json={
                "docType": "term-sheet",
                "docInstanceId": doc_id,
                "role": role,
                "signerName": signer,
                "documentHash": "c" * 64,
            },
            timeout=10,
        )
    r = requests.get(f"{BASE_URL}/api/legal-docs/registry", params={"doc_id": doc_id}, timeout=10)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert {"items", "total", "doc_id"}.issubset(data.keys())
    roles = {item["role"] for item in data["items"]}
    assert roles == {"Investor", "Company"}
    for item in data["items"]:
        assert HEX64.match(item["entry_hash"])
        assert item["document_hash"] == "c" * 64


def test_void_then_resign_same_hash_verifies_active():
    # Sign, void, then re-sign the SAME content hash. The re-sign must anchor a
    # fresh ledger row (not idempotently reuse the now-voided one) so verify
    # reports an active match again.
    doc_id = _doc_id()
    base = {
        "docType": "term-sheet",
        "docInstanceId": doc_id,
        "role": "Investor",
        "signerName": "Recurring Investor LP",
        "documentHash": "f" * 64,
    }

    s1 = requests.post(f"{BASE_URL}/api/legal-docs/sign", json=base, timeout=10)
    assert s1.status_code == 200, s1.text

    v_after_sign = requests.post(
        f"{BASE_URL}/api/legal-docs/verify",
        json={"docInstanceId": doc_id, "documentHash": "f" * 64},
        timeout=10,
    )
    assert v_after_sign.json()["verified"] is True

    void = requests.post(
        f"{BASE_URL}/api/legal-docs/sign",
        json=dict(base, event="void"),
        headers=_auth(_admin_token()),
        timeout=10,
    )
    assert void.status_code == 200
    assert void.json()["event"] == "legal_document_voided"

    v_after_void = requests.post(
        f"{BASE_URL}/api/legal-docs/verify",
        json={"docInstanceId": doc_id, "documentHash": "f" * 64},
        timeout=10,
    )
    assert v_after_void.json()["verified"] is False

    # Re-sign identical content: should anchor a new entry and verify active.
    s2 = requests.post(f"{BASE_URL}/api/legal-docs/sign", json=base, timeout=10)
    assert s2.status_code == 200, s2.text
    assert s2.json()["entry_id"] != s1.json()["entry_id"]

    v_after_resign = requests.post(
        f"{BASE_URL}/api/legal-docs/verify",
        json={"docInstanceId": doc_id, "documentHash": "f" * 64},
        timeout=10,
    )
    vd = v_after_resign.json()
    assert vd["verified"] is True
    assert vd["chain_valid"] is True


def test_conflicting_content_for_same_hash_is_rejected():
    # Two parties anchoring the SAME documentHash must attest to identical
    # content. A second signature carrying a divergent snapshot under the same
    # hash is rejected so verify cannot succeed over mismatched content.
    doc_id = _doc_id()
    base = {
        "docType": "term-sheet",
        "docInstanceId": doc_id,
        "documentHash": "1" * 64,
        "content": {"context": "investor", "fieldValues": {"amount": "1000000"}, "tableData": {}},
    }
    first = requests.post(
        f"{BASE_URL}/api/legal-docs/sign",
        json=dict(base, role="Investor", signerName="Acme Ventures"),
        timeout=10,
    )
    assert first.status_code == 200, first.text

    # Same hash, different content snapshot → conflict.
    conflict = requests.post(
        f"{BASE_URL}/api/legal-docs/sign",
        json={
            "docType": "term-sheet",
            "docInstanceId": doc_id,
            "role": "Company",
            "signerName": "PHINS Insurance, Inc.",
            "documentHash": "1" * 64,
            "content": {"context": "investor", "fieldValues": {"amount": "9999999"}, "tableData": {}},
        },
        timeout=10,
    )
    assert conflict.status_code == 409, conflict.text
    assert "error" in conflict.json()

    # Same hash, matching content snapshot → accepted (genuine co-signer).
    cosign = requests.post(
        f"{BASE_URL}/api/legal-docs/sign",
        json=dict(base, role="Company", signerName="PHINS Insurance, Inc."),
        timeout=10,
    )
    assert cosign.status_code == 200, cosign.text


def test_void_requires_authentication():
    # Anchoring is session-optional, but voiding supersedes active anchors and
    # must require an authenticated session — otherwise anyone who learns a
    # docInstanceId could void legitimate parties' signatures.
    doc_id = _doc_id()
    base = {
        "docType": "term-sheet",
        "docInstanceId": doc_id,
        "role": "Investor",
        "signerName": "Protected Investor LP",
        "documentHash": "9" * 64,
    }
    sign = requests.post(f"{BASE_URL}/api/legal-docs/sign", json=base, timeout=10)
    assert sign.status_code == 200, sign.text

    # Unauthenticated void is rejected and the signature stays active.
    void = requests.post(
        f"{BASE_URL}/api/legal-docs/sign",
        json=dict(base, event="void"),
        timeout=10,
    )
    assert void.status_code == 401, void.text
    assert "error" in void.json()

    v = requests.post(
        f"{BASE_URL}/api/legal-docs/verify",
        json={"docInstanceId": doc_id, "documentHash": "9" * 64},
        timeout=10,
    )
    assert v.json()["verified"] is True

    # Authenticated void succeeds and supersedes the signature.
    auth_void = requests.post(
        f"{BASE_URL}/api/legal-docs/sign",
        json=dict(base, event="void"),
        headers=_auth(_admin_token()),
        timeout=10,
    )
    assert auth_void.status_code == 200, auth_void.text
    assert auth_void.json()["event"] == "legal_document_voided"

    v_after = requests.post(
        f"{BASE_URL}/api/legal-docs/verify",
        json={"docInstanceId": doc_id, "documentHash": "9" * 64},
        timeout=10,
    )
    assert v_after.json()["verified"] is False


def test_verify_rejects_tampered_hash():
    doc_id = _doc_id()
    requests.post(
        f"{BASE_URL}/api/legal-docs/sign",
        json={
            "docType": "esop-agreement",
            "docInstanceId": doc_id,
            "role": "Optionee",
            "signerName": "Jordan Lee",
            "documentHash": "d" * 64,
        },
        timeout=10,
    )
    # A different (tampered) hash must not verify.
    v = requests.post(
        f"{BASE_URL}/api/legal-docs/verify",
        json={"docInstanceId": doc_id, "documentHash": "e" * 64},
        timeout=10,
    )
    assert v.status_code == 200
    assert v.json()["verified"] is False


def test_bad_input_returns_error_shape():
    # Missing required fields.
    r = requests.post(f"{BASE_URL}/api/legal-docs/sign", json={"docType": "x"}, timeout=10)
    assert r.status_code == 400
    assert "error" in r.json()

    # Bad hash length.
    r = requests.post(
        f"{BASE_URL}/api/legal-docs/sign",
        json={
            "docType": "nda",
            "docInstanceId": _doc_id(),
            "role": "Recipient",
            "signerName": "Someone",
            "documentHash": "tooshort",
        },
        timeout=10,
    )
    assert r.status_code == 400
    assert "error" in r.json()

    # Registry without doc_id.
    r = requests.get(f"{BASE_URL}/api/legal-docs/registry", timeout=10)
    assert r.status_code == 400
    assert "error" in r.json()

    # Verify with bad hash.
    r = requests.post(
        f"{BASE_URL}/api/legal-docs/verify",
        json={"docInstanceId": _doc_id(), "documentHash": "nope"},
        timeout=10,
    )
    assert r.status_code == 400
    assert "error" in r.json()
