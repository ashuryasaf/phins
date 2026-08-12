"""
Tests for the Business Relations inquiry pipeline.

Covers:
  * public intake: POST /api/business/inquiries (contact + demo requests from
    the public solutions/intro page) — validation, sanitization, idempotency
  * admin review: GET /api/admin/business-inquiries (role-gated list w/ filters)
  * admin triage: POST /api/admin/business-inquiries/<id>/status (status
    history integrity)
"""

import json
import os

from urllib.request import urlopen, Request
from urllib.error import HTTPError

import web_portal.server as portal


BASE = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _post(path, payload, token=None):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(BASE + path, data=data, headers=headers)
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except HTTPError as e:
        return json.loads(e.read().decode("utf-8")), e.code


def _get(path, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(BASE + path, headers=headers)
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except HTTPError as e:
        return json.loads(e.read().decode("utf-8")), e.code


def _login(username, password):
    body, status = _post("/api/login", {"username": username, "password": password})
    assert status == 200, f"login failed for {username}: {body}"
    return body["token"], body.get("role")


def _valid_payload(**overrides):
    payload = {
        "inquiry_type": "demo",
        "name": "Dana Levi",
        "email": "dana.levi@example.com",
        "organization": "Example Health Group",
        "audience": "enterprise",
        "interest": "underwriting",
        "message": "We would like a walkthrough of the underwriting workbench.",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# public intake
# ---------------------------------------------------------------------------
def test_public_inquiry_submission_success():
    body, status = _post("/api/business/inquiries", _valid_payload())
    assert status == 200, body
    assert body["success"] is True
    inquiry = body["inquiry"]
    assert inquiry["id"].startswith("BRI-")
    assert inquiry["status"] == "new"
    assert inquiry["created_at"]
    # The public response must stay minimal: no echo of message/email.
    assert "email" not in inquiry
    assert "message" not in inquiry

    # Stored record holds the full validated submission with a history trail.
    record = portal.BUSINESS_INQUIRIES[inquiry["id"]]
    assert record["email"] == "dana.levi@example.com"
    assert record["audience"] == "enterprise"
    assert record["interest"] == "underwriting"
    assert record["status_history"][0]["status"] == "new"
    assert record["status_history"][0]["changed_by"] == "public_form"


def test_public_inquiry_requires_name_and_valid_email():
    body, status = _post("/api/business/inquiries", _valid_payload(name=""))
    assert status == 400 and "error" in body

    body, status = _post("/api/business/inquiries", _valid_payload(email="not-an-email"))
    assert status == 400 and "error" in body


def test_public_inquiry_rejects_unknown_enums():
    body, status = _post("/api/business/inquiries", _valid_payload(inquiry_type="spam"))
    assert status == 400 and "inquiry_type" in body["error"]

    body, status = _post("/api/business/inquiries", _valid_payload(audience="alien"))
    assert status == 400 and "audience" in body["error"]

    body, status = _post("/api/business/inquiries", _valid_payload(interest="secrets"))
    assert status == 400 and "interest" in body["error"]


def test_public_inquiry_sanitizes_html_input():
    body, status = _post(
        "/api/business/inquiries",
        _valid_payload(name="Dana <script>alert(1)</script>", message="hello <b>world</b>"),
    )
    assert status == 200, body
    record = portal.BUSINESS_INQUIRIES[body["inquiry"]["id"]]
    assert "<" not in record["name"] and ">" not in record["name"]
    assert "<" not in record["message"] and ">" not in record["message"]


def test_public_inquiry_duplicate_open_request_is_idempotent():
    first, status = _post("/api/business/inquiries", _valid_payload())
    assert status == 200

    second, status = _post("/api/business/inquiries", _valid_payload(message="Second ping"))
    assert status == 200
    assert second.get("duplicate") is True
    assert second["inquiry"]["id"] == first["inquiry"]["id"]
    assert len(portal.BUSINESS_INQUIRIES) == 1

    # A different interest area is a genuinely new inquiry.
    third, status = _post("/api/business/inquiries", _valid_payload(interest="claims"))
    assert status == 200
    assert third.get("duplicate") is None
    assert third["inquiry"]["id"] != first["inquiry"]["id"]
    assert len(portal.BUSINESS_INQUIRIES) == 2


# ---------------------------------------------------------------------------
# admin review + triage
# ---------------------------------------------------------------------------
def test_admin_list_requires_admin_role():
    _, status = _get("/api/admin/business-inquiries")
    assert status == 403

    underwriter_token, _ = _login("underwriter", "under123")
    _, status = _get("/api/admin/business-inquiries", token=underwriter_token)
    assert status == 403


def test_admin_list_returns_inquiries_with_filters():
    _post("/api/business/inquiries", _valid_payload())
    _post(
        "/api/business/inquiries",
        _valid_payload(
            inquiry_type="contact",
            email="joe@example.org",
            name="Joe Broker",
            audience="partner",
            interest="mga_solutions",
        ),
    )

    admin_token, _ = _login("admin", "admin123")
    body, status = _get("/api/admin/business-inquiries", token=admin_token)
    assert status == 200
    assert body["total"] == 2
    assert body["new_count"] == 2
    assert {i["interest"] for i in body["items"]} == {"underwriting", "mga_solutions"}

    body, status = _get(
        "/api/admin/business-inquiries?audience=partner&inquiry_type=contact",
        token=admin_token,
    )
    assert status == 200
    assert body["total"] == 1
    assert body["items"][0]["email"] == "joe@example.org"

    body, status = _get("/api/admin/business-inquiries?search=dana", token=admin_token)
    assert status == 200
    assert body["total"] == 1
    assert body["items"][0]["name"] == "Dana Levi"


def test_admin_status_update_flow_keeps_history():
    created, _ = _post("/api/business/inquiries", _valid_payload())
    inquiry_id = created["inquiry"]["id"]

    admin_token, _ = _login("admin", "admin123")

    # invalid status rejected
    body, status = _post(
        f"/api/admin/business-inquiries/{inquiry_id}/status",
        {"status": "vanished"},
        token=admin_token,
    )
    assert status == 400 and "status" in body["error"]

    # unknown inquiry -> 404
    _, status = _post(
        "/api/admin/business-inquiries/BRI-000000-DEADBEEF/status",
        {"status": "contacted"},
        token=admin_token,
    )
    assert status == 404

    # non-admin cannot triage
    _, status = _post(
        f"/api/admin/business-inquiries/{inquiry_id}/status",
        {"status": "contacted"},
    )
    assert status == 403

    body, status = _post(
        f"/api/admin/business-inquiries/{inquiry_id}/status",
        {"status": "contacted", "note": "Intro call scheduled"},
        token=admin_token,
    )
    assert status == 200
    assert body["inquiry"]["status"] == "contacted"
    history = body["inquiry"]["status_history"]
    assert [h["status"] for h in history] == ["new", "contacted"]
    assert history[-1]["changed_by"] == "admin"
    assert history[-1]["note"] == "Intro call scheduled"

    # once contacted, a new submission with the same email/interest is a new record
    again, status = _post("/api/business/inquiries", _valid_payload())
    assert status == 200
    assert again.get("duplicate") is None
    assert again["inquiry"]["id"] != inquiry_id
