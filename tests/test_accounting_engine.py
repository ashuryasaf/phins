from accounting_engine import AccountingEngine
from decimal import Decimal


def test_allocation_basic():
    acc = AccountingEngine("ACC_TEST", "Test Co")
    alloc = acc.create_allocation(
        bill_id="B1",
        policy_id="P1",
        customer_id="C1",
        total_premium=Decimal("100.00"),
        risk_percentage=Decimal("60"),
    )
    assert alloc.total_premium == Decimal("100.00")
    assert alloc.risk_percentage == Decimal("60")

    posted = acc.post_allocation(alloc.allocation_id, "unit test")
    # `post_allocation` may return a (success, message) tuple; accept either
    if isinstance(posted, tuple):
        assert posted[0] is True
    else:
        assert posted is True

    from datetime import date as _date
    stmt = acc.get_customer_statement("C1", _date.min, _date.max)
    # statement should include at least this allocation
    assert any(a.allocation_id == alloc.allocation_id for a in stmt.allocations)
