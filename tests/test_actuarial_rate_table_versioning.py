"""
Tests for editable mortality / disability age-band rate tables.

Covers the actuary-dashboard feature that lets admins/actuaries add and
remove age-band rows (age_min / age_max / rate_per_1000) on the
"Mortality Rates" and "Disability Incidence Rates" tables:

* ``validate_age_band_rate_rows`` — structural integrity (contiguous bands,
  no gaps/overlaps, full age coverage, sane rates).
* ``ActuarialTablesStore.update_current_tables`` — every accepted change
  snapshots a NEW immutable version (old versions are archived untouched).
* Rate changes flow into the pricing kernel (simulations) and into
  new-policy premium calculations.
* HTTP surface: ``POST /api/actuarial/table-update``,
  ``POST /api/actuarial/reset-table`` and ``GET /api/actuarial/versions``.
"""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from services.actuarial_service import (
    ActuarialTablesStore,
    get_actuarial_store,
    validate_age_band_rate_rows,
)


# ----------------------------------------------------------------------------
# Validation unit tests
# ----------------------------------------------------------------------------


def _full_table(last_rate: float = 75.0):
    return [
        {'age_min': 0, 'age_max': 30, 'rate_per_1000': 0.5},
        {'age_min': 30, 'age_max': 60, 'rate_per_1000': 5.0},
        {'age_min': 60, 'age_max': 120, 'rate_per_1000': last_rate},
    ]


def test_validate_accepts_contiguous_table_and_sorts_rows():
    rows = list(reversed(_full_table()))
    normalized, errors = validate_age_band_rate_rows('mortality_rates', rows)
    assert errors == []
    assert [r['age_min'] for r in normalized] == [0, 30, 60]
    assert normalized[0] == {'age_min': 0, 'age_max': 30, 'rate_per_1000': 0.5}


@pytest.mark.parametrize('rows,expected_fragment', [
    ([], 'at least one age band row is required'),
    ([{'age_min': 10, 'age_max': 120, 'rate_per_1000': 1.0}], 'must start at age 0'),
    ([{'age_min': 0, 'age_max': 90, 'rate_per_1000': 1.0}], 'must end at age 100 or above'),
    (
        [
            {'age_min': 0, 'age_max': 30, 'rate_per_1000': 1.0},
            {'age_min': 40, 'age_max': 120, 'rate_per_1000': 2.0},
        ],
        'gap between bands',
    ),
    (
        [
            {'age_min': 0, 'age_max': 40, 'rate_per_1000': 1.0},
            {'age_min': 30, 'age_max': 120, 'rate_per_1000': 2.0},
        ],
        'overlap',
    ),
    ([{'age_min': 50, 'age_max': 50, 'rate_per_1000': 1.0}], 'must be less than'),
    ([{'age_min': 0, 'age_max': 120, 'rate_per_1000': -1.0}], 'rate_per_1000 must be between'),
    ([{'age_min': 0, 'age_max': 120, 'rate_per_1000': 750.0}], 'rate_per_1000 must be between'),
    ([{'age_min': 0, 'age_max': 200, 'rate_per_1000': 1.0}], 'ages must be between'),
    ([{'age_min': 0, 'age_max': 120}], 'rate_per_1000 is required'),
    ([{'age_min': 'abc', 'age_max': 120, 'rate_per_1000': 1.0}], 'whole numbers'),
])
def test_validate_rejects_bad_tables(rows, expected_fragment):
    normalized, errors = validate_age_band_rate_rows('mortality_rates', rows)
    assert normalized == []
    assert any(expected_fragment.lower() in err.lower() for err in errors), errors


# ----------------------------------------------------------------------------
# Store-level versioning tests (fresh store, no global state)
# ----------------------------------------------------------------------------


def test_update_creates_new_version_and_archives_old():
    store = ActuarialTablesStore()
    assert store.current_version == 'V2.0'
    old_rows = store.get_current_tables()['mortality_rates']

    # "Add a row": split the first default band 0-30 into 0-18 / 18-30
    new_rows = [
        {'age_min': 0, 'age_max': 18, 'rate_per_1000': 0.3},
        {'age_min': 18, 'age_max': 30, 'rate_per_1000': 0.6},
    ] + [dict(r) for r in old_rows[1:]]

    result = store.update_current_tables('mortality_rates', new_rows, 'pytest-actuary')
    assert result['success'] is True
    assert result['version'] == 'V2.1'
    assert store.current_version == 'V2.1'

    # Old version is archived and keeps its original data (immutability)
    assert store.versions['V2.0']['status'] == 'archived'
    assert len(store.versions['V2.0']['mortality_rates']) == len(old_rows)
    assert store.versions['V2.0']['mortality_rates'][0]['age_max'] == 30

    # New version is active, carries a change summary, and drives lookups
    assert store.versions['V2.1']['status'] == 'active'
    assert 'mortality_rates' in store.versions['V2.1']['change_summary']
    assert len(store.get_current_tables()['mortality_rates']) == len(old_rows) + 1
    assert abs(store.get_mortality_rate(10) - 0.3 / 1000.0) < 1e-12
    assert abs(store.get_mortality_rate(20) - 0.6 / 1000.0) < 1e-12


def test_remove_row_creates_new_version():
    store = ActuarialTablesStore()
    result = store.update_current_tables(
        'disability_incidence_rates', _full_table(80.0), 'pytest-actuary')
    assert result['success'] is True
    assert result['version'] == 'V2.1'
    assert len(store.get_current_tables()['disability_incidence_rates']) == 3
    assert abs(store.get_disability_rate(45) - 5.0 / 1000.0) < 1e-12


def test_invalid_update_leaves_store_untouched():
    store = ActuarialTablesStore()
    before_rows = store.get_current_tables()['mortality_rates']
    bad_rows = [
        {'age_min': 0, 'age_max': 30, 'rate_per_1000': 1.0},
        {'age_min': 50, 'age_max': 120, 'rate_per_1000': 2.0},  # gap 30-50
    ]
    result = store.update_current_tables('mortality_rates', bad_rows, 'pytest-actuary')
    assert result['success'] is False
    assert 'gap' in result['error'].lower()
    assert store.current_version == 'V2.0'
    assert store.get_current_tables()['mortality_rates'] == before_rows
    assert list(store.versions.keys()) == ['V2.0']


def test_reset_table_creates_new_version():
    store = ActuarialTablesStore()
    store.update_current_tables('mortality_rates', _full_table(), 'pytest-actuary')
    result = store.reset_tables_to_default('mortality_rates', 'pytest-actuary')
    assert result['success'] is True
    assert result['version'] == 'V2.2'
    assert store.current_version == 'V2.2'
    assert store.get_current_tables()['mortality_rates'] == \
        store.get_default_tables()['mortality_rates']
    assert 'reset' in store.versions['V2.2']['change_summary']


def test_version_snapshots_are_deep_copies():
    """Editing one table in a later version must not leak into archived ones."""
    store = ActuarialTablesStore()
    store.update_current_tables('mortality_rates', _full_table(), 'pytest-actuary')
    v21_disability = store.versions['V2.1']['disability_incidence_rates']

    new_disability = _full_table(80.0)
    store.update_current_tables('disability_incidence_rates', new_disability, 'pytest-actuary')
    assert store.current_version == 'V2.2'

    # V2.1 disability rows must be untouched by the V2.2 edit
    assert store.versions['V2.1']['disability_incidence_rates'] == v21_disability
    assert store.versions['V2.1']['disability_incidence_rates'] != new_disability


def test_version_numbers_keep_incrementing():
    store = ActuarialTablesStore()
    for i in range(11):
        rows = _full_table(50.0 + i)
        result = store.update_current_tables('mortality_rates', rows, 'pytest-actuary')
        assert result['success'] is True
    assert store.current_version == 'V3.1'
    assert len(store.versions) == 12


# ----------------------------------------------------------------------------
# Pricing impact: simulations + new-policy premiums must react to rate edits
# ----------------------------------------------------------------------------


@pytest.fixture
def restored_global_store():
    """Yield the global store and restore both rate tables afterwards."""
    store = get_actuarial_store()
    try:
        yield store
    finally:
        store.reset_tables_to_default('mortality_rates', 'pytest-restore')
        store.reset_tables_to_default('disability_incidence_rates', 'pytest-restore')


def _tripled_rates(rows):
    return [
        {'age_min': r['age_min'], 'age_max': r['age_max'],
         'rate_per_1000': min(float(r['rate_per_1000']) * 3.0, 500.0)}
        for r in rows
    ]


def test_rate_change_flows_into_pricing_kernel_tables(restored_global_store):
    """table_set_from_store (used by the portfolio simulator) must reflect edits."""
    from services.pricing_kernel import table_set_from_store

    store = restored_global_store
    store.reset_tables_to_default('mortality_rates', 'pytest')
    baseline_qx = table_set_from_store(store).mortality_qx(35)
    assert baseline_qx > 0

    defaults = store.get_default_tables()['mortality_rates']
    result = store.update_current_tables('mortality_rates', _tripled_rates(defaults), 'pytest')
    assert result['success'] is True

    updated_tables = table_set_from_store(store)
    assert updated_tables.version == store.current_version
    assert updated_tables.mortality_qx(35) == pytest.approx(baseline_qx * 3.0)


def test_rate_change_affects_new_policy_premium(restored_global_store):
    """calculate_age_adjusted_premium (new policies / quotes) must react."""
    from web_portal.server import calculate_age_adjusted_premium

    store = restored_global_store
    store.reset_tables_to_default('mortality_rates', 'pytest')
    store.reset_tables_to_default('disability_incidence_rates', 'pytest')

    kwargs = dict(base_premium=1000, age=40, policy_type='life', adl_level=5,
                  coverage_amount=300_000, use_actuarial=True, term_years=20)
    baseline = calculate_age_adjusted_premium(**kwargs)
    assert baseline['eligible']

    defaults = store.get_default_tables()
    store.update_current_tables(
        'mortality_rates', _tripled_rates(defaults['mortality_rates']), 'pytest')
    store.update_current_tables(
        'disability_incidence_rates',
        _tripled_rates(defaults['disability_incidence_rates']), 'pytest')

    repriced = calculate_age_adjusted_premium(**kwargs)
    assert repriced['eligible']
    assert repriced['annual_premium'] > baseline['annual_premium']
    assert repriced['mortality_rate'] == pytest.approx(baseline['mortality_rate'] * 3.0)


def test_rate_change_affects_financial_reporting_premium(restored_global_store):
    """The FRS premium calculator must price from the central store tables."""
    from services.financial_reporting_service import FinancialReportingService

    store = restored_global_store
    store.reset_tables_to_default('mortality_rates', 'pytest')
    store.reset_tables_to_default('disability_incidence_rates', 'pytest')

    svc = FinancialReportingService(policies={}, claims={}, billing={},
                                    customers={}, underwriting={})
    baseline = svc.calculate_premium(coverage=500_000, age=45, adl_level=5,
                                     savings_pct=0.50, term_years=15)
    assert baseline['eligible']

    defaults = store.get_default_tables()
    store.update_current_tables(
        'mortality_rates', _tripled_rates(defaults['mortality_rates']), 'pytest')
    store.update_current_tables(
        'disability_incidence_rates',
        _tripled_rates(defaults['disability_incidence_rates']), 'pytest')

    repriced = svc.calculate_premium(coverage=500_000, age=45, adl_level=5,
                                     savings_pct=0.50, term_years=15)
    assert repriced['eligible']
    assert repriced['annual_premium'] > baseline['annual_premium']


def test_rate_change_affects_portfolio_simulation(restored_global_store):
    """The portfolio simulator must price with the updated tables version."""
    import random

    from services.actuarial_service import PortfolioSimulator, SimulationParams

    store = restored_global_store
    store.reset_tables_to_default('mortality_rates', 'pytest')
    store.reset_tables_to_default('disability_incidence_rates', 'pytest')

    params = SimulationParams(
        customer_count=150, age_min=25, age_max=55,
        coverage_min=100_000, coverage_max=400_000, coverage_median=200_000,
        policy_term_mode='fixed', policy_term_fixed=10,
    )

    random.seed(42)
    baseline = PortfolioSimulator(store).generate_portfolio(params)

    defaults = store.get_default_tables()
    store.update_current_tables(
        'mortality_rates', _tripled_rates(defaults['mortality_rates']), 'pytest')
    store.update_current_tables(
        'disability_incidence_rates',
        _tripled_rates(defaults['disability_incidence_rates']), 'pytest')

    random.seed(42)
    repriced = PortfolioSimulator(store).generate_portfolio(params)

    assert repriced['tables_version'] == store.current_version
    assert repriced['tables_version'] != baseline['tables_version']
    assert (repriced['portfolio_summary']['total_annual_premium']
            > baseline['portfolio_summary']['total_annual_premium'])


# ----------------------------------------------------------------------------
# HTTP integration tests against the embedded server (root conftest)
# ----------------------------------------------------------------------------


def _base_url() -> str:
    return os.environ.get('TEST_BASE_URL') or 'http://127.0.0.1:8000'


def _post_json(url: str, payload: dict, token: str | None = None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, data=json.dumps(payload).encode('utf-8'),
                  headers=headers, method='POST')
    with urlopen(req) as resp:
        return resp.read(), resp.status


def _get(url: str, token: str | None = None):
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return resp.read(), resp.status


@pytest.fixture
def admin_token() -> str:
    body, status = _post_json(_base_url() + '/api/login', {
        'username': 'admin', 'password': 'admin123',
    })
    assert status == 200, body
    return json.loads(body)['token']


def test_table_update_endpoint_add_remove_rows_and_versions(admin_token):
    base = _base_url()
    try:
        # Current tables + version
        body, status = _get(base + '/api/actuarial/tables', admin_token)
        assert status == 200
        payload = json.loads(body)
        start_version = payload['current_version']
        rows = payload['tables']['mortality_rates']

        # Add a row: split the first band in two at its midpoint
        first = rows[0]
        mid = (int(first['age_min']) + int(first['age_max'])) // 2
        edited = [
            {'age_min': first['age_min'], 'age_max': mid,
             'rate_per_1000': first['rate_per_1000']},
            {'age_min': mid, 'age_max': first['age_max'],
             'rate_per_1000': float(first['rate_per_1000']) + 0.1},
        ] + [dict(r) for r in rows[1:]]

        body, status = _post_json(base + '/api/actuarial/table-update', {
            'table_type': 'mortality_rates', 'data': edited,
        }, admin_token)
        assert status == 200, body
        result = json.loads(body)
        assert result['success'] is True
        added_version = result['version']
        assert added_version and added_version != start_version
        assert len(result['data']) == len(rows) + 1

        # Remove the row again (merge back) -> another new version
        body, status = _post_json(base + '/api/actuarial/table-update', {
            'table_type': 'mortality_rates', 'data': rows,
        }, admin_token)
        assert status == 200, body
        removed_version = json.loads(body)['version']
        assert removed_version not in (start_version, added_version)

        # Version history lists both edits with change summaries
        body, status = _get(base + '/api/actuarial/versions', admin_token)
        assert status == 200
        versions = json.loads(body)
        assert versions['current_version'] == removed_version
        by_id = {v['version']: v for v in versions['versions']}
        assert by_id[added_version]['status'] == 'archived'
        assert 'mortality_rates' in (by_id[added_version]['change_summary'] or '')
        assert by_id[removed_version]['is_current'] is True
    finally:
        _post_json(base + '/api/actuarial/reset-table',
                   {'table_type': 'mortality_rates'}, admin_token)


def test_table_update_endpoint_rejects_broken_tables(admin_token):
    base = _base_url()
    body, status = _get(base + '/api/actuarial/tables', admin_token)
    assert status == 200
    before = json.loads(body)
    start_version = before['current_version']

    bad = [
        {'age_min': 0, 'age_max': 30, 'rate_per_1000': 1.0},
        {'age_min': 45, 'age_max': 120, 'rate_per_1000': 2.0},  # gap 30-45
    ]
    with pytest.raises(HTTPError) as excinfo:
        _post_json(base + '/api/actuarial/table-update', {
            'table_type': 'disability_incidence_rates', 'data': bad,
        }, admin_token)
    assert excinfo.value.code == 400
    error_payload = json.loads(excinfo.value.read())
    assert 'gap' in error_payload['error'].lower()

    # No version was created and the table is unchanged
    body, status = _get(base + '/api/actuarial/tables', admin_token)
    after = json.loads(body)
    assert after['current_version'] == start_version
    assert after['tables']['disability_incidence_rates'] == \
        before['tables']['disability_incidence_rates']


def test_reset_table_endpoint_returns_new_version(admin_token):
    base = _base_url()
    body, status = _post_json(base + '/api/actuarial/reset-table',
                              {'table_type': 'mortality_rates'}, admin_token)
    assert status == 200, body
    result = json.loads(body)
    assert result['success'] is True
    assert result['version']
    assert result['data'] == get_actuarial_store().get_default_tables()['mortality_rates']
