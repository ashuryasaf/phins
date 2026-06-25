"""
Regression guard for the customer-scoped role-detection bug class.

Premortem risk #1 (cross-tenant data). Several handlers historically computed a
caller's role as ``(user.get('role') or '').lower()`` -- reading only the
in-memory ``USERS`` map. A customer authenticated via a stateless token, or on a
replica whose ``USERS`` map lacks them (the multi-instance path
``validate_session`` explicitly supports), is then misclassified as
non-customer/staff and falls through to branches that honor a request-supplied
``customer_id`` -- leaking or mutating another customer's data.

This exact pattern leaked customer data three separate times before being
eradicated wholesale:

* ``/api/customer/status``            (fixed in #406)
* ``/api/billing/transactions``       (fixed in #406)
* ``/api/health-wallet/purchases``    (fixed in #407)
* 12 further handlers                 (fixed in #409)

The correct pattern is to fall back to the session role, e.g.::

    role = (user.get('role') or session.get('role') or '').lower()

or to use the existing ``get_effective_role(session)`` helper, which already does
this. This test fails if the unsafe ``USERS``-only form is reintroduced so the
bug class cannot quietly creep back in via copy-paste.
"""

from __future__ import annotations

import re
from pathlib import Path

# Files that contain request handlers / authorization logic.
WEB_PORTAL_DIR = Path(__file__).resolve().parent.parent / "web_portal"

# Matches role decisions derived from USERS only, tolerant of whitespace and
# quote style, e.g. (user.get('role') or '').lower() / ( user.get("role") or "" ).
# Crucially it does NOT match the safe form that falls back to the session role:
#   (user.get('role') or session.get('role') or '').lower()
_UNSAFE_ROLE_PATTERN = re.compile(
    r"""\(\s*user\.get\(\s*['"]role['"]\s*\)\s*or\s*['"]['"]\s*\)\.lower\(\)"""
)


def _python_files() -> list[Path]:
    return sorted(WEB_PORTAL_DIR.rglob("*.py"))


def test_no_users_only_role_detection_in_web_portal():
    """No handler may derive role from USERS without a session-role fallback."""
    offenders: list[str] = []
    for path in _python_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _UNSAFE_ROLE_PATTERN.search(line):
                rel = path.relative_to(WEB_PORTAL_DIR.parent)
                offenders.append(f"  {rel}:{lineno}: {line.strip()}")

    assert not offenders, (
        "USERS-only role detection reintroduced (premortem risk #1, cross-tenant "
        "data). Use a session-role fallback -- "
        "`(user.get('role') or session.get('role') or '').lower()` -- or "
        "`get_effective_role(session)`:\n" + "\n".join(offenders)
    )


def test_guard_pattern_actually_matches_the_known_bad_form():
    """Sanity: the guard regex detects the exact historical bug form.

    Prevents the guard from silently rotting into a no-op (e.g. if the pattern
    were broken), which would let the real bug back in undetected.
    """
    bad_examples = [
        "role = (user.get('role') or '').lower()",
        'role = (user.get("role") or "").lower()',
        "role = (user.get('role') or '').lower() if session else 'admin'",
    ]
    for example in bad_examples:
        assert _UNSAFE_ROLE_PATTERN.search(example), example

    safe_examples = [
        "role = (user.get('role') or session.get('role') or '').lower()",
        "role = (user.get('role') or (session.get('role') if session else '') or '').lower()",
        "role = get_effective_role(session)",
    ]
    for example in safe_examples:
        assert not _UNSAFE_ROLE_PATTERN.search(example), example
