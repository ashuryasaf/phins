"""
HTTP round-trips for the A3 async agent routes.

With ``PHINS_AGENT_ASYNC`` off every migrated route answers exactly as before.
With it on, each answers ``202 {job_id, status: "queued", poll_url}`` and
``GET /api/jobs/{id}`` moves to ``completed`` with the synchronous body as
``result`` once the queue drains. Job reads are scoped to the submitter (or
staff); any other principal sees 404.

Routes: /api/claims/probability-report, /api/risk-dashboard/ai-assess,
/api/reports/analyze, /api/reports/generate, /api/mislaka/import,
/api/admin/media/video-agents/submit.
"""

import json
import os
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import web_portal.server as portal
from services.agent_job_queue import reset_job_queue

VOLATILE = {
    'id', 'assessment_id', 'report_id', 'analysis_id', 'document_id', 'analyzed_at',
    'assessment_date', 'created_at', 'updated_at', 'timestamp', 'generated_at',
    'generated_date', 'analysis_date', 'created_date', 'processing_time_seconds',
    'processing_time_ms', 'completed_at', 'upload_date', 'processed_at', 'request_id',
}


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def _base_url():
    return os.environ.get('TEST_BASE_URL') or f"http://127.0.0.1:{os.environ.get('TEST_PORT', '8000')}"


def _tok(token):
    # validate_session only honours in-memory tokens carrying the legacy prefix.
    return token if token.startswith('phins_') else f'phins_{token}'


def _call(method, path, body=None, token=None, raw=None, content_type='application/json'):
    headers = {'Content-Type': content_type}
    if token:
        headers['Authorization'] = f'Bearer {_tok(token)}'
    data = raw if raw is not None else (json.dumps(body).encode('utf-8') if body is not None else None)
    req = Request(_base_url() + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode('utf-8') or '{}')
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode('utf-8') or '{}')


def _seed_session(token, role, username=None, customer_id=None):
    expires = (datetime.now() + timedelta(hours=1)).isoformat()
    session = {'username': username or f'{role}-{token}', 'role': role,
               'expires': expires, 'jti': f'{token}-jti'}
    if customer_id:
        session['customer_id'] = customer_id
    with portal.STATE_LOCK:
        portal.SESSIONS[_tok(token)] = session
    return session


def _seed_claim(claim_id='CLM-ASYNC-1', customer_id='CUST-ASYNC-1'):
    with portal.STATE_LOCK:
        portal.CUSTOMERS[customer_id] = {'id': customer_id, 'name': 'Async Tester',
                                         'email': 'async@example.com'}
        portal.POLICIES['POL-ASYNC-1'] = {'id': 'POL-ASYNC-1', 'customer_id': customer_id,
                                          'coverage_amount': 100000, 'premium': 500,
                                          'status': 'active'}
        portal.CLAIMS[claim_id] = {'id': claim_id, 'customer_id': customer_id,
                                   'policy_id': 'POL-ASYNC-1', 'claimed_amount': 12000,
                                   'status': 'submitted', 'files_count': 1,
                                   'incident_date': '2026-08-01', 'claim_type': 'medical'}


def _drain():
    stats = portal.get_agent_job_queue().process_once()
    return stats


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    # First request on a port resets in-memory state; do it before seeding.
    _call('GET', '/api/health')
    reset_job_queue()
    monkeypatch.delenv('PHINS_AGENT_ASYNC', raising=False)
    yield
    reset_job_queue()


@pytest.fixture
def async_on(monkeypatch):
    monkeypatch.setenv('PHINS_AGENT_ASYNC', '1')


# ── Flag off: unchanged synchronous bodies ────────────────────────────────────

def test_flag_off_claims_report_is_synchronous():
    _seed_claim()
    _seed_session('tok-adj', 'claims_adjuster')
    status, body = _call('POST', '/api/claims/probability-report', {'claim_id': 'CLM-ASYNC-1'},
                         token='tok-adj')
    assert status == 200, body
    assert body['success'] is True
    assert body['report']['claim_id'] == 'CLM-ASYNC-1'
    assert 'job_id' not in body


def test_health_reports_agent_jobs_block(async_on):
    status, body = _call('GET', '/api/health')
    assert status == 200
    assert body['agent_jobs']['async_enabled'] is True
    assert 'queue' in body['agent_jobs']
    assert body['agent_jobs']['max_threads'] >= 1


# ── Claims Bot ────────────────────────────────────────────────────────────────

def test_claims_report_202_then_completed_with_parity(async_on, monkeypatch):
    _seed_claim()
    _seed_session('tok-adj', 'claims_adjuster', username='adjuster-1')

    # Synchronous body for the same claim, captured with the flag off.
    monkeypatch.delenv('PHINS_AGENT_ASYNC')
    _, sync_body = _call('POST', '/api/claims/probability-report', {'claim_id': 'CLM-ASYNC-1'},
                         token='tok-adj')
    monkeypatch.setenv('PHINS_AGENT_ASYNC', '1')

    status, body = _call('POST', '/api/claims/probability-report', {'claim_id': 'CLM-ASYNC-1'},
                         token='tok-adj')
    assert status == 202, body
    assert body['status'] == 'queued'
    assert body['poll_url'] == f"/api/jobs/{body['job_id']}"

    status, job = _call('GET', body['poll_url'], token='tok-adj')
    assert status == 200
    assert job['status'] == 'pending'
    assert job['subject_type'] == 'claim' and job['subject_id'] == 'CLM-ASYNC-1'
    assert job['submitted_by'] == 'adjuster-1'
    assert 'input_params' not in job and 'worker_id' not in job

    assert _drain()['completed'] == 1
    status, job = _call('GET', body['poll_url'], token='tok-adj')
    assert status == 200
    assert job['status'] == 'completed'
    assert job['result']['success'] is True
    assert job['result']['report']['claim_id'] == 'CLM-ASYNC-1'
    assert _stable(job['result']) == _stable(sync_body)


def test_claims_report_validation_still_precedes_enqueue(async_on):
    _seed_claim()
    _seed_session('tok-adj', 'claims_adjuster')
    assert _call('POST', '/api/claims/probability-report', {}, token='tok-adj')[0] == 400
    assert _call('POST', '/api/claims/probability-report', {'claim_id': 'CLM-NOPE'},
                 token='tok-adj')[0] == 404
    # A customer may only queue a report for their own claim.
    _seed_session('tok-other', 'customer', customer_id='CUST-OTHER')
    assert _call('POST', '/api/claims/probability-report', {'claim_id': 'CLM-ASYNC-1'},
                 token='tok-other')[0] == 404
    assert portal.get_agent_job_queue().queue_stats() == {}


# ── GET /api/jobs/{id}: scope ─────────────────────────────────────────────────

def test_job_read_is_scoped_to_submitter_or_staff(async_on):
    _seed_claim()
    _seed_session('tok-cust', 'customer', username='cust-user', customer_id='CUST-ASYNC-1')
    _seed_session('tok-intruder', 'customer', username='intruder', customer_id='CUST-INTRUDER')
    _seed_session('tok-admin', 'admin', username='admin-1')

    status, body = _call('POST', '/api/claims/probability-report', {'claim_id': 'CLM-ASYNC-1'},
                         token='tok-cust')
    assert status == 202, body
    poll = body['poll_url']

    assert _call('GET', poll)[0] == 401
    assert _call('GET', poll, token='tok-intruder') == (404, {'error': 'Job not found'})
    assert _call('GET', poll, token='tok-cust')[0] == 200
    assert _call('GET', poll, token='tok-admin')[0] == 200
    assert _call('GET', '/api/jobs/JOB-DOESNOTEXIST', token='tok-admin')[0] == 404
    assert _call('GET', '/api/jobs/', token='tok-admin')[0] == 404


def test_admin_job_listing_hides_inputs_and_filters(async_on):
    _seed_claim()
    _seed_session('tok-adj', 'claims_adjuster', username='adjuster-1')
    _seed_session('tok-admin', 'admin')
    _call('POST', '/api/claims/probability-report', {'claim_id': 'CLM-ASYNC-1'}, token='tok-adj')

    status, body = _call('GET', '/api/doc-service/jobs?subject_type=claim', token='tok-admin')
    assert status == 200
    assert len(body['jobs']) == 1
    assert body['jobs'][0]['subject_id'] == 'CLM-ASYNC-1'
    assert 'input_params' not in body['jobs'][0]
    assert 'claims_probability_report' in body['handlers']
    assert body['queue'] == {'pending': 1}
    status, body = _call('GET', '/api/doc-service/jobs?subject_type=report', token='tok-admin')
    assert body['jobs'] == []
    # Listing is staff-only; a customer cannot browse the queue.
    _seed_session('tok-cust', 'customer', customer_id='CUST-ASYNC-1')
    assert _call('GET', '/api/doc-service/jobs', token='tok-cust')[0] == 403


# ── Underwriting Bot (multipart upload) ───────────────────────────────────────

def _multipart(filename, content, mime='application/pdf'):
    boundary = 'phinsboundaryA3'
    body = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f'Content-Type: {mime}\r\n\r\n'
    ).encode('utf-8') + content + f'\r\n--{boundary}--\r\n'.encode('utf-8')
    return body, f'multipart/form-data; boundary={boundary}'


def test_underwriting_assessment_202_then_completed(async_on, monkeypatch):
    _seed_session('tok-uw', 'underwriter', username='uw-1')
    content = b"%PDF-1.4\nMedical report: patient stable, non-smoker, normal blood pressure.\n%%EOF\n"
    raw, ctype = _multipart('report.pdf', content)

    monkeypatch.delenv('PHINS_AGENT_ASYNC')
    status, sync_body = _call('POST', '/api/risk-dashboard/ai-assess', raw=raw, content_type=ctype,
                              token='tok-uw')
    assert status == 200, sync_body
    monkeypatch.setenv('PHINS_AGENT_ASYNC', '1')

    status, body = _call('POST', '/api/risk-dashboard/ai-assess', raw=raw, content_type=ctype,
                         token='tok-uw')
    assert status == 202, body
    # Same file, same submitter: idempotent re-submit points at the same job.
    again = _call('POST', '/api/risk-dashboard/ai-assess', raw=raw, content_type=ctype, token='tok-uw')[1]
    assert again['job_id'] == body['job_id']

    assert _drain()['completed'] == 1
    status, job = _call('GET', body['poll_url'], token='tok-uw')
    assert status == 200 and job['status'] == 'completed'
    assert job['result']['assessment']['file_analyzed'] == 'report.pdf'
    assert job['result']['assessment']['analyzed_by'] == 'uw-1'
    assert _stable(job['result']) == _stable(sync_body)
    # Validation errors are answered before anything is queued.
    bad_raw, bad_ctype = _multipart('notes.exe', b'x')
    assert _call('POST', '/api/risk-dashboard/ai-assess', raw=bad_raw, content_type=bad_ctype,
                 token='tok-uw')[0] == 400


# ── Risk Reports ──────────────────────────────────────────────────────────────

@pytest.fixture
def reports_service(tmp_path, monkeypatch):
    import services.ai_risk_reports_service as mod
    monkeypatch.setattr(mod, 'AI_REPORTS_DATA_FILE', str(tmp_path / 'ai_reports.json'))
    service = mod.init_ai_reports_service(load_persisted=False)
    yield service
    mod._ai_reports_service = None


_CSV = (b"policy_number,coverage_amount,premium,claim_count,risk_score\n"
        b"POL-001,100000,500,0,25\nPOL-002,200000,750,1,45\nPOL-003,150000,600,0,30\n")


def test_reports_analyze_and_generate_202_flow(async_on, reports_service, monkeypatch):
    _seed_session('tok-cust', 'customer', username='cust-r', customer_id='CUST-R')
    _seed_session('tok-intruder', 'customer', username='intruder', customer_id='CUST-X')
    doc = reports_service.parse_file('a3.csv', _CSV, 'csv', 'CUST-R', 'customer')

    # Authorization still happens before enqueue: another customer is refused.
    assert _call('POST', '/api/reports/analyze', {'document_id': doc['document_id']},
                 token='tok-intruder')[0] == 403

    monkeypatch.delenv('PHINS_AGENT_ASYNC')
    status, sync_analysis = _call('POST', '/api/reports/analyze', {'document_id': doc['document_id']},
                                  token='tok-cust')
    assert status == 200, sync_analysis
    monkeypatch.setenv('PHINS_AGENT_ASYNC', '1')

    status, body = _call('POST', '/api/reports/analyze', {'document_id': doc['document_id']},
                         token='tok-cust')
    assert status == 202, body
    assert _drain()['completed'] == 1
    status, job = _call('GET', body['poll_url'], token='tok-cust')
    assert job['status'] == 'completed'
    assert job['result']['success'] is True
    assert _stable(job['result']) == _stable(sync_analysis)
    analysis_id = job['result']['id']

    status, body = _call('POST', '/api/reports/generate',
                         {'analysis_id': analysis_id, 'language': 'english',
                          'idempotency_key': 'gen-1'}, token='tok-cust')
    assert status == 202, body
    dup = _call('POST', '/api/reports/generate',
                {'analysis_id': analysis_id, 'language': 'english', 'idempotency_key': 'gen-1'},
                token='tok-cust')[1]
    assert dup['job_id'] == body['job_id']
    assert _drain()['completed'] == 1
    status, job = _call('GET', body['poll_url'], token='tok-cust')
    assert job['status'] == 'completed'
    assert job['result']['success'] is True
    assert job['result']['analysis_id'] == analysis_id
    assert _call('GET', body['poll_url'], token='tok-intruder')[0] == 404


# ── Pension import (Mislaka) ──────────────────────────────────────────────────

def _mislaka_result():
    from services.mislaka_api_service import (MislakaPerson, MislakaPolicy, MislakaQueryResult,
                                              MislakaStatus)
    pols = [MislakaPolicy(policy_id='P1', policy_number='1001', product_type='pension',
                          company_name='Harel', company_code='H', start_date='2015-01-01',
                          status='active', premium_monthly=900.0, accumulated_value=250000.0)]
    return MislakaQueryResult(request_id='r', status=MislakaStatus.SUCCESS,
                              timestamp=datetime.now().isoformat(),
                              person=MislakaPerson(id_number='123456789'), policies=pols,
                              total_policies=1, total_accumulated=250000.0,
                              total_monthly_premium=900.0)


@pytest.fixture
def mislaka(monkeypatch):
    import services.mislaka_api_service as mod
    fake = MagicMock()
    fake.is_configured.return_value = True
    fake.get_person_policies.return_value = _mislaka_result()
    monkeypatch.setattr(mod, '_mislaka_service', fake)
    return fake


def test_mislaka_import_202_flow_and_pii(async_on, reports_service, mislaka):
    _seed_session('tok-cust', 'customer', username='cust-m', customer_id='CUST-M')
    _seed_session('tok-admin', 'admin')
    session = {'user_id': 'u'}  # route requires user_id in the session payload
    with portal.STATE_LOCK:
        portal.SESSIONS[_tok('tok-cust')].update(session)

    status, body = _call('POST', '/api/mislaka/import', {'id_number': '123456789'}, token='tok-cust')
    assert status == 202, body
    status, job = _call('GET', body['poll_url'], token='tok-cust')
    assert status == 200
    assert '123456789' not in json.dumps(job)
    assert job['subject_type'] == 'pension_import'

    assert _drain()['completed'] == 1
    status, job = _call('GET', body['poll_url'], token='tok-cust')
    assert job['status'] == 'completed'
    assert job['result']['policies_count'] == 1
    assert job['result']['total_accumulated'] == 250000.0
    # Admin listing never shows the national ID either.
    status, listing = _call('GET', '/api/doc-service/jobs?subject_type=pension_import', token='tok-admin')
    assert '123456789' not in json.dumps(listing)

    mislaka.is_configured.return_value = False
    assert _call('POST', '/api/mislaka/import', {'id_number': '123456789'}, token='tok-cust')[0] == 503
    assert _call('POST', '/api/mislaka/import', {}, token='tok-cust')[0] == 400


# ── Video Agents ──────────────────────────────────────────────────────────────

@pytest.fixture
def video_mod():
    import services.video_agents_service as mod
    original = mod.MEDIA_GENERATION_AVAILABLE
    mod.MEDIA_GENERATION_AVAILABLE = True
    mod._video_agents_service = None
    mod._job_store = mod._JobStore()
    media = MagicMock()
    media.supported_provider_config.return_value = {
        'gemini': {'enabled': True, 'label': 'Gemini / Veo', 'models': []},
        'kling': {'enabled': False, 'label': 'Kling', 'models': []},
    }
    media.submit_video_generation.return_value = {
        'provider': 'gemini', 'provider_job_id': 'op-http', 'status': 'queued',
        'message': 'Submitted', 'provider_state': {'operation_name': 'op-http'},
    }
    with patch.object(mod, 'get_media_generation_service', return_value=media):
        yield mod
    mod.MEDIA_GENERATION_AVAILABLE = original
    mod._video_agents_service = None
    mod._job_store = mod._JobStore()


@pytest.mark.skipif(not portal.api_extensions_enabled, reason='api extensions not wired')
def test_video_submit_202_flow(async_on, video_mod, monkeypatch):
    # ``/api/admin/media/video-agents/submit`` lives in api_extensions.dispatch_post,
    # which server.do_POST only forwards for the security/foundations prefixes, so
    # (like tests/test_video_agents_service.py) drive the dispatcher directly and
    # poll the resulting job over HTTP.
    from web_portal.api_extensions import dispatch_post
    media_session = _seed_session('tok-media', 'media', username='media-1')
    cust_session = _seed_session('tok-cust', 'customer', username='cust', customer_id='CUST-V')
    payload = {'campaign_id': 'MKT-HTTP', 'provider': 'gemini', 'pipeline_type': 'introductions',
               'poll_mode': 'webhook', 'title': 'Intro'}
    submit = '/api/admin/media/video-agents/submit'
    assert dispatch_post(submit, cust_session, payload, '127.0.0.1')[0] == 403
    assert dispatch_post(submit, None, payload, '127.0.0.1')[0] == 401

    monkeypatch.delenv('PHINS_AGENT_ASYNC')
    status, sync_body = dispatch_post(submit, media_session, payload, '127.0.0.1')
    assert status == 201, sync_body
    monkeypatch.setenv('PHINS_AGENT_ASYNC', '1')

    status, body = dispatch_post(submit, media_session, payload, '127.0.0.1')
    assert status == 202, body
    assert body['poll_url'] == f"/api/jobs/{body['job_id']}"
    assert _drain()['completed'] == 1
    status, job = _call('GET', body['poll_url'], token='tok-media')
    assert status == 200 and job['status'] == 'completed'
    assert job['result']['success'] is True
    assert job['result']['job']['provider_job_id'] == 'op-http'
    assert job['result']['job']['submitted_by'] == 'media-1'
    assert _stable(job['result']) == _stable(sync_body)
    assert job['max_attempts'] == 1
    # Another principal cannot read the media user's job.
    assert _call('GET', body['poll_url'], token='tok-cust')[0] == 404
    # Validation errors are still answered inline, nothing is queued for them.
    bad = dict(payload, pipeline_type='bad_pipeline')
    assert dispatch_post(submit, media_session, bad, '127.0.0.1')[0] == 400
    assert portal.get_agent_job_queue().queue_stats() == {'completed': 1}
