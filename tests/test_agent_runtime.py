"""
Tests for the agent runtime registry (services/agent_runtime.py).
"""

import importlib

import pytest

from services import agent_runtime as rt


def _desc(agent_id="test_agent", module="tests.fake_module", **overrides):
    base = dict(
        id=agent_id, name="Test Agent", version="1.0", module=module,
        description="test", entry_url="/x.html",
        api={"method": "GET", "path": "/api/x"}, roles=("admin",),
    )
    base.update(overrides)
    return rt.AgentDescriptor(**base)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    for agent_id in ("test_agent", "test_agent_2"):
        rt.unregister(agent_id)


def test_register_and_lookup():
    desc = rt.register(_desc())
    assert rt.is_registered("test_agent")
    assert rt.get_descriptor("test_agent") == desc
    assert any(d.id == "test_agent" for d in rt.registry())


def test_reregister_same_module_is_idempotent():
    rt.register(_desc(version="1.0"))
    rt.register(_desc(version="1.1"))
    assert rt.get_descriptor("test_agent").version == "1.1"


def test_reregister_different_module_is_rejected():
    rt.register(_desc(module="tests.module_a"))
    with pytest.raises(ValueError):
        rt.register(_desc(module="tests.module_b"))
    assert rt.get_descriptor("test_agent").module == "tests.module_a"


def test_invalid_descriptor_rejected():
    with pytest.raises(ValueError):
        rt.register(_desc(agent_id=""))
    with pytest.raises(ValueError):
        rt.register("not a descriptor")  # type: ignore[arg-type]


def test_health_defaults_and_probe_failure_never_raise():
    rt.register(_desc())
    assert rt.health("test_agent")["status"] == rt.HEALTH_OK
    assert rt.health("missing")["status"] == rt.HEALTH_UNKNOWN

    def boom():
        raise RuntimeError("probe exploded")

    rt.register(_desc(agent_id="test_agent_2"), health_fn=boom)
    out = rt.health("test_agent_2")
    assert out["status"] == rt.HEALTH_UNAVAILABLE
    assert "probe exploded" in out["error"]


def test_health_normalises_unknown_status_strings():
    rt.register(_desc(), health_fn=lambda: {"status": "GREEN"})
    assert rt.health("test_agent")["status"] == rt.HEALTH_UNKNOWN
    rt.register(_desc(), health_fn=lambda: {"status": "Degraded", "detail": "x"})
    out = rt.health("test_agent")
    assert out["status"] == rt.HEALTH_DEGRADED and out["detail"] == "x"


def test_metrics_falls_back_to_shared_snapshot():
    from services import agent_metrics
    agent_metrics.reset("test_agent")
    rt.register(_desc())
    agent_metrics.record("test_agent", 12.0)
    assert rt.metrics("test_agent")["calls"] == 1
    rt.register(_desc(), metrics_fn=lambda: {"custom": True})
    assert rt.metrics("test_agent") == {"custom": True}


def test_overview_shape():
    rt.register(_desc())
    rows = [r for r in rt.overview() if r["id"] == "test_agent"]
    assert len(rows) == 1
    row = rows[0]
    assert set(("health", "metrics", "registered_at", "roles", "api")) <= set(row)
    assert row["roles"] == ["admin"]


def test_to_capability_matches_catalog_shape():
    cap = _desc().to_capability()
    for key in ("id", "name", "description", "entry_url", "api", "roles",
                "sample_prompts", "deterministic"):
        assert key in cap


# ---------------------------------------------------------------------------
# Real agents
# ---------------------------------------------------------------------------

EXPECTED_AGENT_IDS = {
    "underwriting_bot", "claims_bot", "ai_automation_controller",
    "underwriting_assistant", "assessment_ai", "pension_data_agent",
    "document_intelligence", "customer_communication", "customer_service",
    "marketing_sales", "video_agents", "ai_risk_reports", "bi_analytics",
    "delivery_bidding", "ai_trading_engine",
}


def test_all_agents_register_and_modules_import():
    from services import ai_capabilities
    ai_capabilities.ensure_agents_loaded()
    ids = {d.id for d in rt.registry()}
    missing = EXPECTED_AGENT_IDS - ids
    assert not missing, f"unregistered agents: {sorted(missing)}"
    for desc in rt.registry():
        if desc.id in EXPECTED_AGENT_IDS:
            importlib.import_module(desc.module)


def test_every_registered_api_path_is_routed():
    """Each descriptor's api.path must appear in a real dispatcher."""
    import inspect
    from services import ai_capabilities
    import web_portal.server as server
    import web_portal.api_extensions as ext
    import web_portal.api_bi_analytics as bi
    import web_portal.api_delivery_bidding as delivery
    import web_portal.api_assessment_center as ac

    ai_capabilities.ensure_agents_loaded()
    sources = "\n".join([
        inspect.getsource(server.PortalHandler.do_GET),
        inspect.getsource(server.PortalHandler.do_POST),
        inspect.getsource(ext), inspect.getsource(bi),
        inspect.getsource(delivery), inspect.getsource(ac),
    ])
    for desc in rt.registry():
        if desc.id not in EXPECTED_AGENT_IDS:
            continue
        path = desc.api.get("path", "")
        assert path and path in sources, f"{desc.id}: {path} not routed"


def test_money_moving_agents_are_flagged():
    from services import ai_capabilities
    ai_capabilities.ensure_agents_loaded()
    assert rt.get_descriptor("ai_trading_engine").moves_money is True
    assert rt.get_descriptor("claims_bot").moves_money is False
