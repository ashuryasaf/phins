"""
HTTP round-trips for the AutoPilot safety-control routes (B12):

    GET  /api/terminal/autopilot/halt      status + promoted versions
    POST /api/terminal/autopilot/halt      runtime kill switch
    POST /api/terminal/autopilot/resume    clear the runtime halt
    POST /api/terminal/autopilot/promote   promote a strategy version to live

Status and halt: terminal key or admin session; anything else is 401.
Resume, promote, and every route that sends an order or runs a bot need an
admin session (``ADMIN_SESSION_POST_ROUTES``). The engine behind the routes
is the process singleton, so every test restores the state it changes.
"""

import json
import os
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import web_portal.server as portal
import services.ai_audit_bridge as bridge
from services.terminal_access_service import (
    ADMIN_SESSION_POST_ROUTES, get_access_key_display,
)
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


@pytest.fixture
def admin_token():
    _call('GET', '/api/terminal/autopilot/halt')  # warm-up so seeding survives
    _seed_session('phins_ap_admin', 'admin')
    yield 'phins_ap_admin'
    with portal.STATE_LOCK:
        portal.SESSIONS.pop('phins_ap_admin', None)


class _BrokerSpy:
    """Stands in for the trading platform and records every call that reaches it."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def _record(*args, **kwargs):
            self.calls.append(name)
            return {'status': 'accepted', 'spy': name}
        return _record


@pytest.fixture
def broker(monkeypatch):
    spy = _BrokerSpy()
    monkeypatch.setattr(portal, '_trading_platform', spy)
    return spy


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


def test_halt_status_resume_roundtrip_with_terminal_key(engine, admin_token):
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

    # The key stops trading; it does not start it again.
    status, body = _call('POST', '/api/terminal/autopilot/resume', {}, key=key)
    assert status == 401 and body == {'error': 'Admin sign-in required'}
    assert engine.halt_status()['halted'] is True

    status, body = _call('POST', '/api/terminal/autopilot/resume', {}, token=admin_token)
    assert status == 200 and body['halted'] is False


def test_admin_session_can_halt_and_actor_is_recorded(engine, admin_token):
    status, body = _call('POST', '/api/terminal/autopilot/halt', {'reason': 'admin stop'},
                         token=admin_token)
    assert status == 200
    assert body['halted'] is True and body['actor'] == 'admin:admin-test'


def test_halted_engine_refuses_execute_over_http(engine, admin_token):
    key = get_access_key_display()
    status, created = _call('POST', '/api/terminal/autopilot/create',
                            {'strategy': 'momentum', 'symbols': ['AAPL']}, key=key, token=admin_token)
    assert status == 200 and created.get('id')
    bot_id = created['id']
    try:
        assert created['mode'] == 'live' and created['strategy_version'] == '1.0'
        _call('POST', '/api/terminal/autopilot/halt', {'reason': 'drill'}, key=key)
        status, result = _call('POST', '/api/terminal/autopilot/execute', {'bot_id': bot_id},
                               key=key, token=admin_token)
        assert status == 200
        assert result[0]['error'] == 'Trading halted' and result[0]['halted'] is True
        status, bots = _call('GET', '/api/terminal/autopilot/bots', key=key)
        me = next(b for b in bots if b['id'] == bot_id)
        assert me['trade_count'] == 0 and me['blocked_count'] == 1
    finally:
        engine.delete_bot(bot_id)


def test_promote_route_validates_and_promotes(engine, admin_token):
    key = get_access_key_display()
    status, body = _call('POST', '/api/terminal/autopilot/promote', {'strategy': 'momentum'},
                         token=admin_token)
    assert status == 400 and body == {'error': 'strategy and version required'}
    status, body = _call('POST', '/api/terminal/autopilot/promote',
                         {'strategy': 'nope', 'version': '9'}, token=admin_token)
    assert status == 400 and 'error' in body

    status, created = _call('POST', '/api/terminal/autopilot/create',
                            {'strategy': 'breakout', 'symbols': ['SPY'],
                             'config': {'strategy_version': 'http-test-2.0'}}, key=key, token=admin_token)
    bot_id = created['id']
    try:
        assert created['mode'] == 'shadow'
        # The key alone does not move a shadow bot to live.
        status, body = _call('POST', '/api/terminal/autopilot/promote',
                             {'strategy': 'breakout', 'version': 'http-test-2.0'}, key=key)
        assert status == 401 and body == {'error': 'Admin sign-in required'}
        status, bots = _call('GET', '/api/terminal/autopilot/bots', key=key)
        assert next(b for b in bots if b['id'] == bot_id)['mode'] == 'shadow'

        status, body = _call('POST', '/api/terminal/autopilot/promote',
                             {'strategy': 'breakout', 'version': 'http-test-2.0'}, token=admin_token)
        assert status == 200
        assert 'http-test-2.0' in body['promoted_versions']
        status, bots = _call('GET', '/api/terminal/autopilot/bots', key=key)
        assert next(b for b in bots if b['id'] == bot_id)['mode'] == 'live'
    finally:
        engine.delete_bot(bot_id)
        with engine._lock:
            engine._promoted_versions['breakout'].discard('http-test-2.0')


# --- Order routes: the access key alone does not trade --------------------

_ORDER_BODY = {
    'symbol': 'AAPL', 'side': 'buy', 'qty': 1, 'order_id': 'ord-1', 'bot_id': 'bot-1',
    'action': 'transfer', 'account_id': 'acct-1', 'strategy': 'momentum', 'symbols': ['AAPL'],
    'version': '1.0', 'take_profit_price': 10, 'stop_loss_price': 5,
}


@pytest.mark.parametrize('route', sorted(ADMIN_SESSION_POST_ROUTES))
def test_order_routes_refuse_everything_but_an_admin_session(route, engine, broker):
    key = get_access_key_display()
    bots_before = len(engine.get_bots())

    status, body = _call('POST', route, dict(_ORDER_BODY), key=key)
    assert status == 401 and body == {'error': 'Admin sign-in required'}
    # A wrong key gets the same answer, so the route does not confirm a key.
    status, body = _call('POST', route, dict(_ORDER_BODY), key='not-the-key')
    assert status == 401 and body == {'error': 'Admin sign-in required'}
    status, body = _call('POST', route, dict(_ORDER_BODY, api_key=key))
    assert status == 401 and body == {'error': 'Admin sign-in required'}
    status, body = _call('POST', route, dict(_ORDER_BODY), key=key, token='not-a-session')
    assert status == 401 and body == {'error': 'Admin sign-in required'}

    for role in ('customer', 'accountant', 'agent'):
        token = f'phins_ap_{role}'
        _seed_session(token, role)
        try:
            status, body = _call('POST', route, dict(_ORDER_BODY), key=key, token=token)
            assert status == 403 and body == {'error': 'Admin access required'}, role
        finally:
            with portal.STATE_LOCK:
                portal.SESSIONS.pop(token, None)

    assert broker.calls == []
    assert len(engine.get_bots()) == bots_before
    assert engine.halt_status()['halted'] is False


_KEYED_ORDER_ROUTES = sorted(ADMIN_SESSION_POST_ROUTES - {
    '/api/terminal/autopilot/resume', '/api/terminal/autopilot/promote',
})


@pytest.mark.parametrize('route', _KEYED_ORDER_ROUTES)
def test_an_admin_session_still_needs_the_access_key_on_order_routes(route, engine, broker, admin_token):
    bots_before = len(engine.get_bots())
    status, body = _call('POST', route, dict(_ORDER_BODY), token=admin_token)
    assert status == 401 and body == {'error': 'Invalid access key'}
    status, body = _call('POST', route, dict(_ORDER_BODY), key='not-the-key', token=admin_token)
    assert status == 401 and body == {'error': 'Invalid access key'}
    assert broker.calls == []
    assert len(engine.get_bots()) == bots_before


@pytest.mark.parametrize('route, sent', [
    ('/api/terminal/order', 'submit_order'),
    ('/api/terminal/cancel-order', 'cancel_order'),
    ('/api/terminal/close-position', 'close_position'),
    ('/api/terminal/bracket-order', 'submit_bracket_order'),
    ('/api/terminal/oco-order', 'submit_oco_order'),
    ('/api/terminal/options/order', 'place_option_order'),
    ('/api/terminal/broker/create-account', 'broker_create_account'),
    ('/api/terminal/broker/fund', 'broker_create_transfer'),
    ('/api/terminal/broker/order', 'broker_submit_order'),
])
def test_an_admin_session_with_the_key_reaches_the_broker(route, sent, broker, admin_token):
    key = get_access_key_display()
    status, body = _call('POST', route, dict(_ORDER_BODY), key=key, token=admin_token)
    assert status == 200 and body == {'status': 'accepted', 'spy': sent}
    assert broker.calls == [sent]


def test_the_key_alone_still_reads_and_backtests(broker):
    key = get_access_key_display()
    assert _call('GET', '/api/terminal/positions', key=key)[0] == 200
    assert _call('GET', '/api/terminal/positions')[0] == 401
    assert _call('GET', '/api/terminal/autopilot/bots', key=key)[0] == 200
    status, body = _call('POST', '/api/terminal/backtest', {'api_key': 'not-the-key'})
    assert status == 401 and body == {'error': 'Invalid access key'}
    status, body = _call('POST', '/api/terminal/backtest', {}, key=key)
    assert status != 401 and status != 403


def test_every_route_that_reaches_the_broker_or_a_bot_is_in_the_admin_set():
    """A new order route added without the gate fails here."""
    import re
    from pathlib import Path
    source = Path(portal.__file__).read_text(encoding='utf-8')
    start = source.index('# ========== TRADING TERMINAL API (POST) ==========')
    end = source.index('# ========== END TRADING TERMINAL API (POST) ==========')
    section = source[start:end]
    blocks = re.split(r"\n        if path (?:==|in) ", section)[1:]
    writes = re.compile(
        r"_trading_platform\.(submit_|cancel_|close_|place_|broker_create|broker_submit)"
        r"|engine\.(create_bot|execute_bot_trades|pause_bot|resume_bot|delete_bot|"
        r"resume_trading|promote_strategy_version)"
    )
    gated = set()
    for block in blocks:
        paths = set(re.findall(r"'(/api/terminal/[a-z/-]+)'", block.split(':\n', 1)[0]))
        if writes.search(block):
            gated |= paths
    gated.discard('/api/terminal/autopilot/halt')  # stopping stays open to the key
    assert gated == set(ADMIN_SESSION_POST_ROUTES)
