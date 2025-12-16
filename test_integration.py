#!/usr/bin/env python3
"""
Integration Test for PHINS System
Tests the newly added components to ensure they work together.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))


def test_ai_automation_controller():
    """Test AI automation controller functionality"""
    print("\n" + "=" * 60)
    print("Testing AI Automation Controller")
    print("=" * 60)
    
    from ai_automation_controller import get_automation_controller, AutomationDecision
    
    controller = get_automation_controller()
    
    # Test 1: Auto-quote generation
    print("\n1. Testing auto-quote generation...")
    quote = controller.generate_auto_quote({
        'age': 35,
        'occupation': 'office_worker',
        'health_score': 8,
        'coverage_amount': 500000,
        'smoking': False
    })
    
    assert 'quote_id' in quote
    assert 'annual_premium' in quote
    assert 'confidence_score' in quote
    assert quote['coverage_amount'] == 500000
    print(f"   ✓ Quote generated: {quote['quote_id']}")
    print(f"   ✓ Annual premium: ${quote['annual_premium']}")
    print(f"   ✓ Confidence: {quote['confidence_score']}")
    
    # Test 2: Auto-underwriting
    print("\n2. Testing auto-underwriting...")
    decision, details = controller.auto_underwrite({
        'age': 30,
        'smoker': False,
        'pre_existing_conditions': False,
        'health_score': 8,
        'employment_stable': True
    })
    
    assert decision in [AutomationDecision.AUTO_APPROVE, AutomationDecision.AUTO_REJECT, AutomationDecision.HUMAN_REVIEW]
    assert 'risk_score' in details
    print(f"   ✓ Decision: {decision.value}")
    print(f"   ✓ Risk score: {details['risk_score']}")
    
    # Test 3: Claims processing
    print("\n3. Testing auto-claims processing...")
    claim_decision, claim_details = controller.auto_process_claim({
        'claimed_amount': 750,
        'type': 'medical',
        'policy_coverage': 100000,
        'has_complete_documentation': True,
        'days_since_policy_start': 120
    })
    
    assert claim_decision in [AutomationDecision.AUTO_APPROVE, AutomationDecision.AUTO_REJECT, AutomationDecision.HUMAN_REVIEW]
    print(f"   ✓ Claim decision: {claim_decision.value}")
    
    # Test 4: Metrics
    print("\n4. Testing metrics tracking...")
    metrics = controller.get_metrics()
    assert 'total_processed' in metrics
    assert 'automation_rate' in metrics
    print(f"   ✓ Total processed: {metrics['total_processed']}")
    print(f"   ✓ Automation rate: {metrics['automation_rate']}%")
    
    print("\n✓ All AI automation controller tests passed!")


def test_init_database_module():
    """Test that init_database module can be imported"""
    print("\n" + "=" * 60)
    print("Testing Database Initialization Module")
    print("=" * 60)
    
    import init_database
    
    # Check that main functions exist
    assert hasattr(init_database, 'init_database')
    assert hasattr(init_database, 'main')
    print("   ✓ init_database module imported successfully")
    print("   ✓ Required functions present")
    
    print("\n✓ Database initialization module tests passed!")


def test_html_pages_exist():
    """Test that all required HTML pages exist"""
    print("\n" + "=" * 60)
    print("Testing HTML Pages Existence")
    print("=" * 60)
    
    web_portal_path = os.path.join(os.path.dirname(__file__), 'web_portal', 'static')
    
    required_pages = [
        'index.html',
        'login.html',
        'admin-portal.html',
        'client-portal.html',
        'underwriter-dashboard.html',
        'accountant-dashboard.html',
        'claims-adjuster-dashboard.html',
        'quote.html',
        'apply.html'
    ]
    
    for page in required_pages:
        page_path = os.path.join(web_portal_path, page)
        assert os.path.exists(page_path), f"Missing: {page}"
        print(f"   ✓ {page} exists")
    
    print("\n✓ All required HTML pages exist!")


def test_database_config():
    """Test database configuration"""
    print("\n" + "=" * 60)
    print("Testing Database Configuration")
    print("=" * 60)
    
    from database.config import DatabaseConfig
    
    # Test basic configuration
    db_url = DatabaseConfig.get_database_url()
    assert db_url is not None
    print(f"   ✓ Database URL configured: {db_url[:50]}...")
    
    # Test configuration summary
    config_summary = DatabaseConfig.get_config_summary()
    assert 'database_type' in config_summary
    print(f"   ✓ Database type: {config_summary['database_type']}")
    
    # Test engine options
    engine_options = DatabaseConfig.get_engine_options()
    assert 'echo' in engine_options
    print("   ✓ Engine options configured")
    
    print("\n✓ Database configuration tests passed!")


def test_ai_architecture_documentation():
    """Test that AI architecture documentation exists"""
    print("\n" + "=" * 60)
    print("Testing AI Architecture Documentation")
    print("=" * 60)
    
    doc_path = os.path.join(os.path.dirname(__file__), 'AI_ARCHITECTURE.md')
    assert os.path.exists(doc_path), "AI_ARCHITECTURE.md not found"
    
    # Check file size (should be substantial)
    file_size = os.path.getsize(doc_path)
    assert file_size > 1000, "Documentation seems too small"
    print(f"   ✓ AI_ARCHITECTURE.md exists ({file_size} bytes)")
    
    # Read and check for key sections
    with open(doc_path, 'r') as f:
        content = f.read()
    
    required_sections = [
        'Auto-Quote Generation',
        'Automated Underwriting',
        'Smart Claims Processing',
        'Fraud Detection',
        'Integration'
    ]
    
    for section in required_sections:
        assert section in content, f"Missing section: {section}"
        print(f"   ✓ Section present: {section}")
    
    print("\n✓ AI architecture documentation tests passed!")


def test_login_routing():
    """Test login.js has role-based routing"""
    print("\n" + "=" * 60)
    print("Testing Login Role-Based Routing")
    print("=" * 60)
    
    login_js_path = os.path.join(os.path.dirname(__file__), 'web_portal', 'static', 'login.js')
    assert os.path.exists(login_js_path), "login.js not found"
    
    with open(login_js_path, 'r') as f:
        content = f.read()
    
    # Check for role-based routing
    required_routes = [
        'admin-portal.html',
        'client-portal.html',
        'underwriter-dashboard.html',
        'claims-adjuster-dashboard.html',
        'accountant-dashboard.html'
    ]
    
    for route in required_routes:
        assert route in content, f"Missing route: {route}"
        print(f"   ✓ Route configured: {route}")
    
    print("\n✓ Login routing tests passed!")


def run_all_tests():
    """Run all integration tests"""
    print("\n" + "=" * 70)
    print(" " * 15 + "PHINS SYSTEM INTEGRATION TESTS")
    print("=" * 70)
    
    try:
        test_ai_automation_controller()
        test_init_database_module()
        test_html_pages_exist()
        test_database_config()
        test_ai_architecture_documentation()
        test_login_routing()
        
        print("\n" + "=" * 70)
        print("✓ ALL INTEGRATION TESTS PASSED!")
        print("=" * 70)
        print("\nSystem is ready for deployment!")
        print()
        return True
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return False
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
