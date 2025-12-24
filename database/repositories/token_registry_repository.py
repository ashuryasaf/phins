"""Token Registry Repository"""

from typing import Optional, List
from sqlalchemy.orm import Session

from database.models import TokenRegistry
from .base import BaseRepository


class TokenRegistryRepository(BaseRepository[TokenRegistry]):
    """Repository for TokenRegistry operations"""

    def __init__(self, session: Session):
        super().__init__(TokenRegistry, session)

    def get_by_kind(self, kind: str) -> List[TokenRegistry]:
        return self.filter_by(kind=kind)

    def get_active_token(self, token: str) -> Optional[TokenRegistry]:
        rec = self.get_by_id(token)
        if rec and getattr(rec, "status", None) == "active":
            return rec
        return None

