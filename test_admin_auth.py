#!/usr/bin/env python3
"""Test admin portal authentication"""
import requests
import json
import sys

# Test URL
BASE_URL = "http://localhost:8000"

# Demo accounts from server.py
USERS = {
    'admin': {'password': 'admin123', 'role': 'admin', 'name': 'Admin User'},
    'underwriter': {'password': 'under123', 'role': 'underwriter', 'name': 'John Underwriter'},
    'claims_adjuster': {'password': 'claims123', 'role': 'claims', 'name': 'Jane Claims'},
    'accountant': {'password': 'acct123', 'role': 'accountant', 'name': 'Bob Accountant'}
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
            headers={"Content-Type": "application/json"}
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
    response = requests.get(f"{BASE_URL}/admin-portal.html")
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
print("2. Use credentials: admin / admin123")
print("3. Or use any of the demo accounts listed above")
