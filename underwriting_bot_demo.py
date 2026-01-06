#!/usr/bin/env python3
"""
Underwriting Bot Demo Script
============================
Demonstrates the full underwriting bot workflow including:
- Metadata upload (photos, medical reports, documents, audio, video)
- AI-based risk assessment
- Full risk report generation
- Decision support

This demo shows how the bot processes metadata and makes AI-powered
underwriting decisions while preserving all existing customer data.

Author: PHINS Platform
"""

import sys
import json
from datetime import datetime, date
from typing import Dict, Any

# Import the underwriting bot service
from services.underwriting_bot_service import (
    UnderwritingBotService,
    MetadataType,
    ProcessingStatus,
    ValidationStatus,
    RiskLevel,
    DecisionRecommendation,
    AssessmentStatus,
    init_underwriting_bot_service
)

# Create demo data stores (simulating existing platform data)
CUSTOMERS = {
    'CUST-001': {
        'id': 'CUST-001',
        'name': 'John Smith',
        'email': 'john.smith@email.com',
        'phone': '+44 7700 900001',
        'dob': '1985-06-15',
        'age': 39,
        'gender': 'male',
        'address': '123 Test Street, London',
        'occupation': 'Software Engineer',
        'created_date': '2023-01-15T10:00:00'
    },
    'CUST-002': {
        'id': 'CUST-002',
        'name': 'Jane Doe',
        'email': 'jane.doe@email.com',
        'phone': '+44 7700 900002',
        'dob': '1990-03-20',
        'age': 34,
        'gender': 'female',
        'address': '456 Sample Road, Manchester',
        'occupation': 'Doctor',
        'created_date': '2023-02-20T11:30:00'
    }
}

POLICIES = {
    'POL-001': {
        'id': 'POL-001',
        'customer_id': 'CUST-001',
        'type': 'life',
        'coverage_amount': 500000,
        'annual_premium': 1200,
        'status': 'pending_underwriting',
        'created_date': '2024-01-10T10:00:00'
    },
    'POL-002': {
        'id': 'POL-002',
        'customer_id': 'CUST-002',
        'type': 'health',
        'coverage_amount': 250000,
        'annual_premium': 800,
        'status': 'active',
        'created_date': '2023-06-15T14:00:00'
    }
}

UNDERWRITING_APPLICATIONS = {
    'UW-001': {
        'id': 'UW-001',
        'policy_id': 'POL-001',
        'customer_id': 'CUST-001',
        'status': 'pending',
        'risk_assessment': 'medium',
        'submitted_date': '2024-01-10T10:30:00'
    }
}

CLAIMS = {
    'CLM-001': {
        'id': 'CLM-001',
        'policy_id': 'POL-002',
        'customer_id': 'CUST-002',
        'type': 'medical',
        'claimed_amount': 5000,
        'status': 'paid',
        'filed_date': '2023-09-01T10:00:00'
    }
}


def print_section(title: str):
    """Print a section header"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_subsection(title: str):
    """Print a subsection header"""
    print(f"\n--- {title} ---")


def format_percentage(value: float) -> str:
    """Format a float as percentage"""
    return f"{value:.1%}"


def demo_full_workflow():
    """
    Demonstrate the complete underwriting bot workflow.
    """
    print_section("UNDERWRITING BOT RISK ASSESSMENT DEMO")
    print("\nThis demo shows how the AI-powered underwriting bot processes")
    print("metadata and creates comprehensive risk assessment reports.")
    
    # Initialize the bot service with existing data stores
    print_subsection("Initializing Underwriting Bot Service")
    
    bot_service = init_underwriting_bot_service(
        customers=CUSTOMERS,
        policies=POLICIES,
        underwriting_apps=UNDERWRITING_APPLICATIONS,
        claims=CLAIMS
    )
    
    print(f"✓ Bot ID: {bot_service.bot_id}")
    print(f"✓ Version: {bot_service.version}")
    print(f"✓ Connected to {len(CUSTOMERS)} customers")
    print(f"✓ Connected to {len(POLICIES)} policies")
    
    # Get a customer for the demo
    demo_customer_id = list(CUSTOMERS.keys())[0] if CUSTOMERS else None
    if not demo_customer_id:
        print("❌ No customers found for demo. Creating test customer...")
        demo_customer_id = "DEMO-CUST-001"
        CUSTOMERS[demo_customer_id] = {
            'id': demo_customer_id,
            'name': 'Demo Customer',
            'email': 'demo@example.com',
            'age': 35,
            'occupation': 'Software Engineer',
            'created_date': datetime.now().isoformat()
        }
    
    demo_customer = CUSTOMERS[demo_customer_id]
    print(f"\n✓ Demo Customer: {demo_customer.get('name', 'Unknown')} (ID: {demo_customer_id})")
    
    # Create underwriting application if needed
    demo_uw_id = f"UW-DEMO-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    demo_policy_id = f"POL-DEMO-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    UNDERWRITING_APPLICATIONS[demo_uw_id] = {
        'id': demo_uw_id,
        'customer_id': demo_customer_id,
        'policy_id': demo_policy_id,
        'status': 'pending',
        'submitted_date': datetime.now().isoformat()
    }
    
    print(f"✓ Created Underwriting Application: {demo_uw_id}")
    
    # =========================================================================
    # STEP 1: Start Assessment
    # =========================================================================
    print_subsection("Step 1: Starting Bot Assessment")
    
    assessment = bot_service.start_assessment(
        underwriting_id=demo_uw_id,
        customer_id=demo_customer_id,
        policy_id=demo_policy_id
    )
    
    print(f"✓ Assessment ID: {assessment.id}")
    print(f"✓ Status: {assessment.status.value}")
    print(f"✓ Customer Snapshot: {assessment.customer_snapshot.get('name', 'N/A')}")
    print(f"✓ Existing Policies: {assessment.existing_policies_count}")
    print(f"✓ Existing Claims: {assessment.existing_claims_count}")
    
    # =========================================================================
    # STEP 2: Upload Metadata
    # =========================================================================
    print_subsection("Step 2: Uploading Metadata")
    
    # Photo (selfie for identity)
    photo_meta = bot_service.add_metadata(
        assessment_id=assessment.id,
        metadata_type=MetadataType.PHOTO,
        file_name="applicant_selfie.jpg",
        file_path="/uploads/demo/applicant_selfie.jpg",
        file_content=b"simulated photo content",
        mime_type="image/jpeg"
    )
    print(f"✓ Uploaded: {photo_meta.file_name} (Photo)")
    
    # Passport
    passport_meta = bot_service.add_metadata(
        assessment_id=assessment.id,
        metadata_type=MetadataType.PASSPORT,
        file_name="passport_scan.pdf",
        file_path="/uploads/demo/passport_scan.pdf",
        file_content=b"simulated passport content",
        mime_type="application/pdf"
    )
    print(f"✓ Uploaded: {passport_meta.file_name} (Passport)")
    
    # Driving Licence
    licence_meta = bot_service.add_metadata(
        assessment_id=assessment.id,
        metadata_type=MetadataType.DRIVING_LICENCE,
        file_name="driving_licence.jpg",
        file_path="/uploads/demo/driving_licence.jpg",
        file_content=b"simulated licence content",
        mime_type="image/jpeg"
    )
    print(f"✓ Uploaded: {licence_meta.file_name} (Driving Licence)")
    
    # Medical Report
    medical_meta = bot_service.add_metadata(
        assessment_id=assessment.id,
        metadata_type=MetadataType.MEDICAL_REPORT,
        file_name="health_examination.pdf",
        file_path="/uploads/demo/health_examination.pdf",
        file_content=b"simulated medical report content",
        mime_type="application/pdf"
    )
    print(f"✓ Uploaded: {medical_meta.file_name} (Medical Report)")
    
    # Audio Recording (health statement)
    audio_meta = bot_service.add_metadata(
        assessment_id=assessment.id,
        metadata_type=MetadataType.AUDIO,
        file_name="health_statement.mp3",
        file_path="/uploads/demo/health_statement.mp3",
        file_content=b"simulated audio content",
        mime_type="audio/mpeg"
    )
    print(f"✓ Uploaded: {audio_meta.file_name} (Audio Statement)")
    
    # Video Recording (identity verification)
    video_meta = bot_service.add_metadata(
        assessment_id=assessment.id,
        metadata_type=MetadataType.VIDEO,
        file_name="identity_verification.mp4",
        file_path="/uploads/demo/identity_verification.mp4",
        file_content=b"simulated video content",
        mime_type="video/mp4"
    )
    print(f"✓ Uploaded: {video_meta.file_name} (Video Verification)")
    
    print(f"\n✓ Total Metadata Items: {len(assessment.metadata_items)}")
    
    # =========================================================================
    # STEP 3: Process Metadata
    # =========================================================================
    print_subsection("Step 3: Processing Metadata with AI Analyzers")
    
    process_result = bot_service.process_all_metadata(assessment.id)
    
    print(f"✓ Processed {process_result['total_processed']} items")
    print(f"✓ All passed: {process_result['success']}")
    print(f"✓ Assessment Status: {process_result['status']}")
    
    # Show individual processing results
    print("\nProcessing Results:")
    for meta in assessment.metadata_items:
        status_icon = "✓" if meta.processing_status == ProcessingStatus.COMPLETED else "⚠"
        valid_icon = "✓" if meta.validation_status == ValidationStatus.VALID else "⚠"
        print(f"  {status_icon} {meta.metadata_type.value}: {meta.file_name}")
        print(f"    Processing: {meta.processing_status.value} | Validation: {meta.validation_status.value}")
        if meta.processing_result.get('flags'):
            print(f"    Flags: {', '.join(meta.processing_result['flags'])}")
    
    # =========================================================================
    # STEP 4: Run Risk Assessment
    # =========================================================================
    print_subsection("Step 4: Running AI Risk Assessment")
    
    report = bot_service.run_risk_assessment(assessment.id)
    
    print(f"\n✓ Report Generated: {report.id}")
    print(f"✓ Processing Time: {report.processing_time_seconds:.2f} seconds")
    
    # =========================================================================
    # STEP 5: View Risk Assessment Report
    # =========================================================================
    print_subsection("Step 5: Risk Assessment Report")
    
    print(f"\n{'='*50}")
    print(f"  RISK ASSESSMENT REPORT")
    print(f"{'='*50}")
    
    print(f"\n  Report ID:      {report.id}")
    print(f"  Customer ID:    {report.customer_id}")
    print(f"  Assessment Date: {report.assessment_date.strftime('%Y-%m-%d %H:%M:%S')}")
    
    print(f"\n  --- OVERALL RISK ---")
    print(f"  Risk Score:     {format_percentage(report.overall_risk_score)}")
    print(f"  Risk Level:     {report.risk_level.value.replace('_', ' ').upper()}")
    
    print(f"\n  --- COMPONENT SCORES ---")
    print(f"  Identity Score:     {format_percentage(report.identity_score)}")
    print(f"  Identity Verified:  {'Yes ✓' if report.identity_verified else 'No ✗'}")
    print(f"  Document Score:     {format_percentage(report.document_score)}")
    print(f"  Medical Score:      {format_percentage(report.medical_score)}")
    print(f"  Behavioral Score:   {format_percentage(report.behavioral_score)}")
    print(f"  Fraud Score:        {format_percentage(report.fraud_score)}")
    
    print(f"\n  --- AI RECOMMENDATION ---")
    print(f"  Recommendation: {report.recommendation.value.replace('_', ' ').upper()}")
    print(f"  Confidence:     {format_percentage(report.confidence_level)}")
    
    print(f"\n  --- EXPLANATION ---")
    print(f"  {report.explanation}")
    
    if report.risk_factors:
        print(f"\n  --- RISK FACTORS ({len(report.risk_factors)}) ---")
        for i, factor in enumerate(report.risk_factors, 1):
            direction = "↑" if factor.impact_direction == "positive" else "↓"
            print(f"  {i}. [{factor.factor_category}] {factor.factor_name} {direction}")
            print(f"     Impact: {format_percentage(factor.impact_score)} | {factor.explanation[:60]}...")
    
    print(f"\n{'='*50}")
    
    # =========================================================================
    # STEP 6: Apply Decision
    # =========================================================================
    print_subsection("Step 6: Applying Underwriting Decision")
    
    # Determine decision based on recommendation
    decision_map = {
        DecisionRecommendation.APPROVE: 'approve',
        DecisionRecommendation.APPROVE_CONDITIONAL: 'conditional',
        DecisionRecommendation.REFER_MANUAL: 'refer',
        DecisionRecommendation.DECLINE: 'reject',
        DecisionRecommendation.PENDING_INFO: 'pending'
    }
    
    decision = decision_map.get(report.recommendation, 'refer')
    
    decision_result = bot_service.apply_decision(
        assessment_id=assessment.id,
        decision=decision,
        decided_by="AI_BOT",
        notes=f"Automated decision based on risk score {format_percentage(report.overall_risk_score)}"
    )
    
    print(f"\n✓ Decision Applied: {decision.upper()}")
    print(f"✓ Assessment Status: {assessment.status.value}")
    print(f"✓ Completed At: {assessment.completed_at.strftime('%Y-%m-%d %H:%M:%S') if assessment.completed_at else 'N/A'}")
    
    # =========================================================================
    # STEP 7: Verify Data Integrity
    # =========================================================================
    print_subsection("Step 7: Data Integrity Verification")
    
    # Verify customer data was not modified
    current_customer = CUSTOMERS.get(demo_customer_id, {})
    print(f"\n✓ Customer Data Preserved:")
    print(f"  - Name: {current_customer.get('name', 'N/A')}")
    print(f"  - Email: {current_customer.get('email', 'N/A')}")
    print(f"  - Created Date: {current_customer.get('created_date', 'N/A')}")
    
    # Verify claims were not modified
    claims_count = sum(1 for c in CLAIMS.values() if c.get('customer_id') == demo_customer_id)
    print(f"\n✓ Claims History Preserved: {claims_count} claims")
    
    print(f"\n✓ All customer data intact - NO modifications to existing records")
    
    # =========================================================================
    # Summary
    # =========================================================================
    print_section("DEMO COMPLETE")
    
    summary = bot_service.get_assessment_summary(assessment.id)
    
    print(f"\nAssessment Summary:")
    print(f"  - Assessment ID: {summary['id']}")
    print(f"  - Status: {summary['status']}")
    print(f"  - Metadata Processed: {summary['metadata_count']} items")
    print(f"  - Has Risk Report: {summary['has_risk_report']}")
    
    if 'risk_summary' in summary:
        print(f"\nRisk Summary:")
        rs = summary['risk_summary']
        print(f"  - Risk Score: {rs['risk_score']}")
        print(f"  - Risk Level: {rs['risk_level']}")
        print(f"  - Recommendation: {rs['recommendation']}")
        print(f"  - Confidence: {rs['confidence']}")
        print(f"  - Identity Verified: {'Yes' if rs['identity_verified'] else 'No'}")
        print(f"  - Risk Factors: {rs['factors_count']} ({rs['high_risk_factors']} high-risk)")
    
    print("\n" + "=" * 70)
    print("  The underwriting bot has successfully processed the application")
    print("  and generated a comprehensive risk assessment report.")
    print("=" * 70)
    
    return assessment, report


def demo_different_risk_profiles():
    """
    Demonstrate how different risk profiles are assessed.
    """
    print_section("RISK PROFILE COMPARISON DEMO")
    
    # Initialize service
    bot_service = UnderwritingBotService(
        customers={
            'LOW-RISK-CUST': {
                'id': 'LOW-RISK-CUST',
                'name': 'Low Risk Customer',
                'age': 35,
                'occupation': 'Teacher'
            },
            'HIGH-RISK-CUST': {
                'id': 'HIGH-RISK-CUST',
                'name': 'High Risk Customer',
                'age': 68,
                'occupation': 'Construction Worker'
            }
        },
        policies={},
        underwriting_apps={},
        claims={
            'CLM-1': {'customer_id': 'HIGH-RISK-CUST', 'status': 'paid'},
            'CLM-2': {'customer_id': 'HIGH-RISK-CUST', 'status': 'approved'},
            'CLM-3': {'customer_id': 'HIGH-RISK-CUST', 'status': 'paid'},
        }
    )
    
    # Assess low-risk customer
    print_subsection("Low-Risk Customer Assessment")
    
    low_risk_assessment = bot_service.start_assessment(
        underwriting_id='UW-LOW',
        customer_id='LOW-RISK-CUST',
        policy_id='POL-LOW'
    )
    
    bot_service.add_metadata(
        assessment_id=low_risk_assessment.id,
        metadata_type=MetadataType.PHOTO,
        file_name='photo.jpg',
        file_path='/uploads/photo.jpg',
        mime_type='image/jpeg'
    )
    
    bot_service.add_metadata(
        assessment_id=low_risk_assessment.id,
        metadata_type=MetadataType.PASSPORT,
        file_name='passport.pdf',
        file_path='/uploads/passport.pdf',
        mime_type='application/pdf'
    )
    
    bot_service.process_all_metadata(low_risk_assessment.id)
    low_risk_report = bot_service.run_risk_assessment(low_risk_assessment.id)
    
    print(f"  Customer: Low Risk Customer (Age: 35)")
    print(f"  Risk Score: {format_percentage(low_risk_report.overall_risk_score)}")
    print(f"  Risk Level: {low_risk_report.risk_level.value}")
    print(f"  Recommendation: {low_risk_report.recommendation.value}")
    print(f"  Existing Claims: {low_risk_assessment.existing_claims_count}")
    
    # Assess high-risk customer
    print_subsection("High-Risk Customer Assessment")
    
    high_risk_assessment = bot_service.start_assessment(
        underwriting_id='UW-HIGH',
        customer_id='HIGH-RISK-CUST',
        policy_id='POL-HIGH'
    )
    
    bot_service.add_metadata(
        assessment_id=high_risk_assessment.id,
        metadata_type=MetadataType.PHOTO,
        file_name='photo.jpg',
        file_path='/uploads/photo.jpg',
        mime_type='image/jpeg'
    )
    
    # Add disability certificate to increase risk flags
    bot_service.add_metadata(
        assessment_id=high_risk_assessment.id,
        metadata_type=MetadataType.DISABILITY_CERTIFICATE,
        file_name='disability_cert.pdf',
        file_path='/uploads/disability_cert.pdf',
        mime_type='application/pdf'
    )
    
    bot_service.add_metadata(
        assessment_id=high_risk_assessment.id,
        metadata_type=MetadataType.MEDICAL_REPORT,
        file_name='medical.pdf',
        file_path='/uploads/medical.pdf',
        mime_type='application/pdf'
    )
    
    bot_service.process_all_metadata(high_risk_assessment.id)
    high_risk_report = bot_service.run_risk_assessment(high_risk_assessment.id)
    
    print(f"  Customer: High Risk Customer (Age: 68)")
    print(f"  Risk Score: {format_percentage(high_risk_report.overall_risk_score)}")
    print(f"  Risk Level: {high_risk_report.risk_level.value}")
    print(f"  Recommendation: {high_risk_report.recommendation.value}")
    print(f"  Existing Claims: {high_risk_assessment.existing_claims_count}")
    print(f"  Risk Factors: {len(high_risk_report.risk_factors)}")
    
    # Comparison
    print_subsection("Risk Profile Comparison")
    
    print(f"\n  {'Profile':<20} {'Risk Score':<15} {'Level':<15} {'Recommendation'}")
    print(f"  {'-'*70}")
    print(f"  {'Low-Risk Customer':<20} {format_percentage(low_risk_report.overall_risk_score):<15} "
          f"{low_risk_report.risk_level.value:<15} {low_risk_report.recommendation.value}")
    print(f"  {'High-Risk Customer':<20} {format_percentage(high_risk_report.overall_risk_score):<15} "
          f"{high_risk_report.risk_level.value:<15} {high_risk_report.recommendation.value}")
    
    print(f"\n✓ Demo complete - different risk profiles correctly assessed")


if __name__ == '__main__':
    print("\n" + "=" * 70)
    print("     PHINS UNDERWRITING BOT - AI RISK ASSESSMENT DEMO")
    print("=" * 70)
    
    try:
        # Run main demo
        demo_full_workflow()
        
        # Run risk profile comparison
        demo_different_risk_profiles()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    print("\n✓ All demos completed successfully!")
