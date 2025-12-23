from __future__ import annotations

from typing import Optional, List
from sqlalchemy.orm import Session

from database.models import TokenRegistry


class TokenRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, entry: TokenRegistry) -> TokenRegistry:
        self.session.add(entry)
        self.session.flush()
        return entry

    def get_by_id(self, entry_id: str) -> Optional[TokenRegistry]:
        return self.session.query(TokenRegistry).filter(TokenRegistry.id == entry_id).first()

    def get_by_symbol(self, symbol: str) -> Optional[TokenRegistry]:
        return self.session.query(TokenRegistry).filter(TokenRegistry.symbol == symbol).first()

    def list(self, enabled_only: bool = False, limit: int = 500) -> List[TokenRegistry]:
        q = self.session.query(TokenRegistry)
        if enabled_only:
            q = q.filter(TokenRegistry.enabled.is_(True))
        return q.order_by(TokenRegistry.created_date.desc()).limit(limit).all()

