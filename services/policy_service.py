from datetime import datetime, timedelta
from typing import Dict, Any, Optional

class PolicyService:
    def __init__(self, policies: Dict[str, Any]):
        self._policies = policies

    def create(self, customer_id: str, premium: float, coverage: Dict[str, Any]) -> Dict[str, Any]:
        policy_id = f"POL{len(self._policies) + 1:06d}"
        policy = {
            'policy_id': policy_id,
            'customer_id': customer_id,
            'premium': float(premium),
            'coverage': coverage,
            'status': 'active',
            'uw_status': 'pending',
            'start_date': datetime.now().date().isoformat(),
            'end_date': (datetime.now() + timedelta(days=365)).date().isoformat(),
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
        }
        self._policies[policy_id] = policy
        return policy

    def renew(self, policy_id: str) -> Optional[Dict[str, Any]]:
        p = self._policies.get(policy_id)
        if not p:
            return None
        p['end_date'] = (datetime.now() + timedelta(days=365)).date().isoformat()
        p['uw_status'] = 'pending'
        p['updated_at'] = datetime.now().isoformat()
        return p

    def set_status(self, policy_id: str, status: str) -> Optional[Dict[str, Any]]:
        p = self._policies.get(policy_id)
        if not p:
            return None
        allowed = {'active', 'inactive', 'cancelled', 'lapsed', 'suspended'}
        if status not in allowed:
            raise ValueError('Invalid status')
        p['status'] = status
        p['updated_at'] = datetime.now().isoformat()
        return p
