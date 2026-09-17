"""
Regression tests for false Asaf health seed underwriting rows.

The Railway boot log used to insert a new ``UW-ASAF-{YYYYMMDD}-001`` row on
every midnight restart. Those policies are now treated as false demo data:
`seed_sample_data()` must not create underwriting (or policy) rows for
``POL-ASAF-HEALTH-001``, and a restart must purge any leftover date-stamped
row keyed to that policy.
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


def test_seed_does_not_create_asaf_health_policy_or_uw(db_backed_portal):
    from database.manager import DatabaseManager
    from database.seeds import seed_sample_data

    seed_sample_data()

    ids = _all_asaf_health_uw_ids()
    assert ids == [], (
        "false demo Asaf health policy must not have any UW rows, "
        f"got {ids!r}"
    )
    with DatabaseManager() as db:
        assert db.policies.get_by_id("POL-ASAF-HEALTH-001") is None
        assert db.policies.get_by_id("POL-ASAF-LIFE-001") is None


def test_repeated_seeding_does_not_proliferate_asaf_health_uw(db_backed_portal, monkeypatch):
    """Five seed runs across different calendar days must keep zero Asaf
    health-policy underwriting rows."""
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
    assert ids == [], (
        f"seed_sample_data() leaked {len(ids)} UW rows for the false Asaf "
        f"health policy across simulated cross-day restarts: {ids!r}"
    )


def test_seed_purges_legacy_date_stamped_asaf_health_uw(db_backed_portal):
    """A leftover ``UW-ASAF-{date}-001`` row for the false health policy is
    removed on restart rather than reused or duplicated."""
    from datetime import datetime, timezone

    from database.manager import DatabaseManager
    from database.seeds import seed_sample_data

    seed_sample_data()  # create the prerequisite customer rows

    legacy_id = "UW-ASAF-20260315-001"
    now = datetime(2026, 3, 15, tzinfo=timezone.utc)
    with DatabaseManager() as db:
        created_policy = db.policies.create(
            id="POL-ASAF-HEALTH-001",
            customer_id="CUST-ASAF-001",
            type="health",
            coverage_amount=500000.0,
            annual_premium=2679.34,
            monthly_premium=223.28,
            status="active",
            risk_score="low",
            start_date=now,
        )
        assert created_policy is not None
        created_uw = db.underwriting.create(
            id=legacy_id,
            policy_id="POL-ASAF-HEALTH-001",
            customer_id="CUST-ASAF-001",
            status="approved",
            risk_assessment="low",
            risk_score="low",
            created_date=now,
        )
        assert created_uw is not None

    seed_sample_data()  # simulate a restart

    ids = _all_asaf_health_uw_ids()
    assert ids == [], (
        "seeder must purge leftover false-demo UW rows; "
        f"got {ids!r}"
    )
    with DatabaseManager() as db:
        assert db.underwriting.get_by_id(legacy_id) is None
        assert db.policies.get_by_id("POL-ASAF-HEALTH-001") is None
        assert db.customers.get_by_id("CUST-ASAF-001") is not None
