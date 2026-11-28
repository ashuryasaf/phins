"""Recorded chat-answer edits and the staff-only process review.

Applicants may replace any committed answer. The replacement is an
append-only checksum chain. Card numbers, CVVs, and full national IDs stay
out of that chain and out of the staff review. Prior files are matched at
read time by email, name, and identity hash.
"""

import hashlib
import json
import os
import urllib.error
import urllib.request

import pytest


def _base():
    return os.environ.get("TEST_BASE_URL", "http://localhost:8000").rstrip("/")


def _request(method, path, data=None, token=None):
    url = _base() + path
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
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


def _login(username, password):
    status, body = _post("/api/login", {"username": username, "password": password})
    assert status == 200, body
    return body["token"]


def _answer(app_id, value, resume_code, token=None, expect=200):
    status, body = _post(
        f"/api/chat-application/{app_id}/message",
        {"value": value, "resume_code": resume_code},
        token,
    )
    assert status == expect, body
    return body


def _edit(app_id, step, value, resume_code=None, token=None):
    payload = {"step": step, "value": value}
    if resume_code is not None:
        payload["resume_code"] = resume_code
    return _post(f"/api/chat-application/{app_id}/edit", payload, token)


def _start(email=None):
    status, body = _post("/api/chat-application/start", {})
    assert status == 201, body
    app_id = body["application_id"]
    resume = body["resume_code"]
    if email is None:
        return app_id, resume
    _answer(app_id, "Nora Quill", resume)
    _answer(app_id, email, resume)
    reply = _answer(app_id, "+1-555-0199", resume)
    assert reply.get("otp_required") is True
    status, otp = _post(
        f"/api/chat-application/{app_id}/otp/request",
        {"resume_code": resume},
    )
    assert status == 200, otp
    status, verified = _post(
        f"/api/chat-application/{app_id}/otp/verify",
        {
            "verification_id": otp["verification_id"],
            "otp_code": otp["demo_otp_code"],
            "resume_code": resume,
        },
    )
    assert status == 200, verified
    return app_id, resume


_SIG_PNG = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mP8z8BQz0AEYBxVSF+"
    "FABJADveWkH6oAAAAAElFTkSuQmCC"
)
_PAN = "5555555555554444"
_NATIONAL_ID = "123456782"


def _signature(name="Nora Quillstone"):
    return {
        "name": name,
        "nationality": "Israel",
        "id_number": _NATIONAL_ID,
        "signature_data": _SIG_PNG,
        "method": "drawn_canvas",
    }


def _card(holder="NORA QUILLSTONE"):
    return {
        "card_number": "5555 5555 5555 4444",
        "cardholder_name": holder,
        "expiry_month": "12",
        "expiry_year": "2031",
        "cvv": "123",
    }


def _ledger(app_id, event_type):
    import web_portal.server as portal

    found = []
    for entry in list(getattr(portal, "TRANSACTION_LEDGER", {}).values()):
        if str(entry.get("event_type") or "") != event_type:
            continue
        payload = entry.get("payload") or {}
        if entry.get("entity_id") == app_id or payload.get("application_id") == app_id:
            found.append(entry)
    return found


def _session(app_id):
    from services.chat_application_service import get_chat_application_service

    return get_chat_application_service()._sessions[app_id]


# ---------------------------------------------------------------------------
# Chain, redaction, prior matches
# ---------------------------------------------------------------------------


def test_revision_chain_links_and_redacts_card_and_identity():
    from services.chat_answer_revisions import (
        append_revision,
        history_gap,
        intention_shifts,
        latest_seal,
        redact_answer,
        verify_revisions,
    )
    from services.customer_identity_service import hash_national_id, normalize_national_id

    code, normalized = normalize_national_id(_NATIONAL_ID, "Israel")
    keyed = hash_national_id(code, normalized)
    assert keyed != hashlib.sha256(_NATIONAL_ID.encode("utf-8")).hexdigest()

    card = redact_answer("payment_card", _card())
    signature = redact_answer("signature", _signature())
    card_blob = json.dumps(card)
    signature_blob = json.dumps(signature)
    assert card["card_last4"] == "4444"
    assert _PAN not in card_blob
    assert "cvv" not in card
    assert signature["national_id_last4"] == "6782"
    assert signature["national_id_hash"] == keyed
    assert _NATIONAL_ID not in signature_blob
    assert "signature_data" not in signature

    revisions = []
    append_revision(
        revisions, step_id="payment_card", action="set", at="2026-01-01T00:00:00Z",
        current=_card(), current_display="Card ending 4444",
    )
    append_revision(
        revisions, step_id="payment_card", action="edit", at="2026-01-02T00:00:00Z",
        previous=_card(), current=_card("NORA QUILL"),
        previous_display="Card ending 4444", current_display="Card ending 4444",
    )
    append_revision(
        revisions, step_id="signature", action="set", at="2026-01-03T00:00:00Z",
        current=_signature(), current_display="Signed: Nora Quillstone · ID ••••6782",
    )
    ok, reason = verify_revisions(revisions)
    assert ok, reason
    blob = json.dumps(revisions)
    assert _PAN not in blob
    assert _NATIONAL_ID not in blob
    assert "cvv" not in blob
    assert revisions[0]["checksum"] == revisions[1]["prev_checksum"]

    revisions[1]["checksum"] = "0" * 64
    ok, reason = verify_revisions(revisions)
    assert ok is False
    assert reason == "Answer history failed its integrity check."

    intact = []
    append_revision(
        intact, step_id="name", action="set", at="2026-01-01T00:00:00Z",
        current="Nora Quill", current_display="Nora Quill",
    )
    append_revision(
        intact, step_id="name", action="edit", at="2026-01-02T00:00:00Z",
        previous="Nora Quill", current="Nora Quillstone",
        previous_display="Nora Quill", current_display="Nora Quillstone",
    )
    shifts = intention_shifts(intact)
    assert shifts[0]["from"] == "Nora Quill"
    assert shifts[0]["to"] == "Nora Quillstone"
    assert shifts[0]["category"] == "identity"
    withdrawn = []
    append_revision(
        withdrawn, step_id="conditions_list", action="set", at="2026-01-01T00:00:00Z",
        current="diabetes", current_display="diabetes",
    )
    append_revision(
        withdrawn, step_id="conditions_list", action="withdrawn", at="2026-01-02T00:00:00Z",
        previous="diabetes", previous_display="diabetes",
    )
    pulled = intention_shifts(withdrawn)
    assert pulled[0]["withdrawn"] is True
    assert pulled[0]["from"] == "diabetes"
    assert pulled[0]["to"] is None
    gap = history_gap(intact, {"name": "Nora Quillstone", "email": "a@b.c"}, ["name", "email"])
    assert gap.startswith("Answer history is missing a recorded revision")
    assert "email" in gap
    flattened = {
        "event_type": "chat.process_sealed",
        "entity_id": "CHAPP-1",
        "application_id": "CHAPP-1",
        "seal": {"application_id": "CHAPP-1", "integrity_ok": True, "revisions": intact},
    }
    assert latest_seal([flattened], "CHAPP-1", "chat.process_sealed")["integrity_ok"] is True
    nested = {
        "event_type": "chat.process_sealed",
        "entity_id": "CHAPP-1",
        "payload": {"application_id": "CHAPP-1", "seal": {"integrity_ok": False}},
    }
    assert latest_seal([nested], "CHAPP-1", "chat.process_sealed")["integrity_ok"] is False


def test_prior_matches_trigger_on_email_name_and_id_separately():
    from services.chat_answer_revisions import match_prior

    email_only = match_prior(
        email="nora.prior@example.com",
        name="Someone Else",
        national_id_hash=None,
        customer_id="CUST-SELF",
        applications={
            "UW-EMAIL": {
                "id": "UW-EMAIL",
                "customer_email": "Nora.Prior@example.com",
                "customer_name": "Other Human",
                "status": "pending",
                "submitted_date": "2024-01-01",
            },
        },
        policies={}, claims={}, customers={},
    )
    assert [item["id"] for item in email_only] == ["UW-EMAIL"]
    assert email_only[0]["triggered_by"] == ["email"]

    name_only = match_prior(
        email="nobody@example.com",
        name="Nora Quillstone",
        national_id_hash=None,
        customer_id=None,
        applications={},
        policies={
            "POL-NAME": {
                "id": "POL-NAME",
                "customer_name": "nora  quillstone",
                "customer_email": "different@example.com",
                "status": "active",
            },
        },
        claims={}, customers={},
    )
    assert name_only[0]["triggered_by"] == ["name"]

    # A one-token name is not distinctive enough to attach prior files.
    short = match_prior(
        email=None, name="Nora", national_id_hash=None, customer_id=None,
        applications={"UW-X": {"id": "UW-X", "customer_name": "Nora", "status": "pending"}},
        policies={}, claims={}, customers={},
    )
    assert short == []

    id_hash = "abc123identity"
    by_id = match_prior(
        email="fresh@example.com",
        name="Brand New",
        national_id_hash=id_hash,
        customer_id="CUST-SELF",
        applications={
            "UW-HASH": {
                "id": "UW-HASH",
                "customer_email": "old@example.com",
                "customer_name": "Old Name",
                "national_id_hash": id_hash,
                "status": "closed",
            },
            "UW-LINKED": {
                "id": "UW-LINKED",
                "customer_id": "CUST-OTHER",
                "customer_email": "linked@example.com",
                "customer_name": "Linked Only",
                "status": "pending",
            },
        },
        policies={}, claims={},
        customers={"CUST-OTHER": {"id": "CUST-OTHER", "national_id_hash": id_hash}},
        exclude_ids=["UW-SELF"],
    )
    found = {item["id"]: item["triggered_by"] for item in by_id}
    assert found["UW-HASH"] == ["id"]
    assert found["UW-LINKED"] == ["id"]


# ---------------------------------------------------------------------------
# Policy chat over HTTP
# ---------------------------------------------------------------------------


def test_policy_edit_keeps_the_previous_answer_and_refuses_a_broken_chain():
    _get("/api/health")
    app_id, resume = _start()
    _answer(app_id, "Nora Quill", resume)

    status, edited = _edit(app_id, "name", "Nora Quillstone", resume)
    assert status == 200, edited
    assert edited["edited"] is True
    assert edited["revision_head"]
    name_row = next(item for item in edited["editable"] if item["id"] == "name")
    assert name_row["display"] == "Nora Quillstone"
    assert name_row["edit_count"] == 1
    assert name_row["category"] == "identity"

    session = _session(app_id)
    name_revs = [rev for rev in session["revisions"] if rev["step_id"] == "name"]
    assert name_revs[0]["action"] == "set"
    assert name_revs[0]["current_display"] == "Nora Quill"
    assert name_revs[1]["action"] == "edit"
    assert name_revs[1]["previous_display"] == "Nora Quill"
    assert name_revs[1]["current_display"] == "Nora Quillstone"
    assert _ledger(app_id, "chat.answer_revised")

    before = len(session["revisions"])
    status, same = _edit(app_id, "name", "Nora Quillstone", resume)
    assert status == 200, same
    assert same.get("unchanged") is True
    assert len(_session(app_id)["revisions"]) == before

    status, rejected = _edit(app_id, "name", "X", resume)
    assert status == 400, rejected
    assert _session(app_id)["rejected_edits"]
    assert len(_session(app_id)["revisions"]) == before
    assert _ledger(app_id, "chat.answer_revision_rejected")

    status, staff_edit = _edit(app_id, "name", "Staff Rewrite", token=_login("admin", "admin123"))
    assert status == 403, staff_edit
    assert "resume code" in staff_edit["error"].lower()

    status, hidden = _get(f"/api/chat-application/{app_id}/process-review?resume_code={resume}")
    assert status == 403, hidden

    admin = _login("admin", "admin123")
    status, review = _get(f"/api/chat-application/{app_id}/process-review", admin)
    assert status == 200, review
    assert review["secret"] is True
    assert review["source"] == "session"
    assert review["quick"]["personal"]["name"] == "Nora Quillstone"
    assert review["quick"]["edits"]["identity"] == 1
    assert review["full"]["intention"][0]["from"] == "Nora Quill"
    assert review["full"]["intention"][0]["to"] == "Nora Quillstone"
    assert review["full"]["integrity"]["ok"] is True

    _session(app_id)["revisions"][-1]["checksum"] = "f" * 64
    status, blocked = _edit(app_id, "name", "Nora Other", resume)
    assert status == 409, blocked
    assert blocked["error"] == "Answer history failed its integrity check."


def test_missing_revision_blocks_finalize():
    from services.chat_application_service import get_chat_application_service

    _get("/api/health")
    app_id, resume = _start("gap.chat@example.com")
    svc = get_chat_application_service()
    session = svc._sessions[app_id]
    for _ in range(3):
        for step in svc._steps_for(session):
            session["answers"].setdefault(step["id"], "placeholder")
    status, body = _post(
        f"/api/chat-application/{app_id}/finalize",
        {"resume_code": resume},
    )
    assert status == 409, body
    assert "missing a recorded revision" in body["error"]


def test_health_billing_and_identity_edits_reach_the_staff_review():
    _get("/api/health")
    email = "nora.review.chat@example.com"
    app_id, resume = _start(email)
    status, renamed = _edit(app_id, "name", "Nora Quillstone", resume)
    assert status == 200, renamed

    _answer(app_id, "Israel", resume)
    _answer(app_id, "Tel Aviv", resume)
    _answer(app_id, "1990-05-14", resume)
    _answer(app_id, "female", resume)
    _answer(app_id, "Architect", resume)
    _answer(app_id, 168, resume)
    _answer(app_id, 62, resume)
    _answer(app_id, "no", resume)  # tobacco
    _answer(app_id, "yes", resume)  # medical
    _answer(app_id, "type 2 diabetes, high blood pressure", resume)
    _answer(app_id, "no", resume)  # surgery
    _answer(app_id, "no", resume)  # hazardous
    _answer(app_id, ["none"], resume)
    _answer(app_id, "none", resume)
    _answer(app_id, "none", resume)  # prior disclosure
    assessed = _answer(app_id, "full", resume)
    assert assessed.get("assessment"), assessed

    status, health_edit = _edit(app_id, "medical_conditions", "no", resume)
    assert status == 200, health_edit
    session = _session(app_id)
    assert session["answers"]["medical_conditions"] == "no"
    assert "conditions_list" not in session["answers"]
    assert "prior_disclosure" not in session["answers"]
    withdrawn = {
        rev["step_id"] for rev in session["revisions"] if rev["action"] == "withdrawn"
    }
    assert {"conditions_list", "prior_disclosure"} <= withdrawn
    assert health_edit.get("step", {}).get("id") == "prior_disclosure"

    _answer(app_id, "none", resume)
    _answer(app_id, 500000, resume)
    _answer(app_id, "20", resume)
    quoted = _answer(app_id, "none", resume)
    assert quoted.get("quote"), quoted
    _answer(app_id, "skip", resume)
    _answer(app_id, "monthly", resume)
    _answer(app_id, _card("DANA LEVI"), resume)
    status, card_edit = _edit(app_id, "payment_card", _card("NORA QUILLSTONE"), resume)
    assert status == 200, card_edit
    assert card_edit.get("edited") is True
    _answer(app_id, "yes", resume)
    _answer(app_id, "agree", resume)
    signed = _answer(app_id, _signature(), resume)
    assert signed.get("ready_to_finalize") is True

    session = _session(app_id)
    stored = json.dumps(session["revisions"])
    assert _PAN not in stored
    assert _NATIONAL_ID not in stored
    assert "cvv" not in stored
    card_rev = [rev for rev in session["revisions"] if rev["step_id"] == "payment_card"]
    assert card_rev[-1]["action"] == "edit"
    assert card_rev[-1]["category"] == "billing"
    assert "4444" in card_rev[-1]["current_display"]

    import web_portal.server as portal
    from services.customer_identity_service import hash_national_id, normalize_national_id

    code, normalized = normalize_national_id(_NATIONAL_ID, "Israel")
    id_hash = hash_national_id(code, normalized)
    portal.UNDERWRITING_APPLICATIONS["UW-PRIOR-EMAIL"] = {
        "id": "UW-PRIOR-EMAIL",
        "customer_email": email,
        "customer_name": "Different Person",
        "status": "pending",
        "submitted_date": "2024-01-01",
    }
    portal.UNDERWRITING_APPLICATIONS["UW-PRIOR-NAME"] = {
        "id": "UW-PRIOR-NAME",
        "customer_email": "someone.else.prior@example.com",
        "customer_name": "Nora Quillstone",
        "status": "approved",
        "submitted_date": "2025-02-02",
    }
    portal.CUSTOMERS["CUST-PRIOR-ID"] = {
        "id": "CUST-PRIOR-ID",
        "name": "Old Nora",
        "email": "old.nora.prior@example.com",
        "national_id_hash": id_hash,
        "status": "active",
    }
    portal.UNDERWRITING_APPLICATIONS["UW-PRIOR-ID"] = {
        "id": "UW-PRIOR-ID",
        "customer_id": "CUST-PRIOR-ID",
        "customer_email": "old.nora.prior@example.com",
        "customer_name": "Old Nora",
        "status": "closed",
        "submitted_date": "2023-03-03",
    }

    underwriter = _login("underwriter", "under123")
    status, review = _get(f"/api/chat-application/{app_id}/process-review", underwriter)
    assert status == 200, review
    quick = review["quick"]
    assert quick["personal"]["name"] == "Nora Quillstone"
    assert quick["personal"]["email"] == email
    assert quick["personal"]["national_id_last4"] == "6782"
    assert "national_id_hash" not in quick["personal"]
    assert quick["health"]["medical_conditions"] == "no"
    assert quick["billing"]["card_last4"] == "4444"
    assert quick["billing"]["cardholder_name"] == "NORA QUILLSTONE"
    assert quick["edits"]["identity"] >= 1
    assert quick["edits"]["health"] >= 1
    assert quick["edits"]["billing"] >= 1
    assert quick["edits"]["last_edited_at"]
    triggers = set(quick["prior"]["triggered_by"])
    assert {"email", "name", "id"} <= triggers
    prior_ids = {item["id"] for item in quick["prior"]["items"]}
    assert {"UW-PRIOR-EMAIL", "UW-PRIOR-NAME", "UW-PRIOR-ID"} <= prior_ids

    review_blob = json.dumps(review)
    assert _PAN not in review_blob
    assert _NATIONAL_ID not in review_blob
    assert "cvv" not in review_blob
    intention = {row["step_id"]: row for row in review["full"]["intention"]}
    assert intention["name"]["from"] == "Nora Quill"
    assert intention["medical_conditions"]["from"] == "yes"
    assert intention["medical_conditions"]["to"] == "no"
    assert intention["conditions_list"]["withdrawn"] is True

    status, filed = _post(
        f"/api/chat-application/{app_id}/finalize",
        {"resume_code": resume},
    )
    assert status == 201, filed
    uw_id = filed["underwriting"]["id"]
    assert portal.UNDERWRITING_APPLICATIONS[uw_id]["chat_process_head"]
    assert portal.UNDERWRITING_APPLICATIONS[uw_id]["chat_application_id"] == app_id
    seals = _ledger(app_id, "chat.process_sealed")
    assert seals
    # The platform ledger flattens the event payload onto the row.
    seal = seals[-1].get("seal") or (seals[-1].get("payload") or {}).get("seal")
    assert seal["integrity_ok"] is True
    assert "prior" not in seal
    seal_blob = json.dumps(seal)
    assert "UW-PRIOR-EMAIL" not in seal_blob
    assert _PAN not in seal_blob
    assert _NATIONAL_ID not in seal_blob

    seal_copy = json.dumps(seal, sort_keys=True, default=str)
    revisions_copy = json.dumps(_session(app_id)["revisions"], sort_keys=True, default=str)
    ledger_n = len(portal.TRANSACTION_LEDGER)
    customer_id = filed["customer"]["id"]
    customer_copy = json.dumps(portal.CUSTOMERS[customer_id], sort_keys=True, default=str)
    status, narrowed = _get(
        f"/api/chat-application/{app_id}/process-review"
        "?view=quick&sections=identity,health,ai&ask=Explain%20the%20name%20edit&narrate=1",
        underwriter,
    )
    assert status == 200, narrowed
    assert narrowed["controls"]["view"] == "quick"
    assert narrowed["controls"]["narrate"] is True
    assert narrowed["quick"]["personal"]["name"] == "Nora Quillstone"
    assert "billing" not in narrowed["quick"]
    assert "full" not in narrowed
    report = narrowed["ai_report"]
    assert report["decides"] is False
    assert report["advisory"] is True
    assert report["needs_review"] is True
    assert report["mode"] == "deterministic"
    assert report["fallback_reason"] == "llm_unavailable"
    assert report["prompt_id"]
    assert report["prompt_sha256"]
    assert report["schema_id"]
    narrowed_blob = json.dumps(narrowed)
    assert _PAN not in narrowed_blob
    assert _NATIONAL_ID not in narrowed_blob
    assert json.dumps(seal, sort_keys=True, default=str) == seal_copy
    assert json.dumps(_session(app_id)["revisions"], sort_keys=True, default=str) == revisions_copy
    assert len(portal.TRANSACTION_LEDGER) == ledger_n
    assert json.dumps(portal.CUSTOMERS[customer_id], sort_keys=True, default=str) == customer_copy

    del get_sessions()[app_id]
    status, recovered = _get(f"/api/chat-application/{app_id}/process-review", underwriter)
    assert status == 200, recovered
    assert recovered["source"] == "ledger"
    assert recovered["quick"]["personal"]["name"] == "Nora Quillstone"
    assert recovered["quick"]["billing"]["card_last4"] == "4444"
    assert recovered["full"]["integrity"]["ok"] is True
    assert {"email", "name", "id"} <= set(recovered["quick"]["prior"]["triggered_by"])


def get_sessions():
    from services.chat_application_service import get_chat_application_service

    return get_chat_application_service()._sessions


# ---------------------------------------------------------------------------
# Claims chat
# ---------------------------------------------------------------------------


def _seed_customer(customer_id, email, name="Dana Levi"):
    import web_portal.server as portal

    portal.CUSTOMERS[customer_id] = {
        "id": customer_id,
        "name": name,
        "email": email,
        "phone": "+1-555-0100",
        "status": "active",
    }
    policy_id = f"POL-{customer_id}"
    portal.POLICIES[policy_id] = {
        "id": policy_id,
        "customer_id": customer_id,
        "customer_name": name,
        "customer_email": email,
        "type": "life",
        "status": "active",
        "coverage_amount": 500000,
        "start_date": "2020-01-01",
    }
    return policy_id


def _customer_token(customer_id, email):
    from datetime import datetime, timedelta

    import web_portal.server as portal

    return portal._create_signed_token(
        email, "customer", customer_id, datetime.now() + timedelta(hours=2))


def test_claim_edits_record_rebind_and_stay_staff_only():
    _get("/api/health")
    email = "dana.edit.claim@example.com"
    customer_id = "CUST-EDIT-CLAIM"
    _seed_customer(customer_id, email)
    other_email = "other.edit.claim@example.com"
    _seed_customer("CUST-EDIT-CLAIM-B", other_email, name="Ori Ben Ami")

    token = _customer_token(customer_id, email)
    status, started = _post("/api/claims-chat/start", {"channel": "web_chat"}, token)
    assert status == 201, started
    app_id = started["application_id"]
    assert started["step"]["id"] == "profile"

    status, answered = _post(
        f"/api/claims-chat/{app_id}/message",
        {"value": {"name": "Dana Levi", "email": email, "phone": "+1-555-0100"}},
        token,
    )
    assert status == 200, answered
    status, edited = _post(
        f"/api/claims-chat/{app_id}/edit",
        {"step": "profile", "value": {"name": "Dana Levi Edited", "email": email, "phone": "+1-555-0100"}},
        token,
    )
    assert status == 200, edited
    assert edited["edited"] is True
    assert _ledger(app_id, "claims_chat.answer_revised")

    adjuster = _login("claims_adjuster", "claims123")
    status, staff_blocked = _post(
        f"/api/claims-chat/{app_id}/edit",
        {"step": "profile", "value": {"name": "Rewritten", "email": email, "phone": "+1-555-0100"}},
        adjuster,
    )
    assert status == 403, staff_blocked

    import web_portal.server as portal
    portal.CLAIMS["CLM-PRIOR-EMAIL"] = {
        "id": "CLM-PRIOR-EMAIL",
        "contact_email": email,
        "customer_name": "Someone Else",
        "status": "closed",
        "filed_date": "2022-04-04",
    }
    status, review = _get(f"/api/claims-chat/{app_id}/process-review", adjuster)
    assert status == 200, review
    assert review["kind"] == "claim"
    assert review["quick"]["personal"]["name"] == "Dana Levi Edited"
    assert review["quick"]["edits"]["identity"] >= 1
    assert any(item["id"] == "CLM-PRIOR-EMAIL" for item in review["quick"]["prior"]["items"])
    status, applicant = _get(f"/api/claims-chat/{app_id}/process-review", token)
    assert status == 403, applicant
    status, anonymous = _get(f"/api/claims-chat/{app_id}/process-review")
    assert status == 403, anonymous

    status, external = _post("/api/claims-chat/start", {"channel": "external"})
    assert status == 201, external
    ext_id = external["application_id"]
    ext_resume = external["resume_code"]
    _claim_answer = lambda value, expect=200: _post(
        f"/api/claims-chat/{ext_id}/message",
        {"value": value, "resume_code": ext_resume},
    )
    status, bound = _claim_answer(email)
    assert status == 200, bound
    status, profiled = _claim_answer(
        {"name": "Dana Levi", "email": email, "phone": "+1-555-0100"})
    assert status == 200, profiled
    status, rebound = _post(
        f"/api/claims-chat/{ext_id}/edit",
        {"step": "claimant", "value": other_email, "resume_code": ext_resume},
    )
    assert status == 200, rebound
    from services.claims_chat_service import get_claims_chat_service

    claim_session = get_claims_chat_service()._sessions[ext_id]
    assert claim_session["customer_id"] == "CUST-EDIT-CLAIM-B"
    assert "profile" not in claim_session["answers"]
    assert any(
        rev["step_id"] == "profile" and rev["action"] == "withdrawn"
        for rev in claim_session["revisions"]
    )
    from services.chat_answer_revisions import verify_revisions

    ok, reason = verify_revisions(claim_session["revisions"])
    assert ok, reason


def test_chat_pages_expose_the_edit_control():
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "web_portal" / "static"
    for name in ("apply-chat.html", "file-a-claim.html", "claims-chat.html"):
        text = (root / name).read_text(encoding="utf-8")
        assert 'id="edit-answers-btn"' in text
        assert "Edit an answer" in text
    assert "submitEdit" in (root / "apply-chat.js").read_text(encoding="utf-8")
    assert "submitEdit" in (root / "claims-chat.js").read_text(encoding="utf-8")
    underwriter = (root / "underwriter-dashboard.html").read_text(encoding="utf-8")
    claims = (root / "claims-adjuster-dashboard.html").read_text(encoding="utf-8")
    assert "/chat-process-review.html?id=" in underwriter
    assert "chat_application_id" in underwriter
    assert "/chat-process-review.html?id=" in claims
    assert "claims_chat_id" in claims

    status, page = _request_text("/apply-chat.html")
    assert status == 200
    assert "Edit an answer" in page
    status, claim_page = _request_text("/file-a-claim.html")
    assert status == 200
    assert "Edit an answer" in claim_page
    status, review_page = _request_text("/chat-process-review.html")
    assert status == 200
    assert "Chat process review" in review_page
    assert 'id="ask"' in review_page
    assert 'id="narrate"' in review_page
    assert 'name="section"' in review_page
    assert "Opening it does not change the file." in review_page


def _request_text(path):
    url = _base() + path
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Controls, AI note, withheld chain, memory and database seals
# ---------------------------------------------------------------------------


def test_broken_chain_is_withheld_and_not_repaired():
    _get("/api/health")
    app_id, resume = _start()
    _answer(app_id, "Nora Quill", resume)
    session = _session(app_id)
    intact = json.dumps(session["revisions"], sort_keys=True)
    session["revisions"][-1]["checksum"] = "a" * 64
    broken = json.dumps(session["revisions"], sort_keys=True)
    assert broken != intact
    admin = _login("admin", "admin123")
    status, review = _get(f"/api/chat-application/{app_id}/process-review", admin)
    assert status == 200, review
    assert review["withheld"] is True
    assert review["integrity"]["ok"] is False
    assert review["integrity"]["reason"] == "Answer history failed its integrity check."
    assert "quick" not in review
    assert "full" not in review
    assert "Nora Quill" not in json.dumps(review)
    assert json.dumps(session["revisions"], sort_keys=True) == broken
    status, edited = _edit(app_id, "name", "Nora Other", resume)
    assert status == 409, edited
    assert json.dumps(session["revisions"], sort_keys=True) == broken


def test_ai_report_drops_invented_figures_and_invalid_schema():
    from services.chat_answer_revisions import (
        append_revision,
        build_review,
        explain_sealed_review,
    )
    from services.llm_providers import LLMUnavailableError

    revisions = []
    append_revision(
        revisions, step_id="name", action="set", at="2026-01-01T00:00:00Z",
        current="Nora Quill", current_display="Nora Quill",
    )
    review = build_review(
        kind="policy_application",
        application_id="CHAPP-AI",
        status="submitted",
        subject={"name": "Nora Quill", "email": "nora.ai@example.com", "health": {}, "billing": {}, "coverage": {}},
        revisions=revisions,
        books={"applications": {}, "policies": {}, "claims": {}, "customers": {}},
    )
    name_before = review["quick"]["personal"]["name"]

    class Recorder:
        def __init__(self, result):
            self.result = result
            self.calls = 0

        def structured_completion(self, system, user, schema):
            self.calls += 1
            if isinstance(self.result, Exception):
                raise self.result
            return self.result

    silent = Recorder({"summary_text": "Coverage is 99999."})
    quiet = explain_sealed_review(review, ask="What about 99999?", narrate=False, provider=silent)
    assert silent.calls == 0
    assert quiet["mode"] == "deterministic"
    assert quiet["decides"] is False
    assert "99999" not in quiet["summary_text"]
    assert quiet["prompt_id"]
    assert quiet["prompt_sha256"]
    assert quiet["schema_id"]

    invented = Recorder({
        "summary_text": "The premium is 99999.",
        "key_points": [{"point": "Nothing else"}],
        "review_flags": [],
        "needs_review": True,
    })
    dropped = explain_sealed_review(review, narrate=True, provider=invented)
    assert invented.calls == 1
    assert dropped["fallback_reason"] == "narrative_introduced_numbers"
    assert dropped["mode"] == "deterministic"
    assert dropped["rejected_numbers"] == ["99999"]
    assert "99999" not in dropped["summary_text"]
    assert dropped["decides"] is False

    pan = Recorder({
        "summary_text": "Card 5555555555554444 was used.",
        "key_points": [],
        "review_flags": [],
        "needs_review": True,
    })
    hidden = explain_sealed_review(review, narrate=True, provider=pan)
    assert hidden["fallback_reason"] == "narrative_introduced_numbers"
    assert "5555555555554444" not in json.dumps(hidden)
    assert "rejected_numbers" not in hidden

    invalid = Recorder({"summary_text": "Hello"})
    rejected = explain_sealed_review(review, narrate=True, provider=invalid)
    assert rejected["fallback_reason"] == "schema_invalid"
    assert rejected["mode"] == "deterministic"
    assert rejected["summary_text"]

    offline = Recorder(LLMUnavailableError("down"))
    fallback = explain_sealed_review(review, narrate=True, provider=offline)
    assert fallback["fallback_reason"] == "llm_unavailable"
    assert fallback["mode"] == "deterministic"

    accepted = Recorder({
        "summary_text": "The sealed file is on record.",
        "key_points": [{"point": "The chain is intact.", "evidence_index": 0}],
        "review_flags": ["Human review required"],
        "needs_review": True,
    })
    used = explain_sealed_review(review, narrate=True, provider=accepted)
    assert used["mode"] == "llm"
    assert used["summary_text"] == "The sealed file is on record."
    assert used["decides"] is False
    assert used["needs_review"] is True
    assert review["quick"]["personal"]["name"] == name_before


def test_prior_section_stays_on_the_requested_view():
    from services.chat_answer_revisions import (
        FULL_REVIEW_SECTIONS,
        QUICK_REVIEW_SECTIONS,
        build_review,
        present_process_review,
    )

    review = build_review(
        kind="policy_application",
        application_id="CHAPP-PRIOR-VIEW",
        status="submitted",
        subject={
            "name": "Nora Quill",
            "email": "nora.prior.view@example.com",
            "health": {},
            "billing": {"claimed_amount": 2500},
            "coverage": {},
        },
        revisions=[],
        books={"applications": {}, "policies": {}, "claims": {}, "customers": {}},
    )
    quick_sections = list(QUICK_REVIEW_SECTIONS) + ["ai"]
    full_sections = list(FULL_REVIEW_SECTIONS) + ["ai"]

    quick = present_process_review(
        review, view="quick", sections=quick_sections, narrate=False,
    )
    assert "full" not in quick
    assert quick["quick"]["prior"]["count"] == 0
    assert "personal" in quick["quick"]

    full = present_process_review(
        review, view="full", sections=full_sections, narrate=False,
    )
    assert "quick" not in full
    assert full["full"]["prior"] == []
    assert "contradictions" in full["full"]
    assert "integrity" in full["full"]

    both = present_process_review(
        review, view="both", sections=quick_sections + full_sections, narrate=False,
    )
    assert both["quick"]["prior"]["count"] == 0
    assert both["full"]["prior"] == []

    mixed = present_process_review(
        review, view="full", sections=["billing", "prior"], narrate=False,
    )
    assert mixed["quick"]["billing"]["claimed_amount"] == 2500
    assert "prior" not in mixed["quick"]
    assert mixed["full"]["prior"] == []


def test_database_seal_is_read_without_writing_memory():
    from services.chat_answer_revisions import append_revision, build_seal, serve_process_review

    revisions = []
    append_revision(
        revisions, step_id="name", action="set", at="2026-01-01T00:00:00Z",
        current="Nora Quill", current_display="Nora Quill",
    )
    session = {
        "id": "CHAPP-DB-1",
        "status": "submitted",
        "contact": {"name": "Nora Quill", "email": "nora.db@example.com"},
        "answers": {"name": "Nora Quill"},
        "revisions": revisions,
        "rejected_edits": [],
    }
    seal = build_seal(session, kind="policy_application")
    seal_blob = json.dumps(seal, sort_keys=True)
    memory = [{
        "event_type": "chat.process_sealed",
        "entity_id": "CHAPP-DB-1",
        "application_id": "CHAPP-DB-1",
        "sequence_no": 3,
        "seal": json.loads(seal_blob),
    }]
    memory[0]["seal"]["revisions"][-1]["checksum"] = "b" * 64
    memory_blob = json.dumps(memory, sort_keys=True)
    good = json.loads(seal_blob)
    db_rows = [{
        "event_type": "chat.process_sealed",
        "entity_id": "CHAPP-DB-1",
        "sequence_no": 9,
        "payload": {"application_id": "CHAPP-DB-1", "seal": good},
    }]
    db_blob = json.dumps(db_rows, sort_keys=True)
    missing = {"ok": False, "status_code": 404, "error": "Application not found"}
    status, withheld = serve_process_review(
        missing, "CHAPP-DB-1", "chat.process_sealed", None,
        memory_entries=memory, db_entries=db_rows,
    )
    assert status == 200, withheld
    assert withheld["withheld"] is True
    assert withheld["source"] == "ledger"
    assert "Nora Quill" not in json.dumps(withheld)
    assert json.dumps(memory, sort_keys=True) == memory_blob
    assert json.dumps(db_rows, sort_keys=True) == db_blob

    empty_memory = []
    status, recovered = serve_process_review(
        missing, "CHAPP-DB-1", "chat.process_sealed",
        {"view": "both", "sections": "identity,ai"},
        memory_entries=empty_memory, db_entries=db_rows,
    )
    assert status == 200, recovered
    assert recovered["source"] == "ledger"
    assert recovered["quick"]["personal"]["name"] == "Nora Quill"
    assert recovered["ai_report"]["decides"] is False
    assert "full" not in recovered
    assert empty_memory == []
    assert json.dumps(db_rows, sort_keys=True) == db_blob
    assert json.dumps(good, sort_keys=True) == seal_blob

    claim_revisions = []
    append_revision(
        claim_revisions, step_id="profile", action="set", at="2026-02-01T00:00:00Z",
        current={"name": "Dana Levi", "email": "dana.db@example.com", "phone": "+1-555-0100"},
        current_display="Dana Levi · dana.db@example.com",
    )
    claim_session = {
        "id": "CLCHAT-DB-1",
        "status": "submitted",
        "contact": {"name": "Dana Levi", "email": "dana.db@example.com", "phone": "+1-555-0100"},
        "answers": {"claimed_amount": 2500, "claim_type": "accident"},
        "revisions": claim_revisions,
        "rejected_edits": [],
    }
    claim_seal = build_seal(claim_session, kind="claim")
    claim_blob = json.dumps(claim_seal, sort_keys=True)
    claim_rows = [{
        "event_type": "claims_chat.process_sealed",
        "entity_id": "CLCHAT-DB-1",
        "sequence_no": 4,
        "payload": {"application_id": "CLCHAT-DB-1", "seal": json.loads(claim_blob)},
    }]
    status, claim_review = serve_process_review(
        {"ok": False, "status_code": 404, "error": "Claim chat not found"},
        "CLCHAT-DB-1", "claims_chat.process_sealed",
        {"sections": "identity,billing,ai"},
        memory_entries=[], db_entries=claim_rows,
    )
    assert status == 200, claim_review
    assert claim_review["kind"] == "claim"
    assert claim_review["source"] == "ledger"
    assert claim_review["quick"]["personal"]["name"] == "Dana Levi"
    assert claim_review["quick"]["billing"]["claimed_amount"] == 2500
    assert claim_review["ai_report"]["decides"] is False
    assert json.dumps(claim_rows[0]["payload"]["seal"], sort_keys=True) == claim_blob


def test_filed_claim_review_reads_the_seal_and_does_not_write():
    import base64

    _get("/api/health")
    email = "dana.review.filed@example.com"
    customer_id = "CUST-REVIEW-FILED"
    policy_id = _seed_customer(customer_id, email)
    token = _customer_token(customer_id, email)
    status, started = _post("/api/claims-chat/start", {"channel": "web_chat"}, token)
    assert status == 201, started
    app_id = started["application_id"]
    resume = started["resume_code"]

    def answer(value, expect=200):
        status_code, body = _post(
            f"/api/claims-chat/{app_id}/message",
            {"value": value, "resume_code": resume},
            token,
        )
        assert status_code == expect, body
        return body

    profile = answer({"name": "Dana Levi", "email": email, "phone": "+1-555-0100"})
    assert profile.get("otp_required") is True
    status, otp = _post(
        f"/api/claims-chat/{app_id}/otp/request",
        {"resume_code": resume, "delivery_channel": "email"},
        token,
    )
    assert status == 200, otp
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
    answer(policy_id)
    answer("accident")
    answer("2024-06-15")
    answer("Tel Aviv, Rothschild 12")
    answer("I slipped on a wet stair at the clinic entrance and injured my wrist.")
    answer(2500)
    answer("Ichilov")
    answer("done", expect=400)
    evidence = base64.b64encode(b"clinic invoice dana levi wrist").decode("ascii")
    status, uploaded = _post(
        f"/api/claims-chat/{app_id}/media",
        {
            "resume_code": resume,
            "kind": "document",
            "name": "invoice.txt",
            "mime_type": "text/plain",
            "data_b64": evidence,
        },
        token,
    )
    assert status == 200, uploaded
    answer("done")
    answer("agree")
    signed = answer({
        "name": "Dana Levi",
        "nationality": "Israel",
        "id_number": _NATIONAL_ID,
        "signature_data": _SIG_PNG,
        "method": "drawn_canvas",
    })
    assert signed.get("ready_to_finalize") is True
    status, filed = _post(
        f"/api/claims-chat/{app_id}/finalize",
        {"resume_code": resume},
        token,
    )
    assert status == 201, filed
    claim_id = filed["claim"]["id"]

    import web_portal.server as portal

    adjuster = _login("claims_adjuster", "claims123")
    status, review = _get(f"/api/claims-chat/{app_id}/process-review", adjuster)
    assert status == 200, review
    assert review["kind"] == "claim"
    assert review["source"] == "session"
    assert review["quick"]["personal"]["name"] == "Dana Levi"
    assert review["quick"]["billing"]["claimed_amount"] == 2500
    assert review["ai_report"]["decides"] is False
    assert review["ai_report"]["mode"] == "deterministic"
    assert review["full"]["integrity"]["ok"] is True
    review_blob = json.dumps(review)
    assert _NATIONAL_ID not in review_blob
    assert "national_id_hash" not in review["quick"]["personal"]

    seals = _ledger(app_id, "claims_chat.process_sealed")
    assert seals
    seal = seals[-1].get("seal") or (seals[-1].get("payload") or {}).get("seal")
    seal_copy = json.dumps(seal, sort_keys=True, default=str)
    ledger_n = len(portal.TRANSACTION_LEDGER)
    customer_copy = json.dumps(portal.CUSTOMERS[customer_id], sort_keys=True, default=str)
    claim_copy = json.dumps(portal.CLAIMS[claim_id], sort_keys=True, default=str)
    status, narrowed = _get(
        f"/api/claims-chat/{app_id}/process-review"
        "?view=full&sections=billing,ai&ask=Explain%20the%20amount&narrate=1",
        adjuster,
    )
    assert status == 200, narrowed
    assert narrowed["controls"]["sections"] == ["billing", "ai"]
    assert "personal" not in narrowed.get("quick", {})
    assert narrowed["quick"]["billing"]["claimed_amount"] == 2500
    assert narrowed["ai_report"]["fallback_reason"] == "llm_unavailable"
    assert narrowed["ai_report"]["decides"] is False
    assert _NATIONAL_ID not in json.dumps(narrowed)
    assert json.dumps(seal, sort_keys=True, default=str) == seal_copy
    assert len(portal.TRANSACTION_LEDGER) == ledger_n
    assert json.dumps(portal.CUSTOMERS[customer_id], sort_keys=True, default=str) == customer_copy
    assert json.dumps(portal.CLAIMS[claim_id], sort_keys=True, default=str) == claim_copy

    from services.claims_chat_service import get_claims_chat_service

    del get_claims_chat_service()._sessions[app_id]
    status, recovered = _get(f"/api/claims-chat/{app_id}/process-review", adjuster)
    assert status == 200, recovered
    assert recovered["source"] == "ledger"
    assert recovered["quick"]["personal"]["name"] == "Dana Levi"
    assert recovered["quick"]["billing"]["claimed_amount"] == 2500
    assert json.dumps(seal, sort_keys=True, default=str) == seal_copy

    seal["revisions"][-1]["checksum"] = "c" * 64
    broken = json.dumps(seal, sort_keys=True, default=str)
    status, hidden = _get(f"/api/claims-chat/{app_id}/process-review", adjuster)
    assert status == 200, hidden
    assert hidden["withheld"] is True
    assert "Dana Levi" not in json.dumps(hidden)
    assert json.dumps(seal, sort_keys=True, default=str) == broken
    assert json.dumps(portal.CLAIMS[claim_id], sort_keys=True, default=str) == claim_copy
    status, applicant = _get(f"/api/claims-chat/{app_id}/process-review", token)
    assert status == 403, applicant


# ---------------------------------------------------------------------------
# Process book / catalog (every discoverable chat)
# ---------------------------------------------------------------------------


def test_process_review_catalog_lists_live_sealed_and_pointers():
    """Staff see live chats, ledger seals, and UW pointers without rewriting."""
    import web_portal.server as portal
    from services.chat_answer_revisions import (
        append_revision,
        build_seal,
        build_process_review_catalog,
    )
    from services.chat_application_service import get_chat_application_service

    underwriter = _login("underwriter", "under123")
    accountant = _login("accountant", "acct123")

    status, anon = _get("/api/chat-process-review/list")
    assert status in (401, 403), anon

    # Accountants are staff but outside PROCESS_REVIEW_ROLES.
    status, denied = _get("/api/chat-process-review/list", accountant)
    assert status == 403, denied

    live_id, resume = _start("catalog.live@example.com")
    _answer(live_id, "42", resume)

    sealed_id, sealed_resume = _start("catalog.sealed@example.com")
    # Advance far enough that finalize can seal; use a minimal seal inject
    # for the catalog path when a full apply would be too heavy.
    session = _session(sealed_id)
    append_revision(
        session.setdefault("revisions", []),
        step_id="name", action="set", at="2026-01-01T00:00:00Z",
        current="Catalog Sealed", current_display="Catalog Sealed",
    )
    session["revision_head"] = session["revisions"][-1]["checksum"]
    session["status"] = "submitted"
    session["contact"] = {
        "name": "Catalog Sealed",
        "email": "catalog.sealed@example.com",
        "phone": "+1-555-0100",
    }
    seal = build_seal(session, kind="policy_application")
    portal.TRANSACTION_LEDGER[f"LEDGER-CATALOG-{sealed_id}"] = {
        "id": f"LEDGER-CATALOG-{sealed_id}",
        "event_type": "chat.process_sealed",
        "entity_id": sealed_id,
        "application_id": sealed_id,
        "sequence_no": 900001,
        "timestamp": "2026-01-02T00:00:00Z",
        "seal": seal,
    }
    del get_chat_application_service()._sessions[sealed_id]

    portal.UNDERWRITING_APPLICATIONS["UW-CATALOG-POINTER"] = {
        "id": "UW-CATALOG-POINTER",
        "customer_id": "CUST-CATALOG-POINTER",
        "customer_name": "Pointer Nora",
        "customer_email": "pointer.nora@example.com",
        "status": "pending",
        "source": "chat_adl_referral",
        "chat_application_id": "CHAPP-POINTER-MISSING",
        "created_date": "2026-01-03T00:00:00Z",
    }
    portal.CUSTOMERS["CUST-CATALOG-POINTER"] = {
        "id": "CUST-CATALOG-POINTER",
        "name": "Pointer Nora",
        "email": "pointer.nora@example.com",
        "status": "active",
    }

    ledger_n = len(portal.TRANSACTION_LEDGER)
    status, book = _get("/api/chat-process-review/list?page_size=100", underwriter)
    assert status == 200, book
    assert book["secret"] is True
    assert "health" in book and "report" in book
    assert book["report"]["integrity"]
    ids = {item["application_id"]: item for item in book["items"]}
    assert live_id in ids
    assert ids[live_id]["reviewable"] is True
    assert ids[live_id]["source"] == "session"
    assert sealed_id in ids
    assert ids[sealed_id]["sealed"] is True
    assert ids[sealed_id]["reviewable"] is True
    assert ids[sealed_id]["integrity_ok"] is True
    assert "CHAPP-POINTER-MISSING" in ids
    assert ids["CHAPP-POINTER-MISSING"]["reviewable"] is False
    assert "pointer_without_seal" in ids["CHAPP-POINTER-MISSING"]["flags"]
    assert ids["CHAPP-POINTER-MISSING"]["has_report"] is True
    assert ids["CHAPP-POINTER-MISSING"]["report_url"].endswith("UW-CATALOG-POINTER")
    assert book["health"]["pointers_without_seal"] >= 1
    assert book["health"]["reviewable"] >= 2
    blob = json.dumps(book)
    assert _PAN not in blob
    assert _NATIONAL_ID not in blob
    assert len(portal.TRANSACTION_LEDGER) == ledger_n

    status, filtered = _get(
        "/api/chat-process-review/list?filter=unsealed&page_size=50",
        underwriter,
    )
    assert status == 200, filtered
    assert all(
        "pointer_without_seal" in (item.get("flags") or [])
        for item in filtered["items"]
    )

    # Alias route stays staff-only and read-only.
    status, alias = _get(
        "/api/chat-application/admin/process-reviews?kind=policy",
        underwriter,
    )
    assert status == 200, alias
    assert all(item["kind"] == "policy_application" for item in alias["items"])

    # Unit: withheld seal is flagged in the catalog without repair.
    broken_seal = json.loads(json.dumps(seal))
    broken_seal["application_id"] = "CHAPP-BROKEN-SEAL"
    broken_seal["revisions"][-1]["checksum"] = "d" * 64
    broken_seal["integrity_ok"] = False
    catalog = build_process_review_catalog(
        memory_entries=[{
            "event_type": "chat.process_sealed",
            "entity_id": "CHAPP-BROKEN-SEAL",
            "application_id": "CHAPP-BROKEN-SEAL",
            "sequence_no": 900002,
            "timestamp": "2099-01-01T00:00:00Z",
            "seal": broken_seal,
        }],
        db_entries=[],
        include_inquiries=False,
        q="CHAPP-BROKEN-SEAL",
        page_size=20,
    )
    broken_row = next(
        item for item in catalog["items"]
        if item["application_id"] == "CHAPP-BROKEN-SEAL"
    )
    assert broken_row["withheld"] is True
    assert broken_row["integrity_ok"] is False
    assert broken_row["revision_head"] is None
    assert catalog["health"]["withheld"] >= 1


def test_chat_process_review_page_loads_catalog_endpoint():
    page = open(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "web_portal",
            "static",
            "chat-process-review.html",
        ),
        encoding="utf-8",
    ).read()
    assert "/api/chat-process-review/list" in page
    assert "Process book" in page
    assert "health-tile" in page
    assert "All chats" in page
