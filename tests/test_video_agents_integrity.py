"""
End-to-end integration tests for the /video-agents.html pipeline.

Validates that the connection to video providers via API and media agents
exposed by ``video-agents.html`` works end-to-end with strict data integrity:

- Provider capability + diagnostic reporting
- ``submit -> poll -> finalize`` flow that pulls the provider video,
  stores it as a PHINS media asset and exposes a downloadable URL
- SHA-256 checksum is recorded for every completed video asset
- The new ``/api/admin/media/video-jobs/verify`` integrity endpoint returns
  ``verified=True`` for unchanged assets and ``verified=False`` when the
  underlying file is tampered or missing
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer
from typing import Any, Dict, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal


_STUB_VIDEO_BYTES = b"PHINS-VIDEO-AGENT-STUB-PAYLOAD-1234567890"
_STUB_VIDEO_SHA256 = hashlib.sha256(_STUB_VIDEO_BYTES).hexdigest()


class _ServerThread(threading.Thread):
    def __init__(self, port: int) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(("127.0.0.1", port), portal.PortalHandler)

    def run(self) -> None:
        self.httpd.serve_forever()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def _json_request(
    url: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    token: Optional[str] = None,
):
    headers: Dict[str, str] = {}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req) as resp:
            data = resp.read().decode("utf-8")
            return resp.status, json.loads(data) if data else {}
    except HTTPError as exc:
        data = exc.read().decode("utf-8")
        return exc.code, json.loads(data) if data else {}


def _download_bytes(url: str, token: Optional[str] = None) -> tuple:
    headers: Dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return resp.status, resp.read(), dict(resp.headers)


def _warm_test_port(base: str) -> None:
    """Issue a benign request so server.py's per-port init clears its state.

    Without this, the first real request on a fresh port triggers
    ``_ensure_test_port_state`` which wipes SESSIONS — exactly when we have
    just injected our admin session.

    NOTE: /api/health is intentionally NOT used here because that route
    short-circuits before _ensure_test_port_state runs.  /api/media will
    return 403 without a token, but that's enough to trigger the per-port
    bootstrap so subsequent session injections survive.
    """
    try:
        with urlopen(Request(base + "/api/media")) as resp:
            resp.read()
    except Exception:
        pass


def _inject_admin_session(token: str, username: str = "admin") -> None:
    portal.SESSIONS[token] = {
        "username": username,
        "role": "admin",
        "customer_id": "",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    if username not in portal.USERS:
        portal.USERS[username] = {"role": "admin", "username": username}


class _StreamingStubMediaGenerationService:
    """Stub media generation service that streams a known payload to disk.

    Mirrors the contract of services.media_generation_service so that the
    full server.py video-agents pipeline can run without external HTTP.
    """

    def __init__(self, *, gemini: bool = True, kling: bool = True) -> None:
        self.submissions = []
        self.polls = []
        self.downloads = []
        self._gemini = gemini
        self._kling = kling

    def supported_provider_config(self) -> Dict[str, Dict[str, Any]]:
        return {
            "gemini": {
                "enabled": self._gemini,
                "label": "Gemini / Veo",
                "model": "veo-3-fast-preview",
                "models": ["veo-3-fast-preview"],
            },
            "kling": {
                "enabled": self._kling,
                "label": "Kling",
                "models": ["kling-v2.6-pro"],
            },
        }

    def submit_video_generation(self, **kwargs):
        self.submissions.append(kwargs)
        return {
            "provider": kwargs["provider"],
            "provider_job_id": "stub-task-1",
            "status": "queued",
            "message": "Submitted to stub provider.",
            "provider_state": {"operation_name": "operations/stub-task-1"},
        }

    def poll_video_generation(self, **kwargs):
        self.polls.append(kwargs)
        return {
            "status": "completed",
            "message": "Stub provider completed the video.",
            "provider_job_id": kwargs["provider_job_id"],
            "download_url": "https://cdn.example.com/stub-task-1.mp4",
            "duration": 8,
            "provider_state": {"done": True},
        }

    def download_generated_video(self, **kwargs):
        self.downloads.append(kwargs)
        stream_to_path = str(kwargs.get("stream_to_path") or "").strip()
        if stream_to_path:
            with open(stream_to_path, "wb") as handle:
                handle.write(_STUB_VIDEO_BYTES)
            return {
                "file_path": stream_to_path,
                "content_type": "video/mp4",
                "size": len(_STUB_VIDEO_BYTES),
            }
        import base64

        encoded = base64.b64encode(_STUB_VIDEO_BYTES).decode("ascii")
        return {
            "data_url": f"data:video/mp4;base64,{encoded}",
            "content_type": "video/mp4",
            "size": len(_STUB_VIDEO_BYTES),
        }


def _seed_campaign(campaign_id: str) -> None:
    portal.DESIGN_SETTINGS["marketing_sales_agent"] = {
        "latest_campaign": {
            "campaign": {
                "campaign_id": campaign_id,
                "generated_at": datetime.now().isoformat(),
                "ai_video_blueprints": [
                    {
                        "title": "PHINS Welcome",
                        "format": "Short vertical explainer",
                        "voiceover_style": "Warm and trustworthy",
                        "storyboard": [
                            "Open on a happy family.",
                            "Show clear claims support.",
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


# ---------------------------------------------------------------------------
# Provider diagnostics endpoint
# ---------------------------------------------------------------------------

def test_video_providers_diagnose_reports_missing_credentials(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("KLING_API_KEY", raising=False)
    monkeypatch.delenv("KLING_ACCESS_KEY", raising=False)
    monkeypatch.delenv("KLING_SECRET_KEY", raising=False)

    diag = portal.diagnose_media_video_providers()
    assert diag["any_connected"] is False
    assert diag["providers"]["gemini"]["enabled"] is False
    assert "GEMINI_API_KEY" in diag["providers"]["gemini"]["reason"]
    assert diag["providers"]["kling"]["enabled"] is False
    assert (
        "KLING_API_KEY" in diag["providers"]["kling"]["reason"]
        or "KLING_ACCESS_KEY" in diag["providers"]["kling"]["reason"]
    )
    # Env presence flags must NEVER leak the actual secret values
    assert diag["providers"]["gemini"]["env_vars"]["GEMINI_API_KEY"] is False
    assert diag["providers"]["kling"]["env_vars"]["KLING_API_KEY"] is False


def test_video_providers_diagnose_reports_connected_providers(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("KLING_API_KEY", "test-kling-key")
    monkeypatch.delenv("KLING_ACCESS_KEY", raising=False)
    monkeypatch.delenv("KLING_SECRET_KEY", raising=False)

    # Force a fresh media generation service so it picks up the new env vars
    import services.media_generation_service as mgs

    mgs._media_generation_service = None

    diag = portal.diagnose_media_video_providers()
    assert diag["any_connected"] is True
    assert diag["providers"]["gemini"]["enabled"] is True
    assert "Connected" in diag["providers"]["gemini"]["reason"]
    assert diag["providers"]["kling"]["enabled"] is True
    assert "Connected" in diag["providers"]["kling"]["reason"]
    assert diag["providers"]["gemini"]["env_vars"]["GEMINI_API_KEY"] is True
    assert diag["providers"]["kling"]["env_vars"]["KLING_API_KEY"] is True

    # Reset for downstream tests
    mgs._media_generation_service = None


def test_video_providers_diagnose_endpoint_requires_admin_or_media():
    port = 8395
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _warm_test_port(base)
    try:
        # No token → 403
        status, _ = _json_request(base + "/api/admin/media/video-providers/diagnose")
        assert status == 403

        # Customer role → 403
        token = "phins_video_diag_customer"
        portal.SESSIONS[token] = {
            "username": "cust1",
            "role": "customer",
            "customer_id": "CUST-1",
            "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
        }
        status, _ = _json_request(
            base + "/api/admin/media/video-providers/diagnose",
            token=token,
        )
        assert status == 403

        # Admin → 200
        admin_token = "phins_video_diag_admin"
        _inject_admin_session(admin_token, username="diag_admin")
        status, body = _json_request(
            base + "/api/admin/media/video-providers/diagnose",
            token=admin_token,
        )
        assert status == 200
        assert body["success"] is True
        assert "diagnostics" in body
        assert "providers" in body["diagnostics"]
        assert "gemini" in body["diagnostics"]["providers"]
        assert "kling" in body["diagnostics"]["providers"]
    finally:
        srv.stop()


# ---------------------------------------------------------------------------
# End-to-end submit → finalize → checksum → download → verify
# ---------------------------------------------------------------------------

def _drive_video_pipeline_to_completion(base: str, token: str, campaign_id: str) -> Dict[str, Any]:
    status, batch_resp = _json_request(
        base + "/api/admin/media/video-jobs/batch",
        method="POST",
        token=token,
        payload={
            "campaign_id": campaign_id,
            "provider": "gemini",
            "provider_model": "veo-3-fast-preview",
            "pipeline_type": "introductions",
        },
    )
    assert status == 202, batch_resp
    queued_jobs = batch_resp.get("queued_jobs", [])
    assert queued_jobs, batch_resp

    final_job = None
    for _ in range(40):
        time.sleep(0.1)
        status, jobs_resp = _json_request(
            base + f"/api/admin/media/video-jobs?campaign_id={campaign_id}",
            token=token,
        )
        assert status == 200
        jobs = jobs_resp.get("jobs") or []
        if jobs and jobs[0].get("status") == "completed" and jobs[0].get("generated_asset_id"):
            final_job = jobs[0]
            break

    assert final_job is not None, "Video job did not reach completed state in time"
    return final_job


def test_video_agents_pipeline_full_lifecycle_with_integrity_verify():
    port = 8396
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _warm_test_port(base)

    token = "phins_video_e2e_admin"
    _inject_admin_session(token, username="video_e2e_admin")

    stub = _StreamingStubMediaGenerationService()
    original_factory = portal.get_media_generation_service
    portal.get_media_generation_service = lambda: stub

    try:
        campaign_id = "MKT-INTEGRITY-1"
        _seed_campaign(campaign_id)

        # 1. Capabilities endpoint surfaces both providers (stub reports both enabled)
        status, caps_resp = _json_request(
            base + "/api/admin/media/video-providers", token=token
        )
        assert status == 200
        providers = caps_resp["capabilities"]["providers"]
        assert providers["gemini"]["enabled"] is True
        assert providers["kling"]["enabled"] is True

        # 2. Run the full submit → poll → finalize flow
        final_job = _drive_video_pipeline_to_completion(base, token, campaign_id)
        asset_id = final_job["generated_asset_id"]
        assert asset_id

        # Job response surfaces checksum and size for the UI
        assert final_job.get("asset_checksum"), final_job
        assert final_job.get("asset_size") == len(_STUB_VIDEO_BYTES)
        assert final_job["asset_checksum"].lower() == _STUB_VIDEO_SHA256

        # 3. Download URL is a server-side authenticated route, not the raw provider URL
        download_url = final_job["download_url"]
        assert download_url.startswith("/api/media/")
        assert download_url.endswith("/download")

        # 4. Bytes returned by /api/media/{asset_id}/download MUST match the recorded checksum
        status, body, headers = _download_bytes(base + download_url, token=token)
        assert status == 200
        assert body == _STUB_VIDEO_BYTES
        assert hashlib.sha256(body).hexdigest() == _STUB_VIDEO_SHA256
        assert headers["Content-Type"].startswith("video/")

        # 5. Verify endpoint reports integrity OK
        status, verify_resp = _json_request(
            base + "/api/admin/media/video-jobs/verify",
            method="POST",
            token=token,
            payload={"job_id": final_job["id"], "campaign_id": campaign_id},
        )
        assert status == 200
        integrity = verify_resp["integrity"]
        assert integrity["verified"] is True, integrity
        assert integrity["expected_checksum"] == _STUB_VIDEO_SHA256
        assert integrity["actual_checksum"] == _STUB_VIDEO_SHA256
        assert integrity["expected_size"] == len(_STUB_VIDEO_BYTES)
        assert integrity["actual_size"] == len(_STUB_VIDEO_BYTES)

        # 6. Tamper with the underlying file and re-run verify — must report FAILED
        asset = portal.MEDIA_ASSETS[asset_id]
        file_path = asset.get("file_path")
        if file_path and os.path.isfile(file_path):
            with open(file_path, "ab") as handle:
                handle.write(b"-tampered")
            status, verify_resp_2 = _json_request(
                base + "/api/admin/media/video-jobs/verify",
                method="POST",
                token=token,
                payload={"job_id": final_job["id"], "campaign_id": campaign_id},
            )
            assert status == 200
            integrity2 = verify_resp_2["integrity"]
            assert integrity2["verified"] is False
            assert integrity2["actual_checksum"] != integrity2["expected_checksum"]

        # 7. Job listing summary remains consistent (still 1 completed job)
        status, jobs_resp = _json_request(
            base + f"/api/admin/media/video-jobs?campaign_id={campaign_id}",
            token=token,
        )
        assert status == 200
        summary = jobs_resp["summary"]
        assert summary["total"] == 1
        assert summary["completed"] == 1
        assert summary["failed"] == 0
    finally:
        portal.get_media_generation_service = original_factory
        srv.stop()


def test_video_agents_verify_rejects_non_completed_job():
    """The verify endpoint must refuse to vouch for queued/processing/failed jobs."""
    port = 8397
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _warm_test_port(base)

    token = "phins_video_e2e_admin_partial"
    _inject_admin_session(token, username="video_e2e_admin_partial")

    try:
        # Inject a queued job directly
        job_id = "mjob-test-queued-1"
        portal.MEDIA_PROCESSING_JOBS[job_id] = {
            "id": job_id,
            "job_kind": "video_generation",
            "campaign_id": "MKT-VERIFY-PARTIAL",
            "status": "queued",
            "asset_name": "Pending video",
            "provider": "gemini",
            "blueprint_index": 0,
            "generated_asset_id": "",
            "download_url": "",
        }

        status, body = _json_request(
            base + "/api/admin/media/video-jobs/verify",
            method="POST",
            token=token,
            payload={"job_id": job_id, "campaign_id": "MKT-VERIFY-PARTIAL"},
        )
        assert status == 200
        integrity = body["integrity"]
        assert integrity["verified"] is False
        assert "not completed" in integrity["reason"].lower()
    finally:
        portal.MEDIA_PROCESSING_JOBS.pop("mjob-test-queued-1", None)
        srv.stop()


def test_video_agents_verify_detects_missing_asset():
    """If the generated media asset is missing, verify must surface a clear reason."""
    port = 8398
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _warm_test_port(base)

    token = "phins_video_e2e_admin_missing"
    _inject_admin_session(token, username="video_e2e_admin_missing")

    try:
        job_id = "mjob-test-missing-1"
        portal.MEDIA_PROCESSING_JOBS[job_id] = {
            "id": job_id,
            "job_kind": "video_generation",
            "campaign_id": "MKT-VERIFY-MISSING",
            "status": "completed",
            "asset_name": "Orphan video",
            "provider": "gemini",
            "blueprint_index": 0,
            "generated_asset_id": "media-does-not-exist",
            "download_url": "/api/media/media-does-not-exist/download",
        }

        status, body = _json_request(
            base + "/api/admin/media/video-jobs/verify",
            method="POST",
            token=token,
            payload={"job_id": job_id, "campaign_id": "MKT-VERIFY-MISSING"},
        )
        assert status == 200
        integrity = body["integrity"]
        assert integrity["verified"] is False
        assert "missing" in integrity["reason"].lower() or "asset" in integrity["reason"].lower()
    finally:
        portal.MEDIA_PROCESSING_JOBS.pop("mjob-test-missing-1", None)
        srv.stop()


def test_finalize_records_checksum_for_inline_data_url_assets():
    """Even when the provider returns a small inline data: URL, checksum must be recorded."""
    asset_id_seen: Dict[str, str] = {}

    class _InlineOnlyStub(_StreamingStubMediaGenerationService):
        def download_generated_video(self, **kwargs):
            self.downloads.append(kwargs)
            import base64

            encoded = base64.b64encode(_STUB_VIDEO_BYTES).decode("ascii")
            return {
                "data_url": f"data:video/mp4;base64,{encoded}",
                "content_type": "video/mp4",
                "size": len(_STUB_VIDEO_BYTES),
            }

    stub = _InlineOnlyStub()
    original_factory = portal.get_media_generation_service
    portal.get_media_generation_service = lambda: stub

    try:
        # Build a synthetic job that finalize_media_video_job can consume
        portal.ensure_media_storage_dir()
        job = {
            "id": "mjob-inline-1",
            "job_kind": "video_generation",
            "campaign_id": "MKT-INLINE",
            "blueprint_index": 0,
            "asset_name": "Inline test",
            "provider": "gemini",
            "provider_job_id": "stub-task-inline",
            "status": "processing",
            "progress_pct": 50,
            "requested_by": "admin",
            "auto_publish_to_hero": False,
            "generated_asset_id": "",
            "download_url": "",
        }
        portal.MEDIA_PROCESSING_JOBS["mjob-inline-1"] = job

        poll_result = {
            "status": "completed",
            "message": "stub completed",
            "provider_job_id": "stub-task-inline",
            "download_url": "https://cdn.example.com/inline-stub.mp4",
            "duration": 8,
            "provider_state": {"done": True},
        }

        asset = portal.finalize_media_video_job(job, poll_result)
        assert asset is not None
        asset_id_seen["id"] = asset["id"]
        assert asset["checksum"] == _STUB_VIDEO_SHA256
        assert asset["size"] == len(_STUB_VIDEO_BYTES)

        integrity = portal.verify_media_video_job_integrity(job)
        assert integrity["verified"] is True
        assert integrity["expected_checksum"] == _STUB_VIDEO_SHA256
        assert integrity["actual_checksum"] == _STUB_VIDEO_SHA256
    finally:
        portal.get_media_generation_service = original_factory
        portal.MEDIA_PROCESSING_JOBS.pop("mjob-inline-1", None)
        if asset_id_seen.get("id"):
            portal.MEDIA_ASSETS.pop(asset_id_seen["id"], None)


# ---------------------------------------------------------------------------
# Batch route: structured "no provider connected" error + diagnostics body
# ---------------------------------------------------------------------------

def test_batch_route_returns_structured_error_when_no_provider_connected(monkeypatch):
    """When no provider is configured, /video-jobs/batch must return a 503 with
    machine-readable diagnostics so /video-agents.html can render an actionable
    hint instead of a vague "HTTP 400".
    """
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("KLING_API_KEY", raising=False)
    monkeypatch.delenv("KLING_ACCESS_KEY", raising=False)
    monkeypatch.delenv("KLING_SECRET_KEY", raising=False)
    import services.media_generation_service as mgs
    mgs._media_generation_service = None

    port = 8399
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _warm_test_port(base)
    token = "phins_video_e2e_no_provider"
    _inject_admin_session(token, username="video_e2e_no_provider")

    try:
        _seed_campaign("MKT-NO-PROVIDER")
        status, body = _json_request(
            base + "/api/admin/media/video-jobs/batch",
            method="POST",
            token=token,
            payload={
                "campaign_id": "MKT-NO-PROVIDER",
                "provider": "gemini",
            },
        )
        assert status == 503, body
        assert body.get("error")
        assert body.get("reason") == "provider_not_configured"
        assert "diagnostics" in body
        assert body["diagnostics"]["any_connected"] is False
        # Hint must reference at least one of the env vars operators need to set
        hint = (body.get("hint") or "").upper()
        assert "GEMINI_API_KEY" in hint or "KLING_API_KEY" in hint
    finally:
        mgs._media_generation_service = None
        srv.stop()


def test_batch_route_announces_poll_mode_and_webhook_state():
    """Successful batch submission must echo back the resolved poll_mode and
    webhook_callback_configured so the UI can show the user what will happen.
    """
    port = 8400
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _warm_test_port(base)
    token = "phins_video_e2e_poll"
    _inject_admin_session(token, username="video_e2e_poll")

    stub = _StreamingStubMediaGenerationService()
    original_factory = portal.get_media_generation_service
    portal.get_media_generation_service = lambda: stub

    try:
        _seed_campaign("MKT-POLL-1")
        status, body = _json_request(
            base + "/api/admin/media/video-jobs/batch",
            method="POST",
            token=token,
            payload={
                "campaign_id": "MKT-POLL-1",
                "provider": "gemini",
                "poll_mode": "poll",
            },
        )
        assert status == 202, body
        assert body["poll_mode"] == "poll"
        assert body["provider"] == "gemini"
        assert "webhook_callback_configured" in body
        assert isinstance(body["webhook_callback_configured"], bool)
        assert body["queued_jobs"], body
    finally:
        portal.get_media_generation_service = original_factory
        srv.stop()


def test_publish_endpoint_promotes_completed_video_to_landing_page_hero():
    """After a video is generated, the operator can implement it on phins.ai
    via POST /api/admin/media/video-jobs/publish; integrity must pass first.
    """
    port = 8401
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _warm_test_port(base)
    token = "phins_video_e2e_publish"
    _inject_admin_session(token, username="video_e2e_publish")

    stub = _StreamingStubMediaGenerationService()
    original_factory = portal.get_media_generation_service
    portal.get_media_generation_service = lambda: stub

    try:
        campaign_id = "MKT-PUBLISH-1"
        _seed_campaign(campaign_id)
        # Submit batch
        status, batch_body = _json_request(
            base + "/api/admin/media/video-jobs/batch",
            method="POST",
            token=token,
            payload={
                "campaign_id": campaign_id,
                "provider": "gemini",
                "auto_publish_to_hero": False,  # We'll publish manually below
                "poll_mode": "poll",
            },
        )
        assert status == 202, batch_body

        # Wait for completion
        final_job = None
        for _ in range(40):
            time.sleep(0.1)
            status, jobs_resp = _json_request(
                base + f"/api/admin/media/video-jobs?campaign_id={campaign_id}",
                token=token,
            )
            assert status == 200
            jobs = jobs_resp.get("jobs") or []
            if jobs and jobs[0].get("status") == "completed" and jobs[0].get("generated_asset_id"):
                final_job = jobs[0]
                break
        assert final_job is not None
        # Initially NOT implemented on landing page
        assert final_job.get("implemented_on_landing_page") is False

        # Reset DESIGN_SETTINGS hero to ensure clean state
        portal.DESIGN_SETTINGS["hero_video_id"] = ""

        # Publish
        status, publish_body = _json_request(
            base + "/api/admin/media/video-jobs/publish",
            method="POST",
            token=token,
            payload={"job_id": final_job["id"], "campaign_id": campaign_id},
        )
        assert status == 200, publish_body
        assert publish_body["success"] is True
        assert publish_body["integrity"]["verified"] is True
        assert publish_body["design_settings"]["hero_video_id"] == final_job["generated_asset_id"]
        assert portal.DESIGN_SETTINGS["hero_video_id"] == final_job["generated_asset_id"]

        # Subsequent listing must reflect implemented_on_landing_page=true
        status, jobs_resp = _json_request(
            base + f"/api/admin/media/video-jobs?campaign_id={campaign_id}",
            token=token,
        )
        assert status == 200
        published_job = jobs_resp["jobs"][0]
        assert published_job.get("implemented_on_landing_page") is True
    finally:
        portal.get_media_generation_service = original_factory
        srv.stop()


def test_publish_endpoint_refuses_tampered_asset():
    """Integrity must pass before publish; tampered files must NOT go live."""
    port = 8402
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _warm_test_port(base)
    token = "phins_video_e2e_publish_tamper"
    _inject_admin_session(token, username="video_e2e_publish_tamper")

    stub = _StreamingStubMediaGenerationService()
    original_factory = portal.get_media_generation_service
    portal.get_media_generation_service = lambda: stub

    try:
        campaign_id = "MKT-PUBLISH-TAMPER"
        _seed_campaign(campaign_id)
        status, batch_body = _json_request(
            base + "/api/admin/media/video-jobs/batch",
            method="POST",
            token=token,
            payload={"campaign_id": campaign_id, "provider": "gemini", "poll_mode": "poll"},
        )
        assert status == 202

        final_job = None
        for _ in range(40):
            time.sleep(0.1)
            status, jobs_resp = _json_request(
                base + f"/api/admin/media/video-jobs?campaign_id={campaign_id}",
                token=token,
            )
            assert status == 200
            jobs = jobs_resp.get("jobs") or []
            if jobs and jobs[0].get("status") == "completed":
                final_job = jobs[0]
                break
        assert final_job is not None

        asset_id = final_job["generated_asset_id"]
        asset = portal.MEDIA_ASSETS.get(asset_id) or {}
        file_path = asset.get("file_path")
        if file_path and os.path.isfile(file_path):
            with open(file_path, "ab") as handle:
                handle.write(b"-tampered-by-test")
        else:
            # Force checksum mismatch by flipping it
            asset["checksum"] = "0" * 64

        portal.DESIGN_SETTINGS["hero_video_id"] = ""

        status, publish_body = _json_request(
            base + "/api/admin/media/video-jobs/publish",
            method="POST",
            token=token,
            payload={"job_id": final_job["id"], "campaign_id": campaign_id},
        )
        assert status == 409, publish_body
        assert publish_body.get("error")
        assert publish_body["integrity"]["verified"] is False
        # Hero must NOT have been promoted
        assert portal.DESIGN_SETTINGS.get("hero_video_id") != asset_id
    finally:
        portal.get_media_generation_service = original_factory
        srv.stop()


def test_batch_with_webhook_mode_still_starts_polling_fallback():
    """Even when poll_mode='webhook' is selected and a callback URL is set, the
    server must schedule a polling fallback so a missed webhook never strands a
    job in 'processing'.
    """
    port = 8403
    srv = _ServerThread(port)
    srv.start()
    time.sleep(0.3)
    base = f"http://127.0.0.1:{port}"
    _warm_test_port(base)
    token = "phins_video_e2e_webhook_fallback"
    _inject_admin_session(token, username="video_e2e_webhook_fallback")

    stub = _StreamingStubMediaGenerationService()
    original_factory = portal.get_media_generation_service
    portal.get_media_generation_service = lambda: stub

    try:
        campaign_id = "MKT-WEBHOOK-FALLBACK"
        _seed_campaign(campaign_id)
        status, batch_body = _json_request(
            base + "/api/admin/media/video-jobs/batch",
            method="POST",
            token=token,
            payload={
                "campaign_id": campaign_id,
                "provider": "gemini",
                "poll_mode": "webhook",
                "callback_base_url": "https://example.invalid",
                # Aggressive fallback delay so the test completes quickly
                "webhook_fallback_seconds": 1,
            },
        )
        assert status == 202, batch_body
        assert batch_body["webhook_callback_configured"] is True
        assert batch_body["poll_mode"] == "webhook"

        # The webhook will never arrive (callback URL is invalid + we're not
        # delivering one).  The polling fallback must still drive the job to
        # completed thanks to the stub provider returning completed on poll.
        final_job = None
        for _ in range(60):
            time.sleep(0.1)
            status, jobs_resp = _json_request(
                base + f"/api/admin/media/video-jobs?campaign_id={campaign_id}",
                token=token,
            )
            assert status == 200
            jobs = jobs_resp.get("jobs") or []
            if jobs and jobs[0].get("status") == "completed":
                final_job = jobs[0]
                break
        assert final_job is not None, (
            "Job did not reach completed via polling fallback after webhook mode"
        )
        assert final_job.get("download_url", "").startswith("/api/media/")
    finally:
        portal.get_media_generation_service = original_factory
        srv.stop()
