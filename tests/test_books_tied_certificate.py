"""U6 books-tied daily certificate — seal, freshness gate, ledger evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.erp import books_tied as bt
from services.erp.money_gate import MoneyGateError, authorize_money_move, digest_for
from services.jobs import books_tied_job
from services.platform_event_ledger_service import PlatformEventLedgerService


def _green_books():
    return {
        'unified': {'integrity': {'ok': True, 'failed': []}},
        'reconcile': {'discrepancies': []},
    }


def _red_books():
    return {
        'unified': {
            'integrity': {
                'ok': False,
                'failed': ['claims_counted_once'],
            }
        },
        'reconcile': {'discrepancies': []},
    }


def _ledger():
    return PlatformEventLedgerService({}, use_database=False)


def test_seal_and_verify_round_trip():
    payload = bt.seal_certificate_payload({
        'utc_day': '2026-11-27',
        'ok': True,
        'digest': digest_for([], ok=True),
        'failed_checks': [],
        'evaluated_at': '2026-11-27T01:00:00+00:00',
    })
    assert payload['certificate_sha256']
    entry = {
        'id': 'BOOKS-TIED-2026-11-27',
        'event_type': bt.EVENT_TYPE,
        'payload': payload,
    }
    check = bt.verify_certificate(entry)
    assert check['ok'] is True
    assert check['utc_day'] == '2026-11-27'

    tampered = dict(entry)
    tampered['payload'] = dict(payload)
    tampered['payload']['digest'] = 'deadbeef'
    bad = bt.verify_certificate(tampered)
    assert bad['ok'] is False
    assert bad['reason'] == bt.CERT_TAMPERED


def test_issue_on_green_is_idempotent(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    ledger = _ledger()
    first = bt.issue_certificate(ledger, books=_green_books(), actor='test')
    assert first['issued'] is True
    assert first['entry']['id'] == bt.certificate_entry_id(bt.utc_day())
    assert first['verification']['ok'] is True

    second = bt.issue_certificate(ledger, books=_green_books(), actor='test')
    assert second['issued'] is False
    assert second['reason'] == 'already_issued'
    assert second['verification']['ok'] is True

    # Flattened production shape still verifies.
    flat = ledger.transaction_ledger[first['entry']['id']]
    assert 'payload' not in flat or not isinstance(flat.get('payload'), dict) or 'utc_day' in flat
    assert bt.verify_certificate(flat)['ok'] is True


def test_issue_refuses_red_books(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    ledger = _ledger()
    result = bt.issue_certificate(ledger, books=_red_books(), actor='test')
    assert result['issued'] is False
    assert result['reason'] == 'books_red'
    assert result['failed_checks'] == ['claims_counted_once']
    assert list(ledger.transaction_ledger) == []


def test_freshness_gate_blocks_high_value_without_cert(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    monkeypatch.setenv('PHINS_BOOKS_TIED_REQUIRE', '1')
    ledger = _ledger()
    with pytest.raises(MoneyGateError) as raised:
        authorize_money_move(
            'wallet_withdrawal.release',
            books=_green_books(),
            actor='admin',
            role='admin',
            platform_ledger=ledger,
        )
    assert bt.CERT_MISSING in raised.value.failed_checks

    # Non-high-value ops skip the certificate check.
    verdict = authorize_money_move(
        'remittance.settle',
        books=_green_books(),
        actor='admin',
        role='admin',
        platform_ledger=ledger,
    )
    assert verdict.ok is True


def test_freshness_gate_accepts_today_cert(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    monkeypatch.setenv('PHINS_BOOKS_TIED_REQUIRE', '1')
    ledger = _ledger()
    issued = bt.issue_certificate(ledger, books=_green_books(), actor='test')
    assert issued['issued'] is True
    verdict = authorize_money_move(
        'claim_payout',
        books=_green_books(),
        actor='claims',
        role='claims',
        platform_ledger=ledger,
    )
    assert verdict.ok is True
    assert verdict.failed_checks == []


def test_stale_certificate_refuses(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    monkeypatch.setenv('PHINS_BOOKS_TIED_REQUIRE', '1')
    monkeypatch.setenv('PHINS_BOOKS_TIED_MAX_AGE_HOURS', '2')
    ledger = _ledger()
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    from services.erp.money_gate import MoneyGateVerdict

    stale_verdict = MoneyGateVerdict(
        ok=True,
        failed_checks=[],
        digest=digest_for([], ok=True),
        enforced=True,
        operation='books_tied.issue',
        evaluated_at=old.isoformat(),
    )
    issued = bt.issue_certificate(
        ledger, verdict=stale_verdict, actor='test', day=bt.utc_day(), force=True,
    )
    assert issued['issued'] is True
    with pytest.raises(MoneyGateError) as raised:
        authorize_money_move(
            'agent_commission.settle',
            books=_green_books(),
            actor='admin',
            role='admin',
            platform_ledger=ledger,
        )
    assert bt.CERT_STALE in raised.value.failed_checks


def test_status_report_and_job(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    monkeypatch.setenv('PHINS_BOOKS_TIED_REQUIRE', '1')
    ledger = _ledger()
    before = bt.status_report(ledger)
    assert before['present'] is False
    assert before['fresh'] is False

    result = books_tied_job.run_once(
        books=_green_books(), ledger=ledger, actor='job',
    )
    assert result['certificate']['issued'] is True
    after = result['status']
    assert after['present'] is True
    assert after['intact'] is True
    assert after['fresh'] is True
    assert after['entry_id'].startswith('BOOKS-TIED-')


def test_books_integrity_job_can_issue_certificate(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    from services.jobs import books_integrity_job

    ledger = _ledger()
    result = books_integrity_job.run_once(
        books=_green_books(),
        issue_certificate=True,
        ledger=ledger,
    )
    assert result['ok'] is True
    assert result['certificate']['issued'] is True


def test_freshness_exception_fails_closed(monkeypatch):
    """A crash inside freshness_failures must refuse high-value moves."""
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    monkeypatch.setenv('PHINS_BOOKS_TIED_REQUIRE', '1')

    def _boom(*_a, **_k):
        raise RuntimeError('ledger walk failed')

    monkeypatch.setattr(bt, 'freshness_failures', _boom)
    with pytest.raises(MoneyGateError) as raised:
        authorize_money_move(
            'claim_payout',
            books=_green_books(),
            actor='claims',
            role='claims',
            platform_ledger=_ledger(),
        )
    assert bt.CERT_MISSING in raised.value.failed_checks


def test_inprocess_daily_clock_issues_and_is_idempotent(monkeypatch):
    monkeypatch.setenv('PHINS_MONEY_GATE', '1')
    ledger = _ledger()
    # Reset module flags so this test owns the in-process timer.
    books_tied_job._INPROCESS_STARTED = False
    if books_tied_job._INPROCESS_TIMER is not None:
        try:
            books_tied_job._INPROCESS_TIMER.cancel()
        except Exception:
            pass
        books_tied_job._INPROCESS_TIMER = None

    monkeypatch.setattr(books_tied_job, '_portal_ledger', lambda: ledger)
    first = books_tied_job.start_inprocess_daily_clock(issue_now=True)
    assert first['started'] is True
    assert (first.get('certificate') or {}).get('certificate', {}).get('issued') is True
    second = books_tied_job.start_inprocess_daily_clock(issue_now=False)
    assert second['reason'] == 'already_started'
    if books_tied_job._INPROCESS_TIMER is not None:
        books_tied_job._INPROCESS_TIMER.cancel()
        books_tied_job._INPROCESS_TIMER = None
    books_tied_job._INPROCESS_STARTED = False


def test_books_tied_http_routes(monkeypatch):
    """Accountant GET/POST surface on the embedded portal."""
    import json
    import os
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    import web_portal.server as portal

    monkeypatch.setenv('PHINS_MONEY_GATE', '0')
    token = 'phins_books_tied-admin'
    portal.SESSIONS[token] = portal._stamp_session_payload({
        'username': 'admin', 'role': 'admin', 'expires': '2099-01-01T00:00:00',
    })
    init_set = getattr(portal, '_TEST_PORTS_INITIALIZED', None)
    if isinstance(init_set, set):
        init_set.add(int(os.environ.get('TEST_PORT', '8000')))
    base = os.environ.get('TEST_BASE_URL', 'http://127.0.0.1:8000')

    def call(method, path, body=None):
        data = None if body is None else json.dumps(body).encode('utf-8')
        req = Request(
            base + path,
            data=data,
            method=method,
            headers={
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json',
            },
        )
        try:
            with urlopen(req, timeout=20) as resp:
                return resp.status, json.loads(resp.read().decode('utf-8'))
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode('utf-8') or '{}')

    try:
        status, body = call('GET', '/api/admin/cashflow/books-tied')
        assert status == 200, body
        assert body.get('success') is True
        assert 'books_tied' in body
        assert body['books_tied']['event_type'] == bt.EVENT_TYPE

        status, body = call('POST', '/api/admin/cashflow/books-tied', {})
        assert status == 200, body
        assert 'certificate' in body
        # Green or red books both return a status; red simply does not issue.
        assert body['books_tied']['utc_day']
    finally:
        portal.SESSIONS.pop(token, None)
