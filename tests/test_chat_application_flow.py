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


def _request(method: str, path: str, data=None, token=None, extra_headers=None):
    url = _base() + path
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {}


def _post(path, data=None, token=None, extra_headers=None):
    return _request("POST", path, data or {}, token, extra_headers)


def _get(path, token=None):
    return _request("GET", path, None, token)


_SIG_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mP8z8BQz0AEYBxVSF+"
    "FABJADveWkH6oAAAAAElFTkSuQmCC"
)


def _signature_payload(name, id_number="123456782"):
    """Drawn signature panel payload (name + Israeli ID + PNG)."""
    return {
        "name": name,
        "id_number": id_number,
        "signature_data": _SIG_PNG,
        "method": "drawn_canvas",
    }


def _answer(app_id, value, expect_status=200, resume_code=None):
    payload = {"value": value}
    if resume_code is not None:
        payload["resume_code"] = resume_code
    status, body = _post(f"/api/chat-application/{app_id}/message", payload)
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

    _answer(app_id, name, resume_code=resume_code)
    _answer(app_id, email, resume_code=resume_code)
    reply = _answer(app_id, phone, resume_code=resume_code)
    assert reply.get("otp_required") is True

    status, otp = _post(f"/api/chat-application/{app_id}/otp/request",
                        {"resume_code": resume_code})
    assert status == 200, otp
    assert "demo_otp_code" in otp, "test mode must expose the demo OTP"

    status, verified = _post(f"/api/chat-application/{app_id}/otp/verify", {
        "verification_id": otp["verification_id"],
        "otp_code": otp["demo_otp_code"],
        "resume_code": resume_code,
    })
    assert status == 200, verified
    assert verified["step"]["id"] == "dob"
    return app_id, resume_code


def _complete_questionnaire(app_id, resume_code, medical=False):
    _answer(app_id, "1990-05-14", resume_code=resume_code)   # dob
    _answer(app_id, "female", resume_code=resume_code)       # gender
    _answer(app_id, "Architect", resume_code=resume_code)    # occupation
    _answer(app_id, 168, resume_code=resume_code)            # height
    _answer(app_id, 62, resume_code=resume_code)             # weight
    _answer(app_id, "no", resume_code=resume_code)           # tobacco
    if medical:
        _answer(app_id, "yes", resume_code=resume_code)      # medical_conditions
        _answer(app_id, "type 2 diabetes, high blood pressure", resume_code=resume_code)
    else:
        _answer(app_id, "no", resume_code=resume_code)
    _answer(app_id, "no", resume_code=resume_code)           # surgery
    _answer(app_id, "no", resume_code=resume_code)           # hazardous
    body = _answer(app_id, ["none"], resume_code=resume_code)  # family_history
    _answer(app_id, "none", resume_code=resume_code)           # medications
    _answer(app_id, "none", resume_code=resume_code)           # prior_disclosure
    reply = _answer(app_id, "full", resume_code=resume_code)   # daily_function -> assessment
    assert reply.get("assessment"), reply
    return reply


def test_full_chat_application_happy_path():
    app_id, resume_code = _start_and_verify(
        "chat.applicant.happy@example.com", invite_code="TESTCODE2026")

    assessment_reply = _complete_questionnaire(app_id, resume_code)
    assessment = assessment_reply["assessment"]
    assert assessment["risk_category"] in (
        "very_low", "low", "moderate", "elevated", "high", "very_high")
    assert assessment["recommendation_type"]
    assert 0 < assessment["confidence"] <= 1

    _answer(app_id, 500000, resume_code=resume_code)         # coverage_amount
    _answer(app_id, "20", resume_code=resume_code)           # coverage_years
    quote_reply = _answer(app_id, "none", resume_code=resume_code)  # savings_addon -> quote
    quote = quote_reply["quote"]
    assert quote["monthly"] > 0
    assert quote["annual"] > 0
    assert quote["pricing_source"] in ("pricing_kernel", "flat_fallback")

    # voice note attachment
    voice = base64.b64encode(b"RIFF....fake-wav-bytes....").decode("ascii")
    status, media = _post(f"/api/chat-application/{app_id}/media", {
        "kind": "voice", "name": "note.wav", "mime_type": "audio/wav",
        "data_b64": voice, "duration_seconds": 3.5, "resume_code": resume_code,
    })
    assert status == 200, media
    assert media["media"]["sha256"]
    assert "data_b64" not in media["media"]

    _answer(app_id, "done", resume_code=resume_code)         # media_offer
    _answer(app_id, "monthly", resume_code=resume_code)      # billing_frequency
    _answer(app_id, {                                        # payment_card
        "card_number": "5555 5555 5555 4444",
        "cardholder_name": "DANA LEVI",
        "expiry_month": "12", "expiry_year": "2031", "cvv": "123",
    }, resume_code=resume_code)
    _answer(app_id, "yes", resume_code=resume_code)          # auto_pay
    consent_reply = _answer(app_id, "agree", resume_code=resume_code)  # consent
    assert consent_reply.get("ready_to_finalize") is not True
    assert consent_reply.get("step", {}).get("id") == "signature"
    sign_reply = _answer(
        app_id, _signature_payload("Dana Levi"), resume_code=resume_code
    )  # signature panel
    assert sign_reply.get("ready_to_finalize") is True

    status, result = _post(f"/api/chat-application/{app_id}/finalize",
                           {"resume_code": resume_code})
    assert status == 201, result
    assert result["policy"]["id"].startswith("POL")
    assert result["underwriting"]["id"]
    assert result["payload_checksum"]
    assert result["submission"]["policy_id"] == result["policy"]["id"]

    # double submission is refused
    status, dup = _post(f"/api/chat-application/{app_id}/finalize",
                        {"resume_code": resume_code})
    assert status == 409
    assert "error" in dup

    # PCI DSS: the full PAN and CVV must not linger on the session after submit
    from services.chat_application_service import get_chat_application_service
    session = get_chat_application_service()._sessions.get(app_id)
    card = (session or {}).get("answers", {}).get("payment_card")
    assert isinstance(card, dict), card
    assert not card.get("card_number")
    assert not card.get("cvv")
    assert card.get("card_last4") == "4444"
    assert session["answers"].get("signature_name") == "Dana Levi"
    assert session["answers"].get("id_number") == "123456782"
    assert session["answers"].get("signature_image_sha256")
    assert session["answers"].get("signature_data") is None  # redacted after submit
    assert session["answers"].get("prior_disclosure")

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
                     "media_attached", "payment_captured", "disclosure_captured",
                     "signed", "submitted"):
        assert expected in stages, f"missing journey stage {expected}: {stages}"
    assert journey["ledger_event_count"] > 0
    types = {e["event_type"] for e in journey["ledger_events"]}
    assert "chat.message" in types
    assert any(t.startswith("journey.") for t in types)
    assert all(e.get("entry_hash") for e in journey["ledger_events"])


def test_medical_follow_up_and_risk_loading():
    app_id, resume_code = _start_and_verify("chat.applicant.medical@example.com")
    reply = _complete_questionnaire(app_id, resume_code, medical=True)
    assessment = reply["assessment"]
    assert "type 2 diabetes" in " ".join(assessment["conditions_considered"])
    # diabetes + hypertension must not come back "very_low"
    assert assessment["risk_category"] != "very_low"


def test_pause_and_resume_with_otp_rechallenge():
    email = "chat.applicant.resume@example.com"
    app_id, resume_code = _start_and_verify(email)
    _answer(app_id, "1985-03-02", resume_code=resume_code)   # dob before pausing

    status, paused = _post(f"/api/chat-application/{app_id}/pause",
                           {"resume_code": resume_code})
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
                            {"value": "male", "resume_code": resume_code})
    assert status == 403

    status, verified = _post(f"/api/chat-application/{app_id}/otp/verify", {
        "verification_id": otp["verification_id"],
        "otp_code": otp["demo_otp_code"],
        "resume_code": resume_code,
    })
    assert status == 200, verified
    assert verified["step"]["id"] == "gender"  # continues where it stopped
    # secure resume restores the prior conversation once identity is re-proven
    assert verified.get("transcript"), verified
    assert any(m.get("kind") == "question" for m in verified["transcript"])

    reply = _answer(app_id, "male", resume_code=resume_code)
    assert reply["step"]["id"] == "occupation"

    # journey records the stop and the continuation
    status, state = _get(f"/api/chat-application/{app_id}?resume_code={resume_code}")
    assert status == 200
    stages = [j["stage"] for j in state["journey"]]
    assert "stopped" in stages
    assert "continued" in stages


def test_early_pause_resumes_before_email_is_captured():
    # Pausing before the email step still hands out a resume code, so the code
    # alone must be enough to reopen the (pre-contact) session.
    status, body = _post("/api/chat-application/start", {})
    assert status == 201, body
    app_id = body["application_id"]
    resume_code = body["resume_code"]

    _answer(app_id, "Early Riser", resume_code=resume_code)  # name only
    status, paused = _post(f"/api/chat-application/{app_id}/pause",
                           {"resume_code": resume_code})
    assert status == 200, paused

    # no email on file yet -> the resume code alone reopens the session
    status, resumed = _post("/api/chat-application/resume",
                            {"resume_code": resume_code, "email": ""})
    assert status == 200, resumed
    assert resumed["status"] == "in_progress"
    assert resumed["step"]["id"] == "email"

    # and the applicant can keep going
    _answer(app_id, "chat.applicant.early@example.com", resume_code=resume_code)


def test_validation_and_security_failures():
    status, body = _post("/api/chat-application/start", {})
    assert status == 201
    app_id = body["application_id"]
    resume_code = body["resume_code"]

    # mutating routes require the resume code (IDOR guard): the guessable
    # application id alone must not drive someone else's application.
    status, denied = _post(f"/api/chat-application/{app_id}/message",
                           {"value": "Test User"})
    assert status == 403, denied
    status, denied = _post(f"/api/chat-application/{app_id}/message",
                           {"value": "Test User", "resume_code": "WRONG"})
    assert status == 403, denied

    # invalid name then invalid email are rejected with broker guidance
    status, bad = _post(f"/api/chat-application/{app_id}/message",
                        {"value": "X", "resume_code": resume_code})
    assert status == 400 and "error" in bad
    _answer(app_id, "Test User", resume_code=resume_code)
    status, bad = _post(f"/api/chat-application/{app_id}/message",
                        {"value": "not-an-email", "resume_code": resume_code})
    assert status == 400 and "error" in bad
    _answer(app_id, "chat.applicant.fail@example.com", resume_code=resume_code)
    _answer(app_id, "+1-555-0102", resume_code=resume_code)

    # media and finalize are refused before OTP verification
    status, blocked = _post(f"/api/chat-application/{app_id}/media", {
        "kind": "voice", "name": "note.wav", "mime_type": "audio/wav",
        "data_b64": base64.b64encode(b"x").decode("ascii"),
        "resume_code": resume_code})
    assert status == 403
    status, blocked = _post(f"/api/chat-application/{app_id}/finalize",
                            {"resume_code": resume_code})
    assert status == 403

    # wrong OTP is rejected
    status, otp = _post(f"/api/chat-application/{app_id}/otp/request",
                        {"resume_code": resume_code})
    assert status == 200
    status, bad = _post(f"/api/chat-application/{app_id}/otp/verify", {
        "verification_id": otp["verification_id"], "otp_code": "000000",
        "resume_code": resume_code})
    assert status == 400
    assert bad.get("error_code") in ("INVALID_OTP", "MAX_ATTEMPTS")

    # right OTP works, then premature finalize reports missing steps
    status, ok = _post(f"/api/chat-application/{app_id}/otp/verify", {
        "verification_id": otp["verification_id"],
        "otp_code": otp["demo_otp_code"], "resume_code": resume_code})
    assert status == 200, ok
    status, early = _post(f"/api/chat-application/{app_id}/finalize",
                          {"resume_code": resume_code})
    assert status == 409
    assert "missing" in early["error"].lower() or "Still missing" in early["error"]

    # invalid media payloads
    status, bad = _post(f"/api/chat-application/{app_id}/media", {
        "kind": "hologram", "name": "x", "mime_type": "x", "data_b64": "aGk=",
        "resume_code": resume_code})
    assert status == 400
    status, bad = _post(f"/api/chat-application/{app_id}/media", {
        "kind": "voice", "name": "x", "mime_type": "audio/wav",
        "data_b64": "@@not-base64@@", "resume_code": resume_code})
    assert status == 400

    # invalid card is rejected with guidance
    _answer(app_id, "1992-07-21", resume_code=resume_code)
    _answer(app_id, "other", resume_code=resume_code)
    _answer(app_id, "Pilot", resume_code=resume_code)
    _answer(app_id, 180, resume_code=resume_code)
    _answer(app_id, 80, resume_code=resume_code)
    _answer(app_id, "no", resume_code=resume_code)
    _answer(app_id, "no", resume_code=resume_code)
    _answer(app_id, "no", resume_code=resume_code)
    _answer(app_id, "no", resume_code=resume_code)
    _answer(app_id, ["none"], resume_code=resume_code)
    _answer(app_id, "none", resume_code=resume_code)
    _answer(app_id, "none", resume_code=resume_code)  # prior_disclosure
    _answer(app_id, "full", resume_code=resume_code)         # daily_function
    _answer(app_id, 250000, resume_code=resume_code)
    _answer(app_id, "15", resume_code=resume_code)
    _answer(app_id, "none", resume_code=resume_code)         # savings_addon
    _answer(app_id, "skip", resume_code=resume_code)
    _answer(app_id, "annual", resume_code=resume_code)
    status, bad = _post(f"/api/chat-application/{app_id}/message", {
        "value": {"card_number": "1234", "cardholder_name": "T",
                  "expiry_month": "1", "expiry_year": "2031", "cvv": "12"},
        "resume_code": resume_code})
    assert status == 400 and "error" in bad

    # state access without resume code or staff session is refused
    status, denied = _get(f"/api/chat-application/{app_id}")
    assert status == 403
    status, denied = _get(f"/api/chat-application/{app_id}?resume_code=WRONG")
    assert status == 403

    # unknown application (no valid resume code) is refused
    status, missing = _post("/api/chat-application/CHAPP-00000000000000-XXXXXX/message",
                            {"value": "hi"})
    assert status in (403, 404)


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


def _start_with_contact(email, phone="+1-555-0166"):
    """Start a session and complete contact capture (stop at the OTP gate)."""
    status, body = _post("/api/chat-application/start", {})
    assert status == 201, body
    app_id = body["application_id"]
    resume_code = body["resume_code"]
    _answer(app_id, "Noa Barak", resume_code=resume_code)
    _answer(app_id, email, resume_code=resume_code)
    reply = _answer(app_id, phone, resume_code=resume_code)
    assert reply.get("otp_required") is True
    return app_id, resume_code


def test_otp_delivery_failure_is_retryable_and_keeps_session_consistent():
    """Production-like delivery outage: clear 503, session stays workable."""
    from unittest.mock import patch

    app_id, resume_code = _start_with_contact("chat.applicant.outage@example.com")

    # Simulate production: a real provider is configured (so the pre-flight
    # passes) but the send itself fails.
    with patch("web_portal.api_extensions._demo_otp_exposure_allowed",
               return_value=False), \
         patch("services.notification_service.get_active_email_provider_type",
               return_value="infobip"), \
         patch("web_portal.api_extensions._send_otp_via_channel",
               return_value=(False, "simulated provider outage")):
        status, failed = _post(f"/api/chat-application/{app_id}/otp/request",
                               {"resume_code": resume_code})
    assert status == 503, failed
    assert failed["error_code"] == "OTP_DELIVERY_FAILED"
    assert failed["retryable"] is True
    assert "resume code" in failed["error"]

    # Simulate production with NO provider at all: pre-flight refuses before
    # minting a verification (keeps OTP counters/state clean).
    with patch("web_portal.api_extensions._demo_otp_exposure_allowed",
               return_value=False), \
         patch("services.notification_service.get_active_email_provider_type",
               return_value="noop"):
        status, blocked = _post(f"/api/chat-application/{app_id}/otp/request",
                                {"resume_code": resume_code})
    assert status == 503, blocked
    assert blocked["error_code"] == "OTP_DELIVERY_UNAVAILABLE"
    assert blocked["retryable"] is True

    # Recovery: once delivery works again the same session verifies and
    # continues exactly where it stopped.
    status, otp = _post(f"/api/chat-application/{app_id}/otp/request",
                        {"resume_code": resume_code})
    assert status == 200, otp
    status, verified = _post(f"/api/chat-application/{app_id}/otp/verify", {
        "verification_id": otp["verification_id"],
        "otp_code": otp["demo_otp_code"],
        "resume_code": resume_code,
    })
    assert status == 200, verified
    assert verified["step"]["id"] == "dob"


def test_resume_otp_failure_rolls_back_reverify_state():
    """A failed re-challenge delivery must not brick or silently unlock."""
    from unittest.mock import patch

    email = "chat.applicant.rechallenge@example.com"
    app_id, resume_code = _start_and_verify(email)
    _answer(app_id, "1988-11-30", resume_code=resume_code)  # dob answered
    status, paused = _post(f"/api/chat-application/{app_id}/pause",
                           {"resume_code": resume_code})
    assert status == 200, paused

    # Resume while OTP delivery is down -> clear retryable failure.
    with patch("web_portal.api_extensions._demo_otp_exposure_allowed",
               return_value=False), \
         patch("services.notification_service.get_active_email_provider_type",
               return_value="infobip"), \
         patch("web_portal.api_extensions._send_otp_via_channel",
               return_value=(False, "simulated provider outage")):
        status, failed = _post("/api/chat-application/resume",
                               {"resume_code": resume_code, "email": email})
    assert status == 503, failed
    assert failed["error_code"] == "OTP_DELIVERY_FAILED"

    # Consistency: answers stay blocked (no silent unlock)...
    status, blocked = _post(f"/api/chat-application/{app_id}/message",
                            {"value": "male", "resume_code": resume_code})
    assert status == 403, blocked

    # ...and the NEXT resume still demands the OTP re-challenge (the failed
    # attempt must not have downgraded the session to "unverified").
    status, resumed = _post("/api/chat-application/resume",
                            {"resume_code": resume_code, "email": email})
    assert status == 200, resumed
    assert resumed["status"] == "pending_reverify"
    assert resumed["otp_required"] is True
    otp = resumed["otp"]
    assert "demo_otp_code" in otp

    status, verified = _post(f"/api/chat-application/{app_id}/otp/verify", {
        "verification_id": otp["verification_id"],
        "otp_code": otp["demo_otp_code"],
        "resume_code": resume_code,
    })
    assert status == 200, verified
    assert verified["step"]["id"] == "gender"  # continues where it stopped


def test_start_rate_limit_uses_forwarded_client_ip():
    """Behind the edge proxy, limits must key on X-Forwarded-For, not the
    shared socket address - otherwise a few applicants lock the whole site."""
    from unittest.mock import patch

    import web_portal.api_chat_application as chat_api

    chat_api._start_tracker.clear()
    try:
        with patch.object(chat_api, "_MAX_STARTS_PER_IP_PER_HOUR", 2):
            hdr_a = {"X-Forwarded-For": "203.0.113.50"}
            hdr_b = {"X-Forwarded-For": "203.0.113.51, 100.64.0.9"}
            status, _ = _post("/api/chat-application/start", {}, extra_headers=hdr_a)
            assert status == 201
            status, _ = _post("/api/chat-application/start", {}, extra_headers=hdr_a)
            assert status == 201
            # Same forwarded applicant is now over the limit...
            status, limited = _post("/api/chat-application/start", {}, extra_headers=hdr_a)
            assert status == 429, limited
            # ...but a different applicant behind the same proxy still works.
            status, _ = _post("/api/chat-application/start", {}, extra_headers=hdr_b)
            assert status == 201
    finally:
        chat_api._start_tracker.clear()


def test_hebrew_start_keeps_ascii_resume_code():
    status, body = _post("/api/chat-application/start", {"language": "he"})
    assert status == 201, body
    assert body["resume_code"].startswith("PHINS-CHAT-")
    assert body.get("language") == "he"
    # Resume code itself stays ASCII; surrounding copy is Hebrew.
    texts = " ".join(m.get("text") or "" for m in body["messages"])
    assert body["resume_code"] in texts
    assert any("קוד" in (m.get("text") or "") for m in body["messages"])
    assert body["step"]["id"] == "name"
    prompt = body["step"]["prompt"] or ""
    assert "בואו" in prompt
    assert "שמך" in prompt


def test_signature_requires_id_and_drawn_canvas():
    """Drawn signature panel rejects typed-only and invalid IDs."""
    from services.chat_application_service import _validate_signature
    session = {"contact": {"name": "Dana Levi"}, "answers": {}}
    ok, err = _validate_signature("Dana Levi", session)
    assert ok is False
    ok, err = _validate_signature(
        {"name": "Dana Levi", "id_number": "123456789", "signature_data": _SIG_PNG},
        session,
    )
    assert ok is False  # bad checksum
    ok, cleaned = _validate_signature(_signature_payload("Dana Levi"), session)
    assert ok is True
    assert cleaned["id_number"] == "123456782"
    assert cleaned["image_sha256"]
    assert cleaned["method"] == "drawn_canvas"


def test_uw_decision_auto_answer_and_notification():
    """Approve appends a Phin auto-answer; reject covered via service helper."""
    app_id, resume_code = _start_and_verify("chat.uw.decision@example.com")
    _complete_questionnaire(app_id, resume_code)
    _answer(app_id, 500000, resume_code=resume_code)
    _answer(app_id, "20", resume_code=resume_code)
    _answer(app_id, "none", resume_code=resume_code)
    _answer(app_id, "skip", resume_code=resume_code)
    _answer(app_id, "monthly", resume_code=resume_code)
    _answer(app_id, {
        "card_number": "5555 5555 5555 4444",
        "cardholder_name": "DANA LEVI",
        "expiry_month": "12", "expiry_year": "2031", "cvv": "123",
    }, resume_code=resume_code)
    _answer(app_id, "yes", resume_code=resume_code)
    _answer(app_id, "agree", resume_code=resume_code)
    _answer(app_id, _signature_payload("Dana Levi"), resume_code=resume_code)
    status, result = _post(f"/api/chat-application/{app_id}/finalize",
                           {"resume_code": resume_code})
    assert status == 201, result
    uw_id = result["underwriting"]["id"]

    status, approved = _post("/api/underwriting/approve", {
        "id": uw_id,
        "premium_adjustment": 10,
        "notes": "Modest loading for demo",
        "approved_by": "test_uw",
    })
    assert status == 200, approved
    assert (approved.get("application") or {}).get("chat_auto_answer", {}).get("decision") == "approved"

    status, state = _get(f"/api/chat-application/{app_id}?resume_code={resume_code}")
    assert status == 200, state
    assert state.get("uw_decision", {}).get("decision") == "approved"
    assert any(m.get("kind") == "uw_decision" for m in state.get("transcript") or [])

    # Reject auto-answer without a second full HTTP finalize (rate limits).
    from services.chat_application_service import get_chat_application_service
    svc = get_chat_application_service()
    reject_id = f"{app_id}-REJECT-CLONE"
    src = svc._sessions[app_id]
    svc._sessions[reject_id] = {
        **{k: v for k, v in src.items() if k not in ("transcript", "journey", "uw_decision")},
        "id": reject_id,
        "transcript": list(src.get("transcript") or []),
        "journey": list(src.get("journey") or []),
        "uw_decision": None,
        "contact": dict(src.get("contact") or {}),
        "answers": dict(src.get("answers") or {}),
        "language": "en",
    }
    rejected = svc.post_underwriting_decision(
        reject_id,
        decision="rejected",
        underwriting_id="UW-TEST-REJECT",
        reason="Outside guidelines",
    )
    assert rejected.get("ok") is True
    assert rejected["uw_decision"]["decision"] == "rejected"
    assert any(m.get("kind") == "uw_decision" for m in rejected.get("messages") or [])


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
