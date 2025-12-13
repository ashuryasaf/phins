from datetime import datetime
from typing import Dict, Any, Optional

class ClaimsService:
    def __init__(self, claims: Dict[str, Any]):
        self._claims = claims

    def create(self, policy_id: str, claim_amount: float, description: str) -> Dict[str, Any]:
        claim_id = f"CLM{len(self._claims) + 1:06d}"
        claim = {
            'claim_id': claim_id,
            'policy_id': policy_id,
            'claimed_amount': float(claim_amount),
            'description': description,
            'status': 'pending',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
        }
        self._claims[claim_id] = claim
        return claim

    def approve(self, claim_id: str, approved_amount: float) -> Optional[Dict[str, Any]]:
        c = self._claims.get(claim_id)
        if not c:
            return None
        c['status'] = 'approved'
        c['approved_amount'] = float(approved_amount)
        c['updated_at'] = datetime.now().isoformat()
        return c

    def reject(self, claim_id: str, reason: str) -> Optional[Dict[str, Any]]:
        c = self._claims.get(claim_id)
        if not c:
            return None
        c['status'] = 'rejected'
        c['rejection_reason'] = reason
        c['updated_at'] = datetime.now().isoformat()
        return c
