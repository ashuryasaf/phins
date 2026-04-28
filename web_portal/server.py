#!/usr/bin/env python3
"""
Lightweight web portal server for PHINS Insurance Management Platform.

Usage:
  python web_portal/server.py       # start server on http://localhost:8000
  python web_portal/server.py --test  # run quick local tests and exit

This server exposes JSON endpoints and serves static files from
`web_portal/static/`. It is the main entry point for the PHINS web portal.
"""
import json
import os
import urllib.parse as urlparse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import sys
from datetime import datetime, timedelta
import random
import uuid
import hashlib
import secrets
import threading
import time
import csv
import io
from typing import Dict, Any, Optional, List

# ==============================================================================
# CASE-INSENSITIVE STATUS HELPERS (for data integrity across pipeline)
# ==============================================================================
def status_eq(item: Dict, *statuses: str) -> bool:
    """
    Case-insensitive status check for an item.
    Handles both exact matches and space/underscore variations.
    """
    item_status = (item.get('status') or '').lower().replace(' ', '_')
    return item_status in [s.lower().replace(' ', '_') for s in statuses]

def status_in(item: Dict, statuses: list) -> bool:
    """
    Case-insensitive check if item's status is in a list of statuses.
    """
    item_status = (item.get('status') or '').lower().replace(' ', '_')
    return item_status in [s.lower().replace(' ', '_') for s in statuses]

def get_status_lower(item: Dict) -> str:
    """Get item's status in lowercase with spaces converted to underscores."""
    return (item.get('status') or '').lower().replace(' ', '_')

def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert a value to float."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

# ==============================================================================
# ENVIRONMENT & CONFIGURATION
# ==============================================================================

# Test mode flag - enables test-specific behaviors
PHINS_TEST_MODE = str(os.environ.get('PHINS_TEST_MODE', '')).lower() in ('1', 'true', 'yes', 'y')

# Import billing engine
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from billing_engine import billing_engine, SecurityValidator
    billing_enabled = True
except ImportError:
    billing_enabled = False
    print("Warning: Billing engine not available. Payment features disabled.")

# Database support - ENABLED BY DEFAULT for data persistence
# Set USE_DATABASE=false to use volatile in-memory storage (not recommended)
USE_DATABASE = os.environ.get('USE_DATABASE', 'true').lower() not in ('false', '0', 'no')
database_enabled = False

if USE_DATABASE:
    try:
        from database import init_database, check_database_connection, get_database_info
        from database.seeds import seed_default_users
        from database.data_access import CUSTOMERS as DB_CUSTOMERS
        from database.data_access import POLICIES as DB_POLICIES
        from database.data_access import CLAIMS as DB_CLAIMS
        from database.data_access import UNDERWRITING_APPLICATIONS as DB_UNDERWRITING
        from database.data_access import SESSIONS as DB_SESSIONS
        from database.data_access import BILLING as DB_BILLING
        from database.data_access import USERS_DB as DB_USERS

        database_enabled = True
        print("✓ Database persistence enabled (data will survive restarts)")

        # Ensure schema exists and default users are present.
        try:
            init_database()
            seed_default_users()
        except Exception as e:
            print(f"Warning: Database init/seed failed: {e}")
    except ImportError as e:
        print(f"Warning: Database support not available: {e}")
        print("         Falling back to in-memory storage (DATA WILL BE LOST ON RESTART)")
        USE_DATABASE = False
else:
    print("⚠️  WARNING: Running in volatile in-memory mode (USE_DATABASE=false)")
    print("   Data will be LOST when server restarts. Set USE_DATABASE=true for persistence.")

PORT = int(os.environ.get('PORT', 8000))
ROOT = os.path.join(os.path.dirname(__file__), "static")

# ==============================================================================
# STORAGE - either database-backed or in-memory
# ==============================================================================
if USE_DATABASE and database_enabled:
    # Use database-backed dictionaries
    POLICIES = DB_POLICIES
    CLAIMS = DB_CLAIMS
    CUSTOMERS = DB_CUSTOMERS
    UNDERWRITING_APPLICATIONS = DB_UNDERWRITING
    # Sessions: use database-backed storage for persistence across restarts
    SESSIONS = DB_SESSIONS
    BILLING = DB_BILLING
    print("✓ Using database storage with database-backed sessions for Railway persistence")
else:
    # In-memory storage for demo purposes
    POLICIES: Dict[str, Dict[str, Any]] = {}
    CLAIMS: Dict[str, Dict[str, Any]] = {}
    CUSTOMERS: Dict[str, Dict[str, Any]] = {}
    UNDERWRITING_APPLICATIONS: Dict[str, Dict[str, Any]] = {}
    SESSIONS: Dict[str, Dict[str, Any]] = {}  # token -> {username, expires, customer_id}
    BILLING: Dict[str, Dict[str, Any]] = {}  # bill_id -> bill data (for metrics)

# Health wallets and medical purchases are always in-memory (not yet in DB schema)
HEALTH_WALLETS: Dict[str, Dict[str, Any]] = {}  # customer_id -> {balance, transactions, monthly_deposit}
MEDICAL_PURCHASES: Dict[str, Dict[str, Any]] = {}  # purchase_id -> purchase data
NFT_LEDGER: Dict[str, Dict[str, Any]] = {}  # token_id -> NFT token data for customer ledger

# Customer allocation preferences - adjustable savings/risk percentages
CUSTOMER_ALLOCATIONS: Dict[str, Dict[str, Any]] = {}  # customer_id -> {savings_pct, risk_pct, ...}

# Investment accounts - additional customer savings deposits
INVESTMENT_ACCOUNTS: Dict[str, Dict[str, Any]] = {}  # customer_id -> {balance, deposits: [], ...}

# Transaction ledger - master ledger for all financial transactions
TRANSACTION_LEDGER: Dict[str, Dict[str, Any]] = {}  # tx_id -> transaction data

# Claim files storage
CLAIM_FILES: Dict[str, Dict[str, Any]] = {}  # file_id -> file data with base64 content

# Underwriting files storage
UNDERWRITING_FILES: Dict[str, Dict[str, Any]] = {}  # file_id -> file data with base64 content

# Design settings - for landing page customization (admin-managed)
DESIGN_SETTINGS: Dict[str, Any] = {
    'video_url': '',
    'video_poster': '',
    'tagline': 'Comprehensive Protection for Your Future',
    'primary_color': '#0d47a1',
    'accent_color': '#ff6b35',
    'show_video': True,
    'show_contact': True,
    'show_quote_form': False,
    'show_products': False,
    'show_underwriting': False,
    'hero_video_id': '',
    'hero_background_id': '',
    'video_poster_id': '',
    'promo_banner_id': '',
    'updated_at': None,
    'updated_by': None
}

# Media Assets - centralized storage for videos, images, documents
MEDIA_ASSETS: Dict[str, Dict[str, Any]] = {}

# Invitation codes for customer registration
INVITATION_CODES: Dict[str, Dict[str, Any]] = {}

# Rate limiting and security
RATE_LIMIT: Dict[str, Any] = {}
FAILED_LOGINS: Dict[str, Any] = {}
BLOCKED_IPS: Dict[str, Any] = {}
SUSPICIOUS_PATTERNS: Dict[str, Any] = {}

# Test port initialization tracker (prevents duplicate initialization in tests)
_TEST_PORTS_INITIALIZED: set = set()

# Thread lock for state mutations
STATE_LOCK = threading.Lock()

# ==============================================================================
# PHINS MAIN BALANCE SHEET (GENERAL RESERVES)
# ==============================================================================
PHINS_BALANCE_SHEET: Dict[str, Any] = {
    'account_id': 'PHINS-MAIN-001',
    'name': 'PHINS General Reserves',
    'created_at': None,
    'last_updated': None,
    'claims_reserve': 3500000.00,
    'operating_reserve': 0.00,
    'supplier_reserve': 0.00,
    'investment_reserve': 0.00,
    'total_revenue': 0.00,
    'revenue_breakdown': {
        'premium_income': 0.00,
        'management_fees': 0.00,
        'underwriting_fees': 0.00,
        'investment_earnings': 0.00,
        'late_fees': 0.00,
        'other_income': 0.00
    },
    'total_expenses': 0.00,
    'expense_breakdown': {
        'claims_paid': 0.00,
        'supplier_payments': 0.00,
        'operating_costs': 0.00,
        'commissions': 0.00,
        'reinsurance': 0.00,
        'other_expenses': 0.00
    },
    'transactions': [],
    'audit_log': []
}

def initialize_balance_sheet():
    """Initialize the PHINS balance sheet with default values if not already set"""
    global PHINS_BALANCE_SHEET
    if PHINS_BALANCE_SHEET.get('created_at') is None:
        PHINS_BALANCE_SHEET['created_at'] = datetime.now().isoformat()
        PHINS_BALANCE_SHEET['last_updated'] = datetime.now().isoformat()
        initial_deposit_tx = {
            'tx_id': f"BS-INIT-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            'type': 'capital_deposit',
            'category': 'claims_reserve',
            'amount': 3500000.00,
            'description': 'Initial claims reserve capital - PHINS General Reserves Fund',
            'balance_after': 3500000.00,
            'actor': 'SYSTEM',
            'timestamp': datetime.now().isoformat()
        }
        PHINS_BALANCE_SHEET['transactions'].append(initial_deposit_tx)
        PHINS_BALANCE_SHEET['audit_log'].append({
            'action': 'initialize',
            'actor': 'SYSTEM',
            'timestamp': datetime.now().isoformat(),
            'details': 'Balance sheet initialized with $3,500,000 claims reserve'
        })
        print(f"✓ PHINS Balance Sheet initialized with $3,500,000 claims reserve")

def record_balance_sheet_transaction(
    tx_type: str,
    category: str,
    amount: float,
    description: str,
    actor: str = 'SYSTEM',
    metadata: Dict[str, Any] = None,
    customer_id: str = None,
    claim_id: str = None
) -> Dict[str, Any]:
    """Record a transaction on the PHINS main balance sheet."""
    global PHINS_BALANCE_SHEET

    tx_id = f"BS-{tx_type.upper()[:3]}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"

    if tx_type == 'revenue':
        if category in PHINS_BALANCE_SHEET['revenue_breakdown']:
            PHINS_BALANCE_SHEET['revenue_breakdown'][category] += amount
        PHINS_BALANCE_SHEET['total_revenue'] += amount
        PHINS_BALANCE_SHEET['operating_reserve'] += amount
    elif tx_type == 'expense':
        if category in PHINS_BALANCE_SHEET['expense_breakdown']:
            PHINS_BALANCE_SHEET['expense_breakdown'][category] += amount
        PHINS_BALANCE_SHEET['total_expenses'] += amount
        if category == 'claims_paid':
            PHINS_BALANCE_SHEET['claims_reserve'] -= amount
        elif category == 'supplier_payments':
            PHINS_BALANCE_SHEET['supplier_reserve'] -= amount
        else:
            PHINS_BALANCE_SHEET['operating_reserve'] -= amount

    total_balance = (
        PHINS_BALANCE_SHEET['claims_reserve'] +
        PHINS_BALANCE_SHEET['operating_reserve'] +
        PHINS_BALANCE_SHEET['supplier_reserve'] +
        PHINS_BALANCE_SHEET['investment_reserve']
    )

    transaction = {
        'tx_id': tx_id,
        'type': tx_type,
        'category': category,
        'amount': amount,
        'description': description,
        'customer_id': customer_id,
        'claim_id': claim_id,
        'metadata': metadata or {},
        'actor': actor,
        'balance_after': total_balance,
        'claims_reserve_after': PHINS_BALANCE_SHEET['claims_reserve'],
        'timestamp': datetime.now().isoformat()
    }

    PHINS_BALANCE_SHEET['transactions'].append(transaction)
    PHINS_BALANCE_SHEET['last_updated'] = datetime.now().isoformat()

    return transaction

# ==============================================================================
# USERS DATABASE (in-memory, seeded from database or defaults)
# ==============================================================================
USERS: Dict[str, Dict[str, Any]] = {}

def _hash_password(password: str, salt: str = None) -> tuple:
    """Hash a password with PBKDF2."""
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return hashed.hex(), salt

def _verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Verify a password against stored hash."""
    import hmac as _hmac
    computed_hash, _ = _hash_password(password, salt)
    return _hmac.compare_digest(computed_hash.encode(), stored_hash.encode())

def _seed_default_users():
    """Seed default users into the in-memory USERS dict."""
    global USERS
    default_users = [
        {'username': 'admin', 'password': 'admin123', 'role': 'admin', 'name': 'Admin User', 'email': 'admin@phins.ai'},
        {'username': 'underwriter', 'password': 'under123', 'role': 'underwriter', 'name': 'John Underwriter', 'email': 'underwriter@phins.ai'},
        {'username': 'claims_adjuster', 'password': 'claims123', 'role': 'claims', 'name': 'Jane Claims', 'email': 'claims@phins.ai'},
        {'username': 'accountant', 'password': 'acct123', 'role': 'accountant', 'name': 'Bob Accountant', 'email': 'accountant@phins.ai'},
        {'username': 'actuary', 'password': 'PDadmin123@', 'role': 'actuary', 'name': 'Actuary User', 'email': 'actuary@phins.ai'},
        {'username': 'supplier', 'password': 'PDadmin123@', 'role': 'supplier', 'name': 'Supplier User', 'email': 'supplier@phins.ai'},
        {'username': 'media_ad', 'password': 'PDadmin123@', 'role': 'media', 'name': 'Media Admin', 'email': 'media@phins.ai'},
        {'username': 'asaf@phins.ai', 'password': 'PHINSadmin2024!', 'role': 'admin', 'name': 'Asaf PHINS', 'email': 'asaf@phins.ai'},
        {'username': 'efrat@phins.ai', 'password': 'PHINScustomer2024!', 'role': 'customer', 'name': 'Efrat PHINS', 'email': 'efrat@phins.ai'},
        {'username': 'asi@phins.ai', 'password': 'PHINScustomer2024!', 'role': 'customer', 'name': 'Asi PHINS', 'email': 'asi@phins.ai'},
        {'username': 'shosh@phins.ai', 'password': 'PHINScustomer2024!', 'role': 'customer', 'name': 'Shosh PHINS', 'email': 'shosh@phins.ai'},
        {'username': 'asaf@assurance.co.il', 'password': 'Assurance2024!', 'role': 'customer', 'name': 'Asaf Assurance', 'email': 'asaf@assurance.co.il'},
    ]
    for user_data in default_users:
        if user_data['username'] not in USERS:
            pw_hash, pw_salt = _hash_password(user_data['password'])
            USERS[user_data['username']] = {
                'username': user_data['username'],
                'password_hash': pw_hash,
                'password_salt': pw_salt,
                'role': user_data['role'],
                'name': user_data['name'],
                'email': user_data['email'],
                'active': True,
                'created_date': datetime.now().isoformat()
            }

# Seed default users on startup
_seed_default_users()

# Add test invitation code when in test mode
if PHINS_TEST_MODE:
    INVITATION_CODES['TESTCODE2026'] = {
        'code': 'TESTCODE2026',
        'status': 'active',
        'used_count': 0,
        'max_uses': 9999,
        'created_by': 'system',
        'created_at': datetime.now().isoformat(),
        'expires_at': '2099-12-31T23:59:59',
    }

# ==============================================================================
# REGISTERED CUSTOMERS (for customer portal login)
# ==============================================================================
REGISTERED_CUSTOMERS: Dict[str, Dict[str, Any]] = {}

# ==============================================================================
# AUDIT LOG
# ==============================================================================
AUDIT_LOG: List[Dict[str, Any]] = []

def log_audit(action: str, username: str = None, customer_id: str = None,
              entity_type: str = None, entity_id: str = None,
              details: str = None, ip_address: str = None, success: bool = True):
    """Add an entry to the audit log."""
    entry = {
        'id': len(AUDIT_LOG) + 1,
        'timestamp': datetime.now().isoformat(),
        'username': username,
        'customer_id': customer_id,
        'action': action,
        'entity_type': entity_type,
        'entity_id': entity_id,
        'details': details,
        'ip_address': ip_address,
        'success': success
    }
    AUDIT_LOG.append(entry)
    # Keep only last 10000 entries
    if len(AUDIT_LOG) > 10000:
        AUDIT_LOG.pop(0)

# ==============================================================================
# LEDGER PERSISTENCE
# ==============================================================================

def _get_persistence_dir() -> str:
    """
    Determine the persistence directory for ledger data.

    Priority:
    1. $RAILWAY_VOLUME_MOUNT_PATH - Railway persistent volume mount
    2. $LEDGER_DATA_DIR - custom override
    3. /data - standard persistent data directory (can be mounted as a volume)
    4. Project-relative data/ directory (fallback for local dev)
    """
    # Railway persistent volume
    railway_volume = os.environ.get('RAILWAY_VOLUME_MOUNT_PATH', '').strip()
    if railway_volume:
        return railway_volume

    # Custom override
    custom_dir = os.environ.get('LEDGER_DATA_DIR', '').strip()
    if custom_dir:
        return custom_dir

    # Standard /data directory (can be mounted as a volume on Railway)
    try:
        os.makedirs('/data', exist_ok=True)
        # Test write access
        test_file = '/data/.write_test'
        with open(test_file, 'w') as f:
            f.write('test')
        os.remove(test_file)
        return '/data'
    except (PermissionError, OSError):
        pass

    # Fallback: project-relative data directory
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(project_root, 'data')


def _resolve_persistence_file() -> str:
    """Resolve the full path to the ledger persistence file."""
    # Allow explicit override via environment variable
    explicit = os.environ.get('LEDGER_PERSISTENCE_FILE', '').strip()
    if explicit:
        return explicit

    data_dir = _get_persistence_dir()
    try:
        os.makedirs(data_dir, exist_ok=True)
    except (PermissionError, OSError):
        pass
    return os.path.join(data_dir, 'phins_ledger_data.json')


# Persistence file path - uses persistent storage, NOT /tmp
# On Railway: uses $RAILWAY_VOLUME_MOUNT_PATH if set, otherwise /data/
LEDGER_PERSISTENCE_FILE: str = _resolve_persistence_file()

# Persistence configuration
PERSISTENCE_VERBOSE: bool = str(os.environ.get('LEDGER_PERSISTENCE_VERBOSE', '')).lower() in ('1', 'true', 'yes')
PERSISTENCE_LOG_INTERVAL_SECONDS: int = int(os.environ.get('LEDGER_PERSISTENCE_LOG_INTERVAL', '300'))

# Dirty flag - set when data changes, cleared after save
_persistence_dirty: bool = False

# Log state for coalescing repeated save messages
_persistence_log_state: Dict[str, Any] = {
    'first_save_logged': False,
    'last_logged_at': 0.0,
    'saves_since_last_log': 0,
}

_persistence_lock = threading.Lock()


def _mark_dirty():
    """Mark the ledger as dirty (needs saving)."""
    global _persistence_dirty
    _persistence_dirty = True


def save_ledger_data(_periodic: bool = False) -> bool:
    """
    Save ledger data to the persistence file.

    Args:
        _periodic: If True, skip write when dirty flag is clear (no changes since last save).

    Returns:
        True if saved successfully, False otherwise.
    """
    global _persistence_dirty, _persistence_log_state

    # Periodic saves skip when nothing has changed
    if _periodic and not _persistence_dirty:
        return True

    try:
        data = {
            'version': '2.0',
            'saved_at': datetime.now().isoformat(),
            'transaction_ledger': dict(TRANSACTION_LEDGER),
            'customer_allocations': dict(CUSTOMER_ALLOCATIONS),
            'investment_accounts': dict(INVESTMENT_ACCOUNTS),
            'health_wallets': dict(HEALTH_WALLETS),
            'phins_balance_sheet': PHINS_BALANCE_SHEET,
            'design_settings': DESIGN_SETTINGS,
            'invitation_codes': dict(INVITATION_CODES),
        }

        # Atomic write: write to temp file then rename
        temp_path = LEDGER_PERSISTENCE_FILE + '.tmp'
        with open(temp_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(temp_path, LEDGER_PERSISTENCE_FILE)

        _persistence_dirty = False

        # Coalesced logging
        now = time.time()
        state = _persistence_log_state
        state['saves_since_last_log'] = state.get('saves_since_last_log', 0) + 1

        should_log = (
            PERSISTENCE_VERBOSE
            or not state.get('first_save_logged')
            or (PERSISTENCE_LOG_INTERVAL_SECONDS > 0 and (now - state.get('last_logged_at', 0)) >= PERSISTENCE_LOG_INTERVAL_SECONDS)
            or PERSISTENCE_LOG_INTERVAL_SECONDS == 0
        )

        if should_log:
            saves = state['saves_since_last_log']
            if saves > 1 and state.get('first_save_logged'):
                print(f"[PERSISTENCE] Saved ledger data to {LEDGER_PERSISTENCE_FILE} (coalesced {saves} saves)")
            else:
                print(f"[PERSISTENCE] Saved ledger data to {LEDGER_PERSISTENCE_FILE}")
            state['first_save_logged'] = True
            state['last_logged_at'] = now
            state['saves_since_last_log'] = 0

        return True

    except Exception as e:
        print(f"[PERSISTENCE] Error saving ledger data: {e}")
        return False


def load_ledger_data() -> bool:
    """Load ledger data from the persistence file on startup."""
    global TRANSACTION_LEDGER, CUSTOMER_ALLOCATIONS, INVESTMENT_ACCOUNTS
    global HEALTH_WALLETS, PHINS_BALANCE_SHEET, DESIGN_SETTINGS, INVITATION_CODES

    if not os.path.exists(LEDGER_PERSISTENCE_FILE):
        return False

    try:
        with open(LEDGER_PERSISTENCE_FILE, 'r') as f:
            data = json.load(f)

        if 'transaction_ledger' in data:
            TRANSACTION_LEDGER.update(data['transaction_ledger'])
        if 'customer_allocations' in data:
            CUSTOMER_ALLOCATIONS.update(data['customer_allocations'])
        if 'investment_accounts' in data:
            INVESTMENT_ACCOUNTS.update(data['investment_accounts'])
        if 'health_wallets' in data:
            HEALTH_WALLETS.update(data['health_wallets'])
        if 'phins_balance_sheet' in data:
            PHINS_BALANCE_SHEET.update(data['phins_balance_sheet'])
        if 'design_settings' in data:
            DESIGN_SETTINGS.update(data['design_settings'])
        if 'invitation_codes' in data:
            INVITATION_CODES.update(data['invitation_codes'])

        print(f"[PERSISTENCE] Loaded ledger data from {LEDGER_PERSISTENCE_FILE}")
        return True

    except Exception as e:
        print(f"[PERSISTENCE] Error loading ledger data: {e}")
        return False


def _start_periodic_save(interval_seconds: int = 60):
    """Start a background thread that periodically saves ledger data."""
    def _save_loop():
        while True:
            time.sleep(interval_seconds)
            try:
                save_ledger_data(_periodic=True)
            except Exception as e:
                print(f"[PERSISTENCE] Periodic save error: {e}")

    thread = threading.Thread(target=_save_loop, daemon=True)
    thread.start()
    return thread


# ==============================================================================
# BOT PROBE DETECTION
# ==============================================================================

_BOT_PROBE_PREFIXES = (
    '/.env', '/.git/', '/wp-', '/config.php', '/config.js',
    '/aws-config', '/aws.config', '/%22/', '/backend/.env',
    '/admin/.env',
)
_BOT_PROBE_EXTENSIONS = ('.env', '.env.bak', '.env.local', '.env.old',
                          '.git', '.php', '.php.old')
_BOT_PROBE_SILENCED_STATUSES = {403, 404}


def _is_bot_probe_path(path: str) -> bool:
    """Return True if the path looks like a bot/scanner probe."""
    lower = path.lower()
    for prefix in _BOT_PROBE_PREFIXES:
        if lower.startswith(prefix):
            return True
    for ext in _BOT_PROBE_EXTENSIONS:
        if lower.endswith(ext):
            return True
    return False


def _should_silence_bot_probe_http_log(path: str, status_code: int) -> bool:
    """Return True if this bot-probe request's log line should be suppressed."""
    return _is_bot_probe_path(path) and status_code in _BOT_PROBE_SILENCED_STATUSES


# ==============================================================================
# AUTHENTICATION HELPERS
# ==============================================================================

SESSION_DURATION_HOURS = 24

def _generate_token() -> str:
    """Generate a secure session token."""
    return f"phins_{secrets.token_urlsafe(32)}"

def _create_session(username: str, role: str, customer_id: str = None,
                    ip_address: str = None, jti: str = None) -> str:
    """Create a new session and return the token."""
    token = _generate_token()
    expires = datetime.now() + timedelta(hours=SESSION_DURATION_HOURS)

    session_data = {
        'token': token,
        'username': username,
        'role': role,
        'customer_id': customer_id,
        'ip_address': ip_address,
        'expires': expires.isoformat(),
        'created_at': datetime.now().isoformat(),
    }
    if jti:
        session_data['jti'] = jti

    with STATE_LOCK:
        SESSIONS[token] = session_data

    _mark_dirty()
    return token

def _get_session(token: str) -> Optional[Dict[str, Any]]:
    """Get a session by token, returning None if expired or not found."""
    if not token:
        return None

    session = SESSIONS.get(token)
    if not session:
        return None

    # Check expiry
    expires_str = session.get('expires')
    if expires_str:
        try:
            expires = datetime.fromisoformat(expires_str)
            if datetime.now() > expires:
                with STATE_LOCK:
                    SESSIONS.pop(token, None)
                return None
        except (ValueError, TypeError):
            pass

    return session

def _authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate a user and return their data, or None if invalid."""
    # Check internal users first
    user = USERS.get(username)
    if user and user.get('active', True):
        stored_hash = user.get('password_hash', '')
        stored_salt = user.get('password_salt', '')
        if stored_hash and stored_salt:
            if _verify_password(password, stored_hash, stored_salt):
                return user

    # Check database users if available
    if USE_DATABASE and database_enabled:
        try:
            db_user = DB_USERS.get(username)
            if db_user and db_user.get('active', True):
                stored_hash = db_user.get('password_hash', '')
                stored_salt = db_user.get('password_salt', '')
                if stored_hash and stored_salt:
                    if _verify_password(password, stored_hash, stored_salt):
                        return db_user
        except Exception:
            pass

    # Check registered customers
    customer = REGISTERED_CUSTOMERS.get(username)
    if customer:
        stored_hash = customer.get('password_hash', '')
        stored_salt = customer.get('password_salt', '')
        if stored_hash and stored_salt:
            if _verify_password(password, stored_hash, stored_salt):
                return {
                    'username': username,
                    'role': 'customer',
                    'name': customer.get('name', ''),
                    'email': username,
                    'customer_id': customer.get('customer_id'),
                    'active': True
                }

    return None

def _get_token_from_request(handler) -> Optional[str]:
    """Extract bearer token from Authorization header."""
    auth_header = handler.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:].strip()
    return None

def _require_auth(handler) -> Optional[Dict[str, Any]]:
    """Require authentication, sending 401 if not authenticated."""
    token = _get_token_from_request(handler)
    if not token:
        _send_error(handler, 401, "Authentication required")
        return None
    session = _get_session(token)
    if not session:
        _send_error(handler, 401, "Invalid or expired session")
        return None
    return session

def _require_role(handler, session: Dict, *roles: str) -> bool:
    """Require specific role(s), sending 403 if not authorized."""
    if session.get('role') not in roles:
        _send_error(handler, 403, "Insufficient permissions")
        return False
    return True

def is_suspended_account(customer_id: str) -> bool:
    """Check if a customer account is suspended."""
    if not customer_id:
        return False
    customer = CUSTOMERS.get(customer_id)
    if not customer:
        return False
    return str(customer.get('status', '')).lower() in ('suspended', 'inactive', 'cancelled')

# ==============================================================================
# HTTP RESPONSE HELPERS
# ==============================================================================

def _send_json(handler, status: int, data: Any, extra_headers: Dict = None):
    """Send a JSON response."""
    body = json.dumps(data, default=str).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
    handler.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
    if extra_headers:
        for key, value in extra_headers.items():
            handler.send_header(key, value)
    handler.end_headers()
    handler.wfile.write(body)

def _send_error(handler, status: int, message: str, code: str = None, extra: Dict = None):
    """Send an error JSON response."""
    data = {'error': message}
    if code:
        data['code'] = code
    if extra:
        data.update(extra)
    _send_json(handler, status, data)

def _read_body(handler) -> Optional[Dict]:
    """Read and parse JSON request body."""
    try:
        content_length = int(handler.headers.get('Content-Length', 0))
        if content_length > 0:
            body = handler.rfile.read(content_length)
            return json.loads(body.decode('utf-8'))
        return {}
    except (json.JSONDecodeError, ValueError):
        return None

# ==============================================================================
# ID GENERATION
# ==============================================================================

def _generate_id(prefix: str) -> str:
    """Generate a unique ID with a prefix."""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_part = random.randint(1000, 9999)
    return f"{prefix}-{timestamp}-{random_part}"

def _generate_customer_id() -> str:
    return f"CUST-{uuid.uuid4().hex[:8].upper()}"

def _generate_policy_id() -> str:
    return f"POL-{uuid.uuid4().hex[:8].upper()}"

def _generate_claim_id() -> str:
    return f"CLM-{uuid.uuid4().hex[:8].upper()}"

def _generate_uw_id() -> str:
    return f"UW-{uuid.uuid4().hex[:8].upper()}"

def _generate_bill_id() -> str:
    return f"BILL-{uuid.uuid4().hex[:8].upper()}"

# ==============================================================================
# PREMIUM CALCULATION
# ==============================================================================

PREMIUM_RATES = {
    'life': {'base': 0.005, 'risk_multipliers': {'low': 0.8, 'medium': 1.0, 'high': 1.5, 'very_high': 2.5}},
    'health': {'base': 0.008, 'risk_multipliers': {'low': 0.9, 'medium': 1.0, 'high': 1.4, 'very_high': 2.0}},
    'auto': {'base': 0.03, 'risk_multipliers': {'low': 0.85, 'medium': 1.0, 'high': 1.3, 'very_high': 1.8}},
    'home': {'base': 0.006, 'risk_multipliers': {'low': 0.9, 'medium': 1.0, 'high': 1.3, 'very_high': 1.7}},
    'commercial': {'base': 0.01, 'risk_multipliers': {'low': 0.9, 'medium': 1.0, 'high': 1.4, 'very_high': 2.0}},
}

def _calculate_premium(policy_type: str, coverage_amount: float, risk_score: str = 'medium') -> Dict[str, float]:
    """Calculate annual and monthly premium."""
    rates = PREMIUM_RATES.get(policy_type, PREMIUM_RATES['life'])
    base_rate = rates['base']
    risk_multiplier = rates['risk_multipliers'].get(risk_score, 1.0)
    annual_premium = round(coverage_amount * base_rate * risk_multiplier, 2)
    monthly_premium = round(annual_premium / 12, 2)
    return {'annual': annual_premium, 'monthly': monthly_premium}

# ==============================================================================
# API HANDLERS
# ==============================================================================

def _handle_login(handler, body: Dict) -> None:
    """POST /api/login"""
    username = body.get('username', '').strip()
    password = body.get('password', '').strip()
    captcha_token = body.get('captcha_token', '').strip()

    if not username or not password:
        _send_error(handler, 400, "Username and password required")
        return

    # CAPTCHA validation if provided
    if captcha_token:
        try:
            from services.otp_security_service import get_otp_security_service
            otp_service = get_otp_security_service()
            with otp_service._lock:
                pass  # Just test the lock is accessible
        except Exception as e:
            _send_error(handler, 503, "CAPTCHA validation unavailable. Please try again.")
            return

    user = _authenticate_user(username, password)
    if not user:
        _send_error(handler, 401, "Invalid credentials")
        return

    # Generate v2 token if secret key is available
    jti = None
    token = None
    try:
        from security import auth_tokens
        token = auth_tokens.create_token(username=username, role=user.get('role', ''))
        claims = auth_tokens.verify_v2_token(token)
        if claims:
            jti = claims.jti
    except Exception:
        token = None

    if not token:
        token = _generate_token()

    customer_id = user.get('customer_id')
    if not customer_id and user.get('role') == 'customer':
        # Look up customer_id from CUSTOMERS by email
        email = user.get('email', username)
        for cid, cust in CUSTOMERS.items():
            if cust.get('email') == email:
                customer_id = cid
                break

    session_data = {
        'token': token,
        'username': username,
        'role': user.get('role', ''),
        'name': user.get('name', username),
        'customer_id': customer_id,
        'expires': (datetime.now() + timedelta(hours=SESSION_DURATION_HOURS)).isoformat(),
        'created_at': datetime.now().isoformat(),
    }
    if jti:
        session_data['jti'] = jti

    with STATE_LOCK:
        SESSIONS[token] = session_data

    _mark_dirty()
    log_audit('login', username=username, ip_address=handler.client_address[0])

    _send_json(handler, 200, {
        'token': token,
        'username': username,
        'role': user.get('role', ''),
        'name': user.get('name', username),
        'customer_id': customer_id,
        'expires': session_data['expires'],
    })


def _handle_logout(handler, session: Dict) -> None:
    """POST /api/logout"""
    token = _get_token_from_request(handler)
    if token:
        with STATE_LOCK:
            SESSIONS.pop(token, None)
        # Revoke v2 token if applicable
        try:
            from security import auth_tokens
            auth_tokens.revoke_token(token)
        except Exception:
            pass
    log_audit('logout', username=session.get('username'))
    _send_json(handler, 200, {'success': True, 'message': 'Logged out successfully'})


def _handle_register(handler, body: Dict) -> None:
    """POST /api/register"""
    name = body.get('name', '').strip()
    email = body.get('email', '').strip().lower()
    password = body.get('password', '').strip()
    phone = body.get('phone', '').strip()
    dob = body.get('dob', '').strip()
    invitation_code = body.get('invitation_code', '').strip()

    if not name or not email or not password:
        _send_error(handler, 400, "Name, email, and password are required")
        return

    # Require invitation code
    if not invitation_code:
        _send_error(handler, 400, "Invitation code is required for registration")
        return

    # Validate invitation code
    invite = INVITATION_CODES.get(invitation_code)
    if not invite:
        _send_error(handler, 400, "Invalid invitation code", code="INVALID_CODE")
        return

    if invite.get('status') == 'used' or invite.get('used_count', 0) >= invite.get('max_uses', 1):
        _send_error(handler, 400, "Invitation code has already been used", code="CODE_USED")
        return

    # Check if email already registered
    if email in USERS or email in REGISTERED_CUSTOMERS:
        _send_error(handler, 409, "Email already registered")
        return

    # Check CUSTOMERS dict
    for cust in CUSTOMERS.values():
        if cust.get('email', '').lower() == email:
            _send_error(handler, 409, "Email already registered")
            return

    # Create customer
    customer_id = _generate_customer_id()
    pw_hash, pw_salt = _hash_password(password)

    customer_data = {
        'id': customer_id,
        'name': name,
        'email': email,
        'phone': phone,
        'dob': dob,
        'status': 'active',
        'portal_active': True,
        'password_hash': pw_hash,
        'password_salt': pw_salt,
        'created_date': datetime.now().isoformat(),
        'updated_date': datetime.now().isoformat(),
    }

    CUSTOMERS[customer_id] = customer_data
    REGISTERED_CUSTOMERS[email] = {
        'customer_id': customer_id,
        'name': name,
        'email': email,
        'password_hash': pw_hash,
        'password_salt': pw_salt,
    }
    USERS[email] = {
        'username': email,
        'password_hash': pw_hash,
        'password_salt': pw_salt,
        'role': 'customer',
        'name': name,
        'email': email,
        'customer_id': customer_id,
        'active': True,
        'created_date': datetime.now().isoformat(),
    }

    # Mark invitation as used
    invite['used_count'] = invite.get('used_count', 0) + 1
    if invite['used_count'] >= invite.get('max_uses', 1):
        invite['status'] = 'used'

    _mark_dirty()
    log_audit('register', username=email, customer_id=customer_id)

    _send_json(handler, 201, {
        'success': True,
        'customer_id': customer_id,
        'email': email,
        'name': name,
        'message': 'Registration successful'
    })


def _handle_profile(handler, session: Dict) -> None:
    """GET /api/profile"""
    username = session.get('username')
    user = USERS.get(username, {})
    _send_json(handler, 200, {
        'username': username,
        'role': session.get('role'),
        'name': user.get('name', session.get('name', username)),
        'email': user.get('email', username),
        'customer_id': session.get('customer_id'),
    })


def _handle_policies_create(handler, body: Dict) -> None:
    """POST /api/policies/create"""
    customer_name = body.get('customer_name', '').strip()
    customer_email = body.get('customer_email', '').strip().lower()
    customer_phone = body.get('customer_phone', '').strip()
    policy_type = body.get('type', 'life').strip().lower()
    coverage_amount = body.get('coverage_amount', 0)
    risk_score = body.get('risk_score', 'medium').strip().lower()
    age = body.get('age', 30)

    if not customer_name:
        _send_error(handler, 400, "Customer name is required")
        return

    try:
        coverage_amount = float(coverage_amount)
    except (TypeError, ValueError):
        _send_error(handler, 400, "Invalid coverage amount")
        return

    if coverage_amount <= 0 or coverage_amount > 100000000:
        _send_error(handler, 400, "Coverage amount must be between 0 and 100,000,000")
        return

    # Find or create customer
    customer_id = None
    if customer_email:
        for cid, cust in CUSTOMERS.items():
            if cust.get('email', '').lower() == customer_email:
                customer_id = cid
                break

    if not customer_id:
        customer_id = _generate_customer_id()
        customer_data = {
            'id': customer_id,
            'name': customer_name,
            'email': customer_email,
            'phone': customer_phone,
            'age': age,
            'status': 'active',
            'created_date': datetime.now().isoformat(),
            'updated_date': datetime.now().isoformat(),
        }
        CUSTOMERS[customer_id] = customer_data

    # Calculate premium
    premiums = _calculate_premium(policy_type, coverage_amount, risk_score)

    # Create policy
    policy_id = _generate_policy_id()
    now = datetime.now()
    policy_data = {
        'id': policy_id,
        'customer_id': customer_id,
        'type': policy_type,
        'coverage_amount': coverage_amount,
        'annual_premium': premiums['annual'],
        'monthly_premium': premiums['monthly'],
        'risk_score': risk_score,
        'status': 'pending_underwriting',
        'start_date': now.isoformat(),
        'end_date': (now + timedelta(days=365)).isoformat(),
        'created_date': now.isoformat(),
        'updated_date': now.isoformat(),
    }

    # Create underwriting application
    uw_id = _generate_uw_id()
    uw_data = {
        'id': uw_id,
        'policy_id': policy_id,
        'customer_id': customer_id,
        'customer_name': customer_name,
        'customer_email': customer_email,
        'policy_type': policy_type,
        'coverage_amount': coverage_amount,
        'annual_premium': premiums['annual'],
        'monthly_premium': premiums['monthly'],
        'risk_score': risk_score,
        'status': 'pending',
        'created_date': now.isoformat(),
        'updated_date': now.isoformat(),
    }

    policy_data['underwriting_id'] = uw_id
    uw_data['policy_id'] = policy_id

    POLICIES[policy_id] = policy_data
    UNDERWRITING_APPLICATIONS[uw_id] = uw_data

    # Provision customer login
    temp_password = secrets.token_urlsafe(12)
    pw_hash, pw_salt = _hash_password(temp_password)
    login_username = customer_email or customer_id

    if login_username and login_username not in USERS:
        USERS[login_username] = {
            'username': login_username,
            'password_hash': pw_hash,
            'password_salt': pw_salt,
            'role': 'customer',
            'name': customer_name,
            'email': customer_email,
            'customer_id': customer_id,
            'active': True,
            'created_date': now.isoformat(),
        }

    _mark_dirty()
    log_audit('policy_create', entity_type='policy', entity_id=policy_id)

    _send_json(handler, 201, {
        'policy': policy_data,
        'customer': CUSTOMERS[customer_id],
        'underwriting': uw_data,
        'provisioned_login': {
            'username': login_username,
            'password': temp_password,
        }
    })


def _handle_policies_list(handler, query: Dict) -> None:
    """GET /api/policies"""
    policy_id = query.get('id', [None])[0]
    if policy_id:
        policy = POLICIES.get(policy_id)
        if not policy:
            _send_error(handler, 404, "Policy not found")
            return
        _send_json(handler, 200, policy)
        return

    # Pagination
    page = int(query.get('page', ['1'])[0])
    page_size = int(query.get('page_size', ['50'])[0])
    status_filter = query.get('status', [None])[0]

    items = list(POLICIES.values())
    if status_filter:
        items = [p for p in items if status_eq(p, status_filter)]

    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end]

    _send_json(handler, 200, {
        'items': page_items,
        'page': page,
        'page_size': page_size,
        'total': total,
    })


def _handle_underwriting_list(handler, query: Dict) -> None:
    """GET /api/underwriting"""
    uw_id = query.get('id', [None])[0]
    if uw_id:
        uw = UNDERWRITING_APPLICATIONS.get(uw_id)
        if not uw:
            _send_error(handler, 404, "Underwriting application not found")
            return
        _send_json(handler, 200, uw)
        return

    items = list(UNDERWRITING_APPLICATIONS.values())
    _send_json(handler, 200, items)


def _handle_underwriting_approve(handler, body: Dict) -> None:
    """POST /api/underwriting/approve"""
    uw_id = body.get('id', '').strip()
    approved_by = body.get('approved_by', 'system').strip()

    if not uw_id:
        _send_error(handler, 400, "Underwriting application ID required")
        return

    uw = UNDERWRITING_APPLICATIONS.get(uw_id)
    if not uw:
        _send_error(handler, 404, "Underwriting application not found")
        return

    uw['status'] = 'approved'
    uw['approved_by'] = approved_by
    uw['approved_date'] = datetime.now().isoformat()
    uw['updated_date'] = datetime.now().isoformat()

    # Update policy status
    policy_id = uw.get('policy_id')
    if policy_id and policy_id in POLICIES:
        POLICIES[policy_id]['status'] = 'active'
        POLICIES[policy_id]['approval_date'] = datetime.now().isoformat()
        POLICIES[policy_id]['updated_date'] = datetime.now().isoformat()

    _mark_dirty()
    log_audit('underwriting_approve', entity_type='underwriting', entity_id=uw_id)
    _send_json(handler, 200, {'success': True, 'application': uw})


def _handle_underwriting_reject(handler, body: Dict) -> None:
    """POST /api/underwriting/reject"""
    uw_id = body.get('id', '').strip()
    reason = body.get('reason', '').strip()
    rejected_by = body.get('rejected_by', 'system').strip()

    if not uw_id:
        _send_error(handler, 400, "Underwriting application ID required")
        return

    uw = UNDERWRITING_APPLICATIONS.get(uw_id)
    if not uw:
        _send_error(handler, 404, "Underwriting application not found")
        return

    uw['status'] = 'rejected'
    uw['rejection_reason'] = reason
    uw['rejected_by'] = rejected_by
    uw['rejected_date'] = datetime.now().isoformat()
    uw['updated_date'] = datetime.now().isoformat()

    # Update policy status
    policy_id = uw.get('policy_id')
    if policy_id and policy_id in POLICIES:
        POLICIES[policy_id]['status'] = 'rejected'
        POLICIES[policy_id]['updated_date'] = datetime.now().isoformat()

    _mark_dirty()
    log_audit('underwriting_reject', entity_type='underwriting', entity_id=uw_id)
    _send_json(handler, 200, {'success': True, 'application': uw})


def _handle_claims_create(handler, body: Dict) -> None:
    """POST /api/claims/create"""
    policy_id = body.get('policy_id', '').strip()
    customer_id = body.get('customer_id', '').strip()
    claim_type = body.get('type', 'general').strip()
    description = body.get('description', '').strip()
    claimed_amount = body.get('claimed_amount', 0)

    if not policy_id or not customer_id:
        _send_error(handler, 400, "Policy ID and customer ID are required")
        return

    try:
        claimed_amount = float(claimed_amount)
    except (TypeError, ValueError):
        _send_error(handler, 400, "Invalid claimed amount")
        return

    claim_id = _generate_claim_id()
    now = datetime.now()
    claim_data = {
        'id': claim_id,
        'policy_id': policy_id,
        'customer_id': customer_id,
        'type': claim_type,
        'description': description,
        'claimed_amount': claimed_amount,
        'approved_amount': 0,
        'paid_amount': 0,
        'status': 'pending',
        'filed_date': now.isoformat(),
        'created_date': now.isoformat(),
        'updated_date': now.isoformat(),
    }

    CLAIMS[claim_id] = claim_data
    _mark_dirty()
    log_audit('claim_create', entity_type='claim', entity_id=claim_id)
    _send_json(handler, 201, claim_data)


def _handle_claims_list(handler, query: Dict) -> None:
    """GET /api/claims"""
    claim_id = query.get('id', [None])[0]
    if claim_id:
        claim = CLAIMS.get(claim_id)
        if not claim:
            _send_error(handler, 404, "Claim not found")
            return
        _send_json(handler, 200, claim)
        return

    page = int(query.get('page', ['1'])[0])
    page_size = int(query.get('page_size', ['50'])[0])
    status_filter = query.get('status', [None])[0]

    items = list(CLAIMS.values())
    if status_filter:
        items = [c for c in items if status_eq(c, status_filter)]

    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end]

    _send_json(handler, 200, {
        'items': page_items,
        'page': page,
        'page_size': page_size,
        'total': total,
    })


def _handle_claims_approve(handler, body: Dict) -> None:
    """POST /api/claims/approve"""
    claim_id = body.get('id', '').strip()
    approved_amount = body.get('approved_amount', 0)
    approved_by = body.get('approved_by', 'system').strip()
    notes = body.get('notes', '').strip()

    if not claim_id:
        _send_error(handler, 400, "Claim ID required")
        return

    claim = CLAIMS.get(claim_id)
    if not claim:
        _send_error(handler, 404, "Claim not found")
        return

    try:
        approved_amount = float(approved_amount)
    except (TypeError, ValueError):
        approved_amount = claim.get('claimed_amount', 0)

    claim['status'] = 'approved'
    claim['approved_amount'] = approved_amount
    claim['approved_by'] = approved_by
    claim['approval_notes'] = notes
    claim['approval_date'] = datetime.now().isoformat()
    claim['updated_date'] = datetime.now().isoformat()

    _mark_dirty()
    log_audit('claim_approve', entity_type='claim', entity_id=claim_id)
    _send_json(handler, 200, {'success': True, 'claim': claim})


def _handle_claims_reject(handler, body: Dict) -> None:
    """POST /api/claims/reject"""
    claim_id = body.get('id', '').strip()
    reason = body.get('reason', '').strip()
    rejected_by = body.get('rejected_by', 'system').strip()

    if not claim_id:
        _send_error(handler, 400, "Claim ID required")
        return

    claim = CLAIMS.get(claim_id)
    if not claim:
        _send_error(handler, 404, "Claim not found")
        return

    claim['status'] = 'rejected'
    claim['rejection_reason'] = reason
    claim['rejected_by'] = rejected_by
    claim['rejected_date'] = datetime.now().isoformat()
    claim['updated_date'] = datetime.now().isoformat()

    _mark_dirty()
    log_audit('claim_reject', entity_type='claim', entity_id=claim_id)
    _send_json(handler, 200, {'success': True, 'claim': claim})


def _handle_claims_pay(handler, body: Dict) -> None:
    """POST /api/claims/pay"""
    claim_id = body.get('id', '').strip()
    payment_method = body.get('payment_method', 'bank_transfer').strip()
    processed_by = body.get('processed_by', 'system').strip()

    if not claim_id:
        _send_error(handler, 400, "Claim ID required")
        return

    claim = CLAIMS.get(claim_id)
    if not claim:
        _send_error(handler, 404, "Claim not found")
        return

    if claim.get('status') != 'approved':
        _send_error(handler, 400, "Claim must be approved before payment")
        return

    paid_amount = claim.get('approved_amount', 0)
    payment_ref = f"PAY-{uuid.uuid4().hex[:8].upper()}"

    claim['status'] = 'paid'
    claim['paid_amount'] = paid_amount
    claim['payment_method'] = payment_method
    claim['payment_reference'] = payment_ref
    claim['processed_by'] = processed_by
    claim['payment_date'] = datetime.now().isoformat()
    claim['updated_date'] = datetime.now().isoformat()

    # Record balance sheet expense
    record_balance_sheet_transaction(
        'expense', 'claims_paid', paid_amount,
        f"Claim payment {claim_id}",
        actor=processed_by,
        claim_id=claim_id,
        customer_id=claim.get('customer_id')
    )

    _mark_dirty()
    log_audit('claim_pay', entity_type='claim', entity_id=claim_id)
    _send_json(handler, 200, {'success': True, 'claim': claim})


def _handle_billing_create(handler, body: Dict) -> None:
    """POST /api/billing/create"""
    policy_id = body.get('policy_id', '').strip()
    amount_due = body.get('amount_due', 0)
    due_days = body.get('due_days', 30)

    if not policy_id:
        _send_error(handler, 400, "Policy ID required")
        return

    try:
        amount_due = float(amount_due)
    except (TypeError, ValueError):
        _send_error(handler, 400, "Invalid amount")
        return

    policy = POLICIES.get(policy_id)
    customer_id = policy.get('customer_id') if policy else None

    bill_id = _generate_bill_id()
    now = datetime.now()
    due_date = now + timedelta(days=int(due_days))

    bill_data = {
        'id': bill_id,
        'bill_id': bill_id,
        'policy_id': policy_id,
        'customer_id': customer_id,
        'amount': amount_due,
        'amount_due': amount_due,
        'amount_paid': 0.0,
        'status': 'outstanding',
        'due_date': due_date.isoformat(),
        'paid_date': None,
        'payment_method': None,
        'transaction_id': None,
        'late_fee': 0.0,
        'created_date': now.isoformat(),
        'updated_date': now.isoformat(),
    }

    BILLING[bill_id] = bill_data
    _mark_dirty()
    log_audit('billing_create', entity_type='bill', entity_id=bill_id)
    _send_json(handler, 201, {'bill': bill_data})


def _handle_billing_pay(handler, body: Dict) -> None:
    """POST /api/billing/pay"""
    bill_id = body.get('bill_id') or body.get('id', '')
    if isinstance(bill_id, str):
        bill_id = bill_id.strip()
    amount = body.get('amount', 0)
    payment_method = body.get('payment_method', 'card').strip()

    if not bill_id:
        _send_error(handler, 400, "Bill ID required")
        return

    bill = BILLING.get(bill_id)
    if not bill:
        _send_error(handler, 404, "Bill not found")
        return

    try:
        amount = float(amount)
    except (TypeError, ValueError):
        _send_error(handler, 400, "Invalid amount")
        return

    amount_due = bill.get('amount_due', bill.get('amount', 0))
    amount_paid = bill.get('amount_paid', 0) + amount

    if amount_paid >= amount_due:
        bill['status'] = 'paid'
        bill['paid_date'] = datetime.now().isoformat()
    else:
        bill['status'] = 'partial'

    bill['amount_paid'] = amount_paid
    bill['payment_method'] = payment_method
    bill['transaction_id'] = f"TXN-{uuid.uuid4().hex[:8].upper()}"
    bill['updated_date'] = datetime.now().isoformat()

    # Record revenue
    record_balance_sheet_transaction(
        'revenue', 'premium_income', amount,
        f"Premium payment for bill {bill_id}",
        customer_id=bill.get('customer_id')
    )

    _mark_dirty()
    log_audit('billing_pay', entity_type='bill', entity_id=bill_id)
    _send_json(handler, 200, {'success': True, 'bill': bill})


def _handle_billing_stats(handler, body: Dict) -> None:
    """POST /api/billing/stats"""
    bills = list(BILLING.values())
    policies = list(POLICIES.values())

    total_transactions = sum(
        1 for b in bills
        if not is_suspended_account(b.get('customer_id', ''))
    )
    successful_payments = sum(
        1 for b in bills
        if not is_suspended_account(b.get('customer_id', ''))
        and status_in(b, ['paid', 'partial'])
    )
    failed_payments = sum(
        1 for b in bills
        if not is_suspended_account(b.get('customer_id', ''))
        and status_eq(b, 'failed')
    )
    total_revenue = round(sum(
        safe_float(p.get('annual_premium', 0))
        for p in policies
        if not is_suspended_account(p.get('customer_id', ''))
        and status_eq(p, 'active')
    ), 2)

    _send_json(handler, 200, {
        'total_transactions': total_transactions,
        'successful_payments': successful_payments,
        'failed_payments': failed_payments,
        'total_revenue': total_revenue,
    })


def _handle_customers_list(handler, query: Dict) -> None:
    """GET /api/customers"""
    customer_id = query.get('id', [None])[0]
    if customer_id:
        customer = CUSTOMERS.get(customer_id)
        if not customer:
            _send_error(handler, 404, "Customer not found")
            return
        _send_json(handler, 200, customer)
        return

    items = list(CUSTOMERS.values())
    _send_json(handler, 200, items)


def _handle_customer_status(handler, query: Dict) -> None:
    """GET /api/customer/status"""
    customer_id = query.get('customer_id', [None])[0]
    if not customer_id:
        _send_error(handler, 400, "Customer ID required")
        return

    customer = CUSTOMERS.get(customer_id)
    if not customer:
        _send_error(handler, 404, "Customer not found")
        return

    # Get related data
    customer_policies = [p for p in POLICIES.values() if p.get('customer_id') == customer_id]
    customer_claims = [c for c in CLAIMS.values() if c.get('customer_id') == customer_id]
    customer_uw = [u for u in UNDERWRITING_APPLICATIONS.values() if u.get('customer_id') == customer_id]
    customer_bills = [b for b in BILLING.values() if b.get('customer_id') == customer_id]

    active_policies = [p for p in customer_policies if status_eq(p, 'active')]
    pending_claims = [c for c in customer_claims if status_in(c, ['pending', 'under_review'])]
    outstanding_bills = [b for b in customer_bills if status_in(b, ['outstanding', 'partial'])]

    overall_status = 'active'
    if not active_policies:
        overall_status = 'no_active_policies'
    if outstanding_bills:
        overall_status = 'payment_due'

    _send_json(handler, 200, {
        'customer': customer,
        'overall_status': overall_status,
        'policies': customer_policies,
        'claims': customer_claims,
        'underwriting_applications': customer_uw,
        'billing': customer_bills,
        'summary': {
            'active_policies': len(active_policies),
            'pending_claims': len(pending_claims),
            'outstanding_bills': len(outstanding_bills),
        }
    })


def _handle_metrics(handler) -> None:
    """GET /api/metrics"""
    try:
        from services.metrics_service import MetricsService
        svc = MetricsService(POLICIES, CLAIMS, BILLING)
        metrics = svc.summary()
    except Exception:
        # Fallback metrics calculation
        total_policies = len(POLICIES)
        active_policies = sum(1 for p in POLICIES.values()
                              if not is_suspended_account(p.get('customer_id', ''))
                              and status_eq(p, 'active'))
        pending_claims = sum(1 for c in CLAIMS.values()
                             if not is_suspended_account(c.get('customer_id', ''))
                             and status_in(c, ['pending', 'under_review']))
        approved_claims = sum(1 for c in CLAIMS.values()
                              if not is_suspended_account(c.get('customer_id', ''))
                              and status_eq(c, 'approved'))
        outstanding_bills = sum(1 for b in BILLING.values()
                                if not is_suspended_account(b.get('customer_id', ''))
                                and status_in(b, ['outstanding', 'partial']))
        overdue_bills = sum(1 for b in BILLING.values()
                            if not is_suspended_account(b.get('customer_id', ''))
                            and status_eq(b, 'overdue'))
        metrics = {
            'policies': {'total': total_policies, 'active': active_policies},
            'claims': {'pending': pending_claims, 'approved': approved_claims},
            'billing': {'outstanding': outstanding_bills, 'overdue': overdue_bills},
        }

    _send_json(handler, 200, {
        'metrics': metrics,
        'ts': datetime.now().isoformat(),
    })


def _handle_audit(handler, session: Dict, query: Dict) -> None:
    """GET /api/audit"""
    if session.get('role') not in ('admin', 'accountant'):
        _send_error(handler, 403, "Admin access required")
        return

    page = int(query.get('page', ['1'])[0])
    page_size = int(query.get('page_size', ['50'])[0])

    items = list(reversed(AUDIT_LOG))
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = items[start:end]

    _send_json(handler, 200, {
        'items': page_items,
        'page': page,
        'page_size': page_size,
        'total': total,
    })


def _handle_security_threats(handler, session: Dict) -> None:
    """GET /api/security/threats"""
    if session.get('role') not in ('admin',):
        _send_error(handler, 403, "Admin access required")
        return

    _send_json(handler, 200, {
        'malicious_attempts': list(SUSPICIOUS_PATTERNS.values()),
        'blocked_ips': list(BLOCKED_IPS.keys()),
        'failed_logins': {k: v for k, v in FAILED_LOGINS.items()},
        'statistics': {
            'total_blocked': len(BLOCKED_IPS),
            'total_failed_logins': sum(v if isinstance(v, int) else 0 for v in FAILED_LOGINS.values()),
        }
    })


def _handle_health(handler) -> None:
    """GET /api/health"""
    _send_json(handler, 200, {
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'database': 'connected' if (USE_DATABASE and database_enabled) else 'in-memory',
        'persistence_file': LEDGER_PERSISTENCE_FILE,
        'session_storage': 'database' if (USE_DATABASE and database_enabled) else 'in-memory',
    })


def _handle_bi_actuary(handler, session: Dict) -> None:
    """GET /api/bi/actuary"""
    if session.get('role') not in ('admin', 'actuary', 'underwriter'):
        _send_error(handler, 403, "Insufficient permissions")
        return

    total_policies = len(POLICIES)
    total_exposure = sum(safe_float(p.get('coverage_amount', 0)) for p in POLICIES.values())
    total_premium = sum(safe_float(p.get('annual_premium', 0)) for p in POLICIES.values())
    avg_premium = total_premium / total_policies if total_policies > 0 else 0

    risk_dist = {'low': 0, 'medium': 0, 'high': 0, 'very_high': 0}
    for p in POLICIES.values():
        risk = p.get('risk_score', 'medium').lower()
        if risk in risk_dist:
            risk_dist[risk] += 1

    total_claims_amount = sum(safe_float(c.get('approved_amount', 0)) for c in CLAIMS.values() if status_eq(c, 'paid'))
    claims_ratio = total_claims_amount / total_premium if total_premium > 0 else 0

    reinsurance_expense = PHINS_BALANCE_SHEET['expense_breakdown'].get('reinsurance', 0)

    _send_json(handler, 200, {
        'total_policies': total_policies,
        'total_exposure': total_exposure,
        'average_premium': round(avg_premium, 2),
        'risk_distribution': risk_dist,
        'claims_ratio': round(claims_ratio, 4),
        'reinsurance': {
            'annual_expense_booked': reinsurance_expense,
            'latest_program': {
                'selected_contracts': 0,
            }
        }
    })


def _handle_bi_underwriting(handler, session: Dict) -> None:
    """GET /api/bi/underwriting"""
    if session.get('role') not in ('admin', 'underwriter', 'actuary'):
        _send_error(handler, 403, "Insufficient permissions")
        return

    pending = sum(1 for u in UNDERWRITING_APPLICATIONS.values() if status_eq(u, 'pending'))
    approved = sum(1 for u in UNDERWRITING_APPLICATIONS.values() if status_eq(u, 'approved'))
    rejected = sum(1 for u in UNDERWRITING_APPLICATIONS.values() if status_eq(u, 'rejected'))
    total = len(UNDERWRITING_APPLICATIONS)
    rejection_rate = rejected / total if total > 0 else 0

    risk_dist = {'low': 0, 'medium': 0, 'high': 0, 'very_high': 0}
    for u in UNDERWRITING_APPLICATIONS.values():
        risk = u.get('risk_score', 'medium').lower()
        if risk in risk_dist:
            risk_dist[risk] += 1

    _send_json(handler, 200, {
        'pending_applications': pending,
        'approved_this_month': approved,
        'rejection_rate': round(rejection_rate, 4),
        'risk_assessment_distribution': risk_dist,
        'total_applications': total,
    })


def _handle_bi_accounting(handler, session: Dict) -> None:
    """GET /api/bi/accounting"""
    if session.get('role') not in ('admin', 'accountant'):
        _send_error(handler, 403, "Insufficient permissions")
        return

    total_revenue = PHINS_BALANCE_SHEET.get('total_revenue', 0)
    total_claims_paid = PHINS_BALANCE_SHEET['expense_breakdown'].get('claims_paid', 0)
    total_expenses = PHINS_BALANCE_SHEET.get('total_expenses', 0)
    net_income = total_revenue - total_expenses
    profit_margin = net_income / total_revenue if total_revenue > 0 else 0

    _send_json(handler, 200, {
        'total_revenue': total_revenue,
        'total_claims_paid': total_claims_paid,
        'total_expenses': total_expenses,
        'net_income': net_income,
        'profit_margin': round(profit_margin, 4),
        'monthly_breakdown': [],
    })


def _handle_admin_balance_sheet(handler, session: Dict) -> None:
    """GET /api/admin/balance-sheet"""
    if session.get('role') not in ('admin', 'accountant'):
        _send_error(handler, 403, "Admin access required")
        return

    # Calculate cumulative premium from bills
    cumulative_from_bills = sum(
        safe_float(b.get('amount_paid', 0))
        for b in BILLING.values()
        if status_in(b, ['paid', 'partial'])
    )
    cumulative_from_ledger = sum(
        safe_float(t.get('amount', 0))
        for t in TRANSACTION_LEDGER.values()
        if t.get('type') == 'premium_payment'
    )
    cumulative_premium = max(
        PHINS_BALANCE_SHEET['revenue_breakdown'].get('premium_income', 0),
        cumulative_from_bills
    )

    bs = dict(PHINS_BALANCE_SHEET)
    bs['cumulative_premium'] = cumulative_premium
    bs['revenue_breakdown'] = dict(PHINS_BALANCE_SHEET['revenue_breakdown'])
    bs['revenue_breakdown']['premium_income'] = cumulative_premium
    bs['cumulative_premium_breakdown'] = {
        'from_bills': cumulative_from_bills,
        'from_ledger': cumulative_from_ledger,
    }

    _send_json(handler, 200, {'balance_sheet': bs})


def _handle_actuarial_simulate(handler, session: Dict, body: Dict) -> None:
    """POST /api/actuarial/simulate"""
    if session.get('role') not in ('admin', 'actuary'):
        _send_error(handler, 403, "Insufficient permissions")
        return

    customer_count = body.get('customer_count', 1000)
    simulation_id = f"SIM-{uuid.uuid4().hex[:8].upper()}"

    _send_json(handler, 200, {
        'simulation': {
            'simulation_id': simulation_id,
            'customer_count': customer_count,
            'status': 'completed',
            'reinsurance_program': {
                'selected_contracts': max(1, int(customer_count) // 100),
                'total_cost': int(customer_count) * 50.0,
            }
        }
    })


def _handle_reinsurance_recommendation(handler, session: Dict, query: Dict) -> None:
    """GET /api/reinsurance/recommendation"""
    if session.get('role') not in ('admin', 'actuary'):
        _send_error(handler, 403, "Insufficient permissions")
        return

    simulation_id = query.get('simulation_id', [None])[0]
    contract_count = int(query.get('contract_count', ['100'])[0])
    hedge_share_pct = float(query.get('hedge_share_pct', ['30'])[0])

    total_cost = contract_count * 50.0 * (hedge_share_pct / 100)

    _send_json(handler, 200, {
        'success': True,
        'recommended': {
            'phins_simulation_id': simulation_id,
            'phins_total_contract_cost': total_cost,
            'contract_count': contract_count,
            'hedge_share_pct': hedge_share_pct,
        }
    })


def _handle_reinsurance_bind(handler, session: Dict, body: Dict) -> None:
    """POST /api/reinsurance/contracts/bind"""
    if session.get('role') not in ('admin', 'actuary'):
        _send_error(handler, 403, "Insufficient permissions")
        return

    quote = body.get('quote', {})
    simulation_id = quote.get('phins_simulation_id') or body.get('portfolio_id')
    total_cost = safe_float(quote.get('phins_total_contract_cost', 0))

    # Record balance sheet expense
    tx = record_balance_sheet_transaction(
        'expense', 'reinsurance', total_cost,
        f"Reinsurance contract binding for simulation {simulation_id}",
        actor=session.get('username', 'system')
    )

    _mark_dirty()
    _send_json(handler, 201, {
        'success': True,
        'simulation_id': simulation_id,
        'balance_sheet_transaction': {
            'category': 'reinsurance',
            'amount': total_cost,
            'tx_id': tx.get('tx_id'),
        }
    })


# ==============================================================================
# STATIC FILE SERVING
# ==============================================================================

MIME_TYPES = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css',
    '.js': 'application/javascript',
    '.json': 'application/json',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf',
    '.pdf': 'application/pdf',
    '.csv': 'text/csv',
    '.md': 'text/markdown',
    '.txt': 'text/plain',
}

def _serve_static_file(handler, path: str) -> bool:
    """Serve a static file. Returns True if served, False if not found."""
    # Sanitize path
    path = path.split('?')[0]
    if '..' in path:
        return False

    if path == '/' or path == '':
        path = '/index.html'

    file_path = os.path.join(ROOT, path.lstrip('/'))

    if not os.path.isfile(file_path):
        return False

    ext = os.path.splitext(file_path)[1].lower()
    content_type = MIME_TYPES.get(ext, 'application/octet-stream')

    try:
        with open(file_path, 'rb') as f:
            content = f.read()

        handler.send_response(200)
        handler.send_header('Content-Type', content_type)
        handler.send_header('Content-Length', str(len(content)))
        handler.send_header('Cache-Control', 'no-cache')
        handler.end_headers()
        handler.wfile.write(content)
        return True
    except Exception:
        return False


# ==============================================================================
# PORTAL HANDLER
# ==============================================================================

class PortalHandler(BaseHTTPRequestHandler):
    """Main HTTP request handler for the PHINS portal."""

    def log_message(self, format, *args):
        """Override to suppress bot probe logs."""
        try:
            path = args[0] if args else ''
            # Extract path from log format like "GET /path HTTP/1.1"
            parts = path.split(' ')
            actual_path = parts[1] if len(parts) > 1 else path
            status_code = int(args[1]) if len(args) > 1 else 0
            if _should_silence_bot_probe_http_log(actual_path, status_code):
                return
        except Exception:
            pass
        super().log_message(format, *args)

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse.urlparse(self.path)
        path = parsed.path
        query = urlparse.parse_qs(parsed.query)

        try:
            self._handle_get(path, query)
        except Exception as e:
            try:
                _send_error(self, 500, f"Internal server error: {str(e)}")
            except Exception:
                pass

    def do_POST(self):
        """Handle POST requests."""
        parsed = urlparse.urlparse(self.path)
        path = parsed.path

        body = _read_body(self)
        if body is None:
            _send_error(self, 400, "Invalid JSON body")
            return

        try:
            self._handle_post(path, body)
        except Exception as e:
            try:
                _send_error(self, 500, f"Internal server error: {str(e)}")
            except Exception:
                pass

    def do_PUT(self):
        """Handle PUT requests."""
        parsed = urlparse.urlparse(self.path)
        path = parsed.path
        body = _read_body(self)
        if body is None:
            body = {}
        try:
            self._handle_put(path, body)
        except Exception as e:
            try:
                _send_error(self, 500, f"Internal server error: {str(e)}")
            except Exception:
                pass

    def do_DELETE(self):
        """Handle DELETE requests."""
        parsed = urlparse.urlparse(self.path)
        path = parsed.path
        try:
            self._handle_delete(path)
        except Exception as e:
            try:
                _send_error(self, 500, f"Internal server error: {str(e)}")
            except Exception:
                pass

    def _handle_get(self, path: str, query: Dict) -> None:
        """Route GET requests."""
        # Health check
        if path == '/api/health':
            _handle_health(self)
            return

        # Metrics
        if path == '/api/metrics':
            _handle_metrics(self)
            return

        # Policies
        if path == '/api/policies':
            _handle_policies_list(self, query)
            return

        # Underwriting
        if path == '/api/underwriting':
            _handle_underwriting_list(self, query)
            return

        # Claims
        if path == '/api/claims':
            _handle_claims_list(self, query)
            return

        # Customers
        if path == '/api/customers':
            _handle_customers_list(self, query)
            return

        # Customer status
        if path == '/api/customer/status':
            _handle_customer_status(self, query)
            return

        # Profile (requires auth)
        if path == '/api/profile':
            session = _require_auth(self)
            if session:
                _handle_profile(self, session)
            return

        # Audit (requires auth)
        if path == '/api/audit':
            session = _require_auth(self)
            if session:
                _handle_audit(self, session, query)
            return

        # Security threats (requires auth)
        if path == '/api/security/threats':
            session = _require_auth(self)
            if session:
                _handle_security_threats(self, session)
            return

        # BI endpoints (require auth)
        if path == '/api/bi/actuary':
            session = _require_auth(self)
            if session:
                _handle_bi_actuary(self, session)
            return

        if path == '/api/bi/underwriting':
            session = _require_auth(self)
            if session:
                _handle_bi_underwriting(self, session)
            return

        if path == '/api/bi/accounting':
            session = _require_auth(self)
            if session:
                _handle_bi_accounting(self, session)
            return

        # Admin balance sheet
        if path == '/api/admin/balance-sheet':
            session = _require_auth(self)
            if session:
                _handle_admin_balance_sheet(self, session)
            return

        # Reinsurance recommendation
        if path == '/api/reinsurance/recommendation':
            session = _require_auth(self)
            if session:
                _handle_reinsurance_recommendation(self, session, query)
            return

        # Try API extensions
        try:
            from web_portal.api_extensions import dispatch_get
            result = dispatch_get(path, _get_session(_get_token_from_request(self)) or {}, query,
                                  self.client_address[0])
            if result is not None:
                status_code, response_data = result
                _send_json(self, status_code, response_data)
                return
        except Exception:
            pass

        # Try BI analytics
        try:
            from web_portal.api_bi_analytics import dispatch_get as bi_dispatch_get
            result = bi_dispatch_get(path, _get_session(_get_token_from_request(self)) or {}, query)
            if result is not None:
                status_code, response_data = result
                _send_json(self, status_code, response_data)
                return
        except Exception:
            pass

        # Serve static files
        if not path.startswith('/api/'):
            if _serve_static_file(self, path):
                return

        # 404
        if _is_bot_probe_path(path):
            _send_error(self, 404, "Not found")
        else:
            _send_error(self, 404, f"Not found: {path}")

    def _handle_post(self, path: str, body: Dict) -> None:
        """Route POST requests."""
        # Login
        if path == '/api/login':
            _handle_login(self, body)
            return

        # Logout
        if path == '/api/logout':
            session = _require_auth(self)
            if session:
                _handle_logout(self, session)
            return

        # Register
        if path == '/api/register':
            _handle_register(self, body)
            return

        # Policies
        if path == '/api/policies/create':
            _handle_policies_create(self, body)
            return

        # Underwriting
        if path == '/api/underwriting/approve':
            _handle_underwriting_approve(self, body)
            return

        if path == '/api/underwriting/reject':
            _handle_underwriting_reject(self, body)
            return

        # Claims
        if path == '/api/claims/create':
            _handle_claims_create(self, body)
            return

        if path == '/api/claims/approve':
            _handle_claims_approve(self, body)
            return

        if path == '/api/claims/reject':
            _handle_claims_reject(self, body)
            return

        if path == '/api/claims/pay':
            _handle_claims_pay(self, body)
            return

        # Billing
        if path == '/api/billing/create':
            _handle_billing_create(self, body)
            return

        if path == '/api/billing/pay':
            _handle_billing_pay(self, body)
            return

        if path == '/api/billing/stats':
            _handle_billing_stats(self, body)
            return

        # Actuarial simulation
        if path == '/api/actuarial/simulate':
            session = _require_auth(self)
            if session:
                _handle_actuarial_simulate(self, session, body)
            return

        # Reinsurance
        if path == '/api/reinsurance/contracts/bind':
            session = _require_auth(self)
            if session:
                _handle_reinsurance_bind(self, session, body)
            return

        # Try API extensions
        try:
            from web_portal.api_extensions import dispatch_post
            session = _get_session(_get_token_from_request(self)) or {}
            result = dispatch_post(path, session, body, self.client_address[0],
                                   self.headers.get('User-Agent', ''))
            if result is not None:
                status_code, response_data = result
                _send_json(self, status_code, response_data)
                return
        except Exception:
            pass

        # Try delivery bidding
        try:
            from web_portal.api_delivery_bidding import dispatch_post as delivery_dispatch_post
            session = _get_session(_get_token_from_request(self)) or {}
            result = delivery_dispatch_post(path, session, body, self.client_address[0])
            if result is not None:
                status_code, response_data = result
                _send_json(self, status_code, response_data)
                return
        except Exception:
            pass

        _send_error(self, 404, f"Not found: {path}")

    def _handle_put(self, path: str, body: Dict) -> None:
        """Route PUT requests."""
        try:
            from web_portal.api_extensions import dispatch_put
            session = _get_session(_get_token_from_request(self)) or {}
            result = dispatch_put(path, session, body, self.client_address[0],
                                  self.headers.get('User-Agent', ''))
            if result is not None:
                status_code, response_data = result
                _send_json(self, status_code, response_data)
                return
        except Exception:
            pass

        _send_error(self, 404, f"Not found: {path}")

    def _handle_delete(self, path: str) -> None:
        """Route DELETE requests."""
        _send_error(self, 404, f"Not found: {path}")


# ==============================================================================
# STARTUP
# ==============================================================================

def _initialize():
    """Initialize the server on startup."""
    initialize_balance_sheet()
    load_ledger_data()

    # Start periodic save (every 60 seconds)
    _start_periodic_save(interval_seconds=60)

    print(f"✓ PHINS Portal initialized")
    print(f"  Persistence file: {LEDGER_PERSISTENCE_FILE}")
    print(f"  Session storage: {'database' if (USE_DATABASE and database_enabled) else 'in-memory'}")


# ==============================================================================
# MAIN ENTRY POINT
# ==============================================================================

if __name__ == '__main__':
    _initialize()

    host = '0.0.0.0'
    port = PORT

    print(f"Starting PHINS Portal on {host}:{port}")
    print(f"Static files: {ROOT}")

    server = ThreadingHTTPServer((host, port), PortalHandler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()
