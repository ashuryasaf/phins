"""
PHINS BI and Statistical Analytics Service
==========================================
Comprehensive Business Intelligence and Statistical Analysis for:
- System optimization
- Performance metrics
- Predictive analytics
- Trend analysis
- KPI monitoring
- Community/Foundation analytics

Provides AI-driven insights for decision making across the platform.
"""

import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import defaultdict
import random


class MetricCategory(Enum):
    """Categories of metrics"""
    FINANCIAL = "financial"
    OPERATIONAL = "operational"
    CUSTOMER = "customer"
    SUPPLIER = "supplier"
    CLAIMS = "claims"
    UNDERWRITING = "underwriting"
    MARKETPLACE = "marketplace"
    FOUNDATION = "foundation"
    DELIVERY = "delivery"


class TrendDirection(Enum):
    """Trend direction indicators"""
    STRONG_UP = "strong_up"
    UP = "up"
    STABLE = "stable"
    DOWN = "down"
    STRONG_DOWN = "strong_down"


class AlertSeverity(Enum):
    """Alert severity levels"""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class KPIMetric:
    """Key Performance Indicator metric"""
    name: str
    category: MetricCategory
    value: float
    unit: str  # count, currency, percentage, ratio
    period: str  # daily, weekly, monthly, yearly, all_time
    trend: TrendDirection = TrendDirection.STABLE
    change_percentage: float = 0.0
    target: Optional[float] = None
    target_achieved: bool = True
    historical_values: List[float] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['category'] = self.category.value
        result['trend'] = self.trend.value
        return result


@dataclass
class BIInsight:
    """Business Intelligence insight"""
    insight_id: str
    category: str
    title: str
    description: str
    severity: AlertSeverity
    metric_value: Optional[float] = None
    recommendation: Optional[str] = None
    affected_entities: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['severity'] = self.severity.value
        return result


@dataclass
class StatisticalSummary:
    """Statistical summary of a data series"""
    count: int
    mean: float
    median: float
    std_dev: float
    min_value: float
    max_value: float
    percentile_25: float
    percentile_75: float
    variance: float
    
    def to_dict(self) -> Dict:
        return asdict(self)


class BIAnalyticsService:
    """
    Comprehensive BI and Statistical Analytics Service.
    
    Provides:
    - Real-time KPI monitoring
    - Trend analysis
    - Predictive analytics
    - System optimization recommendations
    - Community/Foundation analytics
    - Financial performance tracking
    """
    
    def __init__(self,
                 customers: Dict = None,
                 suppliers: Dict = None,
                 policies: Dict = None,
                 claims: Dict = None,
                 bills: Dict = None,
                 underwriting_apps: Dict = None,
                 health_wallets: Dict = None,
                 investment_accounts: Dict = None,
                 transaction_ledger: Dict = None,
                 foundations: Dict = None,
                 foundation_members: Dict = None,
                 foundation_funds: Dict = None,
                 supplier_orders: Dict = None,
                 delivery_requests: Dict = None,
                 delivery_bids: Dict = None):
        """Initialize with all data stores"""
        self.customers = customers or {}
        self.suppliers = suppliers or {}
        self.policies = policies or {}
        self.claims = claims or {}
        self.bills = bills or {}
        self.underwriting_apps = underwriting_apps or {}
        self.health_wallets = health_wallets or {}
        self.investment_accounts = investment_accounts or {}
        self.transaction_ledger = transaction_ledger or {}
        self.foundations = foundations or {}
        self.foundation_members = foundation_members or {}
        self.foundation_funds = foundation_funds or {}
        self.supplier_orders = supplier_orders or {}
        self.delivery_requests = delivery_requests or {}
        self.delivery_bids = delivery_bids or {}
        
        # Cache for computed metrics
        self._metrics_cache = {}
        self._cache_timestamp = None
        self._cache_ttl_seconds = 300  # 5 minutes
        
        self._insight_counter = 0
    
    def _generate_insight_id(self) -> str:
        """Generate unique insight ID"""
        self._insight_counter += 1
        return f"INS-{datetime.now().strftime('%Y%m%d')}-{self._insight_counter:05d}"
    
    # =========================================================================
    # STATISTICAL UTILITIES
    # =========================================================================
    
    def _calculate_statistics(self, values: List[float]) -> StatisticalSummary:
        """Calculate comprehensive statistics for a data series"""
        if not values:
            return StatisticalSummary(
                count=0, mean=0, median=0, std_dev=0,
                min_value=0, max_value=0,
                percentile_25=0, percentile_75=0, variance=0
            )
        
        sorted_values = sorted(values)
        n = len(sorted_values)
        
        mean_val = statistics.mean(values)
        median_val = statistics.median(values)
        std_dev = statistics.stdev(values) if n > 1 else 0
        variance = statistics.variance(values) if n > 1 else 0
        
        # Percentiles
        p25_idx = int(n * 0.25)
        p75_idx = int(n * 0.75)
        
        return StatisticalSummary(
            count=n,
            mean=round(mean_val, 2),
            median=round(median_val, 2),
            std_dev=round(std_dev, 2),
            min_value=round(min(values), 2),
            max_value=round(max(values), 2),
            percentile_25=round(sorted_values[p25_idx], 2),
            percentile_75=round(sorted_values[p75_idx], 2),
            variance=round(variance, 2)
        )
    
    def _calculate_trend(self, values: List[float]) -> Tuple[TrendDirection, float]:
        """Calculate trend direction and percentage change"""
        if len(values) < 2:
            return TrendDirection.STABLE, 0.0
        
        # Compare last value to average of previous values
        recent = values[-1]
        previous_avg = statistics.mean(values[:-1])
        
        if previous_avg == 0:
            return TrendDirection.STABLE, 0.0
        
        change_pct = ((recent - previous_avg) / previous_avg) * 100
        
        if change_pct > 20:
            return TrendDirection.STRONG_UP, change_pct
        elif change_pct > 5:
            return TrendDirection.UP, change_pct
        elif change_pct < -20:
            return TrendDirection.STRONG_DOWN, change_pct
        elif change_pct < -5:
            return TrendDirection.DOWN, change_pct
        else:
            return TrendDirection.STABLE, change_pct
    
    # =========================================================================
    # CORE KPI DASHBOARD
    # =========================================================================
    
    def get_executive_dashboard(self) -> Dict[str, Any]:
        """
        Get executive-level dashboard with key metrics.
        
        Returns comprehensive view of platform health and performance.
        """
        now = datetime.now(timezone.utc)
        
        dashboard = {
            'generated_at': now.isoformat(),
            'summary': {},
            'financial_kpis': [],
            'operational_kpis': [],
            'customer_kpis': [],
            'insights': [],
            'alerts': []
        }
        
        # Financial KPIs
        dashboard['financial_kpis'] = self._get_financial_kpis()
        
        # Operational KPIs
        dashboard['operational_kpis'] = self._get_operational_kpis()
        
        # Customer KPIs
        dashboard['customer_kpis'] = self._get_customer_kpis()
        
        # Generate insights
        dashboard['insights'] = self._generate_insights()
        
        # Generate alerts
        dashboard['alerts'] = self._generate_alerts()
        
        # Executive summary
        total_premium = sum(float(p.get('annual_premium', 0) or 0) for p in self.policies.values())
        total_claims_paid = sum(
            float(c.get('approved_amount', 0) or c.get('paid_amount', 0) or 0) 
            for c in self.claims.values() 
            if str(c.get('status', '')).lower() in ['paid', 'approved']
        )
        
        dashboard['summary'] = {
            'total_customers': len(self.customers),
            'total_policies': len(self.policies),
            'active_policies': sum(1 for p in self.policies.values() if str(p.get('status', '')).lower() == 'active'),
            'total_premium_book': round(total_premium, 2),
            'total_claims_paid': round(total_claims_paid, 2),
            'loss_ratio': round((total_claims_paid / total_premium * 100) if total_premium > 0 else 0, 2),
            'total_suppliers': len(self.suppliers),
            'active_suppliers': sum(1 for s in self.suppliers.values() if s.get('status') == 'approved'),
            'wallet_total_balance': round(sum(float(w.get('balance', 0) or 0) for w in self.health_wallets.values()), 2),
            'total_foundations': len(self.foundations),
            'platform_health_score': self._calculate_platform_health_score()
        }
        
        return dashboard
    
    def _get_financial_kpis(self) -> List[Dict]:
        """Calculate financial KPIs"""
        kpis = []
        
        # Total Premium Revenue
        total_premium = sum(float(p.get('annual_premium', 0) or 0) for p in self.policies.values())
        kpis.append(KPIMetric(
            name="Total Premium Revenue",
            category=MetricCategory.FINANCIAL,
            value=round(total_premium, 2),
            unit="currency",
            period="all_time"
        ).to_dict())
        
        # Monthly Premium (estimated)
        monthly_premium = sum(float(p.get('monthly_premium', 0) or 0) for p in self.policies.values() 
                             if str(p.get('status', '')).lower() == 'active')
        kpis.append(KPIMetric(
            name="Monthly Recurring Premium",
            category=MetricCategory.FINANCIAL,
            value=round(monthly_premium, 2),
            unit="currency",
            period="monthly"
        ).to_dict())
        
        # Total Claims Paid
        total_claims_paid = sum(
            float(c.get('approved_amount', 0) or c.get('paid_amount', 0) or 0)
            for c in self.claims.values()
            if str(c.get('status', '')).lower() in ['paid', 'approved']
        )
        kpis.append(KPIMetric(
            name="Total Claims Paid",
            category=MetricCategory.FINANCIAL,
            value=round(total_claims_paid, 2),
            unit="currency",
            period="all_time"
        ).to_dict())
        
        # Loss Ratio
        loss_ratio = (total_claims_paid / total_premium * 100) if total_premium > 0 else 0
        kpis.append(KPIMetric(
            name="Loss Ratio",
            category=MetricCategory.FINANCIAL,
            value=round(loss_ratio, 2),
            unit="percentage",
            period="all_time",
            target=65.0,
            target_achieved=loss_ratio <= 65
        ).to_dict())
        
        # Wallet Total Balance
        wallet_total = sum(float(w.get('balance', 0) or 0) for w in self.health_wallets.values())
        kpis.append(KPIMetric(
            name="Total Wallet Balances",
            category=MetricCategory.FINANCIAL,
            value=round(wallet_total, 2),
            unit="currency",
            period="current"
        ).to_dict())
        
        # Investment Account Total
        investment_total = sum(float(a.get('balance', 0) or 0) for a in self.investment_accounts.values())
        kpis.append(KPIMetric(
            name="Total Investment Accounts",
            category=MetricCategory.FINANCIAL,
            value=round(investment_total, 2),
            unit="currency",
            period="current"
        ).to_dict())
        
        # Outstanding Bills
        outstanding = sum(
            float(b.get('amount', 0) or 0) - float(b.get('amount_paid', 0) or 0)
            for b in self.bills.values()
            if str(b.get('status', '')).lower() in ['outstanding', 'partial', 'overdue']
        )
        kpis.append(KPIMetric(
            name="Outstanding Premiums",
            category=MetricCategory.FINANCIAL,
            value=round(outstanding, 2),
            unit="currency",
            period="current"
        ).to_dict())
        
        return kpis
    
    def _get_operational_kpis(self) -> List[Dict]:
        """Calculate operational KPIs"""
        kpis = []
        
        # Policy Processing
        total_policies = len(self.policies)
        pending_uw = sum(1 for p in self.policies.values() 
                        if 'pending' in str(p.get('status', '')).lower())
        
        kpis.append(KPIMetric(
            name="Policies Pending Underwriting",
            category=MetricCategory.OPERATIONAL,
            value=pending_uw,
            unit="count",
            period="current"
        ).to_dict())
        
        # Claims Processing
        pending_claims = sum(1 for c in self.claims.values() 
                           if str(c.get('status', '')).lower() in ['pending', 'under_review'])
        kpis.append(KPIMetric(
            name="Pending Claims",
            category=MetricCategory.OPERATIONAL,
            value=pending_claims,
            unit="count",
            period="current"
        ).to_dict())
        
        # Underwriting Queue
        pending_apps = sum(1 for a in self.underwriting_apps.values() 
                         if str(a.get('status', '')).lower() == 'pending')
        kpis.append(KPIMetric(
            name="Underwriting Queue Size",
            category=MetricCategory.OPERATIONAL,
            value=pending_apps,
            unit="count",
            period="current",
            target=10,
            target_achieved=pending_apps <= 10
        ).to_dict())
        
        # Supplier Orders
        if self.supplier_orders:
            pending_orders = sum(1 for o in self.supplier_orders.values() 
                               if str(o.get('status', '')).lower() in ['pending', 'processing'])
            kpis.append(KPIMetric(
                name="Pending Supplier Orders",
                category=MetricCategory.OPERATIONAL,
                value=pending_orders,
                unit="count",
                period="current"
            ).to_dict())
        
        # Delivery Requests
        if self.delivery_requests:
            open_deliveries = sum(1 for d in self.delivery_requests.values() 
                                 if str(d.get('status', '')).lower() in ['bidding_open', 'bid_selected', 'picked_up', 'in_transit'])
            kpis.append(KPIMetric(
                name="Active Deliveries",
                category=MetricCategory.OPERATIONAL,
                value=open_deliveries,
                unit="count",
                period="current"
            ).to_dict())
        
        return kpis
    
    def _get_customer_kpis(self) -> List[Dict]:
        """Calculate customer-related KPIs"""
        kpis = []
        
        # Total Customers
        kpis.append(KPIMetric(
            name="Total Customers",
            category=MetricCategory.CUSTOMER,
            value=len(self.customers),
            unit="count",
            period="all_time"
        ).to_dict())
        
        # Customers with Active Policies
        customers_with_policies = set(p.get('customer_id') for p in self.policies.values() 
                                      if str(p.get('status', '')).lower() == 'active')
        kpis.append(KPIMetric(
            name="Customers with Active Policies",
            category=MetricCategory.CUSTOMER,
            value=len(customers_with_policies),
            unit="count",
            period="current"
        ).to_dict())
        
        # Average Policies per Customer
        policies_per_customer = len(self.policies) / len(self.customers) if self.customers else 0
        kpis.append(KPIMetric(
            name="Avg Policies per Customer",
            category=MetricCategory.CUSTOMER,
            value=round(policies_per_customer, 2),
            unit="ratio",
            period="current"
        ).to_dict())
        
        # Customers with Health Wallet
        customers_with_wallet = len([w for w in self.health_wallets.values() 
                                    if float(w.get('balance', 0) or 0) > 0])
        kpis.append(KPIMetric(
            name="Customers with Active Wallet",
            category=MetricCategory.CUSTOMER,
            value=customers_with_wallet,
            unit="count",
            period="current"
        ).to_dict())
        
        # Average Wallet Balance
        wallet_balances = [float(w.get('balance', 0) or 0) for w in self.health_wallets.values()]
        avg_wallet = statistics.mean(wallet_balances) if wallet_balances else 0
        kpis.append(KPIMetric(
            name="Average Wallet Balance",
            category=MetricCategory.CUSTOMER,
            value=round(avg_wallet, 2),
            unit="currency",
            period="current"
        ).to_dict())
        
        return kpis
    
    def _calculate_platform_health_score(self) -> float:
        """Calculate overall platform health score (0-100)"""
        score = 100.0
        
        # Deduct for high pending claims
        pending_claims = sum(1 for c in self.claims.values() 
                           if str(c.get('status', '')).lower() in ['pending', 'under_review'])
        if pending_claims > 20:
            score -= min(20, pending_claims * 0.5)
        
        # Deduct for high underwriting queue
        pending_uw = sum(1 for a in self.underwriting_apps.values() 
                        if str(a.get('status', '')).lower() == 'pending')
        if pending_uw > 10:
            score -= min(15, pending_uw * 0.5)
        
        # Deduct for high loss ratio
        total_premium = sum(float(p.get('annual_premium', 0) or 0) for p in self.policies.values())
        total_claims = sum(float(c.get('approved_amount', 0) or 0) for c in self.claims.values() 
                          if str(c.get('status', '')).lower() in ['paid', 'approved'])
        loss_ratio = (total_claims / total_premium * 100) if total_premium > 0 else 0
        if loss_ratio > 70:
            score -= min(20, (loss_ratio - 70))
        
        # Deduct for low customer engagement
        active_wallets = sum(1 for w in self.health_wallets.values() if float(w.get('balance', 0) or 0) > 0)
        wallet_ratio = active_wallets / len(self.customers) if self.customers else 0
        if wallet_ratio < 0.5:
            score -= 10
        
        return max(0, min(100, round(score, 1)))
    
    # =========================================================================
    # INSIGHTS AND ALERTS
    # =========================================================================
    
    def _generate_insights(self) -> List[Dict]:
        """Generate AI-powered business insights"""
        insights = []
        
        # Premium Revenue Insight
        total_premium = sum(float(p.get('annual_premium', 0) or 0) for p in self.policies.values())
        avg_premium = total_premium / len(self.policies) if self.policies else 0
        insights.append(BIInsight(
            insight_id=self._generate_insight_id(),
            category='financial',
            title='Premium Book Analysis',
            description=f'Total premium book of ${total_premium:,.2f} across {len(self.policies)} policies. '
                       f'Average premium of ${avg_premium:,.2f} per policy.',
            severity=AlertSeverity.INFO,
            metric_value=total_premium
        ).to_dict())
        
        # Claims Pattern Insight
        claim_statuses = defaultdict(int)
        for c in self.claims.values():
            status = str(c.get('status', 'unknown')).lower()
            claim_statuses[status] += 1
        
        if claim_statuses:
            pending_pct = (claim_statuses.get('pending', 0) + claim_statuses.get('under_review', 0)) / len(self.claims) * 100 if self.claims else 0
            insights.append(BIInsight(
                insight_id=self._generate_insight_id(),
                category='claims',
                title='Claims Processing Status',
                description=f'{pending_pct:.1f}% of claims are pending processing. '
                           f'Distribution: {dict(claim_statuses)}',
                severity=AlertSeverity.WARNING if pending_pct > 30 else AlertSeverity.INFO,
                metric_value=pending_pct,
                recommendation='Consider adding claims adjuster resources' if pending_pct > 30 else None
            ).to_dict())
        
        # Supplier Ecosystem Insight
        if self.suppliers:
            approved = sum(1 for s in self.suppliers.values() if s.get('status') == 'approved')
            pending = sum(1 for s in self.suppliers.values() if s.get('status') == 'pending')
            by_type = defaultdict(int)
            for s in self.suppliers.values():
                by_type[s.get('supplier_type', 'other')] += 1
            
            insights.append(BIInsight(
                insight_id=self._generate_insight_id(),
                category='supplier',
                title='Supplier Ecosystem Health',
                description=f'{approved} active suppliers, {pending} pending approval. '
                           f'Categories: {dict(by_type)}',
                severity=AlertSeverity.INFO,
                recommendation='Recruit more delivery suppliers' if by_type.get('delivery', 0) < 3 else None
            ).to_dict())
        
        # Wallet Usage Insight
        total_wallet = sum(float(w.get('balance', 0) or 0) for w in self.health_wallets.values())
        active_wallets = sum(1 for w in self.health_wallets.values() if float(w.get('balance', 0) or 0) > 0)
        insights.append(BIInsight(
            insight_id=self._generate_insight_id(),
            category='customer',
            title='Health Wallet Adoption',
            description=f'{active_wallets} customers with active wallets holding ${total_wallet:,.2f} total. '
                       f'Adoption rate: {active_wallets/len(self.customers)*100:.1f}%' if self.customers else 'No customers yet.',
            severity=AlertSeverity.INFO if active_wallets > len(self.customers) * 0.5 else AlertSeverity.WARNING,
            metric_value=total_wallet
        ).to_dict())
        
        return insights
    
    def _generate_alerts(self) -> List[Dict]:
        """Generate system alerts"""
        alerts = []
        
        # High pending claims alert
        pending_claims = sum(1 for c in self.claims.values() 
                           if str(c.get('status', '')).lower() in ['pending', 'under_review'])
        if pending_claims > 10:
            alerts.append(BIInsight(
                insight_id=self._generate_insight_id(),
                category='operations',
                title='High Pending Claims Queue',
                description=f'{pending_claims} claims awaiting processing',
                severity=AlertSeverity.WARNING if pending_claims < 20 else AlertSeverity.CRITICAL,
                recommendation='Prioritize claims processing to maintain SLA'
            ).to_dict())
        
        # High loss ratio alert
        total_premium = sum(float(p.get('annual_premium', 0) or 0) for p in self.policies.values())
        total_claims = sum(float(c.get('approved_amount', 0) or 0) for c in self.claims.values() 
                          if str(c.get('status', '')).lower() in ['paid', 'approved'])
        loss_ratio = (total_claims / total_premium * 100) if total_premium > 0 else 0
        
        if loss_ratio > 75:
            alerts.append(BIInsight(
                insight_id=self._generate_insight_id(),
                category='financial',
                title='Elevated Loss Ratio',
                description=f'Loss ratio at {loss_ratio:.1f}% exceeds target of 65%',
                severity=AlertSeverity.CRITICAL if loss_ratio > 85 else AlertSeverity.WARNING,
                metric_value=loss_ratio,
                recommendation='Review underwriting criteria and claims patterns'
            ).to_dict())
        
        # Supplier with pending applications
        pending_suppliers = sum(1 for s in self.suppliers.values() if s.get('status') == 'pending')
        if pending_suppliers > 5:
            alerts.append(BIInsight(
                insight_id=self._generate_insight_id(),
                category='supplier',
                title='Pending Supplier Applications',
                description=f'{pending_suppliers} supplier applications awaiting review',
                severity=AlertSeverity.INFO,
                recommendation='Process supplier applications to expand network'
            ).to_dict())
        
        return alerts
    
    # =========================================================================
    # STATISTICAL ANALYSIS
    # =========================================================================
    
    def get_premium_statistics(self) -> Dict[str, Any]:
        """Get statistical analysis of premium data"""
        annual_premiums = [float(p.get('annual_premium', 0) or 0) for p in self.policies.values() if p.get('annual_premium')]
        monthly_premiums = [float(p.get('monthly_premium', 0) or 0) for p in self.policies.values() if p.get('monthly_premium')]
        coverage_amounts = [float(p.get('coverage_amount', 0) or 0) for p in self.policies.values() if p.get('coverage_amount')]
        
        return {
            'annual_premium': self._calculate_statistics(annual_premiums).to_dict() if annual_premiums else None,
            'monthly_premium': self._calculate_statistics(monthly_premiums).to_dict() if monthly_premiums else None,
            'coverage_amount': self._calculate_statistics(coverage_amounts).to_dict() if coverage_amounts else None,
            'premium_to_coverage_ratio': {
                'mean': round(statistics.mean([a/c for a, c in zip(annual_premiums, coverage_amounts) if c > 0]) * 100, 2) if annual_premiums and coverage_amounts else 0,
                'description': 'Average premium as percentage of coverage'
            }
        }
    
    def get_claims_statistics(self) -> Dict[str, Any]:
        """Get statistical analysis of claims data"""
        claim_amounts = [float(c.get('claimed_amount', 0) or 0) for c in self.claims.values() if c.get('claimed_amount')]
        approved_amounts = [float(c.get('approved_amount', 0) or 0) for c in self.claims.values() if c.get('approved_amount')]
        
        # Claims by status
        status_counts = defaultdict(int)
        for c in self.claims.values():
            status_counts[str(c.get('status', 'unknown')).lower()] += 1
        
        # Claims by type
        type_counts = defaultdict(int)
        for c in self.claims.values():
            type_counts[str(c.get('type', 'unknown'))] += 1
        
        # Approval rate
        total_decided = sum(1 for c in self.claims.values() 
                          if str(c.get('status', '')).lower() in ['approved', 'rejected', 'paid'])
        approved = sum(1 for c in self.claims.values() 
                      if str(c.get('status', '')).lower() in ['approved', 'paid'])
        approval_rate = (approved / total_decided * 100) if total_decided > 0 else 0
        
        return {
            'claimed_amounts': self._calculate_statistics(claim_amounts).to_dict() if claim_amounts else None,
            'approved_amounts': self._calculate_statistics(approved_amounts).to_dict() if approved_amounts else None,
            'by_status': dict(status_counts),
            'by_type': dict(type_counts),
            'approval_rate': round(approval_rate, 2),
            'total_claims': len(self.claims),
            'average_approval_ratio': round(statistics.mean([a/c for a, c in zip(approved_amounts, claim_amounts) if c > 0]) * 100, 2) if approved_amounts and claim_amounts else 0
        }
    
    def get_supplier_analytics(self) -> Dict[str, Any]:
        """Get supplier ecosystem analytics"""
        suppliers_list = list(self.suppliers.values())
        
        # By status
        by_status = defaultdict(int)
        for s in suppliers_list:
            by_status[s.get('status', 'unknown')] += 1
        
        # By type
        by_type = defaultdict(int)
        for s in suppliers_list:
            by_type[s.get('supplier_type', 'other')] += 1
        
        # Performance metrics
        ratings = [float(s.get('average_rating', 0) or 0) for s in suppliers_list if s.get('average_rating')]
        revenues = [float(s.get('total_revenue', 0) or 0) for s in suppliers_list]
        orders = [int(s.get('total_orders', 0) or 0) for s in suppliers_list]
        
        # Top suppliers by revenue
        top_by_revenue = sorted(
            [(s.get('id', s.get('supplier_id')), s.get('company_name'), float(s.get('total_revenue', 0) or 0)) 
             for s in suppliers_list],
            key=lambda x: x[2],
            reverse=True
        )[:5]
        
        return {
            'total_suppliers': len(suppliers_list),
            'by_status': dict(by_status),
            'by_type': dict(by_type),
            'rating_statistics': self._calculate_statistics(ratings).to_dict() if ratings else None,
            'revenue_statistics': self._calculate_statistics(revenues).to_dict() if revenues else None,
            'orders_statistics': self._calculate_statistics([float(o) for o in orders]).to_dict() if orders else None,
            'top_suppliers_by_revenue': [
                {'id': t[0], 'name': t[1], 'revenue': t[2]} for t in top_by_revenue
            ]
        }
    
    # =========================================================================
    # FOUNDATION/COMMUNITY ANALYTICS
    # =========================================================================
    
    def get_foundation_analytics(self) -> Dict[str, Any]:
        """Get community foundation analytics for dashboard"""
        foundations_list = list(self.foundations.values())
        
        if not foundations_list:
            return {
                'total_foundations': 0,
                'message': 'No foundations created yet'
            }
        
        # By type
        by_type = defaultdict(int)
        for f in foundations_list:
            by_type[f.get('foundation_type', 'custom')] += 1
        
        # By status
        by_status = defaultdict(int)
        for f in foundations_list:
            by_status[f.get('status', 'draft')] += 1
        
        # Fund totals
        total_fund_balance = sum(float(f.get('total_fund_balance', 0) or 0) for f in foundations_list)
        
        # Member counts
        total_members = sum(int(f.get('current_members', 0) or 0) for f in foundations_list)
        avg_members = total_members / len(foundations_list) if foundations_list else 0
        
        # Detailed fund analytics if available
        fund_analytics = {}
        if self.foundation_funds:
            funds_list = list(self.foundation_funds.values())
            fund_balances = [float(f.get('balance', 0) or 0) for f in funds_list]
            fund_analytics = {
                'total_funds': len(funds_list),
                'total_balance': round(sum(fund_balances), 2),
                'fund_statistics': self._calculate_statistics(fund_balances).to_dict() if fund_balances else None,
                'by_type': dict(defaultdict(int, [(f.get('fund_type', 'custom'), 1) for f in funds_list]))
            }
        
        return {
            'total_foundations': len(foundations_list),
            'by_type': dict(by_type),
            'by_status': dict(by_status),
            'total_fund_balance': round(total_fund_balance, 2),
            'total_members': total_members,
            'average_members': round(avg_members, 1),
            'fund_analytics': fund_analytics,
            'active_foundations': sum(1 for f in foundations_list if f.get('status') == 'active'),
            'insights': [
                {
                    'title': 'Foundation Growth Opportunity',
                    'description': f'{len(foundations_list)} foundations managing ${total_fund_balance:,.2f}. '
                                  f'Average {avg_members:.1f} members per foundation.',
                    'recommendation': 'Consider marketing to increase foundation membership'
                }
            ]
        }
    
    # =========================================================================
    # DELIVERY ANALYTICS
    # =========================================================================
    
    def get_delivery_analytics(self) -> Dict[str, Any]:
        """Get delivery service analytics"""
        if not self.delivery_requests:
            return {
                'total_deliveries': 0,
                'message': 'No delivery data available'
            }
        
        deliveries = list(self.delivery_requests.values())
        
        # By status
        by_status = defaultdict(int)
        for d in deliveries:
            status = d.get('status')
            if hasattr(status, 'value'):
                status = status.value
            by_status[str(status)] += 1
        
        # By priority
        by_priority = defaultdict(int)
        for d in deliveries:
            priority = d.get('priority')
            if hasattr(priority, 'value'):
                priority = priority.value
            by_priority[str(priority)] += 1
        
        # Bidding analytics
        if self.delivery_bids:
            bids = list(self.delivery_bids.values())
            bid_prices = [float(b.get('bid_price', 0) or 0) for b in bids]
            
            return {
                'total_deliveries': len(deliveries),
                'by_status': dict(by_status),
                'by_priority': dict(by_priority),
                'total_bids': len(bids),
                'avg_bids_per_delivery': round(len(bids) / len(deliveries), 2) if deliveries else 0,
                'bid_price_statistics': self._calculate_statistics(bid_prices).to_dict() if bid_prices else None,
                'completed_deliveries': by_status.get('delivered', 0) + by_status.get('confirmed', 0),
                'success_rate': round(
                    (by_status.get('delivered', 0) + by_status.get('confirmed', 0)) / len(deliveries) * 100
                    if deliveries else 0, 2
                )
            }
        
        return {
            'total_deliveries': len(deliveries),
            'by_status': dict(by_status),
            'by_priority': dict(by_priority)
        }
    
    # =========================================================================
    # OPTIMIZATION RECOMMENDATIONS
    # =========================================================================
    
    def get_optimization_recommendations(self) -> List[Dict]:
        """Get AI-powered system optimization recommendations"""
        recommendations = []
        
        # Underwriting optimization
        pending_uw = sum(1 for a in self.underwriting_apps.values() 
                        if str(a.get('status', '')).lower() == 'pending')
        if pending_uw > 5:
            recommendations.append({
                'area': 'Underwriting',
                'priority': 'high' if pending_uw > 10 else 'medium',
                'issue': f'{pending_uw} applications pending',
                'recommendation': 'Enable AI auto-underwriting for low-risk applications',
                'expected_impact': 'Reduce processing time by 60%'
            })
        
        # Claims optimization
        pending_claims = sum(1 for c in self.claims.values() 
                           if str(c.get('status', '')).lower() in ['pending', 'under_review'])
        if pending_claims > 5:
            recommendations.append({
                'area': 'Claims',
                'priority': 'high' if pending_claims > 10 else 'medium',
                'issue': f'{pending_claims} claims awaiting processing',
                'recommendation': 'Implement AI-assisted claims triage for faster routing',
                'expected_impact': 'Reduce average processing time by 40%'
            })
        
        # Wallet adoption
        active_wallets = sum(1 for w in self.health_wallets.values() if float(w.get('balance', 0) or 0) > 0)
        wallet_adoption = active_wallets / len(self.customers) if self.customers else 0
        if wallet_adoption < 0.6:
            recommendations.append({
                'area': 'Customer Engagement',
                'priority': 'medium',
                'issue': f'Only {wallet_adoption*100:.1f}% wallet adoption',
                'recommendation': 'Launch health wallet incentive program',
                'expected_impact': 'Increase wallet adoption to 80%'
            })
        
        # Supplier diversity
        if self.suppliers:
            by_type = defaultdict(int)
            for s in self.suppliers.values():
                if s.get('status') == 'approved':
                    by_type[s.get('supplier_type', 'other')] += 1
            
            under_served = [t for t, c in by_type.items() if c < 3]
            if under_served:
                recommendations.append({
                    'area': 'Supplier Network',
                    'priority': 'medium',
                    'issue': f'Limited suppliers in: {", ".join(under_served)}',
                    'recommendation': 'Target recruitment in under-served categories',
                    'expected_impact': 'Improve service coverage and competitive pricing'
                })
        
        # Delivery optimization
        if self.delivery_requests:
            open_deliveries = sum(1 for d in self.delivery_requests.values() 
                                 if str(d.get('status', '')).lower() == 'bidding_open')
            no_bids = sum(1 for d in self.delivery_requests.values() 
                        if str(d.get('status', '')).lower() == 'bidding_open' and
                        not any(b.get('request_id') == d.get('request_id') for b in self.delivery_bids.values()))
            
            if no_bids > 0:
                recommendations.append({
                    'area': 'Delivery',
                    'priority': 'high',
                    'issue': f'{no_bids} delivery requests with no bids',
                    'recommendation': 'Expand delivery supplier network or adjust pricing',
                    'expected_impact': 'Ensure 100% delivery coverage'
                })
        
        return recommendations


# Singleton instance
_bi_service: Optional[BIAnalyticsService] = None


def get_bi_analytics_service(**kwargs) -> BIAnalyticsService:
    """Get or create BI analytics service singleton"""
    global _bi_service
    if _bi_service is None:
        _bi_service = BIAnalyticsService(**kwargs)
    return _bi_service


def init_bi_analytics_service(**kwargs) -> BIAnalyticsService:
    """Initialize BI analytics service with data stores"""
    global _bi_service
    _bi_service = BIAnalyticsService(**kwargs)
    return _bi_service
