"""
Database Seed Data

Populates the database with default users and sample data.
"""

import hashlib
import secrets
from datetime import datetime
import logging

from database import get_db_session, init_database
from database.repositories import UserRepository

logger = logging.getLogger(__name__)


def hash_password(password: str) -> dict:
    """Hash password using PBKDF2"""
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return {'hash': hashed.hex(), 'salt': salt}


def seed_default_users(session=None):
    """Create default system users"""
    should_close = False
    if session is None:
        session = get_db_session()
        should_close = True
    
    try:
        user_repo = UserRepository(session)
        
        # Default users
        default_users = [
            {
                'username': 'admin',
                'password': 'admin123',
                'role': 'admin',
                'name': 'Admin User',
                'email': 'admin@phins.ai'
            },
            {
                'username': 'underwriter',
                'password': 'under123',
                'role': 'underwriter',
                'name': 'John Underwriter',
                'email': 'underwriter@phins.ai'
            },
            {
                'username': 'claims_adjuster',
                'password': 'claims123',
                'role': 'claims',
                'name': 'Jane Claims',
                'email': 'claims@phins.ai'
            },
            {
                'username': 'accountant',
                'password': 'acct123',
                'role': 'accountant',
                'name': 'Bob Accountant',
                'email': 'accountant@phins.ai'
            }
        ]
        
        for user_data in default_users:
            # Check if user already exists
            existing_user = user_repo.get_by_username(user_data['username'])
            if existing_user:
                logger.info(f"User '{user_data['username']}' already exists, skipping...")
                continue
            
            # Hash password
            password_hash = hash_password(user_data['password'])
            
            # Create user
            user_repo.create(
                username=user_data['username'],
                password_hash=password_hash['hash'],
                password_salt=password_hash['salt'],
                role=user_data['role'],
                name=user_data['name'],
                email=user_data['email'],
                active=True
            )
            logger.info(f"Created user: {user_data['username']} (Role: {user_data['role']})")
        
        logger.info("Default users seeded successfully")
        
    except Exception as e:
        logger.error(f"Error seeding users: {e}")
        if should_close:
            session.rollback()
        raise
    finally:
        if should_close:
            session.close()


def seed_sample_data(session=None):
    """Create sample customers, policies, etc. for testing"""
    should_close = False
    if session is None:
        session = get_db_session()
        should_close = True
    
    try:
        from database.repositories import CustomerRepository, PolicyRepository
        from datetime import timedelta
        
        customer_repo = CustomerRepository(session)
        policy_repo = PolicyRepository(session)
        
        # Sample customer
        sample_customer = customer_repo.find_one_by(email='demo@example.com')
        if not sample_customer:
            sample_customer = customer_repo.create(
                id='CUST-10001',
                name='John Demo',
                first_name='John',
                last_name='Demo',
                email='demo@example.com',
                phone='+1-555-0100',
                dob='1985-06-15',
                age=38,
                gender='male',
                address='123 Main St',
                city='San Francisco',
                state='CA',
                zip='94102',
                occupation='Software Engineer'
            )
            logger.info(f"Created sample customer: {sample_customer.id}")
            
            # Sample policy for demo customer
            start_date = datetime.utcnow()
            end_date = start_date + timedelta(days=365)
            
            sample_policy = policy_repo.create(
                id='POL-20231215-1001',
                customer_id=sample_customer.id,
                type='life',
                coverage_amount=500000.0,
                annual_premium=1200.0,
                monthly_premium=100.0,
                status='active',
                risk_score='low',
                start_date=start_date,
                end_date=end_date,
                uw_status='approved'
            )
            logger.info(f"Created sample policy: {sample_policy.id}")
        else:
            logger.info("Sample customer already exists, skipping...")
        
        logger.info("Sample data seeded successfully")
        
    except Exception as e:
        logger.error(f"Error seeding sample data: {e}")
        if should_close:
            session.rollback()
        raise
    finally:
        if should_close:
            session.close()


def seed_database(include_sample_data: bool = False):
    """
    Main seed function to populate database.
    
    Args:
        include_sample_data: Whether to include sample customers/policies
    """
    logger.info("Starting database seeding...")
    
    # Initialize database schema first
    try:
        init_database()
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        return
    
    # Seed users
    try:
        seed_default_users()
    except Exception as e:
        logger.error(f"Failed to seed users: {e}")
    
    # Optionally seed sample data
    if include_sample_data:
        try:
            seed_sample_data()
        except Exception as e:
            logger.error(f"Failed to seed sample data: {e}")
    
    logger.info("Database seeding completed!")


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Seed with sample data when run directly
    seed_database(include_sample_data=True)
