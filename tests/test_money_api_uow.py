"""U12 — extracted money APIs + unit of work."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.erp.integrity_scorecard import compute_integrity_scorecard
from services.erp.unit_of_work import money_uow, UnitOfWorkError


def test_money_uow_yields_without_db():
    with money_uow(label='test') as session:
        assert session is None


def test_money_uow_propagates_errors():
    with pytest.raises(RuntimeError, match='boom'):
        with money_uow(label='test'):
            raise RuntimeError('boom')


def test_api_modules_exist():
    root = Path(__file__).resolve().parents[1]
    for rel in (
        'web_portal/api_finance.py',
        'web_portal/api_fiduciary.py',
        'web_portal/api_mga.py',
        'services/erp/unit_of_work.py',
    ):
        assert (root / rel).is_file(), rel


def test_mga_dispatch_unauthorized():
    from web_portal import api_mga
    result = api_mga.dispatch_get(
        '/api/admin/cashflow/remittance',
        session={'role': 'customer'},
        qs={},
    )
    assert result is not None
    status, body = result
    assert status == 403
    assert 'error' in body


def test_scorecard_u12_landed_on_this_checkout():
    report = compute_integrity_scorecard()
    by_id = {u['unit_id']: u for u in report['units']}
    assert by_id['U12']['status'] == 'landed', by_id['U12']
