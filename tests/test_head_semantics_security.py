"""
Regression tests for HTTP HEAD semantics + security controls.

HEAD responses must match GET status/headers behavior, but without a body.
In particular, HEAD must not bypass:
- IP blocking
- rate limiting
- query/input validation
and must not return 200 for non-existent paths.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal


class ServerThread(threading.Thread):
    """Thread to run the HTTP server in background."""

    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self) -> None:
        self.httpd.serve_forever()

    def stop(self) -> None:
        self.httpd.shutdown()


def _status(url: str, method: str) -> int:
    req = Request(url, method=method)
    try:
        with urlopen(req) as resp:
            # For HEAD, server should not return a body; don't depend on that here.
            return resp.status
    except HTTPError as e:
        return e.code


def test_head_matches_get_for_missing_path():
    port = 8091
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    try:
        base = f"http://127.0.0.1:{port}"
        path = "/__definitely_missing_404__"
        assert _status(base + path, "GET") == 404
        assert _status(base + path, "HEAD") == 404
    finally:
        srv.stop()


def test_head_enforces_ip_blocking_like_get():
    port = 8092
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    try:
        # Block localhost explicitly for this test (PHINS_TEST_MODE makes localhost non-trusted).
        portal.BLOCKED_IPS["127.0.0.1"] = {
            "reason": "test block",
            "blocked_at": datetime.now().isoformat(),
            "permanent": True,
            "attempts": 1,
        }

        base = f"http://127.0.0.1:{port}"
        assert _status(base + "/health", "GET") == 403
        assert _status(base + "/health", "HEAD") == 403
    finally:
        portal.BLOCKED_IPS.pop("127.0.0.1", None)
        srv.stop()


def test_head_enforces_rate_limiting_like_get():
    port = 8093
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    try:
        base = f"http://127.0.0.1:{port}"

        # Prime per-port state initialization.
        assert _status(base + "/health", "GET") in (200, 404)

        # Force rate-limit for this ip:port key.
        key = f"127.0.0.1:{port}"
        portal.RATE_LIMIT[key] = {
            "count": portal.MAX_REQUESTS_PER_MINUTE,
            "reset_time": datetime.now().timestamp() + 60,
        }

        assert _status(base + "/health", "GET") == 429
        assert _status(base + "/health", "HEAD") == 429
    finally:
        portal.RATE_LIMIT.pop(f"127.0.0.1:{port}", None)
        srv.stop()


def test_head_enforces_query_validation_like_get():
    port = 8094
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)
    try:
        base = f"http://127.0.0.1:{port}"
        # Query validation runs before endpoint handling; include an obvious XSS payload.
        url = base + "/api/system/status?limit=%3Cscript%3Ealert(1)%3C%2Fscript%3E"
        assert _status(url, "GET") == 400
        assert _status(url, "HEAD") == 400
    finally:
        srv.stop()

