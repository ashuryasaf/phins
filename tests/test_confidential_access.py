"""Confidential-document access gate (F3).

``web_portal/static`` is served with path-traversal protection only, so before
the gate the investor business plans under ``/internal/`` and the corporate
instruments under ``/legal/`` (cap table, term sheet, shareholders/employment
agreements, financial model) were readable by anyone who knew the URL — and
``robots.txt`` advertises ``/internal/``. The same applies to
``/api/legal-docs/*``, which returns anchored signer names and the signed
content snapshot for a document instance.

These tests pin the decision matrix in ``security.confidential_access`` plus the
HTTP behaviour of the embedded test server.
"""

import os

import pytest
import requests

from security import confidential_access as ca

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")

TOKEN = "t" * 40


# ---------------------------------------------------------------------------
# Path classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        "/internal/phins-investor-business-plan.html",
        "/internal/",
        "/legal/cap-table.html",
        "/legal/term-sheet.html",
        "/pitch-dashboard.html",
        "/api/legal-docs/registry",
        "/api/legal-docs/sign",
        "/api/legal-docs/verify",
        "/INTERNAL/phins-investor-business-plan.html",  # case-insensitive
    ],
)
def test_confidential_paths_are_recognised(path):
    assert ca.is_confidential_path(path, {}) is True


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/index.html",
        "/dashboard.html",
        "/api/health",
        "/api/fx/rates",
        # Shared assets under a gated prefix must stay readable, otherwise a 401
        # on the stylesheet breaks an authorised page.
        "/legal/legal-docs.css",
        "/legal/legal-docs.js",
    ],
)
def test_public_paths_are_not_gated(path):
    assert ca.is_confidential_path(path, {}) is False


def test_operator_can_extend_the_gated_list():
    env = {"PHINS_CONFIDENTIAL_PATHS": "/board/ /secret-plan.html"}
    assert ca.is_confidential_path("/board/minutes.html", env) is True
    assert ca.is_confidential_path("/secret-plan.html", env) is True
    assert ca.is_confidential_path("/public.html", env) is False


# ---------------------------------------------------------------------------
# Decision matrix
# ---------------------------------------------------------------------------

def test_staff_session_is_allowed_without_a_token():
    decision = ca.evaluate_access(
        "/legal/cap-table.html",
        session={"role": "admin"},
        environ={"PHINS_ENVIRONMENT": "production"},
    )
    assert decision.allowed is True
    assert decision.reason == "staff_session"


def test_customer_session_is_not_treated_as_staff():
    decision = ca.evaluate_access(
        "/legal/cap-table.html",
        session={"role": "customer"},
        environ={"PHINS_ENVIRONMENT": "production", "PHINS_CONFIDENTIAL_ACCESS_TOKEN": TOKEN},
    )
    assert decision.allowed is False


def test_production_without_token_fails_closed():
    """The core F3 regression: no silent anonymous serving in production."""
    decision = ca.evaluate_access(
        "/internal/phins-investor-business-plan.html",
        environ={"PHINS_ENVIRONMENT": "production"},
    )
    assert decision.allowed is False
    assert decision.reason == "not_configured_production"
    assert decision.status == 503


def test_non_production_without_token_stays_open_for_local_dev():
    decision = ca.evaluate_access(
        "/internal/phins-investor-business-plan.html",
        environ={"PHINS_ENVIRONMENT": "development"},
    )
    assert decision.allowed is True
    assert decision.reason == "non_production_default"


def test_railway_pr_preview_without_token_fails_closed():
    """Public PR-preview hosts must not serve confidential docs anonymously,
    even though they inherit PHINS_ENVIRONMENT=production and the secrets
    policy treats them as non-production for startup purposes."""
    for railway_env in ("pr-539", "phins-pr-539"):
        decision = ca.evaluate_access(
            "/internal/phins-investor-business-plan.html",
            environ={
                "PHINS_ENVIRONMENT": "production",
                "RAILWAY_ENVIRONMENT": railway_env,
            },
        )
        assert decision.allowed is False
        assert decision.reason == "not_configured_production"
        assert decision.status == 503


def test_missing_token_is_denied_when_a_token_is_configured():
    decision = ca.evaluate_access(
        "/internal/phins-investor-business-plan.html",
        environ={"PHINS_CONFIDENTIAL_ACCESS_TOKEN": TOKEN, "PHINS_ENVIRONMENT": "development"},
    )
    assert decision.allowed is False
    assert decision.reason == "token_required"
    assert decision.status == 401


def test_wrong_token_is_denied():
    decision = ca.evaluate_access(
        "/legal/term-sheet.html",
        query_params={"access_token": ["wrong-token"]},
        environ={"PHINS_CONFIDENTIAL_ACCESS_TOKEN": TOKEN},
    )
    assert decision.allowed is False


def test_query_token_is_exchanged_for_a_cookie_and_redirected():
    """The token must not linger in history/Referer/access logs."""
    decision = ca.evaluate_access(
        "/internal/phins-investor-business-plan.html?access_token=" + TOKEN,
        query_params={"access_token": [TOKEN]},
        environ={"PHINS_CONFIDENTIAL_ACCESS_TOKEN": TOKEN},
    )
    assert decision.allowed is True
    assert decision.set_cookie is True
    assert decision.redirect_to == "/internal/phins-investor-business-plan.html"
    assert TOKEN not in decision.redirect_to


def test_valid_cookie_is_allowed_and_carries_a_derived_value():
    cookie = f"{ca.ACCESS_COOKIE_NAME}={ca.cookie_value_for_token(TOKEN)}"
    decision = ca.evaluate_access(
        "/legal/cap-table.html",
        cookie_header=cookie,
        environ={"PHINS_CONFIDENTIAL_ACCESS_TOKEN": TOKEN, "PHINS_ENVIRONMENT": "production"},
    )
    assert decision.allowed is True
    assert decision.reason == "access_cookie"
    # The raw shared secret is never placed in the cookie jar.
    assert ca.cookie_value_for_token(TOKEN) != TOKEN
    assert TOKEN not in ca.cookie_value_for_token(TOKEN)


def test_explicit_public_optout_is_honoured():
    decision = ca.evaluate_access(
        "/internal/phins-investor-business-plan.html",
        environ={"PHINS_ENVIRONMENT": "production", "PHINS_CONFIDENTIAL_DOCS_PUBLIC": "true"},
    )
    assert decision.allowed is True
    assert decision.reason == "explicitly_public"
    assert decision.warnings


def test_investor_token_alias_is_accepted():
    decision = ca.evaluate_access(
        "/internal/phins-investor-business-plan.html",
        cookie_header=f"{ca.ACCESS_COOKIE_NAME}={ca.cookie_value_for_token(TOKEN)}",
        environ={"PHINS_INVESTOR_ACCESS_TOKEN": TOKEN},
    )
    assert decision.allowed is True


def test_non_confidential_path_is_never_gated_even_in_production():
    decision = ca.evaluate_access("/dashboard.html", environ={"PHINS_ENVIRONMENT": "production"})
    assert decision.allowed is True
    assert decision.confidential is False


# ---------------------------------------------------------------------------
# Token handling helpers
# ---------------------------------------------------------------------------

def test_token_comparison_rejects_prefixes():
    assert ca.token_matches(TOKEN[:-1], TOKEN, hashed=False) is False
    assert ca.token_matches(TOKEN + "x", TOKEN, hashed=False) is False
    assert ca.token_matches(TOKEN, TOKEN, hashed=False) is True
    assert ca.token_matches("", TOKEN, hashed=False) is False
    assert ca.token_matches(TOKEN, "", hashed=False) is False


def test_sensitive_query_values_are_redacted_for_logs():
    line = f"GET /internal/plan.html?access_token={TOKEN}&x=1 HTTP/1.1"
    redacted = ca.redact_sensitive_query(line)
    assert TOKEN not in redacted
    assert "access_token=REDACTED" in redacted
    assert "x=1" in redacted
    assert ca.has_sensitive_query(line) is True
    assert ca.has_sensitive_query("GET /internal/plan.html HTTP/1.1") is False


def test_strip_sensitive_query_preserves_other_params():
    assert ca.strip_sensitive_query(f"/a.html?access_token={TOKEN}") == "/a.html"
    assert ca.strip_sensitive_query(f"/a.html?doc=1&access_token={TOKEN}") == "/a.html?doc=1"
    assert ca.strip_sensitive_query("/a.html?doc=1") == "/a.html?doc=1"


def test_cookie_is_httponly_and_samesite_lax():
    header = ca.access_cookie_header("abc", secure=True, environ={})
    assert "HttpOnly" in header
    assert "SameSite=Lax" in header
    assert "Secure" in header
    assert header.startswith(f"{ca.ACCESS_COOKIE_NAME}=abc")
    # Plain-HTTP local runs must not receive a Secure cookie they cannot send.
    assert "Secure" not in ca.access_cookie_header("abc", secure=False, environ={})


def test_startup_warning_when_production_has_no_token():
    warnings = ca.startup_warnings({"PHINS_ENVIRONMENT": "production"})
    assert any("DENIED in production" in w for w in warnings)


def test_startup_warning_for_a_weak_token():
    warnings = ca.startup_warnings({"PHINS_CONFIDENTIAL_ACCESS_TOKEN": "short"})
    assert any("shorter than 24 characters" in w for w in warnings)


# ---------------------------------------------------------------------------
# HTTP behaviour against the embedded server (test mode: gate stays open)
# ---------------------------------------------------------------------------

def test_confidential_page_is_served_in_test_mode():
    """Test mode is non-production, so local/CI flows keep working."""
    r = requests.get(f"{BASE_URL}/internal/phins-investor-business-plan.html", timeout=10)
    assert r.status_code == 200
    assert "PHINS" in r.text


def test_registry_still_reachable_in_test_mode():
    r = requests.get(
        f"{BASE_URL}/api/legal-docs/registry", params={"doc_id": "LGL-DOES-NOT-EXIST"}, timeout=10
    )
    assert r.status_code == 200
    assert r.json()["total"] == 0


def test_shared_legal_assets_are_not_blocked():
    for asset in ("/legal/legal-docs.css", "/legal/legal-docs.js"):
        r = requests.get(f"{BASE_URL}{asset}", timeout=10)
        assert r.status_code == 200, asset


def test_robots_disallows_the_gated_paths():
    """Defence in depth: the gate is the control, robots stops indexing."""
    r = requests.get(f"{BASE_URL}/robots.txt", timeout=10)
    assert r.status_code == 200
    for path in ("/internal/", "/legal/", "/pitch-dashboard.html"):
        assert f"Disallow: {path}" in r.text, path


@pytest.fixture
def gate_token(monkeypatch):
    """Configure a shared access token on the running embedded server.

    The pytest harness runs the handler in-process, so the gate — which reads
    the environment per request — picks this up immediately.
    """
    monkeypatch.setenv("PHINS_CONFIDENTIAL_ACCESS_TOKEN", TOKEN)
    return TOKEN


def test_http_confidential_page_denied_without_token(gate_token):
    r = requests.get(
        f"{BASE_URL}/internal/phins-investor-business-plan.html",
        timeout=10,
        allow_redirects=False,
    )
    assert r.status_code == 401
    assert "Access restricted" in r.text
    # The document itself must not leak in the denial body.
    assert "Pre-launch build budget" not in r.text


def test_http_confidential_page_allowed_with_token_then_cookie(gate_token):
    # 1. Token in the query string is accepted, exchanged for a cookie, and the
    #    caller is redirected to the bare URL.
    r = requests.get(
        f"{BASE_URL}/internal/phins-investor-business-plan.html",
        params={"access_token": gate_token},
        timeout=10,
        allow_redirects=False,
    )
    assert r.status_code == 302
    assert r.headers["Location"] == "/internal/phins-investor-business-plan.html"
    assert gate_token not in r.headers["Location"]

    set_cookie = r.headers.get("Set-Cookie", "")
    assert ca.ACCESS_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie
    # The raw shared secret is never handed back to the browser.
    assert gate_token not in set_cookie

    # 2. The issued cookie alone grants access.
    session = requests.Session()
    session.cookies.set(ca.ACCESS_COOKIE_NAME, ca.cookie_value_for_token(gate_token))
    allowed = session.get(
        f"{BASE_URL}/internal/phins-investor-business-plan.html", timeout=10
    )
    assert allowed.status_code == 200
    assert "PHINS" in allowed.text


def test_http_legal_document_denied_without_token(gate_token):
    r = requests.get(f"{BASE_URL}/legal/cap-table.html", timeout=10, allow_redirects=False)
    assert r.status_code == 401


def test_http_registry_denied_without_token(gate_token):
    """Signature registry leaks signer names + signed content; gate it too."""
    r = requests.get(
        f"{BASE_URL}/api/legal-docs/registry",
        params={"doc_id": "LGL-TERM-SHEET-WHATEVER"},
        timeout=10,
    )
    assert r.status_code == 401
    assert "error" in r.json()


def test_http_sign_denied_without_token(gate_token):
    r = requests.post(
        f"{BASE_URL}/api/legal-docs/sign",
        json={
            "docType": "term-sheet",
            "docInstanceId": "LGL-TERM-SHEET-GATED",
            "role": "Investor",
            "signerName": "Anon",
            "documentHash": "a" * 64,
        },
        timeout=10,
    )
    assert r.status_code == 401


def test_http_public_pages_unaffected_by_the_gate(gate_token):
    for path in ("/", "/api/health", "/api/fx/rates"):
        r = requests.get(f"{BASE_URL}{path}", timeout=10)
        assert r.status_code == 200, path


def test_repeated_denials_do_not_ban_the_caller(gate_token):
    """A missing/expired token is not an attack.

    Routing denials through ``log_malicious_attempt`` would count toward the
    permanent IP block (MAX_MALICIOUS_ATTEMPTS), so an invited counterparty with
    an expired cookie — or a whole office behind one NAT address — could lock
    itself out. Denials must stay non-punitive and the caller must still be able
    to authenticate afterwards.
    """
    for _ in range(12):
        denied = requests.get(
            f"{BASE_URL}/internal/phins-investor-business-plan.html",
            timeout=10,
            allow_redirects=False,
        )
        assert denied.status_code == 401

    # Public pages still work...
    assert requests.get(f"{BASE_URL}/api/health", timeout=10).status_code == 200
    # ...and presenting the token now succeeds.
    session = requests.Session()
    session.cookies.set(ca.ACCESS_COOKIE_NAME, ca.cookie_value_for_token(gate_token))
    allowed = session.get(
        f"{BASE_URL}/internal/phins-investor-business-plan.html", timeout=10
    )
    assert allowed.status_code == 200


# ---------------------------------------------------------------------------
# Admin password unlock + share links
# ---------------------------------------------------------------------------

SECRET = "s" * 40


def test_denial_page_offers_admin_unlock_form():
    decision = ca.AccessDecision(
        allowed=False,
        reason="not_configured_production",
        confidential=True,
        status=503,
    )
    html = ca.denial_html(decision, path="/pitch-dashboard.html")
    assert "admin-unlock-form" in html
    assert "/api/confidential/admin-unlock" in html
    assert "Staff / admin unlock" in html
    # Branded gate surface — logo + PHINS wordmark, no document body leak.
    assert "/phins-logo.svg" in html
    assert "PHINS" in html
    assert "gate-card" in html
    assert "Access restricted" in html
    assert 'value="admin"' in html
    assert "Staff password unlock is required" in ca.denial_payload(decision)["error"]
    assert "Pre-launch build budget" not in html


def test_pitch_dashboard_production_requires_password_unlock():
    """Live pitch-dashboard must stay fail-closed until staff/share unlock."""
    env = {"PHINS_ENVIRONMENT": "production", "SESSION_SECRET_KEY": SECRET}
    denied = ca.evaluate_access("/pitch-dashboard.html", environ=env)
    assert denied.allowed is False
    assert denied.reason == "not_configured_production"
    assert denied.status == 503

    cookie = ca.mint_staff_unlock_cookie(
        username="admin", role="admin", environ=env
    )
    allowed = ca.evaluate_access(
        "/pitch-dashboard.html",
        cookie_header=f"{ca.STAFF_UNLOCK_COOKIE_NAME}={cookie}",
        environ=env,
    )
    assert allowed.allowed is True
    assert allowed.reason == "staff_unlock_cookie"


def test_staff_unlock_cookie_grants_access_without_global_token():
    env = {"PHINS_ENVIRONMENT": "production", "SESSION_SECRET_KEY": SECRET}
    cookie = ca.mint_staff_unlock_cookie(
        username="admin", role="admin", environ=env
    )
    decision = ca.evaluate_access(
        "/pitch-dashboard.html",
        cookie_header=f"{ca.STAFF_UNLOCK_COOKIE_NAME}={cookie}",
        environ=env,
    )
    assert decision.allowed is True
    assert decision.reason == "staff_unlock_cookie"


def test_share_cookie_grants_html_but_not_download():
    env = {"PHINS_ENVIRONMENT": "production", "SESSION_SECRET_KEY": SECRET}
    share_cookie = ca.mint_share_cookie(
        share_id="shr_test",
        path="/pitch-dashboard.html",
        environ=env,
    )
    html_ok = ca.evaluate_access(
        "/pitch-dashboard.html",
        cookie_header=f"{ca.SHARE_COOKIE_NAME}={share_cookie}",
        environ=env,
    )
    assert html_ok.allowed is True
    assert html_ok.reason == "share_cookie"

    download_denied = ca.evaluate_access(
        "/phins_business_plan_executive.pdf",
        cookie_header=f"{ca.SHARE_COOKIE_NAME}={share_cookie}",
        environ=env,
    )
    assert download_denied.allowed is False
    assert download_denied.downloadable is True


def test_mint_share_cookie_rejects_download_paths():
    env = {"SESSION_SECRET_KEY": SECRET}
    with pytest.raises(ValueError):
        ca.mint_share_cookie(
            share_id="shr_x",
            path="/internal/exec-actuary-briefing.pdf",
            environ=env,
        )


def test_share_query_requests_password_form_in_production():
    env = {"PHINS_ENVIRONMENT": "production", "SESSION_SECRET_KEY": SECRET}
    decision = ca.evaluate_access(
        "/pitch-dashboard.html",
        query_params={"share": ["shr_abc"]},
        environ=env,
    )
    assert decision.allowed is False
    assert decision.reason == "share_password_required"
    assert decision.share_id == "shr_abc"
    html = ca.denial_html(decision, path="/pitch-dashboard.html", share_id="shr_abc")
    assert "share-unlock-form" in html
    assert "shr_abc" in html


@pytest.fixture
def share_store(tmp_path, monkeypatch):
    from services import confidential_share_service as css

    css.reset_confidential_share_service_for_tests()
    path = tmp_path / "confidential_shares.json"
    service = css.get_confidential_share_service(data_path=str(path))
    monkeypatch.setenv("SESSION_SECRET_KEY", SECRET)
    yield service
    css.reset_confidential_share_service_for_tests()


def test_share_service_rejects_downloadable_targets(share_store):
    from services.confidential_share_service import ShareError

    with pytest.raises(ShareError):
        share_store.create_share(
            path="/phins_business_plan_executive.pdf",
            password="open-sesame",
            max_uses=1,
        )


def test_share_service_single_use_integrity(share_store):
    from services.confidential_share_service import ShareError

    created = share_store.create_share(
        path="/pitch-dashboard.html",
        password="open-sesame",
        max_uses=1,
        label="Once",
    )
    assert created["mode"] == "single"
    public, target = share_store.unlock(created["id"], "open-sesame")
    assert target == "/pitch-dashboard.html"
    assert public["used_count"] == 1
    assert public["status"] == "exhausted"
    # Cookie holders may still view after exhaustion; new unlocks must fail.
    assert share_store.share_is_active_for_path(created["id"], "/pitch-dashboard.html")
    with pytest.raises(ShareError):
        share_store.unlock(created["id"], "open-sesame")


def test_share_service_multi_use_and_wrong_password(share_store):
    from services.confidential_share_service import ShareError

    created = share_store.create_share(
        path="/legal/cap-table.html",
        password="multi-pass",
        max_uses=3,
    )
    assert created["mode"] == "multi"
    share_store.unlock(created["id"], "multi-pass")
    share_store.unlock(created["id"], "multi-pass")
    assert share_store.get_share(created["id"])["remaining_uses"] == 1
    with pytest.raises(ShareError):
        share_store.unlock(created["id"], "wrong-password")
    # Wrong password must not consume a use.
    assert share_store.get_share(created["id"])["remaining_uses"] == 1


def test_http_open_password_unlock_via_admin_form(gate_token, monkeypatch):
    """Deployment open password entered on the gate form unlocks pitch-dashboard."""
    monkeypatch.setenv("PHINS_ENVIRONMENT", "production")
    monkeypatch.setenv("SESSION_SECRET_KEY", SECRET)
    monkeypatch.setenv("PHINS_CONFIDENTIAL_ACCESS_TOKEN", TOKEN)

    session = requests.Session()
    unlock = session.post(
        f"{BASE_URL}/api/confidential/admin-unlock",
        json={"username": "admin", "password": TOKEN, "next": "/pitch-dashboard.html"},
        timeout=10,
    )
    assert unlock.status_code == 200, unlock.text
    body = unlock.json()
    assert body.get("success") is True
    assert body.get("unlock_mode") == "open_password"
    assert ca.ACCESS_COOKIE_NAME in unlock.headers.get("Set-Cookie", "")

    viewed = session.get(f"{BASE_URL}/pitch-dashboard.html", timeout=10)
    assert viewed.status_code == 200
    assert "Access restricted" not in viewed.text
    assert "pitch-top" in viewed.text or "PHINS" in viewed.text


def test_http_admin_unlock_and_share_flow(gate_token, share_store, monkeypatch):
    """End-to-end: admin unlock → create share → recipient opens with password."""
    monkeypatch.setenv("PHINS_ENVIRONMENT", "production")
    monkeypatch.setenv("SESSION_SECRET_KEY", SECRET)
    # Keep the global token configured so the gate stays closed for anonymous
    # callers in this harness (test mode is otherwise open).
    monkeypatch.setenv("PHINS_CONFIDENTIAL_ACCESS_TOKEN", TOKEN)

    denied = requests.get(
        f"{BASE_URL}/pitch-dashboard.html", timeout=10, allow_redirects=False
    )
    assert denied.status_code == 401
    assert "admin-unlock-form" in denied.text

    unlock = requests.post(
        f"{BASE_URL}/api/confidential/admin-unlock",
        json={"username": "admin", "password": "admin123", "next": "/pitch-dashboard.html"},
        timeout=10,
    )
    assert unlock.status_code == 200, unlock.text
    unlock_body = unlock.json()
    assert unlock_body.get("success") is True
    assert unlock_body.get("token")
    assert ca.STAFF_UNLOCK_COOKIE_NAME in unlock.headers.get("Set-Cookie", "")

    admin = requests.Session()
    admin.headers["Authorization"] = f"Bearer {unlock_body['token']}"
    # Carry the staff unlock cookie from the unlock response.
    if unlock.cookies:
        admin.cookies.update(unlock.cookies)

    create = admin.post(
        f"{BASE_URL}/api/confidential/shares",
        json={
            "path": "/pitch-dashboard.html",
            "password": "guest-open",
            "mode": "single",
            "label": "Guest one-shot",
        },
        timeout=10,
    )
    assert create.status_code == 201, create.text
    share = create.json()["share"]
    assert share["mode"] == "single"
    assert "password" not in share
    assert "password_hash" not in share

    # Recipient without auth sees the share password form.
    share_page = requests.get(
        f"{BASE_URL}/pitch-dashboard.html",
        params={"share": share["id"]},
        timeout=10,
        allow_redirects=False,
    )
    assert share_page.status_code == 401
    assert "share-unlock-form" in share_page.text

    recipient = requests.Session()
    opened = recipient.post(
        f"{BASE_URL}/api/confidential/share-unlock",
        json={
            "share_id": share["id"],
            "password": "guest-open",
            "path": "/pitch-dashboard.html",
        },
        timeout=10,
    )
    assert opened.status_code == 200, opened.text
    assert ca.SHARE_COOKIE_NAME in opened.headers.get("Set-Cookie", "")

    viewed = recipient.get(f"{BASE_URL}/pitch-dashboard.html", timeout=10)
    assert viewed.status_code == 200
    assert "Access restricted" not in viewed.text

    # Single-use exhausted for a second recipient.
    second = requests.post(
        f"{BASE_URL}/api/confidential/share-unlock",
        json={
            "share_id": share["id"],
            "password": "guest-open",
            "path": "/pitch-dashboard.html",
        },
        timeout=10,
    )
    assert second.status_code == 400
    assert "remaining uses" in second.json()["error"].lower() or "exhausted" in second.json()["error"].lower()

    # Share cookie must not unlock a downloaded PDF.
    pdf = recipient.get(
        f"{BASE_URL}/phins_business_plan_executive.pdf",
        timeout=10,
        allow_redirects=False,
    )
    # File may 401 (gated) or 404 depending on on-disk casing; never 200 via share.
    assert pdf.status_code != 200


def test_http_create_share_rejects_pdf_target(gate_token, share_store, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET_KEY", SECRET)
    login = requests.post(
        f"{BASE_URL}/api/login",
        json={"username": "admin", "password": "admin123"},
        timeout=10,
    )
    assert login.status_code == 200
    token = login.json()["token"]
    resp = requests.post(
        f"{BASE_URL}/api/confidential/shares",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "path": "/phins_business_plan_executive.pdf",
            "password": "nope",
            "max_uses": 1,
        },
        timeout=10,
    )
    assert resp.status_code == 400
    assert "download" in resp.json()["error"].lower() or "pdf" in resp.json()["error"].lower() or "html" in resp.json()["error"].lower()


def test_cross_worker_single_use_is_atomic(tmp_path):
    """Two worker-like service instances must not both consume a single-use share.

    Simulates multi-process deployments: each instance keeps its own in-memory
    map, so only an exclusive file lock + reload-before-mutate keeps
    ``used_count`` honest across concurrent unlocks.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from services.confidential_share_service import (
        ConfidentialShareService,
        ShareError,
    )

    data_path = tmp_path / "confidential_shares.json"
    writer = ConfidentialShareService(data_path=str(data_path))
    created = writer.create_share(
        path="/pitch-dashboard.html",
        password="once-only",
        max_uses=1,
        label="cross-worker",
    )

    worker_a = ConfidentialShareService(data_path=str(data_path))
    worker_b = ConfidentialShareService(data_path=str(data_path))
    # Stale caches: both still see used_count=0 until they reacquire the store.
    assert worker_a.get_share(created["id"])["used_count"] == 0
    assert worker_b.get_share(created["id"])["used_count"] == 0

    outcomes = []

    def _try_unlock(service: ConfidentialShareService) -> str:
        try:
            service.unlock(created["id"], "once-only")
            return "ok"
        except ShareError:
            return "err"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_try_unlock, worker_a), pool.submit(_try_unlock, worker_b)]
        for future in as_completed(futures):
            outcomes.append(future.result())

    assert outcomes.count("ok") == 1, outcomes
    assert outcomes.count("err") == 1, outcomes

    # A third worker must also see exhaustion after reload.
    worker_c = ConfidentialShareService(data_path=str(data_path))
    with pytest.raises(ShareError):
        worker_c.unlock(created["id"], "once-only")
    final = worker_c.get_share(created["id"])
    assert final["used_count"] == 1
    assert final["status"] == "exhausted"


def test_stale_worker_reloads_before_unlock(tmp_path):
    """A worker that never saw the first unlock must still refuse a second use."""
    from services.confidential_share_service import (
        ConfidentialShareService,
        ShareError,
    )

    data_path = tmp_path / "confidential_shares.json"
    worker_a = ConfidentialShareService(data_path=str(data_path))
    created = worker_a.create_share(
        path="/legal/cap-table.html",
        password="relay",
        max_uses=1,
    )
    worker_b = ConfidentialShareService(data_path=str(data_path))
    worker_a.unlock(created["id"], "relay")
    with pytest.raises(ShareError):
        worker_b.unlock(created["id"], "relay")
    assert worker_b.get_share(created["id"])["used_count"] == 1
