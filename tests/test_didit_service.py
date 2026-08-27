"""Unit tests for the Didit standalone verification client."""

from __future__ import annotations

import base64
import json

import pytest

from services.didit_service import (
    DiditRequestError,
    DiditResult,
    DiditService,
    decode_file_input,
    feature_approved,
)


MIN_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
)


class _FakeResponse:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _b64(data: bytes = MIN_JPEG) -> str:
    return base64.b64encode(data).decode("ascii")


def test_decode_file_input_accepts_data_uri_and_object():
    encoded = _b64()
    name, raw, ctype = decode_file_input(
        f"data:image/jpeg;base64,{encoded}",
        "front_image",
        "front.jpg",
        "image/jpeg",
    )
    assert name == "front.jpg"
    assert raw == MIN_JPEG
    assert ctype == "image/jpeg"

    name, raw, ctype = decode_file_input(
        {"filename": "id.png", "content_type": "image/png", "data": encoded},
        "front_image",
        "front.jpg",
        "image/jpeg",
    )
    assert name == "id.png"
    assert ctype == "image/png"
    assert raw == MIN_JPEG


def test_decode_file_input_rejects_empty():
    with pytest.raises(DiditRequestError):
        decode_file_input("", "front_image", "front.jpg", "image/jpeg")


def test_id_verification_posts_multipart_and_maps_approved():
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers")
        captured["files"] = kwargs.get("files")
        captured["data"] = kwargs.get("data")
        captured["json"] = kwargs.get("json")
        return _FakeResponse(200, {
            "request_id": "req-id-1",
            "id_verification": {
                "status": "Approved",
                "first_name": "Ada",
                "last_name": "Lovelace",
                "document_number": "AB123",
                "warnings": [],
            },
        })

    svc = DiditService(
        api_key="test-key",
        base_url="https://verification.didit.me",
        http_post=fake_post,
    )
    result = svc.id_verification(
        front_image=_b64(),
        back_image=_b64(),
        vendor_data="CUST-1",
        save_api_request=True,
    )
    assert result.ok is True
    assert result.approved is True
    assert result.request_id == "req-id-1"
    assert captured["url"] == "https://verification.didit.me/v3/id-verification/"
    assert captured["headers"]["x-api-key"] == "test-key"
    assert "content-type" not in {k.lower() for k in captured["headers"]} or captured["json"] is None
    assert captured["json"] is None
    assert "front_image" in captured["files"]
    assert "back_image" in captured["files"]
    assert captured["data"]["vendor_data"] == "CUST-1"
    assert captured["data"]["save_api_request"] == "true"
    body = result.to_api_dict()
    assert body["id_verification"]["first_name"] == "Ada"
    assert body["ok"] is True


def test_aml_posts_json_and_maps_didit_403_to_502():
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs.get("json")
        captured["headers"] = kwargs.get("headers")
        return _FakeResponse(403, {"detail": "You do not have permission to perform this action."})

    svc = DiditService(api_key="test-key", http_post=fake_post)
    result = svc.aml(full_name="Jane Doe", date_of_birth="1990-01-15", nationality="US")
    assert result.ok is False
    assert result.status_code == 502
    assert "permission" in (result.error or "").lower()
    assert captured["url"].endswith("/v3/aml/")
    assert captured["headers"]["content-type"] == "application/json"
    assert captured["json"]["full_name"] == "Jane Doe"
    assert captured["json"]["entity_type"] == "person"


def test_database_validation_requires_core_fields():
    svc = DiditService(api_key="test-key", http_post=lambda *a, **k: None)
    with pytest.raises(DiditRequestError) as exc:
        svc.database_validation(first_name="Ada")
    assert "issuing_state" in str(exc.value)


def test_document_ai_requires_name_or_company():
    svc = DiditService(api_key="test-key", http_post=lambda *a, **k: None)
    with pytest.raises(DiditRequestError):
        svc.document_ai(
            document=_b64(b"%PDF-1.4"),
            fields=[{"key": "n", "name": "Name", "instruction": "Read name", "type": "text"}],
        )


def test_document_ai_encodes_fields_and_defaults_threshold():
    captured = {}

    def fake_post(url, **kwargs):
        captured["data"] = kwargs.get("data")
        captured["files"] = kwargs.get("files")
        return _FakeResponse(200, {
            "request_id": "docai-1",
            "document_ai": {"status": "Approved", "extracted_data": {"full_name": "Ada"}, "warnings": []},
        })

    svc = DiditService(api_key="test-key", http_post=fake_post)
    result = svc.document_ai(
        document={"filename": "bill.pdf", "content_type": "application/pdf", "data": _b64(b"%PDF-1.4 test")},
        fields=[{"key": "full_name", "name": "Name", "instruction": "Legal name", "type": "text", "is_full_name": True}],
        expected_first_name="Ada",
        expected_last_name="Lovelace",
    )
    assert result.ok is True
    assert result.approved is True
    encoded = json.loads(captured["data"]["fields"])
    assert encoded[0]["key"] == "full_name"
    assert captured["data"]["document_ai_name_match_score_threshold"] == "80"
    assert "document" in captured["files"]


def test_kyb_search_requires_country_and_contact_otp_paths():
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs.get("json")))
        return _FakeResponse(200, {"request_id": "otp-1", "email": {"status": "Approved"}})

    svc = DiditService(api_key="test-key", http_post=fake_post)
    with pytest.raises(DiditRequestError):
        svc.kyb_search(name="PHINS")

    result = svc.email_send("user@phins.ai", vendor_data="CUST-9")
    assert result.ok is True
    assert calls[-1][0].endswith("/v3/email/send/")
    assert calls[-1][1]["email"] == "user@phins.ai"
    assert calls[-1][1]["vendor_data"] == "CUST-9"

    svc.phone_check("+14155552671", "123456")
    assert calls[-1][0].endswith("/v3/phone/check/")
    assert calls[-1][1]["code"] == "123456"


def test_rate_limit_maps_to_429_with_retry_after():
    def fake_post(url, **kwargs):
        return _FakeResponse(429, {"detail": "rate limited"}, headers={"Retry-After": "12"})

    svc = DiditService(api_key="test-key", http_post=fake_post)
    result = svc.face_search(user_image=_b64())
    assert result.ok is False
    assert result.status_code == 429
    assert result.retry_after == 12


def test_unconfigured_service_raises_before_http():
    svc = DiditService(api_key="", http_post=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no http")))
    with pytest.raises(Exception):
        svc.aml(full_name="X")


def test_feature_approved_helper():
    assert feature_approved({"aml": {"status": "Declined"}}, "aml") is False
    assert feature_approved({"aml": {"status": "Approved"}}, "aml") is True
    assert feature_approved({}, "aml") is None


def test_didit_result_error_envelope():
    result = DiditResult(
        ok=False,
        status_code=400,
        request_id=None,
        payload={"error": "COULD_NOT_RECOGNIZE_DOCUMENT"},
        error="COULD_NOT_RECOGNIZE_DOCUMENT",
        endpoint="id-verification",
    )
    body = result.to_api_dict()
    assert body["error"] == "COULD_NOT_RECOGNIZE_DOCUMENT"
    assert body["ok"] is False
