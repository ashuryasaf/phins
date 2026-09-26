"""
LTC 3+ADL / life reinsurance research pack (Research & Audit bar).

Covers the deterministic study in ``services/ltc_life_reinsurance_research.py``
and the actuarial HTTP surface used by the actuary dashboard.
"""

from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from services.actuarial_service import get_actuarial_store
from services.ltc_life_reinsurance_research import (
    STUDY_ID,
    build_ltc_life_research,
    clear_staged_research_overlay,
    get_staged_research_overlay,
    parse_research_params,
    promote_research_overlay,
    research_table_csv,
    stage_research_overlay,
)


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


def test_params_clamp_unknown_region_and_coverage():
    params = parse_research_params({
        'region': 'mars',
        'coverage_type': 'mystery',
        'adl_threshold': 9,
        'hedge_share_pct': 140,
        'year_from': 1960,
        'year_to': 2090,
    })
    assert params.region == 'us'
    assert params.coverage_type == 'hybrid_life_ltc'
    assert params.adl_threshold == 6
    assert params.hedge_share_pct == 95.0
    assert params.year_from == 1975
    assert params.year_to == 2025


def test_default_pack_is_deterministic_and_internally_consistent():
    a = build_ltc_life_research({})
    b = build_ltc_life_research({})
    assert a['study_id'] == STUDY_ID
    assert a['integrity']['pack_hash'] == b['integrity']['pack_hash']
    assert a['integrity']['exposure_totals_match'] is True
    assert a['integrity']['forecast_mix_normalised'] is True
    assert a['integrity']['historical_span_years'] == 51
    assert len(a['tables']['historical_appetite']) == 51
    assert a['tables']['historical_appetite'][0]['year'] == 1975
    assert a['tables']['historical_appetite'][-1]['year'] == 2025
    assert a['kpis']['ltc3_premium_index_end'] > a['kpis']['life_premium_index_end']
    # Standalone LTC appetite collapsed vs life by the end of the window.
    last = a['tables']['historical_appetite'][-1]
    assert last['ltc3_appetite_pct'] < last['life_appetite_pct']
    assert last['hybrid_appetite_pct'] > last['ltc3_appetite_pct']


def test_cross_risk_links_3adl_to_shorter_life_expectancy():
    pack = build_ltc_life_research({'age_min': 40, 'age_max': 85})
    rows = pack['tables']['cross_risk_adl_mortality']
    assert rows
    for row in rows:
        assert row['remaining_le_after_3adl'] < row['healthy_life_expectancy']
        assert row['excess_mortality_multiple'] > 1.0
        assert 0.2 < row['p_death_within_5y_given_3adl'] < 1.0
        assert row['adl_threshold'] == 3
    older = [r for r in rows if r['age_min'] >= 75][0]
    younger = [r for r in rows if r['age_min'] <= 50][0]
    assert older['remaining_le_after_3adl'] < younger['remaining_le_after_3adl']
    assert older['frailty_correlation'] > younger['frailty_correlation']


def test_stricter_adl_threshold_lowers_incidence():
    two = build_ltc_life_research({'adl_threshold': 2, 'age_min': 60, 'age_max': 75})
    three = build_ltc_life_research({'adl_threshold': 3, 'age_min': 60, 'age_max': 75})
    four = build_ltc_life_research({'adl_threshold': 4, 'age_min': 60, 'age_max': 75})
    ix2 = two['tables']['age_cover_matrix'][0]['ltc3_rate_per_1000']
    ix3 = three['tables']['age_cover_matrix'][0]['ltc3_rate_per_1000']
    ix4 = four['tables']['age_cover_matrix'][0]['ltc3_rate_per_1000']
    assert ix2 > ix3 > ix4


def test_hybrid_has_more_reinsurance_appetite_than_standalone():
    hybrid = build_ltc_life_research({'coverage_type': 'hybrid_life_ltc'})
    standalone = build_ltc_life_research({'coverage_type': 'standalone_ltc'})
    assert hybrid['kpis']['ltc3_appetite_now_pct'] > standalone['kpis']['ltc3_appetite_now_pct']
    assert hybrid['recommended_hedge'] == 'quota_share_combo'
    assert standalone['recommended_hedge'] == 'facultative_xl'


def test_age_cover_and_exposure_scale_with_sliders():
    small = build_ltc_life_research({
        'life_cover': 100000, 'ltc_annual_cover': 12000, 'lives': 1000, 'hedge_share_pct': 20,
    })
    large = build_ltc_life_research({
        'life_cover': 1000000, 'ltc_annual_cover': 120000, 'lives': 10000, 'hedge_share_pct': 40,
    })
    assert small['tables']['age_cover_matrix'][0]['recommended_life_cover'] < (
        large['tables']['age_cover_matrix'][0]['recommended_life_cover']
    )
    assert small['exposure_totals']['net_ceded_exposure'] < large['exposure_totals']['net_ceded_exposure']


def test_pricing_overlay_is_upload_compatible():
    pack = build_ltc_life_research({})
    for row in pack['pricing_use']['disability_incidence_rates']:
        assert {'age_min', 'age_max', 'rate_per_1000'} <= set(row)
        assert 0 < row['rate_per_1000'] < 500
    for row in pack['pricing_use']['adl_mortality_multipliers']:
        assert 1 <= row['adl'] <= 10
        assert 0.5 <= row['multiplier'] <= 12
    filename, csv_bytes = research_table_csv(pack, 'disability_incidence_rates')
    assert filename.endswith('.csv')
    reader = csv.DictReader(io.StringIO(csv_bytes.decode('utf-8')))
    rows = list(reader)
    assert rows and {'age_min', 'age_max', 'rate_per_1000'} <= set(reader.fieldnames or [])


def test_stage_overlay_does_not_mutate_live_rates():
    store = get_actuarial_store()
    before = [dict(r) for r in store.get_current_tables()['disability_incidence_rates']]
    pack = build_ltc_life_research({'adl_threshold': 3})
    clear_staged_research_overlay()
    result = stage_research_overlay(pack, user='pytest')
    assert result['success'] is True
    assert result['promoted'] is False
    staged = get_staged_research_overlay()
    assert staged['study_id'] == STUDY_ID
    after = store.get_current_tables()['disability_incidence_rates']
    assert after == before
    clear_staged_research_overlay()


def test_promote_overlay_writes_3adl_rates_and_can_be_restored():
    store = get_actuarial_store()
    before = [dict(r) for r in store.get_current_tables()['disability_incidence_rates']]
    pack = build_ltc_life_research({'adl_threshold': 3, 'age_min': 40, 'age_max': 80})
    try:
        result = promote_research_overlay(
            pack, table_types=['disability_incidence_rates'], user='pytest',
        )
        assert result['success'] is True
        live = store.get_current_tables()['disability_incidence_rates']
        overlay = pack['pricing_use']['disability_incidence_rates']
        assert live[0]['rate_per_1000'] == overlay[0]['rate_per_1000']
    finally:
        store.update_current_tables('disability_incidence_rates', before, 'pytest')


def test_dashboard_wires_research_and_audit_bar():
    html = Path(__file__).resolve().parents[1].joinpath(
        'web_portal', 'static', 'actuary-dashboard.html'
    ).read_text(encoding='utf-8')
    js = Path(__file__).resolve().parents[1].joinpath(
        'web_portal', 'static', 'ltc-life-research.js'
    ).read_text(encoding='utf-8')
    assert 'Research &amp; Audit' in html
    assert "showSection('ltc-life-research')" in html
    assert 'id="section-ltc-life-research"' in html
    assert 'LTC 3+ADL &amp; Life Research' in html
    assert 'src="/ltc-life-research.js"' in html
    assert '/api/actuarial/ltc-life-research' in js
    assert 'PhinsLtcLifeResearch' in js
    assert 'cross_risk_adl_mortality' in html
    assert 'id="ltc-history-chart"' in html
    assert 'id="ltc-forecast-chart"' in html


def test_research_endpoint_requires_actuary_role():
    try:
        _get(_base_url() + '/api/actuarial/ltc-life-research')
        assert False, 'expected 403 without a token'
    except HTTPError as exc:
        assert exc.code in (401, 403)


def test_research_endpoint_returns_adjustable_tables(admin_token):
    body, status, _ = _get(
        _base_url()
        + '/api/actuarial/ltc-life-research?age_min=45&age_max=75&coverage_type=adb_rider&adl_threshold=3',
        admin_token,
    )
    assert status == 200, body
    pack = json.loads(body)
    assert pack['success'] is True
    assert pack['params']['age_min'] == 45
    assert pack['params']['coverage_type'] == 'adb_rider'
    assert pack['recommended_hedge'] == 'yrt_plus_adb'
    assert pack['integrity']['exposure_totals_match'] is True
    catalog, status, _ = _get(
        _base_url() + '/api/actuarial/ltc-life-research/tables',
        admin_token,
    )
    assert status == 200, catalog
    listed = json.loads(catalog)
    assert listed['total'] >= 7
    names = {item['name'] for item in listed['items']}
    assert 'age_cover_matrix' in names
    assert 'cross_risk_adl_mortality' in names
    table_body, status, _ = _get(
        _base_url() + '/api/actuarial/ltc-life-research/tables?table=age_cover_matrix&age_min=45&age_max=75',
        admin_token,
    )
    assert status == 200, table_body
    table = json.loads(table_body)
    assert table['items']
    assert table['total'] == len(table['items'])
    assert table['items'][0]['age_min'] >= 45


def test_research_download_csv(admin_token):
    body, status, headers = _get(
        _base_url()
        + '/api/actuarial/ltc-life-research/download?table=pricing_overlay&format=csv',
        admin_token,
    )
    assert status == 200, body
    assert 'text/csv' in headers.get('Content-Type', '')
    assert len(headers.get('X-Phins-Table-Integrity', '')) == 64
    reader = csv.DictReader(io.StringIO(body.decode('utf-8')))
    rows = list(reader)
    assert rows
    assert 'life_technical_rate_per_1000' in (reader.fieldnames or [])


def test_research_stage_endpoint(admin_token):
    clear_staged_research_overlay()
    body, status, _ = _post_json(
        _base_url() + '/api/actuarial/ltc-life-research/stage',
        {'coverage_type': 'hybrid_life_ltc', 'adl_threshold': 3},
        admin_token,
    )
    assert status == 200, body
    payload = json.loads(body)
    assert payload['staged'] is True
    assert payload['promoted'] is False
    assert payload['pricing_use']['disability_incidence_rates']
    clear_staged_research_overlay()
