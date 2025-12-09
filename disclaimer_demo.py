#!/usr/bin/env python3
"""
Demo: PHINS Disclaimers for Client Actions

This demo shows how disclaimers are displayed and acknowledged for:
- Buying/purchasing a contract
- Filing an insurance claim
- Investing savings via capital markets routes
"""

from accounting_engine import AccountingEngine, DisclaimerType, InvestmentRoute
from datetime import date
from decimal import Decimal


def main():
    # Initialize the accounting engine
    engine = AccountingEngine(engine_id="PHI-AE-001", organization_name="PHINS Insurance")
    
    print("\n" + "=" * 80)
    print("PHINS DISCLAIMER SYSTEM DEMO")
    print("=" * 80 + "\n")
    
    # Demo 1: Display all available disclaimers
    print("AVAILABLE DISCLAIMERS:")
    print("-" * 80)
    all_disclaimers = engine.get_all_disclaimers()
    for disc in all_disclaimers:
        print(f"• {disc.disclaimer_type.value}: {disc.title}")
    print()
    
    # Demo 2: Display Policy Purchase Disclaimer
    print("\n" + engine.print_disclaimer(DisclaimerType.BUY_CONTRACT))
    
    # Demo 3: Display Claim Submission Disclaimer
    print("\n" + engine.print_disclaimer(DisclaimerType.CLAIM_INSURANCE))
    
    # Demo 4: Display Investment Disclaimer
    print("\n" + engine.print_disclaimer(DisclaimerType.INVEST_SAVINGS))
    
    # Demo 5: Get disclaimers for specific actions
    print("\n" + "=" * 80)
    print("DISCLAIMERS BY ACTION")
    print("=" * 80)
    
    actions = ['buy_contract', 'claim_insurance', 'invest_savings']
    for action in actions:
        disclaimers = engine.get_all_disclaimers_for_action(action)
        print(f"\nAction: {action.upper().replace('_', ' ')}")
        print(f"  Required disclaimers: {len(disclaimers)}")
        for disc in disclaimers:
            print(f"    - {disc.title}")
    
    # Demo 6: Create an allocation and track disclaimer acknowledgments
    print("\n" + "=" * 80)
    print("ALLOCATION WITH DISCLAIMER TRACKING")
    print("=" * 80)
    
    allocation = engine.create_allocation(
        bill_id="BILL-000001",
        policy_id="POL-000001",
        customer_id="CUST-001",
        total_premium=Decimal('1000.00'),
        risk_percentage=Decimal('75'),
        investment_route=InvestmentRoute.MIXED_PORTFOLIO
    )
    
    print(f"\nCreated allocation: {allocation.allocation_id}")
    print(f"Investment route: {allocation.investment_route.value}")
    print(f"Premium: ${allocation.total_premium:.2f}")
    
    # Get pending disclaimers for this allocation
    pending = engine.get_pending_disclaimers(allocation.allocation_id)
    print(f"\nPending disclaimers: {len(pending)}")
    for disc in pending:
        print(f"  - {disc.title}")
    
    # Acknowledge disclaimers
    print("\nAcknowledging disclaimers...")
    engine.acknowledge_disclaimer(allocation.allocation_id, DisclaimerType.BUY_CONTRACT)
    engine.acknowledge_disclaimer(allocation.allocation_id, DisclaimerType.INVEST_SAVINGS)
    
    # Check pending again
    pending_after = engine.get_pending_disclaimers(allocation.allocation_id)
    print(f"Remaining pending disclaimers: {len(pending_after)}")
    for disc in pending_after:
        print(f"  - {disc.title}")
    
    # Demo 7: Summary of disclaimers per action
    print("\n" + "=" * 80)
    print("COMPLIANCE SUMMARY")
    print("=" * 80)
    
    print(f"\nTotal available disclaimers: {len(engine.get_all_disclaimers())}")
    print(f"Allocation {allocation.allocation_id}:")
    print(f"  - Acknowledged: {len(allocation.disclaimers_acknowledged)} disclaimer(s)")
    print(f"  - Pending: {len(pending_after)} disclaimer(s)")
    
    acknowledged_titles = [
        engine.get_disclaimer(dt).title
        for dt in allocation.disclaimers_acknowledged
    ]
    print(f"  - Acknowledged titles:")
    for title in acknowledged_titles:
        print(f"      ✓ {title}")
    
    print("\n" + "=" * 80)
    print("DEMO COMPLETE")
    print("=" * 80 + "\n")


if __name__ == '__main__':
    main()
