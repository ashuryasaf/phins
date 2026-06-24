"""
API customer ledger isolation test
==================================

Ensures `/api/ledger` enforces customer data isolation:
- customer role can only access their own customer_id
"""

import json
import threading
import time
from http.server import HTTPServer
from urllib.request import urlopen, Request
from urllib.error import HTTPError

import web_portal.server as portal


class ServerThread(threading.Thread):
    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _post(url: str, payload: dict, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode("utf-8")
    req = Request(url, data=data, headers=headers)
    with urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.status


def _get(url: str, token: str | None = None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.status


def _reset_customer_state():
    with portal.STATE_LOCK:
        portal.CUSTOMERS.clear()
        portal.HEALTH_WALLETS.clear()
        portal.BILLING.clear()
        portal.POLICIES.clear()
        portal.UNDERWRITING_APPLICATIONS.clear()
        portal.CLAIMS.clear()
        # ledgers are global but safe to clear for isolated test
        portal.TRANSACTION_LEDGER.clear()
        portal.NFT_LEDGER.clear()


def test_customer_cannot_access_other_customer_ledger():
    _reset_customer_state()

    port = 8161
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.5)
    base = f"http://127.0.0.1:{port}"

    try:
        email = "ledger_test_customer@example.com"
        password = "SecurePass123!"

        reg, status = _post(
            f"{base}/api/register",
            {
                "name": "Ledger Test Customer",
                "email": email,
                "password": password,
                "phone": "555-0000",
                "invitation_code": "TESTCODE2026",
            },
        )
        assert status == 201
        cust_id = reg.get("customer_id")
        assert cust_id

        login, status = _post(f"{base}/api/login", {"username": email, "password": password})
        assert status == 200
        token = login["token"]

        # Customer can query ledger without specifying customer_id (defaults to own)
        own_ledger, status = _get(f"{base}/api/ledger", token=token)
        assert status == 200
        assert own_ledger.get("filters_applied", {}).get("customer_id") == cust_id

        # Customer must NOT query other customer's ledger
        try:
            _get(f"{base}/api/ledger?customer_id=CUST-OTHER-999", token=token)
            assert False, "Expected HTTPError(403) for cross-customer ledger access"
        except HTTPError as e:
            assert e.code == 403

    finally:
        srv.stop()

