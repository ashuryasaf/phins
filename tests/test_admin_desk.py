"""Admin Desk registry, diary, documents, and the refusal to send."""

import base64
import csv
import hashlib
import io
import json
import os
import zipfile
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import services.admin_desk_service as desk


@pytest.fixture(autouse=True)
def _fresh_desk(monkeypatch):
    monkeypatch.delenv("PHINS_ADMIN_DESK_MAIL_ASAF", raising=False)
    desk.reset_for_tests()
    yield
    desk.reset_for_tests()


def test_seed_mailbox_is_disabled_and_hides_the_secret():
    rows = desk.list_mailboxes("admin")
    admin = next(row for row in rows if row["id"] == "mbx-admin")
    assert admin["address"] == "asaf@phins.ai"
    assert admin["enabled"] is False
    assert admin["secret_configured"] is False
    assert admin["secret_ref"] == "PHINS_ADMIN_DESK_MAIL_ASAF"
    assert "password" not in json.dumps(admin).lower()
    stored = desk._read(desk._store(), "mbx-admin")
    assert desk.intact(stored)


def test_other_desks_are_slots_on_the_same_registry():
    rows = {row["desk"]: row for row in desk.list_mailboxes("admin")}
    assert set(rows) == {"admin", "actuary", "underwriting", "claims", "accountant", "compliance"}
    assert rows["actuary"]["address"] == ""
    assert rows["claims"]["signature_id"] == "sig-claims-v1"


def test_claims_session_cannot_see_the_admin_mailbox():
    visible = [row["id"] for row in desk.list_mailboxes("claims_adjuster")]
    assert visible == ["mbx-claims"]
    with pytest.raises(desk.DeskError) as raised:
        desk.get_mailbox("mbx-admin", "claims_adjuster")
    assert raised.value.status == 404


def test_enable_refuses_without_a_secret(monkeypatch):
    with pytest.raises(desk.DeskError) as raised:
        desk.set_mailbox_enabled("mbx-admin", True, "admin", "admin")
    assert raised.value.status == 409
    assert raised.value.message == "secret_not_configured"
    monkeypatch.setenv("PHINS_ADMIN_DESK_MAIL_ASAF", "desk-secret")
    enabled = desk.set_mailbox_enabled("mbx-admin", True, "admin", "admin")
    assert enabled["enabled"] is True
    assert enabled["secret_configured"] is True
    assert "desk-secret" not in json.dumps(enabled)


def test_actuary_cannot_enable_a_mailbox():
    with pytest.raises(desk.DeskError) as raised:
        desk.set_mailbox_enabled("mbx-actuary", True, "actuary", "actuary")
    assert raised.value.status == 403


def test_diary_import_is_idempotent_and_keeps_a_contradiction():
    first = desk.import_diary(
        [{"id": "diary-seed-01", "date": "2026-05-26", "time": "—", "counterparty": "Someone else",
          "location": "—", "purpose": "Different purpose", "status": "Held"}],
        "admin", "admin",
    )
    assert first["duplicate"] is False
    assert first["contradictions"] == 1
    assert first["added"] == 0
    again = desk.import_diary(
        [{"id": "diary-seed-01", "date": "2026-05-26", "time": "—", "counterparty": "Someone else",
          "location": "—", "purpose": "Different purpose", "status": "Held"}],
        "admin", "admin",
    )
    assert again["duplicate"] is True
    original = next(row for row in desk.list_diary("admin") if row["id"] == "diary-seed-01")
    assert original["counterparty"] == "Executive Actuary (IL · CA · US)"
    assert len(desk.list_contradictions("admin")) == 1


def test_letter_files_share_a_payload_and_keep_their_own_hashes():
    letter = desk.create_letter("Hello", "One line.\nTwo line.", "admin", "admin", "admin")
    assert letter["signature_id"] == "sig-admin-v1"
    html = desk.document_file(letter["id"], "html", "admin")
    pdf = desk.document_file(letter["id"], "pdf", "admin")
    docx = desk.document_file(letter["id"], "docx", "admin")
    html_bytes = base64.b64decode(html["data_b64"])
    assert b"PHINS" in html_bytes
    assert b"Ashury Asaf" in html_bytes
    assert hashlib.sha256(html_bytes).hexdigest() == html["sha256"]
    assert pdf["sha256"] != html["sha256"]
    package = zipfile.ZipFile(io.BytesIO(base64.b64decode(docx["data_b64"])))
    assert "Ashury Asaf" in package.read("word/document.xml").decode("utf-8")
    again = desk._letter_pdf("Hello", "One line.\nTwo line.", desk._footer_lines("admin", "asaf@phins.ai"))
    assert hashlib.sha256(again).hexdigest() == pdf["sha256"]


def test_table_csv_and_xlsx_carry_the_same_rows_and_require_a_source():
    with pytest.raises(desk.DeskError):
        desk.create_table("Queue", ["Item"], [["Diary"]], "", "admin", "admin", "admin")
    table = desk.create_table(
        "Queue", ["Item", "State"], [["Diary", "Ready"], ["Letter", "Ready"]],
        "Typed on the admin desk", "admin", "admin", "admin",
    )
    csv_file = desk.document_file(table["id"], "csv", "admin")
    xlsx_file = desk.document_file(table["id"], "xlsx", "admin")
    rows = list(csv.reader(io.StringIO(base64.b64decode(csv_file["data_b64"]).decode("utf-8"))))
    assert rows[0] == ["source", "Typed on the admin desk"]
    assert ["Diary", "Ready"] in rows
    from openpyxl import load_workbook
    book = load_workbook(io.BytesIO(base64.b64decode(xlsx_file["data_b64"])))
    sheet_rows = [list(row) for row in book.active.iter_rows(values_only=True)]
    assert sheet_rows[0] == ("source", "Typed on the admin desk") or sheet_rows[0] == ["source", "Typed on the admin desk"]
    assert ("Diary", "Ready") in [tuple(row) for row in sheet_rows]


def test_send_is_refused_and_a_second_click_does_not_change_the_draft(monkeypatch):
    draft = desk.create_draft("mbx-admin", "person@example.com", "Hello", "Body", [], "admin", "admin")
    assert draft["from"] == "asaf@phins.ai"
    assert "Ashury Asaf" in draft["preview"]
    assert draft["sent"] is False
    first = desk.send_draft(draft["id"], "admin", "admin")
    assert first["status"] == "failed"
    assert first["send_error"] == "mailbox_not_ready"
    assert first["sent"] is False
    second = desk.send_draft(draft["id"], "admin", "admin")
    assert second["checksum"] == first["checksum"]
    monkeypatch.setenv("PHINS_ADMIN_DESK_MAIL_ASAF", "desk-secret")
    desk.set_mailbox_enabled("mbx-admin", True, "admin", "admin")
    fresh = desk.create_draft("mbx-admin", "person@example.com", "Hello", "Body", [], "admin", "admin")
    refused = desk.send_draft(fresh["id"], "admin", "admin")
    assert refused["send_error"] == "send_not_connected"
    assert refused["sent"] is False


def test_bad_checksum_is_not_served():
    store = desk._store()
    record = dict(desk._read(store, "mbx-admin"))
    record["address"] = "tampered@example.com"
    store["mbx-admin"] = record
    assert desk._read(store, "mbx-admin") is None
    assert desk.list_mailboxes("admin") == [] or all(row["id"] != "mbx-admin" for row in desk.list_mailboxes("admin"))
    faults = desk.overview("admin")["faults"]
    assert any(fault["subject_id"] == "mbx-admin" for fault in faults)


def _http(method, path, token=None, payload=None):
    base = os.environ["TEST_BASE_URL"]
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(base + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _login(username, password):
    status, body = _http("POST", "/api/login", payload={"username": username, "password": password})
    assert status == 200, body
    return body["token"]


def test_http_desk_scopes_mailboxes_and_serves_the_page():
    desk.reset_for_tests()
    admin = _login("admin", "admin123")
    page_request = Request(os.environ["TEST_BASE_URL"] + "/admin-desk.html")
    with urlopen(page_request, timeout=30) as response:
        page = response.read().decode("utf-8")
        assert response.status == 200
    assert "PHINS Admin Desk" in page
    status, body = _http("GET", "/api/admin/ai-agents/desk", token=admin)
    assert status == 200
    assert any(row["address"] == "asaf@phins.ai" and row["enabled"] is False for row in body["mailboxes"])
    actuary = _login("actuary", "actuary123")
    status, body = _http("GET", "/api/admin/ai-agents/desk", token=actuary)
    assert status == 200
    assert [row["desk"] for row in body["mailboxes"]] == ["actuary"]
    status, body = _http("POST", "/api/admin/ai-agents/desk/drafts/missing/send", token=admin, payload={})
    assert status == 404
