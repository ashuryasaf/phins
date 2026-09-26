"""Regulator inquiries stay off the public contact queue and the sealed outline."""

from __future__ import annotations

import os
import re

import pytest
import requests

from services.regulator_inquiries import (
    SUBJECTS,
    InquiryError,
    apply_open_inquiry,
    clean_message,
)

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
PROBE = "RINQPROBE7741 how are claims counts sealed for this subject"


def _login(username, password):
    return requests.post(f"{BASE_URL}/api/login", json={
        "username": username,
        "password": password,
    }, timeout=30)


def _regulator_headers():
    login = _login("regulator", "regulator123")
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_open_inquiry_appends_and_ignores_a_duplicate_without_touching_the_input():
    stamp = "2026-09-26T21:00:00+00:00"
    inquiry_id = "RINQ-202609-ABCDEF12"
    records = {}
    action, created = apply_open_inquiry(
        records, "regulator", "claims", f"  {PROBE}\n", stamp, inquiry_id,
    )
    assert records == {}
    assert action == "created"
    assert created["id"] == inquiry_id
    assert created["opened_by"] == "regulator"
    assert created["subject"] == "claims"
    assert created["channel"] == "regulator"
    assert created["messages"] == [{"at": stamp, "by": "regulator", "body": PROBE}]
    assert "customer_id" not in created

    stored = {created["id"]: created}
    before = [dict(turn) for turn in created["messages"]]
    action, again = apply_open_inquiry(
        stored, "regulator", "claims", PROBE, stamp, "RINQ-202609-ABCDEF99",
    )
    assert action == "duplicate"
    assert again["messages"] == before
    assert stored[inquiry_id]["messages"] == before

    action, appended = apply_open_inquiry(
        stored, "regulator", " claims ", "A second question on the same subject",
        "2026-09-26T21:05:00+00:00", "RINQ-202609-ABCDEF99",
    )
    assert action == "appended"
    assert appended["id"] == inquiry_id
    assert len(appended["messages"]) == 2
    assert len(stored[inquiry_id]["messages"]) == 1


def test_unknown_subject_and_empty_message_are_refused():
    with pytest.raises(InquiryError, match="outlined subject"):
        apply_open_inquiry({}, "regulator", "actuarial_investments", "hello", "t", "RINQ-202609-ABCDEF12")
    with pytest.raises(InquiryError, match="Message is required"):
        clean_message("   \x00  ")
    with pytest.raises(InquiryError, match="2000"):
        clean_message("x" * 2001)


def test_dashboard_subjects_match_the_inquiry_catalog():
    page = requests.get(f"{BASE_URL}/regulator-dashboard.html", timeout=30)
    assert page.status_code == 200
    found = re.findall(r"\{ id: '([^']+)', label: '([^']+)' \}", page.text)
    assert found == list(SUBJECTS)
    assert 'id="inquiry"' in page.text
    assert "/api/regulator/inquiries" in page.text
    assert 'href="/solutions.html#contact"' in page.text
    solutions = requests.get(f"{BASE_URL}/solutions.html", timeout=30)
    assert solutions.status_code == 200
    assert "/api/business/inquiries" in solutions.text


def test_regulator_inquiry_is_separate_from_the_outline_and_public_queue():
    import web_portal.server as portal

    headers = _regulator_headers()
    created = requests.post(f"{BASE_URL}/api/regulator/inquiries", headers=headers, json={
        "subject": "claims",
        "message": PROBE,
        "opened_by": "admin",
        "email": "visitor@example.com",
        "customer_id": "CUST-LEAK",
        "name": "Visitor",
    }, timeout=30)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["action"] == "created"
    inquiry = body["inquiry"]
    assert inquiry["opened_by"] == "regulator"
    assert inquiry["subject"] == "claims"
    assert inquiry["id"].startswith("RINQ-")
    assert "CUST-LEAK" not in created.text
    assert "visitor@example.com" not in created.text
    assert body["notification"] is None or "recipients" not in body["notification"]

    appended = requests.post(f"{BASE_URL}/api/regulator/inquiries", headers=headers, json={
        "subject": "claims",
        "message": "Follow-up on the same outlined subject",
    }, timeout=30)
    assert appended.status_code == 200, appended.text
    assert appended.json()["action"] == "appended"
    assert len(appended.json()["inquiry"]["messages"]) == 2

    duplicate = requests.post(f"{BASE_URL}/api/regulator/inquiries", headers=headers, json={
        "subject": "claims",
        "message": "Follow-up on the same outlined subject",
    }, timeout=30)
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["action"] == "duplicate"
    assert len(duplicate.json()["inquiry"]["messages"]) == 2

    listed = requests.get(f"{BASE_URL}/api/regulator/inquiries", headers=headers, timeout=30)
    assert listed.status_code == 200, listed.text
    catalog = [(item["id"], item["label"]) for item in listed.json()["subjects"]]
    assert catalog == list(SUBJECTS)
    assert listed.json()["channel"] == "regulator"
    assert listed.json()["public_conversation"].endswith("/solutions.html#contact")
    assert len(listed.json()["items"]) == 1
    assert PROBE in listed.text

    portal.REGULATOR_INQUIRIES["RINQ-202609-FFFF9999"] = {
        "id": "RINQ-202609-FFFF9999",
        "subject": "health",
        "subject_label": "Health",
        "status": "open",
        "opened_by": "someone-else",
        "channel": "regulator",
        "created_at": "t",
        "updated_at": "t",
        "messages": [{"at": "t", "by": "someone-else", "body": "FOREIGN-INQUIRY-8844"}],
        "customer_id": "CUST-FOREIGN",
    }
    scoped = requests.get(f"{BASE_URL}/api/regulator/inquiries", headers=headers, timeout=30)
    assert "FOREIGN-INQUIRY-8844" not in scoped.text
    assert "CUST-FOREIGN" not in scoped.text

    outline = requests.get(f"{BASE_URL}/api/regulator/outline", headers=headers, timeout=60)
    assert outline.status_code == 200, outline.text
    assert PROBE not in outline.text
    assert "FOREIGN-INQUIRY-8844" not in outline.text
    assert portal.BUSINESS_INQUIRIES == {}

    public = requests.post(f"{BASE_URL}/api/business/inquiries", headers=headers, json={
        "inquiry_type": "contact",
        "name": "Regulator",
        "email": "regulator@example.com",
        "message": PROBE,
        "interest": "claims",
    }, timeout=30)
    assert public.status_code == 403, public.text
    assert portal.BUSINESS_INQUIRIES == {}


def test_inquiry_validation_and_role_gate():
    headers = _regulator_headers()
    unknown = requests.post(f"{BASE_URL}/api/regulator/inquiries", headers=headers, json={
        "subject": "billing",
        "message": "This is a public solution interest",
    }, timeout=30)
    assert unknown.status_code == 400, unknown.text
    empty = requests.post(f"{BASE_URL}/api/regulator/inquiries", headers=headers, json={
        "subject": "pricing",
        "message": "   ",
    }, timeout=30)
    assert empty.status_code == 400, empty.text

    assert requests.get(f"{BASE_URL}/api/regulator/inquiries", timeout=30).status_code == 401
    assert requests.post(f"{BASE_URL}/api/regulator/inquiries", json={
        "subject": "pricing",
        "message": "hello",
    }, timeout=30).status_code == 401

    for username, password in (("admin", "admin123"), ("actuary", "actuary123")):
        login = _login(username, password)
        assert login.status_code == 200, login.text
        staff = {"Authorization": f"Bearer {login.json()['token']}"}
        listed = requests.get(f"{BASE_URL}/api/regulator/inquiries", headers=staff, timeout=30)
        posted = requests.post(f"{BASE_URL}/api/regulator/inquiries", headers=staff, json={
            "subject": "pricing",
            "message": "staff should not open this",
        }, timeout=30)
        assert listed.status_code == 403, listed.text
        assert posted.status_code == 403, posted.text


def test_a_failed_durable_write_does_not_publish_the_inquiry(monkeypatch):
    import web_portal.server as portal

    portal.REGULATOR_INQUIRIES.clear()

    def refuse(inquiry_id, data):
        return False

    monkeypatch.setattr(portal, "_persist_regulator_inquiry", refuse)
    status, payload = portal.open_regulator_inquiry(
        {"username": "regulator", "role": "regulator"},
        {"subject": "integrity", "message": "This write must not land"},
        "127.0.0.1",
    )
    assert status == 503
    assert payload["error"] == "Inquiry could not be recorded"
    assert portal.REGULATOR_INQUIRIES == {}
    assert portal.BUSINESS_INQUIRIES == {}


def test_database_mode_uses_agent_artifacts_and_reloads_them(monkeypatch):
    import database.manager as manager
    import web_portal.server as portal

    stored = {}

    class FakeArtifacts:
        def upsert(self, artifact_id, **kwargs):
            assert kwargs["agent_id"] == "regulator_inquiry"
            assert kwargs["kind"] == "inquiry"
            assert kwargs["subject_type"] == "regulator_subject"
            stored[artifact_id] = dict(kwargs["payload"])
            return True

        def iter_payloads(self, agent_id, kind):
            assert agent_id == "regulator_inquiry"
            assert kind == "inquiry"
            for artifact_id, payload in list(stored.items()):
                yield artifact_id, dict(payload), None, {}

    class FakeDB:
        def __init__(self):
            self.agent_artifacts = FakeArtifacts()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(manager, "DatabaseManager", lambda: FakeDB())
    monkeypatch.setattr(portal, "USE_DATABASE", True)
    monkeypatch.setattr(portal, "database_enabled", True)
    portal.REGULATOR_INQUIRIES.clear()
    portal.BUSINESS_INQUIRIES.clear()
    portal._REGULATOR_INQUIRY_LAST_HYDRATE = 0.0

    status, payload = portal.open_regulator_inquiry(
        {"username": "regulator", "role": "regulator"},
        {"subject": "health", "message": "Question on the health section", "customer_id": "CUST-NO"},
        "127.0.0.1",
    )
    assert status == 201, payload
    inquiry_id = payload["inquiry"]["id"]
    assert inquiry_id in stored
    assert "customer_id" not in stored[inquiry_id]
    assert stored[inquiry_id]["messages"][0]["body"] == "Question on the health section"

    portal.REGULATOR_INQUIRIES.clear()
    portal._REGULATOR_INQUIRY_LAST_HYDRATE = 0.0
    listed_status, listed = portal.list_regulator_inquiries(
        {"username": "regulator", "role": "regulator"},
    )
    assert listed_status == 200
    assert [item["id"] for item in listed["items"]] == [inquiry_id]
    assert portal.BUSINESS_INQUIRIES == {}

    stored[inquiry_id]["customer_id"] = "CUST-NO"
    stored[inquiry_id]["messages"].append({
        "at": "t", "by": "regulator", "body": "from the durable row",
    })
    portal.REGULATOR_INQUIRIES.clear()
    portal._REGULATOR_INQUIRY_LAST_HYDRATE = 0.0
    listed_status, listed = portal.list_regulator_inquiries(
        {"username": "regulator", "role": "regulator"},
    )
    assert listed["items"][0]["messages"][-1]["body"] == "from the durable row"
    assert "CUST-NO" not in str(listed)
