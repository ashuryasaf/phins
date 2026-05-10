"""
Regression tests for the asaf seed underwriting application id.

The Railway boot log surfaced this entry on May 10 (the day after the May 9
boot that wrote `UW-ASAF-20260509-001`):

    INFO:database.repositories.base:Created UnderwritingApplication: UW-ASAF-20260510-001
    INFO:database.seeds:Created underwriting application for primary customer: UW-ASAF-20260510-001

Both `database/seeds.py` and the `web_portal/server.py` startup block built
the seed UW id as ``f"UW-ASAF-{now.strftime('%Y%m%d')}-001"``. Every Railway
restart that crossed midnight inserted a fresh row for asaf and left every
prior day's row orphaned in PostgreSQL, so the table grew by one row per
calendar day with no garbage collection.

These tests assert that:

1. `seed_sample_data()` creates AT MOST one underwriting row for asaf's
   health policy, even when invoked many times.
2. The id used is the stable ``UW-ASAF-HEALTH-001`` rather than a
   date-stamped one.
3. When the prod database already contains a legacy date-stamped row, the
   seeder reuses it instead of inserting another one.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def db_backed_portal(monkeypatch):
    """SQLite-backed portal globals so seeds reproduce the production wiring."""
    import web_portal.server as portal
    from database import init_database, reset_connection
    from database.data_access import DatabaseDict

    sqlite_file = Path(tempfile.mkdtemp()) / "phins_uw_seed_id.db"
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


def _all_asaf_health_uw_ids():
    from database.manager import DatabaseManager

    with DatabaseManager() as db:
        rows = db.underwriting.filter_by(
            customer_id="CUST-ASAF-001",
            policy_id="POL-ASAF-HEALTH-001",
        )
        return sorted(row.id for row in rows)


def test_seed_uses_stable_uw_id_for_asaf_health_policy(db_backed_portal):
    from database.seeds import seed_sample_data

    seed_sample_data()

    ids = _all_asaf_health_uw_ids()
    assert ids == ["UW-ASAF-HEALTH-001"], (
        "expected exactly one stable seed UW for asaf's health policy, "
        f"got {ids!r}"
    )


def test_repeated_seeding_does_not_proliferate_uw_rows(db_backed_portal, monkeypatch):
    """Five seed runs across DIFFERENT calendar days (simulating five
    container restarts that crossed midnight) must keep exactly one asaf
    health-policy underwriting row in the DB. With the previous date-stamped
    id this would have produced five rows, one per day."""
    from datetime import datetime, timedelta, timezone

    import database.seeds as seeds_module
    from database.seeds import seed_sample_data

    real_datetime = seeds_module.datetime
    base_day = datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc)

    class _ShiftedDatetime(real_datetime):
        _offset_days = 0

        @classmethod
        def now(cls, tz=None):
            stamp = base_day + timedelta(days=cls._offset_days)
            if tz is None:
                return stamp.replace(tzinfo=None)
            return stamp.astimezone(tz)

    monkeypatch.setattr(seeds_module, "datetime", _ShiftedDatetime)

    for offset in range(5):
        _ShiftedDatetime._offset_days = offset
        seed_sample_data()

    ids = _all_asaf_health_uw_ids()
    assert len(ids) == 1, (
        f"seed_sample_data() leaked {len(ids)} UW rows for asaf's health "
        f"policy across simulated cross-day restarts: {ids!r}"
    )


def test_seed_reuses_legacy_date_stamped_uw_row(db_backed_portal):
    """When prod already has a legacy `UW-ASAF-{date}-001` row from before
    this fix, the seeder must reuse it rather than inserting another row
    under the new stable id."""
    from datetime import datetime, timezone

    from database.manager import DatabaseManager
    from database.seeds import seed_sample_data

    seed_sample_data()  # create the prerequisite policy + customer rows

    legacy_id = "UW-ASAF-20260315-001"
    with DatabaseManager() as db:
        db.underwriting.delete("UW-ASAF-HEALTH-001")
        db.underwriting.create(
            id=legacy_id,
            policy_id="POL-ASAF-HEALTH-001",
            customer_id="CUST-ASAF-001",
            status="approved",
            risk_assessment="low",
            risk_score="low",
            created_date=datetime(2026, 3, 15, tzinfo=timezone.utc),
        )

    seed_sample_data()  # simulate a restart on a different day

    ids = _all_asaf_health_uw_ids()
    assert ids == [legacy_id], (
        "seeder must reuse the pre-existing legacy UW row instead of "
        f"creating a new one; got {ids!r}"
    )

    with DatabaseManager() as db:
        legacy = db.underwriting.get_by_id(legacy_id)
        assert legacy is not None
        assert legacy.status == "approved", (
            "reusing the legacy row must preserve its decision state"
        )
