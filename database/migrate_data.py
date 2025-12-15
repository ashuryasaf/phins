"""
Data Migration Script

Migrates data from in-memory dictionaries to database.
Useful for transitioning existing running servers.
"""

import logging
from typing import Dict, Any
from datetime import datetime

from database import init_database, get_db_session
from database.manager import DatabaseManager

logger = logging.getLogger(__name__)


def migrate_customers(customers_dict: Dict[str, Dict[str, Any]], db: DatabaseManager):
    """Migrate customers from dictionary to database"""
    migrated = 0
    skipped = 0
    
    for customer_id, customer_data in customers_dict.items():
        try:
            # Check if customer already exists
            existing = db.customers.get_by_id(customer_id)
            if existing:
                logger.debug(f"Customer {customer_id} already exists, skipping")
                skipped += 1
                continue
            
            # Create customer
            db.customers.create(
                id=customer_id,
                name=customer_data.get('name', ''),
                first_name=customer_data.get('first_name'),
                last_name=customer_data.get('last_name'),
                email=customer_data.get('email', f'{customer_id}@example.com'),
                phone=customer_data.get('phone'),
                dob=customer_data.get('dob'),
                age=customer_data.get('age'),
                gender=customer_data.get('gender'),
                address=customer_data.get('address'),
                city=customer_data.get('city'),
                state=customer_data.get('state'),
                zip=customer_data.get('zip'),
                occupation=customer_data.get('occupation')
            )
            migrated += 1
            logger.info(f"Migrated customer: {customer_id}")
        except Exception as e:
            logger.error(f"Error migrating customer {customer_id}: {e}")
    
    logger.info(f"Customers migration: {migrated} migrated, {skipped} skipped")
    return migrated, skipped


def migrate_policies(policies_dict: Dict[str, Dict[str, Any]], db: DatabaseManager):
    """Migrate policies from dictionary to database"""
    migrated = 0
    skipped = 0
    
    for policy_id, policy_data in policies_dict.items():
        try:
            # Check if policy already exists
            existing = db.policies.get_by_id(policy_id)
            if existing:
                logger.debug(f"Policy {policy_id} already exists, skipping")
                skipped += 1
                continue
            
            # Parse dates
            start_date = None
            end_date = None
            approval_date = None
            
            if 'start_date' in policy_data and policy_data['start_date']:
                try:
                    start_date = datetime.fromisoformat(policy_data['start_date'])
                except Exception:
                    pass
            
            if 'end_date' in policy_data and policy_data['end_date']:
                try:
                    end_date = datetime.fromisoformat(policy_data['end_date'])
                except Exception:
                    pass
            
            if 'approval_date' in policy_data and policy_data['approval_date']:
                try:
                    approval_date = datetime.fromisoformat(policy_data['approval_date'])
                except Exception:
                    pass
            
            # Create policy
            db.policies.create(
                id=policy_id,
                customer_id=policy_data.get('customer_id', ''),
                type=policy_data.get('type', 'life'),
                coverage_amount=float(policy_data.get('coverage_amount', 0)),
                annual_premium=float(policy_data.get('annual_premium', 0)),
                monthly_premium=float(policy_data.get('monthly_premium', 0)) if policy_data.get('monthly_premium') else None,
                status=policy_data.get('status', 'pending_underwriting'),
                underwriting_id=policy_data.get('underwriting_id'),
                risk_score=policy_data.get('risk_score'),
                start_date=start_date,
                end_date=end_date,
                approval_date=approval_date,
                uw_status=policy_data.get('uw_status')
            )
            migrated += 1
            logger.info(f"Migrated policy: {policy_id}")
        except Exception as e:
            logger.error(f"Error migrating policy {policy_id}: {e}")
    
    logger.info(f"Policies migration: {migrated} migrated, {skipped} skipped")
    return migrated, skipped


def migrate_claims(claims_dict: Dict[str, Dict[str, Any]], db: DatabaseManager):
    """Migrate claims from dictionary to database"""
    migrated = 0
    skipped = 0
    
    for claim_id, claim_data in claims_dict.items():
        try:
            # Check if claim already exists
            existing = db.claims.get_by_id(claim_id)
            if existing:
                logger.debug(f"Claim {claim_id} already exists, skipping")
                skipped += 1
                continue
            
            # Parse dates
            filed_date = None
            approval_date = None
            payment_date = None
            
            if 'filed_date' in claim_data and claim_data['filed_date']:
                try:
                    filed_date = datetime.fromisoformat(claim_data['filed_date'])
                except Exception:
                    filed_date = datetime.utcnow()
            
            if 'approval_date' in claim_data and claim_data['approval_date']:
                try:
                    approval_date = datetime.fromisoformat(claim_data['approval_date'])
                except Exception:
                    pass
            
            if 'payment_date' in claim_data and claim_data['payment_date']:
                try:
                    payment_date = datetime.fromisoformat(claim_data['payment_date'])
                except Exception:
                    pass
            
            # Create claim
            db.claims.create(
                id=claim_id,
                policy_id=claim_data.get('policy_id', ''),
                customer_id=claim_data.get('customer_id', ''),
                type=claim_data.get('type'),
                description=claim_data.get('description'),
                claimed_amount=float(claim_data.get('claimed_amount', 0)),
                approved_amount=float(claim_data.get('approved_amount', 0)) if claim_data.get('approved_amount') else None,
                status=claim_data.get('status', 'pending'),
                filed_date=filed_date,
                approval_date=approval_date,
                payment_date=payment_date,
                rejection_reason=claim_data.get('rejection_reason')
            )
            migrated += 1
            logger.info(f"Migrated claim: {claim_id}")
        except Exception as e:
            logger.error(f"Error migrating claim {claim_id}: {e}")
    
    logger.info(f"Claims migration: {migrated} migrated, {skipped} skipped")
    return migrated, skipped


def migrate_underwriting(underwriting_dict: Dict[str, Dict[str, Any]], db: DatabaseManager):
    """Migrate underwriting applications from dictionary to database"""
    migrated = 0
    skipped = 0
    
    for uw_id, uw_data in underwriting_dict.items():
        try:
            # Check if underwriting app already exists
            existing = db.underwriting.get_by_id(uw_id)
            if existing:
                logger.debug(f"Underwriting {uw_id} already exists, skipping")
                skipped += 1
                continue
            
            # Parse dates
            submitted_date = None
            decision_date = None
            
            if 'submitted_date' in uw_data and uw_data['submitted_date']:
                try:
                    submitted_date = datetime.fromisoformat(uw_data['submitted_date'])
                except Exception:
                    submitted_date = datetime.utcnow()
            
            if 'decision_date' in uw_data and uw_data['decision_date']:
                try:
                    decision_date = datetime.fromisoformat(uw_data['decision_date'])
                except Exception:
                    pass
            
            # Create underwriting application
            db.underwriting.create(
                id=uw_id,
                policy_id=uw_data.get('policy_id'),
                customer_id=uw_data.get('customer_id'),
                status=uw_data.get('status', 'pending'),
                risk_assessment=uw_data.get('risk_assessment'),
                medical_exam_required=uw_data.get('medical_exam_required', False),
                additional_documents_required=uw_data.get('additional_documents_required', False),
                notes=uw_data.get('notes'),
                submitted_date=submitted_date,
                decision_date=decision_date,
                decided_by=uw_data.get('decided_by')
            )
            migrated += 1
            logger.info(f"Migrated underwriting: {uw_id}")
        except Exception as e:
            logger.error(f"Error migrating underwriting {uw_id}: {e}")
    
    logger.info(f"Underwriting migration: {migrated} migrated, {skipped} skipped")
    return migrated, skipped


def migrate_all_data(customers: Dict, policies: Dict, claims: Dict, 
                     underwriting: Dict, users: Dict = None):
    """
    Migrate all data from in-memory dictionaries to database.
    
    Args:
        customers: CUSTOMERS dictionary
        policies: POLICIES dictionary
        claims: CLAIMS dictionary
        underwriting: UNDERWRITING_APPLICATIONS dictionary
        users: USERS dictionary (optional)
    """
    logger.info("Starting data migration...")
    
    # Initialize database
    try:
        init_database()
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        return
    
    # Migrate data
    with DatabaseManager() as db:
        # Migrate in order of dependencies
        migrate_customers(customers, db)
        migrate_policies(policies, db)
        migrate_claims(claims, db)
        migrate_underwriting(underwriting, db)
    
    logger.info("Data migration completed!")


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    print("This script is meant to be imported and used with actual data.")
    print("Example usage:")
    print("  from database.migrate_data import migrate_all_data")
    print("  migrate_all_data(CUSTOMERS, POLICIES, CLAIMS, UNDERWRITING_APPLICATIONS)")
