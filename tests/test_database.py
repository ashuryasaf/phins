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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
