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
    """Create sample customers, policies, underwriting, and billing for demo/testing"""
    should_close = False
    if session is None:
        session = get_db_session()
        should_close = True
    
    try:
        from database.repositories import (
            CustomerRepository, PolicyRepository, 
            UnderwritingRepository, BillingRepository
        )
        from datetime import timedelta
        
        customer_repo = CustomerRepository(session)
        policy_repo = PolicyRepository(session)
        underwriting_repo = UnderwritingRepository(session)
        billing_repo = BillingRepository(session)
        
        now = datetime.utcnow()
        
        # =================================================================
        # PRIMARY TEST ACCOUNT: asaf@assurance.co.il
        # =================================================================
        primary_customer = customer_repo.find_one_by(email='asaf@assurance.co.il')
        if not primary_customer:
            pwd = hash_password('Assurance2024!')
            primary_customer = customer_repo.create(
                id='CUST-ASAF-001',
                name='Asaf Assurance',
                first_name='Asaf',
                last_name='Assurance',
                email='asaf@assurance.co.il',
                phone='+972-50-1234567',
                dob='1985-03-15',
                age=39,
                gender='male',
                address='123 Insurance Blvd',
                city='Tel Aviv',
                state='Israel',
                zip='6100001',
                occupation='Business Owner',
                password_hash=pwd['hash'],
                password_salt=pwd['salt'],
                portal_active=True
            )
            logger.info(f"Created primary customer: {primary_customer.email}")
            
            # Create policies for primary customer
            policies_data = [
                {
                    'id': 'POL-ASAF-LIFE-001',
                    'type': 'life',
                    'coverage_amount': 1000000.0,
                    'annual_premium': 12000.0,
                    'monthly_premium': 1000.0,
                    'status': 'active',
                    'risk_score': 'low'
                },
                {
                    'id': 'POL-ASAF-HEALTH-001',
                    'type': 'health',
                    'coverage_amount': 500000.0,
                    'annual_premium': 6000.0,
                    'monthly_premium': 500.0,
                    'status': 'active',
                    'risk_score': 'medium'
                },
                {
                    'id': 'POL-ASAF-AUTO-001',
                    'type': 'auto',
                    'coverage_amount': 100000.0,
                    'annual_premium': 2400.0,
                    'monthly_premium': 200.0,
                    'status': 'active',
                    'risk_score': 'low'
                }
            ]
            
            for pol_data in policies_data:
                policy = policy_repo.create(
                    id=pol_data['id'],
                    customer_id=primary_customer.id,
                    type=pol_data['type'],
                    coverage_amount=pol_data['coverage_amount'],
                    annual_premium=pol_data['annual_premium'],
                    monthly_premium=pol_data['monthly_premium'],
                    status=pol_data['status'],
                    risk_score=pol_data['risk_score'],
                    start_date=now,
                    end_date=now + timedelta(days=365),
                    approval_date=now
                )
                logger.info(f"Created policy: {policy.id}")
                
                # Create bill for active policy
                if pol_data['status'] == 'active':
                    bill = billing_repo.create(
                        id=f"BILL-{pol_data['id'].replace('POL-', '')}",
                        policy_id=policy.id,
                        customer_id=primary_customer.id,
                        amount=pol_data['monthly_premium'],
                        amount_paid=0.0,
                        status='outstanding',
                        due_date=now + timedelta(days=30)
                    )
                    logger.info(f"Created bill: {bill.id}")
        else:
            logger.info(f"Primary customer {primary_customer.email} already exists, skipping...")
        
        # =================================================================
        # ADDITIONAL TEST CUSTOMERS WITH PENDING UNDERWRITING
        # =================================================================
        additional_customers = [
            {
                'id': 'CUST-TEST-100',
                'name': 'Sarah Cohen',
                'email': 'sarah.cohen@test.com',
                'policy_type': 'life',
                'coverage': 750000
            },
            {
                'id': 'CUST-TEST-101',
                'name': 'David Levy',
                'email': 'david.levy@test.com',
                'policy_type': 'health',
                'coverage': 300000
            },
            {
                'id': 'CUST-TEST-102',
                'name': 'Rachel Green',
                'email': 'rachel.green@test.com',
                'policy_type': 'property',
                'coverage': 500000
            }
        ]
        
        for cust_data in additional_customers:
            existing = customer_repo.find_one_by(email=cust_data['email'])
            if existing:
                logger.info(f"Customer {cust_data['email']} already exists, skipping...")
                continue
            
            pwd = hash_password('Test123!')
            customer = customer_repo.create(
                id=cust_data['id'],
                name=cust_data['name'],
                email=cust_data['email'],
                phone=f"+1-555-{hash(cust_data['email']) % 10000:04d}",
                password_hash=pwd['hash'],
                password_salt=pwd['salt'],
                portal_active=True
            )
            logger.info(f"Created customer: {customer.email}")
            
            # Create pending policy
            pol_id = f"POL-{cust_data['id'].replace('CUST-', '')}"
            uw_id = f"UW-{cust_data['id'].replace('CUST-', '')}"
            
            policy = policy_repo.create(
                id=pol_id,
                customer_id=customer.id,
                type=cust_data['policy_type'],
                coverage_amount=cust_data['coverage'],
                annual_premium=cust_data['coverage'] * 0.012,
                monthly_premium=cust_data['coverage'] * 0.001,
                status='pending_underwriting',
                risk_score='medium',
                underwriting_id=uw_id,
                start_date=now,
                end_date=now + timedelta(days=365)
            )
            logger.info(f"Created pending policy: {policy.id}")
            
            # Create underwriting application
            uw_app = underwriting_repo.create(
                id=uw_id,
                policy_id=pol_id,
                customer_id=customer.id,
                status='pending',
                risk_assessment='medium',
                medical_exam_required=False,
                submitted_date=now
            )
            logger.info(f"Created underwriting application: {uw_app.id}")
        
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
