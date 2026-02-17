"""
PHINS Community Dashboard Service
=================================
Enhanced community/foundation dashboard with:
- Contracts management
- Investment tracking
- Community-specific BI
- Member governance tools
- Contribution analytics

Designed for community foundations to manage their collective
insurance, savings, and investment needs.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import defaultdict


class ContractType(Enum):
    """Types of community contracts"""
    INSURANCE_POOL = "insurance_pool"
    SAVINGS_AGREEMENT = "savings_agreement"
    INVESTMENT_FUND = "investment_fund"
    SERVICE_AGREEMENT = "service_agreement"
    SUPPLIER_CONTRACT = "supplier_contract"
    MEMBER_AGREEMENT = "member_agreement"
    GOVERNANCE_RULES = "governance_rules"
    CONTRIBUTION_SCHEDULE = "contribution_schedule"


class ContractStatus(Enum):
    """Contract lifecycle status"""
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    VOTE_IN_PROGRESS = "vote_in_progress"
    ACTIVE = "active"
    EXPIRED = "expired"
    TERMINATED = "terminated"
    SUSPENDED = "suspended"


class InvestmentType(Enum):
    """Types of community investments"""
    INDEX_FUND = "index_fund"
    BOND_FUND = "bond_fund"
    MONEY_MARKET = "money_market"
    REAL_ESTATE = "real_estate"
    CRYPTO_FUND = "crypto_fund"
    ESG_FUND = "esg_fund"
    CUSTOM = "custom"


class InvestmentStatus(Enum):
    """Investment allocation status"""
    PENDING = "pending"
    ALLOCATED = "allocated"
    PARTIAL = "partial"
    WITHDRAWN = "withdrawn"


@dataclass
class CommunityContract:
    """Community contract record"""
    contract_id: str
    foundation_id: str
    contract_type: ContractType
    title: str
    description: str
    
    # Parties
    parties: List[str]  # member_ids or external entity names
    
    # Terms
    terms_json: str  # JSON string of contract terms
    start_date: str
    end_date: Optional[str] = None
    auto_renew: bool = False
    
    # Financial
    total_value: float = 0.0
    currency: str = "USD"
    
    # Approval
    status: ContractStatus = ContractStatus.DRAFT
    requires_vote: bool = True
    vote_threshold: float = 0.50  # 50% approval needed
    vote_id: Optional[str] = None
    
    # Signatures
    signed_by: List[str] = field(default_factory=list)
    signatures_required: int = 1
    
    # Audit
    created_by: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    activated_at: Optional[str] = None
    
    # Attachments
    attachments: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['contract_type'] = self.contract_type.value
        result['status'] = self.status.value
        return result


@dataclass
class CommunityInvestment:
    """Community investment allocation"""
    investment_id: str
    foundation_id: str
    fund_id: str  # Foundation fund this is allocated from
    
    # Investment details
    investment_type: InvestmentType
    investment_name: str
    description: str = ""
    
    # Allocation
    allocated_amount: float = 0.0
    current_value: float = 0.0
    currency: str = "USD"
    shares_units: float = 0.0
    cost_basis: float = 0.0
    
    # Performance
    total_return: float = 0.0
    return_percentage: float = 0.0
    unrealized_gain_loss: float = 0.0
    realized_gain_loss: float = 0.0
    
    # Risk profile
    risk_level: str = "moderate"  # conservative, moderate, aggressive
    
    # Status
    status: InvestmentStatus = InvestmentStatus.PENDING
    
    # Governance
    requires_vote_to_withdraw: bool = True
    minimum_hold_days: int = 30
    
    # Timestamps
    allocated_at: Optional[str] = None
    last_valuation_date: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['investment_type'] = self.investment_type.value
        result['status'] = self.status.value
        return result


@dataclass
class CommunityDashboardMetrics:
    """Metrics for community dashboard"""
    foundation_id: str
    generated_at: str
    
    # Membership
    total_members: int = 0
    active_members: int = 0
    pending_members: int = 0
    
    # Financial
    total_fund_balance: float = 0.0
    total_contributions_mtd: float = 0.0
    total_contributions_ytd: float = 0.0
    average_contribution: float = 0.0
    
    # Investments
    total_invested: float = 0.0
    total_investment_value: float = 0.0
    investment_return: float = 0.0
    investment_return_pct: float = 0.0
    
    # Contracts
    active_contracts: int = 0
    pending_contracts: int = 0
    total_contract_value: float = 0.0
    
    # Claims/Disbursements
    total_claims_filed: int = 0
    total_claims_paid: float = 0.0
    pending_claims: int = 0
    
    # Governance
    open_votes: int = 0
    participation_rate: float = 0.0
    
    def to_dict(self) -> Dict:
        return asdict(self)


class CommunityDashboardService:
    """
    Service for managing community/foundation dashboards.
    
    Provides:
    - Contract management
    - Investment tracking
    - Community-specific analytics
    - Governance tools
    - Member engagement metrics
    """
    
    def __init__(self,
                 foundations: Dict = None,
                 foundation_members: Dict = None,
                 foundation_funds: Dict = None,
                 foundation_contributions: Dict = None,
                 foundation_claims: Dict = None,
                 foundation_votes: Dict = None,
                 community_contracts: Dict = None,
                 community_investments: Dict = None):
        """Initialize with data stores"""
        self.foundations = foundations or {}
        self.foundation_members = foundation_members or {}
        self.foundation_funds = foundation_funds or {}
        self.foundation_contributions = foundation_contributions or {}
        self.foundation_claims = foundation_claims or {}
        self.foundation_votes = foundation_votes or {}
        self.community_contracts = community_contracts if community_contracts is not None else {}
        self.community_investments = community_investments if community_investments is not None else {}
    
    def _generate_id(self, prefix: str) -> str:
        """Generate unique ID"""
        return f"{prefix}-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
    
    # =========================================================================
    # CONTRACT MANAGEMENT
    # =========================================================================
    
    def create_contract(self,
                       foundation_id: str,
                       contract_type: str,
                       title: str,
                       description: str,
                       terms: Dict,
                       parties: List[str],
                       created_by: str,
                       total_value: float = 0.0,
                       start_date: str = None,
                       end_date: str = None,
                       requires_vote: bool = True) -> Dict[str, Any]:
        """
        Create a new community contract.
        """
        if foundation_id not in self.foundations:
            return {'success': False, 'error': 'Foundation not found'}
        
        try:
            contract_type_enum = ContractType(contract_type.lower())
        except ValueError:
            return {'success': False, 'error': f'Invalid contract type: {contract_type}'}
        
        contract_id = self._generate_id("CTR")
        now = datetime.now(timezone.utc)
        
        contract = CommunityContract(
            contract_id=contract_id,
            foundation_id=foundation_id,
            contract_type=contract_type_enum,
            title=title,
            description=description,
            parties=parties,
            terms_json=json.dumps(terms),
            start_date=start_date or now.isoformat(),
            end_date=end_date,
            total_value=total_value,
            requires_vote=requires_vote,
            created_by=created_by,
            status=ContractStatus.DRAFT
        )
        
        self.community_contracts[contract_id] = contract
        
        return {
            'success': True,
            'contract_id': contract_id,
            'status': contract.status.value,
            'contract': contract.to_dict()
        }
    
    def submit_contract_for_approval(self, contract_id: str, submitted_by: str) -> Dict[str, Any]:
        """Submit a draft contract for approval/voting"""
        if contract_id not in self.community_contracts:
            return {'success': False, 'error': 'Contract not found'}
        
        contract = self.community_contracts[contract_id]
        
        if contract.status != ContractStatus.DRAFT:
            return {'success': False, 'error': f'Contract is not in draft status: {contract.status.value}'}
        
        if contract.requires_vote:
            contract.status = ContractStatus.VOTE_IN_PROGRESS
            vote_id = self._generate_id("VOTE")
            now = datetime.now(timezone.utc)
            self.foundation_votes[vote_id] = {
                'id': vote_id,
                'foundation_id': contract.foundation_id,
                'contract_id': contract.contract_id,
                'proposal_type': 'contract_approval',
                'title': f'Approve Contract: {contract.title}',
                'subject': contract.title,
                'description': contract.description,
                'status': 'open',
                'threshold': contract.vote_threshold,
                'votes_for': 0,
                'votes_against': 0,
                'votes_abstain': 0,
                'result': None,
                'created_by': submitted_by,
                'created_at': now.isoformat(),
                'opens_at': now.isoformat(),
                'closes_at': (now + timedelta(days=7)).isoformat(),
                'updated_at': now.isoformat()
            }
            contract.vote_id = vote_id
        else:
            contract.status = ContractStatus.PENDING_APPROVAL
        
        contract.updated_at = datetime.now(timezone.utc).isoformat()
        
        return {
            'success': True,
            'contract_id': contract_id,
            'status': contract.status.value,
            'vote_id': contract.vote_id if contract.requires_vote else None,
            'message': 'Contract submitted for voting' if contract.requires_vote else 'Contract pending approval'
        }
    
    def approve_contract(self, contract_id: str, approved_by: str) -> Dict[str, Any]:
        """Approve a contract (after successful vote or direct approval)"""
        if contract_id not in self.community_contracts:
            return {'success': False, 'error': 'Contract not found'}
        
        contract = self.community_contracts[contract_id]
        
        if contract.status not in [ContractStatus.PENDING_APPROVAL, ContractStatus.VOTE_IN_PROGRESS]:
            return {'success': False, 'error': f'Contract cannot be approved in current status: {contract.status.value}'}
        
        now = datetime.now(timezone.utc)
        contract.status = ContractStatus.ACTIVE
        contract.activated_at = now.isoformat()
        contract.updated_at = now.isoformat()
        
        if approved_by not in contract.signed_by:
            contract.signed_by.append(approved_by)
        
        return {
            'success': True,
            'contract_id': contract_id,
            'status': contract.status.value,
            'activated_at': contract.activated_at
        }
    
    def get_foundation_contracts(self, foundation_id: str, status: str = None) -> Dict[str, Any]:
        """Get all contracts for a foundation"""
        contracts = [c for c in self.community_contracts.values() 
                    if c.foundation_id == foundation_id]
        
        if status:
            contracts = [c for c in contracts if c.status.value == status.lower()]
        
        # Sort by created date descending
        contracts.sort(key=lambda x: x.created_at, reverse=True)
        
        return {
            'success': True,
            'foundation_id': foundation_id,
            'total_contracts': len(contracts),
            'contracts': [c.to_dict() for c in contracts]
        }
    
    # =========================================================================
    # INVESTMENT MANAGEMENT
    # =========================================================================
    
    def create_investment_allocation(self,
                                     foundation_id: str,
                                     fund_id: str,
                                     investment_type: str,
                                     investment_name: str,
                                     amount: float,
                                     risk_level: str = "moderate",
                                     description: str = "") -> Dict[str, Any]:
        """
        Create a new investment allocation for a foundation fund.
        """
        if foundation_id not in self.foundations:
            return {'success': False, 'error': 'Foundation not found'}
        
        # Validate fund belongs to foundation
        fund = None
        for f_id, f in self.foundation_funds.items():
            if f_id == fund_id and f.get('foundation_id') == foundation_id:
                fund = f
                break
        
        if not fund:
            return {'success': False, 'error': 'Fund not found or does not belong to foundation'}
        
        # Check fund balance
        fund_balance = float(fund.get('balance', 0))
        if fund_balance < amount:
            return {'success': False, 'error': f'Insufficient fund balance. Available: ${fund_balance}'}
        
        try:
            investment_type_enum = InvestmentType(investment_type.lower())
        except ValueError:
            return {'success': False, 'error': f'Invalid investment type: {investment_type}'}
        
        investment_id = self._generate_id("INV")
        now = datetime.now(timezone.utc)
        
        investment = CommunityInvestment(
            investment_id=investment_id,
            foundation_id=foundation_id,
            fund_id=fund_id,
            investment_type=investment_type_enum,
            investment_name=investment_name,
            description=description,
            allocated_amount=amount,
            current_value=amount,  # Initial value equals allocation
            cost_basis=amount,
            risk_level=risk_level,
            status=InvestmentStatus.ALLOCATED,
            allocated_at=now.isoformat()
        )
        
        # Deduct from fund
        fund['balance'] = fund_balance - amount
        
        self.community_investments[investment_id] = investment
        
        return {
            'success': True,
            'investment_id': investment_id,
            'allocated_amount': amount,
            'fund_remaining_balance': fund['balance'],
            'investment': investment.to_dict()
        }
    
    def update_investment_value(self, investment_id: str, new_value: float) -> Dict[str, Any]:
        """Update the current value of an investment (mark-to-market)"""
        if investment_id not in self.community_investments:
            return {'success': False, 'error': 'Investment not found'}
        
        investment = self.community_investments[investment_id]
        old_value = investment.current_value
        
        investment.current_value = new_value
        investment.unrealized_gain_loss = new_value - investment.cost_basis
        investment.total_return = new_value - investment.allocated_amount
        investment.return_percentage = (
            (investment.total_return / investment.allocated_amount * 100) 
            if investment.allocated_amount > 0 else 0
        )
        investment.last_valuation_date = datetime.now(timezone.utc).isoformat()
        
        return {
            'success': True,
            'investment_id': investment_id,
            'old_value': old_value,
            'new_value': new_value,
            'unrealized_gain_loss': investment.unrealized_gain_loss,
            'return_percentage': round(investment.return_percentage, 2)
        }
    
    def withdraw_investment(self, investment_id: str, amount: float, reason: str = "") -> Dict[str, Any]:
        """Withdraw funds from an investment"""
        if investment_id not in self.community_investments:
            return {'success': False, 'error': 'Investment not found'}
        
        investment = self.community_investments[investment_id]
        
        if investment.current_value < amount:
            return {'success': False, 'error': f'Insufficient investment value. Available: ${investment.current_value}'}
        
        # Calculate realized gain/loss on withdrawal
        withdrawal_ratio = amount / investment.current_value
        realized = (investment.current_value - investment.cost_basis) * withdrawal_ratio
        
        investment.current_value -= amount
        investment.cost_basis -= investment.cost_basis * withdrawal_ratio
        investment.realized_gain_loss += realized
        
        if investment.current_value < 0.01:
            investment.status = InvestmentStatus.WITHDRAWN
            investment.current_value = 0
        else:
            investment.status = InvestmentStatus.PARTIAL
        
        # Credit back to fund
        fund = self.foundation_funds.get(investment.fund_id)
        if fund:
            fund['balance'] = float(fund.get('balance', 0)) + amount
        
        return {
            'success': True,
            'investment_id': investment_id,
            'withdrawn_amount': amount,
            'realized_gain_loss': round(realized, 2),
            'remaining_value': round(investment.current_value, 2),
            'status': investment.status.value
        }
    
    def get_foundation_investments(self, foundation_id: str) -> Dict[str, Any]:
        """Get all investments for a foundation"""
        investments = [i for i in self.community_investments.values() 
                      if i.foundation_id == foundation_id]
        
        total_allocated = sum(i.allocated_amount for i in investments)
        total_current = sum(i.current_value for i in investments)
        total_return = total_current - total_allocated
        
        # Group by type
        by_type = defaultdict(lambda: {'count': 0, 'allocated': 0, 'current': 0})
        for inv in investments:
            t = inv.investment_type.value
            by_type[t]['count'] += 1
            by_type[t]['allocated'] += inv.allocated_amount
            by_type[t]['current'] += inv.current_value
        
        return {
            'success': True,
            'foundation_id': foundation_id,
            'total_investments': len(investments),
            'total_allocated': round(total_allocated, 2),
            'total_current_value': round(total_current, 2),
            'total_return': round(total_return, 2),
            'return_percentage': round((total_return / total_allocated * 100) if total_allocated > 0 else 0, 2),
            'by_type': {k: dict(v) for k, v in by_type.items()},
            'investments': [i.to_dict() for i in investments]
        }
    
    # =========================================================================
    # DASHBOARD METRICS
    # =========================================================================
    
    def get_dashboard_metrics(self, foundation_id: str) -> Dict[str, Any]:
        """Get comprehensive dashboard metrics for a foundation"""
        if foundation_id not in self.foundations:
            return {'success': False, 'error': 'Foundation not found'}
        
        foundation = self.foundations[foundation_id]
        now = datetime.now(timezone.utc)
        
        # Get members
        members = [m for m in self.foundation_members.values() 
                  if m.get('foundation_id') == foundation_id]
        active_members = [m for m in members if m.get('status') == 'active']
        
        # Get funds
        funds = [f for f in self.foundation_funds.values() 
                if f.get('foundation_id') == foundation_id]
        total_fund_balance = sum(float(f.get('balance', 0) or 0) for f in funds)
        
        # Get contributions (MTD and YTD)
        contributions = [c for c in self.foundation_contributions.values()
                        if c.get('fund_id') in [f.get('id') for f in funds]]
        
        mtd_start = now.replace(day=1)
        ytd_start = now.replace(month=1, day=1)
        
        mtd_contributions = sum(
            float(c.get('amount', 0) or 0) for c in contributions
            if c.get('paid_date') and c.get('paid_date') >= mtd_start.isoformat()
        )
        ytd_contributions = sum(
            float(c.get('amount', 0) or 0) for c in contributions
            if c.get('paid_date') and c.get('paid_date') >= ytd_start.isoformat()
        )
        
        # Get investments
        investments = [i for i in self.community_investments.values() 
                      if i.foundation_id == foundation_id]
        total_invested = sum(i.allocated_amount for i in investments)
        total_investment_value = sum(i.current_value for i in investments)
        
        # Get contracts
        contracts = [c for c in self.community_contracts.values() 
                    if c.foundation_id == foundation_id]
        active_contracts = [c for c in contracts if c.status == ContractStatus.ACTIVE]
        pending_contracts = [c for c in contracts 
                           if c.status in [ContractStatus.DRAFT, ContractStatus.PENDING_APPROVAL, ContractStatus.VOTE_IN_PROGRESS]]
        
        # Get claims
        claims = [c for c in self.foundation_claims.values()
                 if c.get('foundation_id') == foundation_id]
        pending_claims = [c for c in claims if c.get('status') in ['submitted', 'reviewing', 'vote_open']]
        paid_claims = sum(float(c.get('amount_approved', 0) or 0) for c in claims if c.get('status') == 'paid')
        
        # Get votes
        votes = [v for v in self.foundation_votes.values()
                if v.get('foundation_id') == foundation_id]
        open_votes = [v for v in votes if v.get('status') == 'open']
        
        # Calculate participation rate
        total_votes_cast = sum(v.get('votes_for', 0) + v.get('votes_against', 0) + v.get('votes_abstain', 0) 
                              for v in votes)
        possible_votes = len(votes) * len(active_members) if votes and active_members else 0
        participation_rate = (total_votes_cast / possible_votes * 100) if possible_votes > 0 else 0
        
        metrics = CommunityDashboardMetrics(
            foundation_id=foundation_id,
            generated_at=now.isoformat(),
            total_members=len(members),
            active_members=len(active_members),
            pending_members=len([m for m in members if m.get('status') == 'pending']),
            total_fund_balance=round(total_fund_balance, 2),
            total_contributions_mtd=round(mtd_contributions, 2),
            total_contributions_ytd=round(ytd_contributions, 2),
            average_contribution=round(ytd_contributions / len(active_members), 2) if active_members else 0,
            total_invested=round(total_invested, 2),
            total_investment_value=round(total_investment_value, 2),
            investment_return=round(total_investment_value - total_invested, 2),
            investment_return_pct=round((total_investment_value - total_invested) / total_invested * 100 if total_invested > 0 else 0, 2),
            active_contracts=len(active_contracts),
            pending_contracts=len(pending_contracts),
            total_contract_value=round(sum(c.total_value for c in active_contracts), 2),
            total_claims_filed=len(claims),
            total_claims_paid=round(paid_claims, 2),
            pending_claims=len(pending_claims),
            open_votes=len(open_votes),
            participation_rate=round(participation_rate, 1)
        )
        
        return {
            'success': True,
            'foundation': {
                'id': foundation_id,
                'name': foundation.get('name'),
                'type': foundation.get('foundation_type'),
                'status': foundation.get('status')
            },
            'metrics': metrics.to_dict(),
            'quick_actions': self._get_quick_actions(foundation_id, metrics)
        }
    
    def _get_quick_actions(self, foundation_id: str, metrics: CommunityDashboardMetrics) -> List[Dict]:
        """Generate suggested quick actions based on current metrics"""
        actions = []
        
        if metrics.pending_claims > 0:
            actions.append({
                'action': 'review_claims',
                'title': f'Review {metrics.pending_claims} Pending Claims',
                'priority': 'high',
                'url': f'/foundation/{foundation_id}/claims'
            })
        
        if metrics.open_votes > 0:
            actions.append({
                'action': 'vote',
                'title': f'Cast Vote on {metrics.open_votes} Open Proposals',
                'priority': 'high',
                'url': f'/foundation/{foundation_id}/votes'
            })
        
        if metrics.pending_contracts > 0:
            actions.append({
                'action': 'review_contracts',
                'title': f'Review {metrics.pending_contracts} Pending Contracts',
                'priority': 'medium',
                'url': f'/foundation/{foundation_id}/contracts'
            })
        
        if metrics.pending_members > 0:
            actions.append({
                'action': 'approve_members',
                'title': f'Approve {metrics.pending_members} Pending Members',
                'priority': 'medium',
                'url': f'/foundation/{foundation_id}/members'
            })
        
        if metrics.total_fund_balance > 10000 and metrics.total_invested == 0:
            actions.append({
                'action': 'invest_funds',
                'title': 'Consider Investing Idle Funds',
                'priority': 'low',
                'url': f'/foundation/{foundation_id}/investments'
            })
        
        return actions
    
    # =========================================================================
    # COMMUNITY BI ANALYTICS
    # =========================================================================
    
    def get_foundation_analytics(self, foundation_id: str) -> Dict[str, Any]:
        """Get detailed analytics for foundation dashboard"""
        if foundation_id not in self.foundations:
            return {'success': False, 'error': 'Foundation not found'}
        
        # Get all related data
        members = [m for m in self.foundation_members.values() 
                  if m.get('foundation_id') == foundation_id]
        funds = [f for f in self.foundation_funds.values() 
                if f.get('foundation_id') == foundation_id]
        investments = [i for i in self.community_investments.values() 
                      if i.foundation_id == foundation_id]
        contracts = [c for c in self.community_contracts.values() 
                    if c.foundation_id == foundation_id]
        
        # Member analytics
        member_analytics = {
            'total': len(members),
            'by_role': defaultdict(int),
            'by_status': defaultdict(int),
            'total_contributed': sum(float(m.get('total_contributed', 0) or 0) for m in members),
            'top_contributors': sorted(
                [(m.get('member_id'), float(m.get('total_contributed', 0) or 0)) for m in members],
                key=lambda x: x[1], reverse=True
            )[:5]
        }
        for m in members:
            member_analytics['by_role'][m.get('role', 'member')] += 1
            member_analytics['by_status'][m.get('status', 'unknown')] += 1
        member_analytics['by_role'] = dict(member_analytics['by_role'])
        member_analytics['by_status'] = dict(member_analytics['by_status'])
        
        # Fund analytics
        fund_analytics = {
            'total_funds': len(funds),
            'total_balance': sum(float(f.get('balance', 0) or 0) for f in funds),
            'by_type': defaultdict(lambda: {'count': 0, 'balance': 0})
        }
        for f in funds:
            t = f.get('fund_type', 'custom')
            fund_analytics['by_type'][t]['count'] += 1
            fund_analytics['by_type'][t]['balance'] += float(f.get('balance', 0) or 0)
        fund_analytics['by_type'] = {k: dict(v) for k, v in fund_analytics['by_type'].items()}
        
        # Investment analytics
        investment_analytics = {
            'total_investments': len(investments),
            'total_allocated': sum(i.allocated_amount for i in investments),
            'total_current_value': sum(i.current_value for i in investments),
            'total_unrealized_gain': sum(i.unrealized_gain_loss for i in investments),
            'total_realized_gain': sum(i.realized_gain_loss for i in investments),
            'by_type': defaultdict(lambda: {'count': 0, 'allocated': 0, 'current': 0, 'return': 0}),
            'by_risk': defaultdict(lambda: {'count': 0, 'amount': 0})
        }
        for i in investments:
            t = i.investment_type.value
            investment_analytics['by_type'][t]['count'] += 1
            investment_analytics['by_type'][t]['allocated'] += i.allocated_amount
            investment_analytics['by_type'][t]['current'] += i.current_value
            investment_analytics['by_type'][t]['return'] += i.total_return
            
            investment_analytics['by_risk'][i.risk_level]['count'] += 1
            investment_analytics['by_risk'][i.risk_level]['amount'] += i.current_value
        
        investment_analytics['by_type'] = {k: dict(v) for k, v in investment_analytics['by_type'].items()}
        investment_analytics['by_risk'] = {k: dict(v) for k, v in investment_analytics['by_risk'].items()}
        
        # Contract analytics
        contract_analytics = {
            'total_contracts': len(contracts),
            'by_type': defaultdict(int),
            'by_status': defaultdict(int),
            'total_value': sum(c.total_value for c in contracts),
            'active_value': sum(c.total_value for c in contracts if c.status == ContractStatus.ACTIVE)
        }
        for c in contracts:
            contract_analytics['by_type'][c.contract_type.value] += 1
            contract_analytics['by_status'][c.status.value] += 1
        contract_analytics['by_type'] = dict(contract_analytics['by_type'])
        contract_analytics['by_status'] = dict(contract_analytics['by_status'])
        
        # AI insights
        insights = []
        
        # Investment allocation insight
        total_balance = fund_analytics['total_balance']
        total_invested = investment_analytics['total_allocated']
        investment_ratio = total_invested / total_balance * 100 if total_balance > 0 else 0
        
        if investment_ratio < 30 and total_balance > 5000:
            insights.append({
                'type': 'recommendation',
                'title': 'Investment Opportunity',
                'description': f'Only {investment_ratio:.1f}% of funds are invested. Consider diversifying into growth assets.',
                'priority': 'medium'
            })
        
        # Member engagement insight
        active_ratio = len([m for m in members if m.get('status') == 'active']) / len(members) * 100 if members else 0
        if active_ratio < 80:
            insights.append({
                'type': 'alert',
                'title': 'Member Engagement',
                'description': f'Only {active_ratio:.1f}% of members are active. Consider outreach to inactive members.',
                'priority': 'high' if active_ratio < 60 else 'medium'
            })
        
        # Investment performance insight
        if investment_analytics['total_allocated'] > 0:
            return_pct = (investment_analytics['total_current_value'] - investment_analytics['total_allocated']) / investment_analytics['total_allocated'] * 100
            if return_pct > 10:
                insights.append({
                    'type': 'positive',
                    'title': 'Strong Investment Returns',
                    'description': f'Investments have returned {return_pct:.1f}%. Consider taking profits or rebalancing.',
                    'priority': 'info'
                })
            elif return_pct < -10:
                insights.append({
                    'type': 'alert',
                    'title': 'Investment Performance Alert',
                    'description': f'Investments are down {abs(return_pct):.1f}%. Review portfolio allocation.',
                    'priority': 'high'
                })
        
        return {
            'success': True,
            'foundation_id': foundation_id,
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'member_analytics': member_analytics,
            'fund_analytics': fund_analytics,
            'investment_analytics': investment_analytics,
            'contract_analytics': contract_analytics,
            'insights': insights
        }


# Singleton instance
_community_dashboard_service: Optional[CommunityDashboardService] = None


def get_community_dashboard_service(**kwargs) -> CommunityDashboardService:
    """Get or create community dashboard service singleton"""
    global _community_dashboard_service
    if _community_dashboard_service is None:
        _community_dashboard_service = CommunityDashboardService(**kwargs)
    return _community_dashboard_service


def init_community_dashboard_service(**kwargs) -> CommunityDashboardService:
    """Initialize community dashboard service with data stores"""
    global _community_dashboard_service
    _community_dashboard_service = CommunityDashboardService(**kwargs)
    return _community_dashboard_service
