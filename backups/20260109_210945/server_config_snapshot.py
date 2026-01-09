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

# ==============================================================================
# CASE-INSENSITIVE STATUS HELPERS (for data integrity across pipeline)
# ==============================================================================
def status_eq(item: Dict, *statuses: str) -> bool:
    """
    Case-insensitive status check for an item.
    Handles both exact matches and space/underscore variations.
    Example: status_eq(claim, 'approved', 'paid') checks if status is 'Approved', 'approved', 'APPROVED', etc.
    """
    item_status = (item.get('status') or '').lower().replace(' ', '_')
    return item_status in [s.lower().replace(' ', '_') for s in statuses]

def status_in(item: Dict, statuses: list) -> bool:
    """
    Case-insensitive check if item's status is in a list of statuses.
    Example: status_in(claim, ['pending', 'under_review'])
    """
    item_status = (item.get('status') or '').lower().replace(' ', '_')
    return item_status in [s.lower().replace(' ', '_') for s in statuses]

def get_status_lower(item: Dict) -> str:
    """Get item's status in lowercase with spaces converted to underscores."""
    return (item.get('status') or '').lower().replace(' ', '_')

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
        # This is required for local runs/tests where the DB starts empty.
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

# Claim files storage - stores uploaded documents for claims
# Indexed by file_id -> {claim_id, file_name, file_type, file_size, file_data (base64), uploaded_at}
CLAIM_FILES: Dict[str, Dict[str, Any]] = {}  # file_id -> file data with base64 content

# Underwriting files storage - stores documents uploaded with insurance applications
# Indexed by file_id -> {application_id, file_name, file_type, file_size, file_data (base64), uploaded_at}
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
# Managed via Admin Media Dashboard (/admin-media.html)
# Indexed by asset_id -> {id, name, type, format, size, url, data, thumbnail, source, uploaded_at, uploaded_by}
MEDIA_ASSETS: Dict[str, Dict[str, Any]] = {}

# ========== PHINS MAIN BALANCE SHEET (GENERAL RESERVES) ==========
# Central company balance sheet for all financial operations
# Accessible by: admin, accountant, underwriter, claims_adjuster
PHINS_BALANCE_SHEET: Dict[str, Any] = {
    'account_id': 'PHINS-MAIN-001',
    'name': 'PHINS General Reserves',
    'created_at': None,  # Set on first use
    'last_updated': None,
    
    # Main account balances
    'claims_reserve': 3500000.00,      # $3.5M for claims payments
    'operating_reserve': 0.00,          # General operating funds
    'supplier_reserve': 0.00,           # Funds for supplier payments
    'investment_reserve': 0.00,         # Company investment funds
    
    # Revenue tracking
    'total_revenue': 0.00,
    'revenue_breakdown': {
        'premium_income': 0.00,         # Premium payments from customers
        'management_fees': 0.00,        # Management fees charged
        'underwriting_fees': 0.00,      # Underwriting service fees
        'investment_earnings': 0.00,    # Returns from company investments
        'late_fees': 0.00,              # Late payment penalties
        'other_income': 0.00            # Miscellaneous income
    },
    
    # Expense tracking
    'total_expenses': 0.00,
    'expense_breakdown': {
        'claims_paid': 0.00,            # Claims paid to customers
        'supplier_payments': 0.00,      # Payments to suppliers
        'operating_costs': 0.00,        # Operating expenses
        'commissions': 0.00,            # Agent commissions
        'reinsurance': 0.00,            # Reinsurance premiums
        'other_expenses': 0.00          # Miscellaneous expenses
    },
    
    # Transaction history
    'transactions': [],  # List of all balance sheet transactions
    
    # Audit trail
    'audit_log': []  # List of all changes with timestamps and actors
}

def initialize_balance_sheet():
    """Initialize the PHINS balance sheet with default values if not already set"""
    global PHINS_BALANCE_SHEET
    if PHINS_BALANCE_SHEET.get('created_at') is None:
        PHINS_BALANCE_SHEET['created_at'] = datetime.now().isoformat()
        PHINS_BALANCE_SHEET['last_updated'] = datetime.now().isoformat()
        
        # Record initial capital deposit
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
    """
    Record a transaction on the PHINS main balance sheet.
    
    tx_type: 'revenue', 'expense', 'transfer', 'adjustment'
    category: 'claims_reserve', 'premium_income', 'claims_paid', etc.
    """
    global PHINS_BALANCE_SHEET
    
    tx_id = f"BS-{tx_type.upper()[:3]}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{random.randint(1000, 9999)}"
    
    # Update the appropriate balance
    if tx_type == 'revenue':
        if category in PHINS_BALANCE_SHEET['revenue_breakdown']:
            PHINS_BALANCE_SHEET['revenue_breakdown'][category] += amount
        PHINS_BALANCE_SHEET['total_revenue'] += amount
        PHINS_BALANCE_SHEET['operating_reserve'] += amount
    elif tx_type == 'expense':
        if category in PHINS_BALANCE_SHEET['expense_breakdown']:
            PHINS_BALANCE_SHEET['expense_breakdown'][category] += amount
        PHINS_BALANCE_SHEET['total_expenses'] += amount
        
        # Deduct from appropriate reserve
        if category == 'claims_paid':
            PHINS_BALANCE_SHEET['claims_reserve'] -= amount
        elif category == 'supplier_payments':
            PHINS_BALANCE_SHEET['supplier_reserve'] -= amount
        else:
            PHINS_BALANCE_SHEET['operating_reserve'] -= amount
    elif tx_type == 'transfer':
        # Internal transfer between reserves - handled by caller
        pass
    elif tx_type == 'adjustment':
        # Manual adjustment - handled by caller
        pass
    
    # Calculate total balance
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
