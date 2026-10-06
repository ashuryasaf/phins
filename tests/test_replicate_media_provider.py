"""Replicate as a third video provider next to Gemini and Kling.

The provider contract is the same one the Growth Agent and Video Agents
dashboards already use: submit a prediction, poll or accept the webhook,
download the file, and let the media job layer SHA-256 it. These tests never
call Replicate; they lock the request shape and the checksum of the bytes
that would be stored.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any, Dict

import pytest

from services.media_generation_service import MediaGenerationError, MediaGenerationService


class _Body:
    def __init__(self, payload: bytes, content_type: str = "video/mp4") -> None:
        self._payload = payload
        self._offset = 0
        self.headers = {"Content-Type": content_type}
        self.status = 200

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk

    def __enter__(self) -> "_Body":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False


def _service(monkeypatch: pytest.MonkeyPatch) -> MediaGenerationService:
    monkeypatch.setenv("REPLICATE_API_TOKEN", "r8_test_token_value")
    monkeypatch.delenv("REPLICATE_VIDEO_MODELS", raising=False)
    return MediaGenerationService()


def test_replicate_is_disabled_without_a_token(monkeypatch):
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)
    service = MediaGenerationService()
    config = service.supported_provider_config()["replicate"]
    assert config["enabled"] is False
    assert "google/veo-3.1-fast" in config["models"]
    with pytest.raises(MediaGenerationError, match="REPLICATE_API_TOKEN"):
        service.submit_video_generation(
            provider="replicate",
            prompt="A short story with a disclaimer.",
            title="Story",
        )


def test_submit_targets_the_official_model_endpoint_and_keeps_the_token_out_of_the_body(monkeypatch):
    service = _service(monkeypatch)
    captured: Dict[str, Any] = {}

    def fake_read(request, **kwargs):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["operation"] = kwargs.get("operation")
        return {
            "id": "pred123",
            "status": "starting",
            "urls": {"get": "https://api.replicate.com/v1/predictions/pred123"},
        }

    monkeypatch.setattr(MediaGenerationService, "_read_json_with_diagnostics", staticmethod(fake_read))
    result = service.submit_video_generation(
        provider="replicate",
        prompt="Family story. On-screen disclaimer: general information only.",
        title="Story",
        model="",
        aspect_ratio="9:16",
        duration_seconds=8,
        resolution="720p",
        image_data_url="https://www.phins.ai/media/hero.png",
        callback_url="https://www.phins.ai/api/provider/media-processing/callback?job_id=mjob-1&token=tok",
    )
    assert result["provider"] == "replicate"
    assert result["provider_job_id"] == "pred123"
    assert captured["url"] == "https://api.replicate.com/v1/models/google/veo-3.1-fast/predictions"
    assert captured["auth"] == "Bearer r8_test_token_value"
    assert captured["operation"] == "submit"
    body = captured["body"]
    assert body["webhook"].startswith("https://www.phins.ai/")
    assert body["webhook_events_filter"] == ["completed"]
    assert body["input"]["prompt"].startswith("Family story")
    assert body["input"]["aspect_ratio"] == "9:16"
    assert body["input"]["duration"] == 8
    assert body["input"]["resolution"] == "720p"
    assert body["input"]["image"] == "https://www.phins.ai/media/hero.png"
    assert "r8_test_token_value" not in json.dumps(body)
    assert "metadata" not in body


def test_versioned_model_uses_the_predictions_endpoint(monkeypatch):
    service = _service(monkeypatch)
    captured: Dict[str, Any] = {}

    def fake_read(request, **kwargs):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return {"id": "predver", "status": "starting"}

    monkeypatch.setattr(MediaGenerationService, "_read_json_with_diagnostics", staticmethod(fake_read))
    service.submit_video_generation(
        provider="replicate",
        prompt="Disclaimer card",
        title="Disclaimer",
        model="bytedance/seedance-2.0:abcdef1234567890",
        duration_seconds=5,
    )
    assert captured["url"] == "https://api.replicate.com/v1/predictions"
    assert captured["body"]["version"] == "abcdef1234567890"
    assert captured["body"]["input"]["duration"] == 5


def test_poll_maps_succeeded_output_and_refuses_an_empty_success(monkeypatch):
    service = _service(monkeypatch)

    def fake_read(request, **kwargs):
        if "empty" in request.full_url:
            return {"id": "empty", "status": "succeeded", "output": None}
        return {
            "id": "pred123",
            "status": "succeeded",
            "output": ["https://replicate.delivery/pbxt/story.mp4"],
        }

    monkeypatch.setattr(MediaGenerationService, "_read_json_with_diagnostics", staticmethod(fake_read))
    ready = service.poll_video_generation(
        provider="replicate",
        provider_job_id="pred123",
        provider_state={"get_url": "https://api.replicate.com/v1/predictions/pred123"},
    )
    assert ready["status"] == "completed"
    assert ready["download_url"].endswith("story.mp4")

    empty = service.poll_video_generation(
        provider="replicate",
        provider_job_id="empty",
        provider_state={"get_url": "https://api.replicate.com/v1/predictions/empty"},
    )
    assert empty["status"] == "failed"
    assert "downloadable" in empty["error"]

    canceled = MediaGenerationService.normalize_replicate_prediction(
        {"id": "pred123", "status": "canceled", "error": "stopped"}
    )
    assert canceled["status"] == "failed"
    assert canceled["error"] == "stopped"


def test_download_bytes_match_the_checksum_of_what_was_stored(monkeypatch, tmp_path):
    service = _service(monkeypatch)
    payload = b"PHINS-REPLICATE-VIDEO-BYTES"
    seen_auth = {}

    def fake_open(request, timeout=300, allowed_schemes=("https",)):
        seen_auth["header"] = request.get_header("Authorization")
        return _Body(payload)

    monkeypatch.setattr("services.media_generation_service.validated_urlopen", fake_open)
    destination = tmp_path / "story.mp4"
    downloaded = service.download_generated_video(
        provider="replicate",
        download_url="https://replicate.delivery/pbxt/story.mp4",
        stream_to_path=str(destination),
    )
    stored = destination.read_bytes()
    assert stored == payload
    assert downloaded["size"] == len(payload)
    assert hashlib.sha256(stored).hexdigest() == hashlib.sha256(payload).hexdigest()
    assert seen_auth["header"] == "Bearer r8_test_token_value"


def test_replicate_webhook_signature_round_trip():
    secret_bytes = b"supersecretkey!!"
    secret = "whsec_" + base64.b64encode(secret_bytes).decode("ascii")
    raw_body = b'{"id":"pred123","status":"succeeded","output":"https://replicate.delivery/a.mp4"}'
    webhook_id = "msg_123"
    timestamp = "1710000000"
    signed = f"{webhook_id}.{timestamp}.{raw_body.decode('utf-8')}".encode("utf-8")
    signature = base64.b64encode(hmac.new(secret_bytes, signed, hashlib.sha256).digest()).decode("ascii")
    headers = {
        "webhook-id": webhook_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": f"v1,{signature}",
    }
    assert MediaGenerationService.verify_replicate_webhook_signature(secret, headers, raw_body) is True
    assert MediaGenerationService.verify_replicate_webhook_signature(secret, headers, raw_body + b" ") is False
    assert MediaGenerationService.verify_replicate_webhook_signature("not-a-whsec", headers, raw_body) is False


def test_custom_owner_model_is_accepted_and_garbage_is_not():
    assert MediaGenerationService.replicate_model_id_ok("google/veo-3.1-fast")
    assert MediaGenerationService.replicate_model_id_ok("bytedance/seedance-2.0")
    assert not MediaGenerationService.replicate_model_id_ok("not a model")
    assert not MediaGenerationService.replicate_model_id_ok("../etc/passwd")
    assert not MediaGenerationService.replicate_model_id_ok("https://evil.example/model")
