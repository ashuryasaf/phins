from datetime import datetime
from typing import Dict, Any, List

class AuditService:
    def __init__(self):
        self._events: List[Dict[str, Any]] = []

    def log(self, actor: str, action: str, entity: str, entity_id: str | int, details: Dict[str, Any] | None = None):
        event = {
            'ts': datetime.now().isoformat(),
            'actor': actor,
            'action': action,
            'entity': entity,
            'entity_id': entity_id,
            'details': details or {}
        }
        self._events.append(event)
        # Trim to last 5000 entries to bound memory
        if len(self._events) > 5000:
            self._events[:] = self._events[-5000:]

    def recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        return self._events[-limit:]
