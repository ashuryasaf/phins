"""Design placements survive a restart, and a bad write cannot replace them.

The media dashboard stores which video, thumbnail, and background each page
uses. Those choices live in one checksummed database row. A new process
loads that row after the media library. The login page then plays the
video the dashboard assigned.
"""

import copy
import json
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import web_portal.server as portal
from database.models import MediaDesignDocument
from services.media_design_store import (
    MediaDesignConflict,
    MediaDesignIntegrityError,
    MediaDesignStoreError,
    DESIGN_DOCUMENT_ID,
    document_checksum,
    load_design_in_session,
    merge_design_documents,
    seal_design_in_session,
)


class _ServerThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.httpd = HTTPServer(("127.0.0.1", 0), portal.PortalHandler)
        self.port = self.httpd.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"

    def run(self) -> None:
        self.httpd.serve_forever()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _warm(base: str) -> None:
    try:
        with urlopen(Request(base + "/api/media"), timeout=5) as resp:
            resp.read()
    except Exception:
        pass


def _admin(token: str) -> None:
    portal.USERS.setdefault("design-admin", {"username": "design-admin", "role": "admin"})
    portal.SESSIONS[token] = {
        "username": "design-admin",
        "role": "admin",
        "customer_id": "",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }


def _request(url, method="GET", payload=None, token=None):
    headers = {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body else {}


def _session():
    engine = create_engine("sqlite://")
    MediaDesignDocument.__table__.create(engine)
    return sessionmaker(bind=engine)()


def _asset(asset_id, kind, url):
    portal.MEDIA_ASSETS[asset_id] = {
        "id": asset_id,
        "name": f"{asset_id}.{kind}",
        "type": kind,
        "url": url,
        "data": "",
        "source": "upload",
    }


class _MemoryDesignDB:
    """In-process stand-in for media_design_documents."""

    def __init__(self):
        self.row = None
        self.fail = False

    def seal(self, payload, expected_revision=None):
        if self.fail:
            raise MediaDesignStoreError("db down")
        if not isinstance(payload, dict):
            raise MediaDesignIntegrityError("design document must be an object")
        digest = document_checksum(payload)
        if self.row is None:
            if expected_revision not in (None, 0):
                raise MediaDesignConflict(0, {})
            self.row = {"revision": 1, "sha256": digest, "payload": copy.deepcopy(payload)}
        else:
            current = self.row["revision"]
            if expected_revision is None or int(expected_revision) != current:
                raise MediaDesignConflict(current, copy.deepcopy(self.row["payload"]))
            self.row = {
                "revision": current + 1,
                "sha256": digest,
                "payload": copy.deepcopy(payload),
            }
        return {
            "revision": self.row["revision"],
            "sha256": digest,
            "payload": copy.deepcopy(self.row["payload"]),
        }

    def load(self):
        if self.row is None:
            return None
        if self.row.get("corrupt"):
            return {
                "corrupt": True,
                "revision": self.row["revision"],
                "sha256": self.row.get("sha256") or "",
                "payload": {},
            }
        return {
            "corrupt": False,
            "revision": self.row["revision"],
            "sha256": self.row["sha256"],
            "payload": copy.deepcopy(self.row["payload"]),
        }


def _install_store(monkeypatch, store: _MemoryDesignDB) -> None:
    monkeypatch.setattr(portal, "_media_durable_enabled", lambda: True)
    monkeypatch.setattr("services.media_design_store.seal_design", store.seal)
    monkeypatch.setattr("services.media_design_store.load_design", store.load)


def _design_flags():
    return {
        "revision": portal._design_revision,
        "checksum": portal._design_sealed_checksum,
        "loaded": copy.deepcopy(portal._design_loaded_copy),
        "hydrated": portal._design_hydrated,
        "corrupt": portal._design_corrupt,
        "catalog": portal._media_library_catalog_ok,
        "settings": copy.deepcopy(portal.DESIGN_SETTINGS),
    }


def _restore_flags(saved) -> None:
    portal._design_revision = saved["revision"]
    portal._design_sealed_checksum = saved["checksum"]
    portal._design_loaded_copy = saved["loaded"]
    portal._design_hydrated = saved["hydrated"]
    portal._design_corrupt = saved["corrupt"]
    portal._media_library_catalog_ok = saved["catalog"]
    portal.DESIGN_SETTINGS.clear()
    portal.DESIGN_SETTINGS.update(saved["settings"])


def test_design_document_round_trip_refuses_a_bad_checksum_and_a_stale_revision():
    session = _session()
    payload = {
        "login_hero_video_id": "media-login-hero",
        "login_background_id": "media-login-bg",
        "login_thumbnail_id": "media-login-thumb",
        "tagline": "הגנה מקיפה",
        "show_video": True,
    }
    sealed = seal_design_in_session(session, payload, expected_revision=0)
    assert sealed["revision"] == 1
    assert sealed["sha256"] == document_checksum(payload)
    loaded = load_design_in_session(session, )
    assert loaded["corrupt"] is False
    assert loaded["payload"]["tagline"] == "הגנה מקיפה"
    assert loaded["payload"]["login_hero_video_id"] == "media-login-hero"

    try:
        seal_design_in_session(session, {"login_hero_video_id": "other"}, expected_revision=0)
        raise AssertionError("stale revision replaced the document")
    except MediaDesignConflict as conflict:
        assert conflict.revision == 1
        assert conflict.payload["login_hero_video_id"] == "media-login-hero"
        session.rollback()

    again = seal_design_in_session(
        session,
        {"login_hero_video_id": "media-login-hero", "login_thumbnail_id": "media-login-thumb"},
        expected_revision=1,
    )
    assert again["revision"] == 2
    assert load_design_in_session(session)["payload"]["login_thumbnail_id"] == "media-login-thumb"

    row = session.query(MediaDesignDocument).filter_by(id=DESIGN_DOCUMENT_ID).one()
    row.payload_json = '{"login_hero_video_id":"tampered"}'
    session.commit()
    corrupt = load_design_in_session(session)
    assert corrupt["corrupt"] is True
    assert corrupt["payload"] == {}
    session.close()


def test_merge_keeps_a_slot_the_caller_did_not_change():
    stored = {"hero_video_id": "hero-a", "login_hero_video_id": "login-b", "login_background_id": ""}
    base = {"hero_video_id": "hero-a", "login_hero_video_id": "", "login_background_id": ""}
    incoming = {"hero_video_id": "hero-a", "login_hero_video_id": "", "login_background_id": "bg-c"}
    merged = merge_design_documents(stored, base, incoming)
    assert merged["hero_video_id"] == "hero-a"
    assert merged["login_hero_video_id"] == "login-b"
    assert merged["login_background_id"] == "bg-c"


def test_login_hero_background_and_thumbnail_survive_a_restart(monkeypatch):
    store = _MemoryDesignDB()
    _install_store(monkeypatch, store)
    flags = _design_flags()
    portal._design_revision = 0
    portal._design_sealed_checksum = ""
    portal._design_loaded_copy = None
    portal._design_hydrated = False
    portal._design_corrupt = False
    portal._media_library_catalog_ok = True
    token = "phins_design_restart"
    video_id = "media-design-login-video"
    background_id = "media-design-login-bg"
    thumb_id = "media-design-login-thumb"
    srv = _ServerThread()
    srv.start()
    try:
        _warm(srv.base)
        _admin(token)
        _asset(video_id, "video", "/media-files/media-design-login-video/hero.mp4")
        _asset(background_id, "image", "/media-files/media-design-login-bg/bg.jpg")
        _asset(thumb_id, "image", "/media-files/media-design-login-thumb/thumb.jpg")

        status, body = _request(
            srv.base + "/api/design/settings",
            method="POST",
            token=token,
            payload={
                "login_hero_video_id": video_id,
                "login_background_id": background_id,
                "login_thumbnail_id": thumb_id,
                "hero_video_id": video_id,
                "hero_background_id": background_id,
                "video_poster_id": thumb_id,
            },
        )
        assert status == 200, body
        assert store.row["payload"]["login_hero_video_id"] == video_id
        assert store.row["payload"]["login_background_id"] == background_id
        assert store.row["payload"]["login_thumbnail_id"] == thumb_id
        assert store.row["sha256"] == document_checksum(store.row["payload"])

        # A new process: memory is the code defaults, the database row remains.
        portal.DESIGN_SETTINGS.clear()
        portal.DESIGN_SETTINGS.update({
            "video_url": "",
            "video_poster": "",
            "tagline": "Comprehensive Protection for Your Future",
            "primary_color": "#0d47a1",
            "accent_color": "#ff6b35",
            "show_video": True,
            "hero_video_id": "",
            "hero_background_id": "",
            "video_poster_id": "",
            "login_hero_video_id": "",
            "login_background_id": "",
            "login_thumbnail_id": "",
            "updated_at": None,
        })
        for slot_key in portal.MEDIA_PLACEMENT_SLOTS:
            portal.DESIGN_SETTINGS.setdefault(slot_key, "")
        portal._design_revision = 0
        portal._design_sealed_checksum = ""
        portal._design_loaded_copy = None
        portal._design_hydrated = False
        portal._design_corrupt = False

        assert portal.hydrate_design_settings() == "applied"
        assert portal.DESIGN_SETTINGS["login_hero_video_id"] == video_id
        assert portal.DESIGN_SETTINGS["login_background_id"] == background_id
        assert portal.DESIGN_SETTINGS["login_thumbnail_id"] == thumb_id
        assert portal.DESIGN_SETTINGS["hero_video_id"] == video_id
        assert portal.DESIGN_SETTINGS["video_url"] == "/media-files/media-design-login-video/hero.mp4"
        assert portal.DESIGN_SETTINGS["video_poster"] == "/media-files/media-design-login-thumb/thumb.jpg"

        status, public = _request(srv.base + "/api/design/settings")
        assert status == 200
        assert public["login_hero_video_url"] == "/media-files/media-design-login-video/hero.mp4"
        assert public["login_background_url"] == "/media-files/media-design-login-bg/bg.jpg"
        assert public["login_thumbnail_url"] == "/media-files/media-design-login-thumb/thumb.jpg"
        assert public["hero_background_url"] == "/media-files/media-design-login-bg/bg.jpg"
        assert "login_hero_video_id" not in public
    finally:
        for asset_id in (video_id, background_id, thumb_id):
            portal.MEDIA_ASSETS.pop(asset_id, None)
        _restore_flags(flags)
        portal.SESSIONS.pop(token, None)
        srv.stop()


def test_failed_seal_rolls_back_the_login_hero(monkeypatch):
    store = _MemoryDesignDB()
    store.fail = True
    _install_store(monkeypatch, store)
    flags = _design_flags()
    portal._design_hydrated = False
    portal._design_corrupt = False
    portal._design_revision = 0
    portal._design_sealed_checksum = ""
    portal._design_loaded_copy = None
    token = "phins_design_rollback"
    video_id = "media-design-rollback-video"
    srv = _ServerThread()
    srv.start()
    try:
        _warm(srv.base)
        _admin(token)
        _asset(video_id, "video", "/media-files/media-design-rollback-video/hero.mp4")
        before = portal.DESIGN_SETTINGS.get("login_hero_video_id")
        status, body = _request(
            srv.base + "/api/design/settings",
            method="POST",
            token=token,
            payload={"login_hero_video_id": video_id},
        )
        assert status == 503, body
        assert body["error"] == "Design settings could not be stored durably"
        assert portal.DESIGN_SETTINGS.get("login_hero_video_id") == before
        assert store.row is None
    finally:
        portal.MEDIA_ASSETS.pop(video_id, None)
        _restore_flags(flags)
        portal.SESSIONS.pop(token, None)
        srv.stop()


def test_corrupt_document_is_not_applied_or_replaced(monkeypatch):
    store = _MemoryDesignDB()
    store.row = {"revision": 4, "sha256": "deadbeef", "payload": {}, "corrupt": True}
    _install_store(monkeypatch, store)
    flags = _design_flags()
    portal._design_hydrated = False
    portal._design_corrupt = False
    portal._design_revision = 0
    portal._design_sealed_checksum = ""
    portal._design_loaded_copy = None
    portal.DESIGN_SETTINGS["login_hero_video_id"] = "keep-me"
    try:
        assert portal.hydrate_design_settings() == "corrupt"
        assert portal.DESIGN_SETTINGS["login_hero_video_id"] == "keep-me"
        assert store.row["sha256"] == "deadbeef"
        assert portal.seal_design_settings() is True
        assert store.row["sha256"] == "deadbeef"
    finally:
        _restore_flags(flags)


def test_dangling_placement_is_cleared_only_when_the_library_catalog_loaded(monkeypatch):
    store = _MemoryDesignDB()
    store.row = {
        "revision": 2,
        "sha256": "",
        "payload": {
            "login_hero_video_id": "media-missing-hero",
            "hero_video_id": "media-missing-hero",
            "video_url": "/media-files/media-missing-hero/gone.mp4",
            "updated_at": "2026-01-01T00:00:00",
        },
    }
    store.row["sha256"] = document_checksum(store.row["payload"])
    _install_store(monkeypatch, store)
    flags = _design_flags()
    portal.DESIGN_SETTINGS["updated_at"] = None
    portal.DESIGN_SETTINGS["login_hero_video_id"] = ""
    portal.DESIGN_SETTINGS["hero_video_id"] = ""
    portal._design_hydrated = False
    portal._design_corrupt = False
    portal._design_revision = 0
    portal._design_sealed_checksum = ""
    portal._design_loaded_copy = None
    portal._media_library_catalog_ok = False
    try:
        assert portal.hydrate_design_settings() == "applied"
        assert portal.DESIGN_SETTINGS["login_hero_video_id"] == "media-missing-hero"
        assert store.row["payload"]["login_hero_video_id"] == "media-missing-hero"

        portal._design_hydrated = False
        portal._media_library_catalog_ok = True
        portal.DESIGN_SETTINGS["updated_at"] = None
        assert portal.hydrate_design_settings() == "applied"
        assert portal.DESIGN_SETTINGS["login_hero_video_id"] == ""
        assert portal.DESIGN_SETTINGS["hero_video_id"] == ""
        assert portal.DESIGN_SETTINGS["video_url"] == ""
        assert store.row["payload"]["login_hero_video_id"] == ""
        assert store.row["payload"]["hero_video_id"] == ""
    finally:
        _restore_flags(flags)


def test_revision_conflict_preserves_the_other_replicas_login_hero(monkeypatch):
    store = _MemoryDesignDB()
    _install_store(monkeypatch, store)
    flags = _design_flags()
    base = {
        "hero_video_id": "hero-a",
        "login_hero_video_id": "",
        "login_background_id": "",
        "updated_at": "2026-01-01T00:00:00",
    }
    for slot_key in portal.MEDIA_PLACEMENT_SLOTS:
        base.setdefault(slot_key, "")
    store.row = {"revision": 1, "sha256": document_checksum(base), "payload": copy.deepcopy(base)}
    portal.DESIGN_SETTINGS.clear()
    portal.DESIGN_SETTINGS.update(copy.deepcopy(base))
    portal._design_revision = 1
    portal._design_sealed_checksum = store.row["sha256"]
    portal._design_loaded_copy = copy.deepcopy(base)
    portal._design_hydrated = True
    portal._design_corrupt = False
    portal._media_library_catalog_ok = True

    # Another replica committed a login hero before this save landed.
    remote = copy.deepcopy(base)
    remote["login_hero_video_id"] = "login-b"
    remote["updated_at"] = "2026-01-02T00:00:00"
    store.row = {"revision": 2, "sha256": document_checksum(remote), "payload": remote}

    background_id = "media-design-merge-bg"
    _asset(background_id, "image", "/media-files/media-design-merge-bg/bg.jpg")
    _asset("hero-a", "video", "/media-files/hero-a/hero.mp4")
    _asset("login-b", "video", "/media-files/login-b/login.mp4")
    token = "phins_design_merge"
    srv = _ServerThread()
    srv.start()
    try:
        _warm(srv.base)
        _admin(token)
        status, body = _request(
            srv.base + "/api/design/settings",
            method="POST",
            token=token,
            payload={"login_background_id": background_id},
        )
        assert status == 200, body
        assert portal.DESIGN_SETTINGS["hero_video_id"] == "hero-a"
        assert portal.DESIGN_SETTINGS["login_hero_video_id"] == "login-b"
        assert portal.DESIGN_SETTINGS["login_background_id"] == background_id
        assert store.row["payload"]["login_hero_video_id"] == "login-b"
        assert store.row["payload"]["login_background_id"] == background_id
        assert store.row["revision"] == 3
    finally:
        for asset_id in (background_id, "hero-a", "login-b"):
            portal.MEDIA_ASSETS.pop(asset_id, None)
        _restore_flags(flags)
        portal.SESSIONS.pop(token, None)
        srv.stop()
