#!/usr/bin/env python3
"""
Generate Comprehensive Risk Assessment Report
=============================================
Generates a full AI executive risk assessment report for:
Application #UW-20260106-6316

Applicant Profile:
- Age: 47 years
- Disability: 30% 
- Medical Conditions: Obesity (Class I), Hypertension
- Policy Type: Life Insurance

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


def create_application_data():
    """Create the specific application data for UW-20260106-6316"""
    
    # Application details
    application_id = "UW-20260106-6316"
    
    # Customer data (47-year-old with disability)
    customer_data = {
        'id': 'CUST-20260106-6316',
        'name': 'Michael Thompson',
        'email': 'michael.thompson@email.com',
        'phone': '+44 7700 123456',
        'dob': '1979-03-15',
        'age': 47,
        'gender': 'male',
        'address': '45 Wellington Road',
        'city': 'Birmingham',
        'location': 'Birmingham, West Midlands',
        'state': 'West Midlands',
        'zip': 'B15 2QJ',
        'occupation': 'Retail Manager',
        'marital_status': 'married',
        'dependents': 2,
        'annual_income': 52000,
        'created_date': '2026-01-06T10:00:00'
    }
    
    # Medical data (30% disability, obesity)
    medical_data = {
        'disability_percentage': 30,
        'disability_type': 'Mobility Impairment - Lower Limb',
        'disability_cause': 'Road Traffic Accident (2019)',
        'disability_certified': True,
        'disability_certificate_date': '2020-01-15',
        'bmi': 32.5,
        'bmi_category': 'Obese Class I',
        'height_cm': 178,
        'weight_kg': 103,
        'blood_pressure': '142/88',
        'cholesterol_total': 5.8,
        'smoking_status': 'non_smoker',
        'alcohol_units_weekly': 8,
        'exercise_hours_weekly': 2,
        'family_history': {
            'heart_disease': True,
            'diabetes': False,
            'cancer': False,
            'stroke': True
        },
        'conditions': [
            {
                'name': 'Obesity',
                'icd_code': 'E66.9',
                'severity': 'moderate',
                'diagnosed_date': '2021-06-20',
                'status': 'active',
                'treatment': 'Dietary management, exercise program, nutritionist consultations',
                'risk_impact': 0.25,
                'exclusion_recommended': False,
                'loading_percentage': 15,
                'notes': 'BMI 32.5 (Class I Obesity). Patient engaged with weight management program. No recent complications.'
            },
            {
                'name': 'Essential Hypertension',
                'icd_code': 'I10',
                'severity': 'mild',
                'diagnosed_date': '2022-03-10',
                'status': 'controlled',
                'treatment': 'Lisinopril 10mg daily, lifestyle modifications',
                'risk_impact': 0.20,
                'exclusion_recommended': False,
                'loading_percentage': 10,
                'notes': 'Blood pressure well controlled on medication. Regular monitoring in place.'
            },
            {
                'name': 'Mobility Impairment - Left Leg',
                'icd_code': 'M62.50',
                'severity': 'moderate',
                'diagnosed_date': '2019-08-15',
                'status': 'stable',
                'treatment': 'Physiotherapy, mobility aids, annual orthopaedic review',
                'risk_impact': 0.15,
                'exclusion_recommended': True,
                'loading_percentage': 0,
                'notes': 'Result of RTA in 2019. 30% disability rating. Stable condition, uses walking stick.'
            }
        ],
        'medications': [
            {'name': 'Lisinopril', 'dosage': '10mg', 'frequency': 'once daily', 'purpose': 'Hypertension'},
            {'name': 'Paracetamol', 'dosage': '500mg', 'frequency': 'as needed', 'purpose': 'Pain management'},
            {'name': 'Vitamin D3', 'dosage': '1000IU', 'frequency': 'once daily', 'purpose': 'Supplement'}
        ],
        'recent_tests': {
            'date': '2025-11-15',
            'glucose_fasting': 5.2,
            'hba1c': 5.4,
            'liver_function': 'Normal',
            'kidney_function': 'Normal',
            'ecg': 'Normal sinus rhythm'
        }
    }
    
    # Documents submitted
    documents = [
        {
            'type': 'passport',
            'id': 'DOC-PASS-001',
            'verified': True,
            'authenticity_score': 0.95,
            'expiry_status': 'valid',
            'extracted_data': {
                'full_name': 'MICHAEL JAMES THOMPSON',
                'date_of_birth': '1979-03-15',
                'nationality': 'BRITISH',
                'passport_number': 'AB1234567',
                'expiry_date': '2030-05-20'
            },
            'flags': []
        },
        {
            'type': 'driving_licence',
            'id': 'DOC-DL-001',
            'verified': True,
            'authenticity_score': 0.92,
            'expiry_status': 'valid',
            'extracted_data': {
                'full_name': 'MICHAEL JAMES THOMPSON',
                'date_of_birth': '1979-03-15',
                'licence_number': 'THOMP903155MJ9AB',
                'categories': 'B - Automatic only',
                'restrictions': 'Automatic transmission only due to mobility'
            },
            'flags': ['RESTRICTION_NOTED']
        },
        {
            'type': 'disability_certificate',
            'id': 'DOC-DC-001',
            'verified': True,
            'authenticity_score': 0.98,
            'expiry_status': 'valid',
            'extracted_data': {
                'full_name': 'MICHAEL JAMES THOMPSON',
                'disability_type': 'Mobility Impairment - Lower Limb',
                'disability_percentage': 30,
                'issue_date': '2020-01-15',
                'valid_until': '2027-01-14',
                'issuing_authority': 'Department for Work and Pensions'
            },
            'flags': ['DISABILITY_DECLARED']
        },
        {
            'type': 'medical_report',
            'id': 'DOC-MED-001',
            'verified': True,
            'authenticity_score': 0.96,
            'expiry_status': 'valid',
            'extracted_data': {
                'provider': 'Birmingham NHS Trust',
                'report_date': '2025-11-20',
                'physician': 'Dr. Sarah Williams',
                'conditions': ['Obesity', 'Hypertension', 'Mobility Impairment']
            },
            'flags': ['MULTIPLE_CONDITIONS']
        },
        {
            'type': 'photo',
            'id': 'DOC-PHOTO-001',
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
            'id': 'DOC-VIDEO-001',
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
    
    # Policy data
    policy_data = {
        'id': 'POL-20260106-6316',
        'type': 'Life Insurance',
        'coverage_amount': 350000,
        'annual_premium_base': 1850,
        'term_years': 20,
        'beneficiaries': ['Spouse - Sarah Thompson', 'Children - Emma & James Thompson'],
        'start_date': '2026-02-01'
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
