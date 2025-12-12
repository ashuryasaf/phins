#!/usr/bin/env python3
"""
Test customer application flow to trace where data is stored
"""
import sys
import json
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, '/workspaces/phins')

def test_customer_validation():
    """Test customer validation data structure"""
    print("=" * 60)
    print("TESTING CUSTOMER VALIDATION FLOW")
    print("=" * 60)
    
    from customer_validation import Customer, HealthAssessment, IdentificationDocument, Gender, SmokingStatus, PersonalStatus, DocumentType
    from datetime import date
    
    # Create a test customer with proper structure
    customer = Customer(
        first_name="John",
        last_name="Doe",
        gender=Gender.MALE,
        birthdate=date(1985, 5, 15),
        identification=IdentificationDocument(
            document_type=DocumentType.PASSPORT,
            document_id="P12345678",
            issue_date=date(2020, 1, 1),
            expiry_date=date(2030, 1, 1)
        ),
        smoking_status=SmokingStatus.NON_SMOKER,
        personal_status=PersonalStatus.SINGLE,
        address="123 Main St",
        city="Anytown",
        state_province="CA",
        postal_code="12345",
        health_assessment=HealthAssessment(
            condition_level=3,
            assessment_date=datetime.now()
        ),
        phone="+1-555-123-4567",
        email="john.doe@example.com"
    )
    
    print("\n✓ Customer object created successfully")
    print(f"  Name: {customer.full_name}")
    print(f"  Email: {customer.email}")
    print(f"  Age: {customer.age}")
    print(f"  Health: {customer.health_assessment.get_condition_description()}")
    
    # Get summary (this is like validation)
    summary = customer.get_summary()
    print(f"\n✓ Customer summary generated: {len(summary)} fields")
    print(f"  Health risk score: {summary['health_risk_score']:.2f}")
    print(f"  Requires medical review: {summary['requires_medical_review']}")
    
    return customer, summary


def test_underwriting_application():
    """Test underwriting application creation"""
    print("\n" + "=" * 60)
    print("TESTING UNDERWRITING APPLICATION")
    print("=" * 60)
    
    print("\n✓ Skipping underwriting assistant (requires assistant_id)")
    print("  This module creates underwriting decisions after assessment")
    
    return None


def test_server_storage():
    """Test server storage mechanism"""
    print("\n" + "=" * 60)
    print("TESTING SERVER STORAGE")
    print("=" * 60)
    
    # Import server module
    from web_portal import server
    
    print(f"\n✓ Server module loaded")
    print(f"\nStorage Dictionaries:")
    print(f"  CUSTOMERS: {len(server.CUSTOMERS)} entries")
    print(f"  POLICIES: {len(server.POLICIES)} entries")
    print(f"  UNDERWRITING_APPLICATIONS: {len(server.UNDERWRITING_APPLICATIONS)} entries")
    print(f"  CLAIMS: {len(server.CLAIMS)} entries")
    
    # Simulate creating a customer
    customer_id = "CUST-TEST001"
    server.CUSTOMERS[customer_id] = {
        'id': customer_id,
        'name': 'Test Customer',
        'email': 'test@example.com',
        'phone': '+1-555-999-8888',
        'dob': '1985-05-15',
        'created_date': datetime.now().isoformat()
    }
    
    print(f"\n✓ Test customer added to CUSTOMERS dict")
    print(f"  Customer ID: {customer_id}")
    print(f"  Data: {json.dumps(server.CUSTOMERS[customer_id], indent=2)}")
    
    # Simulate creating underwriting application
    uw_id = f"UW-{datetime.now().strftime('%Y%m%d')}-9999"
    server.UNDERWRITING_APPLICATIONS[uw_id] = {
        'id': uw_id,
        'customer_id': customer_id,
        'status': 'pending',
        'risk_assessment': 'low',
        'submitted_date': datetime.now().isoformat()
    }
    
    print(f"\n✓ Test underwriting application added")
    print(f"  Application ID: {uw_id}")
    print(f"  Status: pending")
    
    # Check dashboard stats
    print(f"\n✓ Dashboard should show:")
    pending_count = sum(1 for u in server.UNDERWRITING_APPLICATIONS.values() 
                       if u.get('status') == 'pending')
    print(f"  Pending applications: {pending_count}")
    
    return customer_id, uw_id


def test_data_retrieval():
    """Test retrieving customer data"""
    print("\n" + "=" * 60)
    print("TESTING DATA RETRIEVAL")
    print("=" * 60)
    
    from web_portal import server
    
    # List all customers
    print(f"\nAll Customers in CUSTOMERS dict:")
    for cust_id, cust_data in server.CUSTOMERS.items():
        print(f"  {cust_id}: {cust_data.get('name')} ({cust_data.get('email')})")
    
    # List all underwriting applications
    print(f"\nAll Underwriting Applications:")
    for uw_id, uw_data in server.UNDERWRITING_APPLICATIONS.items():
        print(f"  {uw_id}:")
        print(f"    Customer: {uw_data.get('customer_id')}")
        print(f"    Status: {uw_data.get('status')}")
        print(f"    Submitted: {uw_data.get('submitted_date')}")


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("PHINS CUSTOMER DATA FLOW TEST")
    print("=" * 60)
    
    try:
        # Test 1: Customer validation
        customer, customer_dict = test_customer_validation()
        
        # Test 2: Underwriting
        decision = test_underwriting_application()
        
        # Test 3: Server storage
        customer_id, uw_id = test_server_storage()
        
        # Test 4: Data retrieval
        test_data_retrieval()
        
        print("\n" + "=" * 60)
        print("SUMMARY - WHERE CLIENT DATA IS STORED")
        print("=" * 60)
        print("""
1. IN-MEMORY STORAGE (web_portal/server.py):
   - CUSTOMERS dictionary: Customer profile data
     * Keys: customer_id (e.g., 'CUST-12345')
     * Values: {id, name, email, phone, dob, created_date}
   
   - UNDERWRITING_APPLICATIONS dictionary: Application status
     * Keys: application_id (e.g., 'UW-20251212-1234')
     * Values: {id, customer_id, status, risk_assessment, submitted_date}
   
   - POLICIES dictionary: Approved policies
     * Keys: policy_id (e.g., 'POL-20251212-5678')
     * Values: {id, customer_id, type, coverage_amount, status}

2. VALIDATION FLOW:
   - Customer fills form → /api/submit-quote (multipart form)
   - Server parses → Creates Customer object (customer_validation.py)
   - Underwriting assessment → UnderwritingAssistant
   - Data stored in → CUSTOMERS + UNDERWRITING_APPLICATIONS dicts
   - Dashboard shows → Pending applications count from UNDERWRITING_APPLICATIONS

3. BILLING CREATION:
   - Happens AFTER underwriting approval
   - Triggered by: /api/underwriting/approve endpoint
   - Policy status changes: pending_underwriting → active
   - Then billing can be created for the active policy

⚠️  ISSUE IDENTIFIED:
   The /api/submit-quote endpoint currently returns a success message
   but does NOT actually store the customer data in CUSTOMERS or 
   UNDERWRITING_APPLICATIONS dictionaries! 
   
   The endpoint at line 939 (handle_quote_submission) just returns
   a success message without parsing the form data or creating records.
   
   This is why you see no pending applications on dashboard!
        """)
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
