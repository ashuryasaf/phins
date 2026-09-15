"""
PHINS Vault (Encryption Helpers)

This module provides best-effort encryption for sensitive admin datasets
(e.g., actuarial tables, regulated configuration) using Fernet (AES-128 + HMAC).

Key resolution (see ``security/keyring.py``):
- PHINS_ENCRYPTION_KEY, when set, is the primary key (base64 urlsafe, 32 bytes).
- Otherwise a durable platform key is minted once and reused (``platform_keys``
  table in database mode, ``PHINS_KEYRING_PATH`` file otherwise), so vaulted
  data is encrypted at rest even on deployments that never set the variable.
- Decryption tries every known key (MultiFernet), so blobs written under a
  previous key stay readable after the operator introduces an explicit one.
- Rotate keys using a proper KMS and re-encrypt stored payloads.
"""

from __future__ import annotations

import base64
import json
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
    """Return a MultiFernet over every known vault key (primary first), or
    ``None`` when no key can be resolved at all."""
    # Import lazily so the repo can still run without cryptography installed.
    from cryptography.fernet import Fernet, MultiFernet  # type: ignore

    from security.keyring import vault_keys

    fernets = []
    for key in vault_keys():
        # Basic sanity check: Fernet keys are urlsafe base64-encoded 32-byte keys.
        try:
            if len(base64.urlsafe_b64decode(key)) != 32:
                continue
        except Exception:
            continue
        fernets.append(Fernet(key.encode("utf-8")))
    if not fernets:
        return None
    return MultiFernet(fernets)


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

