"""Production boot fail-closed gates (ERP/MGA integrity U1).

Two guarantees for real production:

1. Durable database storage is required (no silent in-memory split-brain).
2. The HTTP serve path must not use a tempdir ledger snapshot (lost on redeploy).

Defaults follow :func:`security.secrets_policy._is_production` so Railway PR
previews that inherit ``PHINS_ENVIRONMENT=production`` stay non-production,
and ``PHINS_TEST_MODE`` never fail-closes.

Explicit ``PHINS_REQUIRE_DATABASE=false`` (and aliases) is the only soft
escape hatch for the DB gate. Any other non-empty value is treated as
require-on (fail-closed on typos). ``PHINS_ALLOW_EPHEMERAL_LEDGER=true`` is
the escape hatch for the ledger-path gate.
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

    - Explicit falsy ``PHINS_REQUIRE_DATABASE`` → soft (escape hatch).
    - Any other non-empty explicit value → require DB (fail-closed on typos).
    - Unset → True in real production, False in test / preview / demo.
    """
    env: EnvMap = environ if environ is not None else os.environ
    raw = env.get("PHINS_REQUIRE_DATABASE")
    if raw is not None and str(raw).strip() != "":
        if _falsy(raw):
            return False
        # Truthy *or* unrecognized → keep the guard on.
        return True
    if _test_mode(env):
        return False
    return _production(env)


def ephemeral_ledger_forbidden(environ: Optional[EnvMap] = None) -> bool:
    """Whether an ephemeral (tempdir) ledger path must abort HTTP serve."""
    env: EnvMap = environ if environ is not None else os.environ
    raw = env.get("PHINS_ALLOW_EPHEMERAL_LEDGER")
    if raw is not None and str(raw).strip() != "":
        if _truthy(raw):
            return False
        # Explicit falsy *or* unrecognized → forbid ephemeral (fail-closed).
        return True
    if _test_mode(env):
        return False
    return _production(env)


def ledger_path_is_ephemeral(path: str, *, temp_root: Optional[str] = None) -> bool:
    """True when ``path`` lives under the process tempdir, or cannot be classified.

    Unclassifiable paths fail closed: a durability gate must not treat "unknown"
    as durable.
    """
    root = temp_root if temp_root is not None else tempfile.gettempdir()
    try:
        abs_path = os.path.abspath(path)
        abs_root = os.path.abspath(root)
        return abs_path == abs_root or abs_path.startswith(abs_root + os.sep)
    except (TypeError, ValueError, OSError):
        return True


def refuse_in_memory_boot(*, required: bool, use_database: bool, database_enabled: bool) -> bool:
    """True when the process landed on volatile storage but durability is required."""
    return bool(required) and not (use_database and database_enabled)


def refuse_ephemeral_ledger_boot(*, forbidden: bool, ledger_path: str) -> bool:
    """True when production forbids the resolved ledger path."""
    return bool(forbidden) and ledger_path_is_ephemeral(ledger_path)
