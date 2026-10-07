"""Download path and durable storage for media-library videos and images.

The public playback URL is ``/media-files/{asset_id}/{name}`` while the cache
file is ``{asset_id}-{stem}``. These tests cover that resolution, the
authenticated download, checksum refusal, database round-trip, and delete.
"""

import hashlib
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import web_portal.server as portal
from database.models import MediaLibraryBlob
from services.media_library_store import (
    MediaLibraryIntegrityError,
    MediaLibraryStoreError,
    delete_asset_in_session,
    load_asset_in_session,
    seal_asset_in_session,
)


_VIDEO = b"PHINS-DURABLE-VIDEO-BYTES"


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
    # Inject after the server's first request. Test mode clears SESSIONS the
    # first time a port is used.
    portal.USERS.setdefault("media-admin", {"username": "media-admin", "role": "admin"})
    portal.SESSIONS[token] = {
        "username": "media-admin",
        "role": "admin",
        "customer_id": "",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }


def _session():
    engine = create_engine("sqlite://")
    MediaLibraryBlob.__table__.create(engine)
    return sessionmaker(bind=engine)()


def _seed_video(asset_id: str = "media-durablevid01") -> dict:
    path = portal.write_media_binary_payload(asset_id, "story.mp4", _VIDEO)
    asset = {
        "id": asset_id,
        "name": "story.mp4",
        "type": "video",
        "format": "video/mp4",
        "size": len(_VIDEO),
        "url": portal.build_internal_media_file_url(asset_id, "story.mp4"),
        "data": "",
        "file_path": path,
        "stored_externally": True,
        "checksum": portal.compute_media_checksum(_VIDEO),
    }
    portal.MEDIA_ASSETS[asset_id] = asset
    return asset


def _get(url: str, token: str = ""):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except HTTPError as exc:
        body = exc.read()
        return exc.code, body, exc.headers.get("Content-Type", "")


def test_public_media_url_serves_the_flat_cache_file_as_video():
    asset = _seed_video()
    srv = _ServerThread()
    srv.start()
    try:
        _warm(srv.base)
        assert asset["file_path"].endswith(f"{asset['id']}-story_mp4")
        assert asset["url"] == f"/media-files/{asset['id']}/story_mp4"
        status, body, content_type = _get(srv.base + asset["url"])
        assert status == 200
        assert body == _VIDEO
        assert content_type.startswith("video/mp4")
    finally:
        srv.stop()
        portal.MEDIA_ASSETS.pop(asset["id"], None)


def test_authenticated_download_requires_a_session_and_returns_bytes():
    asset = _seed_video("media-durablevid02")
    token = "phins_media_download_token"
    srv = _ServerThread()
    srv.start()
    try:
        _warm(srv.base)
        _admin(token)
        status, _body, _ctype = _get(srv.base + f"/api/media/{asset['id']}/download")
        assert status == 403
        status, body, content_type = _get(
            srv.base + f"/api/media/{asset['id']}/download",
            token=token,
        )
        assert status == 200
        assert body == _VIDEO
        assert content_type.startswith("video/mp4")
    finally:
        srv.stop()
        portal.MEDIA_ASSETS.pop(asset["id"], None)
        portal.SESSIONS.pop(token, None)


def test_checksum_mismatch_is_not_served():
    asset = _seed_video("media-durablevid03")
    with open(asset["file_path"], "wb") as handle:
        handle.write(b"tampered-video")
    srv = _ServerThread()
    srv.start()
    try:
        _warm(srv.base)
        status, body, _ctype = _get(srv.base + asset["url"])
        assert status == 409
        assert b"checksum" in body.lower()
        token = "phins_media_mismatch_token"
        _admin(token)
        status, body, _ctype = _get(
            srv.base + f"/api/media/{asset['id']}/download",
            token=token,
        )
        assert status == 409
        assert b"Media checksum mismatch" in body
        portal.SESSIONS.pop(token, None)
    finally:
        srv.stop()
        portal.MEDIA_ASSETS.pop(asset["id"], None)


def test_missing_cache_is_restored_from_the_durable_blob(monkeypatch):
    asset = _seed_video("media-durablevid04")
    sha = asset["checksum"]
    original_path = asset["file_path"]
    import os
    os.remove(original_path)
    asset["file_path"] = original_path

    def _enabled():
        return True

    def _load(asset_id):
        assert asset_id == asset["id"]
        return {
            "corrupt": False,
            "asset_id": asset_id,
            "sha256": sha,
            "payload": _VIDEO,
            "record": {"id": asset_id, "checksum": sha},
        }

    monkeypatch.setattr(portal, "_media_durable_enabled", _enabled)
    monkeypatch.setattr("services.media_library_store.load_asset", _load)
    srv = _ServerThread()
    srv.start()
    try:
        _warm(srv.base)
        status, body, content_type = _get(srv.base + asset["url"])
        assert status == 200
        assert body == _VIDEO
        assert content_type.startswith("video/mp4")
        assert os.path.isfile(asset["file_path"])
        assert portal._compute_file_checksum(asset["file_path"]) == sha
    finally:
        srv.stop()
        portal.MEDIA_ASSETS.pop(asset["id"], None)


def test_failed_durable_delete_leaves_the_library_record(monkeypatch):
    asset = _seed_video("media-durablevid05")
    token = "phins_media_delete_token"

    def _enabled():
        return True

    def _boom(_asset_id):
        raise MediaLibraryStoreError("db down")

    monkeypatch.setattr(portal, "_media_durable_enabled", _enabled)
    monkeypatch.setattr("services.media_library_store.delete_asset", _boom)
    srv = _ServerThread()
    srv.start()
    try:
        _warm(srv.base)
        _admin(token)
        req = Request(
            srv.base + f"/api/media/{asset['id']}",
            headers={"Authorization": f"Bearer {token}"},
            method="DELETE",
        )
        try:
            with urlopen(req, timeout=10) as resp:
                status, body = resp.status, resp.read()
        except HTTPError as exc:
            status, body = exc.code, exc.read()
        assert status == 503
        assert b"Durable media delete failed" in body
        assert asset["id"] in portal.MEDIA_ASSETS
        assert __import__("os").path.isfile(asset["file_path"])
    finally:
        srv.stop()
        portal.MEDIA_ASSETS.pop(asset["id"], None)
        portal.SESSIONS.pop(token, None)


def test_blob_round_trip_refuses_a_different_checksum_and_detects_corruption():
    session = _session()
    record = {"id": "media-db1", "name": "clip.mp4", "type": "video", "format": "video/mp4", "checksum": ""}
    digest = seal_asset_in_session(session, "media-db1", _VIDEO, record)
    assert digest == hashlib.sha256(_VIDEO).hexdigest()
    loaded = load_asset_in_session(session, "media-db1")
    assert loaded["corrupt"] is False
    assert loaded["payload"] == _VIDEO
    assert loaded["sha256"] == digest

    try:
        seal_asset_in_session(session, "media-db1", b"other-bytes", {"checksum": ""})
        raise AssertionError("different checksum was stored")
    except MediaLibraryIntegrityError:
        session.rollback()
    again = load_asset_in_session(session, "media-db1")
    assert again["payload"] == _VIDEO

    row = session.query(MediaLibraryBlob).filter_by(asset_id="media-db1").one()
    row.payload = b"corrupted"
    session.commit()
    corrupt = load_asset_in_session(session, "media-db1")
    assert corrupt["corrupt"] is True
    assert corrupt["payload"] == b""

    session.query(MediaLibraryBlob).delete()
    session.commit()
    digest = seal_asset_in_session(session, "media-db1", b"replacement-bytes", {"checksum": ""})
    assert load_asset_in_session(session, "media-db1")["sha256"] == digest
    assert delete_asset_in_session(session, "media-db1") is True
    assert load_asset_in_session(session, "media-db1") is None
    session.close()
