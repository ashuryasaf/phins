#!/usr/bin/env python3
"""
Generate Comprehensive Risk Assessment Report
=============================================
Generates a full AI executive risk assessment report using SYNTHETIC test data.

SECURITY NOTE:
This script uses synthetic/anonymized data for testing and demonstration purposes.
NO REAL PII should ever be committed to this file or generated reports.
Reports are saved to /workspace/reports/ which is gitignored.

This script generates a downloadable HTML report with:
- Full risk assessment breakdown
- Medical condition analysis
- AI-powered recommendations
- Executive summary
- Pipeline-ready structured output

Author: PHINS Platform
"""

import os
import sys
import json
import secrets
import random
from datetime import datetime, date

# Import services
from services.risk_report_generator import (
    RiskReportGenerator,
    ComprehensiveRiskReport,
    MedicalCondition,
    ReportFormat,
    RiskCategory,
    RecommendationType,
    create_risk_report_generator
)

from services.underwriting_bot_service import (
    UnderwritingBotService,
    MetadataType,
    ProcessingStatus,
    ValidationStatus,
    RiskLevel,
    DecisionRecommendation,
    AssessmentStatus
)


def _generate_synthetic_id(prefix: str) -> str:
    """Generate a synthetic ID for testing"""
    return f"{prefix}-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"


def create_application_data():
    """
    Create SYNTHETIC application data for testing the risk assessment pipeline.
    
    SECURITY: All data in this function is synthetic/fake and should not
    resemble any real person. No real PII should be used here.
    """
    
    # Generate unique synthetic IDs
    application_id = _generate_synthetic_id("UW")
    customer_id = _generate_synthetic_id("CUST")
    
    # SYNTHETIC customer data - clearly fake/test data
    customer_data = {
        'id': customer_id,
        'name': 'Test Applicant',  # Generic test name
        'email': f'test.applicant.{secrets.token_hex(4)}@example.test',  # Fake domain
        'phone': '+1-555-0100',  # Reserved test number range
        'dob': '1977-01-01',  # Generic date
        'age': 48,
        'gender': 'unspecified',
        'address': '123 Test Street',
        'city': 'Test City',
        'location': 'Test Region',
        'state': 'Test State',
        'zip': '00000',  # Invalid zip for testing
        'occupation': 'Test Occupation',
        'marital_status': 'unspecified',
        'dependents': 0,
        'annual_income': 50000,
        'created_date': datetime.now().isoformat()
    }
    
    # SYNTHETIC medical data for testing elevated risk scenarios
    medical_data = {
        'disability_percentage': 30,
        'disability_type': 'Mobility Impairment - Test Scenario',
        'disability_cause': 'Test Scenario - Historical Injury',
        'disability_certified': True,
        'disability_certificate_date': '2020-01-01',
        'bmi': 32.0,
        'bmi_category': 'Obese Class I',
        'height_cm': 175,
        'weight_kg': 98,
        'blood_pressure': '140/90',
        'cholesterol_total': 5.5,
        'smoking_status': 'non_smoker',
        'alcohol_units_weekly': 5,
        'exercise_hours_weekly': 2,
        'family_history': {
            'heart_disease': True,
            'diabetes': False,
            'cancer': False,
            'stroke': False
        },
        'conditions': [
            {
                'name': 'Obesity',
                'icd_code': 'E66.9',
                'severity': 'moderate',
                'diagnosed_date': '2021-01-01',
                'status': 'active',
                'treatment': 'Lifestyle modifications',
                'risk_impact': 0.25,
                'exclusion_recommended': False,
                'loading_percentage': 15,
                'notes': 'Test condition - Class I Obesity'
            },
            {
                'name': 'Hypertension',
                'icd_code': 'I10',
                'severity': 'mild',
                'diagnosed_date': '2022-01-01',
                'status': 'controlled',
                'treatment': 'Medication and lifestyle',
                'risk_impact': 0.20,
                'exclusion_recommended': False,
                'loading_percentage': 10,
                'notes': 'Test condition - controlled hypertension'
            },
            {
                'name': 'Mobility Impairment',
                'icd_code': 'M62.50',
                'severity': 'moderate',
                'diagnosed_date': '2019-01-01',
                'status': 'stable',
                'treatment': 'Physical therapy',
                'risk_impact': 0.15,
                'exclusion_recommended': True,
                'loading_percentage': 0,
                'notes': 'Test condition - stable mobility impairment'
            }
        ],
        'medications': [
            {'name': 'Test Medication A', 'dosage': '10mg', 'frequency': 'daily', 'purpose': 'Test purpose'},
            {'name': 'Test Medication B', 'dosage': '500mg', 'frequency': 'as needed', 'purpose': 'Test purpose'}
        ],
        'recent_tests': {
            'date': '2025-01-01',
            'glucose_fasting': 5.0,
            'hba1c': 5.5,
            'liver_function': 'Normal',
            'kidney_function': 'Normal',
            'ecg': 'Normal'
        }
    }
    
    # SYNTHETIC documents - no real document numbers
    documents = [
        {
            'type': 'passport',
            'id': f'DOC-PASS-{secrets.token_hex(4)}',
            'verified': True,
            'authenticity_score': 0.95,
            'expiry_status': 'valid',
            'extracted_data': {
                'full_name': 'TEST APPLICANT',
                'date_of_birth': '1977-01-01',
                'nationality': 'TEST',
                'passport_number': f'TEST{secrets.token_hex(4).upper()}',  # Clearly fake
                'expiry_date': '2030-01-01'
            },
            'flags': []
        },
        {
            'type': 'driving_licence',
            'id': f'DOC-DL-{secrets.token_hex(4)}',
            'verified': True,
            'authenticity_score': 0.92,
            'expiry_status': 'valid',
            'extracted_data': {
                'full_name': 'TEST APPLICANT',
                'date_of_birth': '1977-01-01',
                'licence_number': f'TEST{secrets.token_hex(6).upper()}',  # Clearly fake
                'categories': 'B',
                'restrictions': 'Test restriction'
            },
            'flags': ['RESTRICTION_NOTED']
        },
        {
            'type': 'disability_certificate',
            'id': f'DOC-DC-{secrets.token_hex(4)}',
            'verified': True,
            'authenticity_score': 0.98,
            'expiry_status': 'valid',
            'extracted_data': {
                'full_name': 'TEST APPLICANT',
                'disability_type': 'Mobility Impairment - Test',
                'disability_percentage': 30,
                'issue_date': '2020-01-01',
                'valid_until': '2027-01-01',
                'issuing_authority': 'Test Authority'
            },
            'flags': ['DISABILITY_DECLARED']
        },
        {
            'type': 'medical_report',
            'id': f'DOC-MED-{secrets.token_hex(4)}',
            'verified': True,
            'authenticity_score': 0.96,
            'expiry_status': 'valid',
            'extracted_data': {
                'provider': 'Test Medical Provider',
                'report_date': '2025-01-01',
                'physician': 'Dr. Test',
                'conditions': ['Obesity', 'Hypertension', 'Mobility Impairment']
            },
            'flags': ['MULTIPLE_CONDITIONS']
        },
        {
            'type': 'photo',
            'id': f'DOC-PHOTO-{secrets.token_hex(4)}',
            'verified': True,
            'authenticity_score': 0.94,
            'expiry_status': 'valid',
            'extracted_data': {
                'face_detected': True,
                'face_match_score': 0.91
            },
            'flags': []
        },
        {
            'type': 'video_verification',
            'id': f'DOC-VIDEO-{secrets.token_hex(4)}',
            'verified': True,
            'authenticity_score': 0.93,
            'expiry_status': 'valid',
            'extracted_data': {
                'liveness_check': 'passed',
                'identity_match': 0.89,
                'duration_seconds': 45
            },
            'flags': []
        }
    ]
    
    # SYNTHETIC policy data
    policy_data = {
        'id': _generate_synthetic_id("POL"),
        'type': 'Life Insurance',
        'coverage_amount': 350000,
        'annual_premium_base': 1850,
        'term_years': 20,
        'beneficiaries': ['Test Beneficiary 1', 'Test Beneficiary 2'],
        'start_date': '2026-01-01'
    }
    
    return application_id, customer_data, medical_data, documents, policy_data


def generate_report():
    """Generate the comprehensive risk assessment report"""
    
    print("\n" + "=" * 80)
    print("   GENERATING COMPREHENSIVE RISK ASSESSMENT REPORT")
    print("=" * 80)
    
    # Get application data
    application_id, customer_data, medical_data, documents, policy_data = create_application_data()
    
    print(f"\n📋 Application ID: {application_id}")
    print(f"👤 Applicant: {customer_data['name']}, Age {customer_data['age']}")
    print(f"🏥 Disability: {medical_data['disability_percentage']}% ({medical_data['disability_type']})")
    print(f"📊 BMI Category: {medical_data['bmi_category']}")
    print(f"💰 Coverage Requested: £{policy_data['coverage_amount']:,}")
    
    # Initialize report generator
    generator = create_risk_report_generator()
    
    print("\n⚙️  Processing assessment...")
    
    # Generate comprehensive report
    report = generator.generate_report(
        application_id=application_id,
        customer_data=customer_data,
        medical_data=medical_data,
        documents=documents,
        policy_data=policy_data
    )
    
    print(f"✅ Assessment complete in {report.processing_time_seconds:.2f} seconds")
    
    # Display summary
    print("\n" + "-" * 80)
    print("📊 RISK ASSESSMENT SUMMARY")
    print("-" * 80)
    print(f"   Overall Risk Score: {report.overall_risk_score:.1%}")
    print(f"   Risk Category: {report.risk_category.value.replace('_', ' ').upper()}")
    print(f"   Identity Verified: {'✅ Yes' if report.identity_verified else '❌ No'}")
    print(f"   Medical Risk: {report.medical_score:.1%}")
    print(f"   Lifestyle Score: {report.lifestyle_score:.1%}")
    print(f"   Fraud Score: {report.fraud_score:.1%}")
    
    print("\n" + "-" * 80)
    print("🤖 AI RECOMMENDATION")
    print("-" * 80)
    print(f"   Decision: {report.recommendation.recommendation_type.value.replace('_', ' ').upper()}")
    print(f"   Confidence: {report.recommendation.confidence_level:.1%}")
    if report.recommendation.premium_adjustment > 0:
        print(f"   Premium Loading: +{report.recommendation.premium_adjustment:.0%}")
    print(f"\n   Rationale: {report.recommendation.primary_rationale}")
    
    if report.recommendation.exclusions:
        print("\n   ⚠️  Exclusions:")
        for e in report.recommendation.exclusions:
            print(f"      • {e}")
    
    if report.recommendation.conditions:
        print("\n   📋 Conditions:")
        for c in report.recommendation.conditions:
            print(f"      • {c}")
    
    # Generate HTML report
    print("\n📄 Generating downloadable reports...")
    
    html_report = generator.generate_html_report(report)
    text_report = generator.generate_text_report(report)
    json_report = json.dumps(report.to_dict(), indent=2, default=str)
    
    # Save reports
    report_dir = "/workspace/reports"
    os.makedirs(report_dir, exist_ok=True)
    
    # HTML Report
    html_path = f"{report_dir}/risk_assessment_{application_id}.html"
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_report)
    print(f"   ✅ HTML Report: {html_path}")
    
    # Text Report
    text_path = f"{report_dir}/risk_assessment_{application_id}.txt"
    with open(text_path, 'w', encoding='utf-8') as f:
        f.write(text_report)
    print(f"   ✅ Text Report: {text_path}")
    
    # JSON Report (for pipeline)
    json_path = f"{report_dir}/risk_assessment_{application_id}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        f.write(json_report)
    print(f"   ✅ JSON Report: {json_path}")
    
    # Print full text report to console
    print("\n" + "=" * 80)
    print("   FULL RISK ASSESSMENT REPORT")
    print("=" * 80)
    print(text_report)
    
    # Pipeline output
    print("\n" + "=" * 80)
    print("   PIPELINE-READY OUTPUT")
    print("=" * 80)
    
    pipeline_output = {
        'application_id': application_id,
        'report_id': report.report_id,
        'assessment_status': 'completed',
        'risk_score': report.overall_risk_score,
        'risk_category': report.risk_category.value,
        'recommendation': report.recommendation.recommendation_type.value,
        'confidence': report.recommendation.confidence_level,
        'premium_loading': report.recommendation.premium_adjustment,
        'exclusions': report.recommendation.exclusions,
        'conditions': report.recommendation.conditions,
        'monitoring': report.recommendation.monitoring_requirements,
        'review_period_months': report.recommendation.review_period_months,
        'identity_verified': report.identity_verified,
        'documents_verified': len([d for d in report.documents_verified if d.verified]),
        'risk_factors_count': len(report.risk_factors),
        'medical_conditions_count': len(report.medical_conditions),
        'ready_for_decision': True,
        'auto_approve_eligible': report.recommendation.recommendation_type == RecommendationType.AUTO_APPROVE,
        'generated_at': report.assessment_date.isoformat()
    }
    
    print(json.dumps(pipeline_output, indent=2))
    
    # Save pipeline output
    pipeline_path = f"{report_dir}/pipeline_output_{application_id}.json"
    with open(pipeline_path, 'w') as f:
        json.dump(pipeline_output, f, indent=2)
    print(f"\n   ✅ Pipeline Output: {pipeline_path}")
    
    print("\n" + "=" * 80)
    print("   REPORT GENERATION COMPLETE")
    print("=" * 80)
    print(f"\n📂 Reports saved to: {report_dir}/")
    print(f"\n🔗 Open HTML report in browser: file://{os.path.abspath(html_path)}")
    
    return report, pipeline_output


if __name__ == '__main__':
    report, pipeline_output = generate_report()
