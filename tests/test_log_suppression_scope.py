"""
Security observability regression tests for 4xx access-log suppression.

PR #308 added two suppression mechanisms intended to keep Railway deploy logs
quiet under healthy traffic:

* ``_should_silence_internal_probe`` drops 4xx access-log lines on a small
  set of ``/api/security/*`` paths when the source IP is in a CGNAT/private
  range (Railway edge / sibling-service traffic).
* ``_should_suppress_repeat_4xx`` drops further log lines when the same
  ``(client_ip, path, code)`` tuple repeats more than 3 times within a
  300-second window.

Both mechanisms are sound for *liveness-style* paths but become a liability
on auth-sensitive paths: repeated 401/403 hits on ``/api/login``,
``/api/admin/*`` and ``/api/auth/*`` are the canonical signature of
credential-stuffing, brute force, and lateral-movement attacks. Silencing
them — even partially — meaningfully degrades incident response.

The fix keeps the suppression machinery for benign paths but bypasses it for
a frozen list of auth-sensitive prefixes. These tests pin that behaviour.
"""

from __future__ import annotations

import time

import pytest

import web_portal.server as portal


# ── _should_silence_internal_probe ───────────────────────────────────────────


class TestInternalProbeSilencingScope:
    def test_security_dashboard_from_internal_ip_is_silenced(self):
        # Baseline: the documented path/IP combination is still silenced so
        # we don't regress the original "Railway monitor flood" fix.
        assert portal._should_silence_internal_probe(
            '100.64.1.2', '/api/security/dashboard', 401,
        ) is True

    def test_external_ip_is_never_silenced(self):
        assert portal._should_silence_internal_probe(
            '8.8.8.8', '/api/security/dashboard', 401,
        ) is False

    def test_admin_endpoint_from_internal_ip_is_logged(self):
        # An attacker on a compromised sibling service could probe
        # /api/admin/* from an internal IP. The fix forces those hits to be
        # logged regardless of source.
        for path in (
            '/api/admin/pipeline-process-all',
            '/api/admin/suspend-account',
            '/api/admin/customers/upload',
        ):
            for code in (401, 403, 404):
                assert portal._should_silence_internal_probe(
                    '10.0.0.5', path, code,
                ) is False, f"silenced {path} ({code}) — security regression"

    def test_login_path_is_never_silenced(self):
        for code in (401, 403, 429):
            assert portal._should_silence_internal_probe(
                '10.0.0.5', '/api/login', code,
            ) is False

    def test_auth_and_session_paths_are_never_silenced(self):
        for path in ('/api/auth/login', '/api/auth_validate', '/api/session/validate'):
            assert portal._should_silence_internal_probe(
                '172.20.5.5', path, 401,
            ) is False


# ── _should_suppress_repeat_4xx ───────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_repeat_log_state():
    """Reset the repeat-log dict between tests so windows don't leak state."""
    portal._REPEAT_LOG_STATE.clear()
    yield
    portal._REPEAT_LOG_STATE.clear()


class TestRepeat4xxSuppressionScope:
    def test_login_brute_force_is_never_suppressed(self):
        """100 identical 401s on /api/login must each return False."""
        for _ in range(100):
            suppress, _count = portal._should_suppress_repeat_4xx(
                '203.0.113.10', '/api/login', 401,
            )
            assert suppress is False

    def test_admin_endpoint_repeats_are_never_suppressed(self):
        for _ in range(50):
            suppress, _count = portal._should_suppress_repeat_4xx(
                '203.0.113.10', '/api/admin/pipeline-process-all', 403,
            )
            assert suppress is False

    def test_session_endpoint_repeats_are_never_suppressed(self):
        for _ in range(20):
            suppress, _count = portal._should_suppress_repeat_4xx(
                '203.0.113.10', '/api/session/validate', 401,
            )
            assert suppress is False

    def test_benign_endpoint_repeats_are_still_suppressed(self):
        """The original behaviour for benign paths must remain in place."""
        # First _REPEAT_LOG_THRESHOLD hits pass through.
        for _ in range(portal._REPEAT_LOG_THRESHOLD):
            suppress, _count = portal._should_suppress_repeat_4xx(
                '203.0.113.20', '/api/customers/lookup', 404,
            )
            assert suppress is False
        # Subsequent hits within the window are suppressed.
        suppress, _count = portal._should_suppress_repeat_4xx(
            '203.0.113.20', '/api/customers/lookup', 404,
        )
        assert suppress is True

    def test_non_4xx_codes_are_never_tracked(self):
        for code in (200, 201, 302, 500):
            for _ in range(5):
                suppress, _count = portal._should_suppress_repeat_4xx(
                    '203.0.113.30', '/api/anything', code,
                )
                assert suppress is False

    def test_static_paths_are_never_tracked(self):
        for _ in range(10):
            suppress, _count = portal._should_suppress_repeat_4xx(
                '203.0.113.40', '/static/foo.js', 404,
            )
            assert suppress is False
