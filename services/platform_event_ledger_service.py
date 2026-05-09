"""
Platform event ledger service.

Provides a tamper-evident append-only ledger for transactions and operational
events. The service keeps the existing in-memory transaction ledger compatible
while enriching entries with sequence numbers and hash chaining. When database
mode is available it can also persist the same entries into SQL for long-term
traceability.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, MutableMapping, Optional
import hashlib
import json
import logging
import uuid

logger = logging.getLogger(__name__)

LEDGER_VERSION = "2.0"


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_metadata(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except Exception:
                return value
    return value


def normalize_ledger_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a ledger entry across legacy and current schemas."""
    normalized = dict(entry or {})
    entry_id = normalized.get("id") or normalized.get("tx_id")
    if entry_id:
        normalized["id"] = entry_id
        normalized.setdefault("tx_id", entry_id)
    if normalized.get("type") and not normalized.get("event_type"):
        normalized["event_type"] = normalized["type"]
    elif normalized.get("event_type") and not normalized.get("type"):
        normalized["type"] = normalized["event_type"]

    for key in ("metadata", "details", "payload"):
        if key in normalized:
            normalized[key] = _normalize_metadata(normalized[key])

    return normalized


def _canonical_entry_payload(entry: Dict[str, Any]) -> str:
    payload = normalize_ledger_entry(entry)
    for key in ("entry_hash", "previous_hash"):
        payload.pop(key, None)
    return json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))


def compute_entry_hash(entry: Dict[str, Any], previous_hash: str = "") -> str:
    normalized = normalize_ledger_entry(entry)
    base = "|".join(
        [
            str(normalized.get("id", "")),
            str(normalized.get("sequence_no", "")),
            str(normalized.get("event_type") or normalized.get("type") or ""),
            previous_hash or "",
            _canonical_entry_payload(normalized),
        ]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def sort_ledger_entries(entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def sort_key(item: Dict[str, Any]) -> tuple:
        normalized = normalize_ledger_entry(item)
        raw_sequence = normalized.get("sequence_no")
        try:
            sequence_key = int(raw_sequence)
        except (TypeError, ValueError):
            sequence_key = 10**12

        timestamp_key = str(
            normalized.get("timestamp")
            or normalized.get("created_at")
            or normalized.get("recorded_at")
            or ""
        )
        return (sequence_key, timestamp_key, str(normalized.get("id", "")))

    return sorted((normalize_ledger_entry(entry) for entry in entries), key=sort_key)


def reconcile_ledger_entries(entries: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate hash chain, sequencing, and aggregate coverage."""
    sorted_entries = sort_ledger_entries(entries)
    seen_ids = set()
    previous_hash = ""
    broken_links = []
    sequence_gaps = []
    duplicate_ids = []
    missing_hash_ids = []
    orphaned_entries = []
    type_counts: Dict[str, int] = {}
    amount_total = 0.0

    for expected_sequence, entry in enumerate(sorted_entries, start=1):
        entry_id = str(entry.get("id") or "")
        event_type = str(entry.get("event_type") or entry.get("type") or "unknown")
        type_counts[event_type] = type_counts.get(event_type, 0) + 1
        amount_total += _safe_float(entry.get("amount", 0))

        if not entry.get("customer_id") and not entry.get("entity_id"):
            orphaned_entries.append(entry_id)

        if entry_id in seen_ids:
            duplicate_ids.append(entry_id)
        seen_ids.add(entry_id)

        if entry.get("sequence_no") != expected_sequence:
            sequence_gaps.append(
                {
                    "entry_id": entry_id,
                    "expected_sequence": expected_sequence,
                    "actual_sequence": entry.get("sequence_no"),
                }
            )

        entry_previous_hash = str(entry.get("previous_hash") or "")
        entry_hash = str(entry.get("entry_hash") or "")
        if expected_sequence > 1 and not entry_previous_hash:
            missing_hash_ids.append(entry_id)
        if not entry_hash:
            missing_hash_ids.append(entry_id)

        expected_hash = compute_entry_hash(entry, previous_hash)
        if entry_previous_hash != previous_hash or entry_hash != expected_hash:
            broken_links.append(
                {
                    "entry_id": entry_id,
                    "expected_previous_hash": previous_hash,
                    "actual_previous_hash": entry_previous_hash,
                    "expected_hash": expected_hash,
                    "actual_hash": entry_hash,
                }
            )

        previous_hash = entry_hash or expected_hash

    chain_valid = not broken_links and not sequence_gaps and not duplicate_ids and not missing_hash_ids
    return {
        "total_entries": len(sorted_entries),
        "chain_valid": chain_valid,
        "status": "valid" if chain_valid else "critical",
        "broken_links": broken_links,
        "sequence_gaps": sequence_gaps,
        "duplicate_ids": duplicate_ids,
        "missing_hash_ids": sorted(set(missing_hash_ids)),
        "orphaned_entries": orphaned_entries,
        "type_counts": type_counts,
        "amount_total": round(amount_total, 2),
        "latest_hash": previous_hash,
    }


class PlatformEventLedgerService:
    """Append-only event ledger with optional SQL persistence."""

    def __init__(
        self,
        transaction_ledger: MutableMapping[str, Dict[str, Any]],
        use_database: bool | Callable[[], bool] = False,
        db_manager_factory: Optional[Callable[[], Any]] = None,
    ):
        self.transaction_ledger = transaction_ledger
        self._use_database = use_database
        self._db_manager_factory = db_manager_factory

    def _database_enabled(self) -> bool:
        try:
            return bool(self._use_database() if callable(self._use_database) else self._use_database)
        except Exception:
            return False

    def _get_db_manager_factory(self) -> Callable[[], Any]:
        if self._db_manager_factory is not None:
            return self._db_manager_factory

        from database.manager import DatabaseManager

        return DatabaseManager

    def _get_latest_memory_entry(self) -> Optional[Dict[str, Any]]:
        if not self.transaction_ledger:
            return None
        return sort_ledger_entries(self.transaction_ledger.values())[-1]

    def _get_latest_db_entry(self) -> Optional[Dict[str, Any]]:
        if not self._database_enabled():
            return None
        try:
            db_factory = self._get_db_manager_factory()
            with db_factory() as db:
                latest = db.platform_ledger.get_latest_entry()
                return latest.to_dict() if latest else None
        except Exception as exc:
            logger.debug("Platform ledger DB latest entry unavailable: %s", exc)
            return None

    def _get_latest_entry(self) -> Optional[Dict[str, Any]]:
        latest_memory = self._get_latest_memory_entry()
        latest_db = self._get_latest_db_entry()

        if latest_memory is None:
            return latest_db
        if latest_db is None:
            return latest_memory

        memory_sequence = int(latest_memory.get("sequence_no") or 0)
        db_sequence = int(latest_db.get("sequence_no") or 0)
        return latest_memory if memory_sequence >= db_sequence else latest_db

    def append_event(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        customer_id: Optional[str] = None,
        actor: str = "system",
        amount: float = 0.0,
        currency: str = "USD",
        status: str = "recorded",
        source_system: str = "web_portal",
        payload: Optional[Dict[str, Any]] = None,
        entry_id: Optional[str] = None,
        ledger_type: str = "event",
        timestamp: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Append a ledger entry and optionally persist it to SQL."""
        prepared = normalize_ledger_entry(payload or {})
        resolved_entry_id = str(
            entry_id or prepared.get("id") or f"LED-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}"
        )

        existing = self.transaction_ledger.get(resolved_entry_id)
        if existing is not None:
            return normalize_ledger_entry(existing)

        latest = self._get_latest_entry() or {}
        next_sequence = int(latest.get("sequence_no") or 0) + 1
        previous_hash = str(latest.get("entry_hash") or "")

        prepared.update(
            {
                "id": resolved_entry_id,
                "tx_id": prepared.get("tx_id") or resolved_entry_id,
                "type": prepared.get("type") or event_type,
                "event_type": event_type,
                "ledger_type": prepared.get("ledger_type") or ledger_type,
                "entity_type": prepared.get("entity_type") or entity_type,
                "entity_id": prepared.get("entity_id") or entity_id,
                "customer_id": prepared.get("customer_id") or customer_id,
                "actor": prepared.get("actor") or actor,
                "amount": round(_safe_float(prepared.get("amount", amount)), 2),
                "currency": prepared.get("currency") or currency,
                "status": prepared.get("status") or status,
                "source_system": prepared.get("source_system") or source_system,
                "timestamp": prepared.get("timestamp") or timestamp or datetime.utcnow().isoformat(),
                "recorded_at": prepared.get("recorded_at") or datetime.utcnow().isoformat(),
                "sequence_no": next_sequence,
                "ledger_version": prepared.get("ledger_version") or LEDGER_VERSION,
                "previous_hash": previous_hash,
            }
        )
        prepared["entry_hash"] = compute_entry_hash(prepared, previous_hash)

        self.transaction_ledger[resolved_entry_id] = prepared
        self._persist_entry(prepared)
        return prepared

    def ensure_hash_chain(self) -> Dict[str, Any]:
        """Backfill sequence numbers and hashes for legacy entries."""
        repaired_entries = 0
        previous_hash = ""
        sorted_entries = sort_ledger_entries(self.transaction_ledger.values())

        for sequence_no, entry in enumerate(sorted_entries, start=1):
            normalized = normalize_ledger_entry(entry)
            normalized.setdefault("recorded_at", normalized.get("timestamp") or datetime.utcnow().isoformat())
            normalized.setdefault("event_type", normalized.get("type") or "event")
            normalized.setdefault("type", normalized.get("event_type") or "event")
            normalized.setdefault("entity_type", normalized.get("entity_type") or "transaction")
            normalized.setdefault("entity_id", normalized.get("entity_id") or normalized.get("id"))
            normalized.setdefault("ledger_type", normalized.get("ledger_type") or "event")
            normalized["sequence_no"] = sequence_no
            normalized["previous_hash"] = previous_hash
            normalized["ledger_version"] = LEDGER_VERSION
            expected_hash = compute_entry_hash(normalized, previous_hash)
            needs_update = (
                normalized.get("sequence_no") != sequence_no
                or normalized.get("previous_hash") != previous_hash
                or normalized.get("entry_hash") != expected_hash
                or normalized.get("ledger_version") != LEDGER_VERSION
            )

            normalized["entry_hash"] = expected_hash
            self.transaction_ledger[normalized["id"]] = normalized

            if needs_update:
                repaired_entries += 1

            previous_hash = normalized["entry_hash"]

        summary = reconcile_ledger_entries(self.transaction_ledger.values())
        summary["repaired_entries"] = repaired_entries
        return summary

    def get_integrity_summary(self) -> Dict[str, Any]:
        return reconcile_ledger_entries(self.transaction_ledger.values())

    def hydrate_from_db(self, limit: int = 10000) -> int:
        """Load existing platform_ledger rows from SQL into the in-memory ledger.

        Used after a fresh container start when the JSON persistence file is
        missing but PostgreSQL already contains entries from prior runs. Without
        this hydration, subsequent ``append_event()`` calls observe an empty
        in-memory ledger and a non-empty DB, so they assign sequence numbers
        starting at ``latest_db.sequence_no + 1`` while the DB still holds the
        original (sequence_no=1..N) rows for the same IDs. The result on
        startup integrity validation is "1 broken link, N sequence gaps" and
        a permanent memory↔DB chain divergence.

        Memory entries always take precedence; rows whose IDs are already in
        the in-memory ledger are skipped. Returns the number of rows loaded.
        """
        if not self._database_enabled():
            return 0

        try:
            db_factory = self._get_db_manager_factory()
            with db_factory() as db:
                rows = db.platform_ledger.get_all_by_sequence(limit=limit)
        except Exception as exc:
            logger.warning("Platform ledger DB hydration failed: %s", exc)
            return 0

        loaded = 0
        for row in rows or []:
            if row is None:
                continue
            try:
                record = row.to_dict()
            except Exception:
                continue

            entry_id = record.get("id")
            if not entry_id or entry_id in self.transaction_ledger:
                continue

            payload = record.get("payload")
            if isinstance(payload, dict) and payload.get("id") == entry_id:
                # The persisted JSON payload is the canonical write-time entry
                # (it includes sequence_no, previous_hash, entry_hash). Use it
                # directly so the chain hashes the same way it did originally.
                merged: Dict[str, Any] = dict(payload)
            else:
                merged = {}

            for column in (
                "id",
                "sequence_no",
                "ledger_type",
                "event_type",
                "entity_type",
                "entity_id",
                "customer_id",
                "actor",
                "amount",
                "currency",
                "status",
                "source_system",
                "previous_hash",
                "entry_hash",
                "timestamp",
            ):
                value = record.get(column)
                if value is not None and merged.get(column) in (None, ""):
                    merged[column] = value

            merged.setdefault("tx_id", entry_id)
            merged.setdefault("type", merged.get("event_type") or "event")
            merged.setdefault("ledger_version", LEDGER_VERSION)

            self.transaction_ledger[entry_id] = merged
            loaded += 1

        if loaded:
            logger.info("Hydrated %d platform ledger entries from DB", loaded)
        return loaded

    def _persist_entry(self, entry: Dict[str, Any]) -> None:
        if not self._database_enabled():
            return

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                db_factory = self._get_db_manager_factory()
                with db_factory() as db:
                    if db.platform_ledger.get_by_id(entry["id"]):
                        return
                    db.platform_ledger.record_event(
                        id=entry["id"],
                        sequence_no=entry["sequence_no"],
                        timestamp=entry["timestamp"],
                        ledger_type=entry.get("ledger_type", "event"),
                        event_type=entry.get("event_type") or entry.get("type") or "event",
                        entity_type=entry.get("entity_type"),
                        entity_id=entry.get("entity_id"),
                        customer_id=entry.get("customer_id"),
                        actor=entry.get("actor"),
                        amount=entry.get("amount", 0.0),
                        currency=entry.get("currency", "USD"),
                        status=entry.get("status", "recorded"),
                        source_system=entry.get("source_system", "web_portal"),
                        previous_hash=entry.get("previous_hash"),
                        entry_hash=entry.get("entry_hash"),
                        payload=entry,
                    )
                return
            except Exception as exc:
                if attempt < max_retries:
                    logger.debug("Ledger persist retry %d for %s: %s", attempt + 1, entry.get("id"), exc)
                    continue
                logger.warning("Platform ledger persistence failed for %s: %s", entry.get("id"), exc)
