"""Durable store for the referral acquisition-reward book.

Five tables, one session: the program config, the join edges, the reward
rows, one settlement per affiliated customer, and professional-role requests. The service in
``services/referral_reward_service.py`` is the authority for amounts and
checksums; this repository only reads and writes those rows.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import SQLAlchemyError

from database.models import (
    ProfessionalRequest,
    ReferralLink,
    ReferralProgramConfig,
    ReferralReward,
    ReferralSettlement,
)

_REWARD_JSON = {
    'program_shares': 'program_shares_json',
    'policy': 'policy_json',
    'allocation': 'allocation_json',
    'posted': 'posted_json',
}


def _dumps(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)


def _loads(value: Optional[str]) -> Any:
    if not value:
        return None
    return json.loads(value)


class ReferralRewardRepository:
    """Write-through access to the referral reward tables."""

    def __init__(self, session):
        self.session = session

    def _commit(self) -> bool:
        try:
            self.session.commit()
            return True
        except SQLAlchemyError:
            self.session.rollback()
            raise

    # -- config -------------------------------------------------------------
    def get_config(self) -> Optional[Dict[str, Any]]:
        row = self.session.get(ReferralProgramConfig, 'active')
        if row is None:
            return None
        return {
            'payload': _loads(row.payload_json),
            'checksum': row.checksum,
            'updated_at': row.updated_at,
            'updated_by': row.updated_by,
        }

    def save_config(self, payload: Dict[str, Any], checksum: str,
                    updated_at: str, updated_by: str) -> None:
        row = self.session.get(ReferralProgramConfig, 'active')
        if row is None:
            row = ReferralProgramConfig(id='active', payload_json=_dumps(payload), checksum=checksum)
            self.session.add(row)
        else:
            row.payload_json = _dumps(payload)
            row.checksum = checksum
        row.updated_at = updated_at
        row.updated_by = updated_by
        self._commit()

    # -- links --------------------------------------------------------------
    def list_links(self) -> List[Dict[str, Any]]:
        rows = self.session.query(ReferralLink).all()
        return [self._link_dict(row) for row in rows]

    def upsert_link(self, data: Dict[str, Any]) -> None:
        row = self.session.get(ReferralLink, data['id'])
        if row is None:
            row = ReferralLink(id=data['id'], referee_customer_id=data['referee_customer_id'],
                               referrer_customer_id=data['referrer_customer_id'],
                               joined_at=data.get('joined_at') or '')
            self.session.add(row)
        for field in ('referrer_customer_id', 'invitation_code', 'referee_name',
                      'joined_at', 'paying_at', 'notified_join'):
            if field in data:
                setattr(row, field, data.get(field))
        self._commit()

    def _link_dict(self, row: ReferralLink) -> Dict[str, Any]:
        return {
            'id': row.id,
            'referee_customer_id': row.referee_customer_id,
            'referrer_customer_id': row.referrer_customer_id,
            'invitation_code': row.invitation_code,
            'referee_name': row.referee_name,
            'joined_at': row.joined_at,
            'paying_at': row.paying_at,
            'notified_join': bool(row.notified_join),
        }

    # -- rewards ------------------------------------------------------------
    def list_rewards(self) -> List[Dict[str, Any]]:
        rows = self.session.query(ReferralReward).all()
        return [self._reward_dict(row) for row in rows]

    def upsert_reward(self, data: Dict[str, Any]) -> None:
        row = self.session.get(ReferralReward, data['id'])
        if row is None:
            row = ReferralReward(
                id=data['id'],
                referee_customer_id=data['referee_customer_id'],
                beneficiary_customer_id=data['beneficiary_customer_id'],
                layer=int(data['layer']),
                status=data.get('status') or 'earned',
                checksum=data.get('checksum') or '',
            )
            self.session.add(row)
        for field in ('referee_customer_id', 'beneficiary_customer_id', 'layer',
                      'invitation_code', 'status', 'fee_cents', 'share_bps',
                      'amount_cents', 'currency', 'books_tx_id', 'ledger_entry_id',
                      'earned_at', 'dispatched_at', 'checksum', 'settlement_id',
                      'hold_months', 'release_at'):
            if field in data:
                setattr(row, field, data.get(field))
        for memory_key, column in _REWARD_JSON.items():
            setattr(row, column, _dumps(data.get(memory_key)))
        self._commit()

    def _reward_dict(self, row: ReferralReward) -> Dict[str, Any]:
        return {
            'id': row.id,
            'referee_customer_id': row.referee_customer_id,
            'beneficiary_customer_id': row.beneficiary_customer_id,
            'layer': int(row.layer or 0),
            'invitation_code': row.invitation_code,
            'status': row.status,
            'fee_cents': int(row.fee_cents or 0),
            'share_bps': int(row.share_bps or 0),
            'amount_cents': int(row.amount_cents or 0),
            'currency': row.currency or 'USD',
            'program_shares': _loads(row.program_shares_json) or [],
            'policy': _loads(row.policy_json) or {},
            'allocation': _loads(row.allocation_json),
            'posted': _loads(row.posted_json) or {},
            'books_tx_id': row.books_tx_id,
            'ledger_entry_id': row.ledger_entry_id,
            'earned_at': row.earned_at,
            'dispatched_at': row.dispatched_at,
            'checksum': row.checksum or '',
            'settlement_id': row.settlement_id,
            'hold_months': int(row.hold_months or 0),
            'release_at': row.release_at,
        }

    # -- settlements --------------------------------------------------------
    def list_settlements(self) -> List[Dict[str, Any]]:
        rows = self.session.query(ReferralSettlement).all()
        return [self._settlement_dict(row) for row in rows]

    def upsert_settlement(self, data: Dict[str, Any]) -> None:
        row = self.session.get(ReferralSettlement, data['id'])
        if row is None:
            row = ReferralSettlement(
                id=data['id'],
                referee_customer_id=data['referee_customer_id'],
                status=data.get('status') or 'held',
                checksum=data.get('checksum') or '',
            )
            self.session.add(row)
        for field in ('referee_customer_id', 'fee_cents', 'allocated_cents', 'retained_cents',
                      'status', 'hold_months', 'paying_at', 'release_at', 'reversed_at',
                      'books_tx_id', 'reversal_tx_id', 'ledger_entry_id',
                      'released_ledger_id', 'reversal_ledger_id', 'checksum'):
            if field in data:
                setattr(row, field, data.get(field))
        self._commit()

    def _settlement_dict(self, row: ReferralSettlement) -> Dict[str, Any]:
        return {
            'id': row.id,
            'referee_customer_id': row.referee_customer_id,
            'fee_cents': int(row.fee_cents or 0),
            'allocated_cents': int(row.allocated_cents or 0),
            'retained_cents': int(row.retained_cents or 0),
            'status': row.status,
            'hold_months': int(row.hold_months or 0),
            'paying_at': row.paying_at,
            'release_at': row.release_at,
            'reversed_at': row.reversed_at,
            'books_tx_id': row.books_tx_id,
            'reversal_tx_id': row.reversal_tx_id,
            'ledger_entry_id': row.ledger_entry_id,
            'released_ledger_id': row.released_ledger_id,
            'reversal_ledger_id': row.reversal_ledger_id,
            'checksum': row.checksum or '',
        }

    # -- professional requests ---------------------------------------------
    def list_requests(self) -> List[Dict[str, Any]]:
        rows = self.session.query(ProfessionalRequest).all()
        return [self._request_dict(row) for row in rows]

    def upsert_request(self, data: Dict[str, Any]) -> None:
        row = self.session.get(ProfessionalRequest, data['id'])
        if row is None:
            row = ProfessionalRequest(
                id=data['id'],
                customer_id=data['customer_id'],
                requested_role=data['requested_role'],
                status=data.get('status') or 'pending',
                created_at=data.get('created_at') or '',
            )
            self.session.add(row)
        for field in ('customer_id', 'login_username', 'requested_role', 'status',
                      'supplier_type', 'company_name', 'note', 'agent_id',
                      'supplier_id', 'invitation_code', 'reviewed_by',
                      'reviewed_at', 'review_note', 'created_at', 'updated_at'):
            if field in data:
                setattr(row, field, data.get(field))
        self._commit()

    def _request_dict(self, row: ProfessionalRequest) -> Dict[str, Any]:
        return {
            'id': row.id,
            'customer_id': row.customer_id,
            'login_username': row.login_username,
            'requested_role': row.requested_role,
            'status': row.status,
            'supplier_type': row.supplier_type,
            'company_name': row.company_name,
            'note': row.note,
            'agent_id': row.agent_id,
            'supplier_id': row.supplier_id,
            'invitation_code': row.invitation_code,
            'reviewed_by': row.reviewed_by,
            'reviewed_at': row.reviewed_at,
            'review_note': row.review_note,
            'created_at': row.created_at,
            'updated_at': row.updated_at,
        }
