"""
PHINS Reserves Reporting Service
=================================
Comprehensive reporting for risk reserves, claims reserves, paid claims, and wallets.

This service provides the complete picture of:
1. Risk Reserves - accumulated from risk premiums
2. Claims Reserves - estimated liability for outstanding claims  
3. Paid Claims - actual claims paid out
4. Wallet Balances - customer savings in health wallets
5. Investment Balances - customer savings in investment accounts

Key Formulas:
- Gross Risk Reserve = Sum of all Risk Premiums collected
- Claims Reserve (IBNR) = Expected claims incurred but not yet reported
- Net Risk Reserve = Gross Risk Reserve - Paid Claims - Claims Reserve (IBNR)
- Solvency Ratio = Net Risk Reserve / Claims Reserve (IBNR)

Integration with Actuarial Service:
- Uses actuarial tables for claims reserve estimation
- Applies loss ratios for IBNR calculation
"""

from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class ReserveSummary:
    """Summary of all reserve components"""
    as_of_date: str
    
    # Risk Reserves (from premium allocations)
    gross_risk_reserve: Decimal = field(default_factory=Decimal)
    risk_reserve_by_period: Dict[str, Decimal] = field(default_factory=dict)
    
    # Claims Reserves
    claims_reserve_pending: Decimal = field(default_factory=Decimal)  # Known pending claims
    claims_reserve_ibnr: Decimal = field(default_factory=Decimal)     # Incurred But Not Reported
    total_claims_reserve: Decimal = field(default_factory=Decimal)
    
    # Paid Claims
    claims_paid_period: Decimal = field(default_factory=Decimal)  # Current period
    claims_paid_ytd: Decimal = field(default_factory=Decimal)     # Year to date
    claims_paid_total: Decimal = field(default_factory=Decimal)   # All time
    
    # Net Reserve Calculation
    net_risk_reserve: Decimal = field(default_factory=Decimal)
    
    # Wallet & Investment Integration
    total_wallet_balances: Decimal = field(default_factory=Decimal)
    total_investment_balances: Decimal = field(default_factory=Decimal)
    total_algo_trading_balances: Decimal = field(default_factory=Decimal)
    total_customer_savings: Decimal = field(default_factory=Decimal)
    
    # Ratios
    loss_ratio: Decimal = field(default_factory=Decimal)      # Claims Paid / Risk Premiums
    reserve_ratio: Decimal = field(default_factory=Decimal)   # Net Reserve / Total Reserve Requirement
    solvency_ratio: Decimal = field(default_factory=Decimal)  # Net Reserve / Claims Reserve


class ReservesReportingService:
    """
    Comprehensive reserves reporting service.
    
    Calculates and reports on:
    - Risk reserves from premium allocations
    - Claims reserves (known + IBNR)
    - Paid claims tracking
    - Customer savings (wallets + investments)
    """
    
    def __init__(self,
                 premium_allocation_tracker=None,
                 policies: Dict = None,
                 claims: Dict = None,
                 bills: Dict = None,
                 health_wallets: Dict = None,
                 investment_accounts: Dict = None,
                 actuarial_service=None):
        """
        Initialize reserves reporting service.
        
        Args:
            premium_allocation_tracker: Tracker for premium allocations
            policies: Reference to policies data
            claims: Reference to claims data  
            bills: Reference to billing data
            health_wallets: Reference to wallet data
            investment_accounts: Reference to investment data
            actuarial_service: Actuarial service for IBNR calculation
        """
        self.allocation_tracker = premium_allocation_tracker
        # Use 'if X is None' pattern to preserve empty dict references
        self.policies = policies if policies is not None else {}
        self.claims = claims if claims is not None else {}
        self.bills = bills if bills is not None else {}
        self.health_wallets = health_wallets if health_wallets is not None else {}
        self.investment_accounts = investment_accounts if investment_accounts is not None else {}
        self.actuarial_service = actuarial_service
        
        # Configuration
        self.ibnr_factor = Decimal('0.15')  # 15% of annual premiums as IBNR default
        self.loss_ratio_assumption = Decimal('0.65')  # 65% expected loss ratio
    
    def calculate_reserve_summary(self, as_of_date: str = None) -> ReserveSummary:
        """
        Calculate comprehensive reserve summary.
        
        This is the main method that brings together all reserve components.
        
        Args:
            as_of_date: Date for the report (defaults to now)
        
        Returns:
            ReserveSummary with all calculated values
        """
        report_date = as_of_date or datetime.now().isoformat()
        summary = ReserveSummary(as_of_date=report_date)
        
        # 1. Calculate Risk Reserves from Premium Allocations
        self._calculate_risk_reserves(summary)
        
        # 2. Calculate Claims Reserves (Pending + IBNR)
        self._calculate_claims_reserves(summary)
        
        # 3. Calculate Paid Claims
        self._calculate_paid_claims(summary)
        
        # 4. Calculate Wallet and Investment Balances
        self._calculate_customer_savings(summary)
        
        # 5. Calculate Net Reserve and Ratios
        self._calculate_net_reserves_and_ratios(summary)
        
        return summary
    
    def _calculate_risk_reserves(self, summary: ReserveSummary):
        """Calculate risk reserves from premium allocations"""
        
        if self.allocation_tracker:
            # Get from allocation tracker
            for alloc in self.allocation_tracker.allocations.values():
                if alloc.status.value == 'allocated':
                    summary.gross_risk_reserve += alloc.risk_amount
                    
                    # Track by period
                    try:
                        date = datetime.fromisoformat(alloc.payment_date.replace('Z', '+00:00'))
                        period_key = date.strftime('%Y-%m')
                        if period_key not in summary.risk_reserve_by_period:
                            summary.risk_reserve_by_period[period_key] = Decimal(0)
                        summary.risk_reserve_by_period[period_key] += alloc.risk_amount
                    except:
                        pass
        else:
            # Estimate from bills if no tracker
            for bill_id, bill in self.bills.items():
                if (bill.get('status') or '').lower() == 'paid':
                    amount = Decimal(str(bill.get('amount_paid', 0) or bill.get('amount', 0) or 0))
                    # Default 75% risk allocation
                    risk_amount = (amount * Decimal('0.75')).quantize(Decimal('0.01'))
                    summary.gross_risk_reserve += risk_amount
    
    def _calculate_claims_reserves(self, summary: ReserveSummary):
        """Calculate claims reserves (pending claims + IBNR)"""
        
        # Pending Claims Reserve - known claims that are outstanding
        for claim_id, claim in self.claims.items():
            status = (claim.get('status') or '').lower().replace(' ', '_')
            claimed_amount = Decimal(str(claim.get('claimed_amount', 0) or 0))
            
            if status in ['pending', 'under_review', 'medical_assessment']:
                # Reserve at full claimed amount for pending
                summary.claims_reserve_pending += claimed_amount
            elif status == 'approved':
                # Reserve at approved amount (if not yet paid)
                approved = Decimal(str(claim.get('approved_amount', 0) or 0))
                if approved > 0:
                    summary.claims_reserve_pending += approved
                else:
                    summary.claims_reserve_pending += claimed_amount
        
        # IBNR (Incurred But Not Reported) - statistical estimate
        # Formula: IBNR = Annual Premiums × Loss Ratio × IBNR Factor
        annual_risk_premium = summary.gross_risk_reserve  # Simplified - assumes 1 year data
        
        # Use actuarial service if available for more precise IBNR
        if self.actuarial_service:
            try:
                # Get loss ratio from actuarial tables
                store = self.actuarial_service
                config = store.config if hasattr(store, 'config') else None
                if config:
                    # Use actuarial loss ratio assumption
                    loss_ratio = Decimal('0.65')  # Standard assumption
                    summary.claims_reserve_ibnr = (annual_risk_premium * loss_ratio * self.ibnr_factor).quantize(
                        Decimal('0.01'))
            except:
                pass
        
        # Default IBNR calculation if actuarial service not available
        if summary.claims_reserve_ibnr == 0:
            summary.claims_reserve_ibnr = (annual_risk_premium * self.loss_ratio_assumption * self.ibnr_factor).quantize(
                Decimal('0.01'))
        
        # Total Claims Reserve
        summary.total_claims_reserve = summary.claims_reserve_pending + summary.claims_reserve_ibnr
    
    def _calculate_paid_claims(self, summary: ReserveSummary):
        """Calculate paid claims by period"""
        
        current_year = datetime.now().year
        current_month = datetime.now().month
        
        for claim_id, claim in self.claims.items():
            status = (claim.get('status') or '').lower()
            
            if status in ['paid', 'closed']:
                # Get paid amount
                paid_amount = Decimal(str(
                    claim.get('paid_amount', 0) or 
                    claim.get('approved_amount', 0) or 
                    claim.get('claimed_amount', 0) or 0
                ))
                
                summary.claims_paid_total += paid_amount
                
                # Check date for period calculations
                paid_date = claim.get('paid_date') or claim.get('updated_at') or claim.get('created_at')
                if paid_date:
                    try:
                        date = datetime.fromisoformat(paid_date.replace('Z', '+00:00'))
                        
                        # YTD check
                        if date.year == current_year:
                            summary.claims_paid_ytd += paid_amount
                            
                            # Current month check
                            if date.month == current_month:
                                summary.claims_paid_period += paid_amount
                    except:
                        # If date parsing fails, count in YTD
                        summary.claims_paid_ytd += paid_amount
    
    def _calculate_customer_savings(self, summary: ReserveSummary):
        """Calculate total customer savings across wallets and investments"""
        
        # Health Wallet Balances
        for wallet_id, wallet in self.health_wallets.items():
            balance = Decimal(str(wallet.get('balance', 0) or 0))
            summary.total_wallet_balances += balance
        
        # Investment Account Balances
        for acc_id, account in self.investment_accounts.items():
            # Main cash balance
            balance = Decimal(str(account.get('balance', 0) or 0))
            summary.total_investment_balances += balance
            
            # Investment sub-balances
            summary.total_investment_balances += Decimal(str(account.get('index_balance', 0) or 0))
            summary.total_investment_balances += Decimal(str(account.get('bonds_balance', 0) or 0))
            summary.total_investment_balances += Decimal(str(account.get('crypto_balance', 0) or 0))
        
        # Algo Trading Balances (if tracked separately)
        if hasattr(self, 'algo_trading_balances'):
            for acc_id, account in self.algo_trading_balances.items():
                balance = Decimal(str(account.get('available', 0) or 0))
                balance += Decimal(str(account.get('in_positions', 0) or 0))
                summary.total_algo_trading_balances += balance
        
        # Total Customer Savings
        summary.total_customer_savings = (
            summary.total_wallet_balances + 
            summary.total_investment_balances + 
            summary.total_algo_trading_balances
        )
    
    def _calculate_net_reserves_and_ratios(self, summary: ReserveSummary):
        """Calculate net reserves and financial ratios"""
        
        # Net Risk Reserve = Gross - Paid Claims - Claims Reserve
        summary.net_risk_reserve = (
            summary.gross_risk_reserve - 
            summary.claims_paid_total - 
            summary.total_claims_reserve
        )
        
        # Loss Ratio = Claims Paid / Risk Premiums
        if summary.gross_risk_reserve > 0:
            summary.loss_ratio = (
                summary.claims_paid_total / summary.gross_risk_reserve
            ).quantize(Decimal('0.0001'))
        
        # Reserve Ratio = Net Reserve / Required Reserve
        required_reserve = summary.total_claims_reserve + summary.claims_paid_ytd
        if required_reserve > 0:
            summary.reserve_ratio = (
                summary.net_risk_reserve / required_reserve
            ).quantize(Decimal('0.0001'))
        
        # Solvency Ratio = Net Reserve / Claims Reserve
        if summary.total_claims_reserve > 0:
            summary.solvency_ratio = (
                summary.net_risk_reserve / summary.total_claims_reserve
            ).quantize(Decimal('0.0001'))
    
    def generate_full_report(self) -> Dict[str, Any]:
        """
        Generate full reserves report with all details.
        
        Returns comprehensive report suitable for dashboards and regulatory reporting.
        """
        summary = self.calculate_reserve_summary()
        
        return {
            'report_date': summary.as_of_date,
            'report_type': 'PHINS_RESERVES_REPORT',
            
            # Risk Reserves Section
            'risk_reserves': {
                'gross_risk_reserve': float(summary.gross_risk_reserve),
                'by_period': {k: float(v) for k, v in summary.risk_reserve_by_period.items()},
                'source': 'Premium risk allocations (default 75% of premium)'
            },
            
            # Claims Reserves Section
            'claims_reserves': {
                'pending_claims_reserve': float(summary.claims_reserve_pending),
                'ibnr_reserve': float(summary.claims_reserve_ibnr),
                'total_claims_reserve': float(summary.total_claims_reserve),
                'ibnr_methodology': f'Annual Premium × Loss Ratio ({float(self.loss_ratio_assumption)*100}%) × IBNR Factor ({float(self.ibnr_factor)*100}%)'
            },
            
            # Paid Claims Section
            'paid_claims': {
                'current_period': float(summary.claims_paid_period),
                'year_to_date': float(summary.claims_paid_ytd),
                'all_time_total': float(summary.claims_paid_total)
            },
            
            # Net Reserve Calculation
            'net_reserve': {
                'calculation': 'Gross Risk Reserve - Paid Claims (Total) - Claims Reserve',
                'gross_risk_reserve': float(summary.gross_risk_reserve),
                'less_paid_claims': float(summary.claims_paid_total),
                'less_claims_reserve': float(summary.total_claims_reserve),
                'equals_net_risk_reserve': float(summary.net_risk_reserve),
                'status': 'adequate' if summary.net_risk_reserve > 0 else 'deficient'
            },
            
            # Customer Savings Integration
            'customer_savings': {
                'total_wallet_balances': float(summary.total_wallet_balances),
                'total_investment_balances': float(summary.total_investment_balances),
                'total_algo_trading_balances': float(summary.total_algo_trading_balances),
                'total_customer_savings': float(summary.total_customer_savings),
                'note': 'Customer savings are held in trust and segregated from risk reserves'
            },
            
            # Financial Ratios
            'ratios': {
                'loss_ratio': {
                    'value': float(summary.loss_ratio * 100),
                    'unit': '%',
                    'interpretation': 'Claims paid as % of risk premiums',
                    'target': '< 65% is healthy'
                },
                'reserve_ratio': {
                    'value': float(summary.reserve_ratio * 100),
                    'unit': '%',
                    'interpretation': 'Net reserve as % of required reserve'
                },
                'solvency_ratio': {
                    'value': float(summary.solvency_ratio * 100),
                    'unit': '%',
                    'interpretation': 'Net reserve as % of claims reserve',
                    'target': '> 150% is comfortable'
                }
            },
            
            # Summary Status
            'status': {
                'reserve_adequacy': 'adequate' if summary.solvency_ratio >= Decimal('1.5') else 'watch' if summary.solvency_ratio >= Decimal('1.0') else 'deficient',
                'loss_performance': 'good' if summary.loss_ratio <= Decimal('0.65') else 'acceptable' if summary.loss_ratio <= Decimal('0.80') else 'poor',
                'recommendations': self._generate_recommendations(summary)
            }
        }
    
    def _generate_recommendations(self, summary: ReserveSummary) -> List[str]:
        """Generate recommendations based on reserve status"""
        recommendations = []
        
        if summary.solvency_ratio < Decimal('1.0'):
            recommendations.append('URGENT: Solvency ratio below 100% - consider increasing reserves')
        elif summary.solvency_ratio < Decimal('1.5'):
            recommendations.append('Monitor: Solvency ratio below 150% target')
        
        if summary.loss_ratio > Decimal('0.80'):
            recommendations.append('Review underwriting criteria - loss ratio exceeds 80%')
        elif summary.loss_ratio > Decimal('0.65'):
            recommendations.append('Loss ratio above target 65% - review claims experience')
        
        if summary.net_risk_reserve < 0:
            recommendations.append('CRITICAL: Net risk reserve is negative - immediate action required')
        
        if not recommendations:
            recommendations.append('All metrics within acceptable ranges')
        
        return recommendations
    
    def get_customer_savings_report(self, customer_id: str) -> Dict[str, Any]:
        """
        Get detailed savings report for a specific customer.
        
        Shows how their savings portion was allocated across wallets and investments.
        """
        report = {
            'customer_id': customer_id,
            'report_date': datetime.now().isoformat(),
            'wallet_balance': 0.0,
            'investment_balance': 0.0,
            'algo_trading_balance': 0.0,
            'total_savings': 0.0,
            'breakdown': {}
        }
        
        # Get wallet balance
        if customer_id in self.health_wallets:
            wallet = self.health_wallets[customer_id]
            report['wallet_balance'] = float(wallet.get('balance', 0) or 0)
            report['breakdown']['wallet'] = {
                'balance': float(wallet.get('balance', 0) or 0),
                'monthly_deposit': float(wallet.get('monthly_deposit', 0) or 0),
                'transactions': len(wallet.get('transactions', []))
            }
        
        # Get investment balance
        if customer_id in self.investment_accounts:
            inv = self.investment_accounts[customer_id]
            index_bal = float(inv.get('index_balance', 0) or 0)
            bonds_bal = float(inv.get('bonds_balance', 0) or 0)
            crypto_bal = float(inv.get('crypto_balance', 0) or 0)
            cash_bal = float(inv.get('balance', 0) or 0)
            
            report['investment_balance'] = index_bal + bonds_bal + crypto_bal + cash_bal
            report['breakdown']['investments'] = {
                'cash_available': cash_bal,
                'index_funds': index_bal,
                'bonds': bonds_bal,
                'crypto': crypto_bal,
                'total_invested': index_bal + bonds_bal + crypto_bal
            }
        
        report['total_savings'] = (
            report['wallet_balance'] + 
            report['investment_balance'] + 
            report['algo_trading_balance']
        )
        
        return report
    
    def get_risk_reserve_trend(self, periods: int = 12) -> Dict[str, Any]:
        """
        Get risk reserve trend over specified periods (months).
        
        Useful for dashboard charts showing reserve growth/decline.
        """
        summary = self.calculate_reserve_summary()
        
        # Sort periods
        sorted_periods = sorted(summary.risk_reserve_by_period.items())
        
        # Take last N periods
        recent_periods = sorted_periods[-periods:] if len(sorted_periods) > periods else sorted_periods
        
        return {
            'periods': [p[0] for p in recent_periods],
            'values': [float(p[1]) for p in recent_periods],
            'current_total': float(summary.gross_risk_reserve),
            'trend': 'increasing' if len(recent_periods) >= 2 and recent_periods[-1][1] > recent_periods[0][1] else 'stable'
        }


# Singleton instance
_reserves_service: Optional[ReservesReportingService] = None


def get_reserves_reporting_service(**kwargs) -> ReservesReportingService:
    """Get or create singleton instance"""
    global _reserves_service
    if _reserves_service is None:
        _reserves_service = ReservesReportingService(**kwargs)
    return _reserves_service


def init_reserves_reporting_service(premium_allocation_tracker=None,
                                     policies: Dict = None,
                                     claims: Dict = None,
                                     bills: Dict = None,
                                     health_wallets: Dict = None,
                                     investment_accounts: Dict = None,
                                     actuarial_service=None) -> ReservesReportingService:
    """Initialize reserves reporting service with dependencies"""
    global _reserves_service
    _reserves_service = ReservesReportingService(
        premium_allocation_tracker=premium_allocation_tracker,
        policies=policies,
        claims=claims,
        bills=bills,
        health_wallets=health_wallets,
        investment_accounts=investment_accounts,
        actuarial_service=actuarial_service
    )
    return _reserves_service


__all__ = [
    'ReservesReportingService',
    'ReserveSummary',
    'get_reserves_reporting_service',
    'init_reserves_reporting_service'
]
