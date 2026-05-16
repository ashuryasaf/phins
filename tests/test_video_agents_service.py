"""
Tests for VideoAgentsService and video agents API extension handlers.

Covers:
- Job creation, listing, cancellation, retry
- Cost control enforcement
- Provider capability reporting
- Webhook processing
- API handler auth checks
- Dispatch routing
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# VideoAgentsService unit tests
# ---------------------------------------------------------------------------

class TestVideoAgentsService:
    """Unit tests for VideoAgentsService (no real provider calls)."""

    def _make_service(self):
        """Return a fresh VideoAgentsService with a clean job store."""
        # Import fresh to avoid singleton state leaking between tests
        import importlib
        import services.video_agents_service as mod
        # Reset the singleton and job store for isolation
        mod._video_agents_service = None
        mod._job_store = mod._JobStore()
        return mod.VideoAgentsService()

    def test_get_provider_capabilities_no_media_service(self):
        """When MediaGenerationService is unavailable, capabilities show disabled."""
        import services.video_agents_service as mod
        original = mod.MEDIA_GENERATION_AVAILABLE
        try:
            mod.MEDIA_GENERATION_AVAILABLE = False
            svc = self._make_service()
            caps = svc.get_provider_capabilities()
            assert caps["service_available"] is False
            assert caps["providers"]["gemini"]["enabled"] is False
            assert caps["providers"]["kling"]["enabled"] is False
            assert "pipeline_types" in caps
        finally:
            mod.MEDIA_GENERATION_AVAILABLE = original

    def test_get_provider_capabilities_with_mock_service(self):
        """Provider capabilities are forwarded from MediaGenerationService."""
        import services.video_agents_service as mod
        original = mod.MEDIA_GENERATION_AVAILABLE
        try:
            mod.MEDIA_GENERATION_AVAILABLE = True
            mock_media_svc = MagicMock()
            mock_media_svc.supported_provider_config.return_value = {
                "gemini": {"enabled": True, "label": "Gemini / Veo", "models": ["veo-3.1-generate-preview"]},
                "kling": {"enabled": False, "label": "Kling", "models": []},
            }
            with patch.object(mod, "get_media_generation_service", return_value=mock_media_svc):
                svc = self._make_service()
                caps = svc.get_provider_capabilities()
                assert caps["service_available"] is True
                assert caps["providers"]["gemini"]["enabled"] is True
                assert caps["default_provider"] == "gemini"
                assert "introductions" in caps["pipeline_types"]
        finally:
            mod.MEDIA_GENERATION_AVAILABLE = original

    def test_submit_video_job_invalid_pipeline(self):
        """Submitting with an unknown pipeline type raises ValueError."""
        svc = self._make_service()
        with pytest.raises(ValueError, match="Unsupported pipeline type"):
            svc.submit_video_job(
                campaign_id="MKT-001",
                provider="gemini",
                pipeline_type="nonexistent_pipeline",
            )

    def test_submit_video_job_provider_not_configured(self):
        """Submitting when provider is not configured marks job as failed."""
        import services.video_agents_service as mod
        original = mod.MEDIA_GENERATION_AVAILABLE
        try:
            mod.MEDIA_GENERATION_AVAILABLE = True
            mock_media_svc = MagicMock()
            mock_media_svc.supported_provider_config.return_value = {
                "gemini": {"enabled": False, "label": "Gemini / Veo", "models": []},
                "kling": {"enabled": False, "label": "Kling", "models": []},
            }
            with patch.object(mod, "get_media_generation_service", return_value=mock_media_svc):
                svc = self._make_service()
                job = svc.submit_video_job(
                    campaign_id="MKT-001",
                    provider="gemini",
                    pipeline_type="introductions",
                )
                assert job["status"] == "failed"
                assert "not configured" in job["error"].lower() or "failed" in job["message"].lower()
        finally:
            mod.MEDIA_GENERATION_AVAILABLE = original

    def test_submit_video_job_success(self):
        """Successful submission creates a processing job with provider_job_id."""
        import services.video_agents_service as mod
        original = mod.MEDIA_GENERATION_AVAILABLE
        try:
            mod.MEDIA_GENERATION_AVAILABLE = True
            mock_media_svc = MagicMock()
            mock_media_svc.supported_provider_config.return_value = {
                "gemini": {"enabled": True, "label": "Gemini / Veo", "models": []},
                "kling": {"enabled": False, "label": "Kling", "models": []},
            }
            mock_media_svc.submit_video_generation.return_value = {
                "provider": "gemini",
                "provider_job_id": "op-12345",
                "status": "queued",
                "message": "Submitted to Gemini",
                "provider_state": {"operation_name": "op-12345"},
            }
            with patch.object(mod, "get_media_generation_service", return_value=mock_media_svc):
                svc = self._make_service()
                job = svc.submit_video_job(
                    campaign_id="MKT-001",
                    provider="gemini",
                    pipeline_type="introductions",
                    poll_mode="webhook",  # avoid spawning background thread
                )
                assert job["status"] == "processing"
                assert job["provider_job_id"] == "op-12345"
                assert job["campaign_id"] == "MKT-001"
                assert job["pipeline_type"] == "introductions"
        finally:
            mod.MEDIA_GENERATION_AVAILABLE = original

    def test_submit_batch_all_pipelines(self):
        """Batch submission without pipeline_type submits all 5 pipeline types."""
        import services.video_agents_service as mod
        original = mod.MEDIA_GENERATION_AVAILABLE
        try:
            mod.MEDIA_GENERATION_AVAILABLE = True
            mock_media_svc = MagicMock()
            mock_media_svc.supported_provider_config.return_value = {
                "gemini": {"enabled": True, "label": "Gemini / Veo", "models": []},
                "kling": {"enabled": False, "label": "Kling", "models": []},
            }
            mock_media_svc.submit_video_generation.return_value = {
                "provider": "gemini",
                "provider_job_id": "op-batch",
                "status": "queued",
                "message": "Submitted",
                "provider_state": {},
            }
            with patch.object(mod, "get_media_generation_service", return_value=mock_media_svc):
                svc = self._make_service()
                result = svc.submit_batch(
                    campaign_id="MKT-002",
                    provider="gemini",
                    poll_mode="webhook",
                )
                assert result["queued_count"] == 5
                assert len(result["queued_jobs"]) == 5
                pipeline_types = {j["pipeline_type"] for j in result["queued_jobs"]}
                assert "introductions" in pipeline_types
                assert "claims_assistant" in pipeline_types
        finally:
            mod.MEDIA_GENERATION_AVAILABLE = original

    def test_submit_batch_single_pipeline(self):
        """Batch submission with pipeline_type submits only that pipeline."""
        import services.video_agents_service as mod
        original = mod.MEDIA_GENERATION_AVAILABLE
        try:
            mod.MEDIA_GENERATION_AVAILABLE = True
            mock_media_svc = MagicMock()
            mock_media_svc.supported_provider_config.return_value = {
                "gemini": {"enabled": True, "label": "Gemini / Veo", "models": []},
                "kling": {"enabled": False, "label": "Kling", "models": []},
            }
            mock_media_svc.submit_video_generation.return_value = {
                "provider": "gemini",
                "provider_job_id": "op-single",
                "status": "queued",
                "message": "Submitted",
                "provider_state": {},
            }
            with patch.object(mod, "get_media_generation_service", return_value=mock_media_svc):
                svc = self._make_service()
                result = svc.submit_batch(
                    campaign_id="MKT-003",
                    provider="gemini",
                    pipeline_type="claims_assistant",
                    poll_mode="webhook",
                )
                assert result["queued_count"] == 1
                assert result["queued_jobs"][0]["pipeline_type"] == "claims_assistant"
        finally:
            mod.MEDIA_GENERATION_AVAILABLE = original

    def test_cost_control_user_daily_limit(self):
        """Exceeding per-user daily job limit raises RuntimeError."""
        import services.video_agents_service as mod
        original_limit = mod._MAX_JOBS_PER_USER_PER_DAY
        original = mod.MEDIA_GENERATION_AVAILABLE
        try:
            mod._MAX_JOBS_PER_USER_PER_DAY = 2
            mod.MEDIA_GENERATION_AVAILABLE = True
            mock_media_svc = MagicMock()
            mock_media_svc.supported_provider_config.return_value = {
                "gemini": {"enabled": True, "label": "Gemini / Veo", "models": []},
                "kling": {"enabled": False, "label": "Kling", "models": []},
            }
            mock_media_svc.submit_video_generation.return_value = {
                "provider": "gemini",
                "provider_job_id": "op-x",
                "status": "queued",
                "message": "Submitted",
                "provider_state": {},
            }
            with patch.object(mod, "get_media_generation_service", return_value=mock_media_svc):
                svc = self._make_service()
                # Submit 2 jobs (at limit)
                for _ in range(2):
                    svc.submit_video_job(
                        campaign_id="MKT-004",
                        provider="gemini",
                        pipeline_type="introductions",
                        submitted_by="test_user",
                        poll_mode="webhook",
                    )
                # Third should fail
                with pytest.raises(RuntimeError, match="Daily job limit"):
                    svc.submit_video_job(
                        campaign_id="MKT-004",
                        provider="gemini",
                        pipeline_type="introductions",
                        submitted_by="test_user",
                        poll_mode="webhook",
                    )
        finally:
            mod._MAX_JOBS_PER_USER_PER_DAY = original_limit
            mod.MEDIA_GENERATION_AVAILABLE = original

    def test_list_jobs_by_campaign(self):
        """list_jobs filters correctly by campaign_id."""
        import services.video_agents_service as mod
        original = mod.MEDIA_GENERATION_AVAILABLE
        try:
            mod.MEDIA_GENERATION_AVAILABLE = True
            mock_media_svc = MagicMock()
            mock_media_svc.supported_provider_config.return_value = {
                "gemini": {"enabled": True, "label": "Gemini / Veo", "models": []},
                "kling": {"enabled": False, "label": "Kling", "models": []},
            }
            mock_media_svc.submit_video_generation.return_value = {
                "provider": "gemini",
                "provider_job_id": "op-list",
                "status": "queued",
                "message": "Submitted",
                "provider_state": {},
            }
            with patch.object(mod, "get_media_generation_service", return_value=mock_media_svc):
                svc = self._make_service()
                svc.submit_video_job(
                    campaign_id="MKT-A",
                    provider="gemini",
                    pipeline_type="introductions",
                    poll_mode="webhook",
                )
                svc.submit_video_job(
                    campaign_id="MKT-B",
                    provider="gemini",
                    pipeline_type="claims_assistant",
                    poll_mode="webhook",
                )
                result_a = svc.list_jobs(campaign_id="MKT-A")
                assert result_a["total"] == 1
                assert result_a["jobs"][0]["campaign_id"] == "MKT-A"

                result_b = svc.list_jobs(campaign_id="MKT-B")
                assert result_b["total"] == 1
                assert result_b["jobs"][0]["campaign_id"] == "MKT-B"

                result_all = svc.list_jobs()
                assert result_all["total"] == 2
        finally:
            mod.MEDIA_GENERATION_AVAILABLE = original

    def test_cancel_job(self):
        """Cancelling a processing job sets status to cancelled."""
        import services.video_agents_service as mod
        original = mod.MEDIA_GENERATION_AVAILABLE
        try:
            mod.MEDIA_GENERATION_AVAILABLE = True
            mock_media_svc = MagicMock()
            mock_media_svc.supported_provider_config.return_value = {
                "gemini": {"enabled": True, "label": "Gemini / Veo", "models": []},
                "kling": {"enabled": False, "label": "Kling", "models": []},
            }
            mock_media_svc.submit_video_generation.return_value = {
                "provider": "gemini",
                "provider_job_id": "op-cancel",
                "status": "queued",
                "message": "Submitted",
                "provider_state": {},
            }
            with patch.object(mod, "get_media_generation_service", return_value=mock_media_svc):
                svc = self._make_service()
                job = svc.submit_video_job(
                    campaign_id="MKT-C",
                    provider="gemini",
                    pipeline_type="introductions",
                    poll_mode="webhook",
                )
                job_id = job["id"]
                cancelled = svc.cancel_job(job_id, cancelled_by="test_admin")
                assert cancelled["status"] == "cancelled"
                assert "test_admin" in cancelled["message"]
        finally:
            mod.MEDIA_GENERATION_AVAILABLE = original

    def test_cancel_completed_job_is_noop(self):
        """Cancelling a completed job returns it unchanged."""
        import services.video_agents_service as mod
        # Directly inject a completed job
        mod._job_store = mod._JobStore()
        from datetime import datetime, timezone
        import uuid
        job_id = str(uuid.uuid4())
        job = {
            "id": job_id,
            "status": "completed",
            "campaign_id": "MKT-D",
            "pipeline_type": "introductions",
            "asset_name": "Test",
            "provider": "gemini",
            "provider_model": "",
            "prompt": "test",
            "aspect_ratio": "16:9",
            "duration_seconds": 8,
            "resolution": "720p",
            "image_data_url": "",
            "reference_image_asset_id": "",
            "poll_mode": "poll",
            "auto_publish_to_hero": False,
            "callback_url": "",
            "submitted_by": "admin",
            "blueprint_index": 0,
            "metadata": {},
            "progress_pct": 100,
            "message": "Done",
            "provider_job_id": "op-done",
            "provider_state": {},
            "download_url": "https://example.com/video.mp4",
            "generated_asset_id": "",
            "error": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        mod._job_store.add(job)
        svc = mod.VideoAgentsService()
        result = svc.cancel_job(job_id)
        assert result["status"] == "completed"  # unchanged

    def test_webhook_completed(self):
        """Webhook with completed status updates job to completed."""
        import services.video_agents_service as mod
        mod._job_store = mod._JobStore()
        from datetime import datetime, timezone
        import uuid
        job_id = str(uuid.uuid4())
        job = {
            "id": job_id,
            "status": "processing",
            "campaign_id": "MKT-E",
            "pipeline_type": "introductions",
            "asset_name": "Test",
            "provider": "kling",
            "provider_model": "",
            "prompt": "test",
            "aspect_ratio": "16:9",
            "duration_seconds": 8,
            "resolution": "720p",
            "image_data_url": "",
            "reference_image_asset_id": "",
            "poll_mode": "webhook",
            "auto_publish_to_hero": False,
            "callback_url": "",
            "submitted_by": "admin",
            "blueprint_index": 0,
            "metadata": {},
            "progress_pct": 10,
            "message": "Processing",
            "provider_job_id": "kling-task-001",
            "provider_state": {},
            "download_url": "",
            "generated_asset_id": "",
            "error": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": "",
        }
        mod._job_store.add(job)
        svc = mod.VideoAgentsService()
        webhook_payload = {
            "status": "succeed",
            "data": {
                "works": [
                    {"url": "https://cdn.kling.ai/video.mp4"}
                ]
            }
        }
        updated = svc.handle_webhook(job_id, webhook_payload)
        assert updated["status"] == "completed"
        assert updated["download_url"] == "https://cdn.kling.ai/video.mp4"
        assert updated["progress_pct"] == 100

    def test_webhook_failed(self):
        """Webhook with failed status updates job to failed."""
        import services.video_agents_service as mod
        mod._job_store = mod._JobStore()
        from datetime import datetime, timezone
        import uuid
        job_id = str(uuid.uuid4())
        job = {
            "id": job_id,
            "status": "processing",
            "campaign_id": "MKT-F",
            "pipeline_type": "introductions",
            "asset_name": "Test",
            "provider": "kling",
            "provider_model": "",
            "prompt": "test",
            "aspect_ratio": "16:9",
            "duration_seconds": 8,
            "resolution": "720p",
            "image_data_url": "",
            "reference_image_asset_id": "",
            "poll_mode": "webhook",
            "auto_publish_to_hero": False,
            "callback_url": "",
            "submitted_by": "admin",
            "blueprint_index": 0,
            "metadata": {},
            "progress_pct": 10,
            "message": "Processing",
            "provider_job_id": "kling-task-002",
            "provider_state": {},
            "download_url": "",
            "generated_asset_id": "",
            "error": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": "",
        }
        mod._job_store.add(job)
        svc = mod.VideoAgentsService()
        webhook_payload = {
            "status": "failed",
            "data": {"error_message": "Content policy violation"}
        }
        updated = svc.handle_webhook(job_id, webhook_payload)
        assert updated["status"] == "failed"
        assert "Content policy violation" in updated["error"]

    def test_download_not_completed_raises(self):
        """Downloading a non-completed job raises ValueError."""
        import services.video_agents_service as mod
        mod._job_store = mod._JobStore()
        from datetime import datetime, timezone
        import uuid
        job_id = str(uuid.uuid4())
        job = {
            "id": job_id,
            "status": "processing",
            "campaign_id": "MKT-G",
            "pipeline_type": "introductions",
            "asset_name": "Test",
            "provider": "gemini",
            "provider_model": "",
            "prompt": "test",
            "aspect_ratio": "16:9",
            "duration_seconds": 8,
            "resolution": "720p",
            "image_data_url": "",
            "reference_image_asset_id": "",
            "poll_mode": "poll",
            "auto_publish_to_hero": False,
            "callback_url": "",
            "submitted_by": "admin",
            "blueprint_index": 0,
            "metadata": {},
            "progress_pct": 50,
            "message": "Processing",
            "provider_job_id": "op-dl",
            "provider_state": {},
            "download_url": "",
            "generated_asset_id": "",
            "error": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": "",
        }
        mod._job_store.add(job)
        svc = mod.VideoAgentsService()
        with pytest.raises(ValueError, match="not completed"):
            svc.download_job_video(job_id)


# ---------------------------------------------------------------------------
# API extension handler tests
# ---------------------------------------------------------------------------

class TestVideoAgentsHandlers:
    """Tests for the api_extensions handler functions."""

    def _admin_session(self) -> Dict[str, Any]:
        return {"username": "admin", "role": "admin"}

    def _media_session(self) -> Dict[str, Any]:
        return {"username": "media_user", "role": "media"}

    def _customer_session(self) -> Dict[str, Any]:
        return {"username": "customer1", "role": "customer"}

    def test_require_admin_or_media_no_session(self):
        from web_portal.api_extensions import _require_admin_or_media
        result = _require_admin_or_media(None)
        assert result is not None
        status, body = result
        assert status == 401

    def test_require_admin_or_media_wrong_role(self):
        from web_portal.api_extensions import _require_admin_or_media
        result = _require_admin_or_media(self._customer_session())
        assert result is not None
        status, body = result
        assert status == 403

    def test_require_admin_or_media_admin_ok(self):
        from web_portal.api_extensions import _require_admin_or_media
        result = _require_admin_or_media(self._admin_session())
        assert result is None

    def test_require_admin_or_media_media_ok(self):
        from web_portal.api_extensions import _require_admin_or_media
        result = _require_admin_or_media(self._media_session())
        assert result is None

    def test_handle_video_providers_no_auth(self):
        from web_portal.api_extensions import handle_video_providers
        status, body = handle_video_providers(None)
        assert status == 401

    def test_handle_video_providers_wrong_role(self):
        from web_portal.api_extensions import handle_video_providers
        status, body = handle_video_providers(self._customer_session())
        assert status == 403

    def test_handle_video_providers_success(self):
        from web_portal.api_extensions import handle_video_providers
        import services.video_agents_service as mod
        original = mod.MEDIA_GENERATION_AVAILABLE
        try:
            mod.MEDIA_GENERATION_AVAILABLE = False
            status, body = handle_video_providers(self._admin_session())
            assert status == 200
            assert "capabilities" in body
        finally:
            mod.MEDIA_GENERATION_AVAILABLE = original

    def test_handle_video_jobs_list_no_auth(self):
        from web_portal.api_extensions import handle_video_jobs_list
        status, body = handle_video_jobs_list(None, {})
        assert status == 401

    def test_handle_video_jobs_list_success(self):
        from web_portal.api_extensions import handle_video_jobs_list
        import services.video_agents_service as mod
        mod._job_store = mod._JobStore()
        status, body = handle_video_jobs_list(self._admin_session(), {"campaign_id": ["MKT-TEST"]})
        assert status == 200
        assert "jobs" in body
        assert body["total"] == 0

    def test_handle_video_jobs_batch_no_campaign(self):
        from web_portal.api_extensions import handle_video_jobs_batch
        status, body = handle_video_jobs_batch(self._admin_session(), {})
        assert status == 400
        assert "campaign_id" in body["error"]

    def test_handle_video_jobs_retry_no_job_id(self):
        from web_portal.api_extensions import handle_video_jobs_retry
        status, body = handle_video_jobs_retry(self._admin_session(), {})
        assert status == 400
        assert "job_id" in body["error"]

    def test_handle_video_jobs_cancel_no_job_id(self):
        from web_portal.api_extensions import handle_video_jobs_cancel
        status, body = handle_video_jobs_cancel(self._admin_session(), {})
        assert status == 400
        assert "job_id" in body["error"]

    def test_handle_video_job_get_not_found(self):
        from web_portal.api_extensions import handle_video_job_get
        import services.video_agents_service as mod
        mod._job_store = mod._JobStore()
        status, body = handle_video_job_get(self._admin_session(), "nonexistent-job-id")
        assert status == 404

    def test_handle_video_job_download_not_found(self):
        from web_portal.api_extensions import handle_video_job_download
        import services.video_agents_service as mod
        mod._job_store = mod._JobStore()
        status, body = handle_video_job_download(self._admin_session(), "nonexistent-job-id")
        assert status == 404

    def test_handle_video_webhook_not_found(self):
        from web_portal.api_extensions import handle_video_webhook
        import services.video_agents_service as mod
        mod._job_store = mod._JobStore()
        status, body = handle_video_webhook(None, "nonexistent-job-id", {})
        assert status == 404


# ---------------------------------------------------------------------------
# Dispatch routing tests
# ---------------------------------------------------------------------------

class TestVideoAgentsDispatch:
    """Tests that dispatch_get and dispatch_post route to video agent handlers."""

    def _admin_session(self) -> Dict[str, Any]:
        return {"username": "admin", "role": "admin"}

    def test_dispatch_get_video_jobs(self):
        """The frontend path /api/admin/media/video-jobs is owned by server.py.

        The api_extensions GET dispatcher must NOT intercept it, otherwise the
        in-memory _JobStore (empty) would be served instead of the real
        MEDIA_PROCESSING_JOBS where finalize + checksum happen.
        """
        from web_portal.api_extensions import dispatch_get
        import services.video_agents_service as mod
        mod._job_store = mod._JobStore()
        result = dispatch_get(
            "/api/admin/media/video-jobs",
            self._admin_session(),
            {"campaign_id": ["MKT-X"]},
            "127.0.0.1",
        )
        assert result is None

    def test_dispatch_get_video_agents_jobs(self):
        from web_portal.api_extensions import dispatch_get
        import services.video_agents_service as mod
        mod._job_store = mod._JobStore()
        result = dispatch_get(
            "/api/admin/media/video-agents/jobs",
            self._admin_session(),
            {},
            "127.0.0.1",
        )
        assert result is not None
        status, body = result
        assert status == 200

    def test_dispatch_get_video_job_by_id(self):
        from web_portal.api_extensions import dispatch_get
        import services.video_agents_service as mod
        mod._job_store = mod._JobStore()
        result = dispatch_get(
            "/api/admin/media/video-agents/jobs/some-job-id",
            self._admin_session(),
            {},
            "127.0.0.1",
        )
        assert result is not None
        status, body = result
        assert status == 404  # job doesn't exist

    def test_dispatch_get_video_job_download(self):
        from web_portal.api_extensions import dispatch_get
        import services.video_agents_service as mod
        mod._job_store = mod._JobStore()
        result = dispatch_get(
            "/api/admin/media/video-agents/jobs/some-job-id/download",
            self._admin_session(),
            {},
            "127.0.0.1",
        )
        assert result is not None
        status, body = result
        assert status == 404  # job doesn't exist

    def test_dispatch_post_video_providers(self):
        from web_portal.api_extensions import dispatch_post
        import services.video_agents_service as mod
        original = mod.MEDIA_GENERATION_AVAILABLE
        try:
            mod.MEDIA_GENERATION_AVAILABLE = False
            result = dispatch_post(
                "/api/admin/media/video-providers",
                self._admin_session(),
                {},
                "127.0.0.1",
            )
            assert result is not None
            status, body = result
            assert status == 200
            assert "capabilities" in body
        finally:
            mod.MEDIA_GENERATION_AVAILABLE = original

    def test_dispatch_post_video_jobs_batch_no_campaign(self):
        from web_portal.api_extensions import dispatch_post
        result = dispatch_post(
            "/api/admin/media/video-jobs/batch",
            self._admin_session(),
            {},
            "127.0.0.1",
        )
        assert result is not None
        status, body = result
        assert status == 400

    def test_dispatch_post_video_jobs_retry_no_job_id(self):
        from web_portal.api_extensions import dispatch_post
        result = dispatch_post(
            "/api/admin/media/video-jobs/retry",
            self._admin_session(),
            {},
            "127.0.0.1",
        )
        assert result is not None
        status, body = result
        assert status == 400

    def test_dispatch_post_video_jobs_cancel_no_job_id(self):
        from web_portal.api_extensions import dispatch_post
        result = dispatch_post(
            "/api/admin/media/video-jobs/cancel",
            self._admin_session(),
            {},
            "127.0.0.1",
        )
        assert result is not None
        status, body = result
        assert status == 400

    def test_dispatch_post_video_agents_submit_invalid_pipeline(self):
        from web_portal.api_extensions import dispatch_post
        import services.video_agents_service as mod
        mod._job_store = mod._JobStore()
        result = dispatch_post(
            "/api/admin/media/video-agents/submit",
            self._admin_session(),
            {"campaign_id": "MKT-001", "provider": "gemini", "pipeline_type": "bad_pipeline"},
            "127.0.0.1",
        )
        assert result is not None
        status, body = result
        assert status == 400

    def test_dispatch_post_webhook(self):
        from web_portal.api_extensions import dispatch_post
        import services.video_agents_service as mod
        mod._job_store = mod._JobStore()
        result = dispatch_post(
            "/api/admin/media/video-agents/jobs/nonexistent-id/webhook",
            None,  # webhooks may arrive without session
            {"status": "succeed"},
            "127.0.0.1",
        )
        assert result is not None
        status, body = result
        assert status == 404  # job doesn't exist

    def test_unrelated_paths_return_none(self):
        """Paths not handled by video agents return None from dispatchers."""
        from web_portal.api_extensions import dispatch_get, dispatch_post
        assert dispatch_get("/api/some/other/path", {}, {}, "127.0.0.1") is None
        assert dispatch_post("/api/some/other/path", {}, {}, "127.0.0.1") is None
