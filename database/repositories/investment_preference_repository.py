from __future__ import annotations

from typing import List, Optional

from sqlalchemy.orm import Session

from .base import BaseRepository
from database.models import InvestmentPreference


class InvestmentPreferenceRepository(BaseRepository[InvestmentPreference]):
    def __init__(self, session: Session):
        super().__init__(InvestmentPreference, session)

    def latest_for_policy(self, customer_id: str, policy_id: str) -> Optional[InvestmentPreference]:
        try:
            return (
                self.session.query(InvestmentPreference)
                .filter(InvestmentPreference.customer_id == customer_id, InvestmentPreference.policy_id == policy_id)
                .order_by(InvestmentPreference.created_date.desc())
                .first()
            )
        except Exception:
            return None

    def latest_for_customer(self, customer_id: str, *, limit: int = 200) -> List[InvestmentPreference]:
        try:
            return (
                self.session.query(InvestmentPreference)
                .filter(InvestmentPreference.customer_id == customer_id)
                .order_by(InvestmentPreference.created_date.desc())
                .limit(limit)
                .all()
            )
        except Exception:
            return []

