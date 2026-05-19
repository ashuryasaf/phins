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
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal
import services.media_generation_service as media_generation_service


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

    def supported_provider_config(self):
        return {
            "gemini": {"enabled": True, "label": "Gemini / Veo (stub)", "model": "veo-3-fast-preview", "models": ["veo-3-fast-preview"]},
            "kling": {"enabled": True, "label": "Kling (stub)", "models": ["kling-v2.6-pro"]},
        }

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


class _EventuallyReadyMediaGenerationService(_StubMediaGenerationService):
    def __init__(self):
        super().__init__()
        self._poll_count = 0

    def poll_video_generation(self, **kwargs):
        self.polls.append(kwargs)
        self._poll_count += 1
        if self._poll_count < 2:
            return {
                "status": "processing",
                "message": "Still rendering at provider.",
                "provider_job_id": kwargs["provider_job_id"],
                "provider_state": {"progress": self._poll_count},
            }
        return {
            "status": "completed",
            "message": "Provider completed the video on a later poll.",
            "provider_job_id": kwargs["provider_job_id"],
            "download_url": "https://cdn.example.com/generated/eventually-ready.mp4",
            "duration": 8,
            "provider_state": {"done": True},
        }


class _FakeUrlopenResponse:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None):
        self._body = body
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False
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

        queued_jobs = batch_resp["queued_jobs"]
        assert queued_jobs[0]["provider"] == "gemini"
        assert queued_jobs[0]["provider_model"] == "veo-3-fast-preview"
        assert queued_jobs[0]["callback_path"].startswith("/api/provider/media-processing/callback?")

        # Batch submissions are now drained by a serial worker (so a burst of
        # blueprints can no longer trip "HTTP Error 400" cascades).  Wait for
        # the worker to dispatch both jobs to the stub provider before checking
        # the submission payloads.
        for _ in range(80):
            if len(stub_service.submissions) >= 2:
                break
            time.sleep(0.1)
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

        status, final_jobs_resp = _json_request(
            base + "/api/admin/media/video-jobs?campaign_id=MKT-TEST-BATCH",
            token=token,
        )
        assert status == 200
        summary = final_jobs_resp.get("summary", {})
        assert summary["total"] == 2
        assert summary["completed"] == 2
        assert summary["active"] == 0
        assert summary["failed"] == 0
    finally:
        portal.get_media_generation_service = original_factory
        srv.stop()


def test_marketing_video_generation_repolls_until_completed():
    port = 8297
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_media_admin_token_repoll"
    _inject_session(token, "media_admin_repoll", "admin")

    stub_service = _EventuallyReadyMediaGenerationService()
    original_factory = portal.get_media_generation_service
    portal.get_media_generation_service = lambda: stub_service

    try:
        portal.DESIGN_SETTINGS["marketing_sales_agent"] = {
            "latest_campaign": {
                "campaign": {
                    "campaign_id": "MKT-TEST-REPOLL",
                    "generated_at": datetime.now().isoformat(),
                    "ai_video_blueprints": [
                        {
                            "title": "Claims Confidence",
                            "format": "Short vertical explainer",
                            "voiceover_style": "Clear and calm",
                            "storyboard": [
                                "Show a customer opening the claims portal.",
                                "Explain review and payout milestones.",
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
                "campaign_id": "MKT-TEST-REPOLL",
                "blueprint_index": 0,
                "provider": "kling",
                "poll_mode": "poll",
            },
        )
        assert status == 202

        final_job = None
        for _ in range(30):
            time.sleep(0.25)
            status, jobs_resp = _json_request(
                base + "/api/admin/media/video-jobs?campaign_id=MKT-TEST-REPOLL",
                token=token,
            )
            assert status == 200
            final_job = jobs_resp["jobs"][0]
            if final_job.get("status") == "completed":
                break

        assert final_job is not None
        assert final_job["status"] == "completed"
        assert final_job["generated_asset_id"]
        assert final_job["download_url"] == f"/api/media/{final_job['generated_asset_id']}/download"
        assert len(stub_service.polls) >= 2
    finally:
        portal.get_media_generation_service = original_factory
        srv.stop()


def test_marketing_generate_route_persists_latest_campaign_for_video_agents():
    port = 8295
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_media_admin_token_generate_persist"
    _inject_session(token, "media_admin_generate", "admin")

    try:
        status, generate_resp = _json_request(
            base + "/api/admin/marketing-sales-agent?vertical=insurance&objective=growth&persona=families&region=global&budget_tier=balanced&networks=linkedin,x",
            token=token,
        )
        assert status == 200
        assert generate_resp["success"] is True
        assert "generated" in generate_resp
        assert "latest_campaign" in generate_resp

        generated_campaign_id = str(generate_resp["generated"]["campaign"]["campaign_id"])
        latest_campaign_id = str(generate_resp["latest_campaign"]["campaign"]["campaign_id"])
        assert latest_campaign_id == generated_campaign_id
        assert generate_resp["latest_campaign"]["lifecycle_status"] == "generated"

        status, latest_resp = _json_request(base + "/api/admin/marketing-sales-agent/latest", token=token)
        assert status == 200
        assert latest_resp["latest_campaign"]["campaign"]["campaign_id"] == generated_campaign_id
        assert latest_resp["latest_campaign"]["integrity"]["verified"] is True

        assert "video_job_summary" in latest_resp
        summary = latest_resp["video_job_summary"]
        assert summary["total"] == 0
        assert summary["completed"] == 0
        assert summary["active"] == 0
        assert summary["failed"] == 0
    finally:
        srv.stop()


def test_marketing_video_provider_capabilities_endpoint():
    port = 8296
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_media_admin_token_provider_caps"
    _inject_session(token, "media_admin_caps", "admin")

    try:
        status, caps_resp = _json_request(base + "/api/admin/media/video-providers", token=token)
        assert status == 200
        assert caps_resp["success"] is True
        capabilities = caps_resp["capabilities"]
        assert "providers" in capabilities
        assert "default_provider" in capabilities
        assert "gemini" in capabilities["providers"]
        assert "kling" in capabilities["providers"]
        assert isinstance(capabilities["providers"]["gemini"]["models"], list)
        assert isinstance(capabilities["providers"]["kling"]["models"], list)
    finally:
        srv.stop()


def test_kling_provider_enabled_with_access_secret_credentials(monkeypatch):
    monkeypatch.setenv("KLING_API_KEY", "")
    monkeypatch.setenv("KLING_ACCESS_KEY", "access-key-1")
    monkeypatch.setenv("KLING_SECRET_KEY", "secret-key-1")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    service = media_generation_service.MediaGenerationService()
    capabilities = service.supported_provider_config()

    assert capabilities["kling"]["enabled"] is True


def test_kling_jwt_from_access_secret_is_hs256_and_contains_issuer():
    token = media_generation_service.MediaGenerationService._build_kling_access_secret_jwt(
        access_key="AK-123",
        secret_key="SK-123",
        now_epoch_seconds=1_700_000_000,
        ttl_seconds=1800,
    )

    header_b64, payload_b64, signature_b64 = token.split(".")
    assert header_b64
    assert payload_b64
    assert signature_b64

    import base64 as _base64

    decoded_header = json.loads(_base64.urlsafe_b64decode(header_b64 + "==").decode("utf-8"))
    decoded_payload = json.loads(_base64.urlsafe_b64decode(payload_b64 + "==").decode("utf-8"))

    assert decoded_header["alg"] == "HS256"
    assert decoded_header["typ"] == "JWT"
    assert decoded_payload["iss"] == "AK-123"
    assert decoded_payload["exp"] == 1_700_001_800
    assert decoded_payload["nbf"] == 1_699_999_995


def test_generated_video_download_route_serves_inline_media_payload():
    port = 8298
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_media_admin_token_download"
    _inject_session(token, "media_admin_download", "admin")

    try:
        asset_id = "media-generated-download"
        portal.MEDIA_ASSETS[asset_id] = {
            "id": asset_id,
            "name": "kling-demo.mp4",
            "type": "video",
            "format": "video/mp4",
            "size": 12,
            "url": "",
            "data": "data:video/mp4;base64,cGhpbnMtdmlkZW8=",
            "source": "ai_video_generation",
            "uploaded_at": datetime.now().isoformat(),
            "uploaded_by": "media_admin_download",
        }

        req = Request(base + f"/api/media/{asset_id}/download", headers={"Authorization": f"Bearer {token}"})
        with urlopen(req) as resp:
            body = resp.read()
            headers = dict(resp.headers)

        assert resp.status == 200
        assert body == b"phins-video"
        assert headers["Content-Type"].startswith("video/mp4")
        assert 'filename="kling-demo_mp4.mp4"' in headers["Content-Disposition"]
    finally:
        srv.stop()


def test_kling_submit_uses_documented_base_url_callback_and_mode(monkeypatch):
    monkeypatch.setenv("KLING_API_KEY", "api-key-1")
    monkeypatch.delenv("KLING_ACCESS_KEY", raising=False)
    monkeypatch.delenv("KLING_SECRET_KEY", raising=False)
    monkeypatch.delenv("KLING_API_BASE_URL", raising=False)

    captured = {}

    def _fake_urlopen(request, timeout=0, allowed_schemes=()):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeUrlopenResponse(json.dumps({"task_id": "task-123"}).encode("utf-8"))

    monkeypatch.setattr(media_generation_service, "validated_urlopen", _fake_urlopen)

    service = media_generation_service.MediaGenerationService()
    result = service.submit_video_generation(
        provider="kling",
        prompt="A calm claims explainer video for policyholders",
        title="Claims explainer",
        model="kling-v2.6-pro",
        aspect_ratio="9:16",
        duration_seconds=8,
        callback_url="https://phins.example.com/api/provider/media-processing/callback?job_id=1&token=abc",
    )

    assert result["provider"] == "kling"
    assert result["provider_job_id"] == "task-123"
    assert captured["url"] == "https://api.klingapi.com/v1/videos/text2video"
    assert captured["headers"]["Authorization"] == "Bearer api-key-1"
    assert captured["body"]["model"] == "kling-v2.6-pro"
    assert captured["body"]["mode"] == "professional"
    assert captured["body"]["duration"] == 10
    assert captured["body"]["callBackUrl"].startswith("https://phins.example.com/api/provider/media-processing/callback")


def test_kling_poll_handles_official_api_response_formats(monkeypatch):
    """Verify polling handles the official Kling API response shapes including
    flat task_id/status/url at root, nested data.status, and the 'succeed'
    status value used by some Kling API versions."""
    monkeypatch.setenv("KLING_API_KEY", "api-key-poll-test")
    monkeypatch.delenv("KLING_ACCESS_KEY", raising=False)
    monkeypatch.delenv("KLING_SECRET_KEY", raising=False)

    service = media_generation_service.MediaGenerationService()

    flat_completed = {
        "task_id": "task-flat-1",
        "status": "completed",
        "url": "https://cdn.klingapi.com/videos/flat-1.mp4",
        "format": "mp4",
        "metadata": {"duration": 5},
    }

    def _urlopen_flat(request, timeout=0, allowed_schemes=()):
        return _FakeUrlopenResponse(json.dumps(flat_completed).encode("utf-8"))

    monkeypatch.setattr(media_generation_service, "validated_urlopen", _urlopen_flat)
    result = service.poll_video_generation(
        provider="kling",
        provider_job_id="task-flat-1",
        provider_state={"status_url": "https://api.klingapi.com/v1/videos/task-flat-1"},
    )
    assert result["status"] == "completed"
    assert result["download_url"] == "https://cdn.klingapi.com/videos/flat-1.mp4"

    nested_succeed = {
        "data": {
            "task_id": "task-nested-1",
            "task_status": "succeed",
            "works": [
                {"resource": {"resource": "https://cdn.klingapi.com/videos/nested-1.mp4"}}
            ],
        }
    }

    def _urlopen_nested(request, timeout=0, allowed_schemes=()):
        return _FakeUrlopenResponse(json.dumps(nested_succeed).encode("utf-8"))

    monkeypatch.setattr(media_generation_service, "validated_urlopen", _urlopen_nested)
    result = service.poll_video_generation(
        provider="kling",
        provider_job_id="task-nested-1",
        provider_state={"status_url": "https://api.klingapi.com/v1/videos/task-nested-1"},
    )
    assert result["status"] == "completed"
    assert result["download_url"] == "https://cdn.klingapi.com/videos/nested-1.mp4"

    processing_body = {"task_id": "task-proc-1", "status": "processing"}

    def _urlopen_processing(request, timeout=0, allowed_schemes=()):
        return _FakeUrlopenResponse(json.dumps(processing_body).encode("utf-8"))

    monkeypatch.setattr(media_generation_service, "validated_urlopen", _urlopen_processing)
    result = service.poll_video_generation(
        provider="kling",
        provider_job_id="task-proc-1",
        provider_state={"status_url": "https://api.klingapi.com/v1/videos/task-proc-1"},
    )
    assert result["status"] == "processing"

    failed_body = {
        "task_id": "task-fail-1",
        "status": "failed",
        "error": {"code": 1001, "message": "Content policy violation"},
    }

    def _urlopen_failed(request, timeout=0, allowed_schemes=()):
        return _FakeUrlopenResponse(json.dumps(failed_body).encode("utf-8"))

    monkeypatch.setattr(media_generation_service, "validated_urlopen", _urlopen_failed)
    result = service.poll_video_generation(
        provider="kling",
        provider_job_id="task-fail-1",
        provider_state={"status_url": "https://api.klingapi.com/v1/videos/task-fail-1"},
    )
    assert result["status"] == "failed"
    assert "Content policy violation" in result["error"]


def test_kling_submit_parses_root_level_task_id(monkeypatch):
    """Verify submit handles task_id at root level (official Kling API format)."""
    monkeypatch.setenv("KLING_API_KEY", "api-key-root-tid")
    monkeypatch.delenv("KLING_ACCESS_KEY", raising=False)
    monkeypatch.delenv("KLING_SECRET_KEY", raising=False)

    root_response = {"task_id": "root-task-001"}

    def _fake_urlopen(request, timeout=0, allowed_schemes=()):
        return _FakeUrlopenResponse(json.dumps(root_response).encode("utf-8"))

    monkeypatch.setattr(media_generation_service, "validated_urlopen", _fake_urlopen)
    service = media_generation_service.MediaGenerationService()
    result = service.submit_video_generation(
        provider="kling",
        prompt="Test video",
        title="Root task_id test",
    )
    assert result["provider_job_id"] == "root-task-001"

    nested_response = {"data": {"task_id": "nested-task-002"}}

    def _fake_urlopen_nested(request, timeout=0, allowed_schemes=()):
        return _FakeUrlopenResponse(json.dumps(nested_response).encode("utf-8"))

    monkeypatch.setattr(media_generation_service, "validated_urlopen", _fake_urlopen_nested)
    service2 = media_generation_service.MediaGenerationService()
    result2 = service2.submit_video_generation(
        provider="kling",
        prompt="Test video nested",
        title="Nested task_id test",
    )
    assert result2["provider_job_id"] == "nested-task-002"


# ============ EvoLink Kling v3 routing & error surfacing ============


def test_kling_submit_routes_kling_v3_through_evolink_unified_endpoint(monkeypatch):
    """kling-v3-* models should auto-route to EvoLink's POST /v1/videos/generations.

    Per https://evolink.ai/blog/how-to-access-kling-ai-api-complete-tutorial
    the unified endpoint accepts ``image_start`` (not ``image``) for the
    image-to-video flow and the legacy ``mode`` field is dropped.
    """
    monkeypatch.setenv("KLING_API_KEY", "evolink-bearer-1")
    monkeypatch.delenv("KLING_ACCESS_KEY", raising=False)
    monkeypatch.delenv("KLING_SECRET_KEY", raising=False)
    monkeypatch.delenv("KLING_API_BASE_URL", raising=False)
    monkeypatch.delenv("KLING_TEXT_TO_VIDEO_PATH", raising=False)
    monkeypatch.delenv("KLING_IMAGE_TO_VIDEO_PATH", raising=False)
    monkeypatch.delenv("KLING_API_PROFILE", raising=False)

    captured = {}

    def _fake_urlopen(request, timeout=0, allowed_schemes=()):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeUrlopenResponse(json.dumps({"task_id": "evolink-task-7"}).encode("utf-8"))

    monkeypatch.setattr(media_generation_service, "validated_urlopen", _fake_urlopen)

    service = media_generation_service.MediaGenerationService()
    result = service.submit_video_generation(
        provider="kling",
        prompt="A golden retriever running through a sunlit meadow",
        title="Kling 3 EvoLink T2V",
        model="kling-v3-text-to-video",
        aspect_ratio="16:9",
        duration_seconds=5,
        image_data_url="https://example.com/portrait.jpg",
    )

    assert result["provider_job_id"] == "evolink-task-7"
    assert captured["url"] == "https://api.evolink.ai/v1/videos/generations"
    assert captured["body"]["model"] == "kling-v3-text-to-video"
    # EvoLink uses image_start, not the legacy "image" key.
    assert captured["body"]["image_start"] == "https://example.com/portrait.jpg"
    assert "image" not in captured["body"]
    # The legacy "mode" field is not part of EvoLink's unified spec.
    assert "mode" not in captured["body"]
    # The status_url returned for later polling should target /v1/tasks/{id}.
    status_url = result["provider_state"]["status_url"]
    assert status_url == "https://api.evolink.ai/v1/tasks/evolink-task-7"


def test_kling_submit_clamps_prompt_to_documented_2500_char_limit(monkeypatch):
    """Oversized prompts should be truncated locally, not produce HTTP 400."""
    monkeypatch.setenv("KLING_API_KEY", "clamp-prompt-key")
    monkeypatch.delenv("KLING_ACCESS_KEY", raising=False)
    monkeypatch.delenv("KLING_SECRET_KEY", raising=False)
    monkeypatch.delenv("KLING_API_PROFILE", raising=False)

    captured = {}

    def _fake_urlopen(request, timeout=0, allowed_schemes=()):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeUrlopenResponse(json.dumps({"task_id": "clamp-task"}).encode("utf-8"))

    monkeypatch.setattr(media_generation_service, "validated_urlopen", _fake_urlopen)

    over_limit_prompt = "x" * 3000
    service = media_generation_service.MediaGenerationService()
    service.submit_video_generation(
        provider="kling",
        prompt=over_limit_prompt,
        title="Clamp test",
        model="kling-v2.6-pro",
    )

    assert len(captured["body"]["prompt"]) <= 2500
    assert captured["body"]["prompt"].endswith("...")


def test_batch_video_endpoint_isolates_per_job_submit_failures(monkeypatch):
    """A provider HTTP 400 for one blueprint must not fail the whole batch.

    Previously the batch endpoint submitted blueprints synchronously inside
    the HTTP request thread, so a single provider rejection surfaced in the
    UI as ``Batch generation failed: HTTP Error 400: Bad Request``.  After
    the serial-submission refactor, queued jobs are dispatched by a background
    worker and per-job errors land on the job record.
    """
    from services.media_generation_service import MediaGenerationError

    port = 8324
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_media_admin_token_batch_isolation"
    _inject_session(token, "media_admin_batch_isolation", "admin")

    class _PartialFailureStub(_StubMediaGenerationService):
        def __init__(self):
            super().__init__()
            self._submit_count = 0

        def submit_video_generation(self, **kwargs):
            self._submit_count += 1
            if self._submit_count == 1:
                # First blueprint hits a "bad request" — exactly the kind of
                # provider rejection that used to break the whole batch.
                raise MediaGenerationError(
                    "Kling submit failed with HTTP 400: prompt missing required subject"
                )
            return super().submit_video_generation(**kwargs)

    stub_service = _PartialFailureStub()
    original_factory = portal.get_media_generation_service
    portal.get_media_generation_service = lambda: stub_service

    try:
        portal.DESIGN_SETTINGS["marketing_sales_agent"] = {
            "latest_campaign": {
                "campaign": {
                    "campaign_id": "MKT-BATCH-ISOLATION",
                    "generated_at": datetime.now().isoformat(),
                    "ai_video_blueprints": [
                        {
                            "title": "First blueprint",
                            "format": "Short vertical explainer",
                            "voiceover_style": "Warm",
                            "storyboard": ["Open scene.", "Closing scene."],
                        },
                        {
                            "title": "Second blueprint",
                            "format": "Interview + motion graphics",
                            "voiceover_style": "Authoritative",
                            "storyboard": ["Intro.", "Outro."],
                        },
                    ],
                },
                "integrity": {"verified": True, "algorithm": "hmac-sha256", "signature": "stub"},
                "assets_created": [],
            },
            "published_campaigns": [],
            "social_connections": {},
        }

        status, batch_resp = _json_request(
            base + "/api/admin/media/video-jobs/batch",
            method="POST",
            token=token,
            payload={
                "campaign_id": "MKT-BATCH-ISOLATION",
                "provider": "kling",
                "provider_model": "kling-v2.6-pro",
                "poll_mode": "poll",
            },
        )

        # The HTTP response remains 202 even though one blueprint will fail
        # at the provider — this is the key contract change.
        assert status == 202
        assert len(batch_resp["queued_jobs"]) == 2
        assert batch_resp["submission_queue"]["sequential"] is True

        for _ in range(80):
            if stub_service._submit_count >= 2:
                break
            time.sleep(0.1)
        assert stub_service._submit_count == 2

        job_ids = [job["id"] for job in batch_resp["queued_jobs"]]
        first_job = portal.MEDIA_PROCESSING_JOBS[job_ids[0]]
        second_job = portal.MEDIA_PROCESSING_JOBS[job_ids[1]]

        assert first_job["status"] == "failed"
        assert "HTTP 400" in str(first_job.get("error") or "")
        # Second job was still dispatched to the provider successfully.
        assert second_job["status"] in {"queued", "processing", "completed"}
        assert second_job.get("provider_job_id")
    finally:
        portal.get_media_generation_service = original_factory
        srv.stop()


def test_kling_submit_surfaces_provider_error_body_on_http_400(monkeypatch):
    """HTTPError bodies should be parsed so the UI sees an actionable message."""
    monkeypatch.setenv("KLING_API_KEY", "surface-error-key")
    monkeypatch.delenv("KLING_ACCESS_KEY", raising=False)
    monkeypatch.delenv("KLING_SECRET_KEY", raising=False)

    from urllib.error import HTTPError as _HTTPError
    from io import BytesIO as _BytesIO

    error_body = json.dumps({
        "error": {"message": "Prompt must include at least one subject."},
    }).encode("utf-8")

    def _fake_urlopen(request, timeout=0, allowed_schemes=()):
        raise _HTTPError(
            request.full_url,
            400,
            "Bad Request",
            {"Content-Type": "application/json"},
            _BytesIO(error_body),
        )

    monkeypatch.setattr(media_generation_service, "validated_urlopen", _fake_urlopen)

    service = media_generation_service.MediaGenerationService()
    try:
        service.submit_video_generation(
            provider="kling",
            prompt="Test surfacing",
            title="Surface error",
            model="kling-v2.6-pro",
        )
    except media_generation_service.MediaGenerationError as exc:
        message = str(exc)
    else:
        raise AssertionError("Expected MediaGenerationError for HTTP 400 response")

    assert "HTTP 400" in message
    assert "Prompt must include at least one subject." in message


# ============ NEW TESTS: media controller optimizations ============


def test_media_create_validation_rejects_missing_name():
    port = 8298
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)
    token = "phins_test_validation_name"
    _inject_session(token, "val_admin", "admin")

    try:
        status, resp = _json_request(
            base + "/api/media",
            method="POST",
            token=token,
            payload={"type": "image", "url": "https://example.com/img.png"},
        )
        assert status == 400
        assert "name" in resp.get("error", "").lower()
    finally:
        srv.stop()


def test_media_create_validation_rejects_invalid_type():
    port = 8299
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)
    token = "phins_test_validation_type"
    _inject_session(token, "val_admin2", "admin")

    try:
        status, resp = _json_request(
            base + "/api/media",
            method="POST",
            token=token,
            payload={"name": "test.bin", "type": "executable", "url": "https://example.com/a.bin"},
        )
        assert status == 400
        assert "type" in resp.get("error", "").lower()
    finally:
        srv.stop()


def test_media_create_validation_rejects_missing_data_and_url():
    port = 8300
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)
    token = "phins_test_validation_data"
    _inject_session(token, "val_admin3", "admin")

    try:
        status, resp = _json_request(
            base + "/api/media",
            method="POST",
            token=token,
            payload={"name": "empty.png", "type": "image"},
        )
        assert status == 400
        assert "data" in resp.get("error", "").lower() or "url" in resp.get("error", "").lower()
    finally:
        srv.stop()


def test_media_create_returns_checksum_for_data_upload():
    port = 8301
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)
    token = "phins_test_checksum"
    _inject_session(token, "cksum_admin", "admin")

    try:
        status, resp = _json_request(
            base + "/api/media",
            method="POST",
            token=token,
            payload={
                "name": "checksum-test.png",
                "type": "image",
                "format": "image/png",
                "data": "data:image/png;base64,c3R1Yi1pbWFnZS1ieXRlcw==",
                "source": "upload",
            },
        )
        assert status == 201
        asset = resp["asset"]
        assert asset["checksum"], "Checksum must be a non-empty string"
        assert len(asset["checksum"]) == 64, "SHA-256 hex digest is 64 chars"

        status2, single = _json_request(
            base + f"/api/media/{asset['id']}",
            token=token,
        )
        assert status2 == 200
        assert single["checksum"] == asset["checksum"]
    finally:
        srv.stop()


def test_media_delete_cleans_up_orphaned_processing_jobs():
    port = 8302
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)
    token = "phins_test_delete_cleanup"
    _inject_session(token, "del_admin", "admin")

    try:
        status, create_resp = _json_request(
            base + "/api/media",
            method="POST",
            token=token,
            payload={
                "name": "delete-test-video.mp4",
                "type": "video",
                "format": "video/mp4",
                "data": "data:video/mp4;base64,dmlkZW8tYnl0ZXM=",
                "source": "upload",
            },
        )
        assert status == 201
        asset_id = create_resp["asset"]["id"]

        orphan_job_id = f"orphan-job-{asset_id}"
        portal.MEDIA_PROCESSING_JOBS[orphan_job_id] = {
            "id": orphan_job_id,
            "job_kind": "video_generation",
            "asset_id": asset_id,
            "status": "completed",
        }
        assert orphan_job_id in portal.MEDIA_PROCESSING_JOBS

        status, del_resp = _json_request(
            base + f"/api/media/{asset_id}",
            method="DELETE",
            token=token,
        )
        assert status == 200
        assert del_resp["success"] is True

        assert orphan_job_id not in portal.MEDIA_PROCESSING_JOBS
        assert asset_id not in portal.MEDIA_ASSETS
    finally:
        srv.stop()


def test_media_delete_removes_disk_file():
    import tempfile
    import os

    port = 8303
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)
    token = "phins_test_delete_disk"
    _inject_session(token, "disk_admin", "admin")

    try:
        asset_id = f"media-disktest{int(time.time())}"
        disk_dir = tempfile.mkdtemp(prefix="phins_media_test_")
        file_path = os.path.join(disk_dir, f"{asset_id}-test.mp4")
        with open(file_path, "wb") as f:
            f.write(b"fake-video-bytes")
        assert os.path.exists(file_path)

        portal.MEDIA_ASSETS[asset_id] = {
            "id": asset_id,
            "name": "disk-test.mp4",
            "type": "video",
            "format": "video/mp4",
            "size": 16,
            "url": f"/media-files/{asset_id}/test",
            "data": "",
            "file_path": file_path,
            "stored_externally": True,
            "source": "upload",
            "uploaded_at": datetime.now().isoformat(),
            "uploaded_by": "disk_admin",
        }

        status, del_resp = _json_request(
            base + f"/api/media/{asset_id}",
            method="DELETE",
            token=token,
        )
        assert status == 200
        assert not os.path.exists(file_path), "On-disk file should be removed on delete"
        assert asset_id not in portal.MEDIA_ASSETS
    finally:
        srv.stop()


def test_media_serialize_excludes_file_path():
    asset = {
        "id": "test-ser-001",
        "name": "serialized.mp4",
        "type": "video",
        "file_path": "/tmp/secret/path/file.mp4",
        "stored_externally": True,
        "checksum": "abc123",
    }
    serialized = portal.serialize_media_asset(asset)
    assert "file_path" not in serialized, "file_path must not leak in API responses"
    assert serialized["checksum"] == "abc123"


def test_growth_bridge_latest_campaign_includes_video_job_summary():
    port = 8304
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)
    token = "phins_test_growth_bridge"
    _inject_session(token, "bridge_admin", "admin")

    try:
        portal.DESIGN_SETTINGS["marketing_sales_agent"] = {
            "latest_campaign": {
                "campaign": {
                    "campaign_id": "MKT-BRIDGE-TEST",
                    "generated_at": datetime.now().isoformat(),
                    "scope": {"vertical": "insurance", "objective": "growth"},
                    "ai_video_blueprints": [
                        {"title": "Test BP", "storyboard": ["Scene 1"]},
                    ],
                    "social_network_plan": [],
                    "sales_playbooks": [],
                },
                "integrity": {"verified": True, "algorithm": "hmac-sha256", "signature": "stub"},
                "assets_created": [],
            },
        }

        portal.MEDIA_PROCESSING_JOBS["vj-bridge-1"] = {
            "id": "vj-bridge-1",
            "job_kind": "video_generation",
            "campaign_id": "MKT-BRIDGE-TEST",
            "status": "completed",
        }
        portal.MEDIA_PROCESSING_JOBS["vj-bridge-2"] = {
            "id": "vj-bridge-2",
            "job_kind": "video_generation",
            "campaign_id": "MKT-BRIDGE-TEST",
            "status": "queued",
        }

        status, resp = _json_request(
            base + "/api/admin/marketing-sales-agent/latest",
            token=token,
        )
        assert status == 200
        assert resp["success"] is True
        summary = resp.get("video_job_summary")
        assert summary is not None, "Response must include video_job_summary"
        assert summary["total"] >= 2
        assert summary["completed"] >= 1
        assert summary["active"] >= 1
    finally:
        for jid in ["vj-bridge-1", "vj-bridge-2"]:
            portal.MEDIA_PROCESSING_JOBS.pop(jid, None)
        srv.stop()


def test_compute_media_checksum_produces_hex_digest():
    checksum = portal.compute_media_checksum(b"hello world")
    assert isinstance(checksum, str)
    assert len(checksum) == 64


def test_multipart_media_upload_stores_file_on_disk():
    import os

    port = 8305
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)
    token = "phins_test_multipart_upload"
    _inject_session(token, "mp_admin", "admin")

    try:
        import io
        boundary = b"----TestBoundary12345"
        video_bytes = b"fake-heavy-video-content-" * 100
        body = io.BytesIO()
        body.write(b"------TestBoundary12345\r\n")
        body.write(b'Content-Disposition: form-data; name="file"; filename="heavy.mp4"\r\n')
        body.write(b"Content-Type: video/mp4\r\n\r\n")
        body.write(video_bytes)
        body.write(b"\r\n------TestBoundary12345\r\n")
        body.write(b'Content-Disposition: form-data; name="name"\r\n\r\n')
        body.write(b"heavy-test-video.mp4")
        body.write(b"\r\n------TestBoundary12345\r\n")
        body.write(b'Content-Disposition: form-data; name="type"\r\n\r\n')
        body.write(b"video")
        body.write(b"\r\n------TestBoundary12345\r\n")
        body.write(b'Content-Disposition: form-data; name="source"\r\n\r\n')
        body.write(b"upload")
        body.write(b"\r\n------TestBoundary12345--\r\n")
        body_data = body.getvalue()

        req = Request(
            base + "/api/media/upload",
            data=body_data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": f"multipart/form-data; boundary=----TestBoundary12345",
            },
            method="POST",
        )
        with urlopen(req) as resp:
            status = resp.status
            result = json.loads(resp.read().decode("utf-8"))

        assert status == 201, f"Expected 201, got {status}: {result}"
        asset = result["asset"]
        assert asset["type"] == "video"
        assert asset["name"] == "heavy-test-video.mp4"
        assert asset["stored_externally"] is True
        assert asset["checksum"]
        assert len(asset["checksum"]) == 64
        assert asset["size"] == len(video_bytes)
        assert "file_path" not in asset, "file_path must not leak in API"

        asset_id = asset["id"]
        assert asset_id in portal.MEDIA_ASSETS
        raw = portal.MEDIA_ASSETS[asset_id]
        assert raw.get("file_path")
        assert os.path.isfile(raw["file_path"])

        status2, single = _json_request(base + f"/api/media/{asset_id}", token=token)
        assert status2 == 200
        assert single["checksum"] == asset["checksum"]

        _json_request(base + f"/api/media/{asset_id}", method="DELETE", token=token)
        assert asset_id not in portal.MEDIA_ASSETS
    finally:
        srv.stop()


def test_media_upload_route_exempt_from_default_request_size_limit():
    """The media upload paths should use MAX_MEDIA_UPLOAD_SIZE when set,
    not the default MAX_REQUEST_SIZE."""
    assert portal.MAX_REQUEST_SIZE >= 10 * 1024 * 1024
    assert portal.MAX_MEDIA_UPLOAD_SIZE == 0, (
        "Default MAX_MEDIA_UPLOAD_SIZE should be 0 (unlimited) unless env overrides"
    )


def test_media_download_streams_disk_files():
    import os
    import tempfile

    port = 8306
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)
    token = "phins_test_stream_dl"
    _inject_session(token, "stream_admin", "admin")

    try:
        asset_id = f"media-stream{int(time.time())}"
        disk_dir = tempfile.mkdtemp(prefix="phins_stream_test_")
        file_path = os.path.join(disk_dir, f"{asset_id}-testvid.mp4")
        content = b"streaming-test-" * 200
        with open(file_path, "wb") as f:
            f.write(content)

        portal.MEDIA_ASSETS[asset_id] = {
            "id": asset_id,
            "name": "stream-test.mp4",
            "type": "video",
            "format": "video/mp4",
            "size": len(content),
            "url": f"/media-files/{asset_id}/testvid",
            "data": "",
            "file_path": file_path,
            "stored_externally": True,
            "source": "upload",
            "uploaded_at": datetime.now().isoformat(),
            "uploaded_by": "stream_admin",
        }

        status, downloaded_data, headers = _download(
            base + f"/api/media/{asset_id}/download",
            token=token,
        )
        assert status == 200
        assert len(downloaded_data.encode("latin-1")) == len(content)

        portal.MEDIA_ASSETS.pop(asset_id, None)
        os.remove(file_path)
    finally:
        srv.stop()


def test_video_generation_service_supports_stream_to_path():
    """Verify download_generated_video accepts stream_to_path parameter."""
    import inspect
    from services.media_generation_service import MediaGenerationService
    sig = inspect.signature(MediaGenerationService.download_generated_video)
    assert "stream_to_path" in sig.parameters, (
        "download_generated_video must accept stream_to_path kwarg"
    )


# ============ DESIGN SETTINGS & MEDIA DASHBOARD INTEGRATION TESTS ============


def test_public_design_settings_includes_colors_and_background():
    """Public GET /api/design/settings returns primary_color, accent_color,
    hero_background_url, promo_banner_url, and section visibility flags."""
    port = 8307
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    try:
        portal.DESIGN_SETTINGS['primary_color'] = '#1a237e'
        portal.DESIGN_SETTINGS['accent_color'] = '#ff9800'
        portal.DESIGN_SETTINGS['show_contact'] = False
        portal.DESIGN_SETTINGS['show_quote_form'] = True

        status, resp = _json_request(base + "/api/design/settings")
        assert status == 200
        assert resp['primary_color'] == '#1a237e'
        assert resp['accent_color'] == '#ff9800'
        assert resp['show_contact'] is False
        assert resp['show_quote_form'] is True
        assert resp.get('show_products') is not None
        assert 'hero_background_url' in resp
        assert 'promo_banner_url' in resp
    finally:
        portal.DESIGN_SETTINGS['primary_color'] = '#0d47a1'
        portal.DESIGN_SETTINGS['accent_color'] = '#ff6b35'
        portal.DESIGN_SETTINGS['show_contact'] = True
        portal.DESIGN_SETTINGS['show_quote_form'] = False
        srv.stop()


def test_public_design_settings_resolves_background_and_banner_urls():
    """When hero_background_id and promo_banner_id point to media assets,
    the public response resolves them to playable URLs."""
    port = 8308
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_design_resolve"
    _inject_session(token, "design_admin", "admin")

    bg_id = "media-test-bg-001"
    banner_id = "media-test-banner-001"

    try:
        portal.MEDIA_ASSETS[bg_id] = {
            "id": bg_id, "name": "hero-bg.jpg", "type": "image",
            "url": "/media-files/media-test-bg-001/hero_bg",
            "data": "", "source": "upload",
        }
        portal.MEDIA_ASSETS[banner_id] = {
            "id": banner_id, "name": "promo.jpg", "type": "image",
            "url": "/media-files/media-test-banner-001/promo",
            "data": "", "source": "upload",
        }

        status, _ = _json_request(
            base + "/api/design/settings",
            method="POST",
            token=token,
            payload={
                "hero_background_id": bg_id,
                "promo_banner_id": banner_id,
            },
        )
        assert status == 200

        status, public = _json_request(base + "/api/design/settings")
        assert status == 200
        assert public['hero_background_url'] == "/media-files/media-test-bg-001/hero_bg"
        assert public['promo_banner_url'] == "/media-files/media-test-banner-001/promo"
    finally:
        portal.MEDIA_ASSETS.pop(bg_id, None)
        portal.MEDIA_ASSETS.pop(banner_id, None)
        portal.DESIGN_SETTINGS['hero_background_id'] = ''
        portal.DESIGN_SETTINGS['promo_banner_id'] = ''
        srv.stop()


def test_design_settings_post_rejects_invalid_asset_refs():
    """POST /api/design/settings rejects media asset IDs that don't exist."""
    port = 8309
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_design_invalid_ref"
    _inject_session(token, "design_admin2", "admin")

    try:
        status, resp = _json_request(
            base + "/api/design/settings",
            method="POST",
            token=token,
            payload={"hero_background_id": "nonexistent-asset-xyz"},
        )
        assert status == 400
        assert "invalid" in resp.get("error", "").lower() or "asset" in resp.get("error", "").lower()
        assert "hero_background_id" in resp.get("invalid_refs", [])
    finally:
        srv.stop()


def test_design_settings_post_rejects_non_string_asset_refs():
    """Non-string asset refs are rejected before they can be persisted."""
    port = 8310
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_design_non_string_ref"
    _inject_session(token, "design_admin_non_string", "admin")

    original_hero_video_id = portal.DESIGN_SETTINGS.get("hero_video_id", "")
    portal.DESIGN_SETTINGS["hero_video_id"] = ""

    try:
        status, resp = _json_request(
            base + "/api/design/settings",
            method="POST",
            token=token,
            payload={"hero_video_id": True},
        )
        assert status == 400
        assert "hero_video_id" in resp.get("invalid_refs", [])
        assert portal.DESIGN_SETTINGS["hero_video_id"] == ""
    finally:
        portal.DESIGN_SETTINGS["hero_video_id"] = original_hero_video_id
        srv.stop()


def test_design_settings_post_accepts_empty_string_asset_refs():
    """Empty string asset refs are valid (clearing the assignment)."""
    port = 8311
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_design_empty_ref"
    _inject_session(token, "design_admin3", "admin")

    try:
        status, resp = _json_request(
            base + "/api/design/settings",
            method="POST",
            token=token,
            payload={"hero_background_id": "", "promo_banner_id": ""},
        )
        assert status == 200
        assert resp['success'] is True
    finally:
        srv.stop()


def test_design_settings_post_persists_nested_design_objects():
    """POST /api/design/settings persists designSettings, layoutSettings,
    and brandSettings nested objects from the admin media dashboard."""
    port = 8312
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_nested_settings"
    _inject_session(token, "design_admin4", "admin")

    try:
        status, resp = _json_request(
            base + "/api/design/settings",
            method="POST",
            token=token,
            payload={
                "tagline": "Test tagline",
                "designSettings": {"darkMode": True, "animations": False},
                "brandSettings": {"companyName": "Test Corp"},
            },
        )
        assert status == 200
        settings = resp['settings']
        assert settings['tagline'] == 'Test tagline'
        assert settings['designSettings']['darkMode'] is True
        assert settings['brandSettings']['companyName'] == 'Test Corp'

        status2, admin_resp = _json_request(
            base + "/api/design/settings",
            token=token,
        )
        assert status2 == 200
        assert admin_resp['designSettings']['darkMode'] is True
        assert admin_resp['brandSettings']['companyName'] == 'Test Corp'
    finally:
        portal.DESIGN_SETTINGS.pop('designSettings', None)
        portal.DESIGN_SETTINGS.pop('brandSettings', None)
        portal.DESIGN_SETTINGS['tagline'] = 'Comprehensive Protection for Your Future'
        srv.stop()


def test_delete_media_clears_derived_urls_from_design_settings():
    """Deleting a media asset assigned as hero video also clears
    the derived video_url from DESIGN_SETTINGS."""
    port = 8313
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_delete_clears_url"
    _inject_session(token, "del_admin2", "admin")

    try:
        status, create_resp = _json_request(
            base + "/api/media",
            method="POST",
            token=token,
            payload={
                "name": "hero-video.mp4",
                "type": "video",
                "format": "video/mp4",
                "size": 1024,
                "url": "https://cdn.example.com/hero.mp4",
                "source": "url",
            },
        )
        assert status == 201
        asset_id = create_resp["asset"]["id"]

        status, _ = _json_request(
            base + "/api/design/settings",
            method="POST",
            token=token,
            payload={
                "hero_video_id": asset_id,
                "video_url": "https://cdn.example.com/hero.mp4",
            },
        )
        assert status == 200
        assert portal.DESIGN_SETTINGS['hero_video_id'] == asset_id
        assert portal.DESIGN_SETTINGS['video_url'] == "https://cdn.example.com/hero.mp4"

        status, _ = _json_request(
            base + f"/api/media/{asset_id}",
            method="DELETE",
            token=token,
        )
        assert status == 200
        assert portal.DESIGN_SETTINGS['hero_video_id'] == ''
        assert portal.DESIGN_SETTINGS['video_url'] == ''
    finally:
        srv.stop()


def test_public_settings_gracefully_handles_missing_asset():
    """If a design setting references an asset ID that no longer exists,
    the public response returns empty URLs instead of erroring."""
    port = 8314
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    try:
        portal.DESIGN_SETTINGS['hero_background_id'] = 'deleted-asset-xyz'
        portal.DESIGN_SETTINGS['promo_banner_id'] = 'deleted-asset-abc'

        status, resp = _json_request(base + "/api/design/settings")
        assert status == 200
        assert resp['hero_background_url'] == ''
        assert resp['promo_banner_url'] == ''
    finally:
        portal.DESIGN_SETTINGS['hero_background_id'] = ''
        portal.DESIGN_SETTINGS['promo_banner_id'] = ''
        srv.stop()


def test_design_settings_post_derives_video_url_from_asset_id():
    """Saving from /admin-media.html must store the video URL derived from the
    assigned MEDIA_ASSETS entry, not the URL the dashboard happened to cache.

    This guarantees that the landing page (/) only links to the asset that the
    admin actually selected; if the client-cached URL drifted from what the
    server knows for that asset, the server-side value wins.
    """
    port = 8316
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_design_derive_url"
    _inject_session(token, "derive_admin", "admin")

    asset_id = "media-test-derive-001"
    poster_id = "media-test-derive-poster-001"

    canonical_video_url = "/media-files/media-test-derive-001/hero_video"
    canonical_poster_url = "/media-files/media-test-derive-poster-001/hero_poster"

    try:
        portal.MEDIA_ASSETS[asset_id] = {
            "id": asset_id,
            "name": "hero.mp4",
            "type": "video",
            "url": canonical_video_url,
            "data": "",
            "source": "upload",
        }
        portal.MEDIA_ASSETS[poster_id] = {
            "id": poster_id,
            "name": "poster.jpg",
            "type": "image",
            "url": canonical_poster_url,
            "data": "",
            "source": "upload",
        }

        stale_video_url = "https://cdn.example.com/STALE-hero.mp4"
        stale_poster_url = "https://cdn.example.com/STALE-poster.jpg"

        status, resp = _json_request(
            base + "/api/design/settings",
            method="POST",
            token=token,
            payload={
                "hero_video_id": asset_id,
                "video_poster_id": poster_id,
                "video_url": stale_video_url,
                "video_poster": stale_poster_url,
            },
        )
        assert status == 200
        assert resp["success"] is True

        assert portal.DESIGN_SETTINGS["hero_video_id"] == asset_id
        assert portal.DESIGN_SETTINGS["video_poster_id"] == poster_id
        assert portal.DESIGN_SETTINGS["video_url"] == canonical_video_url
        assert portal.DESIGN_SETTINGS["video_poster"] == canonical_poster_url

        status, public = _json_request(base + "/api/design/settings")
        assert status == 200
        assert public["video_url"] == canonical_video_url
        assert public["video_poster"] == canonical_poster_url
    finally:
        portal.MEDIA_ASSETS.pop(asset_id, None)
        portal.MEDIA_ASSETS.pop(poster_id, None)
        portal.DESIGN_SETTINGS["hero_video_id"] = ""
        portal.DESIGN_SETTINGS["video_poster_id"] = ""
        portal.DESIGN_SETTINGS["video_url"] = ""
        portal.DESIGN_SETTINGS["video_poster"] = ""
        srv.stop()


def test_design_settings_post_clears_video_url_when_id_cleared():
    """Sending an empty hero_video_id must wipe the stored video_url, even if
    the client also sent a non-empty URL. This prevents the landing page from
    keeping a "ghost" video after an admin un-assigns it."""
    port = 8317
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_design_clear_url"
    _inject_session(token, "clear_admin", "admin")

    try:
        portal.DESIGN_SETTINGS["hero_video_id"] = ""
        portal.DESIGN_SETTINGS["video_url"] = "https://cdn.example.com/leftover.mp4"
        portal.DESIGN_SETTINGS["video_poster_id"] = ""
        portal.DESIGN_SETTINGS["video_poster"] = "https://cdn.example.com/leftover.jpg"

        status, resp = _json_request(
            base + "/api/design/settings",
            method="POST",
            token=token,
            payload={
                "hero_video_id": "",
                "video_poster_id": "",
                "video_url": "https://cdn.example.com/STILL-here.mp4",
                "video_poster": "https://cdn.example.com/STILL-here.jpg",
            },
        )
        assert status == 200
        assert resp["success"] is True

        assert portal.DESIGN_SETTINGS["hero_video_id"] == ""
        assert portal.DESIGN_SETTINGS["video_poster_id"] == ""
        assert portal.DESIGN_SETTINGS["video_url"] == ""
        assert portal.DESIGN_SETTINGS["video_poster"] == ""
    finally:
        portal.DESIGN_SETTINGS["video_url"] = ""
        portal.DESIGN_SETTINGS["video_poster"] = ""
        srv.stop()


def test_design_settings_post_reflects_asset_url_change_without_resave():
    """If a media asset's underlying URL changes server-side after the admin
    saved the assignment, the next /api/design/settings GET must reflect the
    new URL — i.e. the public payload resolves through the asset ID rather
    than serving a cached snapshot."""
    port = 8318
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_design_url_changes"
    _inject_session(token, "url_change_admin", "admin")

    asset_id = "media-test-urlchange-001"

    try:
        portal.MEDIA_ASSETS[asset_id] = {
            "id": asset_id,
            "name": "hero.mp4",
            "type": "video",
            "url": "https://cdn.example.com/original.mp4",
            "data": "",
            "source": "url",
        }

        status, _ = _json_request(
            base + "/api/design/settings",
            method="POST",
            token=token,
            payload={"hero_video_id": asset_id},
        )
        assert status == 200
        assert portal.DESIGN_SETTINGS["video_url"] == "https://cdn.example.com/original.mp4"

        # Simulate the asset URL being rewritten (e.g. moved from inline data
        # to disk-backed storage, or migrated to a new CDN path).
        portal.MEDIA_ASSETS[asset_id]["url"] = "/media-files/media-test-urlchange-001/hero"

        status, public = _json_request(base + "/api/design/settings")
        assert status == 200
        assert public["video_url"] == "/media-files/media-test-urlchange-001/hero"
    finally:
        portal.MEDIA_ASSETS.pop(asset_id, None)
        portal.DESIGN_SETTINGS["hero_video_id"] = ""
        portal.DESIGN_SETTINGS["video_url"] = ""
        srv.stop()


def test_video_section_hidden_when_show_video_false():
    """When show_video is False, the public API returns empty video URL."""
    port = 8315
    srv = ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _init_port(base)

    token = "phins_test_hide_video"
    _inject_session(token, "hide_admin", "admin")

    try:
        portal.DESIGN_SETTINGS['video_url'] = 'https://cdn.example.com/video.mp4'
        portal.DESIGN_SETTINGS['show_video'] = False

        status, resp = _json_request(base + "/api/design/settings")
        assert status == 200
        assert resp['video_url'] == ''
        assert resp['video_poster'] == ''
        assert resp['show_video'] is False
    finally:
        portal.DESIGN_SETTINGS['video_url'] = ''
        portal.DESIGN_SETTINGS['show_video'] = True
        srv.stop()
