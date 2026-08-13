"""
End-to-end tests for the chat-style New Policy Application ("Phin" flow).

Covers the full conversational pipeline against the embedded test server:
start -> contact -> OTP gate -> adaptive underwriting questions -> live
assessment -> actuarial quote -> media attachments -> payment -> consent ->
finalize (through the real /api/policies/create backbone), plus pause/resume
with the unique code, failure paths, and the staff BI funnel / A-Z journey
ledger endpoints.
"""

import base64
import json
import os
import urllib.error
import urllib.request

import pytest


def _base() -> str:
    return os.environ.get("TEST_BASE_URL", "http://localhost:8000").rstrip("/")


def _request(method: str, path: str, data=None, token=None):
    url = _base() + path
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {}


def _post(path, data=None, token=None):
    return _request("POST", path, data or {}, token)


def _get(path, token=None):
    return _request("GET", path, None, token)


def _answer(app_id, value, expect_status=200):
    status, body = _post(f"/api/chat-application/{app_id}/message", {"value": value})
    assert status == expect_status, f"answer {value!r} -> {status}: {body}"
    return body


def _start_and_verify(email, name="Dana Levi", phone="+1-555-0100", invite_code=None):
    """Start a session, complete contact capture, and pass the OTP gate."""
    payload = {}
    if invite_code:
        payload["invite_code"] = invite_code
    status, body = _post("/api/chat-application/start", payload)
    assert status == 201, body
    app_id = body["application_id"]
    resume_code = body["resume_code"]
    assert app_id.startswith("CHAPP-")
    assert resume_code.startswith("PHINS-CHAT-")
    assert body["step"]["id"] == "name"

    _answer(app_id, name)
    _answer(app_id, email)
    reply = _answer(app_id, phone)
    assert reply.get("otp_required") is True

    status, otp = _post(f"/api/chat-application/{app_id}/otp/request", {})
    assert status == 200, otp
    assert "demo_otp_code" in otp, "test mode must expose the demo OTP"

    status, verified = _post(f"/api/chat-application/{app_id}/otp/verify", {
        "verification_id": otp["verification_id"],
        "otp_code": otp["demo_otp_code"],
    })
    assert status == 200, verified
    assert verified["step"]["id"] == "dob"
    return app_id, resume_code


def _complete_questionnaire(app_id, medical=False):
    _answer(app_id, "1990-05-14")            # dob
    _answer(app_id, "female")                # gender
    _answer(app_id, "Architect")             # occupation
    _answer(app_id, 168)                     # height
    _answer(app_id, 62)                      # weight
    _answer(app_id, "no")                    # tobacco
    if medical:
        _answer(app_id, "yes")               # medical_conditions
        _answer(app_id, "type 2 diabetes, high blood pressure")
    else:
        _answer(app_id, "no")
    _answer(app_id, "no")                    # surgery
    _answer(app_id, "no")                    # hazardous
    body = _answer(app_id, ["none"])         # family_history
    reply = _answer(app_id, "none")          # medications -> assessment fires
    assert reply.get("assessment"), reply
    return reply


def test_full_chat_application_happy_path():
    app_id, resume_code = _start_and_verify(
        "chat.applicant.happy@example.com", invite_code="TESTCODE2026")

    assessment_reply = _complete_questionnaire(app_id)
    assessment = assessment_reply["assessment"]
    assert assessment["risk_category"] in (
        "very_low", "low", "moderate", "elevated", "high", "very_high")
    assert assessment["recommendation_type"]
    assert 0 < assessment["confidence"] <= 1

    _answer(app_id, 500000)                  # coverage_amount
    quote_reply = _answer(app_id, "20")      # coverage_years -> quote fires
    quote = quote_reply["quote"]
    assert quote["monthly"] > 0
    assert quote["annual"] > 0
    assert quote["pricing_source"] in ("pricing_kernel", "flat_fallback")

    # voice note attachment
    voice = base64.b64encode(b"RIFF....fake-wav-bytes....").decode("ascii")
    status, media = _post(f"/api/chat-application/{app_id}/media", {
        "kind": "voice", "name": "note.wav", "mime_type": "audio/wav",
        "data_b64": voice, "duration_seconds": 3.5,
    })
    assert status == 200, media
    assert media["media"]["sha256"]
    assert "data_b64" not in media["media"]

    _answer(app_id, "done")                  # media_offer
    _answer(app_id, "monthly")               # billing_frequency
    _answer(app_id, {                        # payment_card
        "card_number": "5555 5555 5555 4444",
        "cardholder_name": "DANA LEVI",
        "expiry_month": "12", "expiry_year": "2031", "cvv": "123",
    })
    _answer(app_id, "yes")                   # auto_pay
    consent_reply = _answer(app_id, "agree")  # consent
    assert consent_reply.get("ready_to_finalize") is True

    status, result = _post(f"/api/chat-application/{app_id}/finalize", {})
    assert status == 201, result
    assert result["policy"]["id"].startswith("POL")
    assert result["underwriting"]["id"]
    assert result["payload_checksum"]
    assert result["submission"]["policy_id"] == result["policy"]["id"]

    # double submission is refused
    status, dup = _post(f"/api/chat-application/{app_id}/finalize", {})
    assert status == 409
    assert "error" in dup

    # state readable with the resume code
    status, state = _get(f"/api/chat-application/{app_id}?resume_code={resume_code}")
    assert status == 200, state
    assert state["status"] == "submitted"
    assert state["progress"]["percent"] == 100
    assert any(m["kind"] == "quote" for m in state["transcript"])

    # A-Z journey: chat stages + hash-chained ledger events
    status, journey = _get(f"/api/chat-application/{app_id}/journey?resume_code={resume_code}")
    assert status == 200, journey
    stages = [j["stage"] for j in journey["journey"]]
    for expected in ("invited", "started", "contact_captured", "otp_verified",
                     "questions_completed", "assessed", "quoted",
                     "media_attached", "payment_captured", "submitted"):
        assert expected in stages, f"missing journey stage {expected}: {stages}"
    assert journey["ledger_event_count"] > 0
    types = {e["event_type"] for e in journey["ledger_events"]}
    assert "chat.message" in types
    assert any(t.startswith("journey.") for t in types)
    assert all(e.get("entry_hash") for e in journey["ledger_events"])


def test_medical_follow_up_and_risk_loading():
    app_id, _ = _start_and_verify("chat.applicant.medical@example.com")
    reply = _complete_questionnaire(app_id, medical=True)
    assessment = reply["assessment"]
    assert "type 2 diabetes" in " ".join(assessment["conditions_considered"])
    # diabetes + hypertension must not come back "very_low"
    assert assessment["risk_category"] != "very_low"


def test_pause_and_resume_with_otp_rechallenge():
    email = "chat.applicant.resume@example.com"
    app_id, resume_code = _start_and_verify(email)
    _answer(app_id, "1985-03-02")            # dob answered before pausing

    status, paused = _post(f"/api/chat-application/{app_id}/pause", {})
    assert status == 200, paused
    assert paused["resume_code"] == resume_code

    # wrong email -> generic rejection (no enumeration)
    status, bad = _post("/api/chat-application/resume",
                        {"resume_code": resume_code, "email": "wrong@example.com"})
    assert status == 404
    assert "error" in bad

    # wrong code -> same generic rejection
    status, bad = _post("/api/chat-application/resume",
                        {"resume_code": "PHINS-CHAT-DEADBEEF", "email": email})
    assert status == 404

    # correct code + email -> OTP re-challenge (session was verified)
    status, resumed = _post("/api/chat-application/resume",
                            {"resume_code": resume_code, "email": email})
    assert status == 200, resumed
    assert resumed["status"] == "pending_reverify"
    assert resumed["otp_required"] is True
    otp = resumed["otp"]
    assert "demo_otp_code" in otp

    # answers are blocked until the fresh OTP is verified
    status, blocked = _post(f"/api/chat-application/{app_id}/message",
                            {"value": "male"})
    assert status == 403

    status, verified = _post(f"/api/chat-application/{app_id}/otp/verify", {
        "verification_id": otp["verification_id"],
        "otp_code": otp["demo_otp_code"],
    })
    assert status == 200, verified
    assert verified["step"]["id"] == "gender"  # continues where it stopped

    reply = _answer(app_id, "male")
    assert reply["step"]["id"] == "occupation"

    # journey records the stop and the continuation
    status, state = _get(f"/api/chat-application/{app_id}?resume_code={resume_code}")
    assert status == 200
    stages = [j["stage"] for j in state["journey"]]
    assert "stopped" in stages
    assert "continued" in stages


def test_validation_and_security_failures():
    status, body = _post("/api/chat-application/start", {})
    assert status == 201
    app_id = body["application_id"]

    # invalid name then invalid email are rejected with broker guidance
    status, bad = _post(f"/api/chat-application/{app_id}/message", {"value": "X"})
    assert status == 400 and "error" in bad
    _answer(app_id, "Test User")
    status, bad = _post(f"/api/chat-application/{app_id}/message",
                        {"value": "not-an-email"})
    assert status == 400 and "error" in bad
    _answer(app_id, "chat.applicant.fail@example.com")
    _answer(app_id, "+1-555-0102")

    # media and finalize are refused before OTP verification
    status, blocked = _post(f"/api/chat-application/{app_id}/media", {
        "kind": "voice", "name": "note.wav", "mime_type": "audio/wav",
        "data_b64": base64.b64encode(b"x").decode("ascii")})
    assert status == 403
    status, blocked = _post(f"/api/chat-application/{app_id}/finalize", {})
    assert status == 403

    # wrong OTP is rejected
    status, otp = _post(f"/api/chat-application/{app_id}/otp/request", {})
    assert status == 200
    status, bad = _post(f"/api/chat-application/{app_id}/otp/verify", {
        "verification_id": otp["verification_id"], "otp_code": "000000"})
    assert status == 400
    assert bad.get("error_code") in ("INVALID_OTP", "MAX_ATTEMPTS")

    # right OTP works, then premature finalize reports missing steps
    status, ok = _post(f"/api/chat-application/{app_id}/otp/verify", {
        "verification_id": otp["verification_id"],
        "otp_code": otp["demo_otp_code"]})
    assert status == 200, ok
    status, early = _post(f"/api/chat-application/{app_id}/finalize", {})
    assert status == 409
    assert "missing" in early["error"].lower() or "Still missing" in early["error"]

    # invalid media payloads
    status, bad = _post(f"/api/chat-application/{app_id}/media", {
        "kind": "hologram", "name": "x", "mime_type": "x", "data_b64": "aGk="})
    assert status == 400
    status, bad = _post(f"/api/chat-application/{app_id}/media", {
        "kind": "voice", "name": "x", "mime_type": "audio/wav",
        "data_b64": "@@not-base64@@"})
    assert status == 400

    # invalid card is rejected with guidance
    _answer(app_id, "1992-07-21")
    _answer(app_id, "other")
    _answer(app_id, "Pilot")
    _answer(app_id, 180)
    _answer(app_id, 80)
    _answer(app_id, "no")
    _answer(app_id, "no")
    _answer(app_id, "no")
    _answer(app_id, "no")
    _answer(app_id, ["none"])
    _answer(app_id, "none")
    _answer(app_id, 250000)
    _answer(app_id, "15")
    _answer(app_id, "skip")
    _answer(app_id, "annual")
    status, bad = _post(f"/api/chat-application/{app_id}/message", {
        "value": {"card_number": "1234", "cardholder_name": "T",
                  "expiry_month": "1", "expiry_year": "2031", "cvv": "12"}})
    assert status == 400 and "error" in bad

    # state access without resume code or staff session is refused
    status, denied = _get(f"/api/chat-application/{app_id}")
    assert status == 403
    status, denied = _get(f"/api/chat-application/{app_id}?resume_code=WRONG")
    assert status == 403

    # unknown application
    status, missing = _post("/api/chat-application/CHAPP-00000000000000-XXXXXX/message",
                            {"value": "hi"})
    assert status == 404


def test_staff_funnel_endpoint():
    # unauthenticated access refused
    status, denied = _get("/api/chat-application/admin/funnel")
    assert status == 403

    status, login = _post("/api/login", {"username": "admin", "password": "admin123"})
    assert status == 200, login
    token = login["token"]

    # seed one session so the funnel has data
    _post("/api/chat-application/start", {})

    status, funnel = _get("/api/chat-application/admin/funnel", token=token)
    assert status == 200, funnel
    assert funnel["total_sessions"] >= 1
    assert "stage_counts" in funnel
    assert funnel["stage_counts"]["started"] >= 1
    assert isinstance(funnel["sessions"], list)
    # staff can open a session without a resume code
    app_id = funnel["sessions"][-1]["application_id"]
    status, state = _get(f"/api/chat-application/{app_id}", token=token)
    assert status == 200
    assert "resume_code" in state  # staff view exposes the code for support


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
