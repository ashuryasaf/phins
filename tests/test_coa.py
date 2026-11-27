"""U8 — chart of accounts under four fund rollups."""

from __future__ import annotations

from services.erp import coa
from accounting_engine import AccountType


def test_seed_covers_four_funds():
    rows = coa.seed_chart_of_accounts()
    funds = {r['fund'] for r in rows}
    assert funds == set(coa.FUNDS)
    assert len(rows) >= 8
    codes = [r['code'] for r in rows]
    assert len(codes) == len(set(codes))


def test_map_account_type_aligns_with_engine():
    assert coa.map_account_type(AccountType.RISK_FUND) == coa.FUND_RISK
    assert coa.map_account_type(AccountType.SAVINGS_FUND) == coa.FUND_SAVINGS
    assert coa.map_account_type(AccountType.REINSURANCE) == coa.FUND_REINSURANCE
    assert coa.map_account_type(AccountType.OPERATING) == coa.FUND_OPERATING
    assert coa.map_account_type('risk') == coa.FUND_RISK


def test_chart_fingerprint_stable():
    a = coa.chart_fingerprint()
    b = coa.chart_fingerprint()
    assert a == b and len(a) == 64


def test_status_report_schema():
    report = coa.status_report()
    assert report['schema'] == 'phins.erp_coa.v1'
    assert report['account_count'] == len(coa.seed_chart_of_accounts())
    assert set(report['by_fund']) == set(coa.FUNDS)
