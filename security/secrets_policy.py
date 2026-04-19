"""Runtime validation of security-critical secrets.

Called once at startup from ``web_portal/server.py``. The goals are:

* Refuse to mint tokens with weak/missing signing keys in production.
* Warn loudly in test/dev when defaults are in use.
* Forbid the historical hardcoded ``phins-emergency-unlock-2026`` literal.

The helpers only emit log lines and return a structured report; they never
mutate global state. Callers decide whether a failing check should abort
startup or just warn.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional


LOGGER = logging.getLogger("phins.security.secrets")


# Known-bad or historical defaults that must never appear in production.
_FORBIDDEN_SECRETS = frozenset(
    {
        "phins-emergency-unlock-2026",
        "change-me",
        "changeme",
        "password",
        "admin",
        "admin123",
        "secret",
        "default",
    }
)

_MIN_BYTES = 32


@dataclass
class SecretReport:
    """Structured result of :func:`audit_environment_secrets`."""

    production_mode: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_production(environ: Optional[dict] = None) -> bool:
    env = environ if environ is not None else os.environ
    if str(env.get("PHINS_TEST_MODE", "")).lower() in ("1", "true", "yes", "y"):
        return False
    env_label = str(env.get("ENVIRONMENT", env.get("ENV", ""))).lower()
    if env_label in ("production", "prod", "live"):
        return True
    # Railway, Render, and similar hosts set a platform flag without explicit
    # ENVIRONMENT values; treat any non-test runtime as production.
    if env.get("RAILWAY_ENVIRONMENT") or env.get("RENDER"):
        return True
    return False


def _check_secret(
    env_name: str,
    value: Optional[str],
    *,
    required_in_production: bool,
    production: bool,
) -> tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    val = (value or "").strip()

    if not val:
        msg = f"{env_name} is not set"
        if required_in_production and production:
            errors.append(msg)
        else:
            warnings.append(msg)
        return errors, warnings

    if val.lower() in _FORBIDDEN_SECRETS:
        errors.append(f"{env_name} matches a known-insecure default")
        return errors, warnings

    if len(val.encode("utf-8")) < _MIN_BYTES:
        msg = f"{env_name} is shorter than {_MIN_BYTES} bytes"
        if production:
            errors.append(msg)
        else:
            warnings.append(msg)

    return errors, warnings


def audit_environment_secrets(environ: Optional[dict] = None) -> SecretReport:
    """Audit the process environment for weak or missing security secrets."""
    env = environ if environ is not None else os.environ
    production = _is_production(env)
    report = SecretReport(production_mode=production)

    errors, warnings = _check_secret(
        "SESSION_SECRET_KEY",
        env.get("SESSION_SECRET_KEY"),
        required_in_production=True,
        production=production,
    )
    report.errors.extend(errors)
    report.warnings.extend(warnings)

    # Emergency unlock must not carry its historical default.
    emergency = (env.get("PHINS_EMERGENCY_UNLOCK_KEY") or "").strip()
    if emergency:
        if emergency.lower() in _FORBIDDEN_SECRETS:
            report.errors.append(
                "PHINS_EMERGENCY_UNLOCK_KEY matches a known-insecure default"
            )
        elif len(emergency.encode("utf-8")) < _MIN_BYTES:
            msg = "PHINS_EMERGENCY_UNLOCK_KEY is shorter than 32 bytes"
            if production:
                report.errors.append(msg)
            else:
                report.warnings.append(msg)

    # Admin password (used as a last-resort legacy fallback) must not be a
    # publicly-known default.
    admin_pw = (env.get("PHINS_ADMIN_PASSWORD") or "").strip()
    if admin_pw and admin_pw.lower() in _FORBIDDEN_SECRETS:
        report.errors.append("PHINS_ADMIN_PASSWORD matches a known-insecure default")

    allow_legacy = str(env.get("ALLOW_LEGACY_DEMO_PASSWORDS", "")).lower() in (
        "1",
        "true",
        "yes",
        "y",
    )
    if allow_legacy and production:
        report.errors.append(
            "ALLOW_LEGACY_DEMO_PASSWORDS is enabled in production"
        )

    return report


def log_report(report: SecretReport) -> None:
    """Emit the report to the logger; does not raise."""
    for warning in report.warnings:
        LOGGER.warning("[SECURITY] %s", warning)
    for error in report.errors:
        LOGGER.error("[SECURITY] %s", error)
    if report.ok and not report.warnings:
        LOGGER.info("[SECURITY] Secret policy checks passed")
