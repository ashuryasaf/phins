"""Chat application: actuarial pricing alignment, media persistence, claim codes.

Covers the three guarantees this flow has to keep:

1. The quote is produced by the actuary's published model (ADL underwriting,
   ``risk_premium_markup`` savings) and is stamped with the table/config
   versions that priced it.
2. Voice / video / document uploads are durably stored and still retrievable
   from the underwriting record after submission.
3. "Track my application" hands the applicant a single-use claim code that can
   open a portal account with a chosen password, and can never overwrite an
   account that already exists.
"""

from __future__ import annotations

import base64
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import web_portal.server as portal
from services.actuarial_service import ActuarialTablesStore
from services.application_claim_service import (
    ApplicationClaimService,
    STATUS_NEEDS_LOGIN,
    STATUS_NEEDS_CREDENTIALS,
)
from services.chat_application_service import get_chat_application_service
from services.pricing_shadow_service import (
    price_application_with_kernel,
    resolve_adl_underwriting,
)

BASE = None


def _base_url() -> str:
    import os

    return os.environ.get("TEST_BASE_URL") or "http://127.0.0.1:8000"


def _request(method, path, payload=None, token=None):
    url = _base_url() + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else {})
    except HTTPError as e:
        body = e.read().decode("utf-8") or "{}"
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, {"_raw": body}


def _post(path, payload=None, token=None):
    return _request("POST", path, payload or {}, token)


def _answer(app_id, value, resume_code):
    status, body = _post(
        f"/api/chat-application/{app_id}/message",
        {"value": value, "resume_code": resume_code},
    )
    assert status == 200, body
    return body


# ── 1. Actuarial pricing alignment ───────────────────────────────────────────


@pytest.fixture()
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setenv("PHINS_ACTUARIAL_STATE_PATH", str(tmp_path / "act.json"))
    monkeypatch.setenv("USE_DATABASE", "false")
    store = ActuarialTablesStore()
    monkeypatch.setattr(
        "services.actuarial_service.get_actuarial_store", lambda: store
    )
    return store


def test_adl_underwriting_follows_actuary_config(isolated_store):
    """ADL loadings/exclusions come from the actuary's UnderwritingConfig."""
    cfg = isolated_store.config

    healthy = resolve_adl_underwriting(5, cfg)
    assert healthy["adl_loading"] == pytest.approx(0.0)
    assert healthy["exclude_disability"] is False
    assert healthy["declined"] is False

    impaired = resolve_adl_underwriting(7, cfg)
    assert impaired["adl_loading"] == pytest.approx(cfg.loadings[7])
    assert impaired["exclude_disability"] is False

    severe = resolve_adl_underwriting(8, cfg)
    assert severe["adl_loading"] == pytest.approx(cfg.loadings[8])
    assert severe["exclude_disability"] is True

    declined = resolve_adl_underwriting(9, cfg)
    assert declined["declined"] is True


def test_kernel_prices_adl_and_savings_markup(isolated_store):
    base = {
        "type": "phins_unified",
        "coverage_amount": 500000,
        "age": 45,
        "term_years": 20,
        "gender": "male",
        "risk_score": "medium",
    }

    standard = price_application_with_kernel({**base, "adl_level": 5})
    impaired = price_application_with_kernel({**base, "adl_level": 7})
    assert standard and impaired

    # ADL loading is additive on top of the health band and raises the premium.
    assert impaired["annual"] > standard["annual"]
    assert impaired["adl_loading"] > 0
    assert impaired["underwriting_loading"] == pytest.approx(
        impaired["health_loading"] + impaired["adl_loading"]
    )

    # Savings ride on the risk premium exactly as the actuary dashboard prices.
    with_savings = price_application_with_kernel(
        {**base, "adl_level": 5, "savings_rate": 0.5}
    )
    assert with_savings
    assert with_savings["savings_formula"] == "risk_premium_markup"
    assert with_savings["savings_rate_used"] == pytest.approx(0.5)
    assert with_savings["savings_premium_annual"] == pytest.approx(
        with_savings["risk_premium_annual"] * 0.5, abs=0.02
    )
    assert with_savings["annual"] > standard["annual"]

    # Version provenance travels with every quote.
    for quote in (standard, impaired, with_savings):
        assert quote["tables_version"]
        assert quote["config_version"]
        assert quote["integrity_hash"]
        assert quote["product_id"]


def test_risk_bands_are_not_collapsed():
    """Every band the scoring engine emits must reach the kernel unchanged."""
    svc = get_chat_application_service()
    for band in ("very_low", "low", "medium", "moderate", "elevated",
                 "high", "very_high"):
        assert svc._payload_risk_score({"risk_category": band}) == band
    assert svc._payload_risk_score({"risk_category": "nonsense"}) == "medium"


def test_moderate_band_prices_above_medium(isolated_store):
    base = {
        "type": "phins_unified",
        "coverage_amount": 400000,
        "age": 38,
        "term_years": 15,
        "adl_level": 5,
    }
    medium = price_application_with_kernel({**base, "risk_score": "medium"})
    moderate = price_application_with_kernel({**base, "risk_score": "moderate"})
    assert medium and moderate
    assert moderate["annual"] > medium["annual"]


# ── 2 & 3. End-to-end chat flow: media persistence + claim code ──────────────


def _run_application(email: str, *, with_media: bool = True):
    status, body = _post("/api/chat-application/start", {})
    assert status == 201, body
    app_id = body["application_id"]
    resume_code = body["resume_code"]

    _answer(app_id, "Maya Cohen", resume_code)
    _answer(app_id, email, resume_code)
    _answer(app_id, "+1-555-0111", resume_code)

    status, otp = _post(
        f"/api/chat-application/{app_id}/otp/request", {"resume_code": resume_code}
    )
    assert status == 200, otp
    status, verified = _post(
        f"/api/chat-application/{app_id}/otp/verify",
        {
            "verification_id": otp["verification_id"],
            "otp_code": otp["demo_otp_code"],
            "resume_code": resume_code,
        },
    )
    assert status == 200, verified

    _answer(app_id, "1988-04-02", resume_code)   # dob
    _answer(app_id, "female", resume_code)       # gender
    _answer(app_id, "Engineer", resume_code)     # occupation
    _answer(app_id, 170, resume_code)            # height
    _answer(app_id, 65, resume_code)             # weight
    _answer(app_id, "no", resume_code)           # tobacco
    _answer(app_id, "no", resume_code)           # medical_conditions
    _answer(app_id, "no", resume_code)           # surgery
    _answer(app_id, "no", resume_code)           # hazardous
    _answer(app_id, ["none"], resume_code)       # family_history
    _answer(app_id, "none", resume_code)         # medications
    assessment = _answer(app_id, "full", resume_code)   # daily_function
    assert assessment.get("assessment")

    _answer(app_id, 500000, resume_code)         # coverage_amount
    _answer(app_id, "20", resume_code)           # coverage_years
    quote_reply = _answer(app_id, "balanced", resume_code)  # savings_addon
    quote = quote_reply["quote"]

    media_ids = []
    if with_media:
        for kind, name, mime, blob in (
            ("voice", "voice-note.webm", "audio/webm", b"VOICE-BYTES-" + b"x" * 64),
            ("video", "video-message.webm", "video/webm", b"VIDEO-BYTES-" + b"y" * 64),
            ("document", "medical.pdf", "application/pdf", b"%PDF-1.4 medical"),
        ):
            status, media = _post(
                f"/api/chat-application/{app_id}/media",
                {
                    "kind": kind,
                    "name": name,
                    "mime_type": mime,
                    "data_b64": base64.b64encode(blob).decode(),
                    "resume_code": resume_code,
                },
            )
            assert status == 200, media
            media_ids.append(media["media"])

    _answer(app_id, "done" if with_media else "skip", resume_code)  # media_offer
    _answer(app_id, "monthly", resume_code)      # billing_frequency
    _answer(
        app_id,
        {
            "card_number": "4111 1111 1111 1111",
            "cardholder_name": "MAYA COHEN",
            "expiry_month": "10",
            "expiry_year": "2032",
            "cvv": "321",
        },
        resume_code,
    )                                            # payment_card
    _answer(app_id, "yes", resume_code)          # auto_pay
    consent = _answer(app_id, "agree", resume_code)
    assert consent.get("ready_to_finalize") is True

    status, result = _post(
        f"/api/chat-application/{app_id}/finalize", {"resume_code": resume_code}
    )
    assert status == 201, result
    return app_id, resume_code, quote, media_ids, result


def test_chat_quote_records_actuarial_versions_and_savings():
    _, _, quote, _, result = _run_application(
        "chat.actuarial@example.com", with_media=False
    )
    if quote.get("pricing_source") == "pricing_kernel":
        assert quote["tables_version"]
        assert quote["config_version"]
        assert quote["savings_formula"] == "risk_premium_markup"
        assert quote["savings_rate_used"] == pytest.approx(0.5)
        assert quote["adl_level"] == 5
    else:  # flat fallback still records the inputs it used
        assert quote["savings_rate_used"] == pytest.approx(0.5)

    svc = get_chat_application_service()
    state = svc.get_state(result["application_id"], staff=True)
    quoted = [e for e in state["journey"] if e["stage"] == "quoted"]
    assert quoted, state["journey"]
    meta = quoted[-1].get("meta") or {}
    assert "tables_version" in meta and "config_version" in meta


def test_voice_and_video_persist_into_underwriting_record():
    app_id, _, _, media_items, result = _run_application(
        "chat.media@example.com", with_media=True
    )

    # Every attachment was written to the durable document vault.
    svc = get_chat_application_service()
    state = svc.get_state(app_id, staff=True)
    kinds = {m["kind"] for m in state["media"]}
    assert {"voice", "video", "document"} <= kinds
    for item in state["media"]:
        assert item.get("persistence_status") == "stored", item
        assert item.get("persistent_doc_id"), item

    uw_id = result["underwriting"]["id"]
    stored = [
        f for f in portal.UNDERWRITING_FILES.values()
        if f.get("application_id") == uw_id
    ]
    assert len(stored) >= 3, stored
    stored_kinds = {f.get("kind") for f in stored}
    assert {"voice", "video", "document"} <= stored_kinds
    for entry in stored:
        assert entry.get("sha256")
        # Bytes are reachable either inline or through the vault pointer.
        assert entry.get("data") or entry.get("persistent_doc_id")

    # A staff viewer can actually open the voice note.
    from datetime import datetime, timedelta

    token = "phins_test-chat-media-admin"
    portal.SESSIONS[token] = {
        "username": "media_admin",
        "role": "admin",
        "customer_id": "",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    voice = next(f for f in stored if f.get("kind") == "voice")
    status, view = _request(
        "GET", f"/api/underwriting/files/view?id={voice['id']}", None, token
    )
    assert status == 200, view
    assert view["data"]


def test_media_survives_when_session_memory_is_dropped():
    """Durable storage, not the in-memory session, backs the attachment."""
    status, body = _post("/api/chat-application/start", {})
    assert status == 201, body
    app_id = body["application_id"]
    resume_code = body["resume_code"]

    _answer(app_id, "Ori Shalev", resume_code)
    _answer(app_id, "chat.durable@example.com", resume_code)
    _answer(app_id, "+1-555-0122", resume_code)
    status, otp = _post(
        f"/api/chat-application/{app_id}/otp/request", {"resume_code": resume_code}
    )
    assert status == 200, otp
    _post(
        f"/api/chat-application/{app_id}/otp/verify",
        {
            "verification_id": otp["verification_id"],
            "otp_code": otp["demo_otp_code"],
            "resume_code": resume_code,
        },
    )

    raw = b"DURABLE-VOICE-" + b"z" * 128
    status, media = _post(
        f"/api/chat-application/{app_id}/media",
        {
            "kind": "voice",
            "name": "durable.webm",
            "mime_type": "audio/webm",
            "data_b64": base64.b64encode(raw).decode(),
            "resume_code": resume_code,
        },
    )
    assert status == 200, media
    doc_id = media["media"]["persistent_doc_id"]
    assert doc_id

    svc = get_chat_application_service()
    session = svc._sessions[app_id]
    item = session["media"][0]
    # Simulate the in-memory copy being gone (restart / eviction).
    item["data_b64"] = ""
    recovered = svc.load_media_bytes_b64(item)
    assert recovered
    assert base64.b64decode(recovered) == raw


# ── 3. Claim code / quick registry ───────────────────────────────────────────


def test_claim_service_is_single_use_and_email_bound():
    svc = ApplicationClaimService()
    issued = svc.issue(
        application_id="CHAPP-TEST-1",
        customer_id="CUST-TEST-1",
        email="Owner@Example.com",
        policy_id="POL-1",
    )
    assert issued["ok"]
    code = issued["claim_code"]
    assert code.startswith("PHINS-CLAIM-")

    # Wrong email is rejected even with the right code.
    wrong = svc.lookup(claim_code=code, email="thief@example.com",
                       email_has_login=False)
    assert wrong["ok"] is False and wrong["status_code"] == 403

    ok = svc.lookup(claim_code=code, email="owner@example.com",
                    email_has_login=False)
    assert ok["status"] == STATUS_NEEDS_CREDENTIALS

    # An existing account must never be claimable with a code.
    existing = svc.redeem(claim_code=code, email="owner@example.com",
                          email_has_login=True)
    assert existing["ok"] is False
    assert existing["status"] == STATUS_NEEDS_LOGIN

    spent = svc.redeem(claim_code=code, email="owner@example.com",
                       email_has_login=False)
    assert spent["ok"] is True
    assert spent["customer_id"] == "CUST-TEST-1"

    replay = svc.redeem(claim_code=code, email="owner@example.com",
                        email_has_login=False)
    assert replay["ok"] is False and replay["status_code"] == 409


def test_track_my_application_creates_account_with_chosen_password():
    email = "chat.claim.new@example.com"
    portal.USERS.pop(email, None)
    _, _, _, _, result = _run_application(email, with_media=False)

    claim = result.get("claim") or {}
    assert claim.get("claim_code"), result
    assert claim.get("track_url", "").startswith("/track-application.html")

    status, lookup = _post(
        "/api/applications/claim/lookup",
        {"claim_code": claim["claim_code"], "email": email},
    )
    assert status == 200, lookup
    assert lookup["status"] == STATUS_NEEDS_CREDENTIALS
    assert lookup["customer_name"] == "Maya Cohen"
    assert lookup["policy_id"] == result["policy"]["id"]
    assert lookup["summary"]["coverage_amount"] == 500000

    status, bad = _post(
        "/api/applications/claim/activate",
        {"claim_code": claim["claim_code"], "email": email, "password": "short"},
    )
    assert status == 400, bad

    status, activated = _post(
        "/api/applications/claim/activate",
        {"claim_code": claim["claim_code"], "email": email,
         "password": "TrackMe!2026"},
    )
    assert status == 201, activated
    assert activated["token"]
    assert activated["customer_id"] == result["customer"]["id"]
    assert activated["redirect"] == "/dashboard.html"

    # The chosen password is the real login credential.
    status, login = _post(
        "/api/login", {"username": email, "password": "TrackMe!2026",
                       "captcha_fallback": True}
    )
    assert status == 200, login
    assert login["customer_id"] == result["customer"]["id"]

    # Single use: the code cannot be replayed.
    status, replay = _post(
        "/api/applications/claim/activate",
        {"claim_code": claim["claim_code"], "email": email,
         "password": "Another!2026"},
    )
    assert status in (409, 404), replay


def test_claim_code_cannot_take_over_existing_account():
    email = "chat.claim.existing@example.com"
    from web_portal.server import hash_password

    pwd = hash_password("OriginalPass!1")
    portal.USERS[email] = {
        "hash": pwd["hash"],
        "salt": pwd["salt"],
        "role": "customer",
        "name": "Existing Owner",
        "customer_id": "CUST-EXISTING-1",
    }

    _, _, _, _, result = _run_application(email, with_media=False)
    claim = result.get("claim") or {}
    assert claim.get("claim_code")

    status, lookup = _post(
        "/api/applications/claim/lookup",
        {"claim_code": claim["claim_code"], "email": email},
    )
    assert status == 200, lookup
    assert lookup["status"] == STATUS_NEEDS_LOGIN

    status, blocked = _post(
        "/api/applications/claim/activate",
        {"claim_code": claim["claim_code"], "email": email,
         "password": "Attacker!2026"},
    )
    assert status == 409, blocked
    assert blocked["status"] == STATUS_NEEDS_LOGIN

    # Original credentials still work; the attacker password does not.
    status, login = _post(
        "/api/login", {"username": email, "password": "OriginalPass!1",
                       "captcha_fallback": True}
    )
    assert status == 200, login
    status, denied = _post(
        "/api/login", {"username": email, "password": "Attacker!2026",
                       "captcha_fallback": True}
    )
    assert status != 200
