"""
Tests for Phase 4 of the multimodal document intelligence pipeline:
AI usage metering and cost aggregation.

- Configurable unit prices (never hard-coded) with per-record snapshots
- record_usage / list_records / summarize with totals
- LLM provider usage hook wiring (tokens metered per call, with context)
- Document parse metering on upload
- Staff-only HTTP endpoints
"""

import base64
import json
import os

import pytest
import requests

from services.ai_usage_service import (
    AIUsageService,
    estimate_cost,
    get_ai_usage_service,
    reset_ai_usage_service,
)

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_ai_usage_service()
    yield
    reset_ai_usage_service()


@pytest.fixture
def service():
    return AIUsageService()


# ── Pricing ───────────────────────────────────────────────────────────────────

def test_estimate_cost_defaults_to_zero():
    assert estimate_cost(input_tokens=1_000_000, output_tokens=500_000,
                         pages=100, media_seconds=600) == 0.0


def test_estimate_cost_with_configured_prices(monkeypatch):
    monkeypatch.setenv("PHINS_AI_PRICE_INPUT_PER_MTOK", "0.30")
    monkeypatch.setenv("PHINS_AI_PRICE_OUTPUT_PER_MTOK", "0.60")
    monkeypatch.setenv("PHINS_AI_PRICE_PARSE_PER_PAGE", "0.0015")
    monkeypatch.setenv("PHINS_AI_PRICE_TRANSCRIPTION_PER_MIN", "0.006")
    cost = estimate_cost(input_tokens=2_000_000, output_tokens=1_000_000,
                         pages=10, media_seconds=300)
    # 2*0.30 + 1*0.60 + 10*0.0015 + 5*0.006 = 0.6+0.6+0.015+0.03
    assert cost == pytest.approx(1.245)


def test_price_snapshot_stored_on_record(service, monkeypatch):
    monkeypatch.setenv("PHINS_AI_PRICE_INPUT_PER_MTOK", "0.30")
    record = service.record_usage(provider="openai_compatible",
                                  operation="llm_completion",
                                  input_tokens=1_000_000)
    assert record["unit_price_snapshot"]["input_per_mtok"] == 0.30
    assert record["estimated_cost"] == pytest.approx(0.30)
    # A later price change does not rewrite history.
    monkeypatch.setenv("PHINS_AI_PRICE_INPUT_PER_MTOK", "99")
    stored = service.list_records()[0]
    assert stored["estimated_cost"] == pytest.approx(0.30)


# ── Recording and aggregation ─────────────────────────────────────────────────

def test_record_and_filter(service):
    service.record_usage(provider="self_hosted", operation="document_parse",
                         customer_id="CUST-A", document_id="DOC-1", pages=4)
    service.record_usage(provider="openai_compatible", operation="llm_completion",
                         customer_id="CUST-B", input_tokens=100, output_tokens=20)
    assert len(service.list_records()) == 2
    assert len(service.list_records(customer_id="CUST-A")) == 1
    assert service.list_records(operation="llm_completion")[0]["customer_id"] == "CUST-B"


def test_summarize_by_provider_and_operation(service, monkeypatch):
    monkeypatch.setenv("PHINS_AI_PRICE_INPUT_PER_MTOK", "1.0")
    service.record_usage(provider="openai_compatible", operation="llm_completion",
                         customer_id="CUST-A", input_tokens=500_000)
    service.record_usage(provider="openai_compatible", operation="llm_completion",
                         customer_id="CUST-A", input_tokens=500_000)
    service.record_usage(provider="self_hosted", operation="document_parse",
                         customer_id="CUST-A", pages=12)

    summary = service.summarize(group_by="provider")
    assert summary["totals"]["operations"] == 3
    assert summary["totals"]["estimated_cost"] == pytest.approx(1.0)
    by_key = {g["key"]: g for g in summary["groups"]}
    assert by_key["openai_compatible"]["input_tokens"] == 1_000_000
    assert by_key["self_hosted"]["pages"] == 12

    by_op = service.summarize(group_by="operation")
    assert {g["key"] for g in by_op["groups"]} == {"llm_completion", "document_parse"}

    filtered = service.summarize(customer_id="CUST-NONE")
    assert filtered["totals"]["operations"] == 0


# ── Provider hook integration ─────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_llm_call_metered_with_context(monkeypatch):
    from services.llm_providers import OpenAICompatibleProvider

    usage = get_ai_usage_service()
    provider = OpenAICompatibleProvider(
        endpoint="https://llm.example/v1/chat", api_key="k", model="m")
    provider.usage_hook = usage.usage_hook({
        "customer_id": "CUST-CTX", "prompt_version": "onboarding-v1"})

    monkeypatch.setattr("requests.post", lambda *a, **k: _FakeResponse({
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 321, "completion_tokens": 42},
    }))
    provider.completion("system", "user")

    records = usage.list_records(customer_id="CUST-CTX")
    assert len(records) == 1
    assert records[0]["input_tokens"] == 321
    assert records[0]["output_tokens"] == 42
    assert records[0]["prompt_version"] == "onboarding-v1"
    assert records[0]["operation"] == "llm_completion"


def test_document_parse_metered_on_upload(tmp_path):
    from services.document_processing_service import DocumentProcessingService

    usage = get_ai_usage_service()
    svc = DocumentProcessingService(storage_root=str(tmp_path / "docs"))
    result = svc.upload_document(
        file_name="notes.txt",
        file_data_b64=base64.b64encode(b"policy premium data").decode(),
        mime_type="text/plain", customer_id="CUST-PARSE",
    )
    records = usage.list_records(document_id=result.document_id)
    assert len(records) == 1
    assert records[0]["operation"] == "document_parse"
    assert records[0]["provider"] == "self_hosted"
    assert records[0]["customer_id"] == "CUST-PARSE"


# ── HTTP endpoints ────────────────────────────────────────────────────────────

def _admin_headers():
    resp = requests.post(f"{BASE_URL}/api/login", json={
        "username": "admin", "password": "admin123"})
    if resp.status_code != 200:
        pytest.skip("Admin login failed — test server may not have users seeded")
    return {"Authorization": f"Bearer {resp.json().get('token')}"}


def test_usage_endpoints_require_auth():
    assert requests.get(f"{BASE_URL}/api/ai-usage/summary").status_code == 401
    assert requests.get(f"{BASE_URL}/api/ai-usage/records").status_code == 401


def test_usage_summary_endpoint(monkeypatch):
    headers = _admin_headers()
    get_ai_usage_service().record_usage(
        provider="self_hosted", operation="document_parse",
        customer_id="CUST-HTTP", pages=3)

    resp = requests.get(f"{BASE_URL}/api/ai-usage/summary?group_by=operation",
                        headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert "totals" in payload and "unit_prices" in payload
    keys = {g["key"] for g in payload["groups"]}
    assert "document_parse" in keys

    resp = requests.get(
        f"{BASE_URL}/api/ai-usage/records?customer_id=CUST-HTTP", headers=headers)
    assert resp.status_code == 200
    records = resp.json()["records"]
    assert records and records[0]["pages"] == 3
