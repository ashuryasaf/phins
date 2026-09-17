"""
Regression tests for seeded-data integrity across container restarts.

The Railway boot path calls `seed_sample_data()` on every restart. The function
is intentionally idempotent at the DB-creation layer (it only `create()`s rows
that don't exist yet), but it also mirrors seeded entities into the
`web_portal.server` in-memory dictionaries (POLICIES, BILLING, CLAIMS,
UNDERWRITING_APPLICATIONS, CUSTOMERS).

False demo policies (Asaf life/health/auto, Efrat/Asi/Shosh unified, POL-TEST-*)
and QA test customers (CUST-TEST-100/101/102) are not seeded. Restart seed
**removes** those known IDs and every bill/claim/UW/ledger row keyed to them.
Live PHINS customers stay. Unknown real policies are never swept.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest


FALSE_DEMO_POLICY_IDS = (
    "POL-ASAF-LIFE-001",
    "POL-ASAF-HEALTH-001",
    "POL-ASAF-AUTO-001",
    "POL-EFRAT-UNIFIED-001",
    "POL-ASI-UNIFIED-001",
    "POL-SHOSH-UNIFIED-001",
    "POL-TEST-100",
    "POL-TEST-101",
    "POL-TEST-102",
)
FALSE_TEST_CUSTOMER_IDS = (
    "CUST-TEST-100",
    "CUST-TEST-101",
    "CUST-TEST-102",
)


@pytest.fixture()
def db_backed_portal(monkeypatch):
    """
    Wire `web_portal.server.{POLICIES, BILLING, CLAIMS,
    UNDERWRITING_APPLICATIONS, CUSTOMERS}` to write-through `DatabaseDict`
    wrappers backed by a fresh SQLite file. This mirrors the Railway runtime
    where seed-time `POLICIES[id] = dict` actually issues a SQL UPDATE.

    Yields a tuple of `(portal, dicts_dict)` where `dicts_dict` exposes the
    backing wrappers for assertions.
    """
    import web_portal.server as portal
    from database import init_database, reset_connection
    from database.data_access import DatabaseDict

    sqlite_file = Path(tempfile.mkdtemp()) / "phins_seed_integrity.db"
    monkeypatch.setenv("USE_SQLITE", "true")
    monkeypatch.setenv("SQLITE_PATH", str(sqlite_file))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_DICT_CACHE_TTL_SECONDS", "0")

    reset_connection()
    init_database()

    db_dicts = {
        "POLICIES": DatabaseDict("policies"),
        "CLAIMS": DatabaseDict("claims"),
        "BILLING": DatabaseDict("billing"),
        "CUSTOMERS": DatabaseDict("customers"),
        "UNDERWRITING_APPLICATIONS": DatabaseDict("underwriting"),
    }

    originals = {name: getattr(portal, name) for name in db_dicts}
    for name, wrapper in db_dicts.items():
        monkeypatch.setattr(portal, name, wrapper, raising=True)

    try:
        yield portal, db_dicts
    finally:
        for name, original in originals.items():
            setattr(portal, name, original)
        reset_connection()
        try:
            sqlite_file.unlink()
        except FileNotFoundError:
            pass


def _seed_twice_with_mutations(db_dicts, mutate):
    """
    Run `seed_sample_data()`, apply caller-provided DB mutations, run it a
    second time, and return the post-second-seed snapshot for the entities
    the mutation touched.
    """
    from database.seeds import seed_sample_data

    seed_sample_data()
    mutate()
    db_dicts["POLICIES"].invalidate_cache()
    db_dicts["BILLING"].invalidate_cache()
    db_dicts["CLAIMS"].invalidate_cache()
    db_dicts["UNDERWRITING_APPLICATIONS"].invalidate_cache()
    db_dicts["CUSTOMERS"].invalidate_cache()

    seed_sample_data()


def _insert_false_demo_rows():
    from database.manager import DatabaseManager

    now = datetime.now(timezone.utc)
    fixtures = (
        ("POL-ASAF-LIFE-001", "CUST-ASAF-001", "BILL-ASAF-LIFE-001", "CLM-ASAF-004", "UW-ASAF-LIFE-001"),
        ("POL-ASAF-HEALTH-001", "CUST-ASAF-001", "BILL-ASAF-HEALTH-001", "CLM-ASAF-001", "UW-ASAF-HEALTH-001"),
        ("POL-EFRAT-UNIFIED-001", "CUST-EFRAT-001", "BILL-EFRAT-UNIFIED-001", None, "UW-EFRAT-UNIFIED-001"),
        ("POL-ASI-UNIFIED-001", "CUST-ASI-001", None, None, "UW-ASI-UNIFIED-001"),
        ("POL-SHOSH-UNIFIED-001", "CUST-SHOSH-001", None, None, "UW-SHOSH-UNIFIED-001"),
    )
    with DatabaseManager() as db:
        for policy_id, customer_id, bill_id, claim_id, uw_id in fixtures:
            if db.policies.get_by_id(policy_id) is None:
                created = db.policies.create(
                    id=policy_id,
                    customer_id=customer_id,
                    type="phins_unified",
                    coverage_amount=500000.0,
                    annual_premium=1800.0,
                    monthly_premium=150.0,
                    status="active",
                    risk_score="low",
                    start_date=now,
                )
                assert created is not None, f"failed to insert false demo policy {policy_id}"
            if bill_id and db.billing.get_by_id(bill_id) is None:
                created = db.billing.create(
                    id=bill_id,
                    policy_id=policy_id,
                    customer_id=customer_id,
                    amount=150.0,
                    amount_paid=150.0,
                    status="paid",
                    due_date=now,
                )
                assert created is not None, f"failed to insert false demo bill {bill_id}"
            if claim_id and db.claims.get_by_id(claim_id) is None:
                created = db.claims.create(
                    id=claim_id,
                    policy_id=policy_id,
                    customer_id=customer_id,
                    type="Medical",
                    claimed_amount=2800.0,
                    approved_amount=2800.0,
                    status="Approved",
                )
                assert created is not None, f"failed to insert false demo claim {claim_id}"
            if uw_id and db.underwriting.get_by_id(uw_id) is None:
                created = db.underwriting.create(
                    id=uw_id,
                    policy_id=policy_id,
                    customer_id=customer_id,
                    status="approved",
                    risk_assessment="low",
                    risk_score="low",
                    created_date=now,
                )
                assert created is not None, f"failed to insert false demo UW {uw_id}"


def _insert_false_test_customers():
    from database.manager import DatabaseManager

    now = datetime.now(timezone.utc)
    fixtures = (
        ("CUST-TEST-100", "Sarah Cohen", "sarah.cohen@test.com", "POL-TEST-100", "UW-TEST-100"),
        ("CUST-TEST-101", "David Levy", "david.levy@test.com", "POL-TEST-101", "UW-TEST-101"),
        ("CUST-TEST-102", "Rachel Green", "rachel.green@test.com", "POL-TEST-102", "UW-TEST-102"),
    )
    with DatabaseManager() as db:
        for customer_id, name, email, policy_id, uw_id in fixtures:
            if db.customers.get_by_id(customer_id) is None:
                created = db.customers.create(
                    id=customer_id,
                    name=name,
                    email=email,
                    phone="+1-555-0100",
                    portal_active=True,
                )
                assert created is not None, f"failed to insert false test customer {customer_id}"
            if db.policies.get_by_id(policy_id) is None:
                created = db.policies.create(
                    id=policy_id,
                    customer_id=customer_id,
                    type="phins_unified",
                    coverage_amount=500000.0,
                    annual_premium=1800.0,
                    monthly_premium=150.0,
                    status="pending_underwriting",
                    risk_score="medium",
                    start_date=now,
                )
                assert created is not None, f"failed to insert false test policy {policy_id}"
            bill_id = f"BILL-{policy_id}"
            if db.billing.get_by_id(bill_id) is None:
                created = db.billing.create(
                    id=bill_id,
                    policy_id=policy_id,
                    customer_id=customer_id,
                    amount=150.0,
                    amount_paid=0.0,
                    status="outstanding",
                    due_date=now,
                )
                assert created is not None, f"failed to insert false test bill {bill_id}"
            claim_id = f"CLM-{policy_id}"
            if db.claims.get_by_id(claim_id) is None:
                created = db.claims.create(
                    id=claim_id,
                    policy_id=policy_id,
                    customer_id=customer_id,
                    type="Medical",
                    claimed_amount=500.0,
                    approved_amount=0.0,
                    status="Submitted",
                )
                assert created is not None, f"failed to insert false test claim {claim_id}"
            if db.underwriting.get_by_id(uw_id) is None:
                created = db.underwriting.create(
                    id=uw_id,
                    policy_id=policy_id,
                    customer_id=customer_id,
                    status="pending",
                    risk_assessment="medium",
                    risk_score="medium",
                    created_date=now,
                )
                assert created is not None, f"failed to insert false test UW {uw_id}"


def test_reseed_removes_false_demo_policies_and_keeps_customers(db_backed_portal):
    """Known false demo IDs are deleted on re-seed; customers stay."""
    from database.manager import DatabaseManager
    from database.seeds import FALSE_DEMO_POLICY_IDS as seed_ids

    portal, db_dicts = db_backed_portal
    assert tuple(seed_ids) == FALSE_DEMO_POLICY_IDS

    def mutate():
        _insert_false_demo_rows()
        _insert_false_test_customers()
        with DatabaseManager() as db:
            assert db.policies.get_by_id("POL-ASAF-LIFE-001") is not None
            assert db.billing.get_by_id("BILL-ASAF-LIFE-001") is not None
            assert db.claims.get_by_id("CLM-ASAF-004") is not None
            assert db.underwriting.get_by_id("UW-ASAF-HEALTH-001") is not None
            assert db.customers.get_by_id("CUST-TEST-100") is not None
            assert db.policies.get_by_id("POL-TEST-100") is not None

    _seed_twice_with_mutations(db_dicts, mutate)

    with DatabaseManager() as db:
        for policy_id in FALSE_DEMO_POLICY_IDS:
            assert db.policies.get_by_id(policy_id) is None, policy_id
            assert db.billing.filter_by(policy_id=policy_id) == []
            assert db.claims.filter_by(policy_id=policy_id) == []
            assert db.underwriting.filter_by(policy_id=policy_id) == []
        for customer_id in FALSE_TEST_CUSTOMER_IDS:
            assert db.customers.get_by_id(customer_id) is None, customer_id
            assert db.policies.filter_by(customer_id=customer_id) == []
            assert db.billing.filter_by(customer_id=customer_id) == []
            assert db.claims.filter_by(customer_id=customer_id) == []
            assert db.underwriting.filter_by(customer_id=customer_id) == []
        assert db.customers.get_by_id("CUST-ASAF-001") is not None
        assert db.customers.get_by_id("CUST-EFRAT-001") is not None
        assert db.customers.get_by_id("CUST-ASI-001") is not None
        assert db.customers.get_by_id("CUST-SHOSH-001") is not None


def test_reseed_does_not_sweep_unknown_real_policies(db_backed_portal):
    """Policies outside the known false-demo ID list survive re-seed."""
    from database.manager import DatabaseManager

    portal, db_dicts = db_backed_portal
    keep_id = "POL-KEEP-REAL-001"

    def mutate():
        now = datetime.now(timezone.utc)
        with DatabaseManager() as db:
            created = db.policies.create(
                id=keep_id,
                customer_id="CUST-ASAF-001",
                type="phins_unified",
                coverage_amount=250000.0,
                annual_premium=900.0,
                monthly_premium=75.0,
                status="active",
                risk_score="low",
                start_date=now,
            )
            assert created is not None
            created_bill = db.billing.create(
                id="BILL-KEEP-REAL-001",
                policy_id=keep_id,
                customer_id="CUST-ASAF-001",
                amount=75.0,
                amount_paid=75.0,
                status="paid",
                due_date=now,
            )
            assert created_bill is not None

    _seed_twice_with_mutations(db_dicts, mutate)

    with DatabaseManager() as db:
        policy = db.policies.get_by_id(keep_id)
        assert policy is not None
        assert policy.status == "active"
        bill = db.billing.get_by_id("BILL-KEEP-REAL-001")
        assert bill is not None
        assert bill.status == "paid"
        assert float(bill.amount_paid or 0) == pytest.approx(75.0)


def test_reseed_preserves_paid_bill_on_kept_real_policy(db_backed_portal):
    """A paid bill on an unknown real policy must not be reverted."""
    from database.manager import DatabaseManager

    portal, db_dicts = db_backed_portal
    keep_id = "POL-KEEP-REAL-001"
    bill_id = "BILL-KEEP-REAL-LIVE"

    def mutate():
        now = datetime.now(timezone.utc)
        with DatabaseManager() as db:
            if db.policies.get_by_id(keep_id) is None:
                created_policy = db.policies.create(
                    id=keep_id,
                    customer_id="CUST-ASAF-001",
                    type="phins_unified",
                    coverage_amount=250000.0,
                    annual_premium=900.0,
                    monthly_premium=75.0,
                    status="active",
                    risk_score="low",
                    start_date=now,
                )
                assert created_policy is not None
            created = db.billing.create(
                id=bill_id,
                policy_id=keep_id,
                customer_id="CUST-ASAF-001",
                amount=120.0,
                amount_paid=120.0,
                status="paid",
                payment_method="auto_pay_card",
                transaction_id="TX-KEEP-REAL-LIVE",
                due_date=now,
            )
            assert created is not None

    _seed_twice_with_mutations(db_dicts, mutate)

    with DatabaseManager() as db:
        bill = db.billing.get_by_id(bill_id)
        assert bill is not None, "live bill on a kept real policy should survive re-seed"
        assert bill.status == "paid"
        assert float(bill.amount_paid or 0) == pytest.approx(120.0)
        assert bill.transaction_id == "TX-KEEP-REAL-LIVE"


def test_reseed_preserves_advanced_claim_status(db_backed_portal):
    """A claim workflow advanced on an unknown real policy must persist."""
    from database.manager import DatabaseManager

    portal, db_dicts = db_backed_portal
    keep_id = "POL-KEEP-REAL-001"
    claim_id = "CLM-KEEP-REAL-LIVE"

    def mutate():
        now = datetime.now(timezone.utc)
        with DatabaseManager() as db:
            if db.policies.get_by_id(keep_id) is None:
                created_policy = db.policies.create(
                    id=keep_id,
                    customer_id="CUST-ASAF-001",
                    type="phins_unified",
                    coverage_amount=250000.0,
                    annual_premium=900.0,
                    monthly_premium=75.0,
                    status="active",
                    risk_score="low",
                    start_date=now,
                )
                assert created_policy is not None
            created = db.claims.create(
                id=claim_id,
                policy_id=keep_id,
                customer_id="CUST-ASAF-001",
                type="Medical",
                claimed_amount=2800.0,
                approved_amount=2800.0,
                status="Approved",
            )
            assert created is not None

    _seed_twice_with_mutations(db_dicts, mutate)

    with DatabaseManager() as db:
        claim = db.claims.get_by_id(claim_id)
        assert claim is not None
        assert claim.status == "Approved"
        assert float(claim.approved_amount or 0) == pytest.approx(2800.0)


def test_reseed_preserves_underwriting_decision(db_backed_portal):
    """An underwriting decision on an unknown real policy must persist."""
    from database.manager import DatabaseManager

    portal, db_dicts = db_backed_portal
    keep_id = "POL-KEEP-REAL-001"
    uw_id = "UW-KEEP-REAL-001"

    def mutate():
        now = datetime.now(timezone.utc)
        with DatabaseManager() as db:
            if db.policies.get_by_id(keep_id) is None:
                created_policy = db.policies.create(
                    id=keep_id,
                    customer_id="CUST-ASAF-001",
                    type="phins_unified",
                    coverage_amount=250000.0,
                    annual_premium=900.0,
                    monthly_premium=75.0,
                    status="active",
                    risk_score="low",
                    start_date=now,
                )
                assert created_policy is not None
            if db.underwriting.get_by_id(uw_id) is None:
                created = db.underwriting.create(
                    id=uw_id,
                    policy_id=keep_id,
                    customer_id="CUST-ASAF-001",
                    status="approved",
                    risk_assessment="low",
                    risk_score="low",
                    created_date=now,
                )
                assert created is not None
            else:
                db.underwriting.update(
                    uw_id,
                    status="approved",
                    risk_assessment="low",
                )

    _seed_twice_with_mutations(db_dicts, mutate)

    with DatabaseManager() as db:
        uw = db.underwriting.get_by_id(uw_id)
        assert uw is not None
        assert uw.status == "approved", (
            f"re-seed reverted UW status to {uw.status!r}; underwriting rollback"
        )
        assert uw.risk_assessment == "low"


def test_reseed_does_not_slide_bill_due_date(db_backed_portal):
    """A live bill due_date on an unknown real policy must not be re-anchored."""
    from datetime import timedelta

    from database.manager import DatabaseManager

    portal, db_dicts = db_backed_portal
    keep_id = "POL-KEEP-REAL-001"
    bill_id = "BILL-KEEP-REAL-DUE"
    fixed_due = datetime(2026, 1, 15, tzinfo=timezone.utc)

    def mutate():
        now = datetime.now(timezone.utc)
        with DatabaseManager() as db:
            if db.policies.get_by_id(keep_id) is None:
                created_policy = db.policies.create(
                    id=keep_id,
                    customer_id="CUST-ASAF-001",
                    type="phins_unified",
                    coverage_amount=250000.0,
                    annual_premium=900.0,
                    monthly_premium=75.0,
                    status="active",
                    risk_score="low",
                    start_date=now,
                )
                assert created_policy is not None
            created = db.billing.create(
                id=bill_id,
                policy_id=keep_id,
                customer_id="CUST-ASAF-001",
                amount=99.0,
                amount_paid=0.0,
                status="outstanding",
                due_date=fixed_due,
            )
            assert created is not None
            db.billing.update(bill_id, due_date=fixed_due + timedelta(seconds=0))

    _seed_twice_with_mutations(db_dicts, mutate)

    with DatabaseManager() as db:
        bill = db.billing.get_by_id(bill_id)
        assert bill is not None
        bill_due = bill.due_date
        if hasattr(bill_due, "tzinfo") and bill_due.tzinfo is None:
            bill_due = bill_due.replace(tzinfo=timezone.utc)
        delta = abs((bill_due - fixed_due).total_seconds())
        assert delta < 60, (
            f"re-seed slid due_date from {fixed_due.isoformat()} to "
            f"{bill.due_date!r}; billing pipeline cannot age"
        )


def test_false_demo_ledger_purge_is_durable(db_backed_portal, tmp_path, monkeypatch):
    """Popped demo ledger rows must not come back on hydrate_from_db."""
    from database.manager import DatabaseManager
    from database.seeds import _purge_false_demo_seed
    from services.platform_event_ledger_service import (
        PlatformEventLedgerService,
        reconcile_ledger_entries,
    )

    portal, db_dicts = db_backed_portal
    monkeypatch.setattr(portal, "USE_DATABASE", True, raising=False)
    monkeypatch.setattr(portal, "database_enabled", True, raising=False)

    memory = portal.TRANSACTION_LEDGER
    memory.clear()
    service = PlatformEventLedgerService(
        transaction_ledger=memory,
        use_database=True,
        db_manager_factory=DatabaseManager,
    )
    service.append_event(
        event_type="premium_payment",
        entity_type="transaction",
        entity_id="TX-POL-ASAF-LIFE-001",
        customer_id="CUST-ASAF-001",
        actor="system",
        amount=401.90,
        status="completed",
        source_system="test",
        payload={
            "id": "TX-POL-ASAF-LIFE-001",
            "policy_id": "POL-ASAF-LIFE-001",
            "metadata": {"policy_id": "POL-ASAF-LIFE-001"},
        },
        entry_id="TX-POL-ASAF-LIFE-001",
        ledger_type="transaction",
    )
    service.append_event(
        event_type="premium_payment",
        entity_type="transaction",
        entity_id="TX-KEEP-REAL",
        customer_id="CUST-ASAF-001",
        actor="system",
        amount=75.0,
        status="completed",
        source_system="test",
        payload={"id": "TX-KEEP-REAL", "policy_id": "POL-KEEP-REAL-001"},
        entry_id="TX-KEEP-REAL",
        ledger_type="transaction",
    )

    with DatabaseManager() as db:
        assert db.platform_ledger.get_by_id("TX-POL-ASAF-LIFE-001") is not None
        assert db.platform_ledger.get_by_id("TX-KEEP-REAL") is not None

    monkeypatch.setattr(portal, "platform_event_ledger", service, raising=False)
    monkeypatch.setattr(
        portal,
        "LEDGER_PERSISTENCE_FILE",
        str(tmp_path / "phins_ledger_data.json"),
        raising=False,
    )

    _purge_false_demo_seed(sync_memory=True)

    assert "TX-POL-ASAF-LIFE-001" not in portal.TRANSACTION_LEDGER
    assert "TX-KEEP-REAL" in portal.TRANSACTION_LEDGER

    restart_memory = {}
    restart_service = PlatformEventLedgerService(
        transaction_ledger=restart_memory,
        use_database=True,
        db_manager_factory=DatabaseManager,
    )
    hydrated = restart_service.hydrate_from_db()
    assert "TX-POL-ASAF-LIFE-001" not in restart_memory
    assert "TX-KEEP-REAL" in restart_memory
    assert hydrated >= 1
    summary = reconcile_ledger_entries(restart_memory.values())
    assert summary["chain_valid"]
    with DatabaseManager() as db:
        assert db.platform_ledger.get_by_id("TX-POL-ASAF-LIFE-001") is None
        assert db.platform_ledger.get_by_id("TX-KEEP-REAL") is not None


def test_false_demo_purge_matches_cash_of_db_only_claims(
    db_backed_portal, tmp_path, monkeypatch
):
    """Cash keyed only by a claim_id the DB sweep deleted must go too."""
    from database.manager import DatabaseManager
    from database.seeds import _purge_false_demo_seed
    from services.platform_event_ledger_service import PlatformEventLedgerService

    portal, _db_dicts = db_backed_portal
    monkeypatch.setattr(portal, "USE_DATABASE", True, raising=False)
    monkeypatch.setattr(portal, "database_enabled", True, raising=False)
    # Boot hydrates plain dicts, so the SQL claim has no in-memory mirror.
    monkeypatch.setattr(portal, "CLAIMS", {}, raising=True)

    with DatabaseManager() as db:
        assert db.claims.create(
            id="CLM-ASAF-CASH-001",
            policy_id="POL-ASAF-LIFE-001",
            customer_id="CUST-ASAF-001",
            claimed_amount=1200.0,
            approved_amount=1200.0,
            status="paid",
            filed_date=datetime.now(timezone.utc),
        ) is not None

    memory = portal.TRANSACTION_LEDGER
    memory.clear()
    service = PlatformEventLedgerService(
        transaction_ledger=memory,
        use_database=True,
        db_manager_factory=DatabaseManager,
    )
    service.append_event(
        event_type="claim_payment_received",
        entity_type="claim",
        entity_id="CLM-ASAF-CASH-001",
        customer_id="CUST-ASAF-001",
        actor="system",
        amount=1200.0,
        status="completed",
        source_system="test",
        payload={"id": "TX-CLAIM-CASH-ONLY", "claim_id": "CLM-ASAF-CASH-001"},
        entry_id="TX-CLAIM-CASH-ONLY",
        ledger_type="transaction",
    )

    monkeypatch.setattr(portal, "platform_event_ledger", service, raising=False)
    monkeypatch.setattr(
        portal,
        "LEDGER_PERSISTENCE_FILE",
        str(tmp_path / "phins_ledger_data.json"),
        raising=False,
    )

    _purge_false_demo_seed(sync_memory=True)

    with DatabaseManager() as db:
        assert db.claims.get_by_id("CLM-ASAF-CASH-001") is None
        assert db.platform_ledger.get_by_id("TX-CLAIM-CASH-ONLY") is None

    restart_memory = {}
    restart_service = PlatformEventLedgerService(
        transaction_ledger=restart_memory,
        use_database=True,
        db_manager_factory=DatabaseManager,
    )
    restart_service.hydrate_from_db()
    assert "TX-CLAIM-CASH-ONLY" not in restart_memory
