from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from .base import BaseRepository
from database.models import MarketTick


class MarketTickRepository(BaseRepository[MarketTick]):
    def __init__(self, session: Session):
        super().__init__(MarketTick, session)

    def latest_for_symbol(self, kind: str, symbol: str, *, limit: int = 240) -> List[MarketTick]:
        try:
            return (
                self.session.query(MarketTick)
                .filter(MarketTick.kind == kind, MarketTick.symbol == symbol)
                .order_by(MarketTick.created_date.desc())
                .limit(limit)
                .all()
            )
        except Exception:
            return []
