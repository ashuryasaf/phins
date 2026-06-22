"""
PHINS Video Agents Service
==========================

Wraps MediaGenerationService with persistent job tracking, cost controls,
rate limiting, and fallback logic for insurance-workflow video generation.

Supported pipeline types:
  - introductions
  - regulatory_presentations
  - application_assistant
  - underwriting_assistant
  - claims_assistant

Job lifecycle:
  queued -> processing -> completed | failed | cancelled

Cost controls:
  - Per-user daily job cap (VIDEO_AGENTS_MAX_JOBS_PER_USER_PER_DAY, default 20)
  - Per-campaign job cap (VIDEO_AGENTS_MAX_JOBS_PER_CAMPAIGN, default 50)
  - Global daily job cap (VIDEO_AGENTS_MAX_JOBS_PER_DAY, default 200)

Completion modes:
  - poll: background polling with exponential backoff (default)
  - webhook: Kling/Gemini callback URL; falls back to polling on timeout
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    from services.media_generation_service import get_media_generation_service
    MEDIA_GENERATION_AVAILABLE = True
except ImportError:
    MEDIA_GENERATION_AVAILABLE = False

logger = logging.getLogger('phins.video_agents')


def _audit_video_event(action: str, job_id: Optional[str], details: Dict[str, Any]) -> None:
    """Mirror a video-job lifecycle event into the durable audit store.

    Best-effort and non-fatal. Gives the video-agents job lifecycle a durable
    audit trail independent of the in-memory ``_job_store``. No-op without a
    database.
    """
    try:
        from services.ai_audit_bridge import record_ai_audit
        record_ai_audit(
            action=action,
            entity_type='video_job',
            entity_id=job_id,
            details=details,
            username='video_agents',
        )
    except Exception as exc:
        logger.warning("video job audit mirror failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_MAX_JOBS_PER_USER_PER_DAY = int(os.environ.get("VIDEO_AGENTS_MAX_JOBS_PER_USER_PER_DAY", "20"))
_MAX_JOBS_PER_CAMPAIGN = int(os.environ.get("VIDEO_AGENTS_MAX_JOBS_PER_CAMPAIGN", "50"))
_MAX_JOBS_PER_DAY = int(os.environ.get("VIDEO_AGENTS_MAX_JOBS_PER_DAY", "200"))

# Polling: initial delay, backoff multiplier, max delay (seconds)
_POLL_INITIAL_DELAY = float(os.environ.get("VIDEO_AGENTS_POLL_INITIAL_DELAY", "10"))
_POLL_BACKOFF_MULTIPLIER = float(os.environ.get("VIDEO_AGENTS_POLL_BACKOFF_MULTIPLIER", "1.5"))
_POLL_MAX_DELAY = float(os.environ.get("VIDEO_AGENTS_POLL_MAX_DELAY", "120"))
_POLL_TIMEOUT = float(os.environ.get("VIDEO_AGENTS_POLL_TIMEOUT", "1800"))  # 30 min

# Pipeline prompt templates
_PIPELINE_PROMPTS: Dict[str, str] = {
    "introductions": (
        "Create a polished, professional introduction video for PHINS insurance. "
        "Welcome new customers and partners with a warm, trustworthy tone. "
        "Highlight key benefits: comprehensive coverage, transparent pricing, and AI-powered guidance. "
        "Duration: 30-60 seconds. Style: corporate, approachable, confidence-building."
    ),
    "regulatory_presentations": (
        "Create a clear, authoritative regulatory and compliance presentation video for PHINS. "
        "Suitable for board meetings, regulator reviews, and product-governance explainers. "
        "Tone: formal, evidence-based, traceable. Include compliance checkpoints and audit references. "
        "Duration: 60-90 seconds. Style: professional, structured, regulatory-grade."
    ),
    "application_assistant": (
        "Create an application-assistant explainer video for PHINS insurance applications. "
        "Guide applicants through data capture, supporting documents, and pre-underwriting expectations. "
        "Tone: helpful, clear, step-by-step. Reduce friction and build confidence in the process. "
        "Duration: 45-60 seconds. Style: instructional, friendly, process-focused."
    ),
    "underwriting_assistant": (
        "Create an underwriting-assistant explainer video for PHINS. "
        "Cover evidence requirements, risk review steps, next steps, and case status updates. "
        "Tone: professional, transparent, reassuring. Help applicants understand the underwriting journey. "
        "Duration: 45-60 seconds. Style: informative, structured, trust-building."
    ),
    "claims_assistant": (
        "Create a claims-assistant explainer video for PHINS insurance claims. "
        "Walk claimants through document collection, ADL review, claim stages, and payout checkpoints. "
        "Tone: empathetic, clear, supportive. Reduce anxiety and set accurate expectations. "
        "Duration: 60-90 seconds. Style: compassionate, step-by-step, outcome-focused."
    ),
}

_PIPELINE_TITLES: Dict[str, str] = {
    "introductions": "PHINS Introduction Video",
    "regulatory_presentations": "PHINS Regulatory Presentation",
    "application_assistant": "PHINS Application Assistant",
    "underwriting_assistant": "PHINS Underwriting Assistant",
    "claims_assistant": "PHINS Claims Assistant",
}

SUPPORTED_PIPELINE_TYPES = set(_PIPELINE_PROMPTS.keys())


# ---------------------------------------------------------------------------
# In-memory job store
# ---------------------------------------------------------------------------

class _JobStore:
    """Thread-safe in-memory job store with basic indexing."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # job_id -> job dict
        self._jobs: Dict[str, Dict[str, Any]] = {}
        # campaign_id -> [job_id, ...]
        self._by_campaign: Dict[str, List[str]] = {}
        # user_id -> [job_id, ...]
        self._by_user: Dict[str, List[str]] = {}

    def add(self, job: Dict[str, Any]) -> None:
        job_id = job["id"]
        campaign_id = job.get("campaign_id", "")
        user_id = job.get("submitted_by", "")
        with self._lock:
            self._jobs[job_id] = job
            if campaign_id:
                self._by_campaign.setdefault(campaign_id, []).append(job_id)
            if user_id:
                self._by_user.setdefault(user_id, []).append(job_id)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def update(self, job_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.update(updates)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            return dict(job)

    def list_by_campaign(self, campaign_id: str) -> List[Dict[str, Any]]:
        with self._lock:
            ids = list(self._by_campaign.get(campaign_id, []))
        return [j for j in (self.get(jid) for jid in ids) if j is not None]

    def list_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(j) for j in self._jobs.values()]

    def count_user_jobs_today(self, user_id: str) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            ids = list(self._by_user.get(user_id, []))
        count = 0
        for jid in ids:
            job = self.get(jid)
            if job and str(job.get("created_at", "")).startswith(today):
                count += 1
        return count

    def count_campaign_jobs(self, campaign_id: str) -> int:
        with self._lock:
            return len(self._by_campaign.get(campaign_id, []))

    def count_all_jobs_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        with self._lock:
            return sum(
                1 for j in self._jobs.values()
                if str(j.get("created_at", "")).startswith(today)
            )


_job_store = _JobStore()


# ---------------------------------------------------------------------------
# Background polling worker
# ---------------------------------------------------------------------------

def _poll_job_background(job_id: str) -> None:
    """Poll a provider job in a background thread until terminal state."""
    delay = _POLL_INITIAL_DELAY
    deadline = time.monotonic() + _POLL_TIMEOUT

    while time.monotonic() < deadline:
        time.sleep(delay)
        delay = min(delay * _POLL_BACKOFF_MULTIPLIER, _POLL_MAX_DELAY)

        job = _job_store.get(job_id)
        if job is None:
            return
        if job.get("status") in {"completed", "failed", "cancelled"}:
            return

        provider = job.get("provider", "")
        provider_job_id = job.get("provider_job_id", "")
        provider_state = job.get("provider_state") or {}

        if not provider or not provider_job_id:
            _job_store.update(job_id, {
                "status": "failed",
                "message": "Missing provider or provider_job_id for polling.",
                "progress_pct": 0,
            })
            return

        try:
            if not MEDIA_GENERATION_AVAILABLE:
                raise RuntimeError("MediaGenerationService not available")
            svc = get_media_generation_service()
            result = svc.poll_video_generation(
                provider=provider,
                provider_job_id=provider_job_id,
                provider_state=provider_state,
            )
        except Exception as exc:
            _job_store.update(job_id, {
                "status": "failed",
                "message": f"Polling error: {exc}",
                "progress_pct": 0,
            })
            return

        status = result.get("status", "processing")
        updates: Dict[str, Any] = {
            "provider_state": result.get("provider_state", provider_state),
            "message": result.get("message", ""),
        }

        if status == "completed":
            download_url = result.get("download_url", "")
            updates.update({
                "status": "completed",
                "progress_pct": 100,
                "download_url": download_url,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            _job_store.update(job_id, updates)
            return

        if status == "failed":
            updates.update({
                "status": "failed",
                "progress_pct": 0,
                "error": result.get("error", "Provider reported failure"),
            })
            _job_store.update(job_id, updates)
            return

        # Still processing — update state and continue
        updates["status"] = "processing"
        updates["progress_pct"] = min(90, int(
            (1 - (deadline - time.monotonic()) / _POLL_TIMEOUT) * 90
        ))
        _job_store.update(job_id, updates)

    # Timeout
    _job_store.update(job_id, {
        "status": "failed",
        "message": "Polling timed out after 30 minutes.",
        "progress_pct": 0,
    })


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------

class VideoAgentsService:
    """
    High-level video agents service for PHINS insurance workflows.

    Wraps MediaGenerationService with:
    - Job persistence (in-memory)
    - Cost controls and rate limiting
    - Background polling with exponential backoff
    - Fallback from Kling to Gemini on submission failure
    - Webhook support (pass-through to provider)
    """

    def get_provider_capabilities(self) -> Dict[str, Any]:
        """Return provider availability and model configuration."""
        if not MEDIA_GENERATION_AVAILABLE:
            return {
                "providers": {
                    "gemini": {"enabled": False, "label": "Gemini / Veo", "models": []},
                    "kling": {"enabled": False, "label": "Kling", "models": []},
                },
                "default_provider": "gemini",
                "pipeline_types": sorted(SUPPORTED_PIPELINE_TYPES),
                "service_available": False,
            }

        svc = get_media_generation_service()
        provider_config = svc.supported_provider_config()

        # Determine default provider (prefer first enabled)
        default_provider = "gemini"
        for name in ("gemini", "kling"):
            if provider_config.get(name, {}).get("enabled"):
                default_provider = name
                break

        return {
            "providers": provider_config,
            "default_provider": default_provider,
            "pipeline_types": sorted(SUPPORTED_PIPELINE_TYPES),
            "service_available": True,
        }

    def submit_video_job(
        self,
        *,
        campaign_id: str,
        provider: str,
        pipeline_type: str,
        title: str = "",
        prompt_override: str = "",
        provider_model: str = "",
        aspect_ratio: str = "16:9",
        duration_seconds: int = 8,
        resolution: str = "720p",
        image_data_url: str = "",
        reference_image_asset_id: str = "",
        poll_mode: str = "poll",
        auto_publish_to_hero: bool = False,
        callback_url: str = "",
        submitted_by: str = "admin",
        metadata: Optional[Dict[str, Any]] = None,
        blueprint_index: int = 0,
    ) -> Dict[str, Any]:
        """
        Submit a single video generation job.

        Returns the created job dict.
        Raises ValueError for validation errors.
        Raises RuntimeError for cost-control violations.
        """
        # --- Validate inputs ---
        provider_name = str(provider or "gemini").strip().lower()
        pipeline = str(pipeline_type or "introductions").strip().lower()
        if pipeline not in SUPPORTED_PIPELINE_TYPES:
            raise ValueError(
                f"Unsupported pipeline type: {pipeline!r}. "
                f"Supported: {sorted(SUPPORTED_PIPELINE_TYPES)}"
            )

        # --- Cost controls ---
        user_jobs_today = _job_store.count_user_jobs_today(submitted_by)
        if user_jobs_today >= _MAX_JOBS_PER_USER_PER_DAY:
            raise RuntimeError(
                f"Daily job limit reached for user {submitted_by!r} "
                f"({_MAX_JOBS_PER_USER_PER_DAY} jobs/day)."
            )

        if campaign_id:
            campaign_jobs = _job_store.count_campaign_jobs(campaign_id)
            if campaign_jobs >= _MAX_JOBS_PER_CAMPAIGN:
                raise RuntimeError(
                    f"Campaign job limit reached for {campaign_id!r} "
                    f"({_MAX_JOBS_PER_CAMPAIGN} jobs/campaign)."
                )

        global_today = _job_store.count_all_jobs_today()
        if global_today >= _MAX_JOBS_PER_DAY:
            raise RuntimeError(
                f"Global daily job limit reached ({_MAX_JOBS_PER_DAY} jobs/day)."
            )

        # --- Build prompt and title ---
        resolved_title = str(title or _PIPELINE_TITLES.get(pipeline, "PHINS Video")).strip()
        resolved_prompt = str(prompt_override or _PIPELINE_PROMPTS.get(pipeline, "")).strip()
        if not resolved_prompt:
            resolved_prompt = f"Create a professional insurance video for PHINS: {resolved_title}"

        # --- Create job record ---
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        job: Dict[str, Any] = {
            "id": job_id,
            "campaign_id": campaign_id,
            "pipeline_type": pipeline,
            "asset_name": resolved_title,
            "provider": provider_name,
            "provider_model": provider_model,
            "prompt": resolved_prompt,
            "aspect_ratio": aspect_ratio,
            "duration_seconds": duration_seconds,
            "resolution": resolution,
            "image_data_url": image_data_url,
            "reference_image_asset_id": reference_image_asset_id,
            "poll_mode": poll_mode,
            "auto_publish_to_hero": auto_publish_to_hero,
            "callback_url": callback_url,
            "submitted_by": submitted_by,
            "blueprint_index": blueprint_index,
            "metadata": metadata or {},
            "status": "queued",
            "progress_pct": 0,
            "message": "Job queued, awaiting submission to provider.",
            "provider_job_id": "",
            "provider_state": {},
            "download_url": "",
            "generated_asset_id": "",
            "error": "",
            "created_at": now,
            "updated_at": now,
            "completed_at": "",
        }
        _job_store.add(job)

        # --- Submit to provider (with Kling -> Gemini fallback) ---
        providers_to_try = [provider_name]
        if provider_name == "kling":
            providers_to_try.append("gemini")  # fallback

        submission_error: Optional[str] = None
        for attempt_provider in providers_to_try:
            try:
                if not MEDIA_GENERATION_AVAILABLE:
                    raise RuntimeError("MediaGenerationService not available")

                svc = get_media_generation_service()
                provider_caps = svc.supported_provider_config()
                if not provider_caps.get(attempt_provider, {}).get("enabled"):
                    raise RuntimeError(
                        f"Provider {attempt_provider!r} is not configured on this server."
                    )

                submit_result = svc.submit_video_generation(
                    provider=attempt_provider,
                    prompt=resolved_prompt,
                    title=resolved_title,
                    model=provider_model,
                    aspect_ratio=aspect_ratio,
                    duration_seconds=duration_seconds,
                    resolution=resolution,
                    image_data_url=image_data_url,
                    callback_url=callback_url,
                    metadata=metadata or {},
                )

                # Update job with provider response
                _job_store.update(job_id, {
                    "provider": attempt_provider,
                    "provider_job_id": submit_result.get("provider_job_id", ""),
                    "provider_state": submit_result.get("provider_state", {}),
                    "status": "processing",
                    "progress_pct": 5,
                    "message": submit_result.get(
                        "message",
                        f"Submitted to {attempt_provider.title()}."
                    ),
                    "error": "",
                })

                # Start background polling if poll mode
                if poll_mode != "webhook":
                    t = threading.Thread(
                        target=_poll_job_background,
                        args=(job_id,),
                        daemon=True,
                        name=f"video-poll-{job_id[:8]}",
                    )
                    t.start()

                submission_error = None
                break  # success

            except Exception as exc:
                submission_error = str(exc)
                if attempt_provider != providers_to_try[-1]:
                    # Log fallback attempt
                    _job_store.update(job_id, {
                        "message": (
                            f"{attempt_provider.title()} submission failed ({exc}); "
                            f"falling back to {providers_to_try[providers_to_try.index(attempt_provider) + 1].title()}."
                        ),
                    })

        if submission_error:
            _job_store.update(job_id, {
                "status": "failed",
                "progress_pct": 0,
                "message": f"All providers failed: {submission_error}",
                "error": submission_error,
            })

        final_job = _job_store.get(job_id) or job
        _audit_video_event('video_job_submitted', job_id, {
            'campaign_id': final_job.get('campaign_id'),
            'pipeline_type': final_job.get('pipeline_type'),
            'provider': final_job.get('provider'),
            'status': final_job.get('status'),
            'submitted_by': final_job.get('submitted_by'),
        })
        return final_job

    def submit_batch(
        self,
        *,
        campaign_id: str,
        provider: str,
        pipeline_type: str = "",
        prompt_override: str = "",
        provider_model: str = "",
        image_data_url: str = "",
        reference_image_asset_id: str = "",
        poll_mode: str = "poll",
        auto_publish_to_hero: bool = False,
        submitted_by: str = "admin",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Submit a batch of pipeline videos for a campaign.

        If pipeline_type is specified, submits only that pipeline.
        Otherwise submits all pipeline types.

        Returns a summary dict with queued_jobs list.
        """
        pipelines = (
            [pipeline_type]
            if pipeline_type and pipeline_type in SUPPORTED_PIPELINE_TYPES
            else sorted(SUPPORTED_PIPELINE_TYPES)
        )

        queued_jobs: List[Dict[str, Any]] = []
        errors: List[str] = []

        for idx, pipeline in enumerate(pipelines):
            try:
                job = self.submit_video_job(
                    campaign_id=campaign_id,
                    provider=provider,
                    pipeline_type=pipeline,
                    prompt_override=prompt_override,
                    provider_model=provider_model,
                    image_data_url=image_data_url,
                    reference_image_asset_id=reference_image_asset_id,
                    poll_mode=poll_mode,
                    auto_publish_to_hero=auto_publish_to_hero,
                    submitted_by=submitted_by,
                    metadata=metadata,
                    blueprint_index=idx,
                )
                queued_jobs.append(job)
            except Exception as exc:
                errors.append(f"{pipeline}: {exc}")

        return {
            "queued_jobs": queued_jobs,
            "jobs": queued_jobs,  # alias for frontend compatibility
            "queued_count": len(queued_jobs),
            "error_count": len(errors),
            "errors": errors,
            "campaign_id": campaign_id,
        }

    def list_jobs(
        self,
        campaign_id: str = "",
        status_filter: str = "",
        limit: int = 100,
    ) -> Dict[str, Any]:
        """List video agent jobs, optionally filtered by campaign and status."""
        if campaign_id:
            jobs = _job_store.list_by_campaign(campaign_id)
        else:
            jobs = _job_store.list_all()

        if status_filter:
            jobs = [j for j in jobs if j.get("status") == status_filter]

        # Sort newest first
        jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
        jobs = jobs[:limit]

        total = len(jobs)
        active = sum(1 for j in jobs if j.get("status") in {"queued", "processing"})
        completed = sum(1 for j in jobs if j.get("status") == "completed")
        failed = sum(1 for j in jobs if j.get("status") in {"failed", "cancelled"})

        return {
            "jobs": jobs,
            "total": total,
            "summary": {
                "total": total,
                "active": active,
                "completed": completed,
                "failed": failed,
            },
        }

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a single job by ID."""
        return _job_store.get(job_id)

    def poll_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Manually trigger a poll for a job and return the updated job.

        This is used by the GET /jobs/{job_id} endpoint to provide
        fresh status on demand.
        """
        job = _job_store.get(job_id)
        if job is None:
            return None

        status = job.get("status", "")
        if status in {"completed", "failed", "cancelled"}:
            return job  # terminal — no poll needed

        provider = job.get("provider", "")
        provider_job_id = job.get("provider_job_id", "")
        provider_state = job.get("provider_state") or {}

        if not provider or not provider_job_id:
            return job  # not yet submitted

        try:
            if not MEDIA_GENERATION_AVAILABLE:
                return job
            svc = get_media_generation_service()
            result = svc.poll_video_generation(
                provider=provider,
                provider_job_id=provider_job_id,
                provider_state=provider_state,
            )
        except Exception as exc:
            _job_store.update(job_id, {
                "message": f"Poll error: {exc}",
            })
            return _job_store.get(job_id)

        poll_status = result.get("status", "processing")
        updates: Dict[str, Any] = {
            "provider_state": result.get("provider_state", provider_state),
            "message": result.get("message", ""),
        }

        if poll_status == "completed":
            updates.update({
                "status": "completed",
                "progress_pct": 100,
                "download_url": result.get("download_url", ""),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
        elif poll_status == "failed":
            updates.update({
                "status": "failed",
                "progress_pct": 0,
                "error": result.get("error", "Provider reported failure"),
            })
        else:
            updates["status"] = "processing"

        _job_store.update(job_id, updates)
        return _job_store.get(job_id)

    def cancel_job(self, job_id: str, cancelled_by: str = "admin") -> Optional[Dict[str, Any]]:
        """Cancel a queued or processing job."""
        job = _job_store.get(job_id)
        if job is None:
            return None
        if job.get("status") in {"completed", "failed", "cancelled"}:
            return job  # already terminal

        return _job_store.update(job_id, {
            "status": "cancelled",
            "message": f"Cancelled by {cancelled_by}.",
            "progress_pct": 0,
        })

    def retry_job(self, job_id: str, retried_by: str = "admin") -> Optional[Dict[str, Any]]:
        """
        Retry a failed or cancelled job by re-submitting it to the provider.

        Returns the updated job dict.
        """
        job = _job_store.get(job_id)
        if job is None:
            return None

        if job.get("status") not in {"failed", "cancelled"}:
            return job  # only retry terminal-failure jobs

        # Reset job state
        _job_store.update(job_id, {
            "status": "queued",
            "progress_pct": 0,
            "message": f"Retried by {retried_by}.",
            "provider_job_id": "",
            "provider_state": {},
            "download_url": "",
            "error": "",
            "completed_at": "",
        })

        # Re-submit
        provider = job.get("provider", "gemini")
        provider_job_id_new = ""
        submission_error: Optional[str] = None

        providers_to_try = [provider]
        if provider == "kling":
            providers_to_try.append("gemini")

        for attempt_provider in providers_to_try:
            try:
                if not MEDIA_GENERATION_AVAILABLE:
                    raise RuntimeError("MediaGenerationService not available")

                svc = get_media_generation_service()
                provider_caps = svc.supported_provider_config()
                if not provider_caps.get(attempt_provider, {}).get("enabled"):
                    raise RuntimeError(
                        f"Provider {attempt_provider!r} is not configured."
                    )

                submit_result = svc.submit_video_generation(
                    provider=attempt_provider,
                    prompt=job.get("prompt", ""),
                    title=job.get("asset_name", "PHINS Video"),
                    model=job.get("provider_model", ""),
                    aspect_ratio=job.get("aspect_ratio", "16:9"),
                    duration_seconds=int(job.get("duration_seconds", 8)),
                    resolution=job.get("resolution", "720p"),
                    image_data_url=job.get("image_data_url", ""),
                    callback_url=job.get("callback_url", ""),
                    metadata=job.get("metadata") or {},
                )

                _job_store.update(job_id, {
                    "provider": attempt_provider,
                    "provider_job_id": submit_result.get("provider_job_id", ""),
                    "provider_state": submit_result.get("provider_state", {}),
                    "status": "processing",
                    "progress_pct": 5,
                    "message": submit_result.get("message", f"Retried with {attempt_provider.title()}."),
                    "error": "",
                })

                poll_mode = job.get("poll_mode", "poll")
                if poll_mode != "webhook":
                    t = threading.Thread(
                        target=_poll_job_background,
                        args=(job_id,),
                        daemon=True,
                        name=f"video-retry-{job_id[:8]}",
                    )
                    t.start()

                submission_error = None
                break

            except Exception as exc:
                submission_error = str(exc)

        if submission_error:
            _job_store.update(job_id, {
                "status": "failed",
                "progress_pct": 0,
                "message": f"Retry failed: {submission_error}",
                "error": submission_error,
            })

        return _job_store.get(job_id)

    def download_job_video(
        self,
        job_id: str,
        stream_to_path: str = "",
    ) -> Dict[str, Any]:
        """
        Download the completed video for a job.

        Returns a dict with data_url (or file_path), content_type, and size.
        Raises ValueError if job not found or not completed.
        Raises RuntimeError if download fails.
        """
        job = _job_store.get(job_id)
        if job is None:
            raise ValueError(f"Job {job_id!r} not found.")

        if job.get("status") != "completed":
            raise ValueError(
                f"Job {job_id!r} is not completed (status: {job.get('status')!r})."
            )

        download_url = str(job.get("download_url") or "").strip()
        if not download_url:
            raise ValueError(f"Job {job_id!r} has no download URL.")

        if not MEDIA_GENERATION_AVAILABLE:
            raise RuntimeError("MediaGenerationService not available for download.")

        svc = get_media_generation_service()
        return svc.download_generated_video(
            provider=job.get("provider", "gemini"),
            download_url=download_url,
            stream_to_path=stream_to_path,
        )

    def handle_webhook(
        self,
        job_id: str,
        webhook_payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Process a provider webhook callback for a job.

        Parses the payload and updates job status accordingly.
        Returns the updated job or None if not found.
        """
        job = _job_store.get(job_id)
        if job is None:
            return None

        # Normalize webhook payload (Kling and Gemini have different shapes)
        data = webhook_payload.get("data") if isinstance(webhook_payload.get("data"), dict) else webhook_payload
        status_value = str(
            webhook_payload.get("status")
            or data.get("status")
            or data.get("task_status")
            or ""
        ).strip().lower()

        if status_value in {"succeed", "succeeded", "completed", "done", "ready", "complete"}:
            # Try to extract download URL
            download_url = ""
            works = data.get("works") if isinstance(data.get("works"), list) else []
            for work in works:
                if isinstance(work, dict):
                    resource = work.get("resource") if isinstance(work.get("resource"), dict) else {}
                    candidate = str(
                        work.get("url") or work.get("video_url")
                        or resource.get("resource") or resource.get("url") or ""
                    ).strip()
                    if candidate:
                        download_url = candidate
                        break

            if not download_url:
                download_url = str(
                    data.get("url") or data.get("video_url") or data.get("download_url") or ""
                ).strip()

            updated = _job_store.update(job_id, {
                "status": "completed",
                "progress_pct": 100,
                "download_url": download_url,
                "message": "Completed via webhook callback.",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "provider_state": {**job.get("provider_state", {}), "webhook": webhook_payload},
            })
            _audit_video_event('video_job_completed', job_id, {
                'campaign_id': job.get('campaign_id'),
                'provider': job.get('provider'),
                'has_download_url': bool(download_url),
            })
            return updated

        if status_value in {"failed", "error", "cancelled", "aborted", "rejected"}:
            error_msg = str(
                data.get("error_message") or data.get("message") or "Provider reported failure via webhook."
            )
            updated = _job_store.update(job_id, {
                "status": "failed",
                "progress_pct": 0,
                "error": error_msg,
                "message": f"Failed via webhook: {error_msg}",
                "provider_state": {**job.get("provider_state", {}), "webhook": webhook_payload},
            })
            _audit_video_event('video_job_failed', job_id, {
                'campaign_id': job.get('campaign_id'),
                'provider': job.get('provider'),
                'error': error_msg,
            })
            return updated

        # Still processing — update state
        return _job_store.update(job_id, {
            "status": "processing",
            "message": f"Webhook update: status={status_value or 'unknown'}",
            "provider_state": {**job.get("provider_state", {}), "webhook": webhook_payload},
        })


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_video_agents_service: Optional[VideoAgentsService] = None
_service_lock = threading.Lock()


def get_video_agents_service() -> VideoAgentsService:
    """Return the singleton VideoAgentsService instance."""
    global _video_agents_service
    if _video_agents_service is None:
        with _service_lock:
            if _video_agents_service is None:
                _video_agents_service = VideoAgentsService()
    return _video_agents_service
