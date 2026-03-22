import json
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal


class ServerThread(threading.Thread):
    def __init__(self, port):
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


def _json_request(url, method="GET", payload=None, token=None):
    headers = {}
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    else:
        data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body else {}


def _init_port(base):
    try:
        _json_request(base + "/api/health")
    except Exception:
        pass


def _inject_session(token, username="admin", role="admin"):
    portal.SESSIONS[token] = {
        "username": username,
        "role": role,
        "customer_id": "",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    if username not in portal.USERS:
        portal.USERS[username] = {"role": role, "username": username}


def test_admin_assistant_returns_action_for_bulk_pipeline_request():
    port = 8293
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_admin_assistant_token"
    _inject_session(token, "admin", "admin")

    try:
        status, payload = _json_request(
            base + "/api/admin/assistant",
            method="POST",
            token=token,
            payload={"query": "Please process all customer pipelines now"},
        )

        assert status == 200
        assert payload["success"] is True
        assert payload["intent"] == "action"
        assert payload["action"]["id"] == "process_all_pipelines"
        assert payload["action"]["requires_confirmation"] is True
        assert any("Customers:" in line for line in payload["summary_lines"])
    finally:
        srv.stop()


def test_admin_assistant_requires_admin_role():
    port = 8294
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_non_admin_assistant_token"
    _inject_session(token, "customer@example.com", "customer")

    try:
        status, payload = _json_request(
            base + "/api/admin/assistant",
            method="POST",
            token=token,
            payload={"query": "Give me a dashboard summary"},
        )

        assert status == 403
        assert payload == {"error": "Admin access required"}
    finally:
        srv.stop()
