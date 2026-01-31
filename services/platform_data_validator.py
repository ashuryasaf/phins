"""
PHINS Platform Data Validator Service
=====================================
Comprehensive service for auditing and validating data integrity across:
- User types (admins, suppliers, customers)
- Ledgers and transaction flows
- Data seeding consistency
- Pipeline process integrity

This service ensures data validity and provides AI-driven recommendations
for fixing data inconsistencies.
"""

import json
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class UserType(Enum):
    """User types in the PHINS system"""
    ADMIN = "admin"
    UNDERWRITER = "underwriter"
    CLAIMS_ADJUSTER = "claims_adjuster"
    ACCOUNTANT = "accountant"
    ACTUARY = "actuary"
    MEDIA = "media"
    SUPPLIER = "supplier"
    CUSTOMER = "customer"


class ValidationSeverity(Enum):
    """Severity levels for validation issues"""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass
class ValidationIssue:
    """Represents a data validation issue"""
    issue_id: str
    severity: ValidationSeverity
    category: str  # user_data, ledger, pipeline, seeding, relationship
    entity_type: str  # customer, policy, claim, bill, supplier, etc.
    entity_id: Optional[str]
    field: str
    expected_value: Any
    actual_value: Any
    description: str
    auto_fixable: bool
    fix_action: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['severity'] = self.severity.value
        return result


@dataclass
class ValidationReport:
    """Complete validation report for the platform"""
    report_id: str
    generated_at: str
    platform_health_score: float  # 0-100
    total_entities_checked: int
    total_issues_found: int
    critical_issues: int
    high_issues: int
    medium_issues: int
    low_issues: int
    
    # Category breakdowns
    user_validation: Dict = field(default_factory=dict)
    ledger_validation: Dict = field(default_factory=dict)
    pipeline_validation: Dict = field(default_factory=dict)
    relationship_validation: Dict = field(default_factory=dict)
    
    issues: List[ValidationIssue] = field(default_factory=list)
    ai_recommendations: List[str] = field(default_factory=list)
    auto_fixes_available: int = 0
    
    @property
    def integrity_status(self) -> str:
        """Get integrity status based on health score and critical issues"""
        if self.critical_issues > 0 or self.platform_health_score < 60:
            return 'critical'
        elif self.high_issues > 0 or self.platform_health_score < 80:
            return 'warning'
        else:
            return 'valid'
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['issues'] = [i.to_dict() if hasattr(i, 'to_dict') else i for i in self.issues]
        result['integrity_status'] = self.integrity_status
        return result


class PlatformDataValidator:
    """
    Comprehensive platform data validation service.
    
    Validates:
    1. User data integrity by type (admin, supplier, customer)
    2. Ledger consistency (transactions, NFTs, billing)
    3. Pipeline data flow (application → underwriting → policy → billing → claims)
    4. Data seeding correctness
    5. Relationship integrity (foreign key consistency)
    """
    
    # Valid roles by user type
    VALID_STAFF_ROLES = {'admin', 'underwriter', 'claims_adjuster', 'claims', 'accountant', 'actuary', 'media'}
    VALID_CUSTOMER_ROLE = 'customer'
    VALID_SUPPLIER_ROLE = 'supplier'
    
    # Valid statuses by entity
    VALID_POLICY_STATUSES = {'active', 'inactive', 'cancelled', 'lapsed', 'suspended', 'pending_underwriting'}
    VALID_CLAIM_STATUSES = {'pending', 'under_review', 'approved', 'rejected', 'paid', 'closed'}
    VALID_BILL_STATUSES = {'outstanding', 'partial', 'paid', 'overdue', 'cancelled'}
    VALID_UNDERWRITING_STATUSES = {'pending', 'approved', 'rejected', 'referred', 'approved_conditional'}
    VALID_SUPPLIER_STATUSES = {'pending', 'under_review', 'approved', 'rejected', 'suspended', 'terminated'}
    
    def __init__(self,
                 users: Dict = None,
                 customers: Dict = None,
                 suppliers: Dict = None,
                 policies: Dict = None,
                 claims: Dict = None,
                 bills: Dict = None,
                 underwriting_apps: Dict = None,
                 health_wallets: Dict = None,
                 investment_accounts: Dict = None,
                 transaction_ledger: Dict = None,
                 nft_ledger: Dict = None,
                 foundations: Dict = None,
                 supplier_offers: Dict = None,
                 supplier_orders: Dict = None):
        """Initialize with references to all data stores"""
        self.users = users or {}
        self.customers = customers or {}
        self.suppliers = suppliers or {}
        self.policies = policies or {}
        self.claims = claims or {}
        self.bills = bills or {}
        self.underwriting_apps = underwriting_apps or {}
        self.health_wallets = health_wallets or {}
        self.investment_accounts = investment_accounts or {}
        self.transaction_ledger = transaction_ledger or {}
        self.nft_ledger = nft_ledger or {}
        self.foundations = foundations or {}
        self.supplier_offers = supplier_offers or {}
        self.supplier_orders = supplier_orders or {}
        
        self._issue_counter = 0
    
    def _generate_issue_id(self) -> str:
        """Generate unique issue ID"""
        self._issue_counter += 1
        return f"VAL-{datetime.now().strftime('%Y%m%d')}-{self._issue_counter:05d}"
    
    def run_full_validation(self) -> ValidationReport:
        """
        Run complete platform validation.
        
        Returns comprehensive report with all issues found.
        """
        report = ValidationReport(
            report_id=f"RPT-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            generated_at=datetime.now(timezone.utc).isoformat(),
            platform_health_score=100.0,
            total_entities_checked=0,
            total_issues_found=0,
            critical_issues=0,
            high_issues=0,
            medium_issues=0,
            low_issues=0
        )
        
        # 1. Validate Users
        user_issues = self._validate_users()
        report.issues.extend(user_issues)
        report.user_validation = {
            'total_users': len(self.users),
            'issues_found': len(user_issues),
            'by_role': self._count_users_by_role()
        }
        
        # 2. Validate Customers
        customer_issues = self._validate_customers()
        report.issues.extend(customer_issues)
        
        # 3. Validate Suppliers
        supplier_issues = self._validate_suppliers()
        report.issues.extend(supplier_issues)
        
        # 4. Validate Ledgers
        ledger_issues = self._validate_ledgers()
        report.issues.extend(ledger_issues)
        report.ledger_validation = {
            'transaction_ledger_entries': len(self.transaction_ledger),
            'nft_ledger_entries': len(self.nft_ledger),
            'issues_found': len(ledger_issues)
        }
        
        # 5. Validate Pipeline (Policies, Underwriting, Billing, Claims)
        pipeline_issues = self._validate_pipeline()
        report.issues.extend(pipeline_issues)
        report.pipeline_validation = {
            'policies': len(self.policies),
            'underwriting_apps': len(self.underwriting_apps),
            'bills': len(self.bills),
            'claims': len(self.claims),
            'issues_found': len(pipeline_issues)
        }
        
        # 6. Validate Relationships
        relationship_issues = self._validate_relationships()
        report.issues.extend(relationship_issues)
        report.relationship_validation = {
            'issues_found': len(relationship_issues)
        }
        
        # Calculate totals and scores
        report.total_issues_found = len(report.issues)
        report.critical_issues = sum(1 for i in report.issues if i.severity == ValidationSeverity.CRITICAL)
        report.high_issues = sum(1 for i in report.issues if i.severity == ValidationSeverity.HIGH)
        report.medium_issues = sum(1 for i in report.issues if i.severity == ValidationSeverity.MEDIUM)
        report.low_issues = sum(1 for i in report.issues if i.severity == ValidationSeverity.LOW)
        report.auto_fixes_available = sum(1 for i in report.issues if i.auto_fixable)
        
        # Calculate entity count
        report.total_entities_checked = (
            len(self.users) + len(self.customers) + len(self.suppliers) +
            len(self.policies) + len(self.claims) + len(self.bills) +
            len(self.underwriting_apps) + len(self.health_wallets) +
            len(self.transaction_ledger) + len(self.nft_ledger)
        )
        
        # Calculate health score
        report.platform_health_score = self._calculate_health_score(report)
        
        # Generate AI recommendations
        report.ai_recommendations = self._generate_recommendations(report)
        
        return report
    
    def _validate_users(self) -> List[ValidationIssue]:
        """Validate user data integrity"""
        issues = []
        
        for username, user in self.users.items():
            # Check role validity
            role = user.get('role', '').lower()
            if role not in self.VALID_STAFF_ROLES and role != self.VALID_CUSTOMER_ROLE and role != self.VALID_SUPPLIER_ROLE:
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.HIGH,
                    category='user_data',
                    entity_type='user',
                    entity_id=username,
                    field='role',
                    expected_value=f"One of: {self.VALID_STAFF_ROLES | {self.VALID_CUSTOMER_ROLE, self.VALID_SUPPLIER_ROLE}}",
                    actual_value=role,
                    description=f"User '{username}' has invalid role '{role}'",
                    auto_fixable=False
                ))
            
            # Check required fields
            if not user.get('email'):
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.MEDIUM,
                    category='user_data',
                    entity_type='user',
                    entity_id=username,
                    field='email',
                    expected_value='Valid email address',
                    actual_value=user.get('email'),
                    description=f"User '{username}' missing email address",
                    auto_fixable=False
                ))
            
            # Check password hash exists
            if not user.get('password_hash') or not user.get('password_salt'):
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.CRITICAL,
                    category='user_data',
                    entity_type='user',
                    entity_id=username,
                    field='password_hash',
                    expected_value='Hashed password',
                    actual_value='Missing or null',
                    description=f"User '{username}' has missing password credentials",
                    auto_fixable=False
                ))
            
            # Check customer users have customer_id link
            if role == self.VALID_CUSTOMER_ROLE:
                customer_id = user.get('customer_id')
                if customer_id and customer_id not in self.customers:
                    issues.append(ValidationIssue(
                        issue_id=self._generate_issue_id(),
                        severity=ValidationSeverity.HIGH,
                        category='relationship',
                        entity_type='user',
                        entity_id=username,
                        field='customer_id',
                        expected_value='Valid customer ID',
                        actual_value=customer_id,
                        description=f"User '{username}' linked to non-existent customer '{customer_id}'",
                        auto_fixable=False
                    ))
        
        return issues
    
    def _validate_customers(self) -> List[ValidationIssue]:
        """Validate customer data integrity"""
        issues = []
        emails_seen = set()
        
        for customer_id, customer in self.customers.items():
            # Check email uniqueness
            email = customer.get('email', '').lower()
            if email in emails_seen:
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.CRITICAL,
                    category='user_data',
                    entity_type='customer',
                    entity_id=customer_id,
                    field='email',
                    expected_value='Unique email',
                    actual_value=email,
                    description=f"Duplicate email '{email}' found for customer '{customer_id}'",
                    auto_fixable=False
                ))
            emails_seen.add(email)
            
            # Check required fields
            required_fields = ['name', 'email']
            for req_field in required_fields:
                if not customer.get(req_field):
                    issues.append(ValidationIssue(
                        issue_id=self._generate_issue_id(),
                        severity=ValidationSeverity.MEDIUM,
                        category='user_data',
                        entity_type='customer',
                        entity_id=customer_id,
                        field=req_field,
                        expected_value=f'Valid {req_field}',
                        actual_value=customer.get(req_field),
                        description=f"Customer '{customer_id}' missing required field '{req_field}'",
                        auto_fixable=False
                    ))
            
            # Check ID format
            if not customer_id.startswith('CUST-'):
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.LOW,
                    category='user_data',
                    entity_type='customer',
                    entity_id=customer_id,
                    field='id',
                    expected_value='CUST-* format',
                    actual_value=customer_id,
                    description=f"Customer ID '{customer_id}' doesn't follow CUST-* naming convention",
                    auto_fixable=False
                ))
        
        return issues
    
    def _validate_suppliers(self) -> List[ValidationIssue]:
        """Validate supplier data integrity"""
        issues = []
        
        for supplier_id, supplier in self.suppliers.items():
            # Check status validity
            status = supplier.get('status', '').lower()
            if status not in self.VALID_SUPPLIER_STATUSES:
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.MEDIUM,
                    category='user_data',
                    entity_type='supplier',
                    entity_id=supplier_id,
                    field='status',
                    expected_value=f"One of: {self.VALID_SUPPLIER_STATUSES}",
                    actual_value=status,
                    description=f"Supplier '{supplier_id}' has invalid status '{status}'",
                    auto_fixable=True,
                    fix_action="Set status to 'pending' if unrecognized"
                ))
            
            # Check required fields
            required_fields = ['company_name', 'contact_email', 'supplier_type']
            for req_field in required_fields:
                if not supplier.get(req_field):
                    issues.append(ValidationIssue(
                        issue_id=self._generate_issue_id(),
                        severity=ValidationSeverity.MEDIUM,
                        category='user_data',
                        entity_type='supplier',
                        entity_id=supplier_id,
                        field=req_field,
                        expected_value=f'Valid {req_field}',
                        actual_value=supplier.get(req_field),
                        description=f"Supplier '{supplier_id}' missing required field '{req_field}'",
                        auto_fixable=False
                    ))
            
            # Check approved suppliers have portal access
            if status == 'approved' and not supplier.get('portal_active'):
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.MEDIUM,
                    category='user_data',
                    entity_type='supplier',
                    entity_id=supplier_id,
                    field='portal_active',
                    expected_value=True,
                    actual_value=supplier.get('portal_active'),
                    description=f"Approved supplier '{supplier_id}' doesn't have portal access",
                    auto_fixable=True,
                    fix_action="Set portal_active to True"
                ))
        
        return issues
    
    def _validate_ledgers(self) -> List[ValidationIssue]:
        """Validate transaction and NFT ledger integrity"""
        issues = []
        
        # Validate transaction ledger
        for tx_id, tx in self.transaction_ledger.items():
            # Check required transaction fields
            if not tx.get('customer_id') and not tx.get('entity_id'):
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.MEDIUM,
                    category='ledger',
                    entity_type='transaction',
                    entity_id=tx_id,
                    field='customer_id',
                    expected_value='Valid customer/entity ID',
                    actual_value=None,
                    description=f"Transaction '{tx_id}' missing customer/entity reference",
                    auto_fixable=False
                ))
            
            # Check amount is valid number
            amount = tx.get('amount')
            if amount is not None and not isinstance(amount, (int, float)):
                try:
                    float(amount)
                except (ValueError, TypeError):
                    issues.append(ValidationIssue(
                        issue_id=self._generate_issue_id(),
                        severity=ValidationSeverity.HIGH,
                        category='ledger',
                        entity_type='transaction',
                        entity_id=tx_id,
                        field='amount',
                        expected_value='Numeric value',
                        actual_value=amount,
                        description=f"Transaction '{tx_id}' has invalid amount: {amount}",
                        auto_fixable=True,
                        fix_action="Convert to float or set to 0"
                    ))
            
            # Check timestamp exists
            if not tx.get('timestamp') and not tx.get('created_at'):
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.LOW,
                    category='ledger',
                    entity_type='transaction',
                    entity_id=tx_id,
                    field='timestamp',
                    expected_value='ISO timestamp',
                    actual_value=None,
                    description=f"Transaction '{tx_id}' missing timestamp",
                    auto_fixable=True,
                    fix_action="Set to current timestamp"
                ))
        
        # Validate NFT ledger
        for nft_id, nft in self.nft_ledger.items():
            # Check owner exists
            owner_id = nft.get('owner_id')
            if owner_id:
                owner_exists = (
                    owner_id in self.customers or
                    owner_id in self.suppliers or
                    any(u.get('customer_id') == owner_id for u in self.users.values())
                )
                if not owner_exists:
                    issues.append(ValidationIssue(
                        issue_id=self._generate_issue_id(),
                        severity=ValidationSeverity.MEDIUM,
                        category='ledger',
                        entity_type='nft',
                        entity_id=nft_id,
                        field='owner_id',
                        expected_value='Valid owner reference',
                        actual_value=owner_id,
                        description=f"NFT '{nft_id}' has orphaned owner reference '{owner_id}'",
                        auto_fixable=False
                    ))
            
            # Check verification hash
            if not nft.get('verification_hash') and not nft.get('token_hash'):
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.LOW,
                    category='ledger',
                    entity_type='nft',
                    entity_id=nft_id,
                    field='verification_hash',
                    expected_value='Valid hash',
                    actual_value=None,
                    description=f"NFT '{nft_id}' missing verification hash",
                    auto_fixable=True,
                    fix_action="Generate new verification hash"
                ))
        
        return issues
    
    def _validate_pipeline(self) -> List[ValidationIssue]:
        """Validate insurance pipeline data integrity"""
        issues = []
        
        # Validate Policies
        for policy_id, policy in self.policies.items():
            # Check status validity
            status = str(policy.get('status', '')).lower()
            if status not in self.VALID_POLICY_STATUSES:
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.MEDIUM,
                    category='pipeline',
                    entity_type='policy',
                    entity_id=policy_id,
                    field='status',
                    expected_value=f"One of: {self.VALID_POLICY_STATUSES}",
                    actual_value=status,
                    description=f"Policy '{policy_id}' has invalid status '{status}'",
                    auto_fixable=True,
                    fix_action="Set to 'pending_underwriting'"
                ))
            
            # Check customer exists
            customer_id = policy.get('customer_id')
            if customer_id and customer_id not in self.customers:
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.CRITICAL,
                    category='relationship',
                    entity_type='policy',
                    entity_id=policy_id,
                    field='customer_id',
                    expected_value='Valid customer ID',
                    actual_value=customer_id,
                    description=f"Policy '{policy_id}' references non-existent customer '{customer_id}'",
                    auto_fixable=False
                ))
            
            # Check premium values are valid
            annual = policy.get('annual_premium', 0)
            monthly = policy.get('monthly_premium', 0)
            
            if annual and monthly:
                expected_monthly = float(annual) / 12
                actual_monthly = float(monthly)
                if abs(expected_monthly - actual_monthly) > expected_monthly * 0.05:  # 5% tolerance
                    issues.append(ValidationIssue(
                        issue_id=self._generate_issue_id(),
                        severity=ValidationSeverity.MEDIUM,
                        category='pipeline',
                        entity_type='policy',
                        entity_id=policy_id,
                        field='monthly_premium',
                        expected_value=round(expected_monthly, 2),
                        actual_value=actual_monthly,
                        description=f"Policy '{policy_id}' monthly premium doesn't match annual/12",
                        auto_fixable=True,
                        fix_action=f"Set monthly_premium to {expected_monthly:.2f}"
                    ))
        
        # Validate Claims
        for claim_id, claim in self.claims.items():
            status = str(claim.get('status', '')).lower()
            if status not in self.VALID_CLAIM_STATUSES:
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.MEDIUM,
                    category='pipeline',
                    entity_type='claim',
                    entity_id=claim_id,
                    field='status',
                    expected_value=f"One of: {self.VALID_CLAIM_STATUSES}",
                    actual_value=status,
                    description=f"Claim '{claim_id}' has invalid status '{status}'",
                    auto_fixable=True,
                    fix_action="Set to 'pending'"
                ))
            
            # Check policy exists
            policy_id = claim.get('policy_id')
            if policy_id and policy_id not in self.policies:
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.HIGH,
                    category='relationship',
                    entity_type='claim',
                    entity_id=claim_id,
                    field='policy_id',
                    expected_value='Valid policy ID',
                    actual_value=policy_id,
                    description=f"Claim '{claim_id}' references non-existent policy '{policy_id}'",
                    auto_fixable=False
                ))
        
        # Validate Bills
        for bill_id, bill in self.bills.items():
            status = str(bill.get('status', '')).lower()
            if status not in self.VALID_BILL_STATUSES:
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.MEDIUM,
                    category='pipeline',
                    entity_type='bill',
                    entity_id=bill_id,
                    field='status',
                    expected_value=f"One of: {self.VALID_BILL_STATUSES}",
                    actual_value=status,
                    description=f"Bill '{bill_id}' has invalid status '{status}'",
                    auto_fixable=True,
                    fix_action="Set to 'outstanding'"
                ))
        
        # Validate Underwriting Applications
        for uw_id, uw_app in self.underwriting_apps.items():
            status = str(uw_app.get('status', '')).lower()
            if status not in self.VALID_UNDERWRITING_STATUSES:
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.MEDIUM,
                    category='pipeline',
                    entity_type='underwriting',
                    entity_id=uw_id,
                    field='status',
                    expected_value=f"One of: {self.VALID_UNDERWRITING_STATUSES}",
                    actual_value=status,
                    description=f"Underwriting '{uw_id}' has invalid status '{status}'",
                    auto_fixable=True,
                    fix_action="Set to 'pending'"
                ))
        
        return issues
    
    def _validate_relationships(self) -> List[ValidationIssue]:
        """Validate data relationship integrity"""
        issues = []
        
        # Check health wallets have valid customers
        for wallet_id, wallet in self.health_wallets.items():
            customer_id = wallet.get('customer_id', wallet_id)
            if customer_id not in self.customers:
                # It's possible wallet is keyed by customer ID
                if wallet_id not in self.customers:
                    issues.append(ValidationIssue(
                        issue_id=self._generate_issue_id(),
                        severity=ValidationSeverity.MEDIUM,
                        category='relationship',
                        entity_type='health_wallet',
                        entity_id=wallet_id,
                        field='customer_id',
                        expected_value='Valid customer ID',
                        actual_value=customer_id,
                        description=f"Health wallet '{wallet_id}' has no matching customer",
                        auto_fixable=False
                    ))
        
        # Check supplier offers reference valid suppliers
        for offer_id, offer in self.supplier_offers.items():
            supplier_id = offer.get('supplier_id')
            if supplier_id and supplier_id not in self.suppliers:
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.HIGH,
                    category='relationship',
                    entity_type='supplier_offer',
                    entity_id=offer_id,
                    field='supplier_id',
                    expected_value='Valid supplier ID',
                    actual_value=supplier_id,
                    description=f"Offer '{offer_id}' references non-existent supplier '{supplier_id}'",
                    auto_fixable=False
                ))
        
        # Check supplier orders reference valid customers and suppliers
        for order_id, order in self.supplier_orders.items():
            supplier_id = order.get('supplier_id')
            customer_id = order.get('customer_id')
            
            if supplier_id and supplier_id not in self.suppliers:
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.HIGH,
                    category='relationship',
                    entity_type='supplier_order',
                    entity_id=order_id,
                    field='supplier_id',
                    expected_value='Valid supplier ID',
                    actual_value=supplier_id,
                    description=f"Order '{order_id}' references non-existent supplier",
                    auto_fixable=False
                ))
            
            if customer_id and customer_id not in self.customers:
                issues.append(ValidationIssue(
                    issue_id=self._generate_issue_id(),
                    severity=ValidationSeverity.HIGH,
                    category='relationship',
                    entity_type='supplier_order',
                    entity_id=order_id,
                    field='customer_id',
                    expected_value='Valid customer ID',
                    actual_value=customer_id,
                    description=f"Order '{order_id}' references non-existent customer",
                    auto_fixable=False
                ))
        
        return issues
    
    def _count_users_by_role(self) -> Dict[str, int]:
        """Count users by role"""
        counts = {}
        for user in self.users.values():
            role = user.get('role', 'unknown')
            counts[role] = counts.get(role, 0) + 1
        return counts
    
    def _calculate_health_score(self, report: ValidationReport) -> float:
        """Calculate platform health score (0-100)"""
        if report.total_entities_checked == 0:
            return 100.0
        
        # Weighted severity scoring
        severity_weights = {
            'critical': 20,
            'high': 10,
            'medium': 5,
            'low': 1
        }
        
        total_penalty = (
            report.critical_issues * severity_weights['critical'] +
            report.high_issues * severity_weights['high'] +
            report.medium_issues * severity_weights['medium'] +
            report.low_issues * severity_weights['low']
        )
        
        # Score relative to entities checked
        max_penalty = report.total_entities_checked * 10  # Max 10 points per entity
        score = max(0, 100 - (total_penalty / max(max_penalty, 1)) * 100)
        
        return round(score, 2)
    
    def _generate_recommendations(self, report: ValidationReport) -> List[str]:
        """Generate AI-powered recommendations based on validation results"""
        recommendations = []
        
        if report.critical_issues > 0:
            recommendations.append(
                f"🚨 CRITICAL: {report.critical_issues} critical issues require immediate attention. "
                "These may cause system failures or data corruption."
            )
        
        if report.high_issues > 0:
            recommendations.append(
                f"⚠️ HIGH PRIORITY: {report.high_issues} high severity issues found. "
                "Address these before they escalate to critical."
            )
        
        if report.auto_fixes_available > 0:
            recommendations.append(
                f"💡 AUTO-FIX: {report.auto_fixes_available} issues can be automatically corrected. "
                "Run apply_auto_fixes() to resolve these."
            )
        
        # Check for specific patterns
        relationship_issues = [i for i in report.issues if i.category == 'relationship']
        if len(relationship_issues) > 5:
            recommendations.append(
                f"🔗 DATA INTEGRITY: {len(relationship_issues)} orphaned relationships detected. "
                "Consider running data migration or cleanup scripts."
            )
        
        ledger_issues = [i for i in report.issues if i.category == 'ledger']
        if len(ledger_issues) > 0:
            recommendations.append(
                f"📒 LEDGER: {len(ledger_issues)} ledger inconsistencies found. "
                "Reconcile transaction and NFT ledgers for financial accuracy."
            )
        
        if report.platform_health_score >= 95:
            recommendations.append("✅ EXCELLENT: Platform data integrity is in excellent condition.")
        elif report.platform_health_score >= 80:
            recommendations.append("✅ GOOD: Platform is healthy with minor issues to address.")
        elif report.platform_health_score >= 60:
            recommendations.append("⚠️ ATTENTION NEEDED: Multiple data issues require attention.")
        else:
            recommendations.append("🚨 CRITICAL STATE: Platform data integrity is compromised. Immediate action required.")
        
        return recommendations
    
    def apply_auto_fixes(self, report: ValidationReport = None) -> Dict[str, Any]:
        """
        Apply automatic fixes for issues that can be auto-corrected.
        
        Returns summary of fixes applied.
        """
        if report is None:
            report = self.run_full_validation()
        
        fixes_applied = []
        fixes_failed = []
        
        for issue in report.issues:
            if not issue.auto_fixable:
                continue
            
            try:
                if issue.entity_type == 'supplier' and issue.field == 'portal_active':
                    if issue.entity_id in self.suppliers:
                        self.suppliers[issue.entity_id]['portal_active'] = True
                        fixes_applied.append(f"Activated portal for supplier {issue.entity_id}")
                
                elif issue.entity_type == 'policy' and issue.field == 'monthly_premium':
                    if issue.entity_id in self.policies:
                        self.policies[issue.entity_id]['monthly_premium'] = issue.expected_value
                        fixes_applied.append(f"Corrected monthly premium for policy {issue.entity_id}")
                
                elif issue.entity_type == 'policy' and issue.field == 'status':
                    if issue.entity_id in self.policies:
                        self.policies[issue.entity_id]['status'] = 'pending_underwriting'
                        fixes_applied.append(f"Set pending status for policy {issue.entity_id}")
                
                elif issue.entity_type == 'claim' and issue.field == 'status':
                    if issue.entity_id in self.claims:
                        self.claims[issue.entity_id]['status'] = 'pending'
                        fixes_applied.append(f"Set pending status for claim {issue.entity_id}")
                
                elif issue.entity_type == 'bill' and issue.field == 'status':
                    if issue.entity_id in self.bills:
                        self.bills[issue.entity_id]['status'] = 'outstanding'
                        fixes_applied.append(f"Set outstanding status for bill {issue.entity_id}")
                
                elif issue.entity_type == 'transaction' and issue.field == 'timestamp':
                    if issue.entity_id in self.transaction_ledger:
                        self.transaction_ledger[issue.entity_id]['timestamp'] = datetime.now(timezone.utc).isoformat()
                        fixes_applied.append(f"Added timestamp to transaction {issue.entity_id}")
                
            except Exception as e:
                fixes_failed.append(f"Failed to fix {issue.entity_type}/{issue.entity_id}: {str(e)}")
        
        return {
            'success': True,
            'fixes_applied': len(fixes_applied),
            'fixes_failed': len(fixes_failed),
            'details': fixes_applied,
            'errors': fixes_failed
        }
    
    def get_summary_stats(self) -> Dict[str, Any]:
        """Get quick summary statistics of platform data"""
        return {
            'users': {
                'total': len(self.users),
                'by_role': self._count_users_by_role()
            },
            'customers': {
                'total': len(self.customers),
                'with_policies': len(set(p.get('customer_id') for p in self.policies.values())),
                'with_wallets': len(self.health_wallets)
            },
            'suppliers': {
                'total': len(self.suppliers),
                'approved': sum(1 for s in self.suppliers.values() if s.get('status') == 'approved'),
                'pending': sum(1 for s in self.suppliers.values() if s.get('status') == 'pending')
            },
            'policies': {
                'total': len(self.policies),
                'active': sum(1 for p in self.policies.values() if p.get('status') == 'active'),
                'pending': sum(1 for p in self.policies.values() if 'pending' in str(p.get('status', '')).lower())
            },
            'claims': {
                'total': len(self.claims),
                'pending': sum(1 for c in self.claims.values() if c.get('status') == 'pending'),
                'approved': sum(1 for c in self.claims.values() if c.get('status') == 'approved')
            },
            'ledger': {
                'transactions': len(self.transaction_ledger),
                'nfts': len(self.nft_ledger)
            }
        }


# Singleton instance
_validator_instance: Optional[PlatformDataValidator] = None


def get_platform_validator(**kwargs) -> PlatformDataValidator:
    """Get or create the platform validator singleton"""
    global _validator_instance
    if _validator_instance is None:
        _validator_instance = PlatformDataValidator(**kwargs)
    return _validator_instance


def init_platform_validator(**kwargs) -> PlatformDataValidator:
    """Initialize platform validator with data stores"""
    global _validator_instance
    _validator_instance = PlatformDataValidator(**kwargs)
    return _validator_instance
