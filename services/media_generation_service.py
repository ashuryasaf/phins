"""
Provider-backed media generation service for PHINS.

Supports prompt-based video generation using external providers and a small,
provider-neutral contract for submitting jobs, polling status, and downloading
completed files.
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


class MediaGenerationService:
    """Thin provider abstraction over real video generation APIs."""

    SUPPORTED_PROVIDERS = {"gemini", "kling"}
    DEFAULT_PROVIDER_MODELS = {
        "gemini": ["veo-3.1-generate-preview", "veo-3-fast-preview"],
        "kling": ["kling-v2.6-pro", "kling-v2.6-std"],
    }
    KLING_STANDARD_DURATIONS = (5, 10)

    def __init__(self) -> None:
        self._gemini_api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        self._gemini_model = os.environ.get("PHINS_GEMINI_VIDEO_MODEL", "veo-3.1-generate-preview").strip()
        self._kling_api_key = os.environ.get("KLING_API_KEY", "").strip()
        self._kling_access_key = os.environ.get("KLING_ACCESS_KEY", "").strip()
        self._kling_secret_key = os.environ.get("KLING_SECRET_KEY", "").strip()
        self._kling_base_url = os.environ.get("KLING_API_BASE_URL", "https://api.klingai.com").strip().rstrip("/")
        self._kling_text_to_video_path = os.environ.get("KLING_TEXT_TO_VIDEO_PATH", "/v1/videos/text2video").strip()
        self._kling_image_to_video_path = os.environ.get("KLING_IMAGE_TO_VIDEO_PATH", "/v1/videos/image2video").strip()

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
    ) -> Dict[str, Any]:
        """Download a completed video and return a data URL + metadata."""
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
        with validated_urlopen(request, timeout=120, allowed_schemes=("https",)) as response:
            video_bytes = response.read()
            content_type = response.headers.get("Content-Type", "video/mp4").split(";", 1)[0].strip() or "video/mp4"

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
        with validated_urlopen(request, timeout=60, allowed_schemes=("https",)) as response:
            body = json.loads(response.read().decode("utf-8"))

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
        with validated_urlopen(request, timeout=60, allowed_schemes=("https",)) as response:
            body = json.loads(response.read().decode("utf-8"))

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
        normalized_duration = self._normalize_kling_duration(duration_seconds, selected_model)
        image_payload = self._parse_data_url(image_data_url)
        base_payload: Dict[str, Any] = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio or "16:9",
            "duration": normalized_duration,
            "title": title,
            "model": selected_model,
        }
        if metadata:
            base_payload["metadata"] = metadata
        if callback_url:
            base_payload.setdefault("metadata", {})
            base_payload["metadata"]["phins_callback_url"] = callback_url
        image_endpoint_path = self._kling_image_to_video_path
        if image_payload:
            base_payload["image"] = {
                "data": image_payload["bytes_b64"],
                "mime_type": image_payload["mime_type"],
            }
        attempts = self._build_kling_submit_attempts(
            base_payload=base_payload,
            selected_model=selected_model,
            requested_duration=duration_seconds,
            normalized_duration=normalized_duration,
            use_image_endpoint=bool(image_payload),
        )
        response_body: Dict[str, Any] = {}
        attempt_errors = []
        for index, attempt in enumerate(attempts):
            attempt_url = attempt["url"]
            attempt_body = attempt["body"]
            request = urllib.request.Request(
                attempt_url,
                data=json.dumps(attempt_body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": self._kling_authorization_header(),
                },
                method="POST",
            )
            try:
                with validated_urlopen(request, timeout=60, allowed_schemes=("https",)) as response:
                    response_body = json.loads(response.read().decode("utf-8"))
                    break
            except urllib.error.HTTPError as exc:
                error_payload = self._decode_http_error_json(exc)
                provider_message = self._provider_error_message(error_payload)
                attempt_errors.append(f"{attempt.get('label', f'attempt-{index + 1}')} ({exc.code}): {provider_message}")
                retryable_contract_error = exc.code in {400, 404, 409, 415, 422}
                if not retryable_contract_error or index == len(attempts) - 1:
                    if attempt_errors:
                        raise MediaGenerationError(
                            f"Kling generation failed after {len(attempt_errors)} attempt(s): {attempt_errors[-1]}"
                        ) from exc
                    raise MediaGenerationError(f"Kling generation failed ({exc.code}): {provider_message}") from exc
            except Exception as exc:
                raise MediaGenerationError(f"Kling generation request error: {exc}") from exc
        else:
            summary = attempt_errors[-1] if attempt_errors else "Unknown provider error"
            raise MediaGenerationError(f"Kling generation failed: {summary}")

        data = response_body.get("data") if isinstance(response_body.get("data"), dict) else response_body
        provider_job_id = str(
            data.get("task_id")
            or data.get("id")
            or data.get("job_id")
            or data.get("taskId")
            or ""
        ).strip()
        if not provider_job_id:
            raise MediaGenerationError("Kling generation did not return a task id")

        return {
            "provider": "kling",
            "provider_job_id": provider_job_id,
            "status": "queued",
            "message": f"Submitted to Kling for \"{title}\"",
            "provider_state": {
                "submit_response": response_body,
                "status_url": self._build_kling_status_url(provider_job_id),
                "model": selected_model,
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

        status_url = str(provider_state.get("status_url") or self._build_kling_status_url(provider_job_id)).strip()
        request = urllib.request.Request(
            status_url,
            headers={"Authorization": self._kling_authorization_header()},
            method="GET",
        )
        with validated_urlopen(request, timeout=60, allowed_schemes=("https",)) as response:
            body = json.loads(response.read().decode("utf-8"))

        data = body.get("data") if isinstance(body.get("data"), dict) else body
        status_value = str(
            data.get("status")
            or data.get("task_status")
            or data.get("state")
            or ""
        ).strip().lower()

        if status_value in {"queued", "pending", "submitted", "processing", "running", "in_progress"}:
            return {
                "status": "processing",
                "message": "Kling is still generating the video.",
                "provider_job_id": provider_job_id,
                "provider_state": {
                    "status_url": status_url,
                    "last_poll": body,
                },
            }

        if status_value in {"failed", "error", "cancelled"}:
            return {
                "status": "failed",
                "error": str(data.get("error_message") or data.get("message") or "Kling generation failed"),
                "provider_job_id": provider_job_id,
                "provider_state": {
                    "status_url": status_url,
                    "last_poll": body,
                },
            }

        outputs = data.get("outputs") if isinstance(data.get("outputs"), list) else []
        first_output = outputs[0] if outputs else {}
        download_url = str(
            first_output.get("url")
            or first_output.get("download_url")
            or data.get("video_url")
            or data.get("url")
            or ""
        ).strip()
        if not download_url:
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

    def _build_kling_status_url(self, provider_job_id: str) -> str:
        return f"{self._kling_base_url}/v1/videos/{urllib.parse.quote(provider_job_id, safe='')}"

    def _kling_model_variants(self, selected_model: str) -> list[str]:
        model_name = str(selected_model or "").strip()
        variants = []
        if model_name:
            variants.append(model_name)
            dashed = model_name.replace(".", "-")
            if dashed != model_name:
                variants.append(dashed)
            if "v2.6" in model_name:
                variants.append(model_name.replace("v2.6", "v2-6"))
            if "v2.5" in model_name:
                variants.append(model_name.replace("v2.5", "v2-5"))
            if "v3.0" in model_name:
                variants.append(model_name.replace("v3.0", "v3-0"))
        deduped = []
        seen = set()
        for value in variants:
            key = str(value).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped or [self.DEFAULT_PROVIDER_MODELS["kling"][0]]

    def _build_kling_submit_attempts(
        self,
        *,
        base_payload: Dict[str, Any],
        selected_model: str,
        requested_duration: int,
        normalized_duration: int,
        use_image_endpoint: bool,
    ) -> list[Dict[str, Any]]:
        attempts: list[Dict[str, Any]] = []
        seen_signatures = set()
        endpoint_path = self._kling_image_to_video_path if use_image_endpoint else self._kling_text_to_video_path
        fallback_text_path = self._kling_text_to_video_path
        model_variants = self._kling_model_variants(selected_model)
        requested = int(requested_duration) if requested_duration else 0

        def add_attempt(path: str, body: Dict[str, Any], label: str) -> None:
            signature = f"{path}:{json.dumps(body, sort_keys=True, separators=(',', ':'))}"
            if signature in seen_signatures:
                return
            seen_signatures.add(signature)
            attempts.append({"url": f"{self._kling_base_url}{path}", "body": body, "label": label})

        for model_name in model_variants:
            body = dict(base_payload)
            body["model"] = model_name
            body["duration"] = normalized_duration
            add_attempt(endpoint_path, body, f"primary-model-{model_name}")

            if requested > 0 and requested != normalized_duration:
                requested_body = dict(body)
                requested_body["duration"] = requested
                add_attempt(endpoint_path, requested_body, f"requested-duration-{requested}-model-{model_name}")

            compact_body = dict(body)
            compact_body.pop("title", None)
            add_attempt(endpoint_path, compact_body, f"compact-model-{model_name}")

            model_name_body = dict(compact_body)
            model_name_body["model_name"] = model_name_body.pop("model")
            add_attempt(endpoint_path, model_name_body, f"model-name-key-{model_name}")

            if use_image_endpoint:
                text_fallback = dict(compact_body)
                text_fallback.pop("image", None)
                add_attempt(fallback_text_path, text_fallback, f"text-fallback-model-{model_name}")
                text_model_name_fallback = dict(text_fallback)
                text_model_name_fallback["model_name"] = text_model_name_fallback.pop("model")
                add_attempt(fallback_text_path, text_model_name_fallback, f"text-fallback-model-name-key-{model_name}")

        return attempts

    def _normalize_kling_duration(self, duration_seconds: int, selected_model: str) -> int:
        """
        Normalize duration for Kling models to avoid provider 400 responses.

        - Kling 2.x/1.x models generally accept only 5s or 10s.
        - Kling 3.x accepts a wider 3-15s range.
        """
        model_name = str(selected_model or "").strip().lower()
        requested = int(duration_seconds) if duration_seconds else 8
        if requested < 1:
            requested = 8
        if "kling-v3" in model_name:
            return max(3, min(15, requested))
        if "kling-v2." in model_name or "kling-v1." in model_name:
            if requested in self.KLING_STANDARD_DURATIONS:
                return requested
            return min(self.KLING_STANDARD_DURATIONS, key=lambda value: abs(value - requested))
        if requested in self.KLING_STANDARD_DURATIONS:
            return requested
        return min(self.KLING_STANDARD_DURATIONS, key=lambda value: abs(value - requested))

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

    @staticmethod
    def _decode_http_error_json(exc: urllib.error.HTTPError) -> Dict[str, Any]:
        raw = ""
        try:
            raw = exc.read().decode("utf-8") if exc.fp else ""
        except Exception:
            raw = ""
        if not raw:
            return {"error": str(exc)}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        return {"error": raw}

    @staticmethod
    def _provider_error_message(payload: Dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return "Unknown provider error"
        nested_data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        return str(
            payload.get("error_message")
            or payload.get("message")
            or payload.get("error")
            or nested_data.get("error_message")
            or nested_data.get("message")
            or nested_data.get("error")
            or "Unknown provider error"
        )

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
