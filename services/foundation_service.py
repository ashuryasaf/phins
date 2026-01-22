"""
PHINS Community Foundation Service
Business logic for community foundation (mutual aid) groups

Features:
- Foundation CRUD operations
- Membership management
- Fund management
- Contribution tracking
- Voting system
- Claim processing
- Activity logging
- Data persistence (survives restarts)
- Billing integration (deposits appear on dashboard)
- Automatic backups
"""

from __future__ import annotations

import json
import secrets
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
import uuid

logger = logging.getLogger('phins.foundation')

# Import persistence and billing integration services
try:
    from services.foundation_persistence_service import (
        get_persistence_service,
        FoundationPersistenceService
    )
    PERSISTENCE_AVAILABLE = True
except ImportError:
    PERSISTENCE_AVAILABLE = False
    logger.warning("Foundation persistence service not available")

try:
    from services.ledger_backup_service import (
        get_backup_service,
        LedgerBackupService
    )
    BACKUP_AVAILABLE = True
except ImportError:
    BACKUP_AVAILABLE = False
    logger.warning("Ledger backup service not available")

try:
    from services.foundation_billing_integration import (
        get_billing_integration,
        init_billing_integration,
        FoundationBillingIntegration
    )
    BILLING_INTEGRATION_AVAILABLE = True
except ImportError:
    BILLING_INTEGRATION_AVAILABLE = False
    logger.warning("Foundation billing integration not available")


# ============================================================================
# ENUMS & CONSTANTS
# ============================================================================

class FoundationType(str, Enum):
    FAMILY = "family"
    WORK = "work"
    NEIGHBORHOOD = "neighborhood"
    FRIENDS = "friends"
    ENTREPRENEURS = "entrepreneurs"
    BUSINESS_VENTURE = "business_venture"
    PROFESSIONAL = "professional"
    CUSTOMER_CLUB = "customer_club"
    CUSTOM = "custom"


class FoundationStatus(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REJECTED = "rejected"
    DISSOLVED = "dissolved"


class PipelineStage(str, Enum):
    CREATED = "created"
    PENDING_ACTIVATION = "pending_activation"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    ACTIVE = "active"
    REJECTED = "rejected"
    SUSPENDED = "suspended"
    DISSOLVED = "dissolved"


# Default rules for each foundation type
DEFAULT_RULES = {
    "family": {
        "max_members": 15,
        "contribution_frequency": "monthly",
        "min_contribution": 25.00,
        "auto_approve_threshold": 200.00,
        "reserve_percentage": 15.0,
        "vote_threshold": 0.50,
        "founder_veto": True
    },
    "work": {
        "max_members": 100,
        "contribution_frequency": "monthly",
        "min_contribution": 50.00,
        "auto_approve_threshold": 500.00,
        "reserve_percentage": 20.0,
        "vote_threshold": 0.50,
        "founder_veto": True
    },
    "neighborhood": {
        "max_members": 50,
        "contribution_frequency": "monthly",
        "min_contribution": 30.00,
        "auto_approve_threshold": 300.00,
        "reserve_percentage": 20.0,
        "vote_threshold": 0.50,
        "founder_veto": False
    },
    "friends": {
        "max_members": 35,
        "contribution_frequency": "monthly",
        "min_contribution": 25.00,
        "auto_approve_threshold": 250.00,
        "reserve_percentage": 15.0,
        "vote_threshold": 0.50,
        "founder_veto": False
    },
    "entrepreneurs": {
        "max_members": 50,
        "contribution_frequency": "monthly",
        "min_contribution": 100.00,
        "auto_approve_threshold": 1000.00,
        "reserve_percentage": 25.0,
        "vote_threshold": 0.66,
        "founder_veto": True
    },
    "business_venture": {
        "max_members": 20,
        "contribution_frequency": "quarterly",
        "min_contribution": 500.00,
        "auto_approve_threshold": 2000.00,
        "reserve_percentage": 30.0,
        "vote_threshold": 0.75,
        "founder_veto": True
    },
    "professional": {
        "max_members": 0,  # Unlimited
        "contribution_frequency": "monthly",
        "min_contribution": 75.00,
        "auto_approve_threshold": 750.00,
        "reserve_percentage": 20.0,
        "vote_threshold": 0.50,
        "founder_veto": False
    },
    "customer_club": {
        "max_members": 0,  # Unlimited
        "contribution_frequency": "monthly",
        "min_contribution": 10.00,
        "auto_approve_threshold": 100.00,
        "reserve_percentage": 10.0,
        "vote_threshold": 0.50,
        "founder_veto": True
    },
    "custom": {
        "max_members": 35,
        "contribution_frequency": "monthly",
        "min_contribution": 25.00,
        "auto_approve_threshold": 250.00,
        "reserve_percentage": 20.0,
        "vote_threshold": 0.50,
        "founder_veto": True
    }
}


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class FoundationCreateRequest:
    """Request to create a new foundation"""
    name: str
    foundation_type: str
    description: str = ""
    founder_id: str = ""
    founder_type: str = "customer"  # customer or supplier
    max_members: Optional[int] = None
    custom_rules: Optional[Dict[str, Any]] = None


@dataclass
class FoundationResult:
    """Result of foundation operations"""
    success: bool
    foundation_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'foundation_id': self.foundation_id,
            'error_code': self.error_code,
            'error_message': self.error_message,
            'data': self.data
        }


@dataclass
class MembershipResult:
    """Result of membership operations"""
    success: bool
    member_id: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'member_id': self.member_id,
            'error_code': self.error_code,
            'error_message': self.error_message,
            'data': self.data
        }


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def generate_id(prefix: str) -> str:
    """Generate a unique ID with prefix"""
    unique_part = uuid.uuid4().hex[:8].upper()
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d')
    return f"{prefix}-{timestamp}-{unique_part}"


def generate_invitation_code() -> str:
    """Generate a unique invitation code"""
    return f"FND-{secrets.token_hex(6).upper()}"


def get_default_rules(foundation_type: str) -> Dict[str, Any]:
    """Get default rules for a foundation type"""
    return DEFAULT_RULES.get(foundation_type, DEFAULT_RULES["custom"]).copy()


# ============================================================================
# FOUNDATION SERVICE (In-Memory Implementation)
# ============================================================================

class FoundationService:
    """
    Community Foundation Service
    
    Manages foundation lifecycle, membership, funds, contributions,
    voting, and claims.
    
    Enhanced features:
    - Data persistence (survives server restarts)
    - Automatic backups before mutations
    - Billing integration for dashboard visibility
    """
    
    def __init__(
        self,
        enable_persistence: bool = True,
        enable_backup: bool = True,
        enable_billing_integration: bool = True,
        data_dir: str = None,
        billing_records: Dict = None,
        transaction_ledger: Dict = None,
        bills: Dict = None
    ):
        """
        Initialize the foundation service.
        
        Args:
            enable_persistence: Enable data persistence to disk
            enable_backup: Enable automatic backups
            enable_billing_integration: Enable billing integration for dashboard
            data_dir: Directory for data storage
            billing_records: Optional billing records dict (for billing integration)
            transaction_ledger: Optional transaction ledger dict
            bills: Optional bills dict (for BillingService compatibility)
        """
        # In-memory storage
        self._foundations: Dict[str, Dict[str, Any]] = {}
        self._members: Dict[str, Dict[str, Any]] = {}
        self._funds: Dict[str, Dict[str, Any]] = {}
        self._contributions: Dict[str, Dict[str, Any]] = {}
        self._invitations: Dict[str, Dict[str, Any]] = {}
        self._votes: Dict[str, Dict[str, Any]] = {}
        self._vote_casts: Dict[str, Dict[str, Any]] = {}
        self._claims: Dict[str, Dict[str, Any]] = {}
        self._activities: Dict[str, Dict[str, Any]] = {}
        # Use 'is None' check to preserve reference to caller's dict (even if empty)
        self._billing_integration_records: Dict[str, Dict[str, Any]] = billing_records if billing_records is not None else {}
        
        # Service references
        self._persistence_service: Optional[FoundationPersistenceService] = None
        self._backup_service: Optional[LedgerBackupService] = None
        self._billing_integration: Optional[FoundationBillingIntegration] = None
        
        # Configuration
        self._persistence_enabled = enable_persistence and PERSISTENCE_AVAILABLE
        self._backup_enabled = enable_backup and BACKUP_AVAILABLE
        self._billing_enabled = enable_billing_integration and BILLING_INTEGRATION_AVAILABLE
        
        # Initialize services
        if self._persistence_enabled:
            try:
                self._persistence_service = get_persistence_service(data_dir)
                # Load existing data from disk
                self._load_from_persistence()
                logger.info("Foundation persistence enabled - data loaded from disk")
            except Exception as e:
                logger.error(f"Error initializing persistence: {e}")
                self._persistence_enabled = False
        
        if self._backup_enabled:
            try:
                self._backup_service = get_backup_service()
                logger.info("Foundation backup enabled")
            except Exception as e:
                logger.error(f"Error initializing backup service: {e}")
                self._backup_enabled = False
        
        if self._billing_enabled:
            try:
                # Use init_billing_integration to ensure we get a fresh instance
                # with the specified dictionaries for proper data sharing
                # Use 'is not None' check to preserve references to caller's dicts
                self._billing_integration = init_billing_integration(
                    billing_records=self._billing_integration_records,
                    transaction_ledger=transaction_ledger if transaction_ledger is not None else {},
                    bills=bills if bills is not None else {}
                )
                logger.info("Foundation billing integration enabled")
            except Exception as e:
                logger.error(f"Error initializing billing integration: {e}")
                self._billing_enabled = False
    
    def _load_from_persistence(self) -> None:
        """Load all data from persistence storage."""
        if not self._persistence_service:
            return
        
        try:
            data = self._persistence_service.load_all()
            
            self._foundations = data.get('foundations', {})
            self._members = data.get('members', {})
            self._funds = data.get('funds', {})
            self._contributions = data.get('contributions', {})
            self._invitations = data.get('invitations', {})
            self._votes = data.get('votes', {})
            self._vote_casts = data.get('vote_casts', {})
            self._claims = data.get('claims', {})
            self._activities = data.get('activities', {})
            self._billing_integration_records = data.get('billing_integration', {})
            
            logger.info(f"Loaded {len(self._foundations)} foundations from persistence")
            
        except Exception as e:
            logger.error(f"Error loading from persistence: {e}")
    
    def _persist(self, create_backup: bool = False, backup_label: str = None) -> None:
        """
        Persist all data to disk.
        
        Args:
            create_backup: Create a backup before persisting
            backup_label: Label for the backup
        """
        if not self._persistence_enabled or not self._persistence_service:
            return
        
        try:
            data = {
                'foundations': self._foundations,
                'members': self._members,
                'funds': self._funds,
                'contributions': self._contributions,
                'invitations': self._invitations,
                'votes': self._votes,
                'vote_casts': self._vote_casts,
                'claims': self._claims,
                'activities': self._activities,
                'billing_integration': self._billing_integration_records
            }
            
            # Create backup if requested
            if create_backup and self._backup_enabled and self._backup_service:
                self._backup_service.backup_foundation_ledger(data, backup_label)
            
            # Persist to disk
            self._persistence_service.save_all(data)
            
        except Exception as e:
            logger.error(f"Error persisting data: {e}")
    
    def create_backup(self, label: str = None) -> Optional[str]:
        """
        Create a manual backup of all foundation data.
        
        Args:
            label: Optional label for the backup
            
        Returns:
            Backup ID if successful, None otherwise
        """
        if not self._backup_enabled or not self._backup_service:
            return None
        
        try:
            data = {
                'foundations': self._foundations,
                'members': self._members,
                'funds': self._funds,
                'contributions': self._contributions,
                'invitations': self._invitations,
                'votes': self._votes,
                'vote_casts': self._vote_casts,
                'claims': self._claims,
                'activities': self._activities
            }
            
            return self._backup_service.backup_foundation_ledger(data, label)
            
        except Exception as e:
            logger.error(f"Error creating backup: {e}")
            return None
    
    def get_billing_dashboard_data(self, customer_id: str) -> Dict[str, Any]:
        """
        Get foundation billing data for customer dashboard.
        
        Args:
            customer_id: Customer ID
            
        Returns:
            Dashboard billing data
        """
        if self._billing_enabled and self._billing_integration:
            return self._billing_integration.get_dashboard_billing_data(customer_id)
        
        return {
            'customer_id': customer_id,
            'foundation_billing': {
                'summary': {
                    'total_contributed': 0,
                    'total_received': 0,
                    'net_position': 0,
                    'active_foundations': 0
                },
                'recent_transactions': [],
                'transaction_count': 0
            }
        }
    
    # ========== FOUNDATION CRUD ==========
    
    def create_foundation(self, request: FoundationCreateRequest) -> FoundationResult:
        """Create a new community foundation"""
        # Validate
        if not request.name or len(request.name) < 3:
            return FoundationResult(
                success=False,
                error_code="INVALID_NAME",
                error_message="Foundation name must be at least 3 characters"
            )
        
        if request.foundation_type not in [t.value for t in FoundationType]:
            return FoundationResult(
                success=False,
                error_code="INVALID_TYPE",
                error_message=f"Invalid foundation type: {request.foundation_type}"
            )
        
        if not request.founder_id:
            return FoundationResult(
                success=False,
                error_code="MISSING_FOUNDER",
                error_message="Founder ID is required"
            )
        
        # Get default rules
        default_rules = get_default_rules(request.foundation_type)
        
        # Merge custom rules
        settings = {
            "base_rules": {
                "foundation_type": request.foundation_type,
                "max_members": request.max_members or default_rules["max_members"],
                "founder_veto": default_rules["founder_veto"],
                "dissolution_threshold": 0.75,
                "min_members_to_operate": 2
            },
            "contribution_rules": {
                "frequency": default_rules["contribution_frequency"],
                "min_amount": default_rules["min_contribution"],
                "max_amount": None,
                "grace_period_days": 7,
                "late_fee_percentage": 5.0
            },
            "claim_rules": {
                "waiting_period_days": 30,
                "auto_approve_threshold": default_rules["auto_approve_threshold"],
                "max_claim_percentage": 25.0,
                "requires_documentation": True,
                "vote_threshold": default_rules["vote_threshold"]
            },
            "fund_rules": {
                "min_reserve_percentage": default_rules["reserve_percentage"],
                "max_single_payout_percentage": 25.0,
                "investment_allowed": False
            },
            "voting_rules": {
                "majority_threshold": default_rules["vote_threshold"],
                "supermajority_threshold": 0.66,
                "vote_duration_days": 7,
                "quorum_percentage": 0.50
            },
            "membership_rules": {
                "auto_approve_members": False,
                "require_invitation": True,
                "new_member_vote_required": False,
                "removal_vote_threshold": 0.66
            }
        }
        
        # Apply custom rules
        if request.custom_rules:
            for category, rules in request.custom_rules.items():
                if category in settings and isinstance(rules, dict):
                    settings[category].update(rules)
        
        # Create foundation
        foundation_id = generate_id("FND")
        max_members = settings["base_rules"]["max_members"]
        is_unlimited = max_members == 0
        
        foundation = {
            'id': foundation_id,
            'name': request.name,
            'foundation_type': request.foundation_type,
            'description': request.description,
            'founder_id': request.founder_id,
            'founder_type': request.founder_type,
            'status': 'draft',
            'pipeline_stage': 'created',
            'pipeline_history': [{
                'stage': 'created',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'actor': request.founder_id,
                'notes': 'Foundation created'
            }],
            'max_members': max_members if not is_unlimited else 999999,
            'is_unlimited': is_unlimited,
            'current_members': 1,  # Founder counts
            'total_fund_balance': 0.0,
            'reserve_percentage': settings["fund_rules"]["min_reserve_percentage"],
            'currency': 'USD',
            'settings': settings,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'activated_at': None,
            'rejected_at': None,
            'rejection_reason': None,
            'dissolved_at': None,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        self._foundations[foundation_id] = foundation
        
        # Add founder as first member
        member_id = generate_id("MEM")
        founder_member = {
            'id': member_id,
            'foundation_id': foundation_id,
            'member_id': request.founder_id,
            'member_type': request.founder_type,
            'role': 'founder',
            'status': 'active',
            'contribution_amount': 0.0,
            'total_contributed': 0.0,
            'last_contribution': None,
            'voting_weight': 1.0,
            'display_name': 'Founder',
            'photo_url': None,
            'email': None,
            'phone': None,
            'is_visible': True,
            'joined_at': datetime.now(timezone.utc).isoformat(),
            'invited_at': None,
            'approved_at': datetime.now(timezone.utc).isoformat(),
            'removed_at': None,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        self._members[member_id] = founder_member
        
        # Create default funds
        self._create_default_funds(foundation_id)
        
        # Log activity
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="foundation_created",
            actor_id=request.founder_id,
            details={"name": request.name, "type": request.foundation_type}
        )
        
        logger.info(f"Foundation created: {foundation_id} by {request.founder_id}")
        
        # Persist data to disk
        self._persist(create_backup=True, backup_label=f"foundation_created_{foundation_id[:12]}")
        
        return FoundationResult(
            success=True,
            foundation_id=foundation_id,
            data=foundation
        )
    
    def get_foundation(self, foundation_id: str) -> Optional[Dict[str, Any]]:
        """Get foundation by ID"""
        return self._foundations.get(foundation_id)
    
    def list_foundations(
        self,
        member_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """List foundations, optionally filtered by member or status"""
        foundations = list(self._foundations.values())
        
        # Filter by member
        if member_id:
            member_foundation_ids = set()
            for member in self._members.values():
                if member['member_id'] == member_id and member['status'] in ['active', 'pending']:
                    member_foundation_ids.add(member['foundation_id'])
            foundations = [f for f in foundations if f['id'] in member_foundation_ids]
        
        # Filter by status
        if status:
            foundations = [f for f in foundations if f['status'] == status]
        
        # Sort by created_at descending
        foundations.sort(key=lambda x: x['created_at'], reverse=True)
        
        # Paginate
        return foundations[offset:offset + limit]
    
    def activate_foundation(self, foundation_id: str, actor_id: str, is_admin: bool = False) -> FoundationResult:
        """Activate a draft or suspended foundation"""
        foundation = self._foundations.get(foundation_id)
        
        if not foundation:
            return FoundationResult(
                success=False,
                error_code="NOT_FOUND",
                error_message="Foundation not found"
            )
        
        # Allow admin to activate any foundation with draft, suspended, or pending_review status
        allowed_statuses = ['draft', 'suspended', 'pending_review']
        if foundation['status'] not in allowed_statuses:
            return FoundationResult(
                success=False,
                error_code="INVALID_STATUS",
                error_message=f"Cannot activate foundation with status: {foundation['status']}"
            )
        
        # Check if actor is founder or admin
        if not is_admin and foundation['founder_id'] != actor_id:
            return FoundationResult(
                success=False,
                error_code="UNAUTHORIZED",
                error_message="Only founder or admin can activate the foundation"
            )
        
        now = datetime.now(timezone.utc).isoformat()
        foundation['status'] = 'active'
        foundation['pipeline_stage'] = 'active'
        foundation['activated_at'] = now
        foundation['updated_at'] = now
        
        # Add to pipeline history
        if 'pipeline_history' not in foundation:
            foundation['pipeline_history'] = []
        foundation['pipeline_history'].append({
            'stage': 'active',
            'timestamp': now,
            'actor': actor_id,
            'notes': 'Foundation activated' + (' by admin' if is_admin else '')
        })
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="foundation_activated",
            actor_id=actor_id,
            details={"activated_by_admin": is_admin}
        )
        
        return FoundationResult(
            success=True,
            foundation_id=foundation_id,
            data=foundation
        )
    
    def reject_foundation(self, foundation_id: str, actor_id: str, reason: str = "") -> FoundationResult:
        """Reject a foundation (admin only)"""
        foundation = self._foundations.get(foundation_id)
        
        if not foundation:
            return FoundationResult(
                success=False,
                error_code="NOT_FOUND",
                error_message="Foundation not found"
            )
        
        # Can reject draft or pending_review foundations
        if foundation['status'] not in ['draft', 'pending_review']:
            return FoundationResult(
                success=False,
                error_code="INVALID_STATUS",
                error_message=f"Cannot reject foundation with status: {foundation['status']}"
            )
        
        now = datetime.now(timezone.utc).isoformat()
        foundation['status'] = 'rejected'
        foundation['pipeline_stage'] = 'rejected'
        foundation['rejected_at'] = now
        foundation['rejection_reason'] = reason
        foundation['updated_at'] = now
        
        # Add to pipeline history
        if 'pipeline_history' not in foundation:
            foundation['pipeline_history'] = []
        foundation['pipeline_history'].append({
            'stage': 'rejected',
            'timestamp': now,
            'actor': actor_id,
            'notes': f'Foundation rejected: {reason}' if reason else 'Foundation rejected'
        })
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="foundation_rejected",
            actor_id=actor_id,
            details={"reason": reason}
        )
        
        return FoundationResult(
            success=True,
            foundation_id=foundation_id,
            data=foundation
        )
    
    def process_pipeline(self, foundation_id: str, actor_id: str, target_stage: str, notes: str = "") -> FoundationResult:
        """Process a foundation through the pipeline workflow"""
        foundation = self._foundations.get(foundation_id)
        
        if not foundation:
            return FoundationResult(
                success=False,
                error_code="NOT_FOUND",
                error_message="Foundation not found"
            )
        
        valid_transitions = {
            'created': ['pending_activation', 'in_review', 'active', 'rejected'],
            'pending_activation': ['in_review', 'active', 'rejected'],
            'in_review': ['approved', 'active', 'rejected'],
            'approved': ['active'],
            'active': ['suspended', 'dissolved'],
            'suspended': ['active', 'dissolved'],
            'rejected': ['in_review', 'pending_activation'],  # Allow reconsideration
            'dissolved': []  # Terminal state
        }
        
        current_stage = foundation.get('pipeline_stage', 'created')
        if target_stage not in valid_transitions.get(current_stage, []):
            return FoundationResult(
                success=False,
                error_code="INVALID_TRANSITION",
                error_message=f"Cannot transition from {current_stage} to {target_stage}"
            )
        
        now = datetime.now(timezone.utc).isoformat()
        
        # Update status based on pipeline stage
        status_mapping = {
            'pending_activation': 'pending_review',
            'in_review': 'pending_review',
            'approved': 'active',
            'active': 'active',
            'suspended': 'suspended',
            'rejected': 'rejected',
            'dissolved': 'dissolved'
        }
        
        foundation['pipeline_stage'] = target_stage
        foundation['status'] = status_mapping.get(target_stage, foundation['status'])
        foundation['updated_at'] = now
        
        # Update specific timestamps based on transition
        if target_stage == 'active' and not foundation.get('activated_at'):
            foundation['activated_at'] = now
        elif target_stage == 'rejected':
            foundation['rejected_at'] = now
        elif target_stage == 'dissolved':
            foundation['dissolved_at'] = now
        
        # Add to pipeline history
        if 'pipeline_history' not in foundation:
            foundation['pipeline_history'] = []
        foundation['pipeline_history'].append({
            'stage': target_stage,
            'timestamp': now,
            'actor': actor_id,
            'notes': notes or f'Transitioned to {target_stage}'
        })
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="pipeline_processed",
            actor_id=actor_id,
            details={
                "from_stage": current_stage,
                "to_stage": target_stage,
                "notes": notes
            }
        )
        
        return FoundationResult(
            success=True,
            foundation_id=foundation_id,
            data=foundation
        )
    
    def dissolve_foundation(
        self,
        foundation_id: str,
        actor_id: str,
        reason: str = ""
    ) -> FoundationResult:
        """Dissolve a foundation"""
        foundation = self._foundations.get(foundation_id)
        
        if not foundation:
            return FoundationResult(
                success=False,
                error_code="NOT_FOUND",
                error_message="Foundation not found"
            )
        
        if foundation['founder_id'] != actor_id:
            return FoundationResult(
                success=False,
                error_code="UNAUTHORIZED",
                error_message="Only founder can dissolve the foundation"
            )
        
        foundation['status'] = 'dissolved'
        foundation['dissolved_at'] = datetime.now(timezone.utc).isoformat()
        foundation['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="foundation_dissolved",
            actor_id=actor_id,
            details={"reason": reason}
        )
        
        return FoundationResult(
            success=True,
            foundation_id=foundation_id,
            data=foundation
        )
    
    # ========== MEMBERSHIP ==========
    
    def create_invitation(
        self,
        foundation_id: str,
        invited_by: str,
        invited_email: Optional[str] = None,
        max_uses: int = 1,
        expires_days: int = 7,
        notes: str = ""
    ) -> Dict[str, Any]:
        """Create an invitation to join a foundation"""
        foundation = self._foundations.get(foundation_id)
        
        if not foundation:
            return {"success": False, "error": "Foundation not found"}
        
        # Allow invitations for draft, pending_review, and active foundations
        # This enables founders to invite members while setting up the community
        allowed_statuses = ['draft', 'pending_review', 'active']
        if foundation['status'] not in allowed_statuses:
            return {"success": False, "error": f"Cannot create invitations for {foundation['status']} foundations"}
        
        # Check if inviter is member with invite rights
        inviter_member = self._get_member_by_user(foundation_id, invited_by)
        if not inviter_member or inviter_member['role'] not in ['founder', 'admin']:
            return {"success": False, "error": "You don't have permission to invite members"}
        
        # Check member limit
        if not foundation['is_unlimited'] and foundation['current_members'] >= foundation['max_members']:
            return {"success": False, "error": "Foundation has reached maximum members"}
        
        # Create invitation
        invitation_id = generate_id("INV")
        code = generate_invitation_code()
        
        invitation = {
            'id': invitation_id,
            'foundation_id': foundation_id,
            'code': code,
            'invited_email': invited_email,
            'invited_by': invited_by,
            'status': 'pending',
            'max_uses': max_uses,
            'used_count': 0,
            'notes': notes,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'expires_at': (datetime.now(timezone.utc) + timedelta(days=expires_days)).isoformat(),
            'used_at': None
        }
        
        self._invitations[invitation_id] = invitation
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="invitation_created",
            actor_id=invited_by,
            details={"invitation_id": invitation_id, "email": invited_email}
        )
        
        return {
            "success": True,
            "invitation_id": invitation_id,
            "code": code,
            "foundation_name": foundation['name']
        }
    
    def validate_invitation(self, code: str) -> Dict[str, Any]:
        """Validate an invitation code"""
        invitation = None
        for inv in self._invitations.values():
            if inv['code'] == code:
                invitation = inv
                break
        
        if not invitation:
            return {"valid": False, "error": "Invalid invitation code"}
        
        # Check status
        if invitation['status'] != 'pending':
            return {"valid": False, "error": f"Invitation is {invitation['status']}"}
        
        # Check expiry
        expires_at = datetime.fromisoformat(invitation['expires_at'].replace('Z', '+00:00'))
        if datetime.now(timezone.utc) > expires_at:
            invitation['status'] = 'expired'
            return {"valid": False, "error": "Invitation has expired"}
        
        # Check usage limit
        if invitation['used_count'] >= invitation['max_uses']:
            return {"valid": False, "error": "Invitation has reached maximum uses"}
        
        # Get foundation info
        foundation = self._foundations.get(invitation['foundation_id'])
        
        return {
            "valid": True,
            "invitation_id": invitation['id'],
            "foundation_id": invitation['foundation_id'],
            "foundation_name": foundation['name'] if foundation else None,
            "foundation_type": foundation['foundation_type'] if foundation else None
        }
    
    def join_foundation(
        self,
        code: str,
        member_id: str,
        member_type: str = "customer",
        display_name: Optional[str] = None
    ) -> MembershipResult:
        """Join a foundation using invitation code"""
        # Validate code
        validation = self.validate_invitation(code)
        if not validation.get("valid"):
            return MembershipResult(
                success=False,
                error_code="INVALID_CODE",
                error_message=validation.get("error", "Invalid code")
            )
        
        invitation = None
        for inv in self._invitations.values():
            if inv['code'] == code:
                invitation = inv
                break
        
        if not invitation:
            return MembershipResult(
                success=False,
                error_code="INVALID_CODE",
                error_message="Invitation not found"
            )
        
        foundation_id = invitation['foundation_id']
        foundation = self._foundations.get(foundation_id)
        
        if not foundation:
            return MembershipResult(
                success=False,
                error_code="NOT_FOUND",
                error_message="Foundation not found"
            )
        
        # Check foundation status - allow joining draft, pending_review, and active foundations
        allowed_statuses = ['draft', 'pending_review', 'active']
        if foundation['status'] not in allowed_statuses:
            return MembershipResult(
                success=False,
                error_code="INVALID_STATUS",
                error_message=f"Cannot join a {foundation['status']} foundation"
            )
        
        # Check if already a member
        existing = self._get_member_by_user(foundation_id, member_id)
        if existing and existing['status'] in ['active', 'pending']:
            return MembershipResult(
                success=False,
                error_code="ALREADY_MEMBER",
                error_message="You are already a member of this foundation"
            )
        
        # Get membership rules
        settings = foundation.get('settings', {})
        auto_approve = settings.get('membership_rules', {}).get('auto_approve_members', False)
        
        # Create membership
        new_member_id = generate_id("MEM")
        status = 'active' if auto_approve else 'pending'
        
        member = {
            'id': new_member_id,
            'foundation_id': foundation_id,
            'member_id': member_id,
            'member_type': member_type,
            'role': 'member',
            'status': status,
            'contribution_amount': 0.0,
            'total_contributed': 0.0,
            'last_contribution': None,
            'voting_weight': 1.0,
            'display_name': display_name or f"Member {foundation['current_members'] + 1}",
            'photo_url': None,
            'email': None,
            'phone': None,
            'is_visible': True,
            'joined_at': datetime.now(timezone.utc).isoformat(),
            'invited_at': invitation['created_at'],
            'approved_at': datetime.now(timezone.utc).isoformat() if auto_approve else None,
            'removed_at': None,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        self._members[new_member_id] = member
        
        # Update invitation
        invitation['used_count'] += 1
        invitation['used_at'] = datetime.now(timezone.utc).isoformat()
        if invitation['used_count'] >= invitation['max_uses']:
            invitation['status'] = 'accepted'
        
        # Update foundation member count
        if status == 'active':
            foundation['current_members'] += 1
            foundation['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="member_joined",
            actor_id=member_id,
            details={"status": status, "auto_approved": auto_approve}
        )
        
        return MembershipResult(
            success=True,
            member_id=new_member_id,
            data={
                "status": status,
                "foundation_id": foundation_id,
                "foundation_name": foundation['name'],
                "message": "Welcome to the foundation!" if auto_approve else "Your membership is pending approval"
            }
        )
    
    def approve_member(
        self,
        foundation_id: str,
        member_record_id: str,
        approver_id: str
    ) -> MembershipResult:
        """Approve a pending member"""
        member = self._members.get(member_record_id)
        
        if not member or member['foundation_id'] != foundation_id:
            return MembershipResult(
                success=False,
                error_code="NOT_FOUND",
                error_message="Member not found"
            )
        
        if member['status'] != 'pending':
            return MembershipResult(
                success=False,
                error_code="INVALID_STATUS",
                error_message=f"Member status is {member['status']}, not pending"
            )
        
        # Check approver rights
        approver = self._get_member_by_user(foundation_id, approver_id)
        if not approver or approver['role'] not in ['founder', 'admin']:
            return MembershipResult(
                success=False,
                error_code="UNAUTHORIZED",
                error_message="You don't have permission to approve members"
            )
        
        member['status'] = 'active'
        member['approved_at'] = datetime.now(timezone.utc).isoformat()
        member['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        # Update foundation member count
        foundation = self._foundations.get(foundation_id)
        if foundation:
            foundation['current_members'] += 1
            foundation['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="member_approved",
            actor_id=approver_id,
            details={"member_id": member['member_id']}
        )
        
        return MembershipResult(
            success=True,
            member_id=member_record_id,
            data=member
        )
    
    def get_foundation_members(
        self,
        foundation_id: str,
        include_pending: bool = False
    ) -> List[Dict[str, Any]]:
        """Get all members of a foundation"""
        members = []
        for member in self._members.values():
            if member['foundation_id'] == foundation_id:
                if member['status'] == 'active' or (include_pending and member['status'] == 'pending'):
                    members.append(member)
        
        # Sort by role (founder first, then admin, then member)
        role_order = {'founder': 0, 'admin': 1, 'member': 2, 'observer': 3}
        members.sort(key=lambda x: (role_order.get(x['role'], 4), x['joined_at']))
        
        return members
    
    def leave_foundation(
        self,
        foundation_id: str,
        member_id: str
    ) -> MembershipResult:
        """Leave a foundation (for members)"""
        member = self._get_member_by_user(foundation_id, member_id)
        
        if not member:
            return MembershipResult(
                success=False,
                error_code="NOT_FOUND",
                error_message="You are not a member of this foundation"
            )
        
        if member['role'] == 'founder':
            return MembershipResult(
                success=False,
                error_code="FOUNDER_CANNOT_LEAVE",
                error_message="Founder cannot leave. Transfer ownership or dissolve the foundation."
            )
        
        member['status'] = 'removed'
        member['removed_at'] = datetime.now(timezone.utc).isoformat()
        member['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        # Update foundation member count
        foundation = self._foundations.get(foundation_id)
        if foundation:
            foundation['current_members'] = max(0, foundation['current_members'] - 1)
            foundation['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="member_left",
            actor_id=member_id
        )
        
        return MembershipResult(
            success=True,
            member_id=member['id'],
            data={"message": "You have left the foundation"}
        )
    
    def update_member_photo(
        self,
        foundation_id: str,
        member_record_id: str,
        photo_url: str,
        actor_id: str
    ) -> MembershipResult:
        """Update member photo"""
        member = self._members.get(member_record_id)
        
        if not member or member['foundation_id'] != foundation_id:
            return MembershipResult(
                success=False,
                error_code="NOT_FOUND",
                error_message="Member not found"
            )
        
        # Check if actor is the member or an admin
        if member['member_id'] != actor_id:
            actor_member = self._get_member_by_user(foundation_id, actor_id)
            if not actor_member or actor_member['role'] not in ['founder', 'admin']:
                return MembershipResult(
                    success=False,
                    error_code="UNAUTHORIZED",
                    error_message="You can only update your own photo"
                )
        
        member['photo_url'] = photo_url
        member['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="member_photo_updated",
            actor_id=actor_id,
            details={"member_id": member['member_id']}
        )
        
        return MembershipResult(
            success=True,
            member_id=member_record_id,
            data={"photo_url": photo_url}
        )
    
    def update_member_details(
        self,
        foundation_id: str,
        member_record_id: str,
        actor_id: str,
        display_name: Optional[str] = None,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        photo_url: Optional[str] = None
    ) -> MembershipResult:
        """Update member details"""
        member = self._members.get(member_record_id)
        
        if not member or member['foundation_id'] != foundation_id:
            return MembershipResult(
                success=False,
                error_code="NOT_FOUND",
                error_message="Member not found"
            )
        
        # Check if actor is the member or an admin
        if member['member_id'] != actor_id:
            actor_member = self._get_member_by_user(foundation_id, actor_id)
            if not actor_member or actor_member['role'] not in ['founder', 'admin']:
                return MembershipResult(
                    success=False,
                    error_code="UNAUTHORIZED",
                    error_message="You can only update your own details"
                )
        
        if display_name is not None:
            member['display_name'] = display_name
        if email is not None:
            member['email'] = email
        if phone is not None:
            member['phone'] = phone
        if photo_url is not None:
            member['photo_url'] = photo_url
        
        member['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="member_details_updated",
            actor_id=actor_id,
            details={"member_id": member['member_id']}
        )
        
        return MembershipResult(
            success=True,
            member_id=member_record_id,
            data=member
        )
    
    # ========== FUNDS ==========
    
    def _create_default_funds(self, foundation_id: str) -> None:
        """Create default funds for a new foundation"""
        fund_types = [
            ("Collective Insurance Pool", "insurance", "Shared risk coverage fund"),
            ("Emergency Fund", "emergency", "Emergency assistance fund")
        ]
        
        for name, fund_type, description in fund_types:
            fund_id = generate_id("FUND")
            fund = {
                'id': fund_id,
                'foundation_id': foundation_id,
                'name': name,
                'fund_type': fund_type,
                'description': description,
                'balance': 0.0,
                'currency': 'USD',
                'min_reserve': 0.0,
                'max_claim_percentage': 25.0,
                'status': 'active',
                'created_at': datetime.now(timezone.utc).isoformat(),
                'last_activity': None,
                'updated_at': datetime.now(timezone.utc).isoformat()
            }
            self._funds[fund_id] = fund
    
    def get_foundation_funds(self, foundation_id: str) -> List[Dict[str, Any]]:
        """Get all funds for a foundation"""
        funds = []
        for fund in self._funds.values():
            if fund['foundation_id'] == foundation_id and fund['status'] == 'active':
                funds.append(fund)
        return funds
    
    def make_contribution(
        self,
        foundation_id: str,
        fund_id: str,
        member_id: str,
        amount: float,
        contribution_type: str = "one_time",
        notes: str = ""
    ) -> Dict[str, Any]:
        """
        Make a contribution to a fund.
        
        This method:
        1. Records the contribution
        2. Updates fund and member balances
        3. Creates a billing record for dashboard visibility
        4. Persists data to disk
        5. Creates a backup before the operation
        """
        # Validate member
        member = self._get_member_by_user(foundation_id, member_id)
        if not member or member['status'] != 'active':
            return {"success": False, "error": "You must be an active member to contribute"}
        
        # Validate fund
        fund = self._funds.get(fund_id)
        if not fund or fund['foundation_id'] != foundation_id:
            return {"success": False, "error": "Fund not found"}
        
        if amount <= 0:
            return {"success": False, "error": "Contribution amount must be positive"}
        
        # Get foundation for billing integration
        foundation = self._foundations.get(foundation_id)
        foundation_name = foundation.get('name', 'Unknown Foundation') if foundation else 'Unknown Foundation'
        
        # Create backup before mutation
        self._persist(create_backup=True, backup_label=f"pre_contribution_{member_id[:8]}")
        
        # Create contribution record
        contribution_id = generate_id("CONTRIB")
        contribution = {
            'id': contribution_id,
            'fund_id': fund_id,
            'foundation_id': foundation_id,  # Add foundation reference
            'member_id': member['id'],  # Foundation member record ID
            'member_user_id': member_id,  # User ID for billing lookup
            'amount': amount,
            'contribution_type': contribution_type,
            'status': 'completed',
            'due_date': None,
            'paid_date': datetime.now(timezone.utc).isoformat(),
            'transaction_ref': f"TXN-{secrets.token_hex(6).upper()}",
            'notes': notes,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        self._contributions[contribution_id] = contribution
        
        # Update fund balance
        fund['balance'] += amount
        fund['last_activity'] = datetime.now(timezone.utc).isoformat()
        fund['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        # Update member contribution totals
        member['total_contributed'] += amount
        member['last_contribution'] = datetime.now(timezone.utc).isoformat()
        member['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        # Update foundation total
        if foundation:
            foundation['total_fund_balance'] += amount
            foundation['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        # Log activity
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="contribution_made",
            actor_id=member_id,
            details={"amount": amount, "fund_id": fund_id, "fund_name": fund['name']}
        )
        
        # === BILLING INTEGRATION ===
        # Record the deposit in the billing system so it appears on customer dashboard
        billing_record = None
        if self._billing_enabled and self._billing_integration:
            try:
                billing_record = self._billing_integration.record_foundation_deposit(
                    customer_id=member_id,  # Use the user ID for customer billing
                    foundation_id=foundation_id,
                    foundation_name=foundation_name,
                    amount=amount,
                    contribution_id=contribution_id,
                    fund_name=fund.get('name', ''),
                    notes=notes
                )
                logger.info(f"Billing record created for contribution {contribution_id}: {billing_record.id if billing_record else 'None'}")
            except Exception as e:
                logger.error(f"Error creating billing record: {e}")
        
        # Persist all data to disk
        self._persist()
        
        result = {
            "success": True,
            "contribution_id": contribution_id,
            "amount": amount,
            "new_balance": fund['balance'],
            "transaction_ref": contribution['transaction_ref']
        }
        
        # Include billing record ID if created
        if billing_record:
            result["billing_record_id"] = billing_record.id
            result["billing_reference"] = billing_record.billing_reference
        
        return result
    
    # ========== VOTING ==========
    
    def create_vote(
        self,
        foundation_id: str,
        created_by: str,
        proposal_type: str,
        title: str,
        description: str = "",
        threshold: float = 0.50,
        duration_days: int = 7,
        subject: str = "",
        summary: str = "",
        outlines: Optional[List[str]] = None,
        voting_mechanism: str = "simple_majority",
        options: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Create a new vote/proposal with comprehensive decision-making features.
        
        Args:
            foundation_id: Foundation ID
            created_by: User ID creating the vote
            proposal_type: Type of proposal (general, claim, membership, policy, budget, election)
            title: Short title for the vote
            description: Detailed description
            threshold: Vote threshold for passing (default 0.50 = 50%)
            duration_days: How long voting is open
            subject: Main subject/category of the decision
            summary: Executive summary of the proposal
            outlines: List of key points/outlines
            voting_mechanism: Type of voting (simple_majority, supermajority, unanimous, ranked_choice)
            options: Custom voting options (default: for/against/abstain)
        """
        foundation = self._foundations.get(foundation_id)
        if not foundation:
            return {"success": False, "error": "Foundation not found"}
        
        # Allow voting in active or draft foundations (for setup decisions)
        if foundation['status'] not in ['active', 'draft', 'pending_review']:
            return {"success": False, "error": f"Cannot create votes in {foundation['status']} foundation"}
        
        # Check creator rights - members can propose, but admin creates official votes
        creator_member = self._get_member_by_user(foundation_id, created_by)
        if not creator_member or creator_member['status'] != 'active':
            return {"success": False, "error": "You must be an active member to create votes"}
        
        # Determine if vote requires admin approval based on type
        requires_admin = creator_member['role'] not in ['founder', 'admin']
        
        # Set threshold based on voting mechanism
        mechanism_thresholds = {
            'simple_majority': 0.50,
            'supermajority': 0.66,
            'unanimous': 1.0,
            'ranked_choice': 0.50  # Winner takes all in ranked choice
        }
        actual_threshold = mechanism_thresholds.get(voting_mechanism, threshold)
        
        # Default options
        if options is None:
            if voting_mechanism == 'ranked_choice':
                options = ['Option A', 'Option B', 'Option C']  # Can be customized
            else:
                options = ['for', 'against', 'abstain']
        
        vote_id = generate_id("VOTE")
        vote = {
            'id': vote_id,
            'foundation_id': foundation_id,
            'proposal_type': proposal_type,
            'subject': subject or title,
            'title': title,
            'summary': summary or description[:200] if description else '',
            'description': description,
            'outlines': json.dumps(outlines or []),
            'voting_mechanism': voting_mechanism,
            'options': json.dumps(options),
            'status': 'pending_approval' if requires_admin else 'open',
            'threshold': actual_threshold,
            'quorum': 0.50,
            'votes_for': 0,
            'votes_against': 0,
            'votes_abstain': 0,
            'option_votes': json.dumps({opt: 0 for opt in options}),
            'result': None,
            'decision_record': None,
            'created_by': created_by,
            'created_by_name': creator_member['display_name'],
            'approved_by': created_by if not requires_admin else None,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'opens_at': datetime.now(timezone.utc).isoformat() if not requires_admin else None,
            'closes_at': (datetime.now(timezone.utc) + timedelta(days=duration_days)).isoformat(),
            'closed_at': None,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        self._votes[vote_id] = vote
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="vote_created",
            actor_id=created_by,
            details={
                "vote_id": vote_id,
                "title": title,
                "subject": subject,
                "mechanism": voting_mechanism,
                "requires_approval": requires_admin
            }
        )
        
        return {
            "success": True,
            "vote_id": vote_id,
            "title": title,
            "status": vote['status'],
            "closes_at": vote['closes_at'],
            "requires_approval": requires_admin
        }
    
    def approve_vote(
        self,
        vote_id: str,
        approver_id: str
    ) -> Dict[str, Any]:
        """Approve a pending vote (admin only)"""
        vote = self._votes.get(vote_id)
        if not vote:
            return {"success": False, "error": "Vote not found"}
        
        if vote['status'] != 'pending_approval':
            return {"success": False, "error": f"Vote is {vote['status']}, not pending approval"}
        
        foundation_id = vote['foundation_id']
        approver = self._get_member_by_user(foundation_id, approver_id)
        if not approver or approver['role'] not in ['founder', 'admin']:
            return {"success": False, "error": "Only founder/admin can approve votes"}
        
        vote['status'] = 'open'
        vote['approved_by'] = approver_id
        vote['opens_at'] = datetime.now(timezone.utc).isoformat()
        vote['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="vote_approved",
            actor_id=approver_id,
            details={"vote_id": vote_id, "title": vote['title']}
        )
        
        return {"success": True, "vote_id": vote_id, "status": "open"}
    
    def reject_vote_proposal(
        self,
        vote_id: str,
        rejector_id: str,
        reason: str = ""
    ) -> Dict[str, Any]:
        """Reject a pending vote proposal (admin only)"""
        vote = self._votes.get(vote_id)
        if not vote:
            return {"success": False, "error": "Vote not found"}
        
        if vote['status'] != 'pending_approval':
            return {"success": False, "error": f"Vote is {vote['status']}, not pending approval"}
        
        foundation_id = vote['foundation_id']
        rejector = self._get_member_by_user(foundation_id, rejector_id)
        if not rejector or rejector['role'] not in ['founder', 'admin']:
            return {"success": False, "error": "Only founder/admin can reject vote proposals"}
        
        vote['status'] = 'rejected'
        vote['closed_at'] = datetime.now(timezone.utc).isoformat()
        vote['decision_record'] = json.dumps({
            'outcome': 'rejected_by_admin',
            'rejected_by': rejector_id,
            'reason': reason,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        vote['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="vote_rejected",
            actor_id=rejector_id,
            details={"vote_id": vote_id, "reason": reason}
        )
        
        return {"success": True, "vote_id": vote_id, "status": "rejected"}
    
    def cast_vote(
        self,
        vote_id: str,
        member_id: str,
        choice: str,  # for, against, abstain, or custom option
        reason: str = "",
        ranked_choices: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Cast a vote on a proposal"""
        vote = self._votes.get(vote_id)
        if not vote:
            return {"success": False, "error": "Vote not found"}
        
        if vote['status'] != 'open':
            return {"success": False, "error": f"Vote is {vote['status']}, not open"}
        
        # Check expiry
        closes_at = datetime.fromisoformat(vote['closes_at'].replace('Z', '+00:00'))
        if datetime.now(timezone.utc) > closes_at:
            self._tally_vote(vote_id)
            return {"success": False, "error": "Voting period has ended"}
        
        # Check member
        member = self._get_member_by_user(vote['foundation_id'], member_id)
        if not member or member['status'] != 'active':
            return {"success": False, "error": "You must be an active member to vote"}
        
        # Check if already voted
        for vc in self._vote_casts.values():
            if vc['vote_id'] == vote_id and vc['member_id'] == member['id']:
                return {"success": False, "error": "You have already voted"}
        
        # Validate choice against available options
        try:
            available_options = json.loads(vote.get('options', '["for", "against", "abstain"]'))
        except:
            available_options = ['for', 'against', 'abstain']
        
        if choice not in available_options:
            return {"success": False, "error": f"Invalid vote choice. Valid options: {', '.join(available_options)}"}
        
        # Cast vote
        cast_id = generate_id("CAST")
        vote_cast = {
            'id': cast_id,
            'vote_id': vote_id,
            'member_id': member['id'],
            'member_user_id': member_id,
            'member_name': member['display_name'],
            'vote_choice': choice,
            'ranked_choices': json.dumps(ranked_choices) if ranked_choices else None,
            'weight': member['voting_weight'],
            'reason': reason,
            'cast_at': datetime.now(timezone.utc).isoformat()
        }
        self._vote_casts[cast_id] = vote_cast
        
        # Update vote counts
        if choice == 'for':
            vote['votes_for'] += 1
        elif choice == 'against':
            vote['votes_against'] += 1
        elif choice == 'abstain':
            vote['votes_abstain'] += 1
        
        # Update option votes
        try:
            option_votes = json.loads(vote.get('option_votes', '{}'))
            option_votes[choice] = option_votes.get(choice, 0) + 1
            vote['option_votes'] = json.dumps(option_votes)
        except:
            pass
        
        vote['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        self._log_activity(
            foundation_id=vote['foundation_id'],
            activity_type="vote_cast",
            actor_id=member_id,
            details={"vote_id": vote_id, "choice": choice, "has_reason": bool(reason)}
        )
        
        return {
            "success": True,
            "cast_id": cast_id,
            "choice": choice,
            "current_results": {
                "for": vote['votes_for'],
                "against": vote['votes_against'],
                "abstain": vote['votes_abstain']
            }
        }
    
    def get_vote(self, vote_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific vote with parsed JSON fields"""
        vote = self._votes.get(vote_id)
        if not vote:
            return None
        
        vote_copy = vote.copy()
        # Parse JSON fields
        for field in ['outlines', 'options', 'option_votes', 'decision_record']:
            if vote_copy.get(field) and isinstance(vote_copy[field], str):
                try:
                    vote_copy[field] = json.loads(vote_copy[field])
                except:
                    pass
        return vote_copy
    
    def get_vote_casts(self, vote_id: str) -> List[Dict[str, Any]]:
        """Get all casts for a vote"""
        casts = []
        for cast in self._vote_casts.values():
            if cast['vote_id'] == vote_id:
                cast_copy = cast.copy()
                if cast_copy.get('ranked_choices') and isinstance(cast_copy['ranked_choices'], str):
                    try:
                        cast_copy['ranked_choices'] = json.loads(cast_copy['ranked_choices'])
                    except:
                        pass
                casts.append(cast_copy)
        casts.sort(key=lambda x: x['cast_at'])
        return casts
    
    def get_active_votes(self, foundation_id: str) -> List[Dict[str, Any]]:
        """Get all active votes for a foundation with parsed fields"""
        votes = []
        for vote in self._votes.values():
            if vote['foundation_id'] == foundation_id and vote['status'] in ['open', 'pending_approval']:
                vote_copy = vote.copy()
                # Parse JSON fields
                for field in ['outlines', 'options', 'option_votes']:
                    if vote_copy.get(field) and isinstance(vote_copy[field], str):
                        try:
                            vote_copy[field] = json.loads(vote_copy[field])
                        except:
                            pass
                votes.append(vote_copy)
        # Sort by closes_at
        votes.sort(key=lambda x: x.get('closes_at', ''))
        return votes
    
    def get_all_votes(
        self, 
        foundation_id: str, 
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get all votes for a foundation with optional status filter"""
        votes = []
        for vote in self._votes.values():
            if vote['foundation_id'] == foundation_id:
                if status is None or vote['status'] == status:
                    vote_copy = vote.copy()
                    # Parse JSON fields
                    for field in ['outlines', 'options', 'option_votes', 'decision_record']:
                        if vote_copy.get(field) and isinstance(vote_copy[field], str):
                            try:
                                vote_copy[field] = json.loads(vote_copy[field])
                            except:
                                pass
                    votes.append(vote_copy)
        # Sort by created_at descending
        votes.sort(key=lambda x: x.get('created_at', ''), reverse=True)
        return votes[:limit]
    
    def get_member_vote_status(self, vote_id: str, member_id: str) -> Optional[Dict[str, Any]]:
        """Check if a member has already voted and get their vote"""
        vote = self._votes.get(vote_id)
        if not vote:
            return None
        
        member = self._get_member_by_user(vote['foundation_id'], member_id)
        if not member:
            return None
        
        for cast in self._vote_casts.values():
            if cast['vote_id'] == vote_id and cast['member_id'] == member['id']:
                return {
                    "has_voted": True,
                    "choice": cast['vote_choice'],
                    "reason": cast.get('reason', ''),
                    "cast_at": cast['cast_at']
                }
        
        return {"has_voted": False}
    
    def close_vote(self, vote_id: str, closer_id: str = None) -> Dict[str, Any]:
        """Manually close a vote and tally results"""
        vote = self._votes.get(vote_id)
        if not vote:
            return {"success": False, "error": "Vote not found"}
        
        if vote['status'] != 'open':
            return {"success": False, "error": f"Vote is {vote['status']}, cannot close"}
        
        # If closer specified, check permissions
        if closer_id:
            member = self._get_member_by_user(vote['foundation_id'], closer_id)
            if not member or member['role'] not in ['founder', 'admin']:
                return {"success": False, "error": "Only founder/admin can close votes early"}
        
        self._tally_vote(vote_id)
        
        return {
            "success": True,
            "vote_id": vote_id,
            "result": vote['result'],
            "status": vote['status']
        }
    
    def _tally_vote(self, vote_id: str) -> None:
        """Tally votes 
and determine result with comprehensive decision record"""
        vote = self._votes.get(vote_id)
        if not vote:
            return
        
        total_votes = vote['votes_for'] + vote['votes_against'] + vote['votes_abstain']
        foundation = self._foundations.get(vote['foundation_id'])
        total_members = foundation['current_members'] if foundation else 1
        
        # Check quorum
        participation_rate = total_votes / max(total_members, 1)
        quorum_met = participation_rate >= vote.get('quorum', 0.50)
        
        # Determine result
        if total_votes == 0:
            vote['result'] = 'no_votes'
            vote['status'] = 'failed'
        elif not quorum_met:
            vote['result'] = 'no_quorum'
            vote['status'] = 'failed'
        else:
            # Calculate based on voting mechanism
            mechanism = vote.get('voting_mechanism', 'simple_majority')
            
            if mechanism == 'ranked_choice':
                # For ranked choice, use option_votes
                try:
                    option_votes = json.loads(vote.get('option_votes', '{}'))
                    if option_votes:
                        winner = max(option_votes, key=option_votes.get)
                        vote['result'] = f'winner:{winner}'
                        vote['status'] = 'passed'
                    else:
                        vote['result'] = 'no_votes'
                        vote['status'] = 'failed'
                except:
                    vote['result'] = 'error'
                    vote['status'] = 'failed'
            else:
                # Standard for/against voting
                votes_counted = vote['votes_for'] + vote['votes_against']
                if votes_counted == 0:
                    vote['result'] = 'all_abstain'
                    vote['status'] = 'failed'
                elif vote['votes_for'] / votes_counted >= vote['threshold']:
                    vote['result'] = 'passed'
                    vote['status'] = 'passed'
                else:
                    vote['result'] = 'failed'
                    vote['status'] = 'failed'
        
        vote['closed_at'] = datetime.now(timezone.utc).isoformat()
        vote['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        # Create comprehensive decision record
        decision_record = {
            'outcome': vote['result'],
            'status': vote['status'],
            'voting_mechanism': vote.get('voting_mechanism', 'simple_majority'),
            'threshold_required': vote['threshold'],
            'quorum_required': vote.get('quorum', 0.50),
            'total_members': total_members,
            'total_votes': total_votes,
            'participation_rate': round(participation_rate * 100, 1),
            'quorum_met': quorum_met,
            'votes_for': vote['votes_for'],
            'votes_against': vote['votes_against'],
            'votes_abstain': vote['votes_abstain'],
            'approval_rate': round((vote['votes_for'] / max(vote['votes_for'] + vote['votes_against'], 1)) * 100, 1),
            'closed_at': vote['closed_at'],
            'created_at': vote['created_at'],
            'duration_hours': round((datetime.fromisoformat(vote['closed_at'].replace('Z', '+00:00')) - 
                                     datetime.fromisoformat(vote['created_at'].replace('Z', '+00:00'))).total_seconds() / 3600, 1)
        }
        vote['decision_record'] = json.dumps(decision_record)
        
        self._log_activity(
            foundation_id=vote['foundation_id'],
            activity_type="vote_closed",
            actor_id="system",
            details={
                "vote_id": vote_id,
                "result": vote['result'],
                "votes_for": vote['votes_for'],
                "votes_against": vote['votes_against'],
                "participation_rate": decision_record['participation_rate']
            }
        )
    
    # ========== CLAIMS ==========
    
    def submit_claim(
        self,
        foundation_id: str,
        fund_id: str,
        claimant_id: str,
        claim_type: str,
        amount: float,
        description: str = "",
        supporting_docs: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """Submit a claim request"""
        foundation = self._foundations.get(foundation_id)
        if not foundation or foundation['status'] != 'active':
            return {"success": False, "error": "Foundation not found or not active"}
        
        # Validate member
        member = self._get_member_by_user(foundation_id, claimant_id)
        if not member or member['status'] != 'active':
            return {"success": False, "error": "You must be an active member to submit claims"}
        
        # Validate fund
        fund = self._funds.get(fund_id)
        if not fund or fund['foundation_id'] != foundation_id:
            return {"success": False, "error": "Fund not found"}
        
        # Check claim amount vs fund balance
        max_claim_pct = fund.get('max_claim_percentage', 25.0)
        max_claim_amount = fund['balance'] * (max_claim_pct / 100)
        
        if amount > max_claim_amount:
            return {
                "success": False,
                "error": f"Claim amount exceeds maximum ({max_claim_pct}% of fund balance = ${max_claim_amount:.2f})"
            }
        
        if amount > fund['balance']:
            return {"success": False, "error": "Claim amount exceeds fund balance"}
        
        # Get claim rules
        settings = foundation.get('settings', {})
        claim_rules = settings.get('claim_rules', {})
        auto_approve_threshold = claim_rules.get('auto_approve_threshold', 500.00)
        vote_threshold = claim_rules.get('vote_threshold', 0.50)
        
        # Determine if vote is required
        requires_vote = amount > auto_approve_threshold
        
        claim_id = generate_id("FCLAIM")
        claim = {
            'id': claim_id,
            'foundation_id': foundation_id,
            'fund_id': fund_id,
            'claimant_id': member['id'],
            'claim_type': claim_type,
            'amount_requested': amount,
            'amount_approved': None,
            'description': description,
            'supporting_docs': json.dumps(supporting_docs or []),
            'status': 'vote_open' if requires_vote else 'reviewing',
            'vote_id': None,
            'reviewed_by': None,
            'review_notes': None,
            'payout_date': None,
            'payout_method': None,
            'payout_reference': None,
            'submitted_at': datetime.now(timezone.utc).isoformat(),
            'reviewed_at': None,
            'updated_at': datetime.now(timezone.utc).isoformat()
        }
        
        # If vote required, create vote
        if requires_vote:
            vote_result = self.create_vote(
                foundation_id=foundation_id,
                created_by=claimant_id,
                proposal_type='claim',
                title=f"Claim Request: {claim_type} - ${amount:.2f}",
                description=f"{description}\n\nRequested by: {member['display_name']}",
                threshold=vote_threshold,
                duration_days=7
            )
            if vote_result.get('success'):
                claim['vote_id'] = vote_result['vote_id']
        
        self._claims[claim_id] = claim
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="claim_submitted",
            actor_id=claimant_id,
            details={
                "claim_id": claim_id,
                "amount": amount,
                "requires_vote": requires_vote
            }
        )
        
        return {
            "success": True,
            "claim_id": claim_id,
            "status": claim['status'],
            "requires_vote": requires_vote,
            "vote_id": claim.get('vote_id')
        }
    
    def approve_claim(
        self,
        claim_id: str,
        approver_id: str,
        approved_amount: Optional[float] = None,
        notes: str = ""
    ) -> Dict[str, Any]:
        """Approve a claim (for founder/admin)"""
        claim = self._claims.get(claim_id)
        if not claim:
            return {"success": False, "error": "Claim not found"}
        
        foundation_id = claim['foundation_id']
        
        # Check approver rights
        approver = self._get_member_by_user(foundation_id, approver_id)
        if not approver or approver['role'] not in ['founder', 'admin']:
            return {"success": False, "error": "Only founder/admin can approve claims"}
        
        if claim['status'] not in ['reviewing', 'vote_open']:
            return {"success": False, "error": f"Cannot approve claim with status: {claim['status']}"}
        
        # Check if vote required and passed
        if claim['vote_id']:
            vote = self._votes.get(claim['vote_id'])
            if vote and vote['status'] == 'open':
                return {"success": False, "error": "Vote is still open"}
            if vote and vote['result'] != 'passed':
                return {"success": False, "error": "Vote did not pass"}
        
        amount = approved_amount or claim['amount_requested']
        fund = self._funds.get(claim['fund_id'])
        
        if amount > fund['balance']:
            return {"success": False, "error": "Insufficient fund balance"}
        
        # Update claim
        claim['status'] = 'approved'
        claim['amount_approved'] = amount
        claim['reviewed_by'] = approver_id
        claim['review_notes'] = notes
        claim['reviewed_at'] = datetime.now(timezone.utc).isoformat()
        claim['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        # Deduct from fund
        fund['balance'] -= amount
        fund['last_activity'] = datetime.now(timezone.utc).isoformat()
        fund['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        # Update foundation total
        foundation = self._foundations.get(foundation_id)
        if foundation:
            foundation['total_fund_balance'] -= amount
            foundation['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="claim_approved",
            actor_id=approver_id,
            details={"claim_id": claim_id, "amount": amount}
        )
        
        return {
            "success": True,
            "claim_id": claim_id,
            "approved_amount": amount,
            "status": "approved"
        }
    
    def get_foundation_claims(
        self,
        foundation_id: str,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get claims for a foundation"""
        claims = []
        for claim in self._claims.values():
            if claim['foundation_id'] == foundation_id:
                if status is None or claim['status'] == status:
                    claims.append(claim)
        
        claims.sort(key=lambda x: x['submitted_at'], reverse=True)
        return claims
    
    # ========== ACTIVITY LOGGING ==========
    
    def _log_activity(
        self,
        foundation_id: str,
        activity_type: str,
        actor_id: str,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None
    ) -> None:
        """Log foundation activity"""
        activity_id = generate_id("ACT")
        activity = {
            'id': activity_id,
            'foundation_id': foundation_id,
            'activity_type': activity_type,
            'actor_id': actor_id,
            'details': json.dumps(details or {}),
            'ip_address': ip_address,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        self._activities[activity_id] = activity
    
    def get_foundation_activities(
        self,
        foundation_id: str,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get recent activities for a foundation"""
        activities = []
        for activity in self._activities.values():
            if activity['foundation_id'] == foundation_id:
                act_copy = activity.copy()
                try:
                    act_copy['details'] = json.loads(act_copy['details'])
                except:
                    act_copy['details'] = {}
                activities.append(act_copy)
        
        activities.sort(key=lambda x: x['timestamp'], reverse=True)
        return activities[:limit]
    
    # ========== MEMBER MANAGEMENT ==========
    
    def reject_member(
        self,
        foundation_id: str,
        member_record_id: str,
        rejector_id: str,
        reason: str = ""
    ) -> MembershipResult:
        """Reject a pending member application"""
        member = self._members.get(member_record_id)
        
        if not member or member['foundation_id'] != foundation_id:
            return MembershipResult(
                success=False,
                error_code="NOT_FOUND",
                error_message="Member not found"
            )
        
        if member['status'] != 'pending':
            return MembershipResult(
                success=False,
                error_code="INVALID_STATUS",
                error_message=f"Member status is {member['status']}, not pending"
            )
        
        # Check rejector rights
        rejector = self._get_member_by_user(foundation_id, rejector_id)
        if not rejector or rejector['role'] not in ['founder', 'admin']:
            return MembershipResult(
                success=False,
                error_code="UNAUTHORIZED",
                error_message="Only founder/admin can reject members"
            )
        
        member['status'] = 'rejected'
        member['removed_at'] = datetime.now(timezone.utc).isoformat()
        member['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="member_rejected",
            actor_id=rejector_id,
            details={"member_id": member['member_id'], "reason": reason}
        )
        
        return MembershipResult(
            success=True,
            member_id=member_record_id,
            data={"message": "Member rejected", "reason": reason}
        )
    
    def remove_member(
        self,
        foundation_id: str,
        member_record_id: str,
        remover_id: str,
        reason: str = ""
    ) -> MembershipResult:
        """Remove an active member from the foundation"""
        member = self._members.get(member_record_id)
        
        if not member or member['foundation_id'] != foundation_id:
            return MembershipResult(
                success=False,
                error_code="NOT_FOUND",
                error_message="Member not found"
            )
        
        if member['status'] != 'active':
            return MembershipResult(
                success=False,
                error_code="INVALID_STATUS",
                error_message=f"Member status is {member['status']}, not active"
            )
        
        if member['role'] == 'founder':
            return MembershipResult(
                success=False,
                error_code="CANNOT_REMOVE_FOUNDER",
                error_message="Cannot remove the founder"
            )
        
        # Check remover rights
        remover = self._get_member_by_user(foundation_id, remover_id)
        if not remover or remover['role'] not in ['founder', 'admin']:
            return MembershipResult(
                success=False,
                error_code="UNAUTHORIZED",
                error_message="Only founder/admin can remove members"
            )
        
        member['status'] = 'removed'
        member['removed_at'] = datetime.now(timezone.utc).isoformat()
        member['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        # Update foundation member count
        foundation = self._foundations.get(foundation_id)
        if foundation:
            foundation['current_members'] = max(0, foundation['current_members'] - 1)
            foundation['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="member_removed",
            actor_id=remover_id,
            details={"member_id": member['member_id'], "reason": reason}
        )
        
        return MembershipResult(
            success=True,
            member_id=member_record_id,
            data={"message": "Member removed", "reason": reason}
        )
    
    def update_member_role(
        self,
        foundation_id: str,
        member_record_id: str,
        new_role: str,
        actor_id: str
    ) -> MembershipResult:
        """Update a member's role"""
        member = self._members.get(member_record_id)
        
        if not member or member['foundation_id'] != foundation_id:
            return MembershipResult(
                success=False,
                error_code="NOT_FOUND",
                error_message="Member not found"
            )
        
        if new_role not in ['admin', 'member', 'observer']:
            return MembershipResult(
                success=False,
                error_code="INVALID_ROLE",
                error_message="Invalid role. Valid roles: admin, member, observer"
            )
        
        if member['role'] == 'founder':
            return MembershipResult(
                success=False,
                error_code="CANNOT_CHANGE_FOUNDER",
                error_message="Cannot change founder's role"
            )
        
        # Check actor rights - only founder can change roles
        actor = self._get_member_by_user(foundation_id, actor_id)
        if not actor or actor['role'] != 'founder':
            return MembershipResult(
                success=False,
                error_code="UNAUTHORIZED",
                error_message="Only founder can change member roles"
            )
        
        old_role = member['role']
        member['role'] = new_role
        member['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="member_role_changed",
            actor_id=actor_id,
            details={
                "member_id": member['member_id'],
                "old_role": old_role,
                "new_role": new_role
            }
        )
        
        return MembershipResult(
            success=True,
            member_id=member_record_id,
            data={"role": new_role, "message": f"Role updated to {new_role}"}
        )
    
    # ========== BILLING & REPORTS ==========
    
    def get_foundation_billing_summary(self, foundation_id: str) -> Dict[str, Any]:
        """Get billing summary for a foundation"""
        foundation = self._foundations.get(foundation_id)
        if not foundation:
            return {"error": "Foundation not found"}
        
        # Get all contributions
        contributions = []
        for contrib in self._contributions.values():
            fund = self._funds.get(contrib['fund_id'])
            if fund and fund['foundation_id'] == foundation_id:
                contributions.append(contrib)
        
        # Get all members
        members = self.get_foundation_members(foundation_id, include_pending=False)
        
        # Calculate stats
        total_contributions = sum(c['amount'] for c in contributions)
        total_claims_paid = sum(
            c.get('amount_approved', 0) 
            for c in self._claims.values() 
            if c['foundation_id'] == foundation_id and c['status'] == 'approved'
        )
        
        # Get contribution breakdown by member
        member_contributions = {}
        for contrib in contributions:
            member_id = contrib['member_id']
            if member_id not in member_contributions:
                member_contributions[member_id] = 0
            member_contributions[member_id] += contrib['amount']
        
        # Get monthly breakdown
        monthly_breakdown = {}
        for contrib in contributions:
            month = contrib['paid_date'][:7] if contrib.get('paid_date') else 'Unknown'
            if month not in monthly_breakdown:
                monthly_breakdown[month] = {'contributions': 0, 'count': 0}
            monthly_breakdown[month]['contributions'] += contrib['amount']
            monthly_breakdown[month]['count'] += 1
        
        return {
            "foundation_id": foundation_id,
            "foundation_name": foundation['name'],
            "currency": foundation.get('currency', 'USD'),
            "summary": {
                "total_balance": foundation['total_fund_balance'],
                "total_contributions": total_contributions,
                "total_claims_paid": total_claims_paid,
                "net_balance": total_contributions - total_claims_paid,
                "reserve_percentage": foundation.get('reserve_percentage', 20),
                "reserve_amount": foundation['total_fund_balance'] * (foundation.get('reserve_percentage', 20) / 100),
                "available_for_claims": foundation['total_fund_balance'] * (1 - foundation.get('reserve_percentage', 20) / 100)
            },
            "members": {
                "total": len(members),
                "active_contributors": len([m for m in members if m['total_contributed'] > 0]),
                "average_contribution": total_contributions / max(len(members), 1)
            },
            "monthly_breakdown": [
                {"month": k, **v} 
                for k, v in sorted(monthly_breakdown.items(), reverse=True)[:12]
            ],
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
    
    def get_member_billing_history(
        self, 
        foundation_id: str, 
        member_user_id: str
    ) -> Dict[str, Any]:
        """Get billing history for a specific member"""
        member = self._get_member_by_user(foundation_id, member_user_id)
        if not member:
            return {"error": "Member not found"}
        
        foundation = self._foundations.get(foundation_id)
        
        # Get member's contributions
        contributions = []
        for contrib in self._contributions.values():
            if contrib['member_id'] == member['id']:
                fund = self._funds.get(contrib['fund_id'])
                contrib_copy = contrib.copy()
                contrib_copy['fund_name'] = fund['name'] if fund else 'Unknown'
                contributions.append(contrib_copy)
        
        # Get member's claims
        claims = []
        for claim in self._claims.values():
            if claim['claimant_id'] == member['id']:
                claims.append(claim)
        
        contributions.sort(key=lambda x: x.get('paid_date', ''), reverse=True)
        claims.sort(key=lambda x: x.get('submitted_at', ''), reverse=True)
        
        return {
            "member_id": member['id'],
            "member_user_id": member_user_id,
            "display_name": member['display_name'],
            "foundation_name": foundation['name'] if foundation else None,
            "summary": {
                "total_contributed": member['total_contributed'],
                "contribution_count": len(contributions),
                "last_contribution": member['last_contribution'],
                "claims_submitted": len(claims),
                "claims_approved": len([c for c in claims if c['status'] == 'approved']),
                "total_claimed": sum(c.get('amount_approved', 0) for c in claims if c['status'] == 'approved')
            },
            "contributions": contributions[:20],
            "claims": claims[:10],
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
    
    def get_foundation_report(
        self,
        foundation_id: str,
        report_type: str = "summary"
    ) -> Dict[str, Any]:
        """Generate a comprehensive foundation report"""
        foundation = self._foundations.get(foundation_id)
        if not foundation:
            return {"error": "Foundation not found"}
        
        members = self.get_foundation_members(foundation_id, include_pending=True)
        funds = self.get_foundation_funds(foundation_id)
        votes = self.get_all_votes(foundation_id, limit=100)
        claims = self.get_foundation_claims(foundation_id)
        activities = self.get_foundation_activities(foundation_id, limit=50)
        billing = self.get_foundation_billing_summary(foundation_id)
        
        report = {
            "report_type": report_type,
            "foundation": {
                "id": foundation['id'],
                "name": foundation['name'],
                "type": foundation['foundation_type'],
                "status": foundation['status'],
                "created_at": foundation['created_at'],
                "activated_at": foundation.get('activated_at')
            },
            "membership": {
                "total": len(members),
                "active": len([m for m in members if m['status'] == 'active']),
                "pending": len([m for m in members if m['status'] == 'pending']),
                "by_role": {
                    "founder": len([m for m in members if m['role'] == 'founder']),
                    "admin": len([m for m in members if m['role'] == 'admin']),
                    "member": len([m for m in members if m['role'] == 'member']),
                    "observer": len([m for m in members if m['role'] == 'observer'])
                }
            },
            "financial": billing.get('summary', {}),
            "funds": [
                {
                    "id": f['id'],
                    "name": f['name'],
                    "type": f['fund_type'],
                    "balance": f['balance']
                }
                for f in funds
            ],
            "governance": {
                "total_votes": len(votes),
                "votes_passed": len([v for v in votes if v['status'] == 'passed']),
                "votes_failed": len([v for v in votes if v['status'] == 'failed']),
                "votes_open": len([v for v in votes if v['status'] == 'open']),
                "average_participation": sum(
                    v.get('votes_for', 0) + v.get('votes_against', 0) + v.get('votes_abstain', 0)
                    for v in votes if v['status'] in ['passed', 'failed']
                ) / max(len([v for v in votes if v['status'] in ['passed', 'failed']]), 1)
            },
            "claims": {
                "total": len(claims),
                "pending": len([c for c in claims if c['status'] in ['reviewing', 'vote_open']]),
                "approved": len([c for c in claims if c['status'] == 'approved']),
                "rejected": len([c for c in claims if c['status'] == 'rejected']),
                "total_approved_amount": sum(c.get('amount_approved', 0) for c in claims if c['status'] == 'approved')
            },
            "recent_activities": activities[:10],
            "generated_at": datetime.now(timezone.utc).isoformat()
        }
        
        return report
    
    # ========== HELPERS ==========
    
    def _get_member_by_user(
        self,
        foundation_id: str,
        user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get foundation member by user ID"""
        for member in self._members.values():
            if member['foundation_id'] == foundation_id and member['member_id'] == user_id:
                return member
        return None
    
    def get_user_foundations(self, user_id: str) -> List[Dict[str, Any]]:
        """Get all foundations a user is a member of"""
        result = []
        for member in self._members.values():
            if member['member_id'] == user_id and member['status'] in ['active', 'pending']:
                foundation = self._foundations.get(member['foundation_id'])
                if foundation:
                    # Get active votes count
                    active_votes = len(self.get_active_votes(foundation['id']))
                    result.append({
                        **foundation,
                        'user_role': member['role'],
                        'user_status': member['status'],
                        'user_member_id': member['id'],
                        'active_votes': active_votes
                    })
        return result
    
    def get_pending_invitations(self, email: str) -> List[Dict[str, Any]]:
        """Get pending invitations for an email"""
        invitations = []
        now = datetime.now(timezone.utc)
        
        for invitation in self._invitations.values():
            if (invitation['status'] == 'pending' and
                invitation.get('invited_email', '').lower() == email.lower()):
                expires_at = datetime.fromisoformat(invitation['expires_at'].replace('Z', '+00:00'))
                if now < expires_at:
                    foundation = self._foundations.get(invitation['foundation_id'])
                    invitations.append({
                        **invitation,
                        'foundation_name': foundation['name'] if foundation else None,
                        'foundation_type': foundation['foundation_type'] if foundation else None
                    })
        
        return invitations


# ============================================================================
# SINGLETON INSTANCE
# ============================================================================

_foundation_service: Optional[FoundationService] = None


def get_foundation_service(
    enable_persistence: bool = True,
    enable_backup: bool = True,
    enable_billing_integration: bool = True,
    data_dir: str = None,
    billing_records: Dict = None,
    transaction_ledger: Dict = None,
    bills: Dict = None
) -> FoundationService:
    """
    Get or create the foundation service singleton.
    
    On first call, creates the service with specified options.
    Subsequent calls return the existing instance.
    
    Args:
        enable_persistence: Enable data persistence to disk
        enable_backup: Enable automatic backups
        enable_billing_integration: Enable billing integration for dashboard
        data_dir: Directory for data storage
        billing_records: Optional billing records dict (for billing integration)
        transaction_ledger: Optional transaction ledger dict
        bills: Optional bills dict (for BillingService compatibility)
        
    Returns:
        FoundationService singleton instance
    """
    global _foundation_service
    if _foundation_service is None:
        _foundation_service = FoundationService(
            enable_persistence=enable_persistence,
            enable_backup=enable_backup,
            enable_billing_integration=enable_billing_integration,
            data_dir=data_dir,
            billing_records=billing_records,
            transaction_ledger=transaction_ledger,
            bills=bills
        )
    return _foundation_service


def reset_foundation_service() -> None:
    """Reset the foundation service (for testing)"""
    global _foundation_service
    if _foundation_service:
        # Create final backup before reset
        _foundation_service.create_backup(label="pre_reset")
    _foundation_service = None


def init_foundation_service(
    billing_records: Dict = None,
    transaction_ledger: Dict = None,
    bills: Dict = None,
    enable_persistence: bool = True,
    enable_backup: bool = True,
    enable_billing_integration: bool = True,
    data_dir: str = None
) -> FoundationService:
    """
    Initialize or re-initialize the foundation service.
    
    Use this to set up the service with specific data stores from the main server.
    
    Args:
        billing_records: Billing records dictionary
        transaction_ledger: Transaction ledger dictionary
        bills: Bills dictionary (for BillingService)
        enable_persistence: Enable persistence
        enable_backup: Enable backups
        enable_billing_integration: Enable billing integration
        data_dir: Data directory path
        
    Returns:
        FoundationService instance
    """
    global _foundation_service
    
    # Reset and recreate with new parameters
    if _foundation_service:
        _foundation_service.create_backup(label="pre_reinit")
    
    _foundation_service = FoundationService(
        enable_persistence=enable_persistence,
        enable_backup=enable_backup,
        enable_billing_integration=enable_billing_integration,
        data_dir=data_dir,
        billing_records=billing_records,
        transaction_ledger=transaction_ledger,
        bills=bills
    )
    
    return _foundation_service


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    'FoundationType',
    'FoundationStatus',
    'PipelineStage',
    'DEFAULT_RULES',
    'FoundationCreateRequest',
    'FoundationResult',
    'MembershipResult',
    'FoundationService',
    'get_foundation_service',
    'reset_foundation_service',
    'generate_id',
    'generate_invitation_code',
    'get_default_rules'
]
