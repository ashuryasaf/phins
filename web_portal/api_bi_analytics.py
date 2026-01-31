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
