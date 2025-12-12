#!/usr/bin/env python3
"""
List all pending applications from today with details
"""
import sys
import json
from datetime import datetime, date

sys.path.insert(0, '/workspaces/phins')
import web_portal.server as server

def format_datetime(dt_str):
    """Format datetime string for display"""
    try:
        dt = datetime.fromisoformat(dt_str)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return dt_str

def format_currency(amount):
    """Format currency amount"""
    try:
        return f"${float(amount):,.2f}"
    except:
        return str(amount)

def get_customer_name(customer_id):
    """Get customer name from ID"""
    if customer_id in server.CUSTOMERS:
        return server.CUSTOMERS[customer_id].get('name', 'Unknown')
    return 'Unknown'

def get_customer_email(customer_id):
    """Get customer email from ID"""
    if customer_id in server.CUSTOMERS:
        return server.CUSTOMERS[customer_id].get('email', 'N/A')
    return 'N/A'

def get_policy_details(policy_id):
    """Get policy details from ID"""
    if policy_id in server.POLICIES:
        policy = server.POLICIES[policy_id]
        return {
            'type': policy.get('type', 'N/A'),
            'coverage': policy.get('coverage_amount', 0),
            'premium': policy.get('annual_premium', 0)
        }
    return {'type': 'N/A', 'coverage': 0, 'premium': 0}

def list_pending_applications():
    """List all pending applications"""
    print("=" * 100)
    print(" " * 30 + "🛡️  PHINS INSURANCE SYSTEM")
    print(" " * 25 + "PENDING APPLICATIONS REPORT")
    print(" " * 30 + f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 100)
    
    # Get today's date
    today = date.today()
    today_str = today.isoformat()
    
    # Filter pending applications
    all_pending = []
    today_pending = []
    
    for uw_id, uw_app in server.UNDERWRITING_APPLICATIONS.items():
        if uw_app.get('status') == 'pending':
            all_pending.append((uw_id, uw_app))
            
            # Check if submitted today
            submitted_date = uw_app.get('submitted_date', '')
            if submitted_date.startswith(today_str):
                today_pending.append((uw_id, uw_app))
    
    # Summary statistics
    print(f"\n📊 SUMMARY")
    print("─" * 100)
    print(f"Total Pending Applications: {len(all_pending)}")
    print(f"Pending Applications Today: {len(today_pending)}")
    print(f"Total Customers: {len(server.CUSTOMERS)}")
    print(f"Total Policies: {len(server.POLICIES)}")
    
    # Risk distribution
    risk_counts = {'low': 0, 'medium': 0, 'high': 0, 'very_high': 0}
    for _, app in all_pending:
        risk = app.get('risk_assessment', 'medium')
        risk_counts[risk] = risk_counts.get(risk, 0) + 1
    
    print(f"\nRisk Distribution (All Pending):")
    print(f"  Low Risk: {risk_counts['low']}")
    print(f"  Medium Risk: {risk_counts['medium']}")
    print(f"  High Risk: {risk_counts['high']}")
    print(f"  Very High Risk: {risk_counts['very_high']}")
    
    # Medical exam requirements
    med_exam_required = sum(1 for _, app in all_pending if app.get('medical_exam_required', False))
    print(f"\nMedical Exam Required: {med_exam_required} applications")
    
    # List applications submitted today
    if today_pending:
        print(f"\n\n📅 APPLICATIONS SUBMITTED TODAY ({today_str})")
        print("=" * 100)
        
        for idx, (uw_id, uw_app) in enumerate(today_pending, 1):
            customer_id = uw_app.get('customer_id')
            policy_id = uw_app.get('policy_id')
            
            customer_name = get_customer_name(customer_id)
            customer_email = get_customer_email(customer_id)
            policy_details = get_policy_details(policy_id)
            
            print(f"\n{'─' * 100}")
            print(f"APPLICATION #{idx}")
            print(f"{'─' * 100}")
            print(f"Application ID:      {uw_id}")
            print(f"Submitted:           {format_datetime(uw_app.get('submitted_date', 'N/A'))}")
            print(f"\nCustomer Information:")
            print(f"  Customer ID:       {customer_id}")
            print(f"  Name:              {customer_name}")
            print(f"  Email:             {customer_email}")
            print(f"\nPolicy Information:")
            print(f"  Policy ID:         {policy_id}")
            print(f"  Type:              {policy_details['type'].title()}")
            print(f"  Coverage Amount:   {format_currency(policy_details['coverage'])}")
            print(f"  Annual Premium:    {format_currency(policy_details['premium'])}")
            print(f"\nUnderwriting Assessment:")
            print(f"  Status:            {uw_app.get('status', 'N/A').upper()}")
            print(f"  Risk Level:        {uw_app.get('risk_assessment', 'N/A').upper()}")
            print(f"  Medical Exam Req:  {'YES ⚠️' if uw_app.get('medical_exam_required') else 'NO'}")
            
            # Questionnaire responses
            responses = uw_app.get('questionnaire_responses', {})
            if responses:
                print(f"\nHealth Questionnaire:")
                for key, value in responses.items():
                    if value and value != 'None':
                        print(f"  {key.replace('_', ' ').title()}: {value}")
    else:
        print(f"\n\n📅 APPLICATIONS SUBMITTED TODAY ({today_str})")
        print("=" * 100)
        print("\n⚠️  No applications submitted today yet.")
    
    # List all pending applications (if different from today)
    if len(all_pending) > len(today_pending):
        print(f"\n\n📋 ALL PENDING APPLICATIONS (Including Previous Days)")
        print("=" * 100)
        
        # Group by date
        by_date = {}
        for uw_id, uw_app in all_pending:
            submitted_date = uw_app.get('submitted_date', '')
            date_only = submitted_date.split('T')[0] if 'T' in submitted_date else submitted_date
            if date_only not in by_date:
                by_date[date_only] = []
            by_date[date_only].append((uw_id, uw_app))
        
        # Sort by date (newest first)
        for submission_date in sorted(by_date.keys(), reverse=True):
            apps = by_date[submission_date]
            print(f"\n📅 {submission_date} ({len(apps)} application{'s' if len(apps) != 1 else ''})")
            print("─" * 100)
            
            for uw_id, uw_app in apps:
                customer_id = uw_app.get('customer_id')
                policy_id = uw_app.get('policy_id')
                policy_details = get_policy_details(policy_id)
                
                print(f"\n  {uw_id} | {get_customer_name(customer_id):<25} | "
                      f"{policy_details['type'].title():<12} | "
                      f"{format_currency(policy_details['coverage']):<15} | "
                      f"Risk: {uw_app.get('risk_assessment', 'N/A').upper():<10}")
    
    # Export to JSON
    export_data = {
        'generated_at': datetime.now().isoformat(),
        'summary': {
            'total_pending': len(all_pending),
            'pending_today': len(today_pending),
            'risk_distribution': risk_counts,
            'medical_exam_required': med_exam_required
        },
        'applications': []
    }
    
    for uw_id, uw_app in all_pending:
        customer_id = uw_app.get('customer_id')
        policy_id = uw_app.get('policy_id')
        
        export_data['applications'].append({
            'application_id': uw_id,
            'customer_id': customer_id,
            'customer_name': get_customer_name(customer_id),
            'customer_email': get_customer_email(customer_id),
            'policy_id': policy_id,
            'policy_type': get_policy_details(policy_id)['type'],
            'coverage_amount': get_policy_details(policy_id)['coverage'],
            'annual_premium': get_policy_details(policy_id)['premium'],
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
    print("✅ Report complete!")
    print(f"📄 Detailed JSON export saved to: pending_applications_report.json")
    print("=" * 100 + "\n")
    
    return export_data

def main():
    """Main function"""
    try:
        report = list_pending_applications()
        
        # Return exit code based on pending count
        if report['summary']['pending_today'] > 0:
            sys.exit(0)  # Applications found
        else:
            sys.exit(1)  # No applications
            
    except Exception as e:
        print(f"\n❌ Error generating report: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

if __name__ == '__main__':
    main()
