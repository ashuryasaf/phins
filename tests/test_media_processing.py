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


def test_safe_ascii_filename_stem_reuses_shared_sanitizer_rules():
    assert portal.safe_ascii_filename_stem("  demo.. clip  ") == "demo_clip"
    assert portal.safe_ascii_filename_stem("x" * 120) == "x" * 80
    assert portal.safe_ascii_filename_stem("....", fallback="asset") == "asset"


def test_safe_download_filename_preserves_report_wrapper_behavior():
    assert portal.PortalHandler._safe_download_filename(" report..summary ") == "report__summary"
    assert portal.PortalHandler._safe_download_filename("__report__", fallback="fallback") == "report"
    assert portal.PortalHandler._safe_download_filename("...", fallback="fallback") == "fallback"


class _StubMediaGenerationService:
    def __init__(self):
        self.submissions = []
        self.polls = []
        self.downloads = []

    def submit_video_generation(self, **kwargs):
        self.submissions.append(kwargs)
        return {
            "provider": kwargs["provider"],
            "provider_job_id": "stub-provider-job-1",
            "status": "queued",
            "message": "Stub provider accepted video generation request.",
            "provider_state": {"operation_name": "operations/stub-provider-job-1"},
        }

    def poll_video_generation(self, **kwargs):
        self.polls.append(kwargs)
        return {
            "status": "completed",
            "message": "Stub provider completed the video.",
            "provider_job_id": kwargs["provider_job_id"],
            "download_url": "https://cdn.example.com/generated/stub-video.mp4",
            "duration": 8,
            "provider_state": {"done": True},
        }

    def download_generated_video(self, **kwargs):
        self.downloads.append(kwargs)
        return {
            "data_url": "data:video/mp4;base64,c3R1Yi12aWRlby1ieXRlcw==",
            "content_type": "video/mp4",
            "size": 16,
        }
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


def test_media_upload_persists_large_inline_payload_to_file_storage():
    port = 8295
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_media_large_upload_token"
    _inject_session(token, "media_admin_large", "admin")

    original_inline_limit = portal.MEDIA_INLINE_MAX_BYTES
    portal.MEDIA_INLINE_MAX_BYTES = 16
    try:
        status, create_resp = _json_request(
            base + "/api/media",
            method="POST",
            token=token,
            payload={
                "name": "uploaded-video.mp4",
                "type": "video",
                "format": "video/mp4",
                "data": "data:video/mp4;base64," + ("a" * 160),
                "source": "upload",
            },
        )
        assert status == 201, create_resp
        asset = create_resp["asset"]
        assert asset["stored_externally"] is True
        assert asset["file_path"]
        assert asset["url"].startswith("/uploaded-files/")
        assert asset["file_analysis"]["category"] == "video"
        assert asset["file_analysis"]["storage"] == "external_file"
    finally:
        portal.MEDIA_INLINE_MAX_BYTES = original_inline_limit
        srv.stop()


def test_binary_media_upload_endpoint_creates_valid_video_asset():
    port = 8296
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_media_binary_upload_token"
    _inject_session(token, "media_admin_binary", "admin")

    payload = b"\x00\x00\x00\x18ftypmp42" + (b"video-payload-" * 256)
    req = Request(
        base + "/api/media/upload",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "video/mp4",
            "X-Upload-Filename": "binary-upload.mp4",
        },
        method="POST",
    )

    try:
        with urlopen(req) as resp:
            assert resp.status == 201
            body = json.loads(resp.read().decode("utf-8"))
    finally:
        srv.stop()

    asset = body["asset"]
    assert asset["type"] == "video"
    assert asset["stored_externally"] is True
    assert asset["url"].startswith("/uploaded-files/")
    assert asset["file_analysis"]["category"] == "video"


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


def test_marketing_video_generation_job_creates_media_asset():
    port = 8293
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_media_admin_token_generation"
    _inject_session(token, "media_admin_generation", "admin")

    stub_service = _StubMediaGenerationService()
    original_factory = portal.get_media_generation_service
    portal.get_media_generation_service = lambda: stub_service

    try:
        portal.DESIGN_SETTINGS["marketing_sales_agent"] = {
            "latest_campaign": {
                "campaign": {
                    "campaign_id": "MKT-TEST-VIDEO",
                    "generated_at": datetime.now().isoformat(),
                    "ai_video_blueprints": [
                        {
                            "title": "Family Coverage Hero",
                            "format": "Short vertical explainer",
                            "voiceover_style": "Warm and trustworthy",
                            "storyboard": [
                                "A family reviews policy options on a tablet.",
                                "A quick claims support moment builds confidence.",
                            ],
                        }
                    ],
                },
                "integrity": {"verified": True, "algorithm": "hmac-sha256", "signature": "stub"},
                "assets_created": [],
            },
            "published_campaigns": [],
            "social_connections": {},
        }

        status, create_resp = _json_request(
            base + "/api/admin/media/video-jobs",
            method="POST",
            token=token,
            payload={
                "campaign_id": "MKT-TEST-VIDEO",
                "blueprint_index": 0,
                "provider": "gemini",
            },
        )
        assert status == 202
        job = create_resp["job"]
        assert job["job_kind"] == "video_generation"
        assert job["provider"] == "gemini"
        assert stub_service.submissions

        generated_asset_id = ""
        final_job = None
        for _ in range(20):
            time.sleep(0.15)
            status, jobs_resp = _json_request(
                base + "/api/admin/media/video-jobs?campaign_id=MKT-TEST-VIDEO",
                token=token,
            )
            assert status == 200
            final_job = jobs_resp["jobs"][0]
            generated_asset_id = final_job.get("generated_asset_id", "")
            if final_job.get("status") == "completed" and generated_asset_id:
                break

        assert final_job is not None
        assert final_job["status"] == "completed"
        assert generated_asset_id
        assert stub_service.polls
        assert stub_service.downloads

        status, asset_resp = _json_request(base + f"/api/media/{generated_asset_id}", token=token)
        assert status == 200
        assert asset_resp["type"] == "video"
        assert asset_resp["source"] == "ai_video_generation"
        assert asset_resp["metadata"]["campaign_id"] == "MKT-TEST-VIDEO"
        assert final_job["generated_asset_id"] == generated_asset_id
    finally:
        portal.get_media_generation_service = original_factory
        srv.stop()


def test_marketing_video_generation_batch_route_accepts_dashboard_payload():
    port = 8294
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_media_admin_token_batch"
    _inject_session(token, "media_admin_batch", "admin")

    stub_service = _StubMediaGenerationService()
    original_factory = portal.get_media_generation_service
    portal.get_media_generation_service = lambda: stub_service

    try:
        portal.DESIGN_SETTINGS["marketing_sales_agent"] = {
            "latest_campaign": {
                "campaign": {
                    "campaign_id": "MKT-TEST-BATCH",
                    "generated_at": datetime.now().isoformat(),
                    "ai_video_blueprints": [
                        {
                            "title": "Welcome Families",
                            "format": "Short vertical explainer",
                            "voiceover_style": "Warm and trustworthy",
                            "storyboard": [
                                "Open on a family reviewing benefits on a mobile phone.",
                                "Show advisor support and claims help in a fast montage.",
                            ],
                        },
                        {
                            "title": "Claims Walkthrough",
                            "format": "Interview + motion graphics",
                            "voiceover_style": "Clear and compliant",
                            "storyboard": [
                                "Explain documents needed for a claim.",
                                "Show payout checkpoints and policyholder follow-up.",
                            ],
                        },
                    ],
                },
                "integrity": {"verified": True, "algorithm": "hmac-sha256", "signature": "stub"},
                "assets_created": [],
            },
            "published_campaigns": [],
            "social_connections": {},
        }

        status, image_resp = _json_request(
            base + "/api/media",
            method="POST",
            token=token,
            payload={
                "name": "reference-frame.png",
                "type": "image",
                "format": "image/png",
                "size": 128,
                "data": "data:image/png;base64,c3R1Yi1pbWFnZS1ieXRlcw==",
                "source": "upload",
            },
        )
        assert status == 201
        reference_image_id = image_resp["asset"]["id"]

        status, batch_resp = _json_request(
            base + "/api/admin/media/video-jobs/batch",
            method="POST",
            token=token,
            payload={
                "campaign_id": "MKT-TEST-BATCH",
                "provider": "gemini",
                "provider_model": "veo-3-fast-preview",
                "reference_image_asset_id": reference_image_id,
                "poll_mode": "webhook",
                "auto_publish_to_hero": True,
                "pipeline_type": "claims_assistant",
                "prompt_override": "Keep the narration claims-focused and compliance-safe.",
            },
        )
        assert status == 202
        assert batch_resp["campaign_id"] == "MKT-TEST-BATCH"
        assert len(batch_resp["queued_jobs"]) == 2
        assert len(batch_resp["jobs"]) == 2
        assert stub_service.submissions

        queued_jobs = batch_resp["queued_jobs"]
        assert queued_jobs[0]["provider"] == "gemini"
        assert queued_jobs[0]["provider_model"] == "veo-3-fast-preview"
        assert queued_jobs[0]["callback_path"].startswith("/api/provider/media-processing/callback?")

        assert len(stub_service.submissions) == 2
        for submission in stub_service.submissions:
            assert submission["provider"] == "gemini"
            assert submission["model"] == "veo-3-fast-preview"
            assert submission["image_data_url"] == "data:image/png;base64,c3R1Yi1pbWFnZS1ieXRlcw=="
            assert "Keep the narration claims-focused and compliance-safe." in submission["prompt"]

        assert portal.MEDIA_PROCESSING_JOBS[queued_jobs[0]["id"]]["auto_publish_to_hero"] is True
        assert portal.MEDIA_PROCESSING_JOBS[queued_jobs[1]["id"]]["auto_publish_to_hero"] is False

        completed_jobs = []
        for _ in range(20):
            time.sleep(0.15)
            status, jobs_resp = _json_request(
                base + "/api/admin/media/video-jobs?campaign_id=MKT-TEST-BATCH",
                token=token,
            )
            assert status == 200
            completed_jobs = jobs_resp["jobs"]
            if len(completed_jobs) == 2 and all(job.get("status") == "completed" for job in completed_jobs):
                break

        assert len(completed_jobs) == 2
        assert all(job["status"] == "completed" for job in completed_jobs)
        assert all(job["generated_asset_id"] for job in completed_jobs)
        assert len(stub_service.polls) == 2
        assert len(stub_service.downloads) == 2
        assert portal.DESIGN_SETTINGS["hero_video_id"] in {
            job["generated_asset_id"] for job in completed_jobs
        }
    finally:
        portal.get_media_generation_service = original_factory
        srv.stop()
