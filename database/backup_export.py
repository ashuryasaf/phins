"""
Structured PHINS database export helpers.

This module creates table-by-table JSON exports and a manifest that can be
stored alongside raw database dumps for easier browsing and restore planning.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import MetaData, Table, inspect, select
from sqlalchemy.engine import Engine

from database import get_engine
from database.config import DatabaseConfig


def _utc_now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def _workspace_root() -> Path:
    return Path(os.environ.get("WORKSPACE_PATH") or Path(__file__).resolve().parents[1])


def _serialize_value(value: Any) -> Any:
    """Convert SQLAlchemy-returned values into JSON-safe primitives."""
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        # Preserve exact values in a JSON-safe format.
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _serialize_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize_value(item) for item in value]
    if hasattr(value, "value"):
        return _serialize_value(value.value)
    return str(value)


def _masked_database_summary() -> Dict[str, Any]:
    summary = DatabaseConfig.get_config_summary()
    database_url = DatabaseConfig.get_database_url()

    target: Dict[str, Any] = {"database_url": summary.get("database_url")}
    if database_url.startswith("sqlite:///"):
        sqlite_path = Path(database_url.replace("sqlite:///", "", 1))
        if not sqlite_path.is_absolute():
            sqlite_path = _workspace_root() / sqlite_path
        target.update(
            {
                "database_type": "sqlite",
                "database_path": str(sqlite_path.resolve()),
                "database_path_exists": sqlite_path.exists(),
            }
        )
    else:
        target.update(
            {
                "database_type": "postgresql",
                "database_path": None,
                "database_path_exists": None,
            }
        )

    return target


def can_export_database() -> Dict[str, Any]:
    """
    Determine whether a structured export can run without creating a new DB.
    """
    target = _masked_database_summary()
    database_type = target["database_type"]

    if database_type == "sqlite":
        if target["database_path_exists"]:
            return {"available": True, "reason": "sqlite database file found", "target": target}
        return {"available": False, "reason": "sqlite database file not found", "target": target}

    postgres_configured = bool(
        os.environ.get(DatabaseConfig.ENV_DATABASE_URL) or os.environ.get(DatabaseConfig.ENV_DB_HOST)
    )
    if postgres_configured:
        return {"available": True, "reason": "postgres configuration detected", "target": target}
    return {"available": False, "reason": "postgres database not configured", "target": target}


def _table_schema(inspector: Any, table_name: str) -> Dict[str, Any]:
    return {
        "columns": [
            {
                "name": column["name"],
                "type": str(column["type"]),
                "nullable": bool(column.get("nullable", True)),
                "default": _serialize_value(column.get("default")),
            }
            for column in inspector.get_columns(table_name)
        ],
        "primary_key": inspector.get_pk_constraint(table_name).get("constrained_columns", []) or [],
    }


def _ordered_select(table: Table) -> Any:
    statement = select(table)
    primary_key_columns = list(table.primary_key.columns)
    if primary_key_columns:
        statement = statement.order_by(*primary_key_columns)
    return statement


def export_database_snapshot(output_dir: str) -> Dict[str, Any]:
    """
    Export all existing database tables into JSON files plus a manifest.

    Returns a manifest dictionary describing the export result.
    """
    availability = can_export_database()
    output_path = Path(output_dir)
    tables_path = output_path / "tables"
    output_path.mkdir(parents=True, exist_ok=True)
    tables_path.mkdir(parents=True, exist_ok=True)

    manifest: Dict[str, Any] = {
        "exported_at": _utc_now(),
        "status": "skipped",
        "database": availability["target"],
        "notes": [],
        "table_count": 0,
        "total_rows": 0,
        "tables": [],
    }

    if not availability["available"]:
        manifest["notes"].append(availability["reason"])
        manifest_path = output_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return manifest

    engine: Engine = get_engine()
    inspector = inspect(engine)
    metadata = MetaData()
    table_names = sorted(inspector.get_table_names())

    with engine.connect() as connection:
        for table_name in table_names:
            table = Table(table_name, metadata, autoload_with=engine)
            schema = _table_schema(inspector, table_name)
            rows: List[Dict[str, Any]] = []

            for row in connection.execute(_ordered_select(table)):
                rows.append({key: _serialize_value(value) for key, value in row._mapping.items()})

            relative_export_path = Path("tables") / f"{table_name}.json"
            export_payload = {
                "table": table_name,
                "exported_at": manifest["exported_at"],
                "row_count": len(rows),
                **schema,
                "rows": rows,
            }
            (output_path / relative_export_path).write_text(
                json.dumps(export_payload, indent=2) + "\n",
                encoding="utf-8",
            )

            manifest["tables"].append(
                {
                    "name": table_name,
                    "row_count": len(rows),
                    "primary_key": schema["primary_key"],
                    "export_file": str(relative_export_path),
                }
            )
            manifest["total_rows"] += len(rows)

    manifest["table_count"] = len(table_names)
    manifest["status"] = "completed"
    manifest["notes"].append("Structured JSON export created for all detected tables.")

    manifest_path = output_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


__all__ = ["can_export_database", "export_database_snapshot"]
