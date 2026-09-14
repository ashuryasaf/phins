"""
Provider wiring through the external-call gateway (design §A2): the LLM,
transcription, and media-generation paths must stay transparent to callers
while gaining cache, budget, breaker and retry — and exactly one usage row
per real provider call.
"""

import json
import urllib.error
import urllib.request
from email.message import Message

import pytest

import services.ai_usage_service as usage_mod
import services.external_call_gateway as gw
from services.external_call_gateway import BudgetExceeded


class _HTTP(Exception):
    """Stand-in for requests.HTTPError: exposes ``response.status_code``."""

    def __init__(self, status, retry_after=None):
        super().__init__(f"HTTP {status}")

        class _Resp:
            status_code = status
            headers = {'Retry-After': str(retry_after)} if retry_after is not None else {}
        self.response = _Resp()


@pytest.fixture
def usage():
    usage_mod.reset_ai_usage_service()
    yield usage_mod.get_ai_usage_service()
    usage_mod.reset_ai_usage_service()


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _HTTP(self.status_code)

    def json(self):
        return self._payload


def _llm_payload(content, prompt=100, completion=50):
    return {"choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}


@pytest.fixture
def llm(monkeypatch):
    from services.llm_providers import OpenAICompatibleProvider
    gw.reset_gateway()
    gw.get_gateway()._sleep = lambda s: None
    monkeypatch.delenv(gw.DAILY_CALL_BUDGET_ENV, raising=False)
    monkeypatch.delenv(gw.DAILY_TOKEN_BUDGET_ENV, raising=False)
    provider = OpenAICompatibleProvider(endpoint="https://llm.example/v1/chat", api_key="k", model="m")
    yield provider
    gw.reset_gateway()


def test_llm_identical_prompt_is_served_from_cache_without_second_hook_call(llm, monkeypatch):
    posts, hooks = [], []
    monkeypatch.setattr("requests.post", lambda *a, **k: posts.append(k) or _FakeResponse(_llm_payload("hi")))
    llm.usage_hook = hooks.append
    assert llm.completion("sys", "user") == "hi"
    assert llm.completion("sys", "user") == "hi"
    assert len(posts) == 1 and len(hooks) == 1
    assert hooks[0]["agent_id"] == "assessment_ai"
    assert llm.completion("sys", "different") == "hi" and len(posts) == 2


def test_llm_schema_invalid_completion_is_not_cached(llm, monkeypatch):
    """An unusable reply must not be replayed — and re-validated — forever."""
    replies = ["nonsense", '{"a": 1}', '{"a": 2}']
    posts = []
    monkeypatch.setattr("requests.post", lambda *a, **k: posts.append(k) or _FakeResponse(
        _llm_payload(replies.pop(0))))
    schema = {"type": "object", "required": ["a"]}

    assert llm.structured_completion("sys", "user", schema) == {"a": 1}
    assert len(posts) == 2  # the invalid reply, then the corrected retry
    # The original prompt cached nothing, so it is asked again...
    assert llm.structured_completion("sys", "user", schema) == {"a": 2}
    assert len(posts) == 3
    # ...and this time the valid answer is what the cache holds.
    assert llm.structured_completion("sys", "user", schema) == {"a": 2}
    assert len(posts) == 3


def test_llm_transient_error_is_retried_then_succeeds(llm, monkeypatch):
    responses = [_FakeResponse({}, status=503), _FakeResponse(_llm_payload("ok"))]
    monkeypatch.setattr("requests.post", lambda *a, **k: responses.pop(0))
    hooks = []
    llm.usage_hook = hooks.append
    assert llm.completion("sys", "user") == "ok"
    assert len(hooks) == 1  # failed attempt never reaches the hook


def test_llm_budget_exhaustion_surfaces_as_provider_failure_and_meters_block(llm, monkeypatch, usage):
    monkeypatch.setenv(gw.DAILY_CALL_BUDGET_ENV, "1")
    monkeypatch.setattr("requests.post", lambda *a, **k: _FakeResponse(_llm_payload("hi")))
    llm.call_context = {"customer_id": "CUST-B"}
    assert llm.completion("sys", "one") == "hi"
    with pytest.raises(BudgetExceeded):
        llm.completion("sys", "two")
    blocked = [r for r in usage.list_records() if r["blocked"]]
    assert len(blocked) == 1 and blocked[0]["customer_id"] == "CUST-B"
    assert blocked[0]["agent_id"] == "assessment_ai"


def test_assessment_service_falls_back_when_budget_exhausted(monkeypatch, usage):
    """The deterministic path is used, exactly like any provider failure."""
    from services.assessment_ai_service import AssessmentAIService
    gw.reset_gateway()
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_ENABLED", "1")
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_ENDPOINT", "https://llm.example/v1/chat")
    monkeypatch.setenv("PHINS_ASSESSMENT_AI_API_KEY", "k")
    monkeypatch.setenv(gw.DAILY_CALL_BUDGET_ENV, "1")
    gw.get_gateway()._charge_budget("CUST-FB", "assessment_ai", 0)  # budget already spent today
    posts = []
    monkeypatch.setattr("requests.post", lambda *a, **k: posts.append(1) or _FakeResponse(_llm_payload("{}")))
    svc = AssessmentAIService()
    artifact = svc.generate_structured_assessment(
        {"analysis_type": "onboarding", "customer_id": "CUST-FB", "risk": {"score": 10}},
        customer_id="CUST-FB", assessment_type="onboarding")
    assert artifact["mode"] == "deterministic"
    assert posts == []
    blocked = [r for r in usage.list_records() if r["blocked"]]
    assert blocked and blocked[0]["customer_id"] == "CUST-FB"
    gw.reset_gateway()


def test_transcription_identical_audio_is_not_billed_twice(monkeypatch, usage):
    from services.transcription_providers import get_transcription_provider
    gw.reset_gateway()
    monkeypatch.setenv("PHINS_TRANSCRIPTION_PROVIDER", "openai_compatible")
    monkeypatch.setenv("PHINS_TRANSCRIPTION_ENDPOINT", "https://asr.example/v1/audio/transcriptions")
    monkeypatch.setenv("PHINS_TRANSCRIPTION_API_KEY", "k")
    posts = []
    monkeypatch.setattr("requests.post", lambda *a, **k: posts.append(1) or _FakeResponse(
        {"text": "hello", "duration": 3.0, "segments": []}))
    provider = get_transcription_provider()
    first = provider.transcribe(b"same-bytes")
    second = provider.transcribe(b"same-bytes")
    provider.transcribe(b"other-bytes")
    assert len(posts) == 2
    assert second == first and second is not first  # equal copy, not the cached object
    records = usage.list_records(operation="transcription")
    # Exactly one usage row per real provider call: the cache hit is not billed.
    assert len(records) == 2 and all(r["agent_id"] == "transcription" for r in records)
    assert sum(r["media_seconds"] or 0 for r in records) == pytest.approx(6.0)
    gw.reset_gateway()


class _Ctx:
    """Stand-in for the ``validated_urlopen`` response context manager."""

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def test_media_submit_is_never_retried_but_poll_is(monkeypatch, usage):
    from services import media_generation_service as mgs
    gw.reset_gateway()
    gw.get_gateway()._sleep = lambda s: None
    monkeypatch.setenv(gw.MAX_RETRIES_ENV, "2")
    attempts = {'n': 0}

    def flaky(request, timeout=None, allowed_schemes=None):
        attempts['n'] += 1
        if attempts['n'] == 1:
            raise urllib.error.HTTPError(request.full_url, 503, "busy", Message(), None)
        return _Ctx(json.dumps({"ok": True}).encode())

    monkeypatch.setattr(mgs, "validated_urlopen", flaky)
    req = urllib.request.Request("https://api.klingapi.com/v1/videos/text2video", data=b"{}", method="POST")

    with pytest.raises(mgs.MediaGenerationError) as exc:
        mgs.MediaGenerationService._read_json_with_diagnostics(
            req, timeout=5, provider_label="Kling", operation="submit")
    assert "HTTP 503" in str(exc.value)
    assert attempts['n'] == 1  # a paid job creation is never re-sent

    attempts['n'] = 0
    body = mgs.MediaGenerationService._read_json_with_diagnostics(
        req, timeout=5, provider_label="Kling", operation="poll")
    assert body == {"ok": True} and attempts['n'] == 2

    # Only the (successful) submit would be metered; here the submit failed and
    # the poll is not billable, so no usage rows.
    assert usage.list_records(provider="kling") == []
    attempts['n'] = 5  # succeed at once
    mgs.MediaGenerationService._read_json_with_diagnostics(
        req, timeout=5, provider_label="Kling", operation="submit")
    rows = usage.list_records(provider="kling")
    assert len(rows) == 1 and rows[0]["operation"] == "video_submit" and rows[0]["agent_id"] == "video_agents"
    gw.reset_gateway()


def test_media_polls_stay_outside_the_daily_call_budget(monkeypatch, usage):
    """Polling an already-paid job must never be charged the cap, nor refused by it."""
    from services import media_generation_service as mgs
    gw.reset_gateway()
    monkeypatch.setenv(gw.DAILY_CALL_BUDGET_ENV, "1")
    monkeypatch.setattr(mgs, "validated_urlopen",
                        lambda request, timeout=None, allowed_schemes=None:
                        _Ctx(json.dumps({"ok": True}).encode()))
    req = urllib.request.Request("https://api.klingapi.com/v1/videos/text2video", method="GET")

    def read(operation):
        return mgs.MediaGenerationService._read_json_with_diagnostics(
            req, timeout=5, provider_label="Kling", operation=operation)

    for _ in range(3):
        assert read("poll") == {"ok": True}
    assert gw.get_gateway().budget_usage("global", "video_agents")["calls"] == 0
    assert read("submit") == {"ok": True}      # the one billable call the cap allows
    with pytest.raises(mgs.MediaGenerationError, match="refused"):
        read("submit")
    assert read("poll") == {"ok": True}        # in-flight jobs can still be polled
    gw.reset_gateway()


def test_media_circuit_open_is_reported_as_media_error(monkeypatch):
    from services import media_generation_service as mgs
    gw.reset_gateway()
    monkeypatch.setenv(gw.BREAKER_THRESHOLD_ENV, "1")
    monkeypatch.setenv(gw.MAX_RETRIES_ENV, "0")

    def down(request, timeout=None, allowed_schemes=None):
        raise urllib.error.URLError("unreachable")

    monkeypatch.setattr(mgs, "validated_urlopen", down)
    req = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/op", method="GET")
    with pytest.raises(mgs.MediaGenerationError, match="network error"):
        mgs.MediaGenerationService._read_json_with_diagnostics(
            req, timeout=5, provider_label="Gemini/Veo", operation="poll")
    with pytest.raises(mgs.MediaGenerationError, match="refused"):
        mgs.MediaGenerationService._read_json_with_diagnostics(
            req, timeout=5, provider_label="Gemini/Veo", operation="poll")
    assert gw.get_gateway().snapshot()['breakers']['gemini|generativelanguage.googleapis.com']['state'] == 'open'
    gw.reset_gateway()


def test_admin_health_route_exposes_gateway_snapshot():
    from web_portal import api_extensions as ext
    status, payload = ext.dispatch_get('/api/admin/ai-agents/health',
                                       {'role': 'admin', 'username': 'admin'}, {}, '127.0.0.1')
    assert status == 200
    assert set(payload['gateway']) >= {'stats', 'breakers', 'budgets_today', 'cache_entries'}
    json.dumps(payload)
