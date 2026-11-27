"""
Database Functionality Tests

Tests the database layer, repositories, and integration with the server.
"""

import os
import sys
import pytest
from datetime import datetime, timedelta, timezone

# Set up path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Use SQLite for testing
os.environ['USE_SQLITE'] = '1'
os.environ['SQLITE_PATH'] = '/tmp/test_phins_pytest.db'


def test_database_models():
    """Test that database models can be imported and instantiated"""
    from database.models import Customer, Policy, Claim, User
    
    # Test Customer model
    customer = Customer(
        id='TEST-CUST-001',
        name='Test Customer',
        email='test@example.com'
    )
    assert customer.id == 'TEST-CUST-001'
    assert customer.name == 'Test Customer'
    
    # Test Policy model
    policy = Policy(
        id='TEST-POL-001',
        customer_id='TEST-CUST-001',
        type='life',
        coverage_amount=100000.0,
        annual_premium=1200.0
    )
    assert policy.type == 'life'
    
    # Test Claim model
    claim = Claim(
        id='TEST-CLM-001',
        policy_id='TEST-POL-001',
        customer_id='TEST-CUST-001',
        claimed_amount=5000.0
    )
    assert claim.claimed_amount == 5000.0


def test_database_initialization():
    """Test database initialization"""
    from database import init_database, check_database_connection, get_database_info
    
    # Initialize database
    init_database()
    
    # Check connection
    assert check_database_connection() == True
    
    # Get database info
    info = get_database_info()
    assert info['database_type'] == 'SQLite'
    assert info['connection_ok'] == True


def test_customer_repository():
    """Test customer repository operations"""
    from database import init_database, get_db_session
    from database.repositories import CustomerRepository
    
    # Initialize
    init_database()
    session = get_db_session()
    
    try:
        repo = CustomerRepository(session)
        
        # Create customer
        customer = repo.create(
            id='TEST-CUST-100',
            name='John Repo Test',
            email='john.repo@test.com',
            phone='+1-555-0100'
        )
        assert customer is not None
        assert customer.id == 'TEST-CUST-100'
        session.commit()
        
        # Get customer
        retrieved = repo.get_by_id('TEST-CUST-100')
        assert retrieved is not None
        assert retrieved.email == 'john.repo@test.com'
        
        # Get by email
        by_email = repo.get_by_email('john.repo@test.com')
        assert by_email is not None
        assert by_email.id == 'TEST-CUST-100'
        
        # Update customer
        updated = repo.update('TEST-CUST-100', phone='+1-555-0200')
        session.commit()
        assert updated.phone == '+1-555-0200'
        
        # Delete customer
        assert repo.delete('TEST-CUST-100') == True
        session.commit()
        assert repo.get_by_id('TEST-CUST-100') is None
        
    finally:
        session.close()


def test_policy_repository():
    """Test policy repository operations"""
    from database import init_database, get_db_session
    from database.repositories import PolicyRepository, CustomerRepository
    
    # Initialize
    init_database()
    session = get_db_session()
    
    try:
        customer_repo = CustomerRepository(session)
        policy_repo = PolicyRepository(session)
        
        # Create customer first
        customer = customer_repo.create(
            id='TEST-CUST-200',
            name='Policy Test Customer',
            email='policy.test@example.com'
        )
        session.commit()
        
        # Create policy
        policy = policy_repo.create(
            id='TEST-POL-200',
            customer_id='TEST-CUST-200',
            type='life',
            coverage_amount=250000.0,
            annual_premium=3000.0,
            status='active'
        )
        assert policy is not None
        session.commit()
        
        # Get policies by customer
        policies = policy_repo.get_by_customer('TEST-CUST-200')
        assert len(policies) >= 1
        assert policies[0].type == 'life'
        
        # Get active policies
        active = policy_repo.get_active_policies()
        assert len(active) >= 1
        
        # Cleanup
        policy_repo.delete('TEST-POL-200')
        customer_repo.delete('TEST-CUST-200')
        session.commit()
        
    finally:
        session.close()


def test_database_manager():
    """Test DatabaseManager high-level API"""
    from database import init_database
    from database.manager import DatabaseManager
    
    init_database()
    
    with DatabaseManager() as db:
        # Create customer
        customer = db.customers.create(
            id='TEST-CUST-300',
            name='Manager Test',
            email='manager@test.com'
        )
        assert customer is not None
        
        # Create policy
        policy = db.policies.create(
            id='TEST-POL-300',
            customer_id='TEST-CUST-300',
            type='health',
            coverage_amount=50000.0,
            annual_premium=800.0
        )
        assert policy is not None
        
        # Query
        retrieved_customer = db.customers.get_by_id('TEST-CUST-300')
        assert retrieved_customer.email == 'manager@test.com'
        
        policies = db.policies.get_by_customer('TEST-CUST-300')
        assert len(policies) >= 1


def test_database_manager_session_persists_claim_status():
    """The public session alias must drive claim updates (post-#603 log bug)."""
    from database import init_database
    from database.manager import DatabaseManager

    init_database()

    with DatabaseManager() as db:
        assert db.session is db._ensure_session()
        customer = db.customers.create(
            id='TEST-CUST-SESS',
            name='Session Persist',
            email='session-persist@test.com',
        )
        assert customer is not None
        policy = db.policies.create(
            id='TEST-POL-SESS',
            customer_id='TEST-CUST-SESS',
            type='health',
            coverage_amount=10000.0,
            annual_premium=100.0,
        )
        assert policy is not None
        claim = db.claims.create(
            id='TEST-CLM-SESS',
            policy_id='TEST-POL-SESS',
            customer_id='TEST-CUST-SESS',
            claimed_amount=250.0,
            status='pending',
        )
        assert claim is not None
        updated = db.claims.update('TEST-CLM-SESS', status='approved', approved_amount=250.0)
        assert updated is not None
        assert updated.status == 'approved'
        assert db.claims.get_by_id('TEST-CLM-SESS').status == 'approved'


def test_user_seeding():
    """Test that default users are seeded correctly"""
    from database import init_database
    from database.seeds import seed_default_users
    from database.manager import DatabaseManager
    
    init_database()
    seed_default_users()
    
    with DatabaseManager() as db:
        # Check that users were created
        admin = db.users.get_by_username('admin')
        assert admin is not None
        assert admin.role == 'admin'
        
        underwriter = db.users.get_by_username('underwriter')
        assert underwriter is not None
        assert underwriter.role == 'underwriter'


def test_datetime_conversion():
    """Test that datetime strings are converted properly"""
    from database.data_access import convert_datetime_strings
    from datetime import datetime
    
    # Test data with datetime strings
    data = {
        'id': 'TEST-001',
        'name': 'Test',
        'created_date': '2025-12-15T10:00:00',
        'start_date': '2025-01-01T00:00:00',
        'some_other_field': 'value'
    }
    
    result = convert_datetime_strings(data)
    
    # Check that datetime strings were converted
    assert isinstance(result['created_date'], datetime)
    assert isinstance(result['start_date'], datetime)
    assert result['some_other_field'] == 'value'  # Non-datetime fields unchanged


def test_database_dict_interface():
    """Test DatabaseDict backward-compatible interface"""
    from database import init_database
    from database.data_access import DatabaseDict
    from datetime import datetime
    
    init_database()
    
    # Create a database dict for customers
    customers = DatabaseDict('customers')
    
    # Test dict-like operations
    customers['TEST-CUST-400'] = {
        'id': 'TEST-CUST-400',
        'name': 'Dict Test',
        'email': 'dict@test.com',
        'created_date': datetime.now(timezone.utc).isoformat()
    }
    
    # Get item
    customer = customers['TEST-CUST-400']
    assert customer['email'] == 'dict@test.com'
    
    # Check contains
    assert 'TEST-CUST-400' in customers
    
    # Get with default
    assert customers.get('NONEXISTENT', None) is None
    
    # Cleanup
    del customers['TEST-CUST-400']
    assert 'TEST-CUST-400' not in customers


_KERNEL_PIN = {
    'pricing_source': 'pricing_kernel',
    'integrity_hash': 'pin-hash-1',
    'risk_premium_annual': 1960.15,
    'savings_premium_annual': 980.08,
    'expense_loading_annual': 294.02,
    'profit_margin_annual': 323.43,
    'savings_addon': 'balanced',
}


def _pin_policy_store(policy_id, customer_id):
    from database import init_database
    from database.data_access import DatabaseDict

    init_database()
    customers = DatabaseDict('customers')
    policies = DatabaseDict('policies')
    if policy_id in policies:
        del policies[policy_id]
    if customer_id not in customers:
        customers[customer_id] = {
            'id': customer_id, 'name': 'Pin Test', 'email': f'{customer_id.lower()}@test.com',
        }
    return customers, policies


def test_policy_kernel_pin_survives_the_database_round_trip():
    """The pin keys are not columns. They are sealed together and read back."""
    customers, policies = _pin_policy_store('TEST-POL-PIN-1', 'TEST-CUST-PIN-1')
    try:
        policies['TEST-POL-PIN-1'] = {
            'id': 'TEST-POL-PIN-1', 'customer_id': 'TEST-CUST-PIN-1', 'type': 'life',
            'coverage_amount': 500000, 'annual_premium': 3557.68, 'monthly_premium': 296.47,
            'status': 'active', **_KERNEL_PIN,
        }
        stored = policies['TEST-POL-PIN-1']
        for key, value in _KERNEL_PIN.items():
            assert stored[key] == value
        assert 'kernel_pin_intact' not in stored

        # A later write that names no pin key keeps the pin.
        policies['TEST-POL-PIN-1'] = {'id': 'TEST-POL-PIN-1', 'status': 'lapsed'}
        stored = policies['TEST-POL-PIN-1']
        assert stored['status'] == 'lapsed'
        assert stored['risk_premium_annual'] == 1960.15

        # One key replaced, one cleared, the rest kept.
        policies['TEST-POL-PIN-1'] = {
            'id': 'TEST-POL-PIN-1', 'underwriting_fee_annual': 120.0, 'savings_addon': None,
        }
        stored = policies['TEST-POL-PIN-1']
        assert stored['underwriting_fee_annual'] == 120.0
        assert stored.get('savings_addon') is None
        assert stored['savings_premium_annual'] == 980.08

        from services.financial_unification_service import resolve_premium_split
        split = resolve_premium_split(296.47, stored)
        assert split['risk_amount'] > 0 and split['savings_amount'] > 0
    finally:
        del policies['TEST-POL-PIN-1']
        del customers['TEST-CUST-PIN-1']


def test_policy_kernel_pin_with_a_bad_checksum_is_withheld_and_not_overwritten():
    import json
    from database.manager import DatabaseManager

    customers, policies = _pin_policy_store('TEST-POL-PIN-2', 'TEST-CUST-PIN-2')
    try:
        policies['TEST-POL-PIN-2'] = {
            'id': 'TEST-POL-PIN-2', 'customer_id': 'TEST-CUST-PIN-2', 'type': 'life',
            'coverage_amount': 500000, 'annual_premium': 3557.68, 'status': 'active', **_KERNEL_PIN,
        }
        with DatabaseManager() as db:
            row = db.policies.get_by_id('TEST-POL-PIN-2')
            document = json.loads(row.kernel_pin)
            document['fields']['savings_premium_annual'] = 3000.00
            tampered = json.dumps(document, sort_keys=True)
            db.policies.update('TEST-POL-PIN-2', kernel_pin=tampered)

        stored = policies['TEST-POL-PIN-2']
        assert stored['kernel_pin_intact'] is False
        assert stored.get('savings_premium_annual') is None
        assert stored.get('risk_premium_annual') is None

        # A write over the broken seal does not replace it.
        policies['TEST-POL-PIN-2'] = {'id': 'TEST-POL-PIN-2', **_KERNEL_PIN}
        with DatabaseManager() as db:
            assert db.policies.get_by_id('TEST-POL-PIN-2').kernel_pin == tampered
        assert policies['TEST-POL-PIN-2']['kernel_pin_intact'] is False
    finally:
        del policies['TEST-POL-PIN-2']
        del customers['TEST-CUST-PIN-2']


def test_database_dict_create_defaults_and_extra_round_trip():
    """U3 dual-path: omitted NOT NULL fields + non-column keys survive."""
    from database import init_database
    from database.data_access import DatabaseDict

    init_database()
    customers = DatabaseDict('customers')
    policies = DatabaseDict('policies')
    cid, pid = 'TEST-CUST-U3-EXTRA', 'TEST-POL-U3-EXTRA'
    for store, key in ((policies, pid), (customers, cid)):
        if key in store:
            del store[key]
    try:
        customers[cid] = {'id': cid, 'name': 'U3 Extra'}  # no email
        assert customers[cid]['email'] == 'test-cust-u3-extra@phins.local'
        policies[pid] = {
            'id': pid,
            'customer_id': cid,
            'annual_premium': 1200.0,
            'risk_premium_annual': 960.0,
            'savings_premium_annual': 240.0,
            'pricing_source': 'pricing_kernel',
            'adl_level': 5,
            'adl_level_source': 'unspecified_baseline',
        }
        stored = policies[pid]
        assert stored['type'] == 'life'
        assert stored['coverage_amount'] == 1200.0
        assert stored['risk_premium_annual'] == 960.0
        assert stored['adl_level'] == 5
        assert stored['adl_level_source'] == 'unspecified_baseline'
        # In-place top-level mutation write-throughs like an in-memory dict.
        policies[pid]['adl_level'] = 3
        assert policies[pid]['adl_level'] == 3
    finally:
        if pid in policies:
            del policies[pid]
        if cid in customers:
            del customers[cid]


def test_database_dict_create_fails_closed_without_customer_id():
    from database import init_database
    from database.data_access import DatabaseDict
    import pytest as _pytest

    init_database()
    policies = DatabaseDict('policies')
    pid = 'TEST-POL-U3-FAILCLOSED'
    if pid in policies:
        del policies[pid]
    with _pytest.raises(RuntimeError, match='create failed'):
        policies[pid] = {
            'id': pid,
            'type': 'life',
            'coverage_amount': 1000.0,
            'annual_premium': 100.0,
            # customer_id missing → FK / NOT NULL depending on backend
        }


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
