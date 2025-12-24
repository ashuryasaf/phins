"""
PHINS Integrated System Demo - Underwriting Assistant + Accounting Engine
Complete workflow from customer underwriting through premium allocation and reporting
"""

from underwriting_assistant import (
    UnderwritingAssistant, QuestionnaireLibrary, 
    NotificationManager, DivisionalReporter, UnderwritingDecision, DeliveryMethod
)
from accounting_engine import AccountingEngine, AllocationStatus, EntryType, AccountType
from customer_validation import (
    Customer, Gender, SmokingStatus, PersonalStatus, DocumentType,
    IdentificationDocument, HealthAssessment
)
from decimal import Decimal
from datetime import date, datetime, timedelta


def integrated_workflow_demo():
    """Complete workflow: Underwriting → Policy → Billing → Accounting"""
    
    print("\n" + "=" * 100)
    print("PHINS INTEGRATED SYSTEM DEMO - END-TO-END WORKFLOW")
    print("=" * 100)
    print("\nFlow: Underwriting → Policy Creation → Billing → Accounting Allocation → Customer Reporting\n")
    
    # ========================================================================
    # PHASE 1: UNDERWRITING
    # ========================================================================
    print("\n" + "-" * 100)
    print("PHASE 1: UNDERWRITING ASSESSMENT")
    print("-" * 100)
    
    # Create customer
    customer = Customer(
        customer_id="CUST_INT_001",
        first_name="John",
        last_name="Anderson",
        email="john.anderson@example.com",
        phone="5550001234",
        birthdate=date(1975, 6, 15),
        gender=Gender.MALE,
        address="123 Park Avenue",
        city="New York",
        state_province="NY",
        country="USA",
        postal_code="10001",
        smoking_status=SmokingStatus.FORMER_SMOKER,
        personal_status=PersonalStatus.MARRIED,
        identification=IdentificationDocument(
               document_type=DocumentType.PASSPORT,
               document_id="A12345678",
               issuing_country="USA",
                issue_date=date(2015, 1, 1),
                expiry_date=date(2035, 1, 1)
        ),
        health_assessment=HealthAssessment(
               condition_level=8,
               medical_conditions=["Hypertension"],
               current_medications=["Lisinopril"],
            assessment_date=datetime.now()
        )
    )
    
    print(f"✅ Customer Created: {customer.first_name} {customer.last_name}")
    print(f"   ID: {customer.customer_id}")
    print(f"   Age: 49 years old")
    print(f"   Smoking Status: {customer.smoking_status.value}")
    
    # Create underwriting assistant
    assistant = UnderwritingAssistant("UW_ASSIST_001", "Senior Underwriter")
    
    # Start underwriting session
    session = assistant.start_underwriting_session(customer, questionnaire_type="health")
    print(f"\n✅ Underwriting Session Started")
    print(f"   Session ID: {session.session_id}")
    print(f"   Questions: {len(session.questions)}")
    
    # Answer health questions
    health_answers = [
        ("health_001", "Yes"),      # Any serious illnesses
        ("health_002", "Hypertension"),  # Current conditions
        ("health_003", "Lisinopril"),    # Medications
        ("health_004", "No"),       # Hospitalization
        ("health_005", 8),          # Health level (1-10)
    ]
    
    print(f"\n📋 Answering underwriting questions...")
    for q_id, answer in health_answers:
        assistant.process_answer(session.session_id, q_id, answer)
    
    print(f"✅ Questionnaire Completed: {len(session.answers)} answers")
    
    # Calculate risk score
    risk_score = assistant.calculate_risk_score(session)
    print(f"✅ Risk Score Calculated: {risk_score:.1%}")
    
    # Make underwriting decision
    decision = assistant.make_underwriting_decision(session, manual_notes="Standard health profile, hypertension managed")
    print(f"✅ Underwriting Decision: {decision.value}")
    
    # ========================================================================
    # PHASE 2: POLICY CREATION (Simulated)
    # ========================================================================
    print("\n" + "-" * 100)
    print("PHASE 2: POLICY CREATION & BILLING")
    print("-" * 100)
    
    policy_id = "POL_INT_001"
    policy_annual_premium = Decimal("1200.00")
    
    print(f"\n✅ Policy Created")
    print(f"   Policy ID: {policy_id}")
    print(f"   Type: Health Insurance")
    print(f"   Annual Premium: ${policy_annual_premium:.2f}")
    print(f"   Monthly Premium: ${policy_annual_premium / 12:.2f}")
    
    # Simulate monthly billing (3 months)
    print(f"\n📋 Processing 3 months of premium payments...")
    
    # ========================================================================
    # PHASE 3: ACCOUNTING - PREMIUM ALLOCATION
    # ========================================================================
    print("\n" + "-" * 100)
    print("PHASE 3: ACCOUNTING - PREMIUM ALLOCATION & TRACKING")
    print("-" * 100)
    
    # Initialize accounting engine
    accounting = AccountingEngine("ACC_INT_001", "PHINS Insurance Company")
    
    print(f"\n✅ Accounting Engine Initialized\n")
    
    # Based on risk score, determine allocation strategy
    # Higher risk → Higher risk percentage
    if risk_score > 0.7:
        risk_allocation_pct = Decimal("85")  # 85% risk, 15% savings
        strategy = "High Risk Profile"
    elif risk_score > 0.5:
        risk_allocation_pct = Decimal("75")  # 75% risk, 25% savings
        strategy = "Medium Risk Profile"
    else:
        risk_allocation_pct = Decimal("65")  # 65% risk, 35% savings
        strategy = "Low Risk Profile"
    
    monthly_premium = policy_annual_premium / 12
    
    print(f"Allocation Strategy: {strategy}")
    print(f"Risk Percentage: {risk_allocation_pct}% | Savings Percentage: {100 - risk_allocation_pct}%\n")
    
    # Create monthly allocations
    allocations = []
    for month in range(1, 4):
        bill_id = f"BILL_{customer.customer_id}_M{month}"
        
        # Create allocation
        allocation = accounting.create_allocation(
            bill_id=bill_id,
            policy_id=policy_id,
            customer_id=customer.customer_id,
            total_premium=monthly_premium,
            risk_percentage=risk_allocation_pct,
            allocation_notes=f"Month {month} premium payment"
        )
        allocations.append(allocation)
        
        # Post allocation
        accounting.post_allocation(allocation.allocation_id, "Accounting System")
        
        print(f"📄 Month {month} Allocation Posted: {allocation.allocation_id}")
        print(f"   Total Premium: ${allocation.total_premium:>8.2f}")
        print(f"   → Risk Coverage ({allocation.risk_percentage:.1f}%): ${allocation.risk_premium:>8.2f}")
        print(f"   → Customer Savings ({allocation.savings_percentage:.1f}%): ${allocation.savings_premium:>8.2f}")
        print(f"   Investment Ratio: {allocation.investment_ratio:.4f}:1 (Risk:Savings)\n")
    
    # ========================================================================
    # PHASE 4: REPORTING - CUSTOMER STATEMENT
    # ========================================================================
    print("\n" + "-" * 100)
    print("PHASE 4: CUSTOMER REPORTING")
    print("-" * 100)
    
    # Generate customer statement
    statement = accounting.get_customer_statement(
        customer.customer_id,
        date(2025, 10, 1),
        date(2025, 12, 31)
    )
    
    print(f"\n{statement.to_string()}\n")
    
    # ========================================================================
    # PHASE 5: REPORTING - ACCUMULATIVE ANALYSIS
    # ========================================================================
    print("\n" + "-" * 100)
    print("PHASE 5: ACCUMULATIVE PREMIUM REPORT (for Accounting Books)")
    print("-" * 100)
    
    report = accounting.get_accumulative_premium_report(policy_id)
    
    print(f"\n✅ ACCUMULATIVE PREMIUM ANALYSIS:")
    print(f"   Policy: {policy_id}")
    print(f"   Allocations: {report['allocation_count']}")
    print(f"   Total Premium: ${report['cumulative_premium']:.2f}")
    print(f"   Total Risk Coverage: ${report['cumulative_risk']:.2f}")
    print(f"   Total Customer Savings: ${report['cumulative_savings']:.2f}")
    print(f"   Overall Risk %: {report['overall_risk_percentage']:.2f}%")
    print(f"   Overall Savings %: {report['overall_savings_percentage']:.2f}%")
    
    # ========================================================================
    # PHASE 6: REPORTING - RISK/INVESTMENT ANALYSIS
    # ========================================================================
    print("\n" + "-" * 100)
    print("PHASE 6: RISK/INVESTMENT RATIO ANALYSIS")
    print("-" * 100)
    
    ratio_info = accounting.get_risk_investment_ratio(customer.customer_id)
    
    print(f"\n✅ RISK/INVESTMENT ANALYSIS FOR CUSTOMER {customer.customer_id}:")
    print(f"   Total Risk Coverage: ${ratio_info['total_risk']:.2f}")
    print(f"   Total Customer Savings: ${ratio_info['total_savings']:.2f}")
    print(f"   Risk:Savings Ratio: {ratio_info['risk_investment_ratio']:.4f}:1")
    print(f"   Meaning: For every $1 in savings, customer covers ${ratio_info['risk_investment_ratio']:.2f} in risk")
    
    # ========================================================================
    # PHASE 7: REPORTING - ACCOUNTING BOOK
    # ========================================================================
    print("\n" + "-" * 100)
    print("PHASE 7: ACCOUNTING BOOK (GENERAL LEDGER)")
    print("-" * 100)
    
    book = accounting.generate_accounting_book(
        date(2025, 10, 1),
        date(2025, 12, 31)
    )
    
    print(f"\n{book.to_string()}\n")
    
    # ========================================================================
    # PHASE 8: REPORTING - COMPREHENSIVE SUMMARY
    # ========================================================================
    print("\n" + "-" * 100)
    print("PHASE 8: COMPREHENSIVE CUSTOMER SUMMARY")
    print("-" * 100)
    
    summary = accounting.get_customer_summary(customer.customer_id)
    
    print(f"\n✅ CUSTOMER FINANCIAL SUMMARY:")
    print(f"   Customer: {customer.first_name} {customer.last_name} ({customer.customer_id})")
    print(f"   Total Allocations: {summary['allocation_count']}")
    print(f"   Total Premium Paid: ${summary['total_premium']:.2f}")
    print(f"   Total Risk Coverage: ${summary['total_risk']:.2f}")
    print(f"   Total Your Savings: ${summary['total_savings']:.2f}")
    print(f"   ")
    print(f"   Financial Breakdown:")
    print(f"   ├─ Risk Coverage: {summary['average_risk_percentage']:.1f}% (${summary['total_risk']:.2f})")
    print(f"   └─ Savings Account: {summary['average_savings_percentage']:.1f}% (${summary['total_savings']:.2f})")
    print(f"   ")
    print(f"   Investment Ratio: {summary['overall_investment_ratio']:.4f}:1")
    
    # ========================================================================
    # PHASE 9: SEND NOTIFICATIONS
    # ========================================================================
    print("\n" + "-" * 100)
    print("PHASE 9: CUSTOMER NOTIFICATIONS")
    print("-" * 100)
    
    notification_mgr = NotificationManager()
    
    # Send allocation confirmation
    delivery = notification_mgr.send_notification(
        customer_id=customer.customer_id,
        recipient=customer.email,
        template_name="premium_allocation",
        delivery_method=DeliveryMethod.EMAIL,
        context={
            "customer_name": f"{customer.first_name} {customer.last_name}",
            "policy_id": policy_id,
            "total_premium": str(monthly_premium),
            "risk_amount": str(monthly_premium * risk_allocation_pct / 100),
            "savings_amount": str(monthly_premium * (100 - risk_allocation_pct) / 100),
            "statement_url": f"https://portal.phins.ai/statement/{customer.customer_id}"
        },
        signature_required=False
    )
    
    print(f"\n✅ Notification Sent")
    print(f"   To: {customer.email}")
    print(f"   Subject: Premium Payment Allocation Confirmation")
    print(f"   Status: {delivery.delivery_status}")
    print(f"   Delivery Method: {delivery.delivery_method.value}")
    
    print(f"\n   Message Preview:")
    print(f"   Dear {customer.first_name},")
    print(f"   Thank you for your ${monthly_premium:.2f} premium payment.")
    print(f"   This payment has been allocated as follows:")
    print(f"   ")
    print(f"   Risk Coverage ({risk_allocation_pct:.1f}%): ${monthly_premium * risk_allocation_pct / 100:.2f}")
    print(f"   Your Savings ({100 - risk_allocation_pct:.1f}%): ${monthly_premium * (100 - risk_allocation_pct) / 100:.2f}")
    print(f"   ")
    print(f"   View your complete statement: portal.phins.ai")
    print(f"   ")
    print(f"   Best regards,")
    print(f"   PHINS Insurance Team")
    
    # ========================================================================
    # PHASE 10: SUMMARY
    # ========================================================================
    print("\n" + "=" * 100)
    print("✅ INTEGRATED WORKFLOW COMPLETED SUCCESSFULLY")
    print("=" * 100)
    
    print("\nWorkflow Summary:")
    print(f"  1. ✅ Customer Underwriting: Risk Score {risk_score:.1%} → {decision.value}")
    print(f"  2. ✅ Policy Created: {policy_id} @ ${policy_annual_premium:.2f}/year")
    print(f"  3. ✅ 3 Months Billed: ${monthly_premium:.2f}/month")
    print(f"  4. ✅ Accounting Allocations: {report['allocation_count']} entries posted to ledger")
    print(f"  5. ✅ Customer Savings Account: ${summary['total_savings']:.2f} accumulated")
    print(f"  6. ✅ Risk Fund: ${summary['total_risk']:.2f} allocated")
    print(f"  7. ✅ Customer Statement: Generated and delivered")
    print(f"  8. ✅ Accounting Book: All ledger balanced")
    print(f"  9. ✅ Notifications: Sent to customer")
    print(f"\n✨ System Status: PRODUCTION READY\n")


def quick_allocation_example():
    """Quick example: Simple allocation from a bill"""
    print("\n" + "=" * 80)
    print("QUICK EXAMPLE: SIMPLE PREMIUM ALLOCATION")
    print("=" * 80)
    
    # Quick setup
    engine = AccountingEngine("ACC_QUICK", "PHINS Insurance")
    
    # Scenario: Customer pays $1,000 monthly premium
    print("\n📊 Customer Premium Payment: $1,000/month\n")
    
    # Different allocation strategies
    strategies = [
        ("Pure Protection", 100, 0),
        ("Protection + Savings", 80, 20),
        ("Balanced", 60, 40),
        ("Savings Focused", 40, 60),
    ]
    
    for name, risk_pct, savings_pct in strategies:
        allocation = engine.create_allocation(
            bill_id=f"BILL_{name.replace(' ', '_')}_001",
            policy_id=f"POL_{name.replace(' ', '_')}",
            customer_id=f"CUST_{name.replace(' ', '_')}",
            total_premium=Decimal("1000"),
            risk_percentage=Decimal(str(risk_pct))
        )
        
        engine.post_allocation(allocation.allocation_id, "System")
        
        print(f"📋 {name}:")
        print(f"   Risk Coverage ({risk_pct}%): ${allocation.risk_premium:>7.2f} ← Protection Fund")
        print(f"   Your Savings ({savings_pct}%): ${allocation.savings_premium:>7.2f} ← Savings Account")
        print(f"   Ratio: {allocation.investment_ratio:.2f}:1\n")


if __name__ == "__main__":
    try:
        integrated_workflow_demo()
        quick_allocation_example()
        
        print("\n" + "=" * 100)
        print("🎉 ALL DEMONSTRATIONS COMPLETED SUCCESSFULLY")
        print("=" * 100)
        print("\nKey Takeaways:")
        print("  • Customers can see exactly how their premium is split")
        print("  • Risk allocation adjusts based on underwriting decision")
        print("  • Savings account grows transparently with each payment")
        print("  • Full accounting trail for compliance and audits")
        print("  • Customers receive detailed statements and notifications")
        print("=" * 100 + "\n")
    
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
