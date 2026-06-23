"""
Agent ecosystem repositories ("AgentOS").

Durable backing for the agent/broker layer: agents, invitations, affiliations,
and commission accruals. The authoritative working store lives in
``services/agent_ecosystem_service.py`` (in-memory + hash-chained ledger); these
repositories provide best-effort persistence and load-on-restart.

See docs/agent_ecosystem_design.md and docs/uml/agent_ecosystem.puml.
"""

from typing import List, Optional
from sqlalchemy.orm import Session

from database.models import Agent, AgentInvitation, AgentAffiliation, AgentCommission
from .base import BaseRepository


class AgentRepository(BaseRepository[Agent]):
    """CRUD for agent profiles."""

    def __init__(self, session: Session):
        super().__init__(Agent, session)

    def get_by_username(self, username: str) -> Optional[Agent]:
        return self.find_one_by(user_username=username)

    def list_all(self) -> List[Agent]:
        return self.get_all()


class AgentInvitationRepository(BaseRepository[AgentInvitation]):
    """CRUD for agent invitations (commission locked by admin in advance)."""

    def __init__(self, session: Session):
        super().__init__(AgentInvitation, session)

    def list_by_agent(self, agent_id: str) -> List[AgentInvitation]:
        return self.filter_by(agent_id=agent_id)

    def list_by_status(self, status: str) -> List[AgentInvitation]:
        return self.filter_by(status=status)


class AgentAffiliationRepository(BaseRepository[AgentAffiliation]):
    """CRUD for agent affiliations (one active per principal — enforced in service)."""

    def __init__(self, session: Session):
        super().__init__(AgentAffiliation, session)

    def list_by_agent(self, agent_id: str) -> List[AgentAffiliation]:
        return self.filter_by(agent_id=agent_id)

    def active_for_principal(self, principal_type: str, principal_id: str) -> Optional[AgentAffiliation]:
        return self.find_one_by(
            principal_type=principal_type, principal_id=principal_id, status='active'
        )


class AgentCommissionRepository(BaseRepository[AgentCommission]):
    """CRUD for commission accruals (idempotent on source_event_id+affiliation_id)."""

    def __init__(self, session: Session):
        super().__init__(AgentCommission, session)

    def list_by_agent(self, agent_id: str) -> List[AgentCommission]:
        return self.filter_by(agent_id=agent_id)

    def get_for_event(self, source_event_id: str, affiliation_id: str) -> Optional[AgentCommission]:
        return self.find_one_by(source_event_id=source_event_id, affiliation_id=affiliation_id)
