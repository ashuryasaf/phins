"""
Community Foundation Service for PHINS Platform

Handles all foundation-related business logic including:
- Foundation creation and management
- Membership and invitation system
- Fund management and contributions
- Claims processing with voting
- Governance rules and voting system

Author: PHINS Engineering Team
Version: 1.0
"""

import json
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
import random


class FoundationService:
    """
    Comprehensive service for managing Community Foundations.
    
    Features:
    - Foundation CRUD operations
    - Membership management with roles
    - Private invitation system
    - Fund management (insurance, savings, emergency)
    - Claims processing with auto-approval and voting
    - Democratic governance with configurable rules
    """
    
    def __init__(self, 
                 foundations_store: Dict = None,
                 members_store: Dict = None,
                 funds_store: Dict = None,
                 contributions_store: Dict = None,
                 invitations_store: Dict = None,
                 claims_store: Dict = None,
                 votes_store: Dict = None,
                 vote_casts_store: Dict = None,
                 rules_store: Dict = None,
                 activities_store: Dict = None):
        """
        Initialize the foundation service with storage backends.
        
        Args:
            foundations_store: Foundation records storage
            members_store: Member records storage
            funds_store: Fund records storage
            contributions_store: Contribution records storage
            invitations_store: Invitation records storage
            claims_store: Claim records storage
            votes_store: Vote proposal storage
            vote_casts_store: Individual vote records storage
            rules_store: Foundation rules storage
            activities_store: Activity log storage
        """
        self.foundations = foundations_store if foundations_store is not None else {}
        self.members = members_store if members_store is not None else {}
        self.funds = funds_store if funds_store is not None else {}
        self.contributions = contributions_store if contributions_store is not None else {}
        self.invitations = invitations_store if invitations_store is not None else {}
        self.claims = claims_store if claims_store is not None else {}
        self.votes = votes_store if votes_store is not None else {}
        self.vote_casts = vote_casts_store if vote_casts_store is not None else {}
        self.rules = rules_store if rules_store is not None else {}
        self.activities = activities_store if activities_store is not None else {}
        
        # Foundation type configurations
        self.foundation_types = {
            'family': {
                'name': 'Family',
                'description': 'Mutual support for family members',
                'default_max_members': 15,
                'suggested_contribution': 100.0,
                'icon': '👨‍👩‍👧‍👦'
            },
            'work': {
                'name': 'Work',
                'description': 'Employee benefits pool',
                'default_max_members': 100,
                'suggested_contribution': 50.0,
                'icon': '💼'
            },
            'neighborhood': {
                'name': 'Neighborhood',
                'description': 'Local community emergency fund',
                'default_max_members': 50,
                'suggested_contribution': 25.0,
                'icon': '🏘️'
            },
            'friends': {
                'name': 'Friends',
                'description': 'Peer support network',
                'default_max_members': 35,
                'suggested_contribution': 75.0,
                'icon': '👥'
            },
            'entrepreneurs': {
                'name': 'Entrepreneurs',
                'description': 'Startup risk hedging pool',
                'default_max_members': 50,
                'suggested_contribution': 200.0,
                'icon': '🚀'
            },
            'business_venture': {
                'name': 'Business Venture',
                'description': 'Joint venture coverage',
                'default_max_members': 20,
                'suggested_contribution': 500.0,
                'icon': '🏢'
            },
            'professional': {
                'name': 'Professional',
                'description': 'Industry liability pool',
                'default_max_members': -1,  # Unlimited
                'suggested_contribution': 150.0,
                'icon': '🎯'
            },
            'customer_club': {
                'name': 'Customer Club',
                'description': 'Open membership club',
                'default_max_members': -1,  # Unlimited
                'suggested_contribution': 20.0,
                'icon': '🎪'
            },
            'custom': {
                'name': 'Custom',
                'description': 'Define your own foundation type',
                'default_max_members': 35,
                'suggested_contribution': 50.0,
                'icon': '⚙️'
            }
        }
        
        # Default rules template
        self.default_rules = {
            'contribution': {
                'frequency': 'monthly',
                'min_amount': 25.0,
                'max_amount': None,
                'grace_period_days': 7,
                'late_fee_percentage': 5.0
            },
            'claim_approval': {
                'waiting_period_days': 30,
                'auto_approve_threshold': 500.0,
                'max_claim_percentage': 25.0,
                'requires_documentation': True,
                'vote_threshold': 0.50
            },
            'fund_limits': {
                'min_reserve_percentage': 20.0,
                'max_single_payout_percentage': 25.0,
                'investment_allowed': False
            },
            'voting': {
                'majority_threshold': 0.50,
                'supermajority_threshold': 0.66,
                'vote_duration_days': 7,
                'quorum_percentage': 0.50
            },
            'membership': {
                'auto_approve_members': False,
                'require_invitation': True,
                'new_member_vote_required': False,
                'removal_vote_threshold': 0.66
            }
        }
    
    # =========================================================================
    # ID GENERATION
    # =========================================================================
    
    def generate_foundation_id(self) -> str:
        """Generate a unique foundation ID."""
        timestamp = datetime.now().strftime('%Y%m')
        random_part = secrets.token_hex(4).upper()
        return f"FND-{timestamp}-{random_part}"
    
    def generate_member_id(self) -> str:
        """Generate a unique member ID."""
        timestamp = datetime.now().strftime('%Y%m')
        random_part = secrets.token_hex(4).upper()
        return f"MBR-{timestamp}-{random_part}"
    
    def generate_fund_id(self) -> str:
        """Generate a unique fund ID."""
        timestamp = datetime.now().strftime('%Y%m')
        random_part = secrets.token_hex(4).upper()
        return f"FUND-{timestamp}-{random_part}"
    
    def generate_contribution_id(self) -> str:
        """Generate a unique contribution ID."""
        timestamp = datetime.now().strftime('%Y%m')
        random_part = secrets.token_hex(4).upper()
        return f"CTB-{timestamp}-{random_part}"
    
    def generate_invitation_id(self) -> str:
        """Generate a unique invitation ID."""
        timestamp = datetime.now().strftime('%Y%m')
        random_part = secrets.token_hex(4).upper()
        return f"INV-{timestamp}-{random_part}"
    
    def generate_invitation_code(self) -> str:
        """Generate a unique invitation code."""
        return secrets.token_urlsafe(16)
    
    def generate_claim_id(self) -> str:
        """Generate a unique claim ID."""
        timestamp = datetime.now().strftime('%Y%m')
        random_part = secrets.token_hex(4).upper()
        return f"FCLM-{timestamp}-{random_part}"
    
    def generate_vote_id(self) -> str:
        """Generate a unique vote ID."""
        timestamp = datetime.now().strftime('%Y%m')
        random_part = secrets.token_hex(4).upper()
        return f"VOTE-{timestamp}-{random_part}"
    
    def generate_vote_cast_id(self) -> str:
        """Generate a unique vote cast ID."""
        timestamp = datetime.now().strftime('%Y%m')
        random_part = secrets.token_hex(4).upper()
        return f"VC-{timestamp}-{random_part}"
    
    def generate_rule_id(self) -> str:
        """Generate a unique rule ID."""
        timestamp = datetime.now().strftime('%Y%m')
        random_part = secrets.token_hex(4).upper()
        return f"RULE-{timestamp}-{random_part}"
    
    def generate_activity_id(self) -> str:
        """Generate a unique activity ID."""
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        random_part = secrets.token_hex(3).upper()
        return f"ACT-{timestamp}-{random_part}"
    
    # =========================================================================
    # FOUNDATION MANAGEMENT
    # =========================================================================
    
    def create_foundation(self, 
                          founder_id: str,
                          founder_type: str,
                          founder_name: str,
                          name: str,
                          foundation_type: str,
                          description: str = None,
                          custom_type_name: str = None,
                          max_members: int = None,
                          is_unlimited: bool = False,
                          founder_veto_enabled: bool = True,
                          auto_approve_members: bool = False,
                          require_invitation: bool = True,
                          initial_contribution: float = None,
                          ip_address: str = None) -> Tuple[bool, str, Optional[Dict]]:
        """
        Create a new community foundation.
        
        Args:
            founder_id: Customer or Supplier ID
            founder_type: 'customer' or 'supplier'
            founder_name: Display name for founder
            name: Foundation name
            foundation_type: Type of foundation
            description: Optional description
            custom_type_name: Name for custom type
            max_members: Maximum members (None = use default)
            is_unlimited: Allow unlimited members
            founder_veto_enabled: Enable founder veto power
            auto_approve_members: Auto-approve new members
            require_invitation: Require invitation to join
            initial_contribution: Founder's initial contribution
            ip_address: IP address for audit
            
        Returns:
            Tuple of (success, message, foundation_data)
        """
        try:
            # Validate founder type
            if founder_type not in ('customer', 'supplier'):
                return False, "Invalid founder type. Must be 'customer' or 'supplier'.", None
            
            # Validate foundation type
            if foundation_type not in self.foundation_types:
                return False, f"Invalid foundation type: {foundation_type}", None
            
            # Get type configuration
            type_config = self.foundation_types[foundation_type]
            
            # Set max members
            if is_unlimited:
                max_members = -1
            elif max_members is None:
                max_members = type_config['default_max_members']
            
            # Generate IDs
            foundation_id = self.generate_foundation_id()
            member_id = self.generate_member_id()
            
            now = datetime.utcnow()
            
            # Create foundation record
            foundation = {
                'id': foundation_id,
                'name': name,
                'description': description or type_config['description'],
                'foundation_type': foundation_type,
                'custom_type_name': custom_type_name if foundation_type == 'custom' else None,
                'founder_id': founder_id,
                'founder_type': founder_type,
                'founder_name': founder_name,
                'status': 'draft',
                'activated_at': None,
                'suspended_at': None,
                'dissolved_at': None,
                'suspension_reason': None,
                'dissolution_reason': None,
                'max_members': max_members,
                'is_unlimited': is_unlimited or max_members == -1,
                'current_member_count': 1,
                'min_members_to_operate': 2,
                'founder_veto_enabled': founder_veto_enabled,
                'auto_approve_members': auto_approve_members,
                'require_invitation': require_invitation,
                'new_member_vote_required': False,
                'majority_threshold': 0.50,
                'supermajority_threshold': 0.66,
                'dissolution_threshold': 0.75,
                'quorum_percentage': 0.50,
                'vote_duration_days': 7,
                'total_fund_balance': 0.0,
                'total_contributions': 0.0,
                'total_claims_paid': 0.0,
                'currency': 'USD',
                'settings': json.dumps({
                    'icon': type_config['icon'],
                    'suggested_contribution': type_config['suggested_contribution']
                }),
                'created_at': now.isoformat(),
                'updated_at': now.isoformat()
            }
            
            # Create founder as first member
            founder_member = {
                'id': member_id,
                'foundation_id': foundation_id,
                'member_id': founder_id,
                'member_type': founder_type,
                'display_name': founder_name,
                'role': 'founder',
                'status': 'active',
                'contribution_amount': initial_contribution or type_config['suggested_contribution'],
                'total_contributed': 0.0,
                'last_contribution_date': None,
                'next_contribution_due': None,
                'contributions_missed': 0,
                'voting_weight': 1.0,
                'is_visible': True,
                'share_contribution_amount': False,
                'joined_at': now.isoformat(),
                'invited_at': None,
                'approved_at': now.isoformat(),
                'removed_at': None,
                'removal_reason': None,
                'invited_by': None,
                'approved_by': 'system',
                'removed_by': None,
                'created_at': now.isoformat(),
                'updated_at': now.isoformat()
            }
            
            # Store records
            self.foundations[foundation_id] = foundation
            self.members[member_id] = founder_member
            
            # Create default rules
            self._create_default_rules(foundation_id, founder_id)
            
            # Create default funds
            self._create_default_funds(foundation_id)
            
            # Log activity
            self._log_activity(
                foundation_id=foundation_id,
                activity_type='foundation_created',
                description=f"Foundation '{name}' created by {founder_name}",
                actor_id=member_id,
                actor_name=founder_name,
                actor_type='founder',
                entity_type='foundation',
                entity_id=foundation_id,
                details={'foundation_type': foundation_type},
                ip_address=ip_address
            )
            
            return True, "Foundation created successfully", {
                'foundation': foundation,
                'member': founder_member
            }
            
        except Exception as e:
            return False, f"Error creating foundation: {str(e)}", None
    
    def _create_default_rules(self, foundation_id: str, created_by: str):
        """Create default rules for a foundation."""
        now = datetime.utcnow()
        
        for rule_type, rules in self.default_rules.items():
            for rule_key, rule_value in rules.items():
                rule_id = self.generate_rule_id()
                
                is_base = rule_type == 'governance'  # Base rules can't be changed
                
                rule = {
                    'id': rule_id,
                    'foundation_id': foundation_id,
                    'rule_type': rule_type,
                    'rule_key': rule_key,
                    'rule_value': json.dumps(rule_value),
                    'rule_description': f"{rule_type}.{rule_key}",
                    'is_base_rule': is_base,
                    'requires_vote': not is_base,
                    'vote_threshold': 0.66,
                    'version': 1,
                    'previous_value': None,
                    'created_by': created_by,
                    'modified_by': None,
                    'created_at': now.isoformat(),
                    'updated_at': now.isoformat()
                }
                
                self.rules[rule_id] = rule
    
    def _create_default_funds(self, foundation_id: str):
        """Create default funds for a foundation."""
        now = datetime.utcnow()
        
        # Create main collective insurance fund
        insurance_fund_id = self.generate_fund_id()
        insurance_fund = {
            'id': insurance_fund_id,
            'foundation_id': foundation_id,
            'name': 'Collective Insurance Pool',
            'description': 'Main pool for insurance claims and coverage',
            'fund_type': 'insurance',
            'balance': 0.0,
            'currency': 'USD',
            'total_deposits': 0.0,
            'total_withdrawals': 0.0,
            'total_claims_paid': 0.0,
            'min_reserve_percentage': 0.20,
            'max_claim_percentage': 0.25,
            'auto_approve_threshold': 500.0,
            'claim_waiting_period_days': 30,
            'status': 'active',
            'frozen_at': None,
            'frozen_reason': None,
            'created_at': now.isoformat(),
            'updated_at': now.isoformat(),
            'last_activity_at': None
        }
        self.funds[insurance_fund_id] = insurance_fund
        
        # Create emergency fund
        emergency_fund_id = self.generate_fund_id()
        emergency_fund = {
            'id': emergency_fund_id,
            'foundation_id': foundation_id,
            'name': 'Emergency Reserve',
            'description': 'Emergency fund for urgent situations',
            'fund_type': 'emergency',
            'balance': 0.0,
            'currency': 'USD',
            'total_deposits': 0.0,
            'total_withdrawals': 0.0,
            'total_claims_paid': 0.0,
            'min_reserve_percentage': 0.10,
            'max_claim_percentage': 0.50,
            'auto_approve_threshold': 250.0,
            'claim_waiting_period_days': 0,  # No waiting for emergencies
            'status': 'active',
            'frozen_at': None,
            'frozen_reason': None,
            'created_at': now.isoformat(),
            'updated_at': now.isoformat(),
            'last_activity_at': None
        }
        self.funds[emergency_fund_id] = emergency_fund
    
    def activate_foundation(self, foundation_id: str, actor_id: str, 
                           ip_address: str = None) -> Tuple[bool, str]:
        """Activate a draft foundation."""
        foundation = self.foundations.get(foundation_id)
        if not foundation:
            return False, "Foundation not found"
        
        if foundation['status'] != 'draft':
            return False, f"Foundation is not in draft status (current: {foundation['status']})"
        
        # Check if actor is founder
        member = self._get_member_by_user(foundation_id, actor_id)
        if not member or member['role'] != 'founder':
            return False, "Only the founder can activate the foundation"
        
        now = datetime.utcnow()
        foundation['status'] = 'active'
        foundation['activated_at'] = now.isoformat()
        foundation['updated_at'] = now.isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type='foundation_activated',
            description=f"Foundation activated by {member['display_name']}",
            actor_id=member['id'],
            actor_name=member['display_name'],
            actor_type='founder',
            entity_type='foundation',
            entity_id=foundation_id,
            ip_address=ip_address
        )
        
        return True, "Foundation activated successfully"
    
    def get_foundation(self, foundation_id: str) -> Optional[Dict]:
        """Get foundation by ID."""
        return self.foundations.get(foundation_id)
    
    def get_foundations_for_user(self, user_id: str, user_type: str = None) -> List[Dict]:
        """Get all foundations a user belongs to."""
        results = []
        
        for member in self.members.values():
            if member['member_id'] == user_id and member['status'] == 'active':
                foundation = self.foundations.get(member['foundation_id'])
                if foundation:
                    results.append({
                        'foundation': foundation,
                        'membership': member
                    })
        
        return results
    
    def get_foundation_stats(self, foundation_id: str) -> Dict[str, Any]:
        """Get statistics for a foundation."""
        foundation = self.foundations.get(foundation_id)
        if not foundation:
            return {}
        
        # Count members by status
        members = [m for m in self.members.values() if m['foundation_id'] == foundation_id]
        active_members = len([m for m in members if m['status'] == 'active'])
        pending_members = len([m for m in members if m['status'] == 'pending'])
        
        # Get fund totals
        funds = [f for f in self.funds.values() if f['foundation_id'] == foundation_id]
        total_balance = sum(f['balance'] for f in funds)
        
        # Get claims stats
        claims = [c for c in self.claims.values() if c['foundation_id'] == foundation_id]
        pending_claims = len([c for c in claims if c['status'] in ('submitted', 'reviewing', 'vote_open')])
        total_paid = sum(c.get('amount_paid', 0) or 0 for c in claims if c['status'] == 'paid')
        
        # Get active votes
        votes = [v for v in self.votes.values() if v['foundation_id'] == foundation_id and v['status'] == 'open']
        
        return {
            'foundation_id': foundation_id,
            'active_members': active_members,
            'pending_members': pending_members,
            'total_funds': len(funds),
            'total_balance': total_balance,
            'pending_claims': pending_claims,
            'total_claims_paid': total_paid,
            'active_votes': len(votes),
            'total_contributions': foundation.get('total_contributions', 0)
        }
    
    # =========================================================================
    # MEMBERSHIP MANAGEMENT
    # =========================================================================
    
    def create_invitation(self,
                          foundation_id: str,
                          invited_by_id: str,
                          invited_email: str = None,
                          invited_name: str = None,
                          max_uses: int = 1,
                          expires_in_days: int = 7,
                          notes: str = None,
                          ip_address: str = None) -> Tuple[bool, str, Optional[Dict]]:
        """
        Create an invitation to join a foundation.
        
        Args:
            foundation_id: Target foundation
            invited_by_id: Member ID creating the invitation
            invited_email: Optional email for specific invite
            invited_name: Optional name for specific invite
            max_uses: Max times code can be used (-1 for unlimited)
            expires_in_days: Days until expiration
            notes: Optional notes
            ip_address: IP for audit
            
        Returns:
            Tuple of (success, message, invitation_data)
        """
        foundation = self.foundations.get(foundation_id)
        if not foundation:
            return False, "Foundation not found", None
        
        if foundation['status'] != 'active':
            return False, "Foundation is not active", None
        
        # Verify inviter is founder or admin
        inviter = self.members.get(invited_by_id)
        if not inviter:
            # Try to find by user_id
            inviter = self._get_member_by_user(foundation_id, invited_by_id)
        
        if not inviter or inviter['role'] not in ('founder', 'admin'):
            return False, "Only founders and admins can send invitations", None
        
        # Check member limit
        if not foundation['is_unlimited'] and foundation['max_members'] > 0:
            if foundation['current_member_count'] >= foundation['max_members']:
                return False, "Foundation has reached maximum member capacity", None
        
        now = datetime.utcnow()
        invitation_id = self.generate_invitation_id()
        code = self.generate_invitation_code()
        
        invitation = {
            'id': invitation_id,
            'foundation_id': foundation_id,
            'code': code,
            'invited_email': invited_email,
            'invited_name': invited_name,
            'max_uses': max_uses,
            'used_count': 0,
            'status': 'pending',
            'created_at': now.isoformat(),
            'expires_at': (now + timedelta(days=expires_in_days)).isoformat(),
            'used_at': None,
            'revoked_at': None,
            'invited_by': inviter['id'],
            'invited_by_name': inviter['display_name'],
            'revoked_by': None,
            'notes': notes
        }
        
        self.invitations[invitation_id] = invitation
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type='invitation_created',
            description=f"Invitation created by {inviter['display_name']}",
            actor_id=inviter['id'],
            actor_name=inviter['display_name'],
            actor_type=inviter['role'],
            entity_type='invitation',
            entity_id=invitation_id,
            details={'invited_email': invited_email},
            ip_address=ip_address
        )
        
        return True, "Invitation created successfully", invitation
    
    def validate_invitation(self, code: str) -> Tuple[bool, str, Optional[Dict]]:
        """Validate an invitation code and return foundation info."""
        invitation = None
        for inv in self.invitations.values():
            if inv['code'] == code:
                invitation = inv
                break
        
        if not invitation:
            return False, "Invalid invitation code", None
        
        if invitation['status'] != 'pending':
            return False, f"Invitation is {invitation['status']}", None
        
        # Check expiration
        if invitation['expires_at']:
            expires = datetime.fromisoformat(invitation['expires_at'])
            if datetime.utcnow() > expires:
                invitation['status'] = 'expired'
                return False, "Invitation has expired", None
        
        # Check usage limit
        if invitation['max_uses'] > 0 and invitation['used_count'] >= invitation['max_uses']:
            return False, "Invitation has reached maximum uses", None
        
        # Get foundation info
        foundation = self.foundations.get(invitation['foundation_id'])
        if not foundation:
            return False, "Foundation not found", None
        
        # Return sanitized data (no sensitive info)
        return True, "Valid invitation", {
            'foundation_id': foundation['id'],
            'foundation_name': foundation['name'],
            'foundation_type': foundation['foundation_type'],
            'description': foundation['description'],
            'current_members': foundation['current_member_count'],
            'max_members': foundation['max_members'] if not foundation['is_unlimited'] else 'Unlimited',
            'invited_by': invitation['invited_by_name']
        }
    
    def join_foundation(self,
                        code: str,
                        user_id: str,
                        user_type: str,
                        display_name: str,
                        contribution_amount: float = None,
                        ip_address: str = None) -> Tuple[bool, str, Optional[Dict]]:
        """
        Join a foundation using an invitation code.
        
        Args:
            code: Invitation code
            user_id: Customer or Supplier ID
            user_type: 'customer' or 'supplier'
            display_name: Display name in the foundation
            contribution_amount: Agreed contribution amount
            ip_address: IP for audit
            
        Returns:
            Tuple of (success, message, membership_data)
        """
        # Validate invitation
        valid, message, info = self.validate_invitation(code)
        if not valid:
            return False, message, None
        
        foundation_id = info['foundation_id']
        foundation = self.foundations.get(foundation_id)
        
        # Find the invitation
        invitation = None
        for inv in self.invitations.values():
            if inv['code'] == code:
                invitation = inv
                break
        
        # Check if already a member
        existing = self._get_member_by_user(foundation_id, user_id)
        if existing:
            if existing['status'] == 'active':
                return False, "You are already a member of this foundation", None
            elif existing['status'] == 'removed':
                return False, "You were previously removed from this foundation", None
        
        now = datetime.utcnow()
        member_id = self.generate_member_id()
        
        # Determine initial status based on foundation settings
        initial_status = 'active' if foundation['auto_approve_members'] else 'pending'
        
        # Get suggested contribution
        settings = json.loads(foundation.get('settings', '{}'))
        default_contribution = settings.get('suggested_contribution', 50.0)
        
        member = {
            'id': member_id,
            'foundation_id': foundation_id,
            'member_id': user_id,
            'member_type': user_type,
            'display_name': display_name,
            'role': 'member',
            'status': initial_status,
            'contribution_amount': contribution_amount or default_contribution,
            'total_contributed': 0.0,
            'last_contribution_date': None,
            'next_contribution_due': (now + timedelta(days=30)).isoformat() if initial_status == 'active' else None,
            'contributions_missed': 0,
            'voting_weight': 1.0,
            'is_visible': True,
            'share_contribution_amount': False,
            'joined_at': now.isoformat() if initial_status == 'active' else None,
            'invited_at': now.isoformat(),
            'approved_at': now.isoformat() if initial_status == 'active' else None,
            'removed_at': None,
            'removal_reason': None,
            'invited_by': invitation['invited_by'],
            'approved_by': 'auto' if initial_status == 'active' else None,
            'removed_by': None,
            'created_at': now.isoformat(),
            'updated_at': now.isoformat()
        }
        
        self.members[member_id] = member
        
        # Update invitation
        invitation['used_count'] += 1
        if not invitation['used_at']:
            invitation['used_at'] = now.isoformat()
        if invitation['max_uses'] > 0 and invitation['used_count'] >= invitation['max_uses']:
            invitation['status'] = 'accepted'
        
        # Update foundation member count if auto-approved
        if initial_status == 'active':
            foundation['current_member_count'] += 1
            foundation['updated_at'] = now.isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type='member_joined' if initial_status == 'active' else 'member_pending',
            description=f"{display_name} {'joined' if initial_status == 'active' else 'requested to join'} the foundation",
            actor_id=member_id,
            actor_name=display_name,
            actor_type='member',
            entity_type='member',
            entity_id=member_id,
            ip_address=ip_address
        )
        
        status_message = "Welcome to the foundation!" if initial_status == 'active' else "Your membership is pending approval"
        
        return True, status_message, member
    
    def approve_member(self,
                       foundation_id: str,
                       member_id: str,
                       approver_id: str,
                       ip_address: str = None) -> Tuple[bool, str]:
        """Approve a pending member."""
        foundation = self.foundations.get(foundation_id)
        if not foundation:
            return False, "Foundation not found"
        
        member = self.members.get(member_id)
        if not member or member['foundation_id'] != foundation_id:
            return False, "Member not found"
        
        if member['status'] != 'pending':
            return False, f"Member is not pending (status: {member['status']})"
        
        # Verify approver is founder or admin
        approver = self._get_member_by_user(foundation_id, approver_id)
        if not approver:
            approver = self.members.get(approver_id)
        
        if not approver or approver['role'] not in ('founder', 'admin'):
            return False, "Only founders and admins can approve members"
        
        now = datetime.utcnow()
        member['status'] = 'active'
        member['approved_at'] = now.isoformat()
        member['approved_by'] = approver['id']
        member['joined_at'] = now.isoformat()
        member['next_contribution_due'] = (now + timedelta(days=30)).isoformat()
        member['updated_at'] = now.isoformat()
        
        # Update foundation member count
        foundation['current_member_count'] += 1
        foundation['updated_at'] = now.isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type='member_approved',
            description=f"{member['display_name']} was approved by {approver['display_name']}",
            actor_id=approver['id'],
            actor_name=approver['display_name'],
            actor_type=approver['role'],
            entity_type='member',
            entity_id=member_id,
            ip_address=ip_address
        )
        
        return True, "Member approved successfully"
    
    def remove_member(self,
                      foundation_id: str,
                      member_id: str,
                      remover_id: str,
                      reason: str = None,
                      ip_address: str = None) -> Tuple[bool, str]:
        """Remove a member from the foundation."""
        foundation = self.foundations.get(foundation_id)
        if not foundation:
            return False, "Foundation not found"
        
        member = self.members.get(member_id)
        if not member or member['foundation_id'] != foundation_id:
            return False, "Member not found"
        
        if member['status'] != 'active':
            return False, "Member is not active"
        
        # Verify remover is founder or admin
        remover = self._get_member_by_user(foundation_id, remover_id)
        if not remover:
            remover = self.members.get(remover_id)
        
        if not remover or remover['role'] not in ('founder', 'admin'):
            return False, "Only founders and admins can remove members"
        
        # Can't remove founder
        if member['role'] == 'founder':
            return False, "Cannot remove the founder"
        
        # Admin can't remove another admin
        if member['role'] == 'admin' and remover['role'] == 'admin':
            return False, "Admins cannot remove other admins"
        
        now = datetime.utcnow()
        member['status'] = 'removed'
        member['removed_at'] = now.isoformat()
        member['removed_by'] = remover['id']
        member['removal_reason'] = reason
        member['updated_at'] = now.isoformat()
        
        # Update foundation member count
        foundation['current_member_count'] = max(0, foundation['current_member_count'] - 1)
        foundation['updated_at'] = now.isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type='member_removed',
            description=f"{member['display_name']} was removed by {remover['display_name']}",
            actor_id=remover['id'],
            actor_name=remover['display_name'],
            actor_type=remover['role'],
            entity_type='member',
            entity_id=member_id,
            details={'reason': reason},
            ip_address=ip_address
        )
        
        return True, "Member removed successfully"
    
    def leave_foundation(self,
                         foundation_id: str,
                         user_id: str,
                         ip_address: str = None) -> Tuple[bool, str]:
        """Leave a foundation voluntarily."""
        foundation = self.foundations.get(foundation_id)
        if not foundation:
            return False, "Foundation not found"
        
        member = self._get_member_by_user(foundation_id, user_id)
        if not member:
            return False, "You are not a member of this foundation"
        
        if member['status'] != 'active':
            return False, "You are not an active member"
        
        # Founder can't leave
        if member['role'] == 'founder':
            return False, "Founder cannot leave. You must dissolve the foundation or transfer ownership."
        
        now = datetime.utcnow()
        member['status'] = 'removed'
        member['removed_at'] = now.isoformat()
        member['removed_by'] = member['id']
        member['removal_reason'] = 'Voluntary departure'
        member['updated_at'] = now.isoformat()
        
        # Update foundation member count
        foundation['current_member_count'] = max(0, foundation['current_member_count'] - 1)
        foundation['updated_at'] = now.isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type='member_left',
            description=f"{member['display_name']} left the foundation",
            actor_id=member['id'],
            actor_name=member['display_name'],
            actor_type=member['role'],
            entity_type='member',
            entity_id=member['id'],
            ip_address=ip_address
        )
        
        return True, "You have left the foundation"
    
    def get_members(self, foundation_id: str, include_inactive: bool = False) -> List[Dict]:
        """Get all members of a foundation."""
        members = []
        for member in self.members.values():
            if member['foundation_id'] == foundation_id:
                if include_inactive or member['status'] == 'active':
                    # Return sanitized data
                    members.append(member)
        
        # Sort by role then join date
        role_order = {'founder': 0, 'admin': 1, 'member': 2, 'observer': 3}
        members.sort(key=lambda m: (role_order.get(m['role'], 99), m.get('joined_at', '')))
        
        return members
    
    def _get_member_by_user(self, foundation_id: str, user_id: str) -> Optional[Dict]:
        """Get a member record by their user ID."""
        for member in self.members.values():
            if member['foundation_id'] == foundation_id and member['member_id'] == user_id:
                return member
        return None
    
    # =========================================================================
    # CONTRIBUTION MANAGEMENT
    # =========================================================================
    
    def make_contribution(self,
                          foundation_id: str,
                          fund_id: str,
                          user_id: str,
                          amount: float,
                          contribution_type: str = 'one_time',
                          payment_method: str = 'wallet',
                          notes: str = None,
                          ip_address: str = None) -> Tuple[bool, str, Optional[Dict]]:
        """
        Make a contribution to a foundation fund.
        
        Args:
            foundation_id: Foundation ID
            fund_id: Target fund ID
            user_id: Contributing user's ID
            amount: Contribution amount
            contribution_type: monthly, quarterly, annual, one_time
            payment_method: wallet, bank_transfer, card
            notes: Optional notes
            ip_address: IP for audit
            
        Returns:
            Tuple of (success, message, contribution_data)
        """
        foundation = self.foundations.get(foundation_id)
        if not foundation:
            return False, "Foundation not found", None
        
        if foundation['status'] != 'active':
            return False, "Foundation is not active", None
        
        fund = self.funds.get(fund_id)
        if not fund or fund['foundation_id'] != foundation_id:
            return False, "Fund not found", None
        
        if fund['status'] != 'active':
            return False, "Fund is not active", None
        
        member = self._get_member_by_user(foundation_id, user_id)
        if not member:
            return False, "You are not a member of this foundation", None
        
        if member['status'] != 'active':
            return False, "Your membership is not active", None
        
        if amount <= 0:
            return False, "Contribution amount must be positive", None
        
        now = datetime.utcnow()
        contribution_id = self.generate_contribution_id()
        
        contribution = {
            'id': contribution_id,
            'fund_id': fund_id,
            'member_id': member['id'],
            'amount': amount,
            'currency': fund['currency'],
            'contribution_type': contribution_type,
            'status': 'completed',  # For now, assume immediate completion
            'due_date': None,
            'paid_date': now.isoformat(),
            'payment_method': payment_method,
            'transaction_ref': f"TXN-{secrets.token_hex(6).upper()}",
            'notes': notes,
            'failure_reason': None,
            'created_at': now.isoformat(),
            'updated_at': now.isoformat()
        }
        
        self.contributions[contribution_id] = contribution
        
        # Update fund balance
        fund['balance'] += amount
        fund['total_deposits'] += amount
        fund['last_activity_at'] = now.isoformat()
        fund['updated_at'] = now.isoformat()
        
        # Update member stats
        member['total_contributed'] += amount
        member['last_contribution_date'] = now.isoformat()
        member['updated_at'] = now.isoformat()
        
        # Update foundation totals
        foundation['total_fund_balance'] += amount
        foundation['total_contributions'] += amount
        foundation['updated_at'] = now.isoformat()
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type='contribution_made',
            description=f"{member['display_name']} contributed ${amount:.2f} to {fund['name']}",
            actor_id=member['id'],
            actor_name=member['display_name'],
            actor_type=member['role'],
            entity_type='contribution',
            entity_id=contribution_id,
            details={'amount': amount, 'fund_name': fund['name']},
            ip_address=ip_address
        )
        
        return True, f"Contribution of ${amount:.2f} recorded successfully", contribution
    
    def get_contributions(self, foundation_id: str, fund_id: str = None, 
                          member_id: str = None) -> List[Dict]:
        """Get contributions for a foundation, optionally filtered."""
        results = []
        
        for contribution in self.contributions.values():
            fund = self.funds.get(contribution['fund_id'])
            if not fund or fund['foundation_id'] != foundation_id:
                continue
            
            if fund_id and contribution['fund_id'] != fund_id:
                continue
            
            if member_id and contribution['member_id'] != member_id:
                continue
            
            results.append(contribution)
        
        # Sort by date descending
        results.sort(key=lambda c: c.get('created_at', ''), reverse=True)
        
        return results
    
    # =========================================================================
    # CLAIMS MANAGEMENT
    # =========================================================================
    
    def submit_claim(self,
                     foundation_id: str,
                     fund_id: str,
                     user_id: str,
                     claim_type: str,
                     title: str,
                     amount: float,
                     description: str = None,
                     supporting_docs: List[Dict] = None,
                     ip_address: str = None) -> Tuple[bool, str, Optional[Dict]]:
        """
        Submit a claim against a foundation fund.
        
        Args:
            foundation_id: Foundation ID
            fund_id: Target fund ID
            user_id: Claimant's user ID
            claim_type: Type of claim
            title: Claim title
            amount: Requested amount
            description: Claim description
            supporting_docs: List of document references
            ip_address: IP for audit
            
        Returns:
            Tuple of (success, message, claim_data)
        """
        foundation = self.foundations.get(foundation_id)
        if not foundation:
            return False, "Foundation not found", None
        
        if foundation['status'] != 'active':
            return False, "Foundation is not active", None
        
        fund = self.funds.get(fund_id)
        if not fund or fund['foundation_id'] != foundation_id:
            return False, "Fund not found", None
        
        if fund['status'] != 'active':
            return False, "Fund is not active", None
        
        member = self._get_member_by_user(foundation_id, user_id)
        if not member:
            return False, "You are not a member of this foundation", None
        
        if member['status'] != 'active':
            return False, "Your membership is not active", None
        
        if amount <= 0:
            return False, "Claim amount must be positive", None
        
        # Check waiting period
        joined = datetime.fromisoformat(member['joined_at']) if member['joined_at'] else None
        if joined:
            waiting_days = fund.get('claim_waiting_period_days', 30)
            if (datetime.utcnow() - joined).days < waiting_days:
                return False, f"You must wait {waiting_days} days after joining before submitting claims", None
        
        # Check if claim exceeds fund limits
        max_claim = fund['balance'] * fund['max_claim_percentage']
        if amount > max_claim:
            return False, f"Claim amount exceeds maximum allowed (${max_claim:.2f})", None
        
        # Check available balance (after reserve)
        available = fund['balance'] * (1 - fund['min_reserve_percentage'])
        if amount > available:
            return False, f"Insufficient fund balance. Available: ${available:.2f}", None
        
        now = datetime.utcnow()
        claim_id = self.generate_claim_id()
        
        # Determine if auto-approve or needs voting
        auto_approve = amount <= fund.get('auto_approve_threshold', 500.0)
        
        claim = {
            'id': claim_id,
            'foundation_id': foundation_id,
            'fund_id': fund_id,
            'claimant_id': member['id'],
            'claim_type': claim_type,
            'title': title,
            'description': description,
            'amount_requested': amount,
            'amount_approved': amount if auto_approve else None,
            'amount_paid': None,
            'currency': fund['currency'],
            'status': 'approved' if auto_approve else 'submitted',
            'supporting_docs': json.dumps(supporting_docs or []),
            'vote_id': None,
            'auto_approved': auto_approve,
            'reviewed_by': 'system' if auto_approve else None,
            'reviewed_by_name': 'Auto-Approval' if auto_approve else None,
            'review_notes': 'Automatically approved (under threshold)' if auto_approve else None,
            'rejection_reason': None,
            'payout_date': None,
            'payout_method': None,
            'payout_reference': None,
            'submitted_at': now.isoformat(),
            'reviewed_at': now.isoformat() if auto_approve else None,
            'approved_at': now.isoformat() if auto_approve else None,
            'paid_at': None,
            'cancelled_at': None,
            'claimant_display_name': member['display_name'],
            'created_at': now.isoformat(),
            'updated_at': now.isoformat()
        }
        
        self.claims[claim_id] = claim
        
        # If not auto-approved, create a vote
        if not auto_approve:
            vote_success, vote_msg, vote_data = self._create_claim_vote(
                foundation, fund, claim, member
            )
            if vote_success and vote_data:
                claim['vote_id'] = vote_data['id']
                claim['status'] = 'vote_open'
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type='claim_submitted',
            description=f"{member['display_name']} submitted a claim for ${amount:.2f}" + 
                       (" (auto-approved)" if auto_approve else " (pending vote)"),
            actor_id=member['id'],
            actor_name=member['display_name'],
            actor_type=member['role'],
            entity_type='claim',
            entity_id=claim_id,
            details={'amount': amount, 'claim_type': claim_type, 'auto_approved': auto_approve},
            ip_address=ip_address
        )
        
        status_msg = "Claim auto-approved" if auto_approve else "Claim submitted for voting"
        
        return True, status_msg, claim
    
    def _create_claim_vote(self, foundation: Dict, fund: Dict, claim: Dict, 
                           claimant: Dict) -> Tuple[bool, str, Optional[Dict]]:
        """Create a vote proposal for a claim."""
        now = datetime.utcnow()
        vote_id = self.generate_vote_id()
        
        # Count eligible voters
        eligible = len([m for m in self.members.values() 
                       if m['foundation_id'] == foundation['id'] 
                       and m['status'] == 'active'
                       and m['role'] in ('founder', 'admin', 'member')])
        
        vote = {
            'id': vote_id,
            'foundation_id': foundation['id'],
            'proposal_type': 'claim',
            'title': f"Claim: {claim['title']}",
            'description': f"{claimant['display_name']} is requesting ${claim['amount_requested']:.2f} from {fund['name']}",
            'related_entity_type': 'claim',
            'related_entity_id': claim['id'],
            'threshold': foundation.get('majority_threshold', 0.50),
            'quorum': foundation.get('quorum_percentage', 0.50),
            'votes_for': 0,
            'votes_against': 0,
            'votes_abstain': 0,
            'total_eligible': eligible,
            'status': 'open',
            'result': None,
            'created_at': now.isoformat(),
            'closes_at': (now + timedelta(days=foundation.get('vote_duration_days', 7))).isoformat(),
            'closed_at': None,
            'created_by': claimant['id'],
            'created_by_name': claimant['display_name'],
            'vetoed': False,
            'vetoed_by': None,
            'vetoed_at': None,
            'veto_reason': None
        }
        
        self.votes[vote_id] = vote
        
        return True, "Vote created", vote
    
    def process_claim_payout(self,
                             claim_id: str,
                             processor_id: str,
                             payout_method: str = 'wallet',
                             ip_address: str = None) -> Tuple[bool, str]:
        """Process payout for an approved claim."""
        claim = self.claims.get(claim_id)
        if not claim:
            return False, "Claim not found"
        
        if claim['status'] != 'approved':
            return False, f"Claim is not approved (status: {claim['status']})"
        
        foundation = self.foundations.get(claim['foundation_id'])
        fund = self.funds.get(claim['fund_id'])
        
        if not foundation or not fund:
            return False, "Foundation or fund not found"
        
        # Verify processor is founder or admin
        processor = self._get_member_by_user(foundation['id'], processor_id)
        if not processor:
            processor = self.members.get(processor_id)
        
        if not processor or processor['role'] not in ('founder', 'admin'):
            return False, "Only founders and admins can process payouts"
        
        amount = claim['amount_approved']
        
        # Check fund balance
        if fund['balance'] < amount:
            return False, f"Insufficient fund balance. Available: ${fund['balance']:.2f}"
        
        now = datetime.utcnow()
        
        # Update claim
        claim['status'] = 'paid'
        claim['amount_paid'] = amount
        claim['payout_date'] = now.isoformat()
        claim['paid_at'] = now.isoformat()
        claim['payout_method'] = payout_method
        claim['payout_reference'] = f"PAY-{secrets.token_hex(6).upper()}"
        claim['updated_at'] = now.isoformat()
        
        # Update fund
        fund['balance'] -= amount
        fund['total_withdrawals'] += amount
        fund['total_claims_paid'] += amount
        fund['last_activity_at'] = now.isoformat()
        fund['updated_at'] = now.isoformat()
        
        # Update foundation totals
        foundation['total_fund_balance'] -= amount
        foundation['total_claims_paid'] += amount
        foundation['updated_at'] = now.isoformat()
        
        self._log_activity(
            foundation_id=foundation['id'],
            activity_type='claim_paid',
            description=f"Claim #{claim_id} paid: ${amount:.2f} to {claim['claimant_display_name']}",
            actor_id=processor['id'],
            actor_name=processor['display_name'],
            actor_type=processor['role'],
            entity_type='claim',
            entity_id=claim_id,
            details={'amount': amount, 'payout_method': payout_method},
            ip_address=ip_address
        )
        
        return True, f"Payout of ${amount:.2f} processed successfully"
    
    def get_claims(self, foundation_id: str, status: str = None, 
                   claimant_id: str = None) -> List[Dict]:
        """Get claims for a foundation."""
        results = []
        
        for claim in self.claims.values():
            if claim['foundation_id'] != foundation_id:
                continue
            
            if status and claim['status'] != status:
                continue
            
            if claimant_id and claim['claimant_id'] != claimant_id:
                continue
            
            results.append(claim)
        
        # Sort by date descending
        results.sort(key=lambda c: c.get('submitted_at', ''), reverse=True)
        
        return results
    
    # =========================================================================
    # VOTING SYSTEM
    # =========================================================================
    
    def cast_vote(self,
                  vote_id: str,
                  user_id: str,
                  choice: str,
                  reason: str = None,
                  ip_address: str = None) -> Tuple[bool, str]:
        """
        Cast a vote on a proposal.
        
        Args:
            vote_id: Vote proposal ID
            user_id: Voter's user ID
            choice: 'for', 'against', or 'abstain'
            reason: Optional explanation
            ip_address: IP for audit
            
        Returns:
            Tuple of (success, message)
        """
        vote = self.votes.get(vote_id)
        if not vote:
            return False, "Vote not found"
        
        if vote['status'] != 'open':
            return False, f"Vote is not open (status: {vote['status']})"
        
        # Check if vote has expired
        closes_at = datetime.fromisoformat(vote['closes_at'])
        if datetime.utcnow() > closes_at:
            self._close_vote(vote_id)
            return False, "Vote has expired"
        
        foundation_id = vote['foundation_id']
        member = self._get_member_by_user(foundation_id, user_id)
        if not member:
            return False, "You are not a member of this foundation"
        
        if not member['status'] == 'active':
            return False, "Your membership is not active"
        
        if member['role'] not in ('founder', 'admin', 'member'):
            return False, "You do not have voting rights"
        
        if choice not in ('for', 'against', 'abstain'):
            return False, "Invalid choice. Use 'for', 'against', or 'abstain'"
        
        # Check if already voted
        existing_vote = None
        for vc in self.vote_casts.values():
            if vc['vote_id'] == vote_id and vc['member_id'] == member['id']:
                existing_vote = vc
                break
        
        if existing_vote:
            return False, "You have already voted on this proposal"
        
        now = datetime.utcnow()
        vote_cast_id = self.generate_vote_cast_id()
        
        vote_cast = {
            'id': vote_cast_id,
            'vote_id': vote_id,
            'member_id': member['id'],
            'choice': choice,
            'weight': member.get('voting_weight', 1.0),
            'reason': reason,
            'cast_at': now.isoformat()
        }
        
        self.vote_casts[vote_cast_id] = vote_cast
        
        # Update vote counts
        if choice == 'for':
            vote['votes_for'] += 1
        elif choice == 'against':
            vote['votes_against'] += 1
        else:
            vote['votes_abstain'] += 1
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type='vote_cast',
            description=f"{member['display_name']} voted {choice} on '{vote['title']}'",
            actor_id=member['id'],
            actor_name=member['display_name'],
            actor_type=member['role'],
            entity_type='vote',
            entity_id=vote_id,
            ip_address=ip_address
        )
        
        # Check if we can close the vote early
        self._check_vote_completion(vote_id)
        
        return True, f"Vote recorded: {choice}"
    
    def _check_vote_completion(self, vote_id: str):
        """Check if a vote can be closed early (clear majority)."""
        vote = self.votes.get(vote_id)
        if not vote or vote['status'] != 'open':
            return
        
        total_voted = vote['votes_for'] + vote['votes_against'] + vote['votes_abstain']
        
        # Need quorum
        if total_voted < vote['total_eligible'] * vote['quorum']:
            return
        
        # Check for clear majority that can't be overturned
        remaining = vote['total_eligible'] - total_voted
        
        # If even all remaining votes can't change outcome, close early
        if vote['votes_for'] > (vote['votes_against'] + remaining) * vote['threshold']:
            self._close_vote(vote_id, result='passed')
        elif vote['votes_against'] >= vote['total_eligible'] * (1 - vote['threshold']):
            self._close_vote(vote_id, result='failed')
    
    def _close_vote(self, vote_id: str, result: str = None):
        """Close a vote and determine result."""
        vote = self.votes.get(vote_id)
        if not vote or vote['status'] != 'open':
            return
        
        now = datetime.utcnow()
        
        total_voted = vote['votes_for'] + vote['votes_against']
        
        # Calculate result if not provided
        if result is None:
            # Check quorum
            participation = (vote['votes_for'] + vote['votes_against'] + vote['votes_abstain']) / vote['total_eligible']
            if participation < vote['quorum']:
                result = 'failed'
                vote['result'] = 'Failed: Quorum not reached'
            elif total_voted == 0:
                result = 'failed'
                vote['result'] = 'Failed: No votes cast'
            elif vote['votes_for'] / total_voted >= vote['threshold']:
                result = 'passed'
                vote['result'] = f"Passed: {vote['votes_for']}/{total_voted} votes"
            else:
                result = 'failed'
                vote['result'] = f"Failed: {vote['votes_for']}/{total_voted} votes (needed {vote['threshold']*100:.0f}%)"
        else:
            vote['result'] = result.capitalize()
        
        vote['status'] = result
        vote['closed_at'] = now.isoformat()
        
        # If this was a claim vote, update the claim
        if vote['related_entity_type'] == 'claim' and vote['related_entity_id']:
            claim = self.claims.get(vote['related_entity_id'])
            if claim:
                if result == 'passed':
                    claim['status'] = 'approved'
                    claim['amount_approved'] = claim['amount_requested']
                    claim['approved_at'] = now.isoformat()
                    claim['review_notes'] = f"Approved by vote: {vote['result']}"
                else:
                    claim['status'] = 'rejected'
                    claim['rejection_reason'] = vote['result']
                    claim['reviewed_at'] = now.isoformat()
                claim['updated_at'] = now.isoformat()
    
    def get_active_votes(self, foundation_id: str) -> List[Dict]:
        """Get all active votes for a foundation."""
        results = []
        
        for vote in self.votes.values():
            if vote['foundation_id'] != foundation_id:
                continue
            
            # Check if expired
            if vote['status'] == 'open':
                closes_at = datetime.fromisoformat(vote['closes_at'])
                if datetime.utcnow() > closes_at:
                    self._close_vote(vote['id'])
                    continue
            
            if vote['status'] == 'open':
                results.append(vote)
        
        return results
    
    def founder_veto(self,
                     vote_id: str,
                     founder_id: str,
                     reason: str,
                     ip_address: str = None) -> Tuple[bool, str]:
        """Exercise founder veto on a passed vote."""
        vote = self.votes.get(vote_id)
        if not vote:
            return False, "Vote not found"
        
        if vote['status'] != 'passed':
            return False, "Can only veto passed votes"
        
        foundation = self.foundations.get(vote['foundation_id'])
        if not foundation:
            return False, "Foundation not found"
        
        if not foundation.get('founder_veto_enabled'):
            return False, "Founder veto is not enabled for this foundation"
        
        # Verify founder
        member = self._get_member_by_user(foundation['id'], founder_id)
        if not member or member['role'] != 'founder':
            return False, "Only the founder can exercise veto"
        
        now = datetime.utcnow()
        
        vote['vetoed'] = True
        vote['vetoed_by'] = member['id']
        vote['vetoed_at'] = now.isoformat()
        vote['veto_reason'] = reason
        vote['status'] = 'failed'
        vote['result'] = f"Vetoed by founder: {reason}"
        
        # If this was a claim vote, update the claim
        if vote['related_entity_type'] == 'claim' and vote['related_entity_id']:
            claim = self.claims.get(vote['related_entity_id'])
            if claim:
                claim['status'] = 'rejected'
                claim['rejection_reason'] = f"Founder veto: {reason}"
                claim['reviewed_at'] = now.isoformat()
                claim['updated_at'] = now.isoformat()
        
        self._log_activity(
            foundation_id=foundation['id'],
            activity_type='vote_vetoed',
            description=f"Founder vetoed '{vote['title']}': {reason}",
            actor_id=member['id'],
            actor_name=member['display_name'],
            actor_type='founder',
            entity_type='vote',
            entity_id=vote_id,
            details={'reason': reason},
            ip_address=ip_address
        )
        
        return True, "Veto exercised successfully"
    
    # =========================================================================
    # FUNDS MANAGEMENT
    # =========================================================================
    
    def get_funds(self, foundation_id: str) -> List[Dict]:
        """Get all funds for a foundation."""
        results = []
        
        for fund in self.funds.values():
            if fund['foundation_id'] == foundation_id:
                results.append(fund)
        
        return results
    
    def create_fund(self,
                    foundation_id: str,
                    creator_id: str,
                    name: str,
                    fund_type: str,
                    description: str = None,
                    min_reserve_percentage: float = 0.20,
                    max_claim_percentage: float = 0.25,
                    auto_approve_threshold: float = 500.0,
                    ip_address: str = None) -> Tuple[bool, str, Optional[Dict]]:
        """Create a new fund in a foundation."""
        foundation = self.foundations.get(foundation_id)
        if not foundation:
            return False, "Foundation not found", None
        
        # Verify creator is founder or admin
        member = self._get_member_by_user(foundation_id, creator_id)
        if not member or member['role'] not in ('founder', 'admin'):
            return False, "Only founders and admins can create funds", None
        
        now = datetime.utcnow()
        fund_id = self.generate_fund_id()
        
        fund = {
            'id': fund_id,
            'foundation_id': foundation_id,
            'name': name,
            'description': description,
            'fund_type': fund_type,
            'balance': 0.0,
            'currency': foundation['currency'],
            'total_deposits': 0.0,
            'total_withdrawals': 0.0,
            'total_claims_paid': 0.0,
            'min_reserve_percentage': min_reserve_percentage,
            'max_claim_percentage': max_claim_percentage,
            'auto_approve_threshold': auto_approve_threshold,
            'claim_waiting_period_days': 30,
            'status': 'active',
            'frozen_at': None,
            'frozen_reason': None,
            'created_at': now.isoformat(),
            'updated_at': now.isoformat(),
            'last_activity_at': None
        }
        
        self.funds[fund_id] = fund
        
        self._log_activity(
            foundation_id=foundation_id,
            activity_type='fund_created',
            description=f"Fund '{name}' created by {member['display_name']}",
            actor_id=member['id'],
            actor_name=member['display_name'],
            actor_type=member['role'],
            entity_type='fund',
            entity_id=fund_id,
            ip_address=ip_address
        )
        
        return True, "Fund created successfully", fund
    
    # =========================================================================
    # ACTIVITY LOG
    # =========================================================================
    
    def _log_activity(self,
                      foundation_id: str,
                      activity_type: str,
                      description: str,
                      actor_id: str = None,
                      actor_name: str = None,
                      actor_type: str = None,
                      entity_type: str = None,
                      entity_id: str = None,
                      details: Dict = None,
                      ip_address: str = None):
        """Log an activity."""
        activity_id = self.generate_activity_id()
        
        activity = {
            'id': activity_id,
            'foundation_id': foundation_id,
            'activity_type': activity_type,
            'activity_description': description,
            'actor_id': actor_id,
            'actor_name': actor_name,
            'actor_type': actor_type,
            'entity_type': entity_type,
            'entity_id': entity_id,
            'details': json.dumps(details) if details else None,
            'ip_address': ip_address,
            'created_at': datetime.utcnow().isoformat()
        }
        
        self.activities[activity_id] = activity
    
    def get_activities(self, foundation_id: str, limit: int = 50) -> List[Dict]:
        """Get recent activities for a foundation."""
        results = []
        
        for activity in self.activities.values():
            if activity['foundation_id'] == foundation_id:
                results.append(activity)
        
        # Sort by date descending
        results.sort(key=lambda a: a.get('created_at', ''), reverse=True)
        
        return results[:limit]
    
    # =========================================================================
    # FOUNDATION TYPE INFO
    # =========================================================================
    
    def get_foundation_types(self) -> Dict[str, Dict]:
        """Get all available foundation types with descriptions."""
        return self.foundation_types
    
    def get_foundation_type_info(self, foundation_type: str) -> Optional[Dict]:
        """Get info for a specific foundation type."""
        return self.foundation_types.get(foundation_type)


# Singleton instance for easy import
foundation_service = FoundationService()
