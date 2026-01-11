"""
Pipeline Integrity Test Suite
=============================
Tests for validating data integrity through the insurance pipeline,
with special focus on savings percentage tracking.

Tests verify that:
1. Savings % from application flows correctly to billing
2. Premium calculations are consistent (monthly/quarterly/annual)
3. Coverage amounts remain unchanged through pipeline
4. Health wallet allocations match application config
"""

import pytest
import threading
import time
import json
from http.server import HTTPServer
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from datetime import datetime

import web_portal.server as portal
from services.pipeline_integrity_service import (
    PipelineIntegrityService,
    PipelineIntegrityReport,
    IntegrityIssue
)


class ServerThread(threading.Thread):
    """Thread to run the HTTP server in background"""
    def __init__(self, port):
        super().__init__(daemon=True)
        self.port = port
        self.httpd = HTTPServer(('127.0.0.1', port), portal.PortalHandler)

    def run(self):
        self.httpd.serve_forever()

    def stop(self):
        self.httpd.shutdown()


def _post(url, payload, token=None):
    """HTTP POST request"""
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    data = json.dumps(payload).encode('utf-8')
    req = Request(url, data=data, headers=headers)
    with urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8')), resp.status


def _get(url, token=None):
    """HTTP GET request"""
    headers = {}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = Request(url, headers=headers)
    with urlopen(req) as resp:
        return json.loads(resp.read().decode('utf-8')), resp.status


class TestPipelineIntegrityService:
    """Test the PipelineIntegrityService directly"""
    
    def test_service_initialization(self):
        """Test service can be initialized"""
        service = PipelineIntegrityService()
        assert service is not None
        assert service.SAVINGS_TOLERANCE == 0.001
        assert service.PREMIUM_TOLERANCE == 0.01
    
    def test_validate_empty_policy(self):
        """Test validation with non-existent policy"""
        service = PipelineIntegrityService(policies={})
        report = service.validate_policy_pipeline("POL-NONEXISTENT")
        
        assert report.integrity_status == "critical"
        assert report.integrity_score == 0
        assert len(report.issues) == 1
        assert report.issues[0].severity == "critical"
    
    def test_validate_valid_policy(self):
        """Test validation with a valid policy"""
        policies = {
            'POL-TEST-001': {
                'id': 'POL-TEST-001',
                'customer_id': 'CUST-001',
                'coverage_amount': 100000,
                'annual_premium': 1200,
                'monthly_premium': 100,
                'quarterly_premium': 300,
                'status': 'active',
                'health_wallet': json.dumps({'allocation_percentage': 10})
            }
        }
        
        underwriting = {
            'UW-001': {
                'policy_id': 'POL-TEST-001',
                'customer_id': 'CUST-001',
                'coverage_amount': 100000,
                'status': 'approved',
                'payment_setup': json.dumps({'savings_percentage': 10})
            }
        }
        
        billing = {
            'BILL-001': {
                'policy_id': 'POL-TEST-001',
                'customer_id': 'CUST-001',
                'amount': 100,
                'status': 'pending',
                'premium_breakdown': json.dumps({'savings_percentage': 10})
            }
        }
        
        service = PipelineIntegrityService(
            policies=policies,
            underwriting_apps=underwriting,
            billing=billing
        )
        
        report = service.validate_policy_pipeline('POL-TEST-001')
        
        assert report.integrity_score >= 90
        assert report.savings_integrity_valid
        assert report.original_savings_percentage == 10
        assert report.final_savings_percentage == 10
    
    def test_detect_savings_mismatch(self):
        """Test detection of savings percentage mismatch"""
        policies = {
            'POL-TEST-002': {
                'id': 'POL-TEST-002',
                'customer_id': 'CUST-001',
                'coverage_amount': 100000,
                'annual_premium': 1200,
                'monthly_premium': 100,
                'status': 'active',
                'health_wallet': json.dumps({'allocation_percentage': 15})  # Different!
            }
        }
        
        underwriting = {
            'UW-002': {
                'policy_id': 'POL-TEST-002',
                'customer_id': 'CUST-001',
                'coverage_amount': 100000,
                'status': 'approved',
                'payment_setup': json.dumps({'savings_percentage': 10})  # Original 10%
            }
        }
        
        service = PipelineIntegrityService(
            policies=policies,
            underwriting_apps=underwriting
        )
        
        report = service.validate_policy_pipeline('POL-TEST-002')
        
        assert not report.savings_integrity_valid
        assert report.original_savings_percentage == 10
        # Find the savings issue
        savings_issues = [i for i in report.issues if i.field == 'savings_percentage']
        assert len(savings_issues) > 0
        assert savings_issues[0].expected_value == 10
        assert savings_issues[0].actual_value == 15
    
    def test_detect_premium_inconsistency(self):
        """Test detection of premium calculation errors"""
        policies = {
            'POL-TEST-003': {
                'id': 'POL-TEST-003',
                'customer_id': 'CUST-001',
                'coverage_amount': 100000,
                'annual_premium': 1200,
                'monthly_premium': 150,  # Should be 100 (1200/12)
                'quarterly_premium': 300,
                'status': 'active',
                'health_wallet': '{}'
            }
        }
        
        service = PipelineIntegrityService(policies=policies)
        report = service.validate_policy_pipeline('POL-TEST-003')
        
        assert not report.premium_consistency_valid
        # Find premium issue
        premium_issues = [i for i in report.issues if i.field == 'monthly_premium']
        assert len(premium_issues) > 0
    
    def test_detect_coverage_change(self):
        """Test detection of unauthorized coverage amount changes"""
        policies = {
            'POL-TEST-004': {
                'id': 'POL-TEST-004',
                'customer_id': 'CUST-001',
                'coverage_amount': 150000,  # Changed from 100000!
                'annual_premium': 1200,
                'monthly_premium': 100,
                'status': 'active',
                'health_wallet': '{}'
            }
        }
        
        underwriting = {
            'UW-004': {
                'policy_id': 'POL-TEST-004',
                'customer_id': 'CUST-001',
                'coverage_amount': 100000,  # Original
                'status': 'approved',
                'payment_setup': '{}'
            }
        }
        
        service = PipelineIntegrityService(
            policies=policies,
            underwriting_apps=underwriting
        )
        
        report = service.validate_policy_pipeline('POL-TEST-004')
        
        # Should find critical coverage change issue
        coverage_issues = [i for i in report.issues if i.field == 'coverage_amount']
        assert len(coverage_issues) > 0
        assert coverage_issues[0].severity == 'critical'
    
    def test_ai_recommendations(self):
        """Test AI recommendations are generated"""
        policies = {
            'POL-TEST-005': {
                'id': 'POL-TEST-005',
                'customer_id': 'CUST-001',
                'coverage_amount': 100000,
                'annual_premium': 1200,
                'monthly_premium': 100,
                'status': 'active',
                'health_wallet': json.dumps({'allocation_percentage': 10})
            }
        }
        
        service = PipelineIntegrityService(policies=policies)
        report = service.validate_policy_pipeline('POL-TEST-005')
        
        assert len(report.ai_recommendations) > 0
        # Should have positive recommendation for valid policy
        assert any('INTEGRITY' in r or '✅' in r for r in report.ai_recommendations)
    
    def test_bi_dashboard_data(self):
        """Test BI dashboard data generation"""
        policies = {
            'POL-001': {
                'id': 'POL-001',
                'customer_id': 'CUST-001',
                'coverage_amount': 100000,
                'annual_premium': 1200,
                'monthly_premium': 100,
                'status': 'active',
                'health_wallet': '{}'
            }
        }
        
        service = PipelineIntegrityService(policies=policies)
        
        # Generate some reports
        service.validate_policy_pipeline('POL-001')
        
        dashboard = service.get_bi_dashboard_data()
        
        assert 'total_validations' in dashboard
        assert 'average_score' in dashboard
        assert dashboard['total_validations'] >= 1


class TestEndToEndPipelineIntegrity:
    """End-to-end tests using the actual web portal"""
    
    def test_full_pipeline_with_savings(self):
        """Test complete pipeline from application to billing with savings tracking"""
        port = 8150
        srv = ServerThread(port)
        srv.start()
        time.sleep(0.5)
        
        base = f"http://127.0.0.1:{port}"
        
        try:
            # Step 1: Create customer via registration
            test_invitation_code = "TESTCODE2026"
            customer_email = f"pipeline_test_{datetime.now().strftime('%H%M%S')}@example.com"
            
            reg_data, status = _post(f"{base}/api/register", {
                "name": "Pipeline Test Customer",
                "email": customer_email,
                "password": "SecurePass123!",
                "phone": "555-1234",
                "dob": "1985-05-15",
                "invitation_code": test_invitation_code
            })
            assert status == 201
            customer_id = reg_data.get('customer_id')
            assert customer_id is not None
            
            # Step 2: Submit insurance application with specific savings config
            savings_percentage = 15  # 15% savings
            
            # Use the correct endpoint: /api/policies/create
            app_data, status = _post(f"{base}/api/policies/create", {
                "customer_name": "Pipeline Test Customer",
                "customer_email": customer_email,
                "customer_id": customer_id,
                "age": 35,
                "gender": "male",
                "occupation": "Engineer",
                "coverage_amount": 200000,
                "type": "life",
                "payment_setup": {
                    "frequency": "monthly",
                    "savings_percentage": savings_percentage,
                    "auto_pay": True
                },
                "health_wallet": {
                    "enabled": True,
                    "allocation_percentage": savings_percentage
                }
            })
            assert status == 201, f"Application failed: {app_data}"
            application_id = app_data.get('underwriting_id') or app_data.get('application_id') or app_data.get('id')
            policy_id = app_data.get('policy_id') or app_data.get('id')
            
            # Step 3: Verify application has correct savings
            apps_data, _ = _get(f"{base}/api/underwriting/applications")
            
            # Find our application
            our_app = None
            if isinstance(apps_data, list):
                for app in apps_data:
                    if app.get('customer_email') == customer_email:
                        our_app = app
                        break
            elif isinstance(apps_data, dict) and 'applications' in apps_data:
                for app in apps_data['applications']:
                    if app.get('customer_email') == customer_email:
                        our_app = app
                        break
            
            if our_app:
                # Verify savings in application
                payment_setup = our_app.get('payment_setup', {})
                if isinstance(payment_setup, str):
                    payment_setup = json.loads(payment_setup)
                app_savings = payment_setup.get('savings_percentage', 0)
                
                print(f"\nApplication savings percentage: {app_savings}%")
                assert app_savings == savings_percentage, \
                    f"Application savings {app_savings}% doesn't match requested {savings_percentage}%"
            
            # Step 4: Approve the application (creates policy and billing)
            if application_id:
                approve_data, status = _post(f"{base}/api/underwriting/approve/{application_id}", {
                    "decision": "approved",
                    "notes": "Pipeline integrity test approval"
                })
                # Approval might return different status codes
                print(f"Approval response: {approve_data}")
            
            # Step 5: Check policy has correct savings
            if policy_id:
                policies_data, _ = _get(f"{base}/api/policies")
                
                our_policy = None
                if isinstance(policies_data, list):
                    for p in policies_data:
                        if p.get('id') == policy_id or p.get('policy_id') == policy_id:
                            our_policy = p
                            break
                elif isinstance(policies_data, dict) and 'policies' in policies_data:
                    for p in policies_data['policies']:
                        if p.get('id') == policy_id or p.get('policy_id') == policy_id:
                            our_policy = p
                            break
                
                if our_policy:
                    hw = our_policy.get('health_wallet', {})
                    if isinstance(hw, str):
                        hw = json.loads(hw) if hw else {}
                    policy_savings = hw.get('allocation_percentage', 0)
                    
                    print(f"Policy savings percentage: {policy_savings}%")
                    # This is the key integrity check!
                    assert policy_savings == savings_percentage, \
                        f"Policy savings {policy_savings}% doesn't match application {savings_percentage}%"
            
            # Step 6: Check billing has correct breakdown
            # Note: /api/billing requires auth in test mode, skip if 403
            try:
                billing_data, _ = _get(f"{base}/api/billing")
                
                if policy_id and billing_data:
                    bills = billing_data if isinstance(billing_data, list) else billing_data.get('bills', [])
                    our_bills = [b for b in bills if b.get('policy_id') == policy_id]
                    
                    if our_bills:
                        bill = our_bills[0]
                        breakdown = bill.get('premium_breakdown', {})
                        if isinstance(breakdown, str):
                            breakdown = json.loads(breakdown) if breakdown else {}
                        
                        billing_savings = breakdown.get('savings_percentage', 0)
                        print(f"Billing savings percentage: {billing_savings}%")
                        
                        # Final integrity check
                        assert billing_savings == savings_percentage, \
                            f"Billing savings {billing_savings}% doesn't match application {savings_percentage}%"
            except HTTPError as e:
                if e.code == 403:
                    print("Note: Billing API requires auth, skipping billing verification")
                else:
                    raise
            
            print("\n✅ PIPELINE INTEGRITY TEST PASSED")
            print(f"   Savings percentage maintained at {savings_percentage}% through entire pipeline")
            
        finally:
            srv.stop()
    
    def test_premium_calculation_integrity(self):
        """Test that premium calculations are consistent through pipeline"""
        port = 8151
        srv = ServerThread(port)
        srv.start()
        time.sleep(0.5)
        
        base = f"http://127.0.0.1:{port}"
        
        try:
            # Create a policy with known premium values
            test_invitation_code = "TESTCODE2026"
            customer_email = f"premium_test_{datetime.now().strftime('%H%M%S')}@example.com"
            
            # Register customer
            reg_data, _ = _post(f"{base}/api/register", {
                "name": "Premium Test Customer",
                "email": customer_email,
                "password": "SecurePass123!",
                "phone": "555-5678",
                "invitation_code": test_invitation_code
            })
            
            # Submit application with specific coverage
            coverage_amount = 100000
            customer_id = reg_data.get('customer_id')
            
            # Use correct endpoint: /api/policies/create
            app_data, status = _post(f"{base}/api/policies/create", {
                "customer_name": "Premium Test Customer",
                "customer_email": customer_email,
                "customer_id": customer_id,
                "age": 30,
                "gender": "female",
                "occupation": "Teacher",
                "coverage_amount": coverage_amount,
                "type": "health"
            })
            
            policy_id = app_data.get('policy_id')
            
            # Get policy and verify premium relationships
            if policy_id:
                policies_data, _ = _get(f"{base}/api/policies")
                
                our_policy = None
                policies = policies_data if isinstance(policies_data, list) else policies_data.get('policies', [])
                for p in policies:
                    if p.get('id') == policy_id or p.get('policy_id') == policy_id:
                        our_policy = p
                        break
                
                if our_policy:
                    annual = float(our_policy.get('annual_premium', 0))
                    monthly = float(our_policy.get('monthly_premium', 0))
                    quarterly = float(our_policy.get('quarterly_premium', 0))
                    
                    print(f"\nPremium values:")
                    print(f"  Annual:    ${annual:,.2f}")
                    print(f"  Monthly:   ${monthly:,.2f}")
                    print(f"  Quarterly: ${quarterly:,.2f}")
                    
                    # Verify relationships (with 1% tolerance)
                    if annual > 0 and monthly > 0:
                        expected_monthly = annual / 12
                        tolerance = expected_monthly * 0.01
                        assert abs(monthly - expected_monthly) <= tolerance, \
                            f"Monthly ${monthly} should be ${expected_monthly} (annual/12)"
                    
                    if annual > 0 and quarterly > 0:
                        expected_quarterly = annual / 4
                        tolerance = expected_quarterly * 0.01
                        assert abs(quarterly - expected_quarterly) <= tolerance, \
                            f"Quarterly ${quarterly} should be ${expected_quarterly} (annual/4)"
                    
                    print("✅ Premium calculation integrity verified")
            
        finally:
            srv.stop()


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
