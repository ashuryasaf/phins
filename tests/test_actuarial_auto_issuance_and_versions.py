"""
Tests for the actuary dashboard's version governance + automatic clean
issuance features:

* ``UnderwritingConfig`` auto-approve gates (adjustable parameters) and
  ``evaluate_auto_approval`` rule evaluation.
* Automatic policy issuance on ``POST /api/policies/create`` when every gate
  passes (policy activated, billed, stamped ``system_auto_approve``).
* ``ActuarialTablesStore.restore_version`` / ``restore_config_version`` —
  restore clones history FORWARD; earlier versions are never mutated so
  policies pinned to them keep their issued conditions.
* ``GET /api/actuarial/versions/catalog`` — unified versions bar.
* ``POST /api/actuarial/versions/restore`` — restore endpoint.
* ``GET /api/actuarial/version-insights`` — BI/AI system insights.
* Version # pinning on newly created policies.

HTTP tests reuse the embedded server started by the repository-level
``conftest.py`` (base URL from ``TEST_BASE_URL``).
"""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from services.actuarial_service import (
    evaluate_auto_approval,
    get_actuarial_store,
)


# ----------------------------------------------------------------------------
# Helpers / fixtures
# ----------------------------------------------------------------------------


def _base_url() -> str:
    return os.environ.get('TEST_BASE_URL') or 'http://127.0.0.1:8000'


def _request(method: str, path: str, payload: dict | None = None,
             token: str | None = None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    req = Request(_base_url() + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read() or b'{}'), resp.status
    except HTTPError as err:
        body = err.read()
        try:
            return json.loads(body or b'{}'), err.code
        except json.JSONDecodeError:
            return {'raw': body.decode('utf-8', 'replace')}, err.code


@pytest.fixture
def admin_token() -> str:
    body, status = _request('POST', '/api/login', {
        'username': 'admin', 'password': 'admin123',
    })
    assert status == 200, body
    return body['token']


@pytest.fixture
def auto_approve_guard():
    """Snapshot + restore the auto-approve gates around a test so enabling
    automatic issuance can never leak into unrelated tests."""
    store = get_actuarial_store()
    saved = {
        'auto_approve_enabled': store.config.auto_approve_enabled,
        'auto_approve_max_adl': store.config.auto_approve_max_adl,
        'auto_approve_min_age': store.config.auto_approve_min_age,
        'auto_approve_max_age': store.config.auto_approve_max_age,
        'auto_approve_max_risk_score': store.config.auto_approve_max_risk_score,
        'auto_approve_max_coverage': store.config.auto_approve_max_coverage,
        'auto_approve_require_clean_history': store.config.auto_approve_require_clean_history,
    }
    yield store
    for key, value in saved.items():
        setattr(store.config, key, value)


CLEAN_APPLICANT = {
    'age': 30,
    'adl_level': 2,
    'coverage_amount': 200000,
    'smoking_status': 'non_smoker',
    'medical_conditions': [],
    'prior_disclosure': '',
}


# ----------------------------------------------------------------------------
# Service-layer: adjustable gates + rule evaluation
# ----------------------------------------------------------------------------


def test_default_config_exposes_auto_approve_gates():
    defaults = get_actuarial_store().get_default_config()
    assert defaults['auto_approve_enabled'] is False
    assert defaults['auto_approve_max_adl'] == 3
    assert defaults['auto_approve_min_age'] == 18
    assert defaults['auto_approve_max_age'] == 60
    assert defaults['auto_approve_max_risk_score'] == pytest.approx(0.25)
    assert defaults['auto_approve_max_coverage'] == pytest.approx(500000.0)
    assert defaults['auto_approve_require_clean_history'] is True


def test_evaluate_auto_approval_requires_feature_enabled(auto_approve_guard):
    store = auto_approve_guard
    store.config.auto_approve_enabled = False
    result = evaluate_auto_approval(dict(CLEAN_APPLICANT), risk_score=0.10)
    assert result['auto_approve'] is False
    assert 'auto_approve_disabled' in result['failed']


def test_evaluate_auto_approval_gates(auto_approve_guard):
    store = auto_approve_guard
    store.config.auto_approve_enabled = True

    clean = evaluate_auto_approval(dict(CLEAN_APPLICANT), risk_score=0.15)
    assert clean['auto_approve'] is True, clean
    assert clean['failed'] == []
    assert clean['config_version'] == store.config.config_version
    assert clean['tables_version'] == store.current_version
    # Every gate is reported for audit.
    assert {c['name'] for c in clean['checks']} >= {
        'min_age', 'max_age', 'max_adl', 'max_coverage', 'max_risk_score',
    }

    # Single-gate violations each block automation.
    for override, expected_failure in [
        ({'age': 72}, 'max_age'),
        ({'age': 12}, 'min_age'),
        ({'adl_level': 7}, 'max_adl'),
        ({'coverage_amount': 5_000_000}, 'max_coverage'),
        ({'smoking_status': 'smoker'}, 'clean_history_nonsmoker'),
        # Allow-list gate: former or unknown smoking status is not provably
        # clean and must fail too.
        ({'smoking_status': 'former_smoker'}, 'clean_history_nonsmoker'),
        ({'smoking_status': ''}, 'clean_history_nonsmoker'),
        ({'medical_conditions': [{'condition': 'diabetes'}]},
         'clean_history_no_medical_conditions'),
        ({'prior_disclosure': 'heart surgery 2019'},
         'clean_history_no_prior_disclosure'),
    ]:
        app = dict(CLEAN_APPLICANT)
        app.update(override)
        result = evaluate_auto_approval(app, risk_score=0.15)
        assert result['auto_approve'] is False, override
        assert expected_failure in result['failed'], override

    # Risk score above the adjustable ceiling blocks automation too.
    risky = evaluate_auto_approval(dict(CLEAN_APPLICANT), risk_score=0.60)
    assert risky['auto_approve'] is False
    assert 'max_risk_score' in risky['failed']

    # Missing inputs fail their gate — automation only approves proven cases.
    unknown = evaluate_auto_approval({'coverage_amount': 100000}, risk_score=None)
    assert unknown['auto_approve'] is False


def test_restore_version_clones_forward_without_mutating_history():
    store = get_actuarial_store()
    base_version = store.current_version
    base_tables = json.loads(json.dumps(store.versions[base_version]))

    # Edit a table → promoted to a new sub-version.
    edited = store.update_current_tables('mortality_rates', [
        {'age_min': 0, 'age_max': 65, 'rate_per_1000': 3.3},
        {'age_min': 65, 'age_max': 120, 'rate_per_1000': 44.0},
    ], 'pytest')
    assert edited['success'] is True
    edited_version = store.current_version
    assert edited_version != base_version

    # Restore the original version.
    restored = store.restore_version(base_version, 'pytest')
    assert restored['success'] is True, restored
    new_version = restored['version']
    assert new_version not in (base_version, edited_version)
    assert store.current_version == new_version

    # The restored snapshot carries provenance and the original rates.
    snapshot = store.versions[new_version]
    assert snapshot['restored_from'] == base_version
    assert snapshot['mortality_rates'] == base_tables['mortality_rates']

    # History is untouched: earlier versions keep their exact contents.
    assert store.versions[base_version]['mortality_rates'] == base_tables['mortality_rates']
    assert store.versions[edited_version]['mortality_rates'][0]['rate_per_1000'] == 3.3
    assert store.versions[edited_version]['status'] == 'archived'

    # Restoring the already-current version is rejected.
    again = store.restore_version(new_version, 'pytest')
    assert again['success'] is False

    # Unknown versions are rejected.
    missing = store.restore_version('V99.9', 'pytest')
    assert missing['success'] is False

    # Audit log recorded the restore.
    actions = [e['action'] for e in store.get_audit_log(20)]
    assert 'restore_version' in actions


def test_restore_config_version_is_forward_moving():
    store = get_actuarial_store()
    original_expense = store.config.expense_loading_pct

    first = store.update_config({'expense_loading_pct': 0.18}, 'pytest')
    assert first['success'] is True
    target_version = store.config.config_version

    second = store.update_config({'expense_loading_pct': 0.22}, 'pytest')
    assert second['success'] is True
    latest_version = store.config.config_version
    assert latest_version != target_version

    restored = store.restore_config_version(target_version, 'pytest')
    assert restored['success'] is True, restored
    # Values come back from the historical revision …
    assert store.config.expense_loading_pct == pytest.approx(0.18)
    # … but the revision counter keeps moving forward (no history rewrite).
    assert store.config.config_version not in (target_version, latest_version)

    missing = store.restore_config_version('cfg_v99999', 'pytest')
    assert missing['success'] is False

    # Cleanup: put the expense loading back for other tests.
    store.update_config({'expense_loading_pct': original_expense}, 'pytest')


def test_version_catalog_lists_tables_and_config_revisions():
    store = get_actuarial_store()
    catalog = store.get_version_catalog()
    assert catalog['current_version'] == store.current_version
    assert catalog['current_config_version'] == store.config.config_version

    versions = {v['version']: v for v in catalog['table_versions']}
    assert store.current_version in versions
    current_entry = versions[store.current_version]
    assert current_entry['is_current'] is True
    assert current_entry['restorable'] is False
    assert len(current_entry['integrity_hash']) == 64
    assert current_entry['components'].get('mortality_rates', 0) > 0

    assert catalog['config_revisions'], 'config revisions must never be empty'
    assert any(c['is_current'] for c in catalog['config_revisions'])


# ----------------------------------------------------------------------------
# HTTP: config round-trip, auto issuance, catalog / restore / insights
# ----------------------------------------------------------------------------


def test_config_api_roundtrips_auto_approve_gates(admin_token, auto_approve_guard):
    body, status = _request('POST', '/api/actuarial/config', {
        'auto_approve_enabled': True,
        'auto_approve_max_adl': 4,
        'auto_approve_min_age': 21,
        'auto_approve_max_age': 55,
        'auto_approve_max_risk_score': 30,       # percent input accepted
        'auto_approve_max_coverage': 350000,
        'auto_approve_require_clean_history': False,
    }, admin_token)
    assert status == 200, body
    cfg = body['config']
    assert cfg['auto_approve_enabled'] is True
    assert cfg['auto_approve_max_adl'] == 4
    assert cfg['auto_approve_min_age'] == 21
    assert cfg['auto_approve_max_age'] == 55
    assert cfg['auto_approve_max_risk_score'] == pytest.approx(0.30)
    assert cfg['auto_approve_max_coverage'] == pytest.approx(350000)
    assert cfg['auto_approve_require_clean_history'] is False

    body, status = _request('GET', '/api/actuarial/config', token=admin_token)
    assert status == 200
    assert body['config']['auto_approve_enabled'] is True
    assert body['config']['auto_approve_max_adl'] == 4


def test_clean_application_is_auto_issued(admin_token, auto_approve_guard):
    store = auto_approve_guard
    store.config.auto_approve_enabled = True

    body, status = _request('POST', '/api/policies/create', {
        'customer_name': 'Clara Cleanrecord',
        'customer_email': 'clara.cleanrecord@example.com',
        'type': 'life',
        'coverage_amount': 200000,
        'age': 30,
        'adl_level': 2,
        'smoking_status': 'non_smoker',
    })
    assert status == 201, body

    issuance = body.get('auto_issuance')
    assert issuance is not None, 'auto_issuance outcome missing from response'
    assert issuance['auto_issued'] is True, issuance
    assert issuance['issued_by'] == 'system_auto_approve'
    assert issuance['bill_id'], 'first bill must be generated on issuance'
    assert issuance['underwriting_rule_version'] == store.config.config_version

    policy = body['policy']
    assert policy['status'] == 'active'
    assert policy['approved_by'] == 'system_auto_approve'
    assert policy['auto_issued'] is True
    # Every policy carries its version #.
    assert policy['tables_version'] == store.current_version
    assert policy['config_version'] == store.config.config_version
    assert policy['underwriting_rule_version'] == store.config.config_version

    underwriting = body['underwriting']
    assert underwriting['status'] == 'approved'
    assert underwriting['approved_by'] == 'system_auto_approve'
    evaluation = underwriting['auto_approval_evaluation']
    assert evaluation['auto_approve'] is True
    assert evaluation['failed'] == []


def test_risky_application_stays_in_manual_queue(auto_approve_guard):
    store = auto_approve_guard
    store.config.auto_approve_enabled = True

    body, status = _request('POST', '/api/policies/create', {
        'customer_name': 'Rex Riskington',
        'customer_email': 'rex.riskington@example.com',
        'type': 'life',
        'coverage_amount': 900000,
        'age': 72,
        'adl_level': 7,
        'smoking_status': 'smoker',
    })
    assert status == 201, body

    policy = body['policy']
    assert policy['status'] == 'pending_underwriting'
    assert body['underwriting']['status'] == 'pending'

    issuance = body.get('auto_issuance')
    assert issuance is not None
    assert issuance['auto_issued'] is False
    failed = set(issuance['evaluation']['failed'])
    assert {'max_age', 'max_adl', 'max_coverage'} <= failed


def test_new_policies_carry_version_numbers_even_without_auto_approve(auto_approve_guard):
    store = auto_approve_guard
    store.config.auto_approve_enabled = False

    body, status = _request('POST', '/api/policies/create', {
        'customer_name': 'Vera Versioned',
        'customer_email': 'vera.versioned@example.com',
        'type': 'life',
        'coverage_amount': 150000,
        'age': 40,
    })
    assert status == 201, body
    policy = body['policy']
    assert policy['status'] == 'pending_underwriting'
    assert policy['tables_version'] == store.current_version
    assert policy['config_version'] == store.config.config_version


def test_versions_catalog_endpoint(admin_token):
    body, status = _request('GET', '/api/actuarial/versions/catalog', token=admin_token)
    assert status == 200, body
    assert body['success'] is True
    assert body['current_version']
    assert body['table_versions']
    current = [v for v in body['table_versions'] if v['is_current']]
    assert len(current) == 1
    assert 'policies_pinned' in current[0]
    assert body['config_revisions']
    usage = body['policy_version_usage']
    assert set(usage) >= {'policies_total', 'by_tables_version', 'unversioned'}


def test_restore_endpoint_preserves_issued_policy_pins(admin_token, auto_approve_guard):
    store = auto_approve_guard
    store.config.auto_approve_enabled = False
    issue_version = store.current_version

    # Issue an application pinned to the version in force today.
    body, status = _request('POST', '/api/policies/create', {
        'customer_name': 'Pinned Holder',
        'customer_email': 'pinned.holder@example.com',
        'type': 'life',
        'coverage_amount': 120000,
        'age': 35,
    })
    assert status == 201, body
    assert body['policy']['tables_version'] == issue_version

    # Rates change afterwards (new version) …
    body, status = _request('POST', '/api/actuarial/table-update', {
        'table_type': 'mortality_rates',
        'table_data': [
            {'age_min': 0, 'age_max': 65, 'rate_per_1000': 2.9},
            {'age_min': 65, 'age_max': 120, 'rate_per_1000': 41.0},
        ],
    }, admin_token)
    assert status == 200, body
    changed_version = body['version']
    assert changed_version != issue_version

    # … and the actuary restores the original basis.
    body, status = _request('POST', '/api/actuarial/versions/restore', {
        'version': issue_version,
    }, admin_token)
    assert status == 200, body
    assert body['success'] is True
    new_version = body['new_version']
    assert new_version not in (issue_version, changed_version)
    assert body['restored_from'] == issue_version
    assert store.current_version == new_version

    # The catalog proves immutability: the restored clone hashes identically
    # to the original version, while the interim change stays intact.
    body, status = _request('GET', '/api/actuarial/versions/catalog', token=admin_token)
    assert status == 200
    hashes = {v['version']: v['integrity_hash'] for v in body['table_versions']}
    assert hashes[new_version] == hashes[issue_version]
    assert hashes[changed_version] != hashes[issue_version]

    # Unknown version → 400 with JSON error shape.
    body, status = _request('POST', '/api/actuarial/versions/restore', {
        'version': 'V99.9',
    }, admin_token)
    assert status == 400
    assert body.get('error')

    # Missing payload → 400.
    body, status = _request('POST', '/api/actuarial/versions/restore', {}, admin_token)
    assert status == 400


def test_version_insights_endpoint(admin_token):
    body, status = _request('GET', '/api/actuarial/version-insights', token=admin_token)
    assert status == 200, body
    assert body['success'] is True
    assert body['current_version']
    assert 'adoption' in body and 'auto_issuance' in body
    assert isinstance(body['insights'], list) and body['insights']
    for insight in body['insights']:
        assert {'severity', 'title', 'detail'} <= set(insight)


def test_version_governance_requires_role():
    for method, path, payload in [
        ('GET', '/api/actuarial/versions/catalog', None),
        ('GET', '/api/actuarial/version-insights', None),
        ('POST', '/api/actuarial/versions/restore', {'version': 'V2.0'}),
    ]:
        body, status = _request(method, path, payload)
        assert status in (401, 403), (path, status, body)
