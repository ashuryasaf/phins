"""
Global pytest configuration (applies to repo root tests too).

Why this exists:
- Several test suites assume an HTTP server is already running at http://localhost:8000
  (e.g. test_pr_complete.py defaults to that base URL and some tests hardcode it).
- We start an embedded server once per test session so E2E/API tests are deterministic.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import tempfile
from pathlib import Path
from typing import Optional


# Ensure repo root is importable for all tests (including tests outside /tests)
ROOT_DIR = Path(__file__).resolve().parent
root_str = str(ROOT_DIR)
if root_str not in sys.path:
    sys.path.insert(0, root_str)


def _pick_test_port(preferred: int = 8000) -> int:
    """
    Return a usable TCP port for the embedded test server.

    Strategy:
      1. If TEST_PORT env var is set, honor it.
      2. Else try to bind the preferred port (8000) so legacy tests that
         hard-code http://localhost:8000 still work in single-runner mode.
      3. If that port is taken (e.g. running pytest in parallel or another
         dev server is already on 8000), let the kernel pick a free port.
    """
    forced = os.environ.get("TEST_PORT")
    if forced:
        try:
            return int(forced)
        except ValueError:
            pass
    for candidate in (preferred, 0):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(("127.0.0.1", candidate))
                return probe.getsockname()[1]
        except OSError:
            continue
    return preferred  # last-resort fallback; later bind will raise


_TEST_PORT = _pick_test_port()
os.environ.setdefault("TEST_BASE_URL", f"http://localhost:{_TEST_PORT}")
os.environ.setdefault("TEST_PORT", str(_TEST_PORT))

# For the web portal (HTTP tests), use in-memory storage so each test server can be isolated.
# Database-layer tests still use SQLite via USE_SQLITE/SQLITE_PATH.
os.environ.setdefault("USE_DATABASE", "false")
os.environ.setdefault("USE_SQLITE", "true")
os.environ.setdefault("SQLITE_PATH", str(Path(tempfile.gettempdir()) / "phins_test.db"))
os.environ.setdefault("PHINS_TEST_MODE", "true")
# Keep BI KPI snapshots out of the repo's data/ directory during test runs.
os.environ.setdefault(
    "PHINS_BI_SNAPSHOT_DIR", str(Path(tempfile.gettempdir()) / "phins_test_bi_snapshots")
)


_httpd = None
_thread: Optional[threading.Thread] = None


def pytest_sessionstart(session):  # type: ignore[no-redef]
    """
    Start embedded web portal server for tests.

    Port selection follows _pick_test_port():
      - Honors TEST_PORT env override (CI / parallel pytest workers).
      - Defaults to 8000 when available so legacy tests that hard-code
        http://localhost:8000 keep working.
      - Falls back to a free kernel-assigned port if 8000 is busy.
    """
    global _httpd, _thread

    # Import lazily after env vars are set.
    from http.server import ThreadingHTTPServer
    import web_portal.server as portal

    host = "127.0.0.1"
    port = int(os.environ.get("TEST_PORT", _TEST_PORT))
    _httpd = ThreadingHTTPServer((host, port), portal.PortalHandler)
    # If the kernel picked a port (port 0 case), publish the real bound
    # port so tests reading TEST_PORT/TEST_BASE_URL see the right value.
    bound_port = _httpd.server_address[1]
    os.environ["TEST_PORT"] = str(bound_port)
    os.environ["TEST_BASE_URL"] = f"http://localhost:{bound_port}"
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

    # Reset options wheel singleton so each test starts clean.
    try:
        from services.options_wheel_service import reset_options_wheel_service
        reset_options_wheel_service()
        wheel_svc = getattr(portal, "options_wheel_service", None)
        if wheel_svc is not None:
            wheel_svc.positions.clear()
            wheel_svc.order_history.clear()
            wheel_svc.audit_log.clear()
    except Exception:
        pass

    # Reset document processing service in-memory state.
    try:
        from services.document_processing_service import reset_document_service
        reset_document_service()
    except Exception:
        pass

    # Reset assessment center in-memory state so customer 360 facts don't bleed between tests.
    try:
        from services.assessment_center_service import reset_assessment_center
        reset_assessment_center()
    except Exception:
        pass

    # Reset assessment records so decision-loop snapshots don't bleed between tests.
    try:
        from services.assessment_record_service import reset_assessment_record_service
        reset_assessment_record_service()
    except Exception:
        pass

    # Reset BI snapshot singleton so KPI trend tests stay isolated.
    try:
        from services.bi_snapshot_service import reset_bi_snapshot_service
        reset_bi_snapshot_service()
    except Exception:
        pass

    # Reset shared accounting engine so accounting ledger tests stay isolated.
    try:
        from accounting_engine import reset_accounting_engine
        reset_accounting_engine()
    except Exception:
        pass

    # Reset security hardening modules between tests.
    try:
        from security.firewall import reset_firewall
        reset_firewall()
    except Exception:
        pass
    try:
        from security.intrusion_detector import reset_ids
        reset_ids()
    except Exception:
        pass

