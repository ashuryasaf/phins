"""HTTP create dual-run: AE1–AE3 for actuarial shadow pricing plan."""

from __future__ import annotations

import json
import os
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from services.pricing_shadow_service import (
    get_snapshots_for_policy,
    reset_shadow_store_for_tests,
)


def _base() -> str:
    return os.environ.get('TEST_BASE_URL', 'http://127.0.0.1:8000')


def _post(path: str, payload: dict):
    data = json.dumps(payload).encode('utf-8')
    req = Request(
        _base() + path,
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8'))
    except HTTPError as exc:
        body = exc.read().decode('utf-8')
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {'error': body}
        return exc.code, parsed


@pytest.fixture(autouse=True)
def _clean_shadow(monkeypatch, tmp_path):
    reset_shadow_store_for_tests()
    monkeypatch.setenv('PHINS_ACTUARIAL_STATE_PATH', str(tmp_path / 'act.json'))
    yield
    reset_shadow_store_for_tests()


def _create_payload(*, policy_type: str = 'life', email: str | None = None) -> dict:
    suffix = uuid.uuid4().hex[:8]
    return {
        'customer_name': f'Shadow Tester {suffix}',
        'customer_email': email or f'shadow.{suffix}@example.com',
        'customer_phone': '555-0100',
        'type': policy_type,
        'coverage_amount': 500000,
        'risk_score': 'medium',
        'age': 35,
        'term_years': 20,
    }


def test_ae1_flag_on_life_creates_snapshot_without_changing_billed(monkeypatch):
    monkeypatch.setenv('PHINS_PRICING_SHADOW_ENABLED', '1')
    status, body = _post('/api/policies/create', _create_payload())
    assert status in (200, 201), body
    policy = body['policy']
    billed_annual = float(policy['annual_premium'])
    billed_monthly = float(policy['monthly_premium'])
    assert billed_annual > 0
    shadow = body.get('pricing_shadow')
    assert shadow and shadow.get('enabled') is True
    assert shadow.get('product_id') == 'phins_pure_risk_adjustable'
    assert shadow.get('integrity_hash')
    assert shadow.get('flat_annual') == pytest.approx(billed_annual)
    assert float(policy['annual_premium']) == pytest.approx(billed_annual)
    assert float(policy['monthly_premium']) == pytest.approx(billed_monthly)
    snaps = get_snapshots_for_policy(policy['id'])
    assert len(snaps) >= 1
    assert snaps[0]['integrity_hash'] == shadow['integrity_hash']


def test_ae2_kernel_failure_fail_open(monkeypatch):
    monkeypatch.setenv('PHINS_PRICING_SHADOW_ENABLED', '1')

    def _boom(*_a, **_k):
        raise RuntimeError('forced kernel failure')

    monkeypatch.setattr(
        'services.pricing_shadow_service.build_shadow_snapshot',
        _boom,
    )
    status, body = _post('/api/policies/create', _create_payload(email='shadow.failopen@example.com'))
    assert status in (200, 201), body
    policy = body['policy']
    assert float(policy['annual_premium']) > 0
    assert 'pricing_shadow' not in body or body.get('pricing_shadow') in (None, {})


def test_ae3_flag_off_no_snapshot_side_effects(monkeypatch):
    monkeypatch.setenv('PHINS_PRICING_SHADOW_ENABLED', '0')
    status, body = _post('/api/policies/create', _create_payload(policy_type='life'))
    assert status in (200, 201), body
    policy = body['policy']
    assert float(policy['annual_premium']) > 0
    assert 'pricing_shadow' not in body
    assert get_snapshots_for_policy(policy['id']) == []


def test_ae3_unmapped_auto_type_skips_shadow(monkeypatch):
    monkeypatch.setenv('PHINS_PRICING_SHADOW_ENABLED', '1')
    status, body = _post('/api/policies/create', _create_payload(policy_type='auto'))
    assert status in (200, 201), body
    policy = body['policy']
    assert 'pricing_shadow' not in body
    assert get_snapshots_for_policy(policy['id']) == []


def test_amount_freeze_flag_on_vs_off(monkeypatch):
    """Same payload → billed premiums identical with flag on or off."""
    payload = _create_payload(email='shadow.freeze.a@example.com')
    monkeypatch.setenv('PHINS_PRICING_SHADOW_ENABLED', '0')
    status_off, body_off = _post('/api/policies/create', payload)
    assert status_off in (200, 201), body_off

    payload2 = _create_payload(email='shadow.freeze.b@example.com')
    # Match coverage/age/type from first payload for comparable quote.
    payload2['coverage_amount'] = payload['coverage_amount']
    payload2['age'] = payload['age']
    payload2['type'] = payload['type']
    payload2['term_years'] = payload.get('term_years')
    monkeypatch.setenv('PHINS_PRICING_SHADOW_ENABLED', '1')
    status_on, body_on = _post('/api/policies/create', payload2)
    assert status_on in (200, 201), body_on

    assert body_off['policy']['annual_premium'] == body_on['policy']['annual_premium']
    assert body_off['policy']['monthly_premium'] == body_on['policy']['monthly_premium']
    assert body_on.get('pricing_shadow', {}).get('enabled') is True
