"""
Tests for the unified Life & Disability Tables Registry exposed by the
actuary dashboard's "Tables Bar".

Covers the service-level helpers in ``services.actuarial_service`` and the
HTTP surface in ``web_portal/server.py``:

* ``build_rate_tables_registry`` — assembles global, cohort, and uploaded
  entries with deterministic integrity hashes.
* ``get_active_rate_table_rows`` — looks up rows by scope/table_type/cohort
  for the download endpoint.
* ``GET /api/actuarial/tables/registry`` — returns the unified list.
* ``GET /api/actuarial/tables/registry/download`` — streams CSV/JSON.

These tests reuse the embedded server started by the repository-level
``conftest.py`` (port from ``TEST_PORT``) so we can exercise the full HTTP
contract without spinning up a second listener.
"""

from __future__ import annotations

import csv
import io
import json
import os
from urllib.request import Request, urlopen
from urllib.parse import urlencode

import pytest

from services.actuarial_service import (
    RISK_REFERENCE_MAP_AGE_MAX,
    RISK_REFERENCE_MAP_AGE_MIN,
    SUPPORTED_RATE_BANDS,
    build_cohort_label,
    build_rate_tables_registry,
    build_risk_reference,
    get_active_rate_table_rows,
    get_actuarial_store,
    list_cohort_rate_tables,
    normalize_uploaded_rate_table,
    register_cohort_rate_table,
    remove_cohort_rate_table,
)
from services.adl3_disabled_life_expectancy import (
    CHART_AGE_MAX,
    CHART_AGE_MIN,
    normalize_adl3_expectancy_rows,
)


# ----------------------------------------------------------------------------
# Service-layer unit tests
# ----------------------------------------------------------------------------


def test_build_cohort_label_handles_known_and_unknown_dimensions():
    assert build_cohort_label('ethnicity', 'caucasian', 'mortality_rates') == (
        'Death (mortality) — Caucasian (ethnicity)'
    )
    assert build_cohort_label('gender', 'male', 'disability_incidence_rates') == (
        'Disability (permanent ADL) — Male (gender)'
    )
    # Unknown dimension/value falls back to title-cased values.
    assert build_cohort_label('region', 'baltic', 'mortality_rates') == (
        'Death (mortality) — Baltic (region)'
    )


def test_registry_includes_global_entries_for_both_rate_bands():
    entries = build_rate_tables_registry()
    by_id = {e['id']: e for e in entries}
    assert 'global:mortality_rates' in by_id
    assert 'global:disability_incidence_rates' in by_id
    assert 'global:adl3_disabled_life_expectancy' in by_id
    expectancy = by_id['global:adl3_disabled_life_expectancy']
    assert expectancy['used_in_pricing'] is False
    assert expectancy['assumption_only'] is True
    assert expectancy['row_count'] == 110
    assert 'rows' not in expectancy
    for entry in entries:
        if entry['id'] in ('global:mortality_rates', 'global:disability_incidence_rates'):
            assert entry['used_in_pricing'] is True
        if entry['scope'] == 'global':
            assert entry['integrity_hash'] and len(entry['integrity_hash']) == 64
            assert entry['row_count'] > 0
    looked = get_active_rate_table_rows('global', 'adl3_disabled_life_expectancy')
    assert looked['success'] is True
    assert len(looked['rows']) == 110
    assert looked['rows'][0]['age'] == 1
    assert looked['rows'][34]['average_years'] == 5.248615017
    assert looked['rows'][34]['female_excess_pct'] == 12
    assert 'adl3_disabled_life_expectancy' not in SUPPORTED_RATE_BANDS


def test_registry_surfaces_cohort_overrides_with_friendly_labels():
    """Cohort overrides like 'female Caucasian' must appear as their own
    registry entries, tagged as actively used in pricing.
    """
    rows = [
        {'age_min': 30, 'age_max': 40, 'rate_per_1000': 1.1},
        {'age_min': 40, 'age_max': 50, 'rate_per_1000': 2.4},
    ]
    norm = normalize_uploaded_rate_table('mortality_rates', rows)
    register_cohort_rate_table(
        cohort_dim='ethnicity', cohort_value='caucasian',
        table_type='mortality_rates', normalized=norm['normalized'],
        user='pytest', source_table_id='AT-TEST-1',
        source_name='Caucasian Female Death Table',
    )
    register_cohort_rate_table(
        cohort_dim='ethnicity', cohort_value='asian',
        table_type='disability_incidence_rates', normalized=norm['normalized'],
        user='pytest', source_table_id='AT-TEST-2',
        source_name='Asian Men Disability Table',
    )
    try:
        registry = build_rate_tables_registry()
        labels = {e['id']: e for e in registry}
        cauc_id = 'cohort:ethnicity:caucasian:mortality_rates'
        asian_id = 'cohort:ethnicity:asian:disability_incidence_rates'
        assert cauc_id in labels
        assert asian_id in labels
        assert labels[cauc_id]['used_in_pricing'] is True
        assert 'Caucasian' in labels[cauc_id]['label']
        assert labels[asian_id]['source_name'] == 'Asian Men Disability Table'
        # Integrity hashes must be stable: two consecutive calls return the
        # same SHA-256 for the same in-memory rate band.
        again = build_rate_tables_registry()
        again_labels = {e['id']: e for e in again}
        assert again_labels[cauc_id]['integrity_hash'] == labels[cauc_id]['integrity_hash']
    finally:
        remove_cohort_rate_table('ethnicity', 'caucasian', 'mortality_rates', 'pytest')
        remove_cohort_rate_table('ethnicity', 'asian', 'disability_incidence_rates', 'pytest')


def test_registry_uploaded_entries_are_not_flagged_as_active():
    uploaded = [
        {
            'id': 'AT-UP-1',
            'name': 'Uploaded Mortality (test)',
            'table_type': 'mortality_rates',
            'version': '2026A',
            'effective_date': '2026-01-01',
            'created_by': 'pytest',
            'rows': [{'age_min': 30, 'age_max': 40, 'rate_per_1000': 1.0}],
        },
        {
            'id': 'AT-UP-2',
            'name': 'Pricing CSV (should be skipped)',
            'table_type': 'pricing',
            'rows': [],
        },
    ]
    registry = build_rate_tables_registry(uploaded)
    uploaded_entries = [e for e in registry if e['scope'] == 'uploaded']
    assert len(uploaded_entries) == 1, uploaded_entries
    entry = uploaded_entries[0]
    assert entry['used_in_pricing'] is False
    assert entry['table_type'] in SUPPORTED_RATE_BANDS
    assert entry['row_count'] == 1
    assert entry['integrity_hash']


def test_get_active_rate_table_rows_returns_global_and_cohort_payloads():
    global_result = get_active_rate_table_rows(scope='global', table_type='mortality_rates')
    assert global_result['success'] is True
    assert isinstance(global_result['rows'], list) and global_result['rows']
    assert global_result['integrity_hash']
    # Cohort lookup before any registration must report not-found.
    missing = get_active_rate_table_rows(
        scope='cohort', table_type='mortality_rates',
        cohort_dim='gender', cohort_value='nonexistent',
    )
    assert missing['success'] is False

    norm = normalize_uploaded_rate_table('disability_incidence_rates', [
        {'age_min': 30, 'age_max': 40, 'rate_per_1000': 5.5},
    ])
    register_cohort_rate_table(
        cohort_dim='gender', cohort_value='female',
        table_type='disability_incidence_rates', normalized=norm['normalized'],
        user='pytest',
    )
    try:
        cohort = get_active_rate_table_rows(
            scope='cohort', table_type='disability_incidence_rates',
            cohort_dim='gender', cohort_value='female',
        )
        assert cohort['success'] is True
        assert cohort['rows'][0]['rate_per_1000'] == 5.5
        assert 'phins-cohort-gender-female' in cohort['filename_stem']
    finally:
        remove_cohort_rate_table('gender', 'female', 'disability_incidence_rates', 'pytest')


def _expectancy_upload_rows(average_at_35=None):
    """Published rows with the CSV aliases a replacement file would use."""
    looked = get_active_rate_table_rows('global', 'adl3_disabled_life_expectancy')
    rows = []
    for row in looked['rows']:
        item = {
            'age': row['age'],
            'man': row['male_years'],
            'woman': row['female_years'],
            'average': row['average_years'],
            '%+': row['female_excess_pct'],
        }
        if average_at_35 is not None and int(row['age']) == 35:
            item['average'] = average_at_35
        rows.append(item)
    return rows


def test_adl3_chart_window_matches_the_risk_reference_map():
    assert CHART_AGE_MIN == 20 == RISK_REFERENCE_MAP_AGE_MIN
    assert CHART_AGE_MAX == 85 == RISK_REFERENCE_MAP_AGE_MAX


def test_normalize_adl3_expectancy_keeps_the_published_average():
    rows = _expectancy_upload_rows()
    rows.insert(0, {'age': '', 'man': '', 'woman': '', 'average': '', '%+': ''})
    parsed = normalize_adl3_expectancy_rows(rows)
    assert parsed['valid'] is True
    assert parsed['rows_skipped'] == 1
    by_age = {row['age']: row for row in parsed['normalized']}
    age35 = by_age[35]
    assert age35['average_years'] == 5.248615017
    assert age35['average_years'] != (age35['male_years'] + age35['female_years']) / 2
    assert age35['female_excess_pct'] == 12
    assert by_age[5]['female_excess_pct'] == 23
    assert parsed['normalized'][0]['age'] == 1
    assert by_age[110]['age'] == 110

    percent = normalize_adl3_expectancy_rows([
        {**row, '%+': '12%' if row['age'] == 35 else row['%+']}
        for row in rows
        if row.get('age') != ''
    ])
    assert percent['valid'] is True
    assert {row['age']: row for row in percent['normalized']}[35]['female_excess_pct'] == 12

    fraction = normalize_adl3_expectancy_rows([
        {**row, '%+': 0.12 if row['age'] == 35 else row['%+']}
        for row in rows
        if row.get('age') != ''
    ])
    assert fraction['valid'] is False
    assert fraction['reason'] == 'percent_not_integer'

    duplicated = [dict(row) for row in rows if row.get('age') != '']
    duplicated.append(dict(duplicated[0]))
    duplicate = normalize_adl3_expectancy_rows(duplicated)
    assert duplicate['valid'] is False
    assert duplicate['reason'] == 'duplicate_age'

    brackets = normalize_adl3_expectancy_rows([
        {'age_min': 30, 'age_max': 40, 'rate_per_1000': 1.2},
    ])
    assert brackets['valid'] is False
    assert brackets['reason'] == 'no_valid_rows'

    window = [row for row in rows if row.get('age') != '' and int(row['age']) != 40]
    incomplete = normalize_adl3_expectancy_rows(window)
    assert incomplete['valid'] is False
    assert incomplete['reason'] == 'chart_window_incomplete'


def test_replace_adl3_expectancy_leaves_pricing_unchanged():
    store = get_actuarial_store()
    tables = store.get_current_tables()
    saved = [dict(row) for row in tables['adl3_disabled_life_expectancy']]
    mortality = [dict(row) for row in tables['mortality_rates']]
    disability = [dict(row) for row in tables['disability_incidence_rates']]
    multipliers = [dict(row) for row in tables['adl_mortality_multipliers']]
    version_before = store.current_version
    before = {
        row['age']: row
        for row in build_risk_reference(start_age=35, projection_years=1)['age_map']['rows']
    }
    rejected = store.update_current_tables(
        'adl3_disabled_life_expectancy',
        [{'age_min': 0, 'age_max': 30, 'rate_per_1000': 1.2}],
        'pytest',
    )
    assert rejected['success'] is False
    assert store.current_version == version_before
    cohort = register_cohort_rate_table(
        'gender', 'female', 'adl3_disabled_life_expectancy',
        [{'age': 35, 'male_years': 1, 'female_years': 1, 'average_years': 1}],
        'pytest',
    )
    assert cohort['success'] is False
    try:
        replacement = _expectancy_upload_rows(average_at_35=6.5)
        result = store.update_current_tables('adl3_disabled_life_expectancy', replacement, 'pytest')
        assert result['success'] is True
        current = store.get_current_tables()
        assert current['mortality_rates'] == mortality
        assert current['disability_incidence_rates'] == disability
        assert current['adl_mortality_multipliers'] == multipliers
        after = {
            row['age']: row
            for row in build_risk_reference(start_age=35, projection_years=1)['age_map']['rows']
        }
        assert after[35]['disability_curtate_expectancy'] == 6.5
        assert after[35]['annual_premium'] == before[35]['annual_premium']
        assert after[35]['mortality_qx'] == 0.00133
        assert after[35]['expected_loss'] == before[35]['expected_loss']
        assert after[35]['pricing_basis_disabled_curtate'] == before[35]['pricing_basis_disabled_curtate']
    finally:
        restored = store.update_current_tables('adl3_disabled_life_expectancy', saved, 'pytest')
        assert restored['success'] is True


# ----------------------------------------------------------------------------
# HTTP integration tests against the embedded server (root conftest)
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


def test_registry_endpoint_returns_global_entries(admin_token):
    body, status, _ = _get(_base_url() + '/api/actuarial/tables/registry', admin_token)
    assert status == 200, body
    payload = json.loads(body)
    assert payload['success'] is True
    summary = payload['summary']
    assert summary['global'] == 3
    assert summary['used_in_pricing'] >= 2
    by_id = {e['id']: e for e in payload['items']}
    assert 'global:mortality_rates' in by_id
    assert 'global:disability_incidence_rates' in by_id
    assert 'global:adl3_disabled_life_expectancy' in by_id
    assert by_id['global:adl3_disabled_life_expectancy']['used_in_pricing'] is False
    # Manifest hash must be a 64-char hex string covering the whole registry.
    manifest = payload['integrity']['manifest_hash']
    assert isinstance(manifest, str) and len(manifest) == 64


def test_registry_download_csv_global_table(admin_token):
    qs = urlencode({
        'scope': 'global',
        'table_type': 'mortality_rates',
        'format': 'csv',
    })
    body, status, headers = _get(
        _base_url() + f'/api/actuarial/tables/registry/download?{qs}',
        admin_token,
    )
    assert status == 200, body
    content_type = headers.get('Content-Type', '')
    assert 'text/csv' in content_type
    integrity = headers.get('X-Phins-Table-Integrity', '')
    assert integrity and len(integrity) == 64
    text = body.decode('utf-8')
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    assert rows, 'expected at least one rate-band row'
    # The CSV must include the canonical mortality columns.
    assert {'age_min', 'age_max', 'rate_per_1000'}.issubset(set(reader.fieldnames or []))


def test_registry_records_cohort_override_after_promotion(admin_token):
    """Promoting an uploaded table as a cohort override must surface it as a
    registry entry tagged as 'In use' for pricing/simulation, with a
    deterministic integrity hash and a working JSON download path.
    """
    upload_payload = {
        'id': 'AT-REG-INT-1',
        'name': 'Female Caucasian Death Table',
        'table_type': 'mortality_rates',
        'version': 'PYTEST',
        'effective_date': '2026-05-15',
        'created_by': 'pytest',
        'classification': 'restricted',
        'created_date': '2026-05-15T00:00:00',
    }
    # Encode payload directly into the in-memory ACTUARIAL_TABLES so the
    # test does not depend on multipart/form-data parsing in this suite.
    import web_portal.server as portal
    from security.vault import encrypt_json
    rows = [
        {'age_min': 30, 'age_max': 40, 'rate_per_1000': 0.9},
        {'age_min': 40, 'age_max': 50, 'rate_per_1000': 2.1},
    ]
    blob = encrypt_json(rows).to_json() if encrypt_json else json.dumps(
        {'scheme': 'plain', 'ciphertext': json.dumps(rows)}
    )
    portal.ACTUARIAL_TABLES[upload_payload['id']] = {
        **upload_payload,
        'payload': blob,
    }

    try:
        # Promote as a cohort override (preserves the global rate band).
        body, status, _ = _post_json(
            _base_url() + '/api/actuarial/uploaded-tables/use',
            {
                'table_id': upload_payload['id'],
                'target_table_type': 'mortality_rates',
                'cohort_dim': 'ethnicity',
                'cohort_value': 'caucasian',
            },
            admin_token,
        )
        assert status == 200, body
        promote = json.loads(body)
        assert promote['mode'] == 'cohort_override'

        body, status, _ = _get(_base_url() + '/api/actuarial/tables/registry', admin_token)
        assert status == 200, body
        items = json.loads(body)['items']
        cauc = next((e for e in items if e['id'] == 'cohort:ethnicity:caucasian:mortality_rates'), None)
        assert cauc is not None, items
        assert cauc['used_in_pricing'] is True
        assert cauc['source_table_id'] == upload_payload['id']

        qs = urlencode({
            'scope': 'cohort',
            'table_type': 'mortality_rates',
            'cohort_dim': 'ethnicity',
            'cohort_value': 'caucasian',
            'format': 'json',
        })
        body, status, headers = _get(
            _base_url() + f'/api/actuarial/tables/registry/download?{qs}',
            admin_token,
        )
        assert status == 200, body
        download = json.loads(body)
        assert download['scope'] == 'cohort'
        assert download['row_count'] == len(rows)
        assert headers.get('X-Phins-Table-Integrity') == cauc['integrity_hash']
    finally:
        portal.ACTUARIAL_TABLES.pop(upload_payload['id'], None)
        # Best-effort cleanup of the cohort override.
        for tt in ('mortality_rates', 'disability_incidence_rates'):
            try:
                remove_cohort_rate_table('ethnicity', 'caucasian', tt, 'pytest')
            except Exception:
                pass


def test_registry_download_rejects_unsupported_scope(admin_token):
    import urllib.error
    try:
        _get(
            _base_url() + '/api/actuarial/tables/registry/download?scope=bogus&table_type=mortality_rates',
            admin_token,
        )
        assert False, 'expected HTTPError for invalid scope'
    except urllib.error.HTTPError as exc:
        assert exc.code == 400


def test_use_endpoint_replaces_adl3_expectancy_without_repricing(admin_token):
    import urllib.error
    import web_portal.server as portal
    from security.vault import encrypt_json

    store = get_actuarial_store()
    saved = [dict(row) for row in store.get_current_tables()['adl3_disabled_life_expectancy']]
    upload_id = 'AT-ADL3-REPLACE-1'
    rows = _expectancy_upload_rows(average_at_35=6.25)
    blob = encrypt_json(rows).to_json() if encrypt_json else json.dumps(
        {'scheme': 'plain', 'ciphertext': json.dumps(rows)}
    )
    portal.ACTUARIAL_TABLES[upload_id] = {
        'id': upload_id,
        'name': 'ADL 3 expectancy replacement',
        'table_type': 'adl3_disabled_life_expectancy',
        'payload': blob,
    }
    try:
        try:
            _post_json(
                _base_url() + '/api/actuarial/uploaded-tables/use',
                {
                    'table_id': upload_id,
                    'target_table_type': 'adl3_disabled_life_expectancy',
                    'cohort_dim': 'gender',
                    'cohort_value': 'female',
                },
                admin_token,
            )
            raise AssertionError('cohort replace should be refused')
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
            payload = json.loads(exc.read().decode('utf-8'))
            assert payload['error'] == 'The ADL 3 expectancy table is global. Leave the cohort blank.'

        body, status, _ = _post_json(
            _base_url() + '/api/actuarial/uploaded-tables/use',
            {
                'table_id': upload_id,
                'target_table_type': 'adl3_disabled_life_expectancy',
            },
            admin_token,
        )
        assert status == 200, body
        promoted = json.loads(body)
        assert promoted['mode'] == 'assumption_replace'
        assert promoted['rows_applied'] == 110
        after = {
            row['age']: row
            for row in build_risk_reference(start_age=35, projection_years=1)['age_map']['rows']
        }
        assert after[35]['disability_curtate_expectancy'] == 6.25
        assert after[35]['annual_premium'] == 2070.0
        assert after[35]['mortality_qx'] == 0.00133
    finally:
        portal.ACTUARIAL_TABLES.pop(upload_id, None)
        store.update_current_tables('adl3_disabled_life_expectancy', saved, 'pytest')


def test_registry_rejects_requests_without_credentials():
    """Anonymous and bogus-token requests must NOT see the registry.

    The endpoint guards on ``require_role(['admin', 'actuary'])`` which
    returns 403 in both the anonymous and the wrong-role case. We assert a
    non-2xx response so downstream code never accidentally exposes which
    rate tables drive the platform's pricing.
    """
    import urllib.error
    for token in (None, 'phins_invalid_bogus_token'):
        try:
            _get(_base_url() + '/api/actuarial/tables/registry', token)
            raise AssertionError('expected 401/403 for unauthorized request')
        except urllib.error.HTTPError as exc:
            assert exc.code in (401, 403), exc.code
