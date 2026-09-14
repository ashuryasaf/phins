"""
Tests for the additive Assessment AI narrative layer.

Covers:
- The narrative is OFF by default (existing analysis shapes unchanged).
- When requested, it is additive, advisory, low-confidence and needs review.
- It is deterministic and offline by default (no network, reproducible).
- It introduces NO new facts and stays anchored to existing evidence.
- Filters (adjustable reporting) narrow the underlying fact set.
"""

from __future__ import annotations

import pytest

from services.assessment_center_service import AssessmentCenterService
from services.assessment_ai_service import (
    AssessmentAIService,
    assessment_ai_redact_enabled,
    redact_evidence_for_model,
    redact_risk_for_model,
)


@pytest.fixture
def center(tmp_path):
    return AssessmentCenterService(fact_store_dir=str(tmp_path / "facts"))


def _ingest(center, customer_id="CUST-1"):
    recs = [
        {
            "policy_number": "POL-1", "product_type": "1", "status": "1",
            "company_name": "מגדל", "affiliation_provider": "מגדל",
            "affiliation_product": "New Pension Fund", "accumulated_value": 12000,
            "start_date": "2020-05-01",
        },
        {
            "policy_number": "POL-2", "product_type": "7", "status": "2",
            "company_name": "כלל", "affiliation_provider": "כלל",
            "affiliation_product": "Managers Insurance", "accumulated_value": 0,
            "start_date": "2023-09-15",
        },
    ]
    return center.ingest_external_facts(
        customer_id=customer_id, source="mislaka",
        records=recs, fact_type="external_policy",
    )


class TestNarrativeOptIn:
    def test_off_by_default(self, center):
        _ingest(center)
        payload = center.run_analysis("CUST-1", "describe_data")
        assert "ai_narrative" not in payload

    def test_added_when_requested(self, center):
        _ingest(center)
        payload = center.run_analysis("CUST-1", "describe_data", options={"ai_narrative": True})
        nar = payload["ai_narrative"]
        assert nar["source"] == "assessment_ai"
        assert nar["advisory"] is True
        assert nar["needs_review"] is True
        assert nar["confidence"] <= 0.4
        assert nar["mode"] == "deterministic"


class TestNarrativeIntegrity:
    def test_deterministic_offline(self, center):
        _ingest(center)
        a = center.run_analysis("CUST-1", "cross_document", options={"ai_narrative": True})
        b = center.run_analysis("CUST-1", "cross_document", options={"ai_narrative": True})
        assert a["ai_narrative"]["summary_text"] == b["ai_narrative"]["summary_text"]
        assert a["ai_narrative"]["facts_digest"] == b["ai_narrative"]["facts_digest"]

    def test_evidence_is_anchored_to_real_documents_only(self, center):
        _ingest(center)
        payload = center.run_analysis("CUST-1", "describe_data", options={"ai_narrative": True})
        nar = payload["ai_narrative"]
        # Every highlight must reference a fact that exists in the description.
        described_labels = set()
        for section in payload["description"]["sections"]:
            described_labels.update((section.get("by_label") or {}).keys())
        for h in nar["highlights"]:
            assert h["label"] in described_labels

    def test_llm_disabled_without_config(self):
        svc = AssessmentAIService()
        # No env configured in the test environment.
        assert svc.is_llm_enabled() is False

    def test_audit_trail_records_invocation(self, center):
        _ingest(center)
        center.run_analysis("CUST-1", "describe_data", options={"ai_narrative": True})
        from services.assessment_ai_service import get_assessment_ai_service
        audit = get_assessment_ai_service().recent_audit()
        assert audit, "expected at least one audit record"
        assert audit[-1]["mode"] == "deterministic"


class TestAdjustableReportingFilters:
    def test_policy_number_filter_narrows_facts(self, center):
        _ingest(center)
        full = center.run_analysis("CUST-1", "describe_data")
        filtered = center.run_analysis(
            "CUST-1", "describe_data", options={"filters": {"policy_number": "POL-1"}}
        )
        assert filtered["description"]["fact_count"] < full["description"]["fact_count"]
        assert filtered["description"]["filters_applied"] == {"policy_number": "POL-1"}

    def test_provider_filter(self, center):
        _ingest(center)
        filtered = center.run_analysis(
            "CUST-1", "describe_data", options={"filters": {"provider": "כלל"}}
        )
        assert filtered["description"]["fact_count"] >= 1


class TestAssessmentAiRedaction:
    def test_redact_evidence_drops_label_and_document_name(self):
        redacted = redact_evidence_for_model([
            {
                "label": "national_id",
                "document_name": "passport-dana.pdf",
                "source": "upload",
                "value": "123456782",
                "document_id": "DOC-1",
            }
        ])
        assert redacted == [{"value": "123456782", "document_id": "DOC-1"}]

    def test_redact_risk_keeps_only_safe_keys(self):
        redacted = redact_risk_for_model({
            "level": "high",
            "score": 0.81,
            "summary": "Dana has diabetes per passport-dana.pdf",
            "notes": "reviewer: call the customer",
        })
        assert redacted == {"level": "high", "score": 0.81}

    def test_redact_defaults_on_in_production(self, monkeypatch):
        monkeypatch.delenv("PHINS_ASSESSMENT_AI_REDACT", raising=False)
        monkeypatch.setenv("PHINS_ENVIRONMENT", "production")
        assert assessment_ai_redact_enabled() is True
        monkeypatch.setenv("PHINS_ENVIRONMENT", "development")
        assert assessment_ai_redact_enabled() is False
        monkeypatch.setenv("PHINS_ASSESSMENT_AI_REDACT", "0")
        monkeypatch.setenv("PHINS_ENVIRONMENT", "production")
        assert assessment_ai_redact_enabled() is False
        monkeypatch.setenv("PHINS_ASSESSMENT_AI_REDACT", "1")
        assert assessment_ai_redact_enabled() is True


# ---------------------------------------------------------------------------
# B3: prompt provenance, structured output, retry-then-fallback, redaction
# ---------------------------------------------------------------------------

class _FakeLLM:
    """Stands in for ``get_llm_provider()``: records what was sent and answers
    from a scripted list (a str is a raw completion, a dict a structured one,
    an Exception is raised)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.usage_hook = None
        self.call_context = None

    def structured_completion(self, system_prompt, user_content, schema, *, escalate=False):
        self.calls.append({"system": system_prompt, "user": user_content, "schema": schema})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    def completion(self, system_prompt, user_content, *, escalate=False):
        self.calls.append({"system": system_prompt, "user": user_content, "schema": None})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _enable_llm(monkeypatch, fake):
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_ENABLED", "true")
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_ENDPOINT", "https://llm.example/v1/chat")
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_API_KEY", "test-key")
    monkeypatch.setattr("services.llm_providers.get_llm_provider", lambda: fake)


_VALID_STRUCTURED = {
    "summary_text": "Two external policies are on record; one has no accumulated value.",
    "key_points": [{"point": "Pension fund with 12,000 accumulated", "evidence_index": 0}],
    "review_flags": ["Managers insurance shows zero accumulated value"],
    "needs_review": True,
}


class TestPromptProvenanceAndStructuredOutput:
    def test_narrative_and_audit_carry_prompt_hash(self, center, monkeypatch):
        monkeypatch.delenv("PHINS_ASSESSMENT_AI_ENABLED", raising=False)
        from prompts import get_prompt
        _ingest(center)
        payload = center.run_analysis("CUST-1", "describe_data", options={"ai_narrative": True})
        nar = payload["ai_narrative"]
        template = get_prompt("narrative")
        assert nar["prompt_id"] == template.prompt_id == "narrative-v2"
        assert nar["prompt_version"] == "narrative-v2"
        assert nar["prompt_version_number"] == 2
        assert nar["prompt_sha256"] == template.sha256 and len(nar["prompt_sha256"]) == 64
        assert nar["schema_id"] == "phins:schemas/assessment_narrative"
        from services.assessment_ai_service import get_assessment_ai_service
        audit = get_assessment_ai_service().recent_audit()[-1]
        assert audit["prompt_id"] == "narrative-v2"
        assert audit["prompt_sha256"] == template.sha256
        assert audit["fallback_reason"] is None

    def test_prompt_sha_changes_only_with_prompt_text(self):
        from prompts import PromptTemplate, get_prompt
        v2 = get_prompt("narrative", version=2)
        same = PromptTemplate("x", "narrative", 9, v2.system_prompt, v2.response_schema)
        edited = PromptTemplate("x", "narrative", 9, v2.system_prompt + " ", v2.response_schema)
        assert same.sha256 == v2.sha256
        assert edited.sha256 != v2.sha256
        assert get_prompt("narrative", version=1).sha256 != v2.sha256

    def test_valid_structured_reply_is_used_and_validated(self, center, monkeypatch):
        fake = _FakeLLM([_VALID_STRUCTURED])
        _enable_llm(monkeypatch, fake)
        _ingest(center)
        payload = center.run_analysis("CUST-1", "describe_data", options={"ai_narrative": True})
        nar = payload["ai_narrative"]
        assert nar["mode"] == "llm"
        assert nar["summary_text"] == _VALID_STRUCTURED["summary_text"]
        assert nar["key_points"] == _VALID_STRUCTURED["key_points"]
        assert nar["review_flags"] == _VALID_STRUCTURED["review_flags"]
        assert nar["needs_review"] is True and nar["advisory"] is True
        assert "fallback_reason" not in nar
        assert len(fake.calls) == 1
        assert fake.calls[0]["schema"]["$id"] == "phins:schemas/assessment_narrative"
        assert fake.call_context == {"customer_id": "CUST-1"}

    def test_schema_invalid_reply_retries_then_deterministic_fallback(self, center, monkeypatch):
        """The provider owns the retry budget (PHINS_LLM_VALIDATION_RETRIES);
        drive the real OpenAICompatibleProvider with a fake HTTP layer that
        always answers garbage and confirm: retries happen, the service falls
        back to the deterministic narrative, and the reason is recorded."""
        from services import llm_providers as lp
        from services import external_call_gateway as gw
        monkeypatch.setenv("PHINS_ASSESSMENT_AI_ENABLED", "true")
        monkeypatch.setenv("PHINS_ASSESSMENT_AI_ENDPOINT", "https://llm.example/v1/chat")
        monkeypatch.setenv("PHINS_ASSESSMENT_AI_API_KEY", "test-key")
        monkeypatch.setenv("PHINS_LLM_VALIDATION_RETRIES", "2")
        gw.reset_gateway()
        gw.get_gateway()._sleep = lambda s: None
        posts = []

        class _Resp:
            status_code = 200
            text = "{}"

            def json(self):
                return {"choices": [{"message": {"content": '{"summary_text": ""}'}}],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

            def raise_for_status(self):
                return None

        monkeypatch.setattr("requests.post", lambda *a, **k: posts.append(k) or _Resp())
        try:
            _ingest(center)
            payload = center.run_analysis("CUST-1", "describe_data", options={"ai_narrative": True})
        finally:
            gw.reset_gateway()
        nar = payload["ai_narrative"]
        assert len(posts) == 3, "one attempt plus two validation retries"
        assert nar["mode"] == "deterministic" and nar["model"] == "deterministic-offline"
        assert nar["fallback_reason"].startswith("LLMValidationError")
        assert nar["summary_text"].startswith("Advisory summary for customer CUST-1")
        assert nar["key_points"] == [] and nar["review_flags"] == []
        from services.assessment_ai_service import get_assessment_ai_service
        assert get_assessment_ai_service().recent_audit()[-1]["fallback_reason"].startswith("LLMValidationError")
        assert lp.validate_json_schema({"summary_text": ""}, lp.load_schema("assessment_narrative"))

    def test_provider_reply_that_slips_past_the_schema_is_still_rejected(self, center, monkeypatch):
        # A provider bug returns an object citing evidence that was never sent.
        bogus = dict(_VALID_STRUCTURED, key_points=[{"point": "made up", "evidence_index": 99}])
        fake = _FakeLLM([bogus])
        _enable_llm(monkeypatch, fake)
        _ingest(center)
        nar = center.run_analysis("CUST-1", "describe_data", options={"ai_narrative": True})["ai_narrative"]
        assert nar["mode"] == "deterministic"
        assert "evidence_index 99" in nar["fallback_reason"]
        not_reviewed = dict(_VALID_STRUCTURED, needs_review=False)
        fake = _FakeLLM([not_reviewed])
        _enable_llm(monkeypatch, fake)
        nar = center.run_analysis("CUST-1", "describe_data", options={"ai_narrative": True})["ai_narrative"]
        assert nar["mode"] == "deterministic" and "needs_review" in nar["fallback_reason"]

    def test_production_redacts_what_the_model_receives(self, center, monkeypatch):
        import json as _json
        monkeypatch.delenv("PHINS_ASSESSMENT_AI_REDACT", raising=False)
        monkeypatch.setenv("PHINS_ENVIRONMENT", "production")
        fake = _FakeLLM([_VALID_STRUCTURED])
        _enable_llm(monkeypatch, fake)
        _ingest(center)
        payload = center.run_analysis("CUST-1", "describe_data", options={"ai_narrative": True})
        sent = _json.loads(fake.calls[0]["user"])
        assert sent["evidence"], "evidence trail is still sent"
        for item in sent["evidence"]:
            assert "document_name" not in item and "label" not in item
        assert "מגדל" not in fake.calls[0]["user"] and "POL-1" not in fake.calls[0]["user"]
        # The narrative returned to the reviewer keeps the full provenance.
        assert payload["ai_narrative"]["evidence"][0].get("label")

    def test_pinned_v1_prompt_uses_free_text_completion(self, center, monkeypatch):
        monkeypatch.setenv("PHINS_ASSESSMENT_NARRATIVE_PROMPT_VERSION", "1")
        fake = _FakeLLM(["Free-text advisory summary."])
        _enable_llm(monkeypatch, fake)
        _ingest(center)
        nar = center.run_analysis("CUST-1", "describe_data", options={"ai_narrative": True})["ai_narrative"]
        assert nar["mode"] == "llm" and nar["prompt_version"] == "narrative-v1"
        assert nar["summary_text"] == "Free-text advisory summary."
        assert nar["schema_id"] is None
        assert fake.calls[0]["schema"] is None
