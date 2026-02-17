"""
PHINS Platform Improvements Test Suite
======================================
Comprehensive tests for:
- Platform Data Validator
- Delivery Bidding System
- BI Analytics Service
- Community Dashboard Service

Run with: pytest tests/test_platform_improvements.py -v
"""

import pytest
import json
from datetime import datetime, timedelta, timezone
from typing import Dict

# Import the new services
from services.platform_data_validator import (
    PlatformDataValidator, 
    ValidationSeverity, 
    init_platform_validator
)
from services.delivery_bidding_service import (
    DeliveryBiddingService,
    DeliveryStatus,
    DeliveryPriority,
    BidStatus,
    init_delivery_bidding_service
)
from services.bi_analytics_service import (
    BIAnalyticsService,
    MetricCategory,
    init_bi_analytics_service
)
from services.community_dashboard_service import (
    CommunityDashboardService,
    ContractType,
    ContractStatus,
    InvestmentType,
    init_community_dashboard_service
)


# =============================================================================
# FIXTURES - Sample Data
# =============================================================================

@pytest.fixture
def sample_users():
    """Sample user data for testing"""
    return {
        'admin': {
            'username': 'admin',
            'role': 'admin',
            'email': 'admin@phins.ai',
            'password_hash': 'hash123',
            'password_salt': 'salt123',
            'active': True
        },
        'underwriter': {
            'username': 'underwriter',
            'role': 'underwriter',
            'email': 'uw@phins.ai',
            'password_hash': 'hash456',
            'password_salt': 'salt456',
            'active': True
        },
        'customer_user': {
            'username': 'customer@test.com',
            'role': 'customer',
            'email': 'customer@test.com',
            'password_hash': 'hash789',
            'password_salt': 'salt789',
            'customer_id': 'CUST-001',
            'active': True
        },
        'invalid_role': {
            'username': 'invalid_role',
            'role': 'invalid_role',
            'email': 'invalid@test.com',
            'password_hash': 'hash000',
            'password_salt': 'salt000'
        }
    }


@pytest.fixture
def sample_customers():
    """Sample customer data for testing"""
    return {
        'CUST-001': {
            'id': 'CUST-001',
            'name': 'John Doe',
            'email': 'john@test.com',
            'phone': '+1-555-1234'
        },
        'CUST-002': {
            'id': 'CUST-002',
            'name': 'Jane Smith',
            'email': 'jane@test.com',
            'phone': '+1-555-5678'
        }
    }


@pytest.fixture
def sample_policies():
    """Sample policy data for testing"""
    return {
        'POL-001': {
            'id': 'POL-001',
            'customer_id': 'CUST-001',
            'type': 'health',
            'status': 'active',
            'coverage_amount': 500000.00,
            'annual_premium': 6000.00,
            'monthly_premium': 500.00,
            'start_date': datetime.now().isoformat()
        },
        'POL-002': {
            'id': 'POL-002',
            'customer_id': 'CUST-002',
            'type': 'life',
            'status': 'pending_underwriting',
            'coverage_amount': 1000000.00,
            'annual_premium': 12000.00,
            'monthly_premium': 1000.00,
            'start_date': datetime.now().isoformat()
        }
    }


@pytest.fixture
def sample_claims():
    """Sample claims data for testing"""
    return {
        'CLM-001': {
            'id': 'CLM-001',
            'policy_id': 'POL-001',
            'customer_id': 'CUST-001',
            'type': 'medical',
            'status': 'pending',
            'claimed_amount': 5000.00,
            'filed_date': datetime.now().isoformat()
        },
        'CLM-002': {
            'id': 'CLM-002',
            'policy_id': 'POL-001',
            'customer_id': 'CUST-001',
            'type': 'medical',
            'status': 'approved',
            'claimed_amount': 2000.00,
            'approved_amount': 1800.00,
            'filed_date': datetime.now().isoformat()
        }
    }


@pytest.fixture
def sample_suppliers():
    """Sample supplier data for testing"""
    return {
        'SUP-001': {
            'id': 'SUP-001',
            'company_name': 'FastMed Delivery',
            'contact_email': 'contact@fastmed.com',
            'supplier_type': 'delivery',
            'status': 'approved',
            'portal_active': True,
            'average_rating': 4.5,
            'total_orders': 100,
            'service_areas': json.dumps(['New York', 'New Jersey'])
        },
        'SUP-002': {
            'id': 'SUP-002',
            'company_name': 'MediTransport',
            'contact_email': 'info@meditransport.com',
            'supplier_type': 'delivery',
            'status': 'approved',
            'portal_active': True,
            'average_rating': 4.8,
            'total_orders': 250,
            'service_areas': json.dumps(['nationwide'])
        },
        'SUP-003': {
            'id': 'SUP-003',
            'company_name': 'PendingPharm',
            'contact_email': 'info@pendingpharm.com',
            'supplier_type': 'pharmacy',
            'status': 'pending',
            'portal_active': False
        }
    }


@pytest.fixture
def sample_health_wallets():
    """Sample health wallet data"""
    return {
        'CUST-001': {
            'customer_id': 'CUST-001',
            'balance': 5000.00,
            'transactions': []
        },
        'CUST-002': {
            'customer_id': 'CUST-002',
            'balance': 1000.00,
            'transactions': []
        }
    }


@pytest.fixture
def sample_foundations():
    """Sample foundation data"""
    return {
        'FND-001': {
            'id': 'FND-001',
            'name': 'Community Health Fund',
            'foundation_type': 'family',
            'status': 'active',
            'total_fund_balance': 50000.00,
            'current_members': 12
        }
    }


@pytest.fixture
def sample_foundation_funds():
    """Sample foundation fund data"""
    return {
        'FUND-001': {
            'id': 'FUND-001',
            'foundation_id': 'FND-001',
            'name': 'Emergency Fund',
            'fund_type': 'emergency',
            'balance': 20000.00
        },
        'FUND-002': {
            'id': 'FUND-002',
            'foundation_id': 'FND-001',
            'name': 'Insurance Pool',
            'fund_type': 'insurance',
            'balance': 30000.00
        }
    }


@pytest.fixture
def sample_foundation_members():
    """Sample foundation member data"""
    return {
        'MEM-001': {
            'id': 'MEM-001',
            'foundation_id': 'FND-001',
            'member_id': 'CUST-001',
            'role': 'founder',
            'status': 'active',
            'total_contributed': 5000.00
        },
        'MEM-002': {
            'id': 'MEM-002',
            'foundation_id': 'FND-001',
            'member_id': 'CUST-002',
            'role': 'member',
            'status': 'active',
            'total_contributed': 2000.00
        }
    }


# =============================================================================
# PLATFORM DATA VALIDATOR TESTS
# =============================================================================

class TestPlatformDataValidator:
    """Tests for PlatformDataValidator service"""
    
    def test_validator_initialization(self, sample_users, sample_customers, sample_policies):
        """Test validator can be initialized with data stores"""
        validator = PlatformDataValidator(
            users=sample_users,
            customers=sample_customers,
            policies=sample_policies
        )
        assert validator is not None
        assert len(validator.users) == 4
        assert len(validator.customers) == 2
    
    def test_detect_invalid_role(self, sample_users, sample_customers):
        """Test detection of invalid user roles"""
        validator = PlatformDataValidator(
            users=sample_users,
            customers=sample_customers
        )
        report = validator.run_full_validation()
        
        # Should detect the invalid role
        role_issues = [i for i in report.issues 
                      if i.field == 'role' and i.entity_type == 'user']
        assert len(role_issues) >= 1
        assert any(i.entity_id == 'invalid_role' for i in role_issues)
    
    def test_detect_orphaned_customer_reference(self, sample_users):
        """Test detection of orphaned customer references"""
        # User references a customer that doesn't exist
        validator = PlatformDataValidator(
            users=sample_users,
            customers={}  # No customers
        )
        report = validator.run_full_validation()
        
        # Should detect the orphaned reference
        relationship_issues = [i for i in report.issues if i.category == 'relationship']
        assert len(relationship_issues) >= 1
    
    def test_premium_consistency_validation(self, sample_customers):
        """Test validation of premium calculations"""
        # Policy with inconsistent premiums
        bad_policy = {
            'POL-BAD': {
                'id': 'POL-BAD',
                'customer_id': 'CUST-001',
                'status': 'active',
                'annual_premium': 12000.00,
                'monthly_premium': 500.00,  # Should be 1000
            }
        }
        
        validator = PlatformDataValidator(
            customers=sample_customers,
            policies=bad_policy
        )
        report = validator.run_full_validation()
        
        # Should detect premium inconsistency
        premium_issues = [i for i in report.issues 
                        if i.field == 'monthly_premium' and i.entity_type == 'policy']
        assert len(premium_issues) >= 1
    
    def test_health_score_calculation(self, sample_users, sample_customers, sample_policies, sample_claims):
        """Test platform health score calculation"""
        validator = PlatformDataValidator(
            users=sample_users,
            customers=sample_customers,
            policies=sample_policies,
            claims=sample_claims
        )
        report = validator.run_full_validation()
        
        # Health score should be calculated
        assert 0 <= report.platform_health_score <= 100
        assert report.integrity_status in ['valid', 'warning', 'critical']
    
    def test_summary_stats(self, sample_users, sample_customers, sample_policies):
        """Test summary statistics generation"""
        validator = PlatformDataValidator(
            users=sample_users,
            customers=sample_customers,
            policies=sample_policies
        )
        stats = validator.get_summary_stats()
        
        assert 'users' in stats
        assert 'customers' in stats
        assert 'policies' in stats
        assert stats['users']['total'] == 4
        assert stats['customers']['total'] == 2
        assert stats['policies']['total'] == 2


# =============================================================================
# DELIVERY BIDDING SERVICE TESTS
# =============================================================================

class TestDeliveryBiddingService:
    """Tests for DeliveryBiddingService"""
    
    @pytest.fixture
    def delivery_service(self, sample_suppliers, sample_health_wallets):
        """Create delivery service with sample data"""
        return DeliveryBiddingService(
            suppliers=sample_suppliers,
            health_wallets=sample_health_wallets
        )
    
    def test_create_delivery_request(self, delivery_service):
        """Test creating a delivery request"""
        result = delivery_service.create_delivery_request(
            order_id='ORD-001',
            customer_id='CUST-001',
            pickup_location={
                'latitude': 40.7128,
                'longitude': -74.0060,
                'address': '123 Supplier St',
                'city': 'New York',
                'state': 'NY'
            },
            delivery_location={
                'latitude': 40.7580,
                'longitude': -73.9855,
                'address': '456 Customer Ave',
                'city': 'New York',
                'state': 'NY'
            },
            package_info={
                'description': 'Medical supplies',
                'weight_kg': 2.5
            },
            priority='standard'
        )
        
        assert result['success'] is True
        assert 'request_id' in result
        assert result['status'] == 'bidding_open'
        assert result['distance_km'] > 0
    
    def test_submit_bid(self, delivery_service):
        """Test submitting a delivery bid"""
        # First create a request with explicit max_price
        request_result = delivery_service.create_delivery_request(
            order_id='ORD-002',
            customer_id='CUST-001',
            pickup_location={'latitude': 40.7128, 'longitude': -74.0060},
            delivery_location={'latitude': 40.7580, 'longitude': -73.9855},
            package_info={'description': 'Test package'},
            priority='standard',
            max_price=50.00  # Set explicit max_price to allow our test bid
        )
        
        request_id = request_result['request_id']
        now = datetime.now(timezone.utc)
        
        # Submit a bid within max_price
        bid_result = delivery_service.submit_bid(
            request_id=request_id,
            supplier_id='SUP-001',
            bid_price=25.00,
            estimated_pickup_time=(now + timedelta(hours=2)).isoformat(),
            estimated_delivery_time=(now + timedelta(hours=4)).isoformat(),
            vehicle_type='van'
        )
        
        assert bid_result['success'] is True
        assert 'bid_id' in bid_result
        assert bid_result['ai_score'] > 0
    
    def test_ai_bid_scoring(self, delivery_service):
        """Test that AI scoring ranks bids correctly"""
        # Create request with higher max_price to allow test bids
        request_result = delivery_service.create_delivery_request(
            order_id='ORD-003',
            customer_id='CUST-001',
            pickup_location={'latitude': 40.7128, 'longitude': -74.0060},
            delivery_location={'latitude': 40.7580, 'longitude': -73.9855},
            package_info={'description': 'Test package'},
            priority='express',
            max_price=50.00  # Set explicit max_price to allow test bids
        )
        
        request_id = request_result['request_id']
        now = datetime.now(timezone.utc)
        
        # Submit multiple bids
        # Bid 1: Low price, longer time
        bid1 = delivery_service.submit_bid(
            request_id=request_id,
            supplier_id='SUP-001',
            bid_price=20.00,
            estimated_pickup_time=(now + timedelta(hours=3)).isoformat(),
            estimated_delivery_time=(now + timedelta(hours=8)).isoformat()
        )
        assert bid1['success'] is True, f"Bid 1 failed: {bid1.get('error')}"
        
        # Bid 2: Higher price, faster delivery
        bid2 = delivery_service.submit_bid(
            request_id=request_id,
            supplier_id='SUP-002',
            bid_price=35.00,
            estimated_pickup_time=(now + timedelta(hours=1)).isoformat(),
            estimated_delivery_time=(now + timedelta(hours=3)).isoformat()
        )
        assert bid2['success'] is True, f"Bid 2 failed: {bid2.get('error')}"
        
        bids_result = delivery_service.get_bids_for_request(request_id)
        
        assert bids_result['success'] is True
        assert bids_result['total_bids'] == 2
        assert bids_result['ai_recommended'] is not None
    
    def test_select_bid_with_wallet_payment(self, delivery_service):
        """Test selecting a bid and processing wallet payment"""
        # Create request with explicit max_price
        request_result = delivery_service.create_delivery_request(
            order_id='ORD-004',
            customer_id='CUST-001',  # Has $5000 wallet balance
            pickup_location={'latitude': 40.7128, 'longitude': -74.0060},
            delivery_location={'latitude': 40.7580, 'longitude': -73.9855},
            package_info={'description': 'Test package'},
            priority='standard',
            max_price=50.00  # Set explicit max_price
        )
        
        request_id = request_result['request_id']
        now = datetime.now(timezone.utc)
        
        # Submit bid within max_price
        bid_result = delivery_service.submit_bid(
            request_id=request_id,
            supplier_id='SUP-001',
            bid_price=30.00,
            estimated_pickup_time=(now + timedelta(hours=2)).isoformat(),
            estimated_delivery_time=(now + timedelta(hours=4)).isoformat()
        )
        
        assert bid_result['success'] is True, f"Bid submission failed: {bid_result.get('error')}"
        bid_id = bid_result['bid_id']
        
        # Select bid
        select_result = delivery_service.select_bid(request_id, bid_id)
        
        assert select_result['success'] is True, f"Bid selection failed: {select_result.get('error')}"
        assert select_result['price_paid'] == 30.00
        assert select_result['new_wallet_balance'] == 4970.00  # 5000 - 30
    
    def test_delivery_tracking(self, delivery_service):
        """Test delivery tracking events"""
        # Create and complete a delivery
        request_result = delivery_service.create_delivery_request(
            order_id='ORD-005',
            customer_id='CUST-001',
            pickup_location={'latitude': 40.7128, 'longitude': -74.0060},
            delivery_location={'latitude': 40.7580, 'longitude': -73.9855},
            package_info={'description': 'Test package'},
            priority='standard'
        )
        
        request_id = request_result['request_id']
        tracking = delivery_service.get_delivery_tracking(request_id)
        
        assert tracking['success'] is True
        assert tracking['current_status'] == 'bidding_open'
        assert len(tracking['tracking_events']) >= 1
    
    def test_delivery_analytics(self, delivery_service):
        """Test delivery analytics generation"""
        analytics = delivery_service.get_delivery_analytics()
        
        assert 'total_delivery_requests' in analytics
        assert 'by_status' in analytics
        assert 'by_priority' in analytics


# =============================================================================
# BI ANALYTICS SERVICE TESTS
# =============================================================================

class TestBIAnalyticsService:
    """Tests for BIAnalyticsService"""
    
    @pytest.fixture
    def bi_service(self, sample_customers, sample_suppliers, sample_policies, 
                   sample_claims, sample_health_wallets, sample_foundations):
        """Create BI service with sample data"""
        return BIAnalyticsService(
            customers=sample_customers,
            suppliers=sample_suppliers,
            policies=sample_policies,
            claims=sample_claims,
            health_wallets=sample_health_wallets,
            foundations=sample_foundations
        )
    
    def test_executive_dashboard(self, bi_service):
        """Test executive dashboard generation"""
        dashboard = bi_service.get_executive_dashboard()
        
        assert 'generated_at' in dashboard
        assert 'summary' in dashboard
        assert 'financial_kpis' in dashboard
        assert 'operational_kpis' in dashboard
        assert 'customer_kpis' in dashboard
        assert 'insights' in dashboard
        
        # Check summary
        assert dashboard['summary']['total_customers'] == 2
        assert dashboard['summary']['total_policies'] == 2
    
    def test_financial_kpis(self, bi_service):
        """Test financial KPI calculations"""
        dashboard = bi_service.get_executive_dashboard()
        
        financial_kpis = dashboard['financial_kpis']
        assert len(financial_kpis) > 0
        
        # Find total premium KPI
        premium_kpi = next((k for k in financial_kpis if k['name'] == 'Total Premium Revenue'), None)
        assert premium_kpi is not None
        assert premium_kpi['value'] == 18000.00  # 6000 + 12000
    
    def test_premium_statistics(self, bi_service):
        """Test premium statistical analysis"""
        stats = bi_service.get_premium_statistics()
        
        assert 'annual_premium' in stats
        assert 'monthly_premium' in stats
        assert stats['annual_premium']['count'] == 2
        assert stats['annual_premium']['mean'] == 9000.00  # (6000 + 12000) / 2
    
    def test_claims_statistics(self, bi_service):
        """Test claims statistical analysis"""
        stats = bi_service.get_claims_statistics()
        
        assert 'claimed_amounts' in stats
        assert 'by_status' in stats
        assert stats['total_claims'] == 2
        assert 'pending' in stats['by_status']
        assert 'approved' in stats['by_status']
    
    def test_supplier_analytics(self, bi_service):
        """Test supplier analytics"""
        analytics = bi_service.get_supplier_analytics()
        
        assert analytics['total_suppliers'] == 3
        assert 'by_status' in analytics
        assert 'by_type' in analytics
        assert analytics['by_status']['approved'] == 2
    
    def test_optimization_recommendations(self, bi_service):
        """Test optimization recommendations generation"""
        recommendations = bi_service.get_optimization_recommendations()
        
        assert isinstance(recommendations, list)
        for rec in recommendations:
            assert 'area' in rec
            assert 'priority' in rec
            assert 'recommendation' in rec
    
    def test_platform_health_score(self, bi_service):
        """Test platform health score calculation"""
        dashboard = bi_service.get_executive_dashboard()
        
        health_score = dashboard['summary']['platform_health_score']
        assert 0 <= health_score <= 100


# =============================================================================
# COMMUNITY DASHBOARD SERVICE TESTS
# =============================================================================

class TestCommunityDashboardService:
    """Tests for CommunityDashboardService"""
    
    @pytest.fixture
    def community_service(self, sample_foundations, sample_foundation_funds, sample_foundation_members):
        """Create community dashboard service with sample data"""
        return CommunityDashboardService(
            foundations=sample_foundations,
            foundation_funds=sample_foundation_funds,
            foundation_members=sample_foundation_members
        )
    
    def test_create_contract(self, community_service):
        """Test creating a community contract"""
        result = community_service.create_contract(
            foundation_id='FND-001',
            contract_type='insurance_pool',
            title='Collective Health Coverage',
            description='Shared health insurance pool for members',
            terms={'coverage_type': 'health', 'max_claim': 50000},
            parties=['MEM-001', 'MEM-002'],
            created_by='MEM-001',
            total_value=100000.00
        )
        
        assert result['success'] is True
        assert 'contract_id' in result
        assert result['status'] == 'draft'
    
    def test_submit_contract_for_approval(self, community_service):
        """Test submitting contract for approval"""
        # Create contract
        create_result = community_service.create_contract(
            foundation_id='FND-001',
            contract_type='savings_agreement',
            title='Monthly Savings Plan',
            description='Automatic monthly savings',
            terms={'monthly_amount': 500},
            parties=['MEM-001'],
            created_by='MEM-001'
        )
        
        contract_id = create_result['contract_id']
        
        # Submit for approval
        submit_result = community_service.submit_contract_for_approval(contract_id, 'MEM-001')
        
        assert submit_result['success'] is True
        assert submit_result['status'] == 'vote_in_progress'
        vote_id = submit_result['vote_id']
        assert vote_id in community_service.foundation_votes
        vote = community_service.foundation_votes[vote_id]
        assert vote['contract_id'] == contract_id
        assert vote['foundation_id'] == 'FND-001'
        assert vote['status'] == 'open'
    
    def test_create_investment_allocation(self, community_service):
        """Test creating an investment allocation"""
        result = community_service.create_investment_allocation(
            foundation_id='FND-001',
            fund_id='FUND-001',  # Emergency Fund with $20,000
            investment_type='index_fund',
            investment_name='S&P 500 Index Fund',
            amount=5000.00,
            risk_level='moderate'
        )
        
        assert result['success'] is True
        assert 'investment_id' in result
        assert result['allocated_amount'] == 5000.00
        assert result['fund_remaining_balance'] == 15000.00
    
    def test_update_investment_value(self, community_service):
        """Test updating investment value (mark-to-market)"""
        # Create investment
        create_result = community_service.create_investment_allocation(
            foundation_id='FND-001',
            fund_id='FUND-002',
            investment_type='bond_fund',
            investment_name='Treasury Bond Fund',
            amount=10000.00
        )
        
        investment_id = create_result['investment_id']
        
        # Update value (10% gain)
        update_result = community_service.update_investment_value(investment_id, 11000.00)
        
        assert update_result['success'] is True
        assert update_result['new_value'] == 11000.00
        assert update_result['unrealized_gain_loss'] == 1000.00
        assert update_result['return_percentage'] == 10.00
    
    def test_get_dashboard_metrics(self, community_service):
        """Test getting dashboard metrics"""
        result = community_service.get_dashboard_metrics('FND-001')
        
        assert result['success'] is True
        assert 'metrics' in result
        assert 'quick_actions' in result
        
        metrics = result['metrics']
        assert metrics['total_members'] == 2
        assert metrics['active_members'] == 2
    
    def test_get_foundation_analytics(self, community_service):
        """Test getting foundation analytics"""
        result = community_service.get_foundation_analytics('FND-001')
        
        assert result['success'] is True
        assert 'member_analytics' in result
        assert 'fund_analytics' in result
        assert 'investment_analytics' in result
        assert 'contract_analytics' in result
        assert 'insights' in result
    
    def test_get_foundation_investments(self, community_service):
        """Test getting all foundation investments"""
        # Create some investments first
        community_service.create_investment_allocation(
            foundation_id='FND-001',
            fund_id='FUND-001',
            investment_type='index_fund',
            investment_name='Tech Index',
            amount=3000.00
        )
        
        result = community_service.get_foundation_investments('FND-001')
        
        assert result['success'] is True
        assert result['total_investments'] >= 1
        assert 'by_type' in result
    
    def test_withdraw_investment(self, community_service):
        """Test withdrawing from an investment"""
        # Create investment
        create_result = community_service.create_investment_allocation(
            foundation_id='FND-001',
            fund_id='FUND-002',
            investment_type='money_market',
            investment_name='Cash Reserve',
            amount=5000.00
        )
        
        investment_id = create_result['investment_id']
        
        # Withdraw partial
        withdraw_result = community_service.withdraw_investment(investment_id, 2000.00)
        
        assert withdraw_result['success'] is True
        assert withdraw_result['withdrawn_amount'] == 2000.00
        assert withdraw_result['remaining_value'] == 3000.00


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestPlatformIntegration:
    """Integration tests for all services working together"""
    
    def test_full_delivery_flow(self, sample_suppliers, sample_health_wallets):
        """Test complete delivery flow from request to delivery"""
        service = DeliveryBiddingService(
            suppliers=sample_suppliers,
            health_wallets=sample_health_wallets
        )
        
        # 1. Create request with explicit max_price for urgent delivery
        request = service.create_delivery_request(
            order_id='INT-ORD-001',
            customer_id='CUST-001',
            pickup_location={'latitude': 40.7128, 'longitude': -74.0060, 'city': 'New York'},
            delivery_location={'latitude': 40.7580, 'longitude': -73.9855, 'city': 'New York'},
            package_info={'description': 'Urgent medication', 'medical_item': True},
            priority='urgent',
            max_price=100.00  # Set explicit max_price for urgent delivery
        )
        assert request['success'], f"Request creation failed: {request.get('error')}"
        request_id = request['request_id']
        
        # 2. Submit bids within max_price
        now = datetime.now(timezone.utc)
        bid1 = service.submit_bid(
            request_id=request_id,
            supplier_id='SUP-001',
            bid_price=45.00,
            estimated_pickup_time=(now + timedelta(hours=1)).isoformat(),
            estimated_delivery_time=(now + timedelta(hours=2)).isoformat()
        )
        assert bid1['success'], f"Bid 1 failed: {bid1.get('error')}"
        
        bid2 = service.submit_bid(
            request_id=request_id,
            supplier_id='SUP-002',
            bid_price=50.00,
            estimated_pickup_time=(now + timedelta(minutes=30)).isoformat(),
            estimated_delivery_time=(now + timedelta(hours=1)).isoformat()
        )
        assert bid2['success'], f"Bid 2 failed: {bid2.get('error')}"
        
        # 3. Get bids and check AI ranking
        bids = service.get_bids_for_request(request_id)
        assert bids['total_bids'] == 2, f"Expected 2 bids, got {bids['total_bids']}"
        assert bids['ai_recommended'] is not None, "No AI recommended bid found"
        
        # 4. Select best bid
        best_bid_id = bids['ai_recommended']['bid_id']
        selection = service.select_bid(request_id, best_bid_id)
        assert selection['success'], f"Bid selection failed: {selection.get('error')}"
        
        # 5. Update delivery status
        supplier_id = selection['supplier_id']
        
        # Picked up
        update1 = service.update_delivery_status(
            request_id, 'picked_up', supplier_id,
            location={'latitude': 40.7128, 'longitude': -74.0060}
        )
        assert update1['success']
        
        # In transit
        update2 = service.update_delivery_status(
            request_id, 'in_transit', supplier_id
        )
        assert update2['success']
        
        # Delivered
        update3 = service.update_delivery_status(
            request_id, 'delivered', supplier_id,
            location={'latitude': 40.7580, 'longitude': -73.9855}
        )
        assert update3['success']
        
        # 6. Check final tracking
        tracking = service.get_delivery_tracking(request_id)
        assert tracking['current_status'] == 'delivered'
        assert len(tracking['tracking_events']) >= 4
    
    def test_platform_validation_with_all_data(self, sample_users, sample_customers, 
                                                sample_suppliers, sample_policies,
                                                sample_claims, sample_health_wallets):
        """Test platform validation with comprehensive data"""
        validator = PlatformDataValidator(
            users=sample_users,
            customers=sample_customers,
            suppliers=sample_suppliers,
            policies=sample_policies,
            claims=sample_claims,
            health_wallets=sample_health_wallets
        )
        
        report = validator.run_full_validation()
        
        # Report should be generated
        assert report.report_id is not None
        assert report.generated_at is not None
        assert report.total_entities_checked > 0
        
        # AI recommendations should be generated
        assert len(report.ai_recommendations) > 0
        
        # Print summary for debugging
        print(f"\n=== Platform Validation Report ===")
        print(f"Health Score: {report.platform_health_score}")
        print(f"Total Issues: {report.total_issues_found}")
        print(f"Critical: {report.critical_issues}, High: {report.high_issues}")
        print(f"Auto-fixable: {report.auto_fixes_available}")


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
