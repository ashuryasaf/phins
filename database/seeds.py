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
# Known false demo policies. Seed must not create them; restart seed
# removes only these IDs and records keyed to them. Unknown real policies
# are never swept.
FALSE_DEMO_POLICY_IDS = (
    'POL-ASAF-LIFE-001',
    'POL-ASAF-HEALTH-001',
    'POL-ASAF-AUTO-001',
    'POL-EFRAT-UNIFIED-001',
    'POL-ASI-UNIFIED-001',
    'POL-SHOSH-UNIFIED-001',
    'POL-TEST-100',
    'POL-TEST-101',
    'POL-TEST-102',
)
FALSE_DEMO_POLICY_ID_SET = frozenset(FALSE_DEMO_POLICY_IDS)
FALSE_TEST_CUSTOMER_IDS = (
    'CUST-TEST-100',  # Sarah Cohen
    'CUST-TEST-101',  # David Levy
    'CUST-TEST-102',  # Rachel Green
)
FALSE_TEST_CUSTOMER_ID_SET = frozenset(FALSE_TEST_CUSTOMER_IDS)
FALSE_TEST_CUSTOMER_EMAILS = (
    'sarah.cohen@test.com',
    'david.levy@test.com',
    'rachel.green@test.com',
)
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


def _row_policy_id(row) -> str:
    if isinstance(row, dict):
        return str(row.get('policy_id') or '')
    return str(getattr(row, 'policy_id', '') or '')


def _row_customer_id(row) -> str:
    if isinstance(row, dict):
        return str(row.get('customer_id') or '')
    return str(getattr(row, 'customer_id', '') or '')


def _row_id(row) -> str:
    if isinstance(row, dict):
        return str(row.get('id') or '')
    return str(getattr(row, 'id', '') or '')


def _row_matches_false_demo(row) -> bool:
    """True when a store/repo row is keyed to a known false demo policy or test customer."""
    if row is None:
        return False
    rid = _row_id(row)
    return (
        rid in FALSE_DEMO_POLICY_ID_SET
        or rid in FALSE_TEST_CUSTOMER_ID_SET
        or _row_policy_id(row) in FALSE_DEMO_POLICY_ID_SET
        or _row_customer_id(row) in FALSE_TEST_CUSTOMER_ID_SET
    )


def _safe_delete_repo_row(repo, row_id, label: str) -> None:
    if repo is None or not row_id:
        return
    try:
        if hasattr(repo, 'delete') and repo.delete(row_id):
            logger.info(f"Removed false demo {label} {row_id}")
    except Exception as exc:
        logger.warning(f"Could not remove false demo {label} {row_id}: {exc}")


def _safe_pop_store(store, key) -> None:
    if store is None or key not in store:
        return
    try:
        del store[key]
    except Exception:
        try:
            store.pop(key, None)
        except Exception:
            pass


FALSE_DEMO_LEDGER_PREFIXES = (
    'TX-POL-ASAF',
    'TX-POL-EFRAT',
    'TX-BILL-ASAF',
    'TX-BILL-EFRAT',
    'TX-CLM-ASAF',
)


def _ledger_entry_is_false_demo(tx_id, tx, removed_claim_ids) -> bool:
    """True when a ledger row is keyed to a known false demo policy/claim/customer."""
    tx = tx if isinstance(tx, dict) else {}
    meta = tx.get('metadata') if isinstance(tx.get('metadata'), dict) else {}
    policy_id = str(tx.get('policy_id') or meta.get('policy_id') or '')
    claim_id = str(tx.get('claim_id') or meta.get('claim_id') or '')
    customer_id = str(tx.get('customer_id') or meta.get('customer_id') or '')
    return (
        policy_id in FALSE_DEMO_POLICY_ID_SET
        or customer_id in FALSE_TEST_CUSTOMER_ID_SET
        or claim_id in removed_claim_ids
        or str(tx_id).startswith(FALSE_DEMO_LEDGER_PREFIXES)
    )


def _wallet_balance_from_remaining_txs(txs) -> float:
    """Reconstruct a wallet balance from remaining txs; never return negative."""
    total = 0.0
    for tx in txs:
        if not isinstance(tx, dict):
            continue
        try:
            amount = float(tx.get('amount') or 0)
        except (TypeError, ValueError):
            continue
        tx_type = str(tx.get('type') or '').lower()
        if amount < 0 or tx_type in (
            'purchase', 'debit', 'withdrawal', 'spend', 'payment', 'medical_purchase'
        ):
            total -= abs(amount)
        else:
            total += amount
    return round(max(0.0, total), 2)


def _false_demo_purge_journal_path(kind: str) -> str:
    try:
        from web_portal.server import LEDGER_PERSISTENCE_FILE
        base = os.path.dirname(LEDGER_PERSISTENCE_FILE) or '.'
    except Exception:
        base = os.environ.get('TMPDIR') or '/tmp'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    return os.path.join(base, f'phins_false_demo_{kind}_{stamp}.json')


def _write_false_demo_purge_journal(path: str, payload: dict) -> None:
    """Fail closed: raise if the forensic journal cannot be written."""
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    tmp_path = f'{path}.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, indent=2, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def _payload_dict(row) -> dict:
    payload = getattr(row, 'payload', None)
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str) and payload:
        try:
            parsed = json.loads(payload)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return {}


def _false_demo_ids_from_repo(repo) -> list:
    """Primary keys on a repo keyed to known false demo policies or test customers."""
    found = []
    seen = set()
    if repo is None:
        return found
    for policy_id in FALSE_DEMO_POLICY_IDS:
        try:
            rows = repo.filter_by(policy_id=policy_id) or []
        except Exception:
            rows = []
        for row in rows:
            rid = getattr(row, 'id', None)
            if rid and str(rid) not in seen:
                seen.add(str(rid))
                found.append(str(rid))
    for customer_id in FALSE_TEST_CUSTOMER_IDS:
        try:
            rows = repo.filter_by(customer_id=customer_id) or []
        except Exception:
            rows = []
        for row in rows:
            rid = getattr(row, 'id', None)
            if rid and str(rid) not in seen:
                seen.add(str(rid))
                found.append(str(rid))
    return found


def _collect_false_demo_claim_ids_from_db() -> list:
    """List SQL claim IDs before policy deletes cascade them away."""
    try:
        from database.manager import DatabaseManager
    except ImportError:
        return []
    try:
        with DatabaseManager() as db:
            return _false_demo_ids_from_repo(db.claims)
    except Exception as exc:
        logger.warning(f"False-demo claim id collection skipped: {exc}")
        return []


def _purge_false_demo_seed(
    policy_repo=None,
    billing_repo=None,
    claim_repo=None,
    underwriting_repo=None,
    customer_repo=None,
    user_repo=None,
    sync_memory: bool = True,
) -> dict:
    """Remove known false demo policies, the three QA test customers, and related records.

    Scoped to FALSE_DEMO_POLICY_IDS and FALSE_TEST_CUSTOMER_IDS only. Live
    PHINS customers (Asaf/Efrat/Asi/Shosh), persisted wallets for those
    accounts, and unknown real rows are left in place. No reversing cash is
    invented; known demo ledger rows are dropped and the remaining hash
    chain is rebuilt.
    """
    removed = {
        'policies': 0, 'bills': 0, 'claims': 0, 'uw': 0,
        'customers': 0, 'users': 0, 'ledger': 0,
    }
    POLICIES = BILLING = CLAIMS = UNDERWRITING_APPLICATIONS = None
    TRANSACTION_LEDGER = HEALTH_WALLETS = NFT_LEDGER = None
    CUSTOMERS = INVESTMENT_ACCOUNTS = CUSTOMER_ALLOCATIONS = USERS = None
    if sync_memory:
        try:
            from web_portal.server import (
                BILLING as _B,
                CLAIMS as _C,
                CUSTOMER_ALLOCATIONS as _A,
                CUSTOMERS as _CU,
                HEALTH_WALLETS as _W,
                INVESTMENT_ACCOUNTS as _I,
                NFT_LEDGER as _N,
                POLICIES as _P,
                TRANSACTION_LEDGER as _T,
                UNDERWRITING_APPLICATIONS as _U,
                USERS as _USERS,
            )
            POLICIES, BILLING, CLAIMS = _P, _B, _C
            UNDERWRITING_APPLICATIONS, TRANSACTION_LEDGER = _U, _T
            HEALTH_WALLETS, NFT_LEDGER = _W, _N
            CUSTOMERS, INVESTMENT_ACCOUNTS = _CU, _I
            CUSTOMER_ALLOCATIONS, USERS = _A, _USERS
        except ImportError:
            pass

    removed_claim_ids = set(_collect_false_demo_claim_ids_from_db())

    def _collect_repo_ids(repo):
        ids = []
        seen = set()
        if repo is None:
            return ids

        def _take(rows):
            for row in rows or []:
                rid = getattr(row, 'id', None)
                if not rid:
                    continue
                key = str(rid)
                if key in seen:
                    continue
                seen.add(key)
                ids.append(key)
                if repo is claim_repo:
                    removed_claim_ids.add(key)

        for policy_id in FALSE_DEMO_POLICY_IDS:
            try:
                _take(repo.filter_by(policy_id=policy_id) or [])
            except Exception:
                pass
        for customer_id in FALSE_TEST_CUSTOMER_IDS:
            try:
                _take(repo.filter_by(customer_id=customer_id) or [])
            except Exception:
                pass
        return ids

    for claim_id in _collect_repo_ids(claim_repo):
        _safe_delete_repo_row(claim_repo, claim_id, 'claim')
        removed['claims'] += 1
    for bill_id in _collect_repo_ids(billing_repo):
        _safe_delete_repo_row(billing_repo, bill_id, 'bill')
        removed['bills'] += 1
    for uw_id in _collect_repo_ids(underwriting_repo):
        _safe_delete_repo_row(underwriting_repo, uw_id, 'underwriting')
        removed['uw'] += 1

    policy_ids_to_drop = list(FALSE_DEMO_POLICY_IDS)
    if policy_repo is not None:
        for customer_id in FALSE_TEST_CUSTOMER_IDS:
            try:
                extra = policy_repo.filter_by(customer_id=customer_id) or []
            except Exception:
                extra = []
            for row in extra:
                pid = getattr(row, 'id', None)
                if pid and str(pid) not in policy_ids_to_drop:
                    policy_ids_to_drop.append(str(pid))
        for policy_id in policy_ids_to_drop:
            existing = None
            try:
                existing = policy_repo.find_one_by(id=policy_id)
            except Exception:
                existing = None
            if existing:
                _safe_delete_repo_row(policy_repo, policy_id, 'policy')
                removed['policies'] += 1

    for customer_id in FALSE_TEST_CUSTOMER_IDS:
        existed = False
        if customer_repo is not None:
            try:
                existed = customer_repo.find_one_by(id=customer_id) is not None
            except Exception:
                existed = False
        _safe_delete_repo_row(customer_repo, customer_id, 'customer')
        if existed:
            removed['customers'] += 1
    for email in FALSE_TEST_CUSTOMER_EMAILS:
        existed_user = False
        if user_repo is not None:
            try:
                if hasattr(user_repo, 'get_by_username'):
                    existed_user = user_repo.get_by_username(email) is not None
                else:
                    existed_user = user_repo.find_one_by(username=email) is not None
            except Exception:
                existed_user = False
        _safe_delete_repo_row(user_repo, email, 'user')
        if existed_user:
            removed['users'] += 1

    if CLAIMS is not None:
        for claim_id in list(CLAIMS.keys()):
            row = CLAIMS.get(claim_id) or {}
            if _row_matches_false_demo(row):
                removed_claim_ids.add(str(claim_id))
                _safe_pop_store(CLAIMS, claim_id)
                removed['claims'] += 1
    if BILLING is not None:
        for bill_id in list(BILLING.keys()):
            row = BILLING.get(bill_id) or {}
            if _row_matches_false_demo(row):
                _safe_pop_store(BILLING, bill_id)
                removed['bills'] += 1
    if UNDERWRITING_APPLICATIONS is not None:
        for uw_id in list(UNDERWRITING_APPLICATIONS.keys()):
            row = UNDERWRITING_APPLICATIONS.get(uw_id) or {}
            if _row_matches_false_demo(row):
                _safe_pop_store(UNDERWRITING_APPLICATIONS, uw_id)
                removed['uw'] += 1
    if POLICIES is not None:
        for policy_id in list(POLICIES.keys()):
            row = POLICIES.get(policy_id) or {}
            if (
                str(policy_id) in FALSE_DEMO_POLICY_ID_SET
                or _row_matches_false_demo(row)
            ):
                _safe_pop_store(POLICIES, policy_id)
                removed['policies'] += 1

    if HEALTH_WALLETS is not None:
        for customer_id in FALSE_TEST_CUSTOMER_IDS:
            _safe_pop_store(HEALTH_WALLETS, customer_id)
        for wallet in list(HEALTH_WALLETS.values()):
            if not isinstance(wallet, dict):
                continue
            txs = list(wallet.get('transactions') or [])
            kept = []
            deducted = 0.0
            for tx in txs:
                if not isinstance(tx, dict):
                    kept.append(tx)
                    continue
                tx_id = str(tx.get('id') or '')
                claim_id = str(tx.get('claim_id') or '')
                drop = (
                    claim_id in removed_claim_ids
                    or tx_id.startswith('CLAIM-PAY-SEED-CLM-ASAF')
                    or str(tx.get('policy_id') or '') in FALSE_DEMO_POLICY_ID_SET
                    or str(tx.get('customer_id') or '') in FALSE_TEST_CUSTOMER_ID_SET
                )
                if drop:
                    try:
                        deducted += float(tx.get('amount') or 0)
                    except (TypeError, ValueError):
                        pass
                    continue
                kept.append(tx)
            if deducted:
                wallet['transactions'] = kept
                remaining_have_amounts = any(
                    isinstance(tx, dict) and tx.get('amount') not in (None, '')
                    for tx in kept
                )
                if not kept:
                    wallet['balance'] = 0.0
                elif remaining_have_amounts:
                    wallet['balance'] = _wallet_balance_from_remaining_txs(kept)
                else:
                    try:
                        wallet['balance'] = round(
                            max(0.0, float(wallet.get('balance') or 0) - deducted),
                            2,
                        )
                    except (TypeError, ValueError):
                        wallet['balance'] = 0.0

    if INVESTMENT_ACCOUNTS is not None:
        for customer_id in FALSE_TEST_CUSTOMER_IDS:
            _safe_pop_store(INVESTMENT_ACCOUNTS, customer_id)
    if CUSTOMER_ALLOCATIONS is not None:
        for customer_id in FALSE_TEST_CUSTOMER_IDS:
            _safe_pop_store(CUSTOMER_ALLOCATIONS, customer_id)
    if CUSTOMERS is not None:
        for customer_id in FALSE_TEST_CUSTOMER_IDS:
            if customer_id in CUSTOMERS:
                _safe_pop_store(CUSTOMERS, customer_id)
                removed['customers'] += 1
    if USERS is not None:
        for email in FALSE_TEST_CUSTOMER_EMAILS:
            present = False
            try:
                present = email in USERS
            except Exception:
                present = False
            if present:
                _safe_pop_store(USERS, email)
                removed['users'] += 1

    try:
        from web_portal.server import SUSPENDED_TEST_ACCOUNTS as _SUSPENDED
        for customer_id in FALSE_TEST_CUSTOMER_IDS:
            _SUSPENDED.discard(customer_id)
    except Exception:
        pass

    # Durable operational rows must run before ledger matching so SQL-only
    # claim IDs (boot with no repos / unhydrated CLAIMS) still drop cash rows.
    db_ops = _purge_false_demo_records_from_db(removed_claim_ids)
    removed_claim_ids.update(str(cid) for cid in (db_ops.get('claim_ids') or []))
    for key in ('policies', 'bills', 'claims', 'uw', 'customers', 'users'):
        removed[key] += db_ops.get(key, 0)

    if TRANSACTION_LEDGER is not None:
        for tx_id in list(TRANSACTION_LEDGER.keys()):
            tx = TRANSACTION_LEDGER.get(tx_id) or {}
            if _ledger_entry_is_false_demo(tx_id, tx, removed_claim_ids):
                _safe_pop_store(TRANSACTION_LEDGER, tx_id)
                removed['ledger'] += 1
        try:
            from web_portal.server import platform_event_ledger
            platform_event_ledger.ensure_hash_chain()
        except Exception as exc:
            logger.warning(f"Ledger chain rebuild after false-demo purge skipped: {exc}")

    db_deleted = _purge_false_demo_ledger_from_db(removed_claim_ids)
    removed['ledger'] += db_deleted
    if TRANSACTION_LEDGER is not None:
        try:
            from web_portal.server import mark_ledger_dirty, platform_event_ledger
            backup_path = _false_demo_purge_journal_path('chain_repair')
            persist_summary = platform_event_ledger.persist_chain_to_db(
                backup_path=backup_path,
            )
            if persist_summary.get('applied') and persist_summary.get('verified') is False:
                logger.error(
                    "False-demo ledger persist verification failed: %s",
                    persist_summary,
                )
            elif persist_summary.get('reason') and persist_summary.get('reason') not in (
                'db chain already consistent',
                'database disabled',
                'in-memory ledger empty',
            ):
                logger.warning(
                    "False-demo ledger persist skipped: %s",
                    persist_summary.get('reason'),
                )
            try:
                mark_ledger_dirty()
            except Exception:
                pass
        except Exception as exc:
            logger.warning(f"Durable ledger persist after false-demo purge skipped: {exc}")

    if NFT_LEDGER is not None:
        for token_id in list(NFT_LEDGER.keys()):
            row = NFT_LEDGER.get(token_id) or {}
            meta = row.get('metadata') if isinstance(row, dict) else {}
            if not isinstance(meta, dict):
                meta = {}
            if (
                str(meta.get('policy_id') or '') in FALSE_DEMO_POLICY_ID_SET
                or str(meta.get('claim_id') or '') in removed_claim_ids
                or str(meta.get('customer_id') or row.get('customer_id') or '')
                in FALSE_TEST_CUSTOMER_ID_SET
                or str(row.get('transaction_id') or '').startswith(
                    ('TX-POL-ASAF', 'TX-POL-EFRAT', 'TX-BILL-ASAF', 'TX-BILL-EFRAT', 'TX-CLM-ASAF')
                )
            ):
                _safe_pop_store(NFT_LEDGER, token_id)

    return removed


def _purge_false_demo_records_from_db(removed_claim_ids=None) -> dict:
    """Delete known false-demo operational rows even when seed repos were not passed.

    Boot calls `_purge_false_demo_seed(sync_memory=True)` without repositories.
    Memory DatabaseDict pops are durable in DB mode, but a hydrated plain dict
    would otherwise restore CUST-TEST-* / POL-TEST-* on the next load.
    Collected claim IDs are returned and added to `removed_claim_ids` so
    claim-keyed ledger cash can be dropped even when in-memory CLAIMS was
    empty. Unknown real rows are never swept.
    """
    counts = {
        'policies': 0, 'bills': 0, 'claims': 0, 'uw': 0,
        'customers': 0, 'users': 0, 'claim_ids': [],
    }
    try:
        from database.manager import DatabaseManager
    except ImportError:
        return counts
    try:
        with DatabaseManager() as db:
            claim_ids = _false_demo_ids_from_repo(db.claims)
            counts['claim_ids'] = list(claim_ids)
            if removed_claim_ids is not None:
                removed_claim_ids.update(claim_ids)
            for claim_id in claim_ids:
                if db.claims.delete(claim_id):
                    counts['claims'] += 1
                    logger.info(f"Removed false demo claim {claim_id}")
            for bill_id in _false_demo_ids_from_repo(db.billing):
                if db.billing.delete(bill_id):
                    counts['bills'] += 1
                    logger.info(f"Removed false demo bill {bill_id}")
            for uw_id in _false_demo_ids_from_repo(db.underwriting):
                if db.underwriting.delete(uw_id):
                    counts['uw'] += 1
                    logger.info(f"Removed false demo underwriting {uw_id}")

            policy_ids = list(FALSE_DEMO_POLICY_IDS)
            for customer_id in FALSE_TEST_CUSTOMER_IDS:
                try:
                    extra = db.policies.filter_by(customer_id=customer_id) or []
                except Exception:
                    extra = []
                for row in extra:
                    pid = getattr(row, 'id', None)
                    if pid and str(pid) not in policy_ids:
                        policy_ids.append(str(pid))
            for policy_id in policy_ids:
                if db.policies.get_by_id(policy_id) is not None and db.policies.delete(policy_id):
                    counts['policies'] += 1
                    logger.info(f"Removed false demo policy {policy_id}")
            for customer_id in FALSE_TEST_CUSTOMER_IDS:
                if db.customers.get_by_id(customer_id) is not None and db.customers.delete(customer_id):
                    counts['customers'] += 1
                    logger.info(f"Removed false test customer {customer_id}")
            for email in FALSE_TEST_CUSTOMER_EMAILS:
                try:
                    existing = db.users.get_by_username(email)
                except Exception:
                    existing = None
                if existing is not None and db.users.delete(email):
                    counts['users'] += 1
                    logger.info(f"Removed false test user {email}")
    except Exception as exc:
        logger.warning(f"Durable false-demo operational purge skipped: {exc}")
        return counts
    return counts


def _purge_false_demo_ledger_from_db(removed_claim_ids) -> int:
    """Delete known false-demo rows from platform_ledger_entries.

    Writes a forensic journal first and fails closed if that journal cannot
    be stored. Unknown real ledger rows are never swept.
    """
    deleted = 0
    try:
        from database.manager import DatabaseManager
    except ImportError:
        return 0
    try:
        with DatabaseManager() as db:
            rows = db.platform_ledger.get_all_by_sequence() or []
            to_delete = []
            for row in rows:
                if row is None or not getattr(row, 'id', None):
                    continue
                payload = _payload_dict(row)
                if _ledger_entry_is_false_demo(row.id, payload, removed_claim_ids):
                    to_delete.append(row)
            if not to_delete:
                return 0
            journal_path = _false_demo_purge_journal_path('ledger_delete')
            try:
                _write_false_demo_purge_journal(
                    journal_path,
                    {
                        'schema': 'phins.ledger.false_demo_purge.v1',
                        'backed_up_at': datetime.now(timezone.utc).isoformat(),
                        'removed_ids': [row.id for row in to_delete],
                        'rows': [
                            row.to_dict() if hasattr(row, 'to_dict') else {'id': row.id}
                            for row in to_delete
                        ],
                    },
                )
            except OSError as journal_exc:
                logger.error(
                    "False-demo ledger purge journal could not be written (%s); "
                    "refusing to delete %d platform_ledger rows",
                    journal_exc,
                    len(to_delete),
                )
                return 0
            for row in to_delete:
                if db.platform_ledger.delete(row.id):
                    deleted += 1
                    logger.info(f"Removed false demo ledger row {row.id}")
    except Exception as exc:
        logger.warning(f"Durable false-demo ledger purge skipped: {exc}")
        return deleted
    return deleted


def _retire_non_kernel_demo_seed(policy_repo, billing_repo, claim_repo, sync_memory: bool) -> None:
    """Back-compat wrapper: purge the known false demo policy set."""
    _purge_false_demo_seed(
        policy_repo=policy_repo,
        billing_repo=billing_repo,
        claim_repo=claim_repo,
        sync_memory=sync_memory,
    )


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
                'username': 'regulator',
                'password_env': 'PHINS_REGULATOR_PASSWORD',
                'role': 'regulator',
                'name': 'Regulation Viewer',
                'email': 'regulator@phins.ai'
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
            ClaimRepository, UserRepository
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

        # False demo policies (Asaf life/health/auto, Efrat/Asi/Shosh unified)
        # are not seeded. Purge known IDs and every bill/claim/UW keyed to them.
        claim_repo = ClaimRepository(session)
        user_repo = UserRepository(session)
        # Always sync in-memory ledger/wallets too: TRANSACTION_LEDGER is not
        # a DatabaseDict, so repo-only purge would leave false demo cash rows.
        _purge_false_demo_seed(
            policy_repo=policy_repo,
            billing_repo=billing_repo,
            claim_repo=claim_repo,
            underwriting_repo=underwriting_repo,
            customer_repo=customer_repo,
            user_repo=user_repo,
            sync_memory=True,
        )

        # =================================================================
        # PHINS CUSTOMER ACCOUNTS - PERMANENT DATA (efrat, asi, shosh)
        # These customers are primary platform users with full data persistence.
        # False demo policies for these accounts are not seeded.
        # =================================================================
        efrat_age = _age_from_dob('1990-06-15')
        asi_age = _age_from_dob('1985-03-20')
        shosh_age = _age_from_dob('1988-09-10')

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
                'wallet_balance': 0.0,
                'investment_balance': 0.0
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
                'wallet_balance': 0.0,
                'investment_balance': 0.0
            }
        ]
        
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
            
            # Mirror the customer even when no demo policy is seeded.
            if sync_to_memory and phins_cust['id'] not in CUSTOMERS:
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

            # Create/verify policy — skipped: these accounts have no demo policy.
            pol_data = phins_cust.get('policy')
            existing_policy = None
            existing_app = None
            if pol_data:
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
                        'monthly_deposit': 0.0,
                        'transactions': [] if phins_cust['wallet_balance'] == 0 else [{
                            'id': f'INIT-{phins_cust["id"]}',
                            'type': 'deposit',
                            'amount': phins_cust['wallet_balance'],
                            'timestamp': now.isoformat(),
                            'description': 'Initial wallet balance'
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

        # QA test customers (Sarah/David/Rachel, CUST-TEST-100/101/102) are
        # not seeded. Purge those known IDs and every related record.
        _purge_false_demo_seed(
            policy_repo=policy_repo,
            billing_repo=billing_repo,
            claim_repo=claim_repo,
            underwriting_repo=underwriting_repo,
            customer_repo=customer_repo,
            user_repo=user_repo,
            sync_memory=True,
        )
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
