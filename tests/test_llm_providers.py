"""
Tests for Phase 3 of the multimodal document intelligence pipeline:

- Stdlib JSON-schema validation
- OpenAI-compatible provider with structured output, validation retries,
  rejection of persistently-invalid output, and escalation model routing
- Usage hook metering
- Versioned prompt registry
- Structured lifecycle assessments (deterministic offline + LLM modes),
  advisory confidence cap, and append-only persistence
"""

import json

import pytest

from services.llm_providers import (
    DisabledLLMProvider,
    LLMUnavailableError,
    LLMValidationError,
    OpenAICompatibleProvider,
    get_llm_provider,
    review_disposition,
    validate_json_schema,
    _parse_json_lenient,
)


# ── Schema validation ─────────────────────────────────────────────────────────

SCHEMA = {
    "type": "object",
    "required": ["summary", "risk_level", "confidence"],
    "properties": {
        "summary": {"type": "string", "minLength": 1},
        "risk_level": {"enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "findings": {"type": "array", "items": {"type": "object",
                                                "required": ["title"],
                                                "properties": {"title": {"type": "string"}}}},
    },
}


def test_schema_valid_instance():
    instance = {"summary": "ok", "risk_level": "LOW", "confidence": 0.5,
                "findings": [{"title": "a"}]}
    assert validate_json_schema(instance, SCHEMA) == []


@pytest.mark.parametrize("instance,fragment", [
    ({"risk_level": "LOW", "confidence": 0.5}, "missing required property 'summary'"),
    ({"summary": "x", "risk_level": "EXTREME", "confidence": 0.5}, "not in enum"),
    ({"summary": "x", "risk_level": "LOW", "confidence": 1.5}, "above maximum"),
    ({"summary": "x", "risk_level": "LOW", "confidence": "high"}, "expected number"),
    ({"summary": "", "risk_level": "LOW", "confidence": 0.5}, "minLength"),
    ({"summary": "x", "risk_level": "LOW", "confidence": 0.5,
      "findings": [{"detail": "no title"}]}, "missing required property 'title'"),
])
def test_schema_invalid_instances(instance, fragment):
    errors = validate_json_schema(instance, SCHEMA)
    assert errors and any(fragment in e for e in errors)


def test_lenient_json_parse_handles_fences_and_prose():
    assert _parse_json_lenient('{"a": 1}') == {"a": 1}
    assert _parse_json_lenient('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json_lenient('Here you go: {"a": 1} hope it helps') == {"a": 1}
    assert _parse_json_lenient("no json at all") is None


# ── Review disposition thresholds (spec §17, configurable) ───────────────────

def test_review_disposition_defaults():
    assert review_disposition(0.95) == "accepted"
    assert review_disposition(0.80) == "flagged"
    assert review_disposition(0.50) == "needs_review"
    assert review_disposition(None) == "needs_review"


def test_review_disposition_configurable(monkeypatch):
    monkeypatch.setenv("PHINS_AI_ACCEPT_THRESHOLD", "0.99")
    monkeypatch.setenv("PHINS_AI_REVIEW_THRESHOLD", "0.50")
    assert review_disposition(0.95) == "flagged"
    assert review_disposition(0.45) == "needs_review"


# ── Provider factory ──────────────────────────────────────────────────────────

def test_factory_disabled_without_config(monkeypatch):
    monkeypatch.delenv("PHINS_ASSESSMENT_AI_ENABLED", raising=False)
    assert isinstance(get_llm_provider(), DisabledLLMProvider)
    with pytest.raises(LLMUnavailableError):
        get_llm_provider().completion("s", "u")


def test_factory_openai_compatible_when_configured(monkeypatch):
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_ENABLED", "1")
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_ENDPOINT", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_API_KEY", "test-key")
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_MODEL", "cheap-model")
    monkeypatch.setenv("PHINS_LLM_ESCALATION_MODEL", "strong-model")
    provider = get_llm_provider()
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.model == "cheap-model"
    assert provider.escalation_model == "strong-model"


# ── Fake HTTP endpoint ────────────────────────────────────────────────────────

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _completion_payload(content, prompt_tokens=100, completion_tokens=50):
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt_tokens,
                  "completion_tokens": completion_tokens},
    }


@pytest.fixture
def provider():
    return OpenAICompatibleProvider(
        endpoint="https://llm.example/v1/chat/completions",
        api_key="k", model="cheap-model", escalation_model="strong-model",
    )


def _patch_post(monkeypatch, responses, calls):
    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(json)
        return _FakeResponse(responses.pop(0))
    monkeypatch.setattr("requests.post", fake_post)


# ── Structured completion behaviour ───────────────────────────────────────────

def test_structured_completion_valid_first_try(provider, monkeypatch):
    valid = {"summary": "ok", "risk_level": "LOW", "confidence": 0.8}
    calls = []
    _patch_post(monkeypatch, [_completion_payload(json.dumps(valid))], calls)
    result = provider.structured_completion("system", "user", SCHEMA)
    assert result == valid
    assert len(calls) == 1
    assert calls[0]["model"] == "cheap-model"
    # Schema embedded in the system message so the model knows the contract.
    assert "risk_level" in calls[0]["messages"][0]["content"]


def test_structured_completion_retries_then_succeeds(provider, monkeypatch):
    valid = {"summary": "ok", "risk_level": "LOW", "confidence": 0.8}
    calls = []
    _patch_post(monkeypatch, [
        _completion_payload("not json at all"),
        _completion_payload(json.dumps({"summary": "x", "risk_level": "EXTREME",
                                        "confidence": 0.5})),
        _completion_payload(json.dumps(valid)),
    ], calls)
    result = provider.structured_completion("system", "user", SCHEMA)
    assert result == valid
    assert len(calls) == 3
    # The retry conversation carries validation feedback.
    feedback = calls[1]["messages"][-1]["content"]
    assert "invalid" in feedback


def test_structured_completion_rejects_after_retry_budget(provider, monkeypatch):
    calls = []
    _patch_post(monkeypatch, [
        _completion_payload("garbage"),
        _completion_payload("more garbage"),
        _completion_payload("still garbage"),
    ], calls)
    with pytest.raises(LLMValidationError):
        provider.structured_completion("system", "user", SCHEMA)
    assert len(calls) == 3  # 1 initial + 2 retries (PHINS_LLM_VALIDATION_RETRIES)


def test_escalation_routes_to_stronger_model(provider, monkeypatch):
    valid = {"summary": "ok", "risk_level": "HIGH", "confidence": 0.7}
    calls = []
    _patch_post(monkeypatch, [_completion_payload(json.dumps(valid))], calls)
    provider.structured_completion("system", "user", SCHEMA, escalate=True)
    assert calls[0]["model"] == "strong-model"


def test_usage_hook_metering(provider, monkeypatch):
    usage_records = []
    provider.usage_hook = usage_records.append
    calls = []
    _patch_post(monkeypatch, [_completion_payload("plain text answer",
                                                  prompt_tokens=123,
                                                  completion_tokens=45)], calls)
    provider.completion("system", "user")
    assert len(usage_records) == 1
    record = usage_records[0]
    assert record["input_tokens"] == 123
    assert record["output_tokens"] == 45
    assert record["model"] == "cheap-model"
    assert record["operation"] == "llm_completion"


# ── Prompt registry ───────────────────────────────────────────────────────────

def test_prompt_registry_versions():
    from prompts import get_prompt, list_prompts
    onboarding = get_prompt("onboarding")
    assert onboarding.prompt_id == "onboarding-v1"
    assert onboarding.response_schema is not None
    assert get_prompt("service").prompt_id == "service-v1"
    assert get_prompt("termination").prompt_id == "termination-v1"
    assert get_prompt("narrative").response_schema is None
    catalog = list_prompts()
    assert set(catalog) >= {"onboarding-v1", "service-v1", "termination-v1",
                            "narrative-v1"}
    with pytest.raises(KeyError):
        get_prompt("unknown-type")
    with pytest.raises(KeyError):
        get_prompt("onboarding", version=99)


# ── Structured lifecycle assessments ──────────────────────────────────────────

@pytest.fixture
def ai_service():
    from services.assessment_ai_service import AssessmentAIService
    return AssessmentAIService()


_ANALYSIS_PAYLOAD = {
    "analysis_type": "customer_360",
    "customer_id": "CUST-AI",
    "risk": {"risk_score": 0.62, "risk_level": "high"},
    "description": {
        "fact_count": 3, "document_count": 1,
        "sections": [{
            "category": "Medical", "fact_count": 3,
            "by_label": {"diabetes": [{
                "document_id": "DOC-1", "sha256": "abc123", "confidence": 0.75,
            }]},
        }],
    },
}


def test_structured_assessment_deterministic_offline(ai_service, monkeypatch):
    monkeypatch.delenv("PHINS_ASSESSMENT_AI_ENABLED", raising=False)
    from services.assessment_record_service import (
        get_assessment_record_service, reset_assessment_record_service)
    reset_assessment_record_service()

    artifact = ai_service.generate_structured_assessment(
        _ANALYSIS_PAYLOAD, customer_id="CUST-AI", assessment_type="onboarding")

    assert artifact["mode"] == "deterministic"
    assert artifact["prompt_version"] == "onboarding-v1"
    assert artifact["advisory"] is True and artifact["needs_review"] is True
    assert artifact["schema_valid"] is True
    result = artifact["result"]
    assert result["risk_level"] == "HIGH"
    assert result["requires_human_review"] is True
    assert result["findings"] and result["findings"][0]["evidence_refs"] == ["DOC-1"]
    # Advisory confidence is capped.
    assert artifact["confidence"] <= 0.4

    # Persisted append-only with prompt/model/version for auditability.
    records = get_assessment_record_service().list_records(
        customer_id="CUST-AI", assessment_type="onboarding")
    assert records["total"] == 1
    details = records["items"][0]["details"]
    assert details["prompt_version"] == "onboarding-v1"
    assert details["result"]["risk_level"] == "HIGH"
    reset_assessment_record_service()


def test_structured_assessment_llm_mode(ai_service, monkeypatch):
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_ENABLED", "1")
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_ENDPOINT", "https://llm.example/v1/chat")
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_API_KEY", "k")
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_MODEL", "cheap-model")

    llm_result = {
        "summary": "Customer presents managed diabetes; onboarding evidence complete.",
        "risk_level": "MEDIUM",
        "findings": [{"title": "Chronic condition on file",
                      "detail": "Diabetes recorded", "evidence_refs": ["DOC-1"]}],
        "missing_information": [],
        "contradictions": [],
        "recommendations": ["Verify medical declaration against DOC-1"],
        "confidence": 0.95,
        "requires_human_review": False,
    }
    calls = []
    _patch_post(monkeypatch, [_completion_payload(json.dumps(llm_result))], calls)

    artifact = ai_service.generate_structured_assessment(
        _ANALYSIS_PAYLOAD, customer_id="CUST-AI2", assessment_type="service")

    assert artifact["mode"] == "llm"
    assert artifact["prompt_version"] == "service-v1"
    assert artifact["result"]["summary"].startswith("Customer presents")
    # Model said 0.95, disposition reflects the raw confidence, but the
    # advisory envelope is still capped and still requires review.
    assert artifact["review_disposition"] == "accepted"
    assert artifact["confidence"] <= 0.4
    assert artifact["needs_review"] is True


def test_structured_assessment_llm_failure_falls_back(ai_service, monkeypatch):
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_ENABLED", "1")
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_ENDPOINT", "https://llm.example/v1/chat")
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_API_KEY", "k")

    def explode(*_a, **_k):
        raise ConnectionError("endpoint down")
    monkeypatch.setattr("requests.post", explode)

    artifact = ai_service.generate_structured_assessment(
        _ANALYSIS_PAYLOAD, customer_id="CUST-AI3", assessment_type="termination")
    assert artifact["mode"] == "deterministic"
    assert artifact["result"]["requires_human_review"] is True


def test_narrative_records_prompt_version(ai_service, monkeypatch):
    monkeypatch.delenv("PHINS_ASSESSMENT_AI_ENABLED", raising=False)
    narrative = ai_service.generate_narrative(
        _ANALYSIS_PAYLOAD, customer_id="CUST-AI4")
    assert narrative["prompt_version"] == "narrative-v1"
    assert narrative["advisory"] is True
