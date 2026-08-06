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
2. the caller presents a staff unlock cookie issued after an admin-level
   password entry on the access-restricted page (works even when no shared
   access token is configured on the deployment),
3. the caller presents a valid share-link cookie for an HTML page (single-use
   or multi-use links with a simple open password — downloadable documents are
   excluded from share-link authorisation),
4. the caller presents the shared access token configured in
   ``PHINS_CONFIDENTIAL_ACCESS_TOKEN`` (compared in constant time) via the
   ``phins_confidential_access`` cookie or a one-time ``?access_token=``
   query parameter,
5. the deployment is not production and no token is configured — local
   development and the pytest harness keep working unchanged,
6. an operator has explicitly opted into publishing the documents by setting
   ``PHINS_CONFIDENTIAL_DOCS_PUBLIC=true``.

In production with no token configured the gate fails closed for anonymous
callers: confidential paths are denied rather than silently served. Admins can
still unlock via password, and recipients can unlock via share links.

Tokens supplied in the query string are exchanged for an HttpOnly cookie and
the caller is redirected to the bare path, so the secret does not linger in
browser history, ``Referer`` headers, or access logs. The cookie carries an
HMAC of the token rather than the token itself, so a stolen cookie cannot be
replayed as the shared secret elsewhere.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlencode

# Cookie/query names for the shared-token exchange.
ACCESS_COOKIE_NAME = "phins_confidential_access"
ACCESS_QUERY_PARAM = "access_token"
SHARE_COOKIE_NAME = "phins_confidential_share"
SHARE_QUERY_PARAM = "share"
STAFF_UNLOCK_COOKIE_NAME = "phins_confidential_staff"

# Query parameters whose values must never reach an access log.
SENSITIVE_QUERY_PARAMS = (
    ACCESS_QUERY_PARAM,
    "token",
    "access_key",
    SHARE_QUERY_PARAM,
)

# Roles allowed to read corporate/investor documents with a normal session.
STAFF_ROLES = ("admin", "accountant", "underwriter", "actuary", "compliance", "founder")

# Confidential path prefixes (checked case-insensitively against the URL path).
DEFAULT_CONFIDENTIAL_PREFIXES = ("/internal/", "/legal/")

# Individually confidential files that do not live under a gated prefix.
DEFAULT_CONFIDENTIAL_FILES = (
    "/pitch-dashboard.html",
    "/phins_business_plan_executive.pdf",
    "/phins_business_plan_executive.md",
)

# API endpoints that expose anchored signatures + signed content snapshots.
DEFAULT_CONFIDENTIAL_API_PATHS = (
    "/api/legal-docs/registry",
    "/api/legal-docs/sign",
    "/api/legal-docs/verify",
)

_TRUTHY = ("1", "true", "yes", "y", "on")

# Static assets that must stay readable even under a gated prefix, otherwise a
# 401 on the stylesheet/script/font would break the rendering of an authorised
# page. Image formats are deliberately excluded: a confidential diagram or
# export dropped under a gated prefix must not be served ungated just because it
# is a ``.png``/``.svg``/``.ico``.
_SHARED_ASSET_SUFFIXES = (".css", ".js", ".woff", ".woff2", ".ttf")

_DOWNLOAD_SUFFIXES = (
    ".pdf",
    ".md",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".csv",
    ".zip",
    ".pptx",
    ".ppt",
)

_SIGNED_COOKIE_PREFIX = "v1."
_STAFF_UNLOCK_TTL_DEFAULT = 12 * 60 * 60
_SHARE_COOKIE_TTL_DEFAULT = 12 * 60 * 60


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


def is_downloadable_document(path: str) -> bool:
    """True for export/download artefacts that share links must not unlock."""
    normalized = str(path or "").split("?", 1)[0].split("#", 1)[0].lower()
    return any(normalized.endswith(suffix) for suffix in _DOWNLOAD_SUFFIXES)


def normalize_request_path(path: str) -> str:
    """Pathname only, lowercased, without query/fragment."""
    return str(path or "").split("?", 1)[0].split("#", 1)[0].lower()


def signing_secret(environ: Optional[Mapping[str, str]] = None) -> str:
    """Secret used to mint staff-unlock and share cookies.

    Uses server-only secret material (``SESSION_SECRET_KEY`` then
    ``PHINS_ENCRYPTION_KEY``). The shared confidential access token is
    deliberately excluded: it is a widely distributed open password, so signing
    staff/share cookies with it would let anyone holding the token forge valid
    staff-unlock or share cookies without a password or use consumption. A weak
    fallback is only returned outside production so local/test flows still work
    when no secrets are configured.
    """
    env = _env(environ)
    for name in (
        "SESSION_SECRET_KEY",
        "PHINS_ENCRYPTION_KEY",
    ):
        value = str(env.get(name, "") or "").strip()
        if value:
            return value
    if is_production(env):
        return ""
    return "phins-confidential-dev-fallback"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padded = str(raw or "") + "=" * (-len(raw or "") % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _sign_payload(payload: Mapping[str, Any], secret: str) -> str:
    body = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    sig = hmac.new(
        str(secret).encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{_SIGNED_COOKIE_PREFIX}{body}.{sig}"


def _verify_signed_payload(
    cookie_value: Optional[str], secret: str
) -> Optional[Dict[str, Any]]:
    if not cookie_value or not secret:
        return None
    raw = str(cookie_value)
    if not raw.startswith(_SIGNED_COOKIE_PREFIX):
        return None
    try:
        body, sep, sig = raw[len(_SIGNED_COOKIE_PREFIX) :].partition(".")
        if not sep or not body or not sig:
            return None
        expected = hmac.new(
            str(secret).encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        exp = int(payload.get("exp") or 0)
    except (TypeError, ValueError):
        return None
    if exp and exp < int(time.time()):
        return None
    return payload


def mint_staff_unlock_cookie(
    *,
    username: str,
    role: str,
    environ: Optional[Mapping[str, str]] = None,
    ttl_seconds: Optional[int] = None,
) -> str:
    """Mint an HttpOnly staff-unlock cookie after admin password entry."""
    secret = signing_secret(environ)
    if not secret:
        raise RuntimeError("No signing secret available for staff unlock cookie.")
    if ttl_seconds is None:
        try:
            ttl_seconds = int(
                str(
                    _env(environ).get(
                        "PHINS_CONFIDENTIAL_COOKIE_MAX_AGE", str(_STAFF_UNLOCK_TTL_DEFAULT)
                    )
                ).strip()
                or str(_STAFF_UNLOCK_TTL_DEFAULT)
            )
        except ValueError:
            ttl_seconds = _STAFF_UNLOCK_TTL_DEFAULT
    payload = {
        "typ": "staff_unlock",
        "u": str(username or "")[:80],
        "r": str(role or "").strip().lower()[:40],
        "iat": int(time.time()),
        "exp": int(time.time()) + max(60, int(ttl_seconds)),
    }
    return _sign_payload(payload, secret)


def verify_staff_unlock_cookie(
    cookie_value: Optional[str], environ: Optional[Mapping[str, str]] = None
) -> Optional[Dict[str, Any]]:
    """Return staff-unlock claims when the cookie is valid."""
    payload = _verify_signed_payload(cookie_value, signing_secret(environ))
    if not payload or payload.get("typ") != "staff_unlock":
        return None
    role = str(payload.get("r") or "").strip().lower()
    if role not in STAFF_ROLES:
        return None
    return payload


def mint_share_cookie(
    *,
    share_id: str,
    path: str,
    environ: Optional[Mapping[str, str]] = None,
    ttl_seconds: Optional[int] = None,
) -> str:
    """Mint a path-scoped share cookie after a successful open-password entry."""
    secret = signing_secret(environ)
    if not secret:
        raise RuntimeError("No signing secret available for share cookie.")
    if is_downloadable_document(path):
        raise ValueError("Share cookies cannot authorise downloaded documents.")
    if ttl_seconds is None:
        try:
            ttl_seconds = int(
                str(
                    _env(environ).get(
                        "PHINS_CONFIDENTIAL_COOKIE_MAX_AGE", str(_SHARE_COOKIE_TTL_DEFAULT)
                    )
                ).strip()
                or str(_SHARE_COOKIE_TTL_DEFAULT)
            )
        except ValueError:
            ttl_seconds = _SHARE_COOKIE_TTL_DEFAULT
    payload = {
        "typ": "share",
        "sid": str(share_id or "")[:80],
        "p": normalize_request_path(path),
        "iat": int(time.time()),
        "exp": int(time.time()) + max(60, int(ttl_seconds)),
    }
    return _sign_payload(payload, secret)


def verify_share_cookie(
    cookie_value: Optional[str],
    path: str,
    environ: Optional[Mapping[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """Return share claims when the cookie is valid for ``path`` (HTML only)."""
    if is_downloadable_document(path):
        return None
    payload = _verify_signed_payload(cookie_value, signing_secret(environ))
    if not payload or payload.get("typ") != "share":
        return None
    if normalize_request_path(path) != normalize_request_path(str(payload.get("p") or "")):
        return None
    if not str(payload.get("sid") or "").strip():
        return None
    return payload


def extract_share_id(query_params: Optional[Mapping[str, Iterable[str]]] = None) -> str:
    """Return the ``share`` query value when present."""
    if not query_params:
        return ""
    raw = query_params.get(SHARE_QUERY_PARAM)
    if isinstance(raw, (list, tuple)):
        return str(raw[0]).strip() if raw else ""
    if raw is not None:
        return str(raw).strip()
    return ""


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
    # API endpoints are matched exactly, but a trailing slash must not skip the
    # gate: ``/api/legal-docs/registry/`` is the same endpoint as
    # ``/api/legal-docs/registry`` and stays confidential.
    if normalized.rstrip("/") in api_paths:
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
    cookie_name: str = ACCESS_COOKIE_NAME
    # Redirect target that strips the token from the URL.
    redirect_to: Optional[str] = None
    status: int = 200
    warnings: list = field(default_factory=list)
    # Present when the denial page should show the share open-password form.
    share_id: str = ""
    # True when the denied path is a downloadable export (no share-link unlock).
    downloadable: bool = False

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
    share_active_check: Optional[Any] = None,
) -> AccessDecision:
    """Decide whether a request may read a confidential document.

    ``query_params`` accepts the ``urllib.parse.parse_qs`` shape (``{name:
    [values]}``) as produced by the server's request parsing.

    ``share_active_check`` is an optional ``callable(share_id, path) -> bool``
    used to confirm a share cookie still refers to a non-revoked link. When
    omitted, a structurally valid share cookie alone is accepted (unit tests).
    """
    env = _env(environ)
    if not is_confidential_path(path, env):
        return AccessDecision(allowed=True, reason="not_confidential", confidential=False)

    downloadable = is_downloadable_document(path)
    share_id = extract_share_id(query_params)
    cookies = parse_cookies(cookie_header)

    if session_is_staff(session):
        return AccessDecision(allowed=True, reason="staff_session", confidential=True)

    staff_claims = verify_staff_unlock_cookie(
        cookies.get(STAFF_UNLOCK_COOKIE_NAME), env
    )
    if staff_claims:
        return AccessDecision(allowed=True, reason="staff_unlock_cookie", confidential=True)

    if not downloadable:
        share_claims = verify_share_cookie(
            cookies.get(SHARE_COOKIE_NAME), path, env
        )
        if share_claims:
            sid = str(share_claims.get("sid") or "")
            active = True
            if callable(share_active_check):
                try:
                    active = bool(share_active_check(sid, path))
                except Exception:
                    active = False
            if active:
                return AccessDecision(
                    allowed=True,
                    reason="share_cookie",
                    confidential=True,
                    share_id=sid,
                )

    token = configured_access_token(env)

    if token:
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
                cookie_name=ACCESS_COOKIE_NAME,
                redirect_to=redirect_after_token_exchange(path, query_params),
            )

        if share_id and not downloadable:
            return AccessDecision(
                allowed=False,
                reason="share_password_required",
                confidential=True,
                status=401,
                share_id=share_id,
                downloadable=False,
            )

        return AccessDecision(
            allowed=False,
            reason="token_required",
            confidential=True,
            status=401,
            share_id=share_id,
            downloadable=downloadable,
        )

    # No global token configured.
    if share_id and not downloadable:
        return AccessDecision(
            allowed=False,
            reason="share_password_required",
            confidential=True,
            status=401,
            share_id=share_id,
            downloadable=False,
        )

    if docs_published_publicly(env):
        return AccessDecision(
            allowed=True,
            reason="explicitly_public",
            confidential=True,
            warnings=["PHINS_CONFIDENTIAL_DOCS_PUBLIC=true — confidential documents are served to anyone."],
        )

    if is_production(env):
        # Fail closed for anonymous callers. Admin password unlock and share
        # links remain available through the denial page / unlock APIs.
        return AccessDecision(
            allowed=False,
            reason="not_configured_production",
            confidential=True,
            status=503,
            share_id=share_id,
            downloadable=downloadable,
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


def redirect_after_token_exchange(
    path: str, query_params: Optional[Mapping[str, Iterable[str]]] = None
) -> str:
    """Build the post-exchange redirect target with the token removed.

    The HTTP handler passes the pathname and the ``parse_qs`` query separately,
    so non-sensitive parameters (document ids, locale flags, ...) arrive in
    ``query_params`` rather than embedded in ``path``. Recombine them onto the
    stripped path so a tokenized deep link keeps its query state across the 302.
    """
    base = strip_sensitive_query(path)
    if not query_params:
        return base
    base_path, _sep, existing = base.partition("?")
    kept = [existing] if existing else []
    present = {
        part.split("=", 1)[0].strip().lower()
        for part in existing.split("&")
        if part
    }
    extra = []
    for name, values in query_params.items():
        key = str(name).strip().lower()
        if key in SENSITIVE_QUERY_PARAMS or key in present:
            continue
        if isinstance(values, (list, tuple)):
            extra.extend((str(name), str(value)) for value in values)
        elif values is not None:
            extra.append((str(name), str(values)))
    if extra:
        kept.append(urlencode(extra))
    query = "&".join(part for part in kept if part)
    return base_path + ("?" + query if query else "")


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
    cookie_name: str = ACCESS_COOKIE_NAME,
) -> str:
    """Build the ``Set-Cookie`` value for an accepted access credential."""
    if max_age is None:
        try:
            max_age = int(
                str(_env(environ).get("PHINS_CONFIDENTIAL_COOKIE_MAX_AGE", "43200")).strip()
                or "43200"
            )
        except ValueError:
            max_age = 43200
    name = str(cookie_name or ACCESS_COOKIE_NAME).strip() or ACCESS_COOKIE_NAME
    parts = [
        f"{name}={cookie_value}",
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
    if decision.reason == "share_password_required":
        return {"error": "Share-link password required for this document."}
    if decision.downloadable:
        return {
            "error": (
                "Access required for this downloaded document. "
                "Use a staff account or the configured open password."
            )
        }
    return {"error": "Access token required for confidential documents."}


def denial_html(
    decision: AccessDecision,
    *,
    path: str = "",
    share_id: str = "",
) -> str:
    """Branded HTML denial page with admin / share unlock forms.

    Visual language matches the portal login surface (navy gradient, gold
    accent, PHINS emblem). Form ids and unlock endpoints are unchanged so
    access integrity stays identical.
    """
    message = denial_payload(decision)["error"]
    effective_share = (share_id or decision.share_id or "").strip()
    target_path = normalize_request_path(path) or "/"
    show_share = bool(effective_share) and not decision.downloadable

    if decision.downloadable:
        lead = "This download is confidential."
        detail = (
            "PDF and export files are not unlocked by share links. "
            "Use a staff password or the deployment open password."
        )
    elif show_share:
        lead = "You have a shared confidential link."
        detail = "Enter the open password you were given to continue."
    else:
        lead = "This document is confidential."
        detail = message

    share_block = ""
    if show_share:
        share_block = f"""
<section class="gate-panel gate-panel--primary" aria-labelledby="share-unlock-title">
  <div class="gate-panel__eyebrow">Shared link</div>
  <h2 id="share-unlock-title">Open shared link</h2>
  <p class="gate-panel__copy">Enter the simple password you were given for this link.</p>
  <form id="share-unlock-form" class="gate-form" autocomplete="on">
    <input type="hidden" name="share_id" value="{_html_escape(effective_share)}">
    <input type="hidden" name="path" value="{_html_escape(target_path)}">
    <label class="gate-field">Link password
      <input type="password" name="password" required minlength="4"
             autocomplete="current-password" placeholder="••••••••">
    </label>
    <button type="submit" class="gate-btn">Open document</button>
    <p id="share-unlock-msg" class="gate-msg" role="status" aria-live="polite"></p>
  </form>
</section>
"""

    admin_block = f"""
<section class="gate-panel{' gate-panel--secondary' if show_share else ' gate-panel--primary'}" aria-labelledby="admin-unlock-title">
  <div class="gate-panel__eyebrow">Staff access</div>
  <h2 id="admin-unlock-title">Staff / admin unlock</h2>
  <p class="gate-panel__copy">Enter an admin-level staff password to authorise this browser for confidential documents.</p>
  <form id="admin-unlock-form" class="gate-form" autocomplete="on">
    <input type="hidden" name="next" value="{_html_escape(target_path)}">
    <label class="gate-field">Username
      <input type="text" name="username" required autocomplete="username"
             placeholder="admin">
    </label>
    <label class="gate-field">Password
      <input type="password" name="password" required minlength="6"
             autocomplete="current-password" placeholder="••••••••">
    </label>
    <button type="submit" class="gate-btn{' gate-btn--ghost' if show_share else ''}">Unlock access</button>
    <p id="admin-unlock-msg" class="gate-msg" role="status" aria-live="polite"></p>
  </form>
</section>
"""

    styles = """
<style>
  :root {
    --gate-navy: #060d1f;
    --gate-ink: #0d2a5c;
    --gate-muted: #5a6b85;
    --gate-line: #dde7f5;
    --gate-gold: #e3bf6f;
    --gate-gold-hi: #f7e2a0;
    --gate-gold-lo: #b8893b;
    --gate-card: rgba(249, 251, 255, 0.97);
    --gate-field: #f8fbff;
    --gate-danger: #b42318;
    --gate-ok: #0f766e;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; min-height: 100%; }
  body {
    font-family: 'Inter', system-ui, -apple-system, sans-serif;
    color: var(--gate-ink);
    background: var(--gate-navy);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 28px 16px 40px;
    position: relative;
    overflow-x: hidden;
  }
  .gate-backdrop {
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    background:
      radial-gradient(1000px 600px at 80% -10%, rgba(21, 68, 155, 0.55), transparent 60%),
      radial-gradient(800px 520px at 8% 110%, rgba(11, 92, 130, 0.4), transparent 60%),
      radial-gradient(600px 400px at 50% 45%, rgba(30, 82, 170, 0.22), transparent 65%),
      linear-gradient(165deg, #081428 0%, #060d1f 45%, #0a1834 100%);
  }
  .gate-backdrop::before {
    content: '';
    position: absolute;
    inset: 0;
    background-image:
      linear-gradient(rgba(127, 178, 255, 0.05) 1px, transparent 1px),
      linear-gradient(90deg, rgba(127, 178, 255, 0.05) 1px, transparent 1px);
    background-size: 72px 72px;
    mask-image: radial-gradient(900px 620px at 50% 40%, rgba(0,0,0,0.85), transparent 78%);
    -webkit-mask-image: radial-gradient(900px 620px at 50% 40%, rgba(0,0,0,0.85), transparent 78%);
    animation: gate-grid-drift 28s linear infinite;
  }
  @keyframes gate-grid-drift {
    from { transform: translate3d(0, 0, 0); }
    to { transform: translate3d(-36px, -36px, 0); }
  }
  .gate-shell {
    width: min(100%, 460px);
    position: relative;
    z-index: 1;
    animation: gate-rise 0.7s cubic-bezier(.22, 1, .36, 1) both;
  }
  @keyframes gate-rise {
    from { opacity: 0; transform: translateY(18px) scale(0.985); }
    to { opacity: 1; transform: none; }
  }
  .gate-card {
    background: var(--gate-card);
    border-radius: 22px;
    padding: 40px 36px 28px;
    box-shadow: 0 30px 80px rgba(2, 8, 23, 0.65), 0 0 0 1px rgba(127, 178, 255, 0.22);
    border-top: 3px solid var(--gate-gold);
  }
  .gate-brand {
    text-align: center;
    margin-bottom: 22px;
  }
  .gate-brand a {
    display: inline-block;
    text-decoration: none;
  }
  .gate-brand img {
    width: 78px;
    height: 78px;
    display: block;
    margin: 0 auto 14px;
    filter: drop-shadow(0 8px 24px rgba(18, 63, 130, 0.35));
    animation: gate-logo-in 0.9s cubic-bezier(.22, 1, .36, 1) 0.08s both;
  }
  @keyframes gate-logo-in {
    from { opacity: 0; transform: translateY(-10px) scale(0.92); }
    to { opacity: 1; transform: none; }
  }
  .gate-wordmark {
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 700;
    font-size: 1.65rem;
    letter-spacing: 0.14em;
    color: var(--gate-ink);
    margin: 0 0 6px;
  }
  .gate-title {
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 600;
    font-size: 1.15rem;
    letter-spacing: 0.02em;
    margin: 0 0 8px;
    color: var(--gate-ink);
  }
  .gate-lead {
    margin: 0;
    color: var(--gate-muted);
    font-size: 0.95rem;
    line-height: 1.45;
  }
  .gate-detail {
    margin: 14px 0 0;
    padding: 12px 14px;
    border-radius: 12px;
    background: #eef4fc;
    border: 1px solid var(--gate-line);
    color: #334155;
    font-size: 0.88rem;
    line-height: 1.45;
  }
  .gate-panel {
    margin-top: 18px;
    padding: 16px 16px 14px;
    border-radius: 14px;
    border: 1px solid var(--gate-line);
    background: linear-gradient(180deg, #ffffff 0%, #f8fbff 100%);
  }
  .gate-panel--primary {
    border-color: rgba(201, 162, 75, 0.45);
    box-shadow: 0 0 0 3px rgba(227, 191, 111, 0.12);
  }
  .gate-panel--secondary { opacity: 0.98; }
  .gate-panel__eyebrow {
    font-size: 0.72rem;
    font-weight: 700;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--gate-gold-lo);
    margin-bottom: 6px;
  }
  .gate-panel h2 {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.05rem;
    font-weight: 600;
    margin: 0 0 6px;
    color: var(--gate-ink);
  }
  .gate-panel__copy {
    margin: 0 0 12px;
    color: var(--gate-muted);
    font-size: 0.88rem;
    line-height: 1.4;
  }
  .gate-form { display: grid; gap: 12px; }
  .gate-field {
    display: grid;
    gap: 6px;
    font-size: 0.9rem;
    font-weight: 600;
    color: var(--gate-ink);
  }
  .gate-field input {
    width: 100%;
    padding: 12px 14px;
    border: 2px solid var(--gate-line);
    border-radius: 10px;
    font-size: 1rem;
    font-family: inherit;
    background: var(--gate-field);
    color: var(--gate-ink);
    transition: border-color 0.25s, box-shadow 0.25s, background 0.25s;
  }
  .gate-field input:focus {
    outline: none;
    border-color: var(--gate-gold);
    box-shadow: 0 0 0 4px rgba(201, 162, 75, 0.14);
    background: #fff;
  }
  .gate-btn {
    width: 100%;
    padding: 14px 16px;
    border: none;
    border-radius: 999px;
    cursor: pointer;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 0.95rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #071022;
    background: linear-gradient(135deg, var(--gate-gold-hi) 0%, var(--gate-gold) 100%);
    box-shadow: 0 0 0 1px rgba(184, 137, 59, 0.35), 0 8px 26px rgba(227, 191, 111, 0.35);
    transition: transform 0.25s, box-shadow 0.25s;
  }
  .gate-btn:hover {
    transform: translateY(-2px);
    box-shadow: 0 0 0 1px rgba(184, 137, 59, 0.55), 0 12px 34px rgba(227, 191, 111, 0.5);
  }
  .gate-btn:active { transform: translateY(0); }
  .gate-btn--ghost {
    background: #fff;
    color: var(--gate-ink);
    border: 1.5px solid var(--gate-line);
    box-shadow: none;
    letter-spacing: 0.04em;
  }
  .gate-btn--ghost:hover {
    border-color: #b7c9e6;
    box-shadow: 0 6px 18px rgba(13, 42, 92, 0.08);
  }
  .gate-msg {
    min-height: 1.2em;
    margin: 0;
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--gate-danger);
  }
  .gate-msg.is-ok { color: var(--gate-ok); }
  .gate-footnote {
    margin: 18px 0 0;
    color: var(--gate-muted);
    font-size: 0.82rem;
    line-height: 1.45;
    text-align: center;
  }
  .gate-foot {
    margin-top: 18px;
    text-align: center;
    color: rgba(199, 214, 240, 0.72);
    font-size: 0.78rem;
    letter-spacing: 0.04em;
    animation: gate-rise 0.8s cubic-bezier(.22, 1, .36, 1) 0.15s both;
  }
  .gate-foot a {
    color: var(--gate-gold-hi);
    text-decoration: none;
  }
  .gate-foot a:hover { text-decoration: underline; }
  @media (max-width: 480px) {
    .gate-card { padding: 32px 22px 22px; border-radius: 18px; }
    .gate-brand img { width: 68px; height: 68px; }
    .gate-wordmark { font-size: 1.4rem; }
  }
  @media (prefers-reduced-motion: reduce) {
    .gate-shell, .gate-brand img, .gate-foot, .gate-backdrop::before {
      animation: none !important;
    }
  }
</style>
"""

    script = """
<script>
(function () {
  function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      credentials: "same-origin",
      body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().then(function (data) {
        return {ok: r.ok, status: r.status, data: data || {}};
      }).catch(function () {
        return {ok: r.ok, status: r.status, data: {error: "Unexpected response"}};
      });
    });
  }

  function setMsg(el, text, ok) {
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("is-ok", !!ok);
  }

  var adminForm = document.getElementById("admin-unlock-form");
  if (adminForm) {
    adminForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var msg = document.getElementById("admin-unlock-msg");
      var btn = adminForm.querySelector('button[type="submit"]');
      setMsg(msg, "Checking…", true);
      if (btn) btn.disabled = true;
      var fd = new FormData(adminForm);
      postJson("/api/confidential/admin-unlock", {
        username: fd.get("username"),
        password: fd.get("password"),
        next: fd.get("next")
      }).then(function (res) {
        if (!res.ok) {
          setMsg(msg, (res.data && res.data.error) || "Unlock failed", false);
          if (btn) btn.disabled = false;
          return;
        }
        if (res.data && res.data.token) {
          try { localStorage.setItem("phins_auth_token", res.data.token); } catch (e) {}
        }
        setMsg(msg, "Access granted — opening…", true);
        var next = (res.data && res.data.redirect_to) || fd.get("next") || "/";
        window.location.replace(next);
      }).catch(function () {
        setMsg(msg, "Network error — try again", false);
        if (btn) btn.disabled = false;
      });
    });
  }

  var shareForm = document.getElementById("share-unlock-form");
  if (shareForm) {
    shareForm.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var msg = document.getElementById("share-unlock-msg");
      var btn = shareForm.querySelector('button[type="submit"]');
      setMsg(msg, "Checking…", true);
      if (btn) btn.disabled = true;
      var fd = new FormData(shareForm);
      postJson("/api/confidential/share-unlock", {
        share_id: fd.get("share_id"),
        password: fd.get("password"),
        path: fd.get("path")
      }).then(function (res) {
        if (!res.ok) {
          setMsg(msg, (res.data && res.data.error) || "Unlock failed", false);
          if (btn) btn.disabled = false;
          return;
        }
        setMsg(msg, "Access granted — opening…", true);
        var next = (res.data && res.data.redirect_to) || fd.get("path") || "/";
        window.location.replace(next);
      }).catch(function () {
        setMsg(msg, "Network error — try again", false);
        if (btn) btn.disabled = false;
      });
    });
  }
})();
</script>
"""

    # Share form first when the visitor arrived via a share link — primary path.
    panels = f"{share_block}{admin_block}" if show_share else f"{admin_block}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <meta name="theme-color" content="#060d1f">
  <title>Access restricted · PHINS</title>
  <link rel="icon" type="image/svg+xml" href="/phins-logo.svg">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
  {styles}
</head>
<body>
  <div class="gate-backdrop" aria-hidden="true"></div>
  <div class="gate-shell">
    <main class="gate-card">
      <header class="gate-brand">
        <a href="/" title="PHINS home">
          <img src="/phins-logo.svg" width="78" height="78" alt="PHINS emblem">
        </a>
        <p class="gate-wordmark">PHINS</p>
        <h1 class="gate-title">Access restricted</h1>
        <p class="gate-lead">{_html_escape(lead)}</p>
      </header>
      <p class="gate-detail">{_html_escape(detail)}</p>
      {panels}
      <p class="gate-footnote">If you were given a shared document link, open it with the link password. Staff can unlock with an admin-level password. Downloaded exports are excluded from share links.</p>
    </main>
    <p class="gate-foot"><a href="/">phins.ai</a> · Confidential workspace</p>
  </div>
  {script}
</body>
</html>
"""


def _html_escape(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
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
                "PHINS_CONFIDENTIAL_ACCESS_TOKEN is not set — anonymous access to "
                "confidential documents is DENIED in production. Admins can still "
                "unlock with a staff password; recipients can use single/multi-use "
                "share links. Set the token for a global open password."
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
    if is_production(env) and not signing_secret(env):
        warnings.append(
            "No signing secret available for confidential staff/share cookies "
            "(set SESSION_SECRET_KEY or PHINS_ENCRYPTION_KEY)."
        )
    return warnings
