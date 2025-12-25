from typing import Dict, Any

class MetricsService:
    def __init__(
        self,
        policies: Dict[str, Any],
        claims: Dict[str, Any],
        bills: Dict[str, Any],
        customers: Dict[str, Any] | None = None,
        underwriting: Dict[str, Any] | None = None,
    ):
        self._policies = policies
        self._claims = claims
        self._bills = bills
        self._customers = customers or {}
        self._underwriting = underwriting or {}

    def summary(self) -> Dict[str, Any]:
        total_policies = len(self._policies)
        active_policies = sum(1 for p in self._policies.values() if p.get('status') in ('active', 'in_force'))
        # pending underwriting + pending first-payment/billing window
        pending_policies = sum(1 for p in self._policies.values() if p.get('status') in ('pending_underwriting', 'billing_pending'))
        pending_claims = sum(1 for c in self._claims.values() if c.get('status') in ['pending', 'under_review'])
        approved_claims = sum(1 for c in self._claims.values() if c.get('status') == 'approved')
        overdue_bills = sum(1 for b in self._bills.values() if b.get('status') == 'overdue')
        outstanding_bills = sum(1 for b in self._bills.values() if b.get('status') in ['outstanding', 'partial'])
        underwriting_pending = sum(1 for u in self._underwriting.values() if u.get('status') == 'pending')
        total_exposure = sum(float(p.get('coverage_amount', 0) or 0) for p in self._policies.values())
        disability_exposure = sum(
            float(p.get('coverage_amount', 0) or 0)
            for p in self._policies.values()
            if str(p.get('type') or '').lower() == 'disability'
        )

        return {
            'customers': {
                'total': len(self._customers),
            },
            'policies': {
                'total': total_policies,
                'active': active_policies,
                'pending': pending_policies,
            },
            'claims': {
                'pending': pending_claims,
                'approved': approved_claims,
            },
            'billing': {
                'overdue': overdue_bills,
                'outstanding': outstanding_bills,
            }
            ,
            'underwriting': {
                'pending': underwriting_pending,
            },
            'actuary': {
                'total_exposure': total_exposure,
                'disability_exposure': disability_exposure,
            },
        }
