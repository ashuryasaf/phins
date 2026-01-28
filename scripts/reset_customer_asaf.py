#!/usr/bin/env python3
"""
Customer Data Reset Script for asaf@assurance.co.il (CUST-ASAF-001)

This script resets the following data for the customer:
- All claims (paid, approved, rejected, pending)
- Health wallet balance and transactions
- Investment account deposits and balance
- Algo trading balance
- Savings pipeline balance
- Medical purchase history (wallet purchases)

RESTRICTED TO: CUST-ASAF-001 (asaf@assurance.co.il) ONLY

Usage:
    python scripts/reset_customer_asaf.py [--dry-run] [--production]

Options:
    --dry-run     Show what would be reset without making changes
    --production  Target production server (default: localhost)
"""

import argparse
import json
import sys
import requests
from datetime import datetime


# Customer details - RESTRICTED TO THIS CUSTOMER ONLY
TARGET_CUSTOMER_ID = 'CUST-ASAF-001'
TARGET_CUSTOMER_EMAIL = 'asaf@assurance.co.il'

# Server URLs
LOCAL_URL = 'http://localhost:5000'
PRODUCTION_URL = 'https://phins-portal-production.up.railway.app'


def get_server_url(production: bool) -> str:
    """Get the appropriate server URL"""
    return PRODUCTION_URL if production else LOCAL_URL


def check_server_health(base_url: str) -> bool:
    """Check if server is healthy"""
    try:
        resp = requests.get(f'{base_url}/api/health', timeout=10)
        health = resp.json()
        print(f"Server Status: {health.get('status')}")
        print(f"Database: {health.get('database')}")
        print(f"Version: {health.get('version')}")
        return health.get('status') == 'healthy'
    except Exception as e:
        print(f"Server health check failed: {e}")
        return False


def get_customer_current_state(base_url: str) -> dict:
    """Get current state of customer data (requires admin auth or test mode)"""
    state = {
        'customer_id': TARGET_CUSTOMER_ID,
        'customer_email': TARGET_CUSTOMER_EMAIL,
        'claims': {'count': 0, 'total_claimed': 0, 'total_approved': 0},
        'health_wallet': {'balance': 0, 'transactions': 0},
        'investments': {'balance': 0, 'deposits': 0},
        'algo_trading': {'balance': 0},
        'medical_purchases': {'count': 0, 'total': 0}
    }
    
    # Try to get data via various endpoints
    try:
        # Get customer summary
        resp = requests.get(f'{base_url}/api/customer/summary?customer_id={TARGET_CUSTOMER_ID}', timeout=10)
        if resp.status_code == 200:
            summary = resp.json()
            print(f"\nCustomer Summary (API):")
            print(f"  Policies: {summary.get('policies_count', 'N/A')}")
            print(f"  Claims: {summary.get('claims_count', 'N/A')}")
            print(f"  Coverage: ${summary.get('total_coverage', 0):,.2f}")
    except Exception as e:
        print(f"Could not fetch customer summary: {e}")
    
    return state


def perform_reset(base_url: str, dry_run: bool = False) -> dict:
    """Perform the customer data reset"""
    
    if dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN MODE - No changes will be made")
        print("=" * 60)
        return {'dry_run': True, 'message': 'No changes made'}
    
    print("\n" + "=" * 60)
    print(f"EXECUTING RESET for {TARGET_CUSTOMER_EMAIL}")
    print("=" * 60)
    
    # Call the reset endpoint
    payload = {
        'customer_id': TARGET_CUSTOMER_ID,
        'keep_ledger': True  # Keep audit trail
    }
    
    try:
        resp = requests.post(
            f'{base_url}/api/admin/reset-customer-account',
            json=payload,
            timeout=30
        )
        
        if resp.status_code == 200:
            result = resp.json()
            print("\n✓ Reset completed successfully!")
            print(f"\nRemoved:")
            removed = result.get('removed', {})
            print(f"  - Policies: {removed.get('policies', 0)}")
            print(f"  - Applications: {removed.get('applications', 0)}")
            print(f"  - Claims: {removed.get('claims', 0)}")
            print(f"  - Bills: {removed.get('bills', 0)}")
            print(f"  - Medical Purchases: {removed.get('medical_purchases', 0)}")
            print(f"  - Medical Purchase Total: ${removed.get('medical_purchase_total', 0):,.2f}")
            
            print(f"\nAccount Resets:")
            print(f"  - Investment: {'✓' if result.get('investment_reset') else 'N/A'}")
            print(f"  - Health Wallet: {'✓' if result.get('wallet_reset') else 'N/A'}")
            print(f"  - Algo Trading: {'✓' if result.get('algo_reset') else 'N/A'}")
            print(f"  - Savings Pipeline: {'✓' if result.get('pipeline_reset') else 'N/A'}")
            
            print(f"\nLedger Preserved:")
            ledger = result.get('ledger_entries', {})
            print(f"  - Transactions: {ledger.get('transactions', 0)}")
            print(f"  - NFT Tokens: {ledger.get('nft_tokens', 0)}")
            
            print(f"\nNFT Token: {result.get('nft_token_id', 'N/A')}")
            print(f"Block Number: {result.get('block_number', 'N/A')}")
            
            return result
        
        elif resp.status_code == 403:
            print("\n✗ Authentication required")
            print("  This endpoint requires admin access.")
            print("  Please authenticate first or run with proper credentials.")
            return {'error': 'Authentication required', 'status': 403}
        
        elif resp.status_code == 404:
            print("\n✗ Customer not found")
            return {'error': 'Customer not found', 'status': 404}
        
        else:
            print(f"\n✗ Reset failed with status {resp.status_code}")
            print(f"  Response: {resp.text}")
            return {'error': resp.text, 'status': resp.status_code}
            
    except requests.exceptions.ConnectionError:
        print("\n✗ Could not connect to server")
        return {'error': 'Connection failed'}
    except Exception as e:
        print(f"\n✗ Reset failed: {e}")
        return {'error': str(e)}


def main():
    parser = argparse.ArgumentParser(
        description=f'Reset customer data for {TARGET_CUSTOMER_EMAIL}'
    )
    parser.add_argument('--dry-run', action='store_true',
                       help='Show what would be reset without making changes')
    parser.add_argument('--production', action='store_true',
                       help='Target production server (default: localhost)')
    
    args = parser.parse_args()
    
    base_url = get_server_url(args.production)
    
    print("=" * 60)
    print("PHINS Customer Data Reset")
    print("=" * 60)
    print(f"Target: {base_url}")
    print(f"Customer: {TARGET_CUSTOMER_EMAIL} ({TARGET_CUSTOMER_ID})")
    print(f"Time: {datetime.now().isoformat()}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    print()
    
    # Security check
    print("SECURITY CHECK:")
    print(f"  - Restricted to customer: {TARGET_CUSTOMER_ID}")
    print(f"  - Email: {TARGET_CUSTOMER_EMAIL}")
    print(f"  - Ledger preserved: YES (audit trail maintained)")
    print()
    
    # Check server health
    print("Checking server health...")
    if not check_server_health(base_url):
        print("\n✗ Server is not healthy. Aborting.")
        sys.exit(1)
    
    # Get current state
    print("\nChecking current customer state...")
    get_customer_current_state(base_url)
    
    # Confirm if live mode
    if not args.dry_run:
        print("\n" + "!" * 60)
        print("WARNING: This will permanently reset customer data!")
        print("!" * 60)
        
        confirm = input("\nType 'RESET' to confirm: ")
        if confirm != 'RESET':
            print("\nAborted.")
            sys.exit(0)
    
    # Perform reset
    result = perform_reset(base_url, args.dry_run)
    
    print("\n" + "=" * 60)
    print("RESET COMPLETE")
    print("=" * 60)
    
    return 0 if result.get('success', False) or result.get('dry_run', False) else 1


if __name__ == '__main__':
    sys.exit(main())
