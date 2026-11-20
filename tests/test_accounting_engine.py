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


def test_reversing_an_allocation_offsets_its_entries_and_keeps_the_record():
    from accounting_engine import AccountType, AllocationStatus

    engine = AccountingEngine()
    alloc = engine.create_allocation(
        bill_id="BILL-R", policy_id="POL-R", customer_id="CUST-R",
        total_premium=Decimal("296.47"), risk_percentage=Decimal("100"),
    )
    assert engine.reverse_allocation(alloc.allocation_id, "accountant")[0] is False  # still a draft
    assert engine.post_allocation(alloc.allocation_id, "billing")[0] is True

    ok, _message = engine.reverse_allocation(alloc.allocation_id, "accountant", "pin restored")
    assert ok is True
    assert alloc.status == AllocationStatus.REVERSED
    assert "reversed_by=accountant; pin restored" in alloc.notes
    assert engine._get_account_balance(AccountType.RISK_FUND) == Decimal("0.00")
    assert engine.get_summary()["posted_allocations"] == 0
    # Nothing is removed: the posting and its contra entry are both on the book.
    risk_entries = [e for e in engine.ledger_entries if e.account_type == AccountType.RISK_FUND]
    assert [(e.debit_amount, e.credit_amount) for e in risk_entries] == [
        (Decimal("296.47"), Decimal("0")), (Decimal("0"), Decimal("296.47")),
    ]
    assert engine.reverse_allocation(alloc.allocation_id, "accountant")[0] is False
    assert engine.reverse_allocation("ALLOC-MISSING", "accountant")[0] is False
