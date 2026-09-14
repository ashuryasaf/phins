"""
HTTP round-trips for the AutoPilot safety-control routes (B12):

    GET  /api/terminal/autopilot/halt      status + promoted versions
    POST /api/terminal/autopilot/halt      runtime kill switch
    POST /api/terminal/autopilot/resume    clear the runtime halt
    POST /api/terminal/autopilot/promote   promote a strategy version to live

Terminal key or admin session; anything else is 401. The engine behind the
routes is the process singleton, so every test restores the state it changes.
"""

import json
import os
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import web_portal.server as portal
import services.ai_audit_bridge as bridge
from services.terminal_access_service import get_access_key_display
from services.trading_platform_service import get_autopilot_engine

pytestmark = pytest.mark.skipif(not portal.trading_platform_enabled,
                                reason="trading platform not wired in this build")


def _base_url():
    return os.environ.get('TEST_BASE_URL') or f"http://127.0.0.1:{os.environ.get('TEST_PORT', '8000')}"


def _call(method, path, body=None, key=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if key:
        headers['X-Terminal-Key'] = key
    if token:
        headers['Authorization'] = f'Bearer {token}'
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = Request(_base_url() + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode('utf-8') or '{}')


def _seed_session(token, role):
    expires = (datetime.now() + timedelta(hours=1)).isoformat()
    with portal.STATE_LOCK:
        portal.SESSIONS[token] = {'username': f'{role}-test', 'role': role,
                                  'expires': expires, 'jti': f'{token}-jti'}


@pytest.fixture(autouse=True)
def _quiet_audit(monkeypatch):
    """Keep route tests from writing audit rows; the engine tests cover that."""
    monkeypatch.setattr(bridge, 'record_ai_audit', lambda **kw: True)
    monkeypatch.delenv('PHINS_TRADING_HALT', raising=False)


@pytest.fixture
def engine():
    eng = get_autopilot_engine()
    eng.resume_trading(actor='test-setup')
    yield eng
    eng.resume_trading(actor='test-teardown')


def test_safety_routes_reject_missing_or_bad_credentials(engine):
    # First request per port clears in-memory state; nothing to seed yet.
    assert _call('GET', '/api/terminal/autopilot/halt')[0] == 401
    assert _call('POST', '/api/terminal/autopilot/halt', {'reason': 'x'})[0] == 401
    assert _call('POST', '/api/terminal/autopilot/resume', {})[0] == 401
    assert _call('POST', '/api/terminal/autopilot/promote', {'strategy': 'momentum', 'version': '2'})[0] == 401
    status, body = _call('POST', '/api/terminal/autopilot/halt', {'api_key': 'not-the-key'})
    assert status == 401 and body == {'error': 'Invalid access key'}
    assert engine.halt_status()['halted'] is False


def test_customer_session_cannot_operate_controls(engine):
    _call('GET', '/api/terminal/autopilot/halt')  # warm-up so seeding survives
    _seed_session('phins_ap_customer', 'customer')
    try:
        status, body = _call('POST', '/api/terminal/autopilot/halt', {}, token='phins_ap_customer')
        assert status == 401 and 'error' in body
        assert engine.halt_status()['halted'] is False
    finally:
        with portal.STATE_LOCK:
            portal.SESSIONS.pop('phins_ap_customer', None)


def test_halt_status_resume_roundtrip_with_terminal_key(engine):
    key = get_access_key_display()
    status, body = _call('GET', '/api/terminal/autopilot/halt', key=key)
    assert status == 200
    assert body['halted'] is False and body['source'] is None
    assert body['promoted_versions']['momentum'] == ['1.0']

    status, body = _call('POST', '/api/terminal/autopilot/halt', {'reason': 'ops drill'}, key=key)
    assert status == 200
    assert body['halted'] is True and body['source'] == 'runtime'
    assert body['reason'] == 'ops drill' and body['actor'] == 'terminal_key'

    status, body = _call('GET', '/api/terminal/autopilot/halt', key=key)
    assert body['halted'] is True

    status, body = _call('POST', '/api/terminal/autopilot/resume', {}, key=key)
    assert status == 200 and body['halted'] is False


def test_admin_session_can_halt_and_actor_is_recorded(engine):
    _call('GET', '/api/terminal/autopilot/halt')
    _seed_session('phins_ap_admin', 'admin')
    try:
        status, body = _call('POST', '/api/terminal/autopilot/halt', {'reason': 'admin stop'},
                             token='phins_ap_admin')
        assert status == 200
        assert body['halted'] is True and body['actor'] == 'admin:admin-test'
    finally:
        with portal.STATE_LOCK:
            portal.SESSIONS.pop('phins_ap_admin', None)


def test_halted_engine_refuses_execute_over_http(engine):
    key = get_access_key_display()
    status, created = _call('POST', '/api/terminal/autopilot/create',
                            {'strategy': 'momentum', 'symbols': ['AAPL']}, key=key)
    assert status == 200 and created.get('id')
    bot_id = created['id']
    try:
        assert created['mode'] == 'live' and created['strategy_version'] == '1.0'
        _call('POST', '/api/terminal/autopilot/halt', {'reason': 'drill'}, key=key)
        status, result = _call('POST', '/api/terminal/autopilot/execute', {'bot_id': bot_id}, key=key)
        assert status == 200
        assert result[0]['error'] == 'Trading halted' and result[0]['halted'] is True
        status, bots = _call('GET', '/api/terminal/autopilot/bots', key=key)
        me = next(b for b in bots if b['id'] == bot_id)
        assert me['trade_count'] == 0 and me['blocked_count'] == 1
    finally:
        engine.delete_bot(bot_id)


def test_promote_route_validates_and_promotes(engine):
    key = get_access_key_display()
    status, body = _call('POST', '/api/terminal/autopilot/promote', {'strategy': 'momentum'}, key=key)
    assert status == 400 and body == {'error': 'strategy and version required'}
    status, body = _call('POST', '/api/terminal/autopilot/promote',
                         {'strategy': 'nope', 'version': '9'}, key=key)
    assert status == 400 and 'error' in body

    status, created = _call('POST', '/api/terminal/autopilot/create',
                            {'strategy': 'breakout', 'symbols': ['SPY'],
                             'config': {'strategy_version': 'http-test-2.0'}}, key=key)
    bot_id = created['id']
    try:
        assert created['mode'] == 'shadow'
        status, body = _call('POST', '/api/terminal/autopilot/promote',
                             {'strategy': 'breakout', 'version': 'http-test-2.0'}, key=key)
        assert status == 200
        assert 'http-test-2.0' in body['promoted_versions']
        status, bots = _call('GET', '/api/terminal/autopilot/bots', key=key)
        assert next(b for b in bots if b['id'] == bot_id)['mode'] == 'live'
    finally:
        engine.delete_bot(bot_id)
        with engine._lock:
            engine._promoted_versions['breakout'].discard('http-test-2.0')
