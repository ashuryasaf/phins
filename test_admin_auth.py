#!/usr/bin/env python3
"""Test admin portal authentication"""
import os
import requests
import json
import sys

# Test URL
BASE_URL = "http://localhost:8000"
REQUEST_TIMEOUT = 10

# Demo accounts - passwords loaded from environment variables
USERS = {
    'admin': {'password': os.environ.get('PHINS_ADMIN_PASSWORD', ''), 'role': 'admin', 'name': 'Admin User'},
    'underwriter': {'password': os.environ.get('PHINS_UNDERWRITER_PASSWORD', ''), 'role': 'underwriter', 'name': 'John Underwriter'},
    'claims_adjuster': {'password': os.environ.get('PHINS_CLAIMS_PASSWORD', ''), 'role': 'claims', 'name': 'Jane Claims'},
    'accountant': {'password': os.environ.get('PHINS_ACCOUNTANT_PASSWORD', ''), 'role': 'accountant', 'name': 'Bob Accountant'}
}

print("Testing PHINS Admin Portal Authentication")
print("=" * 50)

# Test each account
for username, user_data in USERS.items():
    print(f"\nTesting: {username} / {user_data['password']}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/api/login",
            json={"username": username, "password": user_data['password']},
            headers={"Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        
        if response.status_code == 200:
            data = response.json()
            print(f"  ✅ SUCCESS")
            print(f"  Token: {data.get('token', 'N/A')[:30]}...")
            print(f"  Role: {data.get('role', 'N/A')}")
            print(f"  Name: {data.get('name', 'N/A')}")
        else:
            print(f"  ❌ FAILED: {response.status_code}")
            print(f"  Response: {response.text}")
    except Exception as e:
        print(f"  ❌ ERROR: {str(e)}")

print("\n" + "=" * 50)
print("Testing admin portal page access...")
try:
    response = requests.get(f"{BASE_URL}/admin-portal.html", timeout=REQUEST_TIMEOUT)
    if response.status_code == 200:
        print("✅ admin-portal.html is accessible")
        if "PHINS Admin Portal" in response.text:
            print("✅ Page content looks correct")
    else:
        print(f"❌ Page returned status: {response.status_code}")
except Exception as e:
    print(f"❌ ERROR accessing page: {str(e)}")

print("\n" + "=" * 50)
print("\n📌 To access the admin portal:")
print("1. Open: http://localhost:8000/admin-portal.html")
print("2. Use credentials configured via environment variables (see SECURITY.md)")
print("3. Or use any of the demo accounts listed above")
