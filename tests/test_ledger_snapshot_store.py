"""The ledger snapshot survives a redeploy without a volume, and never at the cost of a good row."""

from __future__ import annotations

import os

import pytest
import requests

import web_portal.server as portal
from services import ledger_snapshot_store as lss
from services.ledger_snapshot_store import ARTIFACT_ID, LedgerSnapshotStore, build_payload
from services.otp_security_service import _audit_challenge_ref

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")


def _purge():
    from database.manager import DatabaseManager
    from database.models import AgentArtifact
    with DatabaseManager() as db:
        session = db.agent_artifacts.session
        session.query(AgentArtifact).filter(
            AgentArtifact.id.in_([ARTIFACT_ID, lss.STALE_ARTIFACT_ID])
        ).delete(synchronize_session=False)
        session.commit()


def _row():
    from database.manager import DatabaseManager
    from database.models import AgentArtifact
    with DatabaseManager() as db:
        row = db.agent_artifacts.session.get(AgentArtifact, ARTIFACT_ID)
        return None if row is None else (row.payload_json, row.checksum)


@pytest.fixture
def sqlite_db():
    from database import init_database
    init_database()
    _purge()
    yield
    _purge()


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _snapshot(balance, saved_at="2026-11-23T15:00:00"):
    return {
        "saved_at": saved_at,
        "version": "2.0",
        "health_wallets": {"CUST-1": {"customer_id": "CUST-1", "balance": balance}},
        "phins_balance_sheet": {"claims_reserve": 3500000.0, "operating_reserve": 1234.56},
        "transaction_ledger": {"TX-1": {"id": "TX-1"}},
        "media_assets": {"m": {"url": "data:video/mp4;base64,AAAA"}},
        "policies": {},
    }


def _store(**kwargs):
    store = LedgerSnapshotStore(**kwargs)
    store.enable()
    return store


def test_payload_leaves_out_stores_postgres_already_holds():
    payload = build_payload(_snapshot(10.0))
    assert payload["format"] == lss.FORMAT
    assert set(payload["data"]) == {"saved_at", "version", "health_wallets", "phins_balance_sheet"}
    assert payload["omitted"] == ["media_assets", "policies", "transaction_ledger"]


def test_round_trip_restores_the_same_wallets_and_balance_sheet(sqlite_db):
    writer = _store()
    assert writer.load() == ("missing", None)
    assert writer.offer(_snapshot(42.5)) == "written"
    payload_json, checksum = _row()
    assert writer.last_sha256 == checksum

    reader = _store()
    status, data = reader.load()
    assert status == "ok"
    assert data["health_wallets"]["CUST-1"]["balance"] == 42.5
    assert data["phins_balance_sheet"]["operating_reserve"] == 1234.56
    assert "transaction_ledger" not in data
    assert reader.status()["state"] == "ok"


def test_tampered_row_is_not_applied_and_not_overwritten(sqlite_db):
    _store().offer(_snapshot(42.5))
    from database.manager import DatabaseManager
    from database.models import AgentArtifact
    with DatabaseManager() as db:
        row = db.agent_artifacts.session.get(AgentArtifact, ARTIFACT_ID)
        row.payload_json = row.payload_json.replace("42.5", "9999.0")
        db.agent_artifacts.session.commit()
    before = _row()

    store = _store()
    assert store.load() == ("mismatch", None)
    assert store.offer(_snapshot(0.0)) == "blocked"
    assert store.offer(_snapshot(0.0), force=True) == "blocked"
    assert _row() == before
    assert store.status()["state"] == "blocked"


def test_a_failed_read_blocks_writes_so_a_fresh_state_cannot_replace_a_good_row():
    class _Broken:
        def __enter__(self):
            raise RuntimeError("db down")

        def __exit__(self, *exc):
            return False

    store = _store(db_factory=_Broken)
    status, data = store.load()
    assert status == "error" and data is None
    assert store.offer(_snapshot(0.0), force=True) == "blocked"


def test_unknown_row_format_is_refused(sqlite_db):
    from database.manager import DatabaseManager
    with DatabaseManager() as db:
        db.agent_artifacts.upsert(ARTIFACT_ID, agent_id=lss.AGENT_ID, kind=lss.KIND,
                                  payload={"something": "else"})
    before = _row()
    store = _store()
    assert store.load()[0] == "unsupported"
    assert store.offer(_snapshot(1.0)) == "blocked"
    assert _row() == before


def test_writes_are_throttled_and_the_newest_snapshot_wins(sqlite_db):
    clock = _Clock()
    store = _store(min_interval_seconds=60, clock=clock)
    store.load()
    assert store.offer(_snapshot(1.0)) == "written"
    clock.now += 5
    assert store.offer(_snapshot(2.0)) == "throttled"
    assert store.offer(_snapshot(3.0)) == "throttled"
    assert store.status()["state"] == "pending"
    assert _store().load()[1]["health_wallets"]["CUST-1"]["balance"] == 1.0

    clock.now += 60
    assert store.flush() == "written"
    assert _store().load()[1]["health_wallets"]["CUST-1"]["balance"] == 3.0
    assert store.flush() == "idle"

    clock.now += 1
    assert store.offer(_snapshot(4.0), force=True) == "written"
    assert _store().load()[1]["health_wallets"]["CUST-1"]["balance"] == 4.0


def test_oversized_snapshot_is_reported_and_not_written(sqlite_db):
    store = _store(max_bytes=64)
    store.load()
    assert store.offer(_snapshot(1.0)) == "too_large"
    assert _row() is None
    assert store.status()["state"] == "too_large"


def test_a_copy_that_stopped_updating_is_not_restored_by_a_later_boot(sqlite_db):
    clock = _Clock()
    store = _store(min_interval_seconds=60, clock=clock)
    store.load()
    assert store.offer(_snapshot(1.0)) == "written"
    before = _row()

    store.max_bytes = 64
    clock.now += 61
    assert store.offer(_snapshot(2.0)) == "too_large"
    # The oversized snapshot is not serialised again inside the window.
    assert store.offer(_snapshot(3.0)) == "throttled"
    assert _row() == before

    later_boot = _store()
    status, data = later_boot.load()
    assert status == "stale" and data is None
    assert later_boot.offer(_snapshot(0.0), force=True) == "blocked"
    assert _row() == before

    # The process that set the marker clears it with the next snapshot that fits.
    store.max_bytes = lss.DEFAULT_MAX_BYTES
    clock.now += 61
    assert store.offer(_snapshot(4.0)) == "written"
    status, data = _store().load()
    assert status == "ok" and data["health_wallets"]["CUST-1"]["balance"] == 4.0


def test_a_failed_write_is_kept_and_retried_after_the_window(sqlite_db):
    from database.manager import DatabaseManager
    clock = _Clock()
    failing = {"on": False}

    class _Flaky:
        def __enter__(self):
            if failing["on"]:
                raise RuntimeError("db down")
            self._db = DatabaseManager()
            return self._db.__enter__()

        def __exit__(self, *exc):
            return self._db.__exit__(*exc)

    store = _store(db_factory=_Flaky, min_interval_seconds=60, clock=clock)
    store.load()
    failing["on"] = True
    assert store.offer(_snapshot(5.0)) == "error"
    assert store.flush() == "throttled"
    failing["on"] = False
    clock.now += 61
    assert store.flush() == "written"
    assert _store().load()[1]["health_wallets"]["CUST-1"]["balance"] == 5.0


def test_disabled_store_never_touches_the_database():
    store = LedgerSnapshotStore(db_factory=lambda: pytest.fail("no DB access expected"))
    assert store.load() == ("disabled", None)
    assert store.offer(_snapshot(1.0), force=True) == "disabled"


@pytest.fixture
def portal_state(monkeypatch, tmp_path):
    saved = {
        "wallets": dict(portal.HEALTH_WALLETS),
        "bs": dict(portal.PHINS_BALANCE_SHEET),
    }
    monkeypatch.setattr(portal, "LEDGER_PERSISTENCE_FILE", str(tmp_path / "phins_ledger_data.json"))
    yield tmp_path
    portal.HEALTH_WALLETS.clear()
    portal.HEALTH_WALLETS.update(saved["wallets"])
    portal.PHINS_BALANCE_SHEET.clear()
    portal.PHINS_BALANCE_SHEET.update(saved["bs"])


def test_boot_restores_the_database_copy_when_the_file_is_gone(sqlite_db, portal_state, monkeypatch):
    _store().offer(_snapshot(77.0, saved_at="2026-11-23T15:27:00"))
    monkeypatch.setattr(portal, "USE_DATABASE", True)
    monkeypatch.setattr(portal, "database_enabled", True)
    monkeypatch.setattr(portal, "_ledger_snapshot_store", _store())
    portal.HEALTH_WALLETS.pop("CUST-1", None)

    assert portal.load_ledger_data(allow_db_snapshot=True) is True
    assert portal._LEDGER_LOAD_SOURCE == "database"
    assert portal.HEALTH_WALLETS["CUST-1"]["balance"] == 77.0
    assert portal.PHINS_BALANCE_SHEET["operating_reserve"] == 1234.56


def _db_boot(monkeypatch):
    monkeypatch.setattr(portal, "USE_DATABASE", True)
    monkeypatch.setattr(portal, "database_enabled", True)
    store = _store()
    monkeypatch.setattr(portal, "_ledger_snapshot_store", store)
    portal.HEALTH_WALLETS.pop("CUST-1", None)
    return store


def _write_file(snapshot):
    import json
    with open(portal.LEDGER_PERSISTENCE_FILE, "w") as fh:
        json.dump(snapshot, fh)


def test_an_unreadable_file_falls_back_to_the_database_copy(sqlite_db, portal_state, monkeypatch):
    _store().offer(_snapshot(77.0))
    before = _row()
    store = _db_boot(monkeypatch)
    with open(portal.LEDGER_PERSISTENCE_FILE, "w") as fh:
        fh.write('{"health_wallets": {"CUST-1": ')

    assert portal.load_ledger_data(allow_db_snapshot=True) is True
    assert portal._LEDGER_LOAD_SOURCE == "database"
    assert portal.HEALTH_WALLETS["CUST-1"]["balance"] == 77.0
    assert store.blocked_reason is None and _row() == before


def test_the_newer_of_file_and_database_copy_is_restored(sqlite_db, portal_state, monkeypatch):
    _store().offer(_snapshot(77.0, saved_at="2026-11-23T15:27:00"))

    _db_boot(monkeypatch)
    _write_file(_snapshot(10.0, saved_at="2026-11-23T15:00:00"))
    assert portal.load_ledger_data(allow_db_snapshot=True) is True
    assert portal._LEDGER_LOAD_SOURCE == "database"
    assert portal.HEALTH_WALLETS["CUST-1"]["balance"] == 77.0

    _db_boot(monkeypatch)
    _write_file(_snapshot(20.0, saved_at="2026-11-23T15:27:00"))
    assert portal.load_ledger_data(allow_db_snapshot=True) is True
    assert portal._LEDGER_LOAD_SOURCE == "file"
    assert portal.HEALTH_WALLETS["CUST-1"]["balance"] == 20.0

    _db_boot(monkeypatch)
    _write_file(_snapshot(25.0, saved_at="2026-11-23T15:00:00+00:00"))
    assert portal.load_ledger_data(allow_db_snapshot=True) is True
    assert portal._LEDGER_LOAD_SOURCE == "database"

    _db_boot(monkeypatch)
    _write_file(_snapshot(30.0, saved_at="not a timestamp"))
    assert portal.load_ledger_data(allow_db_snapshot=True) is True
    assert portal._LEDGER_LOAD_SOURCE == "file"


def test_a_partly_applied_snapshot_blocks_the_database_copy(sqlite_db, portal_state, monkeypatch):
    _store().offer(_snapshot(77.0))
    before = _row()
    store = _db_boot(monkeypatch)
    broken = _snapshot(5.0, saved_at="2026-11-23T16:00:00")
    broken["nft_ledger"] = ["not", "a", "mapping"]
    _write_file(broken)

    assert portal.load_ledger_data(allow_db_snapshot=True) is False
    assert store.blocked_reason
    assert portal.save_ledger_data(force_db=True) is True
    assert _row() == before


def _stale_copy(saved_at):
    writer = _store()
    assert writer.offer(_snapshot(77.0, saved_at=saved_at)) == "written"
    writer.max_bytes = 64
    assert writer.offer(_snapshot(78.0, saved_at=saved_at), force=True) == "too_large"


def test_a_whole_file_that_is_not_older_replaces_a_copy_that_stopped_updating(
        sqlite_db, portal_state, monkeypatch):
    _stale_copy("2026-11-23T15:00:00")
    store = _db_boot(monkeypatch)
    _write_file(_snapshot(90.0, saved_at="2026-11-23T16:00:00"))

    assert portal.load_ledger_data(allow_db_snapshot=True) is True
    assert portal._LEDGER_LOAD_SOURCE == "file" and store.blocked_reason is None
    assert portal.save_ledger_data(force_db=True) is True
    status, data = _store().load()
    assert status == "ok" and data["health_wallets"]["CUST-1"]["balance"] == 90.0


def test_an_older_file_does_not_replace_a_copy_that_stopped_updating(
        sqlite_db, portal_state, monkeypatch):
    _stale_copy("2026-11-23T15:00:00")
    before = _row()
    store = _db_boot(monkeypatch)
    _write_file(_snapshot(90.0, saved_at="2026-11-23T14:00:00"))

    assert portal.load_ledger_data(allow_db_snapshot=True) is True
    assert store.blocked_reason
    assert portal.save_ledger_data(force_db=True) is True
    assert _row() == before and _store().load()[0] == "stale"


def test_one_shot_commands_do_not_read_the_database_copy(sqlite_db, portal_state, monkeypatch):
    _store().offer(_snapshot(77.0))
    monkeypatch.setattr(portal, "USE_DATABASE", True)
    monkeypatch.setattr(portal, "database_enabled", True)
    monkeypatch.setattr(portal, "_ledger_snapshot_store", _store())
    portal.HEALTH_WALLETS.pop("CUST-1", None)

    assert portal.load_ledger_data() is False
    assert "CUST-1" not in portal.HEALTH_WALLETS


def test_save_offers_the_frozen_snapshot_without_db_authoritative_stores(portal_state, monkeypatch):
    offered = []

    class _Recorder:
        enabled = True
        last_status = None

        def offer(self, snapshot, *, force=False):
            offered.append((snapshot, force))
            return "written"

    monkeypatch.setattr(portal, "_ledger_snapshot_store", _Recorder())
    assert portal.save_ledger_data(force_db=True) is True
    assert os.path.exists(portal.LEDGER_PERSISTENCE_FILE)
    snapshot, force = offered[-1]
    assert force is True
    assert "health_wallets" in snapshot and "phins_balance_sheet" in snapshot
    payload = build_payload(snapshot)
    assert "transaction_ledger" not in payload["data"]


def test_data_dir_created_by_the_image_is_not_a_volume(portal_state, monkeypatch):
    monkeypatch.delenv("LEDGER_PERSISTENCE_FILE", raising=False)
    monkeypatch.delenv("RAILWAY_VOLUME_MOUNT_PATH", raising=False)
    monkeypatch.setattr(portal, "LEDGER_PERSISTENCE_FILE", "/var/lib/phins-not-mounted/phins_ledger_data.json")
    assert portal.persistence_file_on_volume() is False
    monkeypatch.setenv("RAILWAY_VOLUME_MOUNT_PATH", "/var/lib/phins-not-mounted")
    assert portal.persistence_file_on_volume() is True


def test_health_reports_where_the_snapshot_survives():
    body = requests.get(f"{BASE_URL}/api/health", timeout=30).json()
    persistence = body["persistence"]
    assert set(persistence) == {"enabled", "file_on_volume", "database_copy"}
    assert persistence["database_copy"] in {"disabled", "unavailable"}


def test_captcha_audit_logs_a_fingerprint_not_the_signed_ticket():
    ticket = "cchal1.eyJhaCI6WyJkNDcz.signature"
    ref = _audit_challenge_ref(ticket)
    assert ref.startswith("cchal1:sha256:") and len(ref) == len("cchal1:sha256:") + 16
    assert "eyJ" not in ref
    assert _audit_challenge_ref(ticket) == ref
    assert _audit_challenge_ref("CAPTCHA-123") == "CAPTCHA-123"
