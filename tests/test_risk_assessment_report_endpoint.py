import json
import threading
import time
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal


class ServerThread(threading.Thread):
    def __init__(self, port: int):
        super().__init__(daemon=True)
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


def _post(url: str, payload: dict, token: str | None = None):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, headers=headers)
    with urlopen(req) as resp:
        return resp.read().decode("utf-8"), resp.status


def _get(url: str, token: str | None = None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return resp.read().decode("utf-8"), resp.status


def _login_admin_token(base_url: str) -> str:
    body, status = _post(base_url + "/api/login", {"username": "admin", "password": "admin123"})
    assert status == 200
    payload = json.loads(body)
    token = payload.get("token")
    assert token
    return token


def test_risk_assessment_report_handles_mixed_type_application_payload():
    port = 8136
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"
    token = _login_admin_token(base)

    customer_id = "CUST-RISK-MIXED-001"
    policy_id = "POL-RISK-MIXED-001"
    application_id = "UW-RISK-MIXED-001"

    portal.CUSTOMERS[customer_id] = {
        "id": customer_id,
        "name": "Risk Mixed Customer",
        "email": "risk-mixed@example.com",
    }
    portal.POLICIES[policy_id] = {
        "id": policy_id,
        "customer_id": customer_id,
        "type": "health",
        "coverage_amount": 350000,
    }
    portal.UNDERWRITING_APPLICATIONS[application_id] = {
        "id": application_id,
        "customer_id": customer_id,
        "policy_id": policy_id,
        "identity_verified": "true",
        "questionnaire_responses": {
            "age": "42 years",
            "disability_percentage": "25%",
            "smoke": True,
            "height": "172",
            "weight": "95",
        },
        "medical_conditions": [
            {
                "condition": "Hypertension",
                "severity": "moderate",
                "risk_impact": "0.35",
                "loading_percentage": "18",
                "exclusion_recommended": "false",
            }
        ],
        "created_date": "2026-02-20T12:00:00",
    }

    try:
        body, status = _get(base + f"/api/risk-assessment/report?application_id={application_id}", token)
        assert status == 200
        report = json.loads(body)

        assert report.get("application_id") == application_id
        assert report.get("risk_scores", {}).get("overall") is not None
        assert 0 <= float(report["risk_scores"]["overall"]) <= 1
        assert report.get("metadata", {}).get("requested_application_id") == application_id
        assert report.get("metadata", {}).get("resolved_application_id") == application_id
    finally:
        srv.stop()


def test_risk_assessment_report_resolves_legacy_rotating_application_ids():
    port = 8137
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.2)

    base = f"http://127.0.0.1:{port}"
    token = _login_admin_token(base)

    customer_id = "CUST-ASAF-LEGACY-001"
    policy_id = "POL-ASAF-LEGACY-001"
    resolved_application_id = "UW-ASAF-20260222-001"
    requested_legacy_id = "UW-ASAF-20260130-001"

    portal.UNDERWRITING_APPLICATIONS.pop(requested_legacy_id, None)
    portal.CUSTOMERS[customer_id] = {
        "id": customer_id,
        "name": "Asaf Legacy Customer",
        "email": "asaf-legacy@example.com",
    }
    portal.POLICIES[policy_id] = {
        "id": policy_id,
        "customer_id": customer_id,
        "type": "life",
        "coverage_amount": 500000,
    }
    portal.UNDERWRITING_APPLICATIONS[resolved_application_id] = {
        "id": resolved_application_id,
        "customer_id": customer_id,
        "policy_id": policy_id,
        "identity_verified": True,
        "medical_conditions": [],
        "created_date": "2026-02-22T10:00:00",
    }

    try:
        body, status = _get(base + f"/api/risk-assessment/report?application_id={requested_legacy_id}", token)
        assert status == 200
        report = json.loads(body)

        assert report.get("application_id") == resolved_application_id
        assert report.get("metadata", {}).get("requested_application_id") == requested_legacy_id
        assert report.get("metadata", {}).get("resolved_application_id") == resolved_application_id
    except HTTPError as e:
        payload = json.loads(e.read().decode("utf-8"))
        raise AssertionError(f"Expected legacy ID fallback to resolve, got HTTP {e.code}: {payload}") from e
    finally:
        srv.stop()
