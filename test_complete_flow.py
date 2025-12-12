#!/usr/bin/env python3
"""
Complete test: Create sample applications and generate report
"""
import sys
import json
from datetime import datetime, date
import random

# Create in-memory storage (simulating server state)
CUSTOMERS = {}
POLICIES = {}
UNDERWRITING_APPLICATIONS = {}

def create_test_applications():
    """Create test applications"""
    print("=" * 70)
    print("Creating test applications...")
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
        },
        {
            'first_name': 'Maria',
            'last_name': 'Garcia',
            'email': 'maria.garcia@example.com',
            'phone': '+1-555-456-7890',
            'dob': '1992-11-30',
            'gender': 'female',
            'coverage': 750000,
            'policy_type': 'disability',
            'risk': 'low'
        },
        {
            'first_name': 'David',
            'last_name': 'Lee',
            'email': 'david.lee@example.com',
            'phone': '+1-555-567-8901',
            'dob': '1980-07-25',
            'gender': 'male',
            'coverage': 350000,
            'policy_type': 'life',
            'risk': 'medium'
        }
    ]
    
    for idx, customer_data in enumerate(test_customers, 1):
        # Generate IDs
        customer_id = f"CUST-{random.randint(10000, 99999)}"
        policy_id = f"POL-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
        uw_id = f"UW-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
        
        # Create customer
        CUSTOMERS[customer_id] = {
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
        UNDERWRITING_APPLICATIONS[uw_id] = {
            'id': uw_id,
            'policy_id': policy_id,
            'customer_id': customer_id,
            'status': 'pending',
            'risk_assessment': customer_data['risk'],
            'medical_exam_required': customer_data['risk'] == 'high',
            'questionnaire_responses': {
                'smoking': 'No' if customer_data['risk'] == 'low' else 'Yes',
                'health_conditions': 'None' if customer_data['risk'] != 'high' else 'Diabetes',
                'medications': 'None' if customer_data['risk'] != 'high' else 'Metformin',
                'family_history': 'Good' if customer_data['risk'] == 'low' else 'Fair'
            },
            'submitted_date': datetime.now().isoformat()
        }
        
        # Create policy
        base_premium = {
            'life': 1200,
            'health': 800,
            'disability': 1500
        }.get(customer_data['policy_type'], 1000)
        
        # Adjust premium based on risk
        risk_multiplier = {'low': 1.0, 'medium': 1.3, 'high': 1.8, 'very_high': 2.5}
        adjusted_premium = int(base_premium * risk_multiplier[customer_data['risk']])
        
        POLICIES[policy_id] = {
            'id': policy_id,
            'customer_id': customer_id,
            'type': customer_data['policy_type'],
            'coverage_amount': customer_data['coverage'],
            'annual_premium': adjusted_premium,
            'monthly_premium': round(adjusted_premium / 12, 2),
            'status': 'pending_underwriting',
            'underwriting_id': uw_id,
            'risk_score': customer_data['risk'],
            'created_date': datetime.now().isoformat()
        }
        
        print(f"\n✅ Application #{idx}:")
        print(f"   Customer: {customer_data['first_name']} {customer_data['last_name']} ({customer_id})")
        print(f"   Email: {customer_data['email']}")
        print(f"   Application: {uw_id}")
        print(f"   Policy: {customer_data['policy_type'].title()} - ${customer_data['coverage']:,}")
        print(f"   Premium: ${adjusted_premium}/year (${round(adjusted_premium/12, 2)}/month)")
        print(f"   Risk: {customer_data['risk'].upper()}")
    
    print("\n" + "=" * 70)
    print(f"✅ Created {len(test_customers)} test applications")
    print("=" * 70)

def generate_report():
    """Generate pending applications report"""
    print("\n\n")
    print("=" * 100)
    print(" " * 30 + "🛡️  PHINS INSURANCE SYSTEM")
    print(" " * 25 + "PENDING APPLICATIONS REPORT")
    print(" " * 30 + f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 100)
    
    # Get today's date
    today = date.today()
    today_str = today.isoformat()
    
    # Filter pending applications
    all_pending = [(uw_id, uw_app) for uw_id, uw_app in UNDERWRITING_APPLICATIONS.items() 
                   if uw_app.get('status') == 'pending']
    
    today_pending = [(uw_id, uw_app) for uw_id, uw_app in all_pending
                     if uw_app.get('submitted_date', '').startswith(today_str)]
    
    # Summary statistics
    print(f"\n📊 SUMMARY")
    print("─" * 100)
    print(f"Total Pending Applications: {len(all_pending)}")
    print(f"Pending Applications Today: {len(today_pending)}")
    print(f"Total Customers: {len(CUSTOMERS)}")
    print(f"Total Policies: {len(POLICIES)}")
    
    # Risk distribution
    risk_counts = {'low': 0, 'medium': 0, 'high': 0, 'very_high': 0}
    for _, app in all_pending:
        risk = app.get('risk_assessment', 'medium')
        risk_counts[risk] = risk_counts.get(risk, 0) + 1
    
    print(f"\nRisk Distribution:")
    print(f"  🟢 Low Risk: {risk_counts['low']}")
    print(f"  🟡 Medium Risk: {risk_counts['medium']}")
    print(f"  🟠 High Risk: {risk_counts['high']}")
    print(f"  🔴 Very High Risk: {risk_counts['very_high']}")
    
    # Medical exam requirements
    med_exam_required = sum(1 for _, app in all_pending if app.get('medical_exam_required', False))
    print(f"\n⚕️  Medical Exam Required: {med_exam_required} application{'s' if med_exam_required != 1 else ''}")
    
    # Calculate total coverage and premiums
    total_coverage = sum(POLICIES[app['policy_id']]['coverage_amount'] 
                        for _, app in all_pending if app['policy_id'] in POLICIES)
    total_premium = sum(POLICIES[app['policy_id']]['annual_premium'] 
                       for _, app in all_pending if app['policy_id'] in POLICIES)
    
    print(f"\n💰 Financial Summary:")
    print(f"  Total Coverage Amount: ${total_coverage:,}")
    print(f"  Total Annual Premium: ${total_premium:,}")
    
    # List applications submitted today
    print(f"\n\n📅 APPLICATIONS SUBMITTED TODAY ({today_str})")
    print("=" * 100)
    
    if today_pending:
        for idx, (uw_id, uw_app) in enumerate(today_pending, 1):
            customer_id = uw_app.get('customer_id')
            policy_id = uw_app.get('policy_id')
            
            customer = CUSTOMERS.get(customer_id, {})
            policy = POLICIES.get(policy_id, {})
            
            print(f"\n{'─' * 100}")
            print(f"APPLICATION #{idx}")
            print(f"{'─' * 100}")
            print(f"Application ID:      {uw_id}")
            print(f"Submitted:           {datetime.fromisoformat(uw_app.get('submitted_date', '')).strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"\n👤 Customer Information:")
            print(f"  Customer ID:       {customer_id}")
            print(f"  Name:              {customer.get('name', 'Unknown')}")
            print(f"  Email:             {customer.get('email', 'N/A')}")
            print(f"  Phone:             {customer.get('phone', 'N/A')}")
            print(f"  Date of Birth:     {customer.get('dob', 'N/A')}")
            print(f"  Gender:            {customer.get('gender', 'N/A').title()}")
            print(f"\n📄 Policy Information:")
            print(f"  Policy ID:         {policy_id}")
            print(f"  Type:              {policy.get('type', 'N/A').title()}")
            print(f"  Coverage Amount:   ${policy.get('coverage_amount', 0):,}")
            print(f"  Annual Premium:    ${policy.get('annual_premium', 0):,}")
            print(f"  Monthly Premium:   ${policy.get('monthly_premium', 0):.2f}")
            print(f"  Status:            {policy.get('status', 'N/A').replace('_', ' ').title()}")
            print(f"\n✍️  Underwriting Assessment:")
            print(f"  Status:            {uw_app.get('status', 'N/A').upper()}")
            risk_icon = {'low': '🟢', 'medium': '🟡', 'high': '🟠', 'very_high': '🔴'}
            risk_level = uw_app.get('risk_assessment', 'N/A')
            print(f"  Risk Level:        {risk_icon.get(risk_level, '')} {risk_level.upper()}")
            print(f"  Medical Exam Req:  {'YES ⚕️' if uw_app.get('medical_exam_required') else 'NO ✓'}")
            
            # Questionnaire responses
            responses = uw_app.get('questionnaire_responses', {})
            if responses:
                print(f"\n📋 Health Questionnaire:")
                for key, value in responses.items():
                    if value and value != 'None':
                        print(f"  {key.replace('_', ' ').title()}: {value}")
    else:
        print("\n⚠️  No applications submitted today yet.")
    
    # Export to JSON
    export_data = {
        'generated_at': datetime.now().isoformat(),
        'summary': {
            'total_pending': len(all_pending),
            'pending_today': len(today_pending),
            'risk_distribution': risk_counts,
            'medical_exam_required': med_exam_required,
            'total_coverage': total_coverage,
            'total_premium': total_premium
        },
        'applications': []
    }
    
    for uw_id, uw_app in today_pending:
        customer_id = uw_app.get('customer_id')
        policy_id = uw_app.get('policy_id')
        customer = CUSTOMERS.get(customer_id, {})
        policy = POLICIES.get(policy_id, {})
        
        export_data['applications'].append({
            'application_id': uw_id,
            'customer_id': customer_id,
            'customer_name': customer.get('name'),
            'customer_email': customer.get('email'),
            'customer_phone': customer.get('phone'),
            'customer_dob': customer.get('dob'),
            'policy_id': policy_id,
            'policy_type': policy.get('type'),
            'coverage_amount': policy.get('coverage_amount'),
            'annual_premium': policy.get('annual_premium'),
            'monthly_premium': policy.get('monthly_premium'),
            'status': uw_app.get('status'),
            'risk_assessment': uw_app.get('risk_assessment'),
            'medical_exam_required': uw_app.get('medical_exam_required', False),
            'submitted_date': uw_app.get('submitted_date'),
            'questionnaire_responses': uw_app.get('questionnaire_responses', {})
        })
    
    # Save to file
    with open('/workspaces/phins/pending_applications_report.json', 'w') as f:
        json.dump(export_data, f, indent=2)
    
    print("\n\n" + "=" * 100)
    print(f"✅ Report complete! Found {len(today_pending)} pending application{'s' if len(today_pending) != 1 else ''} today.")
    print(f"📄 Detailed JSON export saved to: pending_applications_report.json")
    print("=" * 100 + "\n")

def main():
    """Main function"""
    create_test_applications()
    generate_report()

if __name__ == '__main__':
    main()
