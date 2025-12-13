from datetime import datetime, timedelta
from typing import Dict, Any, Optional

class BillingService:
    def __init__(self, bills: Dict[str, Any]):
        self._bills = bills

    def create_bill(self, policy_id: str, amount_due: float, due_days: int = 30) -> Dict[str, Any]:
        bill_id = f"BILL{len(self._bills) + 1:06d}"
        bill = {
            'bill_id': bill_id,
            'policy_id': policy_id,
            'amount_due': float(amount_due),
            'amount_paid': 0.0,
            'status': 'outstanding',
            'due_date': (datetime.now() + timedelta(days=due_days)).date().isoformat(),
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
        }
        self._bills[bill_id] = bill
        return bill

    def record_payment(self, bill_id: str, amount: float) -> Optional[Dict[str, Any]]:
        b = self._bills.get(bill_id)
        if not b:
            return None
        b['amount_paid'] = round(float(b.get('amount_paid', 0.0)) + float(amount), 2)
        if b['amount_paid'] >= b['amount_due']:
            b['status'] = 'paid'
        elif b['amount_paid'] > 0:
            b['status'] = 'partial'
        b['updated_at'] = datetime.now().isoformat()
        return b

    def apply_late_fee(self, bill_id: str, pct: float = 5.0) -> Optional[Dict[str, Any]]:
        b = self._bills.get(bill_id)
        if not b:
            return None
        # Apply only if overdue and not paid
        try:
            due = datetime.fromisoformat(b['due_date'])
        except Exception:
            return b
        if b.get('status') != 'paid' and datetime.now().date() > due.date():
            b['amount_due'] = round(b['amount_due'] * (1 + pct / 100.0), 2)
            b['status'] = 'overdue'
            b['updated_at'] = datetime.now().isoformat()
        return b
