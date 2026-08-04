"""Access gate for confidential (non-customer-facing) documents.

The platform serves several classes of genuinely confidential material out of
``web_portal/static`` — investor business plans under ``/internal/`` and
corporate legal instruments under ``/legal/`` (cap table, term sheet,
shareholders/employment agreements, financial model). The static file handler
only guards against path traversal, so before this module those documents were
reachable by anyone who knew (or guessed) the URL; ``robots.txt`` even
advertises ``/internal/``. Folder naming and a robots ``Disallow`` are not
access control.

This module centralises the decision so both the static handler and the
``/api/legal-docs/*`` endpoints (which expose anchored signatures, signer names
and the signed content snapshot for a document instance) apply exactly one
consistent rule.

Access is granted when any of the following holds:

1. the caller has an authenticated staff session (admin/accountant/... — the
   roles that legitimately review corporate documents),
2. the caller presents the shared access token configured in
   ``PHINS_CONFIDENTIAL_ACCESS_TOKEN`` (compared in constant time) via the
   ``phins_confidential_access`` cookie or a one-time ``?access_token=``
   query parameter,
3. the deployment is not production and no token is configured — local
   development and the pytest harness keep working unchanged,
4. an operator has explicitly opted into publishing the documents by setting
   ``PHINS_CONFIDENTIAL_DOCS_PUBLIC=true``.

In production with no token configured the gate fails closed: confidential
paths are denied rather than silently served to the internet.

Tokens supplied in the query string are exchanged for an HttpOnly cookie and
the caller is redirected to the bare path, so the secret does not linger in
browser history, ``Referer`` headers, or access logs. The cookie carries an
HMAC of the token rather than the token itself, so a stolen cookie cannot be
replayed as the shared secret elsewhere.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

# Cookie/query names for the shared-token exchange.
ACCESS_COOKIE_NAME = "phins_confidential_access"
ACCESS_QUERY_PARAM = "access_token"

# Query parameters whose values must never reach an access log.
SENSITIVE_QUERY_PARAMS = (ACCESS_QUERY_PARAM, "token", "access_key")

# Roles allowed to read corporate/investor documents with a normal session.
STAFF_ROLES = ("admin", "accountant", "underwriter", "actuary", "compliance", "founder")

# Confidential path prefixes (checked case-insensitively against the URL path).
DEFAULT_CONFIDENTIAL_PREFIXES = ("/internal/", "/legal/")

# Individually confidential files that do not live under a gated prefix.
DEFAULT_CONFIDENTIAL_FILES = ("/pitch-dashboard.html",)

# API endpoints that expose anchored signatures + signed content snapshots.
DEFAULT_CONFIDENTIAL_API_PATHS = (
    "/api/legal-docs/registry",
    "/api/legal-docs/sign",
    "/api/legal-docs/verify",
)

_TRUTHY = ("1", "true", "yes", "y", "on")

# Static assets that must stay readable even under a gated prefix, otherwise a
# 401 on the stylesheet would break the rendering of an authorised page.
_SHARED_ASSET_SUFFIXES = (".css", ".js", ".woff", ".woff2", ".ttf", ".svg", ".ico", ".png")


def _env(environ: Optional[Mapping[str, str]] = None) -> Mapping[str, str]:
    return environ if environ is not None else os.environ


def _flag(name: str, environ: Optional[Mapping[str, str]] = None) -> bool:
    return str(_env(environ).get(name, "")).strip().lower() in _TRUTHY


def is_production(environ: Optional[Mapping[str, str]] = None) -> bool:
    """Production detection, reusing the shared secrets policy when available."""
    env = _env(environ)
    try:
        from security.secrets_policy import _is_production

        return bool(_is_production(dict(env)))
    except Exception:
        if str(env.get("PHINS_TEST_MODE", "")).strip().lower() in _TRUTHY:
            return False
        return str(env.get("PHINS_ENVIRONMENT", "")).strip().lower() in (
            "production",
            "prod",
            "live",
        )


def configured_access_token(environ: Optional[Mapping[str, str]] = None) -> str:
    """Return the configured shared access token (empty when unset).

    ``PHINS_INVESTOR_ACCESS_TOKEN`` is accepted as an alias so an existing
    investor-only deployment can keep its variable name.
    """
    env = _env(environ)
    for name in ("PHINS_CONFIDENTIAL_ACCESS_TOKEN", "PHINS_INVESTOR_ACCESS_TOKEN"):
        value = str(env.get(name, "") or "").strip()
        if value:
            return value
    return ""


def docs_published_publicly(environ: Optional[Mapping[str, str]] = None) -> bool:
    """True when an operator has deliberately made confidential docs public."""
    return _flag("PHINS_CONFIDENTIAL_DOCS_PUBLIC", environ)


def cookie_value_for_token(token: str) -> str:
    """Derive the cookie value for a token.

    The cookie carries ``HMAC-SHA256(token, "phins-confidential-cookie-v1")``
    instead of the raw token so the shared secret is never stored in a browser
    cookie jar or echoed back in request headers.
    """
    return hmac.new(
        str(token or "").encode("utf-8"),
        b"phins-confidential-cookie-v1",
        hashlib.sha256,
    ).hexdigest()


def _confidential_targets(
    environ: Optional[Mapping[str, str]] = None,
) -> Tuple[Sequence[str], Sequence[str], Sequence[str]]:
    """Return (prefixes, files, api_paths), honouring operator extensions."""
    extra = str(_env(environ).get("PHINS_CONFIDENTIAL_PATHS", "") or "").strip()
    prefixes = list(DEFAULT_CONFIDENTIAL_PREFIXES)
    files = list(DEFAULT_CONFIDENTIAL_FILES)
    for raw in extra.replace(",", " ").split():
        entry = raw.strip()
        if not entry:
            continue
        if not entry.startswith("/"):
            entry = "/" + entry
        (prefixes if entry.endswith("/") else files).append(entry.lower())
    return tuple(prefixes), tuple(files), tuple(DEFAULT_CONFIDENTIAL_API_PATHS)


def is_shared_asset(path: str) -> bool:
    """True for stylesheet/script assets that an authorised page needs."""
    return str(path or "").lower().endswith(_SHARED_ASSET_SUFFIXES)


def is_confidential_path(
    path: str, environ: Optional[Mapping[str, str]] = None
) -> bool:
    """True when ``path`` addresses confidential material.

    Shared CSS/JS assets under a gated prefix are excluded: they carry no
    confidential content of their own and blocking them would break the
    rendering of a page the caller is authorised to read.
    """
    normalized = str(path or "").split("?", 1)[0].split("#", 1)[0].lower()
    if not normalized:
        return False
    prefixes, files, api_paths = _confidential_targets(environ)
    if normalized in api_paths:
        return True
    if normalized in files:
        return True
    if any(normalized.startswith(prefix) for prefix in prefixes):
        return not is_shared_asset(normalized)
    return False


def session_is_staff(session: Optional[Mapping[str, Any]]) -> bool:
    """True when the session belongs to a role allowed to read the documents."""
    if not session:
        return False
    role = str(session.get("role") or "").strip().lower()
    return role in STAFF_ROLES


def parse_cookies(cookie_header: Optional[str]) -> Dict[str, str]:
    """Parse a ``Cookie`` header into a plain dict (never raises)."""
    if not cookie_header:
        return {}
    try:
        jar = SimpleCookie()
        jar.load(cookie_header)
        return {key: morsel.value for key, morsel in jar.items()}
    except Exception:
        return {}


def token_matches(candidate: Optional[str], token: str, *, hashed: bool) -> bool:
    """Constant-time comparison of a supplied credential against the token."""
    if not token or not candidate:
        return False
    expected = cookie_value_for_token(token) if hashed else token
    return hmac.compare_digest(str(candidate).encode("utf-8"), expected.encode("utf-8"))


@dataclass
class AccessDecision:
    """Outcome of an access evaluation for a confidential path."""

    allowed: bool
    reason: str
    confidential: bool = False
    # Set the access cookie (token was accepted from the query string).
    set_cookie: bool = False
    cookie_value: str = ""
    # Redirect target that strips the token from the URL.
    redirect_to: Optional[str] = None
    status: int = 200
    warnings: list = field(default_factory=list)

    @property
    def requires_redirect(self) -> bool:
        return bool(self.redirect_to)


def evaluate_access(
    path: str,
    *,
    session: Optional[Mapping[str, Any]] = None,
    cookie_header: Optional[str] = None,
    query_params: Optional[Mapping[str, Iterable[str]]] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> AccessDecision:
    """Decide whether a request may read a confidential document.

    ``query_params`` accepts the ``urllib.parse.parse_qs`` shape (``{name:
    [values]}``) as produced by the server's request parsing.
    """
    env = _env(environ)
    if not is_confidential_path(path, env):
        return AccessDecision(allowed=True, reason="not_confidential", confidential=False)

    if session_is_staff(session):
        return AccessDecision(allowed=True, reason="staff_session", confidential=True)

    token = configured_access_token(env)

    if token:
        cookies = parse_cookies(cookie_header)
        if token_matches(cookies.get(ACCESS_COOKIE_NAME), token, hashed=True):
            return AccessDecision(allowed=True, reason="access_cookie", confidential=True)

        supplied = ""
        if query_params:
            raw = query_params.get(ACCESS_QUERY_PARAM)
            if isinstance(raw, (list, tuple)):
                supplied = str(raw[0]) if raw else ""
            elif raw is not None:
                supplied = str(raw)
        if supplied and token_matches(supplied, token, hashed=False):
            return AccessDecision(
                allowed=True,
                reason="access_token_query",
                confidential=True,
                set_cookie=True,
                cookie_value=cookie_value_for_token(token),
                redirect_to=strip_sensitive_query(path),
            )

        return AccessDecision(
            allowed=False,
            reason="token_required",
            confidential=True,
            status=401,
        )

    # No token configured.
    if docs_published_publicly(env):
        return AccessDecision(
            allowed=True,
            reason="explicitly_public",
            confidential=True,
            warnings=["PHINS_CONFIDENTIAL_DOCS_PUBLIC=true — confidential documents are served to anyone."],
        )

    if is_production(env):
        # Fail closed: never serve investor/corporate documents anonymously in
        # production just because the operator forgot to configure a token.
        return AccessDecision(
            allowed=False,
            reason="not_configured_production",
            confidential=True,
            status=503,
        )

    return AccessDecision(
        allowed=True,
        reason="non_production_default",
        confidential=True,
    )


def strip_sensitive_query(path: str) -> str:
    """Remove sensitive query parameters from a path, preserving the rest."""
    raw = str(path or "")
    base, sep, query = raw.partition("?")
    if not sep or not query:
        return base or "/"
    kept = []
    for part in query.split("&"):
        if not part:
            continue
        name = part.split("=", 1)[0].strip().lower()
        if name in SENSITIVE_QUERY_PARAMS:
            continue
        kept.append(part)
    return base + ("?" + "&".join(kept) if kept else "")


def redact_sensitive_query(path: str) -> str:
    """Replace sensitive query values with ``REDACTED`` for safe logging."""
    raw = str(path or "")
    base, sep, query = raw.partition("?")
    if not sep or not query:
        return raw
    parts = []
    for part in query.split("&"):
        if not part:
            continue
        name, eq, _value = part.partition("=")
        if name.strip().lower() in SENSITIVE_QUERY_PARAMS and eq:
            parts.append(f"{name}=REDACTED")
        else:
            parts.append(part)
    return base + "?" + "&".join(parts)


def has_sensitive_query(path: str) -> bool:
    """True when the path carries a credential-bearing query parameter."""
    _base, sep, query = str(path or "").partition("?")
    if not sep or not query:
        return False
    for part in query.split("&"):
        name, eq, _value = part.partition("=")
        if eq and name.strip().lower() in SENSITIVE_QUERY_PARAMS:
            return True
    return False


def access_cookie_header(
    cookie_value: str,
    *,
    secure: bool,
    max_age: Optional[int] = None,
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    """Build the ``Set-Cookie`` value for an accepted access token."""
    if max_age is None:
        try:
            max_age = int(
                str(_env(environ).get("PHINS_CONFIDENTIAL_COOKIE_MAX_AGE", "43200")).strip()
                or "43200"
            )
        except ValueError:
            max_age = 43200
    parts = [
        f"{ACCESS_COOKIE_NAME}={cookie_value}",
        "Path=/",
        f"Max-Age={max(60, int(max_age))}",
        "HttpOnly",
        "SameSite=Strict",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def denial_payload(decision: AccessDecision) -> Dict[str, str]:
    """JSON body for a denied confidential request (no content disclosure)."""
    if decision.reason == "not_configured_production":
        return {
            "error": (
                "Confidential documents are not available: no access token is "
                "configured on this deployment."
            )
        }
    return {"error": "Access token required for confidential documents."}


def denial_html(decision: AccessDecision) -> str:
    """Minimal HTML body for a denied confidential page request."""
    message = denial_payload(decision)["error"]
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        "<title>Access restricted</title></head><body "
        "style=\"font-family:system-ui,sans-serif;padding:2rem;max-width:40rem\">"
        "<h1 style=\"font-size:1.25rem\">Access restricted</h1>"
        f"<p>{message}</p>"
        "<p style=\"color:#666;font-size:.9rem\">If you were given a document "
        "link, open it with the access token included, or sign in with a staff "
        "account.</p></body></html>"
    )


def startup_warnings(environ: Optional[Mapping[str, str]] = None) -> list:
    """Operator-facing warnings about the confidential-document configuration."""
    env = _env(environ)
    warnings: list = []
    token = configured_access_token(env)
    if docs_published_publicly(env):
        warnings.append(
            "PHINS_CONFIDENTIAL_DOCS_PUBLIC=true — investor/corporate documents "
            "under /internal/ and /legal/ are served to anyone. Unset it to "
            "restore the access gate."
        )
    elif not token:
        if is_production(env):
            warnings.append(
                "PHINS_CONFIDENTIAL_ACCESS_TOKEN is not set — confidential "
                "documents under /internal/ and /legal/ are DENIED in "
                "production. Set the token to share them."
            )
        else:
            warnings.append(
                "PHINS_CONFIDENTIAL_ACCESS_TOKEN is not set — confidential "
                "documents are open on this non-production deployment."
            )
    elif len(token) < 24:
        warnings.append(
            "PHINS_CONFIDENTIAL_ACCESS_TOKEN is shorter than 24 characters; "
            "use a long random value (e.g. `openssl rand -hex 32`)."
        )
    return warnings
