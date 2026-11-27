"""Reinsurance cession cash book (ERP/MGA integrity U10 / KTD5).

Treaty-driven ceded premium / claims / commission live here. Analytical
``_EXPENSE_WEIGHTS`` remain for planning/pitch only — live cession never
reads them as cash truth. ``analytical_divergence_report`` surfaces the
gap deliberately.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Mapping, Optional, Sequence

from services.mga import bordereaux as brd

SCHEMA = 'phins.mga_cession.v1'
DEFAULT_TREATY_ID = 'TRTY-DEFAULT'

_LOCK = threading.RLock()
_TREATIES: Dict[str, Dict[str, Any]] = {}
_ENTRIES: Dict[str, Dict[str, Any]] = {}

_CENT = Decimal('0.01')


def reset_cession_state() -> None:
    with _LOCK:
        _TREATIES.clear()
        _ENTRIES.clear()


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal('0.00')


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)


def _pct(value: Any) -> Decimal:
    try:
        raw = Decimal(str(value or 0))
    except Exception:
        return Decimal('0')
    # Accept 0.2 or 20 as 20%.
    if raw > 1:
        raw = raw / Decimal('100')
    return raw.quantize(Decimal('0.0001'))


def register_treaty(
    *,
    treaty_id: str = DEFAULT_TREATY_ID,
    name: str = 'Default quota share',
    quota_share: Any = '0.20',
    ceding_commission: Any = '0.05',
    binder_id: str = brd.DEFAULT_BINDER_ID,
    currency: str = 'USD',
    actor: str = 'cession',
) -> Dict[str, Any]:
    """Register or replace a treaty (cash book source of truth)."""
    tid = str(treaty_id or DEFAULT_TREATY_ID).strip() or DEFAULT_TREATY_ID
    row = {
        'id': tid,
        'name': str(name or tid),
        'quota_share': float(_pct(quota_share)),
        'ceding_commission': float(_pct(ceding_commission)),
        'binder_id': str(binder_id or brd.DEFAULT_BINDER_ID),
        'currency': str(currency or 'USD'),
        'actor': actor,
        'updated_at': _now_iso(),
        'cash_book': True,
        'analytical_expense_weights': False,
    }
    row['treaty_sha256'] = hashlib.sha256(_canonical(row).encode('utf-8')).hexdigest()
    with _LOCK:
        _TREATIES[tid] = dict(row)
    return dict(row)


def get_treaty(treaty_id: str = DEFAULT_TREATY_ID) -> Optional[Dict[str, Any]]:
    with _LOCK:
        row = _TREATIES.get(str(treaty_id or DEFAULT_TREATY_ID))
        return dict(row) if row else None


def list_treaties() -> List[Dict[str, Any]]:
    with _LOCK:
        return sorted((dict(v) for v in _TREATIES.values()), key=lambda r: str(r.get('id') or ''))


def ensure_default_treaty() -> Dict[str, Any]:
    existing = get_treaty(DEFAULT_TREATY_ID)
    if existing:
        return existing
    return register_treaty()


def _seal_entry(row: Mapping[str, Any]) -> Dict[str, Any]:
    body = {
        'schema': SCHEMA,
        'treaty_id': row.get('treaty_id'),
        'binder_id': row.get('binder_id'),
        'period_id': row.get('period_id'),
        'ceded_premium': row.get('ceded_premium'),
        'ceded_claims': row.get('ceded_claims'),
        'ceded_commission': row.get('ceded_commission'),
        'source_bordereau_id': row.get('source_bordereau_id'),
        'source_bordereau_sha256': row.get('source_bordereau_sha256'),
    }
    digest = hashlib.sha256(_canonical(body).encode('utf-8')).hexdigest()
    sealed = dict(row)
    sealed['schema'] = SCHEMA
    sealed['cession_sha256'] = digest
    sealed['id'] = f"CES-{row.get('treaty_id')}-{row.get('period_id')}-{digest[:12]}"
    return sealed


def verify_entry(row: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not isinstance(row, Mapping):
        return {'ok': False, 'reason': 'cession_missing'}
    expected = _seal_entry(row).get('cession_sha256')
    got = str(row.get('cession_sha256') or '')
    if not got or got != expected:
        return {'ok': False, 'reason': 'checksum_mismatch', 'expected': expected, 'got': got}
    return {'ok': True, 'checksum': got, 'id': row.get('id')}


def post_cession_from_bordereau(
    bordereau: Mapping[str, Any],
    *,
    treaty_id: str = DEFAULT_TREATY_ID,
    actor: str = 'cession',
) -> Dict[str, Any]:
    """Post ceded premium/claims/commission from a sealed bordereau + treaty."""
    check = brd.verify_bordereau(bordereau)
    if not check.get('ok'):
        return {'ok': False, 'reason': 'bordereau_not_intact', 'ae5': check}
    treaty = get_treaty(treaty_id) or ensure_default_treaty()
    qs = _pct(treaty.get('quota_share'))
    comm = _pct(treaty.get('ceding_commission'))
    # Carrier risk cash is the cession base — never expense-weight carve.
    premium_base = _money(
        (bordereau.get('streams') or {}).get('risk')
        if isinstance(bordereau.get('streams'), Mapping)
        else bordereau.get('carrier_payable')
    )
    claims_base = _money(bordereau.get('claims_paid'))
    ceded_premium = (premium_base * qs).quantize(_CENT, rounding=ROUND_HALF_UP)
    ceded_claims = (claims_base * qs).quantize(_CENT, rounding=ROUND_HALF_UP)
    ceded_commission = (ceded_premium * comm).quantize(_CENT, rounding=ROUND_HALF_UP)
    row = {
        'treaty_id': treaty.get('id'),
        'binder_id': str(bordereau.get('binder_id') or treaty.get('binder_id') or brd.DEFAULT_BINDER_ID),
        'period_id': str(bordereau.get('period_id') or ''),
        'ceded_premium': float(ceded_premium),
        'ceded_claims': float(ceded_claims),
        'ceded_commission': float(ceded_commission),
        'quota_share': float(qs),
        'ceding_commission_rate': float(comm),
        'source_bordereau_id': bordereau.get('id'),
        'source_bordereau_sha256': bordereau.get('bordereau_sha256'),
        'currency': str(bordereau.get('currency') or 'USD'),
        'actor': actor,
        'posted_at': _now_iso(),
        'source': 'treaty_cash_book',
    }
    sealed = _seal_entry(row)
    sealed['intact'] = verify_entry(sealed).get('ok') is True
    with _LOCK:
        # One entry per treaty/period (refresh in place).
        for eid, existing in list(_ENTRIES.items()):
            if (
                existing.get('treaty_id') == sealed.get('treaty_id')
                and existing.get('period_id') == sealed.get('period_id')
            ):
                if existing.get('cession_sha256') == sealed.get('cession_sha256'):
                    return {'ok': True, 'already': True, 'entry': dict(existing), 'treaty': treaty}
                _ENTRIES.pop(eid, None)
        _ENTRIES[str(sealed['id'])] = dict(sealed)
    return {'ok': True, 'entry': sealed, 'treaty': treaty}


def list_entries(
    *,
    binder_id: Optional[str] = None,
    period_id: Optional[str] = None,
    treaty_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    with _LOCK:
        rows = [dict(v) for v in _ENTRIES.values()]
    if binder_id:
        rows = [r for r in rows if r.get('binder_id') == binder_id]
    if period_id:
        rows = [r for r in rows if r.get('period_id') == period_id]
    if treaty_id:
        rows = [r for r in rows if r.get('treaty_id') == treaty_id]
    return sorted(rows, key=lambda r: str(r.get('id') or ''))


def cession_totals(
    *,
    binder_id: Optional[str] = None,
    period_id: Optional[str] = None,
) -> Dict[str, Any]:
    premium = Decimal('0.00')
    claims = Decimal('0.00')
    commission = Decimal('0.00')
    withheld = []
    for row in list_entries(binder_id=binder_id, period_id=period_id):
        check = verify_entry(row)
        if not check.get('ok'):
            withheld.append({'id': row.get('id'), 'reason': check.get('reason')})
            continue
        premium += _money(row.get('ceded_premium'))
        claims += _money(row.get('ceded_claims'))
        commission += _money(row.get('ceded_commission'))
    return {
        'ceded_premium': float(premium),
        'ceded_claims': float(claims),
        'ceded_commission': float(commission),
        'withheld': withheld,
    }


def analytical_divergence_report(
    *,
    expense_loading: Any,
    binder_id: Optional[str] = None,
    period_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare cession cash book to analytical ``_EXPENSE_WEIGHTS`` carve.

    Planning weights are labelled non-cash. Divergence is expected and
    reported — never closed by rewriting the cash book from weights.
    """
    from services.premium_flow_reconciliation import _EXPENSE_WEIGHTS

    loading = _money(expense_loading)
    weights = {name: Decimal(str(w)) for name, w in _EXPENSE_WEIGHTS}
    weight_sum = sum(weights.values(), Decimal('0'))
    analytical = {}
    if weight_sum > 0 and loading > 0:
        for name, w in weights.items():
            analytical[name] = float(
                (loading * w / weight_sum).quantize(_CENT, rounding=ROUND_HALF_UP)
            )
    else:
        analytical = {name: 0.0 for name in weights}

    cash = cession_totals(binder_id=binder_id, period_id=period_id)
    # Analytical "reinsurance_ceding_reserve" is the planning analogue of ceded cash.
    analytical_ri = _money(analytical.get('reinsurance_ceding_reserve'))
    cash_ri = _money(cash.get('ceded_premium'))
    delta = cash_ri - analytical_ri
    return {
        'ok': True,
        'labelled_non_cash': True,
        'analytical_source': '_EXPENSE_WEIGHTS',
        'analytical': analytical,
        'analytical_reinsurance_ceding_reserve': float(analytical_ri),
        'cash_book': cash,
        'cash_ceded_premium': float(cash_ri),
        'divergence': float(delta),
        'divergence_abs': float(abs(delta)),
        'cash_equals_analytical': abs(delta) <= Decimal('0.005'),
        'note': (
            'KTD5: analytical expense weights are planning-only; '
            'live cession cash comes from treaties + bordereaux'
        ),
        'reported_at': _now_iso(),
    }


__all__ = [
    'DEFAULT_TREATY_ID',
    'SCHEMA',
    'analytical_divergence_report',
    'cession_totals',
    'ensure_default_treaty',
    'get_treaty',
    'list_entries',
    'list_treaties',
    'post_cession_from_bordereau',
    'register_treaty',
    'reset_cession_state',
    'verify_entry',
]
