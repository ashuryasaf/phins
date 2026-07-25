"""
PHINS Trading Terminal Access Service
=====================================
Single-key access control for the trading terminal APIs (``/api/terminal/*``).

The key is provided via the ``TERMINAL_ACCESS_KEY`` environment variable.
For backward compatibility with existing deployments, the legacy
``INVESTMENT_AI_ACCESS_KEY`` variable is honored when the new one is unset.
When neither is configured, a persistent random key is generated at startup
(retrievable by admins via ``/api/terminal/access-key``).
"""

import hmac
import os
import secrets
from typing import Optional

_TERMINAL_ACCESS_KEY = (
    os.environ.get("TERMINAL_ACCESS_KEY")
    or os.environ.get("INVESTMENT_AI_ACCESS_KEY")
    or None
)

_GENERATED_KEY: Optional[str] = None


def _get_or_create_access_key() -> str:
    """Return the configured access key or generate a persistent one."""
    global _GENERATED_KEY
    if _TERMINAL_ACCESS_KEY:
        return _TERMINAL_ACCESS_KEY
    if _GENERATED_KEY is None:
        _GENERATED_KEY = f"term_{secrets.token_urlsafe(32)}"
    return _GENERATED_KEY


def validate_terminal_access(provided_key: str) -> bool:
    """Validate that the provided key matches the terminal access key."""
    if not provided_key:
        return False
    expected = _get_or_create_access_key()
    return hmac.compare_digest(provided_key, expected)


def get_access_key_display() -> str:
    """Return the current access key (for admin provisioning)."""
    return _get_or_create_access_key()


__all__ = ["validate_terminal_access", "get_access_key_display"]
