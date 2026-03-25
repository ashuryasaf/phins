import json
from pathlib import Path

from database import close_database, init_database, reset_connection
from database.backup_export import can_export_database, export_database_snapshot
from database.manager import DatabaseManager


def test_export_database_snapshot_writes_manifest_and_table_json(tmp_path, monkeypatch):
    db_path = tmp_path / "backup_test.db"
    export_dir = tmp_path / "export"

    close_database()
    monkeypatch.setenv("USE_DATABASE", "true")
    monkeypatch.setenv("USE_SQLITE", "true")
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    monkeypatch.setenv("PHINS_TEST_MODE", "true")
    reset_connection()
    init_database(drop_existing=True)

    with DatabaseManager() as db:
        db.customers.create(
            id="CUST-BACKUP-001",
            name="Backup Export Customer",
            email="backup.export@example.com",
        )
        db.policies.create(
            id="POL-BACKUP-001",
            customer_id="CUST-BACKUP-001",
            type="life",
            coverage_amount=125000.0,
            annual_premium=1250.0,
            status="active",
        )

    availability = can_export_database()
    assert availability["available"] is True
    assert availability["target"]["database_type"] == "sqlite"

    manifest = export_database_snapshot(str(export_dir))

    assert manifest["status"] == "completed"
    assert manifest["table_count"] >= 2
    assert manifest["total_rows"] >= 2

    manifest_path = export_dir / "manifest.json"
    assert manifest_path.exists()

    saved_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    table_names = {entry["name"] for entry in saved_manifest["tables"]}
    assert "customers" in table_names
    assert "policies" in table_names

    customer_export = export_dir / "tables" / "customers.json"
    policy_export = export_dir / "tables" / "policies.json"
    assert customer_export.exists()
    assert policy_export.exists()

    customer_payload = json.loads(customer_export.read_text(encoding="utf-8"))
    policy_payload = json.loads(policy_export.read_text(encoding="utf-8"))

    assert customer_payload["row_count"] >= 1
    assert any(row["id"] == "CUST-BACKUP-001" for row in customer_payload["rows"])
    assert any(row["id"] == "POL-BACKUP-001" for row in policy_payload["rows"])

    close_database()
    reset_connection()
