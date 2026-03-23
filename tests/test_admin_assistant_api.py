import json
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer
from pathlib import Path
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
    portal._ensure_test_port_state(port)

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


def test_admin_assistant_returns_multi_step_workflow_plan():
    port = 8295
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    portal._ensure_test_port_state(port)

    token = "phins_test_admin_assistant_workflow_token"
    _inject_session(token, "admin", "admin")

    try:
        status, payload = _json_request(
            base + "/api/admin/assistant",
            method="POST",
            token=token,
            payload={"query": "show AI insights, then run reconciliation"},
        )

        assert status == 200
        assert payload["success"] is True
        assert payload["intent"] == "workflow"
        assert payload["workflow"]["current_step_index"] == 0
        assert [step["action"]["id"] for step in payload["workflow"]["steps"]] == [
            "load_ai_insights",
            "reconcile_balance_sheet",
        ]
        assert payload["workflow"]["steps"][0]["status"] == "ready"
        assert payload["workflow"]["steps"][1]["status"] == "pending"
    finally:
        srv.stop()


def test_admin_assistant_returns_conditional_workflow_plan():
    port = 8296
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    portal._ensure_test_port_state(port)

    token = "phins_test_admin_assistant_conditional_token"
    _inject_session(token, "admin", "admin")

    try:
        status, payload = _json_request(
            base + "/api/admin/assistant",
            method="POST",
            token=token,
            payload={"query": "validate all customers, then process pipelines if issues are found"},
        )

        assert status == 200
        assert payload["success"] is True
        assert payload["intent"] == "workflow"
        steps = payload["workflow"]["steps"]
        assert [step["action"]["id"] for step in steps] == [
            "validate_all_customers",
            "process_all_pipelines",
        ]
        assert steps[1]["condition"]["type"] == "requires_previous_issues"
        assert "issues are found" in steps[1]["condition"]["source"]
    finally:
        srv.stop()


def test_admin_assistant_requires_admin_role():
    port = 8294
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    portal._ensure_test_port_state(port)

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


def test_admin_assistant_workflow_state_persists_via_database():
    from database import init_database
    from database.manager import DatabaseManager
    original_use_database = portal.USE_DATABASE
    original_database_enabled = getattr(portal, 'database_enabled', False)

    try:
        init_database()
        portal.USE_DATABASE = True
        portal.database_enabled = True

        workflow_payload = {
            "workflow_id": "admin-wf-persisted",
            "label": "Show AI insights -> Reconcile balance sheet",
            "current_step_index": 1,
            "steps": [
                {
                    "id": "load_ai_insights",
                    "label": "Open AI financial insights",
                    "description": "Load insights",
                    "status": "completed",
                    "step_index": 0,
                    "action": {
                        "id": "load_ai_insights",
                        "label": "Open AI financial insights",
                        "description": "Load insights",
                        "requires_confirmation": False,
                        "button_text": "Run action",
                    },
                },
                {
                    "id": "reconcile_balance_sheet",
                    "label": "Reconcile balance sheet",
                    "description": "Reconcile reserves",
                    "status": "ready",
                    "step_index": 1,
                    "action": {
                        "id": "reconcile_balance_sheet",
                        "label": "Reconcile balance sheet",
                        "description": "Reconcile reserves",
                        "requires_confirmation": True,
                        "button_text": "Run action",
                    },
                },
            ],
        }

        workflow_id = portal.save_admin_assistant_workflow_state("admin", workflow_payload)
        assert workflow_id == "admin-wf-persisted"

        restored = portal.get_admin_assistant_workflow_state("admin")
        assert restored is not None
        assert restored["workflow_id"] == "admin-wf-persisted"
        assert restored["steps"][1]["id"] == "reconcile_balance_sheet"

        with DatabaseManager() as db:
            record = db.admin_assistant_workflows.get_by_owner("admin")
            assert record is not None
            assert record.workflow_id == "admin-wf-persisted"
            assert record.to_dict()["workflow_state"]["current_step_index"] == 1

        assert portal.clear_admin_assistant_workflow_state("admin") is True
        assert portal.get_admin_assistant_workflow_state("admin") is None
    finally:
        portal.USE_DATABASE = original_use_database
        portal.database_enabled = original_database_enabled


def test_admin_assistant_persists_and_clears_workflow_state():
    port = 8297
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    portal._ensure_test_port_state(port)

    token = "phins_test_admin_assistant_persist_token"
    _inject_session(token, "admin", "admin")

    workflow_payload = {
        "workflow_id": "admin-wf-test-persist",
        "label": "Validate all customers -> Process all pipelines",
        "current_step_index": 1,
        "steps": [
            {
                "id": "validate_all_customers",
                "label": "Validate all customers",
                "description": "Validate customer records",
                "status": "completed",
                "step_index": 0,
                "action": {
                    "id": "validate_all_customers",
                    "label": "Validate all customers",
                    "description": "Validate customer records",
                    "requires_confirmation": False,
                    "button_text": "Run action",
                },
                "last_result": {
                    "success": True,
                    "issues_found": 2,
                    "message": "Validation found 2 issues.",
                },
            },
            {
                "id": "process_all_pipelines",
                "label": "Process all pipelines",
                "description": "Advance all customer pipelines",
                "status": "ready",
                "step_index": 1,
                "action": {
                    "id": "process_all_pipelines",
                    "label": "Process all pipelines",
                    "description": "Advance all customer pipelines",
                    "requires_confirmation": True,
                    "button_text": "Run action",
                },
                "condition": {
                    "type": "requires_previous_issues",
                    "label": "Only run if issues are found",
                    "source": "issues are found",
                },
            },
        ],
        "history": [
            {
                "step_id": "validate_all_customers",
                "status": "completed",
                "timestamp": "2026-03-23T00:00:00Z",
                "message": "Validation found 2 issues.",
            }
        ],
    }

    try:
        status, save_payload = _json_request(
            base + "/api/admin/assistant",
            method="POST",
            token=token,
            payload={"workflow_state": workflow_payload},
        )

        assert status == 200
        assert save_payload["success"] is True
        assert save_payload["intent"] == "workflow_state_saved"
        assert save_payload["workflow"]["workflow_id"] == workflow_payload["workflow_id"]
        assert save_payload["workflow"]["current_step_index"] == 1

        status, load_payload = _json_request(
            base + "/api/admin/assistant",
            method="POST",
            token=token,
            payload={},
        )

        assert status == 200
        assert load_payload["success"] is True
        assert load_payload["workflow"]["workflow_id"] == workflow_payload["workflow_id"]
        assert load_payload["workflow"]["steps"][0]["status"] == "completed"
        assert load_payload["workflow"]["steps"][1]["status"] == "ready"

        status, clear_payload = _json_request(
            base + "/api/admin/assistant",
            method="POST",
            token=token,
            payload={"clear_workflow": True},
        )

        assert status == 200
        assert clear_payload["success"] is True
        assert clear_payload["intent"] == "workflow_state_cleared"
        assert clear_payload["workflow"] is None
    finally:
        srv.stop()
