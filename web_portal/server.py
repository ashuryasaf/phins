#!/usr/bin/env python3
"""
Lightweight web portal server (dependency-free) for demo purposes.

Usage:
  python web_portal/server.py       # start server on http://localhost:8000
  python web_portal/server.py --test  # run quick local tests and exit

This server exposes simple JSON endpoints and serves static files from
`web_portal/static/`. It's intended as a minimal demo backend suitable
for mobile-friendly web UI or to be used by a simple mobile app prototype.
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
from typing import Dict, Any

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
    except ImportError as e:
        print(f"Warning: Database support not available: {e}")
        print("         Falling back to in-memory storage (DATA WILL BE LOST ON RESTART)")
        USE_DATABASE = False
else:
    print("⚠️  WARNING: Running in volatile in-memory mode (USE_DATABASE=false)")
    print("   Data will be LOST when server restarts. Set USE_DATABASE=true for persistence.")

PORT = 8000
ROOT = os.path.join(os.path.dirname(__file__), "static")

# Storage - either database-backed or in-memory
if USE_DATABASE and database_enabled:
    # Use database-backed dictionaries
    POLICIES = DB_POLICIES
    CLAIMS = DB_CLAIMS
    CUSTOMERS = DB_CUSTOMERS
    UNDERWRITING_APPLICATIONS = DB_UNDERWRITING
    SESSIONS = DB_SESSIONS
    BILLING = DB_BILLING
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
CUSTOMER_ALLOCATIONS: Dict[str, Dict[str, Any]] = {}  # customer_id -> {savings_pct, risk_pct, index_pct, bonds_pct, crypto_pct, updated_at}

# Investment accounts - additional customer savings deposits
INVESTMENT_ACCOUNTS: Dict[str, Dict[str, Any]] = {}  # customer_id -> {balance, deposits: [], allocations: [], created_at}

# Transaction ledger - master ledger for all financial transactions
TRANSACTION_LEDGER: Dict[str, Dict[str, Any]] = {}  # tx_id -> transaction data

# ========== DATA PERSISTENCE LAYER ==========
# Path for persistent storage file
LEDGER_PERSISTENCE_FILE = os.environ.get('LEDGER_PERSISTENCE_FILE', '/tmp/phins_ledger_data.json')
PERSISTENCE_ENABLED = os.environ.get('ENABLE_LEDGER_PERSISTENCE', 'true').lower() == 'true'
_persistence_lock = threading.Lock()

def save_ledger_data():
    """Save all ledger data to persistent storage"""
    if not PERSISTENCE_ENABLED:
        return
    
    try:
        with _persistence_lock:
            data = {
                'saved_at': datetime.now().isoformat(),
                'version': '1.0',
                'health_wallets': HEALTH_WALLETS,
                'medical_purchases': MEDICAL_PURCHASES,
                'nft_ledger': NFT_LEDGER,
                'customer_allocations': CUSTOMER_ALLOCATIONS,
                'investment_accounts': INVESTMENT_ACCOUNTS,
                'transaction_ledger': TRANSACTION_LEDGER
            }
            
            # Write to temp file first, then rename for atomic operation
            temp_file = LEDGER_PERSISTENCE_FILE + '.tmp'
            with open(temp_file, 'w') as f:
                json.dump(data, f, default=str, indent=2)
            
            # Atomic rename
            os.rename(temp_file, LEDGER_PERSISTENCE_FILE)
            print(f"[PERSISTENCE] Saved ledger data to {LEDGER_PERSISTENCE_FILE}")
    except Exception as e:
        print(f"[PERSISTENCE] Error saving ledger data: {e}")

def load_ledger_data():
    """Load ledger data from persistent storage on startup"""
    global HEALTH_WALLETS, MEDICAL_PURCHASES, NFT_LEDGER, CUSTOMER_ALLOCATIONS, INVESTMENT_ACCOUNTS, TRANSACTION_LEDGER
    
    if not PERSISTENCE_ENABLED:
        print("[PERSISTENCE] Persistence disabled, using in-memory storage only")
        return False
    
    if not os.path.exists(LEDGER_PERSISTENCE_FILE):
        print(f"[PERSISTENCE] No persistence file found at {LEDGER_PERSISTENCE_FILE}, starting fresh")
        return False
    
    try:
        with open(LEDGER_PERSISTENCE_FILE, 'r') as f:
            data = json.load(f)
        
        # Load each data store
        HEALTH_WALLETS.update(data.get('health_wallets', {}))
        MEDICAL_PURCHASES.update(data.get('medical_purchases', {}))
        NFT_LEDGER.update(data.get('nft_ledger', {}))
        CUSTOMER_ALLOCATIONS.update(data.get('customer_allocations', {}))
        INVESTMENT_ACCOUNTS.update(data.get('investment_accounts', {}))
        TRANSACTION_LEDGER.update(data.get('transaction_ledger', {}))
        
        print(f"[PERSISTENCE] Loaded ledger data from {LEDGER_PERSISTENCE_FILE}")
        print(f"  - Health Wallets: {len(HEALTH_WALLETS)}")
        print(f"  - Medical Purchases: {len(MEDICAL_PURCHASES)}")
        print(f"  - NFT Ledger: {len(NFT_LEDGER)}")
        print(f"  - Customer Allocations: {len(CUSTOMER_ALLOCATIONS)}")
        print(f"  - Investment Accounts: {len(INVESTMENT_ACCOUNTS)}")
        print(f"  - Transaction Ledger: {len(TRANSACTION_LEDGER)}")
        print(f"  - Saved at: {data.get('saved_at', 'unknown')}")
        return True
    except Exception as e:
        print(f"[PERSISTENCE] Error loading ledger data: {e}")
        return False

def schedule_periodic_save():
    """Schedule periodic saves of ledger data"""
    def save_loop():
        while True:
            time.sleep(60)  # Save every 60 seconds
            save_ledger_data()
    
    if PERSISTENCE_ENABLED:
        save_thread = threading.Thread(target=save_loop, daemon=True)
        save_thread.start()
        print("[PERSISTENCE] Started periodic save thread (every 60 seconds)")

# ========== END DATA PERSISTENCE LAYER ==========

# ========== REAL-TIME BANKING/TRADING/BILLING CONNECTIONS ==========
# Configuration for connecting to external financial services
REAL_TIME_CONFIG = {
    # Banking APIs (prepared for real-time connections)
    'banking': {
        'plaid': {
            'enabled': os.environ.get('PLAID_ENABLED', 'false').lower() == 'true',
            'client_id': os.environ.get('PLAID_CLIENT_ID', ''),
            'secret': os.environ.get('PLAID_SECRET', ''),
            'environment': os.environ.get('PLAID_ENVIRONMENT', 'sandbox'),  # sandbox, development, production
            'supported_products': ['auth', 'transactions', 'balance', 'identity'],
            'webhook_url': os.environ.get('PLAID_WEBHOOK_URL', '')
        },
        'stripe_connect': {
            'enabled': os.environ.get('STRIPE_CONNECT_ENABLED', 'false').lower() == 'true',
            'api_key': os.environ.get('STRIPE_SECRET_KEY', ''),
            'publishable_key': os.environ.get('STRIPE_PUBLISHABLE_KEY', ''),
            'webhook_secret': os.environ.get('STRIPE_WEBHOOK_SECRET', '')
        },
        'ach': {
            'enabled': os.environ.get('ACH_ENABLED', 'false').lower() == 'true',
            'provider': os.environ.get('ACH_PROVIDER', 'stripe'),  # stripe, plaid, dwolla
            'routing_validation': True,
            'micro_deposit_verification': True
        }
    },
    # Trading APIs (prepared for real-time market connections)
    'trading': {
        'alpaca': {
            'enabled': os.environ.get('ALPACA_ENABLED', 'false').lower() == 'true',
            'api_key': os.environ.get('ALPACA_API_KEY', ''),
            'api_secret': os.environ.get('ALPACA_API_SECRET', ''),
            'base_url': os.environ.get('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets'),  # paper or live
            'data_url': 'https://data.alpaca.markets',
            'supported_markets': ['US_EQUITY', 'CRYPTO']
        },
        'coinbase_pro': {
            'enabled': os.environ.get('COINBASE_ENABLED', 'false').lower() == 'true',
            'api_key': os.environ.get('COINBASE_API_KEY', ''),
            'api_secret': os.environ.get('COINBASE_API_SECRET', ''),
            'passphrase': os.environ.get('COINBASE_PASSPHRASE', ''),
            'sandbox': os.environ.get('COINBASE_SANDBOX', 'true').lower() == 'true'
        },
        'interactive_brokers': {
            'enabled': os.environ.get('IB_ENABLED', 'false').lower() == 'true',
            'gateway_host': os.environ.get('IB_GATEWAY_HOST', 'localhost'),
            'gateway_port': int(os.environ.get('IB_GATEWAY_PORT', '4002')),  # 4001=live, 4002=paper
            'client_id': int(os.environ.get('IB_CLIENT_ID', '1')),
            'account_type': os.environ.get('IB_ACCOUNT_TYPE', 'paper')
        }
    },
    # Billing/Subscription Management
    'billing': {
        'stripe_billing': {
            'enabled': os.environ.get('STRIPE_BILLING_ENABLED', 'false').lower() == 'true',
            'api_key': os.environ.get('STRIPE_SECRET_KEY', ''),
            'webhook_secret': os.environ.get('STRIPE_BILLING_WEBHOOK', ''),
            'default_currency': 'usd',
            'auto_invoice': True,
            'proration_behavior': 'create_prorations'
        },
        'paypal_subscriptions': {
            'enabled': os.environ.get('PAYPAL_SUBSCRIPTIONS_ENABLED', 'false').lower() == 'true',
            'client_id': os.environ.get('PAYPAL_CLIENT_ID', ''),
            'client_secret': os.environ.get('PAYPAL_SECRET', ''),
            'sandbox': os.environ.get('PAYPAL_SANDBOX', 'true').lower() == 'true'
        }
    },
    # Market Data Providers
    'market_data': {
        'polygon': {
            'enabled': os.environ.get('POLYGON_ENABLED', 'false').lower() == 'true',
            'api_key': os.environ.get('POLYGON_API_KEY', ''),
            'websocket_enabled': True,
            'subscription_type': 'starter'  # starter, developer, advanced
        },
        'finnhub': {
            'enabled': os.environ.get('FINNHUB_ENABLED', 'false').lower() == 'true',
            'api_key': os.environ.get('FINNHUB_API_KEY', ''),
            'premium': False
        },
        'coingecko': {
            'enabled': True,  # Free API, always available
            'api_url': 'https://api.coingecko.com/api/v3',
            'pro_api_key': os.environ.get('COINGECKO_API_KEY', '')
        }
    },
    # Webhook Configuration
    'webhooks': {
        'base_url': os.environ.get('WEBHOOK_BASE_URL', 'https://phins-portal-production.up.railway.app'),
        'endpoints': {
            'stripe': '/webhooks/stripe',
            'paypal': '/webhooks/paypal',
            'plaid': '/webhooks/plaid',
            'trading': '/webhooks/trading'
        },
        'signing_secret': os.environ.get('WEBHOOK_SIGNING_SECRET', secrets.token_hex(32))
    }
}

def get_real_time_status() -> Dict[str, Any]:
    """Get status of all real-time connections"""
    return {
        'banking': {
            'plaid': REAL_TIME_CONFIG['banking']['plaid']['enabled'],
            'stripe_connect': REAL_TIME_CONFIG['banking']['stripe_connect']['enabled'],
            'ach': REAL_TIME_CONFIG['banking']['ach']['enabled']
        },
        'trading': {
            'alpaca': REAL_TIME_CONFIG['trading']['alpaca']['enabled'],
            'coinbase_pro': REAL_TIME_CONFIG['trading']['coinbase_pro']['enabled'],
            'interactive_brokers': REAL_TIME_CONFIG['trading']['interactive_brokers']['enabled']
        },
        'billing': {
            'stripe_billing': REAL_TIME_CONFIG['billing']['stripe_billing']['enabled'],
            'paypal_subscriptions': REAL_TIME_CONFIG['billing']['paypal_subscriptions']['enabled']
        },
        'market_data': {
            'polygon': REAL_TIME_CONFIG['market_data']['polygon']['enabled'],
            'finnhub': REAL_TIME_CONFIG['market_data']['finnhub']['enabled'],
            'coingecko': REAL_TIME_CONFIG['market_data']['coingecko']['enabled']
        },
        'persistence': {
            'enabled': PERSISTENCE_ENABLED,
            'file_path': LEDGER_PERSISTENCE_FILE
        }
    }

# ========== END REAL-TIME CONNECTIONS CONFIG ==========


def get_customer_allocation(customer_id: str) -> Dict[str, float]:
    """Get customer's allocation preferences or return defaults"""
    default_allocation = {
        'savings_pct': 25.0,  # % of premium to savings/investments
        'risk_pct': 75.0,     # % of premium to risk coverage
        'index_pct': 60.0,    # % of savings to index funds
        'bonds_pct': 30.0,    # % of savings to bonds
        'crypto_pct': 10.0,   # % of savings to crypto
    }
    
    if customer_id in CUSTOMER_ALLOCATIONS:
        return {**default_allocation, **CUSTOMER_ALLOCATIONS[customer_id]}
    return default_allocation


def update_customer_allocation(customer_id: str, allocations: Dict[str, float]) -> Dict[str, Any]:
    """Update customer's allocation preferences with validation"""
    # Validate percentages
    savings_pct = allocations.get('savings_pct', 25.0)
    risk_pct = allocations.get('risk_pct', 75.0)
    
    # Savings + Risk must equal 100%
    if abs((savings_pct + risk_pct) - 100.0) > 0.01:
        raise ValueError("Savings + Risk percentages must equal 100%")
    
    # Investment allocation (of savings) must equal 100%
    index_pct = allocations.get('index_pct', 60.0)
    bonds_pct = allocations.get('bonds_pct', 30.0)
    crypto_pct = allocations.get('crypto_pct', 10.0)
    
    if abs((index_pct + bonds_pct + crypto_pct) - 100.0) > 0.01:
        raise ValueError("Index + Bonds + Crypto percentages must equal 100%")
    
    # Crypto max 30%
    if crypto_pct > 30.0:
        raise ValueError("Crypto allocation cannot exceed 30%")
    
    # Savings must be at least 10% (regulatory requirement)
    if savings_pct < 10.0:
        raise ValueError("Savings allocation must be at least 10%")
    
    allocation_record = {
        'savings_pct': savings_pct,
        'risk_pct': risk_pct,
        'index_pct': index_pct,
        'bonds_pct': bonds_pct,
        'crypto_pct': crypto_pct,
        'updated_at': datetime.now().isoformat(),
        'customer_id': customer_id
    }
    
    CUSTOMER_ALLOCATIONS[customer_id] = allocation_record
    return allocation_record


def record_transaction(
    customer_id: str,
    tx_type: str,
    amount: float,
    description: str,
    metadata: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Record transaction in master ledger and NFT ledger"""
    tx_id = f"TX-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(10000, 99999)}"
    
    transaction = {
        'id': tx_id,
        'customer_id': customer_id,
        'type': tx_type,
        'amount': amount,
        'description': description,
        'metadata': metadata or {},
        'timestamp': datetime.now().isoformat(),
        'status': 'completed'
    }
    
    # Store in transaction ledger
    TRANSACTION_LEDGER[tx_id] = transaction
    
    # Also create NFT token for blockchain record
    nft_token = generate_nft_token(
        customer_id=customer_id,
        transaction_type=tx_type,
        transaction_id=tx_id,
        amount=amount,
        description=description,
        metadata=metadata
    )
    NFT_LEDGER[nft_token['token_id']] = nft_token
    
    transaction['nft_token_id'] = nft_token['token_id']
    
    # Trigger async save to persist changes
    threading.Thread(target=save_ledger_data, daemon=True).start()
    
    return transaction

def generate_nft_token(
    customer_id: str,
    transaction_type: str,
    transaction_id: str,
    amount: float,
    description: str,
    metadata: Dict[str, Any] = None
) -> Dict[str, Any]:
    """Generate an NFT token for transaction integrity and ledger tracking"""
    import hashlib
    token_id = f"NFT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(10000, 99999)}"
    
    # Create transaction hash for integrity
    hash_data = f"{token_id}{customer_id}{transaction_id}{amount}{datetime.now().isoformat()}"
    transaction_hash = hashlib.sha256(hash_data.encode()).hexdigest()[:16]
    
    # Create verification hash
    verification_data = json.dumps({
        'token_id': token_id,
        'customer_id': customer_id,
        'transaction_type': transaction_type,
        'amount': amount
    }, sort_keys=True)
    verification_hash = hashlib.sha3_256(verification_data.encode()).hexdigest()[:32]
    
    nft_token = {
        'token_id': token_id,
        'chain_type': 'PHINS-CHAIN',
        'transaction_hash': transaction_hash,
        'verification_hash': verification_hash,
        'owner_id': customer_id,
        'owner_type': 'customer',
        'transaction_type': transaction_type,
        'transaction_id': transaction_id,
        'amount': amount,
        'description': description,
        'metadata': metadata or {},
        'created_at': datetime.now().isoformat(),
        'status': 'confirmed',
        'block_number': random.randint(1000000, 9999999),
        'gas_fee': 0.0,  # No gas fees on PHINS-CHAIN
        'smart_contract_ref': f"PHINS-SC-{datetime.now().strftime('%Y%m')}-WALLET"
    }
    
    # Store in NFT ledger
    NFT_LEDGER[token_id] = nft_token
    
    return nft_token
try:
    from services.audit_service import AuditService
    audit = AuditService()
except Exception:
    audit = None

# Pipeline service for automatic workflow progression
pipeline_service = None
try:
    from services.pipeline_service import PipelineService
    pipeline_enabled = True
except ImportError:
    pipeline_enabled = False
    print("Warning: Pipeline service not available")

# Marketplace service for services, products, and NFT tokens
marketplace = None
try:
    from services.marketplace_service import get_marketplace_service, PaymentType
    marketplace = get_marketplace_service()
    marketplace_enabled = True
    print("✓ Marketplace service enabled (services, products, NFT tokens)")
except ImportError as e:
    marketplace_enabled = False
    print(f"Warning: Marketplace service not available: {e}")

# Investment Portfolio Service for savings/investment management
portfolio_service = None
try:
    from services.investment_portfolio_service import get_portfolio_service, RiskProfile, AssetClass
    portfolio_service = get_portfolio_service()
    portfolio_enabled = True
    print("✓ Investment Portfolio service enabled (savings, crypto, indexes)")
except ImportError as e:
    portfolio_enabled = False
    print(f"Warning: Investment Portfolio service not available: {e}")

# Algo Trading Service for automated trading strategies
algo_trading_service = None
algo_trading_enabled = False
try:
    from services.algo_trading_service import get_algo_trading_service, TradingStrategy
    if portfolio_service:
        algo_trading_service = get_algo_trading_service(portfolio_service)
        algo_trading_enabled = True
        print("✓ Algo Trading service enabled (automated strategies, signals, bot trading)")
except ImportError as e:
    print(f"Warning: Algo Trading service not available: {e}")

# Unified Balance Service for cross-system balance management
unified_balance_service = None
unified_balance_enabled = False

# Initialize pipeline service with data stores
def _init_pipeline():
    global pipeline_service
    if pipeline_enabled and pipeline_service is None:
        pipeline_service = PipelineService(
            customers=CUSTOMERS,
            policies=POLICIES,
            underwriting=UNDERWRITING_APPLICATIONS,
            billing=BILLING,
            claims=CLAIMS,
            audit_service=audit
        )
        print("✓ Pipeline service initialized (auto-workflow enabled)")

_init_pipeline()

# Initialize unified balance service after data stores are available
def _init_unified_balance():
    global unified_balance_service, unified_balance_enabled
    try:
        from services.unified_balance_service import init_unified_balance_service
        unified_balance_service = init_unified_balance_service(
            health_wallets=HEALTH_WALLETS,
            investment_accounts=INVESTMENT_ACCOUNTS,
            transaction_ledger=TRANSACTION_LEDGER,
            nft_ledger=NFT_LEDGER,
            record_transaction_func=record_transaction,
            generate_nft_token_func=generate_nft_token,
            portfolio_service=portfolio_service,
            algo_trading_service=algo_trading_service
        )
        unified_balance_enabled = True
        print("✓ Unified Balance service enabled (cross-system balance management)")
    except ImportError as e:
        print(f"Warning: Unified Balance service not available: {e}")

_init_unified_balance()

# Initialize savings pipeline service for AI-powered fund allocation
savings_pipeline_service = None
savings_pipeline_enabled = False

def _init_savings_pipeline():
    global savings_pipeline_service, savings_pipeline_enabled
    try:
        from services.savings_pipeline_service import init_savings_pipeline_service
        savings_pipeline_service = init_savings_pipeline_service(
            unified_balance_service=unified_balance_service,
            portfolio_service=portfolio_service,
            algo_trading_service=algo_trading_service,
            record_transaction_func=record_transaction,
            generate_nft_token_func=generate_nft_token,
            # Pass global data stores for proper persistence
            health_wallets=HEALTH_WALLETS,
            investment_accounts=INVESTMENT_ACCOUNTS,
            transaction_ledger=TRANSACTION_LEDGER,
            nft_ledger=NFT_LEDGER
        )
        savings_pipeline_enabled = True
        print("✓ Savings Pipeline service enabled (AI-powered fund allocation)")
    except ImportError as e:
        print(f"Warning: Savings Pipeline service not available: {e}")

_init_savings_pipeline()

# Initialize Portfolio Tracker service for real-time P&L monitoring
portfolio_tracker_service = None
portfolio_tracker_enabled = False

def _init_portfolio_tracker():
    global portfolio_tracker_service, portfolio_tracker_enabled
    try:
        from services.portfolio_tracker_service import init_portfolio_tracker
        portfolio_tracker_service = init_portfolio_tracker(
            health_wallets=HEALTH_WALLETS,
            investment_accounts=INVESTMENT_ACCOUNTS,
            transaction_ledger=TRANSACTION_LEDGER,
            nft_ledger=NFT_LEDGER,
            record_transaction_func=record_transaction,
            generate_nft_token_func=generate_nft_token
        )
        portfolio_tracker_enabled = True
        print("✓ Portfolio Tracker service enabled (real-time P&L monitoring)")
    except ImportError as e:
        print(f"Warning: Portfolio Tracker service not available: {e}")

_init_portfolio_tracker()

# Optional: admin datasets (actuarial tables) and market data (crypto/index)
try:
    from security.vault import encrypt_json
except Exception:
    encrypt_json = None  # type: ignore

try:
    from services.market_data_service import MarketDataService
    _market_data = MarketDataService()
except Exception:
    _market_data = None

# Security tracking
RATE_LIMIT: Dict[str, Dict[str, Any]] = {}  # IP -> {count, reset_time}
FAILED_LOGINS: Dict[str, Dict[str, Any]] = {}  # IP -> {count, lockout_until}
BLOCKED_IPS: Dict[str, Dict[str, Any]] = {}  # IP -> {reason, blocked_at, attempts}
MALICIOUS_ATTEMPTS: list[Dict[str, Any]] = []  # Log of all malicious attempts
SUSPICIOUS_PATTERNS: Dict[str, Dict[str, Any]] = {}  # IP -> {pattern_type, count, first_seen}
MAX_REQUESTS_PER_MINUTE = 60
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION = 900  # 15 minutes in seconds
MAX_MALICIOUS_ATTEMPTS = 10  # Permanent block after this many attempts
MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10MB max request size
SESSION_TIMEOUT = 3600  # 1 hour session timeout
CONNECTION_TIMEOUT = 30  # 30 seconds connection timeout
MAX_SESSIONS_PER_IP = 10  # Max concurrent sessions per IP
CLEANUP_INTERVAL = 300  # Cleanup stale data every 5 minutes
last_cleanup = datetime.now()

# Global lock for in-process shared state (threaded server safety)
STATE_LOCK = threading.RLock()

# Admin data stores (in-memory fallback when DB is disabled)
ACTUARIAL_TABLES: Dict[str, Dict[str, Any]] = {}  # table_id -> metadata + encrypted payload
TOKEN_REGISTRY: Dict[str, Dict[str, Any]] = {}  # entry_id -> token metadata

# Hash passwords for security (in production, use proper password hashing)
def hash_password(password: str) -> dict[str, str]:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return {'hash': hashed.hex(), 'salt': salt}

def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
    return secrets.compare_digest(hashed.hex(), stored_hash)

def validate_session(token: str) -> dict[str, str] | None:
    """Validate session token and return user info or None"""
    if not token or not token.startswith('phins_'):
        return None

    with STATE_LOCK:
        session = SESSIONS.get(token)
        if not session:
            return None

        # Check if session expired
        try:
            expires = datetime.fromisoformat(session['expires'])
            if datetime.now() > expires:
                try:
                    del SESSIONS[token]
                except Exception:
                    # Best-effort cleanup (DB-backed dict may not support del in all cases)
                    pass
                return None
        except (KeyError, ValueError):
            return None

        return session

def check_rate_limit(client_ip: str) -> bool:
    """Check if client has exceeded rate limit"""
    now = datetime.now().timestamp()

    with STATE_LOCK:
        if client_ip in RATE_LIMIT:
            limit_data = RATE_LIMIT[client_ip]
            # Reset counter if minute has passed
            if now > limit_data['reset_time']:
                RATE_LIMIT[client_ip] = {'count': 1, 'reset_time': now + 60}
                return True
            elif limit_data['count'] < MAX_REQUESTS_PER_MINUTE:
                limit_data['count'] += 1
                return True
            else:
                return False
        else:
            RATE_LIMIT[client_ip] = {'count': 1, 'reset_time': now + 60}
            return True

def check_login_lockout(client_ip: str) -> bool:
    """Check if IP is locked out due to failed login attempts"""
    with STATE_LOCK:
        if client_ip in FAILED_LOGINS:
            lockout_data = FAILED_LOGINS[client_ip]
            if datetime.now().timestamp() < lockout_data.get('lockout_until', 0):
                return False  # Still locked out
            elif lockout_data['count'] >= MAX_LOGIN_ATTEMPTS:
                # Reset after lockout period
                del FAILED_LOGINS[client_ip]
        return True

def record_failed_login(client_ip: str):
    """Record a failed login attempt"""
    with STATE_LOCK:
        if client_ip not in FAILED_LOGINS:
            FAILED_LOGINS[client_ip] = {'count': 0}

        FAILED_LOGINS[client_ip]['count'] += 1

        if FAILED_LOGINS[client_ip]['count'] >= MAX_LOGIN_ATTEMPTS:
            FAILED_LOGINS[client_ip]['lockout_until'] = datetime.now().timestamp() + LOCKOUT_DURATION

def require_role(session: dict[str, str] | None, allowed_roles: list[str]) -> bool:
    """Check if user has required role"""
    if not session:
        return False
    
    username = session.get('username')
    if not username:
        return False
    
    user = USERS.get(username)
    if not user:
        return False
    
    return user.get('role') in allowed_roles


def get_session_user(session: dict[str, str] | None) -> Dict[str, Any] | None:
    """Resolve the user dict from a session (best-effort)."""
    if not session:
        return None
    username = session.get('username')
    if not username:
        return None
    with STATE_LOCK:
        return USERS.get(username)

def log_malicious_attempt(client_ip: str, reason: str, details: Dict[str, Any] | None = None):
    """Log a malicious attempt for monitoring and analysis"""
    attempt: Dict[str, Any] = {
        'timestamp': datetime.now().isoformat(),
        'ip': client_ip,
        'reason': reason,
        'details': details or {}
    }
    with STATE_LOCK:
        MALICIOUS_ATTEMPTS.append(attempt)

        # Keep only last 1000 attempts in memory
        if len(MALICIOUS_ATTEMPTS) > 1000:
            MALICIOUS_ATTEMPTS.pop(0)

        # Check if IP should be permanently blocked
        ip_attempts = sum(1 for a in MALICIOUS_ATTEMPTS if a['ip'] == client_ip)
        if ip_attempts >= MAX_MALICIOUS_ATTEMPTS:
            block_ip(client_ip, f"Exceeded {MAX_MALICIOUS_ATTEMPTS} malicious attempts", permanent=True)

    # Print to console for real-time monitoring
    print(f"🚨 SECURITY ALERT: {client_ip} - {reason}")
    if details:
        print(f"   Details: {json.dumps(details, indent=2)}")

def block_ip(client_ip: str, reason: str, permanent: bool = False):
    """Block an IP address"""
    with STATE_LOCK:
        BLOCKED_IPS[client_ip] = {
            'reason': reason,
            'blocked_at': datetime.now().isoformat(),
            'permanent': permanent,
            'attempts': BLOCKED_IPS.get(client_ip, {}).get('attempts', 0) + 1
        }
    print(f"🚫 BLOCKED IP: {client_ip} - {reason} {'(PERMANENT)' if permanent else ''}")

def is_ip_blocked(client_ip: str) -> tuple[bool, str]:
    """Check if IP is blocked, returns (is_blocked, reason)"""
    with STATE_LOCK:
        if client_ip in BLOCKED_IPS:
            block_data = BLOCKED_IPS[client_ip]
            if block_data.get('permanent'):
                return (True, block_data['reason'])
            # Temporary blocks expire after 24 hours
            blocked_at = datetime.fromisoformat(block_data['blocked_at'])
            if datetime.now() - blocked_at < timedelta(hours=24):
                return (True, block_data['reason'])
            else:
                del BLOCKED_IPS[client_ip]
        return (False, "")

def detect_sql_injection(value: str) -> bool:
    """Detect potential SQL injection attempts"""
    sql_patterns = [
        "' OR '", '" OR "', "1=1", "1' OR '1", 'DROP TABLE', 'DELETE FROM',
        'INSERT INTO', 'UPDATE ', 'UNION SELECT', '--', '/*', '*/', 'xp_',
        'sp_', 'EXEC ', 'EXECUTE', ';--', "';--", '";--'
    ]
    value_upper = value.upper()
    return any(pattern.upper() in value_upper for pattern in sql_patterns)

def detect_xss_attempt(value: str) -> bool:
    """Detect potential XSS (Cross-Site Scripting) attempts"""
    xss_patterns = [
        '<script', '</script>', 'javascript:', 'onerror=', 'onload=',
        'onclick=', 'onmouseover=', '<iframe', '<object', '<embed',
        'eval(', 'alert(', 'document.cookie', 'window.location'
    ]
    value_lower = value.lower()
    return any(pattern.lower() in value_lower for pattern in xss_patterns)

def detect_path_traversal(value: str) -> bool:
    """Detect path traversal attempts"""
    patterns = ['../', '..\\', '%2e%2e', '%252e%252e', '/etc/passwd', '/etc/shadow']
    return any(pattern in value.lower() for pattern in patterns)

def detect_command_injection(value: str) -> bool:
    """Detect command injection attempts"""
    patterns = ['&&', '||', ';', '|', '`', '$(', 'system(', 'exec(', 'shell_exec', 'passthru', 
                'wget', 'curl', 'nc ', 'netcat', '/bin/', '/dev/', 'chmod', 'chown']
    return any(pattern in value for pattern in patterns)

def detect_malicious_payload(value: str) -> bool:
    """Detect various malicious payloads and exploits"""
    malicious_patterns = [
        # Code execution
        'eval(', 'exec(', '__import__', 'compile(', 'globals()',
        # File operations
        'open(', 'file(', 'read(', 'write(',
        # System access
        'os.system', 'subprocess', 'popen', 'pty.spawn',
        # Reverse shells
        'socket', 'connect(', 'bind(', 'listen(',
        # Crypto mining (specific patterns - not blocking "crypto" as it's a valid API param)
        'cryptominer', 'cryptojacking', 'coinhive', 'monero.', 'xmrig',
        # Data exfiltration 
        'pickle', 'marshal', 'shelve',
        # LDAP injection
        '(|', '(&', '(!(', '*)(', ')(&',
        # XML injection
        '<!ENTITY', '<!DOCTYPE', 'SYSTEM \"',
        # SSRF
        'file://', 'gopher://', 'dict://', 'ftp://', 'tftp://',
        # Template injection
        '{{', '{%', '<%', '#{', '@{'
    ]
    value_lower = value.lower()
    return any(pattern.lower() in value_lower for pattern in malicious_patterns)

def cleanup_stale_data():
    """Clean up expired sessions, old rate limits, and stale security data"""
    global last_cleanup
    now = datetime.now()
    
    # Only cleanup every CLEANUP_INTERVAL seconds
    if (now - last_cleanup).total_seconds() < CLEANUP_INTERVAL:
        return
    
    last_cleanup = now
    timestamp = now.timestamp()
    
    with STATE_LOCK:
        # Clean expired sessions
        expired_sessions = [token for token, sess in SESSIONS.items()
                           if datetime.fromisoformat(sess['expires']) < now]
        for token in expired_sessions:
            try:
                del SESSIONS[token]
            except Exception:
                pass

        # Clean expired rate limits
        expired_limits = [ip for ip, data in RATE_LIMIT.items()
                         if timestamp > data['reset_time'] + 300]  # 5 min grace
        for ip in expired_limits:
            del RATE_LIMIT[ip]

        # Clean expired login lockouts
        expired_lockouts = [ip for ip, data in FAILED_LOGINS.items()
                           if timestamp > data.get('lockout_until', 0) + 300]
        for ip in expired_lockouts:
            del FAILED_LOGINS[ip]

        # Clean old temporary IP blocks (keep permanent ones)
        expired_blocks = [ip for ip, data in BLOCKED_IPS.items()
                         if not data.get('permanent') and
                         (now - datetime.fromisoformat(data['blocked_at'])).total_seconds() > 86400]
        for ip in expired_blocks:
            del BLOCKED_IPS[ip]

        # Trim malicious attempts log to last 1000
        if len(MALICIOUS_ATTEMPTS) > 1000:
            MALICIOUS_ATTEMPTS[:] = MALICIOUS_ATTEMPTS[-1000:]
    
    if expired_sessions or expired_limits or expired_lockouts or expired_blocks:
        print(f"🧹 Cleanup: Removed {len(expired_sessions)} sessions, {len(expired_limits)} rate limits, "
              f"{len(expired_lockouts)} lockouts, {len(expired_blocks)} blocks")

def check_session_limit(client_ip: str) -> bool:
    """Check if IP has too many concurrent sessions"""
    with STATE_LOCK:
        active_sessions = sum(1 for sess in SESSIONS.values()
                             if sess.get('ip') == client_ip and
                             datetime.fromisoformat(sess['expires']) > datetime.now())
        return active_sessions < MAX_SESSIONS_PER_IP

def validate_input_security(value: str, client_ip: str, field_name: str = 'input') -> tuple[bool, str | None]:
    """Comprehensive input validation, returns (is_valid, error_message)"""
    if not value:
        return (True, None)
    
    value_str = str(value)
    
    # Check for SQL injection
    if detect_sql_injection(value_str):
        log_malicious_attempt(client_ip, 'SQL Injection Attempt', {
            'field': field_name,
            'value_length': len(value_str),
            'sample': value_str[:100]
        })
        block_ip(client_ip, 'SQL Injection detected', permanent=False)
        return (False, 'Invalid input detected')
    
    # Check for XSS
    if detect_xss_attempt(value_str):
        log_malicious_attempt(client_ip, 'XSS Attempt', {
            'field': field_name,
            'value_length': len(value_str),
            'sample': value_str[:100]
        })
        block_ip(client_ip, 'XSS attack detected', permanent=False)
        return (False, 'Invalid input detected')
    
    # Check for path traversal
    if detect_path_traversal(value_str):
        log_malicious_attempt(client_ip, 'Path Traversal Attempt', {
            'field': field_name,
            'value': value_str[:100]
        })
        block_ip(client_ip, 'Path traversal detected', permanent=False)
        return (False, 'Invalid input detected')
    
    # Check for command injection
    if detect_command_injection(value_str):
        log_malicious_attempt(client_ip, 'Command Injection Attempt', {
            'field': field_name,
            'value': value_str[:100]
        })
        block_ip(client_ip, 'Command injection detected', permanent=False)
        return (False, 'Invalid input detected')
    
    # Check for malicious payloads
    if detect_malicious_payload(value_str):
        log_malicious_attempt(client_ip, 'Malicious Payload Detected', {
            'field': field_name,
            'value_length': len(value_str),
            'sample': value_str[:100]
        })
        block_ip(client_ip, 'Malicious code detected', permanent=True)
        return (False, 'Invalid input detected')
    
    return (True, None)

def sanitize_input(value: str, max_length: int = 255) -> str:
    """Sanitize user input to prevent injection attacks"""
    if not value:
        return ''
    
    # Truncate to max length
    value = str(value)[:max_length]
    
    # Remove potentially dangerous characters
    dangerous_chars = ['<', '>', '"', "'", '\\', '\x00', '\n', '\r', '\t']
    for char in dangerous_chars:
        value = value.replace(char, '')
    
    return value.strip()

def validate_email(email: str) -> bool:
    """Basic email validation"""
    import re
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email)) and len(email) <= 254

def validate_amount(amount: Any) -> bool:
    """Validate monetary amounts"""
    try:
        amount = float(amount)
        return 0 <= amount <= 100000000  # Max 100 million
    except (ValueError, TypeError):
        return False

# Store hashed passwords
if USE_DATABASE and database_enabled:
    # Users are stored in database, but we need a helper to check them
    # We'll create a wrapper that checks the database
    class UserDictWrapper:
        """Wrapper to make database users work like a dict"""
        def get(self, username: str, default=None):
            try:
                from database.manager import DatabaseManager
                with DatabaseManager() as db:
                    user = db.users.get_by_username(username)
                    if user:
                        # Get customer_id - either from user record or by looking up by email
                        customer_id = getattr(user, 'customer_id', None)
                        if not customer_id and user.role == 'customer':
                            # Try to find customer by email using repository
                            customer = db.customers.get_by_email(username)
                            if customer:
                                customer_id = customer.id
                        
                        return {
                            'hash': user.password_hash,
                            'salt': user.password_salt,
                            'role': user.role,
                            'name': user.name,
                            'customer_id': customer_id
                        }
            except ImportError as e:
                print(f"Warning: Database module not available: {e}")
            except Exception as e:
                print(f"Warning: Error fetching user from database: {e}")
            return default
        
        def __getitem__(self, username: str):
            result = self.get(username)
            if result is None:
                raise KeyError(username)
            return result
        
        def __setitem__(self, username: str, value: dict):
            """Create or update a user in the database"""
            try:
                from database.manager import DatabaseManager
                with DatabaseManager() as db:
                    existing_user = db.users.get_by_username(username)
                    if existing_user:
                        # Update existing user
                        db.users.update(
                            existing_user.id,
                            password_hash=value.get('hash'),
                            password_salt=value.get('salt'),
                            role=value.get('role', existing_user.role),
                            name=value.get('name', existing_user.name),
                            customer_id=value.get('customer_id', existing_user.customer_id)
                        )
                    else:
                        # Create new user
                        db.users.create(
                            username=username,
                            password_hash=value.get('hash'),
                            password_salt=value.get('salt'),
                            role=value.get('role', 'customer'),
                            name=value.get('name', username),
                            email=username,  # Username is email for customers
                            customer_id=value.get('customer_id'),
                            active=True
                        )
            except Exception as e:
                print(f"Warning: Error creating/updating user in database: {e}")
                raise
        
        def __contains__(self, username: str):
            return self.get(username) is not None
    
    USERS = UserDictWrapper()
else:
    USERS: Dict[str, Dict[str, Any]] = {
        'admin': {**hash_password('PDadmin123@'), 'role': 'admin', 'name': 'Admin User'},
        'underwriter': {**hash_password('PDadmin123@'), 'role': 'underwriter', 'name': 'John Underwriter'},
        'claims_adjuster': {**hash_password('PDadmin123@'), 'role': 'claims', 'name': 'Jane Claims'},
        'accountant': {**hash_password('PDadmin123@'), 'role': 'accountant', 'name': 'Bob Accountant'}
    }


def get_mock_statement(customer_id: str) -> Dict[str, Any]:
    return {
        "customer_id": customer_id,
        "total_premium": 300.0,
        "risk_total": 225.0,
        "savings_total": 75.0,
        "allocations": [
            {"allocation_id": "ALLOC-000001", "amount": 100.0, "risk_amount": 75.0, "savings_amount": 25.0},
            {"allocation_id": "ALLOC-000002", "amount": 100.0, "risk_amount": 75.0, "savings_amount": 25.0},
            {"allocation_id": "ALLOC-000003", "amount": 100.0, "risk_amount": 75.0, "savings_amount": 25.0},
        ],
    }


def generate_policy_id() -> str:
    return f"POL-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"

def generate_claim_id() -> str:
    return f"CLM-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"

def generate_customer_id() -> str:
    return f"CUST-{random.randint(10000, 99999)}"

def calculate_premium(policy_data: Dict[str, Any]) -> Dict[str, float]:
    """Calculate premium based on policy type and customer data"""
    base_premium = {
        'life': 1200,
        'health': 800,
        'auto': 600,
        'property': 1500,
        'business': 3000
    }.get(policy_data.get('type', 'life'), 1000)
    
    # Age factor
    age = policy_data.get('age', 30)
    age_factor = 1.0 + (max(0, age - 25) * 0.02)
    
    # Coverage factor
    coverage = policy_data.get('coverage_amount', 100000)
    coverage_factor = coverage / 100000
    
    # Risk factor based on underwriting
    risk_score = policy_data.get('risk_score', 'medium')
    risk_factors = {'low': 0.8, 'medium': 1.0, 'high': 1.3, 'very_high': 1.6}
    risk_factor = risk_factors.get(risk_score, 1.0)
    
    annual_premium = base_premium * age_factor * coverage_factor * risk_factor
    return {
        'annual': round(annual_premium, 2),
        'monthly': round(annual_premium / 12, 2),
        'quarterly': round(annual_premium / 4, 2)
    }

def get_bi_data_actuary() -> Dict[str, Any]:
    """Generate actuarial BI data"""
    # Best-effort include actuarial upload state (table governance signal)
    actuarial_count = len(ACTUARIAL_TABLES)
    latest_uploaded = None
    try:
        if ACTUARIAL_TABLES:
            latest_uploaded = sorted(
                ACTUARIAL_TABLES.values(),
                key=lambda x: x.get('created_date', ''),
                reverse=True
            )[0].get('created_date')
    except Exception:
        latest_uploaded = None

    return {
        'total_policies': len(POLICIES),
        'total_exposure': sum(p.get('coverage_amount', 0) for p in POLICIES.values()),
        'average_premium': sum(p.get('annual_premium', 0) for p in POLICIES.values()) / max(len(POLICIES), 1),
        'risk_distribution': {
            'low': sum(1 for p in POLICIES.values() if p.get('risk_score') == 'low'),
            'medium': sum(1 for p in POLICIES.values() if p.get('risk_score') == 'medium'),
            'high': sum(1 for p in POLICIES.values() if p.get('risk_score') == 'high'),
            'very_high': sum(1 for p in POLICIES.values() if p.get('risk_score') == 'very_high')
        },
        'claims_ratio': len(CLAIMS) / max(len(POLICIES), 1),
        'loss_ratio': sum(c.get('approved_amount', 0) for c in CLAIMS.values() if c.get('status') == 'paid') / max(sum(p.get('annual_premium', 0) for p in POLICIES.values()), 1),
        'policy_by_type': {
            'life': sum(1 for p in POLICIES.values() if p.get('type') == 'life'),
            'health': sum(1 for p in POLICIES.values() if p.get('type') == 'health'),
            'auto': sum(1 for p in POLICIES.values() if p.get('type') == 'auto'),
            'property': sum(1 for p in POLICIES.values() if p.get('type') == 'property')
        },
        'actuarial_tables': {
            'count': actuarial_count,
            'latest_uploaded': latest_uploaded
        }
    }

def get_bi_data_underwriting() -> Dict[str, Any]:
    """Generate underwriting BI data"""
    return {
        'pending_applications': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('status') == 'pending'),
        'approved_this_month': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('status') == 'approved' and u.get('decision_date', '').startswith(datetime.now().strftime('%Y-%m'))),
        'rejection_rate': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('status') == 'rejected') / max(len(UNDERWRITING_APPLICATIONS), 1),
        'average_processing_time': 3.5,  # days
        'risk_assessment_distribution': {
            'low': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('risk_assessment') == 'low'),
            'medium': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('risk_assessment') == 'medium'),
            'high': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('risk_assessment') == 'high'),
            'very_high': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('risk_assessment') == 'very_high')
        },
        'medical_exams_required': sum(1 for u in UNDERWRITING_APPLICATIONS.values() if u.get('medical_exam_required', False))
    }

def get_bi_data_accounting() -> Dict[str, Any]:
    """Generate accounting BI data"""
    total_premium_collected = sum(p.get('annual_premium', 0) for p in POLICIES.values() if p.get('status') == 'active')
    total_claims_paid = sum(c.get('approved_amount', 0) for c in CLAIMS.values() if c.get('status') == 'paid')
    
    return {
        'total_revenue': total_premium_collected,
        'total_claims_paid': total_claims_paid,
        'net_income': total_premium_collected - total_claims_paid,
        'outstanding_premiums': sum(p.get('annual_premium', 0) * 0.1 for p in POLICIES.values()),  # Mock 10% outstanding
        'pending_claims_liability': sum(c.get('claimed_amount', 0) for c in CLAIMS.values() if c.get('status') in ['pending', 'under_review']),
        'profit_margin': ((total_premium_collected - total_claims_paid) / max(total_premium_collected, 1)) * 100,
        'monthly_breakdown': [
            {'month': (datetime.now() - timedelta(days=30*i)).strftime('%Y-%m'), 
             'revenue': total_premium_collected / 12, 
             'claims': total_claims_paid / 12}
            for i in range(12)
        ][::-1]
    }

def try_get_statement_from_engine(customer_id: str) -> Any:
    try:
        import accounting_engine as ae

        engine = ae.AccountingEngine()
        # Try to call a best-effort method and coerce result to JSON-serializable
        if hasattr(engine, "get_customer_statement"):
            stmt = engine.get_customer_statement(customer_id)  # type: ignore
            try:
                result: Any = json.loads(json.dumps(stmt, default=lambda o: o.__dict__))
                return result
            except Exception:
                return stmt  # type: ignore
    except Exception:
        pass
    return None


class PortalHandler(BaseHTTPRequestHandler):
    def _set_json_headers(self, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # Security headers
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'")
        self.end_headers()
    
    def _generate_text_policy_document(self, policy: Dict, customer: Dict, underwriting: Dict, bills: list, claims: list) -> None:
        """Fallback text document generation when PDF library not available"""
        questionnaire = underwriting.get('questionnaire_responses', {})
        payment_setup = underwriting.get('payment_setup', {})
        health_wallet_info = underwriting.get('health_wallet', {}) or policy.get('health_wallet', {})
        customer_id = policy.get('customer_id')
        
        doc_content = f"""
================================================================================
                           PHINS INSURANCE COMPANY
                        COMPREHENSIVE POLICY DOCUMENT
================================================================================

Document Generated: {datetime.now().strftime('%B %d, %Y at %H:%M:%S')}
Policy Number: {policy.get('id', 'N/A')}
Policy Status: {(policy.get('status', 'Unknown')).replace('_', ' ').title()}
Underwriting Reference: {policy.get('underwriting_id', 'N/A')}

--------------------------------------------------------------------------------
                    SECTION 1: POLICYHOLDER INFORMATION
--------------------------------------------------------------------------------

Full Name: {customer.get('name', underwriting.get('customer_name', 'N/A'))}
Customer ID: {customer_id or 'N/A'}
Email Address: {customer.get('email', underwriting.get('customer_email', 'N/A'))}
Phone Number: {customer.get('phone', 'N/A')}
Age at Application: {underwriting.get('age', 'N/A')} years
Occupation: {customer.get('occupation', questionnaire.get('occupation', 'N/A'))}

--------------------------------------------------------------------------------
                       SECTION 2: COVERAGE DETAILS
--------------------------------------------------------------------------------

Policy Type: {policy.get('type', 'life').upper()}
Coverage Amount: ${policy.get('coverage_amount', 0):,.2f}
Annual Premium: ${policy.get('annual_premium', 0):,.2f}
Monthly Premium: ${policy.get('monthly_premium', 0):,.2f}
Risk Classification: {(policy.get('risk_score', 'Standard')).replace('_', ' ').title()}
Effective Date: {policy.get('start_date', 'N/A')[:10] if policy.get('start_date') else 'N/A'}
Expiration Date: {policy.get('end_date', 'N/A')[:10] if policy.get('end_date') else 'N/A'}
Medical Exam Required: {'Yes' if underwriting.get('medical_exam_required') else 'No'}

--------------------------------------------------------------------------------
                 SECTION 3: HEALTH & LIFESTYLE ASSESSMENT
--------------------------------------------------------------------------------

Tobacco Use: {questionnaire.get('smoke', 'Not Specified')}
Pre-existing Conditions: {'Yes' if questionnaire.get('medical_conditions') == 'yes' else 'None Reported'}
Prior Surgeries (5 years): {'Yes' if questionnaire.get('surgery') == 'yes' else 'None Reported'}
Hazardous Activities: {questionnaire.get('hazardous_activities', 'None')}
Height: {questionnaire.get('height', 'N/A')} cm
Weight: {questionnaire.get('weight', 'N/A')} kg

--------------------------------------------------------------------------------
                SECTION 4: BILLING & PAYMENT CONFIGURATION
--------------------------------------------------------------------------------

Billing Frequency: {payment_setup.get('billing_frequency', 'monthly').title()}
Auto-Pay Enabled: {'Yes' if payment_setup.get('auto_pay') else 'No'}
Payment Method: {(payment_setup.get('card_type', 'Card')).title()} ending in {payment_setup.get('card_last4', '****')}
Cardholder Name: {payment_setup.get('cardholder_name', 'N/A')}

--------------------------------------------------------------------------------
                     SECTION 5: PHINS HEALTH WALLET
--------------------------------------------------------------------------------

Health Wallet Status: {'Enabled' if health_wallet_info.get('enabled') else 'Not Enabled'}
Monthly Auto-Deposit: ${health_wallet_info.get('monthly_deposit', 0):,.2f}

--------------------------------------------------------------------------------
                     SECTION 6: ACCOUNT STATISTICS
--------------------------------------------------------------------------------

Total Policies: {len([p for p in POLICIES.values() if p.get('customer_id') == customer_id])}
Total Claims Filed: {len(claims)}
Application Submitted: {underwriting.get('submitted_date', 'N/A')[:10] if underwriting.get('submitted_date') else 'N/A'}

--------------------------------------------------------------------------------
                       TERMS AND CONDITIONS
--------------------------------------------------------------------------------

This policy is subject to the terms, conditions, and exclusions set forth in 
the PHINS Insurance Company Master Policy Agreement.

Coverage is contingent upon timely payment of premiums and compliance with 
all policy requirements.

For claims or questions, please contact:
- Phone: 1-800-PHINS-HELP
- Email: support@phins.ai
- Web: https://phins.ai

--------------------------------------------------------------------------------

(c) {datetime.now().year} PHINS Insurance Company. All rights reserved.

================================================================================
""".strip()
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.send_header('Content-Disposition', f'attachment; filename="PHINS_Policy_{policy.get("id", "unknown")}.txt"')
        self.end_headers()
        self.wfile.write(doc_content.encode('utf-8'))

    def _set_file_headers(self, path: str) -> None:
        self.send_response(200)
        if path.endswith('.html'):
            self.send_header('Content-Type', 'text/html; charset=utf-8')
        elif path.endswith('.js'):
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
        elif path.endswith('.css'):
            self.send_header('Content-Type', 'text/css; charset=utf-8')
        else:
            self.send_header('Content-Type', 'application/octet-stream')
        # Security headers
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("X-XSS-Protection", "1; mode=block")
        self.end_headers()

    def do_GET(self):
        # Periodic cleanup of stale data
        cleanup_stale_data()
        
        # Security checks
        client_ip = self.client_address[0]
        
        # Check if IP is blocked
        is_blocked, block_reason = is_ip_blocked(client_ip)
        if is_blocked:
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'error': 'Access denied',
                'message': 'Your IP has been blocked due to suspicious activity'
            }).encode('utf-8'))
            return
        
        # Rate limiting
        if not check_rate_limit(client_ip):
            log_malicious_attempt(client_ip, 'Rate Limit Exceeded', {'endpoint': self.path})
            self.send_response(429)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Retry-After', '60')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Too many requests. Please try again later.'}).encode('utf-8'))
            return
        
        parsed = urlparse.urlparse(self.path)
        path = parsed.path
        qs = urlparse.parse_qs(parsed.query)
        
        # Redirect deprecated client-portal.html to main dashboard
        if path == '/client-portal.html':
            self.send_response(301)
            self.send_header('Location', '/dashboard.html')
            self.end_headers()
            return
        
        # Validate query parameters for injection attacks
        for key, values in qs.items():
            for value in values:
                is_valid, error = validate_input_security(value, client_ip, f"query_param_{key}")
                if not is_valid:
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({'error': error}).encode('utf-8'))
                    return

        # Session validation
        auth_header = self.headers.get('Authorization', '')
        token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
        session = validate_session(token) if token else None
        is_authenticated = session is not None
        
        # Security monitoring endpoint (Admin only)
        if path == '/api/security/threats':
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return
            
            # Get query parameters
            limit = int(qs.get('limit', [100])[0])
            
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'malicious_attempts': MALICIOUS_ATTEMPTS[-limit:],
                'blocked_ips': dict(list(BLOCKED_IPS.items())[-50:]),  # Last 50 blocked IPs
                'failed_logins': {k: v for k, v in list(FAILED_LOGINS.items())[-20:]},  # Last 20
                'statistics': {
                    'total_malicious_attempts': len(MALICIOUS_ATTEMPTS),
                    'total_blocked_ips': len(BLOCKED_IPS),
                    'permanent_blocks': sum(1 for b in BLOCKED_IPS.values() if b.get('permanent')),
                    'active_lockouts': sum(1 for f in FAILED_LOGINS.values() 
                                          if f.get('lockout_until', 0) > datetime.now().timestamp())
                }
            }, default=str).encode('utf-8'))
            return
        
        # System status endpoint - shows real-time connection status
        if path == '/api/system/status':
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'status': 'healthy',
                'timestamp': datetime.now().isoformat(),
                'version': '2.0.0',
                'ledger_stats': {
                    'health_wallets': len(HEALTH_WALLETS),
                    'medical_purchases': len(MEDICAL_PURCHASES),
                    'nft_tokens': len(NFT_LEDGER),
                    'transactions': len(TRANSACTION_LEDGER),
                    'investment_accounts': len(INVESTMENT_ACCOUNTS),
                    'customer_allocations': len(CUSTOMER_ALLOCATIONS)
                },
                'real_time_connections': get_real_time_status(),
                'persistence': {
                    'enabled': PERSISTENCE_ENABLED,
                    'file_path': LEDGER_PERSISTENCE_FILE,
                    'file_exists': os.path.exists(LEDGER_PERSISTENCE_FILE) if PERSISTENCE_ENABLED else False
                },
                'services': {
                    'database': database_enabled if 'database_enabled' in dir() else False,
                    'portfolio': portfolio_enabled if 'portfolio_enabled' in dir() else False,
                    'algo_trading': algo_trading_enabled if 'algo_trading_enabled' in dir() else False,
                    'unified_balance': unified_balance_enabled if 'unified_balance_enabled' in dir() else False,
                    'savings_pipeline': savings_pipeline_enabled if 'savings_pipeline_enabled' in dir() else False,
                    'marketplace': marketplace_enabled if 'marketplace_enabled' in dir() else False
                }
            }, default=str).encode('utf-8'))
            return
        
        # Security: Clear blocked IPs (Admin only or with security key)
        if path == '/api/security/clear-blocks':
            # Allow with admin auth OR special security key for emergency access
            security_key = qs.get('key', [''])[0]
            is_authorized = require_role(session, ['admin']) or security_key == 'phins-security-2024'
            
            if not is_authorized:
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access or security key required.'}).encode('utf-8'))
                return
            
            ip_to_clear = qs.get('ip', [''])[0]
            
            with STATE_LOCK:
                if ip_to_clear:
                    # Clear specific IP
                    cleared = 0
                    if ip_to_clear in BLOCKED_IPS:
                        del BLOCKED_IPS[ip_to_clear]
                        cleared += 1
                    if ip_to_clear in FAILED_LOGINS:
                        del FAILED_LOGINS[ip_to_clear]
                        cleared += 1
                    if ip_to_clear in SUSPICIOUS_PATTERNS:
                        del SUSPICIOUS_PATTERNS[ip_to_clear]
                        cleared += 1
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True,
                        'message': f'Cleared {cleared} records for IP {ip_to_clear}',
                        'ip': ip_to_clear
                    }).encode('utf-8'))
                else:
                    # Clear all blocks
                    blocked_count = len(BLOCKED_IPS)
                    failed_count = len(FAILED_LOGINS)
                    suspicious_count = len(SUSPICIOUS_PATTERNS)
                    
                    BLOCKED_IPS.clear()
                    FAILED_LOGINS.clear()
                    SUSPICIOUS_PATTERNS.clear()
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True,
                        'message': 'All security blocks cleared',
                        'cleared': {
                            'blocked_ips': blocked_count,
                            'failed_logins': failed_count,
                            'suspicious_patterns': suspicious_count
                        }
                    }).encode('utf-8'))
            return

        # Audit log endpoint (Admin only)
        if path == '/api/audit':
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return
            # Pagination and basic filtering
            page = int(qs.get('page', ['1'])[0])
            page_size = int(qs.get('page_size', ['50'])[0])
            page = max(1, page)
            page_size = max(1, min(500, page_size))
            actor = qs.get('actor', [None])[0]
            action = qs.get('action', [None])[0]
            entity_type = qs.get('entity_type', [None])[0]
            logs = []
            try:
                # audit may be None if service unavailable
                if audit and hasattr(audit, 'recent'):
                    logs = audit.recent(10000)  # recent window
                else:
                    logs = []
            except Exception:
                logs = []
            # Apply filters
            def _match(entry: Dict[str, Any]) -> bool:
                if actor and entry.get('actor') != actor:
                    return False
                if action and entry.get('action') != action:
                    return False
                if entity_type and entry.get('entity_type') != entity_type:
                    return False
                return True
            filtered = [e for e in logs if _match(e)]
            start = (page - 1) * page_size
            end = start + page_size
            payload = {
                'items': filtered[start:end],
                'page': page,
                'page_size': page_size,
                'total': len(filtered)
            }
            self._set_json_headers()
            self.wfile.write(json.dumps(payload, default=str).encode('utf-8'))
            return
        
        # User Profile Endpoint
        if path == '/api/profile':
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            
            username = session.get('username')
            if not username:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'User not found'}).encode('utf-8'))
                return
            user = get_session_user(session)
            
            if not user:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'User not found'}).encode('utf-8'))
                return

            # Best-effort enrich with customer record fields (email/phone/dob)
            customer_id = user.get('customer_id') or session.get('customer_id')
            customer = None
            if customer_id:
                with STATE_LOCK:
                    customer = CUSTOMERS.get(customer_id)
            
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'username': username,
                'name': user.get('name'),
                'role': user.get('role'),
                'customer_id': customer_id,
                'email': (customer.get('email') if isinstance(customer, dict) else None) or username,
                'phone': (customer.get('phone') if isinstance(customer, dict) else None),
                'dob': (customer.get('dob') if isinstance(customer, dict) else None),
            }).encode('utf-8'))
            return
        
        # BI Dashboard Endpoints (Admin/Management only)
        if path == '/api/bi/actuary':
            if not require_role(session, ['admin', 'accountant', 'underwriter']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return
            self._set_json_headers()
            self.wfile.write(json.dumps(get_bi_data_actuary()).encode('utf-8'))
            return
        
        if path == '/api/bi/underwriting':
            if not require_role(session, ['admin', 'underwriter']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return
            self._set_json_headers()
            self.wfile.write(json.dumps(get_bi_data_underwriting()).encode('utf-8'))
            return
        
        if path == '/api/bi/accounting':
            if not require_role(session, ['admin', 'accountant']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return
            self._set_json_headers()
            self.wfile.write(json.dumps(get_bi_data_accounting()).encode('utf-8'))
            return
        
        # BI Dashboard - comprehensive admin dashboard statistics
        if path == '/api/bi/dashboard':
            if not require_role(session, ['admin', 'accountant', 'underwriter']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return
            
            # Calculate comprehensive dashboard stats
            total_customers = len(CUSTOMERS)
            total_policies = len(POLICIES)
            active_policies = len([p for p in POLICIES.values() if p.get('status') == 'active'])
            pending_applications = len([a for a in UNDERWRITING_APPLICATIONS.values() if a.get('status') == 'pending'])
            approved_applications = len([a for a in UNDERWRITING_APPLICATIONS.values() if a.get('status') == 'approved'])
            
            # Claims stats
            total_claims = len(CLAIMS)
            pending_claims = len([c for c in CLAIMS.values() if c.get('status') in ['pending', 'under_review', 'medical_assessment']])
            approved_claims = len([c for c in CLAIMS.values() if c.get('status') == 'approved'])
            
            # Billing stats
            total_revenue = sum(b.get('amount', 0) for b in BILLING.values() if b.get('status') == 'paid')
            total_premium_collected = sum(b.get('amount', 0) for b in BILLING.values())
            outstanding_balance = sum(b.get('amount', 0) for b in BILLING.values() if b.get('status') == 'outstanding')
            
            # Health wallet stats
            total_wallet_balance = sum(w.get('balance', 0) for w in HEALTH_WALLETS.values())
            total_deposits = sum(t.get('amount', 0) for w in HEALTH_WALLETS.values() for t in w.get('transactions', []) if t.get('type') == 'deposit')
            
            # Investment stats
            total_investment_value = sum(p.get('investment_value', 0) for p in POLICIES.values())
            total_coverage_amount = sum(p.get('coverage_amount', 0) for p in POLICIES.values() if p.get('status') == 'active')
            
            # Claims payment stats
            claims_paid = sum(c.get('amount_approved', 0) for c in CLAIMS.values() if c.get('status') == 'approved')
            
            dashboard_data = {
                'success': True,
                # Customer metrics
                'total_customers': total_customers,
                'new_customers_this_month': len([c for c in CUSTOMERS.values() if c.get('created_at', '')[:7] == datetime.now().strftime('%Y-%m')]),
                
                # Policy metrics
                'total_policies': total_policies,
                'active_policies': active_policies,
                'pending_policies': len([p for p in POLICIES.values() if p.get('status') == 'pending_underwriting']),
                
                # Underwriting metrics
                'total_applications': len(UNDERWRITING_APPLICATIONS),
                'pending_applications': pending_applications,
                'approved_applications': approved_applications,
                'rejected_applications': len([a for a in UNDERWRITING_APPLICATIONS.values() if a.get('status') == 'rejected']),
                
                # Claims metrics
                'total_claims': total_claims,
                'pending_claims': pending_claims,
                'approved_claims': approved_claims,
                'rejected_claims': len([c for c in CLAIMS.values() if c.get('status') == 'rejected']),
                'claims_paid_amount': claims_paid,
                
                # Financial metrics
                'total_revenue': total_revenue,
                'total_premium_collected': total_premium_collected,
                'outstanding_balance': outstanding_balance,
                'total_investment_value': total_investment_value,
                'total_coverage_amount': total_coverage_amount,
                'total_aum': total_investment_value + total_wallet_balance,
                
                # Wallet metrics
                'total_wallet_balance': total_wallet_balance,
                'total_deposits': total_deposits,
                'active_wallets': len([w for w in HEALTH_WALLETS.values() if w.get('balance', 0) > 0]),
                
                # Pipeline summary
                'pipeline': {
                    'registered': len([c for c in CUSTOMERS.values()]),
                    'applied': len(UNDERWRITING_APPLICATIONS),
                    'underwriting': pending_applications,
                    'approved': approved_applications,
                    'active': active_policies,
                    'billing': len([b for b in BILLING.values() if b.get('status') == 'outstanding']),
                    'claims': pending_claims
                },
                
                'timestamp': datetime.now().isoformat()
            }
            
            self._set_json_headers()
            self.wfile.write(json.dumps(dashboard_data).encode('utf-8'))
            return
        
        # Financial Reporting Endpoints
        if path == '/api/financial/portfolio-report':
            if not require_role(session, ['admin', 'accountant']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            try:
                from services.financial_reporting_service import FinancialReportingService
                svc = FinancialReportingService(POLICIES, CLAIMS, BILLING, CUSTOMERS, UNDERWRITING_APPLICATIONS)
                report = svc.generate_portfolio_report()
                self._set_json_headers()
                self.wfile.write(json.dumps(report).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        if path == '/api/financial/forecast':
            if not require_role(session, ['admin', 'accountant']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            try:
                years = int(qs.get('years', [25])[0])
                from services.financial_reporting_service import FinancialReportingService
                svc = FinancialReportingService(POLICIES, CLAIMS, BILLING, CUSTOMERS, UNDERWRITING_APPLICATIONS)
                report = svc.generate_forecast_report(years=years)
                self._set_json_headers()
                self.wfile.write(json.dumps(report).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        if path == '/api/financial/customer-projection':
            if not require_role(session, ['admin', 'accountant', 'underwriter', 'customer']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            try:
                # Get parameters from query string with defaults
                coverage = float(qs.get('coverage', [250000])[0])
                savings_pct = float(qs.get('savings_pct', [0.50])[0])
                adl_level = int(qs.get('adl_level', [5])[0])
                term_years = int(qs.get('term_years', [25])[0])
                age = int(qs.get('age', [35])[0])
                customer_id = qs.get('customer_id', [None])[0]
                
                from services.financial_reporting_service import FinancialReportingService
                svc = FinancialReportingService(POLICIES, CLAIMS, BILLING, CUSTOMERS, UNDERWRITING_APPLICATIONS)
                report = svc.generate_customer_projection(
                    customer_id=customer_id,
                    coverage=coverage,
                    savings_pct=savings_pct,
                    adl_level=adl_level,
                    term_years=term_years,
                    age=age
                )
                self._set_json_headers()
                self.wfile.write(json.dumps(report).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        if path == '/api/financial/data-integrity':
            if not require_role(session, ['admin', 'accountant']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            try:
                from services.financial_reporting_service import FinancialReportingService
                svc = FinancialReportingService(POLICIES, CLAIMS, BILLING, CUSTOMERS, UNDERWRITING_APPLICATIONS)
                report = svc.validate_data_integrity()
                self._set_json_headers()
                self.wfile.write(json.dumps(report).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        if path == '/api/financial/dashboard-summary':
            if not require_role(session, ['admin', 'accountant', 'underwriter', 'claims', 'customer']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            try:
                dashboard_type = qs.get('type', ['accountant'])[0]
                from services.financial_reporting_service import FinancialReportingService
                svc = FinancialReportingService(POLICIES, CLAIMS, BILLING, CUSTOMERS, UNDERWRITING_APPLICATIONS)
                report = svc.get_dashboard_summary(dashboard_type)
                self._set_json_headers()
                self.wfile.write(json.dumps(report).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        if path == '/api/financial/premium-calculator':
            if not require_role(session, ['admin', 'accountant', 'underwriter', 'customer']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            try:
                coverage = float(qs.get('coverage', [250000])[0])
                age = int(qs.get('age', [35])[0])
                adl_level = int(qs.get('adl_level', [5])[0])
                savings_pct = float(qs.get('savings_pct', [0.50])[0])
                term_years = int(qs.get('term_years', [25])[0])
                
                from services.financial_reporting_service import FinancialReportingService
                svc = FinancialReportingService(POLICIES, CLAIMS, BILLING, CUSTOMERS, UNDERWRITING_APPLICATIONS)
                premium = svc.calculate_premium(coverage, age, adl_level, savings_pct, term_years)
                self._set_json_headers()
                self.wfile.write(json.dumps(premium).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return

        # Platform Metrics Endpoint (for dashboards)
        if path == '/api/metrics':
            try:
                from services.metrics_service import MetricsService
                ms = MetricsService(POLICIES, CLAIMS, BILLING)
                data = ms.summary()
            except Exception:
                data = {
                    'policies': {'total': len(POLICIES), 'active': sum(1 for p in POLICIES.values() if p.get('status') == 'active')},
                    'claims': {'pending': sum(1 for c in CLAIMS.values() if c.get('status') in ['pending', 'under_review']),
                               'approved': sum(1 for c in CLAIMS.values() if c.get('status') == 'approved')},
                    'billing': {'overdue': sum(1 for b in BILLING.values() if b.get('status') == 'overdue'),
                                'outstanding': sum(1 for b in BILLING.values() if b.get('status') in ['outstanding', 'partial'])}
                }
            self._set_json_headers()
            self.wfile.write(json.dumps({'metrics': data, 'ts': datetime.now().isoformat()}).encode('utf-8'))
            return

        # Market data endpoints (crypto + indexes)
        if path == '/api/market/crypto':
            if not require_role(session, ['admin', 'accountant', 'customer', 'underwriter', 'claims']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            symbols = qs.get('symbols', ['BTC,ETH'])[0]
            symbols_list = [s.strip() for s in symbols.split(',') if s.strip()]
            if not _market_data:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Market data service unavailable'}).encode('utf-8'))
                return
            try:
                data = _market_data.get_crypto_prices_usd(symbols_list)
                self._set_json_headers()
                self.wfile.write(json.dumps(data).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(502)
                self.wfile.write(json.dumps({'error': 'Market data fetch failed', 'details': str(e)}).encode('utf-8'))
            return

        if path == '/api/market/index':
            if not require_role(session, ['admin', 'accountant', 'customer', 'underwriter', 'claims']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            symbols = qs.get('symbols', ['^spx'])[0]
            symbols_list = [s.strip() for s in symbols.split(',') if s.strip()]
            if not _market_data:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Market data service unavailable'}).encode('utf-8'))
                return
            try:
                data = _market_data.get_index_quotes(symbols_list)
                self._set_json_headers()
                self.wfile.write(json.dumps(data).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(502)
                self.wfile.write(json.dumps({'error': 'Market data fetch failed', 'details': str(e)}).encode('utf-8'))
            return

        # Admin: list actuarial tables (metadata only)
        if path == '/api/admin/actuarial-tables':
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return

            # DB mode: list via repository; otherwise in-memory list.
            if USE_DATABASE and database_enabled:
                try:
                    from database.manager import DatabaseManager
                    with DatabaseManager() as db:
                        tables = [t.to_dict() for t in db.actuarial.list(limit=200)]
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'items': tables}).encode('utf-8'))
                    return
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': 'Failed to load actuarial tables', 'details': str(e)}).encode('utf-8'))
                    return

            with STATE_LOCK:
                items = list(ACTUARIAL_TABLES.values())
            items = sorted(items, key=lambda x: x.get('created_date', ''), reverse=True)
            self._set_json_headers()
            self.wfile.write(json.dumps({'items': items}).encode('utf-8'))
            return

        # Token registry (enabled-only for customers)
        if path == '/api/token-registry':
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return

            user = get_session_user(session) or {}
            role = (user.get('role') or '').lower()
            enabled_only = role == 'customer'

            if USE_DATABASE and database_enabled:
                try:
                    from database.manager import DatabaseManager
                    with DatabaseManager() as db:
                        rows = [r.to_dict() for r in db.tokens.list(enabled_only=enabled_only, limit=500)]
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'items': rows}).encode('utf-8'))
                    return
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': 'Failed to load token registry', 'details': str(e)}).encode('utf-8'))
                    return

            with STATE_LOCK:
                rows = list(TOKEN_REGISTRY.values())
            if enabled_only:
                rows = [r for r in rows if r.get('enabled', True)]
            self._set_json_headers()
            self.wfile.write(json.dumps({'items': rows}).encode('utf-8'))
            return
        
        # Policy Management Endpoints
        if path == '/api/policies':
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return

            user = get_session_user(session) or {}
            role = (user.get('role') or '').lower()
            session_customer_id = user.get('customer_id') or session.get('customer_id')

            policy_id = qs.get('id', [None])[0]
            if policy_id:
                policy = POLICIES.get(policy_id)
                # Customers can only view their own policies
                if policy and (role != 'customer' or (session_customer_id and policy.get('customer_id') == session_customer_id)):
                    self._set_json_headers()
                    self.wfile.write(json.dumps(policy).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Policy not found'}).encode('utf-8'))
            else:
                all_items = list(POLICIES.values())
                if role == 'customer' and session_customer_id:
                    all_items = [p for p in all_items if p.get('customer_id') == session_customer_id]

                wants_paging = ('page' in qs) or ('page_size' in qs)
                if not wants_paging:
                    # Backward-compatible: older UIs expect a plain list
                    self._set_json_headers()
                    self.wfile.write(json.dumps(all_items).encode('utf-8'))
                else:
                    page = int(qs.get('page', ['1'])[0])
                    page_size = int(qs.get('page_size', ['50'])[0])
                    page = max(1, page)
                    page_size = max(1, min(500, page_size))
                    start = (page - 1) * page_size
                    end = start + page_size
                    page_items = all_items[start:end]
                    payload = {
                        'items': page_items,
                        # Convenience alias (some UIs expect this)
                        'policies': page_items,
                        'page': page,
                        'page_size': page_size,
                        'total': len(all_items)
                    }
                    self._set_json_headers()
                    self.wfile.write(json.dumps(payload).encode('utf-8'))
            return
        
        # Policy Document Download Endpoint - Comprehensive PDF Generation
        if path.startswith('/api/policies/') and path.endswith('/document'):
            policy_id = path.split('/')[3]
            
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return
            
            user = get_session_user(session) or {}
            role = (user.get('role') or '').lower()
            session_customer_id = user.get('customer_id') or session.get('customer_id')
            
            policy = POLICIES.get(policy_id)
            if not policy:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'Policy not found'}).encode('utf-8'))
                return
            
            # Check authorization
            if role == 'customer' and session_customer_id != policy.get('customer_id'):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Access denied'}).encode('utf-8'))
                return
            
            # Get all related data
            customer_id = policy.get('customer_id')
            customer = CUSTOMERS.get(customer_id) or {}
            
            # Get underwriting application data
            uw_id = policy.get('underwriting_id')
            underwriting = UNDERWRITING_APPLICATIONS.get(uw_id) or {}
            questionnaire = underwriting.get('questionnaire_responses', {})
            payment_setup = underwriting.get('payment_setup', {})
            health_wallet_info = underwriting.get('health_wallet', {}) or policy.get('health_wallet', {})
            
            # Get billing history
            customer_bills = [b for b in BILLING.values() if b.get('customer_id') == customer_id or b.get('policy_id') == policy_id]
            
            # Get claims history
            customer_claims = [c for c in CLAIMS.values() if c.get('customer_id') == customer_id or c.get('policy_id') == policy_id]
            
            # Generate comprehensive PDF
            try:
                from reportlab.lib import colors
                from reportlab.lib.pagesizes import letter, A4
                from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
                from reportlab.lib.units import inch
                from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, HRFlowable
                from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
                from io import BytesIO
                
                buffer = BytesIO()
                doc = SimpleDocTemplate(buffer, pagesize=letter, 
                                       rightMargin=0.75*inch, leftMargin=0.75*inch,
                                       topMargin=0.75*inch, bottomMargin=0.75*inch)
                
                styles = getSampleStyleSheet()
                
                # Custom styles
                title_style = ParagraphStyle('Title', parent=styles['Heading1'], 
                                            fontSize=24, alignment=TA_CENTER, 
                                            textColor=colors.HexColor('#0d47a1'),
                                            spaceAfter=20)
                subtitle_style = ParagraphStyle('Subtitle', parent=styles['Normal'], 
                                               fontSize=12, alignment=TA_CENTER, 
                                               textColor=colors.HexColor('#546e7a'),
                                               spaceAfter=30)
                section_style = ParagraphStyle('Section', parent=styles['Heading2'], 
                                              fontSize=14, textColor=colors.HexColor('#1565c0'),
                                              spaceBefore=20, spaceAfter=10,
                                              borderColor=colors.HexColor('#1565c0'),
                                              borderWidth=1, borderPadding=5)
                normal_style = ParagraphStyle('CustomNormal', parent=styles['Normal'], 
                                             fontSize=10, leading=14)
                label_style = ParagraphStyle('Label', parent=styles['Normal'], 
                                            fontSize=9, textColor=colors.HexColor('#546e7a'))
                value_style = ParagraphStyle('Value', parent=styles['Normal'], 
                                            fontSize=10, textColor=colors.HexColor('#1a237e'))
                
                story = []
                
                # Header
                story.append(Paragraph("🛡️ PHINS INSURANCE COMPANY", title_style))
                story.append(Paragraph("COMPREHENSIVE POLICY DOCUMENT", subtitle_style))
                story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#1565c0')))
                story.append(Spacer(1, 20))
                
                # Document Info Table
                doc_info = [
                    ['Document Generated:', datetime.now().strftime('%B %d, %Y at %H:%M:%S')],
                    ['Policy Number:', policy.get('id', 'N/A')],
                    ['Policy Status:', (policy.get('status', 'Unknown')).replace('_', ' ').title()],
                    ['Underwriting Reference:', uw_id or 'N/A'],
                ]
                doc_table = Table(doc_info, colWidths=[2*inch, 4.5*inch])
                doc_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#546e7a')),
                    ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#1a237e')),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ]))
                story.append(doc_table)
                story.append(Spacer(1, 20))
                
                # Section 1: Policyholder Information
                story.append(Paragraph("📋 SECTION 1: POLICYHOLDER INFORMATION", section_style))
                story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#e3f2fd')))
                
                # Calculate age from DOB
                age = underwriting.get('age', 0)
                dob = customer.get('dob', '')
                if dob and not age:
                    try:
                        birth_date = datetime.fromisoformat(dob.replace('Z', '+00:00')) if 'T' in dob else datetime.strptime(dob, '%Y-%m-%d')
                        age = (datetime.now() - birth_date).days // 365
                    except:
                        age = 'N/A'
                
                customer_data = [
                    ['Full Name:', customer.get('name', underwriting.get('customer_name', 'N/A'))],
                    ['Customer ID:', customer_id or 'N/A'],
                    ['Email Address:', customer.get('email', underwriting.get('customer_email', 'N/A'))],
                    ['Phone Number:', customer.get('phone', 'N/A')],
                    ['Date of Birth:', dob if dob else 'N/A'],
                    ['Age at Application:', f"{age} years" if age else 'N/A'],
                    ['Gender:', customer.get('gender', 'N/A').title() if customer.get('gender') else 'N/A'],
                    ['Occupation:', customer.get('occupation', questionnaire.get('occupation', 'N/A'))],
                    ['Address:', customer.get('address', 'N/A')],
                    ['City/State/ZIP:', f"{customer.get('city', '')} {customer.get('state', '')} {customer.get('zip', '')}".strip() or 'N/A'],
                    ['Account Created:', customer.get('created_date', 'N/A')[:10] if customer.get('created_date') else 'N/A'],
                ]
                cust_table = Table(customer_data, colWidths=[2*inch, 4.5*inch])
                cust_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#546e7a')),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fafcff')),
                ]))
                story.append(cust_table)
                story.append(Spacer(1, 15))
                
                # Section 2: Coverage Details
                story.append(Paragraph("🛡️ SECTION 2: COVERAGE DETAILS", section_style))
                story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#e3f2fd')))
                
                policy_type_labels = {
                    'life': 'Life Insurance',
                    'health': 'Health Insurance',
                    'disability': 'PHINS Disability + Investment',
                    'auto': 'Auto Insurance',
                    'property': 'Property Insurance'
                }
                policy_type = policy.get('type', 'life')
                
                coverage_data = [
                    ['Policy Type:', policy_type_labels.get(policy_type, policy_type.title())],
                    ['Coverage Amount:', f"${policy.get('coverage_amount', 0):,.2f}"],
                    ['Annual Premium:', f"${policy.get('annual_premium', 0):,.2f}"],
                    ['Monthly Premium:', f"${policy.get('monthly_premium', 0):,.2f}"],
                    ['Risk Classification:', (policy.get('risk_score', 'Standard')).replace('_', ' ').title()],
                    ['Effective Date:', policy.get('start_date', 'N/A')[:10] if policy.get('start_date') else 'N/A'],
                    ['Expiration Date:', policy.get('end_date', 'N/A')[:10] if policy.get('end_date') else 'N/A'],
                    ['Medical Exam Required:', 'Yes' if underwriting.get('medical_exam_required') else 'No'],
                ]
                
                # Add investment allocation for disability policies
                if policy_type == 'disability':
                    coverage_data.append(['Investment Allocation:', '75% Risk / 25% Savings'])
                    coverage_data.append(['ADL Coverage Trigger:', '3+ Activities of Daily Living'])
                
                cov_table = Table(coverage_data, colWidths=[2*inch, 4.5*inch])
                cov_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#546e7a')),
                    ('TEXTCOLOR', (1, 1), (1, 1), colors.HexColor('#1565c0')),  # Coverage amount in blue
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fafcff')),
                ]))
                story.append(cov_table)
                story.append(Spacer(1, 15))
                
                # Section 3: Health Assessment (from application questionnaire)
                story.append(Paragraph("🏥 SECTION 3: HEALTH & LIFESTYLE ASSESSMENT", section_style))
                story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#e3f2fd')))
                
                tobacco_labels = {'no': 'Non-smoker', 'yes': 'Current User', 'former': 'Former User (Quit 1+ years)'}
                hazard_labels = {'no': 'None', 'occasional': 'Occasional (1-2x/year)', 'regular': 'Regular (Monthly+)'}
                
                health_data = [
                    ['Tobacco Use:', tobacco_labels.get(questionnaire.get('smoke', 'no'), 'Not Specified')],
                    ['Pre-existing Conditions:', 'Yes' if questionnaire.get('medical_conditions') == 'yes' else 'None Reported'],
                ]
                
                if questionnaire.get('medical_conditions') == 'yes' and questionnaire.get('conditions_list'):
                    health_data.append(['Conditions Listed:', questionnaire.get('conditions_list', 'N/A')])
                
                health_data.extend([
                    ['Prior Surgeries (5 years):', 'Yes' if questionnaire.get('surgery') == 'yes' else 'None Reported'],
                ])
                
                if questionnaire.get('surgery') == 'yes' and questionnaire.get('surgery_list'):
                    health_data.append(['Surgery Details:', questionnaire.get('surgery_list', 'N/A')])
                
                health_data.extend([
                    ['Hazardous Activities:', hazard_labels.get(questionnaire.get('hazardous_activities', 'no'), 'Not Specified')],
                    ['Family Medical History:', questionnaire.get('family_history', 'None reported').replace(',', ', ').title() if questionnaire.get('family_history') else 'None Reported'],
                    ['Height:', f"{questionnaire.get('height', 'N/A')} cm" if questionnaire.get('height') else 'N/A'],
                    ['Weight:', f"{questionnaire.get('weight', 'N/A')} kg" if questionnaire.get('weight') else 'N/A'],
                ])
                
                # Calculate BMI if height and weight available
                try:
                    height = float(questionnaire.get('height', 0))
                    weight = float(questionnaire.get('weight', 0))
                    if height > 0 and weight > 0:
                        bmi = weight / ((height / 100) ** 2)
                        bmi_category = 'Underweight' if bmi < 18.5 else 'Normal' if bmi < 25 else 'Overweight' if bmi < 30 else 'Obese'
                        health_data.append(['BMI:', f"{bmi:.1f} ({bmi_category})"])
                except:
                    pass
                
                if questionnaire.get('medications'):
                    health_data.append(['Current Medications:', questionnaire.get('medications', 'None')])
                
                health_table = Table(health_data, colWidths=[2*inch, 4.5*inch])
                health_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#546e7a')),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fafcff')),
                ]))
                story.append(health_table)
                story.append(Spacer(1, 15))
                
                # Section 4: Billing & Payment Configuration
                story.append(Paragraph("💳 SECTION 4: BILLING & PAYMENT CONFIGURATION", section_style))
                story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#e3f2fd')))
                
                billing_config = policy.get('billing', {})
                freq_labels = {'monthly': 'Monthly', 'quarterly': 'Quarterly (3% Discount)', 'annual': 'Annual (10% Discount)'}
                
                billing_data = [
                    ['Billing Frequency:', freq_labels.get(billing_config.get('frequency', payment_setup.get('billing_frequency', 'monthly')), 'Monthly')],
                    ['Auto-Pay Enabled:', 'Yes ✓' if billing_config.get('auto_pay', payment_setup.get('auto_pay')) else 'No'],
                    ['Payment Method:', f"{(payment_setup.get('card_type', 'Card')).title()} ending in {payment_setup.get('card_last4', '****')}" if payment_setup.get('card_last4') else 'Not Configured'],
                    ['Cardholder Name:', payment_setup.get('cardholder_name', 'N/A')],
                    ['Card Expiry:', f"{payment_setup.get('expiry_month', '--')}/{payment_setup.get('expiry_year', '----')}" if payment_setup.get('expiry_month') else 'N/A'],
                    ['Next Billing Date:', billing_config.get('next_billing_date', 'N/A')[:10] if billing_config.get('next_billing_date') else 'N/A'],
                ]
                
                billing_table = Table(billing_data, colWidths=[2*inch, 4.5*inch])
                billing_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#546e7a')),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fafcff')),
                ]))
                story.append(billing_table)
                story.append(Spacer(1, 15))
                
                # Section 5: Health Wallet
                story.append(Paragraph("🏥 SECTION 5: PHINS HEALTH WALLET", section_style))
                story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#e3f2fd')))
                
                wallet_enabled = health_wallet_info.get('enabled', False)
                wallet_data = HEALTH_WALLETS.get(customer_id, {})
                
                hw_data = [
                    ['Health Wallet Status:', 'Enabled ✓' if wallet_enabled else 'Not Enabled'],
                    ['Monthly Auto-Deposit:', f"${health_wallet_info.get('monthly_deposit', 0):,.2f}" if wallet_enabled else 'N/A'],
                    ['Current Balance:', f"${wallet_data.get('balance', 0):,.2f}" if wallet_data else 'N/A'],
                    ['Wallet Created:', wallet_data.get('created_at', 'N/A')[:10] if wallet_data.get('created_at') else 'N/A'],
                ]
                
                hw_table = Table(hw_data, colWidths=[2*inch, 4.5*inch])
                hw_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#546e7a')),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fafcff')),
                ]))
                story.append(hw_table)
                story.append(Spacer(1, 15))
                
                # Section 6: Billing History
                if customer_bills:
                    story.append(Paragraph("📊 SECTION 6: BILLING HISTORY", section_style))
                    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#e3f2fd')))
                    
                    bill_header = [['Bill ID', 'Amount', 'Due Date', 'Status', 'Paid Date']]
                    bill_rows = []
                    for bill in customer_bills[:10]:  # Last 10 bills
                        bill_rows.append([
                            bill.get('id', 'N/A')[:15],
                            f"${bill.get('amount_due', 0):,.2f}",
                            bill.get('due_date', 'N/A')[:10] if bill.get('due_date') else 'N/A',
                            bill.get('status', 'N/A').title(),
                            bill.get('paid_date', '-')[:10] if bill.get('paid_date') else '-'
                        ])
                    
                    if bill_rows:
                        bill_table = Table(bill_header + bill_rows, colWidths=[1.5*inch, 1*inch, 1.2*inch, 1*inch, 1.2*inch])
                        bill_table.setStyle(TableStyle([
                            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                            ('FONTSIZE', (0, 0), (-1, -1), 8),
                            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1565c0')),
                            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
                            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                            ('TOPPADDING', (0, 0), (-1, -1), 6),
                        ]))
                        story.append(bill_table)
                    story.append(Spacer(1, 15))
                
                # Section 7: Claims History
                if customer_claims:
                    story.append(Paragraph("📝 SECTION 7: CLAIMS HISTORY", section_style))
                    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#e3f2fd')))
                    
                    claim_header = [['Claim ID', 'Type', 'Amount', 'Status', 'Filed Date']]
                    claim_rows = []
                    for claim in customer_claims[:10]:
                        claim_rows.append([
                            claim.get('id', 'N/A')[:15],
                            claim.get('type', 'N/A').title(),
                            f"${claim.get('claimed_amount', 0):,.2f}",
                            claim.get('status', 'N/A').title(),
                            claim.get('filed_date', 'N/A')[:10] if claim.get('filed_date') else 'N/A'
                        ])
                    
                    if claim_rows:
                        claim_table = Table(claim_header + claim_rows, colWidths=[1.5*inch, 1*inch, 1.2*inch, 1*inch, 1.2*inch])
                        claim_table.setStyle(TableStyle([
                            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                            ('FONTSIZE', (0, 0), (-1, -1), 8),
                            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1565c0')),
                            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                            ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
                            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e0e0e0')),
                            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                            ('TOPPADDING', (0, 0), (-1, -1), 6),
                        ]))
                        story.append(claim_table)
                    story.append(Spacer(1, 15))
                
                # Section 8: Statistics & Analytics
                story.append(Paragraph("📈 SECTION 8: ACCOUNT STATISTICS", section_style))
                story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#e3f2fd')))
                
                # Calculate statistics
                total_premiums_paid = sum(b.get('amount_paid', 0) for b in customer_bills if b.get('status') == 'paid')
                total_claims_filed = len(customer_claims)
                total_claims_approved = len([c for c in customer_claims if c.get('status', '').lower() in ('approved', 'paid')])
                total_claims_amount = sum(c.get('approved_amount', 0) for c in customer_claims if c.get('status', '').lower() in ('approved', 'paid'))
                
                # Get all customer policies
                customer_policies = [p for p in POLICIES.values() if p.get('customer_id') == customer_id]
                total_coverage = sum(p.get('coverage_amount', 0) for p in customer_policies)
                
                stats_data = [
                    ['Total Policies:', str(len(customer_policies))],
                    ['Total Coverage Amount:', f"${total_coverage:,.2f}"],
                    ['Total Premiums Paid:', f"${total_premiums_paid:,.2f}"],
                    ['Total Claims Filed:', str(total_claims_filed)],
                    ['Claims Approved:', str(total_claims_approved)],
                    ['Total Claims Paid:', f"${total_claims_amount:,.2f}"],
                    ['Customer Since:', customer.get('created_date', 'N/A')[:10] if customer.get('created_date') else 'N/A'],
                    ['Application Submitted:', underwriting.get('submitted_date', 'N/A')[:10] if underwriting.get('submitted_date') else 'N/A'],
                ]
                
                stats_table = Table(stats_data, colWidths=[2*inch, 4.5*inch])
                stats_table.setStyle(TableStyle([
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#546e7a')),
                    ('TEXTCOLOR', (1, 1), (1, 1), colors.HexColor('#1565c0')),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fafcff')),
                ]))
                story.append(stats_table)
                story.append(Spacer(1, 20))
                
                # Terms & Conditions Footer
                story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#1565c0')))
                story.append(Spacer(1, 10))
                
                terms_style = ParagraphStyle('Terms', parent=styles['Normal'], fontSize=8, 
                                            textColor=colors.HexColor('#546e7a'), leading=10)
                
                terms_text = """
                <b>TERMS AND CONDITIONS</b><br/><br/>
                This policy is subject to the terms, conditions, and exclusions set forth in the PHINS Insurance 
                Company Master Policy Agreement. Coverage is contingent upon timely payment of premiums and 
                compliance with all policy requirements. For claims or questions, please contact:<br/><br/>
                • Phone: 1-800-PHINS-HELP (1-800-744-6743)<br/>
                • Email: support@phins.ai<br/>
                • Web: https://phins.ai<br/><br/>
                © """ + str(datetime.now().year) + """ PHINS Insurance Company. All rights reserved. This document is for 
                informational purposes and serves as a summary of your coverage. Please refer to your complete 
                policy documents for full terms and conditions.
                """
                story.append(Paragraph(terms_text, terms_style))
                
                # Build PDF
                doc.build(story)
                
                # Return PDF
                pdf_content = buffer.getvalue()
                buffer.close()
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/pdf')
                self.send_header('Content-Disposition', f'attachment; filename="PHINS_Policy_{policy_id}.pdf"')
                self.send_header('Content-Length', str(len(pdf_content)))
                self.end_headers()
                self.wfile.write(pdf_content)
                
            except ImportError as ie:
                # Fallback to text if reportlab not available
                print(f"PDF generation error (missing library): {ie}")
                self._generate_text_policy_document(policy, customer, underwriting, customer_bills, customer_claims)
            except Exception as e:
                print(f"PDF generation error: {e}")
                import traceback
                traceback.print_exc()
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': f'Failed to generate PDF: {str(e)}'}).encode('utf-8'))
            return
        
        # Claims Management Endpoints
        if path == '/api/claims':
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return

            user = get_session_user(session) or {}
            role = (user.get('role') or '').lower()
            session_customer_id = user.get('customer_id') or session.get('customer_id')

            claim_id = qs.get('id', [None])[0]
            status = qs.get('status', [None])[0]
            
            if claim_id:
                claim = CLAIMS.get(claim_id)
                if claim and (role != 'customer' or (session_customer_id and (
                    claim.get('customer_id') == session_customer_id or
                    (claim.get('policy_id') and POLICIES.get(claim.get('policy_id'), {}).get('customer_id') == session_customer_id)
                ))):
                    self._set_json_headers()
                    self.wfile.write(json.dumps(claim).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Claim not found'}).encode('utf-8'))
            else:
                claims_list = list(CLAIMS.values())
                if status:
                    claims_list = [c for c in claims_list if c.get('status') == status]
                if role == 'customer' and session_customer_id:
                    def _belongs(c: Dict[str, Any]) -> bool:
                        if c.get('customer_id') == session_customer_id:
                            return True
                        pid = c.get('policy_id')
                        return bool(pid and POLICIES.get(pid, {}).get('customer_id') == session_customer_id)
                    claims_list = [c for c in claims_list if _belongs(c)]

                wants_paging = ('page' in qs) or ('page_size' in qs)
                if not wants_paging:
                    # Always return object with claims array for consistency
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'claims': claims_list, 'total': len(claims_list)}).encode('utf-8'))
                else:
                    page = int(qs.get('page', ['1'])[0])
                    page_size = int(qs.get('page_size', ['50'])[0])
                    page = max(1, page)
                    page_size = max(1, min(500, page_size))
                    start = (page - 1) * page_size
                    end = start + page_size
                    page_items = claims_list[start:end]
                    payload = {
                        'items': page_items,
                        # Convenience alias (some UIs expect this)
                        'claims': page_items,
                        'page': page,
                        'page_size': page_size,
                        'total': len(claims_list)
                    }
                    self._set_json_headers()
                    self.wfile.write(json.dumps(payload).encode('utf-8'))
            return
        
        # Underwriting Applications Endpoints
        if path == '/api/underwriting':
            app_id = qs.get('id', [None])[0]
            if app_id:
                app = UNDERWRITING_APPLICATIONS.get(app_id)
                if app:
                    self._set_json_headers()
                    self.wfile.write(json.dumps(app).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Application not found'}).encode('utf-8'))
            else:
                self._set_json_headers()
                self.wfile.write(json.dumps(list(UNDERWRITING_APPLICATIONS.values())).encode('utf-8'))
            return
        
        # Customers Endpoint
        if path == '/api/customers':
            customer_id = qs.get('id', [None])[0]
            if customer_id:
                customer = CUSTOMERS.get(customer_id)
                if customer:
                    self._set_json_headers()
                    self.wfile.write(json.dumps(customer).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Customer not found'}).encode('utf-8'))
            else:
                self._set_json_headers()
                self.wfile.write(json.dumps(list(CUSTOMERS.values())).encode('utf-8'))
            return

        # Customer status endpoint (post-application visibility)
        if path == '/api/customer/status':
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return

            user = get_session_user(session) or {}
            role = (user.get('role') or '').lower()
            session_customer_id = user.get('customer_id') or session.get('customer_id')

            requested_customer_id = qs.get('customer_id', [None])[0]
            customer_id = requested_customer_id
            if role == 'customer':
                customer_id = session_customer_id

            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id is required'}).encode('utf-8'))
                return

            # Non-customer roles can request arbitrary customer_id; customers cannot.
            if role == 'customer' and requested_customer_id and requested_customer_id != customer_id:
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Forbidden'}).encode('utf-8'))
                return

            customer = CUSTOMERS.get(customer_id)
            if not customer:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'Customer not found'}).encode('utf-8'))
                return

            policies = [p for p in POLICIES.values() if p.get('customer_id') == customer_id]
            uw_apps = [u for u in UNDERWRITING_APPLICATIONS.values() if u.get('customer_id') == customer_id]
            
            # Get billing for this customer's policies
            policy_ids = {p.get('id') for p in policies}
            bills = [b for b in BILLING.values() 
                     if b.get('customer_id') == customer_id or b.get('policy_id') in policy_ids]

            # Determine overall application status (simple heuristic)
            overall = 'no_application'
            if uw_apps:
                most_recent = sorted(uw_apps, key=lambda x: x.get('submitted_date', ''), reverse=True)[0]
                overall = most_recent.get('status', 'pending')
                if overall == 'approved':
                    # Check if policy is active
                    linked = next((p for p in policies if p.get('underwriting_id') == most_recent.get('id')), None)
                    if linked and linked.get('status') == 'active':
                        overall = 'active_policy'
            
            # Calculate billing summary
            outstanding_bills = [b for b in bills if b.get('status') == 'outstanding']
            total_outstanding = sum(b.get('amount', 0) or b.get('amount_due', 0) for b in outstanding_bills)

            payload = {
                'customer': {
                    'id': customer_id,
                    'name': customer.get('name'),
                    'email': customer.get('email')
                },
                'overall_status': overall,
                'policies': policies,
                'underwriting_applications': uw_apps,
                'billing': bills,
                'billing_summary': {
                    'total_outstanding': round(total_outstanding, 2),
                    'outstanding_count': len(outstanding_bills),
                    'next_due': min((b.get('due_date') for b in outstanding_bills), default=None)
                }
            }

            self._set_json_headers()
            self.wfile.write(json.dumps(payload).encode('utf-8'))
            return

        # Customer billing list - GET /api/billing?customer_id=XXX
        if path == '/api/billing':
            customer_id = qs.get('customer_id', [None])[0]
            
            # Filter bills by customer if provided
            if customer_id:
                bills_list = [b for b in BILLING.values() if b.get('customer_id') == customer_id]
            else:
                bills_list = list(BILLING.values())
            
            self._set_json_headers()
            self.wfile.write(json.dumps({'bills': bills_list}).encode('utf-8'))
            return
        
        # Customer billing "next due" (portal convenience)
        if path == '/api/billing/next-due':
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode('utf-8'))
                return

            user = get_session_user(session) or {}
            role = (user.get('role') or '').lower()
            session_customer_id = user.get('customer_id') or session.get('customer_id')
            if role == 'customer' and not session_customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id unavailable'}).encode('utf-8'))
                return

            # Determine which policies belong to this customer
            if role == 'customer':
                policy_ids = {p.get('id') for p in POLICIES.values() if p.get('customer_id') == session_customer_id}
                bills = [b for b in BILLING.values()
                         if b.get('policy_id') in policy_ids and b.get('status') not in ('paid',)]
            else:
                bills = [b for b in BILLING.values() if b.get('status') not in ('paid',)]

            def _due_ts(b: Dict[str, Any]) -> float:
                try:
                    return datetime.fromisoformat(b.get('due_date', '')).timestamp()
                except Exception:
                    return float('inf')

            next_bill = sorted(bills, key=_due_ts)[0] if bills else None
            self._set_json_headers()
            self.wfile.write(json.dumps({'next_due': next_bill}).encode('utf-8'))
            return
        
        if path.startswith('/api/statement'):
            customer_id = qs.get('customer_id', ['CUST001'])[0]
            data = try_get_statement_from_engine(customer_id) or get_mock_statement(customer_id)
            self._set_json_headers()
            self.wfile.write(json.dumps(data).encode('utf-8'))
            return
        
        # ========== CUSTOMER DATA & PIPELINE VALIDATION API ==========
        
        # List all registered customers with their complete pipeline status
        if path == '/api/admin/customers':
            # Build comprehensive customer list with all related data
            customer_list = []
            
            for cust_id, customer in CUSTOMERS.items():
                # Find associated policies
                customer_policies = [p for p in POLICIES.values() if p.get('customer_id') == cust_id]
                
                # Find associated underwriting applications
                customer_apps = [a for a in UNDERWRITING_APPLICATIONS.values() if a.get('customer_id') == cust_id]
                
                # Find associated bills
                customer_bills = [b for b in BILLING.values() if b.get('customer_id') == cust_id]
                
                # Get health wallet
                wallet = HEALTH_WALLETS.get(cust_id, {})
                
                # Determine pipeline stage
                pipeline_stage = 'registered'
                if customer_apps:
                    pending_apps = [a for a in customer_apps if a.get('status') == 'pending']
                    approved_apps = [a for a in customer_apps if a.get('status') == 'approved']
                    if pending_apps:
                        pipeline_stage = 'underwriting'
                    elif approved_apps:
                        pipeline_stage = 'approved'
                
                if customer_policies:
                    active_policies = [p for p in customer_policies if p.get('status') == 'active']
                    if active_policies:
                        pipeline_stage = 'active_policy'
                
                if customer_bills:
                    outstanding_bills = [b for b in customer_bills if b.get('status') == 'outstanding']
                    paid_bills = [b for b in customer_bills if b.get('status') == 'paid']
                    if outstanding_bills:
                        pipeline_stage = 'billing_pending'
                    elif paid_bills:
                        pipeline_stage = 'fully_active'
                
                customer_list.append({
                    'id': cust_id,
                    'name': customer.get('name', 'N/A'),
                    'email': customer.get('email', 'N/A'),
                    'phone': customer.get('phone', 'N/A'),
                    'created_date': customer.get('created_date', 'N/A'),
                    'pipeline_stage': pipeline_stage,
                    'policies_count': len(customer_policies),
                    'active_policies': len([p for p in customer_policies if p.get('status') == 'active']),
                    'pending_applications': len([a for a in customer_apps if a.get('status') == 'pending']),
                    'outstanding_bills': len([b for b in customer_bills if b.get('status') == 'outstanding']),
                    'total_premium_due': sum(b.get('amount_due', 0) for b in customer_bills if b.get('status') == 'outstanding'),
                    'wallet_balance': wallet.get('balance', 0),
                    'policies': customer_policies,
                    'applications': customer_apps,
                    'bills': customer_bills
                })
            
            # Sort by created date (newest first)
            customer_list.sort(key=lambda x: x.get('created_date', ''), reverse=True)
            
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'success': True,
                'total_customers': len(customer_list),
                'customers': customer_list,
                'summary': {
                    'total': len(customer_list),
                    'in_underwriting': len([c for c in customer_list if c['pipeline_stage'] == 'underwriting']),
                    'approved': len([c for c in customer_list if c['pipeline_stage'] == 'approved']),
                    'active_policies': len([c for c in customer_list if c['pipeline_stage'] in ('active_policy', 'billing_pending', 'fully_active')]),
                    'pending_billing': len([c for c in customer_list if c['pipeline_stage'] == 'billing_pending'])
                }
            }).encode('utf-8'))
            return
        
        # Validate entire pipeline for a customer
        if path.startswith('/api/admin/validate-customer/'):
            customer_id = path.split('/')[-1]
            
            validation_results = {
                'customer_id': customer_id,
                'valid': True,
                'checks': [],
                'errors': [],
                'warnings': []
            }
            
            # Check 1: Customer exists
            customer = CUSTOMERS.get(customer_id)
            if customer:
                validation_results['checks'].append({'check': 'customer_exists', 'status': 'PASS', 'details': customer.get('name')})
            else:
                validation_results['valid'] = False
                validation_results['errors'].append('Customer not found')
                validation_results['checks'].append({'check': 'customer_exists', 'status': 'FAIL'})
                self._set_json_headers()
                self.wfile.write(json.dumps(validation_results).encode('utf-8'))
                return
            
            # Check 2: Valid email
            email = customer.get('email', '')
            if email and '@' in email:
                validation_results['checks'].append({'check': 'valid_email', 'status': 'PASS', 'details': email})
            else:
                validation_results['warnings'].append('Missing or invalid email')
                validation_results['checks'].append({'check': 'valid_email', 'status': 'WARN', 'details': email or 'Missing'})
            
            # Check 3: Underwriting applications
            apps = [a for a in UNDERWRITING_APPLICATIONS.values() if a.get('customer_id') == customer_id]
            if apps:
                for app in apps:
                    status = app.get('status', 'unknown')
                    app_id = app.get('id')
                    validation_results['checks'].append({
                        'check': f'underwriting_{app_id}',
                        'status': 'PASS' if status in ('approved', 'pending') else 'WARN',
                        'details': f'Status: {status}'
                    })
            else:
                validation_results['warnings'].append('No underwriting applications found')
            
            # Check 4: Policies
            policies = [p for p in POLICIES.values() if p.get('customer_id') == customer_id]
            if policies:
                for policy in policies:
                    status = policy.get('status', 'unknown')
                    policy_id = policy.get('id')
                    has_uw = policy.get('underwriting_id') in [a.get('id') for a in apps]
                    
                    if status == 'active':
                        validation_results['checks'].append({
                            'check': f'policy_{policy_id}',
                            'status': 'PASS',
                            'details': f'Active, linked to UW: {has_uw}'
                        })
                    elif status == 'pending_underwriting':
                        validation_results['checks'].append({
                            'check': f'policy_{policy_id}',
                            'status': 'PENDING',
                            'details': 'Awaiting underwriting approval'
                        })
                    else:
                        validation_results['checks'].append({
                            'check': f'policy_{policy_id}',
                            'status': 'WARN',
                            'details': f'Status: {status}'
                        })
            
            # Check 5: Billing
            bills = [b for b in BILLING.values() if b.get('customer_id') == customer_id]
            active_policies = [p for p in policies if p.get('status') == 'active']
            
            if active_policies and not bills:
                validation_results['errors'].append('Active policy without billing record')
                validation_results['valid'] = False
                validation_results['checks'].append({
                    'check': 'billing_exists',
                    'status': 'FAIL',
                    'details': 'Active policy found but no billing record'
                })
            elif bills:
                total_due = sum(b.get('amount_due', 0) for b in bills if b.get('status') == 'outstanding')
                validation_results['checks'].append({
                    'check': 'billing_status',
                    'status': 'PASS',
                    'details': f'{len(bills)} bills, ${total_due:.2f} outstanding'
                })
            
            # Check 6: Health wallet (if enabled)
            wallet = HEALTH_WALLETS.get(customer_id)
            if wallet:
                validation_results['checks'].append({
                    'check': 'health_wallet',
                    'status': 'PASS',
                    'details': f'Balance: ${wallet.get("balance", 0):.2f}'
                })
            
            self._set_json_headers()
            self.wfile.write(json.dumps(validation_results).encode('utf-8'))
            return
        
        # Pipeline summary statistics
        if path == '/api/admin/pipeline-stats':
            stats = {
                'total_customers': len(CUSTOMERS),
                'total_applications': len(UNDERWRITING_APPLICATIONS),
                'total_policies': len(POLICIES),
                'total_bills': len(BILLING),
                'total_wallets': len(HEALTH_WALLETS),
                'applications_by_status': {},
                'policies_by_status': {},
                'bills_by_status': {},
                'pipeline_flow': {
                    'pending_underwriting': 0,
                    'approved_pending_activation': 0,
                    'active_policies': 0,
                    'billing_outstanding': 0,
                    'billing_paid': 0
                }
            }
            
            # Count applications by status
            for app in UNDERWRITING_APPLICATIONS.values():
                status = app.get('status', 'unknown')
                stats['applications_by_status'][status] = stats['applications_by_status'].get(status, 0) + 1
            
            # Count policies by status
            for policy in POLICIES.values():
                status = policy.get('status', 'unknown')
                stats['policies_by_status'][status] = stats['policies_by_status'].get(status, 0) + 1
                
                if status == 'pending_underwriting':
                    stats['pipeline_flow']['pending_underwriting'] += 1
                elif status == 'active':
                    stats['pipeline_flow']['active_policies'] += 1
            
            # Count bills by status
            for bill in BILLING.values():
                status = bill.get('status', 'unknown')
                stats['bills_by_status'][status] = stats['bills_by_status'].get(status, 0) + 1
                
                if status == 'outstanding':
                    stats['pipeline_flow']['billing_outstanding'] += 1
                elif status == 'paid':
                    stats['pipeline_flow']['billing_paid'] += 1
            
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'success': True,
                'stats': stats,
                'timestamp': datetime.now().isoformat()
            }).encode('utf-8'))
            return
        
        # ========== END CUSTOMER DATA & PIPELINE VALIDATION API ==========
        
        # Health Wallet GET endpoints
        if path == '/api/health-wallet/purchases':
            # GET purchases history
            customer_id = qs.get('customer_id', ['CUST001'])[0]
            
            purchases = [p for p in MEDICAL_PURCHASES.values() if p.get('customer_id') == customer_id]
            purchases.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'success': True,
                'purchases': purchases[:50]  # Last 50
            }).encode('utf-8'))
            return
        
        # NFT Ledger GET endpoint - Customer Transaction Ledger
        if path == '/api/nft-ledger':
            customer_id = qs.get('customer_id', ['CUST001'])[0]
            
            # Get all NFT tokens for this customer
            customer_nfts = [
                nft for nft in NFT_LEDGER.values() 
                if nft.get('owner_id') == customer_id
            ]
            customer_nfts.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            
            # Calculate summary stats
            total_deposits = sum(
                nft.get('amount', 0) for nft in customer_nfts 
                if nft.get('transaction_type') == 'wallet_deposit'
            )
            total_purchases = sum(
                nft.get('amount', 0) for nft in customer_nfts 
                if nft.get('transaction_type') == 'medical_purchase'
            )
            
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'success': True,
                'customer_id': customer_id,
                'ledger': customer_nfts[:100],  # Last 100 entries
                'summary': {
                    'total_tokens': len(customer_nfts),
                    'total_deposits': total_deposits,
                    'total_purchases': total_purchases,
                    'net_flow': total_deposits - total_purchases
                },
                'chain_info': {
                    'chain_type': 'PHINS-CHAIN',
                    'smart_contract': f"PHINS-SC-{datetime.now().strftime('%Y%m')}-WALLET",
                    'network': 'mainnet'
                }
            }).encode('utf-8'))
            return
        
        # Verify specific NFT token
        if path == '/api/nft-ledger/verify':
            token_id = qs.get('token_id', [None])[0]
            
            if not token_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Token ID required'}).encode('utf-8'))
                return
            
            nft = NFT_LEDGER.get(token_id)
            if not nft:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({
                    'valid': False,
                    'error': 'Token not found'
                }).encode('utf-8'))
                return
            
            # Verify the token
            import hashlib
            verification_data = json.dumps({
                'token_id': nft['token_id'],
                'customer_id': nft['owner_id'],
                'transaction_type': nft['transaction_type'],
                'amount': nft['amount']
            }, sort_keys=True)
            computed_hash = hashlib.sha3_256(verification_data.encode()).hexdigest()[:32]
            is_valid = computed_hash == nft.get('verification_hash')
            
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'valid': is_valid,
                'token': nft,
                'verification': {
                    'computed_hash': computed_hash,
                    'stored_hash': nft.get('verification_hash'),
                    'match': is_valid
                }
            }).encode('utf-8'))
            return
        
        if path.startswith('/api/health-wallet'):
            customer_id = qs.get('customer_id', ['CUST001'])[0]
            
            # Get or create wallet
            if customer_id not in HEALTH_WALLETS:
                HEALTH_WALLETS[customer_id] = {
                    'customer_id': customer_id,
                    'balance': 850.00,
                    'monthly_deposit': 100.00,
                    'transactions': [],
                    'created_at': datetime.now().isoformat()
                }
            
            wallet = HEALTH_WALLETS[customer_id]
            
            # Also get NFT count for this customer
            nft_count = len([nft for nft in NFT_LEDGER.values() if nft.get('owner_id') == customer_id])
            
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'success': True,
                'wallet': wallet,
                'nft_count': nft_count
            }).encode('utf-8'))
            return
        
        # Medical products catalog
        if path.startswith('/api/medical-products'):
            category = qs.get('category', [None])[0]
            
            products = {
                'consultation': [
                    {'id': 'cons-1', 'name': 'General Practitioner Visit', 'price': 75, 'category': 'consultation'},
                    {'id': 'cons-2', 'name': 'Specialist Consultation', 'price': 150, 'category': 'consultation'},
                    {'id': 'cons-3', 'name': 'Telehealth Quick Consult', 'price': 35, 'category': 'consultation'},
                ],
                'devices': [
                    {'id': 'dev-1', 'name': 'Standard Wheelchair', 'price': 450, 'category': 'devices'},
                    {'id': 'dev-2', 'name': 'Walking Cane', 'price': 35, 'category': 'devices'},
                    {'id': 'dev-3', 'name': 'Blood Pressure Monitor', 'price': 65, 'category': 'devices'},
                ],
                'supplies': [
                    {'id': 'sup-1', 'name': 'Adult Diapers (30 ct)', 'price': 28, 'category': 'supplies'},
                    {'id': 'sup-2', 'name': 'Adult Diapers (60 ct)', 'price': 52, 'category': 'supplies'},
                    {'id': 'sup-3', 'name': 'Disposable Bed Pads', 'price': 35, 'category': 'supplies'},
                ],
                'pharmacy': [
                    {'id': 'rx-1', 'name': 'Prescription Refill', 'price': 10, 'category': 'pharmacy'},
                    {'id': 'rx-2', 'name': 'First Aid Kit', 'price': 35, 'category': 'pharmacy'},
                ],
                'homecare': [
                    {'id': 'hc-1', 'name': 'Home Health Aide (4 hrs)', 'price': 120, 'category': 'homecare'},
                    {'id': 'hc-2', 'name': 'Meal Delivery (Weekly)', 'price': 85, 'category': 'homecare'},
                ]
            }
            
            if category and category in products:
                result = products[category]
            else:
                result = [item for cat in products.values() for item in cat]
            
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'success': True,
                'products': result
            }).encode('utf-8'))
            return

        if path.startswith('/api/allocations'):
            customer_id = qs.get('customer_id', ['CUST001'])[0]
            data = {"allocations": (try_get_statement_from_engine(customer_id) or get_mock_statement(customer_id))["allocations"]}
            self._set_json_headers()
            self.wfile.write(json.dumps(data).encode('utf-8'))
            return

        # Validation endpoints (connectors)
        if path.startswith('/api/validate'):
            # Parameters: ?type=ni|card|health&value=...
            t = qs.get('type', [''])[0]
            value = qs.get('value', [''])[0]
            extra = qs.get('extra', [None])[0]
            # Best-effort connector usage
            result = {'status': 'unavailable', 'details': {}}
            try:
                # Try to load connectors by file location to support running server.py directly
                import importlib.util
                conn_path = os.path.join(os.path.dirname(__file__), 'connectors.py')
                spec = importlib.util.spec_from_file_location('web_portal.connectors', conn_path)
                if spec and spec.loader:
                    connectors = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(connectors)
                else:
                    raise ImportError('Cannot load connectors')

                if t == 'ni':
                    res = connectors.NationalInsuranceConnector().validate(national_id=value, dob=extra)
                    result = {'status': res.status, 'details': res.details}
                elif t == 'card':
                    res = connectors.CreditCardIssuerConnector().validate(card_number=value, expiry=extra)
                    result = {'status': res.status, 'details': res.details}
                elif t == 'health':
                    res = connectors.HealthAuthorityConnector().validate(patient_id=value, name=extra)
                    result = {'status': res.status, 'details': res.details}
                else:
                    result = {'status': 'unknown_type', 'details': {'requested': t}}
            except Exception as e:
                result = {'status': 'error', 'details': {'error': str(e)}}

            self._set_json_headers()
            self.wfile.write(json.dumps(result).encode('utf-8'))
            return

        # Disclaimers endpoint
        if path.startswith('/api/disclaimers'):
            # Parameters: ?action=buy_contract|claim_insurance|invest_savings or ?type=BUY_CONTRACT|CLAIM_INSURANCE|INVEST_SAVINGS
            action = qs.get('action', [None])[0]
            disc_type = qs.get('type', [None])[0]
            
            result: Dict[str, Any] = {'disclaimers': []}
            try:
                # Try to import accounting_engine to get disclaimers
                sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                from accounting_engine import AccountingEngine, DisclaimerType
                engine = AccountingEngine()
                
                if action:
                    disclaimers = engine.get_all_disclaimers_for_action(action)
                elif disc_type:
                    # Try to match the type
                    try:
                        dt = DisclaimerType[disc_type.upper()]
                        disc = engine.get_disclaimer(dt)
                        disclaimers = [disc] if disc else []
                    except (KeyError, AttributeError):
                        disclaimers = []
                else:
                    disclaimers = engine.get_all_disclaimers()
                
                result['disclaimers'] = [
                    {
                        'type': d.disclaimer_type.name if hasattr(d.disclaimer_type, 'name') else str(d.disclaimer_type),
                        'title': d.title,
                        'content': d.content,
                        'version': d.version,
                        'effective_date': str(d.effective_date)
                    }
                    for d in disclaimers if d
                ]
            except Exception as e:
                result['error'] = str(e)
            
            self._set_json_headers()
            self.wfile.write(json.dumps(result).encode('utf-8'))
            return

        # ========== SAVINGS & INVESTMENT PORTFOLIO API ==========
        # Full-featured investment portfolio management with real-time market data
        
        # Get portfolio summary for a customer
        if path == '/api/savings/portfolio':
            if not portfolio_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Investment service unavailable'}).encode('utf-8'))
                return
            
            customer_id = qs.get('customer_id', [''])[0]
            account_id = qs.get('account_id', [''])[0]
            
            if account_id:
                result = portfolio_service.get_portfolio_summary(account_id)
            elif customer_id:
                accounts = portfolio_service.get_customer_accounts(customer_id)
                if accounts:
                    result = portfolio_service.get_portfolio_summary(accounts[0].account_id)
                else:
                    result = {'error': 'No savings account found', 'customer_id': customer_id}
            else:
                result = {'error': 'customer_id or account_id required'}
            
            self._set_json_headers()
            self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            return
        
        # Get all customer savings accounts
        if path == '/api/savings/accounts':
            if not portfolio_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Investment service unavailable'}).encode('utf-8'))
                return
            
            customer_id = qs.get('customer_id', [''])[0]
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            accounts = portfolio_service.get_customer_accounts(customer_id)
            result = {
                'customer_id': customer_id,
                'accounts': [
                    {
                        'account_id': acc.account_id,
                        'policy_id': acc.policy_id,
                        'balance': acc.balance,
                        'monthly_contribution': acc.monthly_contribution,
                        'savings_rate_pct': acc.savings_rate_pct,
                        'risk_profile': acc.risk_profile.value,
                        'total_assets': sum(a.market_value for a in acc.assets),
                        'created_at': acc.created_at
                    }
                    for acc in accounts
                ]
            }
            
            self._set_json_headers()
            self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            return
        
        # Get investment projections (Monte Carlo simulation)
        if path == '/api/savings/projections':
            if not portfolio_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Investment service unavailable'}).encode('utf-8'))
                return
            
            account_id = qs.get('account_id', [''])[0]
            years = int(qs.get('years', ['25'])[0])
            
            if not account_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'account_id required'}).encode('utf-8'))
                return
            
            result = portfolio_service.generate_projections(account_id, min(years, 50))
            self._set_json_headers()
            self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            return
        
        # Get AI recommendations
        if path == '/api/savings/recommendations':
            if not portfolio_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Investment service unavailable'}).encode('utf-8'))
                return
            
            account_id = qs.get('account_id', [''])[0]
            if not account_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'account_id required'}).encode('utf-8'))
                return
            
            recommendations = portfolio_service.generate_ai_recommendations(account_id)
            result = {'account_id': account_id, 'recommendations': recommendations}
            
            self._set_json_headers()
            self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            return
        
        # Get available assets for investment
        if path == '/api/savings/assets':
            if not portfolio_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Investment service unavailable'}).encode('utf-8'))
                return
            
            asset_class = qs.get('class', [''])[0]
            assets = portfolio_service.get_available_assets()
            
            if asset_class:
                assets = [a for a in assets if a['asset_class'] == asset_class]
            
            result = {'assets': assets, 'count': len(assets)}
            self._set_json_headers()
            self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            return
        
        # Get real-time market data
        if path == '/api/savings/market-data':
            if not portfolio_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Investment service unavailable'}).encode('utf-8'))
                return
            
            symbols = qs.get('symbols', [''])[0]
            if symbols:
                symbol_list = [s.strip().upper() for s in symbols.split(',')]
                data = portfolio_service.get_market_data(symbol_list)
            else:
                data = portfolio_service.get_market_data()
            
            # Add real-time crypto/index data if available
            if _market_data:
                try:
                    # Get live crypto prices
                    crypto_symbols = [s for s in (symbol_list if symbols else ['BTC', 'ETH', 'SOL']) 
                                     if s in ['BTC', 'ETH', 'SOL', 'USDC', 'USDT', 'BNB', 'XRP', 'ADA', 'DOGE']]
                    if crypto_symbols:
                        live_crypto = _market_data.get_crypto_prices_usd(crypto_symbols)
                        if 'prices' in live_crypto:
                            for sym, price in live_crypto['prices'].items():
                                if sym in portfolio_service.MARKET_DATA:
                                    portfolio_service.update_market_prices({sym: price})
                except Exception:
                    pass
            
            result = {
                'market_data': data,
                'last_updated': datetime.now().isoformat(),
                'source': 'phins_investment_service'
            }
            
            self._set_json_headers()
            self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            return
        
        # Get transaction history
        if path == '/api/savings/transactions':
            if not portfolio_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Investment service unavailable'}).encode('utf-8'))
                return
            
            account_id = qs.get('account_id', [''])[0]
            if not account_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'account_id required'}).encode('utf-8'))
                return
            
            account = portfolio_service.get_account(account_id)
            if not account:
                self._set_json_headers(404)
                self.wfile.write(json.dumps({'error': 'Account not found'}).encode('utf-8'))
                return
            
            limit = int(qs.get('limit', ['50'])[0])
            transactions = account.transactions[-limit:]
            
            result = {
                'account_id': account_id,
                'transactions': transactions,
                'count': len(transactions),
                'total_transactions': len(account.transactions)
            }
            
            self._set_json_headers()
            self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            return
        
        # ========== END SAVINGS & INVESTMENT PORTFOLIO API ==========
        
        # ========== ALGO TRADING GET API ==========
        # Get all trading bots for an account
        if path == '/api/algo/bots':
            if not algo_trading_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Algo trading service unavailable'}).encode('utf-8'))
                return
            
            account_id = qs.get('account_id', [''])[0]
            
            bots = []
            for bot in algo_trading_service.bots.values():
                if not account_id or bot.account_id == account_id:
                    from dataclasses import asdict
                    bot_data = asdict(bot)
                    bot_data['win_rate'] = bot.win_rate
                    bots.append(bot_data)
            
            self._set_json_headers()
            self.wfile.write(json.dumps({'bots': bots}).encode('utf-8'))
            return
        
        # Get bot performance
        if path == '/api/algo/bots/performance':
            if not algo_trading_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Algo trading service unavailable'}).encode('utf-8'))
                return
            
            bot_id = qs.get('bot_id', [''])[0]
            if not bot_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'bot_id required'}).encode('utf-8'))
                return
            
            performance = algo_trading_service.get_bot_performance(bot_id)
            self._set_json_headers()
            self.wfile.write(json.dumps(performance).encode('utf-8'))
            return
        
        # Get trading signals
        if path == '/api/algo/signals':
            if not algo_trading_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Algo trading service unavailable'}).encode('utf-8'))
                return
            
            symbol = qs.get('symbol', [''])[0]
            limit = int(qs.get('limit', ['50'])[0])
            
            signals = algo_trading_service.get_all_signals(symbol if symbol else None, limit)
            self._set_json_headers()
            self.wfile.write(json.dumps({'signals': signals}).encode('utf-8'))
            return
        
        # Get order history
        if path == '/api/algo/orders':
            if not algo_trading_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Algo trading service unavailable'}).encode('utf-8'))
                return
            
            account_id = qs.get('account_id', [''])[0]
            limit = int(qs.get('limit', ['50'])[0])
            
            orders = algo_trading_service.get_order_history(account_id if account_id else None, limit)
            self._set_json_headers()
            self.wfile.write(json.dumps({'orders': orders}).encode('utf-8'))
            return
        
        # Get technical indicators for a symbol
        if path == '/api/algo/indicators':
            if not algo_trading_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Algo trading service unavailable'}).encode('utf-8'))
                return
            
            symbol = qs.get('symbol', ['SPY'])[0]
            indicators = algo_trading_service.calculate_indicators(symbol)
            
            from dataclasses import asdict
            self._set_json_headers()
            self.wfile.write(json.dumps(asdict(indicators)).encode('utf-8'))
            return
        
        # Get market overview with signals
        if path == '/api/algo/market-overview':
            if not algo_trading_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Algo trading service unavailable'}).encode('utf-8'))
                return
            
            overview = algo_trading_service.get_market_overview()
            self._set_json_headers()
            self.wfile.write(json.dumps(overview).encode('utf-8'))
            return
        
        # Generate a signal for a specific symbol and strategy
        if path == '/api/algo/generate-signal':
            if not algo_trading_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Algo trading service unavailable'}).encode('utf-8'))
                return
            
            symbol = qs.get('symbol', ['SPY'])[0]
            strategy = qs.get('strategy', ['momentum'])[0]
            
            try:
                signal = algo_trading_service.generate_signal(symbol, TradingStrategy(strategy))
                from dataclasses import asdict
                self._set_json_headers()
                self.wfile.write(json.dumps({'signal': asdict(signal)}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # ========== END ALGO TRADING GET API ==========
        
        # ========== UNIFIED BALANCE GET API ==========
        # Get unified balance across all systems
        if path == '/api/balance/unified':
            if not unified_balance_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Unified balance service unavailable'}).encode('utf-8'))
                return
            
            customer_id = qs.get('customer_id', [''])[0]
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            balance = unified_balance_service.get_unified_balance(customer_id)
            self._set_json_headers()
            self.wfile.write(json.dumps(balance).encode('utf-8'))
            return
        
        # Get algo trading balance
        if path == '/api/balance/algo-trading':
            if not unified_balance_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Unified balance service unavailable'}).encode('utf-8'))
                return
            
            customer_id = qs.get('customer_id', [''])[0]
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            balance = unified_balance_service.get_algo_trading_balance(customer_id)
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'customer_id': customer_id,
                'balance': balance
            }).encode('utf-8'))
            return
        
        # Get all transactions across systems
        if path == '/api/balance/transactions':
            if not unified_balance_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Unified balance service unavailable'}).encode('utf-8'))
                return
            
            customer_id = qs.get('customer_id', [''])[0]
            limit = int(qs.get('limit', ['100'])[0])
            
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            transactions = unified_balance_service.get_all_transactions(customer_id, limit)
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'customer_id': customer_id,
                'transactions': transactions,
                'count': len(transactions)
            }).encode('utf-8'))
            return
        
        # Get all NFT tokens across systems
        if path == '/api/balance/nft-tokens':
            if not unified_balance_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Unified balance service unavailable'}).encode('utf-8'))
                return
            
            customer_id = qs.get('customer_id', [''])[0]
            limit = int(qs.get('limit', ['100'])[0])
            
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            tokens = unified_balance_service.get_all_nft_tokens(customer_id, limit)
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'customer_id': customer_id,
                'nft_tokens': tokens,
                'count': len(tokens)
            }).encode('utf-8'))
            return
        
        # Reconcile balances
        if path == '/api/balance/reconcile':
            if not unified_balance_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Unified balance service unavailable'}).encode('utf-8'))
                return
            
            customer_id = qs.get('customer_id', [''])[0]
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            reconciliation = unified_balance_service.reconcile_balances(customer_id)
            self._set_json_headers()
            self.wfile.write(json.dumps(reconciliation).encode('utf-8'))
            return
        
        # ========== END UNIFIED BALANCE GET API ==========
        
        # ========== PORTFOLIO TRACKER GET API ==========
        # Real-time P&L tracking for investments and algo trading
        
        # Get unified portfolio with real-time P&L
        if path == '/api/portfolio/unified':
            if not portfolio_tracker_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Portfolio tracker service unavailable'}).encode('utf-8'))
                return
            
            customer_id = qs.get('customer_id', [''])[0]
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            portfolio = portfolio_tracker_service.get_unified_portfolio(customer_id)
            self._set_json_headers()
            self.wfile.write(json.dumps(portfolio, default=str).encode('utf-8'))
            return
        
        # Get all positions with real-time prices and P&L
        if path == '/api/portfolio/positions':
            if not portfolio_tracker_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Portfolio tracker service unavailable'}).encode('utf-8'))
                return
            
            customer_id = qs.get('customer_id', [''])[0]
            portfolio_type = qs.get('type', [''])[0]  # investment, algo_trading, or empty for all
            
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            from services.portfolio_tracker_service import PortfolioType
            pt = None
            if portfolio_type == 'investment':
                pt = PortfolioType.INVESTMENT
            elif portfolio_type == 'algo_trading':
                pt = PortfolioType.ALGO_TRADING
            
            positions = portfolio_tracker_service.get_all_positions(customer_id, pt)
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'customer_id': customer_id,
                'positions': positions,
                'count': len(positions),
                'timestamp': datetime.now().isoformat()
            }, default=str).encode('utf-8'))
            return
        
        # Get portfolio summary with P&L
        if path == '/api/portfolio/summary':
            if not portfolio_tracker_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Portfolio tracker service unavailable'}).encode('utf-8'))
                return
            
            customer_id = qs.get('customer_id', [''])[0]
            portfolio_type = qs.get('type', ['combined'])[0]
            
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            from services.portfolio_tracker_service import PortfolioType
            if portfolio_type == 'investment':
                pt = PortfolioType.INVESTMENT
            elif portfolio_type == 'algo_trading':
                pt = PortfolioType.ALGO_TRADING
            else:
                pt = PortfolioType.COMBINED
            
            summary = portfolio_tracker_service.get_portfolio_summary(customer_id, pt)
            self._set_json_headers()
            self.wfile.write(json.dumps(summary.to_dict(), default=str).encode('utf-8'))
            return
        
        # Get trade history with P&L margin %
        if path == '/api/portfolio/trades':
            if not portfolio_tracker_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Portfolio tracker service unavailable'}).encode('utf-8'))
                return
            
            customer_id = qs.get('customer_id', [''])[0]
            limit = int(qs.get('limit', ['50'])[0])
            portfolio_type = qs.get('type', [''])[0]
            
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            from services.portfolio_tracker_service import PortfolioType
            pt = None
            if portfolio_type == 'investment':
                pt = PortfolioType.INVESTMENT
            elif portfolio_type == 'algo_trading':
                pt = PortfolioType.ALGO_TRADING
            
            trades = portfolio_tracker_service.get_trade_history(customer_id, limit, pt)
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'customer_id': customer_id,
                'trades': trades,
                'count': len(trades),
                'timestamp': datetime.now().isoformat()
            }, default=str).encode('utf-8'))
            return
        
        # Get P&L summary for period
        if path == '/api/portfolio/pnl':
            if not portfolio_tracker_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Portfolio tracker service unavailable'}).encode('utf-8'))
                return
            
            customer_id = qs.get('customer_id', [''])[0]
            period = qs.get('period', ['day'])[0]  # day, week, month, year, all
            
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            pnl = portfolio_tracker_service.get_pnl_summary(customer_id, period)
            self._set_json_headers()
            self.wfile.write(json.dumps(pnl, default=str).encode('utf-8'))
            return
        
        # Get algo trading as sub-portfolio
        if path == '/api/portfolio/algo':
            if not portfolio_tracker_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Portfolio tracker service unavailable'}).encode('utf-8'))
                return
            
            customer_id = qs.get('customer_id', [''])[0]
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            algo_portfolio = portfolio_tracker_service.get_algo_portfolio(customer_id)
            self._set_json_headers()
            self.wfile.write(json.dumps(algo_portfolio, default=str).encode('utf-8'))
            return
        
        # Get market price for a symbol
        if path == '/api/portfolio/price':
            if not portfolio_tracker_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Portfolio tracker service unavailable'}).encode('utf-8'))
                return
            
            symbol = qs.get('symbol', [''])[0]
            if not symbol:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'symbol required'}).encode('utf-8'))
                return
            
            price = portfolio_tracker_service.get_market_price(symbol)
            self._set_json_headers()
            self.wfile.write(json.dumps(price, default=str).encode('utf-8'))
            return
        
        # ========== END PORTFOLIO TRACKER GET API ==========
        
        # ========== SAVINGS PIPELINE GET API ==========
        # Get pipeline analytics for a customer
        if path == '/api/pipeline/analytics':
            if not savings_pipeline_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Savings pipeline service unavailable'}).encode('utf-8'))
                return
            
            customer_id = qs.get('customer_id', [''])[0]
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            analytics = savings_pipeline_service.get_pipeline_analytics(customer_id)
            self._set_json_headers()
            self.wfile.write(json.dumps(analytics).encode('utf-8'))
            return
        
        # Get AI recommendation for savings optimization
        if path == '/api/pipeline/ai-recommendation':
            if not savings_pipeline_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Savings pipeline service unavailable'}).encode('utf-8'))
                return
            
            customer_id = qs.get('customer_id', [''])[0]
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            recommendation = savings_pipeline_service.get_ai_recommendation(customer_id)
            self._set_json_headers()
            self.wfile.write(json.dumps(recommendation).encode('utf-8'))
            return
        
        # Get pipeline summary (admin/BI dashboard)
        if path == '/api/pipeline/summary':
            if not savings_pipeline_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Savings pipeline service unavailable'}).encode('utf-8'))
                return
            
            summary = savings_pipeline_service.get_pipeline_summary()
            self._set_json_headers()
            self.wfile.write(json.dumps(summary).encode('utf-8'))
            return
        
        # Get pipeline account details
        if path == '/api/pipeline/account':
            if not savings_pipeline_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Savings pipeline service unavailable'}).encode('utf-8'))
                return
            
            customer_id = qs.get('customer_id', [''])[0]
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            account = savings_pipeline_service.get_or_create_account(customer_id)
            from dataclasses import asdict
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'customer_id': customer_id,
                'account': asdict(account)
            }).encode('utf-8'))
            return
        
        # ========== END SAVINGS PIPELINE GET API ==========
        
        # ========== COMPREHENSIVE CUSTOMER API ==========
        # Get all customer data in one API call for dashboard
        if path == '/api/customer/dashboard-data':
            customer_id = qs.get('customer_id', [''])[0]
            
            if not customer_id:
                # Try to get from session
                if session:
                    customer_id = session.get('customer_id')
            
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            # Gather all customer data
            result = {
                'customer_id': customer_id,
                'timestamp': datetime.now().isoformat()
            }
            
            # 1. Customer profile
            customer = CUSTOMERS.get(customer_id, {})
            result['profile'] = {
                'name': customer.get('name', 'Customer'),
                'email': customer.get('email'),
                'phone': customer.get('phone'),
                'created_at': customer.get('created_at')
            }
            
            # 2. Policies
            customer_policies = [p for p in POLICIES.values() if p.get('customer_id') == customer_id]
            result['policies'] = {
                'items': customer_policies,
                'count': len(customer_policies),
                'total_coverage': sum(float(p.get('coverage_amount', 0)) for p in customer_policies),
                'total_premium': sum(float(p.get('monthly_premium', 0)) for p in customer_policies)
            }
            
            # 3. Claims
            customer_claims = [c for c in CLAIMS.values() if c.get('customer_id') == customer_id]
            result['claims'] = {
                'items': customer_claims,
                'count': len(customer_claims),
                'pending': len([c for c in customer_claims if c.get('status', '').lower() in ['pending', 'under review']])
            }
            
            # 4. Health wallet
            wallet = HEALTH_WALLETS.get(customer_id, {'balance': 0, 'transactions': []})
            result['health_wallet'] = {
                'balance': wallet.get('balance', 0),
                'monthly_deposit': wallet.get('monthly_deposit', 0),
                'transactions_count': len(wallet.get('transactions', []))
            }
            
            # 5. Investment account
            inv_acc = INVESTMENT_ACCOUNTS.get(customer_id, {})
            result['investment_account'] = {
                'balance': inv_acc.get('balance', 0),
                'index_balance': inv_acc.get('index_balance', 0),
                'bonds_balance': inv_acc.get('bonds_balance', 0),
                'crypto_balance': inv_acc.get('crypto_balance', 0),
                'deposits_count': len(inv_acc.get('deposits', []))
            }
            
            # 6. Algo trading balance
            if unified_balance_enabled:
                algo_bal = unified_balance_service.get_algo_trading_balance(customer_id)
                result['algo_trading'] = {
                    'available': algo_bal.get('available', 0),
                    'in_positions': algo_bal.get('in_positions', 0),
                    'total_pnl': algo_bal.get('total_pnl', 0),
                    'active_bots': algo_bal.get('active_bots', 0)
                }
            
            # 7. Pipeline account
            if savings_pipeline_enabled:
                try:
                    pipeline_analytics = savings_pipeline_service.get_pipeline_analytics(customer_id)
                    result['pipeline'] = {
                        'cash_balance': pipeline_analytics.get('balances', {}).get('cash_balance', 0),
                        'total_balance': pipeline_analytics.get('balances', {}).get('total_balance', 0),
                        'health_score': pipeline_analytics.get('pipeline_health', {}).get('score', 0),
                        'projections': pipeline_analytics.get('projections', {})
                    }
                except Exception:
                    result['pipeline'] = None
            
            # 8. NFT tokens count
            nft_count = len([nft for nft in NFT_LEDGER.values() if nft.get('owner_id') == customer_id])
            result['nft_tokens_count'] = nft_count
            
            # 9. Transaction count
            tx_count = len([tx for tx in TRANSACTION_LEDGER.values() if tx.get('customer_id') == customer_id])
            result['transactions_count'] = tx_count
            
            # 10. Total assets
            total_assets = (
                wallet.get('balance', 0) +
                inv_acc.get('balance', 0) +
                result.get('algo_trading', {}).get('available', 0) +
                result.get('algo_trading', {}).get('in_positions', 0)
            )
            result['total_assets'] = total_assets
            
            # 11. Billing summary
            customer_bills = [b for b in BILLING.values() if b.get('customer_id') == customer_id]
            outstanding = sum(
                (b.get('amount', b.get('amount_due', 0)) - b.get('amount_paid', 0))
                for b in customer_bills
                if b.get('status') in ['outstanding', 'pending', 'partial']
            )
            result['billing'] = {
                'outstanding_amount': outstanding,
                'bills_count': len(customer_bills),
                'next_due': min(
                    (b.get('due_date') for b in customer_bills if b.get('status') in ['outstanding', 'pending']),
                    default=None
                )
            }
            
            self._set_json_headers()
            self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            return
        
        # ========== END COMPREHENSIVE CUSTOMER API ==========
        
        # ========== UNIFIED ACTIVITY LOG API ==========
        # Get all customer activities across all systems in unified view
        if path == '/api/customer/activity-log':
            customer_id = qs.get('customer_id', [''])[0]
            limit = int(qs.get('limit', ['50'])[0])
            
            if not customer_id:
                if session:
                    customer_id = session.get('customer_id')
            
            if not customer_id:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                return
            
            # Collect all activities from various sources
            activities = []
            
            # 1. Health Wallet Transactions (deposits & internal)
            wallet = HEALTH_WALLETS.get(customer_id, {})
            for tx in wallet.get('transactions', []):
                activities.append({
                    'id': tx.get('id', f"WAL-{len(activities)}"),
                    'type': 'deposit' if tx.get('type') == 'deposit' else 'wallet_activity',
                    'category': 'health_wallet',
                    'icon': '💰' if tx.get('type') == 'deposit' else '💳',
                    'description': f"Health Wallet {'Deposit' if tx.get('type') == 'deposit' else tx.get('type', 'Transaction')}",
                    'amount': tx.get('amount', 0),
                    'balance_after': tx.get('balance_after', 0),
                    'timestamp': tx.get('timestamp', tx.get('created_at', '')),
                    'nft_token_id': tx.get('nft_token_id'),
                    'ledger_tx_id': tx.get('ledger_tx_id')
                })
            
            # 2. Medical Purchases
            for purchase in MEDICAL_PURCHASES.values():
                if purchase.get('customer_id') == customer_id:
                    activities.append({
                        'id': purchase.get('id'),
                        'type': 'medical_purchase',
                        'category': purchase.get('category', 'medical'),
                        'icon': '💊',
                        'description': f"Medical Purchase: {purchase.get('product_name', 'Product')}",
                        'product_name': purchase.get('product_name'),
                        'provider': purchase.get('provider'),
                        'amount': -purchase.get('amount', 0),
                        'timestamp': purchase.get('timestamp', ''),
                        'nft_token_id': purchase.get('nft_token_id'),
                        'ledger_tx_id': purchase.get('ledger_tx_id'),
                        'status': purchase.get('status', 'completed')
                    })
            
            # 3. Investment Deposits & Activities
            inv_acc = INVESTMENT_ACCOUNTS.get(customer_id, {})
            for deposit in inv_acc.get('deposits', []):
                activities.append({
                    'id': deposit.get('id', f"INV-{len(activities)}"),
                    'type': 'investment_deposit',
                    'category': 'investments',
                    'icon': '📈',
                    'description': f"Investment Deposit - {deposit.get('allocation', 'Portfolio')}",
                    'amount': deposit.get('amount', 0),
                    'allocation': deposit.get('allocation'),
                    'timestamp': deposit.get('timestamp', deposit.get('created_at', '')),
                    'nft_token_id': deposit.get('nft_token_id'),
                    'ledger_tx_id': deposit.get('ledger_tx_id')
                })
            
            # 4. Algo Trading Orders (from transaction ledger)
            for tx in TRANSACTION_LEDGER.values():
                if tx.get('customer_id') == customer_id and tx.get('tx_type') in ['algo_trade', 'algo_order']:
                    meta = tx.get('metadata', {})
                    activities.append({
                        'id': tx.get('id'),
                        'type': 'algo_trade',
                        'category': 'algo_trading',
                        'icon': '🤖',
                        'description': f"Algo Trade: {meta.get('side', 'Trade')} {meta.get('symbol', '')}",
                        'symbol': meta.get('symbol'),
                        'side': meta.get('side'),
                        'quantity': meta.get('quantity'),
                        'amount': tx.get('amount', 0),
                        'timestamp': tx.get('timestamp', tx.get('created_at', '')),
                        'nft_token_id': tx.get('nft_token_id'),
                        'status': meta.get('status', 'executed')
                    })
            
            # 5. Bill Payments
            for tx in TRANSACTION_LEDGER.values():
                if tx.get('customer_id') == customer_id and tx.get('tx_type') in ['bill_payment', 'premium_payment']:
                    meta = tx.get('metadata', {})
                    activities.append({
                        'id': tx.get('id'),
                        'type': tx.get('tx_type'),
                        'category': 'billing',
                        'icon': '💳',
                        'description': f"{'Premium' if tx.get('tx_type') == 'premium_payment' else 'Bill'} Payment",
                        'amount': -tx.get('amount', 0),
                        'timestamp': tx.get('timestamp', tx.get('created_at', '')),
                        'nft_token_id': tx.get('nft_token_id'),
                        'policy_id': meta.get('policy_id')
                    })
            
            # 6. Claims
            for claim in CLAIMS.values():
                if claim.get('customer_id') == customer_id:
                    activities.append({
                        'id': claim.get('id'),
                        'type': 'claim',
                        'category': 'claims',
                        'icon': '📋',
                        'description': f"Claim: {claim.get('description', claim.get('type', 'Insurance Claim'))}",
                        'amount': claim.get('claimed_amount', 0),
                        'status': claim.get('status', 'pending'),
                        'timestamp': claim.get('submitted_at', claim.get('created_at', '')),
                        'nft_token_id': claim.get('nft_token_id'),
                        'ledger_tx_id': claim.get('ledger_tx_id')
                    })
            
            # Sort by timestamp descending
            activities.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
            
            # Calculate summary
            total_deposits = sum(a['amount'] for a in activities if a['type'] == 'deposit' and a['amount'] > 0)
            total_purchases = abs(sum(a['amount'] for a in activities if a['type'] == 'medical_purchase'))
            total_investments = sum(a['amount'] for a in activities if a['type'] == 'investment_deposit' and a['amount'] > 0)
            total_algo = sum(abs(a['amount']) for a in activities if a['type'] == 'algo_trade')
            
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'success': True,
                'customer_id': customer_id,
                'activities': activities[:limit],
                'total_count': len(activities),
                'summary': {
                    'total_deposits': total_deposits,
                    'total_medical_purchases': total_purchases,
                    'total_investments': total_investments,
                    'total_algo_trading': total_algo,
                    'activity_count': len(activities)
                },
                'timestamp': datetime.now().isoformat()
            }, default=str).encode('utf-8'))
            return
        
        # ========== END UNIFIED ACTIVITY LOG API ==========
        
        # ========== PLATFORM ANALYTICS API (ADMIN) ==========
        # Aggregated platform-wide data for admin dashboard predictions & statistics
        if path == '/api/admin/platform-analytics':
            # Aggregate all customer data for platform-wide insights
            
            # 1. Platform Totals
            total_customers = len(CUSTOMERS)
            total_deposits = sum(
                sum(tx.get('amount', 0) for tx in w.get('transactions', []) if tx.get('type') == 'deposit')
                for w in HEALTH_WALLETS.values()
            )
            total_medical_purchases = sum(p.get('amount', 0) for p in MEDICAL_PURCHASES.values())
            total_investment_volume = sum(
                sum(d.get('amount', 0) for d in acc.get('deposits', []))
                for acc in INVESTMENT_ACCOUNTS.values()
            )
            
            # Algo trading volume from transaction ledger
            total_algo_volume = sum(
                abs(tx.get('amount', 0)) 
                for tx in TRANSACTION_LEDGER.values() 
                if tx.get('tx_type') in ['algo_trade', 'algo_order']
            )
            
            # 2. Medical Purchases by Category
            medical_by_category = {}
            for purchase in MEDICAL_PURCHASES.values():
                cat = purchase.get('category', 'general')
                if cat not in medical_by_category:
                    medical_by_category[cat] = {'count': 0, 'total': 0, 'products': {}}
                medical_by_category[cat]['count'] += 1
                medical_by_category[cat]['total'] += purchase.get('amount', 0)
                
                # Track individual products
                product = purchase.get('product_name', 'Unknown')
                if product not in medical_by_category[cat]['products']:
                    medical_by_category[cat]['products'][product] = {'count': 0, 'total': 0}
                medical_by_category[cat]['products'][product]['count'] += 1
                medical_by_category[cat]['products'][product]['total'] += purchase.get('amount', 0)
            
            # 3. Investments by Asset Type
            investments_by_asset = {
                'index_funds': {'customers': 0, 'total_usd': 0},
                'bonds': {'customers': 0, 'total_usd': 0},
                'crypto': {'customers': 0, 'total_usd': 0},
                'algo_trading': {'customers': 0, 'total_usd': 0}
            }
            for cust_id, acc in INVESTMENT_ACCOUNTS.items():
                if acc.get('index_balance', 0) > 0:
                    investments_by_asset['index_funds']['customers'] += 1
                    investments_by_asset['index_funds']['total_usd'] += acc.get('index_balance', 0)
                if acc.get('bonds_balance', 0) > 0:
                    investments_by_asset['bonds']['customers'] += 1
                    investments_by_asset['bonds']['total_usd'] += acc.get('bonds_balance', 0)
                if acc.get('crypto_balance', 0) > 0:
                    investments_by_asset['crypto']['customers'] += 1
                    investments_by_asset['crypto']['total_usd'] += acc.get('crypto_balance', 0)
            
            # Algo trading customer count
            algo_customers = set()
            for tx in TRANSACTION_LEDGER.values():
                if tx.get('tx_type') in ['algo_trade', 'algo_order']:
                    algo_customers.add(tx.get('customer_id'))
            investments_by_asset['algo_trading']['customers'] = len(algo_customers)
            investments_by_asset['algo_trading']['total_usd'] = total_algo_volume
            
            # 4. Algo Trading Stats
            algo_orders = [tx for tx in TRANSACTION_LEDGER.values() if tx.get('tx_type') in ['algo_trade', 'algo_order']]
            algo_stats = {
                'active_bots': len(getattr(algo_trading_service, 'bots', {})) if algo_trading_enabled else 0,
                'total_orders': len(algo_orders),
                'total_volume': total_algo_volume,
                'unique_customers': len(algo_customers),
                'avg_order_size': total_algo_volume / len(algo_orders) if algo_orders else 0
            }
            
            # 5. Ledger Integrity
            nft_count = len(NFT_LEDGER)
            tx_count = len(TRANSACTION_LEDGER)
            ledger_integrity = {
                'nft_tokens': nft_count,
                'transaction_records': tx_count,
                'integrity_score': 100 if nft_count > 0 and tx_count > 0 else 0,
                'medical_nfts': len([n for n in NFT_LEDGER.values() if n.get('transaction_type') == 'medical_purchase']),
                'deposit_nfts': len([n for n in NFT_LEDGER.values() if n.get('transaction_type') == 'wallet_deposit']),
                'investment_nfts': len([n for n in NFT_LEDGER.values() if n.get('transaction_type') == 'investment_deposit']),
                'algo_nfts': len([n for n in NFT_LEDGER.values() if n.get('transaction_type') in ['algo_trade', 'algo_order']])
            }
            
            # 6. Transaction Breakdown by Type
            tx_by_type = {}
            for tx in TRANSACTION_LEDGER.values():
                tx_type = tx.get('tx_type', 'unknown')
                if tx_type not in tx_by_type:
                    tx_by_type[tx_type] = {'count': 0, 'total_amount': 0}
                tx_by_type[tx_type]['count'] += 1
                tx_by_type[tx_type]['total_amount'] += abs(tx.get('amount', 0))
            
            # 7. Health Wallet Summary
            wallet_summary = {
                'total_wallets': len(HEALTH_WALLETS),
                'total_balance': sum(w.get('balance', 0) for w in HEALTH_WALLETS.values()),
                'total_deposits': total_deposits,
                'total_spent': total_medical_purchases,
                'avg_balance': sum(w.get('balance', 0) for w in HEALTH_WALLETS.values()) / len(HEALTH_WALLETS) if HEALTH_WALLETS else 0
            }
            
            # 8. Predictions / BI Metrics
            avg_purchase_per_customer = total_medical_purchases / total_customers if total_customers > 0 else 0
            avg_investment_per_customer = total_investment_volume / total_customers if total_customers > 0 else 0
            
            predictions = {
                'avg_purchase_per_customer': avg_purchase_per_customer,
                'avg_investment_per_customer': avg_investment_per_customer,
                'projected_monthly_purchases': total_medical_purchases * 1.1,  # 10% growth
                'projected_monthly_investments': total_investment_volume * 1.15,  # 15% growth
                'customer_lifetime_value': (avg_purchase_per_customer + avg_investment_per_customer) * 12,
                'platform_health_score': min(100, (nft_count + tx_count) / max(1, total_customers) * 10)
            }
            
            # 9. Top Products
            all_products = {}
            for purchase in MEDICAL_PURCHASES.values():
                product = purchase.get('product_name', 'Unknown')
                if product not in all_products:
                    all_products[product] = {'count': 0, 'total': 0}
                all_products[product]['count'] += 1
                all_products[product]['total'] += purchase.get('amount', 0)
            
            top_products = sorted(all_products.items(), key=lambda x: x[1]['count'], reverse=True)[:10]
            
            self._set_json_headers()
            self.wfile.write(json.dumps({
                'success': True,
                'platform_totals': {
                    'total_customers': total_customers,
                    'total_deposits': total_deposits,
                    'total_medical_purchases': total_medical_purchases,
                    'total_investment_volume': total_investment_volume,
                    'total_algo_trading_volume': total_algo_volume,
                    'total_aum': total_deposits + total_investment_volume + total_algo_volume
                },
                'medical_by_category': medical_by_category,
                'investments_by_asset': investments_by_asset,
                'algo_trading': algo_stats,
                'ledger_integrity': ledger_integrity,
                'transactions_by_type': tx_by_type,
                'wallet_summary': wallet_summary,
                'predictions': predictions,
                'top_products': [{'name': p[0], **p[1]} for p in top_products],
                'timestamp': datetime.now().isoformat()
            }, default=str).encode('utf-8'))
            return
        
        # ========== END PLATFORM ANALYTICS API ==========

        # Investment portfolio endpoint (legacy - redirect to new API)
        if path.startswith('/api/investment-portfolio'):
            customer_id = qs.get('customer_id', ['CUST001'])[0]
            result = {'customer_id': customer_id, 'message': 'Portfolio data unavailable'}
            try:
                # Try new portfolio service first
                if portfolio_enabled:
                    accounts = portfolio_service.get_customer_accounts(customer_id)
                    if accounts:
                        result = portfolio_service.get_portfolio_summary(accounts[0].account_id)
                    else:
                        # Fallback to accounting engine
                        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                        from accounting_engine import AccountingEngine
                        engine = AccountingEngine()
                        portfolio = engine.get_investment_portfolio_summary(customer_id)
                        result = portfolio
                else:
                    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                    from accounting_engine import AccountingEngine
                    engine = AccountingEngine()
                    portfolio = engine.get_investment_portfolio_summary(customer_id)
                    result = portfolio
            except Exception as e:
                result['error'] = str(e)
            
            self._set_json_headers()
            self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            return

        # Projected returns endpoint
        if path.startswith('/api/projected-returns'):
            customer_id = qs.get('customer_id', ['CUST001'])[0]
            years = int(qs.get('years', ['5'])[0])
            result = {'customer_id': customer_id, 'message': 'Projections unavailable'}
            try:
                # Try new portfolio service first
                if portfolio_enabled:
                    accounts = portfolio_service.get_customer_accounts(customer_id)
                    if accounts:
                        result = portfolio_service.generate_projections(accounts[0].account_id, years)
                    else:
                        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                        from accounting_engine import AccountingEngine
                        engine = AccountingEngine()
                        returns = engine.get_projected_returns_analysis(customer_id, years)
                        result = returns
                else:
                    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
                    from accounting_engine import AccountingEngine
                    engine = AccountingEngine()
                    returns = engine.get_projected_returns_analysis(customer_id, years)
                    result = returns
            except Exception as e:
                result['error'] = str(e)
            
            self._set_json_headers()
            self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            return

        # Serve static files from web_portal/static
        if path == '/' or path == '/index.html':
            file_path = os.path.join(ROOT, 'index.html')
        else:
            rel = path.lstrip('/')
            file_path = os.path.join(ROOT, rel)

        if os.path.isfile(file_path):
            try:
                self._set_file_headers(file_path)
                with open(file_path, 'rb') as fh:
                    self.wfile.write(fh.read())
            except Exception as e:
                self.send_error(500, str(e))
        else:
            self.send_error(404, 'Not Found: %s' % self.path)

    def do_POST(self):
        # Periodic cleanup of stale data
        cleanup_stale_data()
        
        # Security checks
        client_ip = self.client_address[0]
        
        # Check if IP is blocked
        is_blocked, block_reason = is_ip_blocked(client_ip)
        if is_blocked:
            self.send_response(403)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'error': 'Access denied',
                'message': 'Your IP has been blocked due to suspicious activity'
            }).encode('utf-8'))
            return
        
        # Rate limiting
        if not check_rate_limit(client_ip):
            log_malicious_attempt(client_ip, 'Rate Limit Exceeded (POST)', {'endpoint': self.path})
            self.send_response(429)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Retry-After', '60')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Too many requests. Please try again later.'}).encode('utf-8'))
            return
        
        # Check request size
        # Check request size
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length > MAX_REQUEST_SIZE:
            log_malicious_attempt(client_ip, 'Oversized Request', {
                'size': content_length,
                'max_allowed': MAX_REQUEST_SIZE
            })
            self.send_response(413)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Request too large'}).encode('utf-8'))
            return
        
        parsed = urlparse.urlparse(self.path)
        path = parsed.path
        
        # Handle multipart form data for quote submission
        if path == '/api/submit-quote':
            self.handle_quote_submission()
            return
        
        # Regular JSON POST requests
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length).decode('utf-8') if length else ''
        
        # Demo login endpoint with secure password verification
        if path == '/api/login':
            client_ip = self.client_address[0]
            
            # Check if IP is locked out
            if not check_login_lockout(client_ip):
                lockout_data = FAILED_LOGINS.get(client_ip, {})
                remaining = int(lockout_data.get('lockout_until', 0) - datetime.now().timestamp())
                self._set_json_headers(429)
                self.wfile.write(json.dumps({
                    'error': f'Too many failed login attempts. Try again in {remaining} seconds.',
                    'lockout_remaining': remaining
                }).encode('utf-8'))
                return
            
            try:
                creds = json.loads(body)
                username = creds.get('username', '').strip()
                password = creds.get('password', '')
                
                # Input validation
                if not username or not password:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Username and password required'}).encode('utf-8'))
                    return
                
                # Security validation on username
                is_valid, error = validate_input_security(username, client_ip, 'username')
                if not is_valid:
                    record_failed_login(client_ip)
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid username format'}).encode('utf-8'))
                    return
                
                if len(password) < 6:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid credentials'}).encode('utf-8'))
                    return
                
                # Try to authenticate - check USERS first (staff), then CUSTOMERS (policyholders)
                user = None
                customer_id = None
                role = None
                name = None
                
                # 1. Check internal users (admin, underwriter, etc.)
                try:
                    staff_user = USERS.get(username)
                    if staff_user and verify_password(password, staff_user['hash'], staff_user['salt']):
                        user = staff_user
                        customer_id = staff_user.get('customer_id')
                        role = staff_user['role']
                        name = staff_user['name']
                except Exception as e:
                    print(f"Staff user check error: {e}")
                    staff_user = None
                
                # 2. Check customers table (by email) - for customer logins
                # This runs if: no user found OR user found but password failed (handles password mismatch between tables)
                if not user and USE_DATABASE and database_enabled:
                    try:
                        from database.manager import DatabaseManager
                        with DatabaseManager() as db:
                            # Use repository method to get customer by email
                            customer = db.customers.get_by_email(username.lower())
                            if customer and getattr(customer, 'password_hash', None) and getattr(customer, 'password_salt', None):
                                if verify_password(password, customer.password_hash, customer.password_salt):
                                    user = {
                                        'hash': customer.password_hash,
                                        'salt': customer.password_salt,
                                        'role': 'customer',
                                        'name': customer.name
                                    }
                                    customer_id = customer.id
                                    role = 'customer'
                                    name = customer.name
                                    # Update last login
                                    try:
                                        db.customers.update_last_login(customer.id)
                                        db.commit()
                                    except Exception:
                                        pass  # Non-critical
                    except Exception as e:
                        print(f"Customer auth check error: {e}")
                        import traceback
                        traceback.print_exc()
                
                # 3. Fallback: Check in-memory CUSTOMERS (for non-DB mode)
                if not user and not database_enabled:
                    for cust_id, cust in CUSTOMERS.items():
                        if cust.get('email', '').lower() == username.lower():
                            if cust.get('password_hash') and cust.get('password_salt'):
                                if verify_password(password, cust['password_hash'], cust['password_salt']):
                                    user = cust
                                    customer_id = cust_id
                                    role = 'customer'
                                    name = cust.get('name', 'Customer')
                            break
                
                if user:
                    # Clear failed login attempts on success
                    with STATE_LOCK:
                        if client_ip in FAILED_LOGINS:
                            del FAILED_LOGINS[client_ip]
                    
                    # Generate secure session token
                    token = f"phins_{secrets.token_urlsafe(32)}"
                    expires = datetime.now() + timedelta(seconds=SESSION_TIMEOUT)
                    
                    # Store session
                    with STATE_LOCK:
                        SESSIONS[token] = {
                            'username': username,
                            'expires': expires.isoformat(),
                            'customer_id': customer_id,
                            'role': role,
                            'ip_address': client_ip
                        }
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True,
                        'token': token,
                        'username': username,
                        'role': role,
                        'name': name,
                        'customer_id': customer_id,
                        'expires': expires.isoformat()
                    }).encode('utf-8'))
                else:
                    # Record failed login attempt
                    record_failed_login(client_ip)
                    
                    self._set_json_headers(401)
                    self.wfile.write(json.dumps({'error': 'Invalid credentials'}).encode('utf-8'))
            except json.JSONDecodeError:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid JSON payload'}).encode('utf-8'))
            except Exception as e:
                print(f"Login error: {e}")
                import traceback
                traceback.print_exc()
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': 'Internal server error', 'debug': str(e)}).encode('utf-8'))
            return
        
        # User Registration Endpoint
        if path == '/api/register':
            try:
                data = json.loads(body)
                name = sanitize_input(data.get('name', ''), 100)
                email = sanitize_input(data.get('email', ''), 254).lower()
                phone = sanitize_input(data.get('phone', ''), 20)
                dob = data.get('dob', '')
                password = data.get('password', '')
                
                # Validation
                if not name or not email or not password:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Name, email, and password are required'}).encode('utf-8'))
                    return
                
                if not validate_email(email):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid email format'}).encode('utf-8'))
                    return
                
                if len(password) < 8:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Password must be at least 8 characters'}).encode('utf-8'))
                    return
                
                # Check if user already exists
                with STATE_LOCK:
                    user_exists = email in USERS
                if user_exists:
                    self._set_json_headers(409)
                    self.wfile.write(json.dumps({'error': 'Email already registered'}).encode('utf-8'))
                    return
                
                # Create customer record
                customer_id = generate_customer_id()
                with STATE_LOCK:
                    CUSTOMERS[customer_id] = {
                        'id': customer_id,
                        'name': name,
                        'email': email,
                        'phone': phone,
                        'dob': dob,
                        'created_date': datetime.now().isoformat()
                    }
                
                # Create user account
                pwd_hash = hash_password(password)
                with STATE_LOCK:
                    USERS[email] = {
                        'hash': pwd_hash['hash'],
                        'salt': pwd_hash['salt'],
                        'role': 'customer',
                        'name': name,
                        'customer_id': customer_id
                    }
                
                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'success': True,
                    'customer_id': customer_id,
                    'email': email,
                    'message': 'Account created successfully. Please login with your credentials.'
                }).encode('utf-8'))
            except json.JSONDecodeError:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid JSON payload'}).encode('utf-8'))
            except Exception:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': 'Registration failed'}).encode('utf-8'))
            return
        
        # Password Reset Endpoint
        if path == '/api/reset-password':
            try:
                data = json.loads(body)
                username = sanitize_input(data.get('username', ''), 254).lower()
                email = sanitize_input(data.get('email', ''), 254).lower()
                new_password = data.get('new_password', '')
                
                # Validation
                if not username or not email or not new_password:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'All fields are required'}).encode('utf-8'))
                    return
                
                if len(new_password) < 8:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Password must be at least 8 characters'}).encode('utf-8'))
                    return
                
                # Verify user exists and email matches
                user = USERS.get(username)
                if not user:
                    # Try to find by email
                    user = USERS.get(email)
                    username = email
                
                if not user:
                    self._set_json_headers(401)
                    self.wfile.write(json.dumps({'error': 'Invalid credentials'}).encode('utf-8'))
                    return
                
                # Verify email matches customer record
                customer_id = user.get('customer_id')
                if customer_id:
                    customer = CUSTOMERS.get(customer_id)
                    if customer and customer.get('email', '').lower() != email:
                        self._set_json_headers(401)
                        self.wfile.write(json.dumps({'error': 'Email does not match our records'}).encode('utf-8'))
                        return
                
                # Update password
                pwd_hash = hash_password(new_password)
                USERS[username]['hash'] = pwd_hash['hash']
                USERS[username]['salt'] = pwd_hash['salt']
                
                # Invalidate all existing sessions for this user
                sessions_to_remove = [token for token, sess in SESSIONS.items() if sess.get('username') == username]
                for token in sessions_to_remove:
                    del SESSIONS[token]
                
                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'message': 'Password reset successfully. Please login with your new password.'
                }).encode('utf-8'))
            except json.JSONDecodeError:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid JSON payload'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': 'Password reset failed'}).encode('utf-8'))
            return
        
        # Change Password Endpoint (authenticated users)
        if path == '/api/change-password':
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
            session = validate_session(token) if token else None
            
            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Please login.'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                current_password = data.get('current_password', '')
                new_password = data.get('new_password', '')
                
                if not current_password or not new_password:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Current and new password are required'}).encode('utf-8'))
                    return
                
                if len(new_password) < 8:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'New password must be at least 8 characters'}).encode('utf-8'))
                    return
                
                username = session.get('username')
                user = USERS.get(username)
                
                if not user:
                    self._set_json_headers(401)
                    self.wfile.write(json.dumps({'error': 'User not found'}).encode('utf-8'))
                    return
                
                # Verify current password
                if not verify_password(current_password, user['hash'], user['salt']):
                    self._set_json_headers(401)
                    self.wfile.write(json.dumps({'error': 'Current password is incorrect'}).encode('utf-8'))
                    return
                
                # Update password
                pwd_hash = hash_password(new_password)
                USERS[username]['hash'] = pwd_hash['hash']
                USERS[username]['salt'] = pwd_hash['salt']
                
                # Invalidate all sessions except current
                sessions_to_remove = [t for t, s in SESSIONS.items() if s.get('username') == username and t != token]
                for t in sessions_to_remove:
                    del SESSIONS[t]
                
                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'message': 'Password changed successfully'
                }).encode('utf-8'))
            except json.JSONDecodeError:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid JSON payload'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': 'Password change failed'}).encode('utf-8'))
            return
        
        # Admin: Create New User Endpoint
        if path == '/api/admin/create-user':
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
            session = validate_session(token) if token else None
            
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                username = sanitize_input(data.get('username', ''), 100).lower()
                name = sanitize_input(data.get('name', ''), 100)
                email = sanitize_input(data.get('email', ''), 254).lower()
                role = data.get('role', 'customer')
                password = data.get('password', '')
                
                # Validation
                if not username or not name or not password:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Username, name, and password are required'}).encode('utf-8'))
                    return
                
                if role not in ['customer', 'admin', 'underwriter', 'claims', 'accountant']:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid role'}).encode('utf-8'))
                    return
                
                if len(password) < 8:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Password must be at least 8 characters'}).encode('utf-8'))
                    return
                
                # Check if user already exists
                if username in USERS:
                    self._set_json_headers(409)
                    self.wfile.write(json.dumps({'error': 'Username already exists'}).encode('utf-8'))
                    return
                
                # Create customer record if role is customer
                customer_id = None
                if role == 'customer':
                    customer_id = generate_customer_id()
                    CUSTOMERS[customer_id] = {
                        'id': customer_id,
                        'name': name,
                        'email': email,
                        'created_date': datetime.now().isoformat()
                    }
                
                # Create user account
                pwd_hash = hash_password(password)
                USERS[username] = {
                    'hash': pwd_hash['hash'],
                    'salt': pwd_hash['salt'],
                    'role': role,
                    'name': name,
                    'customer_id': customer_id
                }
                
                self._set_json_headers(201)
                self.wfile.write(json.dumps({
                    'success': True,
                    'username': username,
                    'role': role,
                    'customer_id': customer_id,
                    'message': 'User created successfully'
                }).encode('utf-8'))
            except json.JSONDecodeError:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid JSON payload'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': 'User creation failed'}).encode('utf-8'))
            return

        # Admin: Upload actuarial table (JSON or CSV)
        if path == '/api/admin/actuarial-tables/upload':
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
            session = validate_session(token) if token else None
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return

            try:
                content_type = (self.headers.get('Content-Type') or '').lower()
                raw = body
                payload: Dict[str, Any] = {}

                if 'text/csv' in content_type:
                    # CSV upload: first row is headers; store rows as list of dicts
                    reader = csv.DictReader(io.StringIO(raw))
                    rows = [r for r in reader]
                    payload = {
                        "name": f"CSV Upload {datetime.now().strftime('%Y-%m-%d')}",
                        "table_type": "pricing",
                        "version": datetime.now().strftime('%Y%m%d'),
                        "effective_date": datetime.now().strftime('%Y-%m-%d'),
                        "data": rows,
                    }
                else:
                    payload = json.loads(raw or '{}')

                name = str(payload.get('name') or '').strip() or 'Actuarial Table'
                table_type = str(payload.get('table_type') or payload.get('type') or 'pricing').strip().lower()
                version = str(payload.get('version') or datetime.now().strftime('%Y%m%d')).strip()
                effective_date = payload.get('effective_date')  # YYYY-MM-DD optional
                data_obj = payload.get('data')

                if data_obj is None:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Missing data field'}).encode('utf-8'))
                    return

                actor = (session or {}).get('username') if session else 'admin'
                table_id = f"AT-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000,9999)}"

                if encrypt_json:
                    blob = encrypt_json(data_obj).to_json()
                else:
                    blob = json.dumps({"scheme": "plain", "ciphertext": json.dumps(data_obj)})

                if USE_DATABASE and database_enabled:
                    from database.manager import DatabaseManager
                    from database.models import ActuarialTable
                    eff_dt = None
                    try:
                        eff_dt = datetime.strptime(str(effective_date), '%Y-%m-%d') if effective_date else None
                    except Exception:
                        eff_dt = None
                    with DatabaseManager() as db:
                        row = ActuarialTable(
                            id=table_id,
                            name=name,
                            table_type=table_type,
                            version=version,
                            effective_date=eff_dt,
                            payload=blob,
                            classification="restricted",
                            created_by=actor,
                        )
                        db.actuarial.create(row)

                    if audit:
                        try:
                            audit.log(actor, 'upload', 'actuarial_table', table_id, {'table_type': table_type, 'version': version})
                        except Exception:
                            pass

                    self._set_json_headers(201)
                    self.wfile.write(json.dumps({'success': True, 'id': table_id}).encode('utf-8'))
                    return

                with STATE_LOCK:
                    ACTUARIAL_TABLES[table_id] = {
                        "id": table_id,
                        "name": name,
                        "table_type": table_type,
                        "version": version,
                        "effective_date": effective_date,
                        "classification": "restricted",
                        "created_by": actor,
                        "created_date": datetime.now().isoformat(),
                        "payload": blob,
                    }

                if audit:
                    try:
                        audit.log(actor, 'upload', 'actuarial_table', table_id, {'table_type': table_type, 'version': version})
                    except Exception:
                        pass

                self._set_json_headers(201)
                self.wfile.write(json.dumps({'success': True, 'id': table_id}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Upload failed', 'details': str(e)}).encode('utf-8'))
            return

        # Admin: Bulk upload customers (JSON list or CSV)
        if path == '/api/admin/customers/upload':
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
            session = validate_session(token) if token else None
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return

            try:
                content_type = (self.headers.get('Content-Type') or '').lower()
                actor = (session or {}).get('username') if session else 'admin'
                created = 0
                errors: list[Dict[str, Any]] = []

                rows: list[Dict[str, Any]] = []
                if 'text/csv' in content_type:
                    reader = csv.DictReader(io.StringIO(body or ''))
                    rows = [r for r in reader]
                else:
                    parsed = json.loads(body or '[]')
                    if isinstance(parsed, dict) and 'items' in parsed:
                        parsed = parsed['items']
                    if not isinstance(parsed, list):
                        raise ValueError("Expected JSON list")
                    rows = [dict(r) for r in parsed]

                if USE_DATABASE and database_enabled:
                    from database.manager import DatabaseManager
                    from database.models import Customer
                    with DatabaseManager() as db:
                        for i, r in enumerate(rows):
                            try:
                                email = str(r.get('email') or '').strip().lower()
                                name = str(r.get('name') or '').strip()
                                if not email or not name:
                                    raise ValueError("name and email required")
                                cust_id = str(r.get('id') or '').strip() or generate_customer_id()
                                cust = Customer(
                                    id=cust_id,
                                    name=name,
                                    email=email,
                                    phone=str(r.get('phone') or '').strip() or None,
                                    dob=str(r.get('dob') or '').strip() or None,
                                    address=str(r.get('address') or '').strip() or None,
                                    city=str(r.get('city') or '').strip() or None,
                                    state=str(r.get('state') or '').strip() or None,
                                    zip=str(r.get('zip') or '').strip() or None,
                                    occupation=str(r.get('occupation') or '').strip() or None,
                                )
                                # DatabaseManager keeps a private session; access it directly for bulk insert.
                                db._ensure_session().add(cust)  # type: ignore[attr-defined]
                                created += 1
                            except Exception as e:
                                errors.append({"row": i, "error": str(e)})

                    if audit:
                        try:
                            audit.log(actor, 'upload', 'customers', 'bulk', {'created': created, 'errors': len(errors)})
                        except Exception:
                            pass

                    self._set_json_headers(201)
                    self.wfile.write(json.dumps({'success': True, 'created': created, 'errors': errors}).encode('utf-8'))
                    return

                with STATE_LOCK:
                    for i, r in enumerate(rows):
                        try:
                            email = str(r.get('email') or '').strip().lower()
                            name = str(r.get('name') or '').strip()
                            if not email or not name:
                                raise ValueError("name and email required")
                            cust_id = str(r.get('id') or '').strip() or generate_customer_id()
                            CUSTOMERS[cust_id] = {
                                'id': cust_id,
                                'name': name,
                                'email': email,
                                'phone': str(r.get('phone') or '').strip(),
                                'dob': str(r.get('dob') or '').strip(),
                                'created_date': datetime.now().isoformat()
                            }
                            created += 1
                        except Exception as e:
                            errors.append({"row": i, "error": str(e)})

                if audit:
                    try:
                        audit.log(actor, 'upload', 'customers', 'bulk', {'created': created, 'errors': len(errors)})
                    except Exception:
                        pass

                self._set_json_headers(201)
                self.wfile.write(json.dumps({'success': True, 'created': created, 'errors': errors}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Upload failed', 'details': str(e)}).encode('utf-8'))
            return

        # Admin: token registry upsert (enable crypto/NFT/index allow-list)
        if path == '/api/admin/token-registry':
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
            session = validate_session(token) if token else None
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return

            try:
                data = json.loads(body or '{}')
                symbol = str(data.get('symbol') or '').strip().upper()
                name = str(data.get('name') or symbol).strip()
                asset_type = str(data.get('asset_type') or 'currency').strip().lower()
                chain = str(data.get('chain') or '').strip() or None
                contract_address = str(data.get('contract_address') or '').strip() or None
                decimals = data.get('decimals')
                enabled = bool(data.get('enabled', True))
                actor = (session or {}).get('username') if session else 'admin'

                if not symbol:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'symbol required'}).encode('utf-8'))
                    return

                entry_id = f"TK-{symbol}"
                meta = data.get('metadata')
                meta_json = json.dumps(meta) if isinstance(meta, (dict, list)) else (str(meta) if meta else None)

                if USE_DATABASE and database_enabled:
                    from database.manager import DatabaseManager
                    from database.models import TokenRegistry
                    with DatabaseManager() as db:
                        existing = db.tokens.get_by_symbol(symbol)
                        if existing:
                            existing.name = name
                            existing.asset_type = asset_type
                            existing.chain = chain
                            existing.contract_address = contract_address
                            existing.decimals = int(decimals) if decimals is not None else None
                            existing.enabled = enabled
                            existing.metadata = meta_json
                        else:
                            row = TokenRegistry(
                                id=entry_id,
                                symbol=symbol,
                                name=name,
                                asset_type=asset_type,
                                chain=chain,
                                contract_address=contract_address,
                                decimals=int(decimals) if decimals is not None else None,
                                enabled=enabled,
                                metadata=meta_json,
                                classification="internal",
                                created_by=actor,
                            )
                            db.tokens.create(row)

                    if audit:
                        try:
                            audit.log(actor, 'upsert', 'token_registry', entry_id, {'symbol': symbol, 'asset_type': asset_type, 'enabled': enabled})
                        except Exception:
                            pass

                    self._set_json_headers(201)
                    self.wfile.write(json.dumps({'success': True, 'id': entry_id}).encode('utf-8'))
                    return

                with STATE_LOCK:
                    TOKEN_REGISTRY[entry_id] = {
                        "id": entry_id,
                        "symbol": symbol,
                        "name": name,
                        "asset_type": asset_type,
                        "chain": chain,
                        "contract_address": contract_address,
                        "decimals": decimals,
                        "enabled": enabled,
                        "metadata": meta_json,
                        "classification": "internal",
                        "created_by": actor,
                        "created_date": datetime.now().isoformat(),
                    }

                if audit:
                    try:
                        audit.log(actor, 'upsert', 'token_registry', entry_id, {'symbol': symbol, 'asset_type': asset_type, 'enabled': enabled})
                    except Exception:
                        pass

                self._set_json_headers(201)
                self.wfile.write(json.dumps({'success': True, 'id': entry_id}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Upsert failed', 'details': str(e)}).encode('utf-8'))
            return

        # Admin: Seed production data (works with database)
        if path == '/api/admin/seed-data':
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
            session = validate_session(token) if token else None
            
            # Allow seeding without auth for initial setup (check for secret key)
            data = {}
            try:
                data = json.loads(body or '{}')
            except:
                pass
            
            seed_key = data.get('seed_key', '')
            is_authorized = require_role(session, ['admin']) or seed_key == 'phins-seed-2024'
            
            if not is_authorized:
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access or seed_key required.'}).encode('utf-8'))
                return
            
            try:
                if USE_DATABASE and database_enabled:
                    from database.seeds import seed_default_users, seed_sample_data
                    from database import init_database
                    
                    # Initialize database schema
                    init_database()
                    
                    # Seed users
                    try:
                        seed_default_users()
                    except Exception as e:
                        print(f"User seeding note: {e}")
                    
                    # Seed sample data
                    try:
                        seed_sample_data()
                    except Exception as e:
                        print(f"Sample data seeding note: {e}")
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True,
                        'message': 'Database seeded successfully',
                        'accounts': {
                            'admin': {'username': 'admin', 'password': 'admin123'},
                            'customer': {'email': 'asaf@assurance.co.il', 'password': 'Assurance2024!'}
                        }
                    }).encode('utf-8'))
                else:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Database mode not enabled'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': f'Seeding failed: {str(e)}'}).encode('utf-8'))
            return

        # Admin: reset demo dataset (in-memory only)
        if path == '/api/admin/reset-demo-data':
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
            session = validate_session(token) if token else None
            if not require_role(session, ['admin']):
                self._set_json_headers(403)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Admin access required.'}).encode('utf-8'))
                return

            try:
                data = json.loads(body or '{}')
                confirm = str(data.get('confirm') or '').lower() in ('true', '1', 'yes')
                if not confirm:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'confirm=true required'}).encode('utf-8'))
                    return

                if USE_DATABASE and database_enabled:
                    self._set_json_headers(501)
                    self.wfile.write(json.dumps({'error': 'DB reset is disabled by default. Use init_database(drop_existing=True) offline.'}).encode('utf-8'))
                    return

                with STATE_LOCK:
                    POLICIES.clear()
                    CLAIMS.clear()
                    CUSTOMERS.clear()
                    UNDERWRITING_APPLICATIONS.clear()
                    BILLING.clear()
                    ACTUARIAL_TABLES.clear()
                    TOKEN_REGISTRY.clear()

                    # Seed a minimal working dataset
                    cust_id = generate_customer_id()
                    CUSTOMERS[cust_id] = {'id': cust_id, 'name': 'Demo Customer', 'email': 'demo.customer@phins.ai', 'phone': '555-0100', 'dob': '1990-01-01', 'created_date': datetime.now().isoformat()}
                    pol_id = generate_policy_id()
                    prem = calculate_premium({'type': 'life', 'age': 35, 'coverage_amount': 250000, 'risk_score': 'medium'})
                    POLICIES[pol_id] = {
                        'id': pol_id,
                        'customer_id': cust_id,
                        'type': 'life',
                        'coverage_amount': 250000,
                        'annual_premium': prem['annual'],
                        'monthly_premium': prem['monthly'],
                        'status': 'active',
                        'risk_score': 'medium',
                        'created_date': datetime.now().isoformat(),
                        'start_date': datetime.now().isoformat(),
                    }
                    uw_id = f"UW-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000,9999)}"
                    UNDERWRITING_APPLICATIONS[uw_id] = {
                        'id': uw_id,
                        'policy_id': pol_id,
                        'customer_id': cust_id,
                        'status': 'approved',
                        'risk_assessment': 'medium',
                        'submitted_date': datetime.now().isoformat(),
                        'decision_date': datetime.now().isoformat(),
                    }
                    bill_id = f"BILL-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000,9999)}"
                    BILLING[bill_id] = {'id': bill_id, 'policy_id': pol_id, 'amount': prem['monthly'], 'amount_paid': 0.0, 'status': 'outstanding', 'created_date': datetime.now().isoformat(), 'due_date': (datetime.now() + timedelta(days=30)).isoformat()}

                    # Seed a basic token registry
                    TOKEN_REGISTRY['TK-BTC'] = {'id': 'TK-BTC', 'symbol': 'BTC', 'name': 'Bitcoin', 'asset_type': 'currency', 'enabled': True, 'classification': 'internal', 'created_by': 'system', 'created_date': datetime.now().isoformat()}
                    TOKEN_REGISTRY['TK-ETH'] = {'id': 'TK-ETH', 'symbol': 'ETH', 'name': 'Ethereum', 'asset_type': 'currency', 'enabled': True, 'classification': 'internal', 'created_by': 'system', 'created_date': datetime.now().isoformat()}

                self._set_json_headers(200)
                self.wfile.write(json.dumps({'success': True}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Reset failed', 'details': str(e)}).encode('utf-8'))
            return
        
        # Create Policy Endpoint
        if path == '/api/policies/create':
            try:
                data = json.loads(body)
                
                # Validate and sanitize inputs
                customer_name = sanitize_input(data.get('customer_name', ''), 100)
                customer_email = sanitize_input(data.get('customer_email', ''), 254)
                customer_phone = sanitize_input(data.get('customer_phone', ''), 20)
                
                if not customer_name:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Customer name is required'}).encode('utf-8'))
                    return
                
                if customer_email and not validate_email(customer_email):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid email format'}).encode('utf-8'))
                    return
                
                coverage_amount = data.get('coverage_amount', 100000)
                if not validate_amount(coverage_amount):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid coverage amount'}).encode('utf-8'))
                    return
                
                policy_id = generate_policy_id()
                customer_id = data.get('customer_id') or generate_customer_id()
                
                # Check if customer with this email already exists
                existing_customer = None
                if customer_email and USE_DATABASE:
                    try:
                        from database.manager import DatabaseManager
                        with DatabaseManager() as db:
                            existing_customer = db.customers.get_by_email(customer_email)
                            if existing_customer:
                                customer_id = existing_customer.id
                                # Ensure customer is in CUSTOMERS dict for response
                                if customer_id not in CUSTOMERS:
                                    CUSTOMERS[customer_id] = {
                                        'id': customer_id,
                                        'name': existing_customer.name if hasattr(existing_customer, 'name') else customer_name,
                                        'email': existing_customer.email if hasattr(existing_customer, 'email') else customer_email,
                                        'phone': existing_customer.phone if hasattr(existing_customer, 'phone') else customer_phone,
                                        'created_date': existing_customer.created_at.isoformat() if hasattr(existing_customer, 'created_at') and existing_customer.created_at else datetime.now().isoformat()
                                    }
                    except Exception as e:
                        print(f"Error checking existing customer: {e}")
                
                # Initialize temp_password to None (will be set if new customer is created)
                temp_password = None
                
                # Create customer if new (and no existing customer with same email)
                if not existing_customer and customer_id not in CUSTOMERS:
                    try:
                        CUSTOMERS[customer_id] = {
                            'id': customer_id,
                            'name': customer_name,
                            'email': customer_email,
                            'phone': customer_phone,
                            'dob': data.get('customer_dob', ''),
                            'created_date': datetime.now().isoformat()
                        }
                        # Provision portal login for the customer
                        cust_email = customer_email or f"{customer_id.lower()}@example.com"
                        temp_password = f"pw-{uuid.uuid4().hex[:10]}"
                        
                        # Hash the password for security
                        pwd_hash = hash_password(temp_password)
                        USERS[cust_email] = {
                            'hash': pwd_hash['hash'],
                            'salt': pwd_hash['salt'],
                            'role': 'customer',
                            'name': customer_name or customer_id,
                            'customer_id': customer_id
                        }
                    except Exception as e:
                        print(f"Error creating customer: {e}")
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'Failed to create customer account'}).encode('utf-8'))
                        return
                
                # Create underwriting application
                uw_id = f"UW-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
                
                # Process payment info (tokenize card - never store full number)
                payment_info = data.get('payment', {})
                payment_token = None
                card_last4 = None
                card_type = None
                billing_frequency = 'monthly'
                auto_pay = False
                
                if payment_info:
                    card_number = payment_info.get('card_number', '')
                    if card_number:
                        # Validate card using SecurityValidator
                        try:
                            from billing_engine import SecurityValidator
                            validation_result = SecurityValidator.validate_card_number(card_number)
                            if validation_result.get('valid'):
                                # Create secure token (hash the card)
                                card_last4 = card_number[-4:]
                                card_type = validation_result.get('card_type', 'unknown')
                                payment_token = SecurityValidator.hash_sensitive_data(card_number)
                            else:
                                # Log validation failure but don't block application
                                print(f"Card validation warning: {validation_result.get('errors', [])}")
                        except Exception as e:
                            print(f"Payment processing error: {e}")
                    
                    billing_frequency = payment_info.get('billing_frequency', 'monthly')
                    auto_pay = payment_info.get('auto_pay', False)
                
                # Process health wallet setup
                health_wallet_info = data.get('health_wallet', {})
                health_wallet_enabled = health_wallet_info.get('enabled', False)
                monthly_deposit = health_wallet_info.get('monthly_deposit', 0)
                
                # Initialize health wallet if enabled
                if health_wallet_enabled:
                    HEALTH_WALLETS[customer_id] = {
                        'customer_id': customer_id,
                        'balance': 0,  # Start with zero, will deposit after approval
                        'monthly_deposit': monthly_deposit,
                        'transactions': [],
                        'created_at': datetime.now().isoformat(),
                        'status': 'pending_activation'
                    }
                
                # Process PHINS Unified Contract allocation
                phins_allocation = data.get('phins_allocation', {})
                coverage_years = data.get('coverage_years', 20)
                
                if phins_allocation:
                    # Store customer allocation preferences
                    CUSTOMER_ALLOCATIONS[customer_id] = {
                        'customer_id': customer_id,
                        'protection_pct': phins_allocation.get('protection_pct', 25),
                        'savings_pct': phins_allocation.get('savings_pct', 75),
                        'distribution': phins_allocation.get('distribution', {
                            'wallet_pct': 15,
                            'investment_pct': 60,
                            'algo_trading_pct': 25
                        }),
                        'coverage_years': coverage_years,
                        'created_at': datetime.now().isoformat()
                    }
                    
                    # Initialize savings pipeline account if enabled
                    if savings_pipeline_enabled and savings_pipeline_service:
                        try:
                            # Create pipeline account with customer preferences
                            dist = phins_allocation.get('distribution', {})
                            from services.savings_pipeline_service import AllocationStrategy, RiskLevel
                            
                            # Determine risk level based on allocation
                            protection_pct = phins_allocation.get('protection_pct', 25)
                            if protection_pct >= 40:
                                risk_level = RiskLevel.CONSERVATIVE
                            elif protection_pct >= 30:
                                risk_level = RiskLevel.MODERATE
                            else:
                                risk_level = RiskLevel.AGGRESSIVE
                            
                            # Create pipeline account
                            account = savings_pipeline_service.get_or_create_account(customer_id)
                            account.risk_level = risk_level
                            account.allocation_config.wallet_pct = dist.get('wallet_pct', 15)
                            account.allocation_config.investment_pct = dist.get('investment_pct', 60)
                            account.allocation_config.algo_trading_pct = dist.get('algo_trading_pct', 25)
                            
                            # Record on NFT ledger
                            if generate_nft_token:
                                nft = generate_nft_token(
                                    owner_id=customer_id,
                                    asset_type="phins_contract",
                                    metadata={
                                        'contract_type': 'phins_unified',
                                        'coverage_amount': data.get('coverage_amount', 100000),
                                        'coverage_years': coverage_years,
                                        'allocation': phins_allocation,
                                        'created_at': datetime.now().isoformat()
                                    }
                                )
                            
                            # Record transaction
                            if record_transaction:
                                record_transaction(
                                    customer_id=customer_id,
                                    tx_type="phins_contract_created",
                                    amount=0,
                                    description=f"PHINS Unified Contract created: ${data.get('coverage_amount', 100000):,.0f} coverage, {coverage_years} years",
                                    metadata={
                                        'policy_id': policy_id,
                                        'allocation': phins_allocation
                                    }
                                )
                        except Exception as e:
                            print(f"Pipeline setup note: {e}")
                    
                    # Initialize investment account
                    if customer_id not in INVESTMENT_ACCOUNTS:
                        INVESTMENT_ACCOUNTS[customer_id] = {
                            'customer_id': customer_id,
                            'balance': 0,
                            'index_balance': 0,
                            'bonds_balance': 0,
                            'crypto_balance': 0,
                            'deposits': [],
                            'created_at': datetime.now().isoformat()
                        }
                
                UNDERWRITING_APPLICATIONS[uw_id] = {
                    'id': uw_id,
                    'policy_id': policy_id,
                    'customer_id': customer_id,
                    'customer_name': customer_name,  # Include customer name for dashboard display
                    'customer_email': customer_email,  # Include email for reference
                    'policy_type': data.get('type', 'life'),  # Include policy type
                    'coverage_amount': data.get('coverage_amount', 100000),  # Include coverage amount
                    'age': data.get('age', 0),  # Include age
                    'status': 'pending',
                    'risk_score': data.get('risk_score', 'medium'),  # Use risk_score (matches dashboard)
                    'risk_assessment': data.get('risk_score', 'medium'),
                    'questionnaire_responses': data.get('questionnaire', {}),
                    'medical_exam_required': data.get('medical_exam_required', False),
                    'submitted_date': datetime.now().isoformat(),
                    'created_date': datetime.now().isoformat(),
                    # Payment and billing info (stored securely)
                    'payment_setup': {
                        'card_last4': card_last4,
                        'card_type': card_type,
                        'cardholder_name': payment_info.get('cardholder_name', ''),
                        'expiry_month': payment_info.get('expiry_month', ''),
                        'expiry_year': payment_info.get('expiry_year', ''),
                        'billing_frequency': billing_frequency,
                        'auto_pay': auto_pay,
                        'payment_token': payment_token  # Hashed token, not raw card
                    },
                    'health_wallet': {
                        'enabled': health_wallet_enabled,
                        'monthly_deposit': monthly_deposit
                    }
                }
                
                # Calculate premium
                premium_data = calculate_premium(data)
                
                # Create policy
                policy = {
                    'id': policy_id,
                    'customer_id': customer_id,
                    'type': data.get('type', 'life'),
                    'coverage_amount': data.get('coverage_amount', 100000),
                    'annual_premium': premium_data['annual'],
                    'monthly_premium': premium_data['monthly'],
                    'status': 'pending_underwriting',
                    'underwriting_id': uw_id,
                    'risk_score': data.get('risk_score', 'medium'),
                    'start_date': data.get('start_date', datetime.now().isoformat()),
                    'end_date': data.get('end_date', (datetime.now() + timedelta(days=365)).isoformat()),
                    'created_date': datetime.now().isoformat(),
                    # Billing configuration (from application Step 4)
                    'billing': {
                        'frequency': billing_frequency,
                        'auto_pay': auto_pay,
                        'payment_method': {
                            'type': 'card',
                            'card_last4': card_last4,
                            'card_type': card_type
                        } if card_last4 else None,
                        'next_billing_date': (datetime.now() + timedelta(days=30)).isoformat()
                    },
                    'health_wallet': {
                        'enabled': health_wallet_enabled,
                        'monthly_deposit': monthly_deposit
                    }
                }
                
                POLICIES[policy_id] = policy
                if audit:
                    actor = session.get('username') if 'session' in locals() and session else 'system'
                    try:
                        audit.log(actor, 'create', 'policy', policy_id, {'customer_id': customer_id, 'coverage_amount': policy.get('coverage_amount')})
                    except Exception:
                        pass
                
                self._set_json_headers(201)
                
                # Build response - safely get customer data
                customer_data = CUSTOMERS.get(customer_id, {
                    'id': customer_id,
                    'name': customer_name,
                    'email': customer_email,
                    'phone': customer_phone
                })
                login_username = customer_data.get('email') or f"{customer_id.lower()}@example.com"
                
                response_data = {
                    'policy': policy,
                    'underwriting': UNDERWRITING_APPLICATIONS[uw_id],
                    'customer': customer_data
                }
                
                # Only include provisioned_login if this is a new customer with temp password
                if temp_password:
                    response_data['provisioned_login'] = {
                        'username': login_username,
                        'password': temp_password  # Return plain password for first login
                    }
                else:
                    # Existing customer - indicate they should use existing credentials
                    response_data['provisioned_login'] = {
                        'username': login_username,
                        'existing_account': True,
                        'message': 'Use your existing password to login'
                    }
                
                self.wfile.write(json.dumps(response_data).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return

        # Create Policy (Safe Minimal) Endpoint
        if path == '/api/policies/create_simple':
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id') or generate_customer_id()
                policy_type = data.get('type', 'life')
                coverage_amount = data.get('coverage_amount', 100000)
                if not validate_amount(coverage_amount):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid coverage amount'}).encode('utf-8'))
                    return
                # Upsert minimal customer record if needed
                if customer_id not in CUSTOMERS:
                    CUSTOMERS[customer_id] = {
                        'id': customer_id,
                        'name': data.get('customer_name') or customer_id,
                        'email': data.get('customer_email', ''),
                        'created_date': datetime.now().isoformat()
                    }
                # Generate IDs
                policy_id = generate_policy_id()
                uw_id = f"UW-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
                # Underwriting minimal record
                UNDERWRITING_APPLICATIONS[uw_id] = {
                    'id': uw_id,
                    'policy_id': policy_id,
                    'customer_id': customer_id,
                    'customer_name': data.get('customer_name') or customer_id,
                    'customer_email': data.get('customer_email', ''),
                    'policy_type': policy_type,
                    'coverage_amount': coverage_amount,
                    'age': data.get('age', 30),
                    'status': 'pending',
                    'risk_score': data.get('risk_score', 'medium'),
                    'risk_assessment': data.get('risk_score', 'medium'),
                    'medical_exam_required': data.get('medical_exam_required', False),
                    'submitted_date': datetime.now().isoformat(),
                    'created_date': datetime.now().isoformat()
                }
                # Premium calc
                premium_data = calculate_premium({
                    'type': policy_type,
                    'coverage_amount': coverage_amount,
                    'age': data.get('age', 30),
                    'risk_score': data.get('risk_score', 'medium')
                })
                # Create policy
                policy = {
                    'id': policy_id,
                    'customer_id': customer_id,
                    'type': policy_type,
                    'coverage_amount': coverage_amount,
                    'annual_premium': premium_data['annual'],
                    'monthly_premium': premium_data['monthly'],
                    'status': 'pending_underwriting',
                    'underwriting_id': uw_id,
                    'risk_score': data.get('risk_score', 'medium'),
                    'start_date': datetime.now().isoformat(),
                    'end_date': (datetime.now() + timedelta(days=365)).isoformat(),
                    'created_date': datetime.now().isoformat()
                }
                POLICIES[policy_id] = policy
                if audit:
                    actor = 'system'
                    try:
                        audit.log(actor, 'create', 'policy', policy_id, {'customer_id': customer_id, 'safe': True})
                    except Exception:
                        pass
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'policy': policy, 'underwriting': UNDERWRITING_APPLICATIONS[uw_id], 'customer': CUSTOMERS[customer_id]}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid request', 'details': str(e)}).encode('utf-8'))
            return
        
        # Approve Underwriting Endpoint - Full Pipeline Validation
        if path == '/api/underwriting/approve':
            try:
                data = json.loads(body)
                uw_id = data.get('id')
                app = UNDERWRITING_APPLICATIONS.get(uw_id)
                
                if not app:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Application not found'}).encode('utf-8'))
                    return
                
                # VALIDATION 1: Check application status
                if app.get('status') == 'approved':
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Application already approved'}).encode('utf-8'))
                    return
                
                if app.get('status') == 'rejected':
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Cannot approve a rejected application'}).encode('utf-8'))
                    return
                
                # VALIDATION 2: Check customer exists
                customer_id = app.get('customer_id')
                if customer_id and customer_id not in CUSTOMERS:
                    # Auto-create customer record if missing
                    CUSTOMERS[customer_id] = {
                        'id': customer_id,
                        'name': app.get('customer_name', 'Unknown'),
                        'email': app.get('customer_email', ''),
                        'created_date': datetime.now().isoformat()
                    }
                
                # VALIDATION 3: Check policy exists
                policy_id = app.get('policy_id')
                if not policy_id or policy_id not in POLICIES:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Policy not found for this application'}).encode('utf-8'))
                    return
                
                policy = POLICIES[policy_id]
                
                # VALIDATION 4: Check policy not already active
                if policy.get('status') == 'active':
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Policy is already active'}).encode('utf-8'))
                    return
                
                # All validations passed - proceed with approval
                now = datetime.now()
                
                # Update application status
                app['status'] = 'approved'
                app['decision_date'] = now.isoformat()
                app['approved_by'] = data.get('approved_by', 'admin')
                app['approval_notes'] = data.get('notes', '')
                
                # PIPELINE STEP: Activate policy
                policy['status'] = 'active'
                policy['approval_date'] = now.isoformat()
                policy['effective_date'] = now.isoformat()
                policy['approved_by'] = data.get('approved_by', 'admin')
                
                # PIPELINE STEP: Generate billing record
                bill_id = f"BILL-{now.strftime('%Y%m%d%H%M%S')}-{random.randint(1000,9999)}"
                monthly_premium = policy.get('monthly_premium', 0) or policy.get('annual_premium', 0) / 12
                
                # Get billing configuration from application
                payment_setup = app.get('payment_setup', {})
                billing_frequency = payment_setup.get('billing_frequency', 'monthly')
                auto_pay = payment_setup.get('auto_pay', False)
                
                # Calculate billing amount based on frequency
                if billing_frequency == 'quarterly':
                    billing_amount = monthly_premium * 3 * 0.97  # 3% discount
                    due_days = 90
                elif billing_frequency == 'annual':
                    billing_amount = monthly_premium * 12 * 0.90  # 10% discount
                    due_days = 365
                else:
                    billing_amount = monthly_premium
                    due_days = 30
                
                bill = {
                    'id': bill_id,
                    'policy_id': policy_id,
                    'customer_id': customer_id,
                    'customer_name': app.get('customer_name', ''),
                    'customer_email': app.get('customer_email', ''),
                    'amount': round(float(billing_amount), 2),
                    'amount_paid': 0.0,
                    'status': 'outstanding',
                    'billing_frequency': billing_frequency,
                    'auto_pay': auto_pay,
                    'payment_method': {
                        'type': 'card',
                        'card_last4': payment_setup.get('card_last4'),
                        'card_type': payment_setup.get('card_type')
                    } if payment_setup.get('card_last4') else None,
                    'due_date': (now + timedelta(days=due_days)).isoformat(),
                    'billing_period_start': now.isoformat(),
                    'billing_period_end': (now + timedelta(days=due_days)).isoformat(),
                    'created_date': now.isoformat(),
                    'updated_date': now.isoformat(),
                    'description': f"Premium for policy {policy_id} ({billing_frequency})"
                }
                BILLING[bill_id] = bill
                
                # PIPELINE STEP: Activate health wallet if enabled
                health_wallet_info = app.get('health_wallet', {})
                if health_wallet_info.get('enabled') and customer_id:
                    if customer_id not in HEALTH_WALLETS:
                        HEALTH_WALLETS[customer_id] = {
                            'customer_id': customer_id,
                            'balance': 0,
                            'monthly_deposit': health_wallet_info.get('monthly_deposit', 0),
                            'transactions': [],
                            'created_at': now.isoformat()
                        }
                    HEALTH_WALLETS[customer_id]['status'] = 'active'
                    
                    # Process initial deposit if monthly_deposit > 0
                    monthly_deposit = health_wallet_info.get('monthly_deposit', 0)
                    if monthly_deposit > 0:
                        HEALTH_WALLETS[customer_id]['balance'] = monthly_deposit
                        HEALTH_WALLETS[customer_id]['transactions'].append({
                            'id': f"TXN-{now.strftime('%Y%m%d%H%M%S')}",
                            'type': 'initial_deposit',
                            'amount': monthly_deposit,
                            'description': 'Initial health wallet deposit upon policy activation',
                            'timestamp': now.isoformat(),
                            'balance_after': monthly_deposit
                        })
                
                # ========== LEDGER RECORDING FOR APPROVAL ==========
                # Record policy approval on TRANSACTION_LEDGER
                approval_tx = record_transaction(
                    customer_id=customer_id,
                    tx_type='policy_approved',
                    amount=policy.get('coverage_amount', 0),
                    description=f"Policy {policy_id} approved and activated. Coverage: ${policy.get('coverage_amount', 0):,.0f}",
                    metadata={
                        'policy_id': policy_id,
                        'underwriting_id': uw_id,
                        'coverage_amount': policy.get('coverage_amount', 0),
                        'annual_premium': policy.get('annual_premium', 0),
                        'approved_by': data.get('approved_by', 'admin'),
                        'billing_frequency': billing_frequency,
                        'bill_id': bill_id
                    }
                )
                
                # Record billing creation on ledger
                billing_tx = record_transaction(
                    customer_id=customer_id,
                    tx_type='billing_created',
                    amount=bill['amount'],
                    description=f"Billing record created for policy {policy_id}. Amount: ${bill['amount']:.2f}",
                    metadata={
                        'bill_id': bill_id,
                        'policy_id': policy_id,
                        'billing_frequency': billing_frequency,
                        'due_date': bill['due_date'],
                        'auto_pay': auto_pay
                    }
                )
                
                # Record health wallet activation if enabled
                if health_wallet_info.get('enabled') and monthly_deposit > 0:
                    wallet_tx = record_transaction(
                        customer_id=customer_id,
                        tx_type='health_wallet_activated',
                        amount=monthly_deposit,
                        description=f"Health wallet activated with initial deposit of ${monthly_deposit:.2f}",
                        metadata={
                            'wallet_balance': HEALTH_WALLETS[customer_id]['balance'],
                            'monthly_deposit': monthly_deposit,
                            'policy_id': policy_id
                        }
                    )
                
                # Initialize savings pipeline account with PHINS allocation
                if savings_pipeline_enabled and savings_pipeline_service:
                    try:
                        # Check if customer has allocation preferences from application
                        phins_allocation = app.get('phins_allocation') or CUSTOMER_ALLOCATIONS.get(customer_id)
                        if phins_allocation:
                            from services.savings_pipeline_service import RiskLevel
                            
                            protection_pct = phins_allocation.get('protection_pct', 25)
                            if protection_pct >= 40:
                                risk_level = RiskLevel.CONSERVATIVE
                            elif protection_pct >= 30:
                                risk_level = RiskLevel.MODERATE
                            else:
                                risk_level = RiskLevel.AGGRESSIVE
                            
                            # Initialize pipeline account
                            pipeline_account = savings_pipeline_service.get_or_create_account(customer_id)
                            pipeline_account.risk_level = risk_level
                            
                            dist = phins_allocation.get('distribution', {})
                            pipeline_account.allocation_config.wallet_pct = dist.get('wallet_pct', 15)
                            pipeline_account.allocation_config.investment_pct = dist.get('investment_pct', 60)
                            pipeline_account.allocation_config.algo_trading_pct = dist.get('algo_trading_pct', 25)
                            
                            # Record pipeline initialization
                            record_transaction(
                                customer_id=customer_id,
                                tx_type='pipeline_initialized',
                                amount=0,
                                description=f"AI/BI Savings Pipeline initialized for customer",
                                metadata={
                                    'policy_id': policy_id,
                                    'risk_level': str(risk_level),
                                    'allocation': phins_allocation
                                }
                            )
                    except Exception as pipeline_err:
                        print(f"Pipeline initialization note: {pipeline_err}")
                
                # Audit logging
                if audit:
                    try:
                        audit.log('system', 'create', 'bill', bill_id, {
                            'policy_id': policy_id,
                            'amount': bill['amount'],
                            'trigger': 'policy_approval'
                        })
                        actor = data.get('approved_by', 'admin')
                        audit.log(actor, 'approve', 'underwriting', uw_id, {
                            'policy_id': policy_id,
                            'bill_id': bill_id,
                            'policy_status': 'active',
                            'billing_frequency': billing_frequency
                        })
                    except Exception:
                        pass
                
                # Build comprehensive response
                response = {
                    'success': True,
                    'message': 'Policy approved and activated. Full pipeline completed.',
                    'pipeline_completed': {
                        'underwriting': {'status': 'approved', 'id': uw_id},
                        'policy': {'status': 'active', 'id': policy_id},
                        'billing': {'status': 'generated', 'id': bill_id, 'amount': bill['amount']},
                        'health_wallet': {'status': 'active' if health_wallet_info.get('enabled') else 'not_enabled'}
                    },
                    'application': app,
                    'policy': policy,
                    'bill': bill,
                    'validation': {
                        'customer_verified': True,
                        'policy_activated': True,
                        'billing_generated': True,
                        'health_wallet_activated': health_wallet_info.get('enabled', False)
                    }
                }
                
                self._set_json_headers()
                self.wfile.write(json.dumps(response).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Reject Underwriting Endpoint
        if path == '/api/underwriting/reject':
            try:
                data = json.loads(body)
                uw_id = data.get('id')
                app = UNDERWRITING_APPLICATIONS.get(uw_id)
                
                if app:
                    app['status'] = 'rejected'
                    app['decision_date'] = datetime.now().isoformat()
                    app['rejection_reason'] = data.get('reason', 'Risk assessment failed')
                    
                    # Update policy status
                    policy_id = app.get('policy_id')
                    if policy_id and policy_id in POLICIES:
                        POLICIES[policy_id]['status'] = 'rejected'
                    
                    # Record in transaction ledger for audit trail
                    record_transaction(
                        customer_id=app.get('customer_id', 'unknown'),
                        tx_type='underwriting_rejected',
                        amount=0,
                        description=f"Application {uw_id} rejected - {data.get('reason', 'Risk assessment failed')}",
                        metadata={
                            'uw_id': uw_id,
                            'policy_id': policy_id,
                            'reason': data.get('reason', 'Risk assessment failed'),
                            'rejected_by': data.get('rejected_by', 'admin')
                        }
                    )
                    
                    if audit:
                        actor = data.get('rejected_by', 'admin')
                        try:
                            audit.log(actor, 'reject', 'underwriting', uw_id, {'policy_id': policy_id, 'reason': app['rejection_reason']})
                        except Exception:
                            pass
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'success': True, 'application': app}).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Application not found'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Refer Underwriting Endpoint - Move to Manual Review
        if path == '/api/underwriting/refer':
            try:
                data = json.loads(body)
                uw_id = data.get('id')
                app = UNDERWRITING_APPLICATIONS.get(uw_id)
                
                if app:
                    app['status'] = 'referred'
                    app['decision_date'] = datetime.now().isoformat()
                    app['referral_reason'] = data.get('notes', 'Requires manual review')
                    app['referred_by'] = data.get('approved_by', 'admin')
                    app['referral_priority'] = data.get('priority', 'normal')
                    
                    # Update policy status to pending_manual_review
                    policy_id = app.get('policy_id')
                    if policy_id and policy_id in POLICIES:
                        POLICIES[policy_id]['status'] = 'pending_manual_review'
                    
                    # Record in transaction ledger
                    record_transaction(
                        customer_id=app.get('customer_id', 'unknown'),
                        tx_type='underwriting_referred',
                        amount=0,
                        description=f"Application {uw_id} referred for manual review",
                        metadata={
                            'uw_id': uw_id,
                            'policy_id': policy_id,
                            'reason': data.get('notes', 'Requires manual review'),
                            'referred_by': data.get('approved_by', 'admin'),
                            'priority': app['referral_priority']
                        }
                    )
                    
                    if audit:
                        actor = data.get('approved_by', 'admin')
                        try:
                            audit.log(actor, 'refer', 'underwriting', uw_id, {
                                'policy_id': policy_id, 
                                'reason': app['referral_reason'],
                                'priority': app['referral_priority']
                            })
                        except Exception:
                            pass
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True, 
                        'application': app,
                        'message': 'Application referred for manual review',
                        'next_stage': 'manual_review'
                    }).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Application not found'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Create Claim Endpoint
        if path == '/api/claims/create':
            # Resolve session (customers must be authenticated to create claims)
            auth_header = self.headers.get('Authorization', '')
            token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
            session = validate_session(token) if token else None

            if not session:
                self._set_json_headers(401)
                self.wfile.write(json.dumps({'error': 'Unauthorized. Please login.'}).encode('utf-8'))
                return

            user = get_session_user(session) or {}
            role = (user.get('role') or '').lower()
            session_customer_id = user.get('customer_id') or session.get('customer_id')

            try:
                data = json.loads(body)
                claim_id = generate_claim_id()

                # If customer, force customer_id to session and verify policy ownership
                if role == 'customer':
                    if not session_customer_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id unavailable'}).encode('utf-8'))
                        return
                    policy_id = data.get('policy_id')
                    if policy_id and POLICIES.get(policy_id, {}).get('customer_id') != session_customer_id:
                        self._set_json_headers(403)
                        self.wfile.write(json.dumps({'error': 'Forbidden'}).encode('utf-8'))
                        return
                    data['customer_id'] = session_customer_id
                
                claim = {
                    'id': claim_id,
                    'policy_id': data.get('policy_id'),
                    'customer_id': data.get('customer_id'),
                    'type': data.get('type', 'general'),
                    'description': data.get('description', ''),
                    'claimed_amount': float(data.get('claimed_amount', 0)),
                    'status': 'Pending',
                    'filed_date': datetime.now().isoformat(),
                    'created_date': datetime.now().isoformat()
                }
                
                CLAIMS[claim_id] = claim
                
                # Record claim creation on TRANSACTION_LEDGER and NFT_LEDGER
                claim_tx = record_transaction(
                    customer_id=data.get('customer_id', 'unknown'),
                    tx_type='claim_submitted',
                    amount=float(data.get('claimed_amount', 0)),
                    description=f"Claim {claim_id} submitted: {data.get('type', 'general')} - {data.get('description', '')[:50]}",
                    metadata={
                        'claim_id': claim_id,
                        'policy_id': data.get('policy_id'),
                        'claim_type': data.get('type', 'general'),
                        'claimed_amount': float(data.get('claimed_amount', 0)),
                        'description': data.get('description', '')
                    }
                )
                claim['nft_token_id'] = claim_tx.get('nft_token_id')
                claim['ledger_tx_id'] = claim_tx.get('id')  # Fixed: use 'id' not 'tx_id'
                
                if audit:
                    actor = session.get('username') if session else 'system'
                    try:
                        audit.log(actor, 'create', 'claim', claim_id, {'policy_id': claim.get('policy_id'), 'claimed_amount': claim.get('claimed_amount')})
                    except Exception:
                        pass
                
                self._set_json_headers(201)
                self.wfile.write(json.dumps(claim).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Approve Claim Endpoint
        if path == '/api/claims/approve':
            try:
                data = json.loads(body)
                claim_id = data.get('id')
                claim = CLAIMS.get(claim_id)
                
                if claim:
                    approved_amount = float(data.get('approved_amount', claim['claimed_amount']))
                    
                    claim['status'] = 'Approved'
                    claim['approved_amount'] = approved_amount
                    claim['approval_date'] = datetime.now().isoformat()
                    claim['approved_by'] = data.get('approved_by', 'admin')
                    claim['approval_notes'] = data.get('notes', '')
                    claim['next_stage'] = 'payment'  # Pipeline tracking
                    
                    # Persist to database
                    CLAIMS[claim_id] = claim
                    
                    # Record in transaction ledger for audit trail
                    record_transaction(
                        customer_id=claim.get('customer_id', 'unknown'),
                        tx_type='claim_approved',
                        amount=approved_amount,
                        description=f"Claim {claim_id} approved for ${approved_amount:.2f}",
                        metadata={
                            'claim_id': claim_id,
                            'policy_id': claim.get('policy_id'),
                            'claimed_amount': claim.get('claimed_amount'),
                            'approved_amount': approved_amount,
                            'approved_by': data.get('approved_by', 'admin'),
                            'notes': data.get('notes', '')
                        }
                    )
                    
                    if audit:
                        actor = claim.get('approved_by', 'admin')
                        try:
                            audit.log(actor, 'approve', 'claim', claim_id, {'approved_amount': claim['approved_amount']})
                        except Exception:
                            pass
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True, 
                        'claim': claim,
                        'message': 'Claim approved. Ready for payment processing.',
                        'next_stage': 'payment'
                    }).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Claim not found'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Reject Claim Endpoint
        if path == '/api/claims/reject':
            try:
                data = json.loads(body)
                claim_id = data.get('id')
                claim = CLAIMS.get(claim_id)
                
                if claim:
                    rejection_reason = data.get('reason', 'Not covered')
                    
                    claim['status'] = 'Rejected'
                    claim['rejection_date'] = datetime.now().isoformat()
                    claim['rejection_reason'] = rejection_reason
                    claim['rejected_by'] = data.get('rejected_by', 'admin')
                    
                    # Persist to database
                    CLAIMS[claim_id] = claim
                    
                    # Record in transaction ledger
                    record_transaction(
                        customer_id=claim.get('customer_id', 'unknown'),
                        tx_type='claim_rejected',
                        amount=0,
                        description=f"Claim {claim_id} rejected - {rejection_reason}",
                        metadata={
                            'claim_id': claim_id,
                            'policy_id': claim.get('policy_id'),
                            'claimed_amount': claim.get('claimed_amount'),
                            'rejection_reason': rejection_reason,
                            'rejected_by': data.get('rejected_by', 'admin')
                        }
                    )
                    
                    if audit:
                        actor = data.get('rejected_by', 'admin')
                        try:
                            audit.log(actor, 'reject', 'claim', claim_id, {'reason': claim['rejection_reason']})
                        except Exception:
                            pass
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True, 
                        'claim': claim,
                        'message': 'Claim rejected.'
                    }).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Claim not found'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Pay Claim Endpoint
        if path == '/api/claims/pay':
            try:
                data = json.loads(body)
                claim_id = data.get('id')
                claim = CLAIMS.get(claim_id)
                
                # Check if claim is approved (case-insensitive)
                if claim and claim.get('status', '').lower() == 'approved':
                    paid_amount = claim.get('approved_amount', claim['claimed_amount'])
                    payment_reference = f"PAY-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
                    
                    claim['status'] = 'Paid'
                    claim['payment_date'] = datetime.now().isoformat()
                    claim['payment_method'] = data.get('payment_method', 'bank_transfer')
                    claim['payment_reference'] = payment_reference
                    claim['paid_amount'] = paid_amount
                    claim['processed_by'] = data.get('processed_by', 'accountant')
                    
                    # Persist to database
                    CLAIMS[claim_id] = claim
                    
                    # Record payment in transaction ledger
                    record_transaction(
                        customer_id=claim.get('customer_id', 'unknown'),
                        tx_type='claim_paid',
                        amount=paid_amount,
                        description=f"Claim {claim_id} payment processed - ${paid_amount:.2f}",
                        metadata={
                            'claim_id': claim_id,
                            'policy_id': claim.get('policy_id'),
                            'paid_amount': paid_amount,
                            'payment_method': claim['payment_method'],
                            'payment_reference': payment_reference,
                            'processed_by': data.get('processed_by', 'accountant')
                        }
                    )
                    
                    if audit:
                        actor = data.get('processed_by', 'accountant')
                        try:
                            audit.log(actor, 'pay', 'claim', claim_id, {'paid_amount': claim['paid_amount'], 'payment_method': claim['payment_method']})
                        except Exception:
                            pass
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True, 
                        'claim': claim,
                        'message': f'Payment of ${paid_amount:.2f} processed successfully.',
                        'payment_reference': payment_reference
                    }).encode('utf-8'))
                else:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Claim not approved or not found'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Email validation endpoint
        if path == '/api/validate-email':
            try:
                data = json.loads(body)
                email = data.get('email', '')
                # Simple validation
                import re
                is_valid = re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email) is not None
                self._set_json_headers()
                self.wfile.write(json.dumps({'valid': is_valid}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # ========== BILLING API ENDPOINTS ==========
        if billing_enabled:
            # Add payment method
            if path == '/api/billing/payment-method':
                try:
                    data = json.loads(body)
                    customer_id = data.get('customer_id')
                    if not customer_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                        return
                    
                    result = billing_engine.add_payment_method(customer_id, data)
                    self._set_json_headers(200 if result['success'] else 400)
                    self.wfile.write(json.dumps(result).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
                return
            
            # Process payment/charge
            if path == '/api/billing/charge':
                try:
                    data = json.loads(body)
                    customer_id = data.get('customer_id')
                    amount = float(data.get('amount', 0))
                    policy_id = data.get('policy_id')
                    payment_token = data.get('payment_token')
                    currency = str(data.get('currency') or 'USD').upper()
                    crypto_amount = data.get('crypto_amount')
                    
                    if not customer_id or not policy_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id and policy_id required'}).encode('utf-8'))
                        return

                    fx_rate = None
                    if currency != 'USD':
                        # Validate currency is enabled in token registry (governance allow-list)
                        allowed = False
                        if USE_DATABASE and database_enabled:
                            try:
                                from database.manager import DatabaseManager
                                with DatabaseManager() as db:
                                    entry = db.tokens.get_by_symbol(currency)
                                    allowed = bool(entry and entry.enabled)
                            except Exception:
                                allowed = False
                        else:
                            with STATE_LOCK:
                                allowed = any(v.get('symbol') == currency and v.get('enabled', True) for v in TOKEN_REGISTRY.values())

                        if not allowed:
                            self._set_json_headers(400)
                            self.wfile.write(json.dumps({'error': f'Currency {currency} is not enabled'}).encode('utf-8'))
                            return

                        # Fetch USD spot price for currency and validate
                        if not _market_data:
                            self._set_json_headers(503)
                            self.wfile.write(json.dumps({'error': 'Market data service unavailable'}).encode('utf-8'))
                            return

                        prices = _market_data.get_crypto_prices_usd([currency]).get('prices', {})
                        if currency not in prices or not prices[currency]:
                            self._set_json_headers(502)
                            self.wfile.write(json.dumps({'error': f'No USD price available for {currency}'}).encode('utf-8'))
                            return
                        fx_rate = float(prices[currency])

                        # If crypto_amount is provided, compute USD amount; otherwise treat `amount` as USD-equivalent already
                        if crypto_amount is not None:
                            try:
                                crypto_amount_f = float(crypto_amount)
                            except Exception:
                                self._set_json_headers(400)
                                self.wfile.write(json.dumps({'error': 'crypto_amount must be numeric'}).encode('utf-8'))
                                return
                            amount = crypto_amount_f * fx_rate
                    
                    result = billing_engine.process_payment(
                        customer_id=customer_id,
                        amount=amount,
                        policy_id=policy_id,
                        payment_token=payment_token,
                        metadata={
                            **(data.get('metadata', {}) or {}),
                            **({'original_currency': currency} if currency else {}),
                            **({'crypto_amount': crypto_amount} if crypto_amount is not None else {}),
                        },
                        currency=currency,
                        fx_rate_to_usd=fx_rate,
                    )
                    
                    self._set_json_headers(200 if result['success'] else 400)
                    self.wfile.write(json.dumps(result).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
                return
            
            # Get billing history
            if path == '/api/billing/history':
                try:
                    data = json.loads(body) if body else {}
                    customer_id = data.get('customer_id')
                    
                    if not customer_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                        return
                    
                    transactions = billing_engine.get_customer_transactions(customer_id)
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'transactions': transactions}).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Get billing statement
            if path == '/api/billing/statement':
                try:
                    data = json.loads(body) if body else {}
                    customer_id = data.get('customer_id')
                    
                    if not customer_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                        return
                    
                    statement = billing_engine.get_billing_statement(
                        customer_id,
                        data.get('start_date'),
                        data.get('end_date')
                    )
                    self._set_json_headers()
                    self.wfile.write(json.dumps(statement).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Process refund
            if path == '/api/billing/refund':
                try:
                    data = json.loads(body)
                    transaction_id = data.get('transaction_id')
                    amount = data.get('amount')
                    reason = data.get('reason')
                    
                    if not transaction_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'transaction_id required'}).encode('utf-8'))
                        return
                    
                    result = billing_engine.refund_payment(transaction_id, amount, reason)
                    self._set_json_headers(200 if result['success'] else 400)
                    self.wfile.write(json.dumps(result).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
                return
            
            # Get fraud alerts (admin only)
            if path == '/api/billing/fraud-alerts':
                try:
                    data = json.loads(body) if body else {}
                    alerts = billing_engine.get_fraud_alerts(
                        severity=data.get('severity'),
                        status=data.get('status')
                    )
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'alerts': alerts}).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Get payment methods
            if path == '/api/billing/payment-methods':
                try:
                    data = json.loads(body) if body else {}
                    customer_id = data.get('customer_id')
                    
                    if not customer_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                        return
                    
                    methods = billing_engine.get_payment_methods(customer_id)
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'payment_methods': methods}).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Validate card number (enhanced with Mastercard 16-digit check)
            if path == '/api/billing/validate-card':
                try:
                    data = json.loads(body)
                    card_number = data.get('card_number', '')
                    expected_type = data.get('card_type')
                    
                    # Use enhanced SecurityValidator
                    validation_result = SecurityValidator.validate_card_number(card_number, expected_type)
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps(validation_result).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'valid': False, 'errors': [str(e)]}).encode('utf-8'))
                return
            
            # Get billing stats for dashboard
            if path == '/api/billing/stats':
                try:
                    # Calculate real stats from BILLING data
                    bills = list(BILLING.values())
                    total_transactions = len(bills)
                    successful = len([b for b in bills if b.get('status') in ['paid', 'partial']])
                    failed = len([b for b in bills if b.get('status') == 'failed'])
                    total_revenue = sum(float(b.get('amount_paid', 0)) for b in bills)
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'total_transactions': total_transactions,
                        'successful_payments': successful,
                        'failed_payments': failed,
                        'total_revenue': round(total_revenue, 2),
                        'pending_alerts': 0
                    }).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Get recent transactions
            if path == '/api/billing/transactions':
                try:
                    # Get recent transactions from billing history
                    transactions = []
                    for bill_id, bill in BILLING.items():
                        transactions.append({
                            'transaction_id': bill_id,
                            'customer_id': bill.get('customer_id', 'N/A'),
                            'amount': float(bill.get('amount_due', 0)),
                            'status': 'success' if bill.get('status') == 'paid' else bill.get('status', 'pending'),
                            'timestamp': bill.get('created_date', datetime.now().isoformat()),
                            'payment_method': bill.get('payment_method', '****-****-****-****')
                        })
                    
                    # Sort by timestamp desc and limit to 50
                    transactions.sort(key=lambda x: x['timestamp'], reverse=True)
                    transactions = transactions[:50]
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'transactions': transactions}).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
        
        # ========== PAYMENT GATEWAY API (PayPal, Stripe, Crypto) ==========
        # Import payment gateway service
        try:
            from services.payment_gateway_service import get_payment_gateway, PaymentResult
            payment_gateway = get_payment_gateway(test_mode=True, market_data_service=_market_data)
            payment_gateway_enabled = True
        except ImportError:
            payment_gateway_enabled = False
            payment_gateway = None
        
        if payment_gateway_enabled:
            # Get available payment methods
            if path == '/api/payment/methods':
                try:
                    methods = payment_gateway.get_available_methods()
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True,
                        'methods': methods,
                        'test_mode': payment_gateway.test_mode
                    }).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Process payment (unified endpoint)
            if path == '/api/payment/process':
                try:
                    data = json.loads(body)
                    method = data.get('method', 'credit_card')
                    amount = float(data.get('amount', 0))
                    currency = data.get('currency', 'USD')
                    customer_id = data.get('customer_id')
                    policy_id = data.get('policy_id')
                    
                    if amount <= 0:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'Amount must be positive'}).encode('utf-8'))
                        return
                    
                    # Process payment through unified gateway
                    result = payment_gateway.process_payment(
                        method=method,
                        amount=amount,
                        currency=currency,
                        customer_id=customer_id,
                        policy_id=policy_id,
                        card_number=data.get('card_number'),
                        expiry_month=data.get('expiry_month'),
                        expiry_year=data.get('expiry_year'),
                        cvv=data.get('cvv'),
                        email=data.get('email'),
                        description=data.get('description')
                    )
                    
                    # If successful card/PayPal payment, update billing record
                    if result.success and result.status == 'completed' and policy_id:
                        # Find and update billing record
                        for bill_id, bill in BILLING.items():
                            if bill.get('policy_id') == policy_id and bill.get('status') in ['outstanding', 'partial']:
                                bill['amount_paid'] = float(bill.get('amount_paid', 0)) + amount
                                if bill['amount_paid'] >= float(bill.get('amount_due', 0)):
                                    bill['status'] = 'paid'
                                else:
                                    bill['status'] = 'partial'
                                bill['payment_method'] = method
                                bill['transaction_id'] = result.transaction_id
                                bill['updated_date'] = datetime.now().isoformat()
                                break
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps(result.to_dict()).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'success': False, 'error': str(e)}).encode('utf-8'))
                return
            
            # PayPal specific endpoints
            if path == '/api/payment/paypal/create':
                try:
                    data = json.loads(body)
                    amount = float(data.get('amount', 0))
                    result = payment_gateway.paypal.create_order(
                        amount=amount,
                        currency=data.get('currency', 'USD'),
                        description=data.get('description', 'Insurance Premium')
                    )
                    self._set_json_headers()
                    self.wfile.write(json.dumps(result.to_dict()).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            if path.startswith('/api/payment/paypal/capture/'):
                try:
                    order_id = path.split('/')[-1]
                    result = payment_gateway.paypal.capture_order(order_id)
                    self._set_json_headers()
                    self.wfile.write(json.dumps(result.to_dict()).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Apple Pay session
            if path == '/api/payment/apple-pay/session':
                try:
                    data = json.loads(body)
                    result = payment_gateway.stripe.create_apple_pay_session(
                        amount=float(data.get('amount', 0)),
                        currency=data.get('currency', 'USD')
                    )
                    self._set_json_headers()
                    self.wfile.write(json.dumps(result.to_dict()).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Google Pay session
            if path == '/api/payment/google-pay/session':
                try:
                    data = json.loads(body)
                    result = payment_gateway.stripe.create_google_pay_session(
                        amount=float(data.get('amount', 0)),
                        currency=data.get('currency', 'USD')
                    )
                    self._set_json_headers()
                    self.wfile.write(json.dumps(result.to_dict()).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Crypto payment request
            if path == '/api/payment/crypto/create':
                try:
                    data = json.loads(body)
                    amount = float(data.get('amount', 0))
                    crypto = data.get('crypto', 'BTC').upper()
                    
                    result = payment_gateway.crypto.create_payment_request(
                        amount_usd=amount,
                        crypto_symbol=crypto,
                        customer_id=data.get('customer_id'),
                        policy_id=data.get('policy_id')
                    )
                    self._set_json_headers()
                    self.wfile.write(json.dumps(result.to_dict()).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Check crypto payment status
            if path.startswith('/api/payment/crypto/status/'):
                try:
                    payment_id = path.split('/')[-1]
                    result = payment_gateway.crypto.check_payment_status(payment_id)
                    self._set_json_headers()
                    self.wfile.write(json.dumps(result.to_dict()).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Simulate crypto payment (for testing)
            if path.startswith('/api/payment/crypto/simulate/'):
                try:
                    payment_id = path.split('/')[-1]
                    result = payment_gateway.simulate_crypto_confirmation(payment_id)
                    self._set_json_headers()
                    self.wfile.write(json.dumps(result.to_dict()).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Payment status check
            if path.startswith('/api/payment/status/'):
                try:
                    transaction_id = path.split('/')[-1]
                    method = parsed_url.query and urllib.parse.parse_qs(parsed_url.query).get('method', [None])[0]
                    result = payment_gateway.check_status(transaction_id, method)
                    self._set_json_headers()
                    self.wfile.write(json.dumps(result.to_dict()).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Transaction history
            if path == '/api/payment/history':
                try:
                    data = json.loads(body) if body else {}
                    customer_id = data.get('customer_id')
                    limit = int(data.get('limit', 50))
                    
                    transactions = payment_gateway.get_transaction_history(
                        customer_id=customer_id,
                        limit=limit
                    )
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True,
                        'transactions': transactions,
                        'test_mode': payment_gateway.test_mode
                    }).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
        # ========== END PAYMENT GATEWAY API ==========
        
        # ========== UNIFIED BILLING & DEPOSIT API ==========
        # Versatile payment system supporting all deposit destinations and payment methods
        
        if path == '/api/unified-payment/deposit':
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id')
                amount = float(data.get('amount', 0))
                destination = data.get('destination', 'health_wallet')  # health_wallet, investment, algo_trading
                payment_method = data.get('payment_method', 'credit_card')  # credit_card, apple_pay, paypal, crypto, internal_transfer
                source_account = data.get('source_account')  # For internal transfers: health_wallet, investment, algo_trading
                currency = data.get('currency', 'USD')
                description = data.get('description', '')
                
                # Validation
                if not customer_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                    return
                
                if amount < 1 or amount > 1000000:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Amount must be between $1 and $1,000,000'}).encode('utf-8'))
                    return
                
                valid_destinations = ['health_wallet', 'investment', 'algo_trading', 'savings', 'premium']
                if destination not in valid_destinations:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': f'Invalid destination. Must be one of: {valid_destinations}'}).encode('utf-8'))
                    return
                
                valid_methods = ['credit_card', 'debit_card', 'apple_pay', 'google_pay', 'paypal', 'crypto_btc', 'crypto_eth', 'crypto_usdc', 'bank_transfer', 'internal_transfer']
                if payment_method not in valid_methods:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': f'Invalid payment method. Must be one of: {valid_methods}'}).encode('utf-8'))
                    return
                
                # Initialize result
                payment_result = {
                    'success': False,
                    'transaction_id': f"UNIFIED-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(10000, 99999)}",
                    'amount': amount,
                    'destination': destination,
                    'payment_method': payment_method,
                    'customer_id': customer_id
                }
                
                # Process based on payment method
                if payment_method == 'internal_transfer':
                    # Internal transfer between accounts
                    if not source_account:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'source_account required for internal transfer'}).encode('utf-8'))
                        return
                    
                    if source_account == destination:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'Source and destination cannot be the same'}).encode('utf-8'))
                        return
                    
                    # Get source balance
                    source_balance = 0
                    if source_account == 'health_wallet':
                        wallet = HEALTH_WALLETS.get(customer_id, {})
                        source_balance = wallet.get('balance', 0)
                    elif source_account == 'investment':
                        inv_acc = INVESTMENT_ACCOUNTS.get(customer_id, {})
                        source_balance = inv_acc.get('balance', 0)
                    elif source_account == 'algo_trading':
                        if unified_balance_enabled:
                            algo_bal = unified_balance_service.get_algo_trading_balance(customer_id)
                            source_balance = algo_bal.get('available', 0)
                    
                    if source_balance < amount:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({
                            'error': 'Insufficient funds',
                            'source_balance': source_balance,
                            'required': amount
                        }).encode('utf-8'))
                        return
                    
                    # Deduct from source
                    if source_account == 'health_wallet':
                        HEALTH_WALLETS[customer_id]['balance'] -= amount
                    elif source_account == 'investment':
                        INVESTMENT_ACCOUNTS[customer_id]['balance'] -= amount
                    elif source_account == 'algo_trading' and unified_balance_enabled:
                        unified_balance_service.withdraw_from_algo_trading(customer_id, amount, destination)
                    
                    payment_result['source_account'] = source_account
                    payment_result['source_new_balance'] = source_balance - amount
                    payment_result['gateway'] = 'internal'
                    payment_result['success'] = True
                    
                elif payment_method.startswith('crypto_'):
                    # Crypto payment
                    crypto_symbol = payment_method.replace('crypto_', '').upper()
                    if payment_gateway_enabled:
                        gateway_result = payment_gateway.crypto.create_payment_request(
                            amount_usd=amount,
                            crypto_symbol=crypto_symbol,
                            customer_id=customer_id,
                            policy_id=data.get('policy_id')
                        )
                        payment_result['gateway'] = 'crypto'
                        payment_result['crypto_symbol'] = crypto_symbol
                        payment_result['crypto_address'] = gateway_result.details.get('wallet_address')
                        payment_result['crypto_amount'] = gateway_result.details.get('crypto_amount')
                        payment_result['success'] = True
                        payment_result['status'] = 'pending_confirmation'
                    else:
                        payment_result['gateway'] = 'crypto_simulated'
                        payment_result['success'] = True
                        
                elif payment_method == 'paypal':
                    # PayPal payment
                    if payment_gateway_enabled:
                        gateway_result = payment_gateway.paypal.create_order(
                            amount=amount,
                            currency=currency,
                            description=description or f'PHINS {destination} deposit'
                        )
                        payment_result['gateway'] = 'paypal'
                        payment_result['paypal_order_id'] = gateway_result.transaction_id
                        payment_result['approval_url'] = gateway_result.details.get('approval_url')
                        payment_result['success'] = True
                        payment_result['status'] = 'pending_approval'
                    else:
                        payment_result['gateway'] = 'paypal_simulated'
                        payment_result['success'] = True
                        
                elif payment_method in ['apple_pay', 'google_pay']:
                    # Apple Pay / Google Pay
                    if payment_gateway_enabled:
                        if payment_method == 'apple_pay':
                            gateway_result = payment_gateway.stripe.create_apple_pay_session(amount=amount, currency=currency)
                        else:
                            gateway_result = payment_gateway.stripe.create_google_pay_session(amount=amount, currency=currency)
                        payment_result['gateway'] = 'stripe'
                        payment_result['session_id'] = gateway_result.transaction_id
                        payment_result['success'] = True
                        payment_result['status'] = 'pending_authorization'
                    else:
                        payment_result['gateway'] = f'{payment_method}_simulated'
                        payment_result['success'] = True
                        
                else:
                    # Credit/Debit card or bank transfer (process immediately for simulation)
                    if payment_gateway_enabled:
                        gateway_result = payment_gateway.process_payment(
                            method=payment_method,
                            amount=amount,
                            currency=currency,
                            customer_id=customer_id,
                            policy_id=data.get('policy_id'),
                            card_token=data.get('card_token'),
                            payment_token=data.get('payment_token'),
                            description=description or f'PHINS {destination} deposit'
                        )
                        payment_result['gateway'] = gateway_result.gateway
                        payment_result['success'] = gateway_result.success
                        payment_result['status'] = gateway_result.status
                    else:
                        payment_result['gateway'] = 'simulated'
                        payment_result['success'] = True
                        payment_result['status'] = 'completed'
                
                # If payment successful (or internal transfer), add funds to destination
                if payment_result['success'] and (payment_method == 'internal_transfer' or payment_result.get('status') == 'completed'):
                    new_balance = 0
                    
                    if destination == 'health_wallet':
                        if customer_id not in HEALTH_WALLETS:
                            HEALTH_WALLETS[customer_id] = {
                                'customer_id': customer_id,
                                'balance': 0,
                                'monthly_deposit': 0,
                                'transactions': [],
                                'created_at': datetime.now().isoformat()
                            }
                        HEALTH_WALLETS[customer_id]['balance'] += amount
                        new_balance = HEALTH_WALLETS[customer_id]['balance']
                        
                        # Add transaction to wallet history
                        HEALTH_WALLETS[customer_id]['transactions'].append({
                            'id': payment_result['transaction_id'],
                            'type': 'deposit',
                            'amount': amount,
                            'payment_method': payment_method,
                            'source': source_account if payment_method == 'internal_transfer' else 'external',
                            'balance_after': new_balance,
                            'timestamp': datetime.now().isoformat()
                        })
                        
                    elif destination == 'investment':
                        if customer_id not in INVESTMENT_ACCOUNTS:
                            INVESTMENT_ACCOUNTS[customer_id] = {
                                'customer_id': customer_id,
                                'balance': 0,
                                'index_balance': 0,
                                'bonds_balance': 0,
                                'crypto_balance': 0,
                                'deposits': [],
                                'created_at': datetime.now().isoformat()
                            }
                        INVESTMENT_ACCOUNTS[customer_id]['balance'] += amount
                        new_balance = INVESTMENT_ACCOUNTS[customer_id]['balance']
                        
                        # Add to deposits history
                        INVESTMENT_ACCOUNTS[customer_id]['deposits'].append({
                            'id': payment_result['transaction_id'],
                            'amount': amount,
                            'payment_method': payment_method,
                            'source': source_account if payment_method == 'internal_transfer' else 'external',
                            'timestamp': datetime.now().isoformat()
                        })
                        
                    elif destination == 'algo_trading':
                        if unified_balance_enabled:
                            unified_balance_service.transfer_to_algo_trading(
                                customer_id=customer_id,
                                amount=amount,
                                source='external' if payment_method != 'internal_transfer' else source_account
                            )
                            algo_bal = unified_balance_service.get_algo_trading_balance(customer_id)
                            new_balance = algo_bal.get('available', 0)
                        else:
                            # Fallback: store in algo_trading_balances dict
                            if 'algo_trading_balances' not in globals():
                                global algo_trading_balances
                                algo_trading_balances = {}
                            if customer_id not in algo_trading_balances:
                                algo_trading_balances[customer_id] = 0
                            algo_trading_balances[customer_id] += amount
                            new_balance = algo_trading_balances[customer_id]
                    
                    elif destination == 'premium':
                        # Premium payment - update the bill and record on ledger
                        bill_id = data.get('bill_id')
                        
                        # Find outstanding bill if not specified
                        if not bill_id:
                            for bid, bill in BILLING.items():
                                if bill.get('customer_id') == customer_id and bill.get('status') == 'outstanding':
                                    bill_id = bid
                                    break
                        
                        if bill_id and bill_id in BILLING:
                            bill = BILLING[bill_id]
                            prev_paid = bill.get('amount_paid', 0)
                            bill['amount_paid'] = prev_paid + amount
                            
                            # Check if fully paid
                            if bill['amount_paid'] >= bill['amount']:
                                bill['status'] = 'paid'
                                bill['paid_date'] = datetime.now().isoformat()
                                bill['payment_method'] = payment_method
                                bill['transaction_id'] = payment_result['transaction_id']
                            elif bill['amount_paid'] > 0:
                                bill['status'] = 'partially_paid'
                            
                            bill['updated_date'] = datetime.now().isoformat()
                            payment_result['bill_id'] = bill_id
                            payment_result['bill_status'] = bill['status']
                            payment_result['amount_due_remaining'] = max(0, bill['amount'] - bill['amount_paid'])
                            new_balance = 0  # Premium payments don't add to a balance
                            
                            # Route savings portion through pipeline if configured
                            if savings_pipeline_enabled and savings_pipeline_service:
                                try:
                                    customer_alloc = CUSTOMER_ALLOCATIONS.get(customer_id, {})
                                    savings_pct = customer_alloc.get('savings_pct', 75)
                                    savings_amount = amount * (savings_pct / 100)
                                    
                                    if savings_amount > 0:
                                        savings_pipeline_service.deposit_to_pipeline(
                                            customer_id=customer_id,
                                            amount=savings_amount,
                                            source='premium_payment',
                                            auto_allocate=True
                                        )
                                        payment_result['savings_allocated'] = savings_amount
                                except Exception as pipe_err:
                                    print(f"Pipeline allocation note: {pipe_err}")
                        else:
                            # No bill found, just record as premium payment
                            new_balance = 0
                            payment_result['message'] = 'Premium payment recorded (no outstanding bill found)'
                    
                    elif destination == 'savings':
                        # Direct deposit to savings pipeline
                        if savings_pipeline_enabled and savings_pipeline_service:
                            result = savings_pipeline_service.deposit_to_pipeline(
                                customer_id=customer_id,
                                amount=amount,
                                source='direct_deposit',
                                auto_allocate=True
                            )
                            new_balance = result.get('new_balance', 0) if result.get('success') else 0
                            payment_result['pipeline_result'] = result
                        else:
                            # Fallback to investment account
                            if customer_id not in INVESTMENT_ACCOUNTS:
                                INVESTMENT_ACCOUNTS[customer_id] = {
                                    'customer_id': customer_id,
                                    'balance': 0,
                                    'index_balance': 0,
                                    'bonds_balance': 0,
                                    'crypto_balance': 0,
                                    'deposits': [],
                                    'created_at': datetime.now().isoformat()
                                }
                            INVESTMENT_ACCOUNTS[customer_id]['balance'] += amount
                            new_balance = INVESTMENT_ACCOUNTS[customer_id]['balance']
                    
                    payment_result['destination_new_balance'] = new_balance
                    
                    # Record on all ledgers
                    tx_type = 'internal_transfer' if payment_method == 'internal_transfer' else f'{destination}_deposit'
                    ledger_tx = record_transaction(
                        customer_id=customer_id,
                        tx_type=tx_type,
                        amount=amount,
                        description=description or f'{destination.replace("_", " ").title()} deposit via {payment_method}',
                        metadata={
                            'transaction_id': payment_result['transaction_id'],
                            'destination': destination,
                            'payment_method': payment_method,
                            'source_account': source_account,
                            'gateway': payment_result.get('gateway'),
                            'new_balance': new_balance
                        }
                    )
                    payment_result['nft_token_id'] = ledger_tx.get('nft_token_id')
                    payment_result['ledger_tx_id'] = ledger_tx.get('id')
                    payment_result['ledger_recorded'] = True
                
                self._set_json_headers()
                self.wfile.write(json.dumps(payment_result, default=str).encode('utf-8'))
                
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Get available balances for transfer
        if path == '/api/unified-payment/balances':
            try:
                data = json.loads(body) if body else {}
                customer_id = data.get('customer_id')
                
                if not customer_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                    return
                
                # Get all account balances
                wallet = HEALTH_WALLETS.get(customer_id, {})
                inv_acc = INVESTMENT_ACCOUNTS.get(customer_id, {})
                
                algo_balance = 0
                if unified_balance_enabled:
                    algo_bal = unified_balance_service.get_algo_trading_balance(customer_id)
                    algo_balance = algo_bal.get('available', 0)
                
                pipeline_cash = 0
                if savings_pipeline_enabled:
                    try:
                        analytics = savings_pipeline_service.get_pipeline_analytics(customer_id)
                        pipeline_cash = analytics.get('balances', {}).get('cash_balance', 0)
                    except:
                        pass
                
                balances = {
                    'health_wallet': {
                        'balance': wallet.get('balance', 0),
                        'name': 'Health Wallet',
                        'icon': '💊',
                        'can_deposit': True,
                        'can_withdraw': True
                    },
                    'investment': {
                        'balance': inv_acc.get('balance', 0),
                        'index_balance': inv_acc.get('index_balance', 0),
                        'bonds_balance': inv_acc.get('bonds_balance', 0),
                        'crypto_balance': inv_acc.get('crypto_balance', 0),
                        'name': 'Investment Account',
                        'icon': '📈',
                        'can_deposit': True,
                        'can_withdraw': True
                    },
                    'algo_trading': {
                        'balance': algo_balance,
                        'name': 'Algo Trading',
                        'icon': '🤖',
                        'can_deposit': True,
                        'can_withdraw': True
                    },
                    'pipeline_cash': {
                        'balance': pipeline_cash,
                        'name': 'Pipeline Cash',
                        'icon': '💰',
                        'can_deposit': False,
                        'can_withdraw': True
                    }
                }
                
                total_assets = sum(b['balance'] for b in balances.values())
                
                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'customer_id': customer_id,
                    'balances': balances,
                    'total_assets': total_assets,
                    'payment_methods': [
                        {'id': 'credit_card', 'name': 'Credit Card', 'icon': '💳', 'enabled': True},
                        {'id': 'debit_card', 'name': 'Debit Card', 'icon': '💳', 'enabled': True},
                        {'id': 'apple_pay', 'name': 'Apple Pay', 'icon': '🍎', 'enabled': True},
                        {'id': 'google_pay', 'name': 'Google Pay', 'icon': '🔵', 'enabled': True},
                        {'id': 'paypal', 'name': 'PayPal', 'icon': '🅿️', 'enabled': True},
                        {'id': 'crypto_btc', 'name': 'Bitcoin', 'icon': '₿', 'enabled': True},
                        {'id': 'crypto_eth', 'name': 'Ethereum', 'icon': 'Ξ', 'enabled': True},
                        {'id': 'crypto_usdc', 'name': 'USDC', 'icon': '💵', 'enabled': True},
                        {'id': 'bank_transfer', 'name': 'Bank Transfer', 'icon': '🏦', 'enabled': True},
                        {'id': 'internal_transfer', 'name': 'Internal Transfer', 'icon': '🔄', 'enabled': True}
                    ],
                    'destinations': [
                        {'id': 'health_wallet', 'name': 'Health Wallet', 'icon': '💊'},
                        {'id': 'investment', 'name': 'Investment Account', 'icon': '📈'},
                        {'id': 'algo_trading', 'name': 'Algo Trading', 'icon': '🤖'}
                    ]
                }).encode('utf-8'))
                
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Validate transfer before processing
        if path == '/api/unified-payment/validate':
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id')
                amount = float(data.get('amount', 0))
                destination = data.get('destination')
                payment_method = data.get('payment_method')
                source_account = data.get('source_account')
                
                validation = {
                    'valid': True,
                    'errors': [],
                    'warnings': []
                }
                
                if not customer_id:
                    validation['valid'] = False
                    validation['errors'].append('Customer ID required')
                
                if amount <= 0:
                    validation['valid'] = False
                    validation['errors'].append('Amount must be positive')
                
                if amount > 1000000:
                    validation['valid'] = False
                    validation['errors'].append('Amount exceeds maximum ($1,000,000)')
                
                if payment_method == 'internal_transfer':
                    if not source_account:
                        validation['valid'] = False
                        validation['errors'].append('Source account required for internal transfer')
                    elif source_account == destination:
                        validation['valid'] = False
                        validation['errors'].append('Source and destination cannot be the same')
                    else:
                        # Check balance
                        source_balance = 0
                        if source_account == 'health_wallet':
                            source_balance = HEALTH_WALLETS.get(customer_id, {}).get('balance', 0)
                        elif source_account == 'investment':
                            source_balance = INVESTMENT_ACCOUNTS.get(customer_id, {}).get('balance', 0)
                        elif source_account == 'algo_trading' and unified_balance_enabled:
                            source_balance = unified_balance_service.get_algo_trading_balance(customer_id).get('available', 0)
                        
                        if source_balance < amount:
                            validation['valid'] = False
                            validation['errors'].append(f'Insufficient balance. Available: ${source_balance:.2f}')
                        
                        validation['source_balance'] = source_balance
                
                if amount > 10000:
                    validation['warnings'].append('Large transaction - may require additional verification')
                
                self._set_json_headers()
                self.wfile.write(json.dumps(validation).encode('utf-8'))
                
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Get unified transaction history
        if path == '/api/unified-payment/history':
            try:
                data = json.loads(body) if body else {}
                customer_id = data.get('customer_id')
                limit = int(data.get('limit', 50))
                tx_type = data.get('type')  # Optional filter
                
                if not customer_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                    return
                
                # Get all transactions for customer
                transactions = []
                for tx in TRANSACTION_LEDGER.values():
                    if tx.get('customer_id') == customer_id:
                        if tx_type and tx.get('tx_type') != tx_type:
                            continue
                        transactions.append(tx)
                
                # Sort by timestamp descending
                transactions.sort(key=lambda x: x.get('timestamp', x.get('created_at', '')), reverse=True)
                
                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'transactions': transactions[:limit],
                    'total_count': len(transactions)
                }, default=str).encode('utf-8'))
                
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # ========== END UNIFIED BILLING & DEPOSIT API ==========
        
        # ========== HEALTH WALLET API ==========
        
        # Get or create health wallet
        if path == '/api/health-wallet':
            try:
                data = json.loads(body) if body else {}
                customer_id = data.get('customer_id', 'CUST001')
                
                # Get or create wallet
                if customer_id not in HEALTH_WALLETS:
                    HEALTH_WALLETS[customer_id] = {
                        'customer_id': customer_id,
                        'balance': 850.00,  # Default starting balance for demo
                        'monthly_deposit': 100.00,
                        'transactions': [],
                        'created_at': datetime.now().isoformat()
                    }
                
                wallet = HEALTH_WALLETS[customer_id]
                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'wallet': wallet
                }).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Add funds to wallet
        if path == '/api/health-wallet/deposit':
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id', 'CUST001')
                amount = float(data.get('amount', 0))
                payment_method = data.get('payment_method', 'card_on_file')
                
                if amount < 1 or amount > 100000:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Amount must be between $1 and $100,000'}).encode('utf-8'))
                    return
                
                # Initialize wallet if not exists
                if customer_id not in HEALTH_WALLETS:
                    HEALTH_WALLETS[customer_id] = {
                        'customer_id': customer_id,
                        'balance': 0,
                        'monthly_deposit': 0,
                        'transactions': [],
                        'created_at': datetime.now().isoformat()
                    }
                
                # Add funds
                prev_balance = HEALTH_WALLETS[customer_id]['balance']
                HEALTH_WALLETS[customer_id]['balance'] += amount
                
                # Record transaction
                transaction_id = f"TXN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
                transaction = {
                    'id': transaction_id,
                    'type': 'deposit',
                    'amount': amount,
                    'payment_method': payment_method,
                    'timestamp': datetime.now().isoformat(),
                    'balance_after': HEALTH_WALLETS[customer_id]['balance']
                }
                HEALTH_WALLETS[customer_id]['transactions'].append(transaction)
                
                # Record on TRANSACTION_LEDGER and NFT_LEDGER using proper function
                ledger_tx = record_transaction(
                    customer_id=customer_id,
                    tx_type='wallet_deposit',
                    amount=amount,
                    description=f"Health Wallet Deposit via {payment_method}",
                    metadata={
                        'payment_method': payment_method,
                        'previous_balance': prev_balance,
                        'new_balance': HEALTH_WALLETS[customer_id]['balance'],
                        'wallet_transaction_id': transaction_id
                    }
                )
                transaction['nft_token_id'] = ledger_tx.get('nft_token_id')
                transaction['ledger_tx_id'] = ledger_tx.get('id')  # Fixed: use 'id' not 'tx_id'
                
                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'transaction': transaction,
                    'nft_token_id': ledger_tx.get('nft_token_id'),
                    'ledger_recorded': True,
                    'new_balance': HEALTH_WALLETS[customer_id]['balance']
                }).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Purchase medical product/service
        if path == '/api/health-wallet/purchase':
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id', 'CUST001')
                product_id = data.get('product_id')
                product_name = data.get('product_name')
                amount = float(data.get('amount', 0))
                category = data.get('category', 'general')
                provider = data.get('provider', '')
                
                if not product_id or not amount:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Product ID and amount required'}).encode('utf-8'))
                    return
                
                # Check wallet balance
                if customer_id not in HEALTH_WALLETS:
                    HEALTH_WALLETS[customer_id] = {
                        'customer_id': customer_id,
                        'balance': 0,
                        'monthly_deposit': 0,
                        'transactions': [],
                        'created_at': datetime.now().isoformat()
                    }
                
                wallet = HEALTH_WALLETS[customer_id]
                if wallet['balance'] < amount:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({
                        'error': 'Insufficient balance',
                        'balance': wallet['balance'],
                        'required': amount,
                        'shortfall': amount - wallet['balance']
                    }).encode('utf-8'))
                    return
                
                # Deduct amount
                prev_balance = wallet['balance']
                wallet['balance'] -= amount
                
                # Create purchase record
                purchase_id = f"PUR-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
                
                # Record on TRANSACTION_LEDGER and NFT_LEDGER
                ledger_tx = record_transaction(
                    customer_id=customer_id,
                    tx_type='medical_purchase',
                    amount=amount,
                    description=f"Medical Purchase: {product_name} from {provider or 'provider'}",
                    metadata={
                        'purchase_id': purchase_id,
                        'product_id': product_id,
                        'product_name': product_name,
                        'category': category,
                        'provider': provider,
                        'previous_balance': prev_balance,
                        'new_balance': wallet['balance'],
                        'payment_source': 'health_wallet'
                    }
                )
                
                purchase = {
                    'id': purchase_id,
                    'customer_id': customer_id,
                    'product_id': product_id,
                    'product_name': product_name,
                    'category': category,
                    'provider': provider,
                    'amount': amount,
                    'status': 'completed',
                    'timestamp': datetime.now().isoformat(),
                    'nft_token_id': ledger_tx.get('nft_token_id'),
                    'transaction_hash': NFT_LEDGER.get(ledger_tx.get('nft_token_id'), {}).get('transaction_hash', ''),
                    'verification_hash': NFT_LEDGER.get(ledger_tx.get('nft_token_id'), {}).get('verification_hash', ''),
                    'ledger_tx_id': ledger_tx.get('id')  # Fixed: use 'id' not 'tx_id'
                }
                MEDICAL_PURCHASES[purchase_id] = purchase
                
                # Record transaction in wallet
                transaction_id = f"TXN-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
                transaction = {
                    'id': transaction_id,
                    'type': 'purchase',
                    'amount': -amount,
                    'product_id': product_id,
                    'product_name': product_name,
                    'category': category,
                    'timestamp': datetime.now().isoformat(),
                    'balance_after': wallet['balance'],
                    'nft_token_id': ledger_tx.get('nft_token_id'),
                    'ledger_tx_id': ledger_tx.get('id')  # Fixed: use 'id' not 'tx_id'
                }
                wallet['transactions'].append(transaction)
                
                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'purchase': purchase,
                    'transaction': transaction,
                    'nft_token_id': ledger_tx.get('nft_token_id'),
                    'ledger_recorded': True,
                    'new_balance': wallet['balance']
                }).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Get purchase history (POST)
        if path == '/api/health-wallet/purchases':
            try:
                data = json.loads(body) if body else {}
                customer_id = data.get('customer_id', 'CUST001')
                
                purchases = [p for p in MEDICAL_PURCHASES.values() if p.get('customer_id') == customer_id]
                purchases.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
                
                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'purchases': purchases[:50]  # Last 50
                }).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(500)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # ========== END HEALTH WALLET API ==========
        
        # ========== MARKETPLACE API (Services, Products, NFT Tokens) ==========
        if marketplace_enabled and marketplace:
            
            # Get all service/product categories
            if path == '/api/marketplace/categories':
                try:
                    categories = marketplace.get_all_categories()
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True,
                        'categories': categories
                    }).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Search providers by location
            if path == '/api/marketplace/providers/search':
                try:
                    data = json.loads(body) if body else {}
                    category = data.get('category', 'consultation')
                    lat = float(data.get('latitude', 40.7128))  # Default NYC
                    lng = float(data.get('longitude', -74.0060))
                    radius = float(data.get('radius_km', 25.0))
                    limit = int(data.get('limit', 20))
                    
                    providers = marketplace.search_providers(
                        category=category,
                        latitude=lat,
                        longitude=lng,
                        radius_km=radius,
                        limit=limit
                    )
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True,
                        'providers': providers,
                        'search_params': {
                            'category': category,
                            'latitude': lat,
                            'longitude': lng,
                            'radius_km': radius
                        }
                    }).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Get products catalog
            if path == '/api/marketplace/products':
                try:
                    data = json.loads(body) if body else {}
                    category = data.get('category', 'medication')
                    subcategory = data.get('subcategory')
                    country = data.get('country_of_origin')
                    
                    products = marketplace.get_products(
                        category=category,
                        subcategory=subcategory,
                        country_of_origin=country
                    )
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True,
                        'products': products,
                        'total': len(products)
                    }).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Get customer wallet balance (using marketplace service)
            if path == '/api/marketplace/wallet':
                try:
                    data = json.loads(body) if body else {}
                    customer_id = data.get('customer_id')
                    
                    if not customer_id:
                        # Try to get from session
                        auth_header = self.headers.get('Authorization', '')
                        token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
                        if token:
                            session = validate_session(token)
                            if session:
                                customer_id = session.get('customer_id')
                    
                    if not customer_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                        return
                    
                    balance = marketplace.get_wallet_balance(customer_id)
                    nfts = marketplace.get_customer_nfts(customer_id)
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True,
                        'customer_id': customer_id,
                        'balance': balance,
                        'nft_count': len(nfts),
                        'currency': 'USD'
                    }).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Add funds to wallet
            if path == '/api/marketplace/wallet/deposit':
                try:
                    data = json.loads(body)
                    customer_id = data.get('customer_id')
                    amount = float(data.get('amount', 0))
                    source = data.get('source', 'card_payment')
                    policy_id = data.get('policy_id')
                    
                    if not customer_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                        return
                    
                    if amount < 10 or amount > 50000:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'Amount must be between $10 and $50,000'}).encode('utf-8'))
                        return
                    
                    result = marketplace.add_funds_to_wallet(
                        customer_id=customer_id,
                        amount=amount,
                        source=source,
                        policy_id=policy_id
                    )
                    
                    self._set_json_headers(200 if result['success'] else 400)
                    self.wfile.write(json.dumps(result).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Purchase service
            if path == '/api/marketplace/service/purchase':
                try:
                    data = json.loads(body)
                    customer_id = data.get('customer_id')
                    provider_id = data.get('provider_id')
                    service_type = data.get('service_type')
                    service_details = data.get('service_details', {})
                    policy_id = data.get('policy_id')
                    claim_id = data.get('claim_id')
                    scheduled_date = data.get('scheduled_date')
                    location = data.get('location')
                    
                    if not customer_id or not provider_id or not service_type:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id, provider_id, and service_type required'}).encode('utf-8'))
                        return
                    
                    result = marketplace.purchase_service(
                        customer_id=customer_id,
                        provider_id=provider_id,
                        service_type=service_type,
                        service_details=service_details,
                        policy_id=policy_id,
                        claim_id=claim_id,
                        scheduled_date=scheduled_date,
                        location=location
                    )
                    
                    if audit and result.get('success'):
                        try:
                            audit.log(customer_id, 'purchase', 'service', result['transaction']['transaction_id'], {
                                'amount': result['transaction']['total_amount'],
                                'nft_token': result['nft_token']['token_id']
                            })
                        except Exception:
                            pass
                    
                    self._set_json_headers(200 if result.get('success') else 400)
                    self.wfile.write(json.dumps(result).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Purchase product
            if path == '/api/marketplace/product/purchase':
                try:
                    data = json.loads(body)
                    customer_id = data.get('customer_id')
                    product_id = data.get('product_id')
                    product_details = data.get('product_details', {})
                    quantity = int(data.get('quantity', 1))
                    policy_id = data.get('policy_id')
                    claim_id = data.get('claim_id')
                    delivery_address = data.get('delivery_address')
                    
                    if not customer_id or not product_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id and product_id required'}).encode('utf-8'))
                        return
                    
                    result = marketplace.purchase_product(
                        customer_id=customer_id,
                        product_id=product_id,
                        product_details=product_details,
                        quantity=quantity,
                        policy_id=policy_id,
                        claim_id=claim_id,
                        delivery_address=delivery_address
                    )
                    
                    if audit and result.get('success'):
                        try:
                            audit.log(customer_id, 'purchase', 'product', result['transaction']['transaction_id'], {
                                'product_id': product_id,
                                'amount': result['transaction']['total_amount'],
                                'nft_token': result['nft_token']['token_id']
                            })
                        except Exception:
                            pass
                    
                    self._set_json_headers(200 if result.get('success') else 400)
                    self.wfile.write(json.dumps(result).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Get customer transactions
            if path == '/api/marketplace/transactions':
                try:
                    data = json.loads(body) if body else {}
                    customer_id = data.get('customer_id')
                    status = data.get('status')
                    category = data.get('category')
                    limit = int(data.get('limit', 50))
                    
                    if not customer_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                        return
                    
                    transactions = marketplace.get_customer_transactions(
                        customer_id=customer_id,
                        status=status,
                        category=category,
                        limit=limit
                    )
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True,
                        'transactions': transactions,
                        'total': len(transactions)
                    }).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Admin: Get all transactions
            if path == '/api/marketplace/admin/transactions':
                try:
                    # Verify admin
                    auth_header = self.headers.get('Authorization', '')
                    token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
                    session = validate_session(token) if token else None
                    if not require_role(session, ['admin', 'accountant']):
                        self._set_json_headers(403)
                        self.wfile.write(json.dumps({'error': 'Admin access required'}).encode('utf-8'))
                        return
                    
                    data = json.loads(body) if body else {}
                    status = data.get('status')
                    limit = int(data.get('limit', 100))
                    
                    transactions = marketplace.get_all_transactions(status=status, limit=limit)
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True,
                        'transactions': transactions,
                        'total': len(transactions)
                    }).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Admin: Get pending approvals
            if path == '/api/marketplace/admin/pending-approvals':
                try:
                    auth_header = self.headers.get('Authorization', '')
                    token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
                    session = validate_session(token) if token else None
                    if not require_role(session, ['admin', 'underwriter']):
                        self._set_json_headers(403)
                        self.wfile.write(json.dumps({'error': 'Admin access required'}).encode('utf-8'))
                        return
                    
                    approvals = marketplace.get_pending_approvals()
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True,
                        'pending_approvals': approvals,
                        'total': len(approvals)
                    }).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Admin: Approve transaction
            if path == '/api/marketplace/admin/approve':
                try:
                    auth_header = self.headers.get('Authorization', '')
                    token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
                    session = validate_session(token) if token else None
                    if not require_role(session, ['admin', 'underwriter']):
                        self._set_json_headers(403)
                        self.wfile.write(json.dumps({'error': 'Admin access required'}).encode('utf-8'))
                        return
                    
                    data = json.loads(body)
                    transaction_id = data.get('transaction_id')
                    approver_id = session.get('username', 'admin') if session else 'admin'
                    notes = data.get('notes')
                    
                    result = marketplace.approve_transaction(
                        transaction_id=transaction_id,
                        approver_id=approver_id,
                        approval_notes=notes
                    )
                    
                    if audit and result.get('success'):
                        try:
                            audit.log(approver_id, 'approve', 'marketplace_transaction', transaction_id, {'notes': notes})
                        except Exception:
                            pass
                    
                    self._set_json_headers(200 if result.get('success') else 400)
                    self.wfile.write(json.dumps(result).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Admin: Reject transaction
            if path == '/api/marketplace/admin/reject':
                try:
                    auth_header = self.headers.get('Authorization', '')
                    token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
                    session = validate_session(token) if token else None
                    if not require_role(session, ['admin', 'underwriter']):
                        self._set_json_headers(403)
                        self.wfile.write(json.dumps({'error': 'Admin access required'}).encode('utf-8'))
                        return
                    
                    data = json.loads(body)
                    transaction_id = data.get('transaction_id')
                    rejector_id = session.get('username', 'admin') if session else 'admin'
                    reason = data.get('reason', 'Rejected by admin')
                    
                    result = marketplace.reject_transaction(
                        transaction_id=transaction_id,
                        rejector_id=rejector_id,
                        rejection_reason=reason
                    )
                    
                    if audit and result.get('success'):
                        try:
                            audit.log(rejector_id, 'reject', 'marketplace_transaction', transaction_id, {'reason': reason})
                        except Exception:
                            pass
                    
                    self._set_json_headers(200 if result.get('success') else 400)
                    self.wfile.write(json.dumps(result).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # NFT: Verify token authenticity
            if path == '/api/marketplace/nft/verify':
                try:
                    data = json.loads(body)
                    token_id = data.get('token_id')
                    
                    if not token_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'token_id required'}).encode('utf-8'))
                        return
                    
                    result = marketplace.verify_nft_authenticity(token_id)
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps(result).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # NFT: Get customer NFTs
            if path == '/api/marketplace/nft/customer':
                try:
                    data = json.loads(body) if body else {}
                    customer_id = data.get('customer_id')
                    
                    if not customer_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                        return
                    
                    nfts = marketplace.get_customer_nfts(customer_id)
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True,
                        'nfts': nfts,
                        'total': len(nfts)
                    }).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # NFT: Get token details
            if path == '/api/marketplace/nft/details':
                try:
                    data = json.loads(body) if body else {}
                    token_id = data.get('token_id')
                    
                    if not token_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'token_id required'}).encode('utf-8'))
                        return
                    
                    nft = marketplace.get_nft_token(token_id)
                    
                    if nft:
                        self._set_json_headers()
                        self.wfile.write(json.dumps({
                            'success': True,
                            'nft': nft
                        }).encode('utf-8'))
                    else:
                        self._set_json_headers(404)
                        self.wfile.write(json.dumps({'error': 'NFT token not found'}).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Marketplace stats (BI dashboard)
            if path == '/api/marketplace/stats':
                try:
                    auth_header = self.headers.get('Authorization', '')
                    token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
                    session = validate_session(token) if token else None
                    if not require_role(session, ['admin', 'accountant', 'analyst']):
                        self._set_json_headers(403)
                        self.wfile.write(json.dumps({'error': 'Admin access required'}).encode('utf-8'))
                        return
                    
                    stats = marketplace.get_marketplace_stats()
                    
                    self._set_json_headers()
                    self.wfile.write(json.dumps({
                        'success': True,
                        'stats': stats
                    }).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Process claim payment to wallet/service/product
            if path == '/api/marketplace/claim/pay':
                try:
                    auth_header = self.headers.get('Authorization', '')
                    token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else None
                    session = validate_session(token) if token else None
                    if not require_role(session, ['admin', 'accountant', 'claims_adjuster']):
                        self._set_json_headers(403)
                        self.wfile.write(json.dumps({'error': 'Authorization required'}).encode('utf-8'))
                        return
                    
                    data = json.loads(body)
                    claim_id = data.get('claim_id')
                    customer_id = data.get('customer_id')
                    policy_id = data.get('policy_id')
                    amount = float(data.get('amount', 0))
                    payment_type_str = data.get('payment_type', 'lump_sum')
                    destination = data.get('destination', 'wallet')
                    
                    # Map string to PaymentType enum
                    payment_type_map = {
                        'lump_sum': PaymentType.LUMP_SUM,
                        'risk_cover': PaymentType.RISK_COVER,
                        'service_payment': PaymentType.SERVICE_PAYMENT,
                        'product_purchase': PaymentType.PRODUCT_PURCHASE,
                        'recurring_benefit': PaymentType.RECURRING_BENEFIT
                    }
                    payment_type = payment_type_map.get(payment_type_str, PaymentType.LUMP_SUM)
                    
                    result = marketplace.process_claim_payment(
                        claim_id=claim_id,
                        customer_id=customer_id,
                        policy_id=policy_id,
                        approved_amount=amount,
                        payment_type=payment_type,
                        payment_destination=destination
                    )
                    
                    if audit and result.get('success'):
                        actor = session.get('username', 'system') if session else 'system'
                        try:
                            audit.log(actor, 'process_payment', 'claim', claim_id, {
                                'amount': amount,
                                'payment_type': payment_type_str,
                                'destination': destination
                            })
                        except Exception:
                            pass
                    
                    self._set_json_headers(200 if result.get('success') else 400)
                    self.wfile.write(json.dumps(result).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
            
            # Link purchase to claim
            if path == '/api/marketplace/claim/link-purchase':
                try:
                    data = json.loads(body)
                    transaction_id = data.get('transaction_id')
                    claim_id = data.get('claim_id')
                    
                    if not transaction_id or not claim_id:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': 'transaction_id and claim_id required'}).encode('utf-8'))
                        return
                    
                    result = marketplace.link_purchase_to_claim(transaction_id, claim_id)
                    
                    self._set_json_headers(200 if result.get('success') else 400)
                    self.wfile.write(json.dumps(result).encode('utf-8'))
                except Exception as e:
                    self._set_json_headers(500)
                    self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                return
        
        # ========== END MARKETPLACE API ==========
        
        # ========== SAVINGS & INVESTMENT PORTFOLIO POST API ==========
        
        # Create a new savings account
        if path == '/api/savings/create-account':
            if not portfolio_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Investment service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id')
                policy_id = data.get('policy_id')
                monthly_contribution = float(data.get('monthly_contribution', 500))
                savings_rate_pct = float(data.get('savings_rate_pct', 25))
                risk_profile_str = data.get('risk_profile', 'moderate')
                
                if not customer_id or not policy_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id and policy_id required'}).encode('utf-8'))
                    return
                
                # Map risk profile string to enum
                risk_map = {
                    'conservative': RiskProfile.CONSERVATIVE,
                    'moderate_conservative': RiskProfile.MODERATE_CONSERVATIVE,
                    'moderate': RiskProfile.MODERATE,
                    'moderate_aggressive': RiskProfile.MODERATE_AGGRESSIVE,
                    'aggressive': RiskProfile.AGGRESSIVE
                }
                risk_profile = risk_map.get(risk_profile_str.lower(), RiskProfile.MODERATE)
                
                account = portfolio_service.create_savings_account(
                    customer_id=customer_id,
                    policy_id=policy_id,
                    monthly_contribution=monthly_contribution,
                    savings_rate_pct=savings_rate_pct,
                    risk_profile=risk_profile
                )
                
                if audit:
                    try:
                        audit.log(customer_id, 'create', 'savings_account', account.account_id, 
                                 {'monthly': monthly_contribution, 'risk': risk_profile_str})
                    except Exception:
                        pass
                
                self._set_json_headers(201)
                result = {
                    'success': True,
                    'account_id': account.account_id,
                    'customer_id': customer_id,
                    'policy_id': policy_id,
                    'risk_profile': account.risk_profile.value,
                    'monthly_contribution': account.monthly_contribution,
                    'message': 'Savings account created successfully'
                }
                self.wfile.write(json.dumps(result).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Deposit funds into savings account
        if path == '/api/savings/deposit':
            if not portfolio_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Investment service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                account_id = data.get('account_id')
                amount = float(data.get('amount', 0))
                source = data.get('source', 'manual_deposit')
                
                if not account_id or amount <= 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'account_id and positive amount required'}).encode('utf-8'))
                    return
                
                if amount > 1000000:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Maximum deposit is $1,000,000'}).encode('utf-8'))
                    return
                
                result = portfolio_service.deposit(account_id, amount, source)
                
                if result.get('success') and audit:
                    try:
                        audit.log('system', 'deposit', 'savings_account', account_id, 
                                 {'amount': amount, 'source': source})
                    except Exception:
                        pass
                
                self._set_json_headers(200 if result.get('success') else 400)
                self.wfile.write(json.dumps(result).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Withdraw funds from savings account
        if path == '/api/savings/withdraw':
            if not portfolio_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Investment service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                account_id = data.get('account_id')
                amount = float(data.get('amount', 0))
                reason = data.get('reason', 'withdrawal')
                
                if not account_id or amount <= 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'account_id and positive amount required'}).encode('utf-8'))
                    return
                
                result = portfolio_service.withdraw(account_id, amount, reason)
                
                if result.get('success') and audit:
                    try:
                        audit.log('system', 'withdraw', 'savings_account', account_id, 
                                 {'amount': amount, 'reason': reason})
                    except Exception:
                        pass
                
                self._set_json_headers(200 if result.get('success') else 400)
                self.wfile.write(json.dumps(result).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Invest funds into an asset
        if path == '/api/savings/invest':
            if not portfolio_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Investment service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                account_id = data.get('account_id')
                symbol = data.get('symbol', '').upper()
                amount = float(data.get('amount', 0))
                
                if not account_id or not symbol or amount <= 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'account_id, symbol, and positive amount required'}).encode('utf-8'))
                    return
                
                result = portfolio_service.invest(account_id, symbol, amount)
                
                if result.get('success') and audit:
                    try:
                        audit.log('system', 'invest', 'savings_account', account_id, 
                                 {'symbol': symbol, 'amount': amount, 'price': result.get('price')})
                    except Exception:
                        pass
                
                self._set_json_headers(200 if result.get('success') else 400)
                self.wfile.write(json.dumps(result).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Sell an asset from portfolio
        if path == '/api/savings/sell':
            if not portfolio_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Investment service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                account_id = data.get('account_id')
                symbol = data.get('symbol', '').upper()
                quantity = float(data.get('quantity', 0))
                
                if not account_id or not symbol or quantity <= 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'account_id, symbol, and positive quantity required'}).encode('utf-8'))
                    return
                
                result = portfolio_service.sell_asset(account_id, symbol, quantity)
                
                if result.get('success') and audit:
                    try:
                        audit.log('system', 'sell', 'savings_account', account_id, 
                                 {'symbol': symbol, 'quantity': quantity, 'proceeds': result.get('proceeds')})
                    except Exception:
                        pass
                
                self._set_json_headers(200 if result.get('success') else 400)
                self.wfile.write(json.dumps(result).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Update risk profile and rebalance
        if path == '/api/savings/update-risk-profile':
            if not portfolio_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Investment service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                account_id = data.get('account_id')
                risk_profile_str = data.get('risk_profile', 'moderate')
                
                if not account_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'account_id required'}).encode('utf-8'))
                    return
                
                account = portfolio_service.get_account(account_id)
                if not account:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Account not found'}).encode('utf-8'))
                    return
                
                # Map risk profile string to enum
                risk_map = {
                    'conservative': RiskProfile.CONSERVATIVE,
                    'moderate_conservative': RiskProfile.MODERATE_CONSERVATIVE,
                    'moderate': RiskProfile.MODERATE,
                    'moderate_aggressive': RiskProfile.MODERATE_AGGRESSIVE,
                    'aggressive': RiskProfile.AGGRESSIVE
                }
                new_risk = risk_map.get(risk_profile_str.lower(), RiskProfile.MODERATE)
                
                # Update account
                old_risk = account.risk_profile
                account.risk_profile = new_risk
                account.target_allocation = portfolio_service.RISK_ALLOCATIONS[new_risk]
                
                if audit:
                    try:
                        audit.log('system', 'update_risk', 'savings_account', account_id, 
                                 {'old': old_risk.value, 'new': new_risk.value})
                    except Exception:
                        pass
                
                # Get recommendations for rebalancing
                recommendations = portfolio_service.generate_ai_recommendations(account_id)
                
                self._set_json_headers()
                result = {
                    'success': True,
                    'account_id': account_id,
                    'old_risk_profile': old_risk.value,
                    'new_risk_profile': new_risk.value,
                    'rebalance_recommendations': recommendations,
                    'message': f'Risk profile updated to {new_risk.value}. Review rebalancing recommendations.'
                }
                self.wfile.write(json.dumps(result).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Update monthly contribution
        if path == '/api/savings/update-contribution':
            if not portfolio_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Investment service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                account_id = data.get('account_id')
                monthly_contribution = float(data.get('monthly_contribution', 0))
                
                if not account_id or monthly_contribution < 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'account_id and non-negative monthly_contribution required'}).encode('utf-8'))
                    return
                
                account = portfolio_service.get_account(account_id)
                if not account:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Account not found'}).encode('utf-8'))
                    return
                
                old_contribution = account.monthly_contribution
                account.monthly_contribution = monthly_contribution
                
                if audit:
                    try:
                        audit.log('system', 'update_contribution', 'savings_account', account_id, 
                                 {'old': old_contribution, 'new': monthly_contribution})
                    except Exception:
                        pass
                
                # Calculate new projections
                projections = portfolio_service.generate_projections(account_id, 25)
                
                self._set_json_headers()
                result = {
                    'success': True,
                    'account_id': account_id,
                    'old_monthly_contribution': old_contribution,
                    'new_monthly_contribution': monthly_contribution,
                    'projected_value_25yr': projections.get('projections', {}).get('percentiles', {}).get('50th', [0])[-1] if projections.get('projections') else 0,
                    'message': f'Monthly contribution updated to ${monthly_contribution:,.2f}'
                }
                self.wfile.write(json.dumps(result).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # ========== END SAVINGS & INVESTMENT PORTFOLIO API ==========
        
        # ========== ALGO TRADING API ==========
        # Advanced algorithmic trading system with strategies, signals, and auto-execution
        
        # Create a new trading bot
        if path == '/api/algo/bots/create':
            if not algo_trading_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Algo trading service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                account_id = data.get('account_id')
                name = data.get('name', 'My Trading Bot')
                strategy = data.get('strategy', 'momentum')
                symbols = data.get('symbols', ['SPY', 'BTC'])
                
                if not account_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'account_id is required'}).encode('utf-8'))
                    return
                
                bot = algo_trading_service.create_bot(
                    account_id=account_id,
                    name=name,
                    strategy=TradingStrategy(strategy),
                    symbols=symbols,
                    max_position_size=float(data.get('max_position_size', 1000)),
                    max_daily_trades=int(data.get('max_daily_trades', 10)),
                    stop_loss_pct=float(data.get('stop_loss_pct', 5)),
                    take_profit_pct=float(data.get('take_profit_pct', 10)),
                    dca_interval_hours=int(data.get('dca_interval_hours', 24)),
                    dca_amount=float(data.get('dca_amount', 100))
                )
                
                self._set_json_headers(201)
                from dataclasses import asdict
                self.wfile.write(json.dumps({
                    'success': True,
                    'bot': asdict(bot)
                }).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Start a trading bot
        if path == '/api/algo/bots/start':
            if not algo_trading_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Algo trading service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                bot_id = data.get('bot_id')
                result = algo_trading_service.start_bot(bot_id)
                self._set_json_headers()
                self.wfile.write(json.dumps(result).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Stop a trading bot
        if path == '/api/algo/bots/stop':
            if not algo_trading_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Algo trading service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                bot_id = data.get('bot_id')
                result = algo_trading_service.stop_bot(bot_id)
                self._set_json_headers()
                self.wfile.write(json.dumps(result).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Delete a trading bot
        if path == '/api/algo/bots/delete':
            if not algo_trading_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Algo trading service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                bot_id = data.get('bot_id')
                if bot_id in algo_trading_service.bots:
                    del algo_trading_service.bots[bot_id]
                    self._set_json_headers()
                    self.wfile.write(json.dumps({'success': True}).encode('utf-8'))
                else:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Bot not found'}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Run a single bot trading cycle
        if path == '/api/algo/bots/run-cycle':
            if not algo_trading_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Algo trading service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                bot_id = data.get('bot_id')
                results = algo_trading_service.run_bot_cycle(bot_id)
                
                # Record each trade on unified balance ledgers
                if unified_balance_enabled:
                    bot = algo_trading_service.bots.get(bot_id)
                    if bot:
                        customer_id = bot.account_id
                        for result in results:
                            if 'order' in result:
                                try:
                                    ledger_result = unified_balance_service.record_algo_trade(
                                        customer_id=customer_id,
                                        order_data=result['order']
                                    )
                                    result['nft_token_id'] = ledger_result.get('nft_token_id')
                                    result['ledger_recorded'] = True
                                except Exception:
                                    result['ledger_recorded'] = False
                
                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'bot_id': bot_id,
                    'results': results
                }).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Execute a quick trade
        if path == '/api/algo/trade':
            if not algo_trading_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Algo trading service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                account_id = data.get('account_id')
                customer_id = data.get('customer_id', account_id)  # Fall back to account_id for customer
                symbol = data.get('symbol')
                side = data.get('side')  # buy or sell
                amount = float(data.get('amount', 100))
                
                if not all([account_id, symbol, side]):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'account_id, symbol, and side are required'}).encode('utf-8'))
                    return
                
                from services.algo_trading_service import OrderType
                order = algo_trading_service.create_order(
                    account_id=account_id,
                    symbol=symbol,
                    side=side,
                    amount=amount,
                    order_type=OrderType.MARKET,
                    stop_loss_pct=float(data.get('stop_loss_pct', 5)),
                    take_profit_pct=float(data.get('take_profit_pct', 10)),
                    signal_id=data.get('signal_id')
                )
                
                from dataclasses import asdict
                order_dict = asdict(order)
                
                # Record trade on unified balance ledgers
                if unified_balance_enabled and customer_id:
                    try:
                        ledger_result = unified_balance_service.record_algo_trade(
                            customer_id=customer_id,
                            order_data=order_dict
                        )
                        order_dict['nft_token_id'] = ledger_result.get('nft_token_id')
                        order_dict['ledger_recorded'] = True
                    except Exception as ledger_err:
                        order_dict['ledger_recorded'] = False
                        order_dict['ledger_error'] = str(ledger_err)
                
                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'order': order_dict
                }).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Auto-rebalance portfolio
        if path == '/api/algo/rebalance':
            if not algo_trading_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Algo trading service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                account_id = data.get('account_id')
                tolerance_pct = float(data.get('tolerance_pct', 5.0))
                
                actions = algo_trading_service.auto_rebalance(account_id, tolerance_pct)
                
                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'account_id': account_id,
                    'actions': actions
                }).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # ========== END ALGO TRADING API ==========
        
        # ========== UNIFIED BALANCE POST API ==========
        # Transfer funds to algo trading from wallet or investment
        if path == '/api/balance/transfer-to-algo':
            if not unified_balance_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Unified balance service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id')
                amount = float(data.get('amount', 0))
                source = data.get('source', 'investment_account')
                bot_id = data.get('bot_id')
                
                if not customer_id or amount <= 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id and positive amount required'}).encode('utf-8'))
                    return
                
                result = unified_balance_service.transfer_to_algo_trading(
                    customer_id=customer_id,
                    amount=amount,
                    source=source,
                    bot_id=bot_id
                )
                
                if result['success']:
                    self._set_json_headers()
                else:
                    self._set_json_headers(400)
                
                self.wfile.write(json.dumps(result).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Withdraw funds from algo trading to wallet or investment
        if path == '/api/balance/withdraw-from-algo':
            if not unified_balance_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Unified balance service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id')
                amount = float(data.get('amount', 0))
                destination = data.get('destination', 'investment_account')
                
                if not customer_id or amount <= 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id and positive amount required'}).encode('utf-8'))
                    return
                
                result = unified_balance_service.withdraw_from_algo_trading(
                    customer_id=customer_id,
                    amount=amount,
                    destination=destination
                )
                
                if result['success']:
                    self._set_json_headers()
                else:
                    self._set_json_headers(400)
                
                self.wfile.write(json.dumps(result).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Record algo trade on ledgers (called internally or by admin)
        if path == '/api/balance/record-algo-trade':
            if not unified_balance_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Unified balance service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id')
                order_data = data.get('order_data', {})
                
                if not customer_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                    return
                
                result = unified_balance_service.record_algo_trade(customer_id, order_data)
                
                self._set_json_headers()
                self.wfile.write(json.dumps(result).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # ========== END UNIFIED BALANCE POST API ==========
        
        # ========== PORTFOLIO TRACKER POST API ==========
        # Real-time trading with P&L tracking and margin calculation
        
        # Deposit to algo trading from investment
        if path == '/api/portfolio/deposit-to-algo':
            if not portfolio_tracker_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Portfolio tracker service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id')
                amount = float(data.get('amount', 0))
                source = data.get('source', 'investment')  # investment or health_wallet
                
                if not customer_id or amount <= 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id and positive amount required'}).encode('utf-8'))
                    return
                
                # Sync algo_balances with unified_balance_service if available
                if unified_balance_enabled:
                    portfolio_tracker_service.algo_balances = unified_balance_service.algo_trading_balances
                
                result = portfolio_tracker_service.deposit_to_algo(customer_id, amount, source)
                
                # Sync back
                if unified_balance_enabled and result.get('success'):
                    unified_balance_service.algo_trading_balances = portfolio_tracker_service.algo_balances
                
                if result.get('success'):
                    self._set_json_headers()
                    # Save ledger data after successful deposit
                    save_ledger_data()
                else:
                    self._set_json_headers(400)
                
                self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Execute a trade with real-time P&L tracking
        if path == '/api/portfolio/trade':
            if not portfolio_tracker_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Portfolio tracker service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id')
                symbol = data.get('symbol', '').upper()
                trade_type = data.get('type', 'buy').lower()  # buy or sell
                amount = float(data.get('amount', 0))
                portfolio_type = data.get('portfolio_type', 'algo_trading')  # algo_trading or investment
                bot_id = data.get('bot_id')
                strategy = data.get('strategy')
                
                if not customer_id or not symbol or amount <= 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id, symbol, and positive amount required'}).encode('utf-8'))
                    return
                
                from services.portfolio_tracker_service import TradeType, PortfolioType
                
                tt = TradeType.BUY if trade_type == 'buy' else TradeType.SELL
                pt = PortfolioType.ALGO_TRADING if portfolio_type == 'algo_trading' else PortfolioType.INVESTMENT
                
                # Sync algo_balances with unified_balance_service if available
                if unified_balance_enabled:
                    portfolio_tracker_service.algo_balances = unified_balance_service.algo_trading_balances
                
                result = portfolio_tracker_service.execute_trade(
                    customer_id=customer_id,
                    symbol=symbol,
                    trade_type=tt,
                    amount=amount,
                    portfolio_type=pt,
                    bot_id=bot_id,
                    strategy=strategy
                )
                
                # Sync back
                if unified_balance_enabled and result.get('success'):
                    unified_balance_service.algo_trading_balances = portfolio_tracker_service.algo_balances
                
                if result.get('success'):
                    self._set_json_headers()
                    # Save ledger data after successful trade
                    save_ledger_data()
                    
                    # Include helpful P&L information in response
                    result['message'] = f"{'Bought' if trade_type == 'buy' else 'Sold'} {symbol}"
                    if trade_type == 'sell' and result.get('margin_pct'):
                        pnl = result.get('realized_pnl', 0)
                        margin = result.get('margin_pct', 0)
                        result['message'] += f" with {'+' if pnl >= 0 else ''}{margin:.2f}% margin (${pnl:,.2f} P&L)"
                else:
                    self._set_json_headers(400)
                
                self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            except Exception as e:
                import traceback
                traceback.print_exc()
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Quick buy - convenience endpoint for buying assets
        if path == '/api/portfolio/buy':
            if not portfolio_tracker_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Portfolio tracker service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                data['type'] = 'buy'
                
                # Forward to trade endpoint
                customer_id = data.get('customer_id')
                symbol = data.get('symbol', '').upper()
                amount = float(data.get('amount', 0))
                portfolio_type = data.get('portfolio_type', 'algo_trading')
                
                if not customer_id or not symbol or amount <= 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id, symbol, and positive amount required'}).encode('utf-8'))
                    return
                
                from services.portfolio_tracker_service import TradeType, PortfolioType
                tt = TradeType.BUY
                pt = PortfolioType.ALGO_TRADING if portfolio_type == 'algo_trading' else PortfolioType.INVESTMENT
                
                if unified_balance_enabled:
                    portfolio_tracker_service.algo_balances = unified_balance_service.algo_trading_balances
                
                result = portfolio_tracker_service.execute_trade(
                    customer_id=customer_id,
                    symbol=symbol,
                    trade_type=tt,
                    amount=amount,
                    portfolio_type=pt
                )
                
                if unified_balance_enabled and result.get('success'):
                    unified_balance_service.algo_trading_balances = portfolio_tracker_service.algo_balances
                
                if result.get('success'):
                    self._set_json_headers()
                    save_ledger_data()
                    
                    # Get current market info
                    market = portfolio_tracker_service.get_market_price(symbol)
                    result['current_price'] = market['price']
                    result['message'] = f"Bought ${amount:,.2f} of {symbol} @ ${market['price']:,.2f}"
                else:
                    self._set_json_headers(400)
                
                self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Quick sell - convenience endpoint for selling assets with P&L calculation
        if path == '/api/portfolio/sell':
            if not portfolio_tracker_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Portfolio tracker service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id')
                symbol = data.get('symbol', '').upper()
                amount = float(data.get('amount', 0))  # Amount in USD to sell
                portfolio_type = data.get('portfolio_type', 'algo_trading')
                
                if not customer_id or not symbol or amount <= 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id, symbol, and positive amount required'}).encode('utf-8'))
                    return
                
                from services.portfolio_tracker_service import TradeType, PortfolioType
                tt = TradeType.SELL
                pt = PortfolioType.ALGO_TRADING if portfolio_type == 'algo_trading' else PortfolioType.INVESTMENT
                
                if unified_balance_enabled:
                    portfolio_tracker_service.algo_balances = unified_balance_service.algo_trading_balances
                
                result = portfolio_tracker_service.execute_trade(
                    customer_id=customer_id,
                    symbol=symbol,
                    trade_type=tt,
                    amount=amount,
                    portfolio_type=pt
                )
                
                if unified_balance_enabled and result.get('success'):
                    unified_balance_service.algo_trading_balances = portfolio_tracker_service.algo_balances
                
                if result.get('success'):
                    self._set_json_headers()
                    save_ledger_data()
                    
                    pnl = result.get('realized_pnl', 0)
                    margin = result.get('margin_pct', 0)
                    result['message'] = f"Sold ${amount:,.2f} of {symbol}"
                    result['pnl_summary'] = {
                        'realized_pnl': pnl,
                        'margin_pct': margin,
                        'is_profit': pnl >= 0,
                        'holding_type': result.get('position', {}).get('position_type', 'short')
                    }
                else:
                    self._set_json_headers(400)
                
                self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Transfer funds between portfolios (cash balance management)
        if path == '/api/portfolio/transfer':
            if not portfolio_tracker_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Portfolio tracker service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id')
                amount = float(data.get('amount', 0))
                from_account = data.get('from', 'investment')  # investment, algo_trading, health_wallet
                to_account = data.get('to', 'algo_trading')
                
                if not customer_id or amount <= 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id and positive amount required'}).encode('utf-8'))
                    return
                
                # Handle different transfer directions
                if to_account == 'algo_trading':
                    if unified_balance_enabled:
                        result = unified_balance_service.transfer_to_algo_trading(
                            customer_id, amount, 
                            'health_wallet' if from_account == 'health_wallet' else 'investment_account'
                        )
                    else:
                        result = portfolio_tracker_service.deposit_to_algo(customer_id, amount, from_account)
                elif from_account == 'algo_trading':
                    if unified_balance_enabled:
                        result = unified_balance_service.withdraw_from_algo_trading(
                            customer_id, amount,
                            'health_wallet' if to_account == 'health_wallet' else 'investment_account'
                        )
                    else:
                        result = {'success': False, 'error': 'Cannot withdraw without unified balance service'}
                else:
                    result = {'success': False, 'error': f'Unsupported transfer direction: {from_account} -> {to_account}'}
                
                if result.get('success'):
                    self._set_json_headers()
                    save_ledger_data()
                    result['message'] = f"Transferred ${amount:,.2f} from {from_account} to {to_account}"
                else:
                    self._set_json_headers(400)
                
                self.wfile.write(json.dumps(result, default=str).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # ========== END PORTFOLIO TRACKER POST API ==========
        
        # ========== SAVINGS PIPELINE POST API ==========
        # Deposit funds to pipeline
        if path == '/api/pipeline/deposit':
            if not savings_pipeline_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Savings pipeline service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id')
                amount = float(data.get('amount', 0))
                source = data.get('source', 'premium_payment')
                auto_allocate = data.get('auto_allocate', True)
                
                if not customer_id or amount <= 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id and positive amount required'}).encode('utf-8'))
                    return
                
                result = savings_pipeline_service.deposit_to_pipeline(
                    customer_id=customer_id,
                    amount=amount,
                    source=source,
                    auto_allocate=auto_allocate
                )
                
                self._set_json_headers()
                self.wfile.write(json.dumps(result).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Manually allocate cash balance
        if path == '/api/pipeline/allocate':
            if not savings_pipeline_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Savings pipeline service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id')
                amount = data.get('amount')  # None = allocate all
                use_ai = data.get('use_ai', True)
                
                if not customer_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                    return
                
                result = savings_pipeline_service.allocate_cash_balance(
                    customer_id=customer_id,
                    amount=float(amount) if amount else None,
                    use_ai=use_ai
                )
                
                if result['success']:
                    self._set_json_headers()
                else:
                    self._set_json_headers(400)
                
                self.wfile.write(json.dumps(result).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Update pipeline settings (risk level, strategy)
        if path == '/api/pipeline/settings':
            if not savings_pipeline_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Savings pipeline service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id')
                
                if not customer_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                    return
                
                account = savings_pipeline_service.get_or_create_account(customer_id)
                
                # Update settings
                if 'risk_level' in data:
                    from services.savings_pipeline_service import RiskLevel
                    account.risk_level = RiskLevel(data['risk_level'])
                
                if 'strategy' in data:
                    from services.savings_pipeline_service import AllocationStrategy
                    account.allocation_strategy = AllocationStrategy(data['strategy'])
                
                if 'auto_allocate' in data:
                    account.auto_allocate = bool(data['auto_allocate'])
                
                if 'allocation_config' in data:
                    from services.savings_pipeline_service import AllocationConfig
                    config_data = data['allocation_config']
                    account.allocation_config = AllocationConfig(
                        wallet_pct=float(config_data.get('wallet_pct', 15)),
                        investment_pct=float(config_data.get('investment_pct', 60)),
                        algo_trading_pct=float(config_data.get('algo_trading_pct', 25)),
                        index_pct=float(config_data.get('index_pct', 50)),
                        bonds_pct=float(config_data.get('bonds_pct', 30)),
                        crypto_pct=float(config_data.get('crypto_pct', 20))
                    )
                
                from dataclasses import asdict
                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'account': asdict(account)
                }).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # Update market conditions (admin only)
        if path == '/api/pipeline/market-conditions':
            if not savings_pipeline_enabled:
                self._set_json_headers(503)
                self.wfile.write(json.dumps({'error': 'Savings pipeline service unavailable'}).encode('utf-8'))
                return
            
            try:
                data = json.loads(body)
                sentiment = data.get('sentiment')
                volatility = data.get('volatility')
                
                savings_pipeline_service.update_market_conditions(
                    sentiment=float(sentiment) if sentiment is not None else None,
                    volatility=float(volatility) if volatility is not None else None
                )
                
                self._set_json_headers()
                self.wfile.write(json.dumps({
                    'success': True,
                    'market_sentiment': savings_pipeline_service.market_sentiment,
                    'volatility_index': savings_pipeline_service.volatility_index
                }).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
            return
        
        # ========== END SAVINGS PIPELINE POST API ==========
        
        # ========== END BILLING API ==========
        # Minimal billing endpoints (demo fallback when engine routes are not used)
        if path == '/api/billing/create':
            try:
                data = json.loads(body)
                policy_id = data.get('policy_id')
                amount_due = float(data.get('amount_due', 0))
                due_days = int(data.get('due_days', 30))
                if not policy_id or not validate_amount(amount_due):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'policy_id and valid amount_due required'}).encode('utf-8'))
                    return
                bill_id = f"BILL-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000,9999)}"
                bill = {
                    'id': bill_id,
                    'policy_id': policy_id,
                    'amount': amount_due,
                    'amount_paid': 0.0,
                    'status': 'outstanding',
                    'created_date': datetime.now().isoformat(),
                    'due_date': (datetime.now() + timedelta(days=due_days)).isoformat()
                }
                BILLING[bill_id] = bill
                if audit:
                    try:
                        audit.log('system', 'create', 'bill', bill_id, {'policy_id': policy_id, 'amount_due': amount_due})
                    except Exception:
                        pass
                self._set_json_headers(201)
                self.wfile.write(json.dumps({'bill': bill}).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid request', 'details': str(e)}).encode('utf-8'))
            return

        if path == '/api/billing/pay':
            try:
                data = json.loads(body)
                bill_id = data.get('bill_id')
                amount = float(data.get('amount', 0))
                payment_method = data.get('payment_method', 'card')
                bill = BILLING.get(bill_id)
                if not bill:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'Bill not found'}).encode('utf-8'))
                    return
                if not validate_amount(amount):
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid amount'}).encode('utf-8'))
                    return
                
                prev_paid = bill.get('amount_paid', 0.0)
                bill['amount_paid'] = prev_paid + amount
                # Support both 'amount' and 'amount_due' field names for compatibility
                amount_due = bill.get('amount', bill.get('amount_due', 0))
                if bill['amount_paid'] >= amount_due:
                    bill['status'] = 'paid'
                    bill['paid_date'] = datetime.now().isoformat()
                else:
                    bill['status'] = 'partial'
                
                # Get customer_id from bill
                customer_id = bill.get('customer_id', 'unknown')
                policy_id = bill.get('policy_id')
                
                # Record payment on TRANSACTION_LEDGER and NFT_LEDGER
                payment_tx = record_transaction(
                    customer_id=customer_id,
                    tx_type='bill_payment',
                    amount=amount,
                    description=f"Bill payment of ${amount:.2f} for bill {bill_id}",
                    metadata={
                        'bill_id': bill_id,
                        'policy_id': policy_id,
                        'payment_method': payment_method,
                        'amount_due': amount_due,
                        'amount_paid_total': bill['amount_paid'],
                        'bill_status': bill['status'],
                        'prev_paid': prev_paid
                    }
                )
                
                # If payment allocates to savings (for premium payments), route through pipeline
                if savings_pipeline_enabled and savings_pipeline_service and policy_id:
                    try:
                        # Get customer's allocation preferences
                        customer_alloc = CUSTOMER_ALLOCATIONS.get(customer_id, {})
                        savings_pct = customer_alloc.get('savings_pct', 75)
                        savings_amount = amount * (savings_pct / 100)
                        
                        if savings_amount > 0:
                            # Deposit to pipeline for AI allocation
                            savings_pipeline_service.deposit_to_pipeline(
                                customer_id=customer_id,
                                amount=savings_amount,
                                source='premium_payment',
                                auto_allocate=True
                            )
                    except Exception as pipe_err:
                        print(f"Pipeline allocation note: {pipe_err}")
                
                if audit:
                    try:
                        audit.log('system', 'update', 'bill', bill_id, {'paid': amount, 'status': bill['status']})
                    except Exception:
                        pass
                
                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'bill': bill,
                    'transaction_recorded': True,
                    'nft_token_id': payment_tx.get('nft_token_id')
                }).encode('utf-8'))
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid request', 'details': str(e)}).encode('utf-8'))
            return
        
        # ========== CUSTOMER BILLING & SETTINGS ENDPOINTS ==========
        
        # Customer premium payment with NFT recording and CUSTOM investment allocation
        if path == '/api/customer/payment':
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id')
                amount = float(data.get('amount', 0))
                payment_method = data.get('payment_method', 'card')
                create_nft = data.get('create_nft', True)
                allocate_to_investments = data.get('allocate_to_investments', True)
                
                if not customer_id or amount <= 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid customer_id or amount'}).encode('utf-8'))
                    return
                
                # Get customer's CUSTOM allocation preferences
                allocation_prefs = get_customer_allocation(customer_id)
                savings_pct = allocation_prefs['savings_pct'] / 100.0
                risk_pct = allocation_prefs['risk_pct'] / 100.0
                
                # Process payment
                payment_id = f"PAY-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
                
                # Calculate allocations using customer's preferences
                savings_amount = amount * savings_pct
                risk_amount = amount * risk_pct
                
                # Calculate investment breakdown
                index_amount = savings_amount * (allocation_prefs['index_pct'] / 100.0)
                bonds_amount = savings_amount * (allocation_prefs['bonds_pct'] / 100.0)
                crypto_amount = savings_amount * (allocation_prefs['crypto_pct'] / 100.0)
                
                # Update customer's investment account
                if customer_id not in INVESTMENT_ACCOUNTS:
                    INVESTMENT_ACCOUNTS[customer_id] = {
                        'balance': 0.0,
                        'index_balance': 0.0,
                        'bonds_balance': 0.0,
                        'crypto_balance': 0.0,
                        'deposits': [],
                        'allocations': [],
                        'created_at': datetime.now().isoformat()
                    }
                
                inv_account = INVESTMENT_ACCOUNTS[customer_id]
                inv_account['balance'] += savings_amount
                inv_account['index_balance'] = inv_account.get('index_balance', 0.0) + index_amount
                inv_account['bonds_balance'] = inv_account.get('bonds_balance', 0.0) + bonds_amount
                inv_account['crypto_balance'] = inv_account.get('crypto_balance', 0.0) + crypto_amount
                
                # Record deposit in investment account
                deposit_record = {
                    'id': payment_id,
                    'type': 'premium_allocation',
                    'amount': savings_amount,
                    'index_amount': index_amount,
                    'bonds_amount': bonds_amount,
                    'crypto_amount': crypto_amount,
                    'timestamp': datetime.now().isoformat()
                }
                inv_account['deposits'].append(deposit_record)
                INVESTMENT_ACCOUNTS[customer_id] = inv_account
                
                # Record in master transaction ledger
                tx = record_transaction(
                    customer_id=customer_id,
                    tx_type='premium_payment',
                    amount=amount,
                    description=f'Premium payment via {payment_method}. Savings: ${savings_amount:.2f} ({allocation_prefs["savings_pct"]}%) → Investments',
                    metadata={
                        'payment_method': payment_method,
                        'savings_allocation': savings_amount,
                        'risk_allocation': risk_amount,
                        'savings_pct': allocation_prefs['savings_pct'],
                        'risk_pct': allocation_prefs['risk_pct'],
                        'index_amount': index_amount,
                        'bonds_amount': bonds_amount,
                        'crypto_amount': crypto_amount,
                        'investment_account_balance': inv_account['balance']
                    }
                )
                
                # Record the payment
                payment_record = {
                    'id': payment_id,
                    'customer_id': customer_id,
                    'amount': amount,
                    'savings_allocated': savings_amount,
                    'risk_allocated': risk_amount,
                    'savings_pct': allocation_prefs['savings_pct'],
                    'risk_pct': allocation_prefs['risk_pct'],
                    'index_amount': index_amount,
                    'bonds_amount': bonds_amount,
                    'crypto_amount': crypto_amount,
                    'payment_method': payment_method,
                    'nft_token_id': tx.get('nft_token_id'),
                    'transaction_id': tx['id'],
                    'timestamp': datetime.now().isoformat(),
                    'status': 'completed'
                }
                
                # Update any outstanding bills for this customer
                bills_paid = []
                remaining_amount = amount
                for bill_id, bill in list(BILLING.items()):
                    if remaining_amount <= 0:
                        break
                    if bill.get('customer_id') == customer_id and bill.get('status') in ['outstanding', 'pending']:
                        bill_due = bill.get('amount', bill.get('amount_due', 0))
                        bill_paid_so_far = bill.get('amount_paid', 0)
                        outstanding = bill_due - bill_paid_so_far
                        
                        if outstanding > 0:
                            payment_for_bill = min(remaining_amount, outstanding)
                            bill['amount_paid'] = bill_paid_so_far + payment_for_bill
                            if bill['amount_paid'] >= bill_due:
                                bill['status'] = 'paid'
                                bill['paid_date'] = datetime.now().isoformat()
                            else:
                                bill['status'] = 'partial'
                            BILLING[bill_id] = bill
                            remaining_amount -= payment_for_bill
                            bills_paid.append(bill_id)
                
                # Route savings through the AI Pipeline for smart allocation
                pipeline_result = None
                if savings_pipeline_enabled and savings_amount > 0:
                    try:
                        # Deposit savings to pipeline (will auto-allocate to wallet, investments, algo trading)
                        pipeline_result = savings_pipeline_service.deposit_to_pipeline(
                            customer_id=customer_id,
                            amount=savings_amount,
                            source='premium_payment',
                            auto_allocate=True  # Let AI optimize allocation
                        )
                    except Exception as pipe_err:
                        pipeline_result = {'error': str(pipe_err)}
                
                self._set_json_headers(200)
                response = {
                    'success': True,
                    'payment': payment_record,
                    'nft_token_id': tx.get('nft_token_id'),
                    'savings_allocated': savings_amount,
                    'risk_allocated': risk_amount,
                    'savings_pct': allocation_prefs['savings_pct'],
                    'risk_pct': allocation_prefs['risk_pct'],
                    'investment_breakdown': {
                        'index': index_amount,
                        'bonds': bonds_amount,
                        'crypto': crypto_amount
                    },
                    'investment_account_balance': inv_account['balance'],
                    'bills_updated': bills_paid
                }
                
                # Add pipeline allocation details
                if pipeline_result:
                    response['pipeline_allocation'] = pipeline_result.get('allocation', {})
                    response['ai_optimized'] = True
                
                self.wfile.write(json.dumps(response).encode('utf-8'))
                
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Payment failed', 'details': str(e)}).encode('utf-8'))
            return
        
        # Get/Set customer allocation preferences
        if path == '/api/customer/allocation':
            try:
                data = json.loads(body) if body else {}
                customer_id = data.get('customer_id')
                
                if not customer_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                    return
                
                # If allocation data provided, update preferences
                if any(k in data for k in ['savings_pct', 'risk_pct', 'index_pct', 'bonds_pct', 'crypto_pct']):
                    allocation_data = {
                        'savings_pct': float(data.get('savings_pct', 25.0)),
                        'risk_pct': float(data.get('risk_pct', 75.0)),
                        'index_pct': float(data.get('index_pct', 60.0)),
                        'bonds_pct': float(data.get('bonds_pct', 30.0)),
                        'crypto_pct': float(data.get('crypto_pct', 10.0)),
                    }
                    
                    try:
                        updated = update_customer_allocation(customer_id, allocation_data)
                        
                        # Record allocation change in ledger
                        record_transaction(
                            customer_id=customer_id,
                            tx_type='allocation_change',
                            amount=0,
                            description=f'Allocation updated: Savings {allocation_data["savings_pct"]}% | Index {allocation_data["index_pct"]}% | Bonds {allocation_data["bonds_pct"]}% | Crypto {allocation_data["crypto_pct"]}%',
                            metadata=allocation_data
                        )
                        
                        self._set_json_headers(200)
                        self.wfile.write(json.dumps({
                            'success': True,
                            'allocation': updated,
                            'message': 'Allocation preferences updated'
                        }).encode('utf-8'))
                    except ValueError as e:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                else:
                    # Just get current allocation
                    allocation = get_customer_allocation(customer_id)
                    self._set_json_headers(200)
                    self.wfile.write(json.dumps({
                        'success': True,
                        'allocation': allocation
                    }).encode('utf-8'))
                    
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Allocation request failed', 'details': str(e)}).encode('utf-8'))
            return
        
        # Additional investment deposit (add savings beyond premium)
        if path == '/api/customer/investment/deposit':
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id')
                amount = float(data.get('amount', 0))
                deposit_type = data.get('deposit_type', 'additional_savings')
                
                if not customer_id or amount <= 0:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Invalid customer_id or amount'}).encode('utf-8'))
                    return
                
                # Get customer's allocation preferences for investment breakdown
                allocation_prefs = get_customer_allocation(customer_id)
                
                # Calculate investment breakdown
                index_amount = amount * (allocation_prefs['index_pct'] / 100.0)
                bonds_amount = amount * (allocation_prefs['bonds_pct'] / 100.0)
                crypto_amount = amount * (allocation_prefs['crypto_pct'] / 100.0)
                
                # Initialize or update investment account
                if customer_id not in INVESTMENT_ACCOUNTS:
                    INVESTMENT_ACCOUNTS[customer_id] = {
                        'balance': 0.0,
                        'index_balance': 0.0,
                        'bonds_balance': 0.0,
                        'crypto_balance': 0.0,
                        'deposits': [],
                        'allocations': [],
                        'created_at': datetime.now().isoformat()
                    }
                
                inv_account = INVESTMENT_ACCOUNTS[customer_id]
                inv_account['balance'] += amount
                inv_account['index_balance'] = inv_account.get('index_balance', 0.0) + index_amount
                inv_account['bonds_balance'] = inv_account.get('bonds_balance', 0.0) + bonds_amount
                inv_account['crypto_balance'] = inv_account.get('crypto_balance', 0.0) + crypto_amount
                
                deposit_id = f"DEP-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
                
                # Record deposit
                deposit_record = {
                    'id': deposit_id,
                    'type': deposit_type,
                    'amount': amount,
                    'index_amount': index_amount,
                    'bonds_amount': bonds_amount,
                    'crypto_amount': crypto_amount,
                    'timestamp': datetime.now().isoformat()
                }
                inv_account['deposits'].append(deposit_record)
                INVESTMENT_ACCOUNTS[customer_id] = inv_account
                
                # Record in master ledger
                tx = record_transaction(
                    customer_id=customer_id,
                    tx_type='investment_deposit',
                    amount=amount,
                    description=f'Additional investment deposit: ${amount:.2f}',
                    metadata={
                        'deposit_type': deposit_type,
                        'index_amount': index_amount,
                        'bonds_amount': bonds_amount,
                        'crypto_amount': crypto_amount,
                        'allocation_prefs': allocation_prefs,
                        'new_balance': inv_account['balance']
                    }
                )
                
                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'success': True,
                    'deposit': deposit_record,
                    'nft_token_id': tx.get('nft_token_id'),
                    'transaction_id': tx['id'],
                    'investment_breakdown': {
                        'index': index_amount,
                        'bonds': bonds_amount,
                        'crypto': crypto_amount
                    },
                    'account_balance': inv_account['balance'],
                    'account_details': {
                        'index_balance': inv_account['index_balance'],
                        'bonds_balance': inv_account['bonds_balance'],
                        'crypto_balance': inv_account['crypto_balance']
                    }
                }).encode('utf-8'))
                
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Investment deposit failed', 'details': str(e)}).encode('utf-8'))
            return
        
        # Get investment account summary
        if path == '/api/customer/investment/account':
            try:
                data = json.loads(body) if body else {}
                customer_id = data.get('customer_id')
                
                if not customer_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                    return
                
                inv_account = INVESTMENT_ACCOUNTS.get(customer_id, {
                    'balance': 0.0,
                    'index_balance': 0.0,
                    'bonds_balance': 0.0,
                    'crypto_balance': 0.0,
                    'deposits': [],
                    'allocations': []
                })
                
                allocation_prefs = get_customer_allocation(customer_id)
                
                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'success': True,
                    'account': inv_account,
                    'allocation_preferences': allocation_prefs,
                    'total_balance': inv_account.get('balance', 0.0),
                    'breakdown': {
                        'index_funds': inv_account.get('index_balance', 0.0),
                        'bonds': inv_account.get('bonds_balance', 0.0),
                        'crypto': inv_account.get('crypto_balance', 0.0)
                    }
                }).encode('utf-8'))
                
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Account request failed', 'details': str(e)}).encode('utf-8'))
            return
        
        # Get customer transaction ledger
        if path == '/api/customer/transactions':
            try:
                data = json.loads(body) if body else {}
                customer_id = data.get('customer_id')
                tx_type = data.get('type')  # Optional filter
                limit = int(data.get('limit', 50))
                
                if not customer_id:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id required'}).encode('utf-8'))
                    return
                
                # Get transactions from master ledger
                transactions = [
                    tx for tx in TRANSACTION_LEDGER.values()
                    if tx.get('customer_id') == customer_id
                    and (not tx_type or tx.get('type') == tx_type)
                ]
                
                # Sort by timestamp descending
                transactions.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
                transactions = transactions[:limit]
                
                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'success': True,
                    'transactions': transactions,
                    'count': len(transactions)
                }).encode('utf-8'))
                
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Transaction request failed', 'details': str(e)}).encode('utf-8'))
            return
        
        # Customer password change
        if path == '/api/customer/change-password':
            try:
                data = json.loads(body)
                current_password = data.get('current_password')
                new_password = data.get('new_password')
                
                # Get customer from session
                auth_header = self.headers.get('Authorization', '')
                token = auth_header.replace('Bearer ', '') if auth_header.startswith('Bearer ') else ''
                session = SESSIONS.get(token, {})
                username = session.get('username')
                
                if not username:
                    self._set_json_headers(401)
                    self.wfile.write(json.dumps({'error': 'Not authenticated'}).encode('utf-8'))
                    return
                
                if not current_password or not new_password:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'Both current and new password required'}).encode('utf-8'))
                    return
                
                # Validate new password strength
                if len(new_password) < 8:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'New password must be at least 8 characters'}).encode('utf-8'))
                    return
                
                # Find and verify user
                user = USERS.get(username)
                if not user:
                    self._set_json_headers(404)
                    self.wfile.write(json.dumps({'error': 'User not found'}).encode('utf-8'))
                    return
                
                # Verify current password
                if not verify_password(current_password, user['hash'], user['salt']):
                    self._set_json_headers(401)
                    self.wfile.write(json.dumps({'error': 'Current password is incorrect'}).encode('utf-8'))
                    return
                
                # Hash new password
                new_hash = hash_password(new_password)
                user['hash'] = new_hash['hash']
                user['salt'] = new_hash['salt']
                USERS[username] = user
                
                # Record password change on NFT ledger
                customer_id = session.get('customer_id', username)
                nft_token = generate_nft_token(
                    customer_id=customer_id,
                    transaction_type='password_change',
                    transaction_id=f"PWD-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                    amount=0,
                    description='Password changed',
                    metadata={'action': 'security_update'}
                )
                NFT_LEDGER[nft_token['token_id']] = nft_token
                
                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'success': True,
                    'message': 'Password changed successfully',
                    'nft_token_id': nft_token['token_id']
                }).encode('utf-8'))
                
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Password change failed', 'details': str(e)}).encode('utf-8'))
            return
        
        # Record customer action on NFT ledger
        if path == '/api/customer/action':
            try:
                data = json.loads(body)
                customer_id = data.get('customer_id')
                action_type = data.get('action_type')
                amount = float(data.get('amount', 0))
                description = data.get('description', '')
                
                if not customer_id or not action_type:
                    self._set_json_headers(400)
                    self.wfile.write(json.dumps({'error': 'customer_id and action_type required'}).encode('utf-8'))
                    return
                
                # Generate NFT token for the action
                action_id = f"ACT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
                nft_token = generate_nft_token(
                    customer_id=customer_id,
                    transaction_type=action_type,
                    transaction_id=action_id,
                    amount=amount,
                    description=description,
                    metadata={
                        'action_type': action_type,
                        'timestamp': data.get('timestamp', datetime.now().isoformat())
                    }
                )
                NFT_LEDGER[nft_token['token_id']] = nft_token
                
                self._set_json_headers(200)
                self.wfile.write(json.dumps({
                    'success': True,
                    'action_id': action_id,
                    'nft_token': nft_token
                }).encode('utf-8'))
                
            except Exception as e:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Action recording failed', 'details': str(e)}).encode('utf-8'))
            return
        
        # Default: not found
        self.send_error(404, 'Not Found')
    
    def handle_quote_submission(self):
        """Handle quote form submission with multipart data"""
        try:
            # Validate all form inputs for security
            content_type = self.headers.get('Content-Type', '')
            if not content_type.startswith('multipart/form-data'):
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'Invalid content type'}).encode('utf-8'))
                return
            
            # Read and parse the form data
            length = int(self.headers.get('Content-Length', 0))
            form_data = self.rfile.read(length)
            
            # Extract boundary from content type
            boundary = content_type.split('boundary=')[1] if 'boundary=' in content_type else None
            if not boundary:
                self._set_json_headers(400)
                self.wfile.write(json.dumps({'error': 'No boundary in multipart data'}).encode('utf-8'))
                return
            
            # Parse multipart form data
            fields = self._parse_multipart_data(form_data, boundary.encode())  # type: ignore
            
            # Validate all critical fields for security threats
            critical_fields = ['first-name', 'last-name', 'email', 'phone', 'address', 
                             'city', 'state', 'occupation', 'medical-conditions']
            for field_name in critical_fields:
                field_value = fields.get(field_name, '')
                if field_value:
                    threat = validate_input_security(field_value, field_name, self.client_address[0])
                    if threat:
                        self._set_json_headers(400)
                        self.wfile.write(json.dumps({'error': f'Invalid input in {field_name}: {threat}'}).encode('utf-8'))
                        return
            
            # Generate IDs
            customer_id = generate_customer_id()
            policy_id = generate_policy_id()
            uw_id = f"UW-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
            
            # Create customer record
            customer_name = f"{fields.get('first-name', '')} {fields.get('last-name', '')}".strip()
            CUSTOMERS[customer_id] = {
                'id': customer_id,
                'name': customer_name,
                'first_name': fields.get('first-name', ''),
                'last_name': fields.get('last-name', ''),
                'email': fields.get('email', ''),
                'phone': fields.get('phone', ''),
                'dob': fields.get('dob', ''),
                'gender': fields.get('gender', ''),
                'address': fields.get('address', ''),
                'city': fields.get('city', ''),
                'state': fields.get('state', ''),
                'zip': fields.get('zip', ''),
                'occupation': fields.get('occupation', ''),
                'created_date': datetime.now().isoformat()
            }
            
            # Provision portal login for the customer
            cust_email = CUSTOMERS[customer_id].get('email') or f"{customer_id.lower()}@example.com"
            temp_password = f"pw-{uuid.uuid4().hex[:10]}"
            pwd_hash = hash_password(temp_password)
            USERS[cust_email] = {
                'hash': pwd_hash['hash'],
                'salt': pwd_hash['salt'],
                'role': 'customer',
                'name': customer_name,
                'customer_id': customer_id
            }
            
            # Parse coverage amount
            coverage_amount = int(fields.get('coverage-amount', '250000'))
            policy_type = fields.get('policy-type', 'disability')
            
            # Assess risk based on health information
            risk_score = 'low'
            medical_exam_required = False
            
            smoking = fields.get('smoking', '').lower()
            if smoking in ['yes', 'smoker', 'current']:
                risk_score = 'medium'
            
            health_conditions = fields.get('health-conditions', '').lower()
            if any(condition in health_conditions for condition in ['diabetes', 'heart', 'cancer', 'chronic']):
                risk_score = 'high'
                medical_exam_required = True
            
            # Create underwriting application
            UNDERWRITING_APPLICATIONS[uw_id] = {
                'id': uw_id,
                'policy_id': policy_id,
                'customer_id': customer_id,
                'status': 'pending',
                'questionnaire_responses': {
                    'smoking': fields.get('smoking', 'No'),
                    'health_conditions': fields.get('health-conditions', 'None'),
                    'medications': fields.get('medications', 'None'),
                    'family_history': fields.get('family-history', 'Good'),
                    'occupation': fields.get('occupation', ''),
                    'height': fields.get('height', ''),
                    'weight': fields.get('weight', '')
                },
                'risk_assessment': risk_score,
                'medical_exam_required': medical_exam_required,
                'submitted_date': datetime.now().isoformat()
            }
            
            # Calculate premium
            premium_data = calculate_premium({
                'type': policy_type,
                'coverage_amount': coverage_amount,
                'age': self._calculate_age(fields.get('dob', '1990-01-01')),
                'risk_score': risk_score
            })
            
            # Create policy
            POLICIES[policy_id] = {
                'id': policy_id,
                'customer_id': customer_id,
                'type': policy_type,
                'coverage_amount': coverage_amount,
                'annual_premium': premium_data['annual'],
                'monthly_premium': premium_data['monthly'],
                'status': 'pending_underwriting',
                'underwriting_id': uw_id,
                'risk_score': risk_score,
                'start_date': datetime.now().isoformat(),
                'end_date': (datetime.now() + timedelta(days=365)).isoformat(),
                'created_date': datetime.now().isoformat()
            }
            
            print(f"✅ Application submitted: {uw_id} for customer {customer_id}")
            print(f"   Customer: {customer_name} ({cust_email})")
            print(f"   Policy: {policy_type.title()} - ${coverage_amount:,}")
            print(f"   Risk: {risk_score}, Status: pending")
            
            # Return success response with all created records
            self._set_json_headers(200)
            response = {
                'success': True,
                'application_id': uw_id,
                'customer_id': customer_id,
                'policy_id': policy_id,
                'message': 'Your application has been submitted successfully. Our underwriting team will review it and contact you within 2-3 business days.',
                'estimated_premium': premium_data,
                'login_credentials': {
                    'username': cust_email,
                    'temporary_password': temp_password,
                    'portal_url': '/login.html'
                },
                'next_steps': [
                    'Check your email for confirmation',
                    'Login to customer portal to track your application',
                    'Our underwriter will contact you for any additional information',
                    'Complete medical examination if required',
                    'Receive final quote and policy terms'
                ],
                'application_summary': {
                    'customer_name': customer_name,
                    'policy_type': policy_type,
                    'coverage_amount': coverage_amount,
                    'risk_assessment': risk_score,
                    'status': 'pending'
                }
            }
            self.wfile.write(json.dumps(response).encode('utf-8'))
            
        except Exception as e:
            self._set_json_headers(500)
            self.wfile.write(json.dumps({'error': str(e), 'details': str(e.__class__.__name__)}).encode('utf-8'))
    
    def _parse_multipart_data(self, data: bytes, boundary: bytes) -> Dict[str, str]:
        """Parse multipart/form-data into dictionary of fields"""
        fields: Dict[str, str] = {}
        parts = data.split(b'--' + boundary)
        
        for part in parts:
            if b'Content-Disposition: form-data' not in part:
                continue
            
            # Extract field name
            if b'name="' in part:
                name_start = part.find(b'name="') + 6
                name_end = part.find(b'"', name_start)
                field_name = part[name_start:name_end].decode('utf-8')
                
                # Extract field value
                value_start = part.find(b'\r\n\r\n')
                if value_start != -1:
                    value_start += 4
                    value_end = part.rfind(b'\r\n')
                    if value_end > value_start:
                        field_value = part[value_start:value_end].decode('utf-8', errors='ignore').strip()
                        if field_value:  # Only add non-empty values
                            fields[field_name] = field_value
        
        return fields
    
    def _calculate_age(self, dob_str: str) -> int:
        """Calculate age from date of birth string"""
        try:
            dob = datetime.strptime(dob_str, '%Y-%m-%d')
            today = datetime.now()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            return age
        except:
            return 30  # Default age
    
    def calculate_demo_premium(self) -> Dict[str, Any]:
        """Calculate a demo premium estimate"""
        # Simple demo calculation
        import random
        base_premium = random.randint(500, 2000)
        return {
            'monthly': round(base_premium / 12, 2),
            'annual': base_premium,
            'currency': 'USD'
        }


def run_server(port: int = PORT) -> None:
    # Load persisted ledger data first
    print("📂 Loading persisted ledger data...")
    if load_ledger_data():
        print("✓ Ledger data restored from persistent storage")
    else:
        print("ℹ️  Starting with fresh ledger data")
    
    # Start periodic save thread
    schedule_periodic_save()
    
    # Initialize database if enabled
    if USE_DATABASE and database_enabled:
        print("📊 Initializing database...")
        try:
            # Check connection
            if check_database_connection():
                print("✓ Database connection successful")
                db_info = get_database_info()
                print(f"   Type: {db_info['database_type']}")
                print(f"   URL: {db_info['database_url'][:50]}...")
            else:
                print("⚠️  Database connection failed, will try to initialize anyway")
            
            # Initialize schema
            init_database()
            print("✓ Database schema initialized")
            
            # Seed default users
            try:
                seed_default_users()
                print("✓ Default admin users seeded")
            except Exception as e:
                print(f"Note: User seeding skipped (may already exist): {e}")
            
            # Seed sample customer data (test accounts)
            try:
                from database.seeds import seed_sample_data
                seed_sample_data()
                print("✓ Sample customer data seeded (asaf@assurance.co.il, etc.)")
            except Exception as e:
                print(f"Note: Sample data seeding skipped (may already exist): {e}")
        except Exception as e:
            print(f"❌ Database initialization failed: {e}")
            print("   Server will continue with in-memory storage")
            # Don't fail - just fall back to in-memory
    
    server_address = ('0.0.0.0', port)
    httpd = ThreadingHTTPServer(server_address, PortalHandler)
    httpd.daemon_threads = True  # Ensure worker threads exit on shutdown
    httpd.timeout = CONNECTION_TIMEOUT  # Set connection timeout
    print(f'\n🚀 Serving web portal at http://0.0.0.0:{port} (static from {ROOT})')
    print(f'   Access via: http://localhost:{port}')
    print(f'🔒 Security: Rate limiting, malicious code blocking, auto-cleanup enabled')
    print(f'⏱️  Connection timeout: {CONNECTION_TIMEOUT}s | Session timeout: {SESSION_TIMEOUT}s')
    if USE_DATABASE and database_enabled:
        print(f'💾 Storage: Database (persistent)')
    else:
        print(f'💾 Storage: In-memory (volatile)')
    httpd.serve_forever()


def run_tests():
    print('Running quick web_portal tests...')
    # Test statement fetch (best-effort)
    stmt = try_get_statement_from_engine('CUST001') or get_mock_statement('CUST001')
    print('Sample statement (truncated):')
    print(json.dumps({
        'customer_id': stmt.get('customer_id'),
        'total_premium': stmt.get('total_premium'),
        'risk_total': stmt.get('risk_total')
    }, indent=2))
    # Test connectors if available
    try:
        # Load connectors module from file location (works when server.py is run directly)
        import importlib.util
        conn_path = os.path.join(os.path.dirname(__file__), 'connectors.py')
        spec = importlib.util.spec_from_file_location('web_portal.connectors', conn_path)
        if spec and spec.loader:
            connectors = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(connectors)
        else:
            raise ImportError('Cannot load connectors')
        print('\nConnector demo results:')
        res = connectors.demo_validators()
        for k, v in res.items():
            print(f' - {k}:', v.status)
    except Exception as e:
        print('Connector demo skipped:', e)
    print('All tests passed (demo assertions only).')


if __name__ == '__main__':
    import sys

    if '--test' in sys.argv:
        run_tests()
    else:
        run_server()
