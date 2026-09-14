"""
External-call gateway (design §A2): cache, budget, breaker, retry, metering.
Provider wiring (LLM, transcription, media generation) is covered in
``tests/test_gateway_provider_integration.py``.
"""

import urllib.error
from email.message import Message

import pytest

import services.ai_usage_service as usage_mod
import services.external_call_gateway as gw
from services.circuit_breaker import CircuitBreaker
from services.external_call_gateway import (
    BudgetExceeded,
    CircuitOpen,
    ExternalCallGateway,
    is_transient,
)


class _Transient(ConnectionError):
    pass


class _HTTP(Exception):
    """Stand-in for requests.HTTPError: exposes ``response.status_code``."""

    def __init__(self, status, retry_after=None):
        super().__init__(f"HTTP {status}")

        class _Resp:
            status_code = status
            headers = {'Retry-After': str(retry_after)} if retry_after is not None else {}
        self.response = _Resp()


@pytest.fixture
def gateway(monkeypatch):
    for name in (gw.MAX_RETRIES_ENV, gw.CACHE_TTL_ENV, gw.DAILY_TOKEN_BUDGET_ENV,
                 gw.DAILY_CALL_BUDGET_ENV, gw.BREAKER_THRESHOLD_ENV, gw.BREAKER_RECOVERY_ENV):
        monkeypatch.delenv(name, raising=False)
    g = ExternalCallGateway()
    g._sleep = lambda s: g.__dict__.setdefault('_slept', []).append(s)  # no real waiting
    return g


@pytest.fixture
def usage():
    usage_mod.reset_ai_usage_service()
    yield usage_mod.get_ai_usage_service()
    usage_mod.reset_ai_usage_service()


def _counter(results):
    """request_fn that pops results; exceptions are raised, values returned."""
    calls = {'n': 0}

    def fn():
        calls['n'] += 1
        item = results.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item
    fn.calls = calls
    return fn


# ---------------------------------------------------------------------------
# Pass-through and cache
# ---------------------------------------------------------------------------

def test_success_returns_value_unchanged_and_meters_once(gateway, usage):
    fn = _counter([{"answer": 42}])
    out = gateway.call("llm", fn, operation="llm_completion", agent_id="assessment_ai",
                       usage_from=lambda r: {"input_tokens": 10, "output_tokens": 5, "model": "m"},
                       context={"customer_id": "CUST-GW"})
    assert out == {"answer": 42}
    records = usage.list_records()
    assert len(records) == 1
    rec = records[0]
    assert rec["agent_id"] == "assessment_ai" and rec["blocked"] is False
    assert rec["customer_id"] == "CUST-GW" and rec["input_tokens"] == 10
    assert gateway.budget_usage("CUST-GW", "assessment_ai") == {"calls": 1, "tokens": 15}


def test_cache_hit_skips_provider_and_returns_deep_copy(gateway, usage):
    fn = _counter([{"data": [1, 2]}, {"data": "should-not-be-reached"}])
    key = gateway.make_cache_key("llm", "https://x", {"m": 1})
    first = gateway.call("llm", fn, cache_key=key, agent_id="a")
    first["data"].append(3)  # mutate the caller's copy
    second = gateway.call("llm", fn, cache_key=key, agent_id="a")
    assert fn.calls['n'] == 1
    assert second == {"data": [1, 2]}          # cache is immune to caller mutation
    assert second is not first
    assert gateway.snapshot()['stats']['cache_hits'] == 1
    assert len(usage.list_records()) == 1      # cache hit is not an external call


def test_cache_disabled_when_ttl_zero(gateway, monkeypatch):
    monkeypatch.setenv(gw.CACHE_TTL_ENV, "0")
    fn = _counter([1, 2])
    key = gateway.make_cache_key("llm", "k")
    assert gateway.call("llm", fn, cache_key=key) == 1
    assert gateway.call("llm", fn, cache_key=key) == 2


def test_cache_key_is_canonical_and_order_independent(gateway):
    a = gateway.make_cache_key("llm", {"model": "m", "messages": [{"a": 1, "b": 2}]})
    b = gateway.make_cache_key("llm", {"messages": [{"b": 2, "a": 1}], "model": "m"})
    c = gateway.make_cache_key("transcription", {"model": "m", "messages": [{"a": 1, "b": 2}]})
    assert a == b and a != c and len(a) == 64


def test_failures_are_never_cached(gateway):
    fn = _counter([ValueError("bad"), "ok"])
    key = gateway.make_cache_key("llm", "k")
    with pytest.raises(ValueError):
        gateway.call("llm", fn, cache_key=key)
    assert gateway.call("llm", fn, cache_key=key) == "ok"


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

def test_call_budget_blocks_before_provider_and_records_blocked_row(gateway, usage, monkeypatch):
    monkeypatch.setenv(gw.DAILY_CALL_BUDGET_ENV, "2")
    fn = _counter(["a", "b", "never"])
    gateway.call("llm", fn, agent_id="bot", budget_scope="CUST-1", operation="llm_completion")
    gateway.call("llm", fn, agent_id="bot", budget_scope="CUST-1", operation="llm_completion")
    with pytest.raises(BudgetExceeded) as exc:
        gateway.call("llm", fn, agent_id="bot", budget_scope="CUST-1", operation="llm_completion")
    assert exc.value.kind == "call" and exc.value.used == 2 and exc.value.limit == 2
    assert fn.calls['n'] == 2
    blocked = [r for r in usage.list_records() if r["blocked"]]
    assert len(blocked) == 1
    assert blocked[0]["agent_id"] == "bot" and blocked[0]["customer_id"] is None
    assert blocked[0]["estimated_cost"] == 0
    # another scope is unaffected
    assert gateway.call("llm", _counter(["x"]), agent_id="bot", budget_scope="CUST-2") == "x"
    summary = usage.summarize(group_by="agent")
    assert summary["groups"][0]["key"] == "bot" and summary["groups"][0]["blocked"] == 1
    assert summary["totals"]["blocked"] == 1


def test_token_budget_counts_extracted_usage(gateway, monkeypatch):
    monkeypatch.setenv(gw.DAILY_TOKEN_BUDGET_ENV, "100")
    tokens = lambda r: {"input_tokens": 60, "output_tokens": 0}
    gateway.call("llm", _counter(["a"]), agent_id="x", usage_from=tokens)          # 60
    gateway.call("llm", _counter(["b"]), agent_id="x", usage_from=tokens)          # 120 > 100 after
    with pytest.raises(BudgetExceeded) as exc:
        gateway.call("llm", _counter(["c"]), agent_id="x", usage_from=tokens)
    assert exc.value.kind == "token" and exc.value.used == 120


def test_budget_unlimited_by_default(gateway):
    for i in range(50):
        assert gateway.call("llm", _counter([i]), agent_id="x") == i


# ---------------------------------------------------------------------------
# Retry + breaker
# ---------------------------------------------------------------------------

def test_transient_failure_retries_with_bounded_jitter(gateway, monkeypatch):
    monkeypatch.setenv(gw.MAX_RETRIES_ENV, "2")
    fn = _counter([_Transient("x"), _HTTP(503), "ok"])
    assert gateway.call("llm", fn) == "ok"
    assert fn.calls['n'] == 3
    slept = gateway.__dict__['_slept']
    assert len(slept) == 2
    assert 0 <= slept[0] <= 0.5 and 0 <= slept[1] <= 1.0
    assert gateway.snapshot()['stats']['retries'] == 2
    assert gateway.breaker("llm").state == "closed"


def test_retry_after_header_is_honoured(gateway):
    fn = _counter([_HTTP(429, retry_after=3), "ok"])
    assert gateway.call("llm", fn) == "ok"
    assert gateway.__dict__['_slept'] == [3.0]


def test_retry_budget_exhausted_reraises_provider_error(gateway, monkeypatch):
    monkeypatch.setenv(gw.MAX_RETRIES_ENV, "1")
    fn = _counter([_Transient("1"), _Transient("2"), "unreached"])
    with pytest.raises(_Transient):
        gateway.call("llm", fn)
    assert fn.calls['n'] == 2


def test_non_transient_failure_is_not_retried_and_does_not_trip_breaker(gateway):
    fn = _counter([_HTTP(401), "unreached"])
    with pytest.raises(_HTTP):
        gateway.call("llm", fn)
    assert fn.calls['n'] == 1
    assert gateway.__dict__.get('_slept', []) == []
    assert gateway.breaker("llm").get_status()['consecutive_failures'] == 0


def test_max_retries_zero_never_retries(gateway):
    fn = _counter([_Transient("x"), "unreached"])
    with pytest.raises(_Transient):
        gateway.call("kling", fn, max_retries=0)
    assert fn.calls['n'] == 1


def test_breaker_opens_after_threshold_and_blocks_without_calling(gateway, monkeypatch):
    monkeypatch.setenv(gw.BREAKER_THRESHOLD_ENV, "3")
    monkeypatch.setenv(gw.MAX_RETRIES_ENV, "0")
    for _ in range(3):
        with pytest.raises(_Transient):
            gateway.call("llm", _counter([_Transient("down")]), endpoint="https://a")
    fn = _counter(["unreached"])
    with pytest.raises(CircuitOpen) as exc:
        gateway.call("llm", fn, endpoint="https://a")
    assert fn.calls['n'] == 0
    assert exc.value.status['state'] == 'open'
    assert gateway.snapshot()['stats']['circuit_blocks'] == 1
    # breakers are per (provider, endpoint): a different endpoint still works
    assert gateway.call("llm", _counter(["ok"]), endpoint="https://b") == "ok"
    assert gateway.snapshot()['breakers']['llm|https://a']['state'] == 'open'


def test_breaker_half_open_probe_then_recovers(gateway, monkeypatch):
    monkeypatch.setenv(gw.BREAKER_THRESHOLD_ENV, "1")
    monkeypatch.setenv(gw.BREAKER_RECOVERY_ENV, "0")
    monkeypatch.setenv(gw.MAX_RETRIES_ENV, "0")
    with pytest.raises(_Transient):
        gateway.call("llm", _counter([_Transient("down")]))
    cb = gateway.breaker("llm")
    assert cb.state == "half_open"  # recovery timeout 0 -> immediately probing
    assert gateway.call("llm", _counter(["back"])) == "back"
    assert cb.state == "closed"


def test_is_transient_classification():
    assert is_transient(_HTTP(429)) and is_transient(_HTTP(503)) and is_transient(_HTTP(408))
    assert not is_transient(_HTTP(400)) and not is_transient(_HTTP(401)) and not is_transient(_HTTP(404))
    assert is_transient(ConnectionError()) and is_transient(TimeoutError())
    assert not is_transient(ValueError("bad json"))
    headers = Message()
    assert is_transient(urllib.error.HTTPError("https://x", 502, "bad", headers, None))
    assert not is_transient(urllib.error.HTTPError("https://x", 403, "no", headers, None))
    assert is_transient(urllib.error.URLError("dns"))
    headers['Retry-After'] = '7'
    assert gw.retry_after_of(urllib.error.HTTPError("https://x", 429, "slow", headers, None)) == 7.0


def test_shared_circuit_breaker_matches_smtp_semantics():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=120, name="t")
    assert cb.allow_request() and cb.state == "closed"
    cb.record_failure("a")
    cb.record_non_transient_failure()          # resets the streak
    cb.record_failure("b")
    assert cb.state == "closed"
    cb.record_failure("c")
    assert cb.state == "open" and not cb.allow_request()
    assert cb.get_status() == {'state': 'open', 'consecutive_failures': 2,
                               'last_failure': 'c', 'opened_at': cb._opened_at.isoformat()}


def test_reset_clears_everything(gateway):
    key = gateway.make_cache_key("llm", "k")
    gateway.call("llm", _counter(["v"]), cache_key=key, agent_id="a")
    gateway.reset()
    snap = gateway.snapshot()
    assert snap['cache_entries'] == 0 and snap['breakers'] == {} and snap['budgets_today'] == {}
    assert all(v == 0 for v in snap['stats'].values())
