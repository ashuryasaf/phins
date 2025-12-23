"""
PHINS Vault (Encryption Helpers)

This module provides best-effort encryption for sensitive admin datasets
(e.g., actuarial tables, regulated configuration) using Fernet (AES-128 + HMAC).

Production guidance:
- Set PHINS_ENCRYPTION_KEY to a Fernet key (base64 urlsafe, 32 bytes)
- Rotate keys using a proper KMS and re-encrypt stored payloads.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class VaultBlob:
    """Serialized vault blob stored in DB."""

    scheme: str  # "fernet" or "plain"
    ciphertext: str  # base64/urlsafe token (fernet) or plaintext JSON (plain)

    def to_json(self) -> str:
        return json.dumps({"scheme": self.scheme, "ciphertext": self.ciphertext})

    @staticmethod
    def from_json(value: str) -> "VaultBlob":
        obj = json.loads(value)
        return VaultBlob(scheme=obj.get("scheme", "plain"), ciphertext=obj.get("ciphertext", ""))


def _get_fernet():
    # Import lazily so the repo can still run without cryptography installed.
    from cryptography.fernet import Fernet  # type: ignore

    key = os.environ.get("PHINS_ENCRYPTION_KEY", "").strip()
    if not key:
        return None

    # Basic sanity check: Fernet keys are urlsafe base64-encoded 32-byte keys.
    try:
        raw = base64.urlsafe_b64decode(key)
        if len(raw) != 32:
            return None
    except Exception:
        return None

    return Fernet(key.encode("utf-8"))


def encrypt_json(data: Any) -> VaultBlob:
    """Encrypt JSON-serializable data into a VaultBlob."""
    payload = json.dumps(data, separators=(",", ":"), sort_keys=True)
    f = _get_fernet()
    if not f:
        return VaultBlob(scheme="plain", ciphertext=payload)
    token = f.encrypt(payload.encode("utf-8")).decode("utf-8")
    return VaultBlob(scheme="fernet", ciphertext=token)


def decrypt_json(blob_json: str, default: Optional[Any] = None) -> Any:
    """Decrypt a VaultBlob JSON string into Python data."""
    try:
        blob = VaultBlob.from_json(blob_json)
    except Exception:
        return default

    if blob.scheme == "plain":
        try:
            return json.loads(blob.ciphertext)
        except Exception:
            return default

    if blob.scheme == "fernet":
        f = _get_fernet()
        if not f:
            return default
        try:
            payload = f.decrypt(blob.ciphertext.encode("utf-8")).decode("utf-8")
            return json.loads(payload)
        except Exception:
            return default

    return default

