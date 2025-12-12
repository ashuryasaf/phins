#!/usr/bin/env python3
"""
Test the fixed endpoint by creating sample applications
"""
import sys
import os
sys.path.insert(0, '/workspaces/phins')

# Import the actual server module to modify its global dictionaries
import web_portal.server as server
from datetime import datetime
import random

def create_test_applications():
    """Create some test applications to demonstrate the fix"""
    print("=" * 70)
    print("Creating test applications to demonstrate the fix...")
    print("=" * 70)
    
    test_customers = [
        {
            'first_name': 'John',
            'last_name': 'Doe',
            'email': 'john.doe@example.com',
            'phone': '+1-555-123-4567',
            'dob': '1985-05-15',
            'gender': 'male',
            'coverage': 250000,
            'policy_type': 'life',
            'risk': 'low'
        },
        {
            'first_name': 'Jane',
            'last_name': 'Smith',
            'email': 'jane.smith@example.com',
            'phone': '+1-555-234-5678',
            'dob': '1990-08-20',
            'gender': 'female',
            'coverage': 500000,
            'policy_type': 'disability',
            'risk': 'medium'
        },
        {
            'first_name': 'Robert',
            'last_name': 'Johnson',
            'email': 'robert.j@example.com',
            'phone': '+1-555-345-6789',
            'dob': '1978-03-12',
            'gender': 'male',
            'coverage': 1000000,
            'policy_type': 'health',
            'risk': 'high'
        }
    ]
    
    created = []
    for idx, customer_data in enumerate(test_customers, 1):
        # Generate IDs
        customer_id = f"CUST-{random.randint(10000, 99999)}"
        policy_id = f"POL-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
        uw_id = f"UW-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
        
        # Create customer
        server.CUSTOMERS[customer_id] = {
            'id': customer_id,
            'name': f"{customer_data['first_name']} {customer_data['last_name']}",
            'first_name': customer_data['first_name'],
            'last_name': customer_data['last_name'],
            'email': customer_data['email'],
            'phone': customer_data['phone'],
            'dob': customer_data['dob'],
            'gender': customer_data['gender'],
            'created_date': datetime.now().isoformat()
        }
        
        # Create underwriting application
        server.UNDERWRITING_APPLICATIONS[uw_id] = {
            'id': uw_id,
            'policy_id': policy_id,
            'customer_id': customer_id,
            'status': 'pending',
            'risk_assessment': customer_data['risk'],
            'medical_exam_required': customer_data['risk'] == 'high',
            'questionnaire_responses': {
                'smoking': 'No' if customer_data['risk'] == 'low' else 'Yes',
                'health_conditions': 'None' if customer_data['risk'] != 'high' else 'Diabetes',
                'medications': 'None',
                'family_history': 'Good'
            },
            'submitted_date': datetime.now().isoformat()
        }
        
        # Create policy
        base_premium = {
            'life': 1200,
            'health': 800,
            'disability': 1500
        }.get(customer_data['policy_type'], 1000)
        
        server.POLICIES[policy_id] = {
            'id': policy_id,
            'customer_id': customer_id,
            'type': customer_data['policy_type'],
            'coverage_amount': customer_data['coverage'],
            'annual_premium': base_premium,
            'monthly_premium': round(base_premium / 12, 2),
            'status': 'pending_underwriting',
            'underwriting_id': uw_id,
            'risk_score': customer_data['risk'],
            'created_date': datetime.now().isoformat()
        }
        
        created.append({
            'customer_id': customer_id,
            'uw_id': uw_id,
            'policy_id': policy_id,
            'name': f"{customer_data['first_name']} {customer_data['last_name']}"
        })
        
        print(f"\n✅ Application #{idx} created:")
        print(f"   Customer: {customer_data['first_name']} {customer_data['last_name']} ({customer_id})")
        print(f"   Application: {uw_id}")
        print(f"   Policy: {customer_data['policy_type'].title()} - ${customer_data['coverage']:,}")
        print(f"   Risk: {customer_data['risk'].upper()}")
    
    print("\n" + "=" * 70)
    print(f"✅ Created {len(created)} test applications")
    print("=" * 70)
    
    return created

if __name__ == '__main__':
    create_test_applications()
    print("\n✅ Test data ready! Now run: python list_pending_applications.py")
