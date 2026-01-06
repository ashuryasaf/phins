"""
Database Seed Data

Populates the database with default users and sample data.
"""

import hashlib
import secrets
import random
from datetime import datetime, timedelta
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
        
        # Default users (password: PDadmin123@ for all system accounts)
        default_users = [
            {
                'username': 'admin',
                'password': 'PDadmin123@',
                'role': 'admin',
                'name': 'Admin User',
                'email': 'admin@phins.ai'
            },
            {
                'username': 'actuary',
                'password': 'PDadmin123@',
                'role': 'actuary',
                'name': 'Actuary User',
                'email': 'actuary@phins.ai'
            },
            {
                'username': 'supplier',
                'password': 'PDadmin123@',
                'role': 'supplier',
                'name': 'Supplier User',
                'email': 'supplier@phins.ai'
            },
            {
                'username': 'underwriter',
                'password': 'PDadmin123@',
                'role': 'underwriter',
                'name': 'John Underwriter',
                'email': 'underwriter@phins.ai'
            },
            {
                'username': 'claims_adjuster',
                'password': 'PDadmin123@',
                'role': 'claims',
                'name': 'Jane Claims',
                'email': 'claims@phins.ai'
            },
            {
                'username': 'accountant',
                'password': 'PDadmin123@',
                'role': 'accountant',
                'name': 'Bob Accountant',
                'email': 'accountant@phins.ai'
            },
            # Primary customer account (links to CUST-ASAF-001 in customers table)
            # NOTE: Password must match the one in seed_sample_data for customers table
            {
                'username': 'asaf@assurance.co.il',
                'password': 'Assurance2024!',
                'role': 'customer',
                'name': 'Asaf Assurance',
                'email': 'asaf@assurance.co.il'
            },
            # Admin account for asaf@phins.ai - PERSISTENT ACCOUNT
            # This account is always seeded and should never be deleted
            {
                'username': 'asaf@phins.ai',
                'password': 'PHINSadmin2024!',
                'role': 'admin',
                'name': 'Asaf PHINS',
                'email': 'asaf@phins.ai'
            },
            # Customer account for efrat@phins.ai - PERSISTENT ACCOUNT
            {
                'username': 'efrat@phins.ai',
                'password': 'PHINScustomer2024!',
                'role': 'customer',
                'name': 'Efrat PHINS',
                'email': 'efrat@phins.ai'
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
            UnderwritingRepository, BillingRepository,
            ClaimRepository
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
        # Import in-memory data structures for primary customer sync
        try:
            from web_portal.server import CUSTOMERS, POLICIES, UNDERWRITING_APPLICATIONS, BILLING, CLAIMS
            sync_primary_to_memory = True
        except ImportError:
            sync_primary_to_memory = False
            logger.warning("Could not import in-memory data structures for primary customer")
        
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
            
            # Sync primary customer to memory
            if sync_primary_to_memory:
                CUSTOMERS['CUST-ASAF-001'] = {
                    'id': 'CUST-ASAF-001',
                    'name': 'Asaf Assurance',
                    'email': 'asaf@assurance.co.il',
                    'phone': '+972-50-1234567',
                    'date_of_birth': '1985-03-15',
                    'created_date': now.isoformat()
                }
            
            # Initialize health wallet with $20,000 deposit (as per user's test data)
            from web_portal.server import HEALTH_WALLETS
            HEALTH_WALLETS['CUST-ASAF-001'] = {
                'customer_id': 'CUST-ASAF-001',
                'balance': 20000.00,
                'monthly_deposit': 500.00,
                'transactions': [
                    {
                        'id': 'TXN-SEED-001',
                        'type': 'deposit',
                        'amount': 20000.00,
                        'payment_method': 'bank_transfer',
                        'timestamp': datetime.utcnow().isoformat(),
                        'description': 'Initial deposit via billing',
                        'balance_after': 20000.00
                    }
                ],
                'created_at': datetime.utcnow().isoformat()
            }
            logger.info(f"Created health wallet with $20,000 balance for CUST-ASAF-001")
            
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
                
                # Sync policy to memory
                if sync_primary_to_memory:
                    POLICIES[pol_data['id']] = {
                        'id': pol_data['id'],
                        'customer_id': 'CUST-ASAF-001',
                        'type': pol_data['type'],
                        'coverage_amount': pol_data['coverage_amount'],
                        'annual_premium': pol_data['annual_premium'],
                        'monthly_premium': pol_data['monthly_premium'],
                        'status': pol_data['status'],
                        'risk_score': pol_data['risk_score'],
                        'start_date': now.isoformat(),
                        'end_date': (now + timedelta(days=365)).isoformat(),
                        'approval_date': now.isoformat(),
                        'created_date': now.isoformat(),
                        'updated_date': now.isoformat()
                    }
                
                # Create bill for active policy
                if pol_data['status'] == 'active':
                    bill_id = f"BILL-{pol_data['id'].replace('POL-', '')}"
                    bill = billing_repo.create(
                        id=bill_id,
                        policy_id=policy.id,
                        customer_id=primary_customer.id,
                        amount=pol_data['monthly_premium'],
                        amount_paid=0.0,
                        status='outstanding',
                        due_date=now + timedelta(days=30)
                    )
                    logger.info(f"Created bill: {bill.id}")
                    
                    # Sync bill to memory
                    if sync_primary_to_memory:
                        BILLING[bill_id] = {
                            'id': bill_id,
                            'policy_id': pol_data['id'],
                            'customer_id': 'CUST-ASAF-001',
                            'amount': pol_data['monthly_premium'],
                            'amount_paid': 0.0,
                            'status': 'outstanding',
                            'due_date': (now + timedelta(days=30)).isoformat(),
                            'paid_date': None,
                            'payment_method': None,
                            'transaction_id': None,
                            'late_fee': 0.0,
                            'created_date': now.isoformat(),
                            'updated_date': now.isoformat()
                        }
            
            # Create sample claims for the primary customer
            claim_repo = ClaimRepository(session)
            sample_claims = [
                {
                    'id': 'CLM-ASAF-001',
                    'policy_id': 'POL-ASAF-HEALTH-001',
                    'type': 'Medical',
                    'description': 'Emergency room visit for chest pain - cardiac evaluation',
                    'claimed_amount': 15000.00,
                    'approved_amount': 15000.00,
                    'status': 'Paid'
                },
                {
                    'id': 'CLM-ASAF-002',
                    'policy_id': 'POL-ASAF-HEALTH-001',
                    'type': 'Prescription',
                    'description': 'Monthly prescription medications - cardiovascular',
                    'claimed_amount': 850.00,
                    'approved_amount': 850.00,
                    'status': 'Paid'
                },
                {
                    'id': 'CLM-ASAF-003',
                    'policy_id': 'POL-ASAF-AUTO-001',
                    'type': 'Collision',
                    'description': 'Fender bender accident - rear bumper damage repair',
                    'claimed_amount': 3500.00,
                    'approved_amount': 3200.00,
                    'status': 'Paid'
                },
                {
                    'id': 'CLM-ASAF-004',
                    'policy_id': 'POL-ASAF-HEALTH-001',
                    'type': 'Dental',
                    'description': 'Root canal treatment and crown placement',
                    'claimed_amount': 2800.00,
                    'status': 'Pending'
                },
                {
                    'id': 'CLM-ASAF-005',
                    'policy_id': 'POL-ASAF-LIFE-001',
                    'type': 'Disability',
                    'description': 'Temporary disability claim - work injury recovery',
                    'claimed_amount': 45000.00,
                    'status': 'Under Review'
                }
            ]
            
            for claim_data in sample_claims:
                try:
                    filed_date = now - timedelta(days=random.randint(1, 30))
                    claim = claim_repo.create(
                        id=claim_data['id'],
                        policy_id=claim_data['policy_id'],
                        customer_id=primary_customer.id,
                        type=claim_data['type'],
                        description=claim_data['description'],
                        claimed_amount=claim_data['claimed_amount'],
                        approved_amount=claim_data.get('approved_amount'),
                        status=claim_data['status'],
                        filed_date=filed_date
                    )
                    logger.info(f"Created claim: {claim.id}")
                    
                    # Sync claim to memory
                    if sync_primary_to_memory:
                        CLAIMS[claim_data['id']] = {
                            'id': claim_data['id'],
                            'policy_id': claim_data['policy_id'],
                            'customer_id': 'CUST-ASAF-001',
                            'type': claim_data['type'],
                            'description': claim_data['description'],
                            'claimed_amount': claim_data['claimed_amount'],
                            'approved_amount': claim_data.get('approved_amount', 0),
                            'status': claim_data['status'],
                            'filed_date': filed_date.isoformat(),
                            'created_date': filed_date.isoformat(),
                            'updated_date': now.isoformat()
                        }
                except Exception as e:
                    logger.warning(f"Could not create claim {claim_data['id']}: {e}")
            
            # Create underwriting application for primary customer
            # This is the latest application that can be used for risk assessment reports
            uw_asaf_id = f"UW-ASAF-{now.strftime('%Y%m%d')}-001"
            existing_uw = underwriting_repo.find_one_by(id=uw_asaf_id)
            if not existing_uw:
                try:
                    uw_app = underwriting_repo.create(
                        id=uw_asaf_id,
                        policy_id='POL-ASAF-HEALTH-001',
                        customer_id='CUST-ASAF-001',
                        status='pending',
                        risk_assessment='medium',
                        risk_score='medium',
                        created_date=now
                    )
                    logger.info(f"Created underwriting application for primary customer: {uw_app.id}")
                    
                    # Sync to memory
                    if sync_primary_to_memory:
                        UNDERWRITING_APPLICATIONS[uw_asaf_id] = {
                            'id': uw_asaf_id,
                            'policy_id': 'POL-ASAF-HEALTH-001',
                            'customer_id': 'CUST-ASAF-001',
                            'customer_name': 'Asaf Assurance',
                            'customer_email': 'asaf@assurance.co.il',
                            'policy_type': 'health',
                            'coverage_amount': 500000.0,
                            'annual_premium': 6000.0,
                            'monthly_premium': 500.0,
                            'status': 'pending',
                            'risk_score': 'medium',
                            'risk_assessment': 'medium',
                            'age': 39,
                            'disability_percentage': 30,
                            'bmi': 32,
                            'smoking_status': 'never',
                            'medical_conditions': [
                                {'condition': 'Obesity', 'severity': 'moderate', 'icd_code': 'E66.9'},
                                {'condition': 'Disability', 'severity': 'moderate', 'icd_code': 'Z99.89'}
                            ],
                            'created_date': now.isoformat(),
                            'submitted_date': now.isoformat(),
                            'updated_date': now.isoformat()
                        }
                except Exception as e:
                    logger.warning(f"Could not create underwriting application for primary customer: {e}")
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
        
        # Import in-memory data structures for sync
        try:
            from web_portal.server import CUSTOMERS, POLICIES, UNDERWRITING_APPLICATIONS, BILLING
            sync_to_memory = True
        except ImportError:
            sync_to_memory = False
            logger.warning("Could not import in-memory data structures - database-only seeding")
        
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
            
            annual_premium = cust_data['coverage'] * 0.012
            monthly_premium = cust_data['coverage'] * 0.001
            
            policy = policy_repo.create(
                id=pol_id,
                customer_id=customer.id,
                type=cust_data['policy_type'],
                coverage_amount=cust_data['coverage'],
                annual_premium=annual_premium,
                monthly_premium=monthly_premium,
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
            
            # === SYNC TO IN-MEMORY DATA STRUCTURES ===
            if sync_to_memory:
                # Sync customer
                CUSTOMERS[cust_data['id']] = {
                    'id': cust_data['id'],
                    'name': cust_data['name'],
                    'email': cust_data['email'],
                    'phone': f"+1-555-{hash(cust_data['email']) % 10000:04d}",
                    'created_date': now.isoformat()
                }
                
                # Sync policy
                POLICIES[pol_id] = {
                    'id': pol_id,
                    'customer_id': cust_data['id'],
                    'type': cust_data['policy_type'],
                    'coverage_amount': float(cust_data['coverage']),
                    'annual_premium': float(annual_premium),
                    'monthly_premium': float(monthly_premium),
                    'status': 'pending_underwriting',
                    'underwriting_id': uw_id,
                    'risk_score': 'medium',
                    'start_date': now.isoformat(),
                    'end_date': (now + timedelta(days=365)).isoformat(),
                    'created_date': now.isoformat(),
                    'updated_date': now.isoformat()
                }
                
                # Sync underwriting application
                UNDERWRITING_APPLICATIONS[uw_id] = {
                    'id': uw_id,
                    'policy_id': pol_id,
                    'customer_id': cust_data['id'],
                    'customer_name': cust_data['name'],
                    'customer_email': cust_data['email'],
                    'policy_type': cust_data['policy_type'],
                    'coverage_amount': float(cust_data['coverage']),
                    'annual_premium': float(annual_premium),
                    'monthly_premium': float(monthly_premium),
                    'age': None,
                    'risk_score': 'medium',
                    'status': 'pending',
                    'risk_assessment': 'medium',
                    'medical_exam_required': False,
                    'additional_documents_required': False,
                    'notes': None,
                    'questionnaire_responses': {},
                    'payment_setup': {},
                    'health_wallet': {},
                    'submitted_date': now.isoformat(),
                    'decision_date': None,
                    'decided_by': None,
                    'created_date': now.isoformat(),
                    'updated_date': now.isoformat()
                }
                logger.info(f"Synced {cust_data['id']} to in-memory data structures")
        
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
