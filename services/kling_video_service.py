"""
PHINS Kling Video Service
=========================

Dedicated Kling API client for generating video agents and campaigns.

Wraps the MediaGenerationService with Kling-specific helpers and provides
a clean interface for:
  - Authenticating with KLING_ACCESS_KEY + KLING_SECRET_KEY (JWT) or KLING_API_KEY
  - Submitting text-to-video and image-to-video generation jobs
  - Polling job status
  - Listing generated videos
  - Handling async completion via webhook or polling modes

Environment variables:
  KLING_API_BASE_URL   - Base URL (default: https://api.klingapi.com)
  KLING_ACCESS_KEY     - Access key for JWT auth
  KLING_SECRET_KEY     - Secret key for JWT auth
  KLING_API_KEY        - Direct API key (alternative to access/secret pair)
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from services.media_generation_service import (
    MediaGenerationService,
    MediaGenerationError,
    get_media_generation_service,
)


class KlingVideoService:
    """
    Dedicated Kling video generation service for PHINS insurance workflows.

    Supports all five pipeline templates:
      - introductions
      - regulatory_presentations
      - application_assistant
      - underwriting_assistant
      - claims_assistant
    """

    PIPELINE_PROMPTS: Dict[str, str] = {
        "introductions": (
            "Create a polished, professional introduction video for PHINS insurance. "
            "Welcome customers, partners, and stakeholders with a warm, trustworthy tone. "
            "Highlight the platform's commitment to transparent, customer-first insurance."
        ),
        "regulatory_presentations": (
            "Create a clear, compliance-ready regulatory and board presentation video. "
            "Use a formal, authoritative tone suitable for regulators, board members, and "
            "governance committees. Include traceable, auditable messaging."
        ),
        "application_assistant": (
            "Create an application-assistant video guiding applicants through the insurance "
            "application process. Explain data capture, supporting documents, and "
            "pre-underwriting expectations in a clear, step-by-step format."
        ),
        "underwriting_assistant": (
            "Create an underwriting-assistant explainer video covering evidence requirements, "
            "risk review steps, and case status updates. Use a professional, reassuring tone "
            "that builds applicant confidence during the underwriting process."
        ),
        "claims_assistant": (
            "Create a claims-assistant video walking claimants through document collection, "
            "ADL review, claim stages, and payout checkpoints. Use a calm, empathetic tone "
            "that supports claimants through a potentially stressful process."
        ),
    }

    DEFAULT_MODELS: List[str] = ["kling-v2.6-pro", "kling-v2.6-std"]

    def __init__(self) -> None:
        self._access_key = os.environ.get("KLING_ACCESS_KEY", "").strip()
        self._secret_key = os.environ.get("KLING_SECRET_KEY", "").strip()
        self._api_key = os.environ.get("KLING_API_KEY", "").strip()
        self._base_url = os.environ.get(
            "KLING_API_BASE_URL", "https://api.klingapi.com"
        ).strip().rstrip("/")

    # ------------------------------------------------------------------
    # Credential helpers
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Return True when Kling credentials are available."""
        return bool(self._api_key) or bool(self._access_key and self._secret_key)

    def provider_config(self) -> Dict[str, Any]:
        """Return public provider configuration for the capabilities endpoint."""
        return {
            "enabled": self.is_configured(),
            "label": "Kling",
            "base_url": self._base_url,
            "models": list(self.DEFAULT_MODELS),
            "auth_method": (
                "api_key" if self._api_key
                else "access_secret_jwt" if self.is_configured()
                else "not_configured"
            ),
        }

    # ------------------------------------------------------------------
    # Video generation
    # ------------------------------------------------------------------

    def generate_video(
        self,
        *,
        prompt: str,
        title: str,
        pipeline_type: str = "introductions",
        model: str = "",
        aspect_ratio: str = "16:9",
        duration_seconds: int = 8,
        image_data_url: str = "",
        callback_url: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Submit a Kling video generation job.

        Returns a dict with:
          provider, provider_job_id, status, message, provider_state
        """
        if not self.is_configured():
            raise MediaGenerationError(
                "Kling credentials are not configured. "
                "Set KLING_ACCESS_KEY + KLING_SECRET_KEY or KLING_API_KEY."
            )

        effective_prompt = str(prompt or "").strip()
        if not effective_prompt:
            pipeline_key = str(pipeline_type or "introductions").strip().lower()
            effective_prompt = self.PIPELINE_PROMPTS.get(
                pipeline_key, self.PIPELINE_PROMPTS["introductions"]
            )

        svc = get_media_generation_service()
        return svc.submit_video_generation(
            provider="kling",
            prompt=effective_prompt,
            title=title,
            model=model or self.DEFAULT_MODELS[0],
            aspect_ratio=aspect_ratio,
            duration_seconds=duration_seconds,
            image_data_url=image_data_url,
            callback_url=callback_url,
            metadata=metadata or {},
        )

    def get_video_status(
        self,
        *,
        provider_job_id: str,
        provider_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Poll the status of a previously submitted Kling video job.

        Returns a dict with:
          status (queued|processing|completed|failed),
          provider_job_id, message, [download_url], provider_state
        """
        if not self.is_configured():
            raise MediaGenerationError(
                "Kling credentials are not configured. "
                "Set KLING_ACCESS_KEY + KLING_SECRET_KEY or KLING_API_KEY."
            )
        if not provider_job_id:
            raise MediaGenerationError("provider_job_id is required")

        svc = get_media_generation_service()
        return svc.poll_video_generation(
            provider="kling",
            provider_job_id=provider_job_id,
            provider_state=provider_state or {},
        )

    def list_videos(
        self,
        *,
        campaign_id: str = "",
        pipeline_type: str = "",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        Return a summary of Kling video jobs filtered by campaign or pipeline.

        This is a metadata-only operation — it does not call the Kling API
        directly. Job tracking is managed by the PHINS media processing layer.
        """
        return {
            "provider": "kling",
            "configured": self.is_configured(),
            "base_url": self._base_url,
            "filter": {
                "campaign_id": campaign_id,
                "pipeline_type": pipeline_type,
                "limit": limit,
            },
            "note": (
                "Use GET /api/admin/media/video-jobs?campaign_id=<id> "
                "to list tracked video jobs."
            ),
        }

    # ------------------------------------------------------------------
    # Webhook helpers
    # ------------------------------------------------------------------

    def parse_webhook_payload(self, raw_body: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse and normalise a Kling completion webhook payload.

        Kling sends a POST to the callBackUrl when a job completes.
        This method extracts the canonical fields regardless of the
        exact response shape used by the Kling API version.
        """
        data = raw_body.get("data") if isinstance(raw_body.get("data"), dict) else raw_body

        task_id = str(
            raw_body.get("task_id")
            or data.get("task_id")
            or data.get("id")
            or data.get("job_id")
            or ""
        ).strip()

        status_raw = str(
            raw_body.get("status")
            or data.get("status")
            or data.get("task_status")
            or data.get("state")
            or ""
        ).strip().lower()

        # Normalise Kling status values to PHINS canonical statuses
        if status_raw in {"succeed", "succeeded", "completed", "done", "ready", "complete"}:
            status = "completed"
        elif status_raw in {"failed", "error", "cancelled", "aborted", "rejected"}:
            status = "failed"
        elif status_raw in {"queued", "pending", "submitted", "created"}:
            status = "queued"
        else:
            status = "processing"

        # Extract download URL from various response shapes
        download_url = ""
        works = data.get("works") if isinstance(data.get("works"), list) else []
        for work in works:
            if not isinstance(work, dict):
                continue
            resource = work.get("resource") if isinstance(work.get("resource"), dict) else {}
            candidate = str(
                work.get("url")
                or work.get("video_url")
                or work.get("download_url")
                or resource.get("resource")
                or resource.get("url")
                or ""
            ).strip()
            if candidate:
                download_url = candidate
                break

        if not download_url:
            task_result = data.get("task_result") if isinstance(data.get("task_result"), dict) else {}
            for tv in (task_result.get("videos") or []):
                if isinstance(tv, dict):
                    candidate = str(tv.get("url") or tv.get("video_url") or tv.get("download_url") or "").strip()
                    if candidate:
                        download_url = candidate
                        break

        if not download_url:
            download_url = str(
                data.get("url")
                or data.get("video_url")
                or data.get("download_url")
                or ""
            ).strip()

        error_message = ""
        if status == "failed":
            error_obj = data.get("error") if isinstance(data.get("error"), dict) else {}
            error_message = str(
                data.get("error_message")
                or error_obj.get("message")
                or data.get("message")
                or "Kling generation failed"
            )

        return {
            "provider": "kling",
            "provider_job_id": task_id,
            "status": status,
            "download_url": download_url,
            "error": error_message,
            "raw": raw_body,
        }


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_kling_video_service: Optional[KlingVideoService] = None


def get_kling_video_service() -> KlingVideoService:
    """Return the singleton KlingVideoService instance."""
    global _kling_video_service
    if _kling_video_service is None:
        _kling_video_service = KlingVideoService()
    return _kling_video_service


def reset_kling_video_service() -> None:
    """Reset the singleton (useful for tests that change env vars)."""
    global _kling_video_service
    _kling_video_service = None
