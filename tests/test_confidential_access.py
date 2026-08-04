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


def test_cookie_is_httponly_and_samesite_strict():
    header = ca.access_cookie_header("abc", secure=True, environ={})
    assert "HttpOnly" in header
    assert "SameSite=Strict" in header
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
