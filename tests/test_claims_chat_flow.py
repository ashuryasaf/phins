"""Claims chat: account confirm, OTP, evidence, signature, pipeline integrity."""

import base64
import json
import os
from datetime import datetime, timedelta

import pytest


def _base():
    return os.environ.get("TEST_BASE_URL", "http://localhost:8000").rstrip("/")


def _request(method, path, data=None, token=None):
    import urllib.error
    import urllib.request
    url = _base() + path
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"error": raw}
        return exc.code, parsed


def _post(path, data=None, token=None):
    return _request("POST", path, data or {}, token)


def _get(path, token=None):
    return _request("GET", path, None, token)


_SIG_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mP8z8BQz0AEYBxVSF+"
    "FABJADveWkH6oAAAAAElFTkSuQmCC"
)


def _il_id(n):
    digits = [int(c) for c in f"{n:08d}"]
    total = 0
    for i, digit in enumerate(digits):
        weighted = digit * (1 if i % 2 == 0 else 2)
        if weighted > 9:
            weighted -= 9
        total += weighted
    check = (10 - (total % 10)) % 10
    return f"{n:08d}{check}"


def _signature(name, id_number="123456782"):
    return {
        "name": name,
        "nationality": "Israel",
        "id_number": id_number,
        "signature_data": _SIG_PNG,
        "method": "drawn_canvas",
    }


def _answer(app_id, value, resume_code, token, expect=200):
    status, body = _post(
        f"/api/claims-chat/{app_id}/message",
        {"value": value, "resume_code": resume_code},
        token,
    )
    assert status == expect, body
    return body


def _warm_port():
    """First request on a test port wipes in-memory stores. Seed after that."""
    _get("/api/health")


def _seed(customer_id="CUST-CHAT-CLAIM", email="dana.claim@example.com"):
    _warm_port()
    import web_portal.server as portal
    portal.CUSTOMERS[customer_id] = {
        "id": customer_id,
        "name": "Dana Levi",
        "email": email,
        "phone": "+1-555-0100",
        "status": "active",
    }
    policy_id = "POL-CHAT-CLAIM-1"
    portal.POLICIES[policy_id] = {
        "id": policy_id,
        "customer_id": customer_id,
        "type": "life",
        "status": "active",
        "coverage_amount": 500000,
        "start_date": "2020-01-01",
    }
    return portal, customer_id, policy_id, email


def _staff_token():
    status, body = _post("/api/login", {"username": "claims_adjuster", "password": "claims123"})
    assert status == 200, body
    return body["token"]


def _customer_token(customer_id, email):
    import web_portal.server as portal
    return portal._create_signed_token(
        email, "customer", customer_id, datetime.now() + timedelta(hours=2))


def _pass_otp(app_id, resume, token):
    status, otp = _post(
        f"/api/claims-chat/{app_id}/otp/request",
        {"resume_code": resume, "delivery_channel": "email"},
        token,
    )
    assert status == 200, otp
    assert "demo_otp_code" in otp
    status, verified = _post(
        f"/api/claims-chat/{app_id}/otp/verify",
        {
            "verification_id": otp["verification_id"],
            "otp_code": otp["demo_otp_code"],
            "resume_code": resume,
        },
        token,
    )
    assert status == 200, verified
    return verified


def _file_until_signature(token, *, claimant_email=None, name="Dana Levi",
                          email="dana.claim@example.com", phone="+1-555-0100",
                          policy_id="POL-CHAT-CLAIM-1", id_number="123456782"):
    status, started = _post("/api/claims-chat/start", {"channel": "web_chat"}, token)
    assert status == 201, started
    app_id = started["application_id"]
    resume = started["resume_code"]
    assert app_id.startswith("CLCHAT-")
    assert resume.startswith("PHINS-CLAIM-")

    if claimant_email:
        assert started["step"]["id"] == "claimant"
        bound = _answer(app_id, claimant_email, resume, token)
        assert bound["step"]["id"] == "profile"
        prefill = bound["step"]["input"]["prefill"]
        assert prefill["email"] == claimant_email
        assert prefill["name"] == "Dana Levi"
    else:
        assert started["step"]["id"] == "profile"
        assert started["from_account"] is True
        assert started["step"]["input"]["prefill"]["email"] == email

    profile = _answer(app_id, {"name": name, "email": email, "phone": phone}, resume, token)
    assert profile.get("otp_required") is True
    verified = _pass_otp(app_id, resume, token)
    assert verified["step"]["id"] == "policy_id"

    _answer(app_id, policy_id, resume, token)
    _answer(app_id, "accident", resume, token)
    _answer(app_id, "2024-06-15", resume, token)
    _answer(app_id, "Tel Aviv, Rothschild 12", resume, token)
    _answer(
        app_id,
        "I slipped on a wet stair at the clinic entrance and injured my wrist.",
        resume, token,
    )
    _answer(app_id, 2500, resume, token)
    _answer(app_id, "Ichilov", resume, token)
    media_step = _answer(app_id, "done", resume, token, expect=400)
    assert "attachment" in media_step["error"].lower()

    evidence = b"clinic invoice dana levi wrist"
    status, uploaded = _post(
        f"/api/claims-chat/{app_id}/media",
        {
            "resume_code": resume,
            "kind": "document",
            "name": "invoice.txt",
            "mime_type": "text/plain",
            "data_b64": base64.b64encode(evidence).decode("ascii"),
        },
        token,
    )
    assert status == 200, uploaded
    assert uploaded["media"]["sha256"]
    voice = b"voice-note-bytes"
    status, voice_up = _post(
        f"/api/claims-chat/{app_id}/media",
        {
            "resume_code": resume,
            "kind": "voice",
            "name": "statement.webm",
            "mime_type": "audio/webm",
            "data_b64": base64.b64encode(voice).decode("ascii"),
        },
        token,
    )
    assert status == 200, voice_up
    _answer(app_id, "done", resume, token)
    _answer(app_id, "agree", resume, token)
    signed = _answer(app_id, _signature(name, id_number), resume, token)
    assert signed.get("ready_to_finalize") is True
    return app_id, resume


def test_staff_files_claim_from_known_account_and_pipeline_matches():
    portal, customer_id, policy_id, email = _seed()
    token = _staff_token()
    app_id, resume = _file_until_signature(token, claimant_email=email, policy_id=policy_id)

    status, filed = _post(
        f"/api/claims-chat/{app_id}/finalize",
        {"resume_code": resume},
        token,
    )
    assert status == 201, filed
    claim_id = filed["claim"]["id"]
    assert filed["integrity"]["verified"] is True
    assert filed["integrity"]["identity_outcome"] in ("captured", "consistent")
    assert filed["document_sha256"]
    assert filed["processing"]["notification_id"]
    assert filed["processing"]["pipeline"]["advisory_only"] is True
    assert "123456782" not in filed["document_html"]
    assert "123456782" not in filed["processing_html"]
    assert filed["integrity"]["payload_sha256"] in filed["document_html"]

    claim = portal.CLAIMS[claim_id]
    blob = json.dumps(claim, default=str)
    assert "123456782" not in blob
    assert "id_number" not in claim
    assert claim["customer_id"] == customer_id
    assert claim["policy_id"] == policy_id
    assert claim["type"] == "accident"
    assert claim["claimed_amount"] == 2500
    assert "Rothschild" in claim["description"]
    assert claim["payload_sha256"] == filed["integrity"]["payload_sha256"]
    assert claim["claims_chat_pipeline"]["recommendation"]
    assert claim["customer_identity"]["national_id_last4"]
    assert claim["customer_identity"]["national_id_hash"]

    notices = [
        rec for rec in portal.CLAIM_FILES.values()
        if rec.get("claim_id") == claim_id and rec.get("name") == "first-notice-of-loss.html"
    ]
    assert len(notices) == 1
    raw = base64.b64decode(notices[0]["data"])
    import hashlib
    assert hashlib.sha256(raw).hexdigest() == filed["document_sha256"]
    assert b"123456782" not in raw

    status, again = _post(
        f"/api/claims-chat/{app_id}/finalize", {"resume_code": resume}, token)
    assert status == 200, again
    assert again["claim"]["id"] == claim_id
    assert again["duplicate"] is True

    status, denied = _get(f"/api/claims-chat/{app_id}/document")
    assert status == 403
    status, doc = _get(
        f"/api/claims-chat/{app_id}/document?resume_code={resume}", token)
    assert status == 200, doc
    assert doc["document_sha256"] == filed["document_sha256"]


def test_customer_account_prefills_and_edits_are_honored():
    portal, customer_id, policy_id, email = _seed(
        "CUST-CHAT-CLAIM-2", "edited.claim@example.com")
    token = _customer_token(customer_id, email)
    app_id, resume = _file_until_signature(
        token,
        name="Dana Levi",
        email="edited.claim@example.com",
        phone="+1-555-0199",
        policy_id=policy_id,
    )
    status, filed = _post(
        f"/api/claims-chat/{app_id}/finalize", {"resume_code": resume}, token)
    assert status == 201, filed
    claim = portal.CLAIMS[filed["claim"]["id"]]
    assert claim["customer_id"] == customer_id
    assert "555-0199" not in json.dumps(claim)
    # Edited phone is on the notice, not a second customer id.
    assert "+1-555-0199" in filed["document_html"]
    assert claim["customer_identity"]["nationality"] == "IL"


def test_amount_above_coverage_and_identity_mismatch_do_not_file():
    portal, customer_id, policy_id, email = _seed(
        "CUST-CHAT-CLAIM-3", "mismatch.claim@example.com")
    token = _staff_token()
    status, started = _post("/api/claims-chat/start", {}, token)
    app_id, resume = started["application_id"], started["resume_code"]
    _answer(app_id, email, resume, token)
    _answer(app_id, {"name": "Dana Levi", "email": email, "phone": "+1-555-0100"}, resume, token)
    _pass_otp(app_id, resume, token)
    _answer(app_id, policy_id, resume, token)
    _answer(app_id, "medical", resume, token)
    _answer(app_id, "2024-06-15", resume, token)
    _answer(app_id, "Haifa", resume, token)
    _answer(app_id, "Outpatient visit after a fall on the clinic steps.", resume, token)
    too_high = _answer(app_id, 9000000, resume, token, expect=400)
    assert "coverage" in too_high["error"].lower()

    from services.customer_identity_service import set_identity
    other = _il_id(23456789)
    assert other != "123456782"
    set_identity(
        portal.CUSTOMERS, customer_id, other, "IL",
        source="claims", actor="test",
    )
    _answer(app_id, 1000, resume, token)
    _answer(app_id, "none", resume, token)
    evidence = base64.b64encode(b"bill").decode("ascii")
    status, uploaded = _post(
        f"/api/claims-chat/{app_id}/media",
        {"resume_code": resume, "kind": "document", "name": "bill.txt",
         "mime_type": "text/plain", "data_b64": evidence},
        token,
    )
    assert status == 200, uploaded
    _answer(app_id, "done", resume, token)
    _answer(app_id, "agree", resume, token)
    _answer(app_id, _signature("Dana Levi", "123456782"), resume, token)
    before = set(portal.CLAIMS)
    status, blocked = _post(
        f"/api/claims-chat/{app_id}/finalize", {"resume_code": resume}, token)
    assert status == 409, blocked
    assert blocked.get("code") == "identity_mismatch"
    assert set(portal.CLAIMS) == before


def test_external_link_starts_without_a_customer_session():
    _seed("CUST-CHAT-CLAIM-EXT", "outside.claim@example.com")
    status, blocked = _post("/api/claims-chat/start", {"channel": "web_chat"})
    assert status == 401, blocked
    status, started = _post("/api/claims-chat/start", {"channel": "external"})
    assert status == 201, started
    assert started["step"]["id"] == "claimant"
    app_id = started["application_id"]
    resume = started["resume_code"]
    missing = _answer(app_id, "nobody@example.com", resume, None, expect=400)
    assert "couldn't find" in missing["error"].lower()
    found = _answer(app_id, "outside.claim@example.com", resume, None)
    assert found["step"]["id"] == "profile"
    assert found["step"]["input"]["prefill"]["email"] == "outside.claim@example.com"


def test_resume_code_required_for_stranger():
    _seed("CUST-CHAT-CLAIM-4", "stranger.claim@example.com")
    token = _staff_token()
    status, started = _post("/api/claims-chat/start", {}, token)
    assert status == 201, started
    app_id = started["application_id"]
    status, blocked = _post(
        f"/api/claims-chat/{app_id}/message",
        {"value": "nope@example.com"},
    )
    assert status == 403, blocked
