"""Open links to the PHINS Unified Business Plan: conditional NDA, protected
view, access window, admin-saved factors and the Hebrew edition.

Pins:

* the plan set (page, Hebrew edition, model / portrait / access / factors
  APIs, PDF and Markdown editions) is confidential; the HTML pages and APIs
  share one scope root so a single unlock covers them, while the downloads
  stay staff-only;
* a share link to the plan is NDA-conditional — unlock needs the signed
  undertaking (full name) and records the acceptance with the NDA version and
  SHA-256; the opening gets its own access window (single use ≤ 3 hours) and
  idle timeout, both enforced server-side;
* an open-link viewer sees the protected view (``/api/business-plan/access``
  → ``mode=share``, no download / print / copy) and may only move the factors
  the admin whitelisted — the model API pins the rest and reports them;
* the admin-saved factor set is validated against the register's bounds,
  survives a restart, becomes every viewer's baseline and never claims to be
  the canonical plan;
* the Hebrew dictionary covers every string in the HTML, Markdown and charts.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from security import confidential_access as ca
from services import business_plan_i18n as i18n
from services import business_plan_model as bpm
from services.business_plan_nda import (
    DOC_CONTEXT,
    DOC_TYPE,
    NDA_VERSION,
    doc_instance_id,
    field_values,
    nda_document,
    nda_sha256,
    nda_text,
)
from services.business_plan_settings import BusinessPlanSettings, SettingsError
from services.confidential_share_service import (
    ConfidentialShareService,
    DEFAULT_ACCESS_WINDOW_SECONDS,
    MAX_SINGLE_USE_WINDOW_SECONDS,
    ShareError,
)

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
TOKEN = "t" * 40
SECRET = "s" * 32
PLAN = "/business-plan.html"
PLAN_HE = "/business-plan.he.html"


# ---------------------------------------------------------------------------
# NDA text
# ---------------------------------------------------------------------------
def test_nda_is_the_platform_nda_instantiated_for_the_link():
    day = "2026-10-17"
    en = nda_document("en", label="Investor ACME", effective_date=day, share_id="shr_abc")
    he = nda_document("he", label="משקיע", effective_date=day, share_id="shr_abc")
    assert en["version"] == he["version"] == NDA_VERSION
    assert en["doc_type"] == he["doc_type"] == DOC_TYPE == "nda" and en["context"] == DOC_CONTEXT == "investor"
    assert en["platform_document"] == "/legal/nda.html"
    assert en["doc_instance_id"] == he["doc_instance_id"] == doc_instance_id("shr_abc") == "LGL-NDA-SHR_ABC"
    assert en["sha256"] == nda_sha256("en", label="Investor ACME", effective_date=day)
    assert he["sha256"] == nda_sha256("he", label="משקיע", effective_date=day)
    assert en["sha256"] != he["sha256"]
    # Content-addressed per party and date: another label is another document.
    assert en["sha256"] != nda_sha256("en", label="Investor Other", effective_date=day)
    assert en["addressed_to"] == "Investor ACME" and he["rtl"] is True and en["rtl"] is False
    # Platform clauses 1–7 (Purpose … Governing Law) + the protected-view rider.
    assert [c["heading"] for c in en["clauses"]] == [
        "Purpose", "Confidential Information", "Obligations", "Exclusions", "Term",
        "No License; Return", "Governing Law", "Protected view (open-link rider)",
    ]
    assert len(he["clauses"]) == 8
    fields = en["field_values"]
    assert fields == field_values("Investor ACME", day)
    assert fields["companyName"] == "PHINS Insurance, Inc." and fields["counterpartyName"] == "Investor ACME"
    assert fields["mutual"].startswith("One-way") and fields["termYears"] == 2 and fields["confidYears"] == 5
    assert fields["governingLaw"] == "State of Delaware, USA" and fields["effectiveDate"] == day
    assert "PHINS Unified Business Plan" in fields["purpose"]
    text = nda_text("en", label="Investor ACME", effective_date=day)
    assert "Non-Disclosure Agreement" in text and "screenshot" in text and "Investor ACME" in text
    assert nda_document("xx")["lang"] == "en"  # unknown language falls back
    assert nda_document("en")["doc_instance_id"] is None


# ---------------------------------------------------------------------------
# Gate: the plan set is confidential and shares one scope
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("path", [PLAN, PLAN_HE, "/api/business-plan/model",
                                  "/api/business-plan/founder-portrait", "/api/business-plan/access",
                                  "/api/business-plan/factors",
                                  "/investor-docs/phins-unified-business-plan.pdf",
                                  "/investor-docs/phins-unified-business-plan.he.md"])
def test_plan_set_is_confidential(path):
    assert ca.is_confidential_path(path)
    assert ca.is_business_plan_path(path)


def test_scope_root_covers_pages_and_apis_but_never_downloads():
    for p in (PLAN, PLAN_HE, "/api/business-plan/model", "/api/business-plan/access"):
        assert ca.share_scope_root(p) == PLAN
    assert ca.share_scope_root("/pitch-dashboard.html") == "/pitch-dashboard.html"
    env = {"SESSION_SECRET_KEY": SECRET}
    cookie = ca.mint_share_cookie(share_id="shr_x", path=PLAN, environ=env, session_key="sess1")
    assert ca.verify_share_cookie(cookie, PLAN_HE, env)["sk"] == "sess1"
    assert ca.verify_share_cookie(cookie, "/api/business-plan/model", env)
    assert ca.verify_share_cookie(cookie, "/pitch-dashboard.html", env) is None
    assert ca.verify_share_cookie(cookie, "/investor-docs/phins-unified-business-plan.pdf", env) is None


def test_session_key_reaches_the_active_check_and_closes_the_view():
    env = {"SESSION_SECRET_KEY": SECRET, "PHINS_ENVIRONMENT": "production"}
    cookie = ca.mint_share_cookie(share_id="shr_x", path=PLAN, environ=env, session_key="sess1")
    seen = {}

    def check(sid, path, sk=""):
        seen.update(sid=sid, path=path, sk=sk)
        return sk == "sess1"

    decision = ca.evaluate_access(PLAN_HE, cookie_header=f"{ca.SHARE_COOKIE_NAME}={cookie}",
                                  environ=env, share_active_check=check)
    assert decision.allowed and decision.is_share_viewer and decision.share_session_key == "sess1"
    assert seen == {"sid": "shr_x", "path": PLAN_HE, "sk": "sess1"}
    closed = ca.evaluate_access(PLAN, cookie_header=f"{ca.SHARE_COOKIE_NAME}={cookie}",
                                environ=env, share_active_check=lambda *a: False)
    assert closed.allowed is False and closed.status in (401, 503)


# ---------------------------------------------------------------------------
# Share service: NDA, window, idle, scope
# ---------------------------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    return ConfidentialShareService(data_path=str(tmp_path / "shares.json"))


def test_nda_link_needs_label_and_caps_single_use_window(store):
    with pytest.raises(ShareError):
        store.create_share(path=PLAN, password="open1234", max_uses=1, nda_required=True)
    with pytest.raises(ShareError):
        store.create_share(path=PLAN, password="open1234", max_uses=1, label="ACME",
                           nda_required=True, access_window_seconds=4 * 3600)
    share = store.create_share(path=PLAN, password="open1234", max_uses=1, label="ACME", nda_required=True)
    assert share["nda_required"] and share["nda_version"] == NDA_VERSION
    today = datetime.now(timezone.utc).date().isoformat()
    assert share["nda_effective_date"] == today
    assert share["nda_sha256"] == nda_sha256("en", label="ACME", effective_date=today)
    assert share["nda_doc_instance_id"] == doc_instance_id(share["id"])
    assert share["access_window_seconds"] == DEFAULT_ACCESS_WINDOW_SECONDS == MAX_SINGLE_USE_WINDOW_SECONDS
    assert share["idle_timeout_seconds"] == 1800 and share["scope"] == PLAN
    assert share["expires_at"]  # an unopened NDA link lapses on its own
    multi = store.create_share(path=PLAN_HE, password="open1234", max_uses=5, label="ACME",
                               nda_required=True, access_window_seconds=8 * 3600, lang="he")
    assert multi["access_window_seconds"] == 8 * 3600
    assert multi["nda_sha256"] == nda_sha256("he", label="ACME", effective_date=today)
    plain = store.create_share(path=PLAN, password="open1234", max_uses=1, label="x")
    assert plain["nda_sha256"] is None and plain["nda_doc_instance_id"] is None


def test_unlock_requires_signed_nda_and_records_acceptance(store):
    share = store.create_share(path=PLAN, password="open1234", max_uses=1, label="ACME", nda_required=True)
    with pytest.raises(ShareError, match="NDA"):
        store.unlock(share["id"], "open1234")
    with pytest.raises(ShareError, match="full name"):
        store.unlock(share["id"], "open1234", nda_accepted=True, signer_name=" ")
    assert store.get_share(share["id"])["used_count"] == 0  # refusals consume nothing
    view, target = store.unlock(share["id"], "open1234", nda_accepted=True, signer_name="Dana  Levi",
                                requested_path=PLAN_HE, client_ip="10.0.0.1", user_agent="pytest")
    assert target == PLAN and view["status"] == "exhausted" and view["session_key"]
    acc = view["nda_acceptances"][0]
    assert acc["signer_name"] == "Dana Levi" and acc["nda_sha256"] == share["nda_sha256"]
    assert acc["doc_instance_id"] == share["nda_doc_instance_id"] and acc["signature_method"] == "type"
    assert acc["ledger"] is None and view["signature_method"] == "type"
    assert view["openings"][0]["signer_name"] == "Dana Levi"
    until = datetime.fromisoformat(view["access_until"].replace("Z", "+00:00"))
    assert timedelta(hours=2, minutes=59) < until - datetime.now(timezone.utc) <= timedelta(hours=3)
    raw = store.get_share_raw(share["id"])
    assert raw["nda_acceptances"][0]["ip"] == "10.0.0.1" and raw["nda_acceptances"][0]["user_agent"] == "pytest"
    assert "password" not in view and "password_hash" not in view


def test_drawn_signature_is_validated_and_digested(store):
    import base64
    share = store.create_share(path=PLAN, password="open1234", max_uses=3, label="ACME", nda_required=True)
    with pytest.raises(ShareError, match="PNG"):
        store.unlock(share["id"], "open1234", nda_accepted=True, signer_name="Dana", signature_png="data:image/jpeg;base64,AAAA")
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    data_url = "data:image/png;base64," + base64.b64encode(png).decode()
    view, _ = store.unlock(share["id"], "open1234", nda_accepted=True, signer_name="Dana", signature_png=data_url)
    assert view["nda_acceptances"][0]["signed_drawing"] is True
    assert view["nda_acceptances"][0]["signature_method"] == "draw" and view["signature_method"] == "draw"
    assert len(view["nda_acceptances"][0]["signature_sha256"]) == 64


def test_ledger_receipt_is_attached_and_a_failed_anchor_rolls_the_opening_back(store):
    share = store.create_share(path=PLAN, password="open1234", max_uses=1, label="ACME", nda_required=True)
    view, _ = store.unlock(share["id"], "open1234", nda_accepted=True, signer_name="Dana Levi")
    sk = view["session_key"]
    assert view["status"] == "exhausted" and view["used_count"] == 1

    # The anchor did not happen: the opening is undone and the use is given back.
    assert store.rollback_opening(share["id"], sk) is True
    after = store.get_share(share["id"])
    assert after["status"] == "active" and after["used_count"] == 0
    assert after["openings"] == [] and after["nda_acceptances"] == []
    assert not store.share_is_active_for_path(share["id"], PLAN, session_key=sk)
    assert store.rollback_opening(share["id"], sk) is False  # nothing left to undo
    assert store.attach_ledger_receipt(share["id"], sk, {"entry_id": "x"}) is None

    # Signed again and anchored: the receipt sits on the acceptance and the viewer context.
    view, _ = store.unlock(share["id"], "open1234", nda_accepted=True, signer_name="Dana Levi")
    sk = view["session_key"]
    receipt = store.attach_ledger_receipt(share["id"], sk, {
        "entry_id": "LGLSIG-" + "a" * 64, "sequence_no": 7, "entry_hash": "b" * 64,
        "doc_instance_id": share["nda_doc_instance_id"], "role": "Receiving Party", "signed_at": "2026-10-17T10:00:00Z",
    })
    assert receipt["entry_id"] == "LGLSIG-" + "a" * 64 and receipt["sequence_no"] == 7
    stored = store.get_share(share["id"])["nda_acceptances"][0]["ledger"]
    assert stored == receipt and stored["doc_instance_id"] == doc_instance_id(share["id"])
    ctx = store.viewer_context(share["id"], sk)
    assert ctx["nda_ledger"] == receipt and ctx["nda_doc_instance_id"] == doc_instance_id(share["id"])


def test_opening_window_scope_and_idle_are_enforced(store):
    share = store.create_share(path=PLAN, password="open1234", max_uses=1, label="ACME", nda_required=True)
    view, _ = store.unlock(share["id"], "open1234", nda_accepted=True, signer_name="Dana Levi")
    sk = view["session_key"]
    assert store.share_is_active_for_path(share["id"], PLAN_HE, session_key=sk)
    assert store.share_is_active_for_path(share["id"], "/api/business-plan/model", session_key=sk)
    assert not store.share_is_active_for_path(share["id"], "/pitch-dashboard.html", session_key=sk)
    assert not store.share_is_active_for_path(share["id"], "/investor-docs/phins-unified-business-plan.pdf", session_key=sk)
    assert not store.share_is_active_for_path(share["id"], PLAN, session_key="forged")
    ctx = store.viewer_context(share["id"], sk)
    assert ctx["signer_name"] == "Dana Levi" and ctx["label"] == "ACME" and ctx["access_until"]

    def _session(mutate):
        with store._exclusive_store():
            rec = store._shares[share["id"]]
            mutate(rec["sessions"][0])
            store._persist()

    stale = (datetime.now(timezone.utc) - timedelta(minutes=31)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    _session(lambda s: s.__setitem__("last_seen_at", stale))
    assert not store.share_is_active_for_path(share["id"], PLAN, session_key=sk), "idle view must close"
    fresh = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    gone = (datetime.now(timezone.utc) - timedelta(seconds=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    _session(lambda s: (s.__setitem__("last_seen_at", fresh), s.__setitem__("access_until", gone)))
    assert not store.share_is_active_for_path(share["id"], PLAN, session_key=sk), "window end must close"


def test_legacy_share_records_keep_working(store):
    """Pre-NDA records (no sessions / window fields) still unlock and verify."""
    share = store.create_share(path="/pitch-dashboard.html", password="open1234", max_uses=2)
    with store._exclusive_store():
        rec = store._shares[share["id"]]
        for key in ("sessions", "nda_required", "nda_acceptances", "access_window_seconds", "idle_timeout_seconds", "lang"):
            rec.pop(key, None)
        store._persist()
    view, target = store.unlock(share["id"], "open1234")
    assert target == "/pitch-dashboard.html" and view["nda_required"] is False
    assert store.share_is_active_for_path(share["id"], "/pitch-dashboard.html")
    assert store.share_is_active_for_path(share["id"], "/pitch-dashboard.html", session_key=view["session_key"])


# ---------------------------------------------------------------------------
# Admin-saved factor set
# ---------------------------------------------------------------------------
def test_saved_factors_are_bounded_durable_and_never_canonical(tmp_path):
    path = tmp_path / "bp.json"
    settings = BusinessPlanSettings(data_path=str(path))
    assert settings.get()["has_saved"] is False
    with pytest.raises(SettingsError):
        settings.save(factors={"phins_take": 9})
    with pytest.raises(SettingsError):
        settings.save(factors={"not_a_factor": 1})
    with pytest.raises(SettingsError):
        settings.save(factors={}, viewer_adjustable=["nope"])
    doc = settings.save(factors={"phins_take": 0.30, "wacc": bpm.FACTOR_INDEX["wacc"]["default"]},
                        viewer_adjustable=["phins_take", "prudence"], updated_by="admin")
    assert doc["saved_factors"] == {"phins_take": 0.30}  # defaults are not stored
    assert doc["viewer_adjustable"] == ["phins_take", "prudence"] and doc["updated_by"] == "admin"
    # survives a restart
    again = BusinessPlanSettings(data_path=str(path))
    assert again.saved_factors() == {"phins_take": 0.30}
    # the plan computed on the saved set is a scenario with its own hash
    plan = bpm.compute_plan(settings.baseline())
    assert plan["canonical"] is False and plan["integrity"]["all_hold"] is True
    assert plan["content_hash"] != bpm.compute_plan()["content_hash"]
    # a hand-corrupted value is dropped, not served
    path.write_text(path.read_text().replace("0.3", "9.9"))
    assert BusinessPlanSettings(data_path=str(path)).saved_factors() == {}
    assert settings.clear()["has_saved"] is False


def test_restrict_overrides_pins_locked_factors(tmp_path):
    settings = BusinessPlanSettings(data_path=str(tmp_path / "bp.json"))
    assert settings.restrict_overrides({"wacc": "0.2"}) == ({"wacc": "0.2"}, [])  # no whitelist = all
    settings.save(factors={"phins_take": 0.30, "wacc": 0.18}, viewer_adjustable=["phins_take"])
    effective, restricted = settings.restrict_overrides({"phins_take": "0.22", "wacc": "0.25", "prudence": "0.1"})
    assert effective == {"phins_take": "0.22", "wacc": 0.18} and restricted == ["wacc", "prudence"]
    plan = bpm.compute_plan(effective)
    assert plan["inputs"]["wacc"] == 0.18 and plan["inputs"]["phins_take"] == 0.22
    assert plan["inputs"]["prudence"] == bpm.FACTOR_INDEX["prudence"]["default"]


# ---------------------------------------------------------------------------
# Hebrew edition coverage
# ---------------------------------------------------------------------------
def test_hebrew_dictionary_covers_html_markdown_and_charts():
    from services import business_plan_charts as charts
    from services import business_plan_document as doc

    plan = bpm.compute_plan()
    t = i18n.translator("he")
    with i18n.language_context(t):
        doc._render_html(plan, "he", True)
        doc._render_markdown(plan)
        charts.render_all(plan)
    assert t.misses == set(), sorted(t.misses)[:20]
    he_html = doc.render_html(plan, lang="he")
    en_html = doc.render_html(plan, lang="en")
    assert 'lang="he" dir="rtl"' in he_html and "Heebo" in he_html
    assert he_html.count("data-bp=") == en_html.count("data-bp=")
    assert plan["content_hash"] in he_html and plan["content_hash"] in en_html
    assert "/business-plan-access.js" in he_html and 'id="bp-admin-tools"' in he_html


# ---------------------------------------------------------------------------
# HTTP: the full open-link flow against the embedded server
# ---------------------------------------------------------------------------
@pytest.fixture
def closed_gate(tmp_path, monkeypatch):
    """Production-like gate on the embedded server plus temp share/settings stores."""
    from services import business_plan_settings as bps
    from services import confidential_share_service as css
    from services import signed_document_archive as sda

    monkeypatch.setenv("PHINS_ENVIRONMENT", "production")
    monkeypatch.setenv("SESSION_SECRET_KEY", SECRET)
    monkeypatch.setenv("PHINS_CONFIDENTIAL_ACCESS_TOKEN", TOKEN)
    css.reset_confidential_share_service_for_tests()
    bps.reset_business_plan_settings_for_tests()
    sda.reset_signed_document_archive_for_tests()
    css.get_confidential_share_service(data_path=str(tmp_path / "shares.json"))
    bps.get_business_plan_settings(data_path=str(tmp_path / "bp_settings.json"))
    sda.get_signed_document_archive(str(tmp_path / "signed"))
    yield
    css.reset_confidential_share_service_for_tests()
    bps.reset_business_plan_settings_for_tests()
    sda.reset_signed_document_archive_for_tests()


def _admin_session():
    login = requests.post(f"{BASE_URL}/api/login", json={"username": "admin", "password": "admin123"}, timeout=10)
    assert login.status_code == 200, login.text
    admin = requests.Session()
    admin.headers["Authorization"] = f"Bearer {login.json()['token']}"
    return admin


def test_http_plan_set_is_closed_to_anonymous_callers(closed_gate):
    for path in (PLAN, PLAN_HE, "/api/business-plan/model", "/api/business-plan/access",
                 "/investor-docs/phins-unified-business-plan.pdf"):
        r = requests.get(f"{BASE_URL}{path}", timeout=10, allow_redirects=False)
        assert r.status_code == 401, path
        assert "Adjustable factors" not in r.text


def test_http_nda_link_end_to_end(closed_gate):
    admin = _admin_session()
    staff_access = admin.get(f"{BASE_URL}/api/business-plan/access", timeout=10).json()
    assert staff_access["mode"] == "staff" and staff_access["can_download"] and staff_access["can_save_factors"]

    # Admin saves a default factor set and lets viewers move only phins_take.
    saved = admin.post(f"{BASE_URL}/api/business-plan/factors",
                       json={"factors": {"phins_take": 0.30}, "viewer_adjustable": ["phins_take"]}, timeout=10)
    assert saved.status_code == 200, saved.text
    assert saved.json()["settings"]["saved_factors"] == {"phins_take": 0.30}
    bad = admin.post(f"{BASE_URL}/api/business-plan/factors", json={"factors": {"phins_take": 7}}, timeout=10)
    assert bad.status_code == 400 and "error" in bad.json()

    # A plan link is NDA-conditional whatever the form sent; label required.
    refused = admin.post(f"{BASE_URL}/api/confidential/shares",
                         json={"path": PLAN, "password": "guest-open", "mode": "single"}, timeout=10)
    assert refused.status_code == 400
    create = admin.post(f"{BASE_URL}/api/confidential/shares",
                        json={"path": PLAN, "password": "guest-open", "mode": "single",
                              "label": "Investor ACME", "nda_required": False,
                              "access_window_seconds": 3600, "idle_timeout_seconds": 900}, timeout=10)
    assert create.status_code == 201, create.text
    share = create.json()["share"]
    assert share["nda_required"] is True and share["access_window_seconds"] == 3600
    assert share["idle_timeout_seconds"] == 900
    assert share["nda_sha256"] == nda_sha256("en", label="Investor ACME", effective_date=share["nda_effective_date"])
    instance = share["nda_doc_instance_id"]
    assert instance == doc_instance_id(share["id"])

    # Recipient sees the platform NDA, addressed to the label, with the signature form.
    gate = requests.get(f"{BASE_URL}{PLAN}", params={"share": share["id"]}, timeout=10, allow_redirects=False)
    assert gate.status_code == 401
    assert 'data-nda="1"' in gate.text and "Investor ACME" in gate.text
    assert "nda-signature" in gate.text and "Non-Disclosure Agreement" in gate.text
    assert "PHINS NDA Center" in gate.text and instance in gate.text and "/legal/nda.html" in gate.text
    assert share["nda_sha256"][:16] in gate.text
    assert "Adjustable factors" not in gate.text

    recipient = requests.Session()
    unsigned = recipient.post(f"{BASE_URL}/api/confidential/share-unlock",
                              json={"share_id": share["id"], "password": "guest-open", "path": PLAN}, timeout=10)
    assert unsigned.status_code == 400 and "nda" in unsigned.json()["error"].lower()
    assert admin.get(f"{BASE_URL}/api/legal-docs/registry", params={"doc_id": instance}, timeout=10).json()["items"] == []
    assert requests.get(f"{BASE_URL}/api/legal-docs/registry", params={"doc_id": instance}, timeout=10).status_code == 401
    opened = recipient.post(f"{BASE_URL}/api/confidential/share-unlock",
                            json={"share_id": share["id"], "password": "guest-open", "path": PLAN_HE,
                                  "nda_accepted": True, "signer_name": "Dana Levi"}, timeout=10)
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["redirect_to"].startswith(PLAN_HE) and "session_key" not in body["share"]
    acceptance = body["share"]["nda_acceptances"][0]
    assert acceptance["signer_name"] == "Dana Levi" and acceptance["doc_instance_id"] == instance
    set_cookie = opened.headers.get("Set-Cookie", "")
    assert ca.SHARE_COOKIE_NAME in set_cookie and "Max-Age=3600" in set_cookie

    # The signature is the platform NDA anchored on the platform ledger …
    ledger = body["share"]["nda_ledger"]
    assert ledger == acceptance["ledger"]
    assert ledger["entry_id"].startswith("LGLSIG-") and ledger["sequence_no"] and ledger["entry_hash"]
    assert ledger["doc_instance_id"] == instance and ledger["role"] == "Receiving Party"
    # … visible in the NDA registry and verifiable like any NDA Center signature.
    registry = admin.get(f"{BASE_URL}/api/legal-docs/registry", params={"doc_id": instance}, timeout=10).json()
    assert registry["total"] == 1
    sig = registry["items"][0]
    assert sig["role"] == "Receiving Party" and sig["signer_name"] == "Dana Levi"
    assert sig["document_hash"] == share["nda_sha256"] and sig["signature_method"] == "type"
    assert sig["entry_id"] == ledger["entry_id"] and sig["entry_hash"] == ledger["entry_hash"]
    assert sig["content"]["fieldValues"]["counterpartyName"] == "Investor ACME"
    assert sig["content"]["fieldValues"]["purpose"].startswith("Evaluation of a potential business")
    assert sig["content"]["share_id"] == share["id"]
    verified = admin.post(f"{BASE_URL}/api/legal-docs/verify",
                          json={"docInstanceId": instance, "documentHash": share["nda_sha256"]}, timeout=10)
    assert verified.status_code == 200, verified.text
    assert verified.json()["verified"] is True and verified.json()["chain_valid"] is True
    tampered = admin.post(f"{BASE_URL}/api/legal-docs/verify",
                          json={"docInstanceId": instance, "documentHash": "0" * 64}, timeout=10).json()
    assert tampered["verified"] is False

    # The signed terms land in the IL-pitch signed-documents folder, sealed.
    assert requests.get(f"{BASE_URL}/api/confidential/signed-documents", timeout=10).status_code == 401
    folder = admin.get(f"{BASE_URL}/api/confidential/signed-documents", timeout=10)
    assert folder.status_code == 200, folder.text
    filed = folder.json()["items"]
    assert len(filed) == 1 and filed[0]["intact"] is True
    assert filed[0]["signer_name"] == "Dana Levi" and filed[0]["nda_sha256"] == share["nda_sha256"]
    assert filed[0]["archive_id"] == ledger["archive_id"]
    opened_doc = admin.get(f"{BASE_URL}/api/confidential/signed-documents/{filed[0]['archive_id']}", timeout=10).json()
    assert opened_doc["nda_sha256"] == share["nda_sha256"]
    import hashlib
    assert hashlib.sha256(opened_doc["nda_text"].encode()).hexdigest() == share["nda_sha256"]
    assert "Non-Disclosure Agreement" in opened_doc["nda_text"] and "Investor ACME" in opened_doc["nda_text"]
    rendered = admin.get(f"{BASE_URL}/api/confidential/signed-documents/{filed[0]['archive_id']}/html", timeout=10)
    assert rendered.status_code == 200 and share["nda_sha256"] in rendered.text and "Dana Levi" in rendered.text

    # The cookie from this opening does not unlock a different link.
    other = admin.post(f"{BASE_URL}/api/confidential/shares",
                       json={"path": PLAN, "password": "guest-open", "mode": "multi", "label": "Second Recipient",
                             "max_uses": 5}, timeout=10)
    assert other.status_code == 201, other.text
    second_share = other.json()["share"]
    reused = recipient.get(f"{BASE_URL}{PLAN}", params={"share": second_share["id"]}, timeout=10, allow_redirects=False)
    assert reused.status_code == 401
    assert "Second Recipient" in reused.text and "Non-Disclosure Agreement" in reused.text
    # And the first opening is still the one that can read the page with no share id.
    assert recipient.get(f"{BASE_URL}{PLAN}", timeout=10).status_code == 200

    # One unlock covers the page, the Hebrew edition and the plan APIs …
    assert recipient.get(f"{BASE_URL}{PLAN}", timeout=10).status_code == 200
    he_page = recipient.get(f"{BASE_URL}{PLAN_HE}", timeout=10)
    assert he_page.status_code == 200 and 'dir="rtl"' in he_page.text
    access = recipient.get(f"{BASE_URL}/api/business-plan/access", timeout=10).json()
    assert access["mode"] == "share" and access["protected"] is True
    assert access["can_download"] is False and access["can_print"] is False
    assert access["adjustable"] == ["phins_take"] and access["saved_factors"] == {"phins_take": 0.30}
    assert access["viewer"]["signer_name"] == "Dana Levi" and access["viewer"]["label"] == "Investor ACME"
    assert access["viewer"]["access_until"] and access["viewer"]["idle_timeout_seconds"] == 900
    assert access["viewer"]["nda_doc_instance_id"] == instance and access["viewer"]["nda_ledger"] == ledger

    # … but never the downloads.
    for path in ("/investor-docs/phins-unified-business-plan.pdf", "/investor-docs/phins-unified-business-plan.he.md",
                 "/pitch-dashboard.html"):
        assert recipient.get(f"{BASE_URL}{path}", timeout=10, allow_redirects=False).status_code != 200, path

    # Locked factors are pinned to the saved baseline and reported.
    model = recipient.get(f"{BASE_URL}/api/business-plan/model",
                          params={"phins_take": 0.22, "wacc": 0.25, "charts": 1, "lang": "he"}, timeout=10).json()
    assert model["inputs"]["phins_take"] == 0.22
    assert model["inputs"]["wacc"] == bpm.FACTOR_INDEX["wacc"]["default"]
    assert model["restricted"] == ["wacc"] and model["integrity"]["all_hold"] is True
    assert model["charts"] and any("\u05d0" <= ch <= "\u05ea" for ch in model["charts"][0]["title"])
    # Staff are not restricted by the whitelist.
    staff_model = admin.get(f"{BASE_URL}/api/business-plan/model", params={"wacc": 0.25}, timeout=10).json()
    assert staff_model["inputs"]["wacc"] == 0.25 and "restricted" not in staff_model

    # Single use: a second signer is refused; the first keeps the view.
    second = requests.post(f"{BASE_URL}/api/confidential/share-unlock",
                           json={"share_id": share["id"], "password": "guest-open", "path": PLAN,
                                 "nda_accepted": True, "signer_name": "Someone Else"}, timeout=10)
    assert second.status_code == 400
    assert recipient.get(f"{BASE_URL}{PLAN}", timeout=10).status_code == 200

    # The admin sees who signed and when; revoking closes the live view.
    listed = admin.get(f"{BASE_URL}/api/confidential/shares", timeout=10).json()["items"]
    mine = next(item for item in listed if item["id"] == share["id"])
    assert mine["nda_acceptances"][0]["signer_name"] == "Dana Levi" and mine["openings"][0]["access_until"]
    assert admin.delete(f"{BASE_URL}/api/confidential/shares/{share['id']}", timeout=10).status_code == 200
    assert recipient.get(f"{BASE_URL}{PLAN}", timeout=10, allow_redirects=False).status_code == 401
    assert recipient.get(f"{BASE_URL}/api/business-plan/access", timeout=10).status_code == 401


def test_http_factors_write_is_admin_only(closed_gate):
    anonymous = requests.post(f"{BASE_URL}/api/business-plan/factors", json={"factors": {}}, timeout=10)
    assert anonymous.status_code == 401
    login = requests.post(f"{BASE_URL}/api/login", json={"username": "accountant", "password": "acc123"}, timeout=10)
    if login.status_code == 200:
        staff = requests.post(f"{BASE_URL}/api/business-plan/factors", json={"factors": {}},
                              headers={"Authorization": f"Bearer {login.json()['token']}"}, timeout=10)
        assert staff.status_code == 403


def test_http_public_mode_in_test_harness_still_serves_the_page():
    """No token, non-production (the harness default): the page stays open and
    the access view says so — the existing public tests keep their contract."""
    page = requests.get(f"{BASE_URL}{PLAN}", timeout=10)
    assert page.status_code == 200 and "Adjustable factors" in page.text
    access = requests.get(f"{BASE_URL}/api/business-plan/access", timeout=10).json()
    assert access["mode"] in ("public", "staff") and access["adjustable"] == "all"


def test_share_cookie_does_not_open_a_different_link():
    env = {"SESSION_SECRET_KEY": SECRET, "PHINS_ENVIRONMENT": "production",
           "PHINS_CONFIDENTIAL_ACCESS_TOKEN": TOKEN}
    cookie = ca.mint_share_cookie(share_id="shr_first", path=PLAN, environ=env, session_key="sess1")
    header = f"{ca.SHARE_COOKIE_NAME}={cookie}"

    def check(sid, path, sk=""):
        return sid == "shr_first" and sk == "sess1"

    opened = ca.evaluate_access(PLAN, cookie_header=header, environ=env, share_active_check=check)
    assert opened.allowed and opened.share_id == "shr_first"
    same = ca.evaluate_access(PLAN, cookie_header=header, environ=env, share_active_check=check,
                              query_params={"share": ["shr_first"]})
    assert same.allowed
    other = ca.evaluate_access(PLAN, cookie_header=header, environ=env, share_active_check=check,
                               query_params={"share": ["shr_second"]})
    assert other.allowed is False and other.reason == "share_password_required" and other.share_id == "shr_second"


def test_nda_share_without_a_signed_session_is_closed(store):
    share = store.create_share(path=PLAN, password="open1234", max_uses=3, label="ACME", nda_required=True)
    assert not store.share_is_active_for_path(share["id"], PLAN)
    view, _ = store.unlock(share["id"], "open1234", nda_accepted=True, signer_name="Dana Levi")
    assert store.share_is_active_for_path(share["id"], PLAN, session_key=view["session_key"])
    for mode in ("single", "multi", "unlimited"):
        body_mode = {"single": 1, "multi": 5, "unlimited": None}[mode]
        made = store.create_share(path=PLAN, password="open1234", max_uses=body_mode, label="ACME", nda_required=True)
        with pytest.raises(ShareError, match="NDA"):
            store.unlock(made["id"], "open1234")
        assert store.get_share(made["id"])["used_count"] == 0


def test_filter_removes_unchosen_chapters_and_factor_controls():
    from services.business_plan_parts import PartsError, filter_share_html, freeze_visible_parts

    html = (
        '<nav><a href="#part-deck">Deck</a><a href="#plan-exec">Plan</a></nav>'
        '<section id="plan-exec">Executive</section>'
        '<div id="part-deck"><h2>Investor deck</h2></div><div class="bp-deck"><article>Slide</article></div>'
        '<div class="bp-founder-photo"><img src="/api/business-plan/founder-portrait"></div>'
        '<script type="application/json" id="bp-factors">[{"id":"phins_take"},{"id":"wacc"}]</script>'
    )
    kept = filter_share_html(html, visible_parts=["plan-exec"], viewer_adjustable=["phins_take"])
    assert "Executive" in kept and "Investor deck" not in kept and "Slide" not in kept
    assert "bp-founder-photo" not in kept and "founder-portrait" not in kept
    assert "Deck" not in kept and "phins_take" in kept and "wacc" not in kept
    with pytest.raises(PartsError):
        freeze_visible_parts(["not-a-chapter"])
    page = (Path(__file__).resolve().parents[1] / "web_portal" / "static" / "business-plan.html").read_text(encoding="utf-8")
    redacted = filter_share_html(page, visible_parts=["plan-exec", "factor-panel"], viewer_adjustable=["phins_take"])
    assert 'id="plan-exec"' in redacted and 'id="part-deck"' not in redacted
    assert 'class="bp-deck"' not in redacted and 'class="bp-founder-photo"' not in redacted
    assert 'id="appendix-i"' not in redacted and 'id="bp-factor-panel"' in redacted
    compact = redacted.replace(" ", "")
    assert '"id":"wacc"' not in compact
    assert '"id":"phins_take"' in compact


def test_signed_archive_seals_the_terms_and_rejects_a_tampered_file(tmp_path):
    import hashlib
    from services.signed_document_archive import ArchiveError, SignedDocumentArchive

    text = "Non-Disclosure Agreement\nReceiving Party ACME\n"
    digest = hashlib.sha256(text.encode()).hexdigest()
    archive = SignedDocumentArchive(str(tmp_path / "signed"))
    assert not archive.directory.exists()
    with pytest.raises(ArchiveError):
        archive.store({"nda_text": text, "nda_sha256": "0" * 64, "doc_instance_id": "LGL-NDA-X", "entry_id": "LGLSIG-1"})
    archive_id = archive.store({
        "nda_text": text, "nda_sha256": digest, "doc_instance_id": "LGL-NDA-X", "entry_id": "LGLSIG-1",
        "signer_name": "Dana Levi", "label": "ACME", "sequence_no": 1, "share_id": "shr_x",
    })
    assert archive.directory.is_dir()
    assert archive.list_documents()[0]["signer_name"] == "Dana Levi"
    assert archive.get(archive_id)["nda_text"] == text
    path = archive.directory / f"{archive_id}.json"
    path.write_text(path.read_text(encoding="utf-8").replace("Dana Levi", "Pat Doe"), encoding="utf-8")
    listed = archive.list_documents()
    assert listed[0]["intact"] is False
    with pytest.raises(ArchiveError):
        archive.get(archive_id)


def test_http_link_freezes_structure_and_hides_unchosen_factors(closed_gate):
    from services.business_plan_parts import part_ids

    admin = _admin_session()
    saved = admin.post(f"{BASE_URL}/api/business-plan/factors", json={
        "factors": {"phins_take": 0.30},
        "viewer_adjustable": ["phins_take"],
        "visible_parts": ["plan-exec", "plan-financials", "factor-panel"],
    }, timeout=10)
    assert saved.status_code == 200, saved.text
    assert saved.json()["settings"]["visible_parts"] == ["plan-exec", "plan-financials", "factor-panel"]

    create = admin.post(f"{BASE_URL}/api/confidential/shares", json={
        "path": PLAN, "password": "guest-open", "mode": "unlimited", "label": "Redacted Reader",
    }, timeout=10)
    assert create.status_code == 201, create.text
    share = create.json()["share"]
    assert share["composition"]["visible_parts"] == ["plan-exec", "plan-financials", "factor-panel"]
    assert share["composition"]["viewer_adjustable"] == ["phins_take"]
    assert share["composition"]["saved_factors"] == {"phins_take": 0.30}
    # Unlimited still requires the NDA; nothing is consumed by the refusal.
    refused = requests.post(f"{BASE_URL}/api/confidential/share-unlock",
                            json={"share_id": share["id"], "password": "guest-open", "path": PLAN}, timeout=10)
    assert refused.status_code == 400 and "nda" in refused.json()["error"].lower()
    assert admin.get(f"{BASE_URL}/api/confidential/shares", timeout=10).json()["items"]
    listed = next(item for item in admin.get(f"{BASE_URL}/api/confidential/shares", timeout=10).json()["items"] if item["id"] == share["id"])
    assert listed["used_count"] == 0

    reader = requests.Session()
    opened = reader.post(f"{BASE_URL}/api/confidential/share-unlock", json={
        "share_id": share["id"], "password": "guest-open", "path": PLAN,
        "nda_accepted": True, "signer_name": "Noa Katz",
    }, timeout=10)
    assert opened.status_code == 200, opened.text
    page = reader.get(f"{BASE_URL}{PLAN}", timeout=10)
    assert page.status_code == 200
    assert 'id="plan-exec"' in page.text and 'id="plan-financials"' in page.text
    # Style rules may still name a hidden class. The elements themselves are gone.
    assert 'id="part-deck"' not in page.text and 'class="bp-deck"' not in page.text
    assert 'class="bp-founder-photo"' not in page.text
    assert 'id="appendix-i"' not in page.text
    assert '"id": "phins_take"' in page.text or '"id":"phins_take"' in page.text
    assert '"id": "wacc"' not in page.text and '"id":"wacc"' not in page.text
    # A later admin edit does not reopen chapters on the link already sent.
    admin.post(f"{BASE_URL}/api/business-plan/factors", json={
        "factors": {"phins_take": 0.30}, "viewer_adjustable": "all", "visible_parts": "all",
    }, timeout=10)
    again = reader.get(f"{BASE_URL}{PLAN}", timeout=10).text
    assert 'id="part-deck"' not in again
    access = reader.get(f"{BASE_URL}/api/business-plan/access", timeout=10).json()
    assert access["visible_parts"] == ["plan-exec", "plan-financials", "factor-panel"]
    assert access["adjustable"] == ["phins_take"]
    assert access["saved_factors"] == {"phins_take": 0.30}
    portrait = reader.get(f"{BASE_URL}/api/business-plan/founder-portrait", timeout=10)
    assert portrait.status_code == 404
    # Staff still see every chapter.
    staff_page = admin.get(f"{BASE_URL}{PLAN}", timeout=10).text
    assert 'id="part-deck"' in staff_page and len(part_ids()) > 3
