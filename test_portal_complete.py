#!/usr/bin/env python3
"""
Comprehensive PHINS Admin Portal Test
Spins up the demo server and verifies core endpoints.
"""

import json
import threading
import time
from http.server import HTTPServer

import requests
import web_portal.server as portal


class ServerThread(threading.Thread):
    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


ACCOUNTS = {
    "admin": {
        "password": "admin123",
        "expected_role": "admin",
        "expected_name": "Admin User",
    },
    "underwriter": {
        "password": "under123",
        "expected_role": "underwriter",
        "expected_name": "John Underwriter",
    },
    "claims_adjuster": {
        "password": "claims123",
        "expected_role": "claims",
        "expected_name": "Jane Claims",
    },
    "accountant": {
        "password": "acct123",
        "expected_role": "accountant",
        "expected_name": "Bob Accountant",
    },
}


def test_admin_portal_end_to_end():
    port = 8012
    server = ServerThread(port)
    server.start()
    time.sleep(0.2)

    base_url = f"http://127.0.0.1:{port}"

    try:
        # Static pages load
        for path in ["/", "/admin-portal.html", "/admin.html", "/login.html", "/dashboard.html"]:
            resp = requests.get(base_url + path, timeout=5)
            assert resp.status_code == 200

        # Log in with all demo accounts
        tokens = {}
        for username, details in ACCOUNTS.items():
            resp = requests.post(
                f"{base_url}/api/login",
                json={"username": username, "password": details["password"]},
                headers={"Content-Type": "application/json"},
                timeout=5,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data.get("token", "").startswith("phins_")
            assert data.get("role") == details["expected_role"]
            assert data.get("name") == details["expected_name"]
            tokens[username] = data["token"]

        # Use admin token for authenticated endpoints
        headers = {"Authorization": f"Bearer {tokens['admin']}"}
        endpoints = [
            "/api/policies",
            "/api/claims",
            "/api/underwriting",
            "/api/customers",
            "/api/bi/actuary",
            "/api/bi/underwriting",
            "/api/bi/accounting",
        ]
        for path in endpoints:
            resp = requests.get(base_url + path, headers=headers, timeout=5)
            assert resp.status_code == 200
            json.loads(resp.text)  # response is valid JSON
    finally:
        server.stop()
