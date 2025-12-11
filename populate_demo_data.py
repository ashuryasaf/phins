#!/usr/bin/env python3
"""
Demo script to populate the PHINS admin portal with sample data.
Run this to create demo policies, claims, and underwriting applications.
"""
import requests
import json
from datetime import datetime, timedelta
import random

BASE_URL = "http://localhost:8000"

def login(username, password):
    """Login and get auth token"""
    response = requests.post(f"{BASE_URL}/api/login", 
                           json={"username": username, "password": password})
    if response.ok:
        data = response.json()
        print(f"✓ Logged in as {data['name']} ({data['role']})")
        return data['token']
    print(f"✗ Login failed: {response.text}")
    return None

def create_sample_policy(token, customer_data, policy_data):
    """Create a sample policy with underwriting"""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    payload = {
        **customer_data,
        **policy_data,
        "age": calculate_age(customer_data['customer_dob']),
        "questionnaire": {
            "smoke": random.choice(["yes", "no"]),
            "medical_conditions": random.choice(["yes", "no"]),
            "surgery": "no",
            "hazardous_activities": "no",
            "family_history": random.choice(["yes", "no"]),
            "medications": "None" if random.random() > 0.3 else "Blood pressure medication",
            "height": random.randint(160, 190),
            "weight": random.randint(60, 90)
        }
    }
    
    response = requests.post(f"{BASE_URL}/api/policies/create", headers=headers, json=payload)
    if response.ok:
        data = response.json()
        print(f"✓ Created policy {data['policy']['id']} for {customer_data['customer_name']}")
        return data
    print(f"✗ Failed to create policy: {response.text}")
    return None

def create_sample_claim(token, policy_id, customer_id):
    """Create a sample claim"""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    claim_types = ["medical", "accident", "disability", "property"]
    descriptions = {
        "medical": "Hospital stay for treatment",
        "accident": "Car accident with injuries",
        "disability": "Work-related disability claim",
        "property": "Property damage from fire"
    }
    
    claim_type = random.choice(claim_types)
    payload = {
        "policy_id": policy_id,
        "customer_id": customer_id,
        "type": claim_type,
        "description": descriptions[claim_type],
        "claimed_amount": random.randint(1000, 10000)
    }
    
    response = requests.post(f"{BASE_URL}/api/claims/create", headers=headers, json=payload)
    if response.ok:
        data = response.json()
        print(f"✓ Created claim {data['id']} for policy {policy_id}")
        return data
    print(f"✗ Failed to create claim: {response.text}")
    return None

def approve_underwriting(token, uw_id):
    """Approve an underwriting application"""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"id": uw_id, "approved_by": "Demo Underwriter"}
    
    response = requests.post(f"{BASE_URL}/api/underwriting/approve", headers=headers, json=payload)
    if response.ok:
        print(f"✓ Approved underwriting {uw_id}")
        return True
    return False

def approve_claim(token, claim_id, amount):
    """Approve a claim"""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"id": claim_id, "approved_amount": amount, "approved_by": "Demo Claims Adjuster"}
    
    response = requests.post(f"{BASE_URL}/api/claims/approve", headers=headers, json=payload)
    if response.ok:
        print(f"✓ Approved claim {claim_id}")
        return True
    return False

def pay_claim(token, claim_id):
    """Pay a claim"""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"id": claim_id, "payment_method": "bank_transfer"}
    
    response = requests.post(f"{BASE_URL}/api/claims/pay", headers=headers, json=payload)
    if response.ok:
        data = response.json()
        print(f"✓ Paid claim {claim_id} - Ref: {data['claim']['payment_reference']}")
        return True
    return False

def calculate_age(dob_str):
    """Calculate age from date of birth"""
    dob = datetime.strptime(dob_str, "%Y-%m-%d")
    today = datetime.now()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

def main():
    """Main demo script"""
    print("=" * 60)
    print("PHINS Admin Portal - Sample Data Generator")
    print("=" * 60)
    print()
    
    # Login as admin
    token = login("admin", "admin123")
    if not token:
        print("Failed to login. Make sure the server is running.")
        return
    
    print()
    print("Creating sample policies...")
    print("-" * 60)
    
    # Sample customers and policies
    customers = [
        {
            "customer_name": "John Smith",
            "customer_email": "john.smith@email.com",
            "customer_phone": "+1-555-0101",
            "customer_dob": "1985-03-15"
        },
        {
            "customer_name": "Sarah Johnson",
            "customer_email": "sarah.j@email.com",
            "customer_phone": "+1-555-0102",
            "customer_dob": "1990-07-22"
        },
        {
            "customer_name": "Michael Brown",
            "customer_email": "mbrown@email.com",
            "customer_phone": "+1-555-0103",
            "customer_dob": "1978-11-30"
        },
        {
            "customer_name": "Emily Davis",
            "customer_email": "emily.davis@email.com",
            "customer_phone": "+1-555-0104",
            "customer_dob": "1992-05-18"
        },
        {
            "customer_name": "David Wilson",
            "customer_email": "dwilson@email.com",
            "customer_phone": "+1-555-0105",
            "customer_dob": "1982-09-25"
        }
    ]
    
    policy_types = [
        {"type": "life", "coverage_amount": 250000, "risk_score": "low"},
        {"type": "health", "coverage_amount": 100000, "risk_score": "medium"},
        {"type": "auto", "coverage_amount": 50000, "risk_score": "low"},
        {"type": "property", "coverage_amount": 300000, "risk_score": "medium"},
        {"type": "life", "coverage_amount": 500000, "risk_score": "high"}
    ]
    
    created_policies = []
    
    for customer, policy_type in zip(customers, policy_types):
        result = create_sample_policy(token, customer, policy_type)
        if result:
            created_policies.append(result)
    
    print()
    print("Approving some underwriting applications...")
    print("-" * 60)
    
    # Approve first 3 underwriting applications
    for i, policy_data in enumerate(created_policies[:3]):
        uw_id = policy_data['underwriting']['id']
        approve_underwriting(token, uw_id)
    
    print()
    print("Creating sample claims...")
    print("-" * 60)
    
    # Create claims for approved policies
    created_claims = []
    for policy_data in created_policies[:3]:
        policy_id = policy_data['policy']['id']
        customer_id = policy_data['customer']['id']
        claim = create_sample_claim(token, policy_id, customer_id)
        if claim:
            created_claims.append(claim)
    
    print()
    print("Processing claims...")
    print("-" * 60)
    
    # Approve and pay first claim
    if created_claims:
        claim = created_claims[0]
        approve_claim(token, claim['id'], claim['claimed_amount'] * 0.9)  # Approve 90%
        pay_claim(token, claim['id'])
    
    # Just approve second claim (don't pay yet)
    if len(created_claims) > 1:
        claim = created_claims[1]
        approve_claim(token, claim['id'], claim['claimed_amount'])
    
    print()
    print("=" * 60)
    print("✓ Demo data created successfully!")
    print("=" * 60)
    print()
    print("Summary:")
    print(f"  • Created {len(created_policies)} policies")
    print(f"  • Approved {min(3, len(created_policies))} underwriting applications")
    print(f"  • Created {len(created_claims)} claims")
    print(f"  • Processed 1 claim payment")
    print()
    print("Access the admin portal at: http://localhost:8000/admin-portal.html")
    print("Login with: admin / admin123")
    print()

if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.ConnectionError:
        print("\n✗ Error: Cannot connect to server at http://localhost:8000")
        print("Make sure the server is running: python3 web_portal/server.py")
    except Exception as e:
        print(f"\n✗ Error: {e}")
