"""
Media processing API tests.

Focused coverage for:
- queueing subtitle jobs for video media assets
- handling provider completion callbacks
- downloading generated SRT tracks
- cleaning up subtitle jobs when media is deleted
"""

import json
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal


class ServerThread(threading.Thread):
    def __init__(self, port):
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


def _json_request(url, method="GET", payload=None, token=None, extra_headers=None):
    headers = dict(extra_headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    else:
        data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body) if body else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8")
        return exc.code, json.loads(body) if body else {}


def _download(url, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return resp.status, resp.read().decode("utf-8"), dict(resp.headers)


def _init_port(base):
    # Use an endpoint that still initializes per-port in-memory state.
    try:
        _json_request(base + "/api/media")
    except Exception:
        pass


def _inject_session(token, username="admin", role="admin", customer_id=""):
    portal.SESSIONS[token] = {
        "username": username,
        "role": role,
        "customer_id": customer_id,
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    if username not in portal.USERS:
        portal.USERS[username] = {"role": role, "username": username}


def test_media_subtitle_job_lifecycle_and_download():
    port = 8290
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_media_admin_token"
    _inject_session(token, "media_admin", "admin")

    try:
        status, create_resp = _json_request(
            base + "/api/media",
            method="POST",
            token=token,
            payload={
                "name": "demo-video.mp4",
                "type": "video",
                "format": "video/mp4",
                "size": 2048,
                "url": "https://cdn.example.com/demo-video.mp4",
                "duration": 18,
                "source": "url",
            },
        )
        assert status == 201
        asset = create_resp["asset"]
        asset_id = asset["id"]

        status, job_resp = _json_request(
            base + f"/api/media/{asset_id}/subtitles",
            method="POST",
            token=token,
            payload={"language": "en", "provider": "bridge"},
        )
        assert status == 202
        subtitle_job = job_resp["subtitle_job"]
        assert subtitle_job["status"] == "queued"
        assert subtitle_job["provider"] == "bridge"
        assert subtitle_job["callback_url"]

        callback_url = base + subtitle_job["callback_path"]
        callback_payload = {
            "job_id": subtitle_job["id"],
            "provider_job_id": subtitle_job["provider_job_id"],
            "status": "completed",
            "language": "en",
            "transcript": "Welcome to PHINS media processing subtitles for admins.",
            "segments": [
                {"start": 0, "end": 2.5, "text": "Welcome to PHINS"},
                {"start": 2.5, "end": 5.0, "text": "media processing subtitles"},
                {"start": 5.0, "end": 7.0, "text": "for admins."},
            ],
            "message": "Provider finished subtitle generation",
        }
        status, callback_resp = _json_request(
            callback_url,
            method="POST",
            payload=callback_payload,
            extra_headers={"X-Media-Webhook-Secret": portal.MEDIA_PROVIDER_WEBHOOK_SECRET},
        )
        assert status == 200
        assert callback_resp["job"]["status"] == "completed"
        track = callback_resp["track"]
        assert track["format"] == "srt"
        assert track["download_url"].endswith(".srt") is False  # route uses query param, not filename suffix

        status, asset_resp = _json_request(base + f"/api/media/{asset_id}", token=token)
        assert status == 200
        assert asset_resp["processing"]["subtitle_status"] == "completed"
        assert asset_resp["subtitles"][0]["format"] == "srt"

        status, download_body, headers = _download(base + track["download_url"], token=token)
        assert status == 200
        assert "00:00:00,000 --> 00:00:02,500" in download_body
        assert "Welcome to PHINS" in download_body
        assert headers["Content-Type"].startswith("application/x-subrip")
    finally:
        srv.stop()


def test_media_provider_callback_rejects_invalid_secret():
    port = 8291
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_media_admin_token_invalid"
    _inject_session(token, "media_admin_invalid", "admin")

    try:
        status, create_resp = _json_request(
            base + "/api/media",
            method="POST",
            token=token,
            payload={
                "name": "secured-video.mp4",
                "type": "video",
                "format": "video/mp4",
                "size": 1024,
                "url": "https://cdn.example.com/secured-video.mp4",
                "source": "url",
            },
        )
        assert status == 201
        asset_id = create_resp["asset"]["id"]

        status, job_resp = _json_request(
            base + f"/api/media/{asset_id}/subtitles",
            method="POST",
            token=token,
            payload={"language": "en"},
        )
        assert status == 202
        subtitle_job = job_resp["subtitle_job"]

        status, callback_resp = _json_request(
            base + subtitle_job["callback_url"],
            method="POST",
            payload={
                "job_id": subtitle_job["id"],
                "provider_job_id": subtitle_job["provider_job_id"],
                "status": "completed",
                "transcript": "This should be rejected.",
            },
            extra_headers={"X-Media-Webhook-Secret": "wrong-secret"},
        )
        assert status == 403
        assert "signature" in callback_resp["error"].lower()
    finally:
        srv.stop()


def test_delete_media_removes_processing_job_state():
    port = 8292
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_media_admin_token_delete"
    _inject_session(token, "media_admin_delete", "admin")

    try:
        status, create_resp = _json_request(
            base + "/api/media",
            method="POST",
            token=token,
            payload={
                "name": "delete-video.mp4",
                "type": "video",
                "format": "video/mp4",
                "size": 4096,
                "url": "https://cdn.example.com/delete-video.mp4",
                "source": "url",
            },
        )
        assert status == 201
        asset_id = create_resp["asset"]["id"]

        status, job_resp = _json_request(
            base + f"/api/media/{asset_id}/subtitles",
            method="POST",
            token=token,
            payload={"language": "en"},
        )
        assert status == 202
        job_id = job_resp["subtitle_job"]["id"]
        assert job_id in portal.MEDIA_PROCESSING_JOBS

        status, delete_resp = _json_request(
            base + f"/api/media/{asset_id}",
            method="DELETE",
            token=token,
        )
        assert status == 200
        assert delete_resp["id"] == asset_id
        assert job_id not in portal.MEDIA_PROCESSING_JOBS
    finally:
        srv.stop()
