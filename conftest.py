"""
Global pytest configuration (applies to repo root tests too).

Why this exists:
- Several test suites assume an HTTP server is already running at http://localhost:8000
  (e.g. test_pr_complete.py defaults to that base URL and some tests hardcode it).
- We start an embedded server once per test session so E2E/API tests are deterministic.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path
from typing import Optional


# Ensure repo root is importable for all tests (including tests outside /tests)
ROOT_DIR = Path(__file__).resolve().parent
root_str = str(ROOT_DIR)
if root_str not in sys.path:
    sys.path.insert(0, root_str)


# Ensure tests that read BASE_URL at import time see a valid URL.
os.environ.setdefault("TEST_BASE_URL", "http://localhost:8000")

# For the web portal (HTTP tests), use in-memory storage so each test server can be isolated.
# Database-layer tests still use SQLite via USE_SQLITE/SQLITE_PATH.
os.environ.setdefault("USE_DATABASE", "false")
os.environ.setdefault("USE_SQLITE", "true")
os.environ.setdefault("SQLITE_PATH", "/tmp/phins_test.db")
os.environ.setdefault("PHINS_TEST_MODE", "true")


_httpd = None
_thread: Optional[threading.Thread] = None


def pytest_sessionstart(session):  # type: ignore[no-redef]
    """Start embedded web portal server for tests that expect localhost:8000."""
    global _httpd, _thread

    # Import lazily after env vars are set.
    from http.server import ThreadingHTTPServer
    import web_portal.server as portal

    # Start server on the expected port.
    host, port = "127.0.0.1", 8000
    _httpd = ThreadingHTTPServer((host, port), portal.PortalHandler)
    _thread = threading.Thread(target=_httpd.serve_forever, daemon=True)
    _thread.start()


def pytest_sessionfinish(session, exitstatus):  # type: ignore[no-redef]
    """Shutdown embedded server."""
    global _httpd
    if _httpd is not None:
        try:
            _httpd.shutdown()
        except Exception:
            pass
        _httpd = None


def pytest_runtest_setup(item):  # type: ignore[no-redef]
    """
    Ensure each test starts from a clean in-memory portal state.

    Many tests create customers/policies using fixed IDs/emails; without clearing, they can collide across tests.
    """
    if "web_portal.server" not in sys.modules:
        return
    try:
        import web_portal.server as portal
    except Exception:
        return

    if not getattr(portal, "PHINS_TEST_MODE", False):
        return

    # Clear only in-memory dict-like stores (do not clear USERS).
    for attr in [
        "POLICIES",
        "CLAIMS",
        "CUSTOMERS",
        "UNDERWRITING_APPLICATIONS",
        "SESSIONS",
        "BILLING",
        "HEALTH_WALLETS",
        "MEDICAL_PURCHASES",
        "INVESTMENT_ACCOUNTS",
        "CUSTOMER_ALLOCATIONS",
        "TRANSACTION_LEDGER",
        "RATE_LIMIT",
        "FAILED_LOGINS",
        "BLOCKED_IPS",
        "SUSPICIOUS_PATTERNS",
    ]:
        try:
            obj = getattr(portal, attr, None)
            if isinstance(obj, dict):
                obj.clear()
        except Exception:
            pass

    # Reset per-port initialization tracker (so handlers don't unexpectedly wipe state mid-test).
    try:
        init_set = getattr(portal, "_TEST_PORTS_INITIALIZED", None)
        if isinstance(init_set, set):
            init_set.clear()
    except Exception:
        pass

