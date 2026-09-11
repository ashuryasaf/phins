"""
API Extensions for BI and Analytics
====================================
API endpoints for business intelligence, analytics, and system optimization.

Endpoints:
- GET /api/bi/executive-dashboard - Executive KPIs
- GET /api/bi/delivery-analytics - Delivery system analytics
- GET /api/bi/customer-analytics - Customer behavior analytics
- GET /api/bi/supplier-analytics - Supplier ecosystem analytics
- GET /api/bi/insights - AI-powered insights and recommendations
- GET /api/bi/revenue-forecast - Revenue forecasting
- GET /api/bi/monte-carlo-evaluation - Monte Carlo evaluation of rules/assumptions
- GET /api/integrity/validate - Platform integrity check
"""

import json
from services.bi_analytics_service import get_bi_analytics_service
from services.platform_integrity_service import get_platform_integrity_service
from services.delivery_bidding_service import get_delivery_bidding_service


def handle_executive_dashboard(handler, data_sources: dict) -> tuple:
    """Handle GET /api/bi/executive-dashboard"""
    try:
        bi_service = get_bi_analytics_service()
        
        dashboard = bi_service.get_executive_dashboard(
            customers=data_sources.get('customers', {}),
            policies=data_sources.get('policies', {}),
            claims=data_sources.get('claims', {}),
            billing=data_sources.get('billing', {}),
            balance_sheet=data_sources.get('balance_sheet', {}),
            suppliers=data_sources.get('suppliers', {}),
            deliveries=data_sources.get('deliveries', {})
        )
        
        return 200, dashboard
    
    except Exception as e:
        return 500, {'error': str(e)}


def handle_delivery_analytics(handler) -> tuple:
    """Handle GET /api/bi/delivery-analytics"""
    try:
        bi_service = get_bi_analytics_service()
        delivery_service = get_delivery_bidding_service()
        
        analytics = bi_service.get_delivery_analytics(
            delivery_requests=delivery_service.delivery_requests,
            delivery_bids=delivery_service.delivery_bids,
            active_deliveries=delivery_service.active_deliveries,
            delivery_history=delivery_service.delivery_history,
            supplier_metrics=delivery_service.supplier_metrics
        )
        
        return 200, analytics
    
    except Exception as e:
        return 500, {'error': str(e)}


def handle_customer_analytics(handler, data_sources: dict) -> tuple:
    """Handle GET /api/bi/customer-analytics"""
    try:
        bi_service = get_bi_analytics_service()
        
        analytics = bi_service.get_customer_analytics(
            customers=data_sources.get('customers', {}),
            health_wallets=data_sources.get('health_wallets', {}),
            investment_accounts=data_sources.get('investment_accounts', {}),
            transaction_ledger=data_sources.get('transaction_ledger', {}),
            policies=data_sources.get('policies', {})
        )
        
        return 200, analytics
    
    except Exception as e:
        return 500, {'error': str(e)}


def handle_supplier_analytics(handler, data_sources: dict) -> tuple:
    """Handle GET /api/bi/supplier-analytics"""
    try:
        bi_service = get_bi_analytics_service()
        delivery_service = get_delivery_bidding_service()
        
        analytics = bi_service.get_supplier_analytics(
            suppliers=data_sources.get('suppliers', {}),
            supplier_orders=data_sources.get('supplier_orders', {}),
            supplier_metrics=delivery_service.supplier_metrics
        )
        
        return 200, analytics
    
    except Exception as e:
        return 500, {'error': str(e)}


def handle_ai_insights(handler, data_sources: dict) -> tuple:
    """Handle GET /api/bi/insights"""
    try:
        bi_service = get_bi_analytics_service()
        
        # First get executive dashboard
        dashboard = bi_service.get_executive_dashboard(
            customers=data_sources.get('customers', {}),
            policies=data_sources.get('policies', {}),
            claims=data_sources.get('claims', {}),
            billing=data_sources.get('billing', {}),
            balance_sheet=data_sources.get('balance_sheet', {}),
            suppliers=data_sources.get('suppliers', {}),
            deliveries=data_sources.get('deliveries', {})
        )
        
        # Generate AI insights
        insights = bi_service.generate_ai_insights(dashboard)
        
        return 200, {
            'dashboard_summary': dashboard.get('summary', {}),
            'health_scores': dashboard.get('health_scores', {}),
            'insights': insights,
            'insight_count': len(insights)
        }
    
    except Exception as e:
        return 500, {'error': str(e)}


def handle_revenue_forecast(handler, policies: dict, params: dict = None) -> tuple:
    """Handle GET /api/bi/revenue-forecast"""
    try:
        bi_service = get_bi_analytics_service()
        
        # Extract query parameters
        growth_rate = float(params.get('growth_rate', 0.05)) if params else 0.05
        months_ahead = int(params.get('months_ahead', 12)) if params else 12
        
        forecast = bi_service.predict_revenue_forecast(
            policies=policies,
            historical_growth_rate=growth_rate,
            months_ahead=months_ahead
        )
        
        return 200, forecast
    
    except Exception as e:
        return 500, {'error': str(e)}


def handle_bi_snapshots(handler, params: dict = None) -> tuple:
    """Handle GET /api/bi/snapshots (BI-3).

    Lists stored KPI snapshots newest-first, or — with ``?metric=<name>`` —
    returns the chronological trend series for a single metric.
    """
    try:
        from services.bi_snapshot_service import get_bi_snapshot_service
        svc = get_bi_snapshot_service()
        params = params or {}
        try:
            limit = int(params.get('limit') or 90)
        except (TypeError, ValueError):
            limit = 90
        metric = str(params.get('metric') or '').strip()
        if metric:
            return 200, svc.trend(metric, limit=limit)
        return 200, svc.list_snapshots(limit=limit)
    except Exception as e:
        return 500, {'error': str(e)}


def handle_bi_snapshot_capture(handler, data_sources: dict) -> tuple:
    """Handle POST /api/bi/snapshots/capture (BI-3).

    Computes the executive dashboard from live stores and persists an
    immutable, checksummed KPI snapshot for trend history.
    """
    try:
        from services.bi_snapshot_service import get_bi_snapshot_service
        bi_service = get_bi_analytics_service()
        dashboard = bi_service.get_executive_dashboard(
            customers=data_sources.get('customers', {}),
            policies=data_sources.get('policies', {}),
            claims=data_sources.get('claims', {}),
            billing=data_sources.get('billing', {}),
            balance_sheet=data_sources.get('balance_sheet', {}),
            suppliers=data_sources.get('suppliers', {}),
            deliveries=data_sources.get('deliveries', {})
        )
        record = get_bi_snapshot_service().capture_snapshot(
            dashboard, source=str(data_sources.get('_snapshot_source') or 'api'),
        )
        return 201, record
    except Exception as e:
        return 500, {'error': str(e)}


def handle_monte_carlo_evaluation(handler, data_sources: dict, params: dict = None) -> tuple:
    """Handle GET /api/bi/monte-carlo-evaluation.

    Read-only Monte Carlo evaluation of PHINS's risk-scoring, underwriting,
    actuarial, claims-triage, sales-forecast and AI-threshold assumptions.
    Query parameters (all optional, all bounded by the service):
    ``seed``, ``lives``, ``trials``, ``horizon_years``, ``bootstrap``,
    ``modules`` (comma list of risk,underwriting,actuarial,claims,sales,ai)
    and ``world.<assumption>`` overrides. Live policies/claims are read only
    to seed the observed MRR; the response carries an ``integrity`` block
    proving the inputs were not modified.
    """
    try:
        from services.monte_carlo_evaluation_service import (
            get_monte_carlo_evaluation_service, params_from_query,
        )
        eval_params = params_from_query(params or {})
        observed = {
            'policies': data_sources.get('policies', {}) or {},
            'claims': data_sources.get('claims', {}) or {},
        }
        report = get_monte_carlo_evaluation_service().run(eval_params, observed=observed)
        return 200, report
    except Exception as e:
        return 500, {'error': str(e)}


def handle_integrity_validation(handler, data_sources: dict) -> tuple:
    """Handle GET /api/integrity/validate"""
    try:
        integrity_service = get_platform_integrity_service()
        delivery_service = get_delivery_bidding_service()
        
        validation_result = integrity_service.validate_all(
            users=data_sources.get('users', {}),
            customers=data_sources.get('customers', {}),
            suppliers=data_sources.get('suppliers', {}),
            policies=data_sources.get('policies', {}),
            claims=data_sources.get('claims', {}),
            billing=data_sources.get('billing', {}),
            underwriting_applications=data_sources.get('underwriting_applications', {}),
            health_wallets=data_sources.get('health_wallets', {}),
            investment_accounts=data_sources.get('investment_accounts', {}),
            transaction_ledger=data_sources.get('transaction_ledger', {}),
            balance_sheet=data_sources.get('balance_sheet', {}),
            foundations=data_sources.get('foundations'),
            foundation_members=data_sources.get('foundation_members'),
            supplier_orders=data_sources.get('supplier_orders'),
            delivery_requests=delivery_service.delivery_requests if delivery_service else None,
            active_deliveries=delivery_service.active_deliveries if delivery_service else None
        )
        
        return 200, validation_result
    
    except Exception as e:
        return 500, {'error': str(e)}
