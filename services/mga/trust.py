"""Fiduciary trust sub-ledger (ERP/MGA integrity U10).

Premium risk cash held for the carrier sits on the trust book until
remittance settles. Trust Recon compares the trust TB to an optional bank
import and **flags** a deficit — it never invents cash to balance (plan
integrity: Trust Recon Agent is findings-only / fail-closed).
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Mapping, Optional, Sequence

from services.mga import bordereaux as brd

SCHEMA = 'phins.mga_trust.v1'
KIND_PREMIUM_HELD = 'premium_held'
KIND_REMITTANCE_RELEASED = 'remittance_released'
KIND_ADJUSTMENT = 'adjustment'  # audited only; never silent fill

_LOCK = threading.RLock()
# movement_id -> sealed movement
_MOVEMENTS: Dict[str, Dict[str, Any]] = {}
# binder_id -> last bank import snapshot (optional)
_BANK: Dict[str, Dict[str, Any]] = {}

_CENT = Decimal('0.01')


def reset_trust_state() -> None:
    with _LOCK:
        _MOVEMENTS.clear()
        _BANK.clear()


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal('0.00')


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)


def _seal(row: Mapping[str, Any]) -> Dict[str, Any]:
    body = {
        'schema': SCHEMA,
        'binder_id': row.get('binder_id'),
        'period_id': row.get('period_id'),
        'kind': row.get('kind'),
        'amount': row.get('amount'),
        'currency': row.get('currency'),
        'ref_type': row.get('ref_type'),
        'ref_id': row.get('ref_id'),
        'signed': row.get('signed'),
    }
    digest = hashlib.sha256(_canonical(body).encode('utf-8')).hexdigest()
    sealed = dict(row)
    sealed['schema'] = SCHEMA
    sealed['movement_sha256'] = digest
    sealed['id'] = f"TRM-{row.get('binder_id')}-{digest[:12]}"
    return sealed


def verify_movement(row: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(row, Mapping):
        return {'ok': False, 'reason': 'movement_missing'}
    expected = _seal(row).get('movement_sha256')
    got = str(row.get('movement_sha256') or '')
    if not got or got != expected:
        return {'ok': False, 'reason': 'checksum_mismatch', 'expected': expected, 'got': got}
    return {'ok': True, 'checksum': got, 'id': row.get('id')}


def record_movement(
    *,
    binder_id: str = brd.DEFAULT_BINDER_ID,
    period_id: str,
    kind: str,
    amount: Any,
    signed: int,
    currency: str = 'USD',
    ref_type: str = '',
    ref_id: str = '',
    actor: str = 'trust',
    note: str = '',
) -> Dict[str, Any]:
    """Append a sealed trust movement. ``signed`` is +1 credit / -1 debit."""
    binder = str(binder_id or brd.DEFAULT_BINDER_ID).strip() or brd.DEFAULT_BINDER_ID
    kind_n = str(kind or '').strip().lower()
    if kind_n not in (KIND_PREMIUM_HELD, KIND_REMITTANCE_RELEASED, KIND_ADJUSTMENT):
        raise ValueError(f'unknown trust kind: {kind!r}')
    sign = 1 if int(signed) >= 0 else -1
    cash = abs(_money(amount))
    if cash <= 0 and kind_n != KIND_ADJUSTMENT:
        raise ValueError('trust amount must be positive')
    row = {
        'binder_id': binder,
        'period_id': str(period_id),
        'kind': kind_n,
        'amount': float(cash),
        'signed': sign,
        'signed_amount': float(cash * sign),
        'currency': str(currency or 'USD'),
        'ref_type': str(ref_type or ''),
        'ref_id': str(ref_id or ''),
        'actor': actor,
        'note': str(note or ''),
        'recorded_at': _now_iso(),
    }
    sealed = _seal(row)
    check = verify_movement(sealed)
    sealed['intact'] = bool(check.get('ok'))
    with _LOCK:
        # Idempotent on (binder, period, kind, ref_id, amount, signed).
        for existing in _MOVEMENTS.values():
            if (
                existing.get('binder_id') == binder
                and existing.get('period_id') == str(period_id)
                and existing.get('kind') == kind_n
                and existing.get('ref_id') == sealed.get('ref_id')
                and existing.get('movement_sha256') == sealed.get('movement_sha256')
            ):
                return {'ok': True, 'already': True, 'movement': dict(existing)}
        _MOVEMENTS[str(sealed['id'])] = dict(sealed)
    return {'ok': True, 'movement': sealed}


def hold_premium_from_bordereau(
    bordereau: Mapping[str, Any],
    *,
    actor: str = 'trust',
) -> Dict[str, Any]:
    """Credit trust with carrier risk cash from a sealed bordereau."""
    check = brd.verify_bordereau(bordereau)
    if not check.get('ok'):
        return {'ok': False, 'reason': 'bordereau_not_intact', 'ae5': check}
    amount = _money(bordereau.get('carrier_payable') or bordereau.get('streams', {}).get('risk'))
    return record_movement(
        binder_id=str(bordereau.get('binder_id') or brd.DEFAULT_BINDER_ID),
        period_id=str(bordereau.get('period_id') or ''),
        kind=KIND_PREMIUM_HELD,
        amount=amount,
        signed=+1,
        currency=str(bordereau.get('currency') or 'USD'),
        ref_type='bordereau',
        ref_id=str(bordereau.get('id') or ''),
        actor=actor,
        note='carrier risk cash held pending remittance',
    )


def release_on_remittance(
    run: Mapping[str, Any],
    *,
    actor: str = 'trust',
) -> Dict[str, Any]:
    """Debit trust when a remittance run settles (cash leaves trust)."""
    amount = _money(run.get('amount'))
    return record_movement(
        binder_id=str(run.get('binder_id') or brd.DEFAULT_BINDER_ID),
        period_id=str(run.get('period_id') or ''),
        kind=KIND_REMITTANCE_RELEASED,
        amount=amount,
        signed=-1,
        currency=str(run.get('currency') or 'USD'),
        ref_type='remittance_run',
        ref_id=str(run.get('id') or ''),
        actor=actor,
        note='released to carrier on remittance settle',
    )


def list_movements(
    *,
    binder_id: Optional[str] = None,
    period_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    with _LOCK:
        rows = [dict(v) for v in _MOVEMENTS.values()]
    if binder_id:
        rows = [r for r in rows if r.get('binder_id') == binder_id]
    if period_id:
        rows = [r for r in rows if r.get('period_id') == period_id]
    return sorted(rows, key=lambda r: str(r.get('recorded_at') or '') + str(r.get('id') or ''))


def trust_balance(*, binder_id: str = brd.DEFAULT_BINDER_ID) -> Dict[str, Any]:
    """Sum sealed movements for binder; broken seals are withheld from the total."""
    binder = str(binder_id or brd.DEFAULT_BINDER_ID)
    held = Decimal('0.00')
    released = Decimal('0.00')
    withheld = []
    for row in list_movements(binder_id=binder):
        check = verify_movement(row)
        if not check.get('ok'):
            withheld.append({'id': row.get('id'), 'reason': check.get('reason')})
            continue
        signed_amt = _money(row.get('signed_amount'))
        if row.get('kind') == KIND_PREMIUM_HELD:
            held += abs(signed_amt)
        elif row.get('kind') == KIND_REMITTANCE_RELEASED:
            released += abs(signed_amt)
        else:
            # Adjustments contribute with sign; still never invent balancing cash.
            if signed_amt >= 0:
                held += signed_amt
            else:
                released += abs(signed_amt)
    balance = held - released
    return {
        'binder_id': binder,
        'premium_held': float(held),
        'remittance_released': float(released),
        'balance': float(balance),
        'withheld_movements': withheld,
        'currency': 'USD',
    }


def record_bank_import(
    *,
    binder_id: str = brd.DEFAULT_BINDER_ID,
    balance: Any,
    as_of: Optional[str] = None,
    source: str = 'bank_import',
    actor: str = 'trust_recon',
) -> Dict[str, Any]:
    """Store an optional bank balance for Trust Recon (read-side only)."""
    binder = str(binder_id or brd.DEFAULT_BINDER_ID)
    row = {
        'binder_id': binder,
        'balance': float(_money(balance)),
        'as_of': as_of or _now_iso(),
        'source': str(source or 'bank_import'),
        'actor': actor,
        'recorded_at': _now_iso(),
    }
    row['bank_sha256'] = hashlib.sha256(_canonical(row).encode('utf-8')).hexdigest()
    with _LOCK:
        _BANK[binder] = dict(row)
    return {'ok': True, 'bank': row}


def get_bank_import(binder_id: str = brd.DEFAULT_BINDER_ID) -> Optional[Dict[str, Any]]:
    with _LOCK:
        row = _BANK.get(str(binder_id or brd.DEFAULT_BINDER_ID))
        return dict(row) if row else None


def reconcile_trust(
    *,
    binder_id: str = brd.DEFAULT_BINDER_ID,
    bank_balance: Optional[Any] = None,
) -> Dict[str, Any]:
    """Trust Recon — findings only. Never invents cash to close a deficit."""
    tb = trust_balance(binder_id=binder_id)
    book = _money(tb.get('balance'))
    bank_row = None
    if bank_balance is not None:
        bank = _money(bank_balance)
    else:
        bank_row = get_bank_import(binder_id)
        bank = _money(bank_row.get('balance')) if bank_row else None

    findings: List[Dict[str, Any]] = []
    if tb.get('withheld_movements'):
        findings.append({
            'code': 'trust_seal_withheld',
            'severity': 'high',
            'detail': tb['withheld_movements'],
        })
    if bank is None:
        findings.append({
            'code': 'bank_balance_unavailable',
            'severity': 'info',
            'detail': 'no bank import; trust TB reported without bank tie',
        })
        deficit = None
        ok = not any(f['code'] == 'trust_seal_withheld' for f in findings)
    else:
        # Positive gap = trust books exceed bank (bank short → deficit).
        gap = book - bank
        if abs(gap) > Decimal('0.005'):
            # Fail closed: report deficit/surplus; do NOT post a balancing row.
            is_deficit = gap > 0
            findings.append({
                'code': 'trust_deficit' if is_deficit else 'trust_surplus',
                'severity': 'high' if is_deficit else 'warn',
                'trust_balance': float(book),
                'bank_balance': float(bank),
                'delta': float(gap),
                'auto_fill': False,
                'note': 'Trust Recon never invents cash to balance',
            })
        deficit = gap
        ok = abs(gap) <= Decimal('0.005') and not any(
            f['code'] == 'trust_seal_withheld' for f in findings
        )

    report = {
        'ok': ok,
        'binder_id': str(binder_id or brd.DEFAULT_BINDER_ID),
        'trust': tb,
        'bank': {
            'balance': float(bank) if bank is not None else None,
            'import': bank_row,
        },
        'deficit': float(deficit) if deficit is not None else None,
        'findings': findings,
        'auto_fill_forbidden': True,
        'reconciled_at': _now_iso(),
    }
    report['report_sha256'] = hashlib.sha256(
        _canonical({k: v for k, v in report.items() if k != 'report_sha256'}).encode('utf-8')
    ).hexdigest()
    return report


def trial_balance(*, binder_id: str = brd.DEFAULT_BINDER_ID) -> Dict[str, Any]:
    """Four-line trust TB: held, released, balance, bank (if present)."""
    recon = reconcile_trust(binder_id=binder_id)
    tb = recon['trust']
    return {
        'binder_id': tb['binder_id'],
        'lines': [
            {'account': 'premium_held', 'credit': tb['premium_held'], 'debit': 0.0},
            {'account': 'remittance_released', 'credit': 0.0, 'debit': tb['remittance_released']},
            {'account': 'trust_balance', 'net': tb['balance']},
            {
                'account': 'bank',
                'balance': recon['bank']['balance'],
            },
        ],
        'ok': recon['ok'],
        'findings': recon['findings'],
        'report_sha256': recon['report_sha256'],
    }


__all__ = [
    'KIND_ADJUSTMENT',
    'KIND_PREMIUM_HELD',
    'KIND_REMITTANCE_RELEASED',
    'SCHEMA',
    'get_bank_import',
    'hold_premium_from_bordereau',
    'list_movements',
    'record_bank_import',
    'record_movement',
    'reconcile_trust',
    'release_on_remittance',
    'reset_trust_state',
    'trial_balance',
    'trust_balance',
    'verify_movement',
]
