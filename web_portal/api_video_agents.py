"""
PHINS Video Agents API
======================

API handlers for video agent generation, job tracking, and provider capabilities.

Endpoints handled:
  GET  /api/admin/media/video-providers          - Provider capabilities + Kling config
  GET  /api/admin/media/video-agents/generate    - Generate video agents (alias)
  POST /api/admin/media/video-agents/generate    - Queue a single video agent job
  GET  /api/admin/media/video-agents/jobs        - List video agent jobs
  GET  /api/admin/media/video-agents/jobs/{id}   - Get job status
  POST /api/admin/media/video-agents/webhook     - Receive Kling completion webhooks

These handlers are called from web_portal/server.py dispatch_get / dispatch_post.
They share the MEDIA_ASSETS, MEDIA_PROCESSING_JOBS, and DESIGN_SETTINGS stores
that live in server.py.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Service imports (graceful degradation)
# ---------------------------------------------------------------------------

try:
    from services.kling_video_service import get_kling_video_service
    KLING_SERVICE_AVAILABLE = True
except ImportError:
    KLING_SERVICE_AVAILABLE = False

try:
    from services.media_generation_service import (
        get_media_generation_service,
        MediaGenerationError,
    )
    MEDIA_GENERATION_AVAILABLE = True
except ImportError:
    MEDIA_GENERATION_AVAILABLE = False
    MediaGenerationError = RuntimeError  # type: ignore[misc,assignment]


# ---------------------------------------------------------------------------
# Pipeline prompt templates
# ---------------------------------------------------------------------------

PIPELINE_PROMPTS: Dict[str, str] = {
    "introductions": (
        "Create a polished introduction video for PHINS insurance. "
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


def _pipeline_prompt(pipeline_type: str, override: str = "") -> str:
    """Return the effective prompt for a pipeline type."""
    if override and str(override).strip():
        return str(override).strip()
    key = str(pipeline_type or "introductions").strip().lower()
    return PIPELINE_PROMPTS.get(key, PIPELINE_PROMPTS["introductions"])


# ---------------------------------------------------------------------------
# Provider capabilities
# ---------------------------------------------------------------------------

def handle_video_providers(session: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """
    GET /api/admin/media/video-providers

    Returns provider availability, models, and configuration for the
    video-agents.html frontend.
    """
    role = str(session.get("role") or "").lower()
    if role not in {"admin", "media", "marketing"}:
        return 403, {"error": "Admin or Media role required"}

    providers: Dict[str, Any] = {}

    # Gemini / Veo
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    providers["gemini"] = {
        "enabled": bool(gemini_key),
        "label": "Gemini / Veo",
        "models": ["veo-3.1-generate-preview", "veo-3-fast-preview"],
        "model": os.environ.get("PHINS_GEMINI_VIDEO_MODEL", "veo-3.1-generate-preview").strip(),
    }

    # Kling
    kling_api_key = os.environ.get("KLING_API_KEY", "").strip()
    kling_access_key = os.environ.get("KLING_ACCESS_KEY", "").strip()
    kling_secret_key = os.environ.get("KLING_SECRET_KEY", "").strip()
    kling_base_url = os.environ.get("KLING_API_BASE_URL", "https://api.klingapi.com").strip().rstrip("/")
    kling_enabled = bool(kling_api_key) or bool(kling_access_key and kling_secret_key)

    providers["kling"] = {
        "enabled": kling_enabled,
        "label": "Kling",
        "base_url": kling_base_url,
        "models": ["kling-v2.6-pro", "kling-v2.6-std"],
        "auth_method": (
            "api_key" if kling_api_key
            else "access_secret_jwt" if kling_enabled
            else "not_configured"
        ),
    }

    # Determine default provider
    default_provider = "gemini"
    if not providers["gemini"]["enabled"] and providers["kling"]["enabled"]:
        default_provider = "kling"

    return 200, {
        "success": True,
        "capabilities": {
            "providers": providers,
            "default_provider": default_provider,
        },
    }


# ---------------------------------------------------------------------------
# Video agent job generation
# ---------------------------------------------------------------------------

def handle_generate_video_agent(
    session: Dict[str, Any],
    body: Dict[str, Any],
    media_assets: Dict[str, Any],
    media_processing_jobs: Dict[str, Any],
    design_settings: Dict[str, Any],
    base_url: str = "",
) -> Tuple[int, Dict[str, Any]]:
    """
    POST /api/admin/media/video-agents/generate

    Queue a single video agent generation job for a specific pipeline type.
    """
    role = str(session.get("role") or "").lower()
    if role not in {"admin", "media", "marketing"}:
        return 403, {"error": "Admin or Media role required"}

    if not MEDIA_GENERATION_AVAILABLE:
        return 503, {"error": "Media generation service not available"}

    campaign_id = str(body.get("campaign_id") or "").strip()
    pipeline_type = str(body.get("pipeline_type") or "introductions").strip().lower()
    provider = str(body.get("provider") or "kling").strip().lower()
    model = str(body.get("model") or body.get("provider_model") or "").strip()
    prompt_override = str(body.get("prompt") or body.get("prompt_override") or "").strip()
    image_data_url = str(body.get("image_data_url") or "").strip()
    reference_image_asset_id = str(body.get("reference_image_asset_id") or "").strip()
    poll_mode = str(body.get("poll_mode") or "poll").strip().lower()
    auto_publish = bool(body.get("auto_publish_to_hero", False))

    if not campaign_id:
        return 400, {"error": "campaign_id is required"}

    # Resolve reference image from media assets
    if reference_image_asset_id and not image_data_url:
        ref_asset = media_assets.get(reference_image_asset_id)
        if ref_asset:
            image_data_url = str(ref_asset.get("data") or ref_asset.get("url") or "").strip()

    # Build prompt
    prompt = _pipeline_prompt(pipeline_type, prompt_override)

    # Build job record
    job_id = f"vaj-{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()

    # Build callback URL for webhook mode
    callback_path = ""
    callback_url = ""
    if poll_mode == "webhook" and base_url:
        callback_path = f"/api/admin/media/video-agents/webhook?job_id={job_id}"
        callback_url = f"{base_url}{callback_path}"

    # Submit to provider
    try:
        svc = get_media_generation_service()
        submit_result = svc.submit_video_generation(
            provider=provider,
            prompt=prompt,
            title=f"{pipeline_type.replace('_', ' ').title()} - {campaign_id}",
            model=model,
            aspect_ratio="16:9",
            duration_seconds=8,
            image_data_url=image_data_url,
            callback_url=callback_url,
            metadata={
                "campaign_id": campaign_id,
                "pipeline_type": pipeline_type,
                "job_id": job_id,
            },
        )
    except MediaGenerationError as exc:
        return 503, {"error": str(exc)}
    except Exception as exc:
        return 500, {"error": f"Video generation failed: {exc}"}

    job = {
        "id": job_id,
        "job_kind": "video_agent",
        "campaign_id": campaign_id,
        "pipeline_type": pipeline_type,
        "provider": provider,
        "provider_model": model,
        "provider_job_id": submit_result.get("provider_job_id", ""),
        "provider_state": submit_result.get("provider_state", {}),
        "status": "queued",
        "progress_pct": 0,
        "message": submit_result.get("message", "Queued"),
        "prompt": prompt,
        "image_data_url": image_data_url,
        "reference_image_asset_id": reference_image_asset_id,
        "poll_mode": poll_mode,
        "callback_path": callback_path,
        "callback_url": callback_url,
        "auto_publish_to_hero": auto_publish,
        "asset_name": f"{pipeline_type.replace('_', ' ').title()} Video",
        "generated_asset_id": "",
        "download_url": "",
        "created_at": now_iso,
        "updated_at": now_iso,
        "created_by": str(session.get("username") or "admin"),
    }

    media_processing_jobs[job_id] = job

    return 202, {
        "success": True,
        "job": _serialize_job(job),
        "message": f"Video agent job queued for {pipeline_type} pipeline.",
    }


# ---------------------------------------------------------------------------
# Job listing
# ---------------------------------------------------------------------------

def handle_list_video_agent_jobs(
    session: Dict[str, Any],
    query_params: Dict[str, Any],
    media_processing_jobs: Dict[str, Any],
) -> Tuple[int, Dict[str, Any]]:
    """
    GET /api/admin/media/video-agents/jobs[?campaign_id=X&pipeline_type=Y]

    List video agent jobs with optional filtering.
    """
    role = str(session.get("role") or "").lower()
    if role not in {"admin", "media", "marketing"}:
        return 403, {"error": "Admin or Media role required"}

    campaign_id = str((query_params.get("campaign_id") or [""])[0]).strip()
    pipeline_type = str((query_params.get("pipeline_type") or [""])[0]).strip().lower()

    jobs = [
        j for j in media_processing_jobs.values()
        if j.get("job_kind") == "video_agent"
    ]

    if campaign_id:
        jobs = [j for j in jobs if j.get("campaign_id") == campaign_id]
    if pipeline_type:
        jobs = [j for j in jobs if j.get("pipeline_type") == pipeline_type]

    jobs_sorted = sorted(jobs, key=lambda j: j.get("created_at", ""), reverse=True)

    active = sum(1 for j in jobs_sorted if j.get("status") in {"queued", "processing"})
    completed = sum(1 for j in jobs_sorted if j.get("status") == "completed")
    failed = sum(1 for j in jobs_sorted if j.get("status") in {"failed", "cancelled"})

    return 200, {
        "success": True,
        "jobs": [_serialize_job(j) for j in jobs_sorted],
        "summary": {
            "total": len(jobs_sorted),
            "active": active,
            "completed": completed,
            "failed": failed,
        },
    }


# ---------------------------------------------------------------------------
# Job status
# ---------------------------------------------------------------------------

def handle_get_video_agent_job(
    session: Dict[str, Any],
    job_id: str,
    media_processing_jobs: Dict[str, Any],
) -> Tuple[int, Dict[str, Any]]:
    """
    GET /api/admin/media/video-agents/jobs/{job_id}

    Return the current status of a single video agent job.
    """
    role = str(session.get("role") or "").lower()
    if role not in {"admin", "media", "marketing"}:
        return 403, {"error": "Admin or Media role required"}

    job = media_processing_jobs.get(job_id)
    if not job or job.get("job_kind") != "video_agent":
        return 404, {"error": f"Video agent job not found: {job_id}"}

    return 200, {"success": True, "job": _serialize_job(job)}


# ---------------------------------------------------------------------------
# Webhook receiver
# ---------------------------------------------------------------------------

def handle_video_agent_webhook(
    body: Dict[str, Any],
    query_params: Dict[str, Any],
    media_processing_jobs: Dict[str, Any],
    media_assets: Dict[str, Any],
    design_settings: Dict[str, Any],
    webhook_secret: str = "",
    request_secret: str = "",
) -> Tuple[int, Dict[str, Any]]:
    """
    POST /api/admin/media/video-agents/webhook[?job_id=X]

    Receive a Kling completion webhook and update the job record.
    """
    # Validate webhook secret if configured
    if webhook_secret and request_secret != webhook_secret:
        return 403, {"error": "Invalid webhook signature"}

    job_id = str((query_params.get("job_id") or [""])[0]).strip()
    if not job_id:
        job_id = str(body.get("job_id") or body.get("task_id") or "").strip()

    if not job_id:
        return 400, {"error": "job_id is required"}

    job = media_processing_jobs.get(job_id)
    if not job:
        return 404, {"error": f"Job not found: {job_id}"}

    # Parse Kling webhook payload
    if KLING_SERVICE_AVAILABLE:
        kling_svc = get_kling_video_service()
        parsed = kling_svc.parse_webhook_payload(body)
    else:
        parsed = _parse_kling_webhook_fallback(body)

    now_iso = datetime.now(timezone.utc).isoformat()
    status = parsed.get("status", "processing")
    download_url = parsed.get("download_url", "")
    error = parsed.get("error", "")

    job["status"] = status
    job["updated_at"] = now_iso

    if status == "completed" and download_url:
        job["download_url"] = download_url
        job["progress_pct"] = 100
        job["message"] = "Video generation completed via webhook."

        # Create media asset
        asset_id = _create_media_asset_from_job(job, download_url, media_assets)
        if asset_id:
            job["generated_asset_id"] = asset_id
            job["download_url"] = f"/api/media/{asset_id}/download"

            # Auto-publish to hero if requested
            if job.get("auto_publish_to_hero"):
                design_settings["hero_video_id"] = asset_id

    elif status == "failed":
        job["message"] = error or "Video generation failed."
        job["progress_pct"] = 0

    return 200, {
        "success": True,
        "job": _serialize_job(job),
        "message": f"Webhook processed: {status}",
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _serialize_job(job: Dict[str, Any]) -> Dict[str, Any]:
    """Return a safe, serializable copy of a job record."""
    return {
        "id": job.get("id", ""),
        "job_kind": job.get("job_kind", "video_agent"),
        "campaign_id": job.get("campaign_id", ""),
        "pipeline_type": job.get("pipeline_type", ""),
        "provider": job.get("provider", ""),
        "provider_model": job.get("provider_model", ""),
        "provider_job_id": job.get("provider_job_id", ""),
        "status": job.get("status", "queued"),
        "progress_pct": int(job.get("progress_pct") or 0),
        "message": job.get("message", ""),
        "asset_name": job.get("asset_name", ""),
        "generated_asset_id": job.get("generated_asset_id", ""),
        "download_url": job.get("download_url", ""),
        "poll_mode": job.get("poll_mode", "poll"),
        "callback_path": job.get("callback_path", ""),
        "auto_publish_to_hero": bool(job.get("auto_publish_to_hero", False)),
        "created_at": job.get("created_at", ""),
        "updated_at": job.get("updated_at", ""),
        "created_by": job.get("created_by", ""),
    }


def _create_media_asset_from_job(
    job: Dict[str, Any],
    download_url: str,
    media_assets: Dict[str, Any],
) -> str:
    """Create a media asset record for a completed video job. Returns asset_id."""
    asset_id = f"media-vaj-{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    pipeline_type = job.get("pipeline_type", "video_agent")
    campaign_id = job.get("campaign_id", "")

    media_assets[asset_id] = {
        "id": asset_id,
        "name": f"{pipeline_type.replace('_', ' ').title()} - {campaign_id}.mp4",
        "type": "video",
        "format": "video/mp4",
        "size": 0,
        "url": download_url,
        "data": "",
        "thumbnail": "",
        "source": "ai_video_agent",
        "uploaded_at": now_iso,
        "uploaded_by": job.get("created_by", "system"),
        "metadata": {
            "campaign_id": campaign_id,
            "pipeline_type": pipeline_type,
            "provider": job.get("provider", ""),
            "provider_model": job.get("provider_model", ""),
            "provider_job_id": job.get("provider_job_id", ""),
            "job_id": job.get("id", ""),
        },
    }
    return asset_id


def _parse_kling_webhook_fallback(body: Dict[str, Any]) -> Dict[str, Any]:
    """Minimal Kling webhook parser used when KlingVideoService is unavailable."""
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    status_raw = str(
        body.get("status") or data.get("status") or data.get("task_status") or ""
    ).strip().lower()

    if status_raw in {"succeed", "succeeded", "completed", "done", "ready", "complete"}:
        status = "completed"
    elif status_raw in {"failed", "error", "cancelled", "aborted", "rejected"}:
        status = "failed"
    else:
        status = "processing"

    download_url = str(
        data.get("url") or data.get("video_url") or data.get("download_url") or ""
    ).strip()

    return {
        "provider": "kling",
        "provider_job_id": str(body.get("task_id") or data.get("task_id") or "").strip(),
        "status": status,
        "download_url": download_url,
        "error": str(data.get("error_message") or data.get("message") or ""),
    }
