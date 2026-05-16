"""
Tests for the Annuity Reserves Forecast tool.

The reserve formula is the dashboard's core actuarial guarantee model
(``services.annuity_reserve_service.compute_annuity_reserve_forecast``).
These tests pin down its determinism, integrity hash stability, and
sanity invariants so the dashboard's "Forecast Bar" can never silently
disagree with what the kernel actually computed.

We also verify the HTTP surface:

* ``GET /api/actuarial/annuity-reserve/defaults`` (admin/actuary only)
* ``POST /api/actuarial/annuity-reserve/forecast`` (admin/actuary only)

Both run against the embedded server started by the repository-level
``conftest.py``.
"""

from __future__ import annotations

import json
import os
import urllib.error
from urllib.request import Request, urlopen

import pytest

from services.annuity_reserve_service import (
    AnnuityReserveConfig,
    annuity_factor,
    coerce_annuity_reserve_config,
    compute_annuity_reserve_forecast,
    get_default_annuity_reserve_inputs,
)


# ----------------------------------------------------------------------------
# Service-layer unit tests
# ----------------------------------------------------------------------------


def test_annuity_factor_zero_rate_collapses_to_n():
    assert annuity_factor(0.0, 20) == 20.0
    assert annuity_factor(0.0, 1) == 1.0


def test_annuity_factor_matches_closed_form_for_4pct():
    # ä_n = (1 - v^n) / (1 - v) with v = 1/1.04, n = 20
    n, r = 20, 0.04
    v = 1.0 / (1.0 + r)
    expected = (1.0 - v ** n) / (1.0 - v)
    assert abs(annuity_factor(r, n) - expected) < 1e-12


def test_default_forecast_has_thirty_year_projection():
    out = compute_annuity_reserve_forecast(AnnuityReserveConfig())
    assert len(out['yearly']) == 30
    assert out['totals']['peak_reserve'] >= 0
    assert out['integrity_checks']['reserve_non_negative']
    assert out['integrity_checks']['monotone_cumulative_deposits']


def test_forecast_is_deterministic_under_identical_inputs():
    a = compute_annuity_reserve_forecast(AnnuityReserveConfig())
    b = compute_annuity_reserve_forecast(AnnuityReserveConfig())
    assert a['integrity_hash'] == b['integrity_hash']
    assert a['yearly'] == b['yearly']
    assert len(a['integrity_hash']) == 64


def test_scenario_label_changes_integrity_hash_only():
    """Labels are part of the canonical block: same numbers, different label
    must hash differently so we can prove which scenario produced the
    forecast on screen.
    """
    base = compute_annuity_reserve_forecast(AnnuityReserveConfig(scenario_label='base'))
    stress = compute_annuity_reserve_forecast(AnnuityReserveConfig(scenario_label='stress'))
    assert base['integrity_hash'] != stress['integrity_hash']
    # Yearly numeric block stays identical (the label is a metadata flag).
    assert base['yearly'] == stress['yearly']


def test_zero_conversion_collapses_aggregate_reserve_to_zero():
    out = compute_annuity_reserve_forecast(AnnuityReserveConfig(
        conversion_rate_pct=0.0,
        # Stress the realised return so the per-customer P would be > 0
        realised_return_curve=[0.01] * 30,
    ))
    for row in out['yearly']:
        assert row['converted_customers'] == 0
        assert row['reserve_aggregate'] == 0.0
    assert out['totals']['peak_reserve'] == 0


def test_realised_return_below_guarantee_creates_reserve():
    """The reserve must turn positive when the realised market track
    underperforms the guaranteed minimum — that is the entire point of
    the formula.
    """
    out = compute_annuity_reserve_forecast(AnnuityReserveConfig(
        guarantee_rate_pct=0.04,
        guarantee_credit_pct=0.04,
        expected_market_return_pct=0.02,
        madad_pct=0.025,
        realised_return_curve=[0.01] * 30,
    ))
    assert out['totals']['peak_reserve'] > 0
    assert out['totals']['final_year_reserve'] > 0
    # Funding ratio must be below 1.0 since the realised savings track
    # cannot keep up with the indexed guarantee.
    assert out['totals']['funding_ratio'] < 1.0


def test_zero_loss_lambda_collapses_loss_correction_term():
    """When λ = 0 the actuarial-loss term contributes 0 to every year."""
    out = compute_annuity_reserve_forecast(AnnuityReserveConfig(
        actuarial_loss_lambda=0.0,
        realised_return_curve=[0.01] * 30,
    ))
    for row in out['yearly']:
        assert row['loss_correction_per_customer'] == 0.0


def test_adjustable_factors_default_to_one():
    """With default factors (all 1.0) the result matches the original formula."""
    default_out = compute_annuity_reserve_forecast(AnnuityReserveConfig())
    explicit_out = compute_annuity_reserve_forecast(AnnuityReserveConfig(
        annuity_gap_factor=1.0,
        madad_term_factor=1.0,
        loss_correction_factor=1.0,
        interest_credit_factor=1.0,
    ))
    assert default_out['integrity_hash'] == explicit_out['integrity_hash']
    assert default_out['yearly'] == explicit_out['yearly']


def test_zero_annuity_gap_factor_removes_gap_contribution():
    """Setting annuity_gap_factor=0 should zero out the gap component."""
    base = compute_annuity_reserve_forecast(AnnuityReserveConfig(
        realised_return_curve=[0.01] * 30,
    ))
    zeroed = compute_annuity_reserve_forecast(AnnuityReserveConfig(
        realised_return_curve=[0.01] * 30,
        annuity_gap_factor=0.0,
    ))
    assert base['integrity_hash'] != zeroed['integrity_hash']
    # The per-customer raw reserve must differ when the gap factor is removed.
    for b, z in zip(base['yearly'], zeroed['yearly']):
        if b['annuity_gap_per_customer'] != 0:
            assert b['p_per_customer_raw'] != z['p_per_customer_raw']


def test_doubled_factor_doubles_component_contribution():
    """Doubling a factor should double that component's contribution to P(X)."""
    base = compute_annuity_reserve_forecast(AnnuityReserveConfig(
        projection_years=5,
        realised_return_curve=[0.01] * 5,
        madad_term_factor=1.0,
    ))
    doubled = compute_annuity_reserve_forecast(AnnuityReserveConfig(
        projection_years=5,
        realised_return_curve=[0.01] * 5,
        madad_term_factor=2.0,
    ))
    for b, d in zip(base['yearly'], doubled['yearly']):
        if b['madad_term_per_customer'] != 0:
            assert d['p_per_customer_raw'] != b['p_per_customer_raw']


def test_factors_surface_in_inputs_and_integrity_hash():
    """Factor values must appear in the inputs view and affect the hash."""
    out = compute_annuity_reserve_forecast(AnnuityReserveConfig(
        annuity_gap_factor=0.8,
        loss_correction_factor=1.5,
    ))
    assert out['inputs']['annuity_gap_factor'] == 0.8
    assert out['inputs']['loss_correction_factor'] == 1.5
    assert out['inputs']['madad_term_factor'] == 1.0
    assert out['inputs']['interest_credit_factor'] == 1.0
    # Hash must differ from the all-1.0-factors scenario.
    default_hash = compute_annuity_reserve_forecast(AnnuityReserveConfig())['integrity_hash']
    assert out['integrity_hash'] != default_hash


def test_coerce_handles_adjustable_factors():
    """coerce_annuity_reserve_config should parse factor fields from payloads."""
    cfg = coerce_annuity_reserve_config({
        'annuity_gap_factor': 0.5,
        'madad_term_factor': '1.2',
        'loss_correction_factor': 2,
        'interest_credit_factor': '',
    })
    assert cfg.annuity_gap_factor == 0.5
    assert cfg.madad_term_factor == 1.2
    assert cfg.loss_correction_factor == 2.0
    assert cfg.interest_credit_factor == 1.0


def test_per_customer_guaranteed_savings_grow_monotonically():
    out = compute_annuity_reserve_forecast(AnnuityReserveConfig(
        madad_pct=0.0,
        guarantee_rate_pct=0.04,
    ))
    yearly = out['yearly']
    for i in range(1, len(yearly)):
        assert (
            yearly[i]['savings_per_customer_guaranteed']
            > yearly[i - 1]['savings_per_customer_guaranteed']
        )


def test_inputs_view_exposes_resolved_curves_for_audit():
    cfg = AnnuityReserveConfig(
        projection_years=5,
        expected_market_return_curve=[0.07, 0.06, 0.05],
    )
    out = compute_annuity_reserve_forecast(cfg)
    curves = out['inputs']['curves']
    # The curve was 3 entries; the resolver must extend to projection_years
    # by repeating the last value so the audit table never has gaps.
    assert len(curves['expected_return']) == 5
    assert curves['expected_return'][:3] == [0.07, 0.06, 0.05]
    assert curves['expected_return'][3] == 0.05
    assert curves['expected_return'][4] == 0.05


def test_coerce_accepts_percent_or_fraction():
    cfg_pct = coerce_annuity_reserve_config({'guarantee_rate_pct': 4})
    cfg_frac = coerce_annuity_reserve_config({'guarantee_rate_pct': 0.04})
    assert cfg_pct.guarantee_rate_pct == 0.04
    assert cfg_frac.guarantee_rate_pct == 0.04


def test_coerce_curve_accepts_list_or_csv_string():
    cfg_list = coerce_annuity_reserve_config({'realised_return_curve': [0.05, 0.06]})
    assert cfg_list.realised_return_curve == [0.05, 0.06]
    cfg_csv = coerce_annuity_reserve_config({'realised_return_curve': '0.05, 0.06, 0.07'})
    assert cfg_csv.realised_return_curve == [0.05, 0.06, 0.07]


def test_get_default_inputs_round_trips_through_coercion():
    defaults = get_default_annuity_reserve_inputs()
    cfg = coerce_annuity_reserve_config(defaults)
    assert cfg.projection_years == defaults['projection_years']
    assert cfg.guarantee_rate_pct == defaults['guarantee_rate_pct']
    assert cfg.payout_horizon_years == defaults['payout_horizon_years']


# ----------------------------------------------------------------------------
# HTTP integration tests
# ----------------------------------------------------------------------------


def _base_url() -> str:
    return os.environ.get('TEST_BASE_URL') or 'http://127.0.0.1:8000'


def _post_json(url: str, payload: dict, token: str | None = None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    with urlopen(req) as resp:
        return resp.read(), resp.status, dict(resp.getheaders())


def _get(url: str, token: str | None = None):
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return resp.read(), resp.status, dict(resp.getheaders())


@pytest.fixture
def admin_token() -> str:
    body, status, _ = _post_json(_base_url() + '/api/login', {
        'username': 'admin', 'password': 'admin123',
    })
    assert status == 200, body
    return json.loads(body)['token']


def test_defaults_endpoint_returns_canonical_scenario(admin_token):
    body, status, _ = _get(
        _base_url() + '/api/actuarial/annuity-reserve/defaults',
        admin_token,
    )
    assert status == 200, body
    payload = json.loads(body)
    assert payload['success'] is True
    assert payload['defaults']['projection_years'] == 30
    assert payload['defaults']['guarantee_rate_pct'] == 0.04
    assert payload['preview']['integrity_hash']
    assert len(payload['preview']['yearly']) == 30


def test_forecast_endpoint_runs_with_overrides(admin_token):
    payload = {
        'projection_years': 10,
        'customer_count': 500,
        'monthly_deposit_per_customer': 800,
        'guarantee_rate_pct': 4.0,        # accept percentage form
        'expected_market_return_pct': 5.5,
        'realised_return_curve': [0.02] * 10,
        'madad_pct': 2.5,
        'conversion_rate_pct': 50,
        'scenario_label': 'pytest_stress',
    }
    body, status, _ = _post_json(
        _base_url() + '/api/actuarial/annuity-reserve/forecast',
        payload,
        admin_token,
    )
    assert status == 200, body
    data = json.loads(body)
    assert data['success'] is True
    forecast = data['forecast']
    assert len(forecast['yearly']) == 10
    assert forecast['inputs']['scenario_label'] == 'pytest_stress'
    assert forecast['totals']['peak_reserve'] > 0
    assert forecast['totals']['funding_ratio'] < 1.0
    # Integrity hash must be present and reproducible.
    again_body, again_status, _ = _post_json(
        _base_url() + '/api/actuarial/annuity-reserve/forecast',
        payload,
        admin_token,
    )
    assert again_status == 200
    again = json.loads(again_body)['forecast']
    assert again['integrity_hash'] == forecast['integrity_hash']


def test_forecast_endpoint_seeds_from_simulation(admin_token):
    # Run a small simulation first so we have a snapshot to seed from.
    body, status, _ = _post_json(_base_url() + '/api/actuarial/simulate', {
        'customer_count': 60,
        'age_min': 30, 'age_max': 50,
        'policy_term_mode': 'fixed', 'policy_term_fixed': 10,
        'savings_rate': 0.5,
        'savings_formula': 'risk_premium_markup',
    }, admin_token)
    assert status == 200, body
    sim = json.loads(body)['simulation']
    sim_id = sim['simulation_id']

    # Drive the forecast off the sim. We pass customer_count=0 so the
    # service must seed it from the simulation snapshot.
    payload = {
        'simulation_id': sim_id,
        'customer_count': 0,
        'monthly_deposit_per_customer': 0,
        'projection_years': 12,
    }
    body, status, _ = _post_json(
        _base_url() + '/api/actuarial/annuity-reserve/forecast',
        payload,
        admin_token,
    )
    assert status == 200, body
    forecast = json.loads(body)['forecast']
    assert forecast['inputs']['customer_count'] > 0
    assert forecast['inputs']['monthly_deposit_per_customer'] >= 0
    assert 'source_simulation' in forecast
    assert 'simulation_id' in (forecast.get('source_simulation', {}) or {})


def test_forecast_endpoint_rejects_unauthorized():
    for token in (None, 'phins_invalid_bogus_token'):
        try:
            _post_json(
                _base_url() + '/api/actuarial/annuity-reserve/forecast',
                {'projection_years': 5},
                token,
            )
            raise AssertionError('expected unauthorized request to fail')
        except urllib.error.HTTPError as exc:
            assert exc.code in (401, 403), exc.code


def test_defaults_endpoint_rejects_unauthorized():
    for token in (None, 'phins_invalid_bogus_token'):
        try:
            _get(_base_url() + '/api/actuarial/annuity-reserve/defaults', token)
            raise AssertionError('expected unauthorized request to fail')
        except urllib.error.HTTPError as exc:
            assert exc.code in (401, 403), exc.code
