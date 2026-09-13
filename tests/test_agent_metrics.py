"""
Tests for services/agent_metrics.py — observation-only instrumentation.
"""

import enum

import pytest

from services import agent_metrics as m


@pytest.fixture(autouse=True)
def _reset():
    m.reset()
    yield
    m.reset()


def test_record_and_snapshot_basic():
    m.record("a", 10.0)
    m.record("a", 30.0, decision="approve")
    m.record("a", 50.0, error="RuntimeError: x", decision="reject")
    snap = m.snapshot("a")
    assert snap["calls"] == 3 and snap["errors"] == 1
    assert snap["error_rate"] == round(1 / 3, 4)
    assert snap["latency_ms"]["count"] == 3
    assert snap["latency_ms"]["p50"] == 30.0
    assert snap["latency_ms"]["max"] == 50.0
    assert snap["decisions"] == {"approve": 1, "reject": 1}
    assert snap["last_error"].startswith("RuntimeError")


def test_snapshot_unknown_agent_is_empty_shape():
    snap = m.snapshot("nobody")
    assert snap["calls"] == 0 and snap["latency_ms"]["p95"] is None


def test_reservoir_is_bounded():
    for i in range(m._RESERVOIR + 100):
        m.record("a", float(i))
    snap = m.snapshot("a")
    assert snap["calls"] == m._RESERVOIR + 100
    assert snap["latency_ms"]["count"] == m._RESERVOIR


def test_decision_labels_bounded():
    for i in range(m._MAX_DECISION_LABELS + 10):
        m.record("a", 1.0, decision=f"label{i}")
    snap = m.snapshot("a")
    assert len(snap["decisions"]) == m._MAX_DECISION_LABELS + 1  # + _other
    assert snap["decisions"]["_other"] == 10


def test_gauges():
    m.set_gauge("a", "queue_depth", 7)
    assert m.snapshot("a")["gauges"] == {"queue_depth": 7.0}


def test_instrument_passes_through_result_and_args():
    calls = []

    @m.instrument_agent("agent_x", decision_key="decision")
    def run(a, b=2):
        calls.append((a, b))
        return {"decision": "approve", "a": a, "b": b}

    out = run(1, b=3)
    assert out == {"decision": "approve", "a": 1, "b": 3}
    assert calls == [(1, 3)]
    snap = m.snapshot("agent_x")
    assert snap["calls"] == 1 and snap["decisions"] == {"approve": 1}
    assert snap["in_flight"] == 0
    assert run.__name__ == "run"
    assert run.__phins_agent_id__ == "agent_x"


def test_instrument_reraises_and_counts_error():
    @m.instrument_agent("agent_x")
    def boom():
        raise ValueError("bad input")

    with pytest.raises(ValueError):
        boom()
    snap = m.snapshot("agent_x")
    assert snap["errors"] == 1 and "ValueError" in snap["last_error"]
    assert snap["in_flight"] == 0


def test_instrument_on_methods_and_enum_tuple_results():
    class Decision(enum.Enum):
        AUTO_APPROVE = "auto_approve"

    class Agent:
        @m.instrument_agent("agent_y", decision_fn=lambda r: r[0])
        def decide(self, x):
            return (Decision.AUTO_APPROVE, {"x": x})

        @m.instrument_agent("agent_y", decision_key="recommendation")
        def report(self):
            class R:
                recommendation = Decision.AUTO_APPROVE
            return R()

    agent = Agent()
    assert agent.decide(5)[1] == {"x": 5}
    agent.report()
    assert m.snapshot("agent_y")["decisions"] == {"auto_approve": 2}


def test_decision_extraction_failure_does_not_break_call():
    @m.instrument_agent("agent_z", decision_fn=lambda r: r["missing"]["deeper"])
    def run():
        return {"ok": True}

    assert run() == {"ok": True}
    assert m.snapshot("agent_z")["calls"] == 1
    assert m.snapshot("agent_z")["decisions"] == {}


def test_instrument_does_not_mutate_result_object():
    payload = {"decision": "x", "nested": [1, 2]}

    @m.instrument_agent("agent_w", decision_key="decision")
    def run():
        return payload

    out = run()
    assert out is payload
    assert payload == {"decision": "x", "nested": [1, 2]}


def test_check_slo_respects_min_calls_and_thresholds():
    for _ in range(5):
        m.record("fast", 1.0)
    assert m.check_slo(p95_ms=0.5, min_calls=10) == []
    for _ in range(25):
        m.record("slow", 900.0)
    for _ in range(25):
        m.record("flaky", 1.0, error="E")
    breaches = m.check_slo(p95_ms=500, error_rate=0.1, min_calls=20)
    kinds = {(b["agent_id"], b["kind"]) for b in breaches}
    assert ("slow", "latency_p95") in kinds
    assert ("flaky", "error_rate") in kinds
    assert not any(b["agent_id"] == "fast" for b in breaches)


def test_snapshot_all_sorted():
    m.record("b", 1.0)
    m.record("a", 1.0)
    assert list(m.snapshot_all().keys()) == ["a", "b"]
