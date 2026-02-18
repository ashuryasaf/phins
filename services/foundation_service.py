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


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Best-effort numeric conversion used by financial reconciliations."""
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return float(int(value))
        return float(str(value).replace(",", "").strip())
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """Best-effort integer conversion helper."""
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return int(value)
        return int(float(value))
    except Exception:
        return default


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
        self._asset_transactions: Dict[str, Dict[str, Any]] = {}
        self._liability_records: Dict[str, Dict[str, Any]] = {}
        self._internal_loans: Dict[str, Dict[str, Any]] = {}
        self._customer_connections: Dict[str, Dict[str, Any]] = {}
        self._foundation_ledger: Dict[str, Dict[str, Any]] = {}
        self._integrity_history: Dict[str, Dict[str, Any]] = {}
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

        # Ensure all in-memory records include the latest financial fields.
        self._initialize_foundation_state_defaults()

    def _initialize_foundation_state_defaults(self) -> None:
        """Backfill defaults for foundations and financial state stores."""
        for foundation in self._foundations.values():
            self._ensure_foundation_financial_defaults(foundation)

        # Rebuild missing relationship records from membership table.
        for member in self._members.values():
            foundation_id = member.get("foundation_id")
            member_user_id = str(member.get("member_id") or "")
            if foundation_id and member_user_id:
                self._touch_customer_connection(foundation_id, member_user_id, role=member.get("role"))

    def _ensure_foundation_financial_defaults(self, foundation: Dict[str, Any]) -> None:
        """Ensure a foundation record has complete financial defaults."""
        foundation.setdefault("currency", "USD")
        foundation.setdefault("total_fund_balance", 0.0)
        foundation.setdefault("total_asset_value", 0.0)
        foundation.setdefault("total_liability_value", 0.0)
        foundation.setdefault("net_equity_value", 0.0)
        foundation.setdefault("total_internal_debt", 0.0)
        foundation.setdefault("total_internal_credit", 0.0)
        foundation.setdefault("last_integrity_check_at", None)
        foundation.setdefault("integrity_last_status", "unknown")
        foundation.setdefault("integrity_issue_count", 0)
        foundation.setdefault("last_balance_sheet_at", None)
        foundation.setdefault("analytics", {})
        foundation["total_fund_balance"] = round(_safe_float(foundation.get("total_fund_balance")), 2)
        foundation["total_asset_value"] = round(_safe_float(foundation.get("total_asset_value")), 2)
        foundation["total_liability_value"] = round(_safe_float(foundation.get("total_liability_value")), 2)
        foundation["net_equity_value"] = round(
            _safe_float(foundation.get("total_fund_balance"))
            + _safe_float(foundation.get("total_asset_value"))
            - _safe_float(foundation.get("total_liability_value")),
            2
        )
        foundation["total_internal_debt"] = round(_safe_float(foundation.get("total_internal_debt")), 2)
        foundation["total_internal_credit"] = round(_safe_float(foundation.get("total_internal_credit")), 2)

    def _touch_customer_connection(self, foundation_id: str, member_user_id: str, role: Optional[str] = None) -> None:
        """Maintain a lightweight relationship graph for foundation members."""
        connection_id = f"{foundation_id}:{member_user_id}"
        entry = self._customer_connections.get(connection_id)
        now_iso = datetime.now(timezone.utc).isoformat()
        if not entry:
            entry = {
                "id": connection_id,
                "foundation_id": foundation_id,
                "customer_id": member_user_id,
                "role": role or "member",
                "connected_customers": [],
                "connections_count": 0,
                "joined_at": now_iso,
                "last_seen_at": now_iso,
                "updated_at": now_iso,
            }
            self._customer_connections[connection_id] = entry
        else:
            if role:
                entry["role"] = role
            entry["last_seen_at"] = now_iso
            entry["updated_at"] = now_iso

        # Rebuild connection links against other active members in foundation.
        peers = sorted(
            {
                str(member.get("member_id"))
                for member in self._members.values()
                if member.get("foundation_id") == foundation_id
                and member.get("status") == "active"
                and str(member.get("member_id")) != member_user_id
            }
        )
        entry["connected_customers"] = peers
        entry["connections_count"] = len(peers)
        entry["updated_at"] = now_iso

        # Keep peer lists symmetric for all active members.
        active_member_ids = sorted(
            {
                str(member.get("member_id"))
                for member in self._members.values()
                if member.get("foundation_id") == foundation_id and member.get("status") == "active"
            }
        )
        for customer_id in active_member_ids:
            cid = f"{foundation_id}:{customer_id}"
            existing = self._customer_connections.get(cid)
            if not existing:
                existing = {
                    "id": cid,
                    "foundation_id": foundation_id,
                    "customer_id": customer_id,
                    "role": "member",
                    "connected_customers": [],
                    "connections_count": 0,
                    "joined_at": now_iso,
                    "last_seen_at": now_iso,
                    "updated_at": now_iso,
                }
                self._customer_connections[cid] = existing
            existing_peers = [mid for mid in active_member_ids if mid != customer_id]
            existing["connected_customers"] = existing_peers
            existing["connections_count"] = len(existing_peers)
            existing["last_seen_at"] = now_iso
            existing["updated_at"] = now_iso

    def _reconcile_foundation_totals(self, foundation_id: str, update_timestamp: bool = False) -> Dict[str, Any]:
        """Reconcile computed totals for a foundation financial state."""
        foundation = self._foundations.get(foundation_id)
        if not foundation:
            return {"success": False, "error": "FOUNDATION_NOT_FOUND"}

        cash_total = round(
            sum(
                _safe_float(fund.get("balance"))
                for fund in self._funds.values()
                if fund.get("foundation_id") == foundation_id and fund.get("status") != "archived"
            ),
            2
        )
        foundation["total_fund_balance"] = cash_total

        asset_total = round(
            sum(
                _safe_float(asset.get("net_amount"))
                for asset in self._asset_transactions.values()
                if asset.get("foundation_id") == foundation_id and asset.get("status") == "active"
            ),
            2
        )
        foundation["total_asset_value"] = asset_total

        liability_total = round(
            sum(
                _safe_float(liability.get("outstanding_amount", liability.get("amount")))
                for liability in self._liability_records.values()
                if liability.get("foundation_id") == foundation_id and liability.get("status") in {"open", "active", "past_due"}
            ),
            2
        )
        foundation["total_liability_value"] = liability_total

        internal_outstanding = round(
            sum(
                _safe_float(loan.get("outstanding_amount"))
                for loan in self._internal_loans.values()
                if loan.get("foundation_id") == foundation_id and loan.get("status") in {"active", "past_due"}
            ),
            2
        )
        # Same principal appears as debt for borrowers and credit for lenders.
        internal_debt = internal_outstanding
        internal_credit = internal_outstanding
        foundation["total_internal_debt"] = internal_debt
        foundation["total_internal_credit"] = internal_credit

        foundation["net_equity_value"] = round(cash_total + asset_total - liability_total, 2)
        if update_timestamp:
            foundation["updated_at"] = datetime.now(timezone.utc).isoformat()
        return {
            "success": True,
            "cash_total": cash_total,
            "asset_total": asset_total,
            "liability_total": liability_total,
            "equity": foundation["net_equity_value"],
        }

    def _record_ledger_entry(
        self,
        *,
        foundation_id: str,
        category: str,
        action: str,
        actor_id: str,
        amount: float = 0.0,
        reference_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Record immutable transaction-style entries for foundation ledger views."""
        entry_id = generate_id("LEDGER")
        entry = {
            "id": entry_id,
            "foundation_id": foundation_id,
            "category": category,
            "action": action,
            "actor_id": actor_id,
            "amount": round(_safe_float(amount), 2),
            "reference_id": reference_id,
            "payload": payload or {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "entry_hash": hashlib.sha256(
                f"{entry_id}:{foundation_id}:{category}:{action}:{reference_id or ''}:{amount}".encode()
            ).hexdigest()[:24],
        }
        self._foundation_ledger[entry_id] = entry
        return entry
    
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
            self._asset_transactions = data.get('asset_transactions', {})
            self._liability_records = data.get('liability_records', {})
            self._internal_loans = data.get('internal_loans', {})
            self._customer_connections = data.get('customer_connections', {})
            self._foundation_ledger = data.get('ledger', {})
            self._integrity_history = data.get('integrity_history', {})
            self._billing_integration_records = data.get('billing_integration', {})

            # Normalize loaded records to include expected defaults.
            self._initialize_foundation_state_defaults()
            
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
                'asset_transactions': self._asset_transactions,
                'liability_records': self._liability_records,
                'internal_loans': self._internal_loans,
                'customer_connections': self._customer_connections,
                'ledger': self._foundation_ledger,
                'integrity_history': self._integrity_history,
                'billing_integration': self._billing_integration_records
            }

            if self._persistence_service:
                is_valid, issues = self._persistence_service.validate_data_integrity(data)
                if not is_valid:
                    logger.warning("Foundation persistence validation issues: %s", "; ".join(issues[:8]))
            
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
                'activities': self._activities,
                'asset_transactions': self._asset_transactions,
                'liability_records': self._liability_records,
                'internal_loans': self._internal_loans,
                'customer_connections': self._customer_connections,
                'ledger': self._foundation_ledger,
                'integrity_history': self._integrity_history
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
            'total_asset_value': 0.0,
            'total_liability_value': 0.0,
            'net_equity_value': 0.0,
            'total_internal_debt': 0.0,
            'total_internal_credit': 0.0,
            'last_integrity_check_at': None,
            'integrity_last_status': 'unknown',
            'integrity_issue_count': 0,
            'last_balance_sheet_at': None,
            'analytics': {},
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
        self._ensure_foundation_financial_defaults(foundation)
        
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
        self._touch_customer_connection(foundation_id, request.founder_id, role='founder')
        
        # Create default funds
        self._create_default_funds(foundation_id)
        
        # Log activity
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="foundation_created",
            actor_id=request.founder_id,
            details={"name": request.name, "type": request.foundation_type}
        )
        self._record_ledger_entry(
            foundation_id=foundation_id,
            category="foundation",
            action="created",
            actor_id=request.founder_id,
            reference_id=foundation_id,
            payload={"name": request.name, "foundation_type": request.foundation_type},
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
            invitation['updated_at'] = datetime.now(timezone.utc).isoformat()
            self._persist(create_backup=False)
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
        options: Optional[List[str]] = None,
        proposal_payload: Optional[Dict[str, Any]] = None
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
            'proposal_payload': json.dumps(proposal_payload or {}),
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
                "requires_approval": requires_admin,
                "proposal_type": proposal_type
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
        for field in ['outlines', 'options', 'option_votes', 'decision_record', 'proposal_payload']:
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
                for field in ['outlines', 'options', 'option_votes', 'proposal_payload']:
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
                    for field in ['outlines', 'options', 'option_votes', 'decision_record', 'proposal_payload']:
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

        # Governance automation: execute supported proposal payloads after approval.
        if vote.get('status') == 'passed':
            execution_result = self._execute_vote_outcome(vote)
            if execution_result:
                decision_record['execution_result'] = execution_result
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

    def _execute_vote_outcome(self, vote: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute structured governance proposals once vote passes.

        Supported proposal_type values:
        - asset_purchase / asset_sale
        - liability_open
        - internal_loan
        """
        proposal_type = str(vote.get("proposal_type", "")).strip().lower()
        payload_raw = vote.get("proposal_payload")
        payload: Dict[str, Any] = {}
        if isinstance(payload_raw, str) and payload_raw:
            try:
                payload = json.loads(payload_raw)
            except Exception:
                payload = {}
        elif isinstance(payload_raw, dict):
            payload = payload_raw

        if proposal_type in {"asset_purchase", "asset_sale"}:
            transaction_type = "buy" if proposal_type == "asset_purchase" else "sell"
            result = self.record_asset_transaction(
                foundation_id=vote["foundation_id"],
                actor_id="system",
                asset_symbol=str(payload.get("asset_symbol") or payload.get("symbol") or "ASSET"),
                asset_name=str(payload.get("asset_name") or payload.get("name") or "Governance Asset"),
                asset_type=str(payload.get("asset_type") or "financial"),
                transaction_type=transaction_type,
                amount=_safe_float(payload.get("amount"), 0.0),
                quantity=_safe_float(payload.get("quantity"), 0.0),
                unit_price=_safe_float(payload.get("unit_price"), 0.0) if payload.get("unit_price") is not None else None,
                notes=str(payload.get("notes") or f"Executed from vote {vote.get('id')}"),
                metadata={"vote_id": vote.get("id"), "proposal_type": proposal_type},
                enforce_role_check=False,
            )
            return {"proposal_type": proposal_type, "result": result}

        if proposal_type == "liability_open":
            result = self.record_liability(
                foundation_id=vote["foundation_id"],
                actor_id="system",
                liability_type=str(payload.get("liability_type") or "governance_debt"),
                amount=_safe_float(payload.get("amount"), 0.0),
                creditor_id=payload.get("creditor_id"),
                debtor_id=payload.get("debtor_id") or vote.get("foundation_id"),
                due_date=payload.get("due_date"),
                notes=str(payload.get("notes") or f"Executed from vote {vote.get('id')}"),
                metadata={"vote_id": vote.get("id"), "proposal_type": proposal_type},
                enforce_role_check=False,
            )
            return {"proposal_type": proposal_type, "result": result}

        if proposal_type == "internal_loan":
            result = self.lend_funds(
                foundation_id=vote["foundation_id"],
                lender_user_id=str(payload.get("lender_user_id") or ""),
                borrower_user_id=str(payload.get("borrower_user_id") or ""),
                amount=_safe_float(payload.get("amount"), 0.0),
                actor_id="system",
                interest_rate=_safe_float(payload.get("interest_rate"), 0.0),
                due_days=_safe_int(payload.get("due_days"), 30),
                notes=str(payload.get("notes") or f"Executed from vote {vote.get('id')}"),
            )
            return {"proposal_type": proposal_type, "result": result}

        return {"proposal_type": proposal_type or "none", "result": "no_execution_handler"}
    
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
        details_payload = details or {}
        activity = {
            'id': activity_id,
            'foundation_id': foundation_id,
            'activity_type': activity_type,
            'actor_id': actor_id,
            'details': json.dumps(details_payload),
            'ip_address': ip_address,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        self._activities[activity_id] = activity

        category_map = {
            "foundation": {
                "foundation_created", "foundation_activated", "foundation_rejected",
                "foundation_dissolved", "pipeline_processed"
            },
            "membership": {
                "member_joined", "member_approved", "member_rejected",
                "member_removed", "member_role_changed", "member_details_updated",
                "member_left"
            },
            "invitation": {"invitation_created"},
            "governance": {"vote_created", "vote_cast", "vote_closed", "vote_approved", "vote_rejected"},
            "claims": {"claim_submitted", "claim_approved", "claim_rejected"},
            "financial": {
                "contribution_made", "asset_recorded", "liability_recorded",
                "internal_loan_created", "internal_loan_settled"
            },
        }
        category = "activity"
        for bucket, actions in category_map.items():
            if activity_type in actions:
                category = bucket
                break

        amount = _safe_float(details_payload.get("amount"))
        reference_id = (
            details_payload.get("vote_id")
            or details_payload.get("claim_id")
            or details_payload.get("contribution_id")
            or details_payload.get("asset_id")
            or details_payload.get("liability_id")
            or details_payload.get("loan_id")
            or details_payload.get("foundation_id")
        )
        self._record_ledger_entry(
            foundation_id=foundation_id,
            category=category,
            action=activity_type,
            actor_id=actor_id or "system",
            amount=amount,
            reference_id=reference_id,
            payload=details_payload,
        )

        # Maintain relationship graph on membership operations.
        member_user_id = details_payload.get("member_id") or actor_id
        if activity_type in {
            "member_joined", "member_approved", "member_role_changed",
            "member_details_updated", "foundation_created"
        } and member_user_id:
            role = details_payload.get("new_role")
            if not role:
                member_record = self._get_member_by_user(foundation_id, str(member_user_id))
                role = member_record.get("role") if member_record else None
            self._touch_customer_connection(foundation_id, str(member_user_id), role=role)

        if activity_type in {
            "contribution_made", "claim_approved", "asset_recorded",
            "liability_recorded", "internal_loan_created", "internal_loan_settled"
        }:
            self._reconcile_foundation_totals(foundation_id, update_timestamp=True)

        # Persist after each mutation activity to guarantee record durability.
        self._persist(create_backup=False)
    
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

        balance_sheet = self.get_foundation_balance_sheet(foundation_id)
        assets_total = _safe_float(balance_sheet.get('assets', {}).get('total_assets'))
        liabilities_total = _safe_float(balance_sheet.get('liabilities', {}).get('total_liabilities'))
        equity_total = _safe_float(balance_sheet.get('equity', {}).get('net_equity'))
        
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
                "available_for_claims": foundation['total_fund_balance'] * (1 - foundation.get('reserve_percentage', 20) / 100),
                "assets_total": assets_total,
                "liabilities_total": liabilities_total,
                "equity_total": equity_total
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
            "balance_sheet": balance_sheet if balance_sheet.get("success") else None,
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
        balance_sheet = self.get_foundation_balance_sheet(foundation_id)
        insights = self.get_foundation_bi_ai_insights(foundation_id, lookback_days=180)
        connections = self.get_foundation_connections(foundation_id)
        active_loans = [
            loan for loan in self._internal_loans.values()
            if loan.get("foundation_id") == foundation_id and loan.get("status") in {"active", "past_due"}
        ]
        assets = [
            tx for tx in self._asset_transactions.values()
            if tx.get("foundation_id") == foundation_id and tx.get("status") == "active"
        ]
        liabilities = [
            item for item in self._liability_records.values()
            if item.get("foundation_id") == foundation_id and item.get("status") in {"open", "active", "past_due"}
        ]
        
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
            "balance_sheet": balance_sheet if balance_sheet.get("success") else None,
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
            "assets": {
                "transactions_count": len(assets),
                "total_value": round(sum(_safe_float(tx.get("net_amount")) for tx in assets), 2),
            },
            "liabilities": {
                "count": len(liabilities),
                "total_outstanding": round(
                    sum(_safe_float(item.get("outstanding_amount", item.get("amount"))) for item in liabilities),
                    2
                ),
            },
            "internal_loans": {
                "active_count": len(active_loans),
                "total_outstanding": round(
                    sum(_safe_float(loan.get("outstanding_amount")) for loan in active_loans),
                    2
                ),
            },
            "connections": connections.get("totals", {}),
            "bi_ai_insights": insights if insights.get("success") else None,
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
    
    # ========== COMPREHENSIVE NFT LEDGER ==========
    
    def get_comprehensive_ledger(
        self,
        user_id: str = None,
        foundation_id: str = None,
        limit: int = 100,
        include_all_types: bool = True
    ) -> Dict[str, Any]:
        """
        Get comprehensive NFT ledger with all transaction types.
        
        Returns a complete audit trail of all foundation activities including:
        - Foundation creations
        - New member joins
        - Contributions/Deposits
        - Vote creations and results
        - Claims submissions and approvals
        - Invitations
        - Role changes
        - Pipeline transitions
        
        Args:
            user_id: Filter by user (show only foundations user belongs to)
            foundation_id: Filter by specific foundation
            limit: Maximum entries to return
            include_all_types: Include all transaction types
            
        Returns:
            Comprehensive ledger data with transactions and statistics
        """
        transactions = []
        
        # Determine which foundations to include
        if foundation_id:
            foundation_ids = [foundation_id]
        elif user_id:
            user_foundations = self.get_user_foundations(user_id)
            foundation_ids = [f['id'] for f in user_foundations]
        else:
            foundation_ids = list(self._foundations.keys())
        
        # Collect all activities from relevant foundations
        for fnd_id in foundation_ids:
            foundation = self._foundations.get(fnd_id)
            if not foundation:
                continue
            
            foundation_name = foundation['name']
            
            # Add activities
            for activity in self._activities.values():
                if activity['foundation_id'] == fnd_id:
                    try:
                        details = json.loads(activity['details']) if isinstance(activity['details'], str) else activity['details']
                    except:
                        details = {}
                    
                    tx_type = activity['activity_type']
                    
                    # Map activity types to ledger categories
                    category_map = {
                        'foundation_created': ('creation', '🏛️', 'Foundation Created'),
                        'foundation_activated': ('activation', '✅', 'Foundation Activated'),
                        'foundation_rejected': ('rejection', '❌', 'Foundation Rejected'),
                        'foundation_dissolved': ('dissolution', '🔚', 'Foundation Dissolved'),
                        'pipeline_processed': ('pipeline', '📋', 'Pipeline Updated'),
                        'member_joined': ('membership', '👤', 'New Member Joined'),
                        'member_approved': ('membership', '✅', 'Member Approved'),
                        'member_rejected': ('membership', '❌', 'Member Rejected'),
                        'member_removed': ('membership', '🚫', 'Member Removed'),
                        'member_role_changed': ('membership', '🔄', 'Role Changed'),
                        'invitation_created': ('invitation', '📨', 'Invitation Created'),
                        'contribution_made': ('contribution', '💰', 'Contribution Made'),
                        'vote_created': ('vote', '🗳️', 'Vote Created'),
                        'vote_cast': ('vote', '✋', 'Vote Cast'),
                        'vote_closed': ('vote', '📊', 'Vote Closed'),
                        'vote_approved': ('vote', '✅', 'Vote Approved'),
                        'claim_submitted': ('claim', '📝', 'Claim Submitted'),
                        'claim_approved': ('claim', '✅', 'Claim Approved'),
                        'claim_rejected': ('claim', '❌', 'Claim Rejected'),
                        'fund_created': ('fund', '📁', 'Fund Created'),
                        'asset_recorded': ('asset', '📈', 'Asset Transaction'),
                        'liability_recorded': ('liability', '📉', 'Liability Recorded'),
                        'internal_loan_created': ('loan', '🤝', 'Internal Loan Created'),
                        'internal_loan_settled': ('loan', '✅', 'Internal Loan Settled'),
                    }
                    
                    category, icon, action = category_map.get(tx_type, ('other', '📋', tx_type.replace('_', ' ').title()))
                    
                    # Generate a transaction hash for NFT verification
                    tx_hash = hashlib.sha256(
                        f"{activity['id']}{activity['timestamp']}{fnd_id}{tx_type}".encode()
                    ).hexdigest()[:16].upper()
                    
                    # Build description based on activity type
                    description = action
                    amount = None
                    
                    if 'amount' in details:
                        amount = details['amount']
                        description = f"{action}: ${amount:.2f}"
                    if 'name' in details:
                        description = f"{action}: {details['name']}"
                    if 'result' in details:
                        description = f"{action} - Result: {details['result']}"
                    if 'old_role' in details and 'new_role' in details:
                        description = f"Role changed: {details['old_role']} → {details['new_role']}"
                    
                    transactions.append({
                        'id': activity['id'],
                        'transaction_hash': tx_hash,
                        'foundation_id': fnd_id,
                        'foundation_name': foundation_name,
                        'category': category,
                        'type': tx_type,
                        'icon': icon,
                        'action': action,
                        'description': description,
                        'actor_id': activity['actor_id'],
                        'amount': amount,
                        'details': details,
                        'timestamp': activity['timestamp'],
                        'verified': True,
                        'block_number': abs(hash(activity['id'])) % 1000000  # Simulated block number
                    })

            # Add explicit ledger records for non-activity financial operations.
            for entry in self._foundation_ledger.values():
                if entry.get('foundation_id') != fnd_id:
                    continue
                if any(tx.get('id') == entry.get('id') for tx in transactions):
                    continue
                transactions.append({
                    'id': entry.get('id'),
                    'transaction_hash': entry.get('entry_hash') or hashlib.sha256(
                        f"{entry.get('id')}:{entry.get('timestamp')}".encode()
                    ).hexdigest()[:16].upper(),
                    'foundation_id': fnd_id,
                    'foundation_name': foundation_name,
                    'category': entry.get('category', 'ledger'),
                    'type': entry.get('action', 'ledger_entry'),
                    'icon': '🧾',
                    'action': entry.get('action', 'Ledger Entry').replace('_', ' ').title(),
                    'description': entry.get('action', 'ledger_entry').replace('_', ' ').title(),
                    'actor_id': entry.get('actor_id'),
                    'amount': _safe_float(entry.get('amount')),
                    'details': entry.get('payload') or {},
                    'timestamp': entry.get('timestamp'),
                    'verified': True,
                    'block_number': abs(hash(entry.get('id'))) % 1000000
                })
        
        # Sort by timestamp (newest first)
        transactions.sort(key=lambda x: x['timestamp'], reverse=True)
        
        # Calculate statistics
        stats = {
            'total_transactions': len(transactions),
            'by_category': {},
            'by_foundation': {},
            'total_contributions': 0,
            'total_claims_paid': 0,
            'total_votes': 0,
            'total_members_joined': 0
        }
        
        for tx in transactions:
            cat = tx['category']
            stats['by_category'][cat] = stats['by_category'].get(cat, 0) + 1
            
            fnd_name = tx['foundation_name']
            stats['by_foundation'][fnd_name] = stats['by_foundation'].get(fnd_name, 0) + 1
            
            if tx['type'] == 'contribution_made' and tx['amount']:
                stats['total_contributions'] += tx['amount']
            elif tx['type'] == 'claim_approved' and tx['amount']:
                stats['total_claims_paid'] += tx['amount']
            elif tx['type'] == 'vote_created':
                stats['total_votes'] += 1
            elif tx['type'] == 'member_joined':
                stats['total_members_joined'] += 1
        
        return {
            'transactions': transactions[:limit],
            'statistics': stats,
            'total_count': len(transactions),
            'returned_count': min(len(transactions), limit),
            'generated_at': datetime.now(timezone.utc).isoformat()
        }
    
    def get_vote_statistics(
        self,
        foundation_id: str = None,
        user_id: str = None
    ) -> Dict[str, Any]:
        """
        Get comprehensive voting statistics.
        
        Args:
            foundation_id: Filter by foundation
            user_id: Filter by user's foundations
            
        Returns:
            Detailed voting statistics and analytics
        """
        if foundation_id:
            foundation_ids = [foundation_id]
        elif user_id:
            user_foundations = self.get_user_foundations(user_id)
            foundation_ids = [f['id'] for f in user_foundations]
        else:
            foundation_ids = list(self._foundations.keys())
        
        all_votes = []
        for fnd_id in foundation_ids:
            votes = self.get_all_votes(fnd_id, limit=1000)
            for vote in votes:
                vote['foundation_name'] = self._foundations.get(fnd_id, {}).get('name', 'Unknown')
            all_votes.extend(votes)
        
        # Calculate statistics
        total_votes = len(all_votes)
        passed_votes = [v for v in all_votes if v['status'] == 'passed']
        failed_votes = [v for v in all_votes if v['status'] == 'failed']
        open_votes = [v for v in all_votes if v['status'] == 'open']
        pending_votes = [v for v in all_votes if v['status'] == 'pending_approval']
        
        # Participation statistics
        completed_votes = [v for v in all_votes if v['status'] in ['passed', 'failed']]
        total_participants = sum(
            v.get('votes_for', 0) + v.get('votes_against', 0) + v.get('votes_abstain', 0)
            for v in completed_votes
        )
        
        avg_participation = total_participants / max(len(completed_votes), 1)
        
        # Vote type breakdown
        type_breakdown = {}
        for vote in all_votes:
            vtype = vote.get('proposal_type', 'general')
            if vtype not in type_breakdown:
                type_breakdown[vtype] = {'total': 0, 'passed': 0, 'failed': 0}
            type_breakdown[vtype]['total'] += 1
            if vote['status'] == 'passed':
                type_breakdown[vtype]['passed'] += 1
            elif vote['status'] == 'failed':
                type_breakdown[vtype]['failed'] += 1
        
        # Recent votes with decision records
        recent_votes = []
        for vote in sorted(all_votes, key=lambda x: x.get('created_at', ''), reverse=True)[:10]:
            decision_record = vote.get('decision_record')
            if isinstance(decision_record, str):
                try:
                    decision_record = json.loads(decision_record)
                except:
                    decision_record = {}
            
            recent_votes.append({
                'id': vote['id'],
                'title': vote['title'],
                'foundation_name': vote.get('foundation_name'),
                'proposal_type': vote.get('proposal_type'),
                'status': vote['status'],
                'result': vote.get('result'),
                'votes_for': vote.get('votes_for', 0),
                'votes_against': vote.get('votes_against', 0),
                'votes_abstain': vote.get('votes_abstain', 0),
                'threshold': vote.get('threshold', 0.5),
                'participation_rate': decision_record.get('participation_rate') if decision_record else None,
                'approval_rate': decision_record.get('approval_rate') if decision_record else None,
                'created_at': vote.get('created_at'),
                'closed_at': vote.get('closed_at')
            })
        
        return {
            'summary': {
                'total_votes': total_votes,
                'passed': len(passed_votes),
                'failed': len(failed_votes),
                'open': len(open_votes),
                'pending_approval': len(pending_votes),
                'pass_rate': len(passed_votes) / max(len(completed_votes), 1) * 100,
                'average_participation': round(avg_participation, 1)
            },
            'type_breakdown': type_breakdown,
            'recent_votes': recent_votes,
            'by_foundation': {
                fnd_id: {
                    'name': self._foundations.get(fnd_id, {}).get('name'),
                    'total': len([v for v in all_votes if v.get('foundation_id') == fnd_id]),
                    'passed': len([v for v in passed_votes if v.get('foundation_id') == fnd_id]),
                    'open': len([v for v in open_votes if v.get('foundation_id') == fnd_id])
                }
                for fnd_id in foundation_ids
            },
            'generated_at': datetime.now(timezone.utc).isoformat()
        }

    # ========== FOUNDATION FINANCIAL INTELLIGENCE ==========

    def _require_active_member(
        self,
        foundation_id: str,
        user_id: str,
        allowed_roles: Optional[set] = None
    ) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]]]:
        """Check membership and role constraints for financial operations."""
        member = self._get_member_by_user(foundation_id, user_id)
        if not member:
            return False, "You are not a member of this foundation", None
        if member.get("status") != "active":
            return False, "Only active members can perform this operation", None
        if allowed_roles and member.get("role") not in allowed_roles:
            return False, "Insufficient permissions for this operation", None
        return True, None, member

    def _apply_cash_delta_to_funds(self, foundation_id: str, cash_delta: float) -> bool:
        """Apply cash movement to fund balances while keeping totals consistent."""
        if abs(cash_delta) < 0.000001:
            return True

        funds = [
            fund for fund in self._funds.values()
            if fund.get("foundation_id") == foundation_id and fund.get("status") == "active"
        ]
        if not funds:
            return False

        now_iso = datetime.now(timezone.utc).isoformat()
        if cash_delta > 0:
            target = sorted(funds, key=lambda f: _safe_float(f.get("balance")), reverse=True)[0]
            target["balance"] = round(_safe_float(target.get("balance")) + cash_delta, 2)
            target["last_activity"] = now_iso
            target["updated_at"] = now_iso
            return True

        # cash_delta < 0: consume from funds with highest balance first.
        remaining = round(abs(cash_delta), 2)
        for fund in sorted(funds, key=lambda f: _safe_float(f.get("balance")), reverse=True):
            current_balance = round(_safe_float(fund.get("balance")), 2)
            if current_balance <= 0:
                continue
            deduct = min(current_balance, remaining)
            fund["balance"] = round(current_balance - deduct, 2)
            fund["last_activity"] = now_iso
            fund["updated_at"] = now_iso
            remaining = round(remaining - deduct, 2)
            if remaining <= 0:
                break
        return remaining <= 0

    def record_asset_transaction(
        self,
        *,
        foundation_id: str,
        actor_id: str,
        asset_symbol: str,
        asset_name: str,
        asset_type: str,
        transaction_type: str,
        amount: float,
        quantity: float = 0.0,
        unit_price: Optional[float] = None,
        notes: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        enforce_role_check: bool = True,
    ) -> Dict[str, Any]:
        """Record a foundation asset movement (buy/sell/revalue/adjust)."""
        foundation = self._foundations.get(foundation_id)
        if not foundation:
            return {"success": False, "error": "Foundation not found"}

        if enforce_role_check:
            allowed, error_message, _ = self._require_active_member(
                foundation_id, actor_id, allowed_roles={"founder", "admin"}
            )
            if not allowed:
                return {"success": False, "error": error_message}

        normalized_tx = str(transaction_type or "").strip().lower()
        if normalized_tx not in {"buy", "sell", "revalue", "adjust"}:
            return {"success": False, "error": "Invalid transaction_type (buy/sell/revalue/adjust)"}

        base_amount = round(abs(_safe_float(amount)), 2)
        if base_amount <= 0:
            return {"success": False, "error": "Amount must be positive"}

        cash_delta = 0.0
        net_amount = base_amount
        if normalized_tx == "buy":
            cash_delta = -base_amount
        elif normalized_tx == "sell":
            cash_delta = base_amount
            net_amount = -base_amount
        elif normalized_tx == "revalue":
            # Revaluation affects carrying value without moving cash.
            net_amount = _safe_float(amount)
            cash_delta = 0.0
        elif normalized_tx == "adjust":
            net_amount = _safe_float(amount)
            cash_delta = 0.0

        if cash_delta < 0 and _safe_float(foundation.get("total_fund_balance")) + cash_delta < -0.01:
            return {"success": False, "error": "Insufficient cash balance for asset purchase"}
        if cash_delta != 0 and not self._apply_cash_delta_to_funds(foundation_id, cash_delta):
            return {"success": False, "error": "Unable to apply cash movement to foundation funds"}

        asset_id = generate_id("ASSET")
        asset_record = {
            "id": asset_id,
            "foundation_id": foundation_id,
            "asset_symbol": str(asset_symbol or "UNSPECIFIED").upper(),
            "asset_name": str(asset_name or asset_symbol or "Asset"),
            "asset_type": str(asset_type or "financial"),
            "transaction_type": normalized_tx,
            "amount": base_amount,
            "net_amount": round(_safe_float(net_amount), 2),
            "quantity": round(_safe_float(quantity), 8),
            "unit_price": round(_safe_float(unit_price), 8) if unit_price is not None else None,
            "currency": foundation.get("currency", "USD"),
            "status": "active",
            "notes": notes,
            "metadata": metadata or {},
            "recorded_by": actor_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._asset_transactions[asset_id] = asset_record

        self._log_activity(
            foundation_id=foundation_id,
            activity_type="asset_recorded",
            actor_id=actor_id,
            details={
                "asset_id": asset_id,
                "asset_symbol": asset_record["asset_symbol"],
                "transaction_type": normalized_tx,
                "amount": base_amount,
                "cash_delta": cash_delta,
            },
        )
        reconcile = self._reconcile_foundation_totals(foundation_id)
        return {
            "success": True,
            "asset_id": asset_id,
            "transaction": asset_record,
            "reconciled": reconcile,
        }

    def record_liability(
        self,
        *,
        foundation_id: str,
        actor_id: str,
        liability_type: str,
        amount: float,
        creditor_id: Optional[str] = None,
        debtor_id: Optional[str] = None,
        due_date: Optional[str] = None,
        notes: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        enforce_role_check: bool = True,
    ) -> Dict[str, Any]:
        """Record a liability/debt item in the foundation balance sheet."""
        foundation = self._foundations.get(foundation_id)
        if not foundation:
            return {"success": False, "error": "Foundation not found"}

        if enforce_role_check:
            allowed, error_message, _ = self._require_active_member(
                foundation_id, actor_id, allowed_roles={"founder", "admin"}
            )
            if not allowed:
                return {"success": False, "error": error_message}

        principal = round(abs(_safe_float(amount)), 2)
        if principal <= 0:
            return {"success": False, "error": "Liability amount must be positive"}

        liability_id = generate_id("LIAB")
        record = {
            "id": liability_id,
            "foundation_id": foundation_id,
            "liability_type": str(liability_type or "general").lower(),
            "amount": principal,
            "outstanding_amount": principal,
            "creditor_id": creditor_id,
            "debtor_id": debtor_id,
            "due_date": due_date,
            "status": "open",
            "notes": notes,
            "metadata": metadata or {},
            "recorded_by": actor_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._liability_records[liability_id] = record

        self._log_activity(
            foundation_id=foundation_id,
            activity_type="liability_recorded",
            actor_id=actor_id,
            details={
                "liability_id": liability_id,
                "liability_type": record["liability_type"],
                "amount": principal,
            },
        )
        reconcile = self._reconcile_foundation_totals(foundation_id)
        return {
            "success": True,
            "liability_id": liability_id,
            "liability": record,
            "reconciled": reconcile,
        }

    def lend_funds(
        self,
        *,
        foundation_id: str,
        lender_user_id: str,
        borrower_user_id: str,
        amount: float,
        actor_id: Optional[str] = None,
        interest_rate: float = 0.0,
        due_days: int = 30,
        notes: str = "",
    ) -> Dict[str, Any]:
        """Create an internal member-to-member loan (lend$$ operation)."""
        foundation = self._foundations.get(foundation_id)
        if not foundation:
            return {"success": False, "error": "Foundation not found"}
        if lender_user_id == borrower_user_id:
            return {"success": False, "error": "Lender and borrower must be different members"}

        principal = round(abs(_safe_float(amount)), 2)
        if principal <= 0:
            return {"success": False, "error": "Loan amount must be positive"}

        lender_ok, lender_err, lender_member = self._require_active_member(foundation_id, lender_user_id)
        if not lender_ok:
            return {"success": False, "error": lender_err}
        borrower_ok, borrower_err, borrower_member = self._require_active_member(foundation_id, borrower_user_id)
        if not borrower_ok:
            return {"success": False, "error": borrower_err}

        actor = actor_id or lender_user_id
        actor_member = self._get_member_by_user(foundation_id, actor)
        if actor not in {lender_user_id, borrower_user_id} and (
            not actor_member or actor_member.get("role") not in {"founder", "admin"}
        ):
            return {"success": False, "error": "Only lender, borrower, founder, or admin can create this loan"}

        loan_id = generate_id("LOAN")
        created_at = datetime.now(timezone.utc)
        due_date = (created_at + timedelta(days=max(1, _safe_int(due_days, 30)))).isoformat()
        loan_record = {
            "id": loan_id,
            "foundation_id": foundation_id,
            "lender_member_id": lender_member.get("id"),
            "lender_user_id": lender_user_id,
            "borrower_member_id": borrower_member.get("id"),
            "borrower_user_id": borrower_user_id,
            "principal_amount": principal,
            "outstanding_amount": principal,
            "interest_rate": round(max(0.0, _safe_float(interest_rate)), 4),
            "due_date": due_date,
            "status": "active",
            "notes": notes,
            "created_by": actor,
            "created_at": created_at.isoformat(),
            "updated_at": created_at.isoformat(),
            "settlements": [],
        }
        self._internal_loans[loan_id] = loan_record

        liability_result = self.record_liability(
            foundation_id=foundation_id,
            actor_id=actor,
            liability_type="internal_loan",
            amount=principal,
            creditor_id=lender_user_id,
            debtor_id=borrower_user_id,
            due_date=due_date,
            notes=notes,
            metadata={"loan_id": loan_id},
            enforce_role_check=False,
        )
        if liability_result.get("success"):
            loan_record["liability_id"] = liability_result.get("liability_id")

        self._log_activity(
            foundation_id=foundation_id,
            activity_type="internal_loan_created",
            actor_id=actor,
            details={
                "loan_id": loan_id,
                "lender_user_id": lender_user_id,
                "borrower_user_id": borrower_user_id,
                "amount": principal,
                "interest_rate": loan_record["interest_rate"],
                "liability_id": loan_record.get("liability_id"),
            },
        )
        return {
            "success": True,
            "loan_id": loan_id,
            "loan": loan_record,
        }

    def borrow_funds(
        self,
        *,
        foundation_id: str,
        borrower_user_id: str,
        lender_user_id: str,
        amount: float,
        actor_id: Optional[str] = None,
        interest_rate: float = 0.0,
        due_days: int = 30,
        notes: str = "",
    ) -> Dict[str, Any]:
        """Create an internal member-to-member loan (borrow$$ operation)."""
        return self.lend_funds(
            foundation_id=foundation_id,
            lender_user_id=lender_user_id,
            borrower_user_id=borrower_user_id,
            amount=amount,
            actor_id=actor_id or borrower_user_id,
            interest_rate=interest_rate,
            due_days=due_days,
            notes=notes,
        )

    def settle_internal_loan(
        self,
        *,
        foundation_id: str,
        loan_id: str,
        payer_user_id: str,
        amount: float,
        notes: str = "",
    ) -> Dict[str, Any]:
        """Settle part or all of an internal loan."""
        loan = self._internal_loans.get(loan_id)
        if not loan or loan.get("foundation_id") != foundation_id:
            return {"success": False, "error": "Loan not found"}
        if loan.get("status") not in {"active", "past_due"}:
            return {"success": False, "error": f"Loan cannot be settled in status {loan.get('status')}"}

        payer_member = self._get_member_by_user(foundation_id, payer_user_id)
        if payer_user_id != loan.get("borrower_user_id") and (
            not payer_member or payer_member.get("role") not in {"founder", "admin"}
        ):
            return {"success": False, "error": "Only borrower, founder, or admin can settle this loan"}

        payment_amount = round(abs(_safe_float(amount)), 2)
        if payment_amount <= 0:
            return {"success": False, "error": "Settlement amount must be positive"}

        outstanding_before = round(_safe_float(loan.get("outstanding_amount")), 2)
        if payment_amount - outstanding_before > 0.01:
            return {"success": False, "error": "Settlement amount exceeds outstanding balance"}

        outstanding_after = round(outstanding_before - payment_amount, 2)
        loan["outstanding_amount"] = outstanding_after
        loan["updated_at"] = datetime.now(timezone.utc).isoformat()
        settlements = list(loan.get("settlements") or [])
        settlements.append(
            {
                "settled_by": payer_user_id,
                "amount": payment_amount,
                "notes": notes,
                "settled_at": loan["updated_at"],
            }
        )
        loan["settlements"] = settlements
        if outstanding_after <= 0.01:
            loan["status"] = "settled"
            loan["outstanding_amount"] = 0.0
            loan["settled_at"] = loan["updated_at"]

        liability_id = loan.get("liability_id")
        if liability_id and liability_id in self._liability_records:
            liability = self._liability_records[liability_id]
            liability["outstanding_amount"] = loan["outstanding_amount"]
            liability["updated_at"] = loan["updated_at"]
            if loan.get("status") == "settled":
                liability["status"] = "closed"

        self._log_activity(
            foundation_id=foundation_id,
            activity_type="internal_loan_settled",
            actor_id=payer_user_id,
            details={
                "loan_id": loan_id,
                "amount": payment_amount,
                "remaining": loan["outstanding_amount"],
                "liability_id": liability_id,
            },
        )
        return {"success": True, "loan": loan}

    def get_foundation_balance_sheet(self, foundation_id: str) -> Dict[str, Any]:
        """Build a foundation-level balance sheet (assets/liabilities/equity)."""
        foundation = self._foundations.get(foundation_id)
        if not foundation:
            return {"success": False, "error": "Foundation not found"}

        self._ensure_foundation_financial_defaults(foundation)
        self._reconcile_foundation_totals(foundation_id)

        cash_assets = round(_safe_float(foundation.get("total_fund_balance")), 2)
        asset_positions: Dict[str, Dict[str, Any]] = {}
        for tx in self._asset_transactions.values():
            if tx.get("foundation_id") != foundation_id or tx.get("status") != "active":
                continue
            symbol = tx.get("asset_symbol", "UNSPECIFIED")
            position = asset_positions.setdefault(
                symbol,
                {
                    "asset_symbol": symbol,
                    "asset_name": tx.get("asset_name", symbol),
                    "asset_type": tx.get("asset_type", "financial"),
                    "net_quantity": 0.0,
                    "net_value": 0.0,
                    "transactions": 0,
                },
            )
            position["net_quantity"] = round(position["net_quantity"] + _safe_float(tx.get("quantity")), 8)
            position["net_value"] = round(position["net_value"] + _safe_float(tx.get("net_amount")), 2)
            position["transactions"] += 1

        investment_assets = round(sum(pos["net_value"] for pos in asset_positions.values()), 2)
        liability_items = []
        for liability in self._liability_records.values():
            if liability.get("foundation_id") != foundation_id:
                continue
            if liability.get("status") not in {"open", "active", "past_due"}:
                continue
            liability_items.append(
                {
                    "id": liability.get("id"),
                    "liability_type": liability.get("liability_type"),
                    "outstanding_amount": round(_safe_float(liability.get("outstanding_amount", liability.get("amount"))), 2),
                    "creditor_id": liability.get("creditor_id"),
                    "debtor_id": liability.get("debtor_id"),
                    "due_date": liability.get("due_date"),
                    "status": liability.get("status"),
                }
            )

        pending_claim_liability = round(
            sum(
                _safe_float(claim.get("amount_requested"))
                for claim in self._claims.values()
                if claim.get("foundation_id") == foundation_id and claim.get("status") in {"reviewing", "vote_open"}
            ),
            2
        )
        if pending_claim_liability > 0:
            liability_items.append(
                {
                    "id": f"PENDING-CLAIMS-{foundation_id}",
                    "liability_type": "pending_claims",
                    "outstanding_amount": pending_claim_liability,
                    "creditor_id": None,
                    "debtor_id": foundation_id,
                    "due_date": None,
                    "status": "open",
                }
            )

        total_liabilities = round(sum(_safe_float(item.get("outstanding_amount")) for item in liability_items), 2)
        total_assets = round(cash_assets + investment_assets, 2)
        equity = round(total_assets - total_liabilities, 2)

        balance_sheet = {
            "success": True,
            "foundation_id": foundation_id,
            "foundation_name": foundation.get("name"),
            "currency": foundation.get("currency", "USD"),
            "assets": {
                "cash": cash_assets,
                "investments": investment_assets,
                "positions": sorted(asset_positions.values(), key=lambda x: x["net_value"], reverse=True),
                "total_assets": total_assets,
            },
            "liabilities": {
                "items": liability_items,
                "total_liabilities": total_liabilities,
            },
            "equity": {
                "net_equity": equity,
                "solvency_ratio": round(total_assets / max(total_liabilities, 1.0), 4) if total_liabilities > 0 else 999.0,
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        foundation["total_asset_value"] = investment_assets
        foundation["total_liability_value"] = total_liabilities
        foundation["net_equity_value"] = equity
        foundation["last_balance_sheet_at"] = balance_sheet["generated_at"]
        return balance_sheet

    def get_foundation_bi_ai_insights(self, foundation_id: str, lookback_days: int = 90) -> Dict[str, Any]:
        """Return BI metrics + AI-style optimization recommendations for a foundation."""
        foundation = self._foundations.get(foundation_id)
        if not foundation:
            return {"success": False, "error": "Foundation not found"}

        balance_sheet = self.get_foundation_balance_sheet(foundation_id)
        if not balance_sheet.get("success"):
            return balance_sheet

        cutoff = datetime.now(timezone.utc) - timedelta(days=max(7, _safe_int(lookback_days, 90)))
        contribution_volume = 0.0
        contribution_count = 0
        claim_volume = 0.0
        claim_count = 0
        vote_count = 0
        votes_passed = 0
        for activity in self._activities.values():
            if activity.get("foundation_id") != foundation_id:
                continue
            try:
                ts = datetime.fromisoformat(str(activity.get("timestamp")).replace("Z", "+00:00"))
            except Exception:
                continue
            if ts < cutoff:
                continue
            activity_type = activity.get("activity_type")
            details = activity.get("details", {})
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except Exception:
                    details = {}
            if activity_type == "contribution_made":
                contribution_count += 1
                contribution_volume += _safe_float(details.get("amount"))
            elif activity_type == "claim_approved":
                claim_count += 1
                claim_volume += _safe_float(details.get("amount"))
            elif activity_type == "vote_closed":
                vote_count += 1
                if str(details.get("result", "")).startswith("passed") or details.get("result") == "passed":
                    votes_passed += 1

        total_assets = _safe_float(balance_sheet["assets"]["total_assets"])
        total_liabilities = _safe_float(balance_sheet["liabilities"]["total_liabilities"])
        reserve_ratio = round(
            _safe_float(foundation.get("reserve_percentage", 20.0)) / 100.0,
            4
        )
        claims_to_contributions = round(
            claim_volume / max(contribution_volume, 1.0),
            4
        )

        recommendations: List[str] = []
        if claims_to_contributions > 0.65:
            recommendations.append(
                "Increase reserve ratio or tighten auto-approve thresholds to reduce payout pressure."
            )
        if total_liabilities > total_assets * 0.55:
            recommendations.append(
                "Liabilities exceed 55% of assets; prioritize debt settlement and delay discretionary asset purchases."
            )
        if vote_count > 0 and (votes_passed / max(vote_count, 1)) < 0.35:
            recommendations.append(
                "Low governance pass rate detected; publish clearer proposal summaries before opening votes."
            )
        if not recommendations:
            recommendations.append(
                "Foundation financial health is stable. Continue monthly integrity checks and governance cadence."
            )

        health_score = 100.0
        health_score -= min(40.0, claims_to_contributions * 30.0)
        if total_assets > 0:
            health_score -= min(35.0, (total_liabilities / total_assets) * 35.0)
        health_score += min(10.0, contribution_count * 0.5)
        health_score = round(max(0.0, min(100.0, health_score)), 2)

        return {
            "success": True,
            "foundation_id": foundation_id,
            "lookback_days": max(7, _safe_int(lookback_days, 90)),
            "kpis": {
                "contribution_volume": round(contribution_volume, 2),
                "contribution_count": contribution_count,
                "claim_volume": round(claim_volume, 2),
                "claim_count": claim_count,
                "claims_to_contributions_ratio": claims_to_contributions,
                "governance_pass_rate": round((votes_passed / max(vote_count, 1)) * 100.0, 2) if vote_count else 0.0,
                "reserve_ratio": reserve_ratio,
                "total_assets": round(total_assets, 2),
                "total_liabilities": round(total_liabilities, 2),
                "net_equity": round(_safe_float(balance_sheet["equity"]["net_equity"]), 2),
                "health_score": health_score,
            },
            "recommendations": recommendations,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def validate_foundation_integrity(self, foundation_id: str, auto_correct: bool = False) -> Dict[str, Any]:
        """Validate and optionally fix a foundation's financial/governance integrity."""
        foundation = self._foundations.get(foundation_id)
        if not foundation:
            return {"success": False, "error": "Foundation not found"}

        issues: List[str] = []
        corrections: List[str] = []

        # Member count consistency
        active_members = sum(
            1 for member in self._members.values()
            if member.get("foundation_id") == foundation_id and member.get("status") == "active"
        )
        expected_members = _safe_int(foundation.get("current_members"), 0)
        if active_members != expected_members:
            issues.append(
                f"member_count_mismatch expected={expected_members} actual={active_members}"
            )
            if auto_correct:
                foundation["current_members"] = active_members
                corrections.append("current_members_reconciled")

        # Fund total consistency
        actual_fund_total = round(
            sum(
                _safe_float(fund.get("balance"))
                for fund in self._funds.values()
                if fund.get("foundation_id") == foundation_id and fund.get("status") == "active"
            ),
            2
        )
        expected_fund_total = round(_safe_float(foundation.get("total_fund_balance")), 2)
        if abs(actual_fund_total - expected_fund_total) > 0.01:
            issues.append(
                f"fund_balance_mismatch expected={expected_fund_total} actual={actual_fund_total}"
            )
            if auto_correct:
                foundation["total_fund_balance"] = actual_fund_total
                corrections.append("total_fund_balance_reconciled")

        # Internal loan linkage checks
        for loan in self._internal_loans.values():
            if loan.get("foundation_id") != foundation_id:
                continue
            borrower = self._get_member_by_user(foundation_id, str(loan.get("borrower_user_id")))
            lender = self._get_member_by_user(foundation_id, str(loan.get("lender_user_id")))
            if not borrower:
                issues.append(f"loan_{loan.get('id')}_borrower_missing")
            if not lender:
                issues.append(f"loan_{loan.get('id')}_lender_missing")

        reconcile = self._reconcile_foundation_totals(foundation_id)
        report_id = generate_id("FINT")
        report = {
            "id": report_id,
            "foundation_id": foundation_id,
            "is_valid": len(issues) == 0,
            "issues": issues,
            "corrections": corrections,
            "reconciled_totals": reconcile,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        self._integrity_history[report_id] = report

        foundation["last_integrity_check_at"] = report["checked_at"]
        foundation["integrity_last_status"] = "valid" if report["is_valid"] else "warning"
        foundation["integrity_issue_count"] = len(issues)
        if auto_correct and corrections:
            self._persist(create_backup=False)

        return {"success": True, "report": report}

    def validate_all_foundations_integrity(self, auto_correct: bool = False) -> Dict[str, Any]:
        """Run integrity validation across all foundations."""
        reports = []
        valid_count = 0
        for foundation_id in self._foundations.keys():
            result = self.validate_foundation_integrity(foundation_id, auto_correct=auto_correct)
            report = result.get("report", {})
            if report.get("is_valid"):
                valid_count += 1
            reports.append(report)

        return {
            "success": True,
            "total_foundations": len(reports),
            "valid_foundations": valid_count,
            "invalid_foundations": len(reports) - valid_count,
            "reports": reports,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_foundation_connections(self, foundation_id: str) -> Dict[str, Any]:
        """Return customer relation graph data for a foundation."""
        foundation = self._foundations.get(foundation_id)
        if not foundation:
            return {"success": False, "error": "Foundation not found"}

        nodes = []
        edges = []
        seen_nodes = set()
        members = self.get_foundation_members(foundation_id, include_pending=True)
        for member in members:
            customer_id = str(member.get("member_id"))
            node_id = f"cust:{customer_id}"
            seen_nodes.add(node_id)
            nodes.append(
                {
                    "id": node_id,
                    "customer_id": customer_id,
                    "display_name": member.get("display_name") or customer_id,
                    "role": member.get("role"),
                    "status": member.get("status"),
                }
            )

        for loan in self._internal_loans.values():
            if loan.get("foundation_id") != foundation_id:
                continue
            lender = f"cust:{loan.get('lender_user_id')}"
            borrower = f"cust:{loan.get('borrower_user_id')}"
            edges.append(
                {
                    "id": f"edge:{loan.get('id')}",
                    "source": lender,
                    "target": borrower,
                    "relationship": "internal_loan",
                    "amount": round(_safe_float(loan.get("outstanding_amount")), 2),
                    "status": loan.get("status"),
                }
            )

        return {
            "success": True,
            "foundation_id": foundation_id,
            "foundation_name": foundation.get("name"),
            "nodes": nodes,
            "edges": edges,
            "totals": {"nodes": len(nodes), "edges": len(edges)},
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def sync_foundations_to_seed_snapshot(
        self,
        *,
        seed_path: Optional[str] = None,
        auto_correct_integrity: bool = True,
    ) -> Dict[str, Any]:
        """
        Validate foundations and export seed snapshot with relations and finance data.
        """
        integrity = self.validate_all_foundations_integrity(auto_correct=auto_correct_integrity)
        workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_path = seed_path or os.path.join(workspace_root, "database", "foundation_seed_data.json")
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        foundation_items = []
        for foundation_id, foundation in self._foundations.items():
            balance_sheet = self.get_foundation_balance_sheet(foundation_id)
            insights = self.get_foundation_bi_ai_insights(foundation_id, lookback_days=180)
            members = self.get_foundation_members(foundation_id, include_pending=True)
            votes = self.get_all_votes(foundation_id, limit=500)
            claims = self.get_foundation_claims(foundation_id)
            activities = self.get_foundation_activities(foundation_id, limit=500)
            funds = self.get_foundation_funds(foundation_id)
            assets = [
                tx for tx in self._asset_transactions.values()
                if tx.get("foundation_id") == foundation_id
            ]
            liabilities = [
                liab for liab in self._liability_records.values()
                if liab.get("foundation_id") == foundation_id
            ]
            loans = [
                loan for loan in self._internal_loans.values()
                if loan.get("foundation_id") == foundation_id
            ]
            relations = self.get_foundation_connections(foundation_id)

            foundation_items.append(
                {
                    "foundation": foundation,
                    "funds": funds,
                    "members": members,
                    "votes": votes,
                    "claims": claims,
                    "activities": activities,
                    "assets": assets,
                    "liabilities": liabilities,
                    "internal_loans": loans,
                    "balance_sheet": balance_sheet,
                    "bi_ai_insights": insights,
                    "connections": relations,
                }
            )

        payload = {
            "version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "integrity_summary": integrity,
            "foundations": foundation_items,
            "counts": {
                "foundations": len(self._foundations),
                "members": len(self._members),
                "funds": len(self._funds),
                "contributions": len(self._contributions),
                "votes": len(self._votes),
                "claims": len(self._claims),
                "assets": len(self._asset_transactions),
                "liabilities": len(self._liability_records),
                "internal_loans": len(self._internal_loans),
                "connections": len(self._customer_connections),
                "ledger_entries": len(self._foundation_ledger),
            },
        }

        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)

        return {
            "success": True,
            "seed_path": output_path,
            "counts": payload["counts"],
            "integrity_summary": {
                "total_foundations": integrity.get("total_foundations", 0),
                "invalid_foundations": integrity.get("invalid_foundations", 0),
            },
        }
    
    def make_contribution_with_billing(
        self,
        foundation_id: str,
        fund_id: str,
        member_id: str,
        amount: float,
        payment_method: str = 'wallet',
        payment_reference: str = '',
        wallet_id: str = '',
        notes: str = ''
    ) -> Dict[str, Any]:
        """
        Make a contribution with full billing pipeline integration.
        
        This method:
        1. Validates the contribution
        2. Creates the contribution record
        3. Records to billing integration for dashboard
        4. Creates accounting records
        5. Updates the transaction ledger
        6. Persists all data
        
        Args:
            foundation_id: Foundation ID
            fund_id: Fund to contribute to
            member_id: User making contribution
            amount: Amount to contribute
            payment_method: wallet, credit_card, bank_transfer
            payment_reference: External payment reference (card transaction ID, etc.)
            wallet_id: Customer wallet ID if using wallet
            notes: Additional notes
            
        Returns:
            Contribution result with billing details
        """
        # Validate
        foundation = self._foundations.get(foundation_id)
        if not foundation:
            return {"success": False, "error": "Foundation not found"}
        
        # Check foundation status - allow contributions to draft, pending_review, and active foundations
        allowed_statuses = ['draft', 'pending_review', 'active']
        if foundation['status'] not in allowed_statuses:
            return {"success": False, "error": f"Cannot contribute to {foundation['status']} foundation"}
        
        fund = self._funds.get(fund_id)
        if not fund or fund['foundation_id'] != foundation_id:
            return {"success": False, "error": "Fund not found"}
        
        member = self._get_member_by_user(foundation_id, member_id)
        if not member or member['status'] != 'active':
            return {"success": False, "error": "You must be an active member to contribute"}
        
        # Validate minimum contribution
        settings = foundation.get('settings', {})
        min_contribution = settings.get('contribution_rules', {}).get('min_amount', 1.0)
        if amount < min_contribution:
            return {"success": False, "error": f"Minimum contribution is ${min_contribution}"}
        
        now = datetime.now(timezone.utc)
        
        # Generate IDs
        contribution_id = generate_id("CONTRIB")
        billing_record_id = generate_id("BILL")
        transaction_id = generate_id("TX")
        
        # Create contribution record
        contribution = {
            'id': contribution_id,
            'fund_id': fund_id,
            'member_id': member['id'],
            'member_user_id': member_id,
            'amount': amount,
            'currency': foundation.get('currency', 'USD'),
            'status': 'completed',
            'payment_method': payment_method,
            'payment_reference': payment_reference,
            'wallet_id': wallet_id,
            'notes': notes,
            'paid_date': now.isoformat(),
            'created_at': now.isoformat(),
            'updated_at': now.isoformat()
        }
        
        self._contributions[contribution_id] = contribution
        
        # Update fund balance
        fund['balance'] += amount
        fund['last_activity'] = now.isoformat()
        fund['updated_at'] = now.isoformat()
        
        # Update foundation total
        foundation['total_fund_balance'] += amount
        foundation['updated_at'] = now.isoformat()
        
        # Update member stats
        member['total_contributed'] += amount
        member['last_contribution'] = now.isoformat()
        member['updated_at'] = now.isoformat()
        
        # Create billing integration record
        billing_record = {
            'id': billing_record_id,
            'customer_id': member_id,
            'foundation_id': foundation_id,
            'foundation_name': foundation['name'],
            'contribution_id': contribution_id,
            'fund_id': fund_id,
            'fund_name': fund['name'],
            'amount': amount,
            'currency': foundation.get('currency', 'USD'),
            'payment_method': payment_method,
            'payment_reference': payment_reference,
            'wallet_id': wallet_id,
            'status': 'completed',
            'type': 'contribution',
            'description': f"Contribution to {foundation['name']} - {fund['name']}",
            'created_at': now.isoformat(),
            'completed_at': now.isoformat()
        }
        
        self._billing_integration_records[billing_record_id] = billing_record
        
        # Record to billing integration service if available
        if self._billing_enabled and self._billing_integration:
            self._billing_integration.record_foundation_deposit(
                customer_id=member_id,
                foundation_id=foundation_id,
                foundation_name=foundation['name'],
                amount=amount,
                contribution_id=contribution_id,
                fund_name=fund['name'],
                notes=notes
            )
        
        # Log activity
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="contribution_made",
            actor_id=member_id,
            details={
                "contribution_id": contribution_id,
                "amount": amount,
                "fund_id": fund_id,
                "fund_name": fund['name'],
                "payment_method": payment_method,
                "billing_record_id": billing_record_id
            }
        )
        
        # Persist data
        self._persist(create_backup=False)
        
        logger.info(f"Contribution {contribution_id}: ${amount} to {foundation['name']} by {member_id}")
        
        return {
            "success": True,
            "contribution_id": contribution_id,
            "billing_record_id": billing_record_id,
            "transaction_id": transaction_id,
            "amount": amount,
            "new_fund_balance": fund['balance'],
            "new_foundation_balance": foundation['total_fund_balance'],
            "payment_method": payment_method,
            "status": "completed",
            "recorded_to_ledger": True,
            "recorded_to_billing": self._billing_enabled
        }
    
    def generate_csv_report(
        self,
        foundation_id: str,
        report_type: str = 'transactions'
    ) -> str:
        """
        Generate CSV report data for a foundation.
        
        Args:
            foundation_id: Foundation ID
            report_type: Type of report (transactions, members, contributions, votes)
            
        Returns:
            CSV string content
        """
        foundation = self._foundations.get(foundation_id)
        if not foundation:
            return ""
        
        import csv
        from io import StringIO
        
        output = StringIO()
        
        if report_type == 'transactions':
            # All activities as transactions
            activities = self.get_foundation_activities(foundation_id, limit=1000)
            
            writer = csv.writer(output)
            writer.writerow(['Date', 'Type', 'Description', 'Actor', 'Details', 'Transaction Hash'])
            
            for activity in activities:
                details = activity.get('details', {})
                tx_hash = hashlib.sha256(f"{activity['id']}{activity['timestamp']}".encode()).hexdigest()[:16].upper()
                
                writer.writerow([
                    activity['timestamp'],
                    activity['activity_type'],
                    activity['activity_type'].replace('_', ' ').title(),
                    activity.get('actor_id', ''),
                    json.dumps(details) if details else '',
                    tx_hash
                ])
        
        elif report_type == 'members':
            members = self.get_foundation_members(foundation_id, include_pending=True)
            
            writer = csv.writer(output)
            writer.writerow(['Member ID', 'Display Name', 'Role', 'Status', 'Total Contributed', 'Last Contribution', 'Joined Date'])
            
            for member in members:
                writer.writerow([
                    member['member_id'],
                    member.get('display_name', ''),
                    member['role'],
                    member['status'],
                    member.get('total_contributed', 0),
                    member.get('last_contribution', ''),
                    member.get('joined_at', '')
                ])
        
        elif report_type == 'contributions':
            contributions = []
            for contrib in self._contributions.values():
                fund = self._funds.get(contrib['fund_id'])
                if fund and fund['foundation_id'] == foundation_id:
                    contributions.append(contrib)
            
            writer = csv.writer(output)
            writer.writerow(['Date', 'Member ID', 'Amount', 'Fund', 'Payment Method', 'Status', 'Reference'])
            
            for contrib in sorted(contributions, key=lambda x: x.get('paid_date', ''), reverse=True):
                fund = self._funds.get(contrib['fund_id'], {})
                writer.writerow([
                    contrib.get('paid_date', ''),
                    contrib.get('member_user_id', contrib.get('member_id', '')),
                    contrib['amount'],
                    fund.get('name', ''),
                    contrib.get('payment_method', 'unknown'),
                    contrib.get('status', ''),
                    contrib.get('payment_reference', '')
                ])
        
        elif report_type == 'votes':
            votes = self.get_all_votes(foundation_id, limit=1000)
            
            writer = csv.writer(output)
            writer.writerow(['Date', 'Title', 'Type', 'Status', 'Result', 'For', 'Against', 'Abstain', 'Threshold', 'Participation'])
            
            for vote in votes:
                decision_record = vote.get('decision_record', {})
                if isinstance(decision_record, str):
                    try:
                        decision_record = json.loads(decision_record)
                    except:
                        decision_record = {}
                
                writer.writerow([
                    vote.get('created_at', ''),
                    vote['title'],
                    vote.get('proposal_type', ''),
                    vote['status'],
                    vote.get('result', ''),
                    vote.get('votes_for', 0),
                    vote.get('votes_against', 0),
                    vote.get('votes_abstain', 0),
                    f"{vote.get('threshold', 0.5) * 100}%",
                    f"{decision_record.get('participation_rate', 0)}%" if decision_record else ''
                ])
        
        return output.getvalue()
    
    def get_customer_wallet_balance(self, customer_id: str) -> Dict[str, Any]:
        """
        Get customer wallet balance for foundation contributions.
        
        This integrates with the billing system to check available funds.
        """
        # Calculate from billing records
        total_deposited = 0
        total_withdrawn = 0
        
        for record in self._billing_integration_records.values():
            if record.get('customer_id') == customer_id:
                if record.get('type') == 'wallet_deposit':
                    total_deposited += record.get('amount', 0)
                elif record.get('type') in ['contribution', 'withdrawal']:
                    total_withdrawn += record.get('amount', 0)
        
        # Check if billing integration has wallet data
        if self._billing_enabled and self._billing_integration:
            billing_data = self._billing_integration.get_customer_foundation_billing(customer_id)
            # Sum up any wallet-related records
            for record in billing_data:
                if record.get('transaction_type') == 'wallet_deposit':
                    total_deposited += record.get('amount', 0)
        
        available_balance = total_deposited - total_withdrawn
        
        return {
            'customer_id': customer_id,
            'wallet_balance': max(0, available_balance),
            'total_deposited': total_deposited,
            'total_contributions': total_withdrawn,
            'currency': 'USD'
        }
    
    def deposit_to_wallet(
        self,
        customer_id: str,
        amount: float,
        payment_method: str,
        payment_reference: str = ''
    ) -> Dict[str, Any]:
        """
        Deposit funds to customer's foundation wallet.
        
        Args:
            customer_id: Customer ID
            amount: Amount to deposit
            payment_method: credit_card, bank_transfer, etc.
            payment_reference: External payment reference
            
        Returns:
            Deposit result
        """
        if amount <= 0:
            return {"success": False, "error": "Amount must be positive"}
        
        now = datetime.now(timezone.utc)
        deposit_id = generate_id("WDEP")
        
        # Create wallet deposit record
        deposit_record = {
            'id': deposit_id,
            'customer_id': customer_id,
            'amount': amount,
            'currency': 'USD',
            'type': 'wallet_deposit',
            'payment_method': payment_method,
            'payment_reference': payment_reference,
            'status': 'completed',
            'description': f'Wallet deposit via {payment_method}',
            'created_at': now.isoformat(),
            'completed_at': now.isoformat()
        }
        
        self._billing_integration_records[deposit_id] = deposit_record
        
        # Update wallet balance
        wallet = self.get_customer_wallet_balance(customer_id)
        
        logger.info(f"Wallet deposit {deposit_id}: ${amount} for customer {customer_id}")
        self._persist(create_backup=False)
        
        return {
            "success": True,
            "deposit_id": deposit_id,
            "amount": amount,
            "new_balance": wallet['wallet_balance'],
            "payment_method": payment_method
        }
    
    def update_member_details(
        self,
        foundation_id: str,
        member_record_id: str,
        actor_id: str,
        display_name: str = None,
        email: str = None,
        phone: str = None,
        photo_url: str = None
    ) -> MembershipResult:
        """Update member contact details"""
        member = self._members.get(member_record_id)
        
        if not member or member['foundation_id'] != foundation_id:
            return MembershipResult(
                success=False,
                error_code="NOT_FOUND",
                error_message="Member not found"
            )
        
        # Check actor rights
        actor = self._get_member_by_user(foundation_id, actor_id)
        if not actor:
            return MembershipResult(
                success=False,
                error_code="UNAUTHORIZED",
                error_message="You are not a member of this foundation"
            )
        
        # Can only update own details unless admin/founder
        if member['member_id'] != actor_id and actor['role'] not in ['founder', 'admin']:
            return MembershipResult(
                success=False,
                error_code="UNAUTHORIZED",
                error_message="You can only update your own details"
            )
        
        updated_fields = []
        if display_name is not None:
            member['display_name'] = display_name
            updated_fields.append('display_name')
        if email is not None:
            member['email'] = email
            updated_fields.append('email')
        if phone is not None:
            member['phone'] = phone
            updated_fields.append('phone')
        if photo_url is not None:
            member['photo_url'] = photo_url
            updated_fields.append('photo_url')
        
        member['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type="member_details_updated",
            actor_id=actor_id,
            details={"member_id": member['member_id'], "updated_fields": updated_fields}
        )
        
        return MembershipResult(
            success=True,
            member_id=member_record_id,
            data={"message": "Member details updated", "updated_fields": updated_fields}
        )


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
