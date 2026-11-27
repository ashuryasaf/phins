"""Sealed premium / claims / commission bordereaux (ERP/MGA integrity U9 / AE5).

A bordereau for binder B / period M is built from kernel pins + customer-
ledger premium cash + paid claims for that binder's policies. The sealed
premium total must equal ledger premium cash for those policies to the
cent (AE5). Analytical expense weights are never used as cash truth.
"""

from __future__ import annotations

import hashlib
import json
import threading
from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

DEFAULT_BINDER_ID = 'PHINS-DEFAULT'
SCHEMA = 'phins.mga_bordereau.v1'

_LOCK = threading.RLock()
# id -> sealed bordereau
_STORE: Dict[str, Dict[str, Any]] = {}

_CENT = Decimal('0.01')


def reset_bordereaux_state() -> None:
    """Clear in-memory bordereaux (tests)."""
    with _LOCK:
        _STORE.clear()


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal('0.00')


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)


def binder_of(policy: Optional[Mapping[str, Any]]) -> str:
    if not isinstance(policy, Mapping):
        return DEFAULT_BINDER_ID
    raw = str(policy.get('binder_id') or policy.get('entity_id') or '').strip()
    return raw or DEFAULT_BINDER_ID


def parse_period_id(period_id: str) -> Tuple[int, int]:
    raw = str(period_id or '').strip()
    parts = raw.split('-')
    if len(parts) != 2:
        raise ValueError(f'invalid period_id: {period_id!r}')
    year, month = int(parts[0]), int(parts[1])
    if month < 1 or month > 12:
        raise ValueError(f'invalid period month: {period_id!r}')
    return year, month


def period_bounds(period_id: str) -> Tuple[date, date]:
    year, month = parse_period_id(period_id)
    last = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _as_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _tx_type(tx: Mapping[str, Any]) -> str:
    return str(tx.get('type') or tx.get('transaction_type') or tx.get('kind') or '').strip().lower()


def _tx_amount(tx: Mapping[str, Any]) -> Decimal:
    for key in ('amount', 'cash_amount', 'value'):
        if tx.get(key) is not None:
            return abs(_money(tx.get(key)))
    return Decimal('0.00')


def _tx_meta(tx: Mapping[str, Any]) -> Dict[str, Any]:
    meta = tx.get('metadata')
    return dict(meta) if isinstance(meta, dict) else {}


def _policy_id_of_tx(
    tx: Mapping[str, Any],
    *,
    policies: Mapping[str, Any],
    billing: Optional[Mapping[str, Any]] = None,
) -> str:
    meta = _tx_meta(tx)
    pid = str(meta.get('policy_id') or tx.get('policy_id') or '').strip()
    if pid:
        return pid
    bill_id = str(meta.get('bill_id') or tx.get('bill_id') or '').strip()
    if bill_id and isinstance(billing, Mapping):
        bill = billing.get(bill_id) or {}
        if isinstance(bill, Mapping):
            return str(bill.get('policy_id') or '').strip()
    return ''


def _in_period(stamp: Any, start: date, end: date) -> bool:
    d = _as_date(stamp)
    if d is None:
        return False
    return start <= d <= end


def _seal_body(pack: Mapping[str, Any]) -> Dict[str, Any]:
    # AE5 cash body only — built_at/actor stay off the seal so a rebuild with
    # the same cash is content-addressed (same id / digest; no duplicate run).
    return {
        'schema': SCHEMA,
        'binder_id': pack.get('binder_id'),
        'period_id': pack.get('period_id'),
        'currency': pack.get('currency'),
        'premium_cash': pack.get('premium_cash'),
        'claims_paid': pack.get('claims_paid'),
        'commission': pack.get('commission'),
        'carrier_payable': pack.get('carrier_payable'),
        'lines': pack.get('lines') or [],
        'policy_ids': pack.get('policy_ids') or [],
        'streams': pack.get('streams') or {},
    }


def seal_bordereau(pack: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a copy with ``bordereau_sha256`` over the AE5 body."""
    sealed = dict(pack)
    sealed.pop('bordereau_sha256', None)
    sealed.pop('id', None)
    sealed['schema'] = SCHEMA
    digest = hashlib.sha256(_canonical(_seal_body(sealed)).encode('utf-8')).hexdigest()
    sealed['bordereau_sha256'] = digest
    sealed['id'] = (
        f"BRD-{sealed.get('binder_id')}-{sealed.get('period_id')}-{digest[:12]}"
    )
    return sealed


def verify_bordereau(pack: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Recompute the seal; refuse a tampered or cent-mismatched bordereau."""
    if not isinstance(pack, Mapping):
        return {'ok': False, 'reason': 'bordereau_missing'}
    expected = seal_bordereau(pack).get('bordereau_sha256')
    got = str(pack.get('bordereau_sha256') or '')
    if not got or got != expected:
        return {
            'ok': False,
            'reason': 'checksum_mismatch',
            'expected': expected,
            'got': got,
        }
    # AE5: sealed premium_cash must equal the sum of premium lines.
    lines = pack.get('lines') or []
    premium_lines = [
        _money(row.get('amount'))
        for row in lines
        if isinstance(row, dict) and str(row.get('kind') or '') == 'premium'
    ]
    line_sum = sum(premium_lines, Decimal('0.00'))
    premium_cash = _money(pack.get('premium_cash'))
    if abs(line_sum - premium_cash) > Decimal('0.005'):
        return {
            'ok': False,
            'reason': 'ae5_premium_cent_mismatch',
            'premium_cash': float(premium_cash),
            'lines_sum': float(line_sum),
        }
    return {'ok': True, 'checksum': got, 'id': pack.get('id')}


def build_bordereau(
    *,
    binder_id: str = DEFAULT_BINDER_ID,
    period_id: str,
    policies: Optional[Mapping[str, Any]] = None,
    ledger_transactions: Optional[Iterable[Mapping[str, Any]]] = None,
    claims: Optional[Mapping[str, Any]] = None,
    billing: Optional[Mapping[str, Any]] = None,
    commissions: Optional[Sequence[Mapping[str, Any]]] = None,
    currency: str = 'USD',
    actor: str = 'bordereaux',
) -> Dict[str, Any]:
    """Build and seal a binder/period bordereau (AE5).

    Premium lines come from customer-ledger premium cash for the binder's
    policies in the period, split via kernel pins. Claims lines come from
    paid/closed claim records (or ledger claim cash when present). Commission
    lines are optional inbound rows already scoped to the binder.
    """
    from services.financial_unification_service import (
        CLAIM_CASH_TYPES,
        PREMIUM_CASH_TYPES,
        resolve_premium_split,
    )

    binder = str(binder_id or DEFAULT_BINDER_ID).strip() or DEFAULT_BINDER_ID
    start, end = period_bounds(period_id)
    policies = policies or {}
    claims = claims or {}
    billing = billing or {}
    ledger_list = list(ledger_transactions or [])

    binder_policies = {
        str(pid): dict(pol)
        for pid, pol in policies.items()
        if isinstance(pol, Mapping) and binder_of(pol) == binder
    }
    policy_ids = sorted(binder_policies.keys())
    policy_id_set = set(policy_ids)

    premium_lines: List[Dict[str, Any]] = []
    premium_cash = Decimal('0.00')
    risk_cash = Decimal('0.00')
    savings_cash = Decimal('0.00')
    fee_cash = Decimal('0.00')

    for tx in ledger_list:
        if not isinstance(tx, Mapping):
            continue
        if _tx_type(tx) not in PREMIUM_CASH_TYPES:
            continue
        stamp = tx.get('timestamp') or tx.get('created_at') or tx.get('date') or tx.get('paid_at')
        if not _in_period(stamp, start, end):
            continue
        policy_id = _policy_id_of_tx(tx, policies=binder_policies, billing=billing)
        if policy_id and policy_id not in policy_id_set:
            # Also accept txs that name a binder policy via customer match when
            # policy_id is blank — skip those without a policy link.
            continue
        if not policy_id:
            continue
        amount = _tx_amount(tx)
        if amount <= 0:
            continue
        policy = binder_policies.get(policy_id) or {}
        split = resolve_premium_split(amount, policy)
        risk = _money(split.get('risk_amount'))
        savings = _money(split.get('savings_amount'))
        fee = _money(split.get('underwriting_fee_amount'))
        premium_cash += amount
        risk_cash += risk
        savings_cash += savings
        fee_cash += fee
        premium_lines.append({
            'kind': 'premium',
            'policy_id': policy_id,
            'tx_id': str(tx.get('id') or tx.get('tx_id') or ''),
            'amount': float(amount),
            'risk': float(risk),
            'savings': float(savings),
            'underwriting_fee': float(fee),
            'split_label': split.get('split_label'),
            'date': (_as_date(stamp) or start).isoformat(),
        })

    claims_paid = Decimal('0.00')
    claim_lines: List[Dict[str, Any]] = []
    # Prefer claim records (count once); fall back to ledger claim cash.
    seen_claims: set = set()
    for claim_id, claim in claims.items():
        if not isinstance(claim, Mapping):
            continue
        status = str(claim.get('status') or '').strip().lower().replace(' ', '_')
        if status not in ('paid', 'closed'):
            continue
        policy_id = str(claim.get('policy_id') or '').strip()
        if policy_id not in policy_id_set:
            continue
        paid_at = claim.get('paid_at') or claim.get('closed_at') or claim.get('updated_at') or claim.get('created_at')
        # Undated paid/closed claims are withheld — including them would seal
        # the same claim into every binder period.
        if not paid_at or not _in_period(paid_at, start, end):
            continue
        amount = _money(
            claim.get('amount_paid')
            or claim.get('paid_amount')
            or claim.get('amount')
            or 0
        )
        if amount <= 0:
            continue
        cid = str(claim.get('id') or claim_id)
        seen_claims.add(cid)
        claims_paid += amount
        claim_lines.append({
            'kind': 'claim',
            'claim_id': cid,
            'policy_id': policy_id,
            'amount': float(amount),
            'date': (_as_date(paid_at) or end).isoformat(),
        })

    for tx in ledger_list:
        if not isinstance(tx, Mapping):
            continue
        if _tx_type(tx) not in CLAIM_CASH_TYPES:
            continue
        stamp = tx.get('timestamp') or tx.get('created_at') or tx.get('date')
        if not _in_period(stamp, start, end):
            continue
        meta = _tx_meta(tx)
        claim_id = str(meta.get('claim_id') or tx.get('claim_id') or '').strip()
        if claim_id and claim_id in seen_claims:
            continue
        policy_id = _policy_id_of_tx(tx, policies=binder_policies, billing=billing)
        if policy_id not in policy_id_set:
            continue
        amount = _tx_amount(tx)
        if amount <= 0:
            continue
        if claim_id:
            seen_claims.add(claim_id)
        claims_paid += amount
        claim_lines.append({
            'kind': 'claim',
            'claim_id': claim_id,
            'policy_id': policy_id,
            'tx_id': str(tx.get('id') or tx.get('tx_id') or ''),
            'amount': float(amount),
            'date': (_as_date(stamp) or end).isoformat(),
            'source': 'ledger',
        })

    commission_total = Decimal('0.00')
    commission_lines: List[Dict[str, Any]] = []
    for row in commissions or ():
        if not isinstance(row, Mapping):
            continue
        if str(row.get('binder_id') or binder) != binder:
            continue
        amount = _money(row.get('amount'))
        if amount <= 0:
            continue
        commission_total += amount
        commission_lines.append({
            'kind': 'commission',
            'commission_id': str(row.get('id') or row.get('commission_id') or ''),
            'amount': float(amount),
            'agent_id': str(row.get('agent_id') or ''),
        })

    # Carrier payable = kernel risk cash collected in the period (never expense weights).
    carrier_payable = risk_cash
    built_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
    pack = {
        'schema': SCHEMA,
        'binder_id': binder,
        'period_id': str(period_id),
        'currency': str(currency or 'USD'),
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
        'premium_cash': float(premium_cash),
        'claims_paid': float(claims_paid),
        'commission': float(commission_total),
        'carrier_payable': float(carrier_payable),
        'streams': {
            'risk': float(risk_cash),
            'savings': float(savings_cash),
            'underwriting_fee': float(fee_cash),
        },
        'lines': premium_lines + claim_lines + commission_lines,
        'policy_ids': policy_ids,
        'policy_count': len(policy_ids),
        'built_at': built_at,
        'actor': actor,
    }
    sealed = seal_bordereau(pack)
    check = verify_bordereau(sealed)
    sealed['ae5_ok'] = bool(check.get('ok'))
    sealed['ae5'] = check
    with _LOCK:
        # One bordereau per binder/period — drop prior seals for that slot.
        stale = [
            rid for rid, row in _STORE.items()
            if row.get('binder_id') == binder and row.get('period_id') == str(period_id)
        ]
        for rid in stale:
            _STORE.pop(rid, None)
        _STORE[str(sealed['id'])] = dict(sealed)
    return sealed


def get_bordereau(bordereau_id: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        row = _STORE.get(str(bordereau_id or '').strip())
        return dict(row) if row else None


def list_bordereaux(
    *,
    binder_id: Optional[str] = None,
    period_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    with _LOCK:
        rows = [dict(v) for v in _STORE.values()]
    if binder_id:
        rows = [r for r in rows if r.get('binder_id') == binder_id]
    if period_id:
        rows = [r for r in rows if r.get('period_id') == period_id]
    return sorted(rows, key=lambda r: str(r.get('id') or ''))


__all__ = [
    'DEFAULT_BINDER_ID',
    'SCHEMA',
    'binder_of',
    'build_bordereau',
    'get_bordereau',
    'list_bordereaux',
    'parse_period_id',
    'period_bounds',
    'reset_bordereaux_state',
    'seal_bordereau',
    'verify_bordereau',
]
