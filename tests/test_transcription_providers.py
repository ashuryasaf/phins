"""
Tests for Phase 5 of the multimodal document intelligence pipeline:
audio transcription providers, video degraded path, and timestamped evidence.
"""

import base64
import json
import shutil

import pytest

from services.transcription_providers import (
    DisabledTranscriptionProvider,
    OpenAICompatibleTranscriptionProvider,
    TranscriptionUnavailableError,
    get_transcription_provider,
    transcription_enabled,
)
from services.document_processing_service import DocumentProcessingService
from services.assessment_center_service import AssessmentCenterService
from services.ai_usage_service import get_ai_usage_service, reset_ai_usage_service


@pytest.fixture(autouse=True)
def _reset_usage():
    reset_ai_usage_service()
    yield
    reset_ai_usage_service()


@pytest.fixture
def doc_service(tmp_path):
    return DocumentProcessingService(storage_root=str(tmp_path / "docs"))


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


_VERBOSE_JSON = {
    "text": "Patient reports diabetes. Premium is 500 shekels.",
    "language": "en",
    "duration": 12.5,
    "segments": [
        {"start": 0.0, "end": 6.2, "text": "Patient reports diabetes."},
        {"start": 6.2, "end": 12.5, "text": "Premium is 500 shekels."},
    ],
}


def _enable_provider(monkeypatch):
    monkeypatch.setenv("PHINS_TRANSCRIPTION_PROVIDER", "openai_compatible")
    monkeypatch.setenv("PHINS_TRANSCRIPTION_ENDPOINT",
                       "https://asr.example/v1/audio/transcriptions")
    monkeypatch.setenv("PHINS_TRANSCRIPTION_API_KEY", "k")
    monkeypatch.setattr("requests.post",
                        lambda *a, **k: _FakeResponse(dict(_VERBOSE_JSON)))


# ── Factory / provider behaviour ─────────────────────────────────────────────

def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("PHINS_TRANSCRIPTION_PROVIDER", raising=False)
    provider = get_transcription_provider()
    assert isinstance(provider, DisabledTranscriptionProvider)
    assert transcription_enabled() is False
    with pytest.raises(TranscriptionUnavailableError):
        provider.transcribe(b"audio")


def test_openai_compatible_transcription(monkeypatch):
    _enable_provider(monkeypatch)
    provider = get_transcription_provider()
    assert isinstance(provider, OpenAICompatibleTranscriptionProvider)
    result = provider.transcribe(b"fake-mp3-bytes", file_name="call.mp3")
    assert "diabetes" in result["text"]
    assert result["language"] == "en"
    assert len(result["segments"]) == 2
    assert result["segments"][0]["end"] == 6.2

    # Metered as transcription minutes.
    usage = get_ai_usage_service().list_records(operation="transcription")
    assert len(usage) == 1
    assert usage[0]["media_seconds"] == 12.5


def test_size_limit_enforced(monkeypatch):
    _enable_provider(monkeypatch)
    monkeypatch.setenv("PHINS_TRANSCRIPTION_MAX_BYTES", "10")
    provider = get_transcription_provider()
    with pytest.raises(ValueError):
        provider.transcribe(b"x" * 11)


# ── Document service audio path ───────────────────────────────────────────────

def test_audio_stub_when_disabled(doc_service, monkeypatch):
    monkeypatch.delenv("PHINS_TRANSCRIPTION_PROVIDER", raising=False)
    analysis = doc_service._analyze_audio(b"fake", "audio/mpeg")
    assert "transcript" not in analysis
    assert "external ASR" in analysis["note"]


def test_audio_upload_extracts_transcript(doc_service, monkeypatch):
    _enable_provider(monkeypatch)
    result = doc_service.upload_document(
        file_name="advisor_call.mp3",
        file_data_b64=base64.b64encode(b"fake-mp3").decode(),
        mime_type="audio/mpeg", customer_id="CUST-AUDIO",
    )
    record = doc_service.get_document(result.document_id)
    assert "diabetes" in (record.get("extracted_text") or "")
    meta = json.loads(record.get("extracted_metadata") or "{}")
    segments = meta["transcript"]["segments"]
    assert segments[0]["timestamp_start"] == 0.0
    assert segments[0]["char_start"] == 0
    # Segment offsets index into the extracted text.
    text = record["extracted_text"]
    assert text[segments[1]["char_start"]:segments[1]["char_end"]] == "Premium is 500 shekels."


def test_audio_facts_carry_timestamps(tmp_path, doc_service, monkeypatch):
    _enable_provider(monkeypatch)
    center = AssessmentCenterService(
        document_service=doc_service, fact_store_dir=str(tmp_path / "facts"))
    result = center.upload_and_assess(
        file_name="advisor_call.mp3",
        file_data_b64=base64.b64encode(b"fake-mp3").decode(),
        mime_type="audio/mpeg", customer_id="CUST-TS",
    )
    conditions = [f for f in result.facts if f.fact_type == "medical_condition"]
    assert conditions, "diabetes fact expected from the transcript"
    assert conditions[0].timestamp_start == 0.0
    assert conditions[0].timestamp_end == 6.2
    assert "diabetes" in conditions[0].source_text.lower()


def test_media_bytes_never_mined_as_text(tmp_path, doc_service, monkeypatch):
    """Without a transcript, raw audio bytes must not be decoded into garbage facts."""
    monkeypatch.delenv("PHINS_TRANSCRIPTION_PROVIDER", raising=False)
    center = AssessmentCenterService(
        document_service=doc_service, fact_store_dir=str(tmp_path / "facts"))
    result = center.upload_and_assess(
        file_name="call.mp3",
        # Bytes that would contain fake "facts" if decoded as latin/utf-8 text.
        file_data_b64=base64.b64encode(b"diabetes insulin BMI 33.0").decode(),
        mime_type="audio/mpeg", customer_id="CUST-RAW",
    )
    mined = [f for f in result.facts
             if f.fact_type not in ("document_meta", "extraction_hint")]
    assert mined == []


# ── Video degraded path ───────────────────────────────────────────────────────

def test_video_stub_without_ffmpeg_and_provider(doc_service, monkeypatch):
    monkeypatch.delenv("PHINS_TRANSCRIPTION_PROVIDER", raising=False)
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    analysis = doc_service._analyze_video(b"fake-video", "video/mp4")
    assert "transcript" not in analysis
    assert "ffmpeg" in analysis["note"]


def test_video_transcribes_extracted_audio_track(doc_service, monkeypatch):
    _enable_provider(monkeypatch)
    monkeypatch.setattr(doc_service, "_ffmpeg_extract_audio",
                        lambda raw: b"fake-extracted-audio")
    monkeypatch.setattr(doc_service, "_ffmpeg_keyframe_ocr",
                        lambda raw: "Visible text: Policy POL-123")
    analysis = doc_service._analyze_video(b"fake-video", "video/mp4")
    assert "diabetes" in analysis["transcript"]["text"]
    assert analysis["visible_text"].startswith("Visible text")
    assert "diabetes" in analysis["text"] and "POL-123" in analysis["text"]
