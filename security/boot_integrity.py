"""Production boot fail-closed gates (ERP/MGA integrity U1).

Two guarantees for real production:

1. Durable database storage is required (no silent in-memory split-brain).
2. The ledger snapshot path must not be the process tempdir (lost on redeploy).

Defaults follow :func:`security.secrets_policy._is_production` so Railway PR
previews that inherit ``PHINS_ENVIRONMENT=production`` stay non-production,
and ``PHINS_TEST_MODE`` never fail-closes. An explicit
``PHINS_REQUIRE_DATABASE`` / ``PHINS_ALLOW_EPHEMERAL_LEDGER`` value always wins.
"""

from __future__ import annotations

import os
import tempfile
from typing import Mapping, MutableMapping, Optional, Union

EnvMap = Union[Mapping[str, str], MutableMapping[str, str]]


def _truthy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "y", "on")


def _falsy(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in ("0", "false", "no", "n", "off")


def _test_mode(environ: EnvMap) -> bool:
    return _truthy(environ.get("PHINS_TEST_MODE"))


def _production(environ: EnvMap) -> bool:
    if _test_mode(environ):
        return False
    try:
        from security.secrets_policy import _is_production

        return bool(_is_production(dict(environ)))
    except Exception:
        label = str(
            environ.get("PHINS_ENVIRONMENT")
            or environ.get("ENVIRONMENT")
            or environ.get("ENV")
            or ""
        ).strip().lower()
        return label in ("production", "prod", "live")


def database_required(environ: Optional[EnvMap] = None) -> bool:
    """Whether boot must refuse volatile in-memory storage.

    Explicit ``PHINS_REQUIRE_DATABASE`` wins. Otherwise defaults to True in
    real production and False elsewhere (tests, demos, Railway PR previews).
    """
    env: EnvMap = environ if environ is not None else os.environ
    raw = env.get("PHINS_REQUIRE_DATABASE")
    if raw is not None and str(raw).strip() != "":
        if _falsy(raw):
            return False
        return _truthy(raw)
    if _test_mode(env):
        return False
    return _production(env)


def ephemeral_ledger_forbidden(environ: Optional[EnvMap] = None) -> bool:
    """Whether an ephemeral (tempdir) ledger path must abort boot."""
    env: EnvMap = environ if environ is not None else os.environ
    raw = env.get("PHINS_ALLOW_EPHEMERAL_LEDGER")
    if raw is not None and str(raw).strip() != "":
        if _truthy(raw):
            return False
        if _falsy(raw):
            return True
    if _test_mode(env):
        return False
    return _production(env)


def ledger_path_is_ephemeral(path: str, *, temp_root: Optional[str] = None) -> bool:
    """True when ``path`` lives under the process tempdir."""
    root = temp_root if temp_root is not None else tempfile.gettempdir()
    try:
        return os.path.abspath(path).startswith(os.path.abspath(root) + os.sep) or (
            os.path.abspath(path) == os.path.abspath(root)
        )
    except (TypeError, ValueError, OSError):
        return False


def refuse_in_memory_boot(*, required: bool, use_database: bool, database_enabled: bool) -> bool:
    """True when the process landed on volatile storage but durability is required."""
    return bool(required) and not (use_database and database_enabled)


def refuse_ephemeral_ledger_boot(*, forbidden: bool, ledger_path: str) -> bool:
    """True when production forbids the resolved ledger path."""
    return bool(forbidden) and ledger_path_is_ephemeral(ledger_path)
