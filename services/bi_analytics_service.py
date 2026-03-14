"""
Comprehensive BI and statistical analytics for system optimization.

Features:
- Real-time dashboard analytics
- Predictive analytics for business forecasting
- Supplier performance analysis
- Customer behavior analytics
- Delivery optimization metrics
- Financial health indicators
- Operational efficiency tracking
- AI-powered insights and recommendations

Dashboards:
- Executive Dashboard (high-level KPIs)
- Operations Dashboard (delivery, claims, underwriting)
- Financial Dashboard (revenue, expenses, reserves)
- Supplier Dashboard (performance, ratings, revenue)
- Customer Dashboard (engagement, satisfaction, wallet usage)
"""

import json
import statistics
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict
import logging

logger = logging.getLogger('phins.bi_analytics')

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
    Business Intelligence and Analytics Service for PHINS platform.
    
    Provides:
    - Real-time metrics and KPIs
    - Trend analysis
    - Predictive forecasting
    - Performance benchmarking
    - AI-powered recommendations
    """
    
    def __init__(self):
        """Initialize BI analytics service"""
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl_seconds = 300  # 5 minutes cache
        
        logger.info("BI Analytics Service initialized")
    
    def get_executive_dashboard(
        self,
        customers: Dict[str, Any],
        policies: Dict[str, Any],
        claims: Dict[str, Any],
        billing: Dict[str, Any],
        balance_sheet: Dict[str, Any],
        suppliers: Dict[str, Any] = None,
        deliveries: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Generate executive dashboard with high-level KPIs.
        
        Returns comprehensive business health indicators.
        """
        now = datetime.now(timezone.utc)
        
        # Customer metrics
        total_customers = len(customers)
        active_customers = sum(1 for c in customers.values() 
                             if c.get('status') == 'active')
        
        # Policy metrics
        total_policies = len(policies)
        active_policies = sum(1 for p in policies.values() 
                            if p.get('status') == 'active')
        total_coverage = sum(p.get('coverage_amount', 0) for p in policies.values())
        
        # Premium metrics
        monthly_premium_revenue = sum(p.get('monthly_premium', 0) 
                                    for p in policies.values() 
                                    if p.get('status') == 'active')
        annual_premium_revenue = sum(p.get('annual_premium', 0) 
                                   for p in policies.values() 
                                   if p.get('status') == 'active')
        
        # Claims metrics
        total_claims = len(claims)
        claims_by_status = defaultdict(int)
        total_claimed = 0.0
        total_approved = 0.0
        total_paid = 0.0
        
        for claim in claims.values():
            status = claim.get('status', '').lower()
            claims_by_status[status] += 1
            total_claimed += claim.get('claimed_amount', 0)
            if status in ['approved', 'paid', 'closed']:
                total_approved += claim.get('approved_amount', 0)
            if status == 'paid':
                total_paid += claim.get('approved_amount', 0)
        
        claims_approval_rate = (total_approved / total_claimed * 100) if total_claimed > 0 else 0
        
        # Billing metrics
        total_bills = len(billing)
        outstanding_amount = sum(b.get('amount', 0) - b.get('amount_paid', 0) 
                               for b in billing.values() 
                               if b.get('status') != 'paid')
        
        # Balance sheet metrics
        total_assets = balance_sheet.get('total_assets', 0)
        claims_reserve = balance_sheet.get('claims_reserve', 0)
        total_liabilities = balance_sheet.get('total_liabilities', 0)
        net_worth = total_assets - total_liabilities
        
        # Supplier metrics (if available)
        supplier_metrics = {}
        if suppliers:
            active_suppliers = sum(1 for s in suppliers.values() 
                                 if s.get('status') == 'approved')
            supplier_metrics = {
                'total_suppliers': len(suppliers),
                'active_suppliers': active_suppliers,
                'pending_approval': sum(1 for s in suppliers.values() 
                                      if s.get('status') == 'pending'),
            }
        
        # Delivery metrics (if available)
        delivery_metrics = {}
        if deliveries:
            active_deliveries = sum(1 for d in deliveries.values() 
                                  if d.get('status') not in ['completed', 'cancelled'])
            completed_deliveries = sum(1 for d in deliveries.values() 
                                     if d.get('status') == 'completed')
            delivery_metrics = {
                'active_deliveries': active_deliveries,
                'completed_deliveries': completed_deliveries,
                'total_deliveries': len(deliveries),
            }
        
        # Calculate health scores
        financial_health_score = self._calculate_financial_health_score(
            balance_sheet, monthly_premium_revenue, total_paid
        )
        
        operational_health_score = self._calculate_operational_health_score(
            claims_approval_rate, outstanding_amount, annual_premium_revenue
        )
        
        dashboard = {
            'generated_at': now.isoformat(),
            'summary': {
                'total_customers': total_customers,
                'active_customers': active_customers,
                'total_policies': total_policies,
                'active_policies': active_policies,
                'total_claims': total_claims,
                'monthly_revenue': monthly_premium_revenue,
                'annual_revenue_projection': annual_premium_revenue,
            },
            'financial': {
                'total_assets': total_assets,
                'total_liabilities': total_liabilities,
                'net_worth': net_worth,
                'claims_reserve': claims_reserve,
                'outstanding_receivables': outstanding_amount,
                'total_coverage': total_coverage,
                'loss_ratio': (total_paid / annual_premium_revenue * 100) if annual_premium_revenue > 0 else 0,
            },
            'claims': {
                'total': total_claims,
                'by_status': dict(claims_by_status),
                'total_claimed': total_claimed,
                'total_approved': total_approved,
                'total_paid': total_paid,
                'approval_rate': round(claims_approval_rate, 2),
            },
            'health_scores': {
                'financial_health': financial_health_score,
                'operational_health': operational_health_score,
                'overall_health': round((financial_health_score + operational_health_score) / 2, 2)
            },
            'supplier_metrics': supplier_metrics,
            'delivery_metrics': delivery_metrics,
        }
        
        return dashboard
    
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
    
    def get_delivery_analytics(
        self,
        delivery_requests: Dict[str, Any],
        delivery_bids: Dict[str, Any],
        active_deliveries: Dict[str, Any],
        delivery_history: Dict[str, Any],
        supplier_metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze delivery system performance.
        
        Returns:
            Comprehensive delivery analytics
        """
        # Request analytics
        total_requests = len(delivery_requests)
        open_requests = sum(1 for r in delivery_requests.values() 
                          if r.get('status') == 'open_for_bidding')
        accepted_requests = sum(1 for r in delivery_requests.values() 
                              if r.get('status') == 'bid_accepted')
        
        # Bid analytics
        total_bids = len(delivery_bids)
        avg_bids_per_request = total_bids / total_requests if total_requests > 0 else 0
        
        bid_amounts = [b.get('bid_amount', 0) for b in delivery_bids.values()]
        avg_bid_amount = statistics.mean(bid_amounts) if bid_amounts else 0
        median_bid_amount = statistics.median(bid_amounts) if bid_amounts else 0
        
        # Delivery analytics
        total_active = len(active_deliveries)
        total_completed = len(delivery_history)
        
        # Calculate on-time delivery rate
        on_time_deliveries = 0
        late_deliveries = 0
        
        for delivery in delivery_history.values():
            estimated = delivery.get('estimated_delivery_time')
            actual = delivery.get('actual_delivery_time')
            
            if estimated and actual:
                try:
                    est_dt = datetime.fromisoformat(estimated)
                    act_dt = datetime.fromisoformat(actual)
                    if act_dt <= est_dt:
                        on_time_deliveries += 1
                    else:
                        late_deliveries += 1
                except:
                    pass
        
        on_time_rate = (on_time_deliveries / (on_time_deliveries + late_deliveries) * 100) \
                      if (on_time_deliveries + late_deliveries) > 0 else 0
        
        # Supplier performance
        top_suppliers = sorted(
            supplier_metrics.items(),
            key=lambda x: x[1].get('total_deliveries', 0),
            reverse=True
        )[:5]
        
        top_suppliers_data = [
            {
                'supplier_id': sup_id,
                'total_deliveries': metrics.get('total_deliveries', 0),
                'total_revenue': metrics.get('total_revenue', 0),
                'rating': metrics.get('rating', 0),
                'reliability_score': metrics.get('reliability_score', 0)
            }
            for sup_id, metrics in top_suppliers
        ]
        
        # Distance analytics
        distances = [r.get('distance_km', 0) for r in delivery_requests.values()]
        avg_distance = statistics.mean(distances) if distances else 0
        
        # Urgency breakdown
        urgency_breakdown = defaultdict(int)
        for request in delivery_requests.values():
            urgency = request.get('urgency', 'standard')
            urgency_breakdown[urgency] += 1
        
        return {
            'requests': {
                'total': total_requests,
                'open_for_bidding': open_requests,
                'bid_accepted': accepted_requests,
                'avg_distance_km': round(avg_distance, 2),
                'urgency_breakdown': dict(urgency_breakdown)
            },
            'bids': {
                'total': total_bids,
                'avg_per_request': round(avg_bids_per_request, 2),
                'avg_amount': round(avg_bid_amount, 2),
                'median_amount': round(median_bid_amount, 2)
            },
            'deliveries': {
                'active': total_active,
                'completed': total_completed,
                'total': total_active + total_completed,
                'on_time_deliveries': on_time_deliveries,
                'late_deliveries': late_deliveries,
                'on_time_rate': round(on_time_rate, 2)
            },
            'suppliers': {
                'total_active': len(supplier_metrics),
                'top_performers': top_suppliers_data
            }
        }
    
    def get_customer_analytics(
        self,
        customers: Dict[str, Any],
        health_wallets: Dict[str, Any],
        investment_accounts: Dict[str, Any],
        transaction_ledger: Dict[str, Any],
        policies: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze customer behavior and engagement.
        
        Returns:
            Customer analytics and insights
        """
        total_customers = len(customers)
        
        # Wallet analytics
        wallet_balances = [w.get('balance', 0) for w in health_wallets.values()]
        total_wallet_balance = sum(wallet_balances)
        avg_wallet_balance = statistics.mean(wallet_balances) if wallet_balances else 0
        
        customers_with_wallets = len(health_wallets)
        wallet_adoption_rate = (customers_with_wallets / total_customers * 100) if total_customers > 0 else 0
        
        # Investment analytics
        investment_balances = [inv.get('balance', 0) for inv in investment_accounts.values()]
        total_investment_balance = sum(investment_balances)
        avg_investment_balance = statistics.mean(investment_balances) if investment_balances else 0
        
        customers_with_investments = len(investment_accounts)
        investment_adoption_rate = (customers_with_investments / total_customers * 100) if total_customers > 0 else 0
        
        # Transaction analytics
        customer_transactions = defaultdict(int)
        customer_transaction_volume = defaultdict(float)
        
        for tx in transaction_ledger.values():
            customer_id = tx.get('customer_id')
            if customer_id:
                customer_transactions[customer_id] += 1
                customer_transaction_volume[customer_id] += abs(tx.get('amount', 0))
        
        avg_transactions_per_customer = (sum(customer_transactions.values()) / len(customer_transactions)) \
                                       if customer_transactions else 0
        
        # Policy ownership
        customers_with_policies = len(set(p.get('customer_id') for p in policies.values()))
        policy_adoption_rate = (customers_with_policies / total_customers * 100) if total_customers > 0 else 0
        
        # Top customers by transaction volume
        top_customers = sorted(
            customer_transaction_volume.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        top_customers_data = [
            {
                'customer_id': cust_id,
                'transaction_volume': round(volume, 2),
                'transaction_count': customer_transactions.get(cust_id, 0),
                'wallet_balance': health_wallets.get(cust_id, {}).get('balance', 0),
                'investment_balance': investment_accounts.get(cust_id, {}).get('balance', 0)
            }
            for cust_id, volume in top_customers
        ]
        
        return {
            'summary': {
                'total_customers': total_customers,
                'customers_with_wallets': customers_with_wallets,
                'customers_with_investments': customers_with_investments,
                'customers_with_policies': customers_with_policies
            },
            'wallet_analytics': {
                'total_balance': round(total_wallet_balance, 2),
                'avg_balance': round(avg_wallet_balance, 2),
                'adoption_rate': round(wallet_adoption_rate, 2)
            },
            'investment_analytics': {
                'total_balance': round(total_investment_balance, 2),
                'avg_balance': round(avg_investment_balance, 2),
                'adoption_rate': round(investment_adoption_rate, 2)
            },
            'transaction_analytics': {
                'avg_transactions_per_customer': round(avg_transactions_per_customer, 2),
                'total_transactions': sum(customer_transactions.values())
            },
            'policy_adoption_rate': round(policy_adoption_rate, 2),
            'top_customers': top_customers_data
        }
    
    def get_supplier_analytics(
        self,
        suppliers: Dict[str, Any],
        supplier_orders: Dict[str, Any],
        supplier_metrics: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Analyze supplier ecosystem performance.
        
        Returns:
            Supplier analytics and performance metrics
        """
        total_suppliers = len(suppliers)
        
        # Status breakdown
        status_breakdown = defaultdict(int)
        for supplier in suppliers.values():
            status = supplier.get('status', 'unknown')
            status_breakdown[status] += 1
        
        active_suppliers = status_breakdown.get('approved', 0)
        pending_suppliers = status_breakdown.get('pending', 0)
        
        # Category breakdown
        category_breakdown = defaultdict(int)
        for supplier in suppliers.values():
            category = supplier.get('category', 'unknown')
            category_breakdown[category] += 1
        
        # Order analytics
        total_orders = len(supplier_orders)
        
        orders_by_status = defaultdict(int)
        total_order_value = 0.0
        
        for order in supplier_orders.values():
            status = order.get('status', 'unknown')
            orders_by_status[status] += 1
            total_order_value += order.get('total_amount', 0)
        
        avg_order_value = total_order_value / total_orders if total_orders > 0 else 0
        
        # Performance metrics
        supplier_ratings = [m.get('rating', 0) for m in supplier_metrics.values()]
        avg_supplier_rating = statistics.mean(supplier_ratings) if supplier_ratings else 0
        
        # Top performing suppliers
        top_suppliers = sorted(
            supplier_metrics.items(),
            key=lambda x: x[1].get('total_revenue', 0),
            reverse=True
        )[:10]
        
        top_suppliers_data = [
            {
                'supplier_id': sup_id,
                'total_revenue': metrics.get('total_revenue', 0),
                'total_orders': metrics.get('total_deliveries', 0),
                'rating': metrics.get('rating', 0),
                'reliability_score': metrics.get('reliability_score', 0)
            }
            for sup_id, metrics in top_suppliers
        ]
        
        return {
            'summary': {
                'total_suppliers': total_suppliers,
                'active_suppliers': active_suppliers,
                'pending_approval': pending_suppliers,
                'avg_supplier_rating': round(avg_supplier_rating, 2)
            },
            'status_breakdown': dict(status_breakdown),
            'category_breakdown': dict(category_breakdown),
            'orders': {
                'total_orders': total_orders,
                'total_order_value': round(total_order_value, 2),
                'avg_order_value': round(avg_order_value, 2),
                'orders_by_status': dict(orders_by_status)
            },
            'top_suppliers': top_suppliers_data
        }
    
    def generate_ai_insights(
        self,
        dashboard_data: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Generate AI-powered insights and recommendations.
        
        Returns:
            List of insights with severity and actionable recommendations
        """
        insights = []
        
        # Financial health insights
        financial = dashboard_data.get('financial', {})
        claims = dashboard_data.get('claims', {})
        
        loss_ratio = financial.get('loss_ratio', 0)
        if loss_ratio > 80:
            insights.append({
                'category': 'financial',
                'severity': 'high',
                'title': 'High Loss Ratio Detected',
                'description': f'Loss ratio is {loss_ratio:.1f}%, exceeding healthy threshold of 80%',
                'recommendation': 'Consider: 1) Premium rate adjustments, 2) Stricter underwriting criteria, 3) Claims review process',
                'impact': 'Sustainable profitability at risk'
            })
        elif loss_ratio > 60:
            insights.append({
                'category': 'financial',
                'severity': 'medium',
                'title': 'Elevated Loss Ratio',
                'description': f'Loss ratio is {loss_ratio:.1f}%, approaching cautionary threshold',
                'recommendation': 'Monitor claims trends closely and review premium pricing',
                'impact': 'Profit margins may be compressed'
            })
        
        # Claims approval rate insights
        approval_rate = claims.get('approval_rate', 0)
        if approval_rate < 50:
            insights.append({
                'category': 'operations',
                'severity': 'medium',
                'title': 'Low Claims Approval Rate',
                'description': f'Only {approval_rate:.1f}% of claims are approved',
                'recommendation': 'Review claims adjudication process for efficiency and customer satisfaction',
                'impact': 'Customer satisfaction and retention risk'
            })
        
        # Outstanding receivables insight
        outstanding = financial.get('outstanding_receivables', 0)
        annual_revenue = dashboard_data.get('summary', {}).get('annual_revenue_projection', 0)
        
        if annual_revenue > 0:
            receivables_ratio = (outstanding / annual_revenue) * 100
            if receivables_ratio > 10:
                insights.append({
                    'category': 'financial',
                    'severity': 'medium',
                    'title': 'High Outstanding Receivables',
                    'description': f'Outstanding receivables are {receivables_ratio:.1f}% of annual revenue',
                    'recommendation': 'Implement automated payment reminders and collection procedures',
                    'impact': 'Cash flow constraints'
                })
        
        # Net worth insight
        net_worth = financial.get('net_worth', 0)
        if net_worth < 0:
            insights.append({
                'category': 'financial',
                'severity': 'critical',
                'title': 'Negative Net Worth',
                'description': f'Net worth is negative: ${net_worth:,.2f}',
                'recommendation': 'URGENT: Capital injection required, reduce liabilities, increase revenue',
                'impact': 'Company solvency at risk'
            })
        
        # Health scores
        health_scores = dashboard_data.get('health_scores', {})
        overall_health = health_scores.get('overall_health', 0)
        
        if overall_health >= 80:
            insights.append({
                'category': 'success',
                'severity': 'positive',
                'title': 'Strong Overall Health',
                'description': f'Platform health score: {overall_health:.1f}/100',
                'recommendation': 'Maintain current strategies and consider growth initiatives',
                'impact': 'Strong foundation for expansion'
            })
        elif overall_health < 50:
            insights.append({
                'category': 'operations',
                'severity': 'high',
                'title': 'Low Platform Health Score',
                'description': f'Overall health score: {overall_health:.1f}/100',
                'recommendation': 'Conduct comprehensive review of operations, financials, and customer satisfaction',
                'impact': 'Platform sustainability concerns'
            })
        
        return insights
    
    def predict_revenue_forecast(
        self,
        policies: Dict[str, Any],
        historical_growth_rate: float = 0.05,
        months_ahead: int = 12
    ) -> Dict[str, Any]:
        """
        Predict revenue forecast for the next N months.
        
        Args:
            policies: Current policies
            historical_growth_rate: Historical monthly growth rate (default 5%)
            months_ahead: Number of months to forecast
            
        Returns:
            Revenue forecast by month
        """
        # Calculate current monthly recurring revenue (MRR)
        current_mrr = sum(p.get('monthly_premium', 0) 
                         for p in policies.values() 
                         if p.get('status') == 'active')
        
        # Generate forecast
        forecast = []
        for month in range(1, months_ahead + 1):
            forecasted_mrr = current_mrr * ((1 + historical_growth_rate) ** month)
            forecast.append({
                'month': month,
                'forecasted_mrr': round(forecasted_mrr, 2),
                'forecasted_arr': round(forecasted_mrr * 12, 2)
            })
        
        return {
            'current_mrr': round(current_mrr, 2),
            'current_arr': round(current_mrr * 12, 2),
            'growth_rate': historical_growth_rate * 100,
            'forecast_months': months_ahead,
            'forecast': forecast
        }
    
    # ========== Private Helper Methods ==========
    
    def _calculate_financial_health_score(
        self,
        balance_sheet: Dict[str, Any],
        monthly_revenue: float,
        claims_paid: float
    ) -> float:
        """Calculate financial health score (0-100)"""
        score = 50.0  # Base score
        
        # Net worth contribution (30 points)
        net_worth = balance_sheet.get('total_assets', 0) - balance_sheet.get('total_liabilities', 0)
        if net_worth > 0:
            score += min(30.0, (net_worth / 100000) * 10)
        
        # Claims reserve adequacy (30 points)
        claims_reserve = balance_sheet.get('claims_reserve', 0)
        if monthly_revenue > 0:
            reserve_ratio = claims_reserve / (monthly_revenue * 3)  # 3 months of revenue
            score += min(30.0, reserve_ratio * 30)
        
        # Revenue positivity (20 points)
        if monthly_revenue > 0:
            score += 20.0
        
        return min(100.0, max(0.0, round(score, 2)))
    
    def _calculate_operational_health_score(
        self,
        claims_approval_rate: float,
        outstanding_receivables: float,
        annual_revenue: float
    ) -> float:
        """Calculate operational health score (0-100)"""
        score = 50.0  # Base score
        
        # Claims efficiency (30 points)
        if claims_approval_rate >= 70:
            score += 30.0
        elif claims_approval_rate >= 50:
            score += 20.0
        elif claims_approval_rate >= 30:
            score += 10.0
        
        # Receivables management (20 points)
        if annual_revenue > 0:
            receivables_ratio = outstanding_receivables / annual_revenue
            if receivables_ratio < 0.05:
                score += 20.0
            elif receivables_ratio < 0.10:
                score += 15.0
            elif receivables_ratio < 0.20:
                score += 10.0
        
        return min(100.0, max(0.0, round(score, 2)))

    def _get_financial_kpis(self) -> List[Dict]:
        """Calculate financial KPI metrics"""
        total_premium = round(sum(float(p.get('annual_premium', 0) or 0) for p in self.policies.values()), 2)
        monthly_premium = round(sum(float(p.get('monthly_premium', 0) or 0) for p in self.policies.values()), 2)
        total_claims_paid = round(sum(
            float(c.get('approved_amount', 0) or 0)
            for c in self.claims.values()
            if str(c.get('status', '')).lower() in ['paid', 'approved']
        ), 2)

        return [
            {'name': 'Total Premium Revenue', 'value': total_premium, 'unit': 'currency'},
            {'name': 'Monthly Premium Revenue', 'value': monthly_premium, 'unit': 'currency'},
            {'name': 'Total Claims Paid', 'value': total_claims_paid, 'unit': 'currency'},
            {'name': 'Loss Ratio', 'value': round((total_claims_paid / total_premium * 100) if total_premium > 0 else 0, 2), 'unit': 'percentage'},
        ]

    def _get_operational_kpis(self) -> List[Dict]:
        """Calculate operational KPI metrics"""
        total_claims = len(self.claims)
        pending_claims = sum(1 for c in self.claims.values() if str(c.get('status', '')).lower() == 'pending')
        approved_claims = sum(1 for c in self.claims.values() if str(c.get('status', '')).lower() in ['approved', 'paid'])
        approval_rate = round((approved_claims / total_claims * 100) if total_claims > 0 else 0, 2)

        return [
            {'name': 'Total Claims', 'value': total_claims, 'unit': 'count'},
            {'name': 'Pending Claims', 'value': pending_claims, 'unit': 'count'},
            {'name': 'Claims Approval Rate', 'value': approval_rate, 'unit': 'percentage'},
            {'name': 'Active Policies', 'value': sum(1 for p in self.policies.values() if str(p.get('status', '')).lower() == 'active'), 'unit': 'count'},
        ]

    def _get_customer_kpis(self) -> List[Dict]:
        """Calculate customer KPI metrics"""
        total_customers = len(self.customers)
        active_customers = sum(1 for c in self.customers.values() if str(c.get('status', '')).lower() == 'active')
        wallet_balance = round(sum(float(w.get('balance', 0) or 0) for w in self.health_wallets.values()), 2)

        return [
            {'name': 'Total Customers', 'value': total_customers, 'unit': 'count'},
            {'name': 'Active Customers', 'value': active_customers, 'unit': 'count'},
            {'name': 'Total Wallet Balance', 'value': wallet_balance, 'unit': 'currency'},
        ]

    def _generate_insights(self) -> List[Dict]:
        """Generate AI-driven business insights"""
        insights = []
        total_premium = sum(float(p.get('annual_premium', 0) or 0) for p in self.policies.values())
        if total_premium > 0:
            insights.append({
                'id': self._generate_insight_id(),
                'type': 'financial',
                'message': f'Total annual premium book stands at ${total_premium:,.2f}',
                'priority': 'info'
            })
        if self.claims:
            pending = sum(1 for c in self.claims.values() if str(c.get('status', '')).lower() == 'pending')
            if pending > 0:
                insights.append({
                    'id': self._generate_insight_id(),
                    'type': 'operational',
                    'message': f'{pending} claims are pending review',
                    'priority': 'warning' if pending > 5 else 'info'
                })
        return insights

    def _generate_alerts(self) -> List[Dict]:
        """Generate system alerts"""
        alerts = []
        overdue_claims = sum(1 for c in self.claims.values() if str(c.get('status', '')).lower() == 'pending')
        if overdue_claims > 10:
            alerts.append({
                'severity': 'critical',
                'message': f'{overdue_claims} claims pending – immediate attention required',
                'area': 'claims'
            })
        return alerts

    def _calculate_platform_health_score(self) -> float:
        """Calculate overall platform health score (0-100)"""
        score = 50.0

        # Policy book score (25 points)
        active_policies = sum(1 for p in self.policies.values() if str(p.get('status', '')).lower() == 'active')
        total_policies = len(self.policies)
        if total_policies > 0:
            score += (active_policies / total_policies) * 25

        # Claims efficiency (25 points)
        total_claims = len(self.claims)
        if total_claims > 0:
            resolved = sum(1 for c in self.claims.values() if str(c.get('status', '')).lower() in ['paid', 'approved', 'closed'])
            score += (resolved / total_claims) * 25

        return min(100.0, max(0.0, round(score, 2)))

    def get_premium_statistics(self) -> Dict[str, Any]:
        """Return statistical summary of premium amounts"""
        annual_premiums = [float(p.get('annual_premium', 0) or 0) for p in self.policies.values()]
        monthly_premiums = [float(p.get('monthly_premium', 0) or 0) for p in self.policies.values()]
        return {
            'annual_premium': self._calculate_statistics(annual_premiums).to_dict() if annual_premiums else {},
            'monthly_premium': self._calculate_statistics(monthly_premiums).to_dict() if monthly_premiums else {},
        }

    def get_claims_statistics(self) -> Dict[str, Any]:
        """Return statistical summary of claims data"""
        claimed_amounts = [float(c.get('claimed_amount', 0) or 0) for c in self.claims.values()]
        by_status: Dict[str, int] = defaultdict(int)
        for c in self.claims.values():
            by_status[str(c.get('status', 'unknown')).lower()] += 1
        return {
            'total_claims': len(self.claims),
            'claimed_amounts': self._calculate_statistics(claimed_amounts).to_dict() if claimed_amounts else {},
            'by_status': dict(by_status),
        }

    def get_supplier_analytics(
        self,
        suppliers: Dict[str, Any] = None,
        supplier_orders: Dict[str, Any] = None,
        supplier_metrics: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Analyze supplier ecosystem – uses stored data stores when no arguments are provided"""
        suppliers = suppliers if suppliers is not None else self.suppliers
        supplier_orders = supplier_orders if supplier_orders is not None else self.supplier_orders

        total_suppliers = len(suppliers)
        by_status: Dict[str, int] = defaultdict(int)
        by_type: Dict[str, int] = defaultdict(int)
        for s in suppliers.values():
            by_status[str(s.get('status', 'unknown')).lower()] += 1
            by_type[str(s.get('supplier_type', s.get('type', 'unknown'))).lower()] += 1

        total_orders = len(supplier_orders)
        total_order_value = sum(float(o.get('total_amount', 0) or 0) for o in supplier_orders.values())

        return {
            'total_suppliers': total_suppliers,
            'by_status': dict(by_status),
            'by_type': dict(by_type),
            'total_orders': total_orders,
            'total_order_value': round(total_order_value, 2),
        }

    def get_optimization_recommendations(self) -> List[Dict]:
        """Generate optimization recommendations based on current data"""
        recommendations = []

        # Claims backlog
        pending_claims = sum(1 for c in self.claims.values() if str(c.get('status', '')).lower() == 'pending')
        if pending_claims > 0:
            recommendations.append({
                'area': 'claims',
                'priority': 'high' if pending_claims > 5 else 'medium',
                'recommendation': f'Review and process {pending_claims} pending claim(s) to reduce backlog',
            })

        # Supplier onboarding
        pending_suppliers = sum(1 for s in self.suppliers.values() if str(s.get('status', '')).lower() == 'pending')
        if pending_suppliers > 0:
            recommendations.append({
                'area': 'suppliers',
                'priority': 'medium',
                'recommendation': f'Approve or reject {pending_suppliers} pending supplier application(s)',
            })

        # Policy activation
        inactive_policies = sum(1 for p in self.policies.values() if str(p.get('status', '')).lower() not in ['active', 'cancelled'])
        if inactive_policies > 0:
            recommendations.append({
                'area': 'policies',
                'priority': 'low',
                'recommendation': f'{inactive_policies} policy(ies) are not yet active – follow up with underwriting',
            })

        if not recommendations:
            recommendations.append({
                'area': 'general',
                'priority': 'low',
                'recommendation': 'Platform is operating within normal parameters',
            })

        return recommendations
_bi_analytics_service: Optional[BIAnalyticsService] = None


def get_bi_analytics_service() -> BIAnalyticsService:
    """Get or create BI analytics service singleton"""
    global _bi_analytics_service
    if _bi_analytics_service is None:
        _bi_analytics_service = BIAnalyticsService()
    return _bi_analytics_service


def init_bi_analytics_service(**kwargs) -> BIAnalyticsService:
    """Initialize BI analytics service with data stores"""
    global _bi_analytics_service
    _bi_analytics_service = BIAnalyticsService(**kwargs)
    return _bi_analytics_service
