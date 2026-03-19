#!/usr/bin/env python3
"""
Integration test for risk-dashboard upload functionality
Tests the full workflow: login -> upload -> verify
"""
import requests
import json
import time

BASE_URL = "http://localhost:8000"
REQUEST_TIMEOUT = 10

def test_risk_dashboard_integration():
    """Test the complete risk dashboard upload workflow"""
    print("=" * 70)
    print("RISK DASHBOARD INTEGRATION TEST")
    print("=" * 70)
    
    # Step 1: Login as underwriter
    print("\n[1] Testing login as underwriter...")
    login_response = requests.post(f"{BASE_URL}/api/login", json={
        "username": "underwriter",
        "password": "under123"
    }, timeout=REQUEST_TIMEOUT)
    
    if login_response.status_code == 200:
        login_data = login_response.json()
        token = login_data.get('token')
        print(f"   ✓ Login successful")
        print(f"   ✓ Token: {token[:20]}...")
        print(f"   ✓ Role: {login_data.get('role')}")
    else:
        print(f"   ✗ Login failed: {login_response.status_code}")
        return False
    
    # Step 2: Verify session
    print("\n[2] Testing session verification...")
    verify_response = requests.get(f"{BASE_URL}/api/session/verify", headers={
        "Authorization": f"Bearer {token}"
    }, timeout=REQUEST_TIMEOUT)
    
    if verify_response.status_code == 200:
        verify_data = verify_response.json()
        print(f"   ✓ Session verified")
        print(f"   ✓ Username: {verify_data.get('username')}")
        print(f"   ✓ Role: {verify_data.get('role')}")
    else:
        print(f"   ✗ Session verification failed: {verify_response.status_code}")
        return False
    
    # Step 3: Upload risk assessment data
    print("\n[3] Testing risk assessment upload...")
    upload_data = {
        "data": [
            {
                "customer_id": "CUST-TEST-001",
                "risk_score": 45.5,
                "assessment_date": "2024-02-04",
                "status": "pending",
                "medical_conditions": "None",
                "occupation_risk": "Low",
                "lifestyle_factors": "Non-smoker",
                "premium_loading": 0
            },
            {
                "customer_id": "CUST-TEST-002",
                "risk_score": 65.0,
                "assessment_date": "2024-02-04",
                "status": "pending",
                "medical_conditions": "Diabetes Type 2",
                "occupation_risk": "Medium",
                "lifestyle_factors": "Smoker",
                "premium_loading": 15
            }
        ],
        "filename": "test_upload.json",
        "upload_date": "2024-02-04T10:00:00Z"
    }
    
    upload_response = requests.post(
        f"{BASE_URL}/api/risk-assessment/upload",
        json=upload_data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        timeout=REQUEST_TIMEOUT,
    )
    
    if upload_response.status_code in [200, 201]:
        upload_result = upload_response.json()
        print(f"   ✓ Upload successful")
        print(f"   ✓ Upload ID: {upload_result.get('upload_id')}")
        print(f"   ✓ Processed: {upload_result.get('processed')}")
        print(f"   ✓ Created: {upload_result.get('created')}")
        print(f"   ✓ Updated: {upload_result.get('updated')}")
        print(f"   ✓ Errors: {upload_result.get('total_errors', 0)}")
    else:
        print(f"   ✗ Upload failed: {upload_response.status_code}")
        print(f"   Error: {upload_response.text}")
        return False
    
    # Step 4: Test authorization with wrong role
    print("\n[4] Testing authorization with accountant role (should fail)...")
    
    # Login as accountant
    accountant_login = requests.post(f"{BASE_URL}/api/login", json={
        "username": "accountant",
        "password": "acct123"
    }, timeout=REQUEST_TIMEOUT)
    
    if accountant_login.status_code == 200:
        accountant_token = accountant_login.json().get('token')
        
        # Try to upload (should be denied)
        unauthorized_upload = requests.post(
            f"{BASE_URL}/api/risk-assessment/upload",
            json=upload_data,
            headers={
                "Authorization": f"Bearer {accountant_token}",
                "Content-Type": "application/json"
            },
            timeout=REQUEST_TIMEOUT,
        )
        
        if unauthorized_upload.status_code == 403:
            print(f"   ✓ Authorization check working: {unauthorized_upload.json().get('error')}")
        else:
            print(f"   ✗ Authorization check failed: Expected 403, got {unauthorized_upload.status_code}")
            return False
    
    # Step 5: Test with invalid data
    print("\n[5] Testing validation with invalid data...")
    
    invalid_data = {
        "data": [
            {
                "customer_id": "CUST-TEST-003",
                "risk_score": 150,  # Invalid: > 100
                "assessment_date": "2024-02-04"
            },
            {
                "customer_id": "CUST-TEST-004",
                "risk_score": "not_a_number",  # Invalid: not numeric
                "assessment_date": "2024-02-04"
            }
        ],
        "filename": "test_invalid.json"
    }
    
    invalid_upload = requests.post(
        f"{BASE_URL}/api/risk-assessment/upload",
        json=invalid_data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        timeout=REQUEST_TIMEOUT,
    )
    
    if invalid_upload.status_code in [200, 201]:
        invalid_result = invalid_upload.json()
        print(f"   ✓ Validation working")
        print(f"   ✓ Processed: {invalid_result.get('processed')}")
        print(f"   ✓ Errors: {invalid_result.get('total_errors')}")
        if invalid_result.get('errors'):
            print(f"   ✓ Sample errors:")
            for err in invalid_result.get('errors', [])[:2]:
                print(f"      - {err}")
    else:
        print(f"   ✗ Validation test failed: {invalid_upload.status_code}")
        return False
    
    print("\n" + "=" * 70)
    print("✅ ALL INTEGRATION TESTS PASSED")
    print("=" * 70)
    
    return True

if __name__ == '__main__':
    import sys
    
    print("\nStarting server test in background...")
    print("Note: Make sure the server is running on http://localhost:8000")
    print("You can start it with: python3 web_portal/server.py\n")
    
    time.sleep(2)
    
    try:
        # Test if server is running
        test_response = requests.get(f"{BASE_URL}/api/health", timeout=2)
        print(f"✓ Server is running (status: {test_response.status_code})\n")
    except Exception as e:
        print(f"✗ Server is not running or not accessible: {e}")
        print("Please start the server first: python3 web_portal/server.py")
        sys.exit(1)
    
    try:
        success = test_risk_dashboard_integration()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
