"""
Tests for the admin agent-health surface and the ``agents`` block on
``/api/metrics`` (docs/agent_operations_optimization_design.md §A5).
"""

import json
import os
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import web_portal.server as portal
from web_portal import api_extensions as ext
from services import agent_metrics


def _dispatch(session):
    return ext.dispatch_get('/api/admin/ai-agents/health', session, {}, '127.0.0.1')


def test_health_route_requires_authentication():
    status, payload = _dispatch(None)
    assert status == 401
    assert payload == {'error': 'Authentication required'}


@pytest.mark.parametrize('role', ['customer', 'underwriter', 'media', 'supplier', ''])
def test_health_route_requires_admin(role):
    status, payload = _dispatch({'role': role, 'username': 'x'})
    assert status == 403
    assert 'error' in payload


def test_health_route_admin_payload_shape_and_is_json_serialisable():
    agent_metrics.reset()
    status, payload = _dispatch({'role': 'admin', 'username': 'admin'})
    assert status == 200
    json.dumps(payload)  # server writes json.dumps(...) without default=str
    assert payload['agent_count'] == len(payload['agents']) >= 15
    assert payload['load_failures'] == {}
    assert isinstance(payload['slo_breaches'], list)
    assert sum(payload['health_summary'].values()) == payload['agent_count']
    for agent in payload['agents']:
        assert agent['health']['status'] in ('ok', 'degraded', 'unavailable', 'unknown'), agent['id']
        assert 'calls' in agent['metrics'], agent['id']
        assert agent['api']['method'] and agent['api']['path']
        assert isinstance(agent['moves_money'], bool)


def test_health_probes_are_read_only():
    """Calling the health view must not instantiate any agent singleton."""
    import services.claims_bot_service as claims
    import services.delivery_bidding_service as delivery
    import services.video_agents_service as video
    before = (claims._bot_instance, delivery._delivery_service, video._video_agents_service)
    _dispatch({'role': 'admin', 'username': 'admin'})
    after = (claims._bot_instance, delivery._delivery_service, video._video_agents_service)
    assert before == after


def test_health_route_reflects_metrics_and_slo_breaches():
    agent_metrics.reset()
    for _ in range(25):
        agent_metrics.record('claims_bot', 1.0, error='RuntimeError: boom')
    status, payload = _dispatch({'role': 'admin', 'username': 'admin'})
    assert status == 200
    claims = next(a for a in payload['agents'] if a['id'] == 'claims_bot')
    assert claims['metrics']['errors'] == 25
    assert any(b['agent_id'] == 'claims_bot' and b['kind'] == 'error_rate'
               for b in payload['slo_breaches'])
    agent_metrics.reset()


def test_capabilities_route_source_still_uses_help_text():
    import inspect
    src = inspect.getsource(portal.PortalHandler.do_GET)
    assert "path == '/api/admin/ai-agents/health'" in inspect.getsource(ext.dispatch_get)
    assert "'/api/metrics'" in src and "data['agents']" in src


# ---------------------------------------------------------------------------
# HTTP round-trips against the embedded server from root conftest.py
# ---------------------------------------------------------------------------

def _base_url():
    return os.environ.get('TEST_BASE_URL') or f"http://127.0.0.1:{os.environ.get('TEST_PORT', '8000')}"


def _get(path, token=None):
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    try:
        with urlopen(Request(_base_url() + path, headers=headers), timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode('utf-8') or '{}')


def _seed_session(token, role):
    expires = (datetime.now() + timedelta(hours=1)).isoformat()
    with portal.STATE_LOCK:
        portal.SESSIONS[token] = {
            'username': f'{role}-test', 'role': role, 'expires': expires,
            'jti': f'{token}-jti',
        }


def test_metrics_endpoint_exposes_agents_block_over_http():
    agent_metrics.reset()
    agent_metrics.record('bi_analytics', 3.5)
    status, body = _get('/api/metrics')
    assert status == 200
    assert 'agents' in body['metrics']
    assert body['metrics']['agents']['bi_analytics']['calls'] >= 1
    # Business metrics are untouched by the addition.
    assert {'policies', 'claims', 'billing'} <= set(body['metrics'])
    agent_metrics.reset()


def test_metrics_endpoint_withholds_agent_error_text_over_http():
    """The endpoint is unauthenticated, so error text must not ship on it."""
    agent_metrics.reset()
    agent_metrics.record('bi_analytics', 3.5, error='ValueError: Customer CUST-001 not found',
                         decision='auto_approve')
    status, body = _get('/api/metrics')
    assert status == 200
    snap = body['metrics']['agents']['bi_analytics']
    assert snap['errors'] == 1
    assert 'last_error' not in snap and 'decisions' not in snap
    assert 'CUST-001' not in json.dumps(body)
    agent_metrics.reset()


def test_agent_health_over_http_enforces_admin():
    # The embedded server clears in-memory state on its first request per
    # port (_ensure_test_port_state), so probe unauthenticated first and seed
    # sessions afterwards.
    status, body = _get('/api/admin/ai-agents/health')
    assert status == 401
    _seed_session('phins_agent_health_customer', 'customer')
    _seed_session('phins_agent_health_admin', 'admin')
    try:
        status, body = _get('/api/admin/ai-agents/health', token='phins_agent_health_customer')
        assert status == 403 and 'error' in body
        status, body = _get('/api/admin/ai-agents/health', token='phins_agent_health_admin')
        assert status == 200
        assert body['agent_count'] >= 15
    finally:
        with portal.STATE_LOCK:
            portal.SESSIONS.pop('phins_agent_health_customer', None)
            portal.SESSIONS.pop('phins_agent_health_admin', None)
