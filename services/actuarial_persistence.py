"""
Durable persistence for the actuary dashboard store (central pricing control).

Dashboard adjustments to underwriting config (Pricing Parameters) and rate
tables must survive process restart AND container redeploys. Two layers:

1. **File snapshot** — JSON at ``PHINS_ACTUARIAL_STATE_PATH`` (default
   ``data/actuarial_store_state.json``). Fast local cache; ephemeral on
   container platforms (Railway/Render redeploys wipe it).
2. **Database snapshot** — a row in ``actuarial_tables``
   (``table_type='actuarial_store_state'``, payload = encrypted VaultBlob of
   the full snapshot). Survives redeploys whenever ``DATABASE_URL`` /
   ``USE_DATABASE`` is configured. Written best-effort on every save; read
   FIRST on load so a fresh container picks up the last saved pricing state.

Data integrity: every snapshot embeds ``integrity_sha256`` over its canonical
core (versions + config + current_version + state_revision). Snapshots that
fail the checksum, or whose mortality/disability tables are truncated (which
would silently price seniors at qx=0), are refused at load and the next
source (or built-in defaults) is used instead.

Fail-open relative to pricing: load/save errors are logged and never crash
the portal. Callers may surface a ``persistence_warning`` on API responses.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("phins.actuarial_persistence")

DEFAULT_STATE_PATH = os.environ.get(
    "PHINS_ACTUARIAL_STATE_PATH",
    os.path.join("data", "actuarial_store_state.json"),
)

# DB snapshot row identity
DB_SNAPSHOT_TABLE_TYPE = "actuarial_store_state"
DB_SNAPSHOT_NAME = "Central Pricing Control State"
# Keep this many DB snapshots for audit/rollback; prune older ones.
DB_SNAPSHOT_RETENTION = 30

# Sanity floor: mortality/disability tables must cover attained ages at least
# this high, otherwise senior pricing silently reads qx/ix = 0.
MIN_TABLE_AGE_COVERAGE = 100


def _state_path() -> Path:
    raw = os.environ.get("PHINS_ACTUARIAL_STATE_PATH", DEFAULT_STATE_PATH)
    path = Path(raw)
    if not path.is_absolute():
        # Resolve relative to repo root when possible
        root = Path(__file__).resolve().parents[1]
        path = root / path
    return path


def _database_persistence_enabled() -> bool:
    """DB snapshots follow the server's USE_DATABASE gate (default on)."""
    raw = os.environ.get("USE_DATABASE", "true")
    return str(raw).strip().lower() in ("1", "true", "yes", "y")


def _snapshot_core(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "current_version": payload.get("current_version"),
        "config": payload.get("config"),
        "versions": payload.get("versions"),
        "state_revision": payload.get("state_revision", 0),
    }


def compute_snapshot_checksum(payload: Dict[str, Any]) -> str:
    """SHA-256 over the canonical JSON of the snapshot's pricing core."""
    canonical = json.dumps(
        _snapshot_core(payload), sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_snapshot_tables(payload: Dict[str, Any]) -> Optional[str]:
    """Return an error string when the snapshot is unsafe to price from.

    Guards against truncated persisted state (e.g. a mortality table that
    stops at age 50 makes every senior qx read 0 and collapses premiums).
    """
    versions = payload.get("versions") or {}
    current = payload.get("current_version")
    if not isinstance(versions, dict) or not versions:
        return "snapshot has no table versions"
    if not current or current not in versions:
        return f"current_version {current!r} missing from versions"

    tables = versions.get(current) or {}
    required = (
        "mortality_rates",
        "disability_incidence_rates",
        "adl_mortality_multipliers",
        "adl_disability_multipliers",
    )
    for name in required:
        rows = tables.get(name)
        if not isinstance(rows, list) or not rows:
            return f"current version missing table {name}"

    for name in ("mortality_rates", "disability_incidence_rates"):
        max_age = 0
        senior_rate_positive = False
        for row in tables.get(name, []):
            try:
                age_max = int(row.get("age_max", row.get("age", 0)) or 0)
            except (TypeError, ValueError):
                continue
            max_age = max(max_age, age_max)
            try:
                rate = float(row.get("rate_per_1000") or 0.0)
            except (TypeError, ValueError):
                rate = 0.0
            if age_max >= 65 and rate > 0:
                senior_rate_positive = True
        if max_age < MIN_TABLE_AGE_COVERAGE:
            return (
                f"{name} truncated: covers only to age {max_age} "
                f"(need >= {MIN_TABLE_AGE_COVERAGE}); seniors would price at rate 0"
            )
        if not senior_rate_positive:
            return f"{name} has no positive senior rates (age >= 65)"

    return None


def serialize_store(store: Any) -> Dict[str, Any]:
    cfg = store.config
    payload = {
        "schema_version": 2,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "state_revision": int(getattr(store, "state_revision", 0) or 0),
        "current_version": store.current_version,
        "config": asdict(cfg) if hasattr(cfg, "__dataclass_fields__") else dict(cfg or {}),
        "versions": store.versions,
    }
    payload["integrity_sha256"] = compute_snapshot_checksum(payload)
    return payload


def _persist_to_file(payload: Dict[str, Any], target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    os.replace(tmp, target)
    return str(target)


def _persist_to_database(payload: Dict[str, Any]) -> str:
    """Write a durable DB snapshot row. Returns the row id. Raises on failure."""
    from database.manager import DatabaseManager
    from database.models import ActuarialTable

    try:
        from security.vault import encrypt_json
        blob = encrypt_json(payload).to_json()
    except Exception:
        blob = json.dumps({"scheme": "plain", "ciphertext": json.dumps(payload, default=str)})

    now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC (column convention)
    row_id = f"ACTSTATE-{now.strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
    cfg = payload.get("config") or {}
    version_label = (
        f"{payload.get('current_version', '?')}"
        f"|{cfg.get('config_version', '?')}"
        f"|r{payload.get('state_revision', 0)}"
    )
    with DatabaseManager() as db:
        db.actuarial.create(ActuarialTable(
            id=row_id,
            name=DB_SNAPSHOT_NAME,
            table_type=DB_SNAPSHOT_TABLE_TYPE,
            version=version_label,
            effective_date=now,
            payload=blob,
            classification="restricted",
            created_by=str(cfg.get("modified_by") or "system"),
        ))
        # Prune old snapshots beyond the retention window (keep audit trail
        # shallow; the append-only actuary audit log records every change).
        try:
            from database.models import ActuarialTable as _AT
            stale = (
                db.actuarial.session.query(_AT)
                .filter(_AT.table_type == DB_SNAPSHOT_TABLE_TYPE)
                .order_by(_AT.created_date.desc(), _AT.id.desc())
                .offset(DB_SNAPSHOT_RETENTION)
                .all()
            )
            for row in stale:
                db.actuarial.session.delete(row)
        except Exception as prune_err:
            logger.debug("Snapshot prune skipped: %s", prune_err)
    return row_id


def _load_from_database() -> Optional[Dict[str, Any]]:
    """Read the newest DB snapshot payload, or None."""
    from database.manager import DatabaseManager

    with DatabaseManager() as db:
        row = db.actuarial.latest_by_type(DB_SNAPSHOT_TABLE_TYPE)
        if row is None:
            return None
        raw = row.payload
    try:
        from security.vault import decrypt_json
        payload = decrypt_json(raw, default=None)
    except Exception:
        payload = None
    if payload is None:
        try:
            obj = json.loads(raw)
            payload = json.loads(obj.get("ciphertext") or "null")
        except Exception:
            payload = None
    return payload if isinstance(payload, dict) else None


def persist_actuarial_store(store: Any, path: Optional[str] = None) -> Dict[str, Any]:
    """Persist store state to the file cache and (when enabled) the database.

    Returns a report dict:
    ``{"path", "file_persisted", "db_persisted", "db_enabled", "db_snapshot_id",
    "state_revision", "warning"}``.

    Raises only when NOTHING durable could be written (both layers failed, or
    the file failed with the database layer disabled) so callers can surface
    ``persistence_warning`` on the API response.
    """
    # Refuse to persist a state that could not safely be loaded back.
    payload_probe = serialize_store(store)
    sanity_error = validate_snapshot_tables(payload_probe)
    if sanity_error:
        raise ValueError(f"refusing to persist unsafe pricing state: {sanity_error}")

    # Monotonic revision so operators can correlate file/DB snapshots.
    store.state_revision = int(getattr(store, "state_revision", 0) or 0) + 1
    payload = serialize_store(store)

    report: Dict[str, Any] = {
        "path": None,
        "file_persisted": False,
        "db_persisted": False,
        "db_enabled": _database_persistence_enabled(),
        "db_snapshot_id": None,
        "state_revision": payload["state_revision"],
        "warning": None,
    }

    file_error: Optional[Exception] = None
    target = Path(path) if path else _state_path()
    try:
        report["path"] = _persist_to_file(payload, target)
        report["file_persisted"] = True
    except Exception as exc:
        file_error = exc
        logger.warning("File persistence failed (%s): %s", target, exc)

    db_error: Optional[Exception] = None
    if report["db_enabled"]:
        try:
            report["db_snapshot_id"] = _persist_to_database(payload)
            report["db_persisted"] = True
        except Exception as exc:
            db_error = exc
            logger.warning("Database persistence failed: %s", exc)

    if not report["file_persisted"] and not report["db_persisted"]:
        raise RuntimeError(
            f"actuarial state not persisted (file: {file_error}; db: {db_error})"
        )

    if report["db_enabled"] and not report["db_persisted"]:
        report["warning"] = (
            "saved to local file only — database snapshot failed; state may "
            f"not survive a redeploy ({db_error})"
        )
    elif not report["file_persisted"]:
        report["warning"] = f"database snapshot saved; local file write failed ({file_error})"

    logger.info(
        "Persisted actuarial store r%s (tables=%s config=%s file=%s db=%s)",
        payload["state_revision"], store.current_version,
        getattr(store.config, "config_version", "?"),
        report["file_persisted"], report["db_persisted"],
    )
    return report


def _verify_snapshot(payload: Dict[str, Any], source: str) -> bool:
    """Checksum + sanity checks. Returns True when safe to apply."""
    declared = payload.get("integrity_sha256")
    if declared:
        actual = compute_snapshot_checksum(payload)
        if actual != declared:
            logger.warning(
                "Rejecting %s actuarial snapshot: checksum mismatch (%s != %s)",
                source, actual[:12], str(declared)[:12],
            )
            return False
    sanity_error = validate_snapshot_tables(payload)
    if sanity_error:
        logger.warning("Rejecting %s actuarial snapshot: %s", source, sanity_error)
        return False
    return True


def _apply_snapshot(store: Any, payload: Dict[str, Any]) -> bool:
    versions = payload.get("versions") or {}
    if isinstance(versions, dict) and versions:
        store.versions = versions
    current = payload.get("current_version")
    if current and current in store.versions:
        store.current_version = current
    store.state_revision = int(payload.get("state_revision", 0) or 0)

    cfg_data = payload.get("config") or {}
    if cfg_data:
        try:
            from services.actuarial_service import UnderwritingConfig
            # Only pass known fields
            fields = getattr(UnderwritingConfig, "__dataclass_fields__", {})
            kwargs = {k: v for k, v in cfg_data.items() if k in fields}
            # Ensure new band fields exist even on older snapshots
            kwargs.setdefault("disability_share_of_life", 0.25)
            kwargs.setdefault("disability_share_of_life_post65", 1.0)
            kwargs.setdefault("life_share_of_coverage", 1.0)
            kwargs.setdefault("life_share_of_coverage_post65", 0.25)
            kwargs.setdefault("disability_band_age", 65)
            kwargs.setdefault("pre65_disability_continues_policy", True)
            kwargs.setdefault("post_disability_life_share_of_face", 0.75)
            kwargs.setdefault("post_disability_premium_factor", 1.0)
            kwargs.setdefault("post65_claims_mutually_exclusive", True)
            for _k in (
                "smoker_mortality_factor", "smoker_disability_factor",
                "former_smoker_mortality_factor", "former_smoker_disability_factor",
                "nonsmoker_mortality_factor", "nonsmoker_disability_factor",
                "male_mortality_factor", "male_disability_factor",
                "female_mortality_factor", "female_disability_factor",
            ):
                kwargs.setdefault(_k, 1.0)
            kwargs.setdefault(
                "ethnicity_mortality_factors",
                {"caucasian": 1.0, "african": 1.0, "hispanic": 1.0, "asian": 1.0, "other": 1.0},
            )
            kwargs.setdefault(
                "ethnicity_disability_factors",
                {"caucasian": 1.0, "african": 1.0, "hispanic": 1.0, "asian": 1.0, "other": 1.0},
            )
            kwargs.setdefault("config_version", "cfg_v1")
            store.config = UnderwritingConfig(**kwargs)
        except Exception as exc:
            logger.warning("Failed to restore actuarial config: %s", exc)
            return False
    return True


def _load_file_payload(target: Path) -> Optional[Dict[str, Any]]:
    if not target.exists():
        return None
    try:
        with open(target, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as exc:
        logger.warning("Failed to read actuarial state %s: %s", target, exc)
        return None
    return payload if isinstance(payload, dict) else None


def load_actuarial_store(store: Any, path: Optional[str] = None) -> bool:
    """Load persisted state into an existing store instance.

    With an explicit ``path``, only that file is considered (test isolation).
    Otherwise the newest DATABASE snapshot wins (it survives redeploys),
    falling back to the local file cache. Snapshots failing checksum or
    table-sanity validation are skipped. Returns True if state was applied.
    """
    if path is not None:
        payload = _load_file_payload(Path(path))
        if payload is None or not _verify_snapshot(payload, f"file {path}"):
            return False
        if not _apply_snapshot(store, payload):
            return False
        logger.info("Loaded actuarial store from %s (tables=%s config=%s)",
                    path, store.current_version,
                    getattr(store.config, "config_version", "?"))
        return True

    if _database_persistence_enabled():
        try:
            payload = _load_from_database()
        except Exception as exc:
            logger.warning("Database snapshot load failed: %s", exc)
            payload = None
        if payload is not None and _verify_snapshot(payload, "database"):
            if _apply_snapshot(store, payload):
                logger.info(
                    "Loaded actuarial store from database snapshot r%s "
                    "(tables=%s config=%s)",
                    payload.get("state_revision", "?"), store.current_version,
                    getattr(store.config, "config_version", "?"),
                )
                return True

    target = _state_path()
    payload = _load_file_payload(target)
    if payload is None or not _verify_snapshot(payload, f"file {target}"):
        return False
    if not _apply_snapshot(store, payload):
        return False
    logger.info("Loaded actuarial store from %s (tables=%s config=%s)",
                target, store.current_version,
                getattr(store.config, "config_version", "?"))
    return True
