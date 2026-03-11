"""
Tests for BI Analytics Service
================================
Tests business intelligence and statistical analytics functionality.
"""

import pytest
from services.bi_analytics_service import BIAnalyticsService


@pytest.fixture
def bi_service():
    """Create BI analytics service instance"""
    return BIAnalyticsService()


@pytest.fixture
def sample_customers():
    """Sample customer data"""
    return {
        'CUST-001': {'id': 'CUST-001', 'name': 'John Doe', 'email': 'john@test.com', 'status': 'active'},
        'CUST-002': {'id': 'CUST-002', 'name': 'Jane Smith', 'email': 'jane@test.com', 'status': 'active'},
        'CUST-003': {'id': 'CUST-003', 'name': 'Bob Johnson', 'email': 'bob@test.com', 'status': 'inactive'}
    }


@pytest.fixture
def sample_policies():
    """Sample policy data"""
    return {
        'POL-001': {
            'id': 'POL-001',
            'customer_id': 'CUST-001',
            'type': 'health',
            'status': 'active',
            'coverage_amount': 500000.0,
            'annual_premium': 6000.0,
            'monthly_premium': 500.0
        },
        'POL-002': {
            'id': 'POL-002',
            'customer_id': 'CUST-002',
            'type': 'life',
            'status': 'active',
            'coverage_amount': 1000000.0,
            'annual_premium': 12000.0,
            'monthly_premium': 1000.0
        }
    }


@pytest.fixture
def sample_claims():
    """Sample claims data"""
    return {
        'CLM-001': {
            'id': 'CLM-001',
            'policy_id': 'POL-001',
            'customer_id': 'CUST-001',
            'status': 'paid',
            'claimed_amount': 5000.0,
            'approved_amount': 5000.0
        },
        'CLM-002': {
            'id': 'CLM-002',
            'policy_id': 'POL-001',
            'customer_id': 'CUST-001',
            'status': 'pending',
            'claimed_amount': 2000.0,
            'approved_amount': 0.0
        },
        'CLM-003': {
            'id': 'CLM-003',
            'policy_id': 'POL-002',
            'customer_id': 'CUST-002',
            'status': 'approved',
            'claimed_amount': 10000.0,
            'approved_amount': 8000.0
        }
    }


@pytest.fixture
def sample_billing():
    """Sample billing data"""
    return {
        'BILL-001': {
            'id': 'BILL-001',
            'policy_id': 'POL-001',
            'customer_id': 'CUST-001',
            'amount': 500.0,
            'amount_paid': 500.0,
            'status': 'paid'
        },
        'BILL-002': {
            'id': 'BILL-002',
            'policy_id': 'POL-002',
            'customer_id': 'CUST-002',
            'amount': 1000.0,
            'amount_paid': 500.0,
            'status': 'partial'
        }
    }


@pytest.fixture
def sample_balance_sheet():
    """Sample balance sheet"""
    return {
        'total_assets': 1000000.0,
        'total_liabilities': 200000.0,
        'claims_reserve': 500000.0
    }


def test_executive_dashboard(bi_service, sample_customers, sample_policies, 
                            sample_claims, sample_billing, sample_balance_sheet):
    """Test executive dashboard generation"""
    dashboard = bi_service.get_executive_dashboard_parametric(
        customers=sample_customers,
        policies=sample_policies,
        claims=sample_claims,
        billing=sample_billing,
        balance_sheet=sample_balance_sheet
    )
    
    assert 'summary' in dashboard
    assert 'financial' in dashboard
    assert 'claims' in dashboard
    assert 'health_scores' in dashboard
    
    # Check summary metrics
    summary = dashboard['summary']
    assert summary['total_customers'] == 3
    assert summary['active_customers'] == 2
    assert summary['total_policies'] == 2
    assert summary['active_policies'] == 2
    assert summary['monthly_revenue'] == 1500.0  # 500 + 1000
    
    # Check financial metrics
    financial = dashboard['financial']
    assert financial['total_assets'] == 1000000.0
    assert financial['total_liabilities'] == 200000.0
    assert financial['net_worth'] == 800000.0
    assert financial['claims_reserve'] == 500000.0
    
    # Check claims metrics
    claims_data = dashboard['claims']
    assert claims_data['total'] == 3
    assert claims_data['total_claimed'] == 17000.0  # 5000 + 2000 + 10000
    assert claims_data['total_approved'] == 13000.0  # 5000 + 8000
    assert claims_data['total_paid'] == 5000.0


def test_customer_analytics(bi_service):
    """Test customer analytics"""
    customers = {
        'CUST-001': {'id': 'CUST-001', 'name': 'Customer 1'},
        'CUST-002': {'id': 'CUST-002', 'name': 'Customer 2'}
    }
    
    health_wallets = {
        'CUST-001': {'customer_id': 'CUST-001', 'balance': 5000.0, 'transactions': []},
        'CUST-002': {'customer_id': 'CUST-002', 'balance': 3000.0, 'transactions': []}
    }
    
    investment_accounts = {
        'CUST-001': {'customer_id': 'CUST-001', 'balance': 10000.0}
    }
    
    transaction_ledger = {
        'TXN-001': {'customer_id': 'CUST-001', 'amount': 500.0},
        'TXN-002': {'customer_id': 'CUST-001', 'amount': 1000.0},
        'TXN-003': {'customer_id': 'CUST-002', 'amount': 750.0}
    }
    
    policies = {
        'POL-001': {'customer_id': 'CUST-001', 'status': 'active'}
    }
    
    analytics = bi_service.get_customer_analytics(
        customers=customers,
        health_wallets=health_wallets,
        investment_accounts=investment_accounts,
        transaction_ledger=transaction_ledger,
        policies=policies
    )
    
    assert analytics['summary']['total_customers'] == 2
    assert analytics['summary']['customers_with_wallets'] == 2
    assert analytics['summary']['customers_with_investments'] == 1
    assert analytics['summary']['customers_with_policies'] == 1
    
    assert analytics['wallet_analytics']['total_balance'] == 8000.0
    assert analytics['wallet_analytics']['avg_balance'] == 4000.0
    assert analytics['wallet_analytics']['adoption_rate'] == 100.0
    
    assert analytics['investment_analytics']['total_balance'] == 10000.0
    assert analytics['investment_analytics']['adoption_rate'] == 50.0


def test_ai_insights_high_loss_ratio(bi_service):
    """Test AI insights for high loss ratio"""
    dashboard_data = {
        'financial': {
            'loss_ratio': 90.0,  # High loss ratio
            'outstanding_receivables': 50000.0,
            'net_worth': 100000.0
        },
        'claims': {
            'approval_rate': 75.0
        },
        'summary': {
            'annual_revenue_projection': 500000.0
        },
        'health_scores': {
            'overall_health': 45.0  # Low health
        }
    }
    
    insights = bi_service.generate_ai_insights(dashboard_data)
    
    assert len(insights) > 0
    
    # Should have high loss ratio insight
    loss_ratio_insight = next((i for i in insights if 'Loss Ratio' in i['title']), None)
    assert loss_ratio_insight is not None
    assert loss_ratio_insight['severity'] == 'high'
    assert loss_ratio_insight['category'] == 'financial'


def test_ai_insights_low_health_score(bi_service):
    """Test AI insights for low platform health"""
    dashboard_data = {
        'financial': {
            'loss_ratio': 50.0,
            'outstanding_receivables': 10000.0,
            'net_worth': 50000.0
        },
        'claims': {
            'approval_rate': 70.0
        },
        'summary': {
            'annual_revenue_projection': 500000.0
        },
        'health_scores': {
            'overall_health': 35.0  # Very low health
        }
    }
    
    insights = bi_service.generate_ai_insights(dashboard_data)
    
    # Should have low health score insight
    health_insight = next((i for i in insights if 'Health Score' in i['title']), None)
    assert health_insight is not None
    assert health_insight['severity'] == 'high'


def test_revenue_forecast(bi_service):
    """Test revenue forecasting"""
    policies = {
        'POL-001': {'status': 'active', 'monthly_premium': 500.0},
        'POL-002': {'status': 'active', 'monthly_premium': 1000.0},
        'POL-003': {'status': 'inactive', 'monthly_premium': 300.0}  # Should not count
    }
    
    forecast = bi_service.predict_revenue_forecast(
        policies=policies,
        historical_growth_rate=0.05,  # 5% monthly growth
        months_ahead=12
    )
    
    assert forecast['current_mrr'] == 1500.0  # 500 + 1000
    assert forecast['current_arr'] == 18000.0  # 1500 * 12
    assert forecast['growth_rate'] == 5.0
    assert forecast['forecast_months'] == 12
    
    assert len(forecast['forecast']) == 12
    
    # Check month 1 forecast (5% growth)
    month_1 = forecast['forecast'][0]
    assert month_1['month'] == 1
    assert month_1['forecasted_mrr'] > 1500.0
    
    # Check month 12 forecast (compound growth)
    month_12 = forecast['forecast'][11]
    assert month_12['month'] == 12
    assert month_12['forecasted_mrr'] > month_1['forecasted_mrr']


def test_financial_health_score_calculation(bi_service):
    """Test financial health score calculation"""
    # Good financial health
    balance_sheet_good = {
        'total_assets': 1000000.0,
        'total_liabilities': 200000.0,
        'claims_reserve': 500000.0
    }
    
    score_good = bi_service._calculate_financial_health_score(
        balance_sheet=balance_sheet_good,
        monthly_revenue=50000.0,
        claims_paid=30000.0
    )
    
    assert score_good >= 70.0  # Should be healthy
    assert score_good <= 100.0
    
    # Poor financial health
    balance_sheet_poor = {
        'total_assets': 100000.0,
        'total_liabilities': 200000.0,  # Liabilities exceed assets
        'claims_reserve': 10000.0
    }
    
    score_poor = bi_service._calculate_financial_health_score(
        balance_sheet=balance_sheet_poor,
        monthly_revenue=5000.0,
        claims_paid=10000.0
    )
    
    assert score_poor < score_good  # Should be lower


def test_operational_health_score_calculation(bi_service):
    """Test operational health score calculation"""
    # Good operational health
    score_good = bi_service._calculate_operational_health_score(
        claims_approval_rate=80.0,  # High approval rate
        outstanding_receivables=10000.0,
        annual_revenue=500000.0
    )
    
    assert score_good >= 70.0
    assert score_good <= 100.0
    
    # Poor operational health
    score_poor = bi_service._calculate_operational_health_score(
        claims_approval_rate=30.0,  # Low approval rate
        outstanding_receivables=100000.0,  # High receivables
        annual_revenue=500000.0
    )
    
    assert score_poor < score_good


def test_delivery_analytics(bi_service):
    """Test delivery system analytics"""
    delivery_requests = {
        'REQ-001': {'id': 'REQ-001', 'status': 'open_for_bidding', 'distance_km': 10.5, 'urgency': 'standard'},
        'REQ-002': {'id': 'REQ-002', 'status': 'bid_accepted', 'distance_km': 25.3, 'urgency': 'express'}
    }
    
    delivery_bids = {
        'BID-001': {'id': 'BID-001', 'bid_amount': 35.0},
        'BID-002': {'id': 'BID-002', 'bid_amount': 50.0},
        'BID-003': {'id': 'BID-003', 'bid_amount': 40.0}
    }
    
    active_deliveries = {
        'DEL-001': {'id': 'DEL-001', 'status': 'in_transit'}
    }
    
    delivery_history = {
        'DEL-002': {
            'id': 'DEL-002',
            'status': 'completed',
            'estimated_delivery_time': '2024-01-01T12:00:00Z',
            'actual_delivery_time': '2024-01-01T11:30:00Z'  # On time
        },
        'DEL-003': {
            'id': 'DEL-003',
            'status': 'completed',
            'estimated_delivery_time': '2024-01-01T12:00:00Z',
            'actual_delivery_time': '2024-01-01T13:00:00Z'  # Late
        }
    }
    
    supplier_metrics = {
        'SUP-001': {'total_deliveries': 10, 'total_revenue': 500.0, 'rating': 4.5, 'reliability_score': 0.9},
        'SUP-002': {'total_deliveries': 5, 'total_revenue': 250.0, 'rating': 4.0, 'reliability_score': 0.8}
    }
    
    analytics = bi_service.get_delivery_analytics(
        delivery_requests=delivery_requests,
        delivery_bids=delivery_bids,
        active_deliveries=active_deliveries,
        delivery_history=delivery_history,
        supplier_metrics=supplier_metrics
    )
    
    assert analytics['requests']['total'] == 2
    assert analytics['requests']['open_for_bidding'] == 1
    assert analytics['requests']['bid_accepted'] == 1
    
    assert analytics['bids']['total'] == 3
    assert analytics['bids']['avg_per_request'] > 0
    
    assert analytics['deliveries']['active'] == 1
    assert analytics['deliveries']['completed'] == 2
    assert analytics['deliveries']['on_time_deliveries'] == 1
    assert analytics['deliveries']['late_deliveries'] == 1
    assert analytics['deliveries']['on_time_rate'] == 50.0
    
    assert analytics['suppliers']['total_active'] == 2
    assert len(analytics['suppliers']['top_performers']) == 2


def test_supplier_analytics(bi_service):
    """Test supplier ecosystem analytics"""
    suppliers = {
        'SUP-001': {'id': 'SUP-001', 'status': 'approved', 'category': 'delivery'},
        'SUP-002': {'id': 'SUP-002', 'status': 'approved', 'category': 'healthcare'},
        'SUP-003': {'id': 'SUP-003', 'status': 'pending', 'category': 'delivery'}
    }
    
    supplier_orders = {
        'ORD-001': {'id': 'ORD-001', 'supplier_id': 'SUP-001', 'status': 'completed', 'total_amount': 100.0},
        'ORD-002': {'id': 'ORD-002', 'supplier_id': 'SUP-001', 'status': 'pending', 'total_amount': 150.0},
        'ORD-003': {'id': 'ORD-003', 'supplier_id': 'SUP-002', 'status': 'completed', 'total_amount': 200.0}
    }
    
    supplier_metrics = {
        'SUP-001': {'total_deliveries': 10, 'total_revenue': 500.0, 'rating': 4.5, 'reliability_score': 0.9},
        'SUP-002': {'total_deliveries': 8, 'total_revenue': 800.0, 'rating': 4.8, 'reliability_score': 0.95}
    }
    
    analytics = bi_service.get_supplier_analytics(
        suppliers=suppliers,
        supplier_orders=supplier_orders,
        supplier_metrics=supplier_metrics
    )
    
    assert analytics['summary']['total_suppliers'] == 3
    assert analytics['summary']['active_suppliers'] == 2
    assert analytics['summary']['pending_approval'] == 1
    
    assert analytics['orders']['total_orders'] == 3
    assert analytics['orders']['total_order_value'] == 450.0
    assert analytics['orders']['avg_order_value'] == 150.0
    
    assert len(analytics['top_suppliers']) == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
