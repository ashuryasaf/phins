"""
Regression tests for seeded-data integrity across container restarts.

The Railway boot path calls `seed_sample_data()` on every restart. The function
is intentionally idempotent at the DB-creation layer (it only `create()`s rows
that don't exist yet), but it also mirrors seeded entities into the
`web_portal.server` in-memory dictionaries (POLICIES, BILLING, CLAIMS,
UNDERWRITING_APPLICATIONS, CUSTOMERS).

In production those globals are `DatabaseDict` write-through wrappers, so an
unconditional `POLICIES[id] = {...}` becomes a `repo.update(id, **seed_fields)`
and silently rolls back any live state that workflows have advanced (paid
bills, decided UW applications, status-transitioned claims, slid due_dates).

These tests reproduce the production wiring against an isolated SQLite
database, mutate seeded rows, re-run `seed_sample_data()`, and assert the
mutations survive — i.e. the seeder never overwrites live data.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


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


def test_reseed_preserves_paid_bill(db_backed_portal):
    """A bill that has been paid must not be reverted by re-seeding."""
    from database.manager import DatabaseManager

    portal, db_dicts = db_backed_portal
    bill_id = "BILL-ASAF-LIFE-001"

    def mutate():
        with DatabaseManager() as db:
            db.billing.update(
                bill_id,
                status="paid",
                amount_paid=299.25,
                payment_method="auto_pay_card",
                transaction_id="TX-ASAF-LIFE-001",
            )

    _seed_twice_with_mutations(db_dicts, mutate)

    with DatabaseManager() as db:
        bill = db.billing.get_by_id(bill_id)
        assert bill is not None, "seeded bill should still exist after re-seed"
        assert bill.status == "paid", (
            f"re-seed reverted bill status to {bill.status!r}; live payment lost"
        )
        assert float(bill.amount_paid or 0) == pytest.approx(299.25)
        assert bill.transaction_id == "TX-ASAF-LIFE-001"


def test_reseed_preserves_advanced_claim_status(db_backed_portal):
    """A claim that workflow advanced (e.g. Pending -> Approved) must persist."""
    from database.manager import DatabaseManager

    portal, db_dicts = db_backed_portal
    claim_id = "CLM-ASAF-004"  # seed value: 'Pending'

    def mutate():
        with DatabaseManager() as db:
            db.claims.update(
                claim_id,
                status="Approved",
                approved_amount=2800.0,
            )

    _seed_twice_with_mutations(db_dicts, mutate)

    with DatabaseManager() as db:
        claim = db.claims.get_by_id(claim_id)
        assert claim is not None
        assert claim.status == "Approved", (
            f"re-seed reverted claim status to {claim.status!r}; workflow rollback"
        )
        assert float(claim.approved_amount or 0) == pytest.approx(2800.0)


def test_reseed_preserves_underwriting_decision(db_backed_portal):
    """An underwriting decision must not be rolled back to 'pending'."""
    from datetime import datetime, timezone

    from database.manager import DatabaseManager

    portal, db_dicts = db_backed_portal
    uw_id = f"UW-ASAF-{datetime.now(timezone.utc).strftime('%Y%m%d')}-001"

    def mutate():
        with DatabaseManager() as db:
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


def test_reseed_preserves_phins_customer_policy_status(db_backed_portal):
    """An EFRAT/ASI/SHOSH policy whose status advanced must not be reset."""
    from database.manager import DatabaseManager

    portal, db_dicts = db_backed_portal
    pol_id = "POL-ASI-UNIFIED-001"  # seed value: 'pending_underwriting'

    def mutate():
        with DatabaseManager() as db:
            db.policies.update(pol_id, status="active", risk_score="low")

    _seed_twice_with_mutations(db_dicts, mutate)

    with DatabaseManager() as db:
        policy = db.policies.get_by_id(pol_id)
        assert policy is not None
        assert policy.status == "active", (
            f"re-seed reverted PHINS policy status to {policy.status!r}"
        )


def test_reseed_does_not_slide_bill_due_date(db_backed_portal):
    """The seeded bill due_date must NOT be re-anchored to now+30d on every boot."""
    from datetime import datetime, timedelta, timezone

    from database.manager import DatabaseManager

    portal, db_dicts = db_backed_portal
    bill_id = "BILL-EFRAT-UNIFIED-001"

    fixed_due = datetime(2026, 1, 15, tzinfo=timezone.utc)

    def mutate():
        with DatabaseManager() as db:
            db.billing.update(bill_id, due_date=fixed_due)

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
