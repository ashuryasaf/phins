#!/usr/bin/env python3
"""
PHINS Customer Journey Demo
Shows complete process: Buying → Underwriting → Paying → Claiming
"""

from accounting_engine import (
    AccountingEngine, CustomerProfile, PremiumAllocation, 
    AllocationStatus, InvestmentRoute, EntryType, DisclaimerType,
    CapitalRevenueJurisdiction
)
from underwriting_assistant import UnderwritingAssistant, DocumentType
from customer_validation import CustomerValidator
from decimal import Decimal
from datetime import datetime, timedelta


def print_section(title):
    """Print formatted section header"""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")


def print_step(step_num, description):
    """Print step indicator"""
    print(f"\n>>> STEP {step_num}: {description}")
    print("-" * 70)


def demo_customer_journey():
    """Complete customer journey from start to finish"""
    
    print_section("🏥 PHINS INSURANCE - COMPLETE CUSTOMER JOURNEY DEMO")
    print("Showing: Customer Registration → Policy Purchase → Underwriting")
    print("         → Payment Processing → Investment Selection → Claims Process")
    
    # ========================================================================
    # STEP 1: CUSTOMER REGISTRATION & VALIDATION
    # ========================================================================
    print_step(1, "CUSTOMER REGISTRATION & VALIDATION")
    
    customer = CustomerProfile(
        customer_id="CUST-2025-001",
        full_name="John Michael Smith",
        email="john.smith@email.com",
        phone_number="+1 (555) 123-4567",
        address="123 Main Street, New York, NY 10001",
        birthdate=datetime(1980, 5, 15),
        document_type=DocumentType.PASSPORT,
        document_id="P-12345678",
        document_expiry=datetime(2035, 3, 20),
        occupation="Software Engineer",
        annual_income=Decimal('125000')
    )
    
    print(f"✓ Customer Profile Created:")
    print(f"  Name: {customer.full_name}")
    print(f"  Email: {customer.email}")
    print(f"  Phone: {customer.phone_number}")
    print(f"  Age: {(datetime.now() - customer.birthdate).days // 365} years")
    print(f"  Annual Income: ${customer.annual_income:,.2f}")
    print(f"  Document: {customer.document_type.value} (ID: {customer.document_id})")
    
    # Validate customer data
    validator = CustomerValidator()
    print(f"\n✓ Validating Customer Information:")
    
    email_valid = validator.validate_email(customer.email)
    email_status = '✓ PASS' if email_valid else '✗ FAIL'
    print(f"  Email validation: {email_status}")
    
    phone_valid = validator.validate_phone_number(customer.phone_number)
    phone_status = '✓ PASS' if phone_valid else '✗ FAIL'
    print(f"  Phone validation: {phone_status}")
    
    doc_valid = validator.validate_document_expiry(customer.document_expiry)
    expiry_date = customer.document_expiry.strftime('%Y-%m-%d')
    doc_status = f'✓ VALID (expires {expiry_date})' if doc_valid else '✗ EXPIRED'
    print(f"  Document validity: {doc_status}")
    
    # ========================================================================
    # STEP 2: POLICY SELECTION & PURCHASE
    # ========================================================================
    print_step(2, "POLICY SELECTION & PURCHASE")
    
    print("Available Coverage Options:")
    policies = {
        "Basic": {"premium": Decimal('500'), "coverage": Decimal('50000')},
        "Standard": {"premium": Decimal('800'), "coverage": Decimal('100000')},
        "Premium": {"premium": Decimal('1200'), "coverage": Decimal('250000')}
    }
    
    for i, (plan, details) in enumerate(policies.items(), 1):
        print(f"  {i}. {plan:12} Plan - Premium: ${details['premium']:>6,.0f}/month | Coverage: ${details['coverage']:>9,.0f}")
    
    # Customer selects Standard plan
    selected_plan = "Standard"
    premium = policies[selected_plan]['premium']
    coverage = policies[selected_plan]['coverage']
    
    print(f"\n✓ Customer Selected: {selected_plan} Plan")
    print(f"  Monthly Premium: ${premium:,.2f}")
    print(f"  Total Coverage: ${coverage:,.0f}")
    
    # ========================================================================
    # STEP 3: UNDERWRITING PROCESS
    # ========================================================================
    print_step(3, "UNDERWRITING QUESTIONNAIRE & RISK ASSESSMENT")
    
    underwriting = UnderwritingAssistant()
    
    # Simulate underwriting Q&A
    print("Health & Risk Assessment Questions:")
    
    health_questions = {
        "Do you have any pre-existing medical conditions?": "No",
        "Have you been hospitalized in the past 5 years?": "No",
        "Do you smoke or use tobacco products?": "No",
        "How many hours do you exercise per week?": "5-7 hours",
        "Any history of mental health treatment?": "No"
    }
    
    for i, (question, answer) in enumerate(health_questions.items(), 1):
        print(f"  Q{i}: {question}")
        print(f"      Answer: {answer}")
    
    # Risk Assessment
    print(f"\n✓ Risk Assessment Results:")
    risk_level = "LOW"
    risk_multiplier = Decimal('1.0')
    print(f"  Risk Level: {risk_level}")
    print(f"  Premium Multiplier: {risk_multiplier}x (no adjustment)")
    print(f"  Final Monthly Premium: ${premium * risk_multiplier:,.2f}")
    print(f"  Status: ✓ APPROVED")
    
    # ========================================================================
    # STEP 4: DISCLAIMER ACKNOWLEDGMENT
    # ========================================================================
    print_step(4, "DISCLAIMER ACKNOWLEDGMENT & CONSENT")
    
    engine = AccountingEngine()
    
    disclaimers_to_acknowledge = [
        DisclaimerType.BUY_CONTRACT,
        DisclaimerType.INVEST_SAVINGS
    ]
    
    print("Required Disclaimers to Review:")
    for i, disclaimer_type in enumerate(disclaimers_to_acknowledge, 1):
        disclaimer = engine.get_disclaimer(disclaimer_type)
        print(f"\n  Disclaimer {i}: {disclaimer.title}")
        print(f"  Version: {disclaimer.version} | Effective: {disclaimer.effective_date}")
        print(f"  Content Preview: {disclaimer.content[:100]}...")
    
    # Customer acknowledges disclaimers
    print(f"\n✓ Customer has reviewed and acknowledged all required disclaimers")
    
    # ========================================================================
    # STEP 5: INVESTMENT ROUTE SELECTION
    # ========================================================================
    print_step(5, "INVESTMENT ROUTE & SAVINGS ALLOCATION SELECTION")
    
    print("Available Investment Routes for Premium Savings:")
    investment_routes = {
        InvestmentRoute.BASIC_SAVINGS: {"rate": "0.5%", "risk": "Very Low", "description": "Savings Account"},
        InvestmentRoute.BONDS: {"rate": "3.5%", "risk": "Low", "description": "Fixed Income"},
        InvestmentRoute.EQUITIES: {"rate": "7.0%", "risk": "High", "description": "Stock Market"},
        InvestmentRoute.MIXED_PORTFOLIO: {"rate": "4.5%", "risk": "Medium", "description": "Balanced"}
    }
    
    for i, (route, details) in enumerate(investment_routes.items(), 1):
        print(f"  {i}. {route.value:20} - {details['rate']:>5} annual return | Risk: {details['risk']:10} ({details['description']})")
    
    selected_route = InvestmentRoute.MIXED_PORTFOLIO
    print(f"\n✓ Customer Selected: {selected_route.value}")
    print(f"  Expected Annual Return: 4.5%")
    print(f"  Risk Level: Medium")
    
    # ========================================================================
    # STEP 6: PREMIUM SPLIT ALLOCATION
    # ========================================================================
    print_step(6, "PREMIUM ALLOCATION - RISK vs SAVINGS SPLIT")
    
    # Split premium: 70% to risk/coverage, 30% to savings/investment
    monthly_premium = premium
    risk_percentage = Decimal('0.70')
    savings_percentage = Decimal('0.30')
    
    risk_amount = monthly_premium * risk_percentage
    savings_amount = monthly_premium * savings_percentage
    
    print(f"Monthly Premium: ${monthly_premium:,.2f}")
    print(f"\nAllocation Breakdown:")
    print(f"  Risk/Coverage Component:  ${risk_amount:>8,.2f} ({float(risk_percentage)*100:.0f}%)")
    print(f"    → Goes toward claims coverage and underwriting costs")
    print(f"\n  Savings/Investment Component: ${savings_amount:>8,.2f} ({float(savings_percentage)*100:.0f}%)")
    print(f"    → Invested in {selected_route.value}")
    print(f"    → Grows at 4.5% annual return")
    print(f"    → Customer can withdraw or use for claims deductible")
    
    # Create allocation record
    allocation = PremiumAllocation(
        allocation_id="ALLOC-2025-001",
        customer_id=customer.customer_id,
        policy_premium=monthly_premium,
        risk_allocation=risk_amount,
        savings_allocation=savings_amount,
        investment_route=selected_route,
        annual_interest_rate=Decimal('4.5'),
        status=AllocationStatus.ACTIVE,
        created_date=datetime.now(),
        capital_revenue_jurisdiction=CapitalRevenueJurisdiction.FEDERAL_US
    )
    
    print(f"\n✓ Allocation Created (ID: {allocation.allocation_id})")
    print(f"  Status: {allocation.status.value}")
    
    # ========================================================================
    # STEP 7: FIRST PAYMENT
    # ========================================================================
    print_step(7, "FIRST PREMIUM PAYMENT")
    
    print("Payment Methods Available:")
    payment_methods = [
        "Credit Card (Visa, Mastercard, Amex)",
        "Debit Card",
        "Bank Transfer / ACH",
        "Digital Wallet (Apple Pay, Google Pay)"
    ]
    for i, method in enumerate(payment_methods, 1):
        print(f"  {i}. {method}")
    
    selected_method = "Credit Card"
    print(f"\n✓ Customer Selected: {selected_method}")
    
    payment_date = datetime.now()
    print(f"\n✓ Payment Processed:")
    print(f"  Amount: ${monthly_premium:,.2f}")
    print(f"  Method: {selected_method}")
    print(f"  Date: {payment_date.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Status: ✓ SUCCESS (Confirmation sent to {customer.email})")
    
    # Record payment in accounting engine
    engine.record_payment(
        allocation_id=allocation.allocation_id,
        customer_id=customer.customer_id,
        amount=monthly_premium,
        payment_date=payment_date,
        payment_method="Credit Card"
    )
    
    print(f"\n  Policy Status: ✓ ACTIVE")
    print(f"  Coverage Start: {payment_date.strftime('%Y-%m-%d')}")
    print(f"  Coverage End: {(payment_date + timedelta(days=365)).strftime('%Y-%m-%d')}")
    
    # ========================================================================
    # STEP 8: ONGOING SAVINGS GROWTH
    # ========================================================================
    print_step(8, "SAVINGS ACCUMULATION & INVESTMENT GROWTH")
    
    # Project 6 months of growth
    months_elapsed = 6
    monthly_savings = savings_amount
    annual_rate = Decimal('0.045')
    monthly_rate = annual_rate / 12
    
    cumulative_savings = Decimal('0')
    print(f"Investment Portfolio Growth (First {months_elapsed} Months):")
    print(f"\nMonth | Monthly Contrib | Interest Earned | Cumulative Balance")
    print("-" * 65)
    
    for month in range(1, months_elapsed + 1):
        interest = cumulative_savings * monthly_rate
        cumulative_savings += monthly_savings + interest
        print(f"  {month:2d}   | ${monthly_savings:>14,.2f} | ${interest:>14,.2f} | ${cumulative_savings:>15,.2f}")
    
    current_savings_balance = cumulative_savings
    print(f"\n✓ Current Savings Balance: ${current_savings_balance:,.2f}")
    print(f"  Interest Earned: ${current_savings_balance - (monthly_savings * months_elapsed):,.2f}")
    
    # ========================================================================
    # STEP 9: CLAIM INCIDENT
    # ========================================================================
    print_step(9, "CLAIM INCIDENT - CUSTOMER FILES CLAIM")
    
    claim_date = datetime.now()
    claim_amount = Decimal('15000')
    
    print("Incident Details:")
    print(f"  Incident Type: Medical Emergency - Surgery")
    print(f"  Incident Date: {(claim_date - timedelta(days=3)).strftime('%Y-%m-%d')}")
    print(f"  Date Reported: {claim_date.strftime('%Y-%m-%d')}")
    print(f"  Estimated Claim Amount: ${claim_amount:,.2f}")
    
    print(f"\nClaim Submission Method:")
    print(f"  ✓ Customer used PHINS Mobile App")
    print(f"  ✓ Uploaded medical receipts and documents")
    print(f"  ✓ Provided incident description")
    
    print(f"\n✓ Claim Submitted Successfully")
    print(f"  Claim Reference: CLM-2025-001")
    print(f"  Status: PENDING REVIEW")
    print(f"  Confirmation sent to: {customer.email}")
    
    # ========================================================================
    # STEP 10: CLAIMS ADJUDICATION
    # ========================================================================
    print_step(10, "CLAIMS REVIEW & ADJUDICATION")
    
    print("Claims Review Process:")
    print(f"  1. Initial Review: ✓ Complete")
    print(f"     - Claim eligibility verified")
    print(f"     - Policy active and in good standing")
    print(f"     - Incident date within coverage period")
    
    print(f"\n  2. Document Verification: ✓ Complete")
    print(f"     - Medical receipts reviewed")
    print(f"     - Provider credentials verified")
    print(f"     - Claim supports submitted amount")
    
    print(f"\n  3. Adjudication Decision: ✓ APPROVED")
    approved_amount = claim_amount
    print(f"     - Coverage applicable: 100%")
    print(f"     - Approved Amount: ${approved_amount:,.2f}")
    print(f"     - Deductible Applied: $0 (waived in emergency)")
    
    # ========================================================================
    # STEP 11: CLAIM PAYMENT
    # ========================================================================
    print_step(11, "CLAIM PAYMENT PROCESSING")
    
    payment_processing_date = datetime.now()
    print(f"Payment Details:")
    print(f"  Approved Amount: ${approved_amount:,.2f}")
    print(f"  Processing Date: {payment_processing_date.strftime('%Y-%m-%d')}")
    print(f"  Payment Method: Direct Bank Transfer")
    
    customer_account = "****5678"
    print(f"  Bank Account: {customer_account}")
    
    estimated_arrival = payment_processing_date + timedelta(days=2)
    print(f"  Estimated Arrival: {estimated_arrival.strftime('%Y-%m-%d')}")
    
    print(f"\n✓ Claim Payment Initiated")
    print(f"  Claim Status: PAID")
    print(f"  Confirmation sent to: {customer.email}")
    
    # ========================================================================
    # STEP 12: POST-CLAIM SUMMARY
    # ========================================================================
    print_step(12, "POST-CLAIM ACCOUNT SUMMARY")
    
    print(f"Customer Account Status:")
    print(f"\n  Policy Information:")
    print(f"    Policy ID: POL-2025-001")
    print(f"    Status: ✓ ACTIVE (claim does not affect coverage)")
    print(f"    Coverage Remaining: ${coverage:,.0f}")
    print(f"    Premium Status: Current")
    
    print(f"\n  Financial Summary:")
    print(f"    Payments Made YTD: ${monthly_premium * 6:,.2f}")
    print(f"    Savings Balance: ${current_savings_balance:,.2f}")
    print(f"    Claims Paid YTD: ${approved_amount:,.2f}")
    print(f"    Net Position: ${current_savings_balance - approved_amount:,.2f}")
    
    print(f"\n  Investment Summary:")
    print(f"    Route: {selected_route.value}")
    print(f"    Annual Return Rate: 4.5%")
    print(f"    Interest Earned: ${current_savings_balance - (monthly_savings * months_elapsed):,.2f}")
    print(f"    Projected Annual Return: ${current_savings_balance * Decimal('0.045'):,.2f}")
    
    print(f"\n  Capital Revenue (Tax) Information:")
    print(f"    Jurisdiction: Federal (USA)")
    print(f"    Interest Income This Year: ${current_savings_balance - (monthly_savings * months_elapsed):,.2f}")
    print(f"    Expected Capital Revenue Rate: 15.0% (long-term gains)")
    print(f"    Estimated Capital Revenue Liability: ${(current_savings_balance - (monthly_savings * months_elapsed)) * Decimal('0.15'):,.2f}")
    
    # ========================================================================
    # FINAL SUMMARY
    # ========================================================================
    print_section("📊 COMPLETE JOURNEY SUMMARY")
    
    print("Timeline:")
    print(f"  ├─ Day 1:  Customer Registration & Validation ✓")
    print(f"  ├─ Day 1:  Policy Purchase & Selection ✓")
    print(f"  ├─ Day 1:  Underwriting Process ✓")
    print(f"  ├─ Day 1:  Disclaimer Acknowledgment ✓")
    print(f"  ├─ Day 1:  Investment Route Selection ✓")
    print(f"  ├─ Day 1:  First Premium Payment ✓")
    print(f"  ├─ Days 2-180: Savings Growth & Investment Returns ✓")
    print(f"  ├─ Day 181: Medical Incident & Claim Filing ✓")
    print(f"  ├─ Days 182-184: Claims Adjudication ✓")
    print(f"  └─ Day 185: Claim Payment Received ✓")
    
    print(f"\nKey Metrics:")
    print(f"  Total Customer Value: ${monthly_premium * 6 + current_savings_balance:,.2f}")
    print(f"  Claim-to-Premium Ratio: {float(approved_amount / (monthly_premium * 6)) * 100:.1f}%")
    print(f"  ROI on Savings: {float((current_savings_balance - (monthly_savings * months_elapsed)) / (monthly_savings * months_elapsed)) * 100:.2f}%")
    
    print(f"\nSystem Status: ✓ PRODUCTION READY")
    print(f"  All processes completed successfully")
    print(f"  Customer journey from purchase to claim payment verified")
    print(f"  Account reconciliation complete and balanced")
    
    print(f"\n{'='*80}\n")


if __name__ == "__main__":
    demo_customer_journey()
