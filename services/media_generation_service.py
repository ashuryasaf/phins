"""
Provider-backed media generation service for PHINS.

Supports prompt-based video generation using external providers and a small,
provider-neutral contract for submitting jobs, polling status, and downloading
completed files. Gemini/Veo, Kling, and Replicate share that contract. Replicate
output is downloaded immediately and the caller checksums the bytes; the API
token never leaves this process.

Supports three Kling API routing profiles:

- ``klingapi`` (default host ``https://api.klingapi.com``): the aggregator
  contract.  Submits to ``/v1/videos/text2video`` and
  ``/v1/videos/image2video`` with the aggregator ``model`` id (for example
  ``kling-v2.6-pro``) and polls ``GET /v1/videos/{task_id}``.
- ``official``: the Kling Open Platform (``api.klingai.com`` and
  ``api-singapore.klingai.com``).  The same paths are used, but the body
  must include ``model_name`` (for example ``kling-v2-6``) plus ``mode``
  ``std``/``pro`` and a string ``duration`` of ``"5"`` or ``"10"``.
  Omitting ``model_name`` is rejected with HTTP 400
  ``model_name is required``.  Polling is
  ``GET /v1/videos/text2video/{task_id}`` or ``image2video``.  Selected
  when the base host ends in ``klingai.com`` or
  ``KLING_API_PROFILE=official``.
- ``evolink-v3``: EvoLink's unified routes
  (https://evolink.ai/blog/how-to-access-kling-ai-api-complete-tutorial):
  ``POST /v1/videos/generations`` + ``GET /v1/tasks/{task_id}``, with
  ``image_start`` for image input.  Picked automatically for ``kling-v3``,
  ``kling-o1``, and ``kling-o3`` unless the configured host is the official
  Open Platform.  Force it with ``KLING_API_PROFILE=evolink-v3``.

Both profiles share the same async pattern: submit a task, store the
``task_id``, poll until terminal, save the resulting video promptly because
generated links are time-limited (24h on EvoLink).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Tuple

from security.network import validated_urlopen

#: Agent attribution for gateway budgets and usage rows (agent_runtime id).
_MEDIA_AGENT_ID = "video_agents"


class MediaGenerationError(RuntimeError):
    """Raised when a media generation provider call fails."""


def _extract_provider_error_detail(body_bytes: bytes) -> str:
    """Pull a human-readable error message out of a provider HTTP error body."""
    if not body_bytes:
        return ""
    try:
        text = body_bytes.decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - defensive
        return ""
    text = text.strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return text[:500]
    if isinstance(parsed, dict):
        candidates = []
        for key in ("message", "error_message", "detail", "msg", "reason"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
        nested_error = parsed.get("error")
        if isinstance(nested_error, dict):
            for key in ("message", "detail", "msg", "reason"):
                value = nested_error.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())
        elif isinstance(nested_error, str) and nested_error.strip():
            candidates.append(nested_error.strip())
        if candidates:
            # Preserve order, dedupe.
            seen = []
            for candidate in candidates:
                if candidate not in seen:
                    seen.append(candidate)
            return " | ".join(seen)[:500]
        return text[:500]
    if isinstance(parsed, list) and parsed:
        return str(parsed[0])[:500]
    return text[:500]


# Kling 3 / EvoLink documents a 2500-character prompt limit; truncating just
# below it avoids brittle off-by-one 400s when callers paste long blueprints.
_KLING_PROMPT_MAX_CHARS = 2500

# EvoLink's unified Kling routes use a single endpoint for text/image input.
_KLING_EVOLINK_BASE_URL = "https://api.evolink.ai"
_KLING_EVOLINK_GENERATIONS_PATH = "/v1/videos/generations"
_KLING_EVOLINK_TASK_PATH_PREFIX = "/v1/tasks/"

# PHINS UI / aggregator ids -> Kling Open Platform ``model_name`` values.
# Quality (pro/std) is carried in the separate ``mode`` field, not the name.
_KLING_OFFICIAL_MODEL_NAMES = {
    "kling-v1": "kling-v1",
    "kling-v1-5": "kling-v1-5",
    "kling-v1.5": "kling-v1-5",
    "kling-v1-6": "kling-v1-6",
    "kling-v1.6": "kling-v1-6",
    "kling-v2-master": "kling-v2-master",
    "kling-v2-1": "kling-v2-1",
    "kling-v2.1": "kling-v2-1",
    "kling-v2-1-master": "kling-v2-1-master",
    "kling-v2.1-master": "kling-v2-1-master",
    "kling-v2-5-turbo": "kling-v2-5-turbo",
    "kling-v2.5-turbo": "kling-v2-5-turbo",
    "kling-v2-6": "kling-v2-6",
    "kling-v2.6": "kling-v2-6",
    "kling-v2.6-pro": "kling-v2-6",
    "kling-v2.6-std": "kling-v2-6",
    "kling-v2-6-pro": "kling-v2-6",
    "kling-v2-6-std": "kling-v2-6",
    "kling-v3": "kling-v3",
    "kling-v3-text-to-video": "kling-v3",
    "kling-v3-image-to-video": "kling-v3",
    "kling-video-o1": "kling-video-o1",
    "kling-o1": "kling-video-o1",
    "kling-o3": "kling-v3",
}


class MediaGenerationService:
    """Thin provider abstraction over real video generation APIs."""

    SUPPORTED_PROVIDERS = {"gemini", "kling", "replicate"}
    DEFAULT_PROVIDER_MODELS = {
        "gemini": ["veo-3.1-generate-preview", "veo-3-fast-preview"],
        "kling": [
            "kling-v2.6-pro",
            "kling-v2.6-std",
            "kling-v3-text-to-video",
            "kling-v3-image-to-video",
        ],
        "replicate": list(_DEFAULT_REPLICATE_MODELS),
    }

    def __init__(self) -> None:
        self._gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self._gemini_model = os.environ.get("PHINS_GEMINI_VIDEO_MODEL", "veo-3.1-generate-preview").strip()
        self._kling_api_key = os.environ.get("KLING_API_KEY", "").strip()
        self._kling_access_key = os.environ.get("KLING_ACCESS_KEY", "").strip()
        self._kling_secret_key = os.environ.get("KLING_SECRET_KEY", "").strip()
        self._kling_profile = os.environ.get("KLING_API_PROFILE", "").strip().lower()
        if self._kling_profile == "evolink-v3":
            default_base = _KLING_EVOLINK_BASE_URL
            default_t2v = _KLING_EVOLINK_GENERATIONS_PATH
            default_i2v = _KLING_EVOLINK_GENERATIONS_PATH
        else:
            default_base = "https://api.klingapi.com"
            default_t2v = "/v1/videos/text2video"
            default_i2v = "/v1/videos/image2video"
        self._kling_base_url = os.environ.get("KLING_API_BASE_URL", default_base).strip().rstrip("/")
        self._kling_text_to_video_path = os.environ.get("KLING_TEXT_TO_VIDEO_PATH", default_t2v).strip()
        self._kling_image_to_video_path = os.environ.get("KLING_IMAGE_TO_VIDEO_PATH", default_i2v).strip()
        self._replicate_api_token = os.environ.get("REPLICATE_API_TOKEN", "").strip()
        self._replicate_base_url = os.environ.get(
            "REPLICATE_API_BASE_URL", "https://api.replicate.com"
        ).strip().rstrip("/")
        self._replicate_models = self._configured_replicate_models()

    def supported_provider_config(self) -> Dict[str, Dict[str, Any]]:
        """Return provider availability and public configuration hints."""
        return {
            "gemini": {
                "enabled": bool(self._gemini_api_key),
                "label": "Gemini / Veo",
                "model": self._gemini_model,
                "models": list(self.DEFAULT_PROVIDER_MODELS["gemini"]),
            },
            "kling": {
                "enabled": self._kling_credentials_available(),
                "label": "Kling",
                "base_url": self._kling_base_url,
                "api_schema": self._kling_public_schema_name(),
                "models": list(self.DEFAULT_PROVIDER_MODELS["kling"]),
            },
            "replicate": {
                "enabled": bool(self._replicate_api_token),
                "label": "Replicate",
                "model": self._replicate_models[0] if self._replicate_models else "",
                "models": list(self._replicate_models),
            },
        }

    def submit_video_generation(
        self,
        *,
        provider: str,
        prompt: str,
        title: str,
        model: str = "",
        aspect_ratio: str = "16:9",
        duration_seconds: int = 8,
        resolution: str = "720p",
        image_data_url: str = "",
        callback_url: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        attribution: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Submit a provider-backed video generation request.

        ``attribution`` (optional) names who the paid submit is for so the
        external-call gateway budgets and meters it per submitter instead of
        in one shared bucket: ``{"user_id": ..., "job_id": ..., "customer_id": ...}``.
        """
        provider_name = str(provider or "").strip().lower()
        if provider_name not in self.SUPPORTED_PROVIDERS:
            raise MediaGenerationError(f"Unsupported video provider: {provider}")
        if not str(prompt or "").strip():
            raise MediaGenerationError("Video prompt is required")

        if provider_name == "gemini":
            return self._submit_gemini_video(
                prompt=prompt,
                title=title,
                model=model,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
                resolution=resolution,
                image_data_url=image_data_url,
                callback_url=callback_url,
                metadata=metadata or {},
                attribution=attribution,
            )

        if provider_name == "replicate":
            return self._submit_replicate_video(
                prompt=prompt,
                title=title,
                model=model,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
                resolution=resolution,
                image_data_url=image_data_url,
                callback_url=callback_url,
                metadata=metadata or {},
                attribution=attribution,
            )

        return self._submit_kling_video(
            prompt=prompt,
            title=title,
            model=model,
            aspect_ratio=aspect_ratio,
            duration_seconds=duration_seconds,
            image_data_url=image_data_url,
            callback_url=callback_url,
            metadata=metadata or {},
            attribution=attribution,
        )

    def poll_video_generation(
        self,
        *,
        provider: str,
        provider_job_id: str,
        provider_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Poll a previously submitted provider video generation job."""
        provider_name = str(provider or "").strip().lower()
        if provider_name == "gemini":
            return self._poll_gemini_video(provider_job_id=provider_job_id)
        if provider_name == "kling":
            return self._poll_kling_video(provider_job_id=provider_job_id, provider_state=provider_state or {})
        if provider_name == "replicate":
            return self._poll_replicate_video(
                provider_job_id=provider_job_id,
                provider_state=provider_state or {},
            )
        raise MediaGenerationError(f"Unsupported video provider: {provider}")

    def _is_replicate_api_host(self, hostname: str) -> bool:
        """True only for the configured Replicate API host."""
        api_host = (urllib.parse.urlparse(self._replicate_base_url).hostname or "").lower()
        return bool(api_host) and (hostname or "").lower() == api_host

    def download_generated_video(
        self,
        *,
        provider: str,
        download_url: str,
        stream_to_path: str = '',
    ) -> Dict[str, Any]:
        """Download a completed video and return a data URL + metadata.

        When *stream_to_path* is provided, bytes are streamed to that file
        instead of being held entirely in memory.  The returned dict then
        contains ``file_path`` instead of ``data_url``.
        """
        provider_name = str(provider or "").strip().lower()
        parsed = urllib.parse.urlparse(download_url or "")
        if not parsed.scheme or not parsed.netloc:
            raise MediaGenerationError("Completed provider response did not include a valid video URL")

        if provider_name == "gemini":
            headers = {"x-goog-api-key": self._gemini_api_key}
        elif provider_name == "kling":
            headers = {"Authorization": self._kling_authorization_header()}
        elif provider_name == "replicate":
            if not self._replicate_api_token:
                raise MediaGenerationError("REPLICATE_API_TOKEN is not configured")
            # A prediction or webhook payload can name any host, so the bearer
            # token only ever goes to the API host. Delivery URLs are public
            # and need no credential.
            headers = {}
            if self._is_replicate_api_host(parsed.hostname):
                headers["Authorization"] = f"Bearer {self._replicate_api_token}"
        else:
            raise MediaGenerationError(f"Unsupported video provider: {provider}")

        request = urllib.request.Request(download_url, headers=headers, method="GET")
        try:
            response_ctx = validated_urlopen(request, timeout=300, allowed_schemes=("https",))
        except urllib.error.HTTPError as exc:
            if provider_name == "replicate":
                raise MediaGenerationError(f"Replicate download failed with HTTP {exc.code}") from exc
            raise
        with response_ctx as response:
            content_type = response.headers.get("Content-Type", "video/mp4").split(";", 1)[0].strip() or "video/mp4"

            if stream_to_path:
                total_size = 0
                chunk_size = 256 * 1024
                with open(stream_to_path, 'wb') as dest:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        dest.write(chunk)
                        total_size += len(chunk)
                return {
                    "file_path": stream_to_path,
                    "content_type": content_type,
                    "size": total_size,
                }

            video_bytes = response.read()

        encoded = base64.b64encode(video_bytes).decode("ascii")
        return {
            "data_url": f"data:{content_type};base64,{encoded}",
            "content_type": content_type,
            "size": len(video_bytes),
        }

    def cancel_video_generation(self, *, provider: str, provider_job_id: str) -> None:
        """Best-effort cancel of a provider prediction. Replicate is the only
        provider with a cancel route wired here; other providers are a no-op."""
        if str(provider or "").strip().lower() != "replicate":
            return
        if not self._replicate_api_token or not str(provider_job_id or "").strip():
            return
        url = (
            f"{self._replicate_base_url}/v1/predictions/"
            f"{urllib.parse.quote(str(provider_job_id).strip(), safe='')}/cancel"
        )
        request = urllib.request.Request(
            url,
            data=b"{}",
            headers={
                "Authorization": f"Bearer {self._replicate_api_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        self._read_json_with_diagnostics(
            request,
            timeout=20,
            provider_label="Replicate",
            operation="cancel",
        )

    def probe_replicate_account(self) -> Dict[str, Any]:
        """GET /v1/account. Returns ok/http_status/detail and never the token or account body."""
        if not self._replicate_api_token:
            return {"ok": False, "http_status": 0, "detail": "token_missing"}
        url = f"{self._replicate_base_url}/v1/account"
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self._replicate_api_token}"},
            method="GET",
        )
        try:
            with validated_urlopen(request, timeout=8, allowed_schemes=("https",)) as response:
                response.read()
                status = int(getattr(response, "status", 200) or 200)
            return {"ok": 200 <= status < 300, "http_status": status, "detail": "accepted"}
        except urllib.error.HTTPError as exc:
            status = int(getattr(exc, "code", 0) or 0)
            detail = "rejected" if status in {401, 403} else "http_error"
            return {"ok": False, "http_status": status, "detail": detail}
        except Exception:
            return {"ok": False, "http_status": 0, "detail": "unreachable"}

    def _submit_replicate_video(
        self,
        *,
        prompt: str,
        title: str,
        model: str,
        aspect_ratio: str,
        duration_seconds: int,
        resolution: str,
        image_data_url: str,
        callback_url: str,
        metadata: Dict[str, Any],
        attribution: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self._replicate_api_token:
            raise MediaGenerationError("REPLICATE_API_TOKEN is not configured")

        owner, name, version = self._split_replicate_model(model)
        if not owner or not name:
            raise MediaGenerationError(f"Invalid Replicate model: {model or '(default)'}")

        model_label = f"{owner}/{name}" + (f":{version}" if version else "")
        model_input = self._replicate_input(
            prompt=prompt,
            model_label=model_label,
            aspect_ratio=aspect_ratio,
            duration_seconds=duration_seconds,
            resolution=resolution,
            image_data_url=image_data_url,
        )
        body: Dict[str, Any] = {"input": model_input}
        if version:
            body["version"] = version
            url = f"{self._replicate_base_url}/v1/predictions"
        else:
            url = (
                f"{self._replicate_base_url}/v1/models/"
                f"{urllib.parse.quote(owner, safe='')}/"
                f"{urllib.parse.quote(name, safe='')}/predictions"
            )
        # Replicate has no free-form metadata field. The callback URL already
        # carries the PHINS job id. Only documented input keys are sent, so an
        # unknown field cannot 422 the prediction. ``metadata`` stays on the
        # PHINS job record.
        _ = metadata
        callback = str(callback_url or "").strip()
        if callback.startswith("https://"):
            body["webhook"] = callback
            body["webhook_events_filter"] = ["completed"]

        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._replicate_api_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        response_body = self._read_json_with_diagnostics(
            request,
            timeout=60,
            provider_label="Replicate",
            operation="submit",
            attribution=attribution,
        )
        prediction_id = str(response_body.get("id") or "").strip()
        if not prediction_id:
            raise MediaGenerationError("Replicate generation did not return a prediction id")
        urls = response_body.get("urls") if isinstance(response_body.get("urls"), dict) else {}
        get_url = str(urls.get("get") or "").strip() or (
            f"{self._replicate_base_url}/v1/predictions/{urllib.parse.quote(prediction_id, safe='')}"
        )
        return {
            "provider": "replicate",
            "provider_job_id": prediction_id,
            "status": "queued",
            "message": f"Submitted to Replicate ({model_label}) for \"{title}\"",
            "provider_state": {
                "prediction_id": prediction_id,
                "get_url": get_url,
                "model": model_label,
            },
        }

    def _poll_replicate_video(
        self,
        *,
        provider_job_id: str,
        provider_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self._replicate_api_token:
            raise MediaGenerationError("REPLICATE_API_TOKEN is not configured")
        if not provider_job_id:
            raise MediaGenerationError("Replicate prediction id is required")
        status_url = str(provider_state.get("get_url") or "").strip()
        if not status_url:
            status_url = (
                f"{self._replicate_base_url}/v1/predictions/"
                f"{urllib.parse.quote(provider_job_id, safe='')}"
            )
        request = urllib.request.Request(
            status_url,
            headers={"Authorization": f"Bearer {self._replicate_api_token}"},
            method="GET",
        )
        body = self._read_json_with_diagnostics(
            request,
            timeout=60,
            provider_label="Replicate",
            operation="poll",
        )
        normalized = self.normalize_replicate_prediction(body)
        state = normalized.get("provider_state") if isinstance(normalized.get("provider_state"), dict) else {}
        state["get_url"] = status_url
        state["model"] = str(provider_state.get("model") or "")
        normalized["provider_state"] = state
        return normalized

    def _split_replicate_model(self, model: str) -> Tuple[str, str, str]:
        selected = str(model or "").strip() or (self._replicate_models[0] if self._replicate_models else "")
        if not self.replicate_model_id_ok(selected):
            return "", "", ""
        version = ""
        if ":" in selected:
            selected, version = selected.split(":", 1)
        owner, _, name = selected.partition("/")
        return owner, name, version

    def _replicate_input(
        self,
        *,
        prompt: str,
        model_label: str,
        aspect_ratio: str,
        duration_seconds: int,
        resolution: str,
        image_data_url: str,
    ) -> Dict[str, Any]:
        """Only fields shared by the official video models. Unknown keys 422."""
        model_input: Dict[str, Any] = {"prompt": str(prompt or "")}
        aspect = str(aspect_ratio or "").strip()
        if aspect in _REPLICATE_ASPECTS:
            model_input["aspect_ratio"] = aspect
        model_input["duration"] = self._replicate_duration(model_label, duration_seconds)
        selected_resolution = str(resolution or "").strip().lower()
        if selected_resolution in _REPLICATE_RESOLUTIONS:
            model_input["resolution"] = selected_resolution
        image_value = str(image_data_url or "").strip()
        if image_value.startswith(("https://", "http://", "data:")):
            model_input["image"] = image_value
        return model_input

    @staticmethod
    def _replicate_duration(model_label: str, duration_seconds: int) -> int:
        requested = int(duration_seconds or 8)
        if "veo" in str(model_label or "").lower():
            # Veo accepts 4, 6, or 8 seconds. Snap so a blueprint default of 8
            # is sent as-is and nearby values do not 422.
            return min((4, 6, 8), key=lambda choice: (abs(choice - requested), choice))
        return max(1, min(requested, 15))

    @staticmethod
    def _configured_replicate_models() -> list:
        raw = os.environ.get("REPLICATE_VIDEO_MODELS", "").strip()
        if not raw:
            return list(_DEFAULT_REPLICATE_MODELS)
        models = []
        for part in raw.split(","):
            candidate = part.strip()
            if candidate and MediaGenerationService.replicate_model_id_ok(candidate):
                models.append(candidate)
        return models or list(_DEFAULT_REPLICATE_MODELS)

    @staticmethod
    def replicate_model_id_ok(model: str) -> bool:
        return bool(_REPLICATE_MODEL_RE.match(str(model or "").strip()))

    @staticmethod
    def extract_media_url(value: Any) -> str:
        """First HTTPS (or HTTP) media URL in a Replicate ``output`` value."""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith(("https://", "http://")):
                return text
            return ""
        if isinstance(value, list):
            urls = [MediaGenerationService.extract_media_url(item) for item in value]
            urls = [url for url in urls if url]
            for url in urls:
                lowered = url.lower()
                if ".mp4" in lowered or "video" in lowered:
                    return url
            return urls[0] if urls else ""
        if isinstance(value, dict):
            for key in ("video", "url", "mp4", "path"):
                found = MediaGenerationService.extract_media_url(value.get(key))
                if found:
                    return found
        return ""

    @staticmethod
    def normalize_replicate_prediction(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Map a Replicate prediction object onto the PHINS poll/webhook shape.

        ``succeeded`` without a file URL is a failure: the caller must not
        checksum an empty body or mark the job complete.
        """
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(data, dict):
            data = {}
        status = str(data.get("status") or "").strip().lower()
        prediction_id = str(data.get("id") or "").strip()
        error = data.get("error")
        if isinstance(error, dict):
            error_text = str(error.get("message") or error.get("detail") or "").strip()
        else:
            error_text = str(error or "").strip()
        output_url = MediaGenerationService.extract_media_url(data.get("output"))
        state = {
            "prediction_id": prediction_id,
            "status": status,
            "output_url": output_url,
            "error": error_text,
        }
        if status in {"starting", "processing"}:
            return {
                "status": "processing",
                "message": "Replicate is still generating the video.",
                "provider_job_id": prediction_id,
                "download_url": "",
                "provider_state": state,
            }
        if status in {"failed", "canceled", "cancelled"}:
            return {
                "status": "failed",
                "error": error_text or "Replicate generation failed",
                "message": error_text or "Replicate generation failed",
                "provider_job_id": prediction_id,
                "provider_state": state,
            }
        if status == "succeeded":
            if not output_url:
                return {
                    "status": "failed",
                    "error": "Replicate completed without a downloadable video URL",
                    "message": "Replicate completed without a downloadable video URL",
                    "provider_job_id": prediction_id,
                    "provider_state": state,
                }
            return {
                "status": "completed",
                "message": "Replicate video is ready.",
                "provider_job_id": prediction_id,
                "download_url": output_url,
                "provider_state": state,
            }
        return {
            "status": "processing",
            "message": f"Replicate video status: {status or 'unknown'}",
            "provider_job_id": prediction_id,
            "download_url": "",
            "provider_state": state,
        }

    @staticmethod
    def verify_replicate_webhook_signature(secret: str, headers: Any, raw_body: bytes) -> bool:
        """Verify a Replicate (Svix) webhook signature. The secret is ``whsec_`` + base64 key."""
        raw_secret = str(secret or "").strip()
        if not raw_secret.startswith("whsec_"):
            return False
        try:
            secret_bytes = base64.b64decode(raw_secret.split("_", 1)[1])
        except Exception:
            return False
        if not secret_bytes:
            return False
        webhook_id = str(headers.get("webhook-id") or "").strip()
        webhook_timestamp = str(headers.get("webhook-timestamp") or "").strip()
        signature_header = str(headers.get("webhook-signature") or "").strip()
        if not webhook_id or not webhook_timestamp or not signature_header:
            return False
        try:
            body_text = raw_body.decode("utf-8")
        except UnicodeDecodeError:
            return False
        signed = f"{webhook_id}.{webhook_timestamp}.{body_text}".encode("utf-8")
        expected = base64.b64encode(hmac.new(secret_bytes, signed, hashlib.sha256).digest()).decode("ascii")
        for part in signature_header.split():
            version, _, signature = part.partition(",")
            if version == "v1" and signature and hmac.compare_digest(signature, expected):
                return True
        return False

    def _submit_gemini_video(
        self,
        *,
        prompt: str,
        title: str,
        model: str,
        aspect_ratio: str,
        duration_seconds: int,
        resolution: str,
        image_data_url: str,
        callback_url: str,
        metadata: Dict[str, Any],
        attribution: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self._gemini_api_key:
            raise MediaGenerationError("GEMINI_API_KEY is not configured")

        selected_model = str(model or self._gemini_model).strip() or self._gemini_model

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{urllib.parse.quote(selected_model, safe='')}:predictLongRunning"
        )
        instance: Dict[str, Any] = {"prompt": prompt}
        image_payload = self._parse_data_url(image_data_url)
        if image_payload:
            instance["image"] = {
                "imageBytes": image_payload["bytes_b64"],
                "mimeType": image_payload["mime_type"],
            }

        request_body: Dict[str, Any] = {
            "instances": [instance],
            "parameters": {
                "aspectRatio": aspect_ratio or "16:9",
                "durationSeconds": int(max(1, duration_seconds or 8)),
                "resolution": resolution or "720p",
            },
        }
        if metadata:
            request_body["metadata"] = metadata
        if callback_url:
            request_body.setdefault("metadata", {})
            request_body["metadata"]["phins_callback_url"] = callback_url

        payload = json.dumps(request_body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self._gemini_api_key,
            },
            method="POST",
        )
        body = self._read_json_with_diagnostics(
            request,
            timeout=60,
            provider_label="Gemini/Veo",
            operation="submit",
            attribution=attribution,
        )

        operation_name = str(body.get("name") or "").strip()
        if not operation_name:
            raise MediaGenerationError("Gemini video generation did not return an operation name")

        return {
            "provider": "gemini",
            "provider_job_id": operation_name,
            "status": "queued",
            "message": f"Submitted to Gemini/Veo for \"{title}\"",
            "provider_state": {
                "operation_name": operation_name,
                "model": selected_model,
            },
        }

    def _poll_gemini_video(self, *, provider_job_id: str) -> Dict[str, Any]:
        if not self._gemini_api_key:
            raise MediaGenerationError("GEMINI_API_KEY is not configured")
        if not provider_job_id:
            raise MediaGenerationError("Gemini provider job id is required")

        url = f"https://generativelanguage.googleapis.com/v1beta/{provider_job_id.lstrip('/')}"
        request = urllib.request.Request(
            url,
            headers={"x-goog-api-key": self._gemini_api_key},
            method="GET",
        )
        body = self._read_json_with_diagnostics(
            request,
            timeout=60,
            provider_label="Gemini/Veo",
            operation="poll",
        )

        if body.get("done") is not True:
            return {
                "status": "processing",
                "message": "Gemini/Veo is still generating the video.",
                "provider_job_id": provider_job_id,
                "provider_state": body,
            }

        if body.get("error"):
            return {
                "status": "failed",
                "error": body["error"].get("message", "Gemini/Veo generation failed"),
                "provider_job_id": provider_job_id,
                "provider_state": body,
            }

        response_payload = body.get("response", {})
        samples = (
            response_payload.get("generatedVideos")
            or response_payload.get("generated_videos")
            or response_payload.get("generateVideoResponse", {}).get("generatedSamples")
            or []
        )
        first_sample = samples[0] if samples else {}
        video_payload = first_sample.get("video") or {}
        download_url = str(video_payload.get("uri") or video_payload.get("downloadUri") or "").strip()
        if not download_url:
            raise MediaGenerationError("Gemini/Veo generation completed without a downloadable video URI")

        return {
            "status": "completed",
            "message": "Gemini/Veo video is ready.",
            "provider_job_id": provider_job_id,
            "download_url": download_url,
            "provider_state": body,
        }

    def _submit_kling_video(
        self,
        *,
        prompt: str,
        title: str,
        model: str,
        aspect_ratio: str,
        duration_seconds: int,
        image_data_url: str,
        callback_url: str,
        metadata: Dict[str, Any],
        attribution: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self._kling_credentials_available():
            raise MediaGenerationError("Kling credentials are not configured (set KLING_API_KEY or KLING_ACCESS_KEY + KLING_SECRET_KEY)")

        selected_model = str(model or self.DEFAULT_PROVIDER_MODELS["kling"][0]).strip() or self.DEFAULT_PROVIDER_MODELS["kling"][0]
        # Enforce Kling's documented 2500-character prompt limit so we reject
        # oversized prompts before the provider responds with HTTP 400.  We
        # truncate rather than raise to keep batch jobs flowing — the original
        # untruncated prompt is preserved in metadata for traceability.
        safe_prompt = self._clamp_kling_prompt(prompt)
        evolink_profile = self._kling_use_evolink_profile(selected_model)
        official_schema = (not evolink_profile) and self._kling_use_official_schema()
        duration_value = self._normalize_kling_duration(duration_seconds)
        official_model = self._official_kling_model_name(selected_model)
        # The Open Platform rejects a body that only has ``model`` with
        # HTTP 400 ``model_name is required``.  Aggregators still read
        # ``model``.  Sending the official id under ``model_name`` on every
        # direct submit satisfies both contracts without rewriting stored jobs.
        if evolink_profile:
            body: Dict[str, Any] = {
                "model": selected_model,
                "prompt": safe_prompt,
                "aspect_ratio": aspect_ratio or "16:9",
                "duration": duration_value,
            }
        elif official_schema:
            body = {
                "model_name": official_model,
                "prompt": safe_prompt,
                "aspect_ratio": aspect_ratio or "16:9",
                # Open Platform duration is the string enum "5" / "10".
                "duration": str(duration_value),
            }
        else:
            body = {
                "model": selected_model,
                "model_name": official_model,
                "prompt": safe_prompt,
                "aspect_ratio": aspect_ratio or "16:9",
                # Same string enum as the Open Platform. The live validator
                # behind the aggregator host is the one that returns
                # "model_name is required"; it also rejects a numeric duration
                # after that field is present.
                "duration": str(duration_value),
            }
        mode = self._kling_generation_mode(selected_model)
        if mode and not evolink_profile:
            # EvoLink's unified route doesn't accept the legacy "mode" field;
            # only the direct Kling API needs it.
            body["mode"] = mode
        # Resolve the routing once: when the model name auto-selects the
        # EvoLink profile but the env vars still point at the direct Kling API,
        # we transparently switch the base URL and unified path so callers
        # don't have to set KLING_API_BASE_URL manually for every kling-v3 job.
        if evolink_profile:
            base_url = (
                self._kling_base_url
                if self._kling_base_url.rstrip("/") == _KLING_EVOLINK_BASE_URL
                else _KLING_EVOLINK_BASE_URL
            )
            text_path = _KLING_EVOLINK_GENERATIONS_PATH
            image_path = _KLING_EVOLINK_GENERATIONS_PATH
        else:
            base_url = self._kling_base_url
            text_path = self._kling_text_to_video_path
            image_path = self._kling_image_to_video_path
        image_payload = self._parse_data_url(image_data_url)
        endpoint_path = text_path
        image_field = "image_start" if evolink_profile else "image"
        if image_payload:
            endpoint_path = image_path
            body[image_field] = image_payload["bytes_b64"]
        elif str(image_data_url or "").strip():
            parsed_image_url = urllib.parse.urlparse(str(image_data_url).strip())
            if parsed_image_url.scheme in {"http", "https"} and parsed_image_url.netloc:
                endpoint_path = image_path
                body[image_field] = str(image_data_url).strip()
        if callback_url:
            # Direct Kling uses callBackUrl; EvoLink-style routes accept
            # callback_url.  Send both so the provider can pick the right one.
            body["callBackUrl"] = callback_url
            body["callback_url"] = callback_url

        url = f"{base_url}{endpoint_path}"
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": self._kling_authorization_header(),
            },
            method="POST",
        )
        response_body = self._read_json_with_diagnostics(
            request,
            timeout=60,
            provider_label="Kling",
            operation="submit",
            attribution=attribution,
        )

        business_error = self._kling_business_error(response_body)
        if business_error:
            # A 200 with a non-zero business code is a rejection.  Do not
            # store a task id for a job the provider refused.
            raise MediaGenerationError(f"Kling submit failed: {business_error}")

        data = response_body.get("data") if isinstance(response_body.get("data"), dict) else response_body
        provider_job_id = str(
            response_body.get("task_id")
            or data.get("task_id")
            or data.get("id")
            or data.get("job_id")
            or data.get("taskId")
            or response_body.get("id")
            or ""
        ).strip()
        if not provider_job_id:
            raise MediaGenerationError("Kling generation did not return a task id")

        if evolink_profile:
            status_url = f"{base_url}{_KLING_EVOLINK_TASK_PATH_PREFIX}{urllib.parse.quote(provider_job_id, safe='')}"
        else:
            status_url = self._build_kling_status_url(
                provider_job_id,
                model_name=selected_model,
                endpoint_path=endpoint_path if official_schema else "",
            )

        return {
            "provider": "kling",
            "provider_job_id": provider_job_id,
            "status": "queued",
            "message": f"Submitted to Kling for \"{title}\"",
            "provider_state": {
                "submit_response": response_body,
                "status_url": status_url,
                "model": selected_model,
                "model_name": str(body.get("model_name") or official_model),
                "endpoint_path": endpoint_path,
                "official_schema": official_schema,
                "evolink_profile": evolink_profile,
            },
        }

    def _poll_kling_video(
        self,
        *,
        provider_job_id: str,
        provider_state: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not self._kling_credentials_available():
            raise MediaGenerationError("Kling credentials are not configured (set KLING_API_KEY or KLING_ACCESS_KEY + KLING_SECRET_KEY)")
        if not provider_job_id:
            raise MediaGenerationError("Kling provider job id is required")

        status_url = str(
            provider_state.get("status_url")
            or self._build_kling_status_url(
                provider_job_id,
                model_name=str(provider_state.get("model") or ""),
                endpoint_path=str(provider_state.get("endpoint_path") or ""),
            )
        ).strip()
        request = urllib.request.Request(
            status_url,
            headers={"Authorization": self._kling_authorization_header()},
            method="GET",
        )
        body = self._read_json_with_diagnostics(
            request,
            timeout=60,
            provider_label="Kling",
            operation="poll",
        )

        business_error = self._kling_business_error(body)
        if business_error:
            return {
                "status": "failed",
                "error": business_error,
                "provider_job_id": provider_job_id,
                "provider_state": {
                    "status_url": status_url,
                    "last_poll": body,
                },
            }

        data = body.get("data") if isinstance(body.get("data"), dict) else body
        status_value = str(
            body.get("status")
            or data.get("status")
            or data.get("task_status")
            or data.get("state")
            or ""
        ).strip().lower()

        if status_value in {"queued", "pending", "submitted", "processing", "running", "in_progress", "generating", "created", "in progress"}:
            return {
                "status": "processing",
                "message": "Kling is still generating the video.",
                "provider_job_id": provider_job_id,
                "provider_state": {
                    "status_url": status_url,
                    "last_poll": body,
                },
            }

        if status_value in {"failed", "error", "cancelled", "aborted", "rejected"}:
            error_obj = data.get("error") if isinstance(data.get("error"), dict) else {}
            error_message = str(
                data.get("error_message")
                or error_obj.get("message")
                or data.get("message")
                or "Kling generation failed"
            )
            return {
                "status": "failed",
                "error": error_message,
                "provider_job_id": provider_job_id,
                "provider_state": {
                    "status_url": status_url,
                    "last_poll": body,
                },
            }

        download_url = self._extract_kling_download_url(data)
        if not download_url and data is not body:
            download_url = self._extract_kling_download_url(body)
        if not download_url:
            if status_value not in {"succeed", "succeeded", "completed", "done", "ready", "complete"}:
                return {
                    "status": "processing",
                    "message": f"Kling video status: {status_value or 'unknown'}",
                    "provider_job_id": provider_job_id,
                    "provider_state": {
                        "status_url": status_url,
                        "last_poll": body,
                    },
                }
            raise MediaGenerationError("Kling generation completed without a downloadable video URL")

        return {
            "status": "completed",
            "message": "Kling video is ready.",
            "provider_job_id": provider_job_id,
            "download_url": download_url,
            "provider_state": {
                "status_url": status_url,
                "last_poll": body,
            },
        }

    def _build_kling_status_url(self, provider_job_id: str, model_name: str = "", endpoint_path: str = "") -> str:
        encoded_id = urllib.parse.quote(provider_job_id, safe="")
        # EvoLink polls at /v1/tasks/{task_id}.  The Open Platform polls the
        # same resource that accepted the task (/v1/videos/text2video/{id}
        # or image2video).  The aggregator polls /v1/videos/{task_id}.
        if self._kling_use_evolink_profile(model_name):
            return f"{self._kling_base_url}{_KLING_EVOLINK_TASK_PATH_PREFIX}{encoded_id}"
        if self._kling_use_official_schema():
            resource = str(endpoint_path or "/v1/videos/text2video").strip() or "/v1/videos/text2video"
            if not resource.startswith("/"):
                resource = f"/{resource}"
            return f"{self._kling_base_url}{resource.rstrip('/')}/{encoded_id}"
        return f"{self._kling_base_url}/v1/videos/{encoded_id}"

    @staticmethod
    def _normalize_kling_duration(duration_seconds: int) -> int:
        requested_seconds = int(duration_seconds or 5)
        return 5 if requested_seconds <= 5 else 10

    def _kling_api_host(self) -> str:
        return urllib.parse.urlparse(self._kling_base_url).netloc.lower()

    def _kling_use_official_schema(self) -> bool:
        """Return True when submits must use the Open Platform ``model_name`` contract.

        That contract is what answers HTTP 400 ``model_name is required`` when
        a body only carries the aggregator ``model`` field.  Duration on this
        contract is the string enum ``"5"`` / ``"10"``, and task polling stays
        on the submit resource.
        """
        profile = self._kling_profile
        if profile in {"official", "klingai", "official-v1"}:
            return True
        if profile in {"klingapi", "aggregator", "direct", "evolink-v3"}:
            return False
        host = self._kling_api_host()
        if host.endswith("klingai.com"):
            return True
        return False

    def _kling_public_schema_name(self) -> str:
        """Operator-facing schema label. Never includes credentials."""
        if self._kling_profile == "evolink-v3" or self._kling_base_url.rstrip("/") == _KLING_EVOLINK_BASE_URL:
            return "evolink"
        if self._kling_use_official_schema():
            return "official"
        return "klingapi"

    @staticmethod
    def _official_kling_model_name(model_name: str) -> str:
        """Map a PHINS / aggregator model id onto an Open Platform ``model_name``."""
        normalized = str(model_name or "").strip().lower()
        if normalized in _KLING_OFFICIAL_MODEL_NAMES:
            return _KLING_OFFICIAL_MODEL_NAMES[normalized]
        converted = normalized.replace(".", "-")
        for suffix in ("-professional", "-standard", "-pro", "-std"):
            if converted.endswith(suffix):
                stem = converted[: -len(suffix)]
                if stem:
                    converted = stem
                break
        return _KLING_OFFICIAL_MODEL_NAMES.get(converted, converted or "kling-v2-6")

    @staticmethod
    def _kling_business_error(body: Dict[str, Any]) -> str:
        """Return the provider message when a JSON body carries a non-zero code.

        Kling answers some rejections as HTTP 200 ``{"code": 1201, "message": ...}``.
        ``code`` 0 (and 200) means the call was accepted.  Missing ``code`` is
        the aggregator success shape and is not an error.
        """
        if not isinstance(body, dict):
            return ""
        code = body.get("code")
        if isinstance(code, str) and code.strip().lstrip("-").isdigit():
            try:
                code = int(code.strip())
            except ValueError:
                return ""
        if isinstance(code, bool) or not isinstance(code, int):
            return ""
        if code in (0, 200):
            return ""
        message = str(body.get("message") or body.get("msg") or "").strip()
        return message or f"Kling error code {code}"

    @staticmethod
    def _kling_generation_mode(model_name: str) -> str:
        """Map a Kling model suffix to the API's documented ``mode`` value.

        Per the official Kling AI API reference, the ``mode`` field only
        accepts the short forms ``"std"`` (720P standard) and ``"pro"``
        (1080P professional).  Earlier PHINS revisions sent the long forms
        ``"standard"``/``"professional"`` which triggered HTTP 400 responses
        like ``mode value 'professional' is invalid``.
        """
        normalized = str(model_name or "").strip().lower()
        if normalized.endswith("-pro") or normalized.endswith("-professional"):
            return "pro"
        if normalized.endswith("-std") or normalized.endswith("-standard"):
            return "std"
        return ""

    def _kling_use_evolink_profile(self, model_name: str) -> bool:
        """Return True when the Kling request should target EvoLink's unified routes."""
        if self._kling_profile == "evolink-v3":
            return True
        # A configured Open Platform host must stay on that host.  Auto-routing
        # kling-v3 to EvoLink would drop the caller's credentials and skip
        # model_name, which is the field that host requires.
        if self._kling_use_official_schema():
            return False
        if self._kling_base_url.rstrip("/") == _KLING_EVOLINK_BASE_URL:
            return True
        if _KLING_EVOLINK_GENERATIONS_PATH in self._kling_text_to_video_path:
            return True
        normalized = str(model_name or "").strip().lower()
        return (
            normalized.startswith("kling-v3")
            or normalized.startswith("kling-o1")
            or normalized.startswith("kling-o3")
        )

    @staticmethod
    def _clamp_kling_prompt(prompt: str) -> str:
        """Truncate prompts so they fit Kling's documented 2500-char limit."""
        text = str(prompt or "")
        if len(text) <= _KLING_PROMPT_MAX_CHARS:
            return text
        return text[: _KLING_PROMPT_MAX_CHARS - 3].rstrip() + "..."

    @staticmethod
    def _read_json_with_diagnostics(
        request: urllib.request.Request,
        *,
        timeout: float,
        provider_label: str,
        operation: str,
        attribution: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Open *request* and decode JSON, surfacing provider error bodies.

        ``urllib.error.HTTPError`` only exposes a generic ``HTTP Error 400: Bad
        Request`` style message by default.  Providers like Kling and Gemini
        embed actionable details in the response body (missing field, invalid
        model, rate limit hint, etc.), so we read and surface them in the
        ``MediaGenerationError`` instead of letting the cryptic default reach
        the UI.
        """
        from services.external_call_gateway import GatewayError, get_gateway

        def request_fn() -> bytes:
            with validated_urlopen(request, timeout=timeout, allowed_schemes=("https",)) as response:
                return response.read()

        # Gateway policy (design §A2): breaker per provider host, jittered
        # retry for transient failures on idempotent operations only — a
        # ``submit`` creates a paid job, so a 5xx after the provider may have
        # accepted it is never retried (that would double-bill). Submits are
        # metered as one usage row each and charged to the daily budget;
        # polls/downloads are not billable, so they stay outside the budget —
        # otherwise routine polling would exhaust the cap and strand the
        # already-paid jobs it is polling for.
        provider_kind = provider_label.split("/")[0].strip().lower() or "media"
        billable = operation == "submit"
        # Budget scope: the customer when the job is on a customer's behalf,
        # else the submitting user — never a shared global bucket, so one
        # submitter cannot exhaust everyone else's daily video budget.
        attribution = {k: str(v) for k, v in (attribution or {}).items() if v}
        budget_scope = attribution.get("customer_id") or (
            f"user:{attribution['user_id']}" if attribution.get("user_id") else None)
        context = {k: attribution[k] for k in ("customer_id", "job_id") if k in attribution}
        try:
            raw = get_gateway().call(
                provider_kind,
                request_fn,
                endpoint=urllib.parse.urlparse(request.full_url).netloc,
                operation=f"video_{operation}",
                agent_id=_MEDIA_AGENT_ID,
                budget_scope=budget_scope,
                context=context,
                max_retries=0 if billable else None,
                budget=billable,
                meter=billable,
                usage_from=lambda _raw: {"model": None},
            )
        except GatewayError as exc:
            raise MediaGenerationError(f"{provider_label} {operation} refused: {exc}") from exc
        except urllib.error.HTTPError as exc:
            try:
                body_bytes = exc.read() or b""
            except Exception:  # noqa: BLE001 - defensive
                body_bytes = b""
            detail = _extract_provider_error_detail(body_bytes)
            status_code = getattr(exc, "code", 0) or 0
            message = (
                f"{provider_label} {operation} failed with HTTP {status_code}"
                if status_code
                else f"{provider_label} {operation} failed"
            )
            if detail:
                message = f"{message}: {detail}"
            raise MediaGenerationError(message) from exc
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise MediaGenerationError(
                f"{provider_label} {operation} failed: network error ({reason})"
            ) from exc

        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            snippet = raw[:200].decode("utf-8", errors="replace")
            raise MediaGenerationError(
                f"{provider_label} {operation} returned a non-JSON response: {snippet}"
            ) from exc

    @staticmethod
    def _extract_kling_download_url(data: Dict[str, Any]) -> str:
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
                return candidate

        outputs = data.get("outputs") if isinstance(data.get("outputs"), list) else []
        for output in outputs:
            if not isinstance(output, dict):
                continue
            nested_video = output.get("video") if isinstance(output.get("video"), dict) else {}
            candidate = str(
                output.get("url")
                or output.get("download_url")
                or output.get("video_url")
                or nested_video.get("url")
                or nested_video.get("download_url")
                or ""
            ).strip()
            if candidate:
                return candidate

        task_result = data.get("task_result") if isinstance(data.get("task_result"), dict) else {}
        task_videos = task_result.get("videos") if isinstance(task_result.get("videos"), list) else []
        for tv in task_videos:
            if not isinstance(tv, dict):
                continue
            candidate = str(tv.get("url") or tv.get("video_url") or tv.get("download_url") or "").strip()
            if candidate:
                return candidate

        video_payload = data.get("video") if isinstance(data.get("video"), dict) else {}
        return str(
            data.get("url")
            or data.get("video_url")
            or data.get("download_url")
            or video_payload.get("url")
            or video_payload.get("download_url")
            or ""
        ).strip()

    def _kling_credentials_available(self) -> bool:
        return bool(self._kling_api_key) or bool(self._kling_access_key and self._kling_secret_key)

    def _kling_authorization_header(self) -> str:
        if self._kling_api_key:
            return f"Bearer {self._kling_api_key}"
        if self._kling_access_key and self._kling_secret_key:
            jwt_token = self._build_kling_access_secret_jwt(
                access_key=self._kling_access_key,
                secret_key=self._kling_secret_key,
            )
            return f"Bearer {jwt_token}"
        raise MediaGenerationError("Kling credentials are not configured (set KLING_API_KEY or KLING_ACCESS_KEY + KLING_SECRET_KEY)")

    @staticmethod
    def _base64url_encode(raw_bytes: bytes) -> str:
        return base64.urlsafe_b64encode(raw_bytes).decode("ascii").rstrip("=")

    @classmethod
    def _build_kling_access_secret_jwt(
        cls,
        *,
        access_key: str,
        secret_key: str,
        now_epoch_seconds: Optional[int] = None,
        ttl_seconds: int = 1800,
    ) -> str:
        now_seconds = int(now_epoch_seconds if now_epoch_seconds is not None else time.time())
        token_header = {"alg": "HS256", "typ": "JWT"}
        token_payload = {
            "iss": str(access_key),
            "exp": now_seconds + max(60, int(ttl_seconds)),
            "nbf": max(0, now_seconds - 5),
        }
        encoded_header = cls._base64url_encode(json.dumps(token_header, separators=(",", ":")).encode("utf-8"))
        encoded_payload = cls._base64url_encode(json.dumps(token_payload, separators=(",", ":")).encode("utf-8"))
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        signature = hmac.new(str(secret_key).encode("utf-8"), signing_input, hashlib.sha256).digest()
        encoded_signature = cls._base64url_encode(signature)
        return f"{encoded_header}.{encoded_payload}.{encoded_signature}"

    @staticmethod
    def _parse_data_url(data_url: str) -> Optional[Dict[str, str]]:
        value = str(data_url or "").strip()
        if not value.startswith("data:") or "," not in value:
            return None
        header, encoded = value.split(",", 1)
        mime_type = header[5:].split(";", 1)[0].strip() or "application/octet-stream"
        if ";base64" in header:
            bytes_b64 = encoded.strip()
        else:
            bytes_b64 = base64.b64encode(urllib.parse.unquote_to_bytes(encoded)).decode("ascii")
        return {
            "mime_type": mime_type,
            "bytes_b64": bytes_b64,
        }


_media_generation_service: Optional[MediaGenerationService] = None


def get_media_generation_service() -> MediaGenerationService:
    """Return the singleton media generation service."""
    global _media_generation_service
    if _media_generation_service is None:
        _media_generation_service = MediaGenerationService()
    return _media_generation_service
