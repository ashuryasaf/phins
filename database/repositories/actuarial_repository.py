from __future__ import annotations

from typing import Optional, List
from sqlalchemy.orm import Session

from database.models import ActuarialTable


class ActuarialRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, table: ActuarialTable) -> ActuarialTable:
        self.session.add(table)
        self.session.flush()
        return table

    def get_by_id(self, table_id: str) -> Optional[ActuarialTable]:
        return self.session.query(ActuarialTable).filter(ActuarialTable.id == table_id).first()

    def list(self, limit: int = 200) -> List[ActuarialTable]:
        return (
            self.session.query(ActuarialTable)
            .order_by(ActuarialTable.created_date.desc())
            .limit(limit)
            .all()
        )

    def latest_by_type(self, table_type: str) -> Optional[ActuarialTable]:
        return (
            self.session.query(ActuarialTable)
            .filter(ActuarialTable.table_type == table_type)
            .order_by(ActuarialTable.effective_date.desc().nullslast(), ActuarialTable.created_date.desc())
            .first()
        )

