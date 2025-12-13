from datetime import datetime
from typing import Dict, Any, Optional

class UnderwritingService:
    def __init__(self, applications: Dict[str, Any], policies: Dict[str, Any]):
        self._apps = applications
        self._policies = policies

    def initiate(self, policy_id: str) -> Dict[str, Any]:
        app_id = f"UW{len(self._apps) + 1:06d}"
        app = {
            'uw_id': app_id,
            'policy_id': policy_id,
            'status': 'pending',
            'risk_level': None,
            'requires_medical': False,
            'premium_adjustment_pct': 0.0,
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
        }
        self._apps[app_id] = app
        p = self._policies.get(policy_id)
        if p:
            p['uw_status'] = 'pending'
            p['updated_at'] = datetime.now().isoformat()
        return app

    def assess_risk(self, app_id: str, level: str) -> Optional[Dict[str, Any]]:
        a = self._apps.get(app_id)
        if not a:
            return None
        allowed = {'Low', 'Medium', 'High', 'Very High'}
        if level not in allowed:
            raise ValueError('Invalid risk level')
        a['risk_level'] = level
        a['updated_at'] = datetime.now().isoformat()
        a['requires_medical'] = level in {'High', 'Very High'}
        return a

    def approve(self, app_id: str, premium_adjustment_pct: float = 0.0) -> Optional[Dict[str, Any]]:
        a = self._apps.get(app_id)
        if not a:
            return None
        a['status'] = 'approved'
        a['premium_adjustment_pct'] = float(premium_adjustment_pct)
        a['updated_at'] = datetime.now().isoformat()
        p = self._policies.get(a['policy_id'])
        if p:
            p['uw_status'] = 'approved'
            p['premium'] = round(float(p['premium']) * (1 + a['premium_adjustment_pct']/100.0), 2)
            p['updated_at'] = datetime.now().isoformat()
        return a

    def refer(self, app_id: str, reason: str) -> Optional[Dict[str, Any]]:
        a = self._apps.get(app_id)
        if not a:
            return None
        a['status'] = 'referred'
        a['referral_reason'] = reason
        a['updated_at'] = datetime.now().isoformat()
        return a
