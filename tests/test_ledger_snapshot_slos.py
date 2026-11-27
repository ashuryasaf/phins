"""U14 — incremental ledger snapshots + job-queue DLQ / pending-age SLOs."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from services.agent_job_queue import AgentJobQueue
from services.erp.integrity_scorecard import compute_integrity_scorecard
from services.jobs import durability_guard_job
from services import ledger_snapshot_store as lss


def test_incremental_shards_when_full_would_over_cap():
    snapshot = {
        'saved_at': '2026-11-28T00:00:00Z',
        'version': 1,
        'health_wallets': {'CUST-1': {'balance': 10.0}},
        'wallet_withdrawals': {'W1': {'amount': 1.0}},
        'algo_balances': {'x': 'y' * 100},
    }
    # Tiny cap forces incremental sharding rather than a silent freeze.
    pack = lss.build_incremental_shards(snapshot, max_bytes=80)
    assert pack['index']['incremental'] is True
    assert pack['index']['format'] == lss.FORMAT_INCREMENTAL
    assert 'health_wallets' in pack['shards'] or pack['oversize_keys']
    # Authoritative keys stay omitted from the write set.
    assert 'policies' not in pack['shards']


def test_incremental_enabled_flag():
    assert lss.incremental_enabled() is True


def test_queue_slo_alerts_on_dlq_and_pending_age():
    queue = AgentJobQueue(db_manager=None)
    # Seed a dead-letter and an old pending job directly.
    old = datetime.utcnow() - timedelta(hours=2)
    with queue._lock:
        queue._inmemory_jobs.append({
            'id': 'JOB-DLQ-1',
            'job_type': 't',
            'subject_type': 's',
            'subject_id': '1',
            'status': 'dead_letter',
            'created_date': old,
            'submitted_by': 'test',
            'attempts': 3,
            'input_params': {},
            'result': None,
            'document_id': None,
            'priority': 100,
            'idempotency_key': None,
            'max_attempts': 3,
            'next_retry_at': None,
            'error_message': 'boom',
            'worker_id': None,
            'completed_date': None,
        })
        queue._inmemory_jobs.append({
            'id': 'JOB-PEND-1',
            'job_type': 't',
            'subject_type': 's',
            'subject_id': '2',
            'status': 'pending',
            'created_date': old,
            'submitted_by': 'test',
            'attempts': 0,
            'input_params': {},
            'result': None,
            'document_id': None,
            'priority': 100,
            'idempotency_key': None,
            'max_attempts': 3,
            'next_retry_at': None,
            'error_message': None,
            'worker_id': None,
            'completed_date': None,
        })
    report = queue.slo_report(
        pending_age_alert_seconds=60,
        dlq_depth_alert=1,
    )
    assert report['dead_letter_count'] >= 1
    assert report['oldest_pending_age_seconds'] >= 60
    codes = [a['code'] for a in report['alerts']]
    assert 'dlq_depth' in codes
    assert 'pending_age' in codes
    assert report['ok'] is False


def test_durability_guard_probe_never_rewrites_customer_money():
    snap = {
        'health_wallets': {
            'CUST-REAL': {'id': 'CUST-REAL', 'balance': 42.0},
        },
        'wallet_withdrawals': {},
        'nft_ledger': {},
        'investment_accounts': {},
    }
    before_balance = snap['health_wallets']['CUST-REAL']['balance']
    report = durability_guard_job.run_once(actor='test', snapshot=snap)
    assert report['ok'] is True
    assert report['rewrites_customer_money'] is False
    assert 'CUST-REAL' in snap['health_wallets']
    assert snap['health_wallets']['CUST-REAL']['balance'] == before_balance
    assert durability_guard_job.PROBE_ID not in snap['health_wallets']


def test_scorecard_u14_landed_on_this_checkout():
    report = compute_integrity_scorecard()
    by_id = {u['unit_id']: u for u in report['units']}
    assert by_id['U14']['status'] == 'landed', by_id['U14']
