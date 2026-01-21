"""
PHINS Foundation Ledger Service
Blockchain-like immutable ledger for community foundation actions

Features:
- Immutable ledger entries for all foundation events
- NFT-like action documentation
- Member join/create validation
- Financial transaction tracking
- Investment wallet management
- Risk assessment and BI analytics
- Data integrity verification via hash chains
"""

from __future__ import annotations

import json
import hashlib
import secrets
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import uuid
from decimal import Decimal, ROUND_HALF_UP

logger = logging.getLogger('phins.foundation.ledger')


# ============================================================================
# ENUMS & CONSTANTS
# ============================================================================

class LedgerEntryType(str, Enum):
    """Types of ledger entries"""
    FOUNDATION_CREATED = "foundation_created"
    FOUNDATION_ACTIVATED = "foundation_activated"
    FOUNDATION_SUSPENDED = "foundation_suspended"
    FOUNDATION_DISSOLVED = "foundation_dissolved"
    
    MEMBER_JOINED = "member_joined"
    MEMBER_APPROVED = "member_approved"
    MEMBER_LEFT = "member_left"
    MEMBER_REMOVED = "member_removed"
    MEMBER_PROFILE_UPDATED = "member_profile_updated"
    
    CONTRIBUTION_RECEIVED = "contribution_received"
    CONTRIBUTION_SCHEDULED = "contribution_scheduled"
    
    CLAIM_SUBMITTED = "claim_submitted"
    CLAIM_APPROVED = "claim_approved"
    CLAIM_REJECTED = "claim_rejected"
    CLAIM_PAID = "claim_paid"
    
    INVESTMENT_CREATED = "investment_created"
    INVESTMENT_MATURED = "investment_matured"
    INVESTMENT_WITHDRAWN = "investment_withdrawn"
    
    VOTE_CREATED = "vote_created"
    VOTE_CAST = "vote_cast"
    VOTE_CONCLUDED = "vote_concluded"
    
    BILL_GENERATED = "bill_generated"
    BILL_PAID = "bill_paid"
    BILL_OVERDUE = "bill_overdue"
    
    NFT_MINTED = "nft_minted"
    NFT_TRANSFERRED = "nft_transferred"
    
    RISK_ASSESSMENT = "risk_assessment"
    BI_REPORT_GENERATED = "bi_report_generated"


class WalletType(str, Enum):
    """Types of foundation wallets"""
    OPERATING = "operating"         # Day-to-day operations
    RESERVE = "reserve"             # Emergency reserves
    INVESTMENT = "investment"       # Investment portfolio
    CLAIMS = "claims"               # Claims payout pool
    BILLING = "billing"             # Billing receivables


class InvestmentType(str, Enum):
    """Types of investments"""
    FIXED_DEPOSIT = "fixed_deposit"
    MUTUAL_FUND = "mutual_fund"
    BONDS = "bonds"
    MONEY_MARKET = "money_market"
    CUSTOM = "custom"


class RiskLevel(str, Enum):
    """Risk levels for foundations"""
    VERY_LOW = "very_low"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    VERY_HIGH = "very_high"


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class LedgerEntry:
    """Immutable ledger entry"""
    id: str
    foundation_id: str
    entry_type: str
    timestamp: str
    actor_id: str
    actor_type: str  # member, system, admin
    
    # Entry data (JSON serializable)
    data: Dict[str, Any]
    
    # Privacy classification
    is_public: bool = True  # Public to foundation members
    is_sensitive: bool = False  # Contains PII
    
    # Hash chain for immutability
    previous_hash: str = ""
    entry_hash: str = ""
    
    # Verification
    verified: bool = False
    verified_at: Optional[str] = None
    verified_by: Optional[str] = None
    
    def compute_hash(self) -> str:
        """Compute hash of this entry"""
        content = f"{self.id}{self.foundation_id}{self.entry_type}{self.timestamp}"
        content += f"{self.actor_id}{json.dumps(self.data, sort_keys=True)}{self.previous_hash}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MemberProfile:
    """Extended member profile with sensitive data separation"""
    member_id: str
    foundation_id: str
    
    # Public profile (visible to other members)
    display_name: str
    role: str
    status: str
    joined_at: str
    photo_url: Optional[str] = None
    bio: Optional[str] = None
    
    # Contribution summary (visible to admins)
    total_contributed: float = 0.0
    contribution_count: int = 0
    last_contribution: Optional[str] = None
    contribution_streak: int = 0  # Consecutive months
    
    # Private/Sensitive data (only visible to admins with permission)
    full_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    age: Optional[int] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    id_document_type: Optional[str] = None
    id_document_number: Optional[str] = None
    
    # KYC/Verification status
    kyc_status: str = "pending"  # pending, verified, rejected
    kyc_verified_at: Optional[str] = None
    
    # Risk profile
    risk_score: float = 0.0
    risk_level: str = "moderate"
    
    def to_public_dict(self) -> Dict[str, Any]:
        """Return public data only"""
        return {
            'member_id': self.member_id,
            'display_name': self.display_name,
            'role': self.role,
            'status': self.status,
            'joined_at': self.joined_at,
            'photo_url': self.photo_url,
            'bio': self.bio,
            'total_contributed': self.total_contributed,
            'contribution_count': self.contribution_count,
            'contribution_streak': self.contribution_streak
        }
    
    def to_admin_dict(self) -> Dict[str, Any]:
        """Return all data for admin view"""
        return asdict(self)


@dataclass
class FoundationWallet:
    """Foundation wallet for financial management"""
    id: str
    foundation_id: str
    wallet_type: str
    name: str
    
    balance: float = 0.0
    currency: str = "USD"
    
    # Limits and rules
    min_balance: float = 0.0
    max_single_transaction: float = 0.0
    requires_approval_above: float = 0.0
    
    # Status
    status: str = "active"
    
    # Timestamps
    created_at: str = ""
    updated_at: str = ""
    last_transaction: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Investment:
    """Foundation investment record"""
    id: str
    foundation_id: str
    wallet_id: str
    
    investment_type: str
    name: str
    description: str = ""
    
    # Financial details
    principal: float = 0.0
    current_value: float = 0.0
    expected_return: float = 0.0
    currency: str = "USD"
    
    # Terms
    start_date: str = ""
    maturity_date: Optional[str] = None
    interest_rate: float = 0.0
    
    # Status
    status: str = "active"  # active, matured, withdrawn
    
    # Timestamps
    created_at: str = ""
    updated_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Bill:
    """Member billing record"""
    id: str
    foundation_id: str
    member_id: str
    
    # Bill details
    bill_type: str  # contribution, fee, penalty
    description: str
    amount: float
    currency: str = "USD"
    
    # Period
    period_start: str = ""
    period_end: str = ""
    due_date: str = ""
    
    # Payment
    amount_paid: float = 0.0
    paid_at: Optional[str] = None
    payment_reference: Optional[str] = None
    
    # Status
    status: str = "pending"  # pending, paid, partial, overdue, cancelled
    
    # Timestamps
    created_at: str = ""
    updated_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NFTRecord:
    """NFT-like documentation for foundation actions"""
    id: str
    foundation_id: str
    
    # NFT metadata
    token_type: str  # membership, contribution, achievement, milestone
    title: str
    description: str = ""
    image_url: Optional[str] = None
    
    # Owner
    owner_id: str = ""
    owner_type: str = ""  # member, foundation
    
    # Attributes
    attributes: Dict[str, Any] = field(default_factory=dict)
    
    # Chain reference
    ledger_entry_id: str = ""
    minting_hash: str = ""
    
    # Transfer history
    transfer_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Status
    status: str = "active"
    
    # Timestamps
    minted_at: str = ""
    updated_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RiskAssessment:
    """Foundation risk assessment"""
    id: str
    foundation_id: str
    
    # Assessment details
    assessment_date: str
    assessment_type: str  # initial, periodic, event_triggered
    
    # Risk scores (0-100)
    financial_risk: float = 50.0
    operational_risk: float = 50.0
    member_risk: float = 50.0
    compliance_risk: float = 50.0
    overall_risk: float = 50.0
    
    # Risk level
    risk_level: str = "moderate"
    
    # Factors
    positive_factors: List[str] = field(default_factory=list)
    negative_factors: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    
    # AI/ML insights
    ai_insights: Dict[str, Any] = field(default_factory=dict)
    
    # Timestamps
    created_at: str = ""
    valid_until: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BIReport:
    """Business Intelligence report"""
    id: str
    foundation_id: str
    
    # Report details
    report_type: str  # daily, weekly, monthly, quarterly, custom
    period_start: str
    period_end: str
    
    # Metrics
    metrics: Dict[str, Any] = field(default_factory=dict)
    
    # Comparisons
    period_over_period: Dict[str, Any] = field(default_factory=dict)
    
    # Insights
    insights: List[str] = field(default_factory=list)
    alerts: List[str] = field(default_factory=list)
    
    # Generated by
    generated_by: str = "system"
    generated_at: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def generate_id(prefix: str) -> str:
    """Generate a unique ID with prefix"""
    unique_part = uuid.uuid4().hex[:8].upper()
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d')
    return f"{prefix}-{timestamp}-{unique_part}"


def now_iso() -> str:
    """Get current UTC timestamp in ISO format"""
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# FOUNDATION LEDGER SERVICE
# ============================================================================

class FoundationLedgerService:
    """
    Comprehensive ledger service for community foundations.
    
    Provides:
    - Immutable ledger for all foundation actions
    - Member validation on join/create events
    - Advanced member profiles with privacy separation
    - Wallet management (billing, accounting, investments)
    - NFT documentation for actions
    - Risk assessment and BI analytics
    """
    
    def __init__(self):
        # In-memory storage
        self._ledger_entries: Dict[str, LedgerEntry] = {}
        self._member_profiles: Dict[str, MemberProfile] = {}
        self._wallets: Dict[str, FoundationWallet] = {}
        self._investments: Dict[str, Investment] = {}
        self._bills: Dict[str, Bill] = {}
        self._nft_records: Dict[str, NFTRecord] = {}
        self._risk_assessments: Dict[str, RiskAssessment] = {}
        self._bi_reports: Dict[str, BIReport] = {}
        
        # Track latest hash per foundation for chain
        self._foundation_latest_hash: Dict[str, str] = {}
    
    # ========== LEDGER OPERATIONS ==========
    
    def create_ledger_entry(
        self,
        foundation_id: str,
        entry_type: str,
        actor_id: str,
        actor_type: str,
        data: Dict[str, Any],
        is_public: bool = True,
        is_sensitive: bool = False
    ) -> LedgerEntry:
        """Create a new immutable ledger entry"""
        entry_id = generate_id("LED")
        timestamp = now_iso()
        
        # Get previous hash for chain
        previous_hash = self._foundation_latest_hash.get(foundation_id, "GENESIS")
        
        entry = LedgerEntry(
            id=entry_id,
            foundation_id=foundation_id,
            entry_type=entry_type,
            timestamp=timestamp,
            actor_id=actor_id,
            actor_type=actor_type,
            data=data,
            is_public=is_public,
            is_sensitive=is_sensitive,
            previous_hash=previous_hash
        )
        
        # Compute and set hash
        entry.entry_hash = entry.compute_hash()
        
        # Store entry
        self._ledger_entries[entry_id] = entry
        
        # Update chain
        self._foundation_latest_hash[foundation_id] = entry.entry_hash
        
        logger.info(f"Ledger entry created: {entry_id} type={entry_type} foundation={foundation_id}")
        
        return entry
    
    def get_ledger_entries(
        self,
        foundation_id: str,
        entry_type: Optional[str] = None,
        actor_id: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        include_sensitive: bool = False,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get ledger entries with filtering"""
        entries = []
        
        for entry in self._ledger_entries.values():
            if entry.foundation_id != foundation_id:
                continue
            
            if entry_type and entry.entry_type != entry_type:
                continue
            
            if actor_id and entry.actor_id != actor_id:
                continue
            
            if not include_sensitive and entry.is_sensitive:
                continue
            
            if start_date and entry.timestamp < start_date:
                continue
            
            if end_date and entry.timestamp > end_date:
                continue
            
            entries.append(entry.to_dict())
        
        # Sort by timestamp descending
        entries.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return entries[:limit]
    
    def verify_ledger_integrity(self, foundation_id: str) -> Dict[str, Any]:
        """Verify the integrity of foundation's ledger chain"""
        entries = [e for e in self._ledger_entries.values() 
                   if e.foundation_id == foundation_id]
        
        # Sort by timestamp
        entries.sort(key=lambda x: x.timestamp)
        
        if not entries:
            return {
                'valid': True,
                'message': 'No entries to verify',
                'entries_checked': 0
            }
        
        broken_links = []
        hash_mismatches = []
        
        for i, entry in enumerate(entries):
            # Verify hash
            computed_hash = entry.compute_hash()
            if computed_hash != entry.entry_hash:
                hash_mismatches.append({
                    'entry_id': entry.id,
                    'expected': entry.entry_hash,
                    'computed': computed_hash
                })
            
            # Verify chain
            if i > 0:
                if entry.previous_hash != entries[i-1].entry_hash:
                    broken_links.append({
                        'entry_id': entry.id,
                        'expected_previous': entries[i-1].entry_hash,
                        'actual_previous': entry.previous_hash
                    })
        
        is_valid = len(broken_links) == 0 and len(hash_mismatches) == 0
        
        return {
            'valid': is_valid,
            'entries_checked': len(entries),
            'broken_links': broken_links,
            'hash_mismatches': hash_mismatches,
            'verified_at': now_iso()
        }
    
    # ========== MEMBER JOIN/CREATE VALIDATION ==========
    
    def validate_member_join(
        self,
        foundation_id: str,
        member_id: str,
        member_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate member joining a foundation and record on ledger"""
        validation_result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'ledger_entry_id': None,
            'nft_id': None
        }
        
        # Validate required fields
        if not member_data.get('display_name'):
            validation_result['errors'].append('Display name is required')
        
        # Validate KYC if required
        if member_data.get('require_kyc'):
            if not member_data.get('full_name'):
                validation_result['errors'].append('Full name required for KYC')
            if not member_data.get('date_of_birth'):
                validation_result['errors'].append('Date of birth required for KYC')
            if not member_data.get('id_document_type'):
                validation_result['warnings'].append('ID document recommended for verification')
        
        if validation_result['errors']:
            validation_result['valid'] = False
            return validation_result
        
        # Create member profile
        profile = self._create_member_profile(foundation_id, member_id, member_data)
        
        # Create ledger entry
        ledger_entry = self.create_ledger_entry(
            foundation_id=foundation_id,
            entry_type=LedgerEntryType.MEMBER_JOINED.value,
            actor_id=member_id,
            actor_type='member',
            data={
                'member_id': member_id,
                'display_name': profile.display_name,
                'role': profile.role,
                'kyc_status': profile.kyc_status
            },
            is_sensitive=True
        )
        
        validation_result['ledger_entry_id'] = ledger_entry.id
        
        # Mint membership NFT
        nft = self._mint_membership_nft(foundation_id, member_id, profile, ledger_entry.id)
        validation_result['nft_id'] = nft.id
        
        logger.info(f"Member join validated: member={member_id} foundation={foundation_id}")
        
        return validation_result
    
    def validate_foundation_create(
        self,
        foundation_id: str,
        founder_id: str,
        foundation_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Validate foundation creation and record on ledger"""
        validation_result = {
            'valid': True,
            'errors': [],
            'warnings': [],
            'ledger_entry_id': None,
            'wallets_created': [],
            'risk_assessment_id': None
        }
        
        # Validate foundation name
        name = foundation_data.get('name', '')
        if len(name) < 3:
            validation_result['errors'].append('Foundation name must be at least 3 characters')
        
        # Validate foundation type
        foundation_type = foundation_data.get('foundation_type')
        valid_types = ['family', 'work', 'neighborhood', 'friends', 'entrepreneurs', 
                       'business_venture', 'professional', 'customer_club', 'custom']
        if foundation_type not in valid_types:
            validation_result['errors'].append(f'Invalid foundation type: {foundation_type}')
        
        if validation_result['errors']:
            validation_result['valid'] = False
            return validation_result
        
        # Create ledger entry
        ledger_entry = self.create_ledger_entry(
            foundation_id=foundation_id,
            entry_type=LedgerEntryType.FOUNDATION_CREATED.value,
            actor_id=founder_id,
            actor_type='member',
            data={
                'name': name,
                'foundation_type': foundation_type,
                'founder_id': founder_id,
                'settings': foundation_data.get('settings', {})
            }
        )
        
        validation_result['ledger_entry_id'] = ledger_entry.id
        
        # Create default wallets
        wallets = self._create_foundation_wallets(foundation_id)
        validation_result['wallets_created'] = [w.id for w in wallets]
        
        # Create initial risk assessment
        risk_assessment = self.create_risk_assessment(foundation_id, 'initial')
        validation_result['risk_assessment_id'] = risk_assessment.id
        
        logger.info(f"Foundation creation validated: {foundation_id}")
        
        return validation_result
    
    # ========== MEMBER PROFILES ==========
    
    def _create_member_profile(
        self,
        foundation_id: str,
        member_id: str,
        data: Dict[str, Any]
    ) -> MemberProfile:
        """Create extended member profile"""
        profile_key = f"{foundation_id}:{member_id}"
        
        # Calculate age from date of birth
        age = None
        if data.get('date_of_birth'):
            try:
                dob = datetime.fromisoformat(data['date_of_birth'].replace('Z', '+00:00'))
                today = datetime.now(timezone.utc)
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            except:
                pass
        
        profile = MemberProfile(
            member_id=member_id,
            foundation_id=foundation_id,
            display_name=data.get('display_name', f'Member {member_id[:8]}'),
            role=data.get('role', 'member'),
            status='active',
            joined_at=now_iso(),
            photo_url=data.get('photo_url'),
            bio=data.get('bio'),
            full_name=data.get('full_name'),
            date_of_birth=data.get('date_of_birth'),
            age=age,
            email=data.get('email'),
            phone=data.get('phone'),
            address=data.get('address'),
            id_document_type=data.get('id_document_type'),
            id_document_number=data.get('id_document_number'),
            kyc_status='pending' if data.get('require_kyc') else 'not_required'
        )
        
        self._member_profiles[profile_key] = profile
        
        return profile
    
    def get_member_profile(
        self,
        foundation_id: str,
        member_id: str,
        include_sensitive: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Get member profile"""
        profile_key = f"{foundation_id}:{member_id}"
        profile = self._member_profiles.get(profile_key)
        
        if not profile:
            return None
        
        if include_sensitive:
            return profile.to_admin_dict()
        return profile.to_public_dict()
    
    def update_member_profile(
        self,
        foundation_id: str,
        member_id: str,
        updates: Dict[str, Any],
        actor_id: str
    ) -> Dict[str, Any]:
        """Update member profile and record on ledger"""
        profile_key = f"{foundation_id}:{member_id}"
        profile = self._member_profiles.get(profile_key)
        
        if not profile:
            return {'success': False, 'error': 'Profile not found'}
        
        # Update fields
        for key, value in updates.items():
            if hasattr(profile, key):
                setattr(profile, key, value)
        
        # Recalculate age if DOB updated
        if 'date_of_birth' in updates and updates['date_of_birth']:
            try:
                dob = datetime.fromisoformat(updates['date_of_birth'].replace('Z', '+00:00'))
                today = datetime.now(timezone.utc)
                profile.age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            except:
                pass
        
        # Record on ledger
        self.create_ledger_entry(
            foundation_id=foundation_id,
            entry_type=LedgerEntryType.MEMBER_PROFILE_UPDATED.value,
            actor_id=actor_id,
            actor_type='member',
            data={
                'member_id': member_id,
                'updated_fields': list(updates.keys())
            },
            is_sensitive=True
        )
        
        return {'success': True, 'profile': profile.to_admin_dict()}
    
    def get_all_member_profiles(
        self,
        foundation_id: str,
        include_sensitive: bool = False
    ) -> List[Dict[str, Any]]:
        """Get all member profiles for a foundation"""
        profiles = []
        
        for key, profile in self._member_profiles.items():
            if profile.foundation_id == foundation_id:
                if include_sensitive:
                    profiles.append(profile.to_admin_dict())
                else:
                    profiles.append(profile.to_public_dict())
        
        # Sort by role (founder, admin, member) then by joined date
        role_order = {'founder': 0, 'admin': 1, 'member': 2, 'observer': 3}
        profiles.sort(key=lambda x: (role_order.get(x['role'], 4), x['joined_at']))
        
        return profiles
    
    # ========== WALLET MANAGEMENT ==========
    
    def _create_foundation_wallets(self, foundation_id: str) -> List[FoundationWallet]:
        """Create default wallets for a foundation"""
        wallet_configs = [
            {
                'type': WalletType.OPERATING.value,
                'name': 'Operating Account',
                'min_balance': 0,
                'requires_approval_above': 1000
            },
            {
                'type': WalletType.RESERVE.value,
                'name': 'Reserve Fund',
                'min_balance': 500,
                'requires_approval_above': 500
            },
            {
                'type': WalletType.INVESTMENT.value,
                'name': 'Investment Portfolio',
                'min_balance': 0,
                'requires_approval_above': 2500
            },
            {
                'type': WalletType.CLAIMS.value,
                'name': 'Claims Pool',
                'min_balance': 0,
                'requires_approval_above': 250
            },
            {
                'type': WalletType.BILLING.value,
                'name': 'Billing Receivables',
                'min_balance': 0,
                'requires_approval_above': 0
            }
        ]
        
        wallets = []
        now = now_iso()
        
        for config in wallet_configs:
            wallet = FoundationWallet(
                id=generate_id("WALLET"),
                foundation_id=foundation_id,
                wallet_type=config['type'],
                name=config['name'],
                min_balance=config['min_balance'],
                requires_approval_above=config['requires_approval_above'],
                created_at=now,
                updated_at=now
            )
            self._wallets[wallet.id] = wallet
            wallets.append(wallet)
        
        return wallets
    
    def get_foundation_wallets(self, foundation_id: str) -> List[Dict[str, Any]]:
        """Get all wallets for a foundation"""
        wallets = []
        for wallet in self._wallets.values():
            if wallet.foundation_id == foundation_id:
                wallets.append(wallet.to_dict())
        return wallets
    
    def transfer_between_wallets(
        self,
        foundation_id: str,
        from_wallet_id: str,
        to_wallet_id: str,
        amount: float,
        actor_id: str,
        description: str = ""
    ) -> Dict[str, Any]:
        """Transfer funds between foundation wallets"""
        from_wallet = self._wallets.get(from_wallet_id)
        to_wallet = self._wallets.get(to_wallet_id)
        
        if not from_wallet or from_wallet.foundation_id != foundation_id:
            return {'success': False, 'error': 'Source wallet not found'}
        
        if not to_wallet or to_wallet.foundation_id != foundation_id:
            return {'success': False, 'error': 'Destination wallet not found'}
        
        if from_wallet.balance < amount:
            return {'success': False, 'error': 'Insufficient balance'}
        
        if from_wallet.balance - amount < from_wallet.min_balance:
            return {'success': False, 'error': f'Would violate minimum balance of ${from_wallet.min_balance}'}
        
        # Execute transfer
        from_wallet.balance -= amount
        to_wallet.balance += amount
        
        now = now_iso()
        from_wallet.updated_at = now
        from_wallet.last_transaction = now
        to_wallet.updated_at = now
        to_wallet.last_transaction = now
        
        # Record on ledger
        self.create_ledger_entry(
            foundation_id=foundation_id,
            entry_type=LedgerEntryType.CONTRIBUTION_RECEIVED.value,
            actor_id=actor_id,
            actor_type='admin',
            data={
                'from_wallet': from_wallet_id,
                'to_wallet': to_wallet_id,
                'amount': amount,
                'description': description
            }
        )
        
        return {
            'success': True,
            'from_balance': from_wallet.balance,
            'to_balance': to_wallet.balance
        }
    
    def record_contribution(
        self,
        foundation_id: str,
        member_id: str,
        wallet_type: str,
        amount: float,
        description: str = ""
    ) -> Dict[str, Any]:
        """Record a contribution and update wallet"""
        # Find the target wallet
        target_wallet = None
        for wallet in self._wallets.values():
            if wallet.foundation_id == foundation_id and wallet.wallet_type == wallet_type:
                target_wallet = wallet
                break
        
        if not target_wallet:
            return {'success': False, 'error': 'Wallet not found'}
        
        # Update wallet balance
        target_wallet.balance += amount
        target_wallet.updated_at = now_iso()
        target_wallet.last_transaction = now_iso()
        
        # Update member profile
        profile_key = f"{foundation_id}:{member_id}"
        profile = self._member_profiles.get(profile_key)
        if profile:
            profile.total_contributed += amount
            profile.contribution_count += 1
            profile.last_contribution = now_iso()
        
        # Record on ledger
        ledger_entry = self.create_ledger_entry(
            foundation_id=foundation_id,
            entry_type=LedgerEntryType.CONTRIBUTION_RECEIVED.value,
            actor_id=member_id,
            actor_type='member',
            data={
                'amount': amount,
                'wallet_type': wallet_type,
                'wallet_id': target_wallet.id,
                'description': description
            }
        )
        
        # Mint contribution NFT
        nft = self._mint_contribution_nft(foundation_id, member_id, amount, ledger_entry.id)
        
        return {
            'success': True,
            'wallet_balance': target_wallet.balance,
            'ledger_entry_id': ledger_entry.id,
            'nft_id': nft.id
        }
    
    # ========== INVESTMENTS ==========
    
    def create_investment(
        self,
        foundation_id: str,
        investment_type: str,
        name: str,
        principal: float,
        interest_rate: float,
        maturity_days: Optional[int] = None,
        description: str = "",
        actor_id: str = "system"
    ) -> Dict[str, Any]:
        """Create a new investment"""
        # Find investment wallet
        investment_wallet = None
        for wallet in self._wallets.values():
            if wallet.foundation_id == foundation_id and wallet.wallet_type == WalletType.INVESTMENT.value:
                investment_wallet = wallet
                break
        
        if not investment_wallet:
            return {'success': False, 'error': 'Investment wallet not found'}
        
        if investment_wallet.balance < principal:
            return {'success': False, 'error': 'Insufficient funds in investment wallet'}
        
        # Create investment
        now = now_iso()
        maturity_date = None
        if maturity_days:
            maturity_date = (datetime.now(timezone.utc) + timedelta(days=maturity_days)).isoformat()
        
        investment = Investment(
            id=generate_id("INV"),
            foundation_id=foundation_id,
            wallet_id=investment_wallet.id,
            investment_type=investment_type,
            name=name,
            description=description,
            principal=principal,
            current_value=principal,
            interest_rate=interest_rate,
            start_date=now,
            maturity_date=maturity_date,
            created_at=now,
            updated_at=now
        )
        
        self._investments[investment.id] = investment
        
        # Deduct from wallet
        investment_wallet.balance -= principal
        investment_wallet.updated_at = now
        
        # Record on ledger
        self.create_ledger_entry(
            foundation_id=foundation_id,
            entry_type=LedgerEntryType.INVESTMENT_CREATED.value,
            actor_id=actor_id,
            actor_type='admin',
            data={
                'investment_id': investment.id,
                'type': investment_type,
                'principal': principal,
                'interest_rate': interest_rate
            }
        )
        
        return {'success': True, 'investment': investment.to_dict()}
    
    def get_foundation_investments(self, foundation_id: str) -> List[Dict[str, Any]]:
        """Get all investments for a foundation"""
        investments = []
        for inv in self._investments.values():
            if inv.foundation_id == foundation_id:
                investments.append(inv.to_dict())
        return investments
    
    def calculate_investment_returns(self, foundation_id: str) -> Dict[str, Any]:
        """Calculate total investment returns"""
        investments = [inv for inv in self._investments.values() 
                       if inv.foundation_id == foundation_id and inv.status == 'active']
        
        total_principal = sum(inv.principal for inv in investments)
        total_current_value = 0
        
        now = datetime.now(timezone.utc)
        
        for inv in investments:
            # Calculate accrued value based on time and interest rate
            start = datetime.fromisoformat(inv.start_date.replace('Z', '+00:00'))
            days_held = (now - start).days
            years_held = days_held / 365.0
            
            # Compound interest
            current_value = inv.principal * ((1 + inv.interest_rate / 100) ** years_held)
            inv.current_value = round(current_value, 2)
            total_current_value += current_value
        
        return {
            'total_principal': round(total_principal, 2),
            'total_current_value': round(total_current_value, 2),
            'total_returns': round(total_current_value - total_principal, 2),
            'return_percentage': round(((total_current_value / total_principal) - 1) * 100, 2) if total_principal > 0 else 0,
            'active_investments': len(investments)
        }
    
    # ========== BILLING ==========
    
    def generate_member_bills(
        self,
        foundation_id: str,
        period_start: str,
        period_end: str,
        contribution_amount: float,
        actor_id: str = "system"
    ) -> Dict[str, Any]:
        """Generate bills for all active members"""
        bills_created = []
        now = now_iso()
        due_date = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        
        for key, profile in self._member_profiles.items():
            if profile.foundation_id != foundation_id:
                continue
            if profile.status != 'active':
                continue
            
            bill = Bill(
                id=generate_id("BILL"),
                foundation_id=foundation_id,
                member_id=profile.member_id,
                bill_type='contribution',
                description=f"Monthly contribution for {period_start[:7]}",
                amount=contribution_amount,
                period_start=period_start,
                period_end=period_end,
                due_date=due_date,
                created_at=now,
                updated_at=now
            )
            
            self._bills[bill.id] = bill
            bills_created.append(bill.to_dict())
            
            # Record on ledger
            self.create_ledger_entry(
                foundation_id=foundation_id,
                entry_type=LedgerEntryType.BILL_GENERATED.value,
                actor_id=actor_id,
                actor_type='system',
                data={
                    'bill_id': bill.id,
                    'member_id': profile.member_id,
                    'amount': contribution_amount
                }
            )
        
        return {
            'success': True,
            'bills_created': len(bills_created),
            'bills': bills_created
        }
    
    def record_bill_payment(
        self,
        bill_id: str,
        amount: float,
        payment_reference: str = ""
    ) -> Dict[str, Any]:
        """Record payment for a bill"""
        bill = self._bills.get(bill_id)
        if not bill:
            return {'success': False, 'error': 'Bill not found'}
        
        bill.amount_paid += amount
        bill.paid_at = now_iso()
        bill.payment_reference = payment_reference
        bill.updated_at = now_iso()
        
        if bill.amount_paid >= bill.amount:
            bill.status = 'paid'
        elif bill.amount_paid > 0:
            bill.status = 'partial'
        
        # Record on ledger
        self.create_ledger_entry(
            foundation_id=bill.foundation_id,
            entry_type=LedgerEntryType.BILL_PAID.value,
            actor_id=bill.member_id,
            actor_type='member',
            data={
                'bill_id': bill_id,
                'amount_paid': amount,
                'total_paid': bill.amount_paid,
                'status': bill.status
            }
        )
        
        return {'success': True, 'bill': bill.to_dict()}
    
    def get_member_bills(
        self,
        foundation_id: str,
        member_id: str,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get bills for a member"""
        bills = []
        for bill in self._bills.values():
            if bill.foundation_id == foundation_id and bill.member_id == member_id:
                if status is None or bill.status == status:
                    bills.append(bill.to_dict())
        
        bills.sort(key=lambda x: x['due_date'], reverse=True)
        return bills
    
    def get_foundation_billing_summary(self, foundation_id: str) -> Dict[str, Any]:
        """Get billing summary for foundation"""
        bills = [b for b in self._bills.values() if b.foundation_id == foundation_id]
        
        total_billed = sum(b.amount for b in bills)
        total_collected = sum(b.amount_paid for b in bills)
        outstanding = sum(b.amount - b.amount_paid for b in bills if b.status in ['pending', 'partial'])
        overdue = sum(b.amount - b.amount_paid for b in bills if b.status == 'overdue')
        
        return {
            'total_billed': round(total_billed, 2),
            'total_collected': round(total_collected, 2),
            'outstanding': round(outstanding, 2),
            'overdue': round(overdue, 2),
            'collection_rate': round((total_collected / total_billed) * 100, 2) if total_billed > 0 else 0,
            'total_bills': len(bills),
            'paid_bills': len([b for b in bills if b.status == 'paid']),
            'pending_bills': len([b for b in bills if b.status in ['pending', 'partial']])
        }
    
    # ========== NFT RECORDS ==========
    
    def _mint_membership_nft(
        self,
        foundation_id: str,
        member_id: str,
        profile: MemberProfile,
        ledger_entry_id: str
    ) -> NFTRecord:
        """Mint NFT for membership"""
        nft = NFTRecord(
            id=generate_id("NFT"),
            foundation_id=foundation_id,
            token_type='membership',
            title=f"Membership: {profile.display_name}",
            description=f"Membership certificate for {profile.display_name}",
            owner_id=member_id,
            owner_type='member',
            attributes={
                'role': profile.role,
                'joined_at': profile.joined_at,
                'member_number': profile.member_id
            },
            ledger_entry_id=ledger_entry_id,
            minting_hash=hashlib.sha256(f"{foundation_id}{member_id}{now_iso()}".encode()).hexdigest(),
            minted_at=now_iso(),
            updated_at=now_iso()
        )
        
        self._nft_records[nft.id] = nft
        
        # Record on ledger
        self.create_ledger_entry(
            foundation_id=foundation_id,
            entry_type=LedgerEntryType.NFT_MINTED.value,
            actor_id='system',
            actor_type='system',
            data={
                'nft_id': nft.id,
                'token_type': 'membership',
                'owner_id': member_id
            }
        )
        
        return nft
    
    def _mint_contribution_nft(
        self,
        foundation_id: str,
        member_id: str,
        amount: float,
        ledger_entry_id: str
    ) -> NFTRecord:
        """Mint NFT for contribution"""
        nft = NFTRecord(
            id=generate_id("NFT"),
            foundation_id=foundation_id,
            token_type='contribution',
            title=f"Contribution Certificate",
            description=f"Contribution of ${amount:.2f}",
            owner_id=member_id,
            owner_type='member',
            attributes={
                'amount': amount,
                'contributed_at': now_iso()
            },
            ledger_entry_id=ledger_entry_id,
            minting_hash=hashlib.sha256(f"{foundation_id}{member_id}{amount}{now_iso()}".encode()).hexdigest(),
            minted_at=now_iso(),
            updated_at=now_iso()
        )
        
        self._nft_records[nft.id] = nft
        
        return nft
    
    def get_member_nfts(self, foundation_id: str, member_id: str) -> List[Dict[str, Any]]:
        """Get all NFTs owned by a member"""
        nfts = []
        for nft in self._nft_records.values():
            if nft.foundation_id == foundation_id and nft.owner_id == member_id:
                nfts.append(nft.to_dict())
        return nfts
    
    def get_foundation_nfts(self, foundation_id: str) -> List[Dict[str, Any]]:
        """Get all NFTs for a foundation"""
        nfts = []
        for nft in self._nft_records.values():
            if nft.foundation_id == foundation_id:
                nfts.append(nft.to_dict())
        return nfts
    
    # ========== RISK ASSESSMENT ==========
    
    def create_risk_assessment(
        self,
        foundation_id: str,
        assessment_type: str
    ) -> RiskAssessment:
        """Create a risk assessment for a foundation"""
        # Gather data for assessment
        wallets = self.get_foundation_wallets(foundation_id)
        profiles = self.get_all_member_profiles(foundation_id, include_sensitive=True)
        investments = self.get_foundation_investments(foundation_id)
        billing_summary = self.get_foundation_billing_summary(foundation_id)
        
        # Calculate risk scores
        financial_risk = self._calculate_financial_risk(wallets, investments, billing_summary)
        operational_risk = self._calculate_operational_risk(profiles)
        member_risk = self._calculate_member_risk(profiles, billing_summary)
        compliance_risk = self._calculate_compliance_risk(profiles)
        
        # Calculate overall risk
        weights = {'financial': 0.35, 'operational': 0.25, 'member': 0.25, 'compliance': 0.15}
        overall_risk = (
            financial_risk * weights['financial'] +
            operational_risk * weights['operational'] +
            member_risk * weights['member'] +
            compliance_risk * weights['compliance']
        )
        
        # Determine risk level
        risk_level = self._determine_risk_level(overall_risk)
        
        # Generate factors and recommendations
        positive_factors, negative_factors = self._analyze_risk_factors(
            financial_risk, operational_risk, member_risk, compliance_risk,
            wallets, profiles, billing_summary
        )
        recommendations = self._generate_recommendations(negative_factors, risk_level)
        
        # AI insights
        ai_insights = self._generate_ai_insights(
            financial_risk, operational_risk, member_risk, compliance_risk,
            wallets, investments, profiles
        )
        
        now = now_iso()
        valid_until = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
        
        assessment = RiskAssessment(
            id=generate_id("RISK"),
            foundation_id=foundation_id,
            assessment_date=now,
            assessment_type=assessment_type,
            financial_risk=round(financial_risk, 1),
            operational_risk=round(operational_risk, 1),
            member_risk=round(member_risk, 1),
            compliance_risk=round(compliance_risk, 1),
            overall_risk=round(overall_risk, 1),
            risk_level=risk_level,
            positive_factors=positive_factors,
            negative_factors=negative_factors,
            recommendations=recommendations,
            ai_insights=ai_insights,
            created_at=now,
            valid_until=valid_until
        )
        
        self._risk_assessments[assessment.id] = assessment
        
        # Record on ledger
        self.create_ledger_entry(
            foundation_id=foundation_id,
            entry_type=LedgerEntryType.RISK_ASSESSMENT.value,
            actor_id='system',
            actor_type='system',
            data={
                'assessment_id': assessment.id,
                'overall_risk': overall_risk,
                'risk_level': risk_level
            }
        )
        
        return assessment
    
    def _calculate_financial_risk(
        self,
        wallets: List[Dict],
        investments: List[Dict],
        billing_summary: Dict
    ) -> float:
        """Calculate financial risk score (0-100, higher = more risk)"""
        risk = 50.0  # Start at moderate
        
        # Check total balance
        total_balance = sum(w['balance'] for w in wallets)
        if total_balance > 50000:
            risk -= 10  # Good liquidity
        elif total_balance < 1000:
            risk += 15  # Poor liquidity
        
        # Check collection rate
        collection_rate = billing_summary.get('collection_rate', 0)
        if collection_rate > 90:
            risk -= 10
        elif collection_rate < 50:
            risk += 20
        
        # Check overdue amount
        overdue = billing_summary.get('overdue', 0)
        if overdue > 5000:
            risk += 15
        
        # Check investment diversification
        if len(investments) > 3:
            risk -= 5  # Good diversification
        
        return max(0, min(100, risk))
    
    def _calculate_operational_risk(self, profiles: List[Dict]) -> float:
        """Calculate operational risk score"""
        risk = 50.0
        
        member_count = len(profiles)
        if member_count < 3:
            risk += 20  # Too few members
        elif member_count > 50:
            risk += 10  # Large group coordination challenges
        elif 5 <= member_count <= 30:
            risk -= 10  # Optimal size
        
        # Check for admin coverage
        admin_count = len([p for p in profiles if p.get('role') in ['founder', 'admin']])
        if admin_count < 2:
            risk += 10  # Single point of failure
        
        return max(0, min(100, risk))
    
    def _calculate_member_risk(self, profiles: List[Dict], billing_summary: Dict) -> float:
        """Calculate member risk score"""
        risk = 50.0
        
        # Check average contribution
        active_members = len([p for p in profiles if p.get('status') == 'active'])
        total_contributed = sum(p.get('total_contributed', 0) for p in profiles)
        
        if active_members > 0:
            avg_contribution = total_contributed / active_members
            if avg_contribution > 500:
                risk -= 15  # Good engagement
            elif avg_contribution < 50:
                risk += 15  # Poor engagement
        
        # Check delinquency
        if billing_summary.get('collection_rate', 0) < 70:
            risk += 20
        
        return max(0, min(100, risk))
    
    def _calculate_compliance_risk(self, profiles: List[Dict]) -> float:
        """Calculate compliance risk score"""
        risk = 40.0
        
        # Check KYC status
        kyc_verified = len([p for p in profiles if p.get('kyc_status') == 'verified'])
        total_members = len(profiles)
        
        if total_members > 0:
            kyc_rate = kyc_verified / total_members
            if kyc_rate > 0.9:
                risk -= 20
            elif kyc_rate < 0.5:
                risk += 25
        
        return max(0, min(100, risk))
    
    def _determine_risk_level(self, overall_risk: float) -> str:
        """Determine risk level from score"""
        if overall_risk < 25:
            return RiskLevel.VERY_LOW.value
        elif overall_risk < 40:
            return RiskLevel.LOW.value
        elif overall_risk < 60:
            return RiskLevel.MODERATE.value
        elif overall_risk < 80:
            return RiskLevel.HIGH.value
        else:
            return RiskLevel.VERY_HIGH.value
    
    def _analyze_risk_factors(
        self,
        financial_risk: float,
        operational_risk: float,
        member_risk: float,
        compliance_risk: float,
        wallets: List[Dict],
        profiles: List[Dict],
        billing_summary: Dict
    ) -> Tuple[List[str], List[str]]:
        """Analyze and categorize risk factors"""
        positive = []
        negative = []
        
        # Financial
        if financial_risk < 40:
            positive.append("Strong financial position with healthy reserves")
        elif financial_risk > 60:
            negative.append("Financial reserves below recommended levels")
        
        # Collection rate
        collection_rate = billing_summary.get('collection_rate', 0)
        if collection_rate > 90:
            positive.append(f"Excellent payment collection rate ({collection_rate:.1f}%)")
        elif collection_rate < 70:
            negative.append(f"Low payment collection rate ({collection_rate:.1f}%)")
        
        # Member engagement
        if member_risk < 40:
            positive.append("High member engagement and contribution rates")
        elif member_risk > 60:
            negative.append("Low member engagement - consider outreach programs")
        
        # KYC compliance
        if compliance_risk < 40:
            positive.append("Strong KYC verification compliance")
        elif compliance_risk > 60:
            negative.append("KYC verification needs improvement")
        
        # Admin coverage
        admin_count = len([p for p in profiles if p.get('role') in ['founder', 'admin']])
        if admin_count >= 2:
            positive.append("Multiple administrators provide operational continuity")
        else:
            negative.append("Single administrator - consider adding backup admin")
        
        return positive, negative
    
    def _generate_recommendations(self, negative_factors: List[str], risk_level: str) -> List[str]:
        """Generate recommendations based on risk factors"""
        recommendations = []
        
        for factor in negative_factors:
            if 'reserves' in factor.lower():
                recommendations.append("Increase contribution rates or reduce payouts to build reserves")
            elif 'collection' in factor.lower():
                recommendations.append("Implement automated payment reminders and late fees")
            elif 'engagement' in factor.lower():
                recommendations.append("Launch member engagement initiatives and communication campaigns")
            elif 'kyc' in factor.lower():
                recommendations.append("Require KYC verification for all active members")
            elif 'administrator' in factor.lower():
                recommendations.append("Designate at least one additional administrator")
        
        if risk_level in [RiskLevel.HIGH.value, RiskLevel.VERY_HIGH.value]:
            recommendations.append("Consider engaging professional risk management consultation")
        
        return recommendations
    
    def _generate_ai_insights(
        self,
        financial_risk: float,
        operational_risk: float,
        member_risk: float,
        compliance_risk: float,
        wallets: List[Dict],
        investments: List[Dict],
        profiles: List[Dict]
    ) -> Dict[str, Any]:
        """Generate AI-powered insights"""
        insights = {
            'summary': '',
            'predictions': [],
            'opportunities': [],
            'trend_analysis': {}
        }
        
        # Generate summary
        total_balance = sum(w['balance'] for w in wallets)
        member_count = len(profiles)
        
        insights['summary'] = (
            f"Foundation has {member_count} members with total funds of ${total_balance:,.2f}. "
            f"Risk profile is {'favorable' if (financial_risk + member_risk) / 2 < 50 else 'requiring attention'}."
        )
        
        # Predictions
        if financial_risk < 40:
            insights['predictions'].append({
                'metric': 'Financial Stability',
                'prediction': 'Likely to maintain stable operations for next 12 months',
                'confidence': 0.85
            })
        
        if member_risk < 50:
            insights['predictions'].append({
                'metric': 'Member Retention',
                'prediction': 'Expected retention rate above 85% in next quarter',
                'confidence': 0.75
            })
        
        # Opportunities
        if total_balance > 10000 and len(investments) < 3:
            insights['opportunities'].append(
                "Consider diversifying into additional investment products for better returns"
            )
        
        if member_count > 10 and member_count < 30:
            insights['opportunities'].append(
                "Optimal size for growth - consider targeted recruitment campaigns"
            )
        
        # Trend analysis
        insights['trend_analysis'] = {
            'financial_trend': 'stable' if financial_risk < 50 else 'needs_attention',
            'member_trend': 'growing' if member_count > 5 else 'early_stage',
            'engagement_trend': 'healthy' if member_risk < 50 else 'declining'
        }
        
        return insights
    
    def get_latest_risk_assessment(self, foundation_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent risk assessment"""
        assessments = [a for a in self._risk_assessments.values() 
                       if a.foundation_id == foundation_id]
        
        if not assessments:
            return None
        
        # Sort by date and get latest
        assessments.sort(key=lambda x: x.assessment_date, reverse=True)
        return assessments[0].to_dict()
    
    # ========== BI REPORTS ==========
    
    def generate_bi_report(
        self,
        foundation_id: str,
        report_type: str,
        period_start: str,
        period_end: str
    ) -> BIReport:
        """Generate a comprehensive BI report"""
        # Gather all data
        wallets = self.get_foundation_wallets(foundation_id)
        profiles = self.get_all_member_profiles(foundation_id, include_sensitive=True)
        investments = self.get_foundation_investments(foundation_id)
        investment_returns = self.calculate_investment_returns(foundation_id)
        billing_summary = self.get_foundation_billing_summary(foundation_id)
        ledger_entries = self.get_ledger_entries(
            foundation_id, 
            start_date=period_start, 
            end_date=period_end,
            limit=1000
        )
        
        # Calculate metrics
        metrics = {
            'members': {
                'total': len(profiles),
                'active': len([p for p in profiles if p.get('status') == 'active']),
                'new_this_period': len([e for e in ledger_entries 
                                         if e['entry_type'] == LedgerEntryType.MEMBER_JOINED.value])
            },
            'financial': {
                'total_balance': sum(w['balance'] for w in wallets),
                'operating_balance': next((w['balance'] for w in wallets 
                                           if w['wallet_type'] == WalletType.OPERATING.value), 0),
                'reserve_balance': next((w['balance'] for w in wallets 
                                          if w['wallet_type'] == WalletType.RESERVE.value), 0),
                'investment_balance': next((w['balance'] for w in wallets 
                                             if w['wallet_type'] == WalletType.INVESTMENT.value), 0)
            },
            'contributions': {
                'total_this_period': sum(e['data'].get('amount', 0) for e in ledger_entries 
                                          if e['entry_type'] == LedgerEntryType.CONTRIBUTION_RECEIVED.value),
                'contribution_count': len([e for e in ledger_entries 
                                           if e['entry_type'] == LedgerEntryType.CONTRIBUTION_RECEIVED.value])
            },
            'investments': investment_returns,
            'billing': billing_summary,
            'activity': {
                'total_transactions': len(ledger_entries),
                'claims_submitted': len([e for e in ledger_entries 
                                          if e['entry_type'] == LedgerEntryType.CLAIM_SUBMITTED.value]),
                'votes_created': len([e for e in ledger_entries 
                                       if e['entry_type'] == LedgerEntryType.VOTE_CREATED.value])
            }
        }
        
        # Generate insights
        insights = []
        alerts = []
        
        # Financial insights
        total_balance = metrics['financial']['total_balance']
        if total_balance > 50000:
            insights.append(f"Strong financial position with ${total_balance:,.2f} in reserves")
        elif total_balance < 5000:
            alerts.append(f"Low reserves (${total_balance:,.2f}) - consider increasing contributions")
        
        # Member insights
        if metrics['members']['new_this_period'] > 0:
            insights.append(f"Added {metrics['members']['new_this_period']} new members this period")
        
        # Contribution insights
        contribution_total = metrics['contributions']['total_this_period']
        if contribution_total > 0:
            insights.append(f"Collected ${contribution_total:,.2f} in contributions this period")
        
        # Investment insights
        if investment_returns['total_returns'] > 0:
            insights.append(
                f"Investments generated ${investment_returns['total_returns']:,.2f} in returns "
                f"({investment_returns['return_percentage']:.1f}% ROI)"
            )
        
        # Billing alerts
        if billing_summary['overdue'] > 0:
            alerts.append(f"${billing_summary['overdue']:,.2f} in overdue payments needs attention")
        
        now = now_iso()
        
        report = BIReport(
            id=generate_id("BI"),
            foundation_id=foundation_id,
            report_type=report_type,
            period_start=period_start,
            period_end=period_end,
            metrics=metrics,
            insights=insights,
            alerts=alerts,
            generated_at=now
        )
        
        self._bi_reports[report.id] = report
        
        # Record on ledger
        self.create_ledger_entry(
            foundation_id=foundation_id,
            entry_type=LedgerEntryType.BI_REPORT_GENERATED.value,
            actor_id='system',
            actor_type='system',
            data={
                'report_id': report.id,
                'report_type': report_type
            }
        )
        
        return report
    
    def get_bi_reports(
        self,
        foundation_id: str,
        report_type: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get BI reports for a foundation"""
        reports = []
        for report in self._bi_reports.values():
            if report.foundation_id == foundation_id:
                if report_type is None or report.report_type == report_type:
                    reports.append(report.to_dict())
        
        reports.sort(key=lambda x: x['generated_at'], reverse=True)
        return reports[:limit]
    
    # ========== DASHBOARD DATA ==========
    
    def get_admin_dashboard_data(self, foundation_id: str) -> Dict[str, Any]:
        """Get comprehensive data for admin dashboard"""
        wallets = self.get_foundation_wallets(foundation_id)
        profiles = self.get_all_member_profiles(foundation_id, include_sensitive=True)
        investments = self.get_foundation_investments(foundation_id)
        investment_returns = self.calculate_investment_returns(foundation_id)
        billing_summary = self.get_foundation_billing_summary(foundation_id)
        risk_assessment = self.get_latest_risk_assessment(foundation_id)
        nfts = self.get_foundation_nfts(foundation_id)
        recent_activity = self.get_ledger_entries(foundation_id, limit=50)
        
        # Calculate totals
        total_contributions = sum(p.get('total_contributed', 0) for p in profiles)
        total_balance = sum(w['balance'] for w in wallets)
        
        return {
            'summary': {
                'total_members': len(profiles),
                'active_members': len([p for p in profiles if p.get('status') == 'active']),
                'total_balance': round(total_balance, 2),
                'total_contributions': round(total_contributions, 2),
                'total_investments': round(investment_returns.get('total_current_value', 0), 2),
                'investment_returns': round(investment_returns.get('total_returns', 0), 2),
                'collection_rate': billing_summary.get('collection_rate', 0),
                'risk_level': risk_assessment.get('risk_level', 'unknown') if risk_assessment else 'not_assessed'
            },
            'wallets': wallets,
            'members': profiles,
            'investments': investments,
            'investment_summary': investment_returns,
            'billing': billing_summary,
            'risk_assessment': risk_assessment,
            'nfts': {
                'total': len(nfts),
                'by_type': {
                    'membership': len([n for n in nfts if n['token_type'] == 'membership']),
                    'contribution': len([n for n in nfts if n['token_type'] == 'contribution']),
                    'achievement': len([n for n in nfts if n['token_type'] == 'achievement'])
                }
            },
            'recent_activity': recent_activity[:20],
            'generated_at': now_iso()
        }


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_ledger_service: Optional[FoundationLedgerService] = None


def get_foundation_ledger_service() -> FoundationLedgerService:
    """Get or create the foundation ledger service singleton"""
    global _ledger_service
    if _ledger_service is None:
        _ledger_service = FoundationLedgerService()
    return _ledger_service


def reset_foundation_ledger_service() -> None:
    """Reset the foundation ledger service (for testing)"""
    global _ledger_service
    _ledger_service = None


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'LedgerEntryType',
    'WalletType',
    'InvestmentType',
    'RiskLevel',
    'LedgerEntry',
    'MemberProfile',
    'FoundationWallet',
    'Investment',
    'Bill',
    'NFTRecord',
    'RiskAssessment',
    'BIReport',
    'FoundationLedgerService',
    'get_foundation_ledger_service',
    'reset_foundation_ledger_service'
]
