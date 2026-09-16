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


def test_claim_payment_is_idempotent_on_claim_id():
    acc = AccountingEngine("ACC_CLAIM", "Claim Co")
    ok1, msg1 = acc.post_claim_payment(
        claim_id="CLM-DUP",
        policy_id="P1",
        customer_id="C1",
        amount=Decimal("25.00"),
    )
    ok2, msg2 = acc.post_claim_payment(
        claim_id="CLM-DUP",
        policy_id="P1",
        customer_id="C1",
        amount=Decimal("25.00"),
    )
    assert ok1 is True
    assert ok2 is True
    assert "already recorded" in msg2
    claim_entries = [
        e for e in acc.ledger_entries
        if str(getattr(e, "reference_no", "") or "") == "CLM-DUP"
    ]
    assert len(claim_entries) == 1
