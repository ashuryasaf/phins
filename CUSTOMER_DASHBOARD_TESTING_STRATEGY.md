# Customer Dashboard Testing Strategy

**Document Version:** 1.0  
**Created:** February 3, 2026  
**Purpose:** Comprehensive testing approach for new customer dashboard  
**Status:** 📋 Ready for Implementation Upon Approval

---

## 🧪 Testing Overview

### Three-Layer Testing Approach

```
┌─────────────────────────────────────────────────────────────────┐
│                    TESTING PYRAMID                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│                         🔺                                       │
│                        /  \                                      │
│                       /    \                                     │
│                      / E2E  \                                    │
│                     /  Tests \                                   │
│                    /__________\        10 tests (Manual)         │
│                   /            \                                 │
│                  /  Integration \                                │
│                 /     Tests      \                               │
│                /                  \    20 tests (Automated)      │
│               /____________________\                             │
│              /                      \                            │
│             /      Unit Tests        \                           │
│            /                          \                          │
│           /____________________________\  50 tests (Automated)   │
│                                                                 │
│  Total: 80 automated tests + 10 manual test scenarios           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📝 Test Suite Structure

### File: `tests/test_customer_dashboard_access.py`

```python
"""
Comprehensive test suite for customer dashboard access and authentication.

Test Categories:
1. Authentication Tests (15 tests)
2. Token Management Tests (10 tests)
3. Data Access Tests (10 tests)
4. Data Isolation Tests (5 tests)
5. Error Handling Tests (10 tests)

Total: 50 automated unit/integration tests
"""

import pytest
import json
from datetime import datetime, timedelta
from web_portal import server
from database.manager import DatabaseManager


# ============================================================
# FIXTURES
# ============================================================

@pytest.fixture
def app():
    """Create test application"""
    app = server.create_test_app()
    app.config['TESTING'] = True
    return app


@pytest.fixture
def client(app):
    """Create test client"""
    return app.test_client()


@pytest.fixture
def db():
    """Create test database session"""
    with DatabaseManager(testing=True) as db:
        yield db


@pytest.fixture
def test_customer(db):
    """Create test customer in database"""
    from database.models import Customer
    customer = Customer(
        id='CUST-TEST-001',
        email='testcustomer@phins.test',
        name='Test Customer',
        password_hash='hash_value',
        password_salt='salt_value'
    )
    db.customers.create(customer)
    db.commit()
    return customer


@pytest.fixture
def auth_token(client, test_customer):
    """Get authentication token for test customer"""
    response = client.post('/api/login', json={
        'username': test_customer.email,
        'password': 'TestPassword123!'
    })
    return response.json['token']


@pytest.fixture
def expired_token():
    """Create expired authentication token"""
    # Token creation logic with past expiration date
    pass


# ============================================================
# CATEGORY 1: AUTHENTICATION TESTS (15 tests)
# ============================================================

class TestAuthentication:
    """Test authentication and login functionality"""
    
    def test_customer_login_with_valid_credentials(self, client, test_customer):
        """Verify customer can login with valid email and password"""
        response = client.post('/api/login', json={
            'username': test_customer.email,
            'password': 'TestPassword123!'
        })
        assert response.status_code == 200
        assert 'token' in response.json
        assert 'customer_id' in response.json
    
    def test_customer_login_creates_valid_token(self, client, test_customer):
        """CRITICAL: Verify token contains customer_id"""
        response = client.post('/api/login', json={
            'username': test_customer.email,
            'password': 'TestPassword123!'
        })
        data = response.json
        assert data['customer_id'] is not None
        assert data['customer_id'].startswith('CUST-')
        assert data['role'] == 'customer'
    
    def test_customer_login_with_wrong_password(self, client, test_customer):
        """Verify login fails with incorrect password"""
        response = client.post('/api/login', json={
            'username': test_customer.email,
            'password': 'WrongPassword'
        })
        assert response.status_code == 401
        assert 'error' in response.json
    
    def test_customer_login_with_nonexistent_email(self, client):
        """Verify login fails with non-existent email"""
        response = client.post('/api/login', json={
            'username': 'nonexistent@phins.test',
            'password': 'SomePassword123'
        })
        assert response.status_code == 401
        assert 'error' in response.json
    
    def test_customer_login_with_empty_credentials(self, client):
        """Verify login fails with empty credentials"""
        response = client.post('/api/login', json={
            'username': '',
            'password': ''
        })
        assert response.status_code == 400
        assert 'error' in response.json
    
    def test_customer_id_guarantee_from_database(self, client, db, test_customer):
        """Verify customer_id extracted from database customer record"""
        response = client.post('/api/login', json={
            'username': test_customer.email,
            'password': 'TestPassword123!'
        })
        assert response.json['customer_id'] == test_customer.id
    
    def test_customer_id_guarantee_from_in_memory(self, client, monkeypatch):
        """Verify customer_id recovery from in-memory CUSTOMERS dict"""
        # Simulate database unavailable
        def mock_db_fail(*args, **kwargs):
            raise Exception("Database unavailable")
        
        monkeypatch.setattr('database.manager.DatabaseManager.__enter__', mock_db_fail)
        
        # Add customer to in-memory dict
        from web_portal.server import CUSTOMERS
        CUSTOMERS['CUST-MEMORY-001'] = {
            'id': 'CUST-MEMORY-001',
            'email': 'memory@phins.test',
            'password_hash': 'hash',
            'password_salt': 'salt'
        }
        
        response = client.post('/api/login', json={
            'username': 'memory@phins.test',
            'password': 'TestPassword123!'
        })
        
        assert response.json.get('customer_id') == 'CUST-MEMORY-001'
    
    def test_customer_id_auto_generation_as_last_resort(self, client, monkeypatch):
        """CRITICAL: Verify customer_id auto-generated if all sources fail"""
        # Simulate all sources unavailable
        def mock_all_fail(*args, **kwargs):
            return None
        
        # Test that customer_id is still generated
        # This is the GUARANTEE that prevents 403 errors
        pass
    
    # ... additional authentication tests


# ============================================================
# CATEGORY 2: TOKEN MANAGEMENT TESTS (10 tests)
# ============================================================

class TestTokenManagement:
    """Test token creation, validation, and expiration"""
    
    def test_token_stored_in_session(self, client, auth_token):
        """Verify token is properly stored in session"""
        pass
    
    def test_token_signature_validation(self, client):
        """Verify invalid token signature is rejected"""
        fake_token = "phins_fakepayload.fakesignature"
        response = client.get('/api/customer/dashboard', headers={
            'Authorization': f'Bearer {fake_token}'
        })
        assert response.status_code == 401
    
    def test_token_expiration_handling(self, client, expired_token):
        """Verify expired tokens are rejected"""
        response = client.get('/api/customer/dashboard', headers={
            'Authorization': f'Bearer {expired_token}'
        })
        assert response.status_code == 401
        assert 'expired' in response.json.get('error', '').lower()
    
    def test_token_refresh_mechanism(self, client, auth_token):
        """Verify token can be refreshed before expiration"""
        pass
    
    # ... additional token management tests


# ============================================================
# CATEGORY 3: DATA ACCESS TESTS (10 tests)
# ============================================================

class TestDataAccess:
    """Test customer dashboard data access"""
    
    def test_dashboard_endpoint_requires_auth(self, client):
        """Verify dashboard endpoint requires authentication"""
        response = client.get('/api/customer/dashboard')
        assert response.status_code in [401, 403]
    
    def test_dashboard_returns_customer_data(self, client, auth_token):
        """Verify dashboard returns correct customer data structure"""
        response = client.get('/api/customer/dashboard', headers={
            'Authorization': f'Bearer {auth_token}'
        })
        assert response.status_code == 200
        data = response.json
        assert 'customer' in data
        assert 'policies' in data
        assert 'claims' in data
        assert 'bills' in data
        assert 'summary' in data
    
    def test_dashboard_customer_profile_complete(self, client, auth_token, test_customer):
        """Verify customer profile data is complete"""
        response = client.get('/api/customer/dashboard', headers={
            'Authorization': f'Bearer {auth_token}'
        })
        customer = response.json['customer']
        assert customer['id'] == test_customer.id
        assert customer['email'] == test_customer.email
        assert customer['name'] == test_customer.name
        assert 'created_date' in customer
    
    def test_dashboard_policies_filtered_by_customer(self, client, auth_token, test_customer):
        """Verify policies are filtered by customer_id"""
        response = client.get('/api/customer/dashboard', headers={
            'Authorization': f'Bearer {auth_token}'
        })
        policies = response.json['policies']
        for policy in policies:
            assert policy['customer_id'] == test_customer.id
    
    def test_dashboard_summary_stats_accurate(self, client, auth_token):
        """Verify summary statistics are calculated correctly"""
        response = client.get('/api/customer/dashboard', headers={
            'Authorization': f'Bearer {auth_token}'
        })
        summary = response.json['summary']
        assert 'active_policies_count' in summary
        assert 'open_claims_count' in summary
        assert 'outstanding_bills_amount' in summary
        assert 'total_coverage' in summary
        
        # Verify counts match actual data
        policies = response.json['policies']
        active_count = len([p for p in policies if p['status'] == 'Active'])
        assert summary['active_policies_count'] == active_count
    
    # ... additional data access tests


# ============================================================
# CATEGORY 4: DATA ISOLATION TESTS (5 tests)
# ============================================================

class TestDataIsolation:
    """CRITICAL: Test customer data isolation"""
    
    def test_customers_cannot_see_each_other_data(self, client, db):
        """CRITICAL: Verify customers cannot access each other's data"""
        # Create two customers
        customer1 = create_test_customer(db, 'CUST-ISOLATION-001', 'customer1@test.com')
        customer2 = create_test_customer(db, 'CUST-ISOLATION-002', 'customer2@test.com')
        
        # Login as customer 1
        token1 = login_customer(client, customer1.email)
        
        # Get customer 1 data
        response1 = client.get('/api/customer/dashboard', headers={
            'Authorization': f'Bearer {token1}'
        })
        data1 = response1.json
        
        # Login as customer 2
        token2 = login_customer(client, customer2.email)
        
        # Get customer 2 data
        response2 = client.get('/api/customer/dashboard', headers={
            'Authorization': f'Bearer {token2}'
        })
        data2 = response2.json
        
        # Verify isolation
        assert data1['customer']['id'] != data2['customer']['id']
        assert data1['customer']['email'] != data2['customer']['email']
        
        # Verify no cross-contamination of policies
        policy_ids_1 = [p['id'] for p in data1['policies']]
        policy_ids_2 = [p['id'] for p in data2['policies']]
        assert len(set(policy_ids_1) & set(policy_ids_2)) == 0
    
    def test_customer_cannot_access_with_another_customer_id(self, client, db):
        """Verify customer cannot forge customer_id in request"""
        pass
    
    def test_admin_can_access_all_customer_data(self, client, db):
        """Verify admin role can access any customer's data"""
        pass
    
    # ... additional isolation tests


# ============================================================
# CATEGORY 5: ERROR HANDLING TESTS (10 tests)
# ============================================================

class TestErrorHandling:
    """Test error handling and recovery"""
    
    def test_database_connection_failure_recovery(self, client, monkeypatch):
        """Verify system handles database connection failures gracefully"""
        def mock_db_connection_fail(*args, **kwargs):
            raise Exception("Database connection failed")
        
        monkeypatch.setattr('database.manager.DatabaseManager.__enter__', mock_db_connection_fail)
        
        # Login should still work with fallback
        response = client.post('/api/login', json={
            'username': 'customer@example.com',
            'password': 'password123'
        })
        # Should either succeed with fallback or give clear error
        assert response.status_code in [200, 503]
        if response.status_code == 200:
            data = response.json
            assert 'customer_id' in data
            assert data['customer_id'] is not None
    
    def test_api_timeout_handling(self, client, auth_token, monkeypatch):
        """Verify timeout errors are handled gracefully"""
        pass
    
    def test_network_error_handling(self, client):
        """Verify network errors return user-friendly messages"""
        pass
    
    def test_invalid_session_redirect_to_login(self, client):
        """Verify invalid session redirects to login page"""
        pass
    
    def test_server_error_display_to_user(self, client, monkeypatch):
        """Verify 500 errors display friendly message"""
        pass
    
    # ... additional error handling tests


# ============================================================
# PERFORMANCE TESTS
# ============================================================

class TestPerformance:
    """Test performance and caching"""
    
    def test_dashboard_load_time_under_2_seconds(self, client, auth_token):
        """Verify dashboard loads in < 2 seconds"""
        import time
        start = time.time()
        response = client.get('/api/customer/dashboard', headers={
            'Authorization': f'Bearer {auth_token}'
        })
        elapsed = time.time() - start
        
        assert response.status_code == 200
        assert elapsed < 2.0
    
    def test_dashboard_api_response_time_under_500ms(self, client, auth_token):
        """Verify API responds in < 500ms"""
        import time
        start = time.time()
        response = client.get('/api/customer/dashboard', headers={
            'Authorization': f'Bearer {auth_token}'
        })
        elapsed = time.time() - start
        
        assert response.status_code == 200
        assert elapsed < 0.5
    
    def test_caching_reduces_database_queries(self, client, auth_token, db):
        """Verify caching reduces redundant database queries"""
        pass


# ============================================================
# INTEGRATION TESTS
# ============================================================

def test_complete_customer_journey(client, db):
    """End-to-end test: Registration → Login → Dashboard → Action"""
    
    # Step 1: Register new customer
    register_response = client.post('/api/customer/register', json={
        'email': 'journey@test.com',
        'password': 'SecurePass123!',
        'name': 'Journey Customer',
        'phone': '+1-555-9999'
    })
    assert register_response.status_code == 201
    
    # Step 2: Login
    login_response = client.post('/api/login', json={
        'username': 'journey@test.com',
        'password': 'SecurePass123!'
    })
    assert login_response.status_code == 200
    token = login_response.json['token']
    customer_id = login_response.json['customer_id']
    assert customer_id is not None
    
    # Step 3: Access dashboard
    dashboard_response = client.get('/api/customer/dashboard', headers={
        'Authorization': f'Bearer {token}'
    })
    assert dashboard_response.status_code == 200
    dashboard_data = dashboard_response.json
    assert dashboard_data['customer']['id'] == customer_id
    
    # Step 4: Verify empty state (new customer has no policies)
    assert len(dashboard_data['policies']) == 0
    assert dashboard_data['summary']['active_policies_count'] == 0


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def create_test_customer(db, customer_id, email):
    """Helper to create test customer"""
    from database.models import Customer
    customer = Customer(
        id=customer_id,
        email=email,
        name=f'Test Customer {customer_id}',
        password_hash='test_hash',
        password_salt='test_salt'
    )
    db.customers.create(customer)
    db.commit()
    return customer


def login_customer(client, email):
    """Helper to login customer and get token"""
    response = client.post('/api/login', json={
        'username': email,
        'password': 'TestPassword123!'
    })
    return response.json['token']
```

---

## 🧪 Manual Testing Scenarios

### Scenario 1: New Customer Registration & First Login

```
Steps:
1. Navigate to /register.html
2. Fill out registration form:
   - Email: newcustomer@test.com
   - Password: TestPass123!
   - Name: New Customer
   - Phone: +1-555-1234
3. Click "Register"
4. Verify registration success message
5. Redirected to login page
6. Login with same credentials
7. Verify redirect to customer-dashboard.html
8. Verify dashboard loads without errors
9. Verify empty state messages (no policies, claims, bills)
10. Verify customer name displayed in header

Expected Results:
✓ Registration successful
✓ Login successful with customer_id in token
✓ Dashboard loads in < 2 seconds
✓ No JavaScript errors in console
✓ Customer profile displayed correctly
✓ Empty state messages shown
```

### Scenario 2: Existing Customer Login & Data Display

```
Steps:
1. Navigate to /login.html
2. Login with existing customer:
   - Email: existing@test.com
   - Password: ExistingPass123!
3. Verify redirect to customer-dashboard.html
4. Verify dashboard loads
5. Check policies section
6. Check claims section
7. Check bills section
8. Verify all data belongs to this customer

Expected Results:
✓ Login successful
✓ Dashboard loads with data
✓ Policies displayed (if any)
✓ Claims displayed (if any)
✓ Bills displayed (if any)
✓ Summary stats match data counts
✓ No 403 errors
```

### Scenario 3: Database Connection Failure

```
Steps:
1. Stop PostgreSQL database
2. Attempt customer login
3. Observe behavior

Expected Results:
✓ Login still works (fallback to in-memory)
✓ customer_id still present in token
✓ Clear error message if database features unavailable
✓ Dashboard loads with available data
✓ Graceful degradation, not complete failure
```

### Scenario 4: Session Expiration

```
Steps:
1. Login as customer
2. Navigate to dashboard
3. Wait for token to expire (or manually expire it)
4. Try to access dashboard data
5. Observe behavior

Expected Results:
✓ Expired token detected
✓ User-friendly error message
✓ Automatic redirect to login page
✓ Login message: "Session expired, please login again"
```

### Scenario 5: Mobile Responsiveness

```
Steps:
1. Login on mobile device (or use Chrome DevTools mobile emulation)
2. Access customer-dashboard.html
3. Test all features:
   - Profile section
   - Stats cards
   - Policies section
   - Claims section
   - Bills section
   - Navigation
   - Logout

Expected Results:
✓ Dashboard responsive on mobile
✓ All elements visible and usable
✓ Touch interactions work
✓ No horizontal scrolling
✓ Images/icons appropriately sized
✓ Performance acceptable on mobile network
```

### Scenario 6: Browser Compatibility

Test on:
- [ ] Chrome (latest)
- [ ] Firefox (latest)
- [ ] Safari (latest)
- [ ] Edge (latest)
- [ ] Mobile Safari (iOS)
- [ ] Chrome Mobile (Android)

Expected Results:
✓ Dashboard works on all browsers
✓ No visual glitches
✓ JavaScript functions correctly
✓ Performance acceptable
```

### Scenario 7: Data Isolation Verification

```
Steps:
1. Create two customer accounts
2. Login as Customer A
3. Note policies, claims, bills
4. Logout
5. Login as Customer B
6. Note policies, claims, bills
7. Verify no overlap

Expected Results:
✓ Customer A sees only their data
✓ Customer B sees only their data
✓ No cross-contamination
✓ Different customer_ids in tokens
```

---

## 📊 Success Criteria

### Automated Tests

- [ ] **80+ tests written** (50 unit + 20 integration + 10 performance)
- [ ] **100% pass rate** on all tests
- [ ] **>80% code coverage** on new dashboard code
- [ ] **<2s execution time** for full test suite

### Manual Tests

- [ ] **All 7 scenarios** executed successfully
- [ ] **All 6 browsers** tested and working
- [ ] **Mobile devices** (iOS and Android) tested
- [ ] **No critical bugs** found in manual testing

### Performance Benchmarks

- [ ] Dashboard load time **< 2 seconds**
- [ ] API response time **< 500ms**
- [ ] JavaScript execution time **< 100ms**
- [ ] No memory leaks after **1 hour of use**

---

## 🚀 Testing Timeline

### Development Phase (Days 3-5)

```
Day 3: Write unit tests as code is developed
  ├─ Authentication tests
  ├─ Token management tests
  └─ Data access tests

Day 4: Write integration tests
  ├─ Complete customer journey
  ├─ Database interaction tests
  └─ Error handling tests

Day 5: Manual testing & bug fixes
  ├─ Execute all 7 manual scenarios
  ├─ Fix bugs found
  └─ Re-run automated tests
```

### Staging Phase (Days 6-7)

```
Day 6: Staging deployment tests
  ├─ Smoke tests on staging
  ├─ Performance baseline
  └─ Security scan

Day 7: Internal team testing
  ├─ 5-10 internal users
  ├─ Collect feedback
  └─ Fix critical issues
```

### Production Phase (Days 8+)

```
Days 8-15: Monitor production metrics
  ├─ Error rates
  ├─ Performance metrics
  ├─ User feedback
  └─ Support tickets
```

---

## ✅ Testing Checklist

### Before Implementation
- [ ] Test suite structure defined
- [ ] Test fixtures prepared
- [ ] Test data seeded
- [ ] Testing tools installed

### During Implementation
- [ ] Write tests alongside code
- [ ] Run tests frequently (TDD)
- [ ] Fix failing tests immediately
- [ ] Maintain >80% code coverage

### Before Staging Deployment
- [ ] All 80+ automated tests passing
- [ ] Manual testing scenarios completed
- [ ] Performance benchmarks met
- [ ] Security scan passed
- [ ] No critical bugs

### Before Production Rollout
- [ ] Staging tests all passed
- [ ] Internal team validated
- [ ] Documentation complete
- [ ] Rollback procedure tested
- [ ] Monitoring configured

---

**Status:** 📋 **TESTING STRATEGY COMPLETE** - Ready for implementation

Once implementation begins, this test suite will be created and executed to ensure quality and reliability of the new customer dashboard.
