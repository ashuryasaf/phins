#!/usr/bin/env python3
"""
Visual demonstration of where customer data goes in PHINS system
"""
import sys
sys.path.insert(0, '/workspaces/phins')

from web_portal import server
import json
from datetime import datetime

def print_storage_state(title):
    """Print current state of all storage dictionaries"""
    print("\n" + "="*70)
    print(f"📊 {title}")
    print("="*70)
    
    print(f"\n📁 CUSTOMERS Dictionary: {len(server.CUSTOMERS)} entries")
    if server.CUSTOMERS:
        for cust_id, cust in server.CUSTOMERS.items():
            print(f"  ├─ {cust_id}")
            print(f"  │  ├─ Name: {cust.get('name')}")
            print(f"  │  ├─ Email: {cust.get('email')}")
            print(f"  │  └─ Created: {cust.get('created_date')}")
    else:
        print("  └─ (empty)")
    
    print(f"\n📋 UNDERWRITING_APPLICATIONS Dictionary: {len(server.UNDERWRITING_APPLICATIONS)} entries")
    if server.UNDERWRITING_APPLICATIONS:
        for uw_id, uw in server.UNDERWRITING_APPLICATIONS.items():
            print(f"  ├─ {uw_id}")
            print(f"  │  ├─ Customer: {uw.get('customer_id')}")
            print(f"  │  ├─ Status: {uw.get('status')}")
            print(f"  │  ├─ Risk: {uw.get('risk_assessment')}")
            print(f"  │  └─ Submitted: {uw.get('submitted_date')}")
    else:
        print("  └─ (empty)")
    
    print(f"\n📄 POLICIES Dictionary: {len(server.POLICIES)} entries")
    if server.POLICIES:
        for pol_id, pol in server.POLICIES.items():
            print(f"  ├─ {pol_id}")
            print(f"  │  ├─ Customer: {pol.get('customer_id')}")
            print(f"  │  ├─ Type: {pol.get('type')}")
            print(f"  │  ├─ Coverage: ${pol.get('coverage_amount'):,}")
            print(f"  │  ├─ Status: {pol.get('status')}")
            print(f"  │  └─ Premium: ${pol.get('annual_premium')}/year")
    else:
        print("  └─ (empty)")
    
    # Dashboard stats
    pending = sum(1 for u in server.UNDERWRITING_APPLICATIONS.values() if u.get('status') == 'pending')
    print(f"\n📈 Dashboard Stats:")
    print(f"  ├─ Total Customers: {len(server.CUSTOMERS)}")
    print(f"  ├─ Pending Applications: {pending}")
    print(f"  ├─ Total Policies: {len(server.POLICIES)}")
    print(f"  └─ Active Policies: {sum(1 for p in server.POLICIES.values() if p.get('status') == 'active')}")


def simulate_customer_application():
    """Simulate what SHOULD happen when customer submits application"""
    print("\n" + "="*70)
    print("🎬 SIMULATING CUSTOMER APPLICATION FLOW")
    print("="*70)
    
    # Step 1: Customer fills form
    print("\n✅ Step 1: Customer fills application form at /apply.html")
    print("   - Personal info: John Doe, john@example.com")
    print("   - Coverage: Life insurance, $250,000")
    print("   - Health: Non-smoker, good health")
    
    # Step 2: Form submission (SHOULD create records)
    print("\n✅ Step 2: Customer clicks 'Submit Application'")
    print("   - POST to /api/submit-quote")
    print("   - Form data sent as multipart/form-data")
    
    # Step 3: Server SHOULD process (but currently doesn't)
    print("\n❌ Step 3: Server processes request (BROKEN)")
    print("   Current behavior:")
    print("   - Receives form data")
    print("   - Returns success message")
    print("   - ⚠️  DOES NOT parse form data")
    print("   - ⚠️  DOES NOT create CUSTOMERS entry")
    print("   - ⚠️  DOES NOT create UNDERWRITING_APPLICATIONS entry")
    print("   - ⚠️  DOES NOT create POLICIES entry")
    
    # Step 4: What SHOULD happen
    print("\n✅ Step 4: What SHOULD happen:")
    print("   - Parse multipart form data")
    print("   - Extract all fields from form")
    print("   - Create customer record:")
    
    # Manually create what should be created
    customer_id = "CUST-99999"
    server.CUSTOMERS[customer_id] = {
        'id': customer_id,
        'name': 'John Doe',
        'email': 'john@example.com',
        'phone': '+1-555-123-4567',
        'dob': '1985-05-15',
        'created_date': datetime.now().isoformat()
    }
    print(f"     ✓ CUSTOMERS['{customer_id}'] created")
    
    # Create underwriting application
    uw_id = f"UW-{datetime.now().strftime('%Y%m%d')}-9999"
    server.UNDERWRITING_APPLICATIONS[uw_id] = {
        'id': uw_id,
        'customer_id': customer_id,
        'policy_id': 'POL-20251212-9999',
        'status': 'pending',
        'risk_assessment': 'low',
        'medical_exam_required': False,
        'questionnaire_responses': {
            'smoking': 'no',
            'chronic_conditions': 'none',
            'family_history': 'good'
        },
        'submitted_date': datetime.now().isoformat()
    }
    print(f"     ✓ UNDERWRITING_APPLICATIONS['{uw_id}'] created")
    
    # Create policy
    policy_id = 'POL-20251212-9999'
    server.POLICIES[policy_id] = {
        'id': policy_id,
        'customer_id': customer_id,
        'type': 'life',
        'coverage_amount': 250000,
        'annual_premium': 1200,
        'monthly_premium': 100,
        'status': 'pending_underwriting',
        'underwriting_id': uw_id,
        'created_date': datetime.now().isoformat()
    }
    print(f"     ✓ POLICIES['{policy_id}'] created")
    
    print("\n✅ Step 5: Admin dashboard now shows:")
    print("   - Pending Applications: 1")
    print("   - Can view application details")
    print("   - Can approve/reject application")


def demonstrate_approval_flow():
    """Show what happens after approval"""
    print("\n" + "="*70)
    print("🎬 AFTER UNDERWRITER APPROVES")
    print("="*70)
    
    # Find the pending application
    pending_apps = [u for u in server.UNDERWRITING_APPLICATIONS.values() if u.get('status') == 'pending']
    if pending_apps:
        uw_app = pending_apps[0]
        uw_id = uw_app['id']
        policy_id = uw_app['policy_id']
        
        print(f"\n✅ Underwriter approves application {uw_id}")
        
        # Approve it
        server.UNDERWRITING_APPLICATIONS[uw_id]['status'] = 'approved'
        server.UNDERWRITING_APPLICATIONS[uw_id]['decision_date'] = datetime.now().isoformat()
        print(f"   - Status changed: pending → approved")
        
        # Update policy
        if policy_id in server.POLICIES:
            server.POLICIES[policy_id]['status'] = 'active'
            server.POLICIES[policy_id]['approval_date'] = datetime.now().isoformat()
            print(f"   - Policy {policy_id} activated")
        
        print(f"\n✅ NOW billing can be created:")
        print(f"   - Policy is active")
        print(f"   - Premium: ${server.POLICIES[policy_id]['annual_premium']}/year")
        print(f"   - Can generate invoices")
        print(f"   - Can accept payments")


def main():
    """Main demonstration"""
    print("\n" + "🛡️ "*35)
    print("PHINS CUSTOMER DATA FLOW DEMONSTRATION")
    print("🛡️ "*35)
    
    # Show initial state (empty)
    print_storage_state("INITIAL STATE (After Server Start)")
    
    # Simulate what should happen
    simulate_customer_application()
    
    # Show state after simulation
    print_storage_state("STATE AFTER CUSTOMER APPLICATION (Simulated)")
    
    # Show approval flow
    demonstrate_approval_flow()
    
    # Show final state
    print_storage_state("FINAL STATE (After Approval)")
    
    # Summary
    print("\n" + "="*70)
    print("📝 SUMMARY")
    print("="*70)
    print("""
WHERE CUSTOMER DATA IS STORED:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

File: web_portal/server.py
Lines: 38-41

Storage Dictionaries:
  ├─ CUSTOMERS = {}                    # Customer profiles
  ├─ UNDERWRITING_APPLICATIONS = {}    # Application submissions  
  ├─ POLICIES = {}                     # Insurance policies
  └─ CLAIMS = {}                       # Claims records

Data Flow:
  1. Customer fills form → /apply.html
  2. Submits → POST /api/submit-quote
  3. Server SHOULD create entries in above dictionaries
  4. Dashboard reads from dictionaries to show pending applications
  5. Underwriter approves → status changes
  6. Billing created for active policies

Current Issue:
  ⚠️  /api/submit-quote does NOT create dictionary entries
  ⚠️  Data is lost after submission
  ⚠️  Dashboard shows 0 pending applications
  ⚠️  No billing is created (because no active policy exists)

Fix Required:
  ✓ Implement proper form parsing in handle_quote_submission()
  ✓ Create CUSTOMERS, UNDERWRITING_APPLICATIONS, POLICIES entries
  ✓ Return application ID to customer for tracking

File to Fix: web_portal/server.py, line 939 (handle_quote_submission method)
""")
    
    print("\n" + "="*70)
    print("✅ Test complete - Data storage locations documented above")
    print("="*70 + "\n")


if __name__ == '__main__':
    main()
