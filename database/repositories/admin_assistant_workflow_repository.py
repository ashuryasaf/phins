"""Repository for persisted admin assistant workflow state."""

from typing import Optional, Dict, Any
import json
from sqlalchemy.orm import Session as DBSession

from database.models import AdminAssistantWorkflow
from .base import BaseRepository


class AdminAssistantWorkflowRepository(BaseRepository[AdminAssistantWorkflow]):
    """Repository for admin assistant workflow state operations."""

    def __init__(self, session: DBSession):
        super().__init__(AdminAssistantWorkflow, session)

    def get_by_owner(self, owner_username: str) -> Optional[AdminAssistantWorkflow]:
        """Get workflow state by normalized owner username."""
        return self.get_by_id(owner_username)

    def save_state(self, owner_username: str, workflow_state: Dict[str, Any]) -> Optional[AdminAssistantWorkflow]:
        """Create or update workflow state for an owner."""
        workflow_id = str((workflow_state or {}).get('workflow_id') or '')
        payload = json.dumps(workflow_state or {}, default=str)
        existing = self.get_by_owner(owner_username)
        if existing:
            return self.update(
                owner_username,
                workflow_id=workflow_id,
                workflow_state=payload,
            )
        return self.create(
            owner=owner_username,
            workflow_id=workflow_id,
            workflow_state=payload,
        )

    def delete_by_owner(self, owner_username: str) -> bool:
        """Delete workflow state for an owner."""
        return self.delete(owner_username)
