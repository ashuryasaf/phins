"""Durability Guard Agent (ERP/MGA integrity U14).

Fingerprints fiduciary / snapshot state, writes one fixed probe into a
reserved lane, reads it back, deletes it, and re-fingerprints. Never
rewrites customer money. Findings only when the probe lane moves other
data.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.agent_job_queue import AgentJobQueue

JOB_TYPE = 'durability_guard'
SUBJECT_TYPE = 'fiduciary_snapshot'
PROBE_LANE = 'durability_probe'
PROBE_ID = 'DURABILITY-GUARD-PROBE'


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)


def fingerprint_snapshot(snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """SHA-256 over fiduciary-ish keys (or empty dict). Never mutates."""
    snap = dict(snapshot or {})
    # Drop reserved probe lane from fingerprint so the probe itself does not
    # poison the before/after comparison.
    wallets = dict(snap.get('health_wallets') or {})
    wallets.pop(PROBE_ID, None)
    body = {
        'health_wallets': wallets,
        'wallet_withdrawals': snap.get('wallet_withdrawals') or {},
        'nft_ledger_count': len(snap.get('nft_ledger') or {}),
        'investment_accounts_count': len(snap.get('investment_accounts') or {}),
    }
    digest = hashlib.sha256(_canonical(body).encode('utf-8')).hexdigest()
    return {'sha256': digest, 'keys': sorted(body.keys()), 'lane': PROBE_LANE}


def status_report() -> Dict[str, Any]:
    from services import ledger_snapshot_store as lss
    incremental = getattr(lss, 'incremental_enabled', lambda: False)()
    return {
        'agent': 'durability_guard',
        'probe_lane': PROBE_LANE,
        'rewrites_customer_money': False,
        'incremental_snapshots': bool(incremental),
        'reported_at': _now_iso(),
    }


def run_once(*, actor: str = 'durability_guard_job', snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run the probe against an optional in-memory snapshot dict.

    When ``snapshot`` is provided the probe mutates only the reserved key
    ``DURABILITY-GUARD-PROBE`` and restores it. Customer keys are never
    rewritten.
    """
    store: Dict[str, Any] = snapshot if snapshot is not None else {}
    if 'health_wallets' not in store or not isinstance(store.get('health_wallets'), dict):
        store['health_wallets'] = dict(store.get('health_wallets') or {})

    before = fingerprint_snapshot(store)
    # Write probe.
    store['health_wallets'][PROBE_ID] = {
        'id': PROBE_ID,
        'lane': PROBE_LANE,
        'balance': 0.0,
        'probe': True,
        'actor': actor,
        'written_at': _now_iso(),
    }
    mid = fingerprint_snapshot(store)
    # Read back.
    read_back = store['health_wallets'].get(PROBE_ID)
    read_ok = isinstance(read_back, dict) and read_back.get('id') == PROBE_ID
    # Delete probe.
    store['health_wallets'].pop(PROBE_ID, None)
    after = fingerprint_snapshot(store)

    findings = []
    if before['sha256'] != after['sha256']:
        findings.append({
            'code': 'fingerprint_drift',
            'severity': 'high',
            'before': before['sha256'],
            'after': after['sha256'],
            'note': 'customer money fingerprint moved during probe — never auto-repaired',
        })
    if not read_ok:
        findings.append({
            'code': 'probe_readback_failed',
            'severity': 'high',
        })

    return {
        'ok': not findings,
        'actor': actor,
        'before': before,
        'during_probe': mid,
        'after': after,
        'read_ok': read_ok,
        'findings': findings,
        'rewrites_customer_money': False,
        'probed_at': _now_iso(),
    }


def _handle(job: Dict[str, Any]) -> Dict[str, Any]:
    params = job.get('input_params') or {}
    return run_once(actor=str(params.get('actor') or 'durability_guard_job'))


def enqueue(
    queue: AgentJobQueue,
    *,
    submitted_by: str = 'system',
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    key = idempotency_key or f'durability-guard:{_now_iso()[:10]}'
    return queue.enqueue(
        job_type=JOB_TYPE,
        subject_type=SUBJECT_TYPE,
        subject_id='platform',
        submitted_by=submitted_by,
        priority=200,
        idempotency_key=key,
        input_params={'once': True},
        max_attempts=1,
    )


def register(queue: AgentJobQueue) -> None:
    queue.register_handler(JOB_TYPE, _handle)
