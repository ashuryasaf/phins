"""Resume codes reopen the same apply-chat file after the process restarts.

The code, the answer chain, and the drawn signature live in a checksummed
document. A checksum that does not match is not resumed. A policy created
before a crash is adopted, so filing does not run a second time.
"""

import hashlib
import json
from pathlib import Path

import pytest

from services.chat_answer_revisions import verify_revisions
from services.chat_application_service import ChatPolicyApplicationService
from services.chat_session_store import canonical_text


_SIG_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mP8z8BQz0AEYBxVSF+"
    "FABJADveWkH6oAAAAAElFTkSuQmCC"
)


def _signature_payload(name="Dana Levi", id_number="123456782"):
    return {
        "name": name,
        "nationality": "Israel",
        "id_number": id_number,
        "signature_data": _SIG_PNG,
        "method": "drawn_canvas",
    }


def _service(directory: Path) -> ChatPolicyApplicationService:
    return ChatPolicyApplicationService(sessions_dir=str(directory))


def _answer(svc, app_id, value):
    result = svc.submit_answer(app_id, value)
    assert result.get("ok"), result
    return result


def _write_envelope(directory: Path, session: dict, *, checksum: str = "") -> Path:
    text = canonical_text({"resume_code": session["resume_code"], "session": session})
    digest = checksum or hashlib.sha256(text.encode("utf-8")).hexdigest()
    body = json.dumps(
        {"checksum": digest, "payload_json": text},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    path = directory / f"{session['id']}.json"
    path.write_text(body, encoding="utf-8")
    return path


def _minimal(app_id, code, *, updated_at="2026-10-25T10:00:00+00:00", name="Dana Levi"):
    return {
        "id": app_id,
        "resume_code": code,
        "created_at": "2026-10-25T09:00:00+00:00",
        "updated_at": updated_at,
        "status": "in_progress",
        "channel": "web_chat",
        "language": "en",
        "contact": {"name": name, "email": "dana@example.com", "phone": None,
                    "country": None, "city": None},
        "email_verified": False,
        "phone_verified": False,
        "answers": {"name": name, "email": "dana@example.com"},
        "revisions": [],
        "revision_head": None,
        "media": [],
        "transcript": [],
        "journey": [],
        "finalizing": False,
        "customer_id": None,
        "submission": None,
    }


def test_resume_code_reopens_the_same_application_after_restart(tmp_path):
    first = _service(tmp_path)
    started = first.start_session()
    app_id = started["application_id"]
    code = started["resume_code"]
    assert code.startswith("PHINS-CHAT-")
    _answer(first, app_id, "Dana Levi")
    _answer(first, app_id, "dana.restart@example.com")
    chain = list(first._sessions[app_id]["revisions"])
    ok, reason = verify_revisions(chain)
    assert ok, reason

    restarted = _service(tmp_path)
    resumed = restarted.resume_session(code, "dana.restart@example.com")
    assert resumed["ok"] is True
    assert resumed["application_id"] == app_id
    session = restarted._sessions[app_id]
    assert session["resume_code"] == code
    assert session["contact"]["name"] == "Dana Levi"
    assert session["contact"]["email"] == "dana.restart@example.com"
    assert session["answers"]["name"] == "Dana Levi"
    again_ok, again_reason = verify_revisions(session["revisions"])
    assert again_ok, again_reason
    assert session["revision_head"] == first._sessions[app_id]["revision_head"]

    missed = restarted.resume_session(code, "someone.else@example.com")
    assert missed["ok"] is False
    assert missed["status_code"] == 404


def test_resume_before_email_uses_the_same_code(tmp_path):
    first = _service(tmp_path)
    started = first.start_session()
    code = started["resume_code"]
    restarted = _service(tmp_path)
    resumed = restarted.resume_session(code, "")
    assert resumed["ok"] is True
    assert resumed["application_id"] == started["application_id"]
    assert restarted._sessions[started["application_id"]]["resume_code"] == code


def test_drawn_signature_and_revision_chain_survive_restart(tmp_path):
    first = _service(tmp_path)
    started = first.start_session()
    app_id = started["application_id"]
    code = started["resume_code"]
    _answer(first, app_id, "Dana Levi")
    _answer(first, app_id, "dana.sign@example.com")
    session = first._sessions[app_id]
    session["answers"]["signature"] = {
        "name": "Dana Levi",
        "nationality": "Israel",
        "id_number": "123456782",
        "signature_data": _SIG_PNG,
        "image_sha256": "abc123",
        "method": "drawn_canvas",
    }
    paused = first.pause_session(app_id)
    assert paused["ok"] is True
    assert paused["resume_code"] == code

    restarted = _service(tmp_path)
    loaded = restarted._sessions[app_id]
    assert loaded["resume_code"] == code
    assert loaded["answers"]["signature"]["signature_data"] == _SIG_PNG
    assert loaded["answers"]["signature"]["image_sha256"] == "abc123"
    ok, reason = verify_revisions(loaded["revisions"])
    assert ok, reason
    resumed = restarted.resume_session(code, "dana.sign@example.com")
    assert resumed["application_id"] == app_id


def test_checksum_mismatch_is_not_resumed_and_the_file_stays(tmp_path):
    session = _minimal("CHAPP-TAMPER-1", "PHINS-CHAT-TAMPER01")
    path = _write_envelope(tmp_path, session)
    raw = path.read_text(encoding="utf-8")
    path.write_text(raw.replace("Dana Levi", "Dana Cohen"), encoding="utf-8")

    restarted = _service(tmp_path)
    assert restarted._sessions == {}
    assert restarted._resume_index == {}
    missed = restarted.resume_session("PHINS-CHAT-TAMPER01", "dana@example.com")
    assert missed["status_code"] == 404
    assert path.is_file()
    assert "Dana Cohen" in path.read_text(encoding="utf-8")


def test_duplicate_resume_code_keeps_the_newer_session(tmp_path):
    code = "PHINS-CHAT-DUP00001"
    older = _minimal("CHAPP-DUP-OLD", code, updated_at="2026-10-25T10:00:00+00:00", name="Older Name")
    newer = _minimal("CHAPP-DUP-NEW", code, updated_at="2026-10-25T11:00:00+00:00", name="Newer Name")
    _write_envelope(tmp_path, older)
    _write_envelope(tmp_path, newer)

    restarted = _service(tmp_path)
    assert set(restarted._sessions) == {"CHAPP-DUP-NEW"}
    assert restarted._resume_index[code] == "CHAPP-DUP-NEW"
    assert restarted._sessions["CHAPP-DUP-NEW"]["contact"]["name"] == "Newer Name"
    assert (tmp_path / "CHAPP-DUP-OLD.json").is_file()


def test_filed_session_reloads_without_the_national_id_or_drawing(tmp_path):
    first = _service(tmp_path)
    started = first.start_session()
    app_id = started["application_id"]
    code = started["resume_code"]
    _answer(first, app_id, "Dana Levi")
    _answer(first, app_id, "dana.filed@example.com")
    session = first._sessions[app_id]
    session["answers"]["signature"] = {
        "name": "Dana Levi",
        "nationality": "Israel",
        "id_number": "123456782",
        "signature_data": _SIG_PNG,
        "method": "drawn_canvas",
    }
    filed = first.mark_submitted(
        app_id,
        policy_id="POL-FILED-1",
        underwriting_id="UW-FILED-1",
        customer_id="CUST-FILED-1",
        checksum="abc",
    )
    assert filed["ok"] is True

    restarted = _service(tmp_path)
    loaded = restarted._sessions[app_id]
    assert loaded["resume_code"] == code
    assert loaded["status"] == "submitted"
    assert loaded["submission"]["policy_id"] == "POL-FILED-1"
    blob = json.dumps(loaded["answers"])
    assert "123456782" not in blob
    assert _SIG_PNG not in blob
    assert loaded["answers"].get("signature_data") is None
    assert "signature_data" not in (loaded["answers"].get("signature") or {})
    assert "id_number" not in (loaded["answers"].get("signature") or {})
    assert loaded["answers"]["national_id_last4"] == "6782"
    assert loaded["answers"]["national_id_hash"]
    resumed = restarted.resume_session(code, "dana.filed@example.com")
    assert resumed["status"] == "submitted"
    assert resumed["submission"]["policy_id"] == "POL-FILED-1"


def test_crashed_finalize_is_not_stuck_in_flight(tmp_path):
    session = _minimal("CHAPP-FLIGHT-1", "PHINS-CHAT-FLIGHT01")
    session["finalizing"] = True
    session["status"] = "paused"
    _write_envelope(tmp_path, session)

    restarted = _service(tmp_path)
    loaded = restarted._sessions["CHAPP-FLIGHT-1"]
    assert loaded["finalizing"] is False
    stored = json.loads((tmp_path / "CHAPP-FLIGHT-1.json").read_text(encoding="utf-8"))
    payload = json.loads(stored["payload_json"])
    assert payload["session"]["finalizing"] is False
    actual = hashlib.sha256(stored["payload_json"].encode("utf-8")).hexdigest()
    assert actual == stored["checksum"]


def test_existing_chat_policy_ignores_referrals_without_a_policy():
    import web_portal.server as portal
    from web_portal.api_chat_application import existing_chat_policy

    portal.UNDERWRITING_APPLICATIONS.clear()
    portal.UNDERWRITING_APPLICATIONS["UW-ADL"] = {
        "id": "UW-ADL",
        "chat_application_id": "CHAPP-ADOPT-1",
        "source": "chat_adl_referral",
        "policy_id": None,
    }
    assert existing_chat_policy("CHAPP-ADOPT-1") is None
    portal.UNDERWRITING_APPLICATIONS["UW-REAL"] = {
        "id": "UW-REAL",
        "chat_application_id": "CHAPP-ADOPT-1",
        "source": "chat",
        "policy_id": "POL-ADOPT-1",
        "customer_id": "CUST-ADOPT",
        "status": "pending",
        "annual_premium": 1200,
        "monthly_premium": 100,
    }
    found = existing_chat_policy("CHAPP-ADOPT-1")
    assert found["policy_id"] == "POL-ADOPT-1"
    assert found["underwriting_id"] == "UW-REAL"
    assert existing_chat_policy("CHAPP-OTHER") is None


def _complete(svc, app_id):
    for value in ("Dana Levi", "dana.adopt@example.com", "+1-555-0100"):
        _answer(svc, app_id, value)
    svc._sessions[app_id]["email_verified"] = True
    for value in (
        "Israel",
        "Tel Aviv",
        "1990-05-14",
        "female",
        "Architect",
        168,
        62,
        "no",
        "no",
        "no",
        "no",
        ["none"],
        "none",
        "none",
        "full",
        500000,
        "20",
        "none",
        "skip",
        "monthly",
        {
            "card_number": "5555 5555 5555 4444",
            "cardholder_name": "DANA LEVI",
            "expiry_month": "12",
            "expiry_year": "2031",
            "cvv": "123",
        },
        "yes",
        "agree",
        _signature_payload(),
    ):
        _answer(svc, app_id, value)


def test_restart_adopts_the_policy_instead_of_filing_again(tmp_path, monkeypatch):
    import web_portal.api_chat_application as chat_api
    import web_portal.server as portal

    first = _service(tmp_path)
    started = first.start_session()
    app_id = started["application_id"]
    code = started["resume_code"]
    _complete(first, app_id)
    prepared = first.prepare_finalize(app_id)
    assert prepared["ok"] is True, prepared
    assert first._sessions[app_id]["finalizing"] is True

    portal.UNDERWRITING_APPLICATIONS.clear()
    portal.UNDERWRITING_APPLICATIONS["UW-ADL"] = {
        "id": "UW-ADL",
        "chat_application_id": app_id,
        "source": "chat_adl_referral",
        "policy_id": None,
    }
    portal.UNDERWRITING_APPLICATIONS["UW-ADOPT"] = {
        "id": "UW-ADOPT",
        "chat_application_id": app_id,
        "source": "chat",
        "policy_id": "POL-ADOPT-9",
        "customer_id": "CUST-ADOPT-9",
        "status": "pending",
        "annual_premium": 2400,
        "monthly_premium": 200,
    }

    restarted = _service(tmp_path)
    assert restarted._sessions[app_id]["finalizing"] is False
    assert restarted._sessions[app_id]["resume_code"] == code

    def _refuse_loopback(*_args, **_kwargs):
        raise AssertionError("a second policy create must not run")

    monkeypatch.setattr(chat_api, "_loopback_policy_create", _refuse_loopback)
    monkeypatch.setattr(
        "services.chat_application_service.get_chat_application_service",
        lambda: restarted,
    )
    status, body = chat_api._handle_finalize(app_id, handler=None)
    assert status == 201, body
    assert body["policy"]["id"] == "POL-ADOPT-9"
    assert body["underwriting"]["id"] == "UW-ADOPT"
    filed = restarted._sessions[app_id]
    assert filed["status"] == "submitted"
    assert filed["submission"]["policy_id"] == "POL-ADOPT-9"
    assert filed["finalizing"] is False
    assert "123456782" not in json.dumps(filed["answers"])
    assert "5555555555554444" not in json.dumps(filed["answers"])

    again = _service(tmp_path)
    reopened = again.resume_session(code, "dana.adopt@example.com")
    assert reopened["status"] == "submitted"
    assert reopened["submission"]["policy_id"] == "POL-ADOPT-9"
    assert again._sessions[app_id]["resume_code"] == code
