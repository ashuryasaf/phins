"""Media placement integrity for landing, apply, and chat surfaces.

Use and Save Changes both POST /api/design/settings. A slot accepts only an
existing asset of the matching type, a partial write leaves every other slot
alone, and deleting an asset clears only the slots that pointed at it.
"""

import json
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal


_SLOT_KEYS = (
    "hero_video_id",
    "hero_background_id",
    "video_poster_id",
    "promo_banner_id",
    "apply_disclosure_video_id",
    "apply_disclosure_control_video_id",
    "apply_chat_disclaimer_video_id",
    "claims_chat_disclaimer_video_id",
    "video_url",
    "video_poster",
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
    portal.SESSIONS[token] = {
        "username": "placement-admin",
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


def _snapshot():
    return {key: portal.DESIGN_SETTINGS.get(key, "") for key in _SLOT_KEYS}


def _restore(saved):
    for key, value in saved.items():
        portal.DESIGN_SETTINGS[key] = value


def _asset(asset_id, kind, url):
    portal.MEDIA_ASSETS[asset_id] = {
        "id": asset_id,
        "name": f"{asset_id}.{kind}",
        "type": kind,
        "url": url,
        "data": "",
        "source": "upload",
    }


def test_use_allocates_chat_disclaimers_without_clearing_landing_hero():
    srv = _ServerThread()
    srv.start()
    _warm(srv.base)
    token = "phins_test_place_use"
    _admin(token)
    saved = _snapshot()
    video_id = "media-place-hero"
    chat_id = "media-place-chat"
    claim_id = "media-place-claim"
    try:
        _asset(video_id, "video", "/media-files/media-place-hero/hero.mp4")
        _asset(chat_id, "video", "/media-files/media-place-chat/apply.mp4")
        _asset(claim_id, "video", "/media-files/media-place-claim/claim.mp4")

        status, _ = _request(
            srv.base + "/api/design/settings",
            method="POST",
            token=token,
            payload={"hero_video_id": video_id, "video_url": "https://cdn.example.com/stale.mp4"},
        )
        assert status == 200
        assert portal.DESIGN_SETTINGS["hero_video_id"] == video_id
        assert portal.DESIGN_SETTINGS["video_url"] == "/media-files/media-place-hero/hero.mp4"

        status, body = _request(
            srv.base + "/api/design/settings",
            method="POST",
            token=token,
            payload={
                "apply_chat_disclaimer_video_id": chat_id,
                "claims_chat_disclaimer_video_id": claim_id,
            },
        )
        assert status == 200, body
        assert portal.DESIGN_SETTINGS["hero_video_id"] == video_id
        assert portal.DESIGN_SETTINGS["video_url"] == "/media-files/media-place-hero/hero.mp4"
        assert portal.DESIGN_SETTINGS["apply_chat_disclaimer_video_id"] == chat_id
        assert portal.DESIGN_SETTINGS["claims_chat_disclaimer_video_id"] == claim_id

        status, public = _request(srv.base + "/api/design/settings")
        assert status == 200
        assert public["video_url"] == "/media-files/media-place-hero/hero.mp4"
        assert public["apply_chat_disclaimer_video_url"] == "/media-files/media-place-chat/apply.mp4"
        assert public["claims_chat_disclaimer_video_url"] == "/media-files/media-place-claim/claim.mp4"
        assert "apply_chat_disclaimer_video_id" not in public
        assert "claims_chat_disclaimer_video_id" not in public
    finally:
        for asset_id in (video_id, chat_id, claim_id):
            portal.MEDIA_ASSETS.pop(asset_id, None)
        _restore(saved)
        srv.stop()


def test_save_rejects_wrong_type_and_writes_nothing():
    srv = _ServerThread()
    srv.start()
    _warm(srv.base)
    token = "phins_test_place_type"
    _admin(token)
    saved = _snapshot()
    photo_id = "media-place-photo"
    video_id = "media-place-keep"
    try:
        _asset(photo_id, "image", "/media-files/media-place-photo/banner.jpg")
        _asset(video_id, "video", "/media-files/media-place-keep/keep.mp4")
        portal.DESIGN_SETTINGS["hero_video_id"] = video_id
        portal.DESIGN_SETTINGS["video_url"] = "/media-files/media-place-keep/keep.mp4"
        portal.DESIGN_SETTINGS["claims_chat_disclaimer_video_id"] = ""

        status, body = _request(
            srv.base + "/api/design/settings",
            method="POST",
            token=token,
            payload={
                "hero_video_id": photo_id,
                "claims_chat_disclaimer_video_id": video_id,
            },
        )
        assert status == 400
        assert "hero_video_id" in body.get("invalid_refs", [])
        assert portal.DESIGN_SETTINGS["hero_video_id"] == video_id
        assert portal.DESIGN_SETTINGS["claims_chat_disclaimer_video_id"] == ""

        status, body = _request(
            srv.base + "/api/design/settings",
            method="POST",
            token=token,
            payload={"promo_banner_id": video_id},
        )
        assert status == 400
        assert body.get("invalid_refs") == ["promo_banner_id"]
        assert portal.DESIGN_SETTINGS.get("promo_banner_id", "") == saved.get("promo_banner_id", "")

        status, body = _request(
            srv.base + "/api/design/settings",
            method="POST",
            token=token,
            payload={
                "promo_banner_id": photo_id,
                "hero_background_id": photo_id,
            },
        )
        assert status == 200, body
        assert portal.DESIGN_SETTINGS["promo_banner_id"] == photo_id
        assert portal.DESIGN_SETTINGS["hero_background_id"] == photo_id
        assert portal.DESIGN_SETTINGS["hero_video_id"] == video_id
    finally:
        portal.MEDIA_ASSETS.pop(photo_id, None)
        portal.MEDIA_ASSETS.pop(video_id, None)
        _restore(saved)
        srv.stop()


def test_delete_clears_only_the_placements_that_used_the_asset():
    srv = _ServerThread()
    srv.start()
    _warm(srv.base)
    token = "phins_test_place_delete"
    _admin(token)
    saved = _snapshot()
    shared_id = "media-place-shared"
    other_id = "media-place-other"
    try:
        _asset(shared_id, "video", "/media-files/media-place-shared/shared.mp4")
        _asset(other_id, "video", "/media-files/media-place-other/other.mp4")
        status, _ = _request(
            srv.base + "/api/design/settings",
            method="POST",
            token=token,
            payload={
                "hero_video_id": shared_id,
                "apply_chat_disclaimer_video_id": shared_id,
                "claims_chat_disclaimer_video_id": other_id,
            },
        )
        assert status == 200

        status, _ = _request(
            srv.base + f"/api/media/{shared_id}",
            method="DELETE",
            token=token,
        )
        assert status == 200
        assert portal.DESIGN_SETTINGS["hero_video_id"] == ""
        assert portal.DESIGN_SETTINGS["video_url"] == ""
        assert portal.DESIGN_SETTINGS["apply_chat_disclaimer_video_id"] == ""
        assert portal.DESIGN_SETTINGS["claims_chat_disclaimer_video_id"] == other_id

        status, public = _request(srv.base + "/api/design/settings")
        assert status == 200
        assert public["apply_chat_disclaimer_video_url"] == ""
        assert public["claims_chat_disclaimer_video_url"] == "/media-files/media-place-other/other.mp4"
    finally:
        portal.MEDIA_ASSETS.pop(shared_id, None)
        portal.MEDIA_ASSETS.pop(other_id, None)
        _restore(saved)
        srv.stop()


def test_canonical_platform_color_maps_legacy_defaults_only():
    assert portal.canonical_platform_color("#0d47a1", kind="primary") == "#060d1f"
    assert portal.canonical_platform_color("#1565C0", kind="primary") == "#060d1f"
    assert portal.canonical_platform_color("", kind="primary") == "#060d1f"
    assert portal.canonical_platform_color("#060d1f", kind="primary") == "#060d1f"
    assert portal.canonical_platform_color("#1a237e", kind="primary") == "#1a237e"
    assert portal.canonical_platform_color("#ff6b35", kind="accent") == "#e3bf6f"
    assert portal.canonical_platform_color("#42a5f5", kind="accent") == "#e3bf6f"
    assert portal.canonical_platform_color("#e3bf6f", kind="accent") == "#e3bf6f"
    assert portal.canonical_platform_color("#ff9800", kind="accent") == "#ff9800"


def test_public_palette_is_unified_without_rewriting_stored_colors():
    """Legacy blue/orange defaults are served as navy/gold. A read never
    rewrites DESIGN_SETTINGS, and a media-only save leaves colors alone.
    """
    srv = _ServerThread()
    srv.start()
    _warm(srv.base)
    token = "phins_test_place_palette"
    _admin(token)
    saved_primary = portal.DESIGN_SETTINGS.get("primary_color")
    saved_accent = portal.DESIGN_SETTINGS.get("accent_color")
    saved_contact = portal.DESIGN_SETTINGS.get("show_contact", True)
    try:
        portal.DESIGN_SETTINGS["primary_color"] = "#0d47a1"
        portal.DESIGN_SETTINGS["accent_color"] = "#ff6b35"
        status, public = _request(srv.base + "/api/design/settings")
        assert status == 200
        assert public["primary_color"] == "#060d1f"
        assert public["accent_color"] == "#e3bf6f"
        assert portal.DESIGN_SETTINGS["primary_color"] == "#0d47a1"
        assert portal.DESIGN_SETTINGS["accent_color"] == "#ff6b35"

        status, admin = _request(srv.base + "/api/design/settings", token=token)
        assert status == 200
        assert admin["primary_color"] == "#0d47a1"
        assert admin["accent_color"] == "#ff6b35"

        portal.DESIGN_SETTINGS["primary_color"] = "#1565c0"
        portal.DESIGN_SETTINGS["accent_color"] = "#42a5f5"
        status, public = _request(srv.base + "/api/design/settings")
        assert status == 200
        assert public["primary_color"] == "#060d1f"
        assert public["accent_color"] == "#e3bf6f"
        assert portal.DESIGN_SETTINGS["primary_color"] == "#1565c0"
        assert portal.DESIGN_SETTINGS["accent_color"] == "#42a5f5"

        portal.DESIGN_SETTINGS["primary_color"] = "#1a237e"
        portal.DESIGN_SETTINGS["accent_color"] = "#ff9800"
        status, public = _request(srv.base + "/api/design/settings")
        assert status == 200
        assert public["primary_color"] == "#1a237e"
        assert public["accent_color"] == "#ff9800"
        assert portal.DESIGN_SETTINGS["primary_color"] == "#1a237e"

        status, _ = _request(
            srv.base + "/api/design/settings",
            method="POST",
            token=token,
            payload={"show_contact": saved_contact},
        )
        assert status == 200
        assert portal.DESIGN_SETTINGS["primary_color"] == "#1a237e"
        assert portal.DESIGN_SETTINGS["accent_color"] == "#ff9800"

        status, body = _request(
            srv.base + "/api/design/settings",
            method="POST",
            token=token,
            payload={"primary_color": "#060d1f", "accent_color": "#e3bf6f"},
        )
        assert status == 200, body
        assert portal.DESIGN_SETTINGS["primary_color"] == "#060d1f"
        assert portal.DESIGN_SETTINGS["accent_color"] == "#e3bf6f"
        status, public = _request(srv.base + "/api/design/settings")
        assert public["primary_color"] == "#060d1f"
        assert public["accent_color"] == "#e3bf6f"
    finally:
        portal.DESIGN_SETTINGS["primary_color"] = saved_primary
        portal.DESIGN_SETTINGS["accent_color"] = saved_accent
        portal.DESIGN_SETTINGS["show_contact"] = saved_contact
        srv.stop()


def test_save_keeps_a_url_only_landing_hero():
    """A full save that posts an empty hero id must not erase a landing video
    that was stored only as video_url. Removing an asset id still clears the
    derived URL, and an explicit video_url clear still works.
    """
    srv = _ServerThread()
    srv.start()
    _warm(srv.base)
    token = "phins_test_place_legacy_hero"
    _admin(token)
    saved = _snapshot()
    chat_id = "media-place-legacy-chat"
    hero_id = "media-place-legacy-asset"
    try:
        _asset(chat_id, "video", "/media-files/media-place-legacy-chat/chat.mp4")
        _asset(hero_id, "video", "/media-files/media-place-legacy-asset/hero.mp4")
        portal.DESIGN_SETTINGS["hero_video_id"] = ""
        portal.DESIGN_SETTINGS["video_url"] = "https://cdn.example.com/live-hero.mp4"
        portal.DESIGN_SETTINGS["video_poster_id"] = ""
        portal.DESIGN_SETTINGS["video_poster"] = "https://cdn.example.com/live-poster.jpg"
        portal.DESIGN_SETTINGS["apply_chat_disclaimer_video_id"] = ""

        status, body = _request(
            srv.base + "/api/design/settings",
            method="POST",
            token=token,
            payload={
                "hero_video_id": "",
                "video_poster_id": "",
                "video_url": "",
                "video_poster": "",
                "apply_chat_disclaimer_video_id": chat_id,
            },
        )
        assert status == 200, body
        assert portal.DESIGN_SETTINGS["video_url"] == "https://cdn.example.com/live-hero.mp4"
        assert portal.DESIGN_SETTINGS["video_poster"] == "https://cdn.example.com/live-poster.jpg"
        assert portal.DESIGN_SETTINGS["hero_video_id"] == ""
        assert portal.DESIGN_SETTINGS["apply_chat_disclaimer_video_id"] == chat_id

        status, public = _request(srv.base + "/api/design/settings")
        assert status == 200
        assert public["video_url"] == "https://cdn.example.com/live-hero.mp4"
        assert public["video_poster"] == "https://cdn.example.com/live-poster.jpg"
        assert public["apply_chat_disclaimer_video_url"] == "/media-files/media-place-legacy-chat/chat.mp4"

        status, body = _request(
            srv.base + "/api/design/settings",
            method="POST",
            token=token,
            payload={"video_url": "", "video_poster": ""},
        )
        assert status == 200, body
        assert portal.DESIGN_SETTINGS["video_url"] == ""
        assert portal.DESIGN_SETTINGS["video_poster"] == ""

        portal.DESIGN_SETTINGS["hero_video_id"] = hero_id
        portal.DESIGN_SETTINGS["video_url"] = "/media-files/media-place-legacy-asset/hero.mp4"
        status, body = _request(
            srv.base + "/api/design/settings",
            method="POST",
            token=token,
            payload={
                "hero_video_id": "",
                "video_url": "https://cdn.example.com/ghost.mp4",
            },
        )
        assert status == 200, body
        assert portal.DESIGN_SETTINGS["hero_video_id"] == ""
        assert portal.DESIGN_SETTINGS["video_url"] == ""
    finally:
        portal.MEDIA_ASSETS.pop(chat_id, None)
        portal.MEDIA_ASSETS.pop(hero_id, None)
        _restore(saved)
        srv.stop()


def test_missing_placement_asset_resolves_to_an_empty_public_url():
    saved = _snapshot()
    try:
        portal.DESIGN_SETTINGS["apply_chat_disclaimer_video_id"] = "deleted-chat-video"
        portal.DESIGN_SETTINGS["claims_chat_disclaimer_video_id"] = "deleted-claim-video"
        urls = portal.public_placement_video_urls()
        assert urls["apply_chat_disclaimer_video_url"] == ""
        assert urls["claims_chat_disclaimer_video_url"] == ""
        assert urls["apply_disclosure_video_url"] == portal.get_media_asset_playback_url(
            str(saved.get("apply_disclosure_video_id") or "")
        )
    finally:
        _restore(saved)
