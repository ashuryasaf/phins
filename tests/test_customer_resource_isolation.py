import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal

BASE_URL = "http://127.0.0.1:8000"


def _get_json(url: str, token: str | None = None) -> tuple[int, str, dict]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=10) as resp:
            return (
                resp.status,
                resp.headers.get("Content-Type", ""),
                json.loads(resp.read().decode("utf-8")),
            )
    except HTTPError as exc:
        return (
            exc.code,
            exc.headers.get("Content-Type", ""),
            json.loads(exc.read().decode("utf-8")),
        )


def test_customer_without_customer_id_cannot_access_policy_or_claim():
    try:
        portal._ensure_test_port_state(8000)
        portal.POLICIES["POL-TEST-ISO"] = {
            "id": "POL-TEST-ISO",
            "customer_id": "CUST-TARGET-001",
            "type": "health",
        }
        portal.CLAIMS["CLM-TEST-ISO"] = {
            "id": "CLM-TEST-ISO",
            "customer_id": "CUST-TARGET-001",
            "policy_id": "POL-TEST-ISO",
            "status": "submitted",
        }
        portal.CUSTOMERS["CUST-TARGET-001"] = {
            "id": "CUST-TARGET-001",
            "name": "Target Customer",
            "email": "target@example.com",
        }
        portal.SESSIONS["phins_test_missing_customer_id"] = {
            "username": "missing-customer@example.com",
            "role": "customer",
            "customer_id": None,
            "expires": "2999-01-01T00:00:00",
        }

        token = "phins_test_missing_customer_id"
        policy_status, policy_content_type, policy_body = _get_json(
            f"{BASE_URL}/api/policy/POL-TEST-ISO",
            token=token,
        )
        claim_status, claim_content_type, claim_body = _get_json(
            f"{BASE_URL}/api/claim/CLM-TEST-ISO",
            token=token,
        )

        assert policy_status == 403
        assert policy_content_type.startswith("application/json")
        assert policy_body == {"error": "Customer session invalid"}

        assert claim_status == 403
        assert claim_content_type.startswith("application/json")
        assert claim_body == {"error": "Customer session invalid"}
    finally:
        portal.POLICIES.pop("POL-TEST-ISO", None)
        portal.CLAIMS.pop("CLM-TEST-ISO", None)
        portal.CUSTOMERS.pop("CUST-TARGET-001", None)
        portal.SESSIONS.pop("phins_test_missing_customer_id", None)
