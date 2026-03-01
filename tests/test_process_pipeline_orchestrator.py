"""
Process Pipeline Orchestrator Test Suite
=========================================
Tests for the unified pipeline orchestration across:
- Health Wallet pipeline validation
- Supply Chain pipeline validation
- Delivery Allocation pipeline validation
- Claims automation pipeline
- Billing automation pipeline
- Marketplace supply validation
- Cross-pipeline data integrity
"""

import pytest
from datetime import datetime, timedelta, timezone

from services.process_pipeline_orchestrator import (
    ProcessPipelineOrchestrator,
    PipelineValidationResult,
    MarketplaceSupplyValidation,
    CrossPipelineIntegrityReport,
    SupplyValidationStatus,
    init_process_pipeline_orchestrator,
    reset_process_pipeline_orchestrator,
)
from services.pipeline_integrity_service import (
    PipelineIntegrityService,
    PipelineIntegrityReport,
    IntegrityIssue,
)
from services.delivery_bidding_service import (
    DeliveryBiddingService,
    DeliveryRequest,
    DeliveryBid,
    DeliveryStatus,
    BidStatus,
    GeoLocation,
    DeliveryPriority,
)


# =========================================================================
# FIXTURES
# =========================================================================

@pytest.fixture
def sample_policies():
    return {
        'POL-001': {
            'id': 'POL-001',
            'customer_id': 'CUST-001',
            'status': 'active',
            'coverage_amount': 500000,
            'annual_premium': 6000,
            'monthly_premium': 500,
            'start_date': '2025-01-01T00:00:00+00:00',
            'health_wallet': {'allocation_percentage': 25}
        },
        'POL-002': {
            'id': 'POL-002',
            'customer_id': 'CUST-002',
            'status': 'active',
            'coverage_amount': 300000,
            'annual_premium': 3600,
            'monthly_premium': 300,
            'start_date': '2025-06-01T00:00:00+00:00',
            'health_wallet': {'allocation_percentage': 20}
        }
    }


@pytest.fixture
def sample_customers():
    return {
        'CUST-001': {'id': 'CUST-001', 'name': 'Alice', 'email': 'alice@test.com'},
        'CUST-002': {'id': 'CUST-002', 'name': 'Bob', 'email': 'bob@test.com'}
    }


@pytest.fixture
def sample_health_wallets():
    return {
        'CUST-001': {
            'customer_id': 'CUST-001',
            'balance': 5000.0,
            'initial_balance': 0,
            'transactions': [
                {'id': 'TX-001', 'type': 'premium_savings', 'amount': 5000.0,
                 'timestamp': datetime.now(timezone.utc).isoformat()}
            ],
            'created_at': datetime.now(timezone.utc).isoformat()
        },
        'CUST-002': {
            'customer_id': 'CUST-002',
            'balance': 2000.0,
            'initial_balance': 0,
            'transactions': [
                {'id': 'TX-002', 'type': 'premium_savings', 'amount': 2000.0,
                 'timestamp': datetime.now(timezone.utc).isoformat()}
            ],
            'created_at': datetime.now(timezone.utc).isoformat()
        }
    }


@pytest.fixture
def sample_suppliers():
    return {
        'SUP-001': {
            'id': 'SUP-001',
            'company_name': 'MedPharm Co',
            'supplier_type': 'pharmacy',
            'status': 'approved',
            'invitation_code': 'INV-001',
            'license_number': 'PH-12345',
            'average_rating': 4.5,
            'total_orders': 50,
            'completed_orders': 48,
            'dispute_count': 0,
            'total_revenue': 5000.0,
            'total_commission_paid': 450.0,
        },
        'SUP-002': {
            'id': 'SUP-002',
            'company_name': 'QuickDeliver',
            'supplier_type': 'delivery',
            'status': 'approved',
            'invitation_code': 'INV-002',
            'average_rating': 4.2,
            'total_orders': 100,
            'completed_orders': 95,
            'dispute_count': 2,
            'total_revenue': 15000.0,
        }
    }


@pytest.fixture
def sample_offers():
    return {
        'OFF-001': {
            'id': 'OFF-001',
            'supplier_id': 'SUP-001',
            'name': 'Vitamin Pack',
            'category': 'pharmacy',
            'item_type': 'product',
            'price': 50.00,
            'active': True,
            'description': 'Monthly vitamin supplement pack',
        },
        'OFF-002': {
            'id': 'OFF-002',
            'supplier_id': 'SUP-001',
            'name': 'Health Consultation',
            'category': 'medical',
            'item_type': 'service',
            'price': 100.00,
            'active': True,
            'description': 'Pharmacist health consultation session',
        }
    }


@pytest.fixture
def sample_orders():
    return {
        'ORD-001': {
            'id': 'ORD-001',
            'customer_id': 'CUST-001',
            'supplier_id': 'SUP-001',
            'offer_id': 'OFF-001',
            'total_amount': 50.0,
            'commission': 4.5,
            'supplier_payout': 45.5,
            'wallet_deduction': 50.0,
            'status': 'completed',
        }
    }


@pytest.fixture
def sample_claims():
    return {
        'CLM-001': {
            'id': 'CLM-001',
            'claim_id': 'CLM-001',
            'policy_id': 'POL-001',
            'customer_id': 'CUST-001',
            'amount': 1500.0,
            'status': 'pending',
            'description': 'Minor medical expense claim',
            'date': '2026-01-15T00:00:00+00:00',
            'payment_destination': 'health_wallet',
        },
        'CLM-002': {
            'id': 'CLM-002',
            'claim_id': 'CLM-002',
            'policy_id': 'POL-002',
            'customer_id': 'CUST-002',
            'amount': 200000.0,
            'status': 'pending',
            'description': 'Major medical procedure',
            'date': '2025-06-10T00:00:00+00:00',
            'payment_destination': 'bank_transfer',
        }
    }


@pytest.fixture
def sample_billing():
    return {
        'BILL-001': {
            'bill_id': 'BILL-001',
            'policy_id': 'POL-001',
            'customer_id': 'CUST-001',
            'amount_due': 500.0,
            'amount_paid': 500.0,
            'status': 'paid',
        }
    }


@pytest.fixture
def orchestrator(sample_policies, sample_customers, sample_claims,
                 sample_billing, sample_health_wallets, sample_suppliers,
                 sample_offers, sample_orders):
    reset_process_pipeline_orchestrator()
    return ProcessPipelineOrchestrator(
        policies=sample_policies,
        customers=sample_customers,
        claims=sample_claims,
        billing=sample_billing,
        health_wallets=sample_health_wallets,
        suppliers=sample_suppliers,
        supplier_offers=sample_offers,
        supplier_orders=sample_orders,
    )


# =========================================================================
# HEALTH WALLET PIPELINE TESTS
# =========================================================================

class TestHealthWalletPipeline:

    def test_valid_wallet(self, orchestrator):
        result = orchestrator.validate_health_wallet_pipeline('CUST-001')
        assert result.is_valid is True
        assert result.score > 0
        assert result.stage == 'health_wallet'

    def test_no_wallet(self, orchestrator):
        result = orchestrator.validate_health_wallet_pipeline('CUST-NONEXISTENT')
        assert result.is_valid is True
        assert result.metadata.get('status') == 'no_wallet'

    def test_negative_balance_detected(self, orchestrator):
        orchestrator.health_wallets['CUST-NEGATIVE'] = {
            'balance': -100.0,
            'transactions': []
        }
        result = orchestrator.validate_health_wallet_pipeline('CUST-NEGATIVE')
        assert result.is_valid is False
        assert any(i['severity'] == 'critical' for i in result.issues)


# =========================================================================
# SUPPLY CHAIN PIPELINE TESTS
# =========================================================================

class TestSupplyChainPipeline:

    def test_valid_supply_chain(self, orchestrator):
        result = orchestrator.validate_supply_chain_pipeline()
        assert result.is_valid is True
        assert result.score >= 80
        assert result.metadata['total_suppliers'] == 2

    def test_active_offer_unapproved_supplier(self, orchestrator):
        orchestrator.suppliers['SUP-BAD'] = {'status': 'pending'}
        orchestrator.supplier_offers['OFF-BAD'] = {
            'supplier_id': 'SUP-BAD',
            'active': True,
            'price': 10.0,
        }
        result = orchestrator.validate_supply_chain_pipeline()
        assert any(i.get('id') == 'OFF-BAD' for i in result.issues)

    def test_order_financial_mismatch(self, orchestrator):
        orchestrator.supplier_orders['ORD-BAD'] = {
            'total_amount': 100.0,
            'commission': 10.0,
            'supplier_payout': 50.0,
        }
        result = orchestrator.validate_supply_chain_pipeline()
        error_issues = [i for i in result.issues if i.get('severity') == 'error']
        assert len(error_issues) > 0

    def test_supply_chain_delegates_core_checks_to_integrity_service(self, orchestrator):
        class StubPipelineIntegrity:
            def __init__(self):
                self.called = False

            def validate_supply_chain_integrity(self, suppliers, offers, orders, health_wallets):
                self.called = True
                return {
                    'issues': [
                        {
                            'field': 'offer_supplier_status',
                            'description': 'Active offer OFF-DELEGATED belongs to non-approved supplier SUP-DELEGATED'
                        },
                        {
                            'field': 'order_financials',
                            'description': 'Order ORD-DELEGATED: commission+payout (90.00) != total (100.00)'
                        }
                    ]
                }

        stub = StubPipelineIntegrity()
        orchestrator.pipeline_integrity = stub
        result = orchestrator.validate_supply_chain_pipeline()

        assert stub.called is True
        assert any(i.get('id') == 'OFF-DELEGATED' for i in result.issues)
        assert any(i.get('id') == 'ORD-DELEGATED' for i in result.issues)


# =========================================================================
# DELIVERY PIPELINE TESTS
# =========================================================================

class TestDeliveryPipeline:

    def test_no_delivery_service(self, orchestrator):
        result = orchestrator.validate_delivery_pipeline()
        assert result.is_valid is True
        assert result.metadata.get('status') == 'service_not_initialized'

    def test_delivery_with_service(self, orchestrator):
        delivery_svc = DeliveryBiddingService()
        orchestrator.delivery = delivery_svc
        result = orchestrator.validate_delivery_pipeline()
        assert result.is_valid is True


# =========================================================================
# CLAIMS AUTOMATION TESTS
# =========================================================================

class TestClaimsAutomation:

    def test_low_risk_auto_approve(self, orchestrator):
        result = orchestrator.automate_claim_processing('CLM-001')
        assert result['success'] is True
        assert result['decision'] == 'auto_approve'
        assert result['fraud_score'] <= 0.2
        assert 'payout' in result

    def test_high_value_manual_review(self, orchestrator):
        result = orchestrator.automate_claim_processing('CLM-002')
        assert result['success'] is True
        assert result['decision'] in ('manual_review', 'refer_investigation')

    def test_claim_not_found(self, orchestrator):
        result = orchestrator.automate_claim_processing('CLM-NONEXISTENT')
        assert result['success'] is False

    def test_auto_approve_credits_wallet(self, orchestrator):
        old_balance = orchestrator.health_wallets['CUST-001']['balance']
        result = orchestrator.automate_claim_processing('CLM-001')
        assert result['decision'] == 'auto_approve'
        new_balance = orchestrator.health_wallets['CUST-001']['balance']
        assert new_balance > old_balance

    def test_fraud_score_early_claim(self, orchestrator):
        orchestrator.claims['CLM-EARLY'] = {
            'id': 'CLM-EARLY',
            'policy_id': 'POL-002',
            'customer_id': 'CUST-002',
            'amount': 500,
            'status': 'pending',
            'description': 'Early claim',
            'date': '2025-06-10T00:00:00+00:00',
            'payment_destination': 'health_wallet',
        }
        result = orchestrator.automate_claim_processing('CLM-EARLY')
        assert result['fraud_score'] > 0

    def test_zero_coverage_claim_requires_manual_review_without_crash(self, orchestrator):
        orchestrator.policies['POL-ZERO-COVERAGE'] = {
            'id': 'POL-ZERO-COVERAGE',
            'customer_id': 'CUST-001',
            'status': 'active',
            'coverage_amount': 0,
            'start_date': '2025-01-01T00:00:00+00:00',
        }
        orchestrator.claims['CLM-ZERO-COVERAGE'] = {
            'id': 'CLM-ZERO-COVERAGE',
            'claim_id': 'CLM-ZERO-COVERAGE',
            'policy_id': 'POL-ZERO-COVERAGE',
            'customer_id': 'CUST-001',
            'amount': 100.0,
            'status': 'pending',
            'description': 'Coverage edge case claim',
            'date': '2026-01-15T00:00:00+00:00',
        }

        result = orchestrator.automate_claim_processing('CLM-ZERO-COVERAGE')
        assert result['success'] is True
        assert result['decision'] == 'manual_review'

    def test_auto_approved_claim_updates_status_and_blocks_duplicate_payout(self, orchestrator):
        starting_balance = orchestrator.health_wallets['CUST-001']['balance']

        first = orchestrator.automate_claim_processing('CLM-001')
        assert first['success'] is True
        assert first['decision'] == 'auto_approve'
        assert orchestrator.claims['CLM-001']['status'] == 'paid'

        balance_after_first = orchestrator.health_wallets['CUST-001']['balance']
        second = orchestrator.automate_claim_processing('CLM-001')

        assert second['success'] is False
        assert 'already processed' in second['error']
        assert orchestrator.health_wallets['CUST-001']['balance'] == balance_after_first
        assert balance_after_first > starting_balance


# =========================================================================
# BILLING AUTOMATION TESTS
# =========================================================================

class TestBillingAutomation:

    def test_generate_bill(self, orchestrator):
        result = orchestrator.automate_billing_cycle('POL-001')
        assert result['success'] is True
        assert result['bill']['amount_due'] == 500.0
        assert result['premium_breakdown']['savings_percentage'] == 25.0

    def test_billing_inactive_policy(self, orchestrator):
        orchestrator.policies['POL-INACTIVE'] = {'status': 'cancelled'}
        result = orchestrator.automate_billing_cycle('POL-INACTIVE')
        assert result['success'] is False

    def test_process_payment(self, orchestrator):
        gen = orchestrator.automate_billing_cycle('POL-001')
        bill_id = gen['bill_id']
        result = orchestrator.process_billing_payment(bill_id, 500.0)
        assert result['success'] is True
        assert result['status'] == 'paid'
        assert result['wallet_credit'] is not None
        assert result['wallet_credit']['credited'] is True

    def test_partial_payment(self, orchestrator):
        gen = orchestrator.automate_billing_cycle('POL-001')
        bill_id = gen['bill_id']
        result = orchestrator.process_billing_payment(bill_id, 200.0)
        assert result['success'] is True
        assert result['status'] == 'partial'

    def test_installment_payments_mark_bill_paid(self, orchestrator):
        gen = orchestrator.automate_billing_cycle('POL-001')
        bill_id = gen['bill_id']

        first = orchestrator.process_billing_payment(bill_id, 300.0)
        assert first['success'] is True
        assert first['status'] == 'partial'
        assert first['amount_paid'] == 300.0

        second = orchestrator.process_billing_payment(bill_id, 200.0)
        assert second['success'] is True
        assert second['status'] == 'paid'
        assert second['amount_paid'] == 500.0
        assert second['wallet_credit'] is not None


# =========================================================================
# MARKETPLACE SUPPLY VALIDATION TESTS
# =========================================================================

class TestMarketplaceSupplyValidation:

    def test_auto_approve_good_offer(self, orchestrator):
        result = orchestrator.validate_new_supply('SUP-001', {
            'name': 'Blood Pressure Monitor',
            'category': 'equipment',
            'item_type': 'product',
            'price': 89.99,
            'description': 'Digital blood pressure monitor with Bluetooth connectivity',
        })
        assert result['success'] is True
        assert result['status'] == 'approved'
        assert result['auto_approved'] is True
        assert result['quality_score'] > 0
        assert result['data_hash'] != ''

    def test_reject_unapproved_supplier(self, orchestrator):
        orchestrator.suppliers['SUP-PENDING'] = {'status': 'pending'}
        result = orchestrator.validate_new_supply('SUP-PENDING', {
            'name': 'Test Product',
            'category': 'wellness',
            'item_type': 'product',
            'price': 25.0,
            'description': 'Test description for validation',
        })
        assert result['success'] is False

    def test_reject_missing_compliance(self, orchestrator):
        orchestrator.suppliers['SUP-NOLICENSE'] = {
            'status': 'approved',
            'average_rating': 4.5,
            'total_orders': 50,
            'completed_orders': 50,
            'dispute_count': 0,
        }
        result = orchestrator.validate_new_supply('SUP-NOLICENSE', {
            'name': 'Prescription Medicine',
            'category': 'pharmacy',
            'item_type': 'product',
            'price': 30.0,
            'description': 'Prescription medication requiring pharmacy license',
        })
        assert result['success'] is True
        assert result['compliance_checks']['supplier_licensed'] is False
        assert result['status'] == 'rejected'

    def test_high_price_review(self, orchestrator):
        result = orchestrator.validate_new_supply('SUP-001', {
            'name': 'MRI Scanner',
            'category': 'equipment',
            'item_type': 'product',
            'price': 50000.0,
            'description': 'Full body MRI scanner for medical imaging diagnostics',
        })
        assert result['success'] is True
        assert result['auto_approved'] is False

    def test_approve_and_reject_validation(self, orchestrator):
        result = orchestrator.validate_new_supply('SUP-001', {
            'name': 'Pending Item',
            'category': 'medical',
            'item_type': 'service',
            'price': 200.0,
            'description': 'Medical service requiring manual review and approval',
        })
        val_id = result['validation_id']

        approve_result = orchestrator.approve_supply_validation(val_id, 'admin', 'Looks good')
        assert approve_result['success'] is True
        assert approve_result['status'] == 'approved'

    def test_get_pending_validations(self, orchestrator):
        orchestrator.validate_new_supply('SUP-001', {
            'name': 'Medical Service A',
            'category': 'medical',
            'item_type': 'service',
            'price': 300.0,
            'description': 'Specialized medical consultation service offering',
        })
        pending = orchestrator.get_pending_supply_validations()
        assert isinstance(pending, list)

    def test_supplier_not_found(self, orchestrator):
        result = orchestrator.validate_new_supply('SUP-GHOST', {
            'name': 'Ghost Product',
            'category': 'other',
            'item_type': 'product',
            'price': 10.0,
        })
        assert result['success'] is False


# =========================================================================
# CROSS-PIPELINE INTEGRITY TESTS
# =========================================================================

class TestCrossPipelineIntegrity:

    def test_full_integrity_check(self, orchestrator):
        report = orchestrator.run_full_integrity_check()
        assert isinstance(report, CrossPipelineIntegrityReport)
        assert report.overall_score > 0
        assert report.overall_status in ('healthy', 'warning', 'critical')
        assert report.data_integrity_hash != ''
        assert len(report.stage_results) >= 4

    def test_all_stages_validated(self, orchestrator):
        report = orchestrator.run_full_integrity_check()
        assert 'supply_chain' in report.stage_results
        assert 'delivery' in report.stage_results
        assert 'claims' in report.stage_results
        assert 'billing' in report.stage_results
        assert 'health_wallet' in report.stage_results

    def test_recommendations_generated(self, orchestrator):
        report = orchestrator.run_full_integrity_check()
        assert isinstance(report.recommendations, list)
        assert len(report.recommendations) > 0

    def test_report_serializable(self, orchestrator):
        report = orchestrator.run_full_integrity_check()
        result_dict = report.to_dict()
        assert 'report_id' in result_dict
        assert 'overall_score' in result_dict
        assert 'stage_results' in result_dict


# =========================================================================
# PIPELINE DASHBOARD TESTS
# =========================================================================

class TestPipelineDashboard:

    def test_dashboard_data(self, orchestrator):
        dashboard = orchestrator.get_pipeline_dashboard()
        assert 'health_wallets' in dashboard
        assert 'supply_chain' in dashboard
        assert 'claims' in dashboard
        assert 'billing' in dashboard
        assert 'marketplace_validations' in dashboard
        assert 'automation' in dashboard

    def test_dashboard_counts(self, orchestrator):
        dashboard = orchestrator.get_pipeline_dashboard()
        assert dashboard['health_wallets']['total_wallets'] == 2
        assert dashboard['supply_chain']['total_suppliers'] == 2
        assert dashboard['claims']['total_claims'] == 2

    def test_automation_log(self, orchestrator):
        orchestrator.automate_claim_processing('CLM-001')
        orchestrator.automate_billing_cycle('POL-001')
        log = orchestrator.get_automation_log()
        assert len(log) >= 2


# =========================================================================
# PIPELINE INTEGRITY SERVICE ENHANCEMENTS TESTS
# =========================================================================

class TestPipelineIntegrityEnhancements:

    def test_supply_chain_integrity(self, sample_suppliers, sample_offers,
                                     sample_orders, sample_health_wallets):
        svc = PipelineIntegrityService()
        result = svc.validate_supply_chain_integrity(
            sample_suppliers, sample_offers, sample_orders, sample_health_wallets
        )
        assert result['stage'] == 'supply_chain'
        assert result['score'] > 0
        assert result['status'] in ('valid', 'warning', 'critical')

    def test_supply_chain_order_mismatch(self, sample_suppliers, sample_offers,
                                          sample_health_wallets):
        bad_orders = {
            'ORD-BAD': {
                'total_amount': 100.0,
                'commission': 10.0,
                'supplier_payout': 50.0,
                'wallet_deduction': 0,
                'customer_id': 'CUST-001'
            }
        }
        svc = PipelineIntegrityService()
        result = svc.validate_supply_chain_integrity(
            sample_suppliers, sample_offers, bad_orders, sample_health_wallets
        )
        assert len(result['issues']) > 0

    def test_delivery_integrity_empty(self):
        svc = PipelineIntegrityService()
        result = svc.validate_delivery_integrity({}, {}, {})
        assert result['score'] == 100.0

    def test_marketplace_integrity(self, sample_suppliers, sample_offers):
        svc = PipelineIntegrityService()
        result = svc.validate_marketplace_data_integrity(
            sample_suppliers, sample_offers
        )
        assert result['stage'] == 'marketplace'
        assert result['score'] > 0

    def test_marketplace_zero_price_offer(self, sample_suppliers):
        offers = {
            'OFF-FREE': {
                'id': 'OFF-FREE',
                'supplier_id': 'SUP-001',
                'price': 0,
                'active': True,
            }
        }
        svc = PipelineIntegrityService()
        result = svc.validate_marketplace_data_integrity(sample_suppliers, offers)
        assert len(result['issues']) > 0


# =========================================================================
# DELIVERY BIDDING SERVICE TESTS (Post-Fix)
# =========================================================================

class TestDeliveryBiddingServiceFixed:

    def test_import(self):
        from services.delivery_bidding_service import DeliveryBiddingService
        svc = DeliveryBiddingService()
        assert svc is not None

    def test_create_delivery_request(self):
        svc = DeliveryBiddingService()
        result = svc.create_delivery_request(
            order_id='ORD-TEST-001',
            customer_id='CUST-001',
            pickup_location={'latitude': 32.0853, 'longitude': 34.7818, 'city': 'Tel Aviv'},
            delivery_location={'latitude': 31.7683, 'longitude': 35.2137, 'city': 'Jerusalem'},
            package_info={'description': 'Medical supplies', 'weight_kg': 2.0},
            priority='standard'
        )
        assert result['success'] is True
        assert 'request_id' in result
        assert result['distance_km'] > 0

    def test_submit_bid(self):
        suppliers = {'SUP-D1': {'company_name': 'FastDeliver', 'status': 'approved',
                                'supplier_type': 'delivery', 'average_rating': 4.3}}
        svc = DeliveryBiddingService(suppliers=suppliers)
        req = svc.create_delivery_request(
            order_id='ORD-BID-001',
            customer_id='CUST-001',
            pickup_location={'latitude': 32.0, 'longitude': 34.8},
            delivery_location={'latitude': 31.8, 'longitude': 35.2},
            package_info={'description': 'Meds'},
        )
        req_id = req['request_id']
        now = datetime.now(timezone.utc)
        bid_result = svc.submit_bid(
            request_id=req_id,
            supplier_id='SUP-D1',
            bid_price=25.0,
            estimated_pickup_time=(now + timedelta(hours=1)).isoformat(),
            estimated_delivery_time=(now + timedelta(hours=4)).isoformat(),
        )
        assert bid_result['success'] is True
        assert bid_result['ai_score'] > 0

    def test_select_bid_with_wallet(self):
        wallets = {'CUST-W1': {'balance': 500.0, 'transactions': []}}
        suppliers = {'SUP-D2': {'company_name': 'QuickShip', 'status': 'approved',
                                'supplier_type': 'delivery', 'average_rating': 4.0}}
        svc = DeliveryBiddingService(suppliers=suppliers, health_wallets=wallets)
        req = svc.create_delivery_request(
            order_id='ORD-SEL-001',
            customer_id='CUST-W1',
            pickup_location={'latitude': 32.0, 'longitude': 34.8},
            delivery_location={'latitude': 31.5, 'longitude': 34.5},
            package_info={'description': 'Package'},
        )
        req_id = req['request_id']
        now = datetime.now(timezone.utc)
        bid = svc.submit_bid(
            request_id=req_id,
            supplier_id='SUP-D2',
            bid_price=30.0,
            estimated_pickup_time=(now + timedelta(hours=1)).isoformat(),
            estimated_delivery_time=(now + timedelta(hours=5)).isoformat(),
        )
        sel = svc.select_bid(req_id, bid['bid_id'], 'customer')
        assert sel['success'] is True
        assert sel['price_paid'] == 30.0
        assert wallets['CUST-W1']['balance'] == 470.0

    def test_delivery_analytics(self):
        svc = DeliveryBiddingService()
        analytics = svc.get_delivery_analytics()
        assert 'total_delivery_requests' in analytics

    def test_ai_insights(self):
        svc = DeliveryBiddingService()
        insights = svc.get_ai_delivery_insights()
        assert 'recommendations' in insights
        assert 'alerts' in insights


# =========================================================================
# END-TO-END PIPELINE TEST
# =========================================================================

class TestEndToEndPipeline:

    def test_full_customer_journey(self, orchestrator):
        """Test complete flow: billing -> wallet funded -> marketplace purchase -> claim -> integrity"""
        bill_result = orchestrator.automate_billing_cycle('POL-001')
        assert bill_result['success'] is True
        bill_id = bill_result['bill_id']

        pay_result = orchestrator.process_billing_payment(bill_id, 500.0)
        assert pay_result['success'] is True
        assert pay_result['wallet_credit']['credited'] is True

        supply_result = orchestrator.validate_new_supply('SUP-001', {
            'name': 'Blood Test Kit',
            'category': 'equipment',
            'item_type': 'product',
            'price': 35.0,
            'description': 'At-home blood test kit for routine health monitoring',
        })
        assert supply_result['success'] is True
        assert supply_result['status'] == 'approved'

        claim_result = orchestrator.automate_claim_processing('CLM-001')
        assert claim_result['success'] is True

        report = orchestrator.run_full_integrity_check()
        assert report.overall_score > 50
        assert report.overall_status in ('healthy', 'warning')

    def test_pipeline_dashboard_after_operations(self, orchestrator):
        orchestrator.automate_billing_cycle('POL-001')
        orchestrator.automate_claim_processing('CLM-001')
        orchestrator.validate_new_supply('SUP-001', {
            'name': 'Test Supply',
            'category': 'wellness',
            'item_type': 'product',
            'price': 20.0,
            'description': 'Wellness product for daily health maintenance',
        })

        dashboard = orchestrator.get_pipeline_dashboard()
        assert dashboard['automation']['total_actions'] >= 3
        assert dashboard['marketplace_validations']['total'] >= 1
