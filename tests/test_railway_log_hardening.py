"""
Regression tests for the production hardening derived from Railway deploy
logs (see PR #307).

Two real bugs were observed:

1. ``/api/security/dashboard`` was being polled every 30 seconds from a
   Railway-internal IP without auth, producing a 403 storm in ``railway
   logs``. The endpoint was correct - the *log volume* was the problem.

2. Multiple ``fetch('/api/...')`` calls in ``dashboard.html`` were issued
   without an ``Authorization`` header, so customer dashboards loaded with
   401/403 responses on /api/customer/activity-log, /api/statement,
   /api/health-wallet/purchases, /api/nft-ledger, /api/balance/unified,
   /api/savings/accounts, /api/investment/unified.

This module asserts:

* the repetitive 4xx log suppressor stops emitting after the configured
  threshold, then resumes once the window expires, and
* every front-end page that depends on customer-scoped GET routes loads
  the ``ui-clarity.js`` shim that injects the auth token.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_repetitive_4xx_log_suppression_kicks_in():
    import web_portal.server as portal

    # Clear and tighten the window so the test runs deterministically.
    with portal._REPEAT_LOG_LOCK:
        portal._REPEAT_LOG_STATE.clear()
    original_threshold = portal._REPEAT_LOG_THRESHOLD
    portal._REPEAT_LOG_THRESHOLD = 2  # type: ignore[assignment]

    try:
        # First two hits pass through.
        for _ in range(portal._REPEAT_LOG_THRESHOLD):
            suppress, missed = portal._should_suppress_repeat_4xx(
                "100.64.0.3", "/api/security/dashboard", "403"
            )
            assert suppress is False
            assert missed == 0

        # Subsequent identical hits get silenced.
        for _ in range(50):
            suppress, missed = portal._should_suppress_repeat_4xx(
                "100.64.0.3", "/api/security/dashboard", "403"
            )
            assert suppress is True
            assert missed == 0

        with portal._REPEAT_LOG_LOCK:
            state = portal._REPEAT_LOG_STATE[("100.64.0.3", "/api/security/dashboard", "403")]
        assert state["suppressed"] >= 50
    finally:
        portal._REPEAT_LOG_THRESHOLD = original_threshold  # type: ignore[assignment]


def test_repeat_log_suppression_resumes_with_summary():
    import web_portal.server as portal

    with portal._REPEAT_LOG_LOCK:
        portal._REPEAT_LOG_STATE.clear()
    portal._REPEAT_LOG_THRESHOLD = 1  # type: ignore[assignment]
    portal._REPEAT_LOG_WINDOW_S = 0.2  # type: ignore[assignment]

    # First hit logs.
    suppress, _ = portal._should_suppress_repeat_4xx("9.9.9.9", "/api/widgets", "401")
    assert suppress is False
    # Second hit suppressed.
    suppress, _ = portal._should_suppress_repeat_4xx("9.9.9.9", "/api/widgets", "401")
    assert suppress is True

    import time as _time
    _time.sleep(0.3)

    # Window expired - the next hit logs and reports the suppressed total.
    suppress, summary_count = portal._should_suppress_repeat_4xx(
        "9.9.9.9", "/api/widgets", "401"
    )
    assert suppress is False
    assert summary_count >= 1


def test_only_4xx_api_paths_are_suppressed():
    import web_portal.server as portal

    with portal._REPEAT_LOG_LOCK:
        portal._REPEAT_LOG_STATE.clear()
    # 200 should never be suppressed regardless of repetition.
    for _ in range(20):
        suppress, _ = portal._should_suppress_repeat_4xx(
            "1.2.3.4", "/api/health", "200"
        )
        assert suppress is False
    # Static asset requests (non /api/) also pass through unmodified.
    for _ in range(20):
        suppress, _ = portal._should_suppress_repeat_4xx(
            "1.2.3.4", "/styles.css", "404"
        )
        assert suppress is False


# ── UI shim assertions ─────────────────────────────────────────────────────

UI_CLARITY = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "ui-clarity.js"


def test_ui_clarity_installs_auth_fetch_shim():
    """The shim is the safety net for missing Authorization headers - it
    must remain in ui-clarity.js so every page that loads ui-clarity.js
    inherits the protection automatically.
    """
    text = UI_CLARITY.read_text(encoding="utf-8")
    assert "__phinsAuthFetchInstalled" in text
    assert "Authorization" in text
    assert "Bearer " in text
    assert "/api/" in text


@pytest.mark.parametrize("page", [
    "dashboard.html",
    "documents.html",
    "assessment-center.html",
    "risk-dashboard.html",
    "risk-reports-dashboard.html",
    "admin.html",
])
def test_pages_load_ui_clarity_shim(page):
    """Pages that issue authenticated /api/ requests must include
    ui-clarity.js so the auth-fetch shim activates and the production
    401/403 storm cannot recur.
    """
    path = Path(__file__).resolve().parents[1] / "web_portal" / "static" / page
    assert path.exists(), f"Missing static page: {page}"
    content = path.read_text(encoding="utf-8")
    assert "ui-clarity.js" in content, (
        f"{page} does not load ui-clarity.js; missing-Authorization "
        "regressions could re-appear in Railway logs."
    )
