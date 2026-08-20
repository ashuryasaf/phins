"""Runtime validation of security-critical secrets.

Called once at startup from ``web_portal/server.py``. The goals are:

* Refuse to mint tokens with weak/missing signing keys in production.
* Warn loudly in test/dev when defaults are in use.
* Forbid the historical hardcoded ``phins-emergency-unlock-2026`` literal.

The audit helpers only emit log lines and return a structured report; they
never mutate global state. Callers decide whether a failing check should abort
startup or just warn. The one exception is :func:`ensure_session_secret_key`,
which intentionally provisions a strong key into the environment when none is
configured (documented at its definition).
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from typing import Callable, List, Optional


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


def _is_railway_preview_environment(name: str) -> bool:
    """Return True for Railway PR-preview environment names.

    Railway names these ``pr-539`` or ``<service>-pr-539`` (for example
    ``phins-pr-539``). A startswith(``pr-``) check misses the service-prefixed
    form, and PR environments inherit ``PHINS_ENVIRONMENT=production`` from
    the parent service, so they must be recognized before that inherited
    label is trusted.
    """
    token = (name or "").strip().lower()
    if not token:
        return False
    if token.startswith("pr-"):
        return True
    parts = token.split("-")
    for index, part in enumerate(parts[:-1]):
        nxt = parts[index + 1]
        if part == "pr" and nxt[:1].isdigit():
            return True
    return False


def _is_production(environ: Optional[dict] = None) -> bool:
    env = environ if environ is not None else os.environ
    if str(env.get("PHINS_TEST_MODE", "")).lower() in ("1", "true", "yes", "y"):
        return False
    # Railway PR environments clone production variables. The environment
    # *name* is the source of truth — treat previews as non-production even
    # when they inherited PHINS_ENVIRONMENT=production.
    railway_env = str(env.get("RAILWAY_ENVIRONMENT", "")).strip().lower()
    railway_env_name = str(env.get("RAILWAY_ENVIRONMENT_NAME", "")).strip().lower()
    if _is_railway_preview_environment(railway_env) or _is_railway_preview_environment(
        railway_env_name
    ):
        return False
    production_labels = {"production", "prod", "live"}
    non_production_labels = {"development", "dev", "staging", "stage", "test", "testing"}
    env_label = str(
        env.get("PHINS_ENVIRONMENT", env.get("ENVIRONMENT", env.get("ENV", "")))
    ).strip().lower()
    if env_label in production_labels:
        return True
    if env_label in non_production_labels:
        return False
    if railway_env in production_labels:
        return True
    if railway_env in non_production_labels:
        return False
    # Render sets a platform flag; if no explicit environment hint is present,
    # keep the previous secure default and treat it as production.
    if env.get("RENDER"):
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
        # In production, a known-insecure default is hard-failed so the boot
        # sequence aborts. In test/dev we still want the test runner to start,
        # so downgrade to a warning. The length check below still runs; it
        # catches the same condition from a different angle.
        msg = f"{env_name} matches a known-insecure default"
        if production:
            errors.append(msg)
        else:
            warnings.append(msg)

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
            msg = "PHINS_EMERGENCY_UNLOCK_KEY matches a known-insecure default"
            if production:
                report.errors.append(msg)
            else:
                report.warnings.append(msg)
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
        msg = "PHINS_ADMIN_PASSWORD matches a known-insecure default"
        if production:
            report.errors.append(msg)
        else:
            report.warnings.append(msg)

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


def generate_session_secret_key() -> str:
    """Return a fresh, cryptographically strong signing key (>= 32 bytes)."""
    return secrets.token_urlsafe(48)


def ensure_session_secret_key(
    environ: Optional[dict] = None,
    *,
    generator: Optional[Callable[[], str]] = None,
) -> Optional[str]:
    """Provision a strong ``SESSION_SECRET_KEY`` into ``environ`` if missing.

    A missing key would otherwise force auth to degrade to insecure legacy v1
    tokens (or, under the fail-closed startup policy, block boot entirely).
    Generating a strong random key keeps token signing secure by default.

    Only the *absent* case is provisioned: an explicitly configured key (even a
    weak one) is left untouched so the audit can still flag it and fail closed.

    Returns the generated key, or ``None`` if a usable key was already present.

    NOTE: unlike the audit helpers, this intentionally mutates ``environ`` (the
    process environment by default) so the rest of the process sees the key.

    Caveat: an auto-generated key is process-local, so it is not stable across
    restarts or replicas. Operators should still set a persistent
    ``SESSION_SECRET_KEY`` for durable sessions in multi-instance deployments.
    """
    env = environ if environ is not None else os.environ
    existing = (env.get("SESSION_SECRET_KEY") or "").strip()
    if existing:
        return None
    key = (generator or generate_session_secret_key)()
    env["SESSION_SECRET_KEY"] = key
    return key


def _enforcement_override(environ: Optional[dict] = None) -> Optional[bool]:
    """Return the explicit operator override for secret-policy enforcement.

    ``PHINS_ENFORCE_SECRET_POLICY`` semantics:
      * truthy  -> always enforce (abort on violations)
      * falsy   -> never enforce (continue despite violations) -- escape hatch
      * unset   -> ``None`` (caller applies the secure default)
    """
    env = environ if environ is not None else os.environ
    raw = env.get("PHINS_ENFORCE_SECRET_POLICY")
    if raw is None:
        return None
    token = str(raw).strip().lower()
    if token in ("1", "true", "yes", "y", "on"):
        return True
    if token in ("0", "false", "no", "n", "off"):
        return False
    # Unrecognized value: treat as unset so the secure default applies.
    return None


def should_abort_startup(
    report: SecretReport, environ: Optional[dict] = None
) -> tuple[bool, str]:
    """Decide whether secret-policy violations should abort startup.

    Fail-closed by default in production: when the audit reports errors in a
    production runtime the process refuses to boot, UNLESS an operator has
    explicitly opted out via ``PHINS_ENFORCE_SECRET_POLICY=false`` (a deliberate,
    documented escape hatch). Non-production runtimes never abort -- they only
    warn -- so local dev and the test suite keep working.

    Returns ``(abort, reason)``.
    """
    if report.ok:
        return False, ""
    if not report.production_mode:
        # Dev/test: surface via warnings/logs, never block startup.
        return False, ""

    override = _enforcement_override(environ)
    if override is False:
        return False, "PHINS_ENFORCE_SECRET_POLICY explicitly disabled"
    # override is True (explicit) or None (secure default) -> enforce.
    return True, "; ".join(report.errors)


def log_report(report: SecretReport) -> None:
    """Emit the report to the logger; does not raise."""
    for warning in report.warnings:
        LOGGER.warning("[SECURITY] %s", warning)
    for error in report.errors:
        LOGGER.error("[SECURITY] %s", error)
    if report.ok and not report.warnings:
        LOGGER.info("[SECURITY] Secret policy checks passed")
