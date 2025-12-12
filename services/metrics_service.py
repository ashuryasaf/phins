from typing import Dict, Any

class MetricsService:
    def __init__(self, policies: Dict[str, Any], claims: Dict[str, Any], bills: Dict[str, Any]):
        self._policies = policies
        self._claims = claims
        self._bills = bills

    def summary(self) -> Dict[str, Any]:
        total_policies = len(self._policies)
        active_policies = sum(1 for p in self._policies.values() if p.get('status') == 'active')
        pending_claims = sum(1 for c in self._claims.values() if c.get('status') in ['pending', 'under_review'])
        approved_claims = sum(1 for c in self._claims.values() if c.get('status') == 'approved')
        overdue_bills = sum(1 for b in self._bills.values() if b.get('status') == 'overdue')
        outstanding_bills = sum(1 for b in self._bills.values() if b.get('status') in ['outstanding', 'partial'])

        return {
            'policies': {
                'total': total_policies,
                'active': active_policies,
            },
            'claims': {
                'pending': pending_claims,
                'approved': approved_claims,
            },
            'billing': {
                'overdue': overdue_bills,
                'outstanding': outstanding_bills,
            }
        }
