"""
B8 — Video Agents lifecycle hardening
(docs/agent_operations_optimization_design.md §B8).

Inline ``server.py`` pipeline (``/api/admin/media/video-jobs*`` +
``/api/provider/media-processing/callback``):

- completion mode defaults to ``webhook`` when a callback base URL exists and
  degrades to ``poll`` otherwise; an explicit ``poll_mode`` still wins
- identical requests (campaign, blueprint, prompt, provider, model, image)
  reuse the existing job; ``force`` regenerates
- replayed or stale webhook deliveries are refused and change nothing
- webhook-then-poll and poll-then-webhook produce exactly one download, one
  asset and one terminal transition
- ``rearm_media_video_jobs`` resumes jobs a previous process left in flight
- polls ride the agent job queue (one durable, self-rescheduling row per
  video job) when ``PHINS_AGENT_ASYNC`` is on; an in-flight job past
  ``VIDEO_AGENTS_POLL_TIMEOUT`` is failed instead of polled forever

``services/video_agents_service.py`` mirror: completion-mode resolution,
webhook fallback poller, dedupe with ``force``, restart re-arm, and a late
callback never reopening a terminal job.

All servers bind port 0 (no fixed ports); nothing here hardcodes
``localhost:8000``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from datetime import datetime, timedelta
from http.server import HTTPServer
from typing import Any, Dict, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import web_portal.server as portal

_STUB_VIDEO_BYTES = b"PHINS-B8-STUB-VIDEO-PAYLOAD"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _json_request(url: str, method: str = "GET", payload: Optional[Dict[str, Any]] = None,
                  token: Optional[str] = None, headers: Optional[Dict[str, str]] = None,
                  raw_body: Optional[bytes] = None):
    hdrs: Dict[str, str] = dict(headers or {})
    body = raw_body
    if payload is not None and body is None:
        body = json.dumps(payload).encode("utf-8")
    if body is not None:
        hdrs.setdefault("Content-Type", "application/json")
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    req = Request(url, data=body, headers=hdrs, method=method)
    try:
        with urlopen(req) as resp:
            data = resp.read().decode("utf-8")
            return resp.status, json.loads(data) if data else {}
    except HTTPError as exc:
        data = exc.read().decode("utf-8")
        return exc.code, json.loads(data) if data else {}


def _warm(base: str) -> None:
    try:
        with urlopen(Request(base + "/api/media")) as resp:
            resp.read()
    except Exception:
        pass


def _inject_admin_session(token: str, username: str) -> None:
    portal.SESSIONS[token] = {
        "username": username,
        "role": "admin",
        "customer_id": "",
        "expires": (datetime.now() + timedelta(hours=1)).isoformat(),
    }
    if username not in portal.USERS:
        portal.USERS[username] = {"role": "admin", "username": username}


def _seed_campaign(campaign_id: str, blueprints: int = 1) -> None:
    portal.DESIGN_SETTINGS["marketing_sales_agent"] = {
        "latest_campaign": {
            "campaign": {
                "campaign_id": campaign_id,
                "generated_at": datetime.now().isoformat(),
                "ai_video_blueprints": [
                    {
                        "title": f"PHINS Welcome {i + 1}",
                        "format": "Short vertical explainer",
                        "voiceover_style": "Warm and trustworthy",
                        "storyboard": ["Open on a happy family.", "Show clear claims support."],
                    }
                    for i in range(blueprints)
                ],
            },
            "integrity": {"verified": True, "algorithm": "hmac-sha256", "signature": "stub"},
            "assets_created": [],
        },
        "published_campaigns": [],
        "social_connections": {},
    }


class _StubProvider:
    """Media generation stub. ``poll_outcomes`` is consumed left to right; when
    exhausted the last value repeats (default: completed on the first poll)."""

    def __init__(self, poll_outcomes=("completed",)) -> None:
        self.submissions = []
        self.polls = []
        self.downloads = []
        self._outcomes = list(poll_outcomes)
        self._seq = 0

    def supported_provider_config(self):
        return {
            "gemini": {"enabled": True, "label": "Gemini / Veo", "model": "veo", "models": ["veo"]},
            "kling": {"enabled": False, "label": "Kling", "models": []},
        }

    def submit_video_generation(self, **kwargs):
        self.submissions.append(kwargs)
        self._seq += 1
        return {
            "provider": kwargs["provider"],
            "provider_job_id": f"stub-task-{self._seq}",
            "status": "queued",
            "message": "Submitted to stub provider.",
            "provider_state": {"operation_name": f"operations/stub-task-{self._seq}"},
        }

    def poll_video_generation(self, **kwargs):
        self.polls.append(kwargs)
        outcome = self._outcomes[min(len(self.polls), len(self._outcomes)) - 1]
        if outcome == "processing":
            return {"status": "processing", "progress_pct": 40, "provider_job_id": kwargs["provider_job_id"],
                    "provider_state": {"done": False}}
        return {
            "status": "completed",
            "message": "Stub provider completed the video.",
            "provider_job_id": kwargs["provider_job_id"],
            "download_url": f"https://cdn.example.com/{kwargs['provider_job_id']}.mp4",
            "duration": 8,
            "provider_state": {"done": True},
        }

    def download_generated_video(self, **kwargs):
        self.downloads.append(kwargs)
        path = str(kwargs.get("stream_to_path") or "")
        if path:
            with open(path, "wb") as fh:
                fh.write(_STUB_VIDEO_BYTES)
            return {"file_path": path, "content_type": "video/mp4", "size": len(_STUB_VIDEO_BYTES)}
        encoded = base64.b64encode(_STUB_VIDEO_BYTES).decode("ascii")
        return {"data_url": f"data:video/mp4;base64,{encoded}", "content_type": "video/mp4",
                "size": len(_STUB_VIDEO_BYTES)}


@pytest.fixture
def server():
    srv = _ServerThread()
    srv.start()
    time.sleep(0.2)
    _warm(srv.base)
    yield srv
    srv.stop()


@pytest.fixture
def admin_token(server):
    token = "phins_b8_admin"
    _inject_admin_session(token, "video_b8_admin")
    return token


@pytest.fixture
def stub(monkeypatch):
    provider = _StubProvider()
    monkeypatch.setattr(portal, "get_media_generation_service", lambda: provider)
    return provider


def _wait_for(predicate, timeout: float = 8.0, step: float = 0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return predicate()


def _job(job_id: str) -> Dict[str, Any]:
    return portal.MEDIA_PROCESSING_JOBS[job_id]


def _assets_for_job(job_id: str):
    return [a for a in portal.MEDIA_ASSETS.values()
            if isinstance(a, dict) and (a.get("metadata") or {}).get("job_id") == job_id]


def _callback(server, job: Dict[str, Any], body: Dict[str, Any], *, headers=None, raw_body=None):
    return _json_request(
        server.base + job["callback_path"], method="POST", payload=body, raw_body=raw_body,
        headers={"X-Media-Webhook-Secret": portal.MEDIA_PROVIDER_WEBHOOK_SECRET, **(headers or {})},
    )


# ---------------------------------------------------------------------------
# Completion mode
# ---------------------------------------------------------------------------

class TestCompletionMode:
    def test_default_is_webhook_only_when_a_callback_url_exists(self, monkeypatch):
        monkeypatch.delenv("VIDEO_AGENTS_COMPLETION_MODE", raising=False)
        assert portal.media_video_default_completion_mode() == "webhook"
        assert portal.resolve_media_video_completion_mode("", "https://phins.example") == "webhook"
        assert portal.resolve_media_video_completion_mode(None, "") == "poll"
        # Explicit request wins in both directions.
        assert portal.resolve_media_video_completion_mode("poll", "https://phins.example") == "poll"
        assert portal.resolve_media_video_completion_mode("WEBHOOK", "https://phins.example") == "webhook"
        # Webhook without any way to receive one is reported honestly as poll.
        assert portal.resolve_media_video_completion_mode("webhook", "") == "poll"

    def test_env_can_flip_the_default_back_to_poll(self, monkeypatch):
        monkeypatch.setenv("VIDEO_AGENTS_COMPLETION_MODE", "poll")
        assert portal.resolve_media_video_completion_mode("", "https://phins.example") == "poll"
        monkeypatch.setenv("VIDEO_AGENTS_COMPLETION_MODE", "nonsense")
        assert portal.media_video_default_completion_mode() == "webhook"

    def test_batch_without_poll_mode_uses_webhook_and_hands_provider_the_callback(
            self, server, admin_token, stub, monkeypatch):
        monkeypatch.delenv("VIDEO_AGENTS_COMPLETION_MODE", raising=False)
        campaign = "MKT-B8-MODE"
        _seed_campaign(campaign)
        status, body = _json_request(
            server.base + "/api/admin/media/video-jobs/batch", method="POST", token=admin_token,
            payload={"campaign_id": campaign, "provider": "gemini",
                     "callback_base_url": "https://hooks.example", "webhook_fallback_seconds": 1})
        assert status == 202, body
        assert body["poll_mode"] == "webhook"
        assert body["webhook_callback_configured"] is True
        job_id = body["queued_jobs"][0]["id"]
        # Submission happens on the serial worker; the provider receives the
        # public callback URL that carries the per-job token.
        assert _wait_for(lambda: stub.submissions)
        assert stub.submissions[0]["callback_url"].startswith("https://hooks.example/api/provider/media-processing/callback?job_id=" + job_id)
        # No webhook ever arrives; the polling fallback still finishes the job.
        assert _wait_for(lambda: _job(job_id)["status"] == "completed")
        assert len(stub.downloads) == 1

    def test_batch_without_callback_reports_poll(self, server, admin_token, stub, monkeypatch):
        monkeypatch.delenv("VIDEO_AGENTS_COMPLETION_MODE", raising=False)
        monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
        campaign = "MKT-B8-NOCB"
        _seed_campaign(campaign)
        status, body = _json_request(
            server.base + "/api/admin/media/video-jobs/batch", method="POST", token=admin_token,
            payload={"campaign_id": campaign, "provider": "gemini", "poll_mode": "webhook"})
        assert status == 202, body
        assert body["poll_mode"] == "poll"
        assert body["webhook_callback_configured"] is False

    def test_diagnostics_expose_default_mode_and_scheduler(self, monkeypatch):
        monkeypatch.delenv("PHINS_AGENT_ASYNC", raising=False)
        monkeypatch.setenv("WEBHOOK_BASE_URL", "https://hooks.example")
        diag = portal.diagnose_media_video_providers()
        assert diag["default_completion_mode"] == "webhook"
        assert diag["poll_scheduler"] == "thread"
        monkeypatch.delenv("WEBHOOK_BASE_URL")
        monkeypatch.setenv("PHINS_AGENT_ASYNC", "1")
        diag = portal.diagnose_media_video_providers()
        assert diag["default_completion_mode"] == "poll"
        assert diag["poll_scheduler"] == "queue"


# ---------------------------------------------------------------------------
# Request dedupe
# ---------------------------------------------------------------------------

class TestRequestDedupe:
    def test_duplicate_batch_reuses_existing_job_and_force_regenerates(self, server, admin_token, stub):
        campaign = "MKT-B8-DEDUPE"
        _seed_campaign(campaign)
        url = server.base + "/api/admin/media/video-jobs/batch"
        payload = {"campaign_id": campaign, "provider": "gemini", "poll_mode": "poll"}

        status, first = _json_request(url, method="POST", token=admin_token, payload=payload)
        assert status == 202 and len(first["queued_jobs"]) == 1
        job_id = first["queued_jobs"][0]["id"]

        status, second = _json_request(url, method="POST", token=admin_token, payload=payload)
        assert status == 202, second
        assert second["queued_jobs"] == []
        assert second["deduplicated_count"] == 1
        assert second["reused_jobs"][0]["id"] == job_id
        assert second["reused_jobs"][0]["deduplicated"] is True
        assert "reused" in second["message"]

        # A different prompt is a different request.
        status, other = _json_request(url, method="POST", token=admin_token,
                                      payload=dict(payload, prompt_override="Different angle"))
        assert status == 202 and len(other["queued_jobs"]) == 1
        assert other["queued_jobs"][0]["id"] != job_id

        # force creates a fresh job for the identical request.
        status, forced = _json_request(url, method="POST", token=admin_token, payload=dict(payload, force=True))
        assert status == 202 and len(forced["queued_jobs"]) == 1
        assert forced["queued_jobs"][0]["id"] != job_id
        assert forced["deduplicated_count"] == 0

        # The fingerprint is on the record but never in the API payload.
        assert _job(job_id)["request_fingerprint"]
        assert "request_fingerprint" not in first["queued_jobs"][0]

    def test_completed_job_is_reused_but_failed_job_is_not(self, server, admin_token, stub):
        campaign = "MKT-B8-DEDUPE-TERMINAL"
        _seed_campaign(campaign)
        url = server.base + "/api/admin/media/video-jobs"
        payload = {"campaign_id": campaign, "blueprint_index": 0, "provider": "gemini",
                   "poll_mode": "poll", "poll_delay_seconds": 1}
        status, first = _json_request(url, method="POST", token=admin_token, payload=payload)
        assert status == 202 and first["deduplicated"] is False
        job_id = first["job"]["id"]
        assert _wait_for(lambda: _job(job_id)["status"] == "completed")

        status, again = _json_request(url, method="POST", token=admin_token, payload=payload)
        assert status == 200 and again["deduplicated"] is True
        assert again["job"]["id"] == job_id
        assert again["job"]["status"] == "completed"
        assert len(stub.submissions) == 1

        # Mark it failed: the next identical request is a legitimate retry.
        _job(job_id)["status"] = "failed"
        status, retry = _json_request(url, method="POST", token=admin_token, payload=payload)
        assert status == 202 and retry["deduplicated"] is False
        assert retry["job"]["id"] != job_id

    def test_fingerprint_covers_every_billable_input(self):
        base = dict(campaign_id="C", blueprint_index=0, provider="gemini", provider_model="veo",
                    prompt="p", image_data_url="")
        ref = portal.media_video_request_fingerprint(**base)
        assert portal.media_video_request_fingerprint(**base) == ref
        assert portal.media_video_request_fingerprint(**dict(base, provider="Gemini")) == ref  # normalised
        for change in ({"blueprint_index": 1}, {"provider": "kling"}, {"provider_model": "veo-2"},
                       {"prompt": "q"}, {"image_data_url": "data:image/png;base64,AAAA"},
                       {"campaign_id": "D"}):
            assert portal.media_video_request_fingerprint(**dict(base, **change)) != ref


# ---------------------------------------------------------------------------
# Webhook replay protection + single terminal transition
# ---------------------------------------------------------------------------

def _submit_processing_job(server, admin_token, campaign: str, stub) -> str:
    """Submit one job whose provider stays 'processing' on poll."""
    _seed_campaign(campaign)
    status, body = _json_request(
        server.base + "/api/admin/media/video-jobs", method="POST", token=admin_token,
        payload={"campaign_id": campaign, "blueprint_index": 0, "provider": "gemini",
                 "poll_mode": "webhook", "callback_base_url": "https://hooks.example",
                 "webhook_fallback_seconds": 3600})
    assert status == 202, body
    job_id = body["job"]["id"]
    assert _job(job_id)["provider_job_id"]
    return job_id


class TestWebhookIntegrity:
    def test_replayed_delivery_is_refused_and_changes_nothing(self, server, admin_token, monkeypatch):
        stub = _StubProvider(poll_outcomes=("processing",))
        monkeypatch.setattr(portal, "get_media_generation_service", lambda: stub)
        job_id = _submit_processing_job(server, admin_token, "MKT-B8-REPLAY", stub)
        job = _job(job_id)
        body = {"status": "completed", "download_url": "https://cdn.example.com/final.mp4",
                "provider_job_id": job["provider_job_id"]}

        status, first = _callback(server, job, body)
        assert status == 200, first
        assert first["already_terminal"] is False
        assert first["job"]["status"] == "completed"
        assert len(stub.downloads) == 1
        assert len(_assets_for_job(job_id)) == 1
        asset_id = job["generated_asset_id"]

        # Byte-identical replay (no nonce header -> body hash is the nonce).
        status, replay = _callback(server, job, body)
        assert status == 409, replay
        assert replay["error"] == "Replayed webhook delivery"
        assert replay["job_id"] == job_id
        assert len(stub.downloads) == 1
        assert _assets_for_job(job_id) == [portal.MEDIA_ASSETS[asset_id]]

        # Same nonce, different body: still a replay of that delivery id.
        _callback(server, job, dict(body, message="x"), headers={"X-Media-Nonce": "delivery-77"})
        status, replay2 = _callback(server, job, dict(body, message="y"), headers={"X-Media-Nonce": "delivery-77"})
        assert status == 409

        # A genuinely new delivery for a job that is already terminal is
        # acknowledged without touching the asset or downloading again.
        status, late = _callback(server, job, dict(body, message="late duplicate from provider"))
        assert status == 200, late
        assert late["already_terminal"] is True
        assert late["job"]["generated_asset_id"] == asset_id
        assert len(stub.downloads) == 1
        assert len(_assets_for_job(job_id)) == 1

        # Fingerprints are persisted on the job so a replay is caught after a restart.
        fingerprints = [d["fingerprint"] for d in job["webhook_deliveries"]]
        assert len(fingerprints) == len(set(fingerprints)) >= 3

    def test_stale_or_future_timestamp_is_refused(self, server, admin_token, monkeypatch):
        stub = _StubProvider(poll_outcomes=("processing",))
        monkeypatch.setattr(portal, "get_media_generation_service", lambda: stub)
        monkeypatch.setenv("MEDIA_WEBHOOK_REPLAY_WINDOW_SECONDS", "120")
        job_id = _submit_processing_job(server, admin_token, "MKT-B8-STALE", stub)
        job = _job(job_id)
        body = {"status": "completed", "download_url": "https://cdn.example.com/final.mp4"}

        stale = str(int(time.time()) - 600)
        status, resp = _callback(server, job, body, headers={"X-Media-Timestamp": stale})
        assert status == 403 and "timestamp" in resp["error"].lower()
        future = str(int(time.time()) + 600)
        status, resp = _callback(server, job, dict(body, n=2), headers={"X-Media-Timestamp": future})
        assert status == 403
        assert _job(job_id)["status"] != "completed"
        assert stub.downloads == []

        # ISO-8601 and millisecond epochs inside the window are accepted.
        iso_now = datetime.utcnow().isoformat() + "Z"
        status, resp = _callback(server, job, body, headers={"X-Media-Timestamp": iso_now})
        assert status == 200, resp
        assert _job(job_id)["status"] == "completed"
        assert len(stub.downloads) == 1

    def test_replay_check_unit_semantics(self, monkeypatch):
        monkeypatch.setenv("MEDIA_WEBHOOK_REPLAY_WINDOW_SECONDS", "300")
        job = {"id": "mjob-unit-replay"}
        headers: Dict[str, str] = {}
        now = 1_700_000_000.0
        assert portal.check_media_webhook_replay(job, headers, b'{"a":1}', {}, now=now) is None
        assert portal.check_media_webhook_replay(job, headers, b'{"a":1}', {}, now=now) == (409, "Replayed webhook delivery")
        assert portal.check_media_webhook_replay(job, headers, b'{"a":2}', {}, now=now) is None
        # Same payload for a different job is a different delivery.
        assert portal.check_media_webhook_replay({"id": "mjob-other"}, headers, b'{"a":1}', {}, now=now) is None
        # Payload-embedded timestamp is honoured when there is no header.
        assert portal.check_media_webhook_replay(job, headers, b'{"a":3}', {"timestamp": now - 301}, now=now) == (
            403, "Webhook timestamp outside the accepted window")
        assert portal.check_media_webhook_replay(job, headers, b'{"a":3}', {"timestamp": now - 299}, now=now) is None
        # Per-job history is bounded.
        for i in range(100):
            portal.check_media_webhook_replay(job, headers, f'{{"i":{i}}}'.encode(), {}, now=now)
        assert len(job["webhook_deliveries"]) == portal._MEDIA_WEBHOOK_DELIVERIES_PER_JOB


class TestSingleTerminalTransition:
    def test_poll_then_webhook(self, server, admin_token, stub):
        _seed_campaign("MKT-B8-RACE-A")
        status, body = _json_request(
            server.base + "/api/admin/media/video-jobs", method="POST", token=admin_token,
            payload={"campaign_id": "MKT-B8-RACE-A", "blueprint_index": 0, "provider": "gemini",
                     "poll_mode": "poll", "poll_delay_seconds": 1, "callback_base_url": "https://hooks.example"})
        assert status == 202, body
        job_id = body["job"]["id"]
        assert _wait_for(lambda: _job(job_id)["status"] == "completed")
        job = _job(job_id)
        assert len(stub.downloads) == 1
        asset_id = job["generated_asset_id"]

        status, late = _callback(server, job, {"status": "completed", "download_url": "https://cdn.example.com/other.mp4"})
        assert status == 200 and late["already_terminal"] is True
        assert job["generated_asset_id"] == asset_id
        assert job["download_url"] == f"/api/media/{asset_id}/download"
        assert len(stub.downloads) == 1
        assert len(_assets_for_job(job_id)) == 1
        assert job["completed_at"] == late["job"]["completed_at"]

    def test_webhook_then_poll(self, server, admin_token, monkeypatch):
        stub = _StubProvider(poll_outcomes=("processing",))
        monkeypatch.setattr(portal, "get_media_generation_service", lambda: stub)
        job_id = _submit_processing_job(server, admin_token, "MKT-B8-RACE-B", stub)
        job = _job(job_id)
        status, resp = _callback(server, job, {"status": "completed", "download_url": "https://cdn.example.com/w.mp4"})
        assert status == 200 and resp["job"]["status"] == "completed"
        polls_before = len(stub.polls)

        # The (fallback) poll fires afterwards: it must not touch the provider
        # nor the job.
        outcome = portal.poll_media_video_job_once(job_id)
        assert outcome == {"status": "completed", "rearm_in": None}
        assert len(stub.polls) == polls_before
        assert len(stub.downloads) == 1
        assert len(_assets_for_job(job_id)) == 1

    def test_concurrent_finalize_calls_download_once(self, stub):
        job_id = "mjob-b8-concurrent"
        portal.MEDIA_PROCESSING_JOBS[job_id] = {
            "id": job_id, "job_kind": "video_generation", "campaign_id": "MKT-B8-CONC",
            "blueprint_index": 0, "asset_name": "Race", "provider": "gemini",
            "provider_job_id": "stub-race", "provider_state": {}, "status": "processing",
            "progress_pct": 50, "requested_at": datetime.now().isoformat(), "requested_by": "t",
            "auto_publish_to_hero": False, "generated_asset_id": "", "download_url": "",
        }
        try:
            results = []
            barrier = threading.Barrier(6)

            def worker():
                barrier.wait()
                results.append(portal.finalize_media_video_job(
                    portal.MEDIA_PROCESSING_JOBS[job_id],
                    {"status": "completed", "download_url": "https://cdn.example.com/r.mp4"}))

            threads = [threading.Thread(target=worker) for _ in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
            assert len(stub.downloads) == 1
            assert len(_assets_for_job(job_id)) == 1
            assert all(r is not None and r["id"] == portal.MEDIA_PROCESSING_JOBS[job_id]["generated_asset_id"]
                       for r in results)
        finally:
            portal.MEDIA_PROCESSING_JOBS.pop(job_id, None)

    def test_cancel_after_completion_is_refused(self, server, admin_token, stub):
        _seed_campaign("MKT-B8-CANCEL")
        status, body = _json_request(
            server.base + "/api/admin/media/video-jobs", method="POST", token=admin_token,
            payload={"campaign_id": "MKT-B8-CANCEL", "blueprint_index": 0, "provider": "gemini",
                     "poll_mode": "poll", "poll_delay_seconds": 1})
        job_id = body["job"]["id"]
        assert _wait_for(lambda: _job(job_id)["status"] == "completed")
        status, resp = _json_request(server.base + "/api/admin/media/video-jobs/cancel", method="POST",
                                     token=admin_token, payload={"job_id": job_id})
        assert status == 409 and "already completed" in resp["error"]
        assert _job(job_id)["status"] == "completed"


# ---------------------------------------------------------------------------
# Restart re-arm, poll timeout, queue-backed polls
# ---------------------------------------------------------------------------

def _seed_inflight(job_id: str, *, status: str, provider_job_id: str, campaign: str,
                   requested_at: Optional[str] = None) -> Dict[str, Any]:
    job = {
        "id": job_id, "job_kind": "video_generation", "campaign_id": campaign,
        "blueprint_index": 0, "asset_name": f"Video {job_id}", "provider": "gemini",
        "provider_job_id": provider_job_id, "provider_state": {}, "provider_model": "",
        "prompt": "p", "aspect_ratio": "16:9", "status": status, "progress_pct": 0,
        "requested_at": requested_at or datetime.now().isoformat(), "requested_by": "t",
        "completed_at": None, "error": None, "message": "", "auto_publish_to_hero": False,
        "generated_asset_id": "", "download_url": "", "callback_token": "tok",
        "callback_path": f"/api/provider/media-processing/callback?job_id={job_id}&token=tok",
        "callback_url": "", "image_data_url": "",
    }
    portal.MEDIA_PROCESSING_JOBS[job_id] = job
    return job


class TestRestartAndQueue:
    def test_rearm_resumes_submission_and_polling_but_not_terminal_jobs(self, stub, monkeypatch):
        monkeypatch.delenv("PHINS_AGENT_ASYNC", raising=False)
        _seed_campaign("MKT-B8-REARM")
        ids = ["mjob-b8-rearm-q", "mjob-b8-rearm-p", "mjob-b8-rearm-done", "mjob-b8-rearm-failed"]
        try:
            _seed_inflight(ids[0], status="queued", provider_job_id="", campaign="MKT-B8-REARM")
            _seed_inflight(ids[1], status="processing", provider_job_id="stub-old-1", campaign="MKT-B8-REARM")
            _seed_inflight(ids[2], status="completed", provider_job_id="stub-old-2", campaign="MKT-B8-REARM")
            _seed_inflight(ids[3], status="failed", provider_job_id="stub-old-3", campaign="MKT-B8-REARM")

            stats = portal.rearm_media_video_jobs()
            assert stats == {"submission": 1, "polling": 1}
            assert _wait_for(lambda: _job(ids[0])["status"] == "completed" and _job(ids[1])["status"] == "completed")
            # The queued job went through the provider submit; the processing
            # one was only polled.
            assert len(stub.submissions) == 1
            assert stub.submissions[0]["title"] == f"Video {ids[0]}"
            assert _job(ids[2])["status"] == "completed" and _job(ids[3])["status"] == "failed"
            assert len(stub.downloads) == 2
        finally:
            for job_id in ids:
                portal.MEDIA_PROCESSING_JOBS.pop(job_id, None)

    def test_poll_timeout_fails_a_job_still_processing_after_the_deadline(self, monkeypatch):
        stub = _StubProvider(poll_outcomes=("processing",))
        monkeypatch.setattr(portal, "get_media_generation_service", lambda: stub)
        monkeypatch.setenv("VIDEO_AGENTS_POLL_TIMEOUT", "60")
        fresh = "mjob-b8-timeout-fresh"
        old = "mjob-b8-timeout-old"
        try:
            _seed_inflight(fresh, status="processing", provider_job_id="s-1", campaign="MKT-B8-TO")
            _seed_inflight(old, status="processing", provider_job_id="s-2", campaign="MKT-B8-TO",
                           requested_at=(datetime.now() - timedelta(hours=2)).isoformat())
            assert portal.poll_media_video_job_once(fresh) == {
                "status": "processing", "rearm_in": portal.MEDIA_VIDEO_POLL_INTERVAL_SECONDS}
            outcome = portal.poll_media_video_job_once(old)
            assert outcome == {"status": "failed", "rearm_in": None}
            assert "timed out" in _job(old)["error"]
            assert _job(old)["provider_status"] == "timeout"
            # The provider was still asked once more before giving up, so a
            # video that finished during downtime is pulled, not abandoned.
            assert len(stub.polls) == 2
        finally:
            portal.MEDIA_PROCESSING_JOBS.pop(fresh, None)
            portal.MEDIA_PROCESSING_JOBS.pop(old, None)

    def test_polls_become_one_self_rescheduling_queue_row(self, monkeypatch):
        from services.agent_job_queue import AgentJobQueue

        stub = _StubProvider(poll_outcomes=("processing", "processing", "completed"))
        monkeypatch.setattr(portal, "get_media_generation_service", lambda: stub)
        monkeypatch.setenv("PHINS_AGENT_ASYNC", "1")
        queue = AgentJobQueue(poll_interval=0.01)
        monkeypatch.setattr(portal, "get_agent_job_queue", lambda: queue)
        job_id = "mjob-b8-queue"
        try:
            _seed_inflight(job_id, status="processing", provider_job_id="s-q", campaign="MKT-B8-Q")
            assert portal.schedule_media_job_poll(job_id, delay_seconds=1) == "queue"
            # Scheduling again while the row is parked does not create a second row.
            assert portal.schedule_media_job_poll(job_id, delay_seconds=1) == "queue"
            rows = queue.list_jobs(job_type=portal.MEDIA_VIDEO_POLL_JOB_TYPE, subject_id=job_id)
            assert len(rows) == 1
            row_id = rows[0]["id"]
            assert rows[0]["status"] == "pending"
            assert queue.process_once()["claimed"] == 0  # deferred by delay_seconds

            def make_due():
                queue._update_job(row_id, {"next_retry_at": datetime.utcnow() - timedelta(seconds=1)})

            make_due()
            assert queue.process_once()["rescheduled"] == 1
            assert _job(job_id)["status"] == "processing"
            make_due()
            assert queue.process_once()["rescheduled"] == 1
            make_due()
            stats = queue.process_once()
            assert stats["completed"] == 1
            row = queue.get_job(row_id)
            assert row["status"] == "completed"
            assert row["result"] == {"job_id": job_id, "status": "completed"}
            assert row["attempts"] == 1
            assert _job(job_id)["status"] == "completed"
            assert len(stub.polls) == 3 and len(stub.downloads) == 1
            assert len(queue.list_jobs(job_type=portal.MEDIA_VIDEO_POLL_JOB_TYPE, subject_id=job_id)) == 1
        finally:
            portal.MEDIA_PROCESSING_JOBS.pop(job_id, None)

    def test_queue_handler_is_bound_on_the_shared_queue(self, monkeypatch):
        from services.agent_job_queue import reset_job_queue
        reset_job_queue()
        try:
            queue = portal.get_agent_job_queue()
            assert portal.MEDIA_VIDEO_POLL_JOB_TYPE in queue.handlers()
        finally:
            reset_job_queue()

    def test_scheduler_falls_back_to_a_thread_when_the_queue_is_unavailable(self, stub, monkeypatch):
        monkeypatch.setenv("PHINS_AGENT_ASYNC", "1")

        def broken():
            raise RuntimeError("queue down")

        monkeypatch.setattr(portal, "get_agent_job_queue", broken)
        job_id = "mjob-b8-fallback"
        try:
            _seed_inflight(job_id, status="processing", provider_job_id="s-f", campaign="MKT-B8-F")
            assert portal.schedule_media_job_poll(job_id, delay_seconds=1) == "thread"
            assert _wait_for(lambda: _job(job_id)["status"] == "completed")
        finally:
            portal.MEDIA_PROCESSING_JOBS.pop(job_id, None)


# ---------------------------------------------------------------------------
# services/video_agents_service.py mirror
# ---------------------------------------------------------------------------

class TestServiceMirror:
    @pytest.fixture
    def mod(self, monkeypatch):
        import services.video_agents_service as mod
        from unittest.mock import MagicMock

        monkeypatch.setattr(mod, "_job_store", mod._JobStore(enabled=False))
        monkeypatch.setattr(mod, "MEDIA_GENERATION_AVAILABLE", True)
        media = MagicMock()
        media.supported_provider_config.return_value = {
            "gemini": {"enabled": True, "label": "Gemini / Veo", "models": []},
            "kling": {"enabled": False, "label": "Kling", "models": []},
        }
        media.submit_video_generation.return_value = {
            "provider": "gemini", "provider_job_id": "op-b8", "status": "queued",
            "message": "Submitted", "provider_state": {"operation_name": "op-b8"},
        }
        media.poll_video_generation.return_value = {
            "status": "completed", "download_url": "https://cdn.example.com/b8.mp4", "provider_state": {}}
        monkeypatch.setattr(mod, "get_media_generation_service", lambda: media)
        mod._media = media
        return mod

    def test_resolve_completion_mode(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "_DEFAULT_COMPLETION_MODE", "webhook")
        assert mod.resolve_completion_mode("", "https://cb") == "webhook"
        assert mod.resolve_completion_mode("", "") == "poll"
        assert mod.resolve_completion_mode("poll", "https://cb") == "poll"
        assert mod.resolve_completion_mode("webhook", "") == "poll"
        monkeypatch.setattr(mod, "_DEFAULT_COMPLETION_MODE", "poll")
        assert mod.resolve_completion_mode("", "https://cb") == "poll"

    def test_default_with_callback_is_webhook_and_arms_a_fallback_poller(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "_DEFAULT_COMPLETION_MODE", "webhook")
        monkeypatch.setattr(mod, "_WEBHOOK_FALLBACK_SECONDS", 0.2)
        svc = mod.VideoAgentsService()
        job = svc.submit_video_job(campaign_id="MKT-S-1", provider="gemini", pipeline_type="introductions",
                                   callback_url="https://hooks.example/cb")
        assert job["poll_mode"] == "webhook"
        assert job["status"] == "processing"
        assert mod._media.submit_video_generation.call_args.kwargs["callback_url"] == "https://hooks.example/cb"
        # The webhook never comes; the fallback poller completes the job.
        assert _wait_for(lambda: mod._job_store.get(job["id"])["status"] == "completed", timeout=5)

    def test_webhook_mode_without_fallback_never_polls(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "_WEBHOOK_FALLBACK_SECONDS", 0)
        svc = mod.VideoAgentsService()
        job = svc.submit_video_job(campaign_id="MKT-S-2", provider="gemini", pipeline_type="introductions",
                                   poll_mode="webhook", callback_url="https://hooks.example/cb")
        time.sleep(0.2)
        assert mod._job_store.get(job["id"])["status"] == "processing"
        mod._media.poll_video_generation.assert_not_called()

    def test_dedupe_returns_existing_job_without_consuming_caps(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "_WEBHOOK_FALLBACK_SECONDS", 0)
        monkeypatch.setattr(mod, "_MAX_JOBS_PER_USER_PER_DAY", 1)
        svc = mod.VideoAgentsService()
        kwargs = dict(campaign_id="MKT-S-3", provider="gemini", pipeline_type="claims_assistant",
                      poll_mode="webhook", callback_url="https://hooks.example/cb", submitted_by="u1")
        first = svc.submit_video_job(**kwargs)
        assert "deduplicated" not in first
        again = svc.submit_video_job(**kwargs)
        assert again["deduplicated"] is True and again["id"] == first["id"]
        assert mod._media.submit_video_generation.call_count == 1
        assert len(mod._job_store.list_all()) == 1
        # The stored record is not polluted by the response flag.
        assert "deduplicated" not in mod._job_store.get(first["id"])
        # A different prompt is a new request — and now the cap applies.
        with pytest.raises(RuntimeError, match="Daily job limit"):
            svc.submit_video_job(**dict(kwargs, prompt_override="another cut"))
        # force bypasses dedupe (and hits the cap, proving it reached creation).
        with pytest.raises(RuntimeError, match="Daily job limit"):
            svc.submit_video_job(**dict(kwargs, force=True))
        # Failed jobs never satisfy dedupe.
        mod._job_store.mark_terminal(first["id"], {"status": "failed", "error": "x"})
        monkeypatch.setattr(mod, "_MAX_JOBS_PER_USER_PER_DAY", 5)
        fresh = svc.submit_video_job(**kwargs)
        assert fresh["id"] != first["id"] and "deduplicated" not in fresh

    def test_batch_reports_deduplicated_count(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "_WEBHOOK_FALLBACK_SECONDS", 0)
        svc = mod.VideoAgentsService()
        one = svc.submit_batch(campaign_id="MKT-S-4", provider="gemini", pipeline_type="introductions",
                               poll_mode="webhook", callback_url="https://hooks.example/cb")
        assert one["queued_count"] == 1 and one["deduplicated_count"] == 0
        two = svc.submit_batch(campaign_id="MKT-S-4", provider="gemini", pipeline_type="introductions",
                               poll_mode="webhook", callback_url="https://hooks.example/cb")
        assert two["queued_count"] == 1 and two["deduplicated_count"] == 1
        assert two["queued_jobs"][0]["id"] == one["queued_jobs"][0]["id"]

    def test_late_webhook_never_reopens_a_terminal_job(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "_WEBHOOK_FALLBACK_SECONDS", 0)
        svc = mod.VideoAgentsService()
        job = svc.submit_video_job(campaign_id="MKT-S-5", provider="gemini", pipeline_type="introductions",
                                   poll_mode="webhook", callback_url="https://hooks.example/cb")
        done = svc.handle_webhook(job["id"], {"status": "succeed", "data": {"url": "https://cdn.example.com/v.mp4"}})
        assert done["status"] == "completed"
        # A "processing" callback arriving after completion used to flip the
        # job back to processing.
        late = svc.handle_webhook(job["id"], {"status": "processing"})
        assert late["status"] == "completed"
        assert late["download_url"] == "https://cdn.example.com/v.mp4"
        again = svc.handle_webhook(job["id"], {"status": "failed", "data": {"error_message": "nope"}})
        assert again["status"] == "completed"

    def test_rearm_in_flight_jobs(self, mod, monkeypatch):
        monkeypatch.setattr(mod, "_WEBHOOK_FALLBACK_SECONDS", 0)
        monkeypatch.setattr(mod, "_POLL_INITIAL_DELAY", 0.05)
        svc = mod.VideoAgentsService()
        accepted = svc.submit_video_job(campaign_id="MKT-S-6", provider="gemini", pipeline_type="introductions",
                                        poll_mode="webhook", callback_url="https://hooks.example/cb")
        orphan = svc.submit_video_job(campaign_id="MKT-S-6", provider="gemini", pipeline_type="claims_assistant",
                                      poll_mode="webhook", callback_url="https://hooks.example/cb")
        mod._job_store.update(orphan["id"], {"provider_job_id": ""})   # never accepted by the provider
        finished = svc.submit_video_job(campaign_id="MKT-S-6", provider="gemini", pipeline_type="introductions",
                                        prompt_override="done", poll_mode="webhook", callback_url="https://hooks.example/cb")
        mod._job_store.mark_terminal(finished["id"], {"status": "completed"})

        stats = mod.rearm_in_flight_jobs()
        assert stats == {"polling": 1, "failed": 1}
        assert mod._job_store.get(orphan["id"])["status"] == "failed"
        assert _wait_for(lambda: mod._job_store.get(accepted["id"])["status"] == "completed", timeout=5)
        # Re-arming again while the first poller is alive (or finished) never doubles up.
        assert mod.rearm_in_flight_jobs() == {"polling": 0, "failed": 0}
        health = mod._video_agents_health()
        assert health["completion"]["default_mode"] in {"webhook", "poll"}
        assert isinstance(health["pollers_armed"], int)
