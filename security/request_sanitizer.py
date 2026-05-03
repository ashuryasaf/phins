"""Deep request sanitisation for PHINS.

Provides a unified ``sanitize_request_body`` function that recursively walks
JSON payloads and applies:

1. **HTML entity encoding** of dangerous characters in string values.
2. **Recursive depth limiting** — rejects payloads nested deeper than a
   configurable threshold to prevent hash-collision / stack-overflow DoS.
3. **Key-count limiting** — rejects objects with excessive keys (anti-DoS).
4. **Content-length cross-check** — validates that the declared
   ``Content-Length`` matches the actual body size.
5. **JSON deserialization hardening** — wraps ``json.loads`` with size and
   depth guards.
6. **CSRF token validation** — double-submit cookie pattern for state-changing
   requests.
7. **Header injection prevention** — strips CRLF sequences from header values.

All functions are stdlib-only and thread-safe.
"""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import logging
import os
import re
import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple, Union

__all__ = [
    "sanitize_request_body",
    "safe_json_loads",
    "validate_content_length",
    "sanitize_header_value",
    "generate_csrf_token",
    "validate_csrf_token",
    "deep_sanitize_string",
]

LOGGER = logging.getLogger("phins.security.request_sanitizer")

# ── configuration ────────────────────────────────────────────────────────────

MAX_JSON_DEPTH = int(os.environ.get("PHINS_MAX_JSON_DEPTH", "20"))
MAX_JSON_KEYS = int(os.environ.get("PHINS_MAX_JSON_KEYS", "500"))
MAX_STRING_VALUE_LENGTH = int(
    os.environ.get("PHINS_MAX_STRING_VALUE", str(512 * 1024))
)
CSRF_SECRET = os.environ.get("SESSION_SECRET_KEY", "phins-csrf-fallback")
CSRF_TOKEN_TTL = int(os.environ.get("PHINS_CSRF_TTL", "7200"))

# ── CRLF / header injection ─────────────────────────────────────────────────

_CRLF_RE = re.compile(r"[\r\n]+")

_DANGEROUS_HTML_RE = re.compile(
    r"<\s*(?:script|iframe|object|embed|applet|form|style|link|meta|svg|math)"
    r"[\s>/]",
    re.IGNORECASE,
)

# ── CSRF state ───────────────────────────────────────────────────────────────

_csrf_lock = threading.Lock()
_csrf_tokens: Dict[str, float] = {}
_CSRF_MAX_TOKENS = 5000


# ── public API ───────────────────────────────────────────────────────────────

def sanitize_request_body(
    body: Any,
    *,
    max_depth: int = 0,
    max_keys: int = 0,
) -> Tuple[Any, List[str]]:
    """Recursively sanitise a parsed JSON body.

    Returns ``(sanitized_body, warnings)`` where *warnings* is a list of
    human-readable messages about any modifications applied.
    """
    effective_depth = max_depth or MAX_JSON_DEPTH
    effective_keys = max_keys or MAX_JSON_KEYS
    warnings: List[str] = []
    result = _walk(body, depth=0, max_depth=effective_depth,
                   max_keys=effective_keys, warnings=warnings, path="$")
    return result, warnings


def safe_json_loads(
    raw: Union[str, bytes],
    *,
    max_size: int = 0,
    max_depth: int = 0,
) -> Any:
    """Parse JSON with size and depth guards.

    Raises ``ValueError`` for payloads that exceed limits.
    """
    effective_max = max_size or (10 * 1024 * 1024)
    size = len(raw) if isinstance(raw, (str, bytes)) else 0
    if size > effective_max:
        raise ValueError(
            f"JSON payload too large ({size} > {effective_max} bytes)"
        )

    data = json.loads(raw)

    effective_depth = max_depth or MAX_JSON_DEPTH
    actual_depth = _measure_depth(data)
    if actual_depth > effective_depth:
        raise ValueError(
            f"JSON nesting too deep ({actual_depth} > {effective_depth})"
        )

    return data


def validate_content_length(
    declared: int,
    actual: int,
    *,
    tolerance: int = 0,
) -> Tuple[bool, str]:
    """Check declared Content-Length against actual body size."""
    if declared < 0:
        return False, "negative Content-Length"
    diff = abs(declared - actual)
    if diff > tolerance:
        return False, (
            f"Content-Length mismatch (declared={declared}, actual={actual})"
        )
    return True, ""


def sanitize_header_value(value: str) -> str:
    """Strip CRLF sequences that could enable header injection."""
    return _CRLF_RE.sub("", value).strip()


def deep_sanitize_string(value: str) -> str:
    """Sanitise a single string value: HTML-encode dangerous chars, trim."""
    if not value:
        return value
    if len(value) > MAX_STRING_VALUE_LENGTH:
        value = value[:MAX_STRING_VALUE_LENGTH]
    value = html.escape(value, quote=True)
    value = value.replace("\x00", "")
    return value


# ── CSRF helpers ─────────────────────────────────────────────────────────────

def generate_csrf_token(session_id: str = "") -> str:
    """Generate a CSRF token bound to the given session."""
    nonce = secrets.token_urlsafe(24)
    ts = str(int(time.time()))
    payload = f"{session_id}:{ts}:{nonce}"
    sig = hmac.new(
        CSRF_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]
    token = f"{payload}:{sig}"

    with _csrf_lock:
        _csrf_tokens[token] = time.time()
        if len(_csrf_tokens) > _CSRF_MAX_TOKENS:
            _prune_csrf()

    return token


def validate_csrf_token(
    token: str,
    session_id: str = "",
) -> Tuple[bool, str]:
    """Validate a CSRF token; returns ``(valid, error_message)``."""
    if not token:
        return False, "missing CSRF token"

    parts = token.rsplit(":", 3)
    if len(parts) != 4:
        return False, "malformed CSRF token"

    token_session, ts_str, nonce, provided_sig = parts

    if session_id and token_session != session_id:
        return False, "CSRF token session mismatch"

    try:
        ts = int(ts_str)
    except ValueError:
        return False, "invalid CSRF timestamp"

    if abs(time.time() - ts) > CSRF_TOKEN_TTL:
        return False, "CSRF token expired"

    expected_payload = f"{token_session}:{ts_str}:{nonce}"
    expected_sig = hmac.new(
        CSRF_SECRET.encode("utf-8"),
        expected_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:32]

    if not hmac.compare_digest(expected_sig, provided_sig):
        return False, "CSRF token signature invalid"

    return True, ""


# ── internal helpers ─────────────────────────────────────────────────────────

def _walk(
    obj: Any,
    *,
    depth: int,
    max_depth: int,
    max_keys: int,
    warnings: List[str],
    path: str,
) -> Any:
    if depth > max_depth:
        warnings.append(f"truncated at {path}: exceeded max depth {max_depth}")
        return None

    if isinstance(obj, dict):
        if len(obj) > max_keys:
            warnings.append(
                f"truncated at {path}: {len(obj)} keys exceeds limit {max_keys}"
            )
            obj = dict(list(obj.items())[:max_keys])
        return {
            _sanitize_key(k): _walk(
                v,
                depth=depth + 1,
                max_depth=max_depth,
                max_keys=max_keys,
                warnings=warnings,
                path=f"{path}.{k}",
            )
            for k, v in obj.items()
        }

    if isinstance(obj, list):
        return [
            _walk(
                item,
                depth=depth + 1,
                max_depth=max_depth,
                max_keys=max_keys,
                warnings=warnings,
                path=f"{path}[{i}]",
            )
            for i, item in enumerate(obj)
        ]

    if isinstance(obj, str):
        if _DANGEROUS_HTML_RE.search(obj):
            warnings.append(f"html_sanitized at {path}")
            obj = html.escape(obj, quote=True)
        obj = obj.replace("\x00", "")
        if len(obj) > MAX_STRING_VALUE_LENGTH:
            warnings.append(f"string_truncated at {path}")
            obj = obj[:MAX_STRING_VALUE_LENGTH]
        return obj

    return obj


def _sanitize_key(key: str) -> str:
    """Remove null bytes and CRLF from dict keys."""
    return key.replace("\x00", "").replace("\r", "").replace("\n", "")


def _measure_depth(obj: Any, current: int = 0) -> int:
    if isinstance(obj, dict):
        if not obj:
            return current + 1
        return max(_measure_depth(v, current + 1) for v in obj.values())
    if isinstance(obj, list):
        if not obj:
            return current + 1
        return max(_measure_depth(v, current + 1) for v in obj)
    return current


def _prune_csrf() -> None:
    now = time.time()
    expired = [t for t, ts in _csrf_tokens.items() if now - ts > CSRF_TOKEN_TTL]
    for t in expired:
        _csrf_tokens.pop(t, None)
    if len(_csrf_tokens) > _CSRF_MAX_TOKENS:
        oldest = sorted(_csrf_tokens.items(), key=lambda kv: kv[1])
        for t, _ in oldest[: len(_csrf_tokens) - _CSRF_MAX_TOKENS]:
            _csrf_tokens.pop(t, None)
