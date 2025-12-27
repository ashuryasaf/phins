"""
Insurance Pipeline Service

Handles automatic workflow progression through the insurance lifecycle:
Application → Underwriting → Policy Activation → Billing → Claims

ARCHITECTURE:
- Event-driven pipeline triggers
- Automatic state transitions
- Audit trail for all transitions
- Database persistence by default

This service ensures data flows correctly through the admin pipeline
when customers submit applications.
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import logging
import uuid

logger = logging.getLogger(__name__)


class PipelineService:
    """
    Unified pipeline service for insurance workflow management.
    
    Ensures data persists and flows through:
    Customer Portal → Underwriting Queue → Policy Activation → Billing Generation
    """
    
    # Pipeline stages
    STAGE_APPLICATION = 'application'
    STAGE_UNDERWRITING = 'underwriting'
    STAGE_APPROVED = 'approved'
    STAGE_ACTIVE = 'active'
    STAGE_BILLING = 'billing'
    STAGE_CLAIM = 'claim'
    
    # Status mappings
    UNDERWRITING_STATUSES = ('pending', 'under_review', 'referred', 'approved', 'rejected')
    POLICY_STATUSES = ('pending_underwriting', 'active', 'inactive', 'cancelled', 'lapsed', 'suspended')
    
    def __init__(self, 
                 customers: Dict[str, Any],
                 policies: Dict[str, Any],
                 underwriting: Dict[str, Any],
                 billing: Dict[str, Any],
                 claims: Dict[str, Any],
                 audit_service=None):
        """
        Initialize pipeline with data stores.
        
        Args:
            customers: Customer data store (dict-like)
            policies: Policy data store
            underwriting: Underwriting applications store
            billing: Billing/invoices store
            claims: Claims store
            audit_service: Optional audit service for logging
        """
        self._customers = customers
        self._policies = policies
        self._underwriting = underwriting
        self._billing = billing
        self._claims = claims
        self._audit = audit_service
    
    def _log_event(self, actor: str, action: str, entity: str, entity_id: str, details: Dict = None):
        """Log pipeline event to audit trail"""
        if self._audit:
            try:
                self._audit.log(actor, action, entity, entity_id, details or {})
            except Exception as e:
                logger.warning(f"Audit log failed: {e}")
        logger.info(f"Pipeline: {actor} {action} {entity}:{entity_id}")
    
    def _generate_id(self, prefix: str) -> str:
        """Generate unique ID with prefix"""
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        unique = uuid.uuid4().hex[:6].upper()
        return f"{prefix}-{timestamp}-{unique}"
    
    # =========================================================================
    # STAGE 1: Application Submission
    # =========================================================================
    
    def submit_application(self, 
                          customer_data: Dict[str, Any],
                          policy_data: Dict[str, Any],
                          questionnaire: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Submit new insurance application.
        
        This is the entry point to the pipeline. Creates:
        1. Customer record (or updates existing)
        2. Policy record (pending_underwriting)
        3. Underwriting application (pending)
        
        Returns dict with customer, policy, and underwriting IDs.
        """
        now = datetime.now()
        
        # 1. Create/update customer
        customer_id = customer_data.get('id') or self._generate_id('CUST')
        customer = {
            'id': customer_id,
            'name': customer_data.get('name', ''),
            'email': customer_data.get('email', ''),
            'phone': customer_data.get('phone', ''),
            'dob': customer_data.get('dob', ''),
            'address': customer_data.get('address', ''),
            'city': customer_data.get('city', ''),
            'state': customer_data.get('state', ''),
            'zip': customer_data.get('zip', ''),
            'occupation': customer_data.get('occupation', ''),
            'created_date': now.isoformat(),
            'updated_date': now.isoformat()
        }
        
        # Store customer (will update if exists)
        self._customers[customer_id] = customer
        
        # 2. Create policy (pending underwriting)
        policy_id = self._generate_id('POL')
        policy = {
            'id': policy_id,
            'customer_id': customer_id,
            'type': policy_data.get('type', 'life'),
            'coverage_amount': float(policy_data.get('coverage_amount', 100000)),
            'annual_premium': float(policy_data.get('annual_premium', 0)),
            'monthly_premium': float(policy_data.get('monthly_premium', 0)),
            'status': 'pending_underwriting',
            'risk_score': policy_data.get('risk_score', 'medium'),
            'start_date': policy_data.get('start_date', now.isoformat()),
            'end_date': policy_data.get('end_date', (now + timedelta(days=365)).isoformat()),
            'created_date': now.isoformat(),
            'updated_date': now.isoformat()
        }
        self._policies[policy_id] = policy
        
        # 3. Create underwriting application (auto-queued for admin review)
        uw_id = self._generate_id('UW')
        underwriting_app = {
            'id': uw_id,
            'policy_id': policy_id,
            'customer_id': customer_id,
            'status': 'pending',  # Queued for underwriter review
            'risk_assessment': policy_data.get('risk_score', 'medium'),
            'questionnaire_responses': questionnaire or {},
            'medical_exam_required': policy_data.get('risk_score') in ('high', 'very_high'),
            'additional_documents_required': False,
            'submitted_date': now.isoformat(),
            'created_date': now.isoformat(),
            'updated_date': now.isoformat()
        }
        self._underwriting[uw_id] = underwriting_app
        
        # Link policy to underwriting
        policy['underwriting_id'] = uw_id
        self._policies[policy_id] = policy
        
        self._log_event('system', 'submit_application', 'pipeline', policy_id, {
            'customer_id': customer_id,
            'underwriting_id': uw_id,
            'stage': self.STAGE_APPLICATION
        })
        
        return {
            'success': True,
            'customer_id': customer_id,
            'policy_id': policy_id,
            'underwriting_id': uw_id,
            'stage': self.STAGE_UNDERWRITING,
            'message': 'Application submitted. Pending underwriting review.'
        }
    
    # =========================================================================
    # STAGE 2: Underwriting Decision
    # =========================================================================
    
    def approve_underwriting(self, 
                            uw_id: str, 
                            approved_by: str,
                            premium_adjustment_pct: float = 0.0,
                            notes: str = '') -> Dict[str, Any]:
        """
        Approve underwriting application.
        
        Triggers:
        1. Update underwriting status → approved
        2. Update policy status → active
        3. Generate initial billing
        """
        uw_app = self._underwriting.get(uw_id)
        if not uw_app:
            return {'success': False, 'error': 'Underwriting application not found'}
        
        if uw_app.get('status') != 'pending':
            return {'success': False, 'error': f"Cannot approve: status is {uw_app.get('status')}"}
        
        now = datetime.now()
        policy_id = uw_app.get('policy_id')
        policy = self._policies.get(policy_id)
        
        if not policy:
            return {'success': False, 'error': 'Associated policy not found'}
        
        # 1. Update underwriting
        uw_app['status'] = 'approved'
        uw_app['decision_date'] = now.isoformat()
        uw_app['decided_by'] = approved_by
        uw_app['notes'] = notes
        uw_app['premium_adjustment_pct'] = premium_adjustment_pct
        uw_app['updated_date'] = now.isoformat()
        self._underwriting[uw_id] = uw_app
        
        # 2. Activate policy (with premium adjustment if any)
        if premium_adjustment_pct != 0:
            policy['annual_premium'] = round(policy['annual_premium'] * (1 + premium_adjustment_pct / 100), 2)
            policy['monthly_premium'] = round(policy['annual_premium'] / 12, 2)
        
        policy['status'] = 'active'
        policy['approval_date'] = now.isoformat()
        policy['updated_date'] = now.isoformat()
        self._policies[policy_id] = policy
        
        # 3. Auto-generate first bill (pipeline trigger)
        bill_result = self._generate_initial_billing(policy_id, policy)
        
        self._log_event(approved_by, 'approve_underwriting', 'pipeline', uw_id, {
            'policy_id': policy_id,
            'premium_adjustment': premium_adjustment_pct,
            'bill_id': bill_result.get('bill_id'),
            'stage': self.STAGE_ACTIVE
        })
        
        return {
            'success': True,
            'underwriting_id': uw_id,
            'policy_id': policy_id,
            'policy_status': 'active',
            'bill_id': bill_result.get('bill_id'),
            'stage': self.STAGE_BILLING,
            'message': 'Policy approved and activated. Initial bill generated.'
        }
    
    def reject_underwriting(self, 
                           uw_id: str, 
                           rejected_by: str,
                           reason: str) -> Dict[str, Any]:
        """Reject underwriting application"""
        uw_app = self._underwriting.get(uw_id)
        if not uw_app:
            return {'success': False, 'error': 'Underwriting application not found'}
        
        now = datetime.now()
        policy_id = uw_app.get('policy_id')
        
        # Update underwriting
        uw_app['status'] = 'rejected'
        uw_app['decision_date'] = now.isoformat()
        uw_app['decided_by'] = rejected_by
        uw_app['rejection_reason'] = reason
        uw_app['updated_date'] = now.isoformat()
        self._underwriting[uw_id] = uw_app
        
        # Update policy
        if policy_id and policy_id in self._policies:
            self._policies[policy_id]['status'] = 'rejected'
            self._policies[policy_id]['updated_date'] = now.isoformat()
        
        self._log_event(rejected_by, 'reject_underwriting', 'pipeline', uw_id, {
            'policy_id': policy_id,
            'reason': reason
        })
        
        return {
            'success': True,
            'underwriting_id': uw_id,
            'policy_id': policy_id,
            'message': 'Application rejected.'
        }
    
    def refer_underwriting(self, 
                          uw_id: str, 
                          referred_by: str,
                          reason: str) -> Dict[str, Any]:
        """Refer underwriting for additional review"""
        uw_app = self._underwriting.get(uw_id)
        if not uw_app:
            return {'success': False, 'error': 'Underwriting application not found'}
        
        now = datetime.now()
        uw_app['status'] = 'referred'
        uw_app['referral_reason'] = reason
        uw_app['referred_by'] = referred_by
        uw_app['referred_date'] = now.isoformat()
        uw_app['updated_date'] = now.isoformat()
        self._underwriting[uw_id] = uw_app
        
        self._log_event(referred_by, 'refer_underwriting', 'pipeline', uw_id, {
            'reason': reason
        })
        
        return {
            'success': True,
            'underwriting_id': uw_id,
            'status': 'referred',
            'message': 'Application referred for additional review.'
        }
    
    # =========================================================================
    # STAGE 3: Billing Generation
    # =========================================================================
    
    def _generate_initial_billing(self, policy_id: str, policy: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-generate initial bill when policy is activated"""
        now = datetime.now()
        bill_id = self._generate_id('BILL')
        
        # Get premium - handle both dict and object access
        if isinstance(policy, dict):
            monthly_premium = policy.get('monthly_premium', 0)
            customer_id = policy.get('customer_id')
        else:
            monthly_premium = getattr(policy, 'monthly_premium', 0)
            customer_id = getattr(policy, 'customer_id', None)
        
        bill = {
            'id': bill_id,
            'policy_id': policy_id,
            'customer_id': customer_id,
            'amount': float(monthly_premium) if monthly_premium else 0.0,
            'amount_paid': 0.0,
            'status': 'outstanding',
            'due_date': (now + timedelta(days=30)).isoformat(),
            'late_fee': 0.0,
            'created_date': now.isoformat(),
            'updated_date': now.isoformat()
        }
        
        self._billing[bill_id] = bill
        
        self._log_event('system', 'generate_bill', 'billing', bill_id, {
            'policy_id': policy_id,
            'amount': bill['amount'],
            'trigger': 'policy_activation'
        })
        
        return {'bill_id': bill_id, 'amount': bill['amount']}
    
    def record_payment(self, 
                      bill_id: str, 
                      amount: float,
                      payment_method: str = 'card',
                      transaction_id: str = None) -> Dict[str, Any]:
        """Record payment against a bill"""
        bill = self._billing.get(bill_id)
        if not bill:
            return {'success': False, 'error': 'Bill not found'}
        
        now = datetime.now()
        bill['amount_paid'] = round(float(bill.get('amount_paid', 0)) + amount, 2)
        bill['payment_method'] = payment_method
        bill['transaction_id'] = transaction_id or self._generate_id('TXN')
        bill['updated_date'] = now.isoformat()
        
        if bill['amount_paid'] >= bill['amount']:
            bill['status'] = 'paid'
            bill['paid_date'] = now.isoformat()
        elif bill['amount_paid'] > 0:
            bill['status'] = 'partial'
        
        self._billing[bill_id] = bill
        
        self._log_event('system', 'record_payment', 'billing', bill_id, {
            'amount': amount,
            'new_status': bill['status']
        })
        
        return {
            'success': True,
            'bill_id': bill_id,
            'status': bill['status'],
            'amount_paid': bill['amount_paid'],
            'amount_due': bill['amount']
        }
    
    # =========================================================================
    # STAGE 4: Claims Processing
    # =========================================================================
    
    def file_claim(self,
                  policy_id: str,
                  claim_data: Dict[str, Any]) -> Dict[str, Any]:
        """File a new claim against a policy"""
        policy = self._policies.get(policy_id)
        if not policy:
            return {'success': False, 'error': 'Policy not found'}
        
        if policy.get('status') != 'active':
            return {'success': False, 'error': f"Cannot file claim: policy status is {policy.get('status')}"}
        
        now = datetime.now()
        claim_id = self._generate_id('CLM')
        
        claim = {
            'id': claim_id,
            'policy_id': policy_id,
            'customer_id': policy.get('customer_id'),
            'type': claim_data.get('type', 'general'),
            'description': claim_data.get('description', ''),
            'claimed_amount': float(claim_data.get('amount', 0)),
            'status': 'pending',
            'filed_date': now.isoformat(),
            'created_date': now.isoformat(),
            'updated_date': now.isoformat()
        }
        
        self._claims[claim_id] = claim
        
        self._log_event('customer', 'file_claim', 'claims', claim_id, {
            'policy_id': policy_id,
            'amount': claim['claimed_amount']
        })
        
        return {
            'success': True,
            'claim_id': claim_id,
            'status': 'pending',
            'message': 'Claim filed successfully. Pending review.'
        }
    
    # =========================================================================
    # Pipeline Status & Queries
    # =========================================================================
    
    def get_pending_underwriting(self) -> List[Dict[str, Any]]:
        """Get all pending underwriting applications for admin queue"""
        pending = []
        for uw_id, uw_app in self._underwriting.items():
            if uw_app.get('status') == 'pending':
                # Enrich with customer and policy data
                policy = self._policies.get(uw_app.get('policy_id'), {})
                customer = self._customers.get(uw_app.get('customer_id'), {})
                pending.append({
                    **uw_app,
                    'customer_name': customer.get('name', 'Unknown'),
                    'customer_email': customer.get('email', ''),
                    'policy_type': policy.get('type', ''),
                    'coverage_amount': policy.get('coverage_amount', 0)
                })
        return sorted(pending, key=lambda x: x.get('submitted_date', ''), reverse=True)
    
    def get_customer_pipeline_status(self, customer_id: str) -> Dict[str, Any]:
        """Get complete pipeline status for a customer"""
        customer = self._customers.get(customer_id, {})
        policies = [p for p in self._policies.values() if p.get('customer_id') == customer_id]
        claims = [c for c in self._claims.values() if c.get('customer_id') == customer_id]
        bills = [b for b in self._billing.values() if b.get('customer_id') == customer_id]
        
        return {
            'customer': customer,
            'policies': policies,
            'claims': claims,
            'bills': bills,
            'summary': {
                'total_policies': len(policies),
                'active_policies': sum(1 for p in policies if p.get('status') == 'active'),
                'pending_underwriting': sum(1 for p in policies if p.get('status') == 'pending_underwriting'),
                'open_claims': sum(1 for c in claims if c.get('status') in ('pending', 'under_review')),
                'outstanding_bills': sum(1 for b in bills if b.get('status') == 'outstanding')
            }
        }


# Singleton instance for global access
_pipeline_instance: Optional[PipelineService] = None


def get_pipeline_service(customers, policies, underwriting, billing, claims, audit=None) -> PipelineService:
    """Get or create pipeline service instance"""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = PipelineService(
            customers=customers,
            policies=policies,
            underwriting=underwriting,
            billing=billing,
            claims=claims,
            audit_service=audit
        )
    return _pipeline_instance


__all__ = ['PipelineService', 'get_pipeline_service']
