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

Public API (consumed by `web_portal/api_bi_analytics.py`):
- BIAnalyticsService.get_executive_dashboard(customers, policies, claims, billing, balance_sheet, suppliers=None, deliveries=None)
- BIAnalyticsService.get_delivery_analytics(...)
- BIAnalyticsService.get_customer_analytics(...)
- BIAnalyticsService.get_supplier_analytics(...)
- BIAnalyticsService.generate_ai_insights(dashboard_data)
- BIAnalyticsService.predict_revenue_forecast(policies, historical_growth_rate=0.05, months_ahead=12)
- get_bi_analytics_service() — module-level singleton accessor
"""

import hashlib
import json
import statistics
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
import logging

from services import kpi_definitions as kpi

logger = logging.getLogger('phins.bi_analytics')


# ---------------------------------------------------------------------------
# Enums and dataclasses
#
# Preserved for backward compatibility — external modules and tests import
# `MetricCategory` and related symbols from this module.
# ---------------------------------------------------------------------------


class MetricCategory(Enum):
    """Categories of metrics."""
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
    """Trend direction indicators."""
    STRONG_UP = "strong_up"
    UP = "up"
    STABLE = "stable"
    DOWN = "down"
    STRONG_DOWN = "strong_down"


class AlertSeverity(Enum):
    """Alert severity levels."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class KPIMetric:
    """Key Performance Indicator metric."""
    name: str
    category: MetricCategory
    value: float
    unit: str
    period: str
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
    """Business Intelligence insight."""
    insight_id: str
    category: str
    title: str
    description: str
    severity: AlertSeverity
    metric_value: Optional[float] = None
    recommendation: Optional[str] = None
    affected_entities: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict:
        result = asdict(self)
        result['severity'] = self.severity.value
        return result


@dataclass
class StatisticalSummary:
    """Statistical summary of a data series."""
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


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------


class BIAnalyticsService:
    """
    Business Intelligence and Analytics Service for PHINS platform.

    All dashboard methods accept their data sources as keyword arguments rather
    than holding references — this keeps the singleton compatible with the
    runtime storage-swap performed by `attempt_database_recovery` in
    `web_portal/server.py`. (See `PHINS_PLATFORM_ASSESSMENT.md` §2.1.)
    """

    def __init__(self, cache_ttl_seconds: int = 300):
        # BI-2: the cache is now wired into every dashboard method. Each entry is
        # keyed by method name + a cheap content fingerprint of the inputs, so a
        # cached dashboard can never contradict a changed data store (when the
        # underlying data changes, the fingerprint changes and we recompute).
        # The cache holds READ-ONLY derived views; it is never a write source.
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache_lock = threading.Lock()
        logger.info("BI Analytics Service initialized")

    # ------------------------------------------------------------------
    # Caching primitives (BI-2)
    # ------------------------------------------------------------------

    @staticmethod
    def _fingerprint(*sources: Any) -> str:
        """Cheap, stable content fingerprint over dashboard inputs.

        Single pass over the inputs; far cheaper than the multi-aggregation
        dashboards it guards, but sensitive enough that any add/remove/amount
        change invalidates the cache. We deliberately hash a compact signature
        rather than the full payload to keep this O(n) and allocation-light.
        """
        hasher = hashlib.sha256()
        for src in sources:
            if isinstance(src, dict):
                hasher.update(str(len(src)).encode())
                # Sort keys so ordering never affects the fingerprint.
                for key in sorted(src.keys(), key=str):
                    val = src[key]
                    if isinstance(val, dict):
                        # Signature = a few mutation-sensitive fields only.
                        sig = (
                            key,
                            val.get('status'),
                            val.get('balance'),
                            val.get('amount'),
                            val.get('amount_paid'),
                            val.get('monthly_premium'),
                            val.get('annual_premium'),
                            val.get('coverage_amount'),
                            val.get('claimed_amount'),
                            val.get('approved_amount'),
                            val.get('total_amount'),
                            val.get('total_revenue'),
                            val.get('total_deliveries'),
                        )
                        hasher.update(repr(sig).encode())
                    else:
                        hasher.update(repr((key, val)).encode())
            else:
                try:
                    hasher.update(json.dumps(src, sort_keys=True, default=str).encode())
                except (TypeError, ValueError):
                    hasher.update(repr(src).encode())
        return hasher.hexdigest()

    def _cached(self, key: str, fingerprint: str, compute: Callable[[], Any]) -> Any:
        """Return a cached value if fresh and inputs unchanged, else recompute.

        On *any* doubt (TTL elapsed or fingerprint mismatch) we recompute, so the
        cache can only ever return data consistent with the current inputs.
        """
        now = time.monotonic()
        with self._cache_lock:
            entry = self.cache.get(key)
            if (
                entry is not None
                and entry.get('fingerprint') == fingerprint
                and (now - entry.get('stored_at', 0)) < self.cache_ttl_seconds
            ):
                return entry['value']
        value = compute()
        with self._cache_lock:
            self.cache[key] = {
                'fingerprint': fingerprint,
                'stored_at': now,
                'value': value,
            }
        return value

    def invalidate_cache(self) -> None:
        """Drop all cached dashboards (e.g. after a bulk data import)."""
        with self._cache_lock:
            self.cache.clear()

    # ------------------------------------------------------------------
    # Executive dashboard
    # ------------------------------------------------------------------

    def get_executive_dashboard(
        self,
        customers: Dict[str, Any],
        policies: Dict[str, Any],
        claims: Dict[str, Any],
        billing: Dict[str, Any],
        balance_sheet: Dict[str, Any],
        suppliers: Optional[Dict[str, Any]] = None,
        deliveries: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generate executive dashboard with high-level KPIs (cached, BI-2)."""
        fingerprint = self._fingerprint(
            customers, policies, claims, billing, balance_sheet, suppliers, deliveries
        )
        return self._cached(
            'executive_dashboard',
            fingerprint,
            lambda: self._compute_executive_dashboard(
                customers, policies, claims, billing, balance_sheet,
                suppliers, deliveries,
            ),
        )

    def _compute_executive_dashboard(
        self,
        customers: Dict[str, Any],
        policies: Dict[str, Any],
        claims: Dict[str, Any],
        billing: Dict[str, Any],
        balance_sheet: Dict[str, Any],
        suppliers: Optional[Dict[str, Any]] = None,
        deliveries: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)

        total_customers = len(customers)
        active_customers = sum(
            1 for c in customers.values() if c.get('status') == 'active'
        )

        total_policies = len(policies)
        active_policies = sum(
            1 for p in policies.values() if p.get('status') == 'active'
        )
        total_coverage = sum(p.get('coverage_amount', 0) for p in policies.values())

        monthly_premium_revenue = sum(
            p.get('monthly_premium', 0)
            for p in policies.values()
            if p.get('status') == 'active'
        )
        annual_premium_revenue = sum(
            p.get('annual_premium', 0)
            for p in policies.values()
            if p.get('status') == 'active'
        )

        total_claims = len(claims)
        claims_by_status: Dict[str, int] = defaultdict(int)
        total_claimed = 0.0
        total_approved = 0.0
        total_paid = 0.0
        for claim in claims.values():
            status = str(claim.get('status', '')).lower()
            claims_by_status[status] += 1
            total_claimed += claim.get('claimed_amount', 0)
            if status in ('approved', 'paid', 'closed'):
                total_approved += claim.get('approved_amount', 0)
            if status == 'paid':
                total_paid += claim.get('approved_amount', 0)

        claims_approval_rate = kpi.approval_rate_pct(total_approved, total_claimed)

        outstanding_amount = sum(
            b.get('amount', 0) - b.get('amount_paid', 0)
            for b in billing.values()
            if b.get('status') != 'paid'
        )

        total_assets = balance_sheet.get('total_assets', 0)
        claims_reserve = balance_sheet.get('claims_reserve', 0)
        total_liabilities = balance_sheet.get('total_liabilities', 0)
        net_worth = kpi.net_worth(total_assets, total_liabilities)

        supplier_metrics: Dict[str, Any] = {}
        if suppliers:
            supplier_metrics = {
                'total_suppliers': len(suppliers),
                'active_suppliers': sum(
                    1 for s in suppliers.values() if s.get('status') == 'approved'
                ),
                'pending_approval': sum(
                    1 for s in suppliers.values() if s.get('status') == 'pending'
                ),
            }

        delivery_metrics: Dict[str, Any] = {}
        if deliveries:
            delivery_metrics = {
                'active_deliveries': sum(
                    1 for d in deliveries.values()
                    if d.get('status') not in ('completed', 'cancelled')
                ),
                'completed_deliveries': sum(
                    1 for d in deliveries.values() if d.get('status') == 'completed'
                ),
                'total_deliveries': len(deliveries),
            }

        financial_health_score = self._calculate_financial_health_score(
            balance_sheet, monthly_premium_revenue, total_paid
        )
        operational_health_score = self._calculate_operational_health_score(
            claims_approval_rate, outstanding_amount, annual_premium_revenue
        )

        return {
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
                'loss_ratio': kpi.loss_ratio_pct(total_paid, annual_premium_revenue),
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
                'overall_health': round(
                    (financial_health_score + operational_health_score) / 2, 2
                ),
            },
            'supplier_metrics': supplier_metrics,
            'delivery_metrics': delivery_metrics,
        }

    # ------------------------------------------------------------------
    # Delivery / customer / supplier analytics
    # ------------------------------------------------------------------

    def get_delivery_analytics(
        self,
        delivery_requests: Dict[str, Any],
        delivery_bids: Dict[str, Any],
        active_deliveries: Dict[str, Any],
        delivery_history: Dict[str, Any],
        supplier_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Analyze delivery system performance (cached, BI-2)."""
        fingerprint = self._fingerprint(
            delivery_requests, delivery_bids, active_deliveries,
            delivery_history, supplier_metrics,
        )
        return self._cached(
            'delivery_analytics',
            fingerprint,
            lambda: self._compute_delivery_analytics(
                delivery_requests, delivery_bids, active_deliveries,
                delivery_history, supplier_metrics,
            ),
        )

    def _compute_delivery_analytics(
        self,
        delivery_requests: Dict[str, Any],
        delivery_bids: Dict[str, Any],
        active_deliveries: Dict[str, Any],
        delivery_history: Dict[str, Any],
        supplier_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        total_requests = len(delivery_requests)
        open_requests = sum(
            1 for r in delivery_requests.values()
            if r.get('status') == 'open_for_bidding'
        )
        accepted_requests = sum(
            1 for r in delivery_requests.values()
            if r.get('status') == 'bid_accepted'
        )

        total_bids = len(delivery_bids)
        avg_bids_per_request = (
            total_bids / total_requests if total_requests > 0 else 0
        )

        bid_amounts = [b.get('bid_amount', 0) for b in delivery_bids.values()]
        avg_bid_amount = statistics.mean(bid_amounts) if bid_amounts else 0
        median_bid_amount = statistics.median(bid_amounts) if bid_amounts else 0

        total_active = len(active_deliveries)
        total_completed = len(delivery_history)

        on_time_deliveries = 0
        late_deliveries = 0
        for delivery in delivery_history.values():
            estimated = delivery.get('estimated_delivery_time')
            actual = delivery.get('actual_delivery_time')
            if not estimated or not actual:
                continue
            try:
                est_dt = datetime.fromisoformat(estimated)
                act_dt = datetime.fromisoformat(actual)
                if act_dt <= est_dt:
                    on_time_deliveries += 1
                else:
                    late_deliveries += 1
            except (TypeError, ValueError):
                continue

        timed_total = on_time_deliveries + late_deliveries
        on_time_rate = (
            (on_time_deliveries / timed_total * 100) if timed_total > 0 else 0
        )

        top_suppliers = sorted(
            supplier_metrics.items(),
            key=lambda x: x[1].get('total_deliveries', 0),
            reverse=True,
        )[:5]
        top_suppliers_data = [
            {
                'supplier_id': sup_id,
                'total_deliveries': metrics.get('total_deliveries', 0),
                'total_revenue': metrics.get('total_revenue', 0),
                'rating': metrics.get('rating', 0),
                'reliability_score': metrics.get('reliability_score', 0),
            }
            for sup_id, metrics in top_suppliers
        ]

        distances = [r.get('distance_km', 0) for r in delivery_requests.values()]
        avg_distance = statistics.mean(distances) if distances else 0

        urgency_breakdown: Dict[str, int] = defaultdict(int)
        for request in delivery_requests.values():
            urgency_breakdown[request.get('urgency', 'standard')] += 1

        return {
            'requests': {
                'total': total_requests,
                'open_for_bidding': open_requests,
                'bid_accepted': accepted_requests,
                'avg_distance_km': round(avg_distance, 2),
                'urgency_breakdown': dict(urgency_breakdown),
            },
            'bids': {
                'total': total_bids,
                'avg_per_request': round(avg_bids_per_request, 2),
                'avg_amount': round(avg_bid_amount, 2),
                'median_amount': round(median_bid_amount, 2),
            },
            'deliveries': {
                'active': total_active,
                'completed': total_completed,
                'total': total_active + total_completed,
                'on_time_deliveries': on_time_deliveries,
                'late_deliveries': late_deliveries,
                'on_time_rate': round(on_time_rate, 2),
            },
            'suppliers': {
                'total_active': len(supplier_metrics),
                'top_performers': top_suppliers_data,
            },
        }

    def get_customer_analytics(
        self,
        customers: Dict[str, Any],
        health_wallets: Dict[str, Any],
        investment_accounts: Dict[str, Any],
        transaction_ledger: Dict[str, Any],
        policies: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Analyze customer behavior and engagement (cached, BI-2)."""
        fingerprint = self._fingerprint(
            customers, health_wallets, investment_accounts,
            transaction_ledger, policies,
        )
        return self._cached(
            'customer_analytics',
            fingerprint,
            lambda: self._compute_customer_analytics(
                customers, health_wallets, investment_accounts,
                transaction_ledger, policies,
            ),
        )

    def _compute_customer_analytics(
        self,
        customers: Dict[str, Any],
        health_wallets: Dict[str, Any],
        investment_accounts: Dict[str, Any],
        transaction_ledger: Dict[str, Any],
        policies: Dict[str, Any],
    ) -> Dict[str, Any]:
        total_customers = len(customers)

        wallet_balances = [w.get('balance', 0) for w in health_wallets.values()]
        total_wallet_balance = sum(wallet_balances)
        avg_wallet_balance = (
            statistics.mean(wallet_balances) if wallet_balances else 0
        )

        customers_with_wallets = len(health_wallets)
        wallet_adoption_rate = (
            (customers_with_wallets / total_customers * 100)
            if total_customers > 0 else 0
        )

        investment_balances = [
            inv.get('balance', 0) for inv in investment_accounts.values()
        ]
        total_investment_balance = sum(investment_balances)
        avg_investment_balance = (
            statistics.mean(investment_balances) if investment_balances else 0
        )

        customers_with_investments = len(investment_accounts)
        investment_adoption_rate = (
            (customers_with_investments / total_customers * 100)
            if total_customers > 0 else 0
        )

        customer_transactions: Dict[str, int] = defaultdict(int)
        customer_transaction_volume: Dict[str, float] = defaultdict(float)
        for tx in transaction_ledger.values():
            customer_id = tx.get('customer_id')
            if customer_id is None:
                continue
            customer_transactions[customer_id] += 1
            customer_transaction_volume[customer_id] += abs(tx.get('amount', 0))

        avg_transactions_per_customer = (
            sum(customer_transactions.values()) / len(customer_transactions)
        ) if customer_transactions else 0

        customers_with_policies = len(
            {p.get('customer_id') for p in policies.values() if p.get('customer_id')}
        )
        policy_adoption_rate = (
            (customers_with_policies / total_customers * 100)
            if total_customers > 0 else 0
        )

        top_customers = sorted(
            customer_transaction_volume.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:10]
        top_customers_data = [
            {
                'customer_id': cust_id,
                'transaction_volume': round(volume, 2),
                'transaction_count': customer_transactions.get(cust_id, 0),
                'wallet_balance': health_wallets.get(cust_id, {}).get('balance', 0),
                'investment_balance': investment_accounts.get(cust_id, {}).get('balance', 0),
            }
            for cust_id, volume in top_customers
        ]

        return {
            'summary': {
                'total_customers': total_customers,
                'customers_with_wallets': customers_with_wallets,
                'customers_with_investments': customers_with_investments,
                'customers_with_policies': customers_with_policies,
            },
            'wallet_analytics': {
                'total_balance': round(total_wallet_balance, 2),
                'avg_balance': round(avg_wallet_balance, 2),
                'adoption_rate': round(wallet_adoption_rate, 2),
            },
            'investment_analytics': {
                'total_balance': round(total_investment_balance, 2),
                'avg_balance': round(avg_investment_balance, 2),
                'adoption_rate': round(investment_adoption_rate, 2),
            },
            'transaction_analytics': {
                'avg_transactions_per_customer': round(
                    avg_transactions_per_customer, 2
                ),
                'total_transactions': sum(customer_transactions.values()),
            },
            'policy_adoption_rate': round(policy_adoption_rate, 2),
            'top_customers': top_customers_data,
        }

    def get_supplier_analytics(
        self,
        suppliers: Dict[str, Any],
        supplier_orders: Dict[str, Any],
        supplier_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Analyze supplier ecosystem performance (cached, BI-2)."""
        fingerprint = self._fingerprint(suppliers, supplier_orders, supplier_metrics)
        return self._cached(
            'supplier_analytics',
            fingerprint,
            lambda: self._compute_supplier_analytics(
                suppliers, supplier_orders, supplier_metrics,
            ),
        )

    def _compute_supplier_analytics(
        self,
        suppliers: Dict[str, Any],
        supplier_orders: Dict[str, Any],
        supplier_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        total_suppliers = len(suppliers)

        status_breakdown: Dict[str, int] = defaultdict(int)
        category_breakdown: Dict[str, int] = defaultdict(int)
        for supplier in suppliers.values():
            status_breakdown[supplier.get('status', 'unknown')] += 1
            category_breakdown[supplier.get('category', 'unknown')] += 1

        active_suppliers = status_breakdown.get('approved', 0)
        pending_suppliers = status_breakdown.get('pending', 0)

        total_orders = len(supplier_orders)
        orders_by_status: Dict[str, int] = defaultdict(int)
        total_order_value = 0.0
        for order in supplier_orders.values():
            orders_by_status[order.get('status', 'unknown')] += 1
            total_order_value += order.get('total_amount', 0)
        avg_order_value = total_order_value / total_orders if total_orders > 0 else 0

        supplier_ratings = [m.get('rating', 0) for m in supplier_metrics.values()]
        avg_supplier_rating = (
            statistics.mean(supplier_ratings) if supplier_ratings else 0
        )

        top_suppliers = sorted(
            supplier_metrics.items(),
            key=lambda x: x[1].get('total_revenue', 0),
            reverse=True,
        )[:10]
        top_suppliers_data = [
            {
                'supplier_id': sup_id,
                'total_revenue': metrics.get('total_revenue', 0),
                'total_orders': metrics.get('total_deliveries', 0),
                'rating': metrics.get('rating', 0),
                'reliability_score': metrics.get('reliability_score', 0),
            }
            for sup_id, metrics in top_suppliers
        ]

        return {
            'summary': {
                'total_suppliers': total_suppliers,
                'active_suppliers': active_suppliers,
                'pending_approval': pending_suppliers,
                'avg_supplier_rating': round(avg_supplier_rating, 2),
            },
            'status_breakdown': dict(status_breakdown),
            'category_breakdown': dict(category_breakdown),
            'orders': {
                'total_orders': total_orders,
                'total_order_value': round(total_order_value, 2),
                'avg_order_value': round(avg_order_value, 2),
                'orders_by_status': dict(orders_by_status),
            },
            'top_suppliers': top_suppliers_data,
        }

    # ------------------------------------------------------------------
    # AI insights and forecasting
    # ------------------------------------------------------------------

    def generate_ai_insights(
        self,
        dashboard_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Generate AI-powered insights and recommendations."""
        insights: List[Dict[str, Any]] = []
        financial = dashboard_data.get('financial', {}) or {}
        claims = dashboard_data.get('claims', {}) or {}

        loss_ratio = financial.get('loss_ratio', 0)
        if loss_ratio > 80:
            insights.append({
                'category': 'financial',
                'severity': 'high',
                'title': 'High Loss Ratio Detected',
                'description': f'Loss ratio is {loss_ratio:.1f}%, exceeding healthy threshold of 80%',
                'recommendation': (
                    'Consider: 1) Premium rate adjustments, '
                    '2) Stricter underwriting criteria, '
                    '3) Claims review process'
                ),
                'impact': 'Sustainable profitability at risk',
            })
        elif loss_ratio > 60:
            insights.append({
                'category': 'financial',
                'severity': 'medium',
                'title': 'Elevated Loss Ratio',
                'description': f'Loss ratio is {loss_ratio:.1f}%, approaching cautionary threshold',
                'recommendation': 'Monitor claims trends closely and review premium pricing',
                'impact': 'Profit margins may be compressed',
            })

        approval_rate = claims.get('approval_rate', 0)
        if approval_rate < 50:
            insights.append({
                'category': 'operations',
                'severity': 'medium',
                'title': 'Low Claims Approval Rate',
                'description': f'Only {approval_rate:.1f}% of claims are approved',
                'recommendation': (
                    'Review claims adjudication process for efficiency and customer satisfaction'
                ),
                'impact': 'Customer satisfaction and retention risk',
            })

        outstanding = financial.get('outstanding_receivables', 0)
        annual_revenue = (
            dashboard_data.get('summary', {}).get('annual_revenue_projection', 0)
        )
        if annual_revenue > 0:
            receivables_ratio = (outstanding / annual_revenue) * 100
            if receivables_ratio > 10:
                insights.append({
                    'category': 'financial',
                    'severity': 'medium',
                    'title': 'High Outstanding Receivables',
                    'description': (
                        f'Outstanding receivables are {receivables_ratio:.1f}% '
                        'of annual revenue'
                    ),
                    'recommendation': (
                        'Implement automated payment reminders and collection procedures'
                    ),
                    'impact': 'Cash flow constraints',
                })

        net_worth = financial.get('net_worth', 0)
        if net_worth < 0:
            insights.append({
                'category': 'financial',
                'severity': 'critical',
                'title': 'Negative Net Worth',
                'description': f'Net worth is negative: ${net_worth:,.2f}',
                'recommendation': (
                    'URGENT: Capital injection required, reduce liabilities, increase revenue'
                ),
                'impact': 'Company solvency at risk',
            })

        health_scores = dashboard_data.get('health_scores', {}) or {}
        overall_health = health_scores.get('overall_health', 0)
        if overall_health >= 80:
            insights.append({
                'category': 'success',
                'severity': 'positive',
                'title': 'Strong Overall Health',
                'description': f'Platform health score: {overall_health:.1f}/100',
                'recommendation': 'Maintain current strategies and consider growth initiatives',
                'impact': 'Strong foundation for expansion',
            })
        elif overall_health < 50:
            insights.append({
                'category': 'operations',
                'severity': 'high',
                'title': 'Low Platform Health Score',
                'description': f'Overall health score: {overall_health:.1f}/100',
                'recommendation': (
                    'Conduct comprehensive review of operations, financials, and customer satisfaction'
                ),
                'impact': 'Platform sustainability concerns',
            })

        return insights

    def predict_revenue_forecast(
        self,
        policies: Dict[str, Any],
        historical_growth_rate: float = 0.05,
        months_ahead: int = 12,
    ) -> Dict[str, Any]:
        """Predict revenue forecast for the next N months."""
        current_mrr = sum(
            p.get('monthly_premium', 0)
            for p in policies.values()
            if p.get('status') == 'active'
        )

        forecast = []
        for month in range(1, months_ahead + 1):
            forecasted_mrr = current_mrr * ((1 + historical_growth_rate) ** month)
            forecast.append({
                'month': month,
                'forecasted_mrr': round(forecasted_mrr, 2),
                'forecasted_arr': round(forecasted_mrr * 12, 2),
            })

        return {
            'current_mrr': round(current_mrr, 2),
            'current_arr': round(current_mrr * 12, 2),
            'growth_rate': historical_growth_rate * 100,
            'forecast_months': months_ahead,
            'forecast': forecast,
        }

    # ------------------------------------------------------------------
    # Health score helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_financial_health_score(
        balance_sheet: Dict[str, Any],
        monthly_revenue: float,
        claims_paid: float,
    ) -> float:
        score = 50.0
        net_worth = (
            balance_sheet.get('total_assets', 0)
            - balance_sheet.get('total_liabilities', 0)
        )
        if net_worth > 0:
            score += min(30.0, (net_worth / 100000) * 10)
        claims_reserve = balance_sheet.get('claims_reserve', 0)
        if monthly_revenue > 0:
            reserve_ratio = claims_reserve / (monthly_revenue * 3)
            score += min(30.0, reserve_ratio * 30)
        if monthly_revenue > 0:
            score += 20.0
        return min(100.0, max(0.0, round(score, 2)))

    @staticmethod
    def _calculate_operational_health_score(
        claims_approval_rate: float,
        outstanding_receivables: float,
        annual_revenue: float,
    ) -> float:
        score = 50.0
        if claims_approval_rate >= 70:
            score += 30.0
        elif claims_approval_rate >= 50:
            score += 20.0
        elif claims_approval_rate >= 30:
            score += 10.0
        if annual_revenue > 0:
            receivables_ratio = outstanding_receivables / annual_revenue
            if receivables_ratio < 0.05:
                score += 20.0
            elif receivables_ratio < 0.10:
                score += 15.0
            elif receivables_ratio < 0.20:
                score += 10.0
        return min(100.0, max(0.0, round(score, 2)))


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------


_bi_analytics_service: Optional[BIAnalyticsService] = None


def get_bi_analytics_service() -> BIAnalyticsService:
    """Get or create the BI analytics service singleton."""
    global _bi_analytics_service
    if _bi_analytics_service is None:
        _bi_analytics_service = BIAnalyticsService()
    return _bi_analytics_service


def init_bi_analytics_service(*_args, **_kwargs) -> BIAnalyticsService:
    """
    Backward-compatible initializer. Older call sites passed data-store
    references here; the current service reads its inputs per-call (see
    PHINS_PLATFORM_ASSESSMENT.md §2.1 on why), so the arguments are accepted
    and ignored. Returns the singleton.
    """
    global _bi_analytics_service
    _bi_analytics_service = BIAnalyticsService()
    return _bi_analytics_service


__all__ = [
    'AlertSeverity',
    'BIAnalyticsService',
    'BIInsight',
    'KPIMetric',
    'MetricCategory',
    'StatisticalSummary',
    'TrendDirection',
    'get_bi_analytics_service',
    'init_bi_analytics_service',
]
