"""Staff address book on the signed-documents desk.

Revoke and delete close a link. They do not remove the share row, rewrite
its password seal or use history, or touch a sealed signature. The open
password is readable by staff and absent from an unlock response and the
public gate.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
import requests

from services.confidential_share_service import ShareError

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
TOKEN = "t" * 40
SECRET = "s" * 32
ROOT = Path(__file__).resolve().parents[1]


def _stable(record: dict) -> dict:
    keys = (
        "password_hash",
        "password_salt",
        "password_vault",
        "used_count",
        "use_log",
        "sessions",
        "nda_acceptances",
        "nda_sha256",
        "max_uses",
        "label",
        "path",
    )
    return {key: record.get(key) for key in keys}


@pytest.fixture
def store(tmp_path, monkeypatch):
    from services import confidential_share_service as css
    from services import document_use_ledger as dul
    from services import signed_document_archive as sda

    monkeypatch.setenv("USE_DATABASE", "false")
    monkeypatch.setenv("PHINS_DOCUMENT_USE_LEDGER_PATH", str(tmp_path / "use.json"))
    css.reset_confidential_share_service_for_tests()
    dul.reset_document_use_ledger_for_tests()
    sda.reset_signed_document_archive_for_tests()
    service = css.get_confidential_share_service(data_path=str(tmp_path / "shares.json"))
    sda.get_signed_document_archive(str(tmp_path / "signed"))
    dul.get_document_use_ledger(str(tmp_path / "use.json"))
    yield service
    css.reset_confidential_share_service_for_tests()
    dul.reset_document_use_ledger_for_tests()
    sda.reset_signed_document_archive_for_tests()


def test_staff_list_shows_password_and_unlock_does_not(store):
    created = store.create_share(
        path="/pitch-dashboard.html",
        password="desk-open-1",
        max_uses=3,
        label="Dana Levi",
    )
    assert "password" not in created
    assert "password_hash" not in created
    assert "password_vault" not in created

    listed = store.list_shares(reveal_password=True)
    row = next(item for item in listed if item["id"] == created["id"])
    assert row["password"] == "desk-open-1"
    assert row["password_retained"] is True
    assert row["password_unreadable"] is False
    assert row["label"] == "Dana Levi"
    assert row["status"] == "active"
    assert row["used_count"] == 0
    assert row["share_url_path"].endswith("?share=" + created["id"])
    assert "password_hash" not in row and "password_vault" not in row

    hidden = store.get_share(created["id"])
    assert "password" not in hidden
    view, _target = store.unlock(created["id"], "desk-open-1")
    assert "password" not in view and "password_hash" not in view and "password_vault" not in view


def test_legacy_and_unreadable_seals_do_not_invent_a_password(store):
    created = store.create_share(
        path="/pitch-dashboard.html", password="desk-open-1", max_uses=2, label="ACME"
    )
    raw_path = store._path
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    payload["shares"][created["id"]].pop("password_vault", None)
    raw_path.write_text(json.dumps(payload), encoding="utf-8")
    legacy = store.list_shares(reveal_password=True)[0]
    assert legacy["password_retained"] is False
    assert legacy["password"] is None
    assert legacy["password_unreadable"] is False
    store.unlock(created["id"], "desk-open-1")

    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    payload["shares"][created["id"]]["password_vault"] = json.dumps(
        {"scheme": "fernet", "ciphertext": "not-a-token"}
    )
    raw_path.write_text(json.dumps(payload), encoding="utf-8")
    broken = store.list_shares(reveal_password=True)[0]
    assert broken["password_unreadable"] is True
    assert broken["password"] is None
    store.unlock(created["id"], "desk-open-1")


def test_revoke_and_delete_keep_the_row_the_seal_and_the_chain(store, tmp_path):
    from services.document_use_ledger import get_document_use_ledger
    from services.signed_document_archive import get_signed_document_archive

    created = store.create_share(
        path="/business-plan.html",
        password="desk-open-1",
        max_uses=1,
        label="ACME",
        nda_required=True,
    )
    view, _target = store.unlock(
        created["id"], "desk-open-1", nda_accepted=True, signer_name="Dana Levi"
    )
    session_key = view["session_key"]
    before = _stable(store.get_share_raw(created["id"]))
    assert store.share_is_active_for_path(created["id"], "/business-plan.html", session_key)

    text = "Non-Disclosure Agreement\nReceiving Party ACME\n"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    archive = get_signed_document_archive()
    archive_id = archive.store_signature({
        "doc_type": "nda",
        "doc_instance_id": created["nda_doc_instance_id"],
        "entry_id": "LGLSIG-address-book",
        "document_hash": digest,
        "document_text": text,
        "share_id": created["id"],
        "label": "ACME",
        "signer_name": "Dana Levi",
    })
    sealed_path = archive.directory / f"{archive_id}.json"
    sealed_bytes = sealed_path.read_bytes()

    revoked = store.revoke_share(created["id"], revoked_by="admin")
    assert revoked["status"] == "revoked"
    assert revoked["revoked_at"] and revoked["revoked_by"] == "admin"
    again = store.revoke_share(created["id"], revoked_by="other")
    assert again["revoked_at"] == revoked["revoked_at"]
    assert again["revoked_by"] == "admin"
    assert not store.share_is_active_for_path(created["id"], "/business-plan.html", session_key)
    with pytest.raises(ShareError, match="revoked"):
        store.unlock(created["id"], "desk-open-1", nda_accepted=True, signer_name="Dana Levi")

    deleted = store.delete_share(created["id"], deleted_by="admin")
    assert deleted["status"] == "deleted"
    assert deleted["deleted_at"] and deleted["deleted_by"] == "admin"
    second = store.delete_share(created["id"], deleted_by="other")
    assert second["deleted_at"] == deleted["deleted_at"]
    with pytest.raises(ShareError, match="deleted"):
        store.revoke_share(created["id"], revoked_by="admin")
    with pytest.raises(ShareError, match="deleted"):
        store.unlock(created["id"], "desk-open-1", nda_accepted=True, signer_name="Dana Levi")
    assert store.get_share(created["id"])["id"] == created["id"]
    assert not store.share_is_active_for_path(created["id"], "/business-plan.html", session_key)

    after = _stable(store.get_share_raw(created["id"]))
    assert after == before
    assert sealed_path.read_bytes() == sealed_bytes
    report = get_document_use_ledger().list_events()
    assert report["intact"] is True
    assert any(item["action"] == "signed" and item["share_id"] == created["id"] for item in report["items"])


def test_pitch_desk_markup_has_fold_and_address_book():
    html = (ROOT / "web_portal" / "static" / "pitch-dashboard.html").read_text(encoding="utf-8")
    assert 'id="signed-use-toggle"' in html
    assert 'id="addressed-links"' in html
    assert '"signed-use-section": "investor-documents-section"' in html
    assert "phinsSetSignedUseOpen" in html
    assert ">Revoke<" in html or 'textContent = "Revoke"' in html
    assert 'textContent = "Delete"' in html


@pytest.fixture
def http_book(tmp_path, monkeypatch):
    from services import confidential_share_service as css
    from services import document_use_ledger as dul

    monkeypatch.setenv("PHINS_ENVIRONMENT", "production")
    monkeypatch.setenv("SESSION_SECRET_KEY", SECRET)
    monkeypatch.setenv("PHINS_CONFIDENTIAL_ACCESS_TOKEN", TOKEN)
    monkeypatch.setenv("USE_DATABASE", "false")
    monkeypatch.setenv("PHINS_DOCUMENT_USE_LEDGER_PATH", str(tmp_path / "use.json"))
    css.reset_confidential_share_service_for_tests()
    dul.reset_document_use_ledger_for_tests()
    css.get_confidential_share_service(data_path=str(tmp_path / "shares.json"))
    dul.get_document_use_ledger(str(tmp_path / "use.json"))
    yield
    css.reset_confidential_share_service_for_tests()
    dul.reset_document_use_ledger_for_tests()


def _admin():
    login = requests.post(
        f"{BASE_URL}/api/login",
        json={"username": "admin", "password": "admin123"},
        timeout=10,
    )
    assert login.status_code == 200, login.text
    session = requests.Session()
    session.headers["Authorization"] = f"Bearer {login.json()['token']}"
    return session


def test_http_address_book_revoke_and_delete_keep_the_chain(http_book):
    from services.document_use_ledger import get_document_use_ledger

    anonymous = requests.get(f"{BASE_URL}/api/confidential/shares", timeout=10)
    assert anonymous.status_code == 401

    admin = _admin()
    created = admin.post(
        f"{BASE_URL}/api/confidential/shares",
        json={
            "path": "/pitch-dashboard.html",
            "password": "desk-open-1",
            "mode": "multi",
            "max_uses": 5,
            "label": "Investor ACME",
        },
        timeout=10,
    )
    assert created.status_code == 201, created.text
    share = created.json()["share"]
    assert "password" not in share

    page = requests.get(
        f"{BASE_URL}/pitch-dashboard.html",
        params={"share": share["id"]},
        timeout=10,
        allow_redirects=False,
    )
    assert page.status_code == 401
    assert "desk-open-1" not in page.text

    listed = admin.get(f"{BASE_URL}/api/confidential/shares", timeout=10)
    assert listed.status_code == 200
    row = next(item for item in listed.json()["items"] if item["id"] == share["id"])
    assert row["password"] == "desk-open-1"
    assert row["label"] == "Investor ACME"
    assert row["max_uses"] == 5
    assert "password_hash" not in row

    revoked = admin.delete(f"{BASE_URL}/api/confidential/shares/{share['id']}", timeout=10)
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["share"]["status"] == "revoked"
    refused = requests.post(
        f"{BASE_URL}/api/confidential/share-unlock",
        json={"share_id": share["id"], "password": "desk-open-1", "path": "/pitch-dashboard.html"},
        timeout=10,
    )
    assert refused.status_code == 400
    assert "revoked" in refused.json()["error"].lower()

    deleted = admin.post(f"{BASE_URL}/api/confidential/shares/{share['id']}/delete", json={}, timeout=10)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["share"]["status"] == "deleted"
    blocked = admin.delete(f"{BASE_URL}/api/confidential/shares/{share['id']}", timeout=10)
    assert blocked.status_code == 409

    kept = admin.get(f"{BASE_URL}/api/confidential/shares", timeout=10).json()["items"]
    still = next(item for item in kept if item["id"] == share["id"])
    assert still["status"] == "deleted"
    assert still["password"] == "desk-open-1"
    assert still["used_count"] == 0

    report = get_document_use_ledger().list_events()
    assert report["intact"] is True
    actions = [item["action"] for item in report["items"] if item["share_id"] == share["id"]]
    assert actions.count("sent") == 1
    assert actions.count("revoked") == 1
    assert actions.count("deleted") == 1
    assert get_document_use_ledger().list_events()["total"] == report["total"]
