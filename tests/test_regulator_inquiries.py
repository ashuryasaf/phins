"""Regulator inquiries stay off the public contact queue and the sealed outline."""

from __future__ import annotations

import os
import re

import pytest
import requests

from services.regulator_inquiries import (
    AUDIENCE,
    ORGANIZATION,
    SUBJECTS,
    InquiryError,
    apply_open_inquiry,
    business_relations_row,
    clean_message,
)

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
PROBE = "RINQPROBE7741 how are claims counts sealed for this subject"
CONTACT_NAME = "Dana Regulator"
CONTACT_EMAIL = "dana.regulator@example.com"


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
        f"  {CONTACT_NAME} ", CONTACT_EMAIL,
    )
    assert records == {}
    assert action == "created"
    assert created["id"] == inquiry_id
    assert created["opened_by"] == "regulator"
    assert created["full_name"] == CONTACT_NAME
    assert created["email"] == CONTACT_EMAIL
    assert created["organization"] == ORGANIZATION
    assert created["audience"] == AUDIENCE
    assert created["subject"] == "claims"
    assert created["channel"] == "regulator"
    assert created["messages"] == [{"at": stamp, "by": "regulator", "body": PROBE}]
    assert "customer_id" not in created

    filed = business_relations_row(created, "BRI-202609-ABCDEF12", stamp)
    assert filed["organization"] == ORGANIZATION
    assert filed["audience"] == AUDIENCE
    assert filed["interest"] == "regulator:claims"
    assert filed["name"] == CONTACT_NAME
    assert "customer_id" not in filed
    assert PROBE in filed["message"]

    stored = {created["id"]: created}
    before = [dict(turn) for turn in created["messages"]]
    action, again = apply_open_inquiry(
        stored, "regulator", "claims", PROBE, stamp, "RINQ-202609-ABCDEF99",
        "Other Name", "other@example.com",
    )
    assert action == "duplicate"
    assert again["messages"] == before
    assert again["email"] == CONTACT_EMAIL
    assert stored[inquiry_id]["messages"] == before

    action, appended = apply_open_inquiry(
        stored, "regulator", " claims ", "A second question on the same subject",
        "2026-09-26T21:05:00+00:00", "RINQ-202609-ABCDEF99",
        CONTACT_NAME, CONTACT_EMAIL,
    )
    assert action == "appended"
    assert appended["id"] == inquiry_id
    assert len(appended["messages"]) == 2
    assert len(stored[inquiry_id]["messages"]) == 1


def test_unknown_subject_and_empty_message_are_refused():
    with pytest.raises(InquiryError, match="outlined subject"):
        apply_open_inquiry(
            {}, "regulator", "actuarial_investments", "hello", "t",
            "RINQ-202609-ABCDEF12", CONTACT_NAME, CONTACT_EMAIL,
        )
    with pytest.raises(InquiryError, match="Full name"):
        apply_open_inquiry(
            {}, "regulator", "claims", "hello", "t", "RINQ-202609-ABCDEF12", " ", CONTACT_EMAIL,
        )
    with pytest.raises(InquiryError, match="email"):
        apply_open_inquiry(
            {}, "regulator", "claims", "hello", "t", "RINQ-202609-ABCDEF12", CONTACT_NAME, "not-an-email",
        )
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
    assert 'id="inquiry-name"' in page.text
    assert 'id="inquiry-email"' in page.text
    assert 'value="capital markets authority"' in page.text
    assert 'value="regulations contact"' in page.text
    solutions = requests.get(f"{BASE_URL}/solutions.html", timeout=30)
    assert solutions.status_code == 200
    assert "/api/business/inquiries" in solutions.text


def test_regulator_inquiry_is_separate_from_the_outline_and_public_queue():
    import web_portal.server as portal

    headers = _regulator_headers()
    created = requests.post(f"{BASE_URL}/api/regulator/inquiries", headers=headers, json={
        "subject": "claims",
        "message": PROBE,
        "name": CONTACT_NAME,
        "email": CONTACT_EMAIL,
        "organization": "Someone Else",
        "audience": "investor",
        "opened_by": "admin",
        "customer_id": "CUST-LEAK",
    }, timeout=30)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["action"] == "created"
    inquiry = body["inquiry"]
    assert inquiry["opened_by"] == "regulator"
    assert inquiry["full_name"] == CONTACT_NAME
    assert inquiry["email"] == CONTACT_EMAIL
    assert inquiry["organization"] == ORGANIZATION
    assert inquiry["audience"] == AUDIENCE
    assert inquiry["subject"] == "claims"
    assert inquiry["id"].startswith("RINQ-")
    assert body["business_inquiry"]["id"].startswith("BRI-")
    assert body["business_inquiry"]["organization"] == ORGANIZATION
    assert body["business_inquiry"]["audience"] == AUDIENCE
    assert "CUST-LEAK" not in created.text
    assert "Someone Else" not in created.text
    assert "recipients" not in body["notification"]
    assert body["notification"]["acknowledgement"]["recipient"] == CONTACT_EMAIL
    filed = portal.BUSINESS_INQUIRIES[body["business_inquiry"]["id"]]
    assert filed["interest"] == "regulator:claims"
    assert filed["email"] == CONTACT_EMAIL
    assert "customer_id" not in filed

    business_id = body["business_inquiry"]["id"]
    appended = requests.post(f"{BASE_URL}/api/regulator/inquiries", headers=headers, json={
        "subject": "claims",
        "message": "Follow-up on the same outlined subject",
        "name": CONTACT_NAME,
        "email": CONTACT_EMAIL,
    }, timeout=30)
    assert appended.status_code == 200, appended.text
    assert appended.json()["action"] == "appended"
    assert len(appended.json()["inquiry"]["messages"]) == 2
    assert appended.json()["business_inquiry"]["id"] == business_id
    assert portal.BUSINESS_INQUIRIES[business_id]["message"].count("Follow-up") == 1

    duplicate = requests.post(f"{BASE_URL}/api/regulator/inquiries", headers=headers, json={
        "subject": "claims",
        "message": "Follow-up on the same outlined subject",
        "name": CONTACT_NAME,
        "email": CONTACT_EMAIL,
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
    assert CONTACT_EMAIL not in outline.text
    assert "FOREIGN-INQUIRY-8844" not in outline.text
    assert len(portal.BUSINESS_INQUIRIES) == 1

    public = requests.post(f"{BASE_URL}/api/business/inquiries", headers=headers, json={
        "inquiry_type": "contact",
        "name": "Regulator",
        "email": "regulator@example.com",
        "message": PROBE,
        "interest": "claims",
    }, timeout=30)
    assert public.status_code == 403, public.text
    assert len(portal.BUSINESS_INQUIRIES) == 1


def test_inquiry_validation_and_role_gate():
    headers = _regulator_headers()
    unknown = requests.post(f"{BASE_URL}/api/regulator/inquiries", headers=headers, json={
        "subject": "billing",
        "message": "This is a public solution interest",
        "name": CONTACT_NAME,
        "email": CONTACT_EMAIL,
    }, timeout=30)
    assert unknown.status_code == 400, unknown.text
    empty = requests.post(f"{BASE_URL}/api/regulator/inquiries", headers=headers, json={
        "subject": "pricing",
        "message": "   ",
        "name": CONTACT_NAME,
        "email": CONTACT_EMAIL,
    }, timeout=30)
    missing_email = requests.post(f"{BASE_URL}/api/regulator/inquiries", headers=headers, json={
        "subject": "pricing",
        "message": "A real question",
        "name": CONTACT_NAME,
        "email": "not-an-email",
    }, timeout=30)
    assert missing_email.status_code == 400, missing_email.text
    forged = requests.post(f"{BASE_URL}/api/business/inquiries", json={
        "inquiry_type": "contact",
        "name": CONTACT_NAME,
        "email": CONTACT_EMAIL,
        "organization": ORGANIZATION,
        "audience": AUDIENCE,
        "interest": "platform",
        "message": "A visitor cannot file this audience",
    }, timeout=30)
    assert forged.status_code == 400, forged.text
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
            "name": CONTACT_NAME,
            "email": CONTACT_EMAIL,
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
        {
            "subject": "integrity",
            "message": "This write must not land",
            "name": CONTACT_NAME,
            "email": CONTACT_EMAIL,
        },
        "127.0.0.1",
    )
    assert status == 503
    assert payload["error"] == "Inquiry could not be recorded"
    assert portal.REGULATOR_INQUIRIES == {}
    assert portal.BUSINESS_INQUIRIES == {}


def test_ordinary_punctuation_in_a_message_is_not_read_as_an_attack():
    import web_portal.server as portal

    prose = (
        "Two questions; first, how is the claims count sealed | second, "
        "which subject covers reserve movements -- and where is it shown?"
    )
    status, payload = portal.open_regulator_inquiry(
        {"username": "regulator", "role": "regulator"},
        {"subject": "claims", "message": prose},
        "203.0.113.9",
    )
    assert status == 201, payload
    assert payload["inquiry"]["messages"][0]["body"] == prose
    assert not portal.is_ip_blocked("203.0.113.9")[0]


def test_a_credential_rename_keeps_the_open_inquiry_on_the_same_account():
    import web_portal.server as portal

    old_name = "regulator.inquiry-probe"
    new_name = "regulator.inquiry-probe2"
    record = {
        **portal.hash_password("inquiry-pass-1"),
        "role": "regulator",
        "name": "Inquiry Probe",
    }
    portal.USERS[old_name] = record
    portal._FALLBACK_USERS[old_name] = record
    try:
        status, opened = portal.open_regulator_inquiry(
            {"username": old_name, "role": "regulator"},
            {"subject": "pricing", "message": "Question asked before the rename"},
            "127.0.0.1",
        )
        assert status == 201, opened
        inquiry_id = opened["inquiry"]["id"]

        status, rotated = portal.update_regulator_credentials(
            {"username": old_name, "role": "regulator"},
            {
                "current_password": "inquiry-pass-1",
                "new_password": "inquiry-pass-2",
                "new_username": new_name,
            },
        )
        assert status == 200, rotated

        renamed = {"username": new_name, "role": "regulator"}
        listed_status, listed = portal.list_regulator_inquiries(renamed)
        assert listed_status == 200
        assert [item["id"] for item in listed["items"]] == [inquiry_id]

        status, again = portal.open_regulator_inquiry(
            renamed,
            {"subject": "pricing", "message": "Question asked after the rename"},
            "127.0.0.1",
        )
        assert status == 200, again
        assert again["action"] == "appended"
        assert again["inquiry"]["id"] == inquiry_id
    finally:
        for name in (old_name, new_name):
            portal._FALLBACK_USERS.pop(name, None)
            try:
                del portal.USERS[name]
            except Exception:
                pass
            portal._REGULATOR_LEGACY_RETIRED.discard(name)


def test_database_mode_uses_agent_artifacts_and_reloads_them(monkeypatch):
    import database.manager as manager
    import web_portal.server as portal

    stored = {}
    business_stored = {}

    class FakeBusiness:
        def upsert_from_dict(self, inquiry_id, data):
            business_stored[inquiry_id] = dict(data)
            return True

        def load_all_as_dicts(self):
            return {key: dict(value) for key, value in business_stored.items()}

        def delete(self, inquiry_id):
            business_stored.pop(inquiry_id, None)
            return True

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
            self.business_inquiries = FakeBusiness()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def close(self):
            return None

    monkeypatch.setattr(manager, "DatabaseManager", lambda: FakeDB())
    monkeypatch.setattr(portal, "USE_DATABASE", True)
    monkeypatch.setattr(portal, "database_enabled", True)
    portal.REGULATOR_INQUIRIES.clear()
    portal.BUSINESS_INQUIRIES.clear()
    portal._REGULATOR_INQUIRY_LAST_HYDRATE = 0.0

    status, payload = portal.open_regulator_inquiry(
        {"username": "regulator", "role": "regulator"},
        {
            "subject": "health",
            "message": "Question on the health section",
            "name": CONTACT_NAME,
            "email": CONTACT_EMAIL,
            "organization": "Other Org",
            "customer_id": "CUST-NO",
        },
        "127.0.0.1",
    )
    assert status == 201, payload
    inquiry_id = payload["inquiry"]["id"]
    assert inquiry_id in stored
    assert "customer_id" not in stored[inquiry_id]
    assert stored[inquiry_id]["organization"] == ORGANIZATION
    assert stored[inquiry_id]["messages"][0]["body"] == "Question on the health section"
    business_id = payload["business_inquiry"]["id"]
    assert business_stored[business_id]["organization"] == ORGANIZATION
    assert business_stored[business_id]["audience"] == AUDIENCE
    assert business_stored[business_id]["email"] == CONTACT_EMAIL
    assert "customer_id" not in business_stored[business_id]
    assert "Other Org" not in str(business_stored[business_id])

    portal.REGULATOR_INQUIRIES.clear()
    portal._REGULATOR_INQUIRY_LAST_HYDRATE = 0.0
    listed_status, listed = portal.list_regulator_inquiries(
        {"username": "regulator", "role": "regulator"},
    )
    assert listed_status == 200
    assert [item["id"] for item in listed["items"]] == [inquiry_id]
    assert portal.BUSINESS_INQUIRIES[business_id]["audience"] == AUDIENCE

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
