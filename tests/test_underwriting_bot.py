"""
Test Suite for Underwriting Bot Service
=======================================
Comprehensive tests for:
- Metadata processing (photos, medical reports, documents, audio, video)
- Risk assessment engine
- Decision making
- Data integrity (customer data preservation)
- Pipeline integration

Author: PHINS Platform
"""

import pytest
import sys
import os
from datetime import datetime, date, timedelta
import json

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.underwriting_bot_service import (
    UnderwritingBotService,
    MetadataType,
    ProcessingStatus,
    ValidationStatus,
    RiskLevel,
    DecisionRecommendation,
    AssessmentStatus,
    UnderwritingMetadata,
    RiskAssessmentReport,
    BotAssessment,
    PhotoAnalyzer,
    MedicalReportAnalyzer,
    OfficialDocumentAnalyzer,
    AudioAnalyzer,
    VideoAnalyzer,
    RiskAssessmentEngine,
    init_underwriting_bot_service
)


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def sample_customers():
    """Sample customer data"""
    return {
        'CUST-001': {
            'id': 'CUST-001',
            'name': 'John Smith',
            'email': 'john.smith@email.com',
            'phone': '+44 7700 900001',
            'dob': '1985-06-15',
            'age': 39,
            'gender': 'male',
            'address': '123 Test Street',
            'city': 'London',
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
            'address': '456 Sample Road',
            'city': 'Manchester',
            'occupation': 'Doctor',
            'created_date': '2023-02-20T11:30:00'
        },
        'CUST-003': {
            'id': 'CUST-003',
            'name': 'Bob Wilson',
            'email': 'bob.wilson@email.com',
            'phone': '+44 7700 900003',
            'dob': '1955-12-01',
            'age': 69,
            'gender': 'male',
            'address': '789 Elder Lane',
            'city': 'Birmingham',
            'occupation': 'Retired',
            'created_date': '2022-06-10T09:00:00'
        }
    }


@pytest.fixture
def sample_policies():
    """Sample policy data"""
    return {
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


@pytest.fixture
def sample_underwriting():
    """Sample underwriting applications"""
    return {
        'UW-001': {
            'id': 'UW-001',
            'policy_id': 'POL-001',
            'customer_id': 'CUST-001',
            'status': 'pending',
            'risk_assessment': 'medium',
            'submitted_date': '2024-01-10T10:30:00'
        }
    }


@pytest.fixture
def sample_claims():
    """Sample claims data"""
    return {
        'CLM-001': {
            'id': 'CLM-001',
            'policy_id': 'POL-002',
            'customer_id': 'CUST-002',
            'type': 'medical',
            'claimed_amount': 5000,
            'status': 'paid',
            'filed_date': '2023-09-01T10:00:00'
        },
        'CLM-002': {
            'id': 'CLM-002',
            'policy_id': 'POL-002',
            'customer_id': 'CUST-002',
            'type': 'medical',
            'claimed_amount': 2500,
            'status': 'approved',
            'filed_date': '2024-01-05T11:00:00'
        }
    }


@pytest.fixture
def bot_service(sample_customers, sample_policies, sample_underwriting, sample_claims):
    """Initialize bot service with sample data"""
    return UnderwritingBotService(
        customers=sample_customers,
        policies=sample_policies,
        underwriting_apps=sample_underwriting,
        claims=sample_claims
    )


# ============================================================================
# Test: Individual Analyzers
# ============================================================================

class TestPhotoAnalyzer:
    """Tests for PhotoAnalyzer"""
    
    def test_photo_analysis_success(self):
        """Test successful photo analysis"""
        analyzer = PhotoAnalyzer()
        metadata = UnderwritingMetadata(
            id='META-001',
            underwriting_id='UW-001',
            customer_id='CUST-001',
            metadata_type=MetadataType.PHOTO,
            file_name='selfie.jpg',
            file_path='/uploads/selfie.jpg',
            file_hash='abc123',
            file_size_bytes=150000,
            mime_type='image/jpeg',
            upload_date=datetime.now()
        )
        
        result = analyzer.analyze(metadata)
        
        assert result['processing_success'] is True
        assert 'features' in result
        assert 'scores' in result
        assert 'identity_confidence' in result['scores']
        assert result['scores']['identity_confidence'] > 0
    
    def test_photo_analysis_returns_quality_score(self):
        """Test that photo analysis returns quality score"""
        analyzer = PhotoAnalyzer()
        metadata = UnderwritingMetadata(
            id='META-002',
            underwriting_id='UW-001',
            customer_id='CUST-001',
            metadata_type=MetadataType.PHOTO,
            file_name='id_photo.png',
            file_path='/uploads/id_photo.png',
            file_hash='def456',
            file_size_bytes=200000,
            mime_type='image/png',
            upload_date=datetime.now()
        )
        
        result = analyzer.analyze(metadata)
        
        assert 'quality_score' in result['scores']
        assert 0 <= result['scores']['quality_score'] <= 1


class TestMedicalReportAnalyzer:
    """Tests for MedicalReportAnalyzer"""
    
    def test_medical_report_analysis_success(self):
        """Test successful medical report analysis"""
        analyzer = MedicalReportAnalyzer()
        metadata = UnderwritingMetadata(
            id='META-003',
            underwriting_id='UW-001',
            customer_id='CUST-001',
            metadata_type=MetadataType.MEDICAL_REPORT,
            file_name='medical_report.pdf',
            file_path='/uploads/medical_report.pdf',
            file_hash='ghi789',
            file_size_bytes=500000,
            mime_type='application/pdf',
            upload_date=datetime.now()
        )
        
        result = analyzer.analyze(metadata)
        
        assert result['processing_success'] is True
        assert 'conditions_found' in result
        assert 'scores' in result
        assert 'medical_risk_score' in result['scores']
    
    def test_medical_report_condition_detection(self):
        """Test medical report detects conditions"""
        analyzer = MedicalReportAnalyzer()
        metadata = UnderwritingMetadata(
            id='META-004',
            underwriting_id='UW-001',
            customer_id='CUST-001',
            metadata_type=MetadataType.MEDICAL_REPORT,
            file_name='health_record.pdf',
            file_path='/uploads/health_record.pdf',
            file_hash='jkl012',
            file_size_bytes=600000,
            mime_type='application/pdf',
            upload_date=datetime.now()
        )
        
        result = analyzer.analyze(metadata)
        
        # Should find at least one condition (simulated)
        assert isinstance(result['conditions_found'], list)
        assert 'medications' in result


class TestOfficialDocumentAnalyzer:
    """Tests for OfficialDocumentAnalyzer"""
    
    def test_passport_analysis(self):
        """Test passport document analysis"""
        analyzer = OfficialDocumentAnalyzer()
        metadata = UnderwritingMetadata(
            id='META-005',
            underwriting_id='UW-001',
            customer_id='CUST-001',
            metadata_type=MetadataType.PASSPORT,
            file_name='passport.pdf',
            file_path='/uploads/passport.pdf',
            file_hash='mno345',
            file_size_bytes=300000,
            mime_type='application/pdf',
            upload_date=datetime.now()
        )
        
        result = analyzer.analyze(metadata, document_type='passport')
        
        assert result['processing_success'] is True
        assert result['document_type'] == 'passport'
        assert 'extracted_fields' in result
        assert 'full_name' in result['extracted_fields']
        assert 'date_of_birth' in result['extracted_fields']
    
    def test_driving_licence_analysis(self):
        """Test driving licence document analysis"""
        analyzer = OfficialDocumentAnalyzer()
        metadata = UnderwritingMetadata(
            id='META-006',
            underwriting_id='UW-001',
            customer_id='CUST-001',
            metadata_type=MetadataType.DRIVING_LICENCE,
            file_name='driving_licence.jpg',
            file_path='/uploads/driving_licence.jpg',
            file_hash='pqr678',
            file_size_bytes=250000,
            mime_type='image/jpeg',
            upload_date=datetime.now()
        )
        
        result = analyzer.analyze(metadata, document_type='driving_licence')
        
        assert result['processing_success'] is True
        assert result['document_type'] == 'driving_licence'
        assert 'licence_number' in result['extracted_fields']
    
    def test_disability_certificate_analysis(self):
        """Test disability certificate analysis"""
        analyzer = OfficialDocumentAnalyzer()
        metadata = UnderwritingMetadata(
            id='META-007',
            underwriting_id='UW-001',
            customer_id='CUST-001',
            metadata_type=MetadataType.DISABILITY_CERTIFICATE,
            file_name='disability_cert.pdf',
            file_path='/uploads/disability_cert.pdf',
            file_hash='stu901',
            file_size_bytes=400000,
            mime_type='application/pdf',
            upload_date=datetime.now()
        )
        
        result = analyzer.analyze(metadata, document_type='disability_certificate')
        
        assert result['processing_success'] is True
        assert 'DISABILITY_DECLARED' in result['flags']


class TestAudioAnalyzer:
    """Tests for AudioAnalyzer"""
    
    def test_audio_analysis_success(self):
        """Test successful audio analysis"""
        analyzer = AudioAnalyzer()
        metadata = UnderwritingMetadata(
            id='META-008',
            underwriting_id='UW-001',
            customer_id='CUST-001',
            metadata_type=MetadataType.AUDIO,
            file_name='health_statement.mp3',
            file_path='/uploads/health_statement.mp3',
            file_hash='vwx234',
            file_size_bytes=1000000,
            mime_type='audio/mpeg',
            upload_date=datetime.now()
        )
        
        result = analyzer.analyze(metadata)
        
        assert result['processing_success'] is True
        assert 'sentiment' in result
        assert 'stress_level' in result['sentiment']


class TestVideoAnalyzer:
    """Tests for VideoAnalyzer"""
    
    def test_video_analysis_success(self):
        """Test successful video analysis"""
        analyzer = VideoAnalyzer()
        metadata = UnderwritingMetadata(
            id='META-009',
            underwriting_id='UW-001',
            customer_id='CUST-001',
            metadata_type=MetadataType.VIDEO,
            file_name='identity_verification.mp4',
            file_path='/uploads/identity_verification.mp4',
            file_hash='yz0123',
            file_size_bytes=5000000,
            mime_type='video/mp4',
            upload_date=datetime.now()
        )
        
        result = analyzer.analyze(metadata)
        
        assert result['processing_success'] is True
        assert 'identity_verification' in result
        assert 'liveness' in result
        assert result['liveness']['is_live'] is True


# ============================================================================
# Test: Risk Assessment Engine
# ============================================================================

class TestRiskAssessmentEngine:
    """Tests for RiskAssessmentEngine"""
    
    def test_calculate_risk_score_low_risk(self):
        """Test risk calculation for low-risk profile"""
        engine = RiskAssessmentEngine()
        
        risk_score, factors = engine.calculate_risk_score(
            identity_score=0.95,
            document_score=0.90,
            medical_score=0.2,  # Low medical risk
            behavioral_score=0.85,
            fraud_score=0.05,  # Low fraud risk
            history_score=0.0,  # No claims history issues
            age=35
        )
        
        assert 0 <= risk_score <= 1
        assert risk_score < 0.4  # Should be low risk
    
    def test_calculate_risk_score_high_risk(self):
        """Test risk calculation for high-risk profile"""
        engine = RiskAssessmentEngine()
        
        risk_score, factors = engine.calculate_risk_score(
            identity_score=0.60,
            document_score=0.70,
            medical_score=0.8,  # High medical risk
            behavioral_score=0.50,
            fraud_score=0.4,  # Elevated fraud risk
            history_score=0.5,  # Some claims history
            age=70
        )
        
        assert 0 <= risk_score <= 1
        assert risk_score > 0.5  # Should be elevated risk
        assert len(factors) > 0  # Should have risk factors
    
    def test_determine_risk_level(self):
        """Test risk level determination"""
        engine = RiskAssessmentEngine()
        
        assert engine.determine_risk_level(0.1) == RiskLevel.VERY_LOW
        assert engine.determine_risk_level(0.3) == RiskLevel.LOW
        assert engine.determine_risk_level(0.5) == RiskLevel.MEDIUM
        assert engine.determine_risk_level(0.7) == RiskLevel.HIGH
        assert engine.determine_risk_level(0.9) == RiskLevel.VERY_HIGH
    
    def test_make_recommendation_approve(self):
        """Test recommendation for low-risk case"""
        engine = RiskAssessmentEngine()
        
        recommendation, confidence, explanation = engine.make_recommendation(
            risk_score=0.25,
            identity_verified=True,
            identity_score=0.90,
            fraud_score=0.1,
            document_score=0.85
        )
        
        assert recommendation == DecisionRecommendation.APPROVE
        assert confidence > 0.8
    
    def test_make_recommendation_refer_on_identity_failure(self):
        """Test recommendation refers when identity fails"""
        engine = RiskAssessmentEngine()
        
        recommendation, confidence, explanation = engine.make_recommendation(
            risk_score=0.30,
            identity_verified=False,
            identity_score=0.50,
            fraud_score=0.1,
            document_score=0.85
        )
        
        assert recommendation == DecisionRecommendation.REFER_MANUAL
        assert 'identity' in explanation.lower() or 'Identity' in explanation
    
    def test_make_recommendation_refer_on_high_fraud(self):
        """Test recommendation refers when fraud score is high"""
        engine = RiskAssessmentEngine()
        
        recommendation, confidence, explanation = engine.make_recommendation(
            risk_score=0.40,
            identity_verified=True,
            identity_score=0.85,
            fraud_score=0.7,  # High fraud
            document_score=0.85
        )
        
        assert recommendation == DecisionRecommendation.REFER_MANUAL
        assert 'fraud' in explanation.lower() or 'Fraud' in explanation


# ============================================================================
# Test: Underwriting Bot Service
# ============================================================================

class TestUnderwritingBotService:
    """Tests for main UnderwritingBotService"""
    
    def test_service_initialization(self, bot_service):
        """Test service initializes correctly"""
        assert bot_service is not None
        assert bot_service.bot_id.startswith('UW-BOT-')
        assert bot_service.version == '1.0.0'
    
    def test_start_assessment(self, bot_service):
        """Test starting a new assessment"""
        assessment = bot_service.start_assessment(
            underwriting_id='UW-001',
            customer_id='CUST-001',
            policy_id='POL-001'
        )
        
        assert assessment is not None
        assert assessment.id.startswith('BOT-ASS-')
        assert assessment.status == AssessmentStatus.INITIATED
        assert assessment.customer_id == 'CUST-001'
        assert assessment.existing_policies_count >= 0
        assert 'name' in assessment.customer_snapshot
    
    def test_add_metadata(self, bot_service):
        """Test adding metadata to assessment"""
        assessment = bot_service.start_assessment(
            underwriting_id='UW-001',
            customer_id='CUST-001',
            policy_id='POL-001'
        )
        
        metadata = bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.PHOTO,
            file_name='selfie.jpg',
            file_path='/uploads/selfie.jpg',
            file_content=b'fake image content',
            mime_type='image/jpeg'
        )
        
        assert metadata is not None
        assert metadata.id.startswith('META-')
        assert metadata.metadata_type == MetadataType.PHOTO
        assert len(assessment.metadata_items) == 1
    
    def test_process_metadata(self, bot_service):
        """Test processing uploaded metadata"""
        assessment = bot_service.start_assessment(
            underwriting_id='UW-001',
            customer_id='CUST-001',
            policy_id='POL-001'
        )
        
        metadata = bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.PASSPORT,
            file_name='passport.pdf',
            file_path='/uploads/passport.pdf',
            file_content=b'fake passport content',
            mime_type='application/pdf'
        )
        
        result = bot_service.process_metadata(metadata.id)
        
        assert result['success'] is True
        assert metadata.processing_status == ProcessingStatus.COMPLETED
    
    def test_process_all_metadata(self, bot_service):
        """Test processing all metadata in assessment"""
        assessment = bot_service.start_assessment(
            underwriting_id='UW-001',
            customer_id='CUST-001',
            policy_id='POL-001'
        )
        
        # Add multiple metadata items
        bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.PHOTO,
            file_name='selfie.jpg',
            file_path='/uploads/selfie.jpg',
            mime_type='image/jpeg'
        )
        
        bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.PASSPORT,
            file_name='passport.pdf',
            file_path='/uploads/passport.pdf',
            mime_type='application/pdf'
        )
        
        result = bot_service.process_all_metadata(assessment.id)
        
        assert result['total_processed'] == 2
    
    def test_run_risk_assessment(self, bot_service):
        """Test running full risk assessment"""
        assessment = bot_service.start_assessment(
            underwriting_id='UW-001',
            customer_id='CUST-001',
            policy_id='POL-001'
        )
        
        # Add and process metadata
        bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.PHOTO,
            file_name='selfie.jpg',
            file_path='/uploads/selfie.jpg',
            mime_type='image/jpeg'
        )
        
        bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.PASSPORT,
            file_name='passport.pdf',
            file_path='/uploads/passport.pdf',
            mime_type='application/pdf'
        )
        
        bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.MEDICAL_REPORT,
            file_name='medical.pdf',
            file_path='/uploads/medical.pdf',
            mime_type='application/pdf'
        )
        
        bot_service.process_all_metadata(assessment.id)
        
        report = bot_service.run_risk_assessment(assessment.id)
        
        assert report is not None
        assert report.id.startswith('REPORT-')
        assert 0 <= report.overall_risk_score <= 1
        assert report.risk_level in RiskLevel
        assert report.recommendation in DecisionRecommendation
        assert assessment.status == AssessmentStatus.DECISION_READY
    
    def test_apply_decision_approve(self, bot_service):
        """Test applying approval decision"""
        assessment = bot_service.start_assessment(
            underwriting_id='UW-001',
            customer_id='CUST-001',
            policy_id='POL-001'
        )
        
        bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.PHOTO,
            file_name='selfie.jpg',
            file_path='/uploads/selfie.jpg',
            mime_type='image/jpeg'
        )
        
        bot_service.process_all_metadata(assessment.id)
        bot_service.run_risk_assessment(assessment.id)
        
        result = bot_service.apply_decision(
            assessment_id=assessment.id,
            decision='approve',
            decided_by='admin_user',
            notes='Low risk, approved automatically'
        )
        
        assert result['success'] is True
        assert assessment.status == AssessmentStatus.APPROVED
    
    def test_apply_decision_reject(self, bot_service):
        """Test applying rejection decision"""
        assessment = bot_service.start_assessment(
            underwriting_id='UW-001',
            customer_id='CUST-001',
            policy_id='POL-001'
        )
        
        bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.PHOTO,
            file_name='selfie.jpg',
            file_path='/uploads/selfie.jpg',
            mime_type='image/jpeg'
        )
        
        bot_service.process_all_metadata(assessment.id)
        bot_service.run_risk_assessment(assessment.id)
        
        result = bot_service.apply_decision(
            assessment_id=assessment.id,
            decision='reject',
            decided_by='admin_user',
            notes='High risk factors identified',
            override_recommendation=True
        )
        
        assert result['success'] is True
        assert assessment.status == AssessmentStatus.REJECTED
        assert assessment.risk_report.human_override is True


# ============================================================================
# Test: Data Integrity
# ============================================================================

class TestDataIntegrity:
    """Tests to verify data integrity is maintained"""
    
    def test_customer_data_not_modified(self, bot_service, sample_customers):
        """Test that customer data is never modified"""
        # Store original customer data
        original_customer = sample_customers['CUST-001'].copy()
        
        # Run full assessment
        assessment = bot_service.start_assessment(
            underwriting_id='UW-001',
            customer_id='CUST-001',
            policy_id='POL-001'
        )
        
        bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.PHOTO,
            file_name='selfie.jpg',
            file_path='/uploads/selfie.jpg',
            mime_type='image/jpeg'
        )
        
        bot_service.process_all_metadata(assessment.id)
        bot_service.run_risk_assessment(assessment.id)
        bot_service.apply_decision(assessment.id, 'approve', 'test')
        
        # Verify customer data unchanged
        current_customer = sample_customers['CUST-001']
        
        assert current_customer['name'] == original_customer['name']
        assert current_customer['email'] == original_customer['email']
        assert current_customer['age'] == original_customer['age']
        assert current_customer['created_date'] == original_customer['created_date']
    
    def test_claims_history_not_modified(self, bot_service, sample_claims):
        """Test that claims history is never modified"""
        # Store original claims
        original_claims_count = len(sample_claims)
        original_claim = sample_claims['CLM-001'].copy()
        
        # Run assessment for customer with claims
        assessment = bot_service.start_assessment(
            underwriting_id='UW-002',
            customer_id='CUST-002',  # Customer with claims
            policy_id='POL-002'
        )
        
        bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.MEDICAL_REPORT,
            file_name='medical.pdf',
            file_path='/uploads/medical.pdf',
            mime_type='application/pdf'
        )
        
        bot_service.process_all_metadata(assessment.id)
        bot_service.run_risk_assessment(assessment.id)
        
        # Verify claims unchanged
        assert len(sample_claims) == original_claims_count
        assert sample_claims['CLM-001']['claimed_amount'] == original_claim['claimed_amount']
        assert sample_claims['CLM-001']['status'] == original_claim['status']
    
    def test_customer_snapshot_is_readonly(self, bot_service):
        """Test that customer snapshot is read-only copy"""
        assessment = bot_service.start_assessment(
            underwriting_id='UW-001',
            customer_id='CUST-001',
            policy_id='POL-001'
        )
        
        # Modify snapshot (should not affect original)
        assessment.customer_snapshot['name'] = 'MODIFIED NAME'
        
        # Original should be unchanged
        assert bot_service._customers['CUST-001']['name'] == 'John Smith'


# ============================================================================
# Test: Full Workflow
# ============================================================================

class TestFullWorkflow:
    """End-to-end workflow tests"""
    
    def test_complete_assessment_workflow(self, bot_service):
        """Test complete assessment workflow from start to decision"""
        # 1. Start assessment
        assessment = bot_service.start_assessment(
            underwriting_id='UW-001',
            customer_id='CUST-001',
            policy_id='POL-001'
        )
        assert assessment.status == AssessmentStatus.INITIATED
        
        # 2. Add various metadata types
        bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.PHOTO,
            file_name='selfie.jpg',
            file_path='/uploads/selfie.jpg',
            mime_type='image/jpeg'
        )
        
        bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.PASSPORT,
            file_name='passport.pdf',
            file_path='/uploads/passport.pdf',
            mime_type='application/pdf'
        )
        
        bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.MEDICAL_REPORT,
            file_name='medical.pdf',
            file_path='/uploads/medical.pdf',
            mime_type='application/pdf'
        )
        
        bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.VIDEO,
            file_name='identity_check.mp4',
            file_path='/uploads/identity_check.mp4',
            mime_type='video/mp4'
        )
        
        assert len(assessment.metadata_items) == 4
        
        # 3. Process all metadata
        process_result = bot_service.process_all_metadata(assessment.id)
        assert process_result['total_processed'] == 4
        
        # 4. Run risk assessment
        report = bot_service.run_risk_assessment(assessment.id)
        assert report is not None
        assert assessment.status == AssessmentStatus.DECISION_READY
        
        # 5. Get summary
        summary = bot_service.get_assessment_summary(assessment.id)
        assert 'risk_summary' in summary
        assert 'full_explanation' in summary
        
        # 6. Apply decision
        decision_result = bot_service.apply_decision(
            assessment_id=assessment.id,
            decision='approve',
            decided_by='test_admin'
        )
        assert decision_result['success'] is True
        
        # 7. Verify final state
        assert assessment.completed_at is not None
        assert assessment.risk_report.id == report.id


# ============================================================================
# Test: Report Generation
# ============================================================================

class TestReportGeneration:
    """Tests for report generation"""
    
    def test_report_contains_all_scores(self, bot_service):
        """Test that report contains all component scores"""
        assessment = bot_service.start_assessment(
            underwriting_id='UW-001',
            customer_id='CUST-001',
            policy_id='POL-001'
        )
        
        bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.PHOTO,
            file_name='selfie.jpg',
            file_path='/uploads/selfie.jpg',
            mime_type='image/jpeg'
        )
        
        bot_service.process_all_metadata(assessment.id)
        report = bot_service.run_risk_assessment(assessment.id)
        
        # Check all scores present
        assert hasattr(report, 'identity_score')
        assert hasattr(report, 'document_score')
        assert hasattr(report, 'medical_score')
        assert hasattr(report, 'behavioral_score')
        assert hasattr(report, 'fraud_score')
    
    def test_report_to_dict_serialization(self, bot_service):
        """Test that report can be serialized to dict"""
        assessment = bot_service.start_assessment(
            underwriting_id='UW-001',
            customer_id='CUST-001',
            policy_id='POL-001'
        )
        
        bot_service.add_metadata(
            assessment_id=assessment.id,
            metadata_type=MetadataType.PHOTO,
            file_name='selfie.jpg',
            file_path='/uploads/selfie.jpg',
            mime_type='image/jpeg'
        )
        
        bot_service.process_all_metadata(assessment.id)
        report = bot_service.run_risk_assessment(assessment.id)
        
        report_dict = report.to_dict()
        
        assert isinstance(report_dict, dict)
        assert 'id' in report_dict
        assert 'overall_risk_score' in report_dict
        assert 'recommendation' in report_dict
        
        # Should be JSON serializable
        json_str = json.dumps(report_dict)
        assert len(json_str) > 0


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
