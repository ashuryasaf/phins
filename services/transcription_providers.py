"""
Audio Transcription Provider Abstraction
========================================
Vendor-neutral speech-to-text for the document intelligence pipeline
(Phase 5 of docs/multimodal_assessment_pipeline_plan.md).

Providers:

* ``openai_compatible`` — any Whisper-style ``/v1/audio/transcriptions``
  HTTP endpoint (OpenAI, Groq, self-hosted Whisper, Deepgram-compatible
  gateways). Plain HTTP, no SDK, matching the platform convention.
* ``disabled`` (default) — raises so callers keep their current stub
  behaviour; no audio ever leaves the platform unless an operator opts in.

The existing media *subtitle* webhook flow (``bridge`` provider in
``web_portal/server.py``) stays as-is for media assets; this module serves the
synchronous/worker document path where the transcript must come back in-call.

Output contract (spec §9):
    {"text": str, "language": str|None,
     "segments": [{"start": float, "end": float, "text": str}, ...],
     "provider": str, "model": str|None, "duration_seconds": float|None}

Environment:
    PHINS_TRANSCRIPTION_PROVIDER   openai_compatible | disabled (default)
    PHINS_TRANSCRIPTION_ENDPOINT   e.g. https://api.openai.com/v1/audio/transcriptions
    PHINS_TRANSCRIPTION_API_KEY    bearer key
    PHINS_TRANSCRIPTION_MODEL      model id (default whisper-1)
    PHINS_TRANSCRIPTION_TIMEOUT    request timeout seconds (default 120)
    PHINS_TRANSCRIPTION_MAX_BYTES  refuse larger uploads (default 25MB)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TranscriptionUnavailableError(RuntimeError):
    """No transcription provider is configured for this deployment."""


class AudioTranscriptionProvider:
    """Provider interface for speech-to-text."""

    def transcribe(self, raw: bytes, *, file_name: str = "audio.mp3",
                   mime_type: str = "audio/mpeg",
                   language_hint: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError

    def describe(self) -> Dict[str, Any]:
        return {"provider": type(self).__name__}


class DisabledTranscriptionProvider(AudioTranscriptionProvider):
    def transcribe(self, raw, *, file_name="audio.mp3", mime_type="audio/mpeg",
                   language_hint=None):
        raise TranscriptionUnavailableError(
            "No transcription provider configured "
            "(set PHINS_TRANSCRIPTION_PROVIDER=openai_compatible)")

    def describe(self):
        return {"provider": "disabled"}


class OpenAICompatibleTranscriptionProvider(AudioTranscriptionProvider):
    """Whisper-style multipart transcription over HTTP."""

    def __init__(self, endpoint: str, api_key: str, model: str = "whisper-1",
                 timeout: float = 120.0):
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_bytes = int(os.environ.get(
            "PHINS_TRANSCRIPTION_MAX_BYTES", 25 * 1024 * 1024))

    def describe(self):
        return {"provider": "openai_compatible", "model": self.model}

    def transcribe(self, raw: bytes, *, file_name: str = "audio.mp3",
                   mime_type: str = "audio/mpeg",
                   language_hint: Optional[str] = None) -> Dict[str, Any]:
        import requests

        if not raw:
            raise ValueError("Empty audio payload")
        if len(raw) > self.max_bytes:
            raise ValueError(
                f"Audio exceeds transcription size limit ({self.max_bytes} bytes)")

        data: Dict[str, Any] = {
            "model": self.model,
            # verbose_json returns segments with timestamps where supported.
            "response_format": "verbose_json",
        }
        if language_hint:
            data["language"] = language_hint

        from security.network import assert_safe_provider_url

        assert_safe_provider_url(self.endpoint)
        start = time.time()
        response = requests.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
            files={"file": (file_name, raw, mime_type)},
            data=data,
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        duration_ms = int((time.time() - start) * 1000)

        segments: List[Dict[str, Any]] = []
        for seg in payload.get("segments") or []:
            try:
                segments.append({
                    "start": float(seg.get("start", 0.0)),
                    "end": float(seg.get("end", 0.0)),
                    "text": str(seg.get("text", "")).strip(),
                })
            except (TypeError, ValueError):
                continue

        text = str(payload.get("text") or "").strip()
        if not text and segments:
            text = " ".join(s["text"] for s in segments if s["text"])
        if not text:
            raise ValueError("Transcription returned no text")

        duration_seconds = payload.get("duration")
        try:
            duration_seconds = float(duration_seconds) if duration_seconds else (
                segments[-1]["end"] if segments else None)
        except (TypeError, ValueError):
            duration_seconds = None

        result = {
            "text": text,
            "language": payload.get("language"),
            "segments": segments,
            "provider": "openai_compatible",
            "model": self.model,
            "duration_seconds": duration_seconds,
            "request_duration_ms": duration_ms,
        }
        self._meter(result)
        return result

    @staticmethod
    def _meter(result: Dict[str, Any]) -> None:
        try:
            from services.ai_usage_service import get_ai_usage_service
            get_ai_usage_service().record_usage(
                provider=result.get("provider", "openai_compatible"),
                operation="transcription",
                model=result.get("model"),
                media_seconds=result.get("duration_seconds"),
                duration_ms=result.get("request_duration_ms"),
            )
        except Exception as exc:
            logger.debug("Transcription usage metering skipped: %s", exc)


# ── Factory ───────────────────────────────────────────────────────────────────

def transcription_enabled() -> bool:
    return get_transcription_provider().describe().get("provider") != "disabled"


def get_transcription_provider() -> AudioTranscriptionProvider:
    provider_name = os.environ.get("PHINS_TRANSCRIPTION_PROVIDER", "disabled").strip().lower()
    if provider_name == "openai_compatible":
        endpoint = os.environ.get("PHINS_TRANSCRIPTION_ENDPOINT", "").strip()
        api_key = os.environ.get("PHINS_TRANSCRIPTION_API_KEY", "").strip()
        if endpoint and api_key:
            try:
                from security.network import assert_safe_provider_url
                assert_safe_provider_url(endpoint)
            except ValueError as exc:
                logger.warning("Transcription endpoint rejected: %s", exc)
                return DisabledTranscriptionProvider()
            return OpenAICompatibleTranscriptionProvider(
                endpoint=endpoint,
                api_key=api_key,
                model=os.environ.get("PHINS_TRANSCRIPTION_MODEL", "whisper-1"),
                timeout=float(os.environ.get("PHINS_TRANSCRIPTION_TIMEOUT", "120")),
            )
        logger.warning(
            "PHINS_TRANSCRIPTION_PROVIDER=openai_compatible but endpoint/key "
            "missing; transcription disabled")
    return DisabledTranscriptionProvider()
