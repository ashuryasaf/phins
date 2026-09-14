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


def test_summarize_by_agent_counts_blocked_calls(service, monkeypatch):
    monkeypatch.setenv("PHINS_AI_PRICE_INPUT_PER_MTOK", "1.0")
    service.record_usage(provider="openai_compatible", operation="llm_completion",
                         agent_id="assessment_ai", input_tokens=1_000_000)
    service.record_usage(provider="openai_compatible", operation="llm_completion",
                         agent_id="assessment_ai", blocked=True)
    service.record_usage(provider="openai_compatible", operation="transcription",
                         agent_id="document_intelligence", media_seconds=30)
    service.record_usage(provider="self_hosted", operation="document_parse", pages=2)

    summary = service.summarize(group_by="agent")
    by_key = {g["key"]: g for g in summary["groups"]}
    assert set(by_key) == {"assessment_ai", "document_intelligence", None}
    assert by_key["assessment_ai"]["operations"] == 2
    assert by_key["assessment_ai"]["blocked"] == 1
    # A blocked call never contributes cost or tokens.
    assert by_key["assessment_ai"]["estimated_cost"] == pytest.approx(1.0)
    assert by_key["assessment_ai"]["input_tokens"] == 1_000_000
    assert by_key["document_intelligence"]["blocked"] == 0
    assert summary["totals"]["operations"] == 4
    assert summary["totals"]["blocked"] == 1

    blocked_row = [r for r in service.list_records() if r["blocked"]][0]
    assert blocked_row["estimated_cost"] == 0.0
    assert blocked_row["agent_id"] == "assessment_ai"


# ── Database-backed path ──────────────────────────────────────────────────────

def _sqlite_db_manager():
    from database import init_database
    from database.manager import DatabaseManager
    init_database()
    return DatabaseManager()


def test_db_backed_records_persist_agent_and_blocked_and_aggregate_by_agent():
    """The SQLAlchemy path must carry agent_id/blocked end to end: create ->
    list_filtered -> aggregate(group_by='agent')."""
    from database.models import AIUsageRecord

    db = _sqlite_db_manager()
    marker = f"CUST-AIU-{os.getpid()}"
    try:
        service = AIUsageService(db_manager=db)
        service.record_usage(provider="openai_compatible", operation="llm_completion",
                             customer_id=marker, agent_id="assessment_ai",
                             input_tokens=10, output_tokens=5)
        service.record_usage(provider="openai_compatible", operation="llm_completion",
                             customer_id=marker, agent_id="assessment_ai", blocked=True)
        service.record_usage(provider="openai_compatible", operation="transcription",
                             customer_id=marker, agent_id="document_intelligence",
                             media_seconds=12)

        rows = service.list_records(customer_id=marker)
        assert len(rows) == 3
        assert {r["agent_id"] for r in rows} == {"assessment_ai", "document_intelligence"}
        assert sum(1 for r in rows if r["blocked"]) == 1
        # Blocked rows are stored with zero cost and no tokens (nothing was consumed).
        blocked = [r for r in rows if r["blocked"]][0]
        assert blocked["estimated_cost"] == 0.0
        assert blocked["input_tokens"] is None

        summary = service.summarize(group_by="agent", customer_id=marker)
        by_key = {g["key"]: g for g in summary["groups"]}
        assert by_key["assessment_ai"]["operations"] == 2
        assert by_key["assessment_ai"]["blocked"] == 1
        assert by_key["assessment_ai"]["input_tokens"] == 10
        assert by_key["document_intelligence"]["blocked"] == 0
        assert summary["totals"]["blocked"] == 1
        assert summary["totals"]["operations"] == 3

        # Existing group keys are unaffected by the new column.
        by_provider = service.summarize(group_by="provider", customer_id=marker)
        assert by_provider["totals"]["operations"] == 3
        assert by_provider["groups"][0]["blocked"] == 1
    finally:
        try:
            session = db._ensure_session()
            session.query(AIUsageRecord).filter(
                AIUsageRecord.customer_id == marker).delete(synchronize_session=False)
            session.commit()
        finally:
            db.close()


def test_upgrade_schema_adds_agent_and_blocked_to_pre_gateway_table(tmp_path):
    """A database created before A2 lacks the two columns; upgrade_schema must
    add them without touching existing rows, and 'blocked' must default to
    false for those rows."""
    from sqlalchemy import create_engine, inspect, text
    from database import upgrade_schema

    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE ai_usage_records ("
            " id VARCHAR(80) PRIMARY KEY, provider VARCHAR(60), operation VARCHAR(60),"
            " customer_id VARCHAR(80), estimated_cost FLOAT, input_tokens INTEGER,"
            " output_tokens INTEGER, pages INTEGER, media_seconds FLOAT,"
            " created_date DATETIME)"))
        conn.execute(text(
            "INSERT INTO ai_usage_records (id, provider, operation, customer_id, estimated_cost)"
            " VALUES ('AIU-LEGACY', 'openai_compatible', 'llm_completion', 'CUST-L', 0.5)"))

    assert upgrade_schema(engine) is True
    columns = {c["name"] for c in inspect(engine).get_columns("ai_usage_records")}
    assert {"agent_id", "blocked"} <= columns
    # Idempotent: a second run is a no-op and still reports success.
    assert upgrade_schema(engine) is True

    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT provider, estimated_cost, agent_id, blocked FROM ai_usage_records"
            " WHERE id='AIU-LEGACY'")).one()
    assert row[0] == "openai_compatible"
    assert row[1] == 0.5
    assert row[2] is None
    assert not row[3]
    engine.dispose()


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
