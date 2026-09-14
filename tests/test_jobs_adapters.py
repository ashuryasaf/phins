"""
Golden-parity tests for the agent job adapters (A3, services/jobs/*).

For each migrated agent: the synchronous function the route calls and the
queue handler (enqueue -> process_once -> job result) must produce the same
payload on the same fixture, modulo generated ids / timestamps. Run in
memory and, for one adapter, on SQLite to prove the row round-trip.
"""

import base64
import copy
import os
from datetime import datetime
from typing import Any, Dict, Iterable
from unittest.mock import MagicMock, patch

import pytest

from services.agent_job_queue import AgentJobQueue, reset_job_queue
from services import jobs
from services.jobs import (
    JobContext,
    claims_bot_job,
    pension_import_job,
    public_job_view,
    queued_response,
    register_all,
    risk_report_job,
    underwriting_bot_job,
    video_job,
)

VOLATILE = {
    'id', 'assessment_id', 'report_id', 'analysis_id', 'document_id', 'decision_id',
    'analyzed_at', 'assessment_date', 'created_at', 'updated_at', 'timestamp',
    'generated_at', 'generated_date', 'analysis_date', 'created_date',
    'processing_time_seconds', 'processing_time_ms', 'completed_at',
    'upload_date', 'processed_at', 'request_id',
}


def _stable(value: Any, drop: Iterable[str] = VOLATILE) -> Any:
    drop = set(drop)
    if isinstance(value, dict):
        return {k: _stable(v, drop) for k, v in value.items() if k not in drop}
    if isinstance(value, list):
        return [_stable(v, drop) for v in value]
    return value


@pytest.fixture(autouse=True)
def _isolate():
    reset_job_queue()
    yield
    reset_job_queue()


@pytest.fixture
def queue():
    q = AgentJobQueue(poll_interval=0.01)
    yield q
    q.stop(timeout=1.0)


def _context(**overrides) -> JobContext:
    claims = {
        'CLM-A3-1': {'id': 'CLM-A3-1', 'customer_id': 'CUST-A3', 'policy_id': 'POL-A3',
                     'claimed_amount': 12000, 'status': 'submitted', 'files_count': 2,
                     'incident_date': '2026-08-01', 'claim_type': 'medical'},
    }
    policies = {'POL-A3': {'id': 'POL-A3', 'customer_id': 'CUST-A3', 'coverage_amount': 100000,
                           'premium': 500, 'status': 'active'}}
    customers = {'CUST-A3': {'id': 'CUST-A3', 'name': 'A3 Tester', 'email': 'a3@example.com'}}
    uw = {'UW-A3': {'id': 'UW-A3', 'customer_id': 'CUST-A3', 'policy_id': 'POL-A3',
                    'medical_conditions': [{'condition': 'hypertension'}], 'identity_verified': True}}
    ctx = JobContext(customers=customers, policies=policies, underwriting_apps=uw,
                     claims=claims, audit=None,
                     sanitize_claim_report=lambda r: {k: v for k, v in r.items() if k != 'evidence'})
    for k, v in overrides.items():
        setattr(ctx, k, v)
    return ctx


def _run(queue, job):
    stats = queue.process_once()
    assert stats['completed'] == 1, (stats, queue.get_job(job['id']))
    return queue.get_job(job['id'])


# ── Registration / helpers ────────────────────────────────────────────────────

def test_register_all_binds_every_adapter(queue):
    register_all(queue)  # no context: bots are not bound
    assert set(queue.handlers()) == {
        risk_report_job.ANALYZE_JOB_TYPE, risk_report_job.GENERATE_JOB_TYPE,
        pension_import_job.JOB_TYPE, video_job.JOB_TYPE,
    }
    register_all(queue, _context())
    assert underwriting_bot_job.JOB_TYPE in queue.handlers()
    assert claims_bot_job.JOB_TYPE in queue.handlers()


def test_queued_response_and_public_view(queue):
    queue.register_handler('t', lambda job: {'ok': 1})
    job = queue.enqueue(job_type='t', subject_type='x', subject_id='1', submitted_by='u',
                        input_params={'secret': 'value'})
    assert queued_response(job) == {'job_id': job['id'], 'status': 'queued',
                                    'poll_url': f"/api/jobs/{job['id']}"}
    queue.process_once()
    done = queue.get_job(job['id'])
    assert queued_response(done)['status'] == 'completed'
    view = public_job_view(done)
    assert 'input_params' not in view and 'worker_id' not in view
    assert view['result'] == {'ok': 1}
    assert view['poll_url'] == f"/api/jobs/{job['id']}"


# ── Underwriting Bot ──────────────────────────────────────────────────────────

def _pdf_bytes() -> bytes:
    return (b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n"
            b"Medical report: patient stable, no chronic conditions. "
            b"Blood pressure normal. Non-smoker.\n%%EOF\n")


def test_underwriting_assessment_parity(queue):
    ctx = _context()
    register_all(queue, ctx)
    content = _pdf_bytes()

    sync = underwriting_bot_job.response_body(underwriting_bot_job.run_ai_assessment(
        ctx, filename='report.pdf', file_content=content, mime_type='application/pdf',
        actor='underwriter'))

    job = underwriting_bot_job.enqueue_ai_assessment(
        queue, filename='report.pdf', file_content=content, mime_type='application/pdf',
        actor='underwriter', submitted_by='underwriter')
    assert job['subject_type'] == 'application'
    assert job['input_params']['file_b64'] == base64.b64encode(content).decode('ascii')
    done = _run(queue, job)

    assert _stable(done['result']) == _stable(sync)
    assert done['result']['assessment']['file_analyzed'] == 'report.pdf'
    assert done['result']['assessment']['analyzed_by'] == 'underwriter'
    assert done['result']['success'] is True


def test_underwriting_idempotency_is_content_and_submitter_scoped(queue):
    register_all(queue, _context())
    content = _pdf_bytes()
    a = underwriting_bot_job.enqueue_ai_assessment(
        queue, filename='a.pdf', file_content=content, mime_type='', actor='u1', submitted_by='u1')
    again = underwriting_bot_job.enqueue_ai_assessment(
        queue, filename='a.pdf', file_content=content, mime_type='', actor='u1', submitted_by='u1')
    other_user = underwriting_bot_job.enqueue_ai_assessment(
        queue, filename='a.pdf', file_content=content, mime_type='', actor='u2', submitted_by='u2')
    assert a['id'] == again['id']
    assert other_user['id'] != a['id']
    with pytest.raises(ValueError):
        underwriting_bot_job.enqueue_ai_assessment(
            queue, filename='big.pdf', file_content=b'x' * (underwriting_bot_job.MAX_FILE_BYTES + 1),
            mime_type='', actor='u1', submitted_by='u1')


# ── Claims Bot ────────────────────────────────────────────────────────────────

def test_claims_probability_report_parity(queue):
    ctx = _context()
    register_all(queue, ctx)

    sync_report = claims_bot_job.generate_probability_report(ctx, 'CLM-A3-1')
    assert sync_report is not None
    sync = claims_bot_job.response_body(ctx.sanitize_claim_report(sync_report))

    job = claims_bot_job.enqueue_probability_report(
        queue, claim_id='CLM-A3-1', claim=ctx.claims['CLM-A3-1'], submitted_by='adjuster')
    assert job['subject_type'] == 'claim' and job['subject_id'] == 'CLM-A3-1'
    done = _run(queue, job)

    assert _stable(done['result']) == _stable(sync)
    assert done['result']['report']['claim_id'] == 'CLM-A3-1'
    assert 'evidence' not in done['result']['report']


def test_claims_report_idempotency_tracks_claim_content(queue):
    ctx = _context()
    register_all(queue, ctx)
    claim = ctx.claims['CLM-A3-1']
    first = claims_bot_job.enqueue_probability_report(queue, claim_id='CLM-A3-1', claim=claim,
                                                      submitted_by='adjuster')
    dup = claims_bot_job.enqueue_probability_report(queue, claim_id='CLM-A3-1', claim=claim,
                                                    submitted_by='adjuster')
    assert first['id'] == dup['id']
    changed = dict(claim, claimed_amount=99000)
    fresh = claims_bot_job.enqueue_probability_report(queue, claim_id='CLM-A3-1', claim=changed,
                                                      submitted_by='adjuster')
    assert fresh['id'] != first['id']


def test_claims_report_missing_claim_fails_the_job(queue):
    register_all(queue, _context())
    job = queue.enqueue(job_type=claims_bot_job.JOB_TYPE, subject_type='claim',
                        subject_id='CLM-NOPE', input_params={'claim_id': 'CLM-NOPE'}, max_attempts=1)
    assert queue.process_once()['dead_letter'] == 1
    assert 'not found' in queue.get_job(job['id'])['error_message']


# ── Risk Reports ──────────────────────────────────────────────────────────────

_CSV = (b"policy_number,coverage_amount,premium,claim_count,risk_score\n"
        b"POL-001,100000,500,0,25\nPOL-002,200000,750,1,45\n"
        b"POL-003,150000,600,0,30\nPOL-004,500000,1500,3,85\n")


@pytest.fixture
def reports_service(tmp_path, monkeypatch):
    import services.ai_risk_reports_service as mod
    monkeypatch.setattr(mod, 'AI_REPORTS_DATA_FILE', str(tmp_path / 'ai_reports.json'))
    service = mod.init_ai_reports_service(load_persisted=False)
    yield service
    mod._ai_reports_service = None


def test_risk_report_analyze_and_generate_parity(queue, reports_service):
    register_all(queue)
    doc = reports_service.parse_file('a3.csv', _CSV, 'csv', 'CUST-R', 'customer')
    document_id = doc['document_id']

    sync_analysis = risk_report_job.run_analyze(document_id)
    job = risk_report_job.enqueue_analyze(queue, document_id=document_id, submitted_by='CUST-R')
    assert job['subject_type'] == 'report' and job['subject_id'] == document_id
    done = _run(queue, job)
    assert _stable(done['result']) == _stable(sync_analysis)
    assert done['result']['success'] is True
    analysis_id = done['result']['id']

    sync_report = risk_report_job.run_generate(analysis_id, 'english')
    gen = risk_report_job.enqueue_generate(queue, analysis_id=analysis_id, language='english',
                                           submitted_by='CUST-R')
    done_gen = _run(queue, gen)
    assert _stable(done_gen['result']) == _stable(sync_report)
    assert done_gen['result']['success'] is True


def test_risk_report_unknown_document_fails_visibly(queue, reports_service):
    register_all(queue)
    job = risk_report_job.enqueue_analyze(queue, document_id='DOC-NOPE', submitted_by='u')
    queue._update_job(job['id'], {'max_attempts': 1})
    assert queue.process_once()['dead_letter'] == 1
    assert queue.get_job(job['id'])['error_message']


# ── Pension import ────────────────────────────────────────────────────────────

def _mislaka_result(policies=True):
    from services.mislaka_api_service import MislakaPolicy, MislakaQueryResult, MislakaStatus, MislakaPerson
    pols = [
        MislakaPolicy(policy_id='P1', policy_number='1001', product_type='pension',
                      company_name='Harel', company_code='H', start_date='2015-01-01',
                      status='active', premium_monthly=900.0, cover_amount=0.0,
                      accumulated_value=250000.0, management_fee_percent=0.5,
                      investment_track='general', beneficiaries=['spouse']),
        MislakaPolicy(policy_id='P2', policy_number='1002', product_type='life',
                      company_name='Migdal', company_code='M', start_date='2019-06-01',
                      status='active', premium_monthly=120.0, cover_amount=500000.0),
    ] if policies else []
    return MislakaQueryResult(
        request_id='req-1', status=MislakaStatus.SUCCESS if policies else MislakaStatus.NOT_FOUND,
        timestamp=datetime.now().isoformat(), person=MislakaPerson(id_number='123456789'),
        policies=pols, total_policies=len(pols),
        total_accumulated=sum(p.accumulated_value for p in pols),
        total_monthly_premium=sum(p.premium_monthly for p in pols),
        error_message='' if policies else 'not found',
    )


@pytest.fixture
def mislaka(monkeypatch):
    import services.mislaka_api_service as mod
    fake = MagicMock()
    fake.is_configured.return_value = True
    fake.get_person_policies.return_value = _mislaka_result()
    monkeypatch.setattr(mod, '_mislaka_service', fake)
    return fake


def test_pension_import_parity_and_pii_handling(queue, reports_service, mislaka):
    register_all(queue)
    sync = pension_import_job.run_pension_import(id_number='123456789', user_id='CUST-P',
                                                 user_role='customer')
    assert sync['policies_count'] == 2

    job = pension_import_job.enqueue_pension_import(
        queue, id_number='123456789', user_id='CUST-P', user_role='customer', submitted_by='CUST-P')
    # The national ID never appears in the subject; the vault blob carries it.
    assert '123456789' not in job['subject_id']
    assert job['subject_id'] == pension_import_job.subject_id_for('123456789')
    assert 'id_number' not in job['input_params']
    assert '123456789' not in str(public_job_view(job))
    done = _run(queue, job)
    assert _stable(done['result']) == _stable(sync)
    assert done['result']['total_accumulated'] == 250000.0
    assert mislaka.get_person_policies.call_args_list[-1].args == ('123456789',)


def test_pension_import_vault_is_encrypted_when_key_set(queue, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv('PHINS_ENCRYPTION_KEY', Fernet.generate_key().decode('ascii'))
    job = pension_import_job.enqueue_pension_import(
        queue, id_number='987654321', user_id='u', user_role='customer', submitted_by='u')
    blob = job['input_params']['subject_vault']
    assert '"scheme": "fernet"' in blob
    assert '987654321' not in blob


def test_pension_import_typed_failures(queue, reports_service, mislaka):
    mislaka.is_configured.return_value = False
    with pytest.raises(pension_import_job.MislakaNotConfigured):
        pension_import_job.run_pension_import(id_number='1', user_id='u', user_role='customer')
    mislaka.is_configured.return_value = True
    mislaka.get_person_policies.return_value = _mislaka_result(policies=False)
    with pytest.raises(pension_import_job.NoPoliciesFound) as exc:
        pension_import_job.run_pension_import(id_number='1', user_id='u', user_role='customer')
    assert exc.value.message == 'not found'

    register_all(queue)
    job = pension_import_job.enqueue_pension_import(
        queue, id_number='1', user_id='u', user_role='customer', submitted_by='u')
    queue._update_job(job['id'], {'max_attempts': 1})
    assert queue.process_once()['dead_letter'] == 1
    assert queue.get_job(job['id'])['error_message'] == 'not found'


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
        'provider': 'gemini', 'provider_job_id': 'op-a3', 'status': 'queued',
        'message': 'Submitted to Gemini', 'provider_state': {'operation_name': 'op-a3'},
    }
    with patch.object(mod, 'get_media_generation_service', return_value=media):
        yield mod
    mod.MEDIA_GENERATION_AVAILABLE = original
    mod._video_agents_service = None
    mod._job_store = mod._JobStore()


def test_video_submit_parity(queue, video_mod):
    register_all(queue)
    params = {'campaign_id': 'MKT-A3', 'provider': 'gemini', 'pipeline_type': 'introductions',
              'poll_mode': 'webhook', 'title': 'Intro', 'submitted_by': 'media_ad'}
    sync = video_job.run_submit(**params)
    assert sync['job']['status'] == 'processing'

    job = video_job.enqueue_submit(queue, params=params, submitted_by='media_ad')
    assert job['max_attempts'] == 1  # provider submit is never retried
    assert job['subject_type'] == 'video_job'
    done = _run(queue, job)
    assert _stable(done['result']) == _stable(sync)
    assert done['result']['job']['provider_job_id'] == 'op-a3'
    assert done['result']['job']['submitted_by'] == 'media_ad'
    # Both submissions exist in the video job store (sync + async).
    assert len(video_mod._job_store.list_all()) == 2


def test_video_submit_validation_error_dead_letters_once(queue, video_mod):
    register_all(queue)
    job = video_job.enqueue_submit(queue, params={'provider': 'gemini', 'pipeline_type': 'nope'},
                                   submitted_by='media_ad')
    assert queue.process_once()['dead_letter'] == 1
    assert 'Unsupported pipeline type' in queue.get_job(job['id'])['error_message']


# ── SQLite round-trip for one adapter ─────────────────────────────────────────

def test_claims_adapter_round_trips_through_sqlite():
    from database import init_database
    from database.manager import DatabaseManager
    from database.models import DocumentProcessingJob

    init_database()
    db = DatabaseManager()
    ctx = _context()
    marker = f"CLM-A3-{os.getpid()}"
    ctx.claims[marker] = dict(ctx.claims['CLM-A3-1'], id=marker)
    try:
        q = AgentJobQueue(db_manager=db, poll_interval=0.01)
        register_all(q, ctx)
        job = claims_bot_job.enqueue_probability_report(
            q, claim_id=marker, claim=ctx.claims[marker], submitted_by='adjuster')
        done = _run(q, job)
        assert done['document_id'] is None
        assert done['subject_type'] == 'claim'
        assert done['result']['report']['claim_id'] == marker
        sync = claims_bot_job.response_body(
            ctx.sanitize_claim_report(claims_bot_job.generate_probability_report(ctx, marker)))
        assert _stable(done['result']) == _stable(sync)
    finally:
        try:
            session = db._ensure_session()
            session.query(DocumentProcessingJob).filter(
                DocumentProcessingJob.subject_id == marker).delete(synchronize_session=False)
            session.commit()
        finally:
            db.close()
