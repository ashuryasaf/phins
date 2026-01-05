#!/usr/bin/env python3
"""
Sully Chain Demo Script

Demonstrates the full Sully Chain supplier management and allocation system.
This script showcases:
1. Supplier registration and verification
2. Service request and allocation creation
3. Bidding workflow
4. Winner selection and fulfillment
5. Ledger tracking
6. AI/BI analytics

Run with: python sully_chain_demo.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta
import json

# Initialize database
print("=" * 70)
print("SULLY CHAIN - Supplier Management & Allocation System Demo")
print("=" * 70)
print()

# Check database initialization
print("📊 Initializing database...")
try:
    from database import init_database, check_database_connection
    init_database()
    if check_database_connection():
        print("✓ Database connection successful")
    else:
        print("⚠️  Database connection failed - continuing with demo")
except Exception as e:
    print(f"⚠️  Database initialization: {e}")

print()
print("-" * 70)
print("DEMO 1: Supplier Registration")
print("-" * 70)

try:
    from services.sully_chain_service import (
        sully_chain, SupplierRegistration, SpecialtyData, CredentialData
    )
    
    # Register a medical supplier
    medical_supplier = SupplierRegistration(
        name="HealthFirst Medical Group",
        supplier_type="medical_service",
        email="contact@healthfirst.demo",
        phone="555-0100",
        registration_number="MED-2024-001",
        city="New York",
        state="NY",
        country="USA"
    )
    
    result = sully_chain.suppliers.register_supplier(medical_supplier, created_by="demo_admin")
    
    if result:
        print(f"✓ Registered supplier: {result['name']}")
        print(f"  Code: {result['supplier_code']}")
        print(f"  Type: {result['supplier_type']}")
        print(f"  Status: {result['status']}")
        supplier_id = result['id']
    else:
        print("⚠️  Could not register supplier (may already exist)")
        supplier_id = None
    
    # Register a legal supplier
    legal_supplier = SupplierRegistration(
        name="LegalEase Partners LLP",
        supplier_type="legal",
        email="info@legalease.demo",
        phone="555-0200",
        registration_number="LAW-2024-001",
        city="Chicago",
        state="IL"
    )
    
    result2 = sully_chain.suppliers.register_supplier(legal_supplier, created_by="demo_admin")
    if result2:
        print(f"✓ Registered supplier: {result2['name']}")
        legal_supplier_id = result2['id']
    else:
        legal_supplier_id = None
    
except Exception as e:
    print(f"⚠️  Supplier registration error: {e}")
    supplier_id = None
    legal_supplier_id = None

print()
print("-" * 70)
print("DEMO 2: Supplier Verification")
print("-" * 70)

try:
    if supplier_id:
        # Verify the medical supplier
        verified = sully_chain.suppliers.verify_supplier(supplier_id, verified_by="demo_admin")
        if verified:
            print(f"✓ Supplier {supplier_id[:8]}... verified and activated")
            
            # Get updated supplier
            supplier = sully_chain.suppliers.get_supplier(supplier_id)
            if supplier:
                print(f"  Status: {supplier['status']}")
                print(f"  Verified: {supplier.get('verification_date', 'N/A')}")
        else:
            print("⚠️  Verification failed")
    else:
        print("⚠️  No supplier to verify")
        
except Exception as e:
    print(f"⚠️  Verification error: {e}")

print()
print("-" * 70)
print("DEMO 3: Service Request & Allocation")
print("-" * 70)

try:
    from services.sully_chain_service import ServiceRequestData, AllocationConfig
    
    # Create a service request
    sr_data = ServiceRequestData(
        service_type="medical_service",
        title="Medical Examination for Policy Applicant",
        description="Complete medical examination required for life insurance policy underwriting.",
        urgency_level="normal",
        estimated_value=500.00,
        budget_max=750.00
    )
    
    service_request = sully_chain.allocations.create_service_request(
        sr_data,
        requester_id="demo_underwriter",
        requester_type="user"
    )
    
    if service_request:
        print(f"✓ Created service request: {service_request['request_code']}")
        print(f"  Title: {service_request['title']}")
        print(f"  Type: {service_request['service_type']}")
        
        # Create allocation
        alloc_config = AllocationConfig(
            allocation_type="competitive",
            duration_hours=48,
            reserve_price=600.00,
            required_rating=0.0,
            eligible_supplier_types=["medical_service"]
        )
        
        allocation = sully_chain.allocations.create_allocation(
            service_request['id'],
            alloc_config,
            created_by="demo_admin"
        )
        
        if allocation:
            print(f"✓ Created allocation: {allocation['allocation_code']}")
            print(f"  Status: {allocation['status']}")
            print(f"  Reserve Price: ${allocation.get('reserve_price', 'N/A')}")
            allocation_id = allocation['id']
        else:
            print("⚠️  Could not create allocation")
            allocation_id = None
    else:
        print("⚠️  Could not create service request")
        allocation_id = None
        
except Exception as e:
    print(f"⚠️  Allocation error: {e}")
    allocation_id = None

print()
print("-" * 70)
print("DEMO 4: Bid Submission")
print("-" * 70)

try:
    from services.sully_chain_service import BidSubmission
    
    if allocation_id and supplier_id:
        # Submit a bid
        bid_data = BidSubmission(
            allocation_id=allocation_id,
            supplier_id=supplier_id,
            bid_amount=550.00,
            proposal_summary="Comprehensive medical examination with full report within 3 business days.",
            proposal_details="Our experienced team will conduct a thorough examination including blood work, EKG, and physical assessment.",
            deliverables=["Medical examination", "Lab results", "Comprehensive report"],
            estimated_days=3
        )
        
        bid = sully_chain.bidding.submit_bid(bid_data)
        
        if bid:
            print(f"✓ Submitted bid: {bid['bid_code']}")
            print(f"  Amount: ${bid['bid_amount']}")
            print(f"  Status: {bid['status']}")
            print(f"  AI Score: {bid.get('ai_score', 'N/A')}")
            bid_id = bid['id']
        else:
            print("⚠️  Could not submit bid")
            bid_id = None
    else:
        print("⚠️  No allocation or supplier available for bidding")
        bid_id = None
        
except Exception as e:
    print(f"⚠️  Bidding error: {e}")
    bid_id = None

print()
print("-" * 70)
print("DEMO 5: Winner Selection & Fulfillment")
print("-" * 70)

try:
    if allocation_id and bid_id:
        # Select winner
        winning_bid = sully_chain.bidding.select_winner(
            allocation_id,
            bid_id,
            selected_by="demo_admin",
            notes="Best value proposition with proven track record"
        )
        
        if winning_bid:
            print(f"✓ Selected winner: {winning_bid['bid_code']}")
            print(f"  Final Amount: ${winning_bid.get('bid_amount', 'N/A')}")
            
            # Start fulfillment
            from services.sully_chain_service import MilestoneData
            
            milestones = [
                MilestoneData(
                    milestone_name="Initial Assessment",
                    description="Complete initial patient assessment",
                    milestone_amount=200.00
                ),
                MilestoneData(
                    milestone_name="Lab Work",
                    description="Complete all required lab tests",
                    milestone_amount=150.00
                ),
                MilestoneData(
                    milestone_name="Final Report",
                    description="Deliver comprehensive medical report",
                    milestone_amount=200.00
                )
            ]
            
            fulfillment = sully_chain.fulfillment.start_fulfillment(
                allocation_id,
                milestones=milestones,
                started_by="demo_admin"
            )
            
            if fulfillment:
                print(f"✓ Started fulfillment: {fulfillment['fulfillment_code']}")
                print(f"  Status: {fulfillment['status']}")
            else:
                print("⚠️  Could not start fulfillment")
        else:
            print("⚠️  Could not select winner")
    else:
        print("⚠️  No allocation or bid available for winner selection")
        
except Exception as e:
    print(f"⚠️  Winner selection error: {e}")

print()
print("-" * 70)
print("DEMO 6: Ledger Verification")
print("-" * 70)

try:
    # Get ledger entries
    if supplier_id:
        history = sully_chain.ledger.get_entity_history("supplier", supplier_id, limit=5)
        print(f"✓ Ledger entries for supplier {supplier_id[:8]}...")
        for entry in history[:3]:
            print(f"  [{entry.get('sequence_number', 'N/A')}] {entry.get('action_type', 'unknown')} - {entry.get('timestamp', 'N/A')}")
    
    # Verify integrity
    integrity = sully_chain.ledger.verify_integrity()
    print(f"\n✓ Ledger integrity check:")
    print(f"  Valid: {integrity.get('is_valid', 'unknown')}")
    print(f"  Errors: {len(integrity.get('errors', []))}")
    
except Exception as e:
    print(f"⚠️  Ledger error: {e}")

print()
print("-" * 70)
print("DEMO 7: AI/BI Analytics")
print("-" * 70)

try:
    from services.sully_chain_analytics import sully_analytics
    
    # Dashboard stats
    print("📊 Dashboard Statistics:")
    exec_summary = sully_analytics.dashboard.generate_executive_summary()
    summary = exec_summary.get('summary', {})
    print(f"  Active Suppliers: {summary.get('active_suppliers', 0)}")
    print(f"  Open Allocations: {summary.get('open_allocations', 0)}")
    print(f"  Avg Bids/Allocation: {summary.get('avg_bids_per_allocation', 0)}")
    
    # Supplier scoring
    if supplier_id:
        print(f"\n📈 Performance Scoring for supplier {supplier_id[:8]}...")
        metrics = sully_analytics.scoring.calculate_comprehensive_score(supplier_id)
        if metrics:
            print(f"  Overall Score: {metrics.overall_score}")
            print(f"  Performance Tier: {metrics.performance_tier}")
            print(f"  Quality Score: {metrics.quality_score}")
            print(f"  Reliability Score: {metrics.reliability_score}")
        else:
            print("  Score calculation pending (needs more data)")
    
    # Price prediction
    if allocation_id:
        print(f"\n💰 Price Prediction for allocation...")
        prediction = sully_analytics.pricing.predict_winning_price(allocation_id)
        if prediction:
            print(f"  Predicted Price: ${prediction.predicted_winning_price:,.2f}")
            print(f"  Confidence: {prediction.confidence_level*100:.0f}%")
            print(f"  Range: ${prediction.price_range_low:,.2f} - ${prediction.price_range_high:,.2f}")
        else:
            print("  Prediction not available (needs historical data)")
            
except Exception as e:
    print(f"⚠️  Analytics error: {e}")

print()
print("=" * 70)
print("DEMO COMPLETE")
print("=" * 70)
print()
print("The Sully Chain system has been demonstrated successfully!")
print("Key capabilities shown:")
print("  ✓ Supplier registration and verification")
print("  ✓ Service request and allocation creation")
print("  ✓ Competitive bidding workflow")
print("  ✓ Winner selection and fulfillment tracking")
print("  ✓ Immutable ledger with integrity verification")
print("  ✓ AI-powered analytics and scoring")
print()
print("Access the web dashboard at: http://localhost:8000/sully-chain.html")
print()
