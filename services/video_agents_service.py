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

from services.agent_metrics import instrument_agent, set_gauge as _set_agent_gauge
from services.hydrated_store import HydratedStore

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
    """Thread-safe job store with basic indexing.

    Memory mode: a process-local dict (pre-A4 behaviour). DB mode (A4): the
    ``video_jobs`` table is the truth behind a read-through ``HydratedStore``
    cache, so webhook, poller and every web instance agree on a job's
    lifecycle. ``update``/``mark_terminal`` are conditional UPDATEs in the
    table (optimistic concurrency; ``mark_terminal`` additionally refuses
    already-terminal rows) so exactly one racer performs the terminal
    transition — the same guarantee the in-memory lock gives, now across
    processes.
    """

    TERMINAL = frozenset({"completed", "failed", "cancelled"})

    def __init__(self, enabled=None) -> None:
        self._lock = threading.Lock()
        self._store = HydratedStore(
            "video_agents.jobs", loader=self._load, saver=self._save,
            deleter=self._remove, enabled=enabled)

    # -- durable plumbing (DB mode only) ------------------------------------
    @staticmethod
    def _db():
        from database.manager import DatabaseManager
        return DatabaseManager()

    def _load(self, since):
        with self._db() as db:
            yield from db.video_jobs.iter_jobs(since)

    def _save(self, key, job):
        with self._db() as db:
            db.video_jobs.upsert(job)

    def _remove(self, key):
        with self._db() as db:
            db.video_jobs.delete_job(key)

    @property
    def durable(self) -> bool:
        return self._store.durable

    def snapshot(self) -> Dict[str, Any]:
        return self._store.snapshot()

    # -- API (unchanged) ----------------------------------------------------
    def add(self, job: Dict[str, Any]) -> None:
        with self._lock:
            self._store.put(job["id"], job)

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self._store.get(job_id)
        return dict(job) if job else None

    def update(self, job_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if self.durable:
            try:
                with self._db() as db:
                    merged = db.video_jobs.update_fields(job_id, updates)
            except Exception as exc:
                logger.warning("video_jobs update failed for %s: %s", job_id, exc)
                merged = None
            if merged is None:
                return None
            self._store.set_local(job_id, merged)
            return dict(merged)
        with self._lock:
            job = self._store.get(job_id)
            if job is None:
                return None
            job.update(updates)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            return dict(job)

    def mark_terminal(self, job_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Atomically transition a job to a terminal state.

        Returns the updated job only if this call performed the transition
        (the job existed and was not already terminal); returns ``None`` if the
        job is missing or already ``completed``/``failed``/``cancelled``. This
        lets callers emit exactly one terminal audit event per job lifecycle
        even when webhook and polling paths race.
        """
        if self.durable:
            try:
                with self._db() as db:
                    merged = db.video_jobs.mark_terminal(job_id, updates, tuple(self.TERMINAL))
            except Exception as exc:
                logger.warning("video_jobs mark_terminal failed for %s: %s", job_id, exc)
                merged = None
            if merged is None:
                # Refresh the cache so the caller sees who won.
                self._store.coalescer.reset()
                return None
            self._store.set_local(job_id, merged)
            return dict(merged)
        with self._lock:
            job = self._store.get(job_id)
            if job is None:
                return None
            if job.get("status") in self.TERMINAL:
                return None
            job.update(updates)
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            return dict(job)

    def list_by_campaign(self, campaign_id: str) -> List[Dict[str, Any]]:
        if not campaign_id:
            return []
        jobs = [dict(j) for j in self._store.values() if j.get("campaign_id", "") == campaign_id]
        jobs.sort(key=lambda j: str(j.get("created_at", "")))
        return jobs

    def list_all(self) -> List[Dict[str, Any]]:
        return [dict(j) for j in self._store.values()]

    def count_user_jobs_today(self, user_id: str) -> int:
        if not user_id:
            return 0
        today = datetime.now(timezone.utc).date().isoformat()
        return sum(
            1 for j in self._store.values()
            if j.get("submitted_by", "") == user_id and str(j.get("created_at", "")).startswith(today)
        )

    def count_campaign_jobs(self, campaign_id: str) -> int:
        if not campaign_id:
            return 0
        return sum(1 for j in self._store.values() if j.get("campaign_id", "") == campaign_id)

    def count_all_jobs_today(self) -> int:
        today = datetime.now(timezone.utc).date().isoformat()
        return sum(
            1 for j in self._store.values()
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
            if _job_store.mark_terminal(job_id, {
                "status": "failed",
                "message": "Missing provider or provider_job_id for polling.",
                "progress_pct": 0,
            }) is not None:
                _audit_video_event('video_job_failed', job_id, {
                    'campaign_id': job.get('campaign_id'),
                    'provider': provider,
                    'error': "Missing provider or provider_job_id for polling.",
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
            if _job_store.mark_terminal(job_id, {
                "status": "failed",
                "message": f"Polling error: {exc}",
                "progress_pct": 0,
            }) is not None:
                _audit_video_event('video_job_failed', job_id, {
                    'campaign_id': job.get('campaign_id'),
                    'provider': provider,
                    'error': f"Polling error: {exc}",
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
            if _job_store.mark_terminal(job_id, updates) is not None:
                _audit_video_event('video_job_completed', job_id, {
                    'campaign_id': job.get('campaign_id'),
                    'provider': provider,
                    'has_download_url': bool(download_url),
                })
            return

        if status == "failed":
            error_msg = result.get("error", "Provider reported failure")
            updates.update({
                "status": "failed",
                "progress_pct": 0,
                "error": error_msg,
            })
            if _job_store.mark_terminal(job_id, updates) is not None:
                _audit_video_event('video_job_failed', job_id, {
                    'campaign_id': job.get('campaign_id'),
                    'provider': provider,
                    'error': error_msg,
                })
            return

        # Still processing — update state and continue
        updates["status"] = "processing"
        updates["progress_pct"] = min(90, int(
            (1 - (deadline - time.monotonic()) / _POLL_TIMEOUT) * 90
        ))
        _job_store.update(job_id, updates)

    # Timeout — but a webhook may have reached a terminal state during the
    # final sleep window, so atomically transition and only audit if this
    # path is the one that finished the job.
    timed_out_job = _job_store.get(job_id)
    if timed_out_job is None:
        return
    if _job_store.mark_terminal(job_id, {
        "status": "failed",
        "message": "Polling timed out after 30 minutes.",
        "progress_pct": 0,
    }) is not None:
        _audit_video_event('video_job_failed', job_id, {
            'campaign_id': timed_out_job.get('campaign_id'),
            'provider': timed_out_job.get('provider'),
            'error': "Polling timed out after 30 minutes.",
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

    @instrument_agent('video_agents', decision_key='status')
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
                    attribution={"user_id": submitted_by, "job_id": job_id},
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
        if submission_error:
            # Terminal submission failure never starts the background poller,
            # so emit the durable terminal failure event here for parity with
            # polling/webhook/timeout failure paths.
            _audit_video_event('video_job_failed', job_id, {
                'campaign_id': final_job.get('campaign_id'),
                'provider': final_job.get('provider'),
                'error': submission_error,
            })
        return final_job

    @instrument_agent('video_agents')
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

        terminal_audit: Optional[tuple] = None
        if poll_status == "completed":
            download_url = result.get("download_url", "")
            updates.update({
                "status": "completed",
                "progress_pct": 100,
                "download_url": download_url,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            })
            terminal_audit = ('video_job_completed', {
                'campaign_id': job.get('campaign_id'),
                'provider': provider,
                'has_download_url': bool(download_url),
            })
        elif poll_status == "failed":
            error_msg = result.get("error", "Provider reported failure")
            updates.update({
                "status": "failed",
                "progress_pct": 0,
                "error": error_msg,
            })
            terminal_audit = ('video_job_failed', {
                'campaign_id': job.get('campaign_id'),
                'provider': provider,
                'error': error_msg,
            })
        else:
            updates["status"] = "processing"

        if terminal_audit is not None:
            # Atomically transition so a concurrent poll/webhook cannot emit a
            # duplicate terminal audit for the same job.
            if _job_store.mark_terminal(job_id, updates) is not None:
                _audit_video_event(terminal_audit[0], job_id, terminal_audit[1])
        else:
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
                    attribution={"user_id": job.get("submitted_by", ""), "job_id": job_id},
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
            # A retry that fails before polling never starts the background
            # poller/webhook, so emit the durable terminal failure event here
            # for parity with submit and polling/webhook failure paths.
            final_job = _job_store.get(job_id) or job
            _audit_video_event('video_job_failed', job_id, {
                'campaign_id': final_job.get('campaign_id'),
                'provider': final_job.get('provider'),
                'error': submission_error,
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

            updated = _job_store.mark_terminal(job_id, {
                "status": "completed",
                "progress_pct": 100,
                "download_url": download_url,
                "message": "Completed via webhook callback.",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "provider_state": {**job.get("provider_state", {}), "webhook": webhook_payload},
            })
            if updated is not None:
                _audit_video_event('video_job_completed', job_id, {
                    'campaign_id': job.get('campaign_id'),
                    'provider': job.get('provider'),
                    'has_download_url': bool(download_url),
                })
                return updated
            return _job_store.get(job_id)

        if status_value in {"failed", "error", "cancelled", "aborted", "rejected"}:
            error_msg = str(
                data.get("error_message") or data.get("message") or "Provider reported failure via webhook."
            )
            updated = _job_store.mark_terminal(job_id, {
                "status": "failed",
                "progress_pct": 0,
                "error": error_msg,
                "message": f"Failed via webhook: {error_msg}",
                "provider_state": {**job.get("provider_state", {}), "webhook": webhook_payload},
            })
            if updated is not None:
                _audit_video_event('video_job_failed', job_id, {
                    'campaign_id': job.get('campaign_id'),
                    'provider': job.get('provider'),
                    'error': error_msg,
                })
                return updated
            return _job_store.get(job_id)

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


# ---------------------------------------------------------------------------
# Agent runtime registration (discovery + health only; no behaviour change).
# ---------------------------------------------------------------------------
def _video_agents_health() -> Dict[str, Any]:
    """Read-only probe over the in-memory job store; never submits work."""
    jobs = _job_store.list_all()
    by_status: Dict[str, int] = {}
    for job in jobs:
        key = str(job.get('status') or 'unknown')
        by_status[key] = by_status.get(key, 0) + 1
    active = by_status.get('queued', 0) + by_status.get('processing', 0)
    _set_agent_gauge('video_agents', 'active_jobs', active)
    return {
        'status': 'ok' if MEDIA_GENERATION_AVAILABLE else 'degraded',
        'media_generation_available': MEDIA_GENERATION_AVAILABLE,
        'initialized': _video_agents_service is not None,
        'jobs_total': len(jobs),
        'jobs_by_status': by_status,
        'caps': {
            'per_user_per_day': _MAX_JOBS_PER_USER_PER_DAY,
            'per_campaign': _MAX_JOBS_PER_CAMPAIGN,
            'per_day': _MAX_JOBS_PER_DAY,
        },
    }


try:
    from services.agent_runtime import AgentDescriptor as _AgentDescriptor, register as _register_agent
    _register_agent(_AgentDescriptor(
        id='video_agents',
        name='Video Agents',
        version='1.0.0',
        module=__name__,
        description=(
            'Generates insurance-workflow videos (introductions, regulatory, '
            'application/underwriting/claims assistants) with cost controls.'
        ),
        entry_url='/video-agents.html',
        api={'method': 'POST', 'path': '/api/admin/media/video-jobs/batch'},
        roles=('admin', 'media'),
        deterministic=False,
        executes_async=True,
        sample_prompts=(
            'Generate an introduction video for this campaign',
        ),
    ), health_fn=_video_agents_health)
except Exception as _reg_exc:  # pragma: no cover
    logger.warning("video agents registration skipped: %s", _reg_exc)
