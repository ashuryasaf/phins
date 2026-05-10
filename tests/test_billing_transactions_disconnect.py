"""
Regression tests for /api/billing/transactions client-disconnect handling.

Background
----------
Production logs on Railway showed back-to-back errors like::

    "GET /api/billing/transactions HTTP/1.1" 200 -
    "GET /api/billing/transactions HTTP/1.1" 500 -
    Exception occurred during processing of request from ('100.64.0.10', 48344)
    BrokenPipeError: [Errno 32] Broken pipe
    During handling of the above exception, another exception occurred:
    BrokenPipeError: [Errno 32] Broken pipe

The first BrokenPipeError came from ``self.wfile.write(...)`` after the
client disconnected mid-response. The endpoint's blanket ``except Exception``
then tried to send a 500 via ``_set_json_headers(500)`` — but the 200 status
line and headers had already been flushed and the socket was dead, so
``flush_headers()`` raised a *second* BrokenPipeError that escaped the
handler entirely. ``socketserver.BaseServer`` then printed the noisy
"Exception occurred during processing of request" traceback.

These tests pin down the two fixes:

1. ``/api/billing/transactions`` no longer attempts a 500 fallback after
   the response body has begun streaming; ``BrokenPipeError`` /
   ``ConnectionResetError`` / ``ConnectionAbortedError`` during the write
   phase are silently absorbed.
2. ``PortalHandler.handle()`` swallows the same client-disconnect errors
   globally, so other endpoints with the legacy try/except pattern can no
   longer spam tracebacks into the deploy log when a client goes away.

The embedded server fixture from the root ``conftest.py`` is reused.
"""

from __future__ import annotations

import http.client
import http.server
import json
import socket

import pytest


def _get_response(path: str) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=10)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def test_billing_transactions_returns_200_when_empty():
    """Smoke test: the endpoint still returns valid JSON in the happy path."""
    status, body = _get_response("/api/billing/transactions")
    assert status == 200
    payload = json.loads(body.decode("utf-8"))
    assert "transactions" in payload
    assert isinstance(payload["transactions"], list)


def test_billing_transactions_returns_200_with_data():
    """Populate BILLING/CUSTOMERS and confirm the endpoint serialises them."""
    import web_portal.server as portal

    # The first request to a port triggers ``_ensure_test_port_state`` which
    # clears in-memory stores. Mark the port as initialised up front so our
    # injected fixtures survive the next request.
    portal._TEST_PORTS_INITIALIZED.add(8000)

    portal.CUSTOMERS["CUST-DISC-1"] = {
        "customer_id": "CUST-DISC-1",
        "name": "Disconnect Tester",
    }
    portal.BILLING["BILL-DISC-1"] = {
        "bill_id": "BILL-DISC-1",
        "customer_id": "CUST-DISC-1",
        "policy_id": None,
        "amount": 42.0,
        "status": "paid",
        "payment_method": "credit_card",
        "card_last4": "1234",
        "created_date": "2026-05-10T11:24:10",
    }

    try:
        status, body = _get_response("/api/billing/transactions")
        assert status == 200
        payload = json.loads(body.decode("utf-8"))
        ids = [t.get("id") for t in payload["transactions"]]
        assert "BILL-DISC-1" in ids
    finally:
        portal.BILLING.pop("BILL-DISC-1", None)
        portal.CUSTOMERS.pop("CUST-DISC-1", None)


def test_server_survives_client_disconnect_mid_request():
    """
    Send a partial request and slam the socket shut. The server must not
    crash, and the next normal request must still succeed. This validates
    that the global ``handle()`` wrapper doesn't break legitimate traffic
    when a peer disconnects abruptly (the same scenario the Railway log
    captured for /api/billing/transactions).
    """
    sock = socket.create_connection(("127.0.0.1", 8000), timeout=5)
    try:
        sock.sendall(b"GET /api/billing/transactions HTTP/1.1\r\nHost: localhost\r\n\r\n")
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
    finally:
        sock.close()

    status, body = _get_response("/api/billing/transactions")
    assert status == 200
    assert b"transactions" in body


def test_portal_handle_swallows_broken_pipe(monkeypatch, capsys):
    """
    The global override on ``PortalHandler.handle`` must absorb
    BrokenPipeError / ConnectionResetError / ConnectionAbortedError so the
    underlying ``socketserver.BaseServer`` never prints the
    "Exception occurred during processing of request" traceback.
    """
    from web_portal.server import PortalHandler

    cases = [
        BrokenPipeError(32, "Broken pipe"),
        ConnectionResetError(104, "Connection reset by peer"),
        ConnectionAbortedError(103, "Software caused connection abort"),
    ]

    for exc in cases:
        instance = PortalHandler.__new__(PortalHandler)
        instance.client_address = ("100.64.0.10", 48344)
        instance.path = "/api/billing/transactions"

        def boom(self, _exc=exc):
            raise _exc

        monkeypatch.setattr(http.server.BaseHTTPRequestHandler, "handle", boom)

        instance.handle()

        out = capsys.readouterr().out
        assert "100.64.0.10" in out
        assert "/api/billing/transactions" in out
        assert type(exc).__name__ in out


def test_portal_handle_lets_other_exceptions_through(monkeypatch):
    """Non-disconnect errors must still propagate so real bugs stay visible."""
    from web_portal.server import PortalHandler

    instance = PortalHandler.__new__(PortalHandler)
    instance.client_address = ("127.0.0.1", 1)
    instance.path = "/"

    def boom(self):
        raise RuntimeError("not a disconnect")

    monkeypatch.setattr(http.server.BaseHTTPRequestHandler, "handle", boom)

    with pytest.raises(RuntimeError, match="not a disconnect"):
        instance.handle()
