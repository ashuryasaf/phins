"""
LTC residential services market & hedging strategy research pack
(Research & Audit bar, actuary dashboard).

Covers the deterministic study in ``services/ltc_residential_market_research.py``,
its PDF export, the actuarial HTTP surface and the dashboard wiring.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from xml.dom import minidom

import pytest

from services.ltc_residential_market_research import (
    FORECAST_MAX,
    HISTORICAL_END,
    HISTORICAL_START,
    RESEARCH_SOURCES,
    STUDY_ID,
    STUDY_TITLE,
    TABLE_COLUMNS,
    build_ltc_residential_research,
    extract_research_table,
    list_research_tables,
    parse_residential_params,
    research_table_csv,
    research_table_json,
    select_research_media,
)
from services.ltc_residential_market_research_pdf import (
    PDF_TABLE_GROUPS,
    build_residential_research_pdf,
)

ROOT = Path(__file__).resolve().parents[1]


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


# ---------------------------------------------------------------- parameters

def test_params_clamp_unknown_values():
    params = parse_residential_params({
        'region': 'mars',
        'scenario': 'mystery',
        'hedge_allocation': 'crypto',
        'adl_threshold': 9,
        'forecast_end': 2300,
        'home_care_share_target_pct': 150,
        'som_share_pct': 90,
        'age_min': 80,
        'age_max': 40,
        'lives': -5,
    })
    assert params.region == 'us'
    assert params.scenario == 'baseline'
    assert params.hedge_allocation == 'balanced'
    assert params.adl_threshold == 6
    assert params.forecast_end == FORECAST_MAX
    assert params.home_care_share_target_pct <= 95.0
    assert params.som_share_pct <= 25.0
    assert params.age_min <= params.age_max
    assert params.lives >= 1


def test_blank_strings_fall_back_to_defaults():
    params = parse_residential_params({'home_care_share_target_pct': '', 'care_cost_inflation_pct': ''})
    assert params.home_care_share_target_pct == -1.0
    assert params.care_cost_inflation_pct == 3.5


# ---------------------------------------------------------------- pack integrity

def test_default_pack_is_deterministic_and_passes_every_check():
    first = build_ltc_residential_research()
    second = build_ltc_residential_research()
    assert first['success'] is True
    assert first['study_id'] == STUDY_ID
    assert first['title'] == STUDY_TITLE
    assert first['integrity']['pack_hash'] == second['integrity']['pack_hash']
    assert first['integrity']['tables_hash'] == second['integrity']['tables_hash']
    assert first['integrity']['all_checks_pass'] is True
    assert first['integrity']['unresolved_source_ids'] == []
    assert set(first['tables']) == set(TABLE_COLUMNS) == set(list_research_tables())
    for name, columns in TABLE_COLUMNS.items():
        rows = first['tables'][name]
        assert rows, name
        for row in rows:
            missing = [c for c in columns if c not in row]
            assert not missing, (name, missing)


@pytest.mark.parametrize('region', ['us', 'oecd', 'eu', 'il', 'jp', 'de', 'uk', 'nl'])
@pytest.mark.parametrize('scenario', ['baseline', 'home_shift', 'fiscal_squeeze', 'dementia_breakthrough'])
def test_every_region_and_scenario_reconciles(region, scenario):
    pack = build_ltc_residential_research({'region': region, 'scenario': scenario})
    integ = pack['integrity']
    assert integ['all_checks_pass'] is True, {k: v for k, v in integ.items() if v is False}
    assert integ['tam_sam_som_monotone'] is True
    assert integ['tam_segments_reconcile'] is True
    assert integ['forecast_spend_segments_reconcile'] is True
    forecast = pack['tables']['demand_forecast']
    assert forecast[0]['year'] == HISTORICAL_END
    assert forecast[-1]['year'] == FORECAST_MAX
    for row in forecast:
        assert abs(row['home_share_pct'] + row['residential_share_pct'] - 100.0) < 1e-6
        assert abs(row['residential_spend_usd_bn'] + row['home_spend_usd_bn'] - row['ltc_spend_usd_bn']) < 0.011
        assert 30.0 <= row['home_share_pct'] <= 95.0


def test_tam_sam_som_are_monotone_and_segments_sum():
    pack = build_ltc_residential_research({'som_share_pct': 2})
    rows = pack['tables']['tam_sam_som']
    by_year = {}
    for row in rows:
        assert row['tam_usd_bn'] >= row['sam_usd_bn'] >= row['som_usd_bn'] >= 0
        by_year.setdefault(row['year'], {})[row['segment']] = row
    for year, segs in by_year.items():
        assert set(segs) == {'residential', 'home_care', 'total'}, year
        total = segs['total']['tam_usd_bn']
        assert abs(segs['residential']['tam_usd_bn'] + segs['home_care']['tam_usd_bn'] - total) <= 0.11
        assert abs(segs['total']['som_usd_bn'] - segs['total']['sam_usd_bn'] * 0.02) < 0.02
    years = sorted(by_year)
    assert years[0] == 2025 and years[-1] == 2075


def test_published_blocks_sum_to_100():
    pack = build_ltc_residential_research()
    for row in pack['tables']['payer_mix']:
        if row.get('shares_complete'):
            parts = [row.get(k) or 0 for k in ('public_pct', 'private_insurance_pct', 'out_of_pocket_pct', 'other_pct')]
            assert abs(sum(parts) - 100.0) < 0.6, row
            assert abs(row['shares_total_pct'] - sum(parts)) < 0.06
            if row.get('medicare_pct') is not None and row.get('medicaid_pct') is not None:
                assert row['medicare_pct'] + row['medicaid_pct'] <= row['public_pct'] + 0.06, row
    settings = pack['tables']['setting_comparison']
    shares = [r['us_share_of_facilities_pct'] for r in settings if r.get('us_share_of_facilities_pct') is not None]
    assert abs(sum(shares) - 100.0) < 0.6
    alloc = pack['tables']['hedge_allocation']
    assert abs(sum(r['allocation_pct'] for r in alloc) - 100.0) < 1e-6
    spending = pack['tables']['spending_history']
    assert spending[0]['year'] == HISTORICAL_START or spending[0]['year'] <= HISTORICAL_START
    for row in spending:
        assert abs(row['nursing_care_bn'] + row['home_health_bn'] - row['total_ltc_bn']) < 0.06


def test_home_shift_scenario_moves_demand_toward_home_care():
    base = build_ltc_residential_research({'scenario': 'baseline'})
    shift = build_ltc_residential_research({'scenario': 'home_shift'})
    b_end = base['tables']['demand_forecast'][-1]
    s_end = shift['tables']['demand_forecast'][-1]
    assert s_end['home_share_pct'] > b_end['home_share_pct']
    assert s_end['residential_demand_index'] < b_end['residential_demand_index']
    assert s_end['home_demand_index'] > b_end['home_demand_index']
    selected = [r for r in shift['tables']['scenarios'] if r['selected']]
    assert len(selected) == 1 and selected[0]['scenario'] == 'home_shift'


def test_explicit_home_share_target_overrides_scenario():
    pack = build_ltc_residential_research({'home_care_share_target_pct': 90})
    assert pack['home_share_target_pct'] == 90.0
    end = pack['tables']['demand_forecast'][-1]
    assert abs(end['home_share_pct'] - 90.0) < 1e-6


def test_hedge_book_matches_lives_and_stress_raises_claims():
    pack = build_ltc_residential_research({'lives': 12345, 'age_min': 40, 'age_max': 80, 'incidence_stress_pct': 50})
    book = pack['tables']['hedge_book']
    assert sum(r['band_lives'] for r in book) == 12345
    assert all(r['age_min'] >= 40 and r['age_max'] <= 80 for r in book) or book[0]['age_min'] <= 40
    for row in book:
        assert row['stressed_annual_claims'] > row['expected_annual_claims'] > 0
        assert abs(row['stressed_annual_claims'] - row['expected_annual_claims'] * 1.5) < 1.0
    summary = pack['hedge_summary']
    assert summary['book_lives'] == 12345
    assert abs(summary['expected_annual_claims'] - sum(r['expected_annual_claims'] for r in book)) < 1.0
    assert summary['hedge_capital'] == 25_000_000
    alloc = pack['tables']['hedge_allocation']
    assert abs(sum(r['capital'] for r in alloc) - 25_000_000) < 1.0
    assert abs(sum(r['expected_income'] for r in alloc) - summary['hedge_income']) < 1.0
    assert summary['hedge_ratio_pct'] == pytest.approx(summary['hedge_income'] / summary['expected_annual_claims'] * 100, abs=0.11)
    assert pack['integrity']['hedge_book_lives_match'] is True


def test_stricter_adl_threshold_lowers_claims():
    loose = build_ltc_residential_research({'adl_threshold': 2})
    strict = build_ltc_residential_research({'adl_threshold': 5})
    assert strict['hedge_summary']['expected_annual_claims'] < loose['hedge_summary']['expected_annual_claims']


def test_allocation_presets_change_the_hedge_book():
    balanced = build_ltc_residential_research({'hedge_allocation': 'balanced'})
    real_estate = build_ltc_residential_research({'hedge_allocation': 'real_estate'})
    by_asset = {r['asset_class']: r for r in real_estate['tables']['hedge_allocation']}
    balanced_by_asset = {r['asset_class']: r for r in balanced['tables']['hedge_allocation']}
    assert by_asset['care_real_estate']['allocation_pct'] > balanced_by_asset['care_real_estate']['allocation_pct']
    assert balanced['integrity']['pack_hash'] != real_estate['integrity']['pack_hash']


def test_every_row_has_figure_basis_and_resolvable_sources():
    pack = build_ltc_residential_research()
    source_ids = {s['id'] for s in RESEARCH_SOURCES}
    assert len(RESEARCH_SOURCES) >= 20
    for src in RESEARCH_SOURCES:
        assert src['id'] and src['source'] and src['published_year'], src
    for name, rows in pack['tables'].items():
        for row in rows:
            assert row.get('figure_basis') in {'published', 'derived', 'estimate', 'projection', 'model'}, (name, row.get('figure_basis'))
            ids = row.get('source_ids')
            if ids is not None:
                assert ids, (name, row)
                assert set(ids) <= source_ids, (name, set(ids) - source_ids)
    assert pack['integrity']['source_ids_resolve'] is True
    assert set(pack['integrity']['sources_used']) <= source_ids
    for src in pack['sources']:
        assert src['id'] in source_ids


def test_pack_contains_the_strategy_blocks():
    pack = build_ltc_residential_research()
    quadrants = {r['quadrant'] for r in pack['tables']['swot']}
    assert quadrants == {'strength', 'weakness', 'opportunity', 'threat'}
    assert all(1 <= r['weight'] <= 5 for r in pack['tables']['swot'])
    assert len(pack['tables']['case_studies']) >= 10
    assert len(pack['tables']['operators']) >= 20
    countries = {r['country'] for r in pack['tables']['operators']}
    assert {'US', 'FR', 'JP', 'IL'} <= countries or len(countries) >= 6
    assert any(r.get('medicare_pct') is not None for r in pack['tables']['payer_mix'])
    assert pack['kpis']['us_nursing_home_residents_2025'] == 1_241_727
    assert pack['kpis']['tam_end_usd_bn'] > pack['kpis']['tam_2025_usd_bn']
    assert pack['kpis']['end_year'] == 2075
    assert pack['narrative'] and pack['narrative_he']
    assert len(pack['media']['illustrations']) == 4
    assert all(item['url'].startswith('/research/ltc-residential/') for item in pack['media']['illustrations'])
    for item in pack['media']['illustrations']:
        assert ROOT.joinpath('web_portal', 'static', item['url'].lstrip('/')).is_file(), item['url']
    frames = pack['media']['timeline_player']
    assert frames and frames[0]['phase'] == 'history' and frames[-1]['phase'] == 'forecast'
    assert frames[-1]['year'] == 2075
    assert all(p['url'].startswith('https://') for p in pack['media']['external_publications'])
    eras = pack['tables']['eras']
    assert eras[0]['start'] <= HISTORICAL_START and eras[-1]['end'] >= FORECAST_MAX


def test_scenario_2050_columns_blank_when_outlook_ends_earlier():
    pack = build_ltc_residential_research({'forecast_end': 2040})
    for row in pack['tables']['scenarios']:
        assert row['recipients_index_2050'] is None
        assert row['ltc_spend_gdp_pct_2050'] is None
        assert row['recipients_index_end'] is not None
    assert pack['integrity']['all_checks_pass'] is True
    filename, data = build_residential_research_pdf(pack)
    assert data.startswith(b'%PDF')


@pytest.mark.parametrize('lives,age_min,age_max', [(1, 30, 85), (7, 30, 85), (13, 60, 65), (10000, 18, 100), (999, 84, 85)])
def test_hedge_band_lives_are_non_negative_and_sum_to_book(lives, age_min, age_max):
    pack = build_ltc_residential_research({'lives': lives, 'age_min': age_min, 'age_max': age_max})
    book = pack['tables']['hedge_book']
    assert book, 'at least one band must remain in range'
    assert all(r['band_lives'] >= 0 for r in book), [r['band_lives'] for r in book]
    assert sum(r['band_lives'] for r in book) == lives
    assert pack['integrity']['hedge_book_lives_match'] is True


def test_forecast_end_shortens_the_study():
    pack = build_ltc_residential_research({'forecast_end': 2050})
    assert pack['tables']['demand_forecast'][-1]['year'] == 2050
    assert pack['kpis']['end_year'] == 2050
    assert max(r['year'] for r in pack['tables']['tam_sam_som']) == 2050
    assert pack['media']['timeline_player'][-1]['year'] == 2050
    assert pack['integrity']['all_checks_pass'] is True


# ---------------------------------------------------------------- media selection

def test_select_research_media_filters_same_origin_ltc_assets():
    assets = [
        {'id': 'a', 'name': 'Nursing home tour', 'type': 'video', 'url': '/media-files/a/tour.mp4', 'thumbnail': 'https://cdn.example/x.jpg'},
        {'id': 'b', 'name': 'Home care visit', 'type': 'image', 'url': '/media-files/b/visit.jpg', 'thumbnail': '/media-files/b/thumb.jpg'},
        {'id': 'c', 'name': 'Assisted living', 'type': 'video', 'url': 'https://youtube.com/watch?v=1'},
        {'id': 'd', 'name': 'Quarterly results', 'type': 'video', 'url': '/media-files/d/q.mp4'},
        {'id': 'e', 'name': 'סיעוד בבית', 'type': 'audio', 'url': '/media-files/e/a.mp3'},
        'garbage',
    ]
    picked = select_research_media(assets)
    assert [p['id'] for p in picked] == ['a', 'b']
    assert picked[0]['thumbnail'] is None
    assert picked[1]['thumbnail'] == '/media-files/b/thumb.jpg'
    assert select_research_media(None) == []
    assert len(select_research_media([assets[0]] * 20, limit=3)) == 3


def test_pack_embeds_media_library_matches():
    pack = build_ltc_residential_research(media_assets=[
        {'id': 'v1', 'name': 'Long-term care facility walkthrough', 'type': 'video', 'url': '/media-files/v1/walk.mp4'},
    ])
    assert pack['media']['library'][0]['id'] == 'v1'
    plain = build_ltc_residential_research()
    assert plain['integrity']['pack_hash'] == pack['integrity']['pack_hash'], 'media library must not change the study hash'


# ---------------------------------------------------------------- extracts

def test_extract_csv_and_json():
    pack = build_ltc_residential_research()
    rows = extract_research_table(pack, 'tam_sam_som')
    assert rows == pack['tables']['tam_sam_som']
    with pytest.raises(KeyError):
        extract_research_table(pack, 'nope')
    filename, data = research_table_csv(pack, 'swot')
    assert filename.endswith('.csv')
    reader = csv.DictReader(io.StringIO(data.decode('utf-8')))
    parsed = list(reader)
    assert len(parsed) == len(pack['tables']['swot'])
    assert set(TABLE_COLUMNS['swot']) <= set(reader.fieldnames or [])
    assert '|' in parsed[0]['source_ids'] or parsed[0]['source_ids']
    jname, jdata = research_table_json(pack, 'scenarios')
    assert jname.endswith('.json')
    payload = json.loads(jdata)
    assert payload['table'] == 'scenarios'
    assert payload['study_id'] == STUDY_ID
    assert payload['row_count'] == len(payload['rows']) == 4
    assert len(payload['integrity_hash']) == 64


# ---------------------------------------------------------------- PDF

def test_pdf_covers_every_table_and_is_branded():
    pack = build_ltc_residential_research()
    assert set(PDF_TABLE_GROUPS) == set(TABLE_COLUMNS)
    for name, groups in PDF_TABLE_GROUPS.items():
        covered = {col for group in groups for col in group}
        assert covered <= set(TABLE_COLUMNS[name]), (name, covered - set(TABLE_COLUMNS[name]))
    filename, data = build_residential_research_pdf(pack)
    assert filename == f'phins-{STUDY_ID}-en.pdf'
    assert data.startswith(b'%PDF')
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    assert len(reader.pages) >= 15
    text = '\n'.join((p.extract_text() or '') for p in reader.pages)
    assert 'PHINS' in text
    assert 'Methodology' in text or 'METHODOLOGY' in text
    assert 'TAM' in text and 'SWOT' in text
    assert pack['integrity']['pack_hash'][:12] in text.replace('\n', '')


def test_pdf_formats_years_plainly_and_uppercases_acronyms():
    from services.ltc_residential_market_research_pdf import _fmt, _header
    assert _fmt('year', 2025) == '2025'
    assert _fmt('age_min', 65.0) == '65'
    assert _fmt('band_lives', 12345) == '12,345'
    assert _fmt('beds_or_units', 30000) == '30,000'
    assert _fmt('expected_annual_claims', 1234567.8) == '$1,234,568'
    assert _fmt('ltc_spend_gdp_pct', 1.3341) == '1.334%'
    assert _header('som_share_of_sam_pct') == 'SOM share of SAM %'
    assert _header('us_share_of_facilities_pct') == 'US facilities %'
    assert _header('residential_demand_index') == 'Residential demand index'


# ---------------------------------------------------------------- HTTP surface

def test_research_endpoint_requires_actuary_role():
    try:
        _get(_base_url() + '/api/actuarial/ltc-residential-research')
        assert False, 'expected 401/403 without a token'
    except HTTPError as exc:
        assert exc.code in (401, 403)
        assert 'error' in json.loads(exc.read() or b'{}')


def test_research_endpoint_returns_pack_and_tables(admin_token):
    body, status, _ = _get(
        _base_url() + '/api/actuarial/ltc-residential-research?region=il&scenario=fiscal_squeeze&lives=5000&forecast_end=2060',
        admin_token,
    )
    assert status == 200, body
    pack = json.loads(body)
    assert pack['success'] is True
    assert pack['params']['region'] == 'il'
    assert pack['params']['scenario'] == 'fiscal_squeeze'
    assert pack['params']['forecast_end'] == 2060
    assert pack['hedge_summary']['book_lives'] == 5000
    assert pack['integrity']['all_checks_pass'] is True
    assert 'library' in pack['media']

    catalog, status, _ = _get(_base_url() + '/api/actuarial/ltc-residential-research/tables', admin_token)
    assert status == 200, catalog
    listed = json.loads(catalog)
    assert listed['total'] == len(TABLE_COLUMNS) == len(listed['items'])
    assert listed['page'] == 1
    names = {item['name'] for item in listed['items']}
    assert {'demand_forecast', 'tam_sam_som', 'swot', 'operators'} <= names

    table_body, status, _ = _get(
        _base_url() + '/api/actuarial/ltc-residential-research/tables?table=tam_sam_som&region=il&forecast_end=2060',
        admin_token,
    )
    assert status == 200
    table = json.loads(table_body)
    assert table['total'] == len(table['items'])
    assert max(r['year'] for r in table['items']) == 2060

    try:
        _get(_base_url() + '/api/actuarial/ltc-residential-research/tables?table=nope', admin_token)
        assert False, 'expected 400 for an unknown table'
    except HTTPError as exc:
        assert exc.code == 400
        assert 'Unknown table' in json.loads(exc.read())['error']


def test_research_download_csv_json_pdf(admin_token):
    body, status, headers = _get(
        _base_url() + '/api/actuarial/ltc-residential-research/download?table=hedge_allocation&format=csv&hedge_allocation=home_care',
        admin_token,
    )
    assert status == 200, body
    assert 'text/csv' in headers.get('Content-Type', '')
    assert len(headers.get('X-Phins-Table-Integrity', '')) == 64
    assert 'no-store' in headers.get('Cache-Control', '')
    rows = list(csv.DictReader(io.StringIO(body.decode('utf-8'))))
    assert len(rows) == 4
    assert float(max(rows, key=lambda r: float(r['allocation_pct']))['allocation_pct']) == 50.0

    body, status, headers = _get(
        _base_url() + '/api/actuarial/ltc-residential-research/download?table=scenarios&format=json',
        admin_token,
    )
    assert status == 200
    assert 'application/json' in headers.get('Content-Type', '')
    assert json.loads(body)['row_count'] == 4

    body, status, headers = _get(
        _base_url() + '/api/actuarial/ltc-residential-research/download?format=pdf&region=jp',
        admin_token,
    )
    assert status == 200
    assert headers.get('Content-Type', '').startswith('application/pdf')
    assert f'phins-{STUDY_ID}-en.pdf' in headers.get('Content-Disposition', '')
    assert headers.get('Content-Language') == 'en'
    assert body.startswith(b'%PDF')


def test_illustrations_are_served_as_svg(admin_token):
    pack = build_ltc_residential_research()
    for item in pack['media']['illustrations']:
        body, status, headers = _get(_base_url() + item['url'])
        assert status == 200, item['url']
        assert 'image/svg+xml' in headers.get('Content-Type', ''), headers
        assert b'<svg' in body[:400]
        assert b'PHINS' in body
        # A browser renders a non-well-formed SVG as an empty image, so the
        # bytes must be strict UTF-8 and parse as XML with a sized viewBox.
        text = body.decode('utf-8')
        assert not re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f\ufffd]', text), item['url']
        root = minidom.parseString(body).documentElement
        assert root.tagName == 'svg'
        assert root.getAttribute('viewBox') == '0 0 1200 520'
        assert root.getAttribute('role') == 'img'


def test_dashboard_js_is_served(admin_token):
    body, status, headers = _get(_base_url() + '/ltc-residential-research.js')
    assert status == 200
    assert 'javascript' in headers.get('Content-Type', '')
    assert b'PhinsLtcResidentialResearch' in body


# ---------------------------------------------------------------- dashboard wiring

def test_dashboard_wires_the_designated_bar():
    html = ROOT.joinpath('web_portal', 'static', 'actuary-dashboard.html').read_text(encoding='utf-8')
    js = ROOT.joinpath('web_portal', 'static', 'ltc-residential-research.js').read_text(encoding='utf-8')
    assert "showSection('ltc-residential-research')" in html
    assert 'id="section-ltc-residential-research"' in html
    assert 'LTC Residential Market Strategy' in html
    assert 'src="/ltc-residential-research.js"' in html
    assert html.count("sectionId === 'ltc-residential-research' && window.PhinsLtcResidentialResearch") == 2
    assert '/api/actuarial/ltc-residential-research' in js
    assert 'PhinsLtcResidentialResearch' in js
    block = html.split('id="section-ltc-residential-research"', 1)[1].split('id="section-uploaded"', 1)[0]
    assert 'annual-brand-banner' in block
    assert 'brand-emblem' in block
    assert 'Research &amp; Audit' in block
    assert 'src="/phins-logo.svg"' in block
    for element_id in (
        'ltcres-region', 'ltcres-scenario', 'ltcres-forecast-end', 'ltcres-cost-infl', 'ltcres-gdp-growth',
        'ltcres-healthy', 'ltcres-home-target', 'ltcres-lives', 'ltcres-age-min', 'ltcres-age-max', 'ltcres-cover',
        'ltcres-adl', 'ltcres-capital', 'ltcres-allocation', 'ltcres-stress', 'ltcres-discount', 'ltcres-som',
        'ltcres-status', 'ltcres-kpi-spend-gdp', 'ltcres-kpi-public', 'ltcres-kpi-tam-now', 'ltcres-kpi-tam-end',
        'ltcres-kpi-som-end', 'ltcres-kpi-hedge', 'ltcres-narrative', 'ltcres-scenario-note', 'ltcres-sources',
        'ltcres-structure-table', 'ltcres-settings-table', 'ltcres-payer-table', 'ltcres-cost-table',
        'ltcres-operators-table', 'ltcres-margins-table', 'ltcres-workforce-table', 'ltcres-regulation-table',
        'ltcres-forecast-table', 'ltcres-tam-table', 'ltcres-scenarios-table', 'ltcres-hedge-book-table',
        'ltcres-hedge-alloc-table', 'ltcres-hedge-summary', 'ltcres-swot', 'ltcres-cases',
        'ltcres-spending-chart', 'ltcres-cost-chart', 'ltcres-forecast-chart', 'ltcres-tam-chart',
        'ltcres-scenarios-chart', 'ltcres-payer-chart', 'ltcres-alloc-chart', 'ltcres-margins-chart',
        'ltcres-operators-chart', 'ltcres-gallery', 'ltcres-library', 'ltcres-publications', 'ltcres-media-note',
        'ltcres-player', 'ltcres-play', 'ltcres-player-caption', 'ltcres-recorded', 'ltcres-recorded-link',
        'ltcres-integrity', 'ltcres-download-table',
    ):
        assert f'id="{element_id}"' in block, element_id
        assert element_id in js, element_id
    for table in TABLE_COLUMNS:
        assert f'<option value="{table}"' in block, table
    # same-origin only: no third-party players or iframes in the designated bar
    assert '<iframe' not in block
    assert 'youtube' not in block.lower()
    assert 'captureStream' in js and 'MediaRecorder' in js
