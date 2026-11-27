"""Chart of accounts — natural accounts under four fund rollups (U8 / KTD4).

Maps onto existing ``AccountType`` fund semantics (Risk / Savings /
Reinsurance / Operating). Natural accounts are content-addressed seed data;
this module never invents a second cash identity or pricing writer.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Fund rollups — keep values aligned with accounting_engine.AccountType.
FUND_RISK = 'Risk Fund'
FUND_SAVINGS = 'Savings Fund'
FUND_REINSURANCE = 'Reinsurance'
FUND_OPERATING = 'Operating'

FUNDS: Tuple[str, ...] = (
    FUND_RISK,
    FUND_SAVINGS,
    FUND_REINSURANCE,
    FUND_OPERATING,
)

# Natural account seed: (code, name, fund, normal_balance).
# Codes are stable; changing them is a deliberate reviewed change.
_SEED_ACCOUNTS: Tuple[Tuple[str, str, str, str], ...] = (
    # Risk
    ('4100', 'Premium — risk', FUND_RISK, 'credit'),
    ('4200', 'Claims paid — risk', FUND_RISK, 'debit'),
    ('1250', 'Claims reserve', FUND_RISK, 'credit'),
    # Savings
    ('4300', 'Premium — savings', FUND_SAVINGS, 'credit'),
    ('1450', 'Customer savings held', FUND_SAVINGS, 'credit'),
    ('4400', 'Investment income', FUND_SAVINGS, 'credit'),
    # Reinsurance
    ('1500', 'Reinsurance ceding reserve', FUND_REINSURANCE, 'credit'),
    ('1510', 'Carrier share held', FUND_REINSURANCE, 'credit'),
    ('4600', 'Cession expense (cash book)', FUND_REINSURANCE, 'debit'),
    # Operating
    ('1600', 'Operating reserve', FUND_OPERATING, 'credit'),
    ('5100', 'Underwriting fee income', FUND_OPERATING, 'credit'),
    ('5200', 'Expense loading', FUND_OPERATING, 'credit'),
    ('5300', 'Profit loading', FUND_OPERATING, 'credit'),
    ('6100', 'Operating expense', FUND_OPERATING, 'debit'),
)

_ACCOUNT_TYPE_ALIASES = {
    'risk fund': FUND_RISK,
    'risk': FUND_RISK,
    'risk_fund': FUND_RISK,
    'savings fund': FUND_SAVINGS,
    'savings': FUND_SAVINGS,
    'savings_fund': FUND_SAVINGS,
    'reinsurance': FUND_REINSURANCE,
    'operating': FUND_OPERATING,
}


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)


def seed_chart_of_accounts() -> List[Dict[str, Any]]:
    """Return the seeded natural-account chart (immutable copy)."""
    rows: List[Dict[str, Any]] = []
    for code, name, fund, normal in _SEED_ACCOUNTS:
        rows.append({
            'code': code,
            'name': name,
            'fund': fund,
            'normal_balance': normal,
            'active': True,
        })
    return rows


def chart_fingerprint() -> str:
    """SHA-256 of the seeded chart (codes + funds + normals)."""
    body = [
        {'code': c, 'name': n, 'fund': f, 'normal_balance': bal}
        for c, n, f, bal in _SEED_ACCOUNTS
    ]
    return hashlib.sha256(_canonical(body).encode('utf-8')).hexdigest()


def list_accounts(*, fund: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = seed_chart_of_accounts()
    if fund is None:
        return rows
    target = map_account_type(fund)
    return [r for r in rows if r['fund'] == target]


def map_account_type(account_type: Any) -> str:
    """Map an ``AccountType`` value / alias onto a fund rollup name."""
    if account_type is None:
        return FUND_OPERATING
    raw = getattr(account_type, 'value', account_type)
    text = str(raw or '').strip()
    if text in FUNDS:
        return text
    return _ACCOUNT_TYPE_ALIASES.get(text.lower().replace('-', '_'), FUND_OPERATING)


def fund_rollup(fund: str) -> Dict[str, Any]:
    """One fund with its natural accounts and chart fingerprint."""
    target = map_account_type(fund)
    accounts = list_accounts(fund=target)
    return {
        'fund': target,
        'account_count': len(accounts),
        'accounts': accounts,
        'chart_fingerprint': chart_fingerprint(),
    }


def status_report() -> Dict[str, Any]:
    """Accountant-facing CoA summary."""
    by_fund = {f: fund_rollup(f) for f in FUNDS}
    return {
        'schema': 'phins.erp_coa.v1',
        'funds': list(FUNDS),
        'account_count': sum(int(v['account_count']) for v in by_fund.values()),
        'chart_fingerprint': chart_fingerprint(),
        'by_fund': by_fund,
    }


def accounts_for_types(account_types: Sequence[Any]) -> List[Dict[str, Any]]:
    """Natural accounts covering the given fund types (deduped by code)."""
    seen = set()
    out: List[Dict[str, Any]] = []
    for at in account_types:
        fund = map_account_type(at)
        for row in list_accounts(fund=fund):
            if row['code'] in seen:
                continue
            seen.add(row['code'])
            out.append(row)
    return out


__all__ = [
    'FUND_OPERATING',
    'FUND_REINSURANCE',
    'FUND_RISK',
    'FUND_SAVINGS',
    'FUNDS',
    'accounts_for_types',
    'chart_fingerprint',
    'fund_rollup',
    'list_accounts',
    'map_account_type',
    'seed_chart_of_accounts',
    'status_report',
]
