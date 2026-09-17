"""
Database Seed Data

Populates the database with default users and sample data.
Includes dynamic customer loading for persistence across restarts.

SECURITY NOTE:
All passwords are loaded from environment variables. If not set, random
unusable passwords are generated (users won't be able to login until
proper passwords are configured via environment variables).

Required environment variables:
- PHINS_ADMIN_PASSWORD, PHINS_UNDERWRITER_PASSWORD, etc. for system users
- PHINS_USER_{NAME}_PASSWORD for named user accounts
- PHINS_DEFAULT_CUSTOMER_PASSWORD for test customers (optional)
"""

import hashlib
import secrets
import random
import json
import os
from datetime import datetime, timedelta, timezone
import logging

from database import get_db_session, init_database
from database.repositories import UserRepository

logger = logging.getLogger(__name__)

# Path to dynamic customers file (created by registration)
DYNAMIC_CUSTOMERS_FILE = os.path.join(os.path.dirname(__file__), 'dynamic_customers.json')


def hash_password(password: str) -> dict:
    """Hash password using PBKDF2"""
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return {'hash': hashed.hex(), 'salt': salt}


def _is_db_backed_store(store) -> bool:
    """Return True when a server data store is a write-through DatabaseDict.

    When web_portal.server runs in database mode its CUSTOMERS/POLICIES/
    UNDERWRITING_APPLICATIONS/BILLING/CLAIMS "dicts" are DatabaseDict wrappers
    whose __setitem__ performs a SELECT + UPDATE against the database. Seed
    code that mirrors freshly created rows into those stores would therefore
    re-write the row the repository just persisted (the "Created X" followed
    by "Updated X" pattern in startup logs). Mirroring is only useful for the
    plain in-memory dicts used when the database is disabled.
    """
    try:
        from database.data_access import DatabaseDict
        return isinstance(store, DatabaseDict)
    except ImportError:
        return False


def _get_env_password(env_var: str, username: str) -> str:
    """
    Get password from environment variable or generate random unusable password.
    
    Args:
        env_var: Environment variable name
        username: Username for logging
        
    Returns:
        Password string from env var or random password
    """
    password = os.environ.get(env_var)
    if password:
        return password
    else:
        logger.warning(f"⚠️  No password configured for '{username}'. Set {env_var} environment variable.")
        return secrets.token_urlsafe(32)  # Random password that cannot be guessed


KERNEL_SEED_POLICY_TYPES = frozenset({'life', 'health', 'phins_unified'})
DEMO_NON_KERNEL_POLICY_IDS = ('POL-ASAF-AUTO-001',)
DEMO_NON_KERNEL_CLAIM_IDS = ('CLM-ASAF-003',)
DEMO_NON_KERNEL_BILL_IDS = ('BILL-ASAF-AUTO-001',)


def _age_from_dob(dob_value, as_of=None) -> int:
    """Whole years from ISO date-of-birth, matching kernel age extraction."""
    text = str(dob_value or '').strip()
    if not text:
        return 30
    try:
        dob = datetime.fromisoformat(text[:10]).date()
    except (TypeError, ValueError):
        return 30
    today = (as_of or datetime.now(timezone.utc)).date()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return age if age > 0 else 30


def _kernel_quote_seed_policy(**payload) -> dict:
    """Price a PHINS unified seed policy. Raises if the type is not kernel-mapped."""
    from services.pricing_shadow_service import kernel_quote_for_seed
    return kernel_quote_for_seed(payload)


def _seed_policy_from_kernel(
    *,
    policy_id: str,
    coverage_amount: float,
    age: int,
    gender: str,
    smoking_status: str,
    risk_score: str,
    status: str,
    adl_level: int = 5,
    term_years: int = 20,
) -> dict:
    kernel = _kernel_quote_seed_policy(
        type='phins_unified',
        coverage_amount=coverage_amount,
        age=age,
        gender=gender,
        smoking_status=smoking_status,
        risk_score=risk_score,
        adl_level=adl_level,
        term_years=term_years,
    )
    return {
        'id': policy_id,
        'type': 'phins_unified',
        'coverage_amount': float(coverage_amount),
        'annual_premium': round(float(kernel['annual']), 2),
        'monthly_premium': round(float(kernel['monthly']), 2),
        'quarterly_premium': kernel.get('quarterly'),
        'status': status,
        'risk_score': risk_score,
        'kernel': kernel,
        'age': age,
        'gender': gender,
        'smoking_status': smoking_status,
        'adl_level': adl_level,
    }


def _pin_kernel_on_policy_dict(policy: dict, kernel: dict) -> dict:
    from services.financial_unification_service import pin_kernel_fields_on_policy
    policy['type'] = 'phins_unified'
    policy['product_id'] = kernel.get('product_id') or 'phins_pure_risk_adjustable'
    policy['pricing_source'] = kernel.get('pricing_source') or 'pricing_kernel'
    pin_kernel_fields_on_policy(policy, kernel)
    return policy


def _retire_non_kernel_demo_seed(policy_repo, billing_repo, claim_repo, sync_memory: bool) -> None:
    """Cancel known demo auto/property seed IDs. Never sweeps unknown real policies.

    Paid claim cash already on the customer ledger is left in place so
    historical cash identity is not reversed.
    """
    POLICIES = BILLING = CLAIMS = None
    if sync_memory:
        try:
            from web_portal.server import POLICIES as _P, BILLING as _B, CLAIMS as _C
            POLICIES, BILLING, CLAIMS = _P, _B, _C
        except ImportError:
            POLICIES = BILLING = CLAIMS = None

    for policy_id in DEMO_NON_KERNEL_POLICY_IDS:
        existing = policy_repo.find_one_by(id=policy_id)
        if existing and str(getattr(existing, 'status', '') or '').lower() not in (
            'cancelled', 'canceled', 'void', 'retired'
        ):
            try:
                policy_repo.update(policy_id, status='cancelled')
                logger.info(f"Retired non-kernel demo policy {policy_id}")
            except Exception as exc:
                logger.warning(f"Could not retire demo policy {policy_id}: {exc}")
        if POLICIES is not None and policy_id in POLICIES:
            row = POLICIES.get(policy_id) or {}
            row['status'] = 'cancelled'
            row['cancelled_reason'] = 'non_kernel_demo_retired'
            POLICIES[policy_id] = row

    for bill_id in DEMO_NON_KERNEL_BILL_IDS:
        existing_bill = billing_repo.find_one_by(id=bill_id)
        if existing_bill:
            paid = float(getattr(existing_bill, 'amount_paid', 0) or 0)
            status = str(getattr(existing_bill, 'status', '') or '').lower()
            if paid <= 0.0 and status not in ('void', 'cancelled', 'canceled'):
                try:
                    billing_repo.update(bill_id, status='void')
                    logger.info(f"Voided unpaid non-kernel demo bill {bill_id}")
                except Exception as exc:
                    logger.warning(f"Could not void demo bill {bill_id}: {exc}")
        if BILLING is not None and bill_id in BILLING:
            bill = BILLING.get(bill_id) or {}
            if float(bill.get('amount_paid') or 0) <= 0:
                bill['status'] = 'void'
                BILLING[bill_id] = bill

    for claim_id in DEMO_NON_KERNEL_CLAIM_IDS:
        # Do not reverse a paid claim (cash already moved). Skip creating
        # these on fresh seeds; leave existing paid rows as historical cash.
        existing_claim = claim_repo.find_one_by(id=claim_id)
        if existing_claim:
            status = str(getattr(existing_claim, 'status', '') or '').lower()
            paid = float(
                getattr(existing_claim, 'paid_amount', 0)
                or getattr(existing_claim, 'approved_amount', 0)
                or 0
            )
            if status not in ('paid', 'closed') and paid <= 0:
                try:
                    claim_repo.update(claim_id, status='Cancelled')
                    logger.info(f"Cancelled unpaid non-kernel demo claim {claim_id}")
                except Exception as exc:
                    logger.warning(f"Could not cancel demo claim {claim_id}: {exc}")
        if CLAIMS is not None and claim_id in CLAIMS:
            claim = CLAIMS.get(claim_id) or {}
            status = str(claim.get('status') or '').lower()
            paid = float(claim.get('paid_amount') or claim.get('approved_amount') or 0)
            if status not in ('paid', 'closed') and paid <= 0:
                claim['status'] = 'Cancelled'
                CLAIMS[claim_id] = claim


def _seed_paid_claim_cash_to_ledger(sample_claims) -> None:
    """Write canonical claim_payment_received rows for paid seed claims."""
    try:
        from web_portal.server import TRANSACTION_LEDGER, platform_event_ledger
    except ImportError:
        return
    for claim_data in sample_claims:
        if str(claim_data.get('status') or '').lower() != 'paid':
            continue
        amount = float(claim_data.get('approved_amount') or 0)
        if amount <= 0:
            continue
        claim_id = claim_data['id']
        tx_id = f'TX-{claim_id}-PAID'
        if tx_id in TRANSACTION_LEDGER:
            continue
        payload = {
            'id': tx_id,
            'customer_id': 'CUST-ASAF-001',
            'type': 'claim_payment_received',
            'amount': amount,
            'description': f"Claim {claim_id} paid - deposited to Health Wallet",
            'metadata': {
                'claim_id': claim_id,
                'policy_id': claim_data.get('policy_id'),
                'destination': 'health_wallet',
                'source': 'seed_claim_cash',
            },
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'status': 'completed',
        }
        try:
            platform_event_ledger.append_event(
                event_type='claim_payment_received',
                entity_type='claim',
                entity_id=claim_id,
                customer_id='CUST-ASAF-001',
                actor='system',
                amount=amount,
                status='completed',
                source_system='demo_seed',
                payload=payload,
                entry_id=tx_id,
                ledger_type='transaction',
                timestamp=payload['timestamp'],
            )
        except Exception as exc:
            logger.warning(f"Could not seed claim cash {tx_id}: {exc}")


def seed_default_users(session=None):
    """Create default system users"""
    should_close = False
    if session is None:
        session = get_db_session()
        should_close = True
    
    try:
        user_repo = UserRepository(session)
        
        # System users - passwords loaded from environment variables
        default_users = [
            {
                'username': 'admin',
                'password_env': 'PHINS_ADMIN_PASSWORD',
                'role': 'admin',
                'name': 'Admin User',
                'email': 'admin@phins.ai'
            },
            {
                'username': 'actuary',
                'password_env': 'PHINS_ACTUARY_PASSWORD',
                'role': 'actuary',
                'name': 'Actuary User',
                'email': 'actuary@phins.ai'
            },
            {
                'username': 'supplier',
                'password_env': 'PHINS_SUPPLIER_PASSWORD',
                'role': 'supplier',
                'name': 'Supplier User',
                'email': 'supplier@phins.ai'
            },
            {
                'username': 'underwriter',
                'password_env': 'PHINS_UNDERWRITER_PASSWORD',
                'role': 'underwriter',
                'name': 'John Underwriter',
                'email': 'underwriter@phins.ai'
            },
            {
                'username': 'claims_adjuster',
                'password_env': 'PHINS_CLAIMS_PASSWORD',
                'role': 'claims',
                'name': 'Jane Claims',
                'email': 'claims@phins.ai'
            },
            {
                'username': 'accountant',
                'password_env': 'PHINS_ACCOUNTANT_PASSWORD',
                'role': 'accountant',
                'name': 'Bob Accountant',
                'email': 'accountant@phins.ai'
            },
            {
                'username': 'agent',
                'password_env': 'PHINS_AGENT_PASSWORD',
                'role': 'agent',
                'name': 'Demo Agent',
                'email': 'agent@phins.ai'
            },
            {
                'username': 'media_ad',
                'password_env': 'PHINS_MEDIA_PASSWORD',
                'role': 'media',
                'name': 'Media Admin',
                'email': 'media@phins.ai'
            },
            # Primary customer account (links to CUST-ASAF-001 in customers table)
            {
                'username': 'asaf@assurance.co.il',
                'password_env': 'PHINS_USER_ASAF_ASSURANCE_PASSWORD',
                'role': 'customer',
                'name': 'Asaf Assurance',
                'email': 'asaf@assurance.co.il'
            },
            # Admin account for asaf@phins.ai - PERSISTENT ACCOUNT
            {
                'username': 'asaf@phins.ai',
                'password_env': 'PHINS_USER_ASAF_PHINS_PASSWORD',
                'role': 'admin',
                'name': 'Asaf PHINS',
                'email': 'asaf@phins.ai'
            },
            # Customer account for efrat@phins.ai - PERSISTENT ACCOUNT
            {
                'username': 'efrat@phins.ai',
                'password_env': 'PHINS_USER_EFRAT_PASSWORD',
                'role': 'customer',
                'name': 'Efrat PHINS',
                'email': 'efrat@phins.ai'
            },
            # Customer account for asi@phins.ai - PERSISTENT ACCOUNT
            {
                'username': 'asi@phins.ai',
                'password_env': 'PHINS_USER_ASI_PASSWORD',
                'role': 'customer',
                'name': 'Asi PHINS',
                'email': 'asi@phins.ai'
            },
            # Customer account for shosh@phins.ai - PERSISTENT ACCOUNT
            {
                'username': 'shosh@phins.ai',
                'password_env': 'PHINS_USER_SHOSH_PASSWORD',
                'role': 'customer',
                'name': 'Shosh PHINS',
                'email': 'shosh@phins.ai'
            }
        ]
        
        # Single SELECT for all default accounts instead of one primary-key
        # lookup per user on every startup.
        existing_by_username = {
            user.username: user
            for user in user_repo.get_by_usernames(
                [user_data['username'] for user_data in default_users]
            )
        }

        skipped_existing = 0
        for user_data in default_users:
            # Check if user already exists
            existing_user = existing_by_username.get(user_data['username'])
            if existing_user:
                # Update role if it has changed (important for role changes like media_ad)
                if existing_user.role != user_data['role']:
                    existing_user.role = user_data['role']
                    session.commit()
                    logger.info(f"Updated user '{user_data['username']}' role to: {user_data['role']}")
                else:
                    skipped_existing += 1
                continue
            
            # Resolve + hash the password only when the account is actually
            # created. Resolving eagerly for accounts that already exist
            # emitted a misleading "No password configured" warning (and
            # generated a throwaway random password) on every startup.
            password_hash = hash_password(
                _get_env_password(user_data['password_env'], user_data['username'])
            )
            
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
        
        if skipped_existing:
            logger.info(f"Default users: {skipped_existing} already exist with correct roles, skipped")
        logger.info("Default users seeded successfully")
        
        # ========== LOAD DYNAMIC CUSTOMERS (from registration) ==========
        seed_dynamic_customers(session, user_repo)
        
    except Exception as e:
        logger.error(f"Error seeding users: {e}")
        if should_close:
            session.rollback()
        raise
    finally:
        if should_close:
            session.close()


def seed_dynamic_customers(session, user_repo):
    """Load dynamically registered customers from JSON file"""
    try:
        if not os.path.exists(DYNAMIC_CUSTOMERS_FILE):
            logger.info("No dynamic customers file found, skipping...")
            return
        
        with open(DYNAMIC_CUSTOMERS_FILE, 'r') as f:
            dynamic_customers = json.load(f)
        
        if not dynamic_customers:
            logger.info("Dynamic customers file is empty")
            return
        
        # Deduplicate: keep the last entry per email/username (most recent)
        seen: dict = {}
        for customer in dynamic_customers:
            key = customer.get('username', customer.get('email', ''))
            if key:
                seen[key] = customer
        unique_customers = list(seen.values())

        # One SELECT for all dynamic accounts instead of a lookup per customer.
        # Fall back to per-user lookups for repos (e.g. test doubles) that only
        # implement get_by_username.
        candidate_usernames = [
            customer.get('username', customer.get('email', ''))
            for customer in unique_customers
            if customer.get('username', customer.get('email', ''))
        ]
        batch_lookup = getattr(user_repo, 'get_by_usernames', None)
        if callable(batch_lookup):
            existing_usernames = {
                user.username for user in batch_lookup(candidate_usernames)
            }
        else:
            existing_usernames = {
                username for username in candidate_usernames
                if user_repo.get_by_username(username)
            }

        created_count = 0
        skipped_count = 0
        for customer in unique_customers:
            username = customer.get('username', customer.get('email', ''))
            if not username:
                continue
            
            if username in existing_usernames:
                skipped_count += 1
                continue
            
            # Use pre-hashed credentials if available, otherwise hash now
            if (
                customer.get('password_hash')
                and customer.get('password_salt')
                and customer['password_hash'] != 'REDACTED'
                and customer['password_salt'] != 'REDACTED'
            ):
                pw_hash = {'hash': customer['password_hash'], 'salt': customer['password_salt']}
            else:
                default_cust_pwd = os.environ.get('PHINS_DEFAULT_CUSTOMER_PASSWORD', secrets.token_urlsafe(32))
                pw_hash = hash_password(customer.get('password', default_cust_pwd))
            
            user_repo.create(
                username=username,
                password_hash=pw_hash['hash'],
                password_salt=pw_hash['salt'],
                role='customer',
                name=customer.get('name', username),
                email=customer.get('email', username),
                active=True
            )
            created_count += 1
            logger.info(f"Created dynamic customer: {username}")
        
        logger.info(f"Dynamic customers loaded: {len(unique_customers)} processed ({created_count} created, {skipped_count} skipped)")
        
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing dynamic customers file: {e}")
    except Exception as e:
        logger.error(f"Error loading dynamic customers: {e}")


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
        
        now = datetime.now(timezone.utc)
        
        # =================================================================
        # PRIMARY TEST ACCOUNT: asaf@assurance.co.il
        # =================================================================
        # Import in-memory data structures for primary customer sync.
        # Skip mirroring when the stores are DB-backed: the repository create
        # below already persists the row, so the mirror write would only issue
        # a redundant SELECT + UPDATE against the same database row.
        try:
            from web_portal.server import CUSTOMERS, POLICIES, UNDERWRITING_APPLICATIONS, BILLING, CLAIMS
            sync_primary_to_memory = not _is_db_backed_store(CUSTOMERS)
        except ImportError:
            sync_primary_to_memory = False
            logger.warning("Could not import in-memory data structures for primary customer")
        
        primary_customer = customer_repo.find_one_by(email='asaf@assurance.co.il')
        if not primary_customer:
            pwd = hash_password(_get_env_password('PHINS_USER_ASAF_ASSURANCE_PASSWORD', 'asaf@assurance.co.il'))
            primary_customer = customer_repo.create(
                id='CUST-ASAF-001',
                name='Asaf Assurance',
                first_name='Asaf',
                last_name='Assurance',
                email='asaf@assurance.co.il',
                phone='+972-50-1234567',
                dob='1985-03-15',
                age=_age_from_dob('1985-03-15'),
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
            
            # Initialize health wallet — balance will be populated by claim
            # payment processing below (Paid claims deposit into wallet).
            from web_portal.server import HEALTH_WALLETS
            HEALTH_WALLETS['CUST-ASAF-001'] = {
                'customer_id': 'CUST-ASAF-001',
                'balance': 0.00,
                'monthly_deposit': 0.00,
                'transactions': [],
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            logger.info(f"Created empty health wallet for CUST-ASAF-001 (claim payments will populate balance)")
        else:
            logger.info(f"Primary customer {primary_customer.email} already exists, verifying related data...")

        # =================================================================
        # Idempotent creation of primary customer policies/bills/claims/UW.
        # This block runs on every call so that re-deployments (where the
        # primary customer already exists) still ensure all dependent rows
        # are present in the database. Previously, because these were nested
        # under `if not primary_customer:`, subsequent deploys tried to
        # insert claims referencing policies that were never persisted,
        # causing `claims_policy_id_fkey` foreign-key violations.
        # =================================================================

        # PREMIUM CALCULATION: actuarial kernel for PHINS unified only.
        # Auto / property / business are not kernel products and are not seeded.
        asaf_age = _age_from_dob(getattr(primary_customer, 'dob', None) or '1985-03-15')
        try:
            asaf_life = _seed_policy_from_kernel(
                policy_id='POL-ASAF-LIFE-001',
                coverage_amount=1000000.0,
                age=asaf_age,
                gender='male',
                smoking_status='never',
                risk_score='low',
                status='active',
            )
            asaf_health = _seed_policy_from_kernel(
                policy_id='POL-ASAF-HEALTH-001',
                coverage_amount=500000.0,
                age=asaf_age,
                gender='male',
                smoking_status='never',
                risk_score='medium',
                status='active',
            )
        except Exception as kern_err:
            logger.warning(f"Kernel seed pricing failed, skipping Asaf policies: {kern_err}")
            asaf_life = asaf_health = None

        policies_data = [p for p in (asaf_life, asaf_health) if p]

        for pol_data in policies_data:
            kernel = pol_data.get('kernel') or {}
            billing_blob = {
                'auto_pay': True,
                'frequency': 'monthly',
                'next_billing_date': (now + timedelta(days=30)).isoformat(),
                'product_id': kernel.get('product_id') or 'phins_pure_risk_adjustable',
                'pricing_source': kernel.get('pricing_source') or 'pricing_kernel',
                'integrity_hash': kernel.get('integrity_hash'),
                'risk_premium_annual': kernel.get('risk_premium_annual'),
                'savings_premium_annual': kernel.get('savings_premium_annual'),
            }
            existing_policy = policy_repo.find_one_by(id=pol_data['id'])
            if existing_policy and str(getattr(existing_policy, 'type', '') or '').lower() in (
                'life', 'health'
            ):
                # Convert legacy demo life/health labels to PHINS unified without
                # rewriting billed premiums on an already-issued row.
                try:
                    policy_repo.update(pol_data['id'], type='phins_unified')
                    logger.info(f"Converted seed policy {pol_data['id']} type to phins_unified")
                except Exception as e:
                    logger.warning(f"Could not convert {pol_data['id']} to phins_unified: {e}")
            if not existing_policy:
                try:
                    policy = policy_repo.create(
                        id=pol_data['id'],
                        customer_id=primary_customer.id,
                        type='phins_unified',
                        coverage_amount=pol_data['coverage_amount'],
                        annual_premium=pol_data['annual_premium'],
                        monthly_premium=pol_data['monthly_premium'],
                        status=pol_data['status'],
                        risk_score=pol_data['risk_score'],
                        start_date=now,
                        end_date=now + timedelta(days=365),
                        approval_date=now,
                        billing=json.dumps(billing_blob),
                    )
                    if policy is not None:
                        logger.info(
                            f"Created kernel-priced policy {policy.id} "
                            f"${pol_data['annual_premium']:.2f}/yr"
                        )
                    else:
                        logger.warning(f"Policy repo returned None for {pol_data['id']}; skipping dependents")
                        continue
                except Exception as e:
                    logger.warning(f"Could not create policy {pol_data['id']}: {e}")
                    continue

            # Sync policy to memory ONLY for newly-seeded rows. When the policy
            # already exists in the DB we must NOT rewrite billed premiums.
            if sync_primary_to_memory and not existing_policy:
                seeded = {
                    'id': pol_data['id'],
                    'customer_id': 'CUST-ASAF-001',
                    'type': 'phins_unified',
                    'coverage_amount': pol_data['coverage_amount'],
                    'annual_premium': pol_data['annual_premium'],
                    'monthly_premium': pol_data['monthly_premium'],
                    'status': pol_data['status'],
                    'risk_score': pol_data['risk_score'],
                    'start_date': now.isoformat(),
                    'end_date': (now + timedelta(days=365)).isoformat(),
                    'approval_date': now.isoformat(),
                    'created_date': now.isoformat(),
                    'updated_date': now.isoformat(),
                    'payment_setup': {
                        'auto_pay': True,
                        'billing_frequency': 'monthly',
                        'card_type': 'mastercard',
                        'card_last4': '4242',
                        'next_billing_date': (now + timedelta(days=30)).isoformat(),
                    },
                    'billing': billing_blob,
                    'age': pol_data.get('age'),
                    'gender': pol_data.get('gender'),
                    'smoking_status': pol_data.get('smoking_status'),
                    'adl_level': pol_data.get('adl_level', 5),
                }
                _pin_kernel_on_policy_dict(seeded, kernel)
                POLICIES[pol_data['id']] = seeded
            elif sync_primary_to_memory and existing_policy and pol_data['id'] in POLICIES:
                row = POLICIES[pol_data['id']]
                if str(row.get('type') or '').lower() in ('life', 'health', ''):
                    row['type'] = 'phins_unified'
                if not row.get('product_id'):
                    row['product_id'] = 'phins_pure_risk_adjustable'

            # Create bill for active policy (idempotent)
            if pol_data['status'] == 'active':
                bill_id = f"BILL-{pol_data['id'].replace('POL-', '')}"
                existing_bill = billing_repo.find_one_by(id=bill_id)
                if not existing_bill:
                    try:
                        billing_repo.create(
                            id=bill_id,
                            policy_id=pol_data['id'],
                            customer_id=primary_customer.id,
                            amount=pol_data['monthly_premium'],
                            amount_paid=0.0,
                            status='outstanding',
                            due_date=now + timedelta(days=30)
                        )
                        logger.info(f"Created bill: {bill_id}")
                    except Exception as e:
                        logger.warning(f"Could not create bill {bill_id}: {e}")

                # Mirror billing to memory ONLY for newly-seeded bills. An
                # existing bill may have been paid, partially paid, or had its
                # due_date advanced; rewriting the seed dict would reset
                # status='outstanding', amount_paid=0, and slide the due_date
                # forward 30 days every restart, breaking the billing pipeline.
                if sync_primary_to_memory and not existing_bill:
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

        # Create sample claims for the primary customer (idempotent;
        # depends on policies persisted above). Auto collision is not a
        # kernel product and is no longer seeded.
        claim_repo = ClaimRepository(session)
        _retire_non_kernel_demo_seed(policy_repo, billing_repo, claim_repo, sync_primary_to_memory)
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
                existing_claim = claim_repo.find_one_by(id=claim_data['id'])
                if not existing_claim:
                    # Guard against FK violation: only insert if the referenced
                    # policy is present in the DB.
                    parent_policy = policy_repo.find_one_by(id=claim_data['policy_id'])
                    if not parent_policy:
                        logger.warning(
                            f"Skipping claim {claim_data['id']}: parent policy "
                            f"{claim_data['policy_id']} not found in database"
                        )
                    else:
                        claim = claim_repo.create(
                            id=claim_data['id'],
                            policy_id=claim_data['policy_id'],
                            customer_id=primary_customer.id,
                            type=claim_data['type'],
                            description=claim_data['description'],
                            claimed_amount=claim_data['claimed_amount'],
                            approved_amount=claim_data.get('approved_amount'),
                            status=claim_data['status'],
                            filed_date=filed_date,
                            created_date=filed_date
                        )
                        if claim is not None:
                            logger.info(f"Created claim: {claim.id}")

                # Mirror claim to memory ONLY for newly-seeded claims. A claim
                # whose status advanced (e.g. Pending → Approved → Paid) must
                # not be reverted to its seed status on every container start;
                # that would corrupt the claims pipeline and the wallet
                # reconciliation that runs immediately afterwards.
                if sync_primary_to_memory and not existing_claim:
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

        # Reconcile paid claims → wallet: any claim with status "Paid" must
        # have its approved_amount reflected in the customer's health wallet.
        # Idempotent: skip claims whose payment transaction is already recorded.
        try:
            from web_portal.server import HEALTH_WALLETS
            paid_claims_total = 0.0
            for claim_data in sample_claims:
                if claim_data['status'] == 'Paid' and claim_data.get('approved_amount'):
                    cust_id = 'CUST-ASAF-001'
                    wallet = HEALTH_WALLETS.get(cust_id)
                    if not wallet:
                        continue

                    tx_id = f"CLAIM-PAY-SEED-{claim_data['id']}"
                    transactions = wallet.setdefault('transactions', [])
                    if any(tx.get('id') == tx_id for tx in transactions):
                        continue

                    amt = float(claim_data['approved_amount'])
                    wallet['balance'] += amt
                    paid_claims_total += amt
                    transactions.append({
                        'id': tx_id,
                        'type': 'claim_payment',
                        'amount': amt,
                        'source': 'PHINS_CLAIMS_RESERVE',
                        'claim_id': claim_data['id'],
                        'description': f"Claim {claim_data['id']} payment - {claim_data['description'][:50]}",
                        'balance_after': wallet['balance'],
                        'timestamp': datetime.now(timezone.utc).isoformat()
                    })
            if paid_claims_total > 0:
                logger.info(f"Reconciled {paid_claims_total:.2f} in paid claims to CUST-ASAF-001 wallet")
            else:
                logger.info("Paid claims already reconciled in CUST-ASAF-001 wallet, skipping")
        except ImportError:
            logger.warning("Could not import HEALTH_WALLETS for paid claim reconciliation")

        _seed_paid_claim_cash_to_ledger(sample_claims)

        # Create underwriting application for primary customer (idempotent).
        # This is the latest application that can be used for risk assessment reports.
        #
        # IMPORTANT: previously this used `f"UW-ASAF-{now.strftime('%Y%m%d')}-001"`
        # which generated a NEW id every calendar day, so each Railway restart
        # crossing midnight inserted yet another orphaned UW row for asaf and
        # left every prior day's row in PostgreSQL forever. Use a stable id
        # and reuse any pre-existing seed UW (date-stamped or otherwise) for
        # asaf's health policy so prod data accumulated under the old scheme
        # is preserved without being duplicated.
        STABLE_UW_ASAF_ID = 'UW-ASAF-HEALTH-001'
        existing_uw = (
            underwriting_repo.find_one_by(id=STABLE_UW_ASAF_ID)
            or underwriting_repo.get_by_policy('POL-ASAF-HEALTH-001')
        )
        uw_asaf_id = existing_uw.id if existing_uw else STABLE_UW_ASAF_ID
        # Single source of truth for the seeded application. Used both for
        # the DB create (fields outside the model are filtered by the
        # repository) and the in-memory mirror, so we no longer need a
        # create-then-update double write to enrich the row.
        # Align the seed UW with the issued kernel-priced PHINS unified policy.
        health_quote = asaf_health or {}
        uw_asaf_payload = {
                'id': uw_asaf_id,
                'policy_id': 'POL-ASAF-HEALTH-001',
                'customer_id': 'CUST-ASAF-001',
                'customer_name': 'Asaf Assurance',
                'customer_email': 'asaf@assurance.co.il',
                'policy_type': 'phins_unified',
                'coverage_amount': 500000.0,
                'annual_premium': health_quote.get('annual_premium', 0),
                'monthly_premium': health_quote.get('monthly_premium', 0),
                'status': 'approved',
                'risk_score': 'medium',
                'risk_assessment': 'medium',
                'age': asaf_age,
                'gender': 'male',
                'occupation': 'Business Owner',
                'disability_percentage': 30,
                'disability_type': 'Mobility Impairment - Lower Limb',
                'disability_status': 'stable',
                'bmi': 32,
                'height_cm': 175,
                'weight_kg': 98,
                'smoking_status': 'never',
                'medical_conditions': [
                    {
                        'condition': 'Obesity',
                        'icd_code': 'E66.9',
                        'severity': 'moderate',
                        'status': 'active',
                        'treatment': 'Dietary management, exercise program',
                        'risk_impact': 0.07,
                        'loading_percentage': 15,
                        'notes': 'BMI 32.0 (Class I Obesity). Weight management program.'
                    },
                    {
                        'condition': 'Mobility Impairment - Lower Limb',
                        'icd_code': 'M62.50',
                        'severity': 'moderate',
                        'status': 'stable',
                        'treatment': 'Physiotherapy, mobility aids',
                        'risk_impact': 0.18,
                        'loading_percentage': 20,
                        'exclusion_recommended': True,
                        'notes': '30% disability rating. Stable condition.'
                    }
                ],
                'documents': [
                    {'type': 'national_id', 'verified': True, 'authenticity_score': 0.95, 'expiry_status': 'valid'},
                    {'type': 'disability_certificate', 'verified': True, 'authenticity_score': 0.98, 'expiry_status': 'valid', 'flags': 'DISABILITY_DECLARED'},
                    {'type': 'medical_report', 'verified': True, 'authenticity_score': 0.96, 'expiry_status': 'valid', 'flags': 'MULTIPLE_CONDITIONS'}
                ],
                'identity_verified': True,
                'medical_exam_required': True,
                'premium_adjustment': 35,
                'created_date': now.isoformat(),
                'submitted_date': now.isoformat(),
                'updated_date': now.isoformat()
            }

        if not existing_uw:
            try:
                # Only insert if parent policy exists to avoid FK violation
                parent_policy = policy_repo.find_one_by(id='POL-ASAF-HEALTH-001')
                if parent_policy:
                    # convert_datetime_strings() serializes the JSON fields
                    # (medical_conditions, documents) and parses the ISO
                    # timestamps exactly like the DatabaseDict write-through
                    # used to do when the mirror enriched this row.
                    from database.data_access import convert_datetime_strings
                    uw_app = underwriting_repo.create(
                        **convert_datetime_strings(uw_asaf_payload)
                    )
                    if uw_app is not None:
                        logger.info(f"Created underwriting application for primary customer: {uw_app.id}")
                else:
                    logger.warning(
                        f"Skipping underwriting {uw_asaf_id}: parent policy "
                        f"POL-ASAF-HEALTH-001 not found in database"
                    )
            except Exception as e:
                logger.warning(f"Could not create underwriting application for primary customer: {e}")

        # Mirror UW application to memory ONLY for newly-seeded rows. An
        # existing application may have advanced through the underwriting
        # pipeline (status, risk_assessment, premium_adjustment, documents);
        # rewriting the seed dict on every restart would silently roll the
        # decision back to 'pending'.
        if sync_primary_to_memory and not existing_uw:
            UNDERWRITING_APPLICATIONS[uw_asaf_id] = uw_asaf_payload

        # =================================================================
        # PHINS CUSTOMER ACCOUNTS - PERMANENT DATA (efrat, asi, shosh)
        # These customers are primary platform users with full data persistence.
        # Premiums are kernel-priced PHINS unified (not the legacy $0.25/1000 table).
        # =================================================================
        try:
            efrat_age = _age_from_dob('1990-06-15')
            asi_age = _age_from_dob('1985-03-20')
            shosh_age = _age_from_dob('1988-09-10')
            efrat_pol = _seed_policy_from_kernel(
                policy_id='POL-EFRAT-UNIFIED-001', coverage_amount=500000.0,
                age=efrat_age, gender='female', smoking_status='never',
                risk_score='low', status='active',
            )
            asi_pol = _seed_policy_from_kernel(
                policy_id='POL-ASI-UNIFIED-001', coverage_amount=400000.0,
                age=asi_age, gender='male', smoking_status='never',
                risk_score='low', status='pending_underwriting',
            )
            shosh_pol = _seed_policy_from_kernel(
                policy_id='POL-SHOSH-UNIFIED-001', coverage_amount=450000.0,
                age=shosh_age, gender='female', smoking_status='never',
                risk_score='low', status='pending_underwriting',
            )
        except Exception as kern_err:
            logger.warning(f"Kernel seed pricing failed for PHINS customers: {kern_err}")
            efrat_pol = asi_pol = shosh_pol = None
            efrat_age, asi_age, shosh_age = 35, 40, 37

        phins_customers = [
            {
                'id': 'CUST-EFRAT-001',
                'name': 'Efrat PHINS',
                'email': 'efrat@phins.ai',
                'phone': '+972-50-9876543',
                'dob': '1990-06-15',
                'age': efrat_age,
                'gender': 'female',
                'occupation': 'Product Manager',
                'password_env': 'PHINS_USER_EFRAT_PASSWORD',
                'policy': efrat_pol,
                'application': {
                    'id': 'UW-EFRAT-001',
                    'status': 'approved',
                    'risk_score': 'low',
                    'bmi': 22,
                    'smoking_status': 'never',
                    'disability_percentage': 0,
                    'medical_conditions': []
                },
                'wallet_balance': 5000.0,
                'investment_balance': 10000.0
            },
            {
                'id': 'CUST-ASI-001',
                'name': 'Asi PHINS',
                'email': 'asi@phins.ai',
                'phone': '+972-50-1111111',
                'dob': '1985-03-20',
                'age': asi_age,
                'gender': 'male',
                'occupation': 'Software Engineer',
                'password_env': 'PHINS_USER_ASI_PASSWORD',
                'policy': asi_pol,
                'application': {
                    'id': 'UW-ASI-001',
                    'status': 'pending',
                    'risk_score': 'low',
                    'bmi': 24,
                    'smoking_status': 'never',
                    'disability_percentage': 0,
                    'medical_conditions': []
                },
                'wallet_balance': 0.0,
                'investment_balance': 0.0
            },
            {
                'id': 'CUST-SHOSH-001',
                'name': 'Shosh PHINS',
                'email': 'shosh@phins.ai',
                'phone': '+972-50-2222222',
                'dob': '1988-09-10',
                'age': shosh_age,
                'gender': 'female',
                'occupation': 'Marketing Director',
                'password_env': 'PHINS_USER_SHOSH_PASSWORD',
                'policy': shosh_pol,
                'application': {
                    'id': 'UW-SHOSH-001',
                    'status': 'pending',
                    'risk_score': 'low',
                    'bmi': 23,
                    'smoking_status': 'never',
                    'disability_percentage': 0,
                    'medical_conditions': []
                },
                'wallet_balance': 0.0,
                'investment_balance': 0.0
            }
        ]
        phins_customers = [c for c in phins_customers if c.get('policy')]
        
        # Import additional in-memory structures
        try:
            from web_portal.server import HEALTH_WALLETS, INVESTMENT_ACCOUNTS
            sync_wallets = True
        except ImportError:
            sync_wallets = False
        
        # Import main in-memory structures for syncing. DB-backed stores are
        # write-through, so mirroring newly created rows would just re-write
        # them; mirror only when the server runs on plain in-memory dicts.
        try:
            from web_portal.server import CUSTOMERS, POLICIES, UNDERWRITING_APPLICATIONS, BILLING
            sync_to_memory = not _is_db_backed_store(CUSTOMERS)
        except ImportError:
            sync_to_memory = False
            logger.warning("Could not import in-memory data structures for PHINS customers")
        
        for phins_cust in phins_customers:
            existing = customer_repo.find_one_by(email=phins_cust['email'])
            if existing:
                logger.info(f"PHINS customer {phins_cust['email']} already exists, syncing to memory...")
            else:
                # Password resolved only when the customer is actually created
                # (avoids a spurious missing-password warning on every boot).
                pwd = hash_password(
                    _get_env_password(phins_cust['password_env'], phins_cust['email'])
                )
                customer = customer_repo.create(
                    id=phins_cust['id'],
                    name=phins_cust['name'],
                    email=phins_cust['email'],
                    phone=phins_cust['phone'],
                    dob=phins_cust['dob'],
                    age=phins_cust['age'],
                    gender=phins_cust['gender'],
                    occupation=phins_cust['occupation'],
                    password_hash=pwd['hash'],
                    password_salt=pwd['salt'],
                    portal_active=True
                )
                logger.info(f"Created PHINS customer: {phins_cust['email']} → {phins_cust['id']}")
            
            # Create/verify policy
            pol_data = phins_cust['policy']
            existing_policy = policy_repo.find_one_by(id=pol_data['id'])
            if existing_policy and str(getattr(existing_policy, 'type', '') or '').lower() in (
                'life', 'health'
            ):
                try:
                    policy_repo.update(pol_data['id'], type='phins_unified')
                    logger.info(f"Converted seed policy {pol_data['id']} type to phins_unified")
                except Exception as e:
                    logger.warning(f"Could not convert {pol_data['id']} to phins_unified: {e}")
            if not existing_policy:
                policy_kwargs = dict(
                    id=pol_data['id'],
                    customer_id=phins_cust['id'],
                    type=pol_data['type'],
                    coverage_amount=pol_data['coverage_amount'],
                    annual_premium=pol_data['annual_premium'],
                    monthly_premium=pol_data['monthly_premium'],
                    status=pol_data['status'],
                    risk_score=pol_data['risk_score'],
                    start_date=now,
                    end_date=now + timedelta(days=365)
                )
                if pol_data['status'] == 'active':
                    # Previously only written via the in-memory mirror's DB
                    # write-through; persist directly at create time.
                    policy_kwargs['billing'] = json.dumps({
                        'auto_pay': True,
                        'frequency': 'monthly',
                        'next_billing_date': (now + timedelta(days=30)).isoformat(),
                    })
                policy_repo.create(**policy_kwargs)
                logger.info(f"Created policy: {pol_data['id']} for {phins_cust['email']}")
            
            # Create/verify underwriting application
            app_data = phins_cust['application']
            existing_app = underwriting_repo.find_one_by(id=app_data['id'])
            if not existing_app:
                underwriting_repo.create(
                    id=app_data['id'],
                    policy_id=pol_data['id'],
                    customer_id=phins_cust['id'],
                    customer_name=phins_cust['name'],
                    customer_email=phins_cust['email'],
                    policy_type=pol_data['type'],
                    coverage_amount=pol_data['coverage_amount'],
                    age=phins_cust['age'],
                    gender=phins_cust['gender'],
                    occupation=phins_cust['occupation'],
                    status=app_data['status'],
                    risk_assessment=app_data['risk_score'],
                    risk_score=app_data['risk_score'],
                    bmi=app_data.get('bmi'),
                    smoking_status=app_data.get('smoking_status'),
                    disability_percentage=app_data.get('disability_percentage', 0),
                    medical_conditions=json.dumps(app_data.get('medical_conditions', [])),
                    medical_exam_required=False,
                    submitted_date=now,
                    created_date=now
                )
                logger.info(f"Created underwriting application: {app_data['id']} for {phins_cust['email']}")
            
            # Create billing record for active policies (FIX: CUST-EFRAT-001 validation error)
            if pol_data['status'] == 'active':
                bill_id = f"BILL-{pol_data['id'].replace('POL-', '')}"
                existing_bill = billing_repo.find_one_by(id=bill_id)
                if not existing_bill:
                    billing_repo.create(
                        id=bill_id,
                        policy_id=pol_data['id'],
                        customer_id=phins_cust['id'],
                        amount=pol_data['monthly_premium'],
                        amount_paid=0.0,
                        status='outstanding',
                        due_date=now + timedelta(days=30)
                    )
                    logger.info(f"Created billing record: {bill_id} for {phins_cust['email']}")
                
                # Mirror bill to memory ONLY for newly-seeded bills. See the
                # primary-customer billing block above for rationale: rewriting
                # an existing bill resets payment status, amount_paid, and
                # slides the due_date forward 30 days on every restart.
                if sync_to_memory and not existing_bill:
                    BILLING[bill_id] = {
                        'id': bill_id,
                        'policy_id': pol_data['id'],
                        'customer_id': phins_cust['id'],
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
                    logger.info(f"Synced billing record {bill_id} to memory")
            
            # Mirror PHINS customer / policy / UW to memory ONLY for newly-
            # seeded rows. For existing rows we MUST NOT overwrite the live
            # state (status transitions, premium adjustments, billing dates,
            # underwriting decisions) with the seed defaults — that was the
            # root cause of repeated `Updated Policy/Bill/UnderwritingApplication`
            # log entries on every Railway restart and silent rollbacks of
            # workflow progress.
            if sync_to_memory:
                if not existing:
                    CUSTOMERS[phins_cust['id']] = {
                        'id': phins_cust['id'],
                        'name': phins_cust['name'],
                        'email': phins_cust['email'],
                        'phone': phins_cust['phone'],
                        'date_of_birth': phins_cust['dob'],
                        'age': phins_cust['age'],
                        'gender': phins_cust['gender'],
                        'occupation': phins_cust['occupation'],
                        'created_date': now.isoformat(),
                        'status': 'active'
                    }

                if not existing_policy:
                    policy_mem = {
                        'id': pol_data['id'],
                        'customer_id': phins_cust['id'],
                        'type': pol_data['type'],
                        'coverage_amount': pol_data['coverage_amount'],
                        'annual_premium': pol_data['annual_premium'],
                        'monthly_premium': pol_data['monthly_premium'],
                        'status': pol_data['status'],
                        'risk_score': pol_data['risk_score'],
                        'start_date': now.isoformat(),
                        'end_date': (now + timedelta(days=365)).isoformat(),
                        'created_date': now.isoformat()
                    }
                    if pol_data['status'] == 'active':
                        policy_mem['payment_setup'] = {
                            'auto_pay': True,
                            'billing_frequency': 'monthly',
                            'card_type': 'mastercard',
                            'card_last4': '4242',
                            'next_billing_date': (now + timedelta(days=30)).isoformat(),
                        }
                        policy_mem['billing'] = {
                            'auto_pay': True,
                            'frequency': 'monthly',
                            'next_billing_date': (now + timedelta(days=30)).isoformat(),
                        }
                    _pin_kernel_on_policy_dict(policy_mem, pol_data.get('kernel') or {})
                    POLICIES[pol_data['id']] = policy_mem
                elif pol_data['id'] in POLICIES:
                    row = POLICIES[pol_data['id']]
                    if str(row.get('type') or '').lower() in ('life', 'health', ''):
                        row['type'] = 'phins_unified'
                    if not row.get('product_id'):
                        row['product_id'] = 'phins_pure_risk_adjustable'
                    POLICIES[pol_data['id']] = row

                if not existing_app:
                    UNDERWRITING_APPLICATIONS[app_data['id']] = {
                        'id': app_data['id'],
                        'policy_id': pol_data['id'],
                        'customer_id': phins_cust['id'],
                        'customer_name': phins_cust['name'],
                        'customer_email': phins_cust['email'],
                        'policy_type': pol_data['type'],
                        'coverage_amount': pol_data['coverage_amount'],
                        'annual_premium': pol_data['annual_premium'],
                        'monthly_premium': pol_data['monthly_premium'],
                        'age': phins_cust['age'],
                        'gender': phins_cust['gender'],
                        'occupation': phins_cust['occupation'],
                        'risk_score': app_data['risk_score'],
                        'status': app_data['status'],
                        'risk_assessment': app_data['risk_score'],
                        'bmi': app_data.get('bmi'),
                        'smoking_status': app_data.get('smoking_status'),
                        'disability_percentage': app_data.get('disability_percentage', 0),
                        'medical_conditions': app_data.get('medical_conditions', []),
                        'medical_exam_required': False,
                        'submitted_date': now.isoformat(),
                        'created_date': now.isoformat(),
                        'updated_date': now.isoformat()
                    }
            
            # Initialize wallets
            if sync_wallets:
                if phins_cust['id'] not in HEALTH_WALLETS:
                    HEALTH_WALLETS[phins_cust['id']] = {
                        'customer_id': phins_cust['id'],
                        'balance': phins_cust['wallet_balance'],
                        'monthly_deposit': pol_data['monthly_premium'] * 0.2,
                        'transactions': [] if phins_cust['wallet_balance'] == 0 else [{
                            'id': f'INIT-{phins_cust["id"]}',
                            'type': 'deposit',
                            'amount': phins_cust['wallet_balance'],
                            'timestamp': now.isoformat(),
                            'description': 'Initial policy savings'
                        }],
                        'created_at': now.isoformat()
                    }
                
                if phins_cust['id'] not in INVESTMENT_ACCOUNTS:
                    INVESTMENT_ACCOUNTS[phins_cust['id']] = {
                        'customer_id': phins_cust['id'],
                        'balance': phins_cust['investment_balance'],
                        'index_balance': phins_cust['investment_balance'] * 0.6,
                        'bonds_balance': phins_cust['investment_balance'] * 0.3,
                        'crypto_balance': phins_cust['investment_balance'] * 0.1,
                        'deposits': [],
                        'created_at': now.isoformat()
                    }
            
            logger.info(f"Synced {phins_cust['email']} to in-memory structures")
        
        # =================================================================
        # ADDITIONAL TEST CUSTOMERS WITH PENDING UNDERWRITING
        # (For testing purposes - can be suspended)
        # =================================================================
        additional_customers = [
            {
                'id': 'CUST-TEST-100',
                'name': 'Sarah Cohen',
                'email': 'sarah.cohen@test.com',
                'policy_type': 'phins_unified',
                'coverage': 750000,
                'age': 30,
                'gender': 'female',
                'risk_score': 'medium',
            },
            {
                'id': 'CUST-TEST-101',
                'name': 'David Levy',
                'email': 'david.levy@test.com',
                'policy_type': 'phins_unified',
                'coverage': 300000,
                'age': 30,
                'gender': 'male',
                'risk_score': 'medium',
            },
            {
                'id': 'CUST-TEST-102',
                'name': 'Rachel Green',
                'email': 'rachel.green@test.com',
                'policy_type': 'phins_unified',
                'coverage': 500000,
                'age': 30,
                'gender': 'female',
                'risk_score': 'medium',
            }
        ]
        
        # Import in-memory data structures for sync (skipped for DB-backed
        # stores — see _is_db_backed_store; the creates below already persist)
        try:
            from web_portal.server import CUSTOMERS, POLICIES, UNDERWRITING_APPLICATIONS, BILLING
            sync_to_memory = not _is_db_backed_store(CUSTOMERS)
        except ImportError:
            sync_to_memory = False
            logger.warning("Could not import in-memory data structures - database-only seeding")
        
        for cust_data in additional_customers:
            existing = customer_repo.find_one_by(email=cust_data['email'])
            if existing:
                logger.info(f"Customer {cust_data['email']} already exists, skipping...")
                continue
            
            # Test accounts - use env var or random password
            test_pwd = _get_env_password('PHINS_TEST_CUSTOMER_PASSWORD', cust_data['email'])
            pwd = hash_password(test_pwd)
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
            
            # Create pending kernel-priced PHINS unified policy
            pol_id = f"POL-{cust_data['id'].replace('CUST-', '')}"
            uw_id = f"UW-{cust_data['id'].replace('CUST-', '')}"
            try:
                quoted = _seed_policy_from_kernel(
                    policy_id=pol_id,
                    coverage_amount=cust_data['coverage'],
                    age=int(cust_data.get('age') or 30),
                    gender=cust_data.get('gender') or 'female',
                    smoking_status='never',
                    risk_score=cust_data.get('risk_score') or 'medium',
                    status='pending_underwriting',
                )
            except Exception as kern_err:
                logger.warning(f"Skipping non-kernel test policy for {cust_data['email']}: {kern_err}")
                continue
            annual_premium = quoted['annual_premium']
            monthly_premium = quoted['monthly_premium']
            
            policy = policy_repo.create(
                id=pol_id,
                customer_id=customer.id,
                type='phins_unified',
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
                customer_name=cust_data['name'],
                customer_email=cust_data['email'],
                policy_type='phins_unified',
                coverage_amount=float(cust_data['coverage']),
                status='pending',
                risk_assessment='medium',
                risk_score='medium',
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
                    'type': 'phins_unified',
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
                _pin_kernel_on_policy_dict(POLICIES[pol_id], quoted.get('kernel') or {})
                
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

        try:
            seed_supply_chain_data()
        except Exception as e:
            logger.error(f"Failed to seed supply chain data: {e}")
    
    logger.info("Database seeding completed!")


def seed_supply_chain_data():
    """
    Seed supply chain, marketplace, and delivery data for pipeline integrity.
    Ensures the supply chain ecosystem has baseline data for validation and testing.
    """
    logger.info("Seeding supply chain and marketplace data...")

    try:
        import web_portal.server as server
    except Exception:
        logger.warning("Cannot import server module; skipping supply chain seeding")
        return

    suppliers = getattr(server, 'SUPPLIERS', None)
    offers = getattr(server, 'SUPPLIER_OFFERS', None)
    invitations = getattr(server, 'SUPPLY_CHAIN_INVITATIONS', None)
    health_wallets = getattr(server, 'HEALTH_WALLETS', None)

    if suppliers is None or offers is None:
        logger.warning("SUPPLIERS or SUPPLIER_OFFERS stores not available")
        return

    now = datetime.now(timezone.utc)

    seed_suppliers = [
        {
            "id": "SUP-SEED-PHARMA-001",
            "company_name": "HealthFirst Pharmacy",
            "contact_email": "contact@healthfirst.com",
            "contact_name": "Dr. Rachel Green",
            "supplier_type": "pharmacy",
            "category": "medical",
            "status": "approved",
            "invitation_code": "PHINS-SEED-PHARMA",
            "commission_rate": 9.0,
            "license_number": "PH-2024-98765",
            "average_rating": 4.7,
            "total_orders": 42,
            "completed_orders": 40,
            "total_revenue": 8500.0,
            "total_commission_paid": 765.0,
            "on_time_delivery_rate": 97.0,
            "dispute_count": 0,
            "portal_active": True,
            "approval_date": now.isoformat(),
            "created_date": now.isoformat(),
            "updated_date": now.isoformat()
        },
        {
            "id": "SUP-SEED-DELIVERY-001",
            "company_name": "MediExpress Delivery",
            "contact_email": "ops@mediexpress.com",
            "contact_name": "David Cohen",
            "supplier_type": "delivery",
            "category": "logistics",
            "status": "approved",
            "invitation_code": "PHINS-SEED-DELIV",
            "commission_rate": 15.0,
            "average_rating": 4.5,
            "total_orders": 120,
            "completed_orders": 115,
            "total_revenue": 18000.0,
            "total_commission_paid": 2700.0,
            "on_time_delivery_rate": 94.0,
            "dispute_count": 1,
            "portal_active": True,
            "service_areas": '["Tel Aviv", "Jerusalem", "Haifa", "nationwide"]',
            "approval_date": now.isoformat(),
            "created_date": now.isoformat(),
            "updated_date": now.isoformat()
        },
        {
            "id": "SUP-SEED-DOCTOR-001",
            "company_name": "Assuta Medical Group",
            "contact_email": "admin@assuta-med.com",
            "contact_name": "Dr. Sarah Levi",
            "supplier_type": "doctor",
            "category": "medical",
            "status": "approved",
            "invitation_code": "PHINS-SEED-DOC",
            "commission_rate": 8.0,
            "license_number": "MD-2023-54321",
            "insurance_certificate": "INS-CERT-ASSUTA-2026",
            "average_rating": 4.9,
            "total_orders": 85,
            "completed_orders": 85,
            "total_revenue": 42500.0,
            "total_commission_paid": 3400.0,
            "on_time_delivery_rate": 100.0,
            "dispute_count": 0,
            "portal_active": True,
            "approval_date": now.isoformat(),
            "created_date": now.isoformat(),
            "updated_date": now.isoformat()
        }
    ]

    for sup in seed_suppliers:
        if sup['id'] not in suppliers:
            suppliers[sup['id']] = sup
            logger.info(f"  Seeded supplier: {sup['company_name']}")

    seed_offers = [
        {
            "id": "OFF-SEED-001",
            "supplier_id": "SUP-SEED-PHARMA-001",
            "name": "Prescription Medication Package",
            "description": "Standard prescription fulfillment with pharmacist consultation",
            "item_type": "product",
            "category": "pharmacy",
            "price": 45.00,
            "currency": "USD",
            "active": True,
            "offer_status": "approved",
            "wallet_compatible": ["health"],
            "delivery_config": {"mode": "delivery", "eta_days": 2, "fee": 5.00},
            "billing_config": {"billing_cycle": "one_time", "invoice_supported": True, "tax_rate_pct": 0.0},
            "created_date": now.isoformat(),
            "updated_date": now.isoformat(),
            "total_orders": 30,
            "total_revenue": 1350.0,
            "average_rating": 4.8
        },
        {
            "id": "OFF-SEED-002",
            "supplier_id": "SUP-SEED-DOCTOR-001",
            "name": "Telemedicine Consultation",
            "description": "30-minute video consultation with board-certified physician",
            "item_type": "service",
            "category": "medical",
            "price": 120.00,
            "currency": "USD",
            "active": True,
            "offer_status": "approved",
            "wallet_compatible": ["health"],
            "delivery_config": {"mode": "on_site", "eta_days": 0, "fee": 0.0},
            "billing_config": {"billing_cycle": "one_time", "invoice_supported": True, "tax_rate_pct": 0.0},
            "created_date": now.isoformat(),
            "updated_date": now.isoformat(),
            "total_orders": 50,
            "total_revenue": 6000.0,
            "average_rating": 4.9
        },
        {
            "id": "OFF-SEED-003",
            "supplier_id": "SUP-SEED-PHARMA-001",
            "name": "Wellness Supplement Kit",
            "description": "Monthly wellness supplement kit with vitamins and minerals",
            "item_type": "product",
            "category": "wellness",
            "price": 65.00,
            "currency": "USD",
            "active": True,
            "offer_status": "approved",
            "wallet_compatible": ["health"],
            "delivery_config": {"mode": "delivery", "eta_days": 3, "fee": 0.0},
            "billing_config": {"billing_cycle": "monthly", "invoice_supported": True, "tax_rate_pct": 0.0},
            "created_date": now.isoformat(),
            "updated_date": now.isoformat(),
            "total_orders": 15,
            "total_revenue": 975.0,
            "average_rating": 4.6
        }
    ]

    for offer in seed_offers:
        if offer['id'] not in offers:
            offers[offer['id']] = offer
            logger.info(f"  Seeded offer: {offer['name']}")

    if invitations is not None:
        seed_invitations = {
            "PHINS-SEED-PHARMA": {
                "code": "PHINS-SEED-PHARMA",
                "created_at": now.isoformat(),
                "created_by": "admin",
                "supplier_type": "pharmacy",
                "expires_at": (now + timedelta(days=365)).isoformat(),
                "max_uses": 1,
                "used_count": 1,
                "used_by": ["SUP-SEED-PHARMA-001"],
                "status": "used"
            },
            "PHINS-SEED-DELIV": {
                "code": "PHINS-SEED-DELIV",
                "created_at": now.isoformat(),
                "created_by": "admin",
                "supplier_type": "delivery",
                "expires_at": (now + timedelta(days=365)).isoformat(),
                "max_uses": 1,
                "used_count": 1,
                "used_by": ["SUP-SEED-DELIVERY-001"],
                "status": "used"
            },
            "PHINS-SEED-DOC": {
                "code": "PHINS-SEED-DOC",
                "created_at": now.isoformat(),
                "created_by": "admin",
                "supplier_type": "doctor",
                "expires_at": (now + timedelta(days=365)).isoformat(),
                "max_uses": 1,
                "used_count": 1,
                "used_by": ["SUP-SEED-DOCTOR-001"],
                "status": "used"
            }
        }
        for code, inv in seed_invitations.items():
            if code not in invitations:
                invitations[code] = inv

    if health_wallets:
        for cid, wallet in health_wallets.items():
            if 'supply_chain_enabled' not in wallet:
                wallet['supply_chain_enabled'] = True

    logger.info("Supply chain and marketplace data seeded successfully")


if __name__ == '__main__':
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Seed with sample data when run directly
    seed_database(include_sample_data=True)
