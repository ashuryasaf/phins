"""Admin meeting summary notes — service + staff-gated API + dashboard UI.

Admins draft summary notes from meetings (pinned to the pitch-dashboard
Meeting Diary) so they can be referred to in the future for BI, adjustments
for further regulatory requirements, and AI-affiliated use.

Covers:
- ``services.meeting_notes_service`` — validation, draft/final revisions,
  tag normalization, filtering (the BI/AI read surface), archiving.
- ``/api/meetings/notes`` HTTP routes on the embedded test server — staff
  gating (401 for anonymous / non-staff), full CRUD cycle as admin.
- The pitch dashboard ships the staff-revealed notes admin block.
"""

import os
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
REPO = Path(__file__).resolve().parents[1]
PITCH = REPO / "web_portal" / "static" / "pitch-dashboard.html"


@pytest.fixture
def notes_store(tmp_path):
    """Fresh file-backed store on a temp path; also swaps the singleton the
    embedded HTTP server uses (same process), so HTTP tests stay isolated."""
    from services import meeting_notes_service as mns

    mns.reset_meeting_notes_service_for_tests()
    service = mns.get_meeting_notes_service(
        data_path=str(tmp_path / "meeting_notes.json")
    )
    yield service
    mns.reset_meeting_notes_service_for_tests()


def _admin_token():
    resp = requests.post(
        f"{BASE_URL}/api/login",
        json={"username": "admin", "password": "admin123"},
        timeout=10,
    )
    assert resp.status_code == 200, resp.text
    token = resp.json().get("token")
    assert token
    return token


# ---------------------------------------------------------------------------
# Service behaviour
# ---------------------------------------------------------------------------

def test_create_draft_note_defaults(notes_store):
    note = notes_store.create_note(
        title="Authority pre-ruling — outcomes",
        summary="Pre-ruling path agreed in principle; submission list to follow.",
        meeting_ref="regulatory-preruling-avi-ovadia",
        meeting_date="TBA",
        counterparty="Mr. Avi Ovadia — Capital Market, Insurance & Savings Authority",
        regulatory_adjustments="Adjust reserving disclosure cadence per Authority guidance.",
        tags=["BI", "Regulatory", "AI"],
    )
    assert note["id"].startswith("note_")
    assert note["status"] == "draft"
    assert note["revision"] == 1
    assert note["archived"] is False
    # tags normalized to lowercase for stable BI/AI querying
    assert note["tags"] == ["bi", "regulatory", "ai"]
    assert note["created_at"]
    assert note["updated_at"] is None


def test_note_validation_rules(notes_store):
    from services.meeting_notes_service import MeetingNoteError

    with pytest.raises(MeetingNoteError):
        notes_store.create_note(title="", summary="body")
    with pytest.raises(MeetingNoteError):
        notes_store.create_note(title="t", summary="")
    with pytest.raises(MeetingNoteError):
        notes_store.create_note(title="t", summary="s", status="published")
    with pytest.raises(MeetingNoteError):
        notes_store.create_note(title="t" * 200, summary="s")


def test_tag_normalization_dedupes_and_sanitizes(notes_store):
    note = notes_store.create_note(
        title="t",
        summary="s",
        tags=["AI", "ai", "  Regulatory Path ", "", "b!i"],
    )
    assert note["tags"] == ["ai", "regulatory-path", "b-i"]


def test_update_bumps_revision_and_finalizes(notes_store):
    from services.meeting_notes_service import MeetingNoteError

    note = notes_store.create_note(title="t", summary="first draft")
    updated = notes_store.update_note(
        note["id"],
        {"summary": "expanded summary", "status": "final"},
        updated_by="admin",
    )
    assert updated["revision"] == 2
    assert updated["status"] == "final"
    assert updated["summary"] == "expanded summary"
    assert updated["updated_at"]
    # empty update payloads are rejected
    with pytest.raises(MeetingNoteError):
        notes_store.update_note(note["id"], {})
    with pytest.raises(MeetingNoteError):
        notes_store.update_note("note_missing", {"summary": "x"})


def test_list_filters_are_the_bi_read_surface(notes_store):
    a = notes_store.create_note(
        title="Reg note", summary="s", tags=["regulatory"], meeting_ref="preruling"
    )
    notes_store.create_note(title="BI note", summary="s", tags=["bi"])
    notes_store.create_note(title="Plain", summary="s")

    assert len(notes_store.list_notes()) == 3
    reg = notes_store.list_notes(tag="regulatory")
    assert [n["title"] for n in reg] == ["Reg note"]
    ref = notes_store.list_notes(meeting_ref="PRERULING")
    assert [n["title"] for n in ref] == ["Reg note"]

    notes_store.update_note(a["id"], {"status": "final"})
    finals = notes_store.list_notes(status="final")
    assert [n["title"] for n in finals] == ["Reg note"]


def test_archive_is_soft_delete_kept_for_audit(notes_store):
    from services.meeting_notes_service import MeetingNoteError

    note = notes_store.create_note(title="t", summary="s")
    archived = notes_store.archive_note(note["id"], archived_by="admin")
    assert archived["archived"] is True
    assert archived["archived_at"]
    # hidden from the default list, still queryable for audit/BI
    assert notes_store.list_notes() == []
    kept = notes_store.list_notes(include_archived=True)
    assert [n["id"] for n in kept] == [note["id"]]
    # archived notes are read-only
    with pytest.raises(MeetingNoteError):
        notes_store.update_note(note["id"], {"summary": "x"})


def test_notes_persist_across_service_instances(tmp_path):
    from services import meeting_notes_service as mns

    path = str(tmp_path / "meeting_notes.json")
    first = mns.MeetingNotesService(data_path=path)
    created = first.create_note(title="t", summary="s", tags=["bi"])
    second = mns.MeetingNotesService(data_path=path)
    loaded = second.get_note(created["id"])
    assert loaded and loaded["title"] == "t" and loaded["tags"] == ["bi"]


# ---------------------------------------------------------------------------
# HTTP API — staff gating + CRUD cycle
# ---------------------------------------------------------------------------

def test_api_requires_staff_authorization(notes_store):
    listed = requests.get(f"{BASE_URL}/api/meetings/notes", timeout=10)
    assert listed.status_code == 401
    assert "error" in listed.json()

    created = requests.post(
        f"{BASE_URL}/api/meetings/notes",
        json={"title": "t", "summary": "s"},
        timeout=10,
    )
    assert created.status_code == 401

    updated = requests.put(
        f"{BASE_URL}/api/meetings/notes/note_x",
        json={"summary": "s"},
        timeout=10,
    )
    assert updated.status_code == 401

    deleted = requests.delete(f"{BASE_URL}/api/meetings/notes/note_x", timeout=10)
    assert deleted.status_code == 401


def test_api_admin_full_note_lifecycle(notes_store):
    token = _admin_token()
    auth = {"Authorization": f"Bearer {token}"}

    # Draft a summary note from the pre-ruling meeting.
    created = requests.post(
        f"{BASE_URL}/api/meetings/notes",
        headers=auth,
        json={
            "title": "Authority pre-ruling — summary",
            "summary": "Authority open to the functional MGA bridge; pre-ruling path sketched.",
            "meeting_ref": "regulatory-preruling-avi-ovadia",
            "meeting_date": "TBA",
            "counterparty": "Mr. Avi Ovadia — Capital Market, Insurance & Savings Authority",
            "regulatory_adjustments": "Quarterly assumption-change report format to follow Authority template.",
            "tags": ["bi", "regulatory", "ai"],
        },
        timeout=10,
    )
    assert created.status_code == 201, created.text
    note = created.json()["note"]
    assert note["status"] == "draft"
    assert note["tags"] == ["bi", "regulatory", "ai"]
    assert note["created_by"] == "admin"

    # Listed with the standard paginated shape.
    listed = requests.get(f"{BASE_URL}/api/meetings/notes", headers=auth, timeout=10)
    assert listed.status_code == 200
    body = listed.json()
    assert set(body) >= {"items", "page", "page_size", "total"}
    assert body["total"] == 1
    assert body["items"][0]["id"] == note["id"]

    # Tag filter — the future BI / AI read path.
    for tag, expected in (("regulatory", 1), ("distribution", 0)):
        filtered = requests.get(
            f"{BASE_URL}/api/meetings/notes",
            headers=auth,
            params={"tag": tag},
            timeout=10,
        )
        assert filtered.status_code == 200
        assert filtered.json()["total"] == expected, tag

    # Edit + finalize stores a new revision.
    updated = requests.put(
        f"{BASE_URL}/api/meetings/notes/{note['id']}",
        headers=auth,
        json={"summary": "Expanded after review.", "status": "final"},
        timeout=10,
    )
    assert updated.status_code == 200, updated.text
    final_note = updated.json()["note"]
    assert final_note["revision"] == 2
    assert final_note["status"] == "final"
    assert final_note["updated_by"] == "admin"

    # Validation errors surface as { "error": ... }.
    bad = requests.put(
        f"{BASE_URL}/api/meetings/notes/{note['id']}",
        headers=auth,
        json={"status": "published"},
        timeout=10,
    )
    assert bad.status_code == 400
    assert "error" in bad.json()

    missing = requests.put(
        f"{BASE_URL}/api/meetings/notes/note_missing",
        headers=auth,
        json={"summary": "x"},
        timeout=10,
    )
    assert missing.status_code == 404

    # Archive (soft delete): hidden by default, kept when asked for.
    archived = requests.delete(
        f"{BASE_URL}/api/meetings/notes/{note['id']}", headers=auth, timeout=10
    )
    assert archived.status_code == 200
    assert archived.json()["note"]["archived"] is True

    default_list = requests.get(
        f"{BASE_URL}/api/meetings/notes", headers=auth, timeout=10
    )
    assert default_list.json()["total"] == 0
    audit_list = requests.get(
        f"{BASE_URL}/api/meetings/notes",
        headers=auth,
        params={"include_archived": "1"},
        timeout=10,
    )
    assert audit_list.json()["total"] == 1


def test_api_rejects_invalid_json_body(notes_store):
    token = _admin_token()
    resp = requests.post(
        f"{BASE_URL}/api/meetings/notes",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        data="{not json",
        timeout=10,
    )
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_api_non_staff_session_is_rejected(notes_store):
    # The demo ``agent`` login is non-staff (not in confidential_access
    # STAFF_ROLES) and enabled in PHINS_TEST_MODE.
    login = requests.post(
        f"{BASE_URL}/api/login",
        json={"username": "agent", "password": "agent123"},
        timeout=10,
    )
    if login.status_code != 200:
        pytest.skip("no non-staff demo login available in this harness")
    token = login.json().get("token")
    resp = requests.get(
        f"{BASE_URL}/api/meetings/notes",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10,
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Pitch dashboard — staff-revealed notes admin UI
# ---------------------------------------------------------------------------

def test_dashboard_ships_meeting_notes_admin_block():
    html = PITCH.read_text(encoding="utf-8")
    # hidden until the staff check passes (same pattern as the share admin)
    assert 'id="meeting-notes-admin" hidden' in html
    assert 'id="meeting-note-form"' in html
    assert 'id="meeting-notes-list"' in html
    assert '"/api/meetings/notes"' in html
    # dedicated regulatory-adjustments field + reference tags
    assert 'id="note-regulatory"' in html
    for tag_input in ("note-tag-bi", "note-tag-regulatory", "note-tag-ai"):
        assert f'id="{tag_input}"' in html, tag_input
    # draft/final workflow controls
    assert 'id="note-status"' in html
    assert "Finalize" in html
    # the block lives inside the Meeting Diary panel
    diary = html.split('id="il-meeting-diary"', 1)[1]
    assert 'id="meeting-notes-admin"' in diary.split("</section>", 1)[0]


def test_dashboard_integrity_notice_covers_notes():
    html = PITCH.read_text(encoding="utf-8")
    assert "Meeting summary notes are a staff-gated admin record" in html
    assert "AI/BI layers may read notes but never post" in html
