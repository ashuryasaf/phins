from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from .base import BaseRepository
from database.models import MarketTick


class MarketTickRepository(BaseRepository[MarketTick]):
    def __init__(self, session: Session):
        super().__init__(MarketTick, session)

    def latest_for_symbol(self, kind: str, symbol: str, *, currency: str | None = None, limit: int = 240) -> List[MarketTick]:
        try:
            q = self.session.query(MarketTick).filter(MarketTick.kind == kind, MarketTick.symbol == symbol)
            if currency:
                q = q.filter(MarketTick.currency == currency)
            return (
                q
                .order_by(MarketTick.created_date.desc())
                .limit(limit)
                .all()
            )
        except Exception:
            return []
