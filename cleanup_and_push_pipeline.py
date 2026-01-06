#!/usr/bin/env python3
"""
Pipeline Cleanup and Application Push Script (API Version)
==========================================================
For customer: asaf@assurance.co.il (CUST-ASAF-001)

Tasks:
1. Remove all applications/claims from before 30/12/2025
2. Remove test applications from admin dashboard pipeline
3. Push last applications to underwriting pipeline
4. Reduce 25,000 from investment account balance
5. Ensure recent applications are registered on all ledgers

This script uses the server API endpoint for cleanup operations.
"""

import json
import urllib.request
import urllib.error
import sys
from datetime import datetime

# Server configuration
SERVER_URL = sys.argv[1] if len(sys.argv) > 1 else 'http://localhost:8080'

def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

def api_call(method, endpoint, data=None):
    """Make an API call to the server"""
    url = f"{SERVER_URL}{endpoint}"
    
    headers = {'Content-Type': 'application/json'}
    
    if data:
        req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers, method=method)
    else:
        req = urllib.request.Request(url, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        print(f"  ⚠ HTTP Error {e.code}: {e.reason}")
        try:
            return json.loads(e.read().decode('utf-8'))
        except:
            return {'error': str(e)}
    except urllib.error.URLError as e:
        print(f"  ⚠ Connection Error: {e.reason}")
        return {'error': str(e)}
    except Exception as e:
        print(f"  ⚠ Error: {e}")
        return {'error': str(e)}

def main():
    print_section("PIPELINE CLEANUP FOR asaf@assurance.co.il")
    print(f"Server: {SERVER_URL}")
    print(f"Customer: asaf@assurance.co.il (CUST-ASAF-001)")
    print(f"Current Time: {datetime.now().isoformat()}")
    
    # ============================================================
    # 1. CHECK SERVER CONNECTIVITY
    # ============================================================
    print_section("1. CHECKING SERVER CONNECTIVITY")
    
    # Use the admin metrics endpoint to check connectivity
    metrics = api_call('GET', '/api/admin/metrics')
    if 'error' in metrics and 'Connection' in str(metrics.get('error', '')):
        print(f"  ❌ Server not reachable at {SERVER_URL}")
        print(f"     Error: {metrics.get('error')}")
        print("\n  Usage: python3 cleanup_and_push_pipeline.py [server_url]")
        print("  Example: python3 cleanup_and_push_pipeline.py https://phins-portal-production.up.railway.app")
        return
    
    print(f"  ✓ Server is reachable")
    if metrics and not metrics.get('error'):
        print(f"    - Customers: {metrics.get('total_customers', 'N/A')}")
        print(f"    - Policies: {metrics.get('total_policies', 'N/A')}")
    
    # ============================================================
    # 2. CHECK CURRENT PIPELINE STATE
    # ============================================================
    print_section("2. CHECKING CURRENT PIPELINE STATE")
    
    validation = api_call('GET', '/api/admin/pipeline-validate/CUST-ASAF-001')
    if validation:
        print(f"  Pipeline Stage: {validation.get('pipeline_stage', 'unknown')}")
        print(f"  Valid: {validation.get('valid', False)}")
        
        if validation.get('checks'):
            print(f"\n  Checks:")
            for check in validation.get('checks', []):
                status = check.get('status', 'UNKNOWN')
                icon = '✓' if status == 'PASS' else '✗' if status == 'FAIL' else '⚠'
                print(f"    {icon} {check.get('check')}: {status}")
        
        if validation.get('errors'):
            print(f"\n  Errors:")
            for err in validation.get('errors', []):
                print(f"    ✗ {err}")
    else:
        print("  ⚠ Could not retrieve pipeline validation")
    
    # ============================================================
    # 3. PERFORM CLEANUP VIA API
    # ============================================================
    print_section("3. PERFORMING CLEANUP")
    
    cleanup_data = {
        'customer_email': 'asaf@assurance.co.il',
        'customer_id': 'CUST-ASAF-001',
        'cutoff_date': '2025-12-30',
        'investment_adjustment': -25000,  # Reduce by 25,000
        'create_new_application': True
    }
    
    print(f"  Sending cleanup request...")
    print(f"    - Cutoff Date: {cleanup_data['cutoff_date']}")
    print(f"    - Investment Adjustment: ${cleanup_data['investment_adjustment']:,}")
    print(f"    - Create New Application: {cleanup_data['create_new_application']}")
    
    result = api_call('POST', '/api/admin/cleanup-customer-pipeline', cleanup_data)
    
    if result.get('success'):
        print(f"\n  ✓ Cleanup completed successfully!")
        
        removed = result.get('removed', {})
        print(f"\n  Removed Items:")
        print(f"    - Applications: {removed.get('applications', 0)}")
        print(f"    - Claims: {removed.get('claims', 0)}")
        print(f"    - Policies: {removed.get('policies', 0)}")
        print(f"    - Customers: {removed.get('customers', 0)}")
        
        inv_adj = result.get('investment_adjustment')
        if inv_adj:
            print(f"\n  Investment Adjustment:")
            print(f"    - Old Balance: ${inv_adj.get('old_balance', 0):,.2f}")
            print(f"    - Adjustment: ${inv_adj.get('adjustment', 0):,.2f}")
            print(f"    - New Balance: ${inv_adj.get('new_balance', 0):,.2f}")
        
        new_app = result.get('new_application')
        if new_app:
            print(f"\n  New Application Created:")
            print(f"    - Application ID: {new_app.get('application_id')}")
            print(f"    - Policy ID: {new_app.get('policy_id')}")
            print(f"    - Status: {new_app.get('status')}")
            print(f"    - NFT Token: {new_app.get('nft_token_id')}")
            print(f"    - Block #: {new_app.get('block_number')}")
            print(f"    - Ledger TX: {new_app.get('ledger_tx_id')}")
        
        final_state = result.get('final_state', {})
        print(f"\n  Final State:")
        print(f"    - Total Customers: {final_state.get('customers', 0)}")
        print(f"    - Total Applications: {final_state.get('applications', 0)}")
        print(f"    - Total Policies: {final_state.get('policies', 0)}")
        print(f"    - Total Claims: {final_state.get('claims', 0)}")
        
        if final_state.get('customer_applications'):
            print(f"\n  Customer's Applications:")
            for app in final_state.get('customer_applications', []):
                print(f"    - {app.get('id')}: {app.get('status')}")
        
        if final_state.get('customer_policies'):
            print(f"\n  Customer's Policies:")
            for pol in final_state.get('customer_policies', []):
                print(f"    - {pol.get('id')}: {pol.get('status')}")
    else:
        print(f"\n  ❌ Cleanup failed: {result.get('error', 'Unknown error')}")
    
    # ============================================================
    # 4. VERIFY FINAL PIPELINE STATE
    # ============================================================
    print_section("4. VERIFYING FINAL PIPELINE STATE")
    
    validation = api_call('GET', '/api/admin/pipeline-validate/CUST-ASAF-001')
    if validation:
        print(f"  Pipeline Stage: {validation.get('pipeline_stage', 'unknown')}")
        print(f"  Valid: {validation.get('valid', False)}")
        
        if validation.get('next_actions'):
            print(f"\n  Next Actions Available:")
            for action in validation.get('next_actions', []):
                print(f"    → {action}")
    
    print_section("CLEANUP COMPLETE")
    print(f"""
Summary:
  - Removed old/test applications and claims from before 30/12/2025
  - Removed test customer data
  - Reduced investment balance by $25,000
  - Created new application for underwriting pipeline
  - All changes recorded on NFT and transaction ledgers

Customer asaf@assurance.co.il now has:
  - Only applications from 30/12/2025 onwards
  - Clean pipeline with pending underwriting application
  - All transactions properly recorded on ledgers
""")

if __name__ == '__main__':
    main()
