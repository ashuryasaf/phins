"""
Provider-backed media generation service for PHINS.

Supports prompt-based video generation using external providers and a small,
provider-neutral contract for submitting jobs, polling status, and downloading
completed files.

Supports two Kling API routing profiles:

- ``direct`` (default): talks to the official Kling API at
  ``https://api.klingapi.com`` using the ``/v1/videos/text2video`` and
  ``/v1/videos/image2video`` endpoints with the ``image`` field for image
  inputs.  This is what the existing PHINS deployments use.
- ``evolink-v3``: talks to the EvoLink unified Kling routes documented at
  https://evolink.ai/blog/how-to-access-kling-ai-api-complete-tutorial
  (``POST /v1/videos/generations`` + ``GET /v1/tasks/{task_id}``).  This
  profile uses the ``image_start`` field for image-to-video and is picked
  automatically when the requested model starts with ``kling-v3``,
  ``kling-o1``, or ``kling-o3``.  It can also be forced with the env var
  ``KLING_API_PROFILE=evolink-v3``.

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
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional

from security.network import validated_urlopen


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


class MediaGenerationService:
    """Thin provider abstraction over real video generation APIs."""

    SUPPORTED_PROVIDERS = {"gemini", "kling"}
    DEFAULT_PROVIDER_MODELS = {
        "gemini": ["veo-3.1-generate-preview", "veo-3-fast-preview"],
        "kling": [
            "kling-v2.6-pro",
            "kling-v2.6-std",
            "kling-v3-text-to-video",
            "kling-v3-image-to-video",
        ],
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
                "models": list(self.DEFAULT_PROVIDER_MODELS["kling"]),
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
    ) -> Dict[str, Any]:
        """Submit a provider-backed video generation request."""
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
        raise MediaGenerationError(f"Unsupported video provider: {provider}")

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
        else:
            raise MediaGenerationError(f"Unsupported video provider: {provider}")

        request = urllib.request.Request(download_url, headers=headers, method="GET")
        with validated_urlopen(request, timeout=300, allowed_schemes=("https",)) as response:
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
        body: Dict[str, Any] = {
            "model": selected_model,
            "prompt": safe_prompt,
            "aspect_ratio": aspect_ratio or "16:9",
            "duration": self._normalize_kling_duration(duration_seconds),
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
        )

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
            status_url = self._build_kling_status_url(provider_job_id)

        return {
            "provider": "kling",
            "provider_job_id": provider_job_id,
            "status": "queued",
            "message": f"Submitted to Kling for \"{title}\"",
            "provider_state": {
                "submit_response": response_body,
                "status_url": status_url,
                "model": selected_model,
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

        status_url = str(provider_state.get("status_url") or self._build_kling_status_url(provider_job_id, model_name=str(provider_state.get("model") or ""))).strip()
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

    def _build_kling_status_url(self, provider_job_id: str, model_name: str = "") -> str:
        encoded_id = urllib.parse.quote(provider_job_id, safe="")
        # EvoLink polls at /v1/tasks/{task_id}; the direct Kling API exposes
        # /v1/videos/{task_id}.  We mirror whichever profile this service is
        # configured for so a single provider_state can survive across restarts.
        if self._kling_use_evolink_profile(model_name):
            return f"{self._kling_base_url}{_KLING_EVOLINK_TASK_PATH_PREFIX}{encoded_id}"
        return f"{self._kling_base_url}/v1/videos/{encoded_id}"

    @staticmethod
    def _normalize_kling_duration(duration_seconds: int) -> int:
        requested_seconds = int(duration_seconds or 5)
        return 5 if requested_seconds <= 5 else 10

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
    ) -> Dict[str, Any]:
        """Open *request* and decode JSON, surfacing provider error bodies.

        ``urllib.error.HTTPError`` only exposes a generic ``HTTP Error 400: Bad
        Request`` style message by default.  Providers like Kling and Gemini
        embed actionable details in the response body (missing field, invalid
        model, rate limit hint, etc.), so we read and surface them in the
        ``MediaGenerationError`` instead of letting the cryptic default reach
        the UI.
        """
        try:
            with validated_urlopen(request, timeout=timeout, allowed_schemes=("https",)) as response:
                raw = response.read()
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
