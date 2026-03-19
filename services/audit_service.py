from __future__ import annotations

from datetime import datetime
from typing import Dict, Any, List, Callable, Optional
import json
import logging
import os
import uuid

from services.platform_event_ledger_service import compute_entry_hash

logger = logging.getLogger(__name__)


class AuditService:
    def __init__(
        self,
        max_events: int = 5000,
        db_manager_factory: Optional[Callable[[], Any]] = None,
        persist_to_database: Optional[bool] = None,
    ):
        self._events: List[Dict[str, Any]] = []
        self._max_events = max_events
        self._db_manager_factory = db_manager_factory
        self._persist_to_database = (
            persist_to_database
            if persist_to_database is not None
            else os.environ.get("USE_DATABASE", "true").lower() not in ("false", "0", "no")
        )

    def _get_db_manager_factory(self) -> Callable[[], Any]:
        if self._db_manager_factory is not None:
            return self._db_manager_factory

        from database.manager import DatabaseManager

        return DatabaseManager

    def _serialize_details(self, details: Dict[str, Any]) -> str:
        try:
            return json.dumps(details, sort_keys=True, default=str)
        except Exception:
            return json.dumps({"raw_details": str(details)})

    def _deserialize_details(self, details: Any) -> Dict[str, Any]:
        if isinstance(details, dict):
            return details
        if isinstance(details, str) and details:
            try:
                parsed = json.loads(details)
                return parsed if isinstance(parsed, dict) else {"value": parsed}
            except Exception:
                return {"raw_details": details}
        return {}

    def _extract_customer_id(self, entity: str, entity_id: str | int, details: Dict[str, Any]) -> Optional[str]:
        if details.get("customer_id"):
            return str(details["customer_id"])
        if entity == "customer":
            return str(entity_id)
        return None

    def _format_db_log(self, log: Any) -> Dict[str, Any]:
        details = self._deserialize_details(getattr(log, "details", None))
        timestamp = getattr(log, "timestamp", None)
        ts_value = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp or "")
        return {
            "id": getattr(log, "id", None),
            "ts": ts_value,
            "timestamp": ts_value,
            "actor": getattr(log, "username", None) or "system",
            "action": getattr(log, "action", None),
            "entity": getattr(log, "entity_type", None),
            "entity_type": getattr(log, "entity_type", None),
            "entity_id": getattr(log, "entity_id", None),
            "customer_id": getattr(log, "customer_id", None),
            "details": details,
            "ip_address": getattr(log, "ip_address", None),
            "success": getattr(log, "success", True),
        }

    def _persist_event(self, event: Dict[str, Any]) -> None:
        if not self._persist_to_database:
            return

        details = event.get("details", {})
        customer_id = self._extract_customer_id(event["entity"], event["entity_id"], details)

        try:
            db_factory = self._get_db_manager_factory()
            with db_factory() as db:
                db.audit.log_action(
                    username=event["actor"],
                    action=event["action"],
                    entity_type=event["entity"],
                    entity_id=str(event["entity_id"]),
                    details=self._serialize_details(details),
                    customer_id=customer_id,
                    success=event.get("success", True),
                )

                ledger_payload = {
                    "audit_event_id": event["id"],
                    "action": event["action"],
                    "entity": event["entity"],
                    "entity_id": str(event["entity_id"]),
                    "actor": event["actor"],
                    "details": details,
                    "timestamp": event["timestamp"],
                }
                latest_ledger_entry = db.platform_ledger.get_latest_entry()
                sequence_no = (latest_ledger_entry.sequence_no + 1) if latest_ledger_entry else 1
                previous_hash = latest_ledger_entry.entry_hash if latest_ledger_entry else ""
                ledger_entry = {
                    "id": f"AUDIT-{event['id']}",
                    "sequence_no": sequence_no,
                    "timestamp": event["timestamp"],
                    "ledger_type": "audit",
                    "event_type": f"audit.{event['action']}",
                    "entity_type": event["entity"],
                    "entity_id": str(event["entity_id"]),
                    "customer_id": customer_id,
                    "actor": event["actor"],
                    "amount": 0.0,
                    "currency": "USD",
                    "status": "recorded",
                    "source_system": "audit_service",
                    "previous_hash": previous_hash,
                    "payload": ledger_payload,
                }
                ledger_entry["entry_hash"] = compute_entry_hash(ledger_entry, previous_hash)
                db.platform_ledger.record_event(
                    **ledger_entry,
                )
        except Exception as exc:
            logger.debug("Audit persistence unavailable: %s", exc)

    def log(self, actor: str, action: str, entity: str, entity_id: str | int, details: Dict[str, Any] | None = None):
        timestamp = datetime.utcnow().isoformat()
        event = {
            "id": f"AUD-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8].upper()}",
            "ts": timestamp,
            "timestamp": timestamp,
            "actor": actor,
            "action": action,
            "entity": entity,
            "entity_type": entity,
            "entity_id": str(entity_id),
            "details": details or {},
            "success": True,
        }
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events[:] = self._events[-self._max_events :]

        self._persist_event(event)
        return event

    def recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        if self._persist_to_database:
            try:
                db_factory = self._get_db_manager_factory()
                with db_factory() as db:
                    logs = db.audit.get_recent_logs(hours=24 * 365, limit=limit)
                    if logs:
                        return [self._format_db_log(log) for log in reversed(logs)]
            except Exception as exc:
                logger.debug("Audit DB read unavailable: %s", exc)

        return self._events[-limit:]
