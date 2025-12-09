"""
PHINS Insurance Management System - Demonstration
Shows complete workflows and usage examples
"""

from phins_system import (
    PHINSInsuranceSystem,
    Company, Customer, InsurancePolicy,
    PolicyType, CustomerType, PaymentFrequency,
    RiskLevel, ReinsuranceType, PaymentMethod,
    PolicyManagement, ClaimsManagement, BillingManagement, UnderwritingEngine,
    Reinsurance
)
from datetime import datetime, timedelta


def print_header(title: str):
    """Print a section header"""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print(f"{'=' * 70}\n")


def demo_company_management(system: PHINSInsuranceSystem):
    """Demonstrate company management"""
    print_header("1. COMPANY MANAGEMENT")

    # Create company
    company = Company(
        company_id="PHI001",
        name="PHINS Insurance Company",
        registration_number="REG-2025-001",
        business_address="123 Insurance Ave, New York, NY 10001",
        phone="+1-800-PHINS-01",
        email="info@phins.com",
        license_number="LIC-NY-2025-001",
        website="https://www.phins.com"
    )

    system.register_company(company)
    print(f"✓ Registered Company: {company}")
    print(f"  License: {company.license_number}")
    print(f"  Status: {company.status}")


def demo_customer_management(system: PHINSInsuranceSystem):
    """Demonstrate customer management"""
    print_header("2. CUSTOMER MANAGEMENT")

    # Create customers
    customers = [
        Customer(
            customer_id="CUST001",
            first_name="John",
            last_name="Smith",
            email="john.smith@email.com",
            phone="+1-555-0100",
            address="456 Main Street",
            city="New York",
            state="NY",
            postal_code="10001",
            country_code="US",
            customer_type=CustomerType.INDIVIDUAL,
            identification_number="123-45-6789",
            portal_access=True
        ),
        Customer(
            customer_id="CUST002",
            first_name="Jane",
            last_name="Doe",
            email="jane.doe@email.com",
            phone="+1-555-0101",
            address="789 Oak Avenue",
            city="Los Angeles",
            state="CA",
            postal_code="90001",
            country_code="US",
            customer_type=CustomerType.BUSINESS,
            identification_number="98-7654321",
            portal_access=True
        )
    ]

    for customer in customers:
        system.register_customer(customer)
        print(f"✓ Registered Customer: {customer}")
        print(f"  Type: {customer.customer_type.value}")
        print(f"  Portal Access: {'Enabled' if customer.portal_access else 'Disabled'}\n")


def demo_policy_management(system: PHINSInsuranceSystem):
    """Demonstrate policy sales workflow"""
    print_header("3. POLICY MANAGEMENT - SALES DIVISION")

    # Create policies
    print("Creating insurance policies...\n")

    policy1 = system.create_policy(
        customer_id="CUST001",
        policy_type=PolicyType.AUTO,
        premium=1200.00,
        coverage=500000.00,
        deductible=500.00
    )

    policy2 = system.create_policy(
        customer_id="CUST001",
        policy_type=PolicyType.HOME,
        premium=1800.00,
        coverage=750000.00,
        deductible=1000.00
    )

    policy3 = system.create_policy(
        customer_id="CUST002",
        policy_type=PolicyType.COMMERCIAL,
        premium=5000.00,
        coverage=2000000.00,
        deductible=2500.00
    )

    policies = [policy1, policy2, policy3]
    for policy in policies:
        print(f"✓ Created Policy: {policy}")
        print(f"  Status: {policy.status.value}")
        print(f"  Active: {'Yes' if policy.is_active() else 'No'}")
        print(f"  Premium: ${policy.premium_amount:,.2f}")
        print(f"  Coverage: ${policy.coverage_amount:,.2f}\n")


def demo_underwriting(system: PHINSInsuranceSystem):
    """Demonstrate underwriting workflow"""
    print_header("4. UNDERWRITING DIVISION - RISK ASSESSMENT")

    policy = system.get_policy(list(system.policies.keys())[0])
    
    # Initiate underwriting
    underwriting = system.initiate_underwriting(policy.policy_id, policy.customer_id)
    print(f"✓ Initiated Underwriting: {underwriting}")
    
    # Assess risk
    print("\nPerforming risk assessment...")
    UnderwritingEngine.assess_risk(
        underwriting,
        RiskLevel.MEDIUM,
        medical_required=False,
        additional_docs=False
    )
    
    # Approve with premium adjustment
    print("✓ Risk Assessment Complete")
    print(f"  Risk Level: {underwriting.risk_assessment.value}")
    print(f"  Medical Required: {underwriting.medical_required}")
    
    UnderwritingEngine.approve_underwriting(underwriting, premium_adjustment=0.0)
    print(f"\n✓ Underwriting Approved")
    print(f"  Decision: {underwriting.decision.value}")
    print(f"  Premium Adjustment: {underwriting.premium_adjustment}%")


def demo_billing(system: PHINSInsuranceSystem):
    """Demonstrate billing workflow"""
    print_header("5. BILLING & ACCOUNTING DIVISION")

    policy = system.get_policy(list(system.policies.keys())[0])
    
    # Create bill
    print("Creating billing invoice...\n")
    bill = system.create_bill(
        policy_id=policy.policy_id,
        customer_id=policy.customer_id,
        amount=policy.premium_amount
    )
    
    print(f"✓ Created Bill: {bill}")
    print(f"  Bill Date: {bill.bill_date.strftime('%Y-%m-%d')}")
    print(f"  Due Date: {bill.due_date.strftime('%Y-%m-%d')}")
    print(f"  Amount Due: ${bill.amount_due:,.2f}")
    print(f"  Status: {bill.status.value}")
    
    # Record payment
    print("\nRecording customer payment...\n")
    BillingManagement.record_payment(bill, 600.00, PaymentMethod.BANK_TRANSFER)
    print(f"✓ Payment Recorded: ${600.00:,.2f}")
    print(f"  Amount Paid: ${bill.amount_paid:,.2f}")
    print(f"  Balance: ${bill.balance:,.2f}")
    print(f"  Status: {bill.status.value}")
    
    # Record final payment
    print("\nRecording final payment...\n")
    BillingManagement.record_payment(bill, bill.balance, PaymentMethod.ONLINE_PORTAL)
    print(f"✓ Final Payment Recorded: ${bill.balance:,.2f}")
    print(f"  Total Paid: ${bill.amount_paid:,.2f}")
    print(f"  Status: {bill.status.value}")


def demo_claims(system: PHINSInsuranceSystem):
    """Demonstrate claims processing"""
    print_header("6. CLAIMS DIVISION - CLAIMS PROCESSING")

    policy = system.get_policy(list(system.policies.keys())[0])
    
    # File claim
    print("Customer files insurance claim...\n")
    claim = system.file_claim(
        policy_id=policy.policy_id,
        customer_id=policy.customer_id,
        amount=25000.00,
        description="Vehicle collision damage"
    )
    
    print(f"✓ Claim Filed: {claim}")
    print(f"  Claim Date: {claim.claim_date.strftime('%Y-%m-%d %H:%M')}")
    print(f"  Claim Amount: ${claim.claim_amount:,.2f}")
    print(f"  Status: {claim.status.value}\n")
    
    # Adjuster reviews and approves
    print("Claims adjuster reviews claim...\n")
    ClaimsManagement.approve_claim(claim, 24500.00)
    
    print(f"✓ Claim Approved")
    print(f"  Approved Amount: ${claim.approved_amount:,.2f}")
    print(f"  Status: {claim.status.value}\n")
    
    # Process payment
    print("Processing claim payment...\n")
    success = ClaimsManagement.process_claim_payment(claim)
    
    if success:
        print(f"✓ Claim Payment Processed")
        print(f"  Payment Date: {claim.payment_date.strftime('%Y-%m-%d')}")
        print(f"  Status: {claim.status.value}")


def demo_reinsurance(system: PHINSInsuranceSystem):
    """Demonstrate reinsurance management"""
    print_header("7. REINSURANCE DIVISION - RISK TRANSFER")

    # Get a policy to create reinsurance for
    policies = list(system.policies.values())
    if len(policies) > 0:
        policy = policies[-1] if len(policies) > 2 else policies[0]
    else:
        print("No policies available for reinsurance demonstration")
        return
    
    print("Creating reinsurance arrangement...\n")
    reinsurance = Reinsurance(
        reinsurance_id="REIN001",
        policy_id=policy.policy_id,
        reinsurance_partner="Global Reinsurance Partners Ltd.",
        reinsurance_type=ReinsuranceType.EXCESS_OF_LOSS,
        ceded_amount=1500000.00,
        commission_rate=8.5
    )
    
    system.create_reinsurance(reinsurance)
    
    print(f"✓ Created Reinsurance: {reinsurance}")
    print(f"  Partner: {reinsurance.reinsurance_partner}")
    print(f"  Type: {reinsurance.reinsurance_type.value}")
    print(f"  Ceded Amount: ${reinsurance.ceded_amount:,.2f}")
    print(f"  Commission Rate: {reinsurance.commission_rate}%")
    print(f"  Commission Earned: ${reinsurance.commission_earned:,.2f}")


def demo_customer_portal(system: PHINSInsuranceSystem):
    """Demonstrate customer portal features"""
    print_header("8. CUSTOMER PORTAL - SELF-SERVICE ACCESS")

    customer = system.get_customer("CUST001")
    
    print(f"Customer: {customer.full_name}")
    print(f"Account Status: {customer.status}")
    print(f"Portal Access: {'Enabled' if customer.portal_access else 'Disabled'}\n")
    
    # Get customer policies
    policies = system.get_customer_policies(customer.customer_id)
    print(f"✓ My Policies ({len(policies)} active):")
    for policy in policies:
        print(f"  - {policy.policy_id}: {policy.policy_type.value} (${policy.premium_amount:,.2f}/year)")
    
    # Get customer claims
    claims = system.get_customer_claims(customer.customer_id)
    print(f"\n✓ My Claims ({len(claims)} total):")
    for claim in claims:
        print(f"  - {claim.claim_id}: {claim.status.value} (${claim.claim_amount:,.2f})")
    
    # Get billing summary
    billing = system.get_customer_billing(customer.customer_id)
    print(f"\n✓ Billing Summary:")
    print(f"  Total Due: ${billing['total_due']:,.2f}")
    print(f"  Overdue Bills: {billing['overdue_count']}")
    print(f"  Paid Bills: {billing['paid_count']}")


def demo_system_reporting(system: PHINSInsuranceSystem):
    """Demonstrate system-wide reporting"""
    print_header("9. SYSTEM REPORTING & ANALYTICS")

    summary = system.get_system_summary()
    
    print("PHINS Insurance System Summary")
    print("-" * 70)
    print(f"Total Companies:           {summary['total_companies']}")
    print(f"Total Customers:           {summary['total_customers']}")
    print(f"Total Policies:            {summary['total_policies']}")
    print(f"Active Policies:           {summary['active_policies']}")
    print(f"Total Revenue:             ${summary['total_revenue']:,.2f}")
    print()
    print(f"Total Claims:              {summary['total_claims']}")
    print(f"Pending Claims:            {summary['pending_claims']}")
    print(f"Claims Approved & Paid:    ${summary['total_claims_approved']:,.2f}")
    print()
    print(f"Total Bills:               {summary['total_bills']}")
    print(f"Outstanding Bills:         {summary['outstanding_bills']}")


def main():
    """Run complete demonstration"""
    print("\n")
    print(" " * 15 + "PHINS INSURANCE MANAGEMENT SYSTEM")
    print(" " * 20 + "Python Demonstration")
    print(" " * 15 + "=" * 40)
    
    # Initialize system
    system = PHINSInsuranceSystem()
    
    # Run all demonstrations
    demo_company_management(system)
    demo_customer_management(system)
    demo_policy_management(system)
    demo_underwriting(system)
    demo_billing(system)
    demo_claims(system)
    demo_reinsurance(system)
    demo_customer_portal(system)
    demo_system_reporting(system)
    
    print("\n" + "=" * 70)
    print("  Demonstration Complete!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
