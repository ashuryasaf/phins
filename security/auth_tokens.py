"""PHINS hardened authentication tokens (v2).

This module provides HMAC-signed, revocable bearer tokens as a drop-in upgrade
to the legacy ``phins_<b64>.<16-hex>`` tokens minted directly in
``web_portal/server.py``.

Design goals
------------

1. **Full-length HMAC-SHA256 signature.** The legacy format truncated the
   signature to the first 16 hex digits (~64 bits), which is below the modern
   forgery-resistance bar. v2 tokens keep the entire 32-byte digest encoded as
   url-safe base64 (43 chars), matching the strength of the underlying hash.

2. **Constant-time verification.** We never short-circuit on the first mismatch
   and always use :func:`hmac.compare_digest` for signature comparison.

3. **Revocation support.** Every token carries a random ``jti`` (JWT-style id).
   Revoked ``jti`` values are held in an in-memory denylist until they would
   have expired anyway. Callers invoke :func:`revoke_token` on logout,
   password change, password reset, or admin lockout.

4. **Key rotation.** ``_primary_key()`` returns the active signing key, while
   ``_rotation_keys()`` returns previous keys that remain accepted for
   verification during a rotation window. Configure via the
   ``SESSION_SECRET_KEY`` (primary) and ``SESSION_SECRET_KEYS_PREVIOUS``
   (comma-separated) environment variables.

5. **No silent fallback to weak secrets.** When the effective key is missing or
   shorter than 32 bytes, token creation raises ``TokenSecretError`` at call
   time rather than producing a forgery-prone token with a default value. The
   legacy fallback to ``PHINS_ADMIN_PASSWORD`` has been removed.

6. **Backward compatibility.** :func:`verify_any_token` recognizes both v2
   (``phins2_...``) and legacy v1 (``phins_...``) formats, so existing sessions
   remain valid until they expire.

The module is pure standard library so it can be imported before
``web_portal/server.py`` is fully initialised (e.g. from tests).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

__all__ = [
    "TokenSecretError",
    "TokenClaims",
    "create_token",
    "verify_v2_token",
    "verify_any_token",
    "revoke_token",
    "is_revoked",
    "prune_revocations",
    "register_legacy_verifier",
    "token_metadata",
    "set_secret_provider_for_tests",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class TokenSecretError(RuntimeError):
    """Raised when the signing secret is missing or too weak to use."""


# ---------------------------------------------------------------------------
# Secret management
# ---------------------------------------------------------------------------


_MIN_SECRET_BYTES = 32
_TOKEN_PREFIX_V2 = "phins2_"
_TOKEN_PREFIX_V1 = "phins_"

_secret_provider_override: Optional[Callable[[], Tuple[str, List[str]]]] = None


def set_secret_provider_for_tests(
    provider: Optional[Callable[[], Tuple[str, List[str]]]],
) -> None:
    """Test helper to override secret resolution without touching env vars."""
    global _secret_provider_override
    _secret_provider_override = provider


def _resolve_secrets() -> Tuple[str, List[str]]:
    """Return ``(primary_key, previous_keys)`` from env or test override."""
    if _secret_provider_override is not None:
        try:
            primary, previous = _secret_provider_override()
        except Exception as exc:  # pragma: no cover - defensive
            raise TokenSecretError(f"secret provider failed: {exc}") from exc
        return primary or "", list(previous or [])

    primary = (os.environ.get("SESSION_SECRET_KEY") or "").strip()
    raw_previous = os.environ.get("SESSION_SECRET_KEYS_PREVIOUS") or ""
    previous = [
        key.strip()
        for key in raw_previous.split(",")
        if key and key.strip()
    ]
    return primary, previous


def _primary_key() -> str:
    """Return the active signing key, raising if unusable."""
    primary, _ = _resolve_secrets()
    if not primary:
        raise TokenSecretError(
            "SESSION_SECRET_KEY is not configured; cannot mint auth tokens"
        )
    if len(primary.encode("utf-8")) < _MIN_SECRET_BYTES:
        raise TokenSecretError(
            "SESSION_SECRET_KEY is shorter than 32 bytes; refuse to mint tokens"
        )
    return primary


def _verification_keys() -> List[str]:
    """Return every key accepted for verification (primary + previous)."""
    primary, previous = _resolve_secrets()
    keys: List[str] = []
    if primary:
        keys.append(primary)
    for key in previous:
        if key and key not in keys:
            keys.append(key)
    return keys


# ---------------------------------------------------------------------------
# Token primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TokenClaims:
    """Decoded claims produced by :func:`verify_v2_token`."""

    username: str
    role: str
    customer_id: Optional[str]
    jti: str
    issued_at: float
    expires_at: float

    def to_session_dict(self) -> Dict[str, Any]:
        """Return the shape expected by ``validate_session`` in server.py."""
        expires_iso = datetime.fromtimestamp(self.expires_at).isoformat()
        return {
            "username": self.username,
            "role": self.role,
            "customer_id": self.customer_id,
            "expires": expires_iso,
            "jti": self.jti,
            "token_version": 2,
        }


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def _sign(key: str, message: bytes) -> bytes:
    return hmac.new(key.encode("utf-8"), message, hashlib.sha256).digest()


def create_token(
    username: str,
    role: str,
    customer_id: Optional[str],
    expires_at: datetime,
    *,
    issued_at: Optional[datetime] = None,
    jti: Optional[str] = None,
) -> Tuple[str, TokenClaims]:
    """Mint a v2 token along with the decoded claims.

    The token format is ``phins2_<b64(payload)>.<b64(sig)>`` where the signature
    is the full 32-byte HMAC-SHA256 of the payload bytes.
    """
    if not username or not isinstance(username, str):
        raise ValueError("username is required")
    if not role or not isinstance(role, str):
        raise ValueError("role is required")

    key = _primary_key()
    issued_at = issued_at or datetime.now()
    jti = jti or secrets.token_urlsafe(16)
    issued_at_ts = int(issued_at.timestamp())
    expires_at_ts = int(expires_at.timestamp())

    payload = {
        "sub": username,
        "role": role,
        "cid": customer_id or "",
        "iat": issued_at_ts,
        "exp": expires_at_ts,
        "jti": jti,
        "v": 2,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    payload_b64 = _b64encode(payload_bytes)
    signature = _sign(key, payload_b64.encode("ascii"))
    token = f"{_TOKEN_PREFIX_V2}{payload_b64}.{_b64encode(signature)}"

    claims = TokenClaims(
        username=username,
        role=role,
        customer_id=customer_id or None,
        jti=jti,
        issued_at=float(payload["iat"]),
        expires_at=float(payload["exp"]),
    )
    return token, claims


def verify_v2_token(token: str) -> Optional[TokenClaims]:
    """Verify a v2 token, returning its claims or ``None`` on any failure.

    ``None`` is returned for every failure mode so callers can treat unknown
    formats, expired tokens, bad signatures, and revoked tokens identically
    and avoid leaking which check failed.
    """
    if not token or not isinstance(token, str):
        return None
    if not token.startswith(_TOKEN_PREFIX_V2):
        return None

    body = token[len(_TOKEN_PREFIX_V2):]
    if "." not in body:
        return None
    payload_b64, signature_b64 = body.rsplit(".", 1)

    try:
        provided_sig = _b64decode(signature_b64)
    except Exception:
        return None

    candidate_keys = _verification_keys()
    if not candidate_keys:
        return None

    match = False
    for key in candidate_keys:
        expected = _sign(key, payload_b64.encode("ascii"))
        if hmac.compare_digest(expected, provided_sig):
            match = True
    if not match:
        return None

    try:
        payload_bytes = _b64decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    if payload.get("v") != 2:
        return None

    try:
        exp = float(payload.get("exp", 0))
        iat = float(payload.get("iat", 0))
    except (TypeError, ValueError):
        return None

    now = time.time()
    if exp <= 0 or now >= exp:
        return None
    # Reject tokens issued in the far future (clock skew / replay guards).
    if iat > now + 300:
        return None

    username = str(payload.get("sub") or "")
    role = str(payload.get("role") or "")
    customer_id = payload.get("cid") or None
    jti = str(payload.get("jti") or "")
    if not username or not role or not jti:
        return None

    if is_revoked(jti):
        return None

    return TokenClaims(
        username=username,
        role=role,
        customer_id=customer_id or None,
        jti=jti,
        issued_at=iat,
        expires_at=exp,
    )


# ---------------------------------------------------------------------------
# Legacy verifier hook
# ---------------------------------------------------------------------------


_legacy_verifier: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None


def register_legacy_verifier(
    verifier: Optional[Callable[[str], Optional[Dict[str, Any]]]],
) -> None:
    """Register a function used to verify pre-v2 tokens.

    ``server.py`` wires the existing ``_verify_signed_token`` into this hook so
    this module can treat legacy tokens without importing server internals.
    """
    global _legacy_verifier
    _legacy_verifier = verifier


def verify_any_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify v2 first, then delegate to the registered legacy verifier."""
    if not token:
        return None
    if token.startswith(_TOKEN_PREFIX_V2):
        claims = verify_v2_token(token)
        if claims is None:
            return None
        return claims.to_session_dict()
    if _legacy_verifier is not None:
        return _legacy_verifier(token)
    return None


def token_metadata(token: str) -> Dict[str, Any]:
    """Return non-sensitive metadata about a token (used for debug endpoints)."""
    if not token or not isinstance(token, str):
        return {"format": "invalid"}
    if token.startswith(_TOKEN_PREFIX_V2):
        return {"format": "v2", "length": len(token)}
    if token.startswith(_TOKEN_PREFIX_V1):
        return {"format": "v1", "length": len(token)}
    return {"format": "unknown", "length": len(token)}


# ---------------------------------------------------------------------------
# Revocation registry
# ---------------------------------------------------------------------------


_revocation_lock = threading.RLock()
_revoked: Dict[str, float] = {}
# Upper bound on entries kept in memory; beyond this the oldest are evicted
# first to keep memory usage bounded even under attack.
_REVOCATION_HARD_LIMIT = 20_000


def revoke_token(jti: str, expires_at: float) -> None:
    """Mark ``jti`` revoked until ``expires_at`` (unix epoch seconds)."""
    if not jti:
        return
    with _revocation_lock:
        _revoked[jti] = max(_revoked.get(jti, 0.0), float(expires_at))
        if len(_revoked) > _REVOCATION_HARD_LIMIT:
            # Evict the earliest-expiring entries first.
            for old_jti, _exp in sorted(_revoked.items(), key=lambda kv: kv[1])[
                : len(_revoked) - _REVOCATION_HARD_LIMIT
            ]:
                _revoked.pop(old_jti, None)


def is_revoked(jti: str) -> bool:
    if not jti:
        return False
    now = time.time()
    with _revocation_lock:
        exp = _revoked.get(jti)
        if exp is None:
            return False
        if exp <= now:
            # Garbage-collect lazily so the registry stays small.
            _revoked.pop(jti, None)
            return False
        return True


def prune_revocations(*, now: Optional[float] = None) -> int:
    """Remove expired revocations; return the number of entries removed."""
    now_ts = now if now is not None else time.time()
    removed = 0
    with _revocation_lock:
        for jti in [jti for jti, exp in _revoked.items() if exp <= now_ts]:
            _revoked.pop(jti, None)
            removed += 1
    return removed


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def revoked_jtis_for_tests() -> Iterable[str]:
    """Return a snapshot of revoked jtis; used by tests."""
    with _revocation_lock:
        return list(_revoked.keys())
