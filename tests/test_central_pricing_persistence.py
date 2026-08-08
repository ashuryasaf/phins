"""Central pricing control durability: config + rate-table saves must survive
restart/redeploy (file + database snapshot), version on every table edit, and
refuse corrupted or truncated snapshots (data integrity)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from services.actuarial_service import ActuarialTablesStore
from services.actuarial_persistence import (
    compute_snapshot_checksum,
    load_actuarial_store,
    persist_actuarial_store,
    serialize_store,
    validate_snapshot_tables,
)


@pytest.fixture()
def isolated_state(tmp_path, monkeypatch):
    state = tmp_path / "actuarial_store_state.json"
    monkeypatch.setenv("PHINS_ACTUARIAL_STATE_PATH", str(state))
    monkeypatch.setenv("USE_DATABASE", "false")
    return state


def test_config_save_survives_restart(isolated_state):
    store = ActuarialTablesStore()
    result = store.update_config(
        {"post_disability_premium_factor": 0.9, "smoker_mortality_factor": 1.8},
        user="pytest",
    )
    assert result["success"] is True
    assert result["persisted"] is True
    assert result["state_revision"] == 1
    assert result.get("persistence_warning") is None

    restored = ActuarialTablesStore()
    assert load_actuarial_store(restored, str(isolated_state)) is True
    assert restored.config.post_disability_premium_factor == pytest.approx(0.9)
    assert restored.config.smoker_mortality_factor == pytest.approx(1.8)
    assert restored.config.config_version == store.config.config_version
    assert restored.state_revision == 1


def test_rate_table_edit_creates_subversion_and_survives_restart(isolated_state):
    store = ActuarialTablesStore()
    new_adl = [{"adl": i, "multiplier": 0.5 + i * 0.2} for i in range(1, 11)]
    result = store.update_current_tables("adl_disability_multipliers", new_adl, "pytest")
    assert result["success"] is True
    assert result["version"] == "V2.0.1"
    assert result["persisted"] is True
    assert store.current_version == "V2.0.1"
    assert store.versions["V2.0"]["status"] == "archived"
    assert store.versions["V2.0.1"]["status"] == "active"
    assert store.versions["V2.0.1"]["parent_version"] == "V2.0"
    # The archived version keeps its original rows for audit resolution.
    assert store.versions["V2.0"]["adl_disability_multipliers"][0]["multiplier"] == pytest.approx(0.3)

    # Kernel pricing stamps the new sub-version into every priced policy.
    from services.pricing_kernel import table_set_from_store
    assert table_set_from_store(store).version == "V2.0.1"

    restored = ActuarialTablesStore()
    assert load_actuarial_store(restored, str(isolated_state)) is True
    assert restored.current_version == "V2.0.1"
    assert restored.get_adl_disability_multiplier(10) == pytest.approx(2.5)

    # A second edit becomes V2.0.2 under the same major.minor.
    second = store.update_current_tables(
        "adl_mortality_multipliers",
        [{"adl": i, "multiplier": 1.0} for i in range(1, 11)],
        "pytest",
    )
    assert second["version"] == "V2.0.2"


def test_upload_new_tables_still_works_after_subversions(isolated_state):
    store = ActuarialTablesStore()
    store.update_current_tables(
        "lapse_rates", [{"year": 1, "rate": 0.05}], "pytest"
    )
    assert store.current_version == "V2.0.1"

    tables = {k: v for k, v in store.get_current_tables().items()
              if isinstance(v, list)}
    result = store.upload_new_tables(tables, "pytest")
    assert result["success"] is True
    assert result["version"] == "V2.1"
    assert store.current_version == "V2.1"


def test_reset_table_persists_and_subversions(isolated_state):
    store = ActuarialTablesStore()
    store.update_current_tables(
        "adl_benefit_percentages",
        [{"adl": i, "benefit_pct": 0.5} for i in range(1, 11)],
        "pytest",
    )
    result = store.reset_tables_to_default("adl_benefit_percentages", "pytest")
    assert result["success"] is True
    assert result["version"] == "V2.0.2"
    assert result["persisted"] is True

    restored = ActuarialTablesStore()
    assert load_actuarial_store(restored, str(isolated_state)) is True
    assert restored.get_adl_benefit_pct(1) == pytest.approx(0.0)
    assert restored.current_version == "V2.0.2"


def test_tampered_snapshot_rejected(isolated_state):
    store = ActuarialTablesStore()
    store.update_config({"smoker_mortality_factor": 2.0}, user="pytest")

    payload = json.loads(isolated_state.read_text())
    # Simulate silent on-disk corruption of a rate after the save.
    payload["versions"][payload["current_version"]]["mortality_rates"][0]["rate_per_1000"] = 0.0001
    isolated_state.write_text(json.dumps(payload))

    restored = ActuarialTablesStore()
    assert load_actuarial_store(restored, str(isolated_state)) is False
    # Tampered snapshot refused → factory defaults stay in force.
    assert restored.config.smoker_mortality_factor == pytest.approx(1.0)


def test_truncated_mortality_snapshot_rejected(isolated_state):
    store = ActuarialTablesStore()
    persist_actuarial_store(store)

    payload = json.loads(isolated_state.read_text())
    current = payload["current_version"]
    # Truncate mortality to age 50 — seniors would silently price at qx=0.
    payload["versions"][current]["mortality_rates"] = [
        {"age_min": 0, "age_max": 50, "rate_per_1000": 1.0},
    ]
    payload["integrity_sha256"] = compute_snapshot_checksum(payload)  # valid checksum
    isolated_state.write_text(json.dumps(payload))

    assert validate_snapshot_tables(payload) is not None
    restored = ActuarialTablesStore()
    assert load_actuarial_store(restored, str(isolated_state)) is False
    # Store keeps safe defaults with full senior coverage.
    assert restored.get_mortality_rate(80) > 0


def test_persist_refuses_unsafe_state(isolated_state):
    store = ActuarialTablesStore()
    # Corrupt the in-memory state directly (bypassing validated setters).
    store.versions[store.current_version]["mortality_rates"] = [
        {"age_min": 0, "age_max": 40, "rate_per_1000": 1.0},
    ]
    result = store.update_config({"discount_rate": 0.04}, user="pytest")
    assert result["success"] is True  # in-memory update still applies
    assert result["persisted"] is False
    assert "refusing to persist" in result["persistence_warning"]
    assert not isolated_state.exists()


def test_database_snapshot_survives_file_loss(tmp_path, monkeypatch):
    """Redeploy scenario: local file wiped, state restored from the database."""
    state = tmp_path / "act_state.json"
    monkeypatch.setenv("PHINS_ACTUARIAL_STATE_PATH", str(state))
    monkeypatch.setenv("USE_DATABASE", "true")
    monkeypatch.setenv("USE_SQLITE", "true")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "pricing_persist.db"))
    monkeypatch.delenv("DATABASE_URL", raising=False)

    import database as db_module
    db_module.reset_connection()
    try:
        engine = db_module.get_engine()
        db_module.Base.metadata.create_all(engine)

        store = ActuarialTablesStore()
        result = store.update_config(
            {"post_disability_premium_factor": 0.8}, user="pytest"
        )
        assert result["persisted"] is True
        assert result["persisted_to_database"] is True

        table_edit = store.update_current_tables(
            "lapse_rates", [{"year": 1, "rate": 0.07}], "pytest"
        )
        assert table_edit["persisted_to_database"] is True

        # Simulate container redeploy: the local file cache is gone.
        state.unlink()

        restored = ActuarialTablesStore()
        assert load_actuarial_store(restored) is True
        assert restored.config.post_disability_premium_factor == pytest.approx(0.8)
        assert restored.current_version == store.current_version
        assert restored.get_lapse_rate(1) == pytest.approx(0.07)
    finally:
        db_module.reset_connection()


def test_snapshot_checksum_roundtrip(isolated_state):
    store = ActuarialTablesStore()
    payload = serialize_store(store)
    assert payload["integrity_sha256"] == compute_snapshot_checksum(payload)
    assert validate_snapshot_tables(payload) is None


def test_http_saves_report_durability(isolated_state):
    """Config + rate-table save APIs must tell the operator the save is durable
    (persisted flag, sub-version) so 'changes are not persistent' is visible
    immediately instead of after the next redeploy."""
    import threading
    import time
    from http.server import HTTPServer
    from urllib.request import Request, urlopen

    import web_portal.server as portal

    httpd = HTTPServer(("127.0.0.1", 0), portal.PortalHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        time.sleep(0.2)
        base = f"http://127.0.0.1:{port}"

        def post(path, payload, token=None):
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            req = Request(base + path, data=json.dumps(payload).encode("utf-8"),
                          headers=headers, method="POST")
            with urlopen(req) as resp:
                return json.loads(resp.read()), resp.status

        login, _ = post("/api/login", {"username": "admin", "password": "admin123"})
        token = login["token"]

        # Pricing Parameters save reports durable persistence.
        body, status = post("/api/actuarial/config",
                            {"expense_loading_pct": 0.16}, token)
        assert status == 200
        assert body["success"] is True
        assert body["persisted"] is True
        assert body.get("state_revision") >= 1
        assert "persistence_warning" not in body

        # Rate-table save creates a durable sub-version.
        from services.actuarial_service import get_actuarial_store
        store = get_actuarial_store()
        rows = list(store.get_current_tables()["lapse_rates"])
        body, status = post("/api/actuarial/table-update",
                            {"table_type": "lapse_rates", "data": rows}, token)
        assert status == 200
        assert body["success"] is True
        assert body["version"].count(".") == 2  # e.g. V2.0.1 sub-version
        assert body["persisted"] is True

        # Saved state is on disk with a valid checksum → survives restart.
        assert isolated_state.exists()
        payload = json.loads(isolated_state.read_text())
        assert payload["integrity_sha256"] == compute_snapshot_checksum(payload)
        assert payload["current_version"] == body["version"]
    finally:
        httpd.shutdown()
        httpd.server_close()
        # The global store singleton was mutated via the API; reset it so
        # other tests see factory state.
        import services.actuarial_service as asvc
        asvc._actuarial_store = None
