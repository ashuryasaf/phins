from typing import Dict, Any

# Case-insensitive status helpers
def _status_eq(item: Dict, *statuses: str) -> bool:
    """Case-insensitive status check"""
    item_status = (item.get('status') or '').lower().replace(' ', '_')
    return item_status in [s.lower().replace(' ', '_') for s in statuses]

def _status_in(item: Dict, statuses: list) -> bool:
    """Case-insensitive check if item's status is in a list"""
    item_status = (item.get('status') or '').lower().replace(' ', '_')
    return item_status in [s.lower().replace(' ', '_') for s in statuses]

class MetricsService:
    def __init__(self, policies: Dict[str, Any], claims: Dict[str, Any], bills: Dict[str, Any]):
        self._policies = policies
        self._claims = claims
        self._bills = bills

    def summary(self) -> Dict[str, Any]:
        total_policies = len(self._policies)
        active_policies = sum(1 for p in self._policies.values() if _status_eq(p, 'active'))
        pending_claims = sum(1 for c in self._claims.values() if _status_in(c, ['pending', 'under_review']))
        approved_claims = sum(1 for c in self._claims.values() if _status_eq(c, 'approved'))
        overdue_bills = sum(1 for b in self._bills.values() if _status_eq(b, 'overdue'))
        outstanding_bills = sum(1 for b in self._bills.values() if _status_in(b, ['outstanding', 'partial']))

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
