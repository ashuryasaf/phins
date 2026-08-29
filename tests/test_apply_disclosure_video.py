"""Apply-form product disclosure video is versioned from Admin Media."""

from tests.test_media_processing import (
    ServerThread,
    _inject_session,
    _init_port,
    _json_request,
)
import web_portal.server as portal


def _start(port):
    srv = ServerThread(port)
    srv.start()
    import time
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)
    return srv, base


def test_public_design_settings_includes_apply_disclosure_fields():
    srv, base = _start(8317)
    try:
        status, resp = _json_request(base + "/api/design/settings")
        assert status == 200
        assert resp.get("apply_disclosure_video_url") == ""
        assert resp.get("apply_disclosure_version_label") == "light"
        assert "apply_disclosure_control_video_url" not in resp
        assert "apply_disclosure_control_video_id" not in resp
    finally:
        srv.stop()


def test_admin_can_assign_light_and_control_disclosure_videos():
    srv, base = _start(8318)
    token = "phins_test_apply_disclosure"
    _inject_session(token, "media_admin", "admin")
    live_id = "media-apply-disclosure-live"
    control_id = "media-apply-disclosure-control"
    original = {
        "apply_disclosure_video_id": portal.DESIGN_SETTINGS.get("apply_disclosure_video_id", ""),
        "apply_disclosure_control_video_id": portal.DESIGN_SETTINGS.get("apply_disclosure_control_video_id", ""),
        "apply_disclosure_version_label": portal.DESIGN_SETTINGS.get("apply_disclosure_version_label", "light"),
    }
    try:
        portal.MEDIA_ASSETS[live_id] = {
            "id": live_id, "name": "apply-light.mp4", "type": "video",
            "url": "/media-files/apply-light/disclosure",
            "data": "", "source": "upload",
        }
        portal.MEDIA_ASSETS[control_id] = {
            "id": control_id, "name": "apply-control.mp4", "type": "video",
            "url": "/media-files/apply-control/disclosure",
            "data": "", "source": "upload",
        }
        status, resp = _json_request(
            base + "/api/design/settings",
            method="POST",
            token=token,
            payload={
                "apply_disclosure_video_id": live_id,
                "apply_disclosure_control_video_id": control_id,
                "apply_disclosure_version_label": "light",
            },
        )
        assert status == 200
        assert portal.DESIGN_SETTINGS["apply_disclosure_video_id"] == live_id
        assert portal.DESIGN_SETTINGS["apply_disclosure_control_video_id"] == control_id

        status, public = _json_request(base + "/api/design/settings")
        assert status == 200
        assert public["apply_disclosure_video_url"] == "/media-files/apply-light/disclosure"
        assert public["apply_disclosure_version_label"] == "light"
        assert "apply-control" not in str(public.get("apply_disclosure_video_url"))
    finally:
        portal.MEDIA_ASSETS.pop(live_id, None)
        portal.MEDIA_ASSETS.pop(control_id, None)
        portal.DESIGN_SETTINGS.update(original)
        srv.stop()


def test_invalid_apply_disclosure_asset_is_rejected():
    srv, base = _start(8319)
    token = "phins_test_apply_disclosure_bad"
    _inject_session(token, "media_admin", "admin")
    original = portal.DESIGN_SETTINGS.get("apply_disclosure_video_id", "")
    try:
        portal.DESIGN_SETTINGS["apply_disclosure_video_id"] = ""
        status, resp = _json_request(
            base + "/api/design/settings",
            method="POST",
            token=token,
            payload={"apply_disclosure_video_id": "missing-asset"},
        )
        assert status == 400
        assert "apply_disclosure_video_id" in resp.get("invalid_refs", [])
        assert portal.DESIGN_SETTINGS["apply_disclosure_video_id"] == ""
    finally:
        portal.DESIGN_SETTINGS["apply_disclosure_video_id"] = original
        srv.stop()
