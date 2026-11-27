"""Premium tax accrual engine (ERP/MGA integrity U11).

Tax accrues on collected premium as an **additive** GL obligation. It never
rewrites billed premium, kernel pins, or carrier remittance cash. Jurisdiction
rules are explicit; a missing jurisdiction accrues nothing (fail closed).
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Mapping, Optional

from services.mga import bordereaux as brd

SCHEMA = 'phins.mga_premium_tax.v1'

# Jurisdiction → rate (fraction). Additive only — never a premium rewrite.
JURISDICTION_RATES: Dict[str, Decimal] = {
    'IL': Decimal('0.01'),       # Israel stamp / premium tax specimen
    'US-CA': Decimal('0.0235'),  # California surplus-lines style specimen
    'US-NY': Decimal('0.036'),
    'CY': Decimal('0.015'),
}

_LOCK = threading.RLock()
_ACCRUALS: Dict[str, Dict[str, Any]] = {}

_CENT = Decimal('0.01')


def reset_premium_tax_state() -> None:
    with _LOCK:
        _ACCRUALS.clear()


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal('0.00')


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)


def normalize_jurisdiction(value: Any) -> str:
    raw = str(value or '').strip().upper().replace('_', '-')
    if raw in JURISDICTION_RATES:
        return raw
    # Common aliases
    aliases = {
        'ISRAEL': 'IL',
        'ISR': 'IL',
        'CA': 'US-CA',
        'CALIFORNIA': 'US-CA',
        'NY': 'US-NY',
        'NEW-YORK': 'US-NY',
        'CYPRUS': 'CY',
    }
    return aliases.get(raw, raw)


def rate_for(jurisdiction: Any) -> Optional[Decimal]:
    key = normalize_jurisdiction(jurisdiction)
    return JURISDICTION_RATES.get(key)


def list_jurisdictions() -> List[Dict[str, Any]]:
    return [
        {'jurisdiction': code, 'rate': float(rate), 'additive': True}
        for code, rate in sorted(JURISDICTION_RATES.items())
    ]


def _seal(row: Mapping[str, Any]) -> Dict[str, Any]:
    body = {
        'schema': SCHEMA,
        'jurisdiction': row.get('jurisdiction'),
        'binder_id': row.get('binder_id'),
        'period_id': row.get('period_id'),
        'taxable_premium': row.get('taxable_premium'),
        'rate': row.get('rate'),
        'tax_amount': row.get('tax_amount'),
        'source_bordereau_id': row.get('source_bordereau_id'),
        'billed_premium_unchanged': True,
    }
    digest = hashlib.sha256(_canonical(body).encode('utf-8')).hexdigest()
    sealed = dict(row)
    sealed['schema'] = SCHEMA
    sealed['tax_sha256'] = digest
    sealed['id'] = f"TAX-{row.get('jurisdiction')}-{row.get('period_id')}-{digest[:12]}"
    return sealed


def verify_accrual(row: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(row, Mapping):
        return {'ok': False, 'reason': 'accrual_missing'}
    expected = _seal(row).get('tax_sha256')
    got = str(row.get('tax_sha256') or '')
    if not got or got != expected:
        return {'ok': False, 'reason': 'checksum_mismatch', 'expected': expected, 'got': got}
    if row.get('billed_premium_unchanged') is not True:
        return {'ok': False, 'reason': 'billed_premium_guard_missing'}
    return {'ok': True, 'checksum': got, 'id': row.get('id')}


def accrue_from_bordereau(
    bordereau: Mapping[str, Any],
    *,
    jurisdiction: Any,
    actor: str = 'premium_tax',
    engine: Any = None,
) -> Dict[str, Any]:
    """Accrue additive premium tax from sealed bordereau premium cash.

    Never mutates ``annual_premium``, bills, or kernel pins. Optional
    ``engine`` receives a descriptive GL note only when provided — the
    billed premium path is untouched.
    """
    check = brd.verify_bordereau(bordereau)
    if not check.get('ok'):
        return {'ok': False, 'reason': 'bordereau_not_intact', 'ae5': check}
    jur = normalize_jurisdiction(jurisdiction)
    rate = rate_for(jur)
    if rate is None:
        return {
            'ok': False,
            'reason': 'jurisdiction_unknown',
            'jurisdiction': jur,
            'known': sorted(JURISDICTION_RATES),
        }
    taxable = _money(bordereau.get('premium_cash'))
    tax_amount = (taxable * rate).quantize(_CENT, rounding=ROUND_HALF_UP)
    row = {
        'jurisdiction': jur,
        'binder_id': str(bordereau.get('binder_id') or brd.DEFAULT_BINDER_ID),
        'period_id': str(bordereau.get('period_id') or ''),
        'taxable_premium': float(taxable),
        'rate': float(rate),
        'tax_amount': float(tax_amount),
        'currency': str(bordereau.get('currency') or 'USD'),
        'source_bordereau_id': bordereau.get('id'),
        'source_bordereau_sha256': bordereau.get('bordereau_sha256'),
        'billed_premium_unchanged': True,
        'additive_gl': True,
        'status': 'accrued',
        'actor': actor,
        'accrued_at': _now_iso(),
        'remitted_at': None,
    }
    sealed = _seal(row)
    sealed['intact'] = verify_accrual(sealed).get('ok') is True
    gl_post = None
    if engine is not None and tax_amount > 0 and hasattr(engine, '_create_ledger_entry'):
        # Additive operating accrual only — never a premium rewrite.
        try:
            from accounting_engine import AccountType, EntryType
            from datetime import date as date_cls
            entry = engine._create_ledger_entry(
                allocation_id=f"TAX-{sealed['id']}",
                policy_id='TAX-ACCRUAL',
                customer_id='TAX-ACCRUAL',
                entry_date=date_cls.today(),
                entry_type=EntryType.FEE_APPLIED,
                account_type=AccountType.OPERATING,
                debit_amount=tax_amount,
                description=f'premium_tax_accrual {jur} additive',
                reference_no=str(sealed['id']),
            )
            gl_post = {
                'ok': True,
                'entry_id': getattr(entry, 'entry_id', None) or getattr(entry, 'id', None),
            }
        except Exception as exc:
            # Tax accrual record still stands; GL post failure is reported.
            gl_post = {'ok': False, 'error': str(exc)}
    sealed['gl_post'] = gl_post
    with _LOCK:
        for eid, existing in list(_ACCRUALS.items()):
            if (
                existing.get('jurisdiction') == sealed.get('jurisdiction')
                and existing.get('period_id') == sealed.get('period_id')
                and existing.get('binder_id') == sealed.get('binder_id')
            ):
                if existing.get('tax_sha256') == sealed.get('tax_sha256'):
                    return {'ok': True, 'already': True, 'accrual': dict(existing)}
                # Refresh unpaid accrual in place; never rewrite billed premium.
                if existing.get('status') == 'remitted':
                    return {
                        'ok': False,
                        'reason': 'tax_already_remitted',
                        'accrual': dict(existing),
                    }
                _ACCRUALS.pop(eid, None)
        _ACCRUALS[str(sealed['id'])] = dict(sealed)
    return {'ok': True, 'accrual': sealed, 'billed_premium_rewritten': False}


def mark_remitted(accrual_id: str, *, actor: str = 'premium_tax') -> Dict[str, Any]:
    with _LOCK:
        row = _ACCRUALS.get(str(accrual_id or '').strip())
        if row is None:
            return {'ok': False, 'reason': 'accrual_not_found'}
        if row.get('status') == 'remitted':
            return {'ok': True, 'already': True, 'accrual': dict(row)}
        updated = dict(row)
        updated['status'] = 'remitted'
        updated['remitted_at'] = _now_iso()
        updated['remitted_by'] = actor
        # Re-seal without changing tax_amount / taxable_premium.
        body = {
            'schema': SCHEMA,
            'jurisdiction': updated.get('jurisdiction'),
            'binder_id': updated.get('binder_id'),
            'period_id': updated.get('period_id'),
            'taxable_premium': updated.get('taxable_premium'),
            'rate': updated.get('rate'),
            'tax_amount': updated.get('tax_amount'),
            'source_bordereau_id': updated.get('source_bordereau_id'),
            'billed_premium_unchanged': True,
        }
        updated['tax_sha256'] = hashlib.sha256(_canonical(body).encode('utf-8')).hexdigest()
        _ACCRUALS[updated['id']] = updated
        return {'ok': True, 'accrual': dict(updated)}


def list_accruals(
    *,
    binder_id: Optional[str] = None,
    period_id: Optional[str] = None,
    jurisdiction: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    with _LOCK:
        rows = [dict(v) for v in _ACCRUALS.values()]
    if binder_id:
        rows = [r for r in rows if r.get('binder_id') == binder_id]
    if period_id:
        rows = [r for r in rows if r.get('period_id') == period_id]
    if jurisdiction:
        jur = normalize_jurisdiction(jurisdiction)
        rows = [r for r in rows if r.get('jurisdiction') == jur]
    if status:
        rows = [r for r in rows if r.get('status') == status]
    return sorted(rows, key=lambda r: str(r.get('id') or ''))


def remittance_schedule(
    *,
    binder_id: Optional[str] = None,
    period_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Tax due / remitted schedule — additive obligations only."""
    accrued = list_accruals(binder_id=binder_id, period_id=period_id, status='accrued')
    remitted = list_accruals(binder_id=binder_id, period_id=period_id, status='remitted')
    due = sum((_money(r.get('tax_amount')) for r in accrued), Decimal('0.00'))
    paid = sum((_money(r.get('tax_amount')) for r in remitted), Decimal('0.00'))
    return {
        'due': float(due),
        'remitted': float(paid),
        'outstanding': float(due),
        'accrued_rows': accrued,
        'remitted_rows': remitted,
        'billed_premium_rewritten': False,
        'additive_only': True,
    }


__all__ = [
    'JURISDICTION_RATES',
    'SCHEMA',
    'accrue_from_bordereau',
    'list_accruals',
    'list_jurisdictions',
    'mark_remitted',
    'normalize_jurisdiction',
    'rate_for',
    'remittance_schedule',
    'reset_premium_tax_state',
    'verify_accrual',
]
