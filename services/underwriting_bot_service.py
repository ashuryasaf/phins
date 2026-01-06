"""
PHINS Underwriting Bot Service
==============================
AI-powered underwriting bot that processes metadata (photos, medical reports,
official documents, audio, video) and creates comprehensive risk assessment reports
to support automated and assisted underwriting decisions.

Features:
- Multi-type metadata processing (photos, medical reports, documents, audio, video)
- AI-based risk assessment engine
- Full risk assessment report generation
- Integration with existing pipeline (preserves all customer data)
- Validated process as part of the underwriting pipeline
- Data integrity protection (never modifies existing customer data)

Author: PHINS Platform
Version: 1.0.0
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, date, timedelta
from enum import Enum
from typing import Dict, List, Any, Optional, Tuple, Callable
import hashlib
import json
import uuid
import re
import math


# ============================================================================
# ENUMS - Underwriting Bot Types
# ============================================================================

class MetadataType(Enum):
    """Types of metadata that can be processed"""
    PHOTO = "photo"
    MEDICAL_REPORT = "medical_report"
    PASSPORT = "passport"
    DRIVING_LICENCE = "driving_licence"
    NATIONAL_INSURANCE = "national_insurance"
    DISABILITY_CERTIFICATE = "disability_certificate"
    AUDIO = "audio"
    VIDEO = "video"
    OTHER_DOCUMENT = "other_document"


class ProcessingStatus(Enum):
    """Status of metadata processing"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    REQUIRES_REVIEW = "requires_review"


class ValidationStatus(Enum):
    """Validation status for metadata"""
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"
    SUSPICIOUS = "suspicious"


class RiskLevel(Enum):
    """Risk level categories"""
    VERY_LOW = "very_low"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class DecisionRecommendation(Enum):
    """AI decision recommendations"""
    APPROVE = "approve"
    APPROVE_CONDITIONAL = "approve_conditional"
    REFER_MANUAL = "refer_manual"
    DECLINE = "decline"
    PENDING_INFO = "pending_info"


class AssessmentStatus(Enum):
    """Assessment lifecycle status"""
    INITIATED = "initiated"
    COLLECTING_METADATA = "collecting_metadata"
    VALIDATING_METADATA = "validating_metadata"
    PROCESSING = "processing"
    RISK_ASSESSING = "risk_assessing"
    DECISION_READY = "decision_ready"
    APPROVED = "approved"
    REJECTED = "rejected"
    REFERRED = "referred"
    CONDITIONAL_APPROVAL = "conditional_approval"
    COMPLETED = "completed"
    VALIDATION_FAILED = "validation_failed"


# ============================================================================
# DATA CLASSES - Metadata and Assessment Components
# ============================================================================

@dataclass
class UnderwritingMetadata:
    """Represents uploaded metadata for underwriting assessment"""
    id: str
    underwriting_id: str
    customer_id: str
    metadata_type: MetadataType
    file_name: str
    file_path: str
    file_hash: str
    file_size_bytes: int
    mime_type: str
    upload_date: datetime
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
    processing_result: Dict[str, Any] = field(default_factory=dict)
    extracted_data: Dict[str, Any] = field(default_factory=dict)
    validation_status: ValidationStatus = ValidationStatus.PENDING
    validation_notes: str = ""
    confidence_score: float = 0.0
    created_date: datetime = field(default_factory=datetime.now)
    updated_date: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'id': self.id,
            'underwriting_id': self.underwriting_id,
            'customer_id': self.customer_id,
            'metadata_type': self.metadata_type.value,
            'file_name': self.file_name,
            'file_path': self.file_path,
            'file_hash': self.file_hash,
            'file_size_bytes': self.file_size_bytes,
            'mime_type': self.mime_type,
            'upload_date': self.upload_date.isoformat() if self.upload_date else None,
            'processing_status': self.processing_status.value,
            'processing_result': self.processing_result,
            'extracted_data': self.extracted_data,
            'validation_status': self.validation_status.value,
            'validation_notes': self.validation_notes,
            'confidence_score': self.confidence_score,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }


@dataclass
class ExtractedFeature:
    """Feature extracted from metadata"""
    id: str
    metadata_id: str
    feature_type: str  # identity, health, document, behavioral
    feature_name: str
    feature_value: Any
    confidence: float
    source_location: str = ""  # Where in the document/media this was found
    created_date: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'metadata_id': self.metadata_id,
            'feature_type': self.feature_type,
            'feature_name': self.feature_name,
            'feature_value': str(self.feature_value),
            'confidence': self.confidence,
            'source_location': self.source_location,
            'created_date': self.created_date.isoformat() if self.created_date else None
        }


@dataclass
class RiskFactor:
    """Individual risk factor identified during assessment"""
    id: str
    report_id: str
    factor_category: str  # age, health, lifestyle, occupation, location, history
    factor_name: str
    factor_value: Any
    impact_score: float  # -1.0 (reduces risk) to 1.0 (increases risk)
    impact_direction: str  # positive (increases risk), negative (decreases risk), neutral
    source_metadata_id: Optional[str] = None
    explanation: str = ""
    created_date: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'report_id': self.report_id,
            'factor_category': self.factor_category,
            'factor_name': self.factor_name,
            'factor_value': str(self.factor_value),
            'impact_score': self.impact_score,
            'impact_direction': self.impact_direction,
            'source_metadata_id': self.source_metadata_id,
            'explanation': self.explanation,
            'created_date': self.created_date.isoformat() if self.created_date else None
        }


@dataclass
class RiskAssessmentReport:
    """Comprehensive risk assessment report"""
    id: str
    underwriting_id: str
    customer_id: str
    assessment_date: datetime
    overall_risk_score: float  # 0.0 (lowest risk) to 1.0 (highest risk)
    risk_level: RiskLevel
    
    # Component scores
    identity_verified: bool
    identity_score: float
    document_score: float
    medical_score: float
    behavioral_score: float
    fraud_score: float
    
    # Decision
    recommendation: DecisionRecommendation
    confidence_level: float
    risk_factors: List[RiskFactor] = field(default_factory=list)
    explanation: str = ""
    
    # Human override
    human_override: bool = False
    human_decision: Optional[str] = None
    human_notes: str = ""
    
    # Metadata
    metadata_processed: List[str] = field(default_factory=list)  # List of metadata IDs
    processing_time_seconds: float = 0.0
    created_date: datetime = field(default_factory=datetime.now)
    updated_date: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'underwriting_id': self.underwriting_id,
            'customer_id': self.customer_id,
            'assessment_date': self.assessment_date.isoformat() if self.assessment_date else None,
            'overall_risk_score': self.overall_risk_score,
            'risk_level': self.risk_level.value,
            'identity_verified': self.identity_verified,
            'identity_score': self.identity_score,
            'document_score': self.document_score,
            'medical_score': self.medical_score,
            'behavioral_score': self.behavioral_score,
            'fraud_score': self.fraud_score,
            'recommendation': self.recommendation.value,
            'confidence_level': self.confidence_level,
            'risk_factors': [rf.to_dict() for rf in self.risk_factors],
            'explanation': self.explanation,
            'human_override': self.human_override,
            'human_decision': self.human_decision,
            'human_notes': self.human_notes,
            'metadata_processed': self.metadata_processed,
            'processing_time_seconds': self.processing_time_seconds,
            'created_date': self.created_date.isoformat() if self.created_date else None,
            'updated_date': self.updated_date.isoformat() if self.updated_date else None
        }
    
    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of the report"""
        return {
            'report_id': self.id,
            'risk_score': f"{self.overall_risk_score:.2%}",
            'risk_level': self.risk_level.value.replace('_', ' ').title(),
            'recommendation': self.recommendation.value.replace('_', ' ').title(),
            'confidence': f"{self.confidence_level:.2%}",
            'identity_verified': self.identity_verified,
            'factors_count': len(self.risk_factors),
            'high_risk_factors': sum(1 for f in self.risk_factors if f.impact_score > 0.5)
        }


@dataclass 
class BotAssessment:
    """Complete bot assessment session"""
    id: str
    underwriting_id: str
    customer_id: str
    policy_id: str
    status: AssessmentStatus
    metadata_items: List[UnderwritingMetadata] = field(default_factory=list)
    extracted_features: List[ExtractedFeature] = field(default_factory=list)
    risk_report: Optional[RiskAssessmentReport] = None
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    
    # Customer data snapshot (READ-ONLY - for reference, not modified)
    customer_snapshot: Dict[str, Any] = field(default_factory=dict)
    existing_policies_count: int = 0
    existing_claims_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'underwriting_id': self.underwriting_id,
            'customer_id': self.customer_id,
            'policy_id': self.policy_id,
            'status': self.status.value,
            'metadata_count': len(self.metadata_items),
            'features_extracted': len(self.extracted_features),
            'has_risk_report': self.risk_report is not None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'existing_policies_count': self.existing_policies_count,
            'existing_claims_count': self.existing_claims_count
        }


# ============================================================================
# METADATA ANALYZERS
# ============================================================================

class PhotoAnalyzer:
    """Analyzes photos for identity verification and health indicators"""
    
    def __init__(self):
        self.supported_formats = ['image/jpeg', 'image/png', 'image/webp']
        
    def analyze(self, metadata: UnderwritingMetadata, file_content: bytes = None) -> Dict[str, Any]:
        """
        Analyze a photo for:
        - Face detection and quality
        - Identity verification potential
        - Visible health indicators
        - Document photo validation
        """
        result = {
            'analysis_type': 'photo',
            'features': [],
            'scores': {},
            'flags': []
        }
        
        # Simulated analysis (in production, would use actual CV/ML models)
        # Face detection
        face_detected = True  # Simulated
        face_quality = 0.85  # Simulated quality score
        
        result['features'].append({
            'name': 'face_detected',
            'value': face_detected,
            'confidence': 0.95
        })
        
        result['features'].append({
            'name': 'face_quality',
            'value': face_quality,
            'confidence': 0.90
        })
        
        # Image quality assessment
        image_quality = 0.88  # Simulated
        result['features'].append({
            'name': 'image_quality',
            'value': image_quality,
            'confidence': 0.92
        })
        
        # Calculate scores
        result['scores'] = {
            'identity_confidence': face_quality * 0.95 if face_detected else 0.0,
            'quality_score': image_quality,
            'usability_score': (face_quality + image_quality) / 2 if face_detected else 0.0
        }
        
        # Flags
        if not face_detected:
            result['flags'].append('NO_FACE_DETECTED')
        if face_quality < 0.6:
            result['flags'].append('LOW_FACE_QUALITY')
        if image_quality < 0.5:
            result['flags'].append('LOW_IMAGE_QUALITY')
            
        result['processing_success'] = True
        return result


class MedicalReportAnalyzer:
    """Analyzes medical reports for health risk assessment"""
    
    # Common medical conditions and their risk impact
    CONDITION_RISK_MAPPING = {
        'diabetes': {'category': 'chronic', 'base_risk': 0.6, 'multiplier': 1.3},
        'hypertension': {'category': 'chronic', 'base_risk': 0.5, 'multiplier': 1.2},
        'heart_disease': {'category': 'critical', 'base_risk': 0.8, 'multiplier': 1.5},
        'cancer': {'category': 'critical', 'base_risk': 0.85, 'multiplier': 1.8},
        'asthma': {'category': 'manageable', 'base_risk': 0.3, 'multiplier': 1.1},
        'obesity': {'category': 'lifestyle', 'base_risk': 0.4, 'multiplier': 1.2},
        'depression': {'category': 'mental', 'base_risk': 0.35, 'multiplier': 1.15},
        'anxiety': {'category': 'mental', 'base_risk': 0.3, 'multiplier': 1.1},
        'arthritis': {'category': 'chronic', 'base_risk': 0.35, 'multiplier': 1.1},
        'copd': {'category': 'chronic', 'base_risk': 0.6, 'multiplier': 1.4},
    }
    
    def __init__(self):
        self.supported_formats = ['application/pdf', 'image/jpeg', 'image/png', 'text/plain']
    
    def analyze(self, metadata: UnderwritingMetadata, file_content: bytes = None,
                extracted_text: str = "") -> Dict[str, Any]:
        """
        Analyze medical report for:
        - Pre-existing conditions
        - Current medications
        - Risk indicators
        - Lab result anomalies
        """
        result = {
            'analysis_type': 'medical_report',
            'conditions_found': [],
            'medications': [],
            'lab_results': [],
            'risk_indicators': [],
            'scores': {},
            'flags': []
        }
        
        # Simulated text extraction and analysis
        # In production, would use OCR and NLP
        
        # Simulate finding some conditions based on file analysis
        simulated_conditions = ['hypertension']  # Example condition found
        
        for condition in simulated_conditions:
            if condition in self.CONDITION_RISK_MAPPING:
                cond_data = self.CONDITION_RISK_MAPPING[condition]
                result['conditions_found'].append({
                    'condition': condition,
                    'category': cond_data['category'],
                    'risk_impact': cond_data['base_risk'],
                    'confidence': 0.85
                })
        
        # Simulate medication detection
        result['medications'] = [
            {'name': 'Lisinopril', 'purpose': 'blood_pressure', 'risk_modifier': 0.1}
        ]
        
        # Calculate medical risk score
        base_risk = 0.2  # Healthy baseline
        for cond in result['conditions_found']:
            base_risk += cond['risk_impact'] * 0.3
        
        base_risk = min(base_risk, 1.0)
        
        result['scores'] = {
            'medical_risk_score': base_risk,
            'conditions_severity': len(result['conditions_found']) * 0.15,
            'medication_impact': len(result['medications']) * 0.05
        }
        
        # Add flags
        if base_risk > 0.7:
            result['flags'].append('HIGH_MEDICAL_RISK')
        if any(c['category'] == 'critical' for c in result['conditions_found']):
            result['flags'].append('CRITICAL_CONDITION_PRESENT')
            
        result['processing_success'] = True
        return result


class OfficialDocumentAnalyzer:
    """Analyzes official documents (passport, driving licence, NI, disability cert)"""
    
    DOCUMENT_FIELDS = {
        'passport': ['full_name', 'date_of_birth', 'nationality', 'passport_number', 
                     'issue_date', 'expiry_date', 'place_of_birth', 'gender'],
        'driving_licence': ['full_name', 'date_of_birth', 'licence_number', 'categories',
                            'issue_date', 'expiry_date', 'address', 'restrictions'],
        'national_insurance': ['full_name', 'ni_number', 'date_of_birth'],
        'disability_certificate': ['full_name', 'date_of_birth', 'disability_type',
                                   'disability_level', 'issue_date', 'valid_until',
                                   'issuing_authority', 'benefits_entitled']
    }
    
    def __init__(self):
        self.supported_formats = ['application/pdf', 'image/jpeg', 'image/png']
    
    def analyze(self, metadata: UnderwritingMetadata, file_content: bytes = None,
                document_type: str = "") -> Dict[str, Any]:
        """
        Analyze official document for:
        - Data extraction (OCR)
        - Authenticity verification
        - Expiry checking
        - Cross-reference validation
        """
        doc_type = document_type or metadata.metadata_type.value
        
        result = {
            'analysis_type': 'official_document',
            'document_type': doc_type,
            'extracted_fields': {},
            'authenticity': {},
            'scores': {},
            'flags': []
        }
        
        # Simulated OCR and document analysis
        # In production, would use actual OCR and document verification services
        
        if doc_type == 'passport':
            result['extracted_fields'] = {
                'full_name': 'JOHN SMITH',  # Simulated
                'date_of_birth': '1985-06-15',
                'nationality': 'BRITISH',
                'passport_number': 'AB123456',
                'issue_date': '2020-01-15',
                'expiry_date': '2030-01-14',
                'gender': 'M'
            }
        elif doc_type == 'driving_licence':
            result['extracted_fields'] = {
                'full_name': 'JOHN SMITH',
                'date_of_birth': '1985-06-15',
                'licence_number': 'SMITH806159J99AB',
                'categories': 'B',
                'expiry_date': '2025-06-15'
            }
        elif doc_type == 'national_insurance':
            result['extracted_fields'] = {
                'full_name': 'JOHN SMITH',
                'ni_number': 'AB123456C',
                'date_of_birth': '1985-06-15'
            }
        elif doc_type == 'disability_certificate':
            result['extracted_fields'] = {
                'full_name': 'JOHN SMITH',
                'disability_type': 'mobility',
                'disability_level': 'moderate',
                'valid_until': '2026-12-31',
                'issuing_authority': 'DWP'
            }
            # Add risk consideration for disability
            result['flags'].append('DISABILITY_DECLARED')
        
        # Authenticity checks (simulated)
        result['authenticity'] = {
            'format_valid': True,
            'security_features': 0.9,
            'tampering_detected': False,
            'machine_readable': True
        }
        
        # Check expiry
        expiry_str = result['extracted_fields'].get('expiry_date') or result['extracted_fields'].get('valid_until')
        if expiry_str:
            try:
                expiry = datetime.strptime(expiry_str, '%Y-%m-%d').date()
                days_to_expiry = (expiry - date.today()).days
                result['extracted_fields']['days_to_expiry'] = days_to_expiry
                
                if days_to_expiry < 0:
                    result['flags'].append('DOCUMENT_EXPIRED')
                elif days_to_expiry < 90:
                    result['flags'].append('DOCUMENT_EXPIRING_SOON')
            except:
                pass
        
        # Calculate scores
        authenticity_score = (
            (1.0 if result['authenticity']['format_valid'] else 0.0) * 0.3 +
            result['authenticity']['security_features'] * 0.4 +
            (0.0 if result['authenticity']['tampering_detected'] else 1.0) * 0.3
        )
        
        result['scores'] = {
            'authenticity_score': authenticity_score,
            'completeness_score': len(result['extracted_fields']) / 8,  # Ratio of fields found
            'validity_score': 0.0 if 'DOCUMENT_EXPIRED' in result['flags'] else 1.0
        }
        
        result['processing_success'] = True
        return result


class AudioAnalyzer:
    """Analyzes audio recordings for underwriting assessment"""
    
    def __init__(self):
        self.supported_formats = ['audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/webm']
    
    def analyze(self, metadata: UnderwritingMetadata, file_content: bytes = None,
                transcription: str = "") -> Dict[str, Any]:
        """
        Analyze audio for:
        - Transcription
        - Sentiment analysis
        - Stress detection
        - Health indicators in voice
        """
        result = {
            'analysis_type': 'audio',
            'transcription': '',
            'sentiment': {},
            'health_indicators': [],
            'scores': {},
            'flags': []
        }
        
        # Simulated transcription (in production, would use speech-to-text)
        result['transcription'] = transcription or "Transcription not available"
        
        # Simulated sentiment analysis
        result['sentiment'] = {
            'overall': 'neutral',
            'confidence': 0.78,
            'emotions_detected': ['calm'],
            'stress_level': 0.2  # 0-1 scale
        }
        
        # Simulated voice health analysis
        result['health_indicators'] = [
            {'indicator': 'speech_clarity', 'value': 'normal', 'confidence': 0.85},
            {'indicator': 'breathing_pattern', 'value': 'regular', 'confidence': 0.72}
        ]
        
        # Calculate scores
        result['scores'] = {
            'stress_score': result['sentiment']['stress_level'],
            'clarity_score': 0.85,
            'authenticity_score': 0.90  # Voice authenticity
        }
        
        # Flags
        if result['sentiment']['stress_level'] > 0.7:
            result['flags'].append('HIGH_STRESS_DETECTED')
            
        result['processing_success'] = True
        return result


class VideoAnalyzer:
    """Analyzes video recordings for identity verification and assessment"""
    
    def __init__(self):
        self.supported_formats = ['video/mp4', 'video/webm', 'video/quicktime']
    
    def analyze(self, metadata: UnderwritingMetadata, file_content: bytes = None) -> Dict[str, Any]:
        """
        Analyze video for:
        - Face matching with photos/documents
        - Liveness detection
        - Identity verification
        - Behavioral analysis
        """
        result = {
            'analysis_type': 'video',
            'identity_verification': {},
            'liveness': {},
            'behavioral': [],
            'scores': {},
            'flags': []
        }
        
        # Simulated video analysis
        result['identity_verification'] = {
            'face_detected': True,
            'face_match_score': 0.92,  # Match with document photos
            'multiple_faces': False,
            'face_consistent_throughout': True
        }
        
        result['liveness'] = {
            'is_live': True,
            'confidence': 0.95,
            'spoof_detection': 'passed',
            'eye_blink_detected': True,
            'head_movement_detected': True
        }
        
        result['behavioral'] = [
            {'aspect': 'engagement', 'score': 0.85},
            {'aspect': 'nervousness', 'score': 0.25},
            {'aspect': 'consistency', 'score': 0.90}
        ]
        
        # Calculate scores
        result['scores'] = {
            'identity_confidence': result['identity_verification']['face_match_score'],
            'liveness_score': result['liveness']['confidence'] if result['liveness']['is_live'] else 0.0,
            'behavioral_score': sum(b['score'] for b in result['behavioral']) / len(result['behavioral'])
        }
        
        # Flags
        if not result['liveness']['is_live']:
            result['flags'].append('LIVENESS_FAILED')
        if result['identity_verification']['face_match_score'] < 0.7:
            result['flags'].append('LOW_IDENTITY_MATCH')
        if result['identity_verification']['multiple_faces']:
            result['flags'].append('MULTIPLE_FACES_DETECTED')
            
        result['processing_success'] = True
        return result


# ============================================================================
# RISK ASSESSMENT ENGINE
# ============================================================================

class RiskAssessmentEngine:
    """
    AI-powered risk assessment engine.
    
    Combines features from all metadata analyzers to produce:
    - Overall risk score
    - Risk level classification
    - Decision recommendation
    - Detailed explanation
    """
    
    # Risk thresholds
    RISK_THRESHOLDS = {
        RiskLevel.VERY_LOW: (0.0, 0.2),
        RiskLevel.LOW: (0.2, 0.4),
        RiskLevel.MEDIUM: (0.4, 0.6),
        RiskLevel.HIGH: (0.6, 0.8),
        RiskLevel.VERY_HIGH: (0.8, 1.0)
    }
    
    # Decision thresholds
    DECISION_RULES = {
        'auto_approve_max_risk': 0.35,
        'conditional_approve_max_risk': 0.55,
        'refer_max_risk': 0.75,
        'min_identity_score': 0.7,
        'max_fraud_score': 0.5,
        'min_document_score': 0.6,
    }
    
    # Weight factors for different score components
    SCORE_WEIGHTS = {
        'identity': 0.20,
        'document': 0.15,
        'medical': 0.30,
        'behavioral': 0.10,
        'fraud': 0.15,
        'history': 0.10
    }
    
    def __init__(self):
        self.engine_id = f"RISK-ENG-{uuid.uuid4().hex[:8]}"
    
    def calculate_risk_score(self, 
                             identity_score: float,
                             document_score: float,
                             medical_score: float,
                             behavioral_score: float,
                             fraud_score: float,
                             history_score: float = 0.0,
                             age: int = None,
                             occupation_risk: float = 0.0) -> Tuple[float, List[RiskFactor]]:
        """
        Calculate overall risk score from component scores.
        
        Args:
            identity_score: 0-1, higher = more confident identity
            document_score: 0-1, higher = better document quality
            medical_score: 0-1, higher = HIGHER medical risk
            behavioral_score: 0-1, higher = better behavioral assessment
            fraud_score: 0-1, higher = HIGHER fraud risk
            history_score: 0-1, higher = HIGHER claims history risk
            age: Customer age in years
            occupation_risk: 0-1, occupation-based risk factor
            
        Returns:
            Tuple of (overall_risk_score, list of risk factors)
        """
        risk_factors = []
        
        # Invert scores where higher is better (to make higher = more risk for calculation)
        identity_risk = 1.0 - identity_score
        document_risk = 1.0 - document_score
        behavioral_risk = 1.0 - behavioral_score
        
        # Medical and fraud scores are already risk scores (higher = more risk)
        medical_risk = medical_score
        fraud_risk = fraud_score
        history_risk = history_score
        
        # Calculate weighted risk
        weighted_risk = (
            identity_risk * self.SCORE_WEIGHTS['identity'] +
            document_risk * self.SCORE_WEIGHTS['document'] +
            medical_risk * self.SCORE_WEIGHTS['medical'] +
            behavioral_risk * self.SCORE_WEIGHTS['behavioral'] +
            fraud_risk * self.SCORE_WEIGHTS['fraud'] +
            history_risk * self.SCORE_WEIGHTS['history']
        )
        
        # Age adjustment
        if age is not None:
            if age < 25:
                age_factor = 0.15
                risk_factors.append(RiskFactor(
                    id=f"RF-{uuid.uuid4().hex[:8]}",
                    report_id="",
                    factor_category="age",
                    factor_name="Young Age",
                    factor_value=age,
                    impact_score=0.15,
                    impact_direction="positive",
                    explanation=f"Age {age} is below 25, adding moderate risk factor"
                ))
            elif age > 65:
                age_factor = 0.20
                risk_factors.append(RiskFactor(
                    id=f"RF-{uuid.uuid4().hex[:8]}",
                    report_id="",
                    factor_category="age",
                    factor_name="Senior Age",
                    factor_value=age,
                    impact_score=0.20,
                    impact_direction="positive",
                    explanation=f"Age {age} is above 65, adding elevated risk factor"
                ))
            else:
                age_factor = 0.0
            
            weighted_risk += age_factor * 0.1
        
        # Occupation adjustment
        if occupation_risk > 0:
            weighted_risk += occupation_risk * 0.1
            risk_factors.append(RiskFactor(
                id=f"RF-{uuid.uuid4().hex[:8]}",
                report_id="",
                factor_category="occupation",
                factor_name="Occupation Risk",
                factor_value=occupation_risk,
                impact_score=occupation_risk,
                impact_direction="positive" if occupation_risk > 0.3 else "neutral",
                explanation=f"Occupation risk factor: {occupation_risk:.2f}"
            ))
        
        # Add component risk factors
        if identity_risk > 0.3:
            risk_factors.append(RiskFactor(
                id=f"RF-{uuid.uuid4().hex[:8]}",
                report_id="",
                factor_category="identity",
                factor_name="Identity Verification Concern",
                factor_value=identity_score,
                impact_score=identity_risk,
                impact_direction="positive",
                explanation=f"Identity verification score {identity_score:.2f} below threshold"
            ))
        
        if medical_risk > 0.5:
            risk_factors.append(RiskFactor(
                id=f"RF-{uuid.uuid4().hex[:8]}",
                report_id="",
                factor_category="health",
                factor_name="Medical Risk Elevated",
                factor_value=medical_risk,
                impact_score=medical_risk,
                impact_direction="positive",
                explanation=f"Medical risk score {medical_risk:.2f} indicates health concerns"
            ))
        
        if fraud_risk > 0.3:
            risk_factors.append(RiskFactor(
                id=f"RF-{uuid.uuid4().hex[:8]}",
                report_id="",
                factor_category="fraud",
                factor_name="Fraud Risk Indicator",
                factor_value=fraud_risk,
                impact_score=fraud_risk,
                impact_direction="positive",
                explanation=f"Fraud detection score {fraud_risk:.2f} requires attention"
            ))
        
        if history_risk > 0.4:
            risk_factors.append(RiskFactor(
                id=f"RF-{uuid.uuid4().hex[:8]}",
                report_id="",
                factor_category="history",
                factor_name="Claims History Concern",
                factor_value=history_risk,
                impact_score=history_risk,
                impact_direction="positive",
                explanation=f"Claims history indicates elevated risk"
            ))
        
        # Normalize final score to 0-1
        final_risk = min(max(weighted_risk, 0.0), 1.0)
        
        return final_risk, risk_factors
    
    def determine_risk_level(self, risk_score: float) -> RiskLevel:
        """Determine risk level from score"""
        for level, (min_score, max_score) in self.RISK_THRESHOLDS.items():
            if min_score <= risk_score < max_score:
                return level
        return RiskLevel.VERY_HIGH
    
    def make_recommendation(self,
                           risk_score: float,
                           identity_verified: bool,
                           identity_score: float,
                           fraud_score: float,
                           document_score: float,
                           medical_flags: List[str] = None) -> Tuple[DecisionRecommendation, float, str]:
        """
        Make underwriting recommendation based on assessment.
        
        Returns:
            Tuple of (recommendation, confidence, explanation)
        """
        medical_flags = medical_flags or []
        explanation_parts = []
        confidence = 0.9  # Base confidence
        
        # Check hard failures first
        if not identity_verified or identity_score < self.DECISION_RULES['min_identity_score']:
            return (
                DecisionRecommendation.REFER_MANUAL,
                0.95,
                f"Identity verification failed or below threshold (score: {identity_score:.2f}). Manual review required."
            )
        
        if fraud_score > self.DECISION_RULES['max_fraud_score']:
            return (
                DecisionRecommendation.REFER_MANUAL,
                0.90,
                f"Fraud score ({fraud_score:.2f}) exceeds threshold. Manual review required for fraud assessment."
            )
        
        if document_score < self.DECISION_RULES['min_document_score']:
            return (
                DecisionRecommendation.PENDING_INFO,
                0.85,
                f"Document quality score ({document_score:.2f}) below minimum. Additional documentation required."
            )
        
        # Check for critical medical flags
        if 'CRITICAL_CONDITION_PRESENT' in medical_flags:
            return (
                DecisionRecommendation.REFER_MANUAL,
                0.92,
                "Critical medical condition detected. Requires manual medical underwriting review."
            )
        
        # Risk-based decision
        if risk_score <= self.DECISION_RULES['auto_approve_max_risk']:
            explanation_parts.append(f"Risk score ({risk_score:.2%}) within auto-approval threshold")
            explanation_parts.append("All verification checks passed")
            return (
                DecisionRecommendation.APPROVE,
                min(confidence, 0.95),
                ". ".join(explanation_parts) + "."
            )
        
        elif risk_score <= self.DECISION_RULES['conditional_approve_max_risk']:
            explanation_parts.append(f"Risk score ({risk_score:.2%}) within conditional approval range")
            if 'HIGH_MEDICAL_RISK' in medical_flags:
                explanation_parts.append("Medical conditions require exclusions or premium adjustment")
            return (
                DecisionRecommendation.APPROVE_CONDITIONAL,
                min(confidence, 0.88),
                ". ".join(explanation_parts) + "."
            )
        
        elif risk_score <= self.DECISION_RULES['refer_max_risk']:
            explanation_parts.append(f"Risk score ({risk_score:.2%}) requires manual underwriter review")
            return (
                DecisionRecommendation.REFER_MANUAL,
                min(confidence, 0.85),
                ". ".join(explanation_parts) + "."
            )
        
        else:
            explanation_parts.append(f"Risk score ({risk_score:.2%}) exceeds acceptable threshold")
            explanation_parts.append("Recommendation to decline based on risk assessment")
            return (
                DecisionRecommendation.DECLINE,
                min(confidence, 0.82),
                ". ".join(explanation_parts) + "."
            )
    
    def generate_full_explanation(self,
                                  report: RiskAssessmentReport,
                                  customer_name: str = "Applicant") -> str:
        """Generate a comprehensive human-readable explanation"""
        lines = []
        
        lines.append(f"=== RISK ASSESSMENT REPORT FOR {customer_name.upper()} ===")
        lines.append("")
        lines.append(f"Overall Risk Score: {report.overall_risk_score:.2%}")
        lines.append(f"Risk Level: {report.risk_level.value.replace('_', ' ').title()}")
        lines.append(f"Recommendation: {report.recommendation.value.replace('_', ' ').title()}")
        lines.append(f"Confidence: {report.confidence_level:.2%}")
        lines.append("")
        
        lines.append("--- Component Scores ---")
        lines.append(f"• Identity Verification: {'VERIFIED' if report.identity_verified else 'NOT VERIFIED'} (Score: {report.identity_score:.2%})")
        lines.append(f"• Document Quality: {report.document_score:.2%}")
        lines.append(f"• Medical Risk: {report.medical_score:.2%}")
        lines.append(f"• Behavioral Assessment: {report.behavioral_score:.2%}")
        lines.append(f"• Fraud Detection: {report.fraud_score:.2%}")
        lines.append("")
        
        if report.risk_factors:
            lines.append("--- Risk Factors Identified ---")
            for i, factor in enumerate(report.risk_factors, 1):
                direction = "↑" if factor.impact_direction == "positive" else "↓" if factor.impact_direction == "negative" else "→"
                lines.append(f"{i}. [{factor.factor_category.upper()}] {factor.factor_name} {direction}")
                lines.append(f"   Impact: {factor.impact_score:.2%} | {factor.explanation}")
            lines.append("")
        
        lines.append("--- Decision Explanation ---")
        lines.append(report.explanation)
        
        if report.human_override:
            lines.append("")
            lines.append("--- Human Override ---")
            lines.append(f"Decision overridden to: {report.human_decision}")
            lines.append(f"Notes: {report.human_notes}")
        
        return "\n".join(lines)


# ============================================================================
# MAIN UNDERWRITING BOT SERVICE
# ============================================================================

class UnderwritingBotService:
    """
    Main Underwriting Bot Service.
    
    Orchestrates the entire underwriting assessment process:
    1. Receives metadata (photos, documents, medical reports, audio, video)
    2. Processes and validates all metadata
    3. Extracts features from each metadata type
    4. Calculates risk scores using AI engine
    5. Generates comprehensive risk assessment reports
    6. Makes or recommends underwriting decisions
    
    IMPORTANT: This service NEVER modifies existing customer data.
    All customer data (details, transactions, investments, claims) is READ-ONLY.
    """
    
    def __init__(self,
                 customers: Dict = None,
                 policies: Dict = None,
                 underwriting_apps: Dict = None,
                 claims: Dict = None,
                 audit_service = None,
                 pipeline_service = None):
        """
        Initialize the Underwriting Bot Service.
        
        Args:
            customers: CUSTOMERS data store (READ-ONLY access)
            policies: POLICIES data store (READ-ONLY for existing, write for new UW status)
            underwriting_apps: UNDERWRITING_APPLICATIONS data store
            claims: CLAIMS data store (READ-ONLY for history)
            audit_service: Audit service for logging
            pipeline_service: Pipeline service for workflow integration
        """
        self.bot_id = f"UW-BOT-{uuid.uuid4().hex[:8]}"
        self.version = "1.0.0"
        
        # Data stores (preserving references, never resetting)
        self._customers = customers or {}
        self._policies = policies or {}
        self._underwriting = underwriting_apps or {}
        self._claims = claims or {}
        self._audit = audit_service
        self._pipeline = pipeline_service
        
        # Bot-specific data stores (new data only)
        self.assessments: Dict[str, BotAssessment] = {}
        self.metadata_store: Dict[str, UnderwritingMetadata] = {}
        self.reports: Dict[str, RiskAssessmentReport] = {}
        
        # Initialize analyzers
        self.photo_analyzer = PhotoAnalyzer()
        self.medical_analyzer = MedicalReportAnalyzer()
        self.document_analyzer = OfficialDocumentAnalyzer()
        self.audio_analyzer = AudioAnalyzer()
        self.video_analyzer = VideoAnalyzer()
        
        # Initialize risk engine
        self.risk_engine = RiskAssessmentEngine()
        
        self._log_event('system', 'bot_initialized', 'underwriting_bot', self.bot_id, {
            'version': self.version
        })
    
    def _log_event(self, actor: str, action: str, entity: str, entity_id: str, details: Dict = None):
        """Log event to audit service"""
        if self._audit:
            try:
                self._audit.log(actor, action, entity, entity_id, details or {})
            except:
                pass
        print(f"[UW-BOT] {action}: {entity}:{entity_id}")
    
    def _generate_id(self, prefix: str) -> str:
        """Generate unique ID"""
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        unique = uuid.uuid4().hex[:6].upper()
        return f"{prefix}-{timestamp}-{unique}"
    
    # =========================================================================
    # Assessment Lifecycle
    # =========================================================================
    
    def start_assessment(self, 
                        underwriting_id: str,
                        customer_id: str,
                        policy_id: str) -> BotAssessment:
        """
        Start a new bot assessment session.
        
        This creates a new assessment without modifying any existing customer data.
        Customer data is read-only and snapshotted for reference.
        """
        assessment_id = self._generate_id('BOT-ASS')
        
        # Read-only snapshot of customer data (NEVER MODIFIED)
        customer = self._customers.get(customer_id, {})
        customer_snapshot = {
            'name': customer.get('name', ''),
            'email': customer.get('email', ''),
            'age': customer.get('age', 0),
            'occupation': customer.get('occupation', ''),
            'snapshot_date': datetime.now().isoformat()
        }
        
        # Count existing policies and claims (READ-ONLY)
        existing_policies = sum(1 for p in self._policies.values() 
                               if p.get('customer_id') == customer_id)
        existing_claims = sum(1 for c in self._claims.values() 
                            if c.get('customer_id') == customer_id)
        
        assessment = BotAssessment(
            id=assessment_id,
            underwriting_id=underwriting_id,
            customer_id=customer_id,
            policy_id=policy_id,
            status=AssessmentStatus.INITIATED,
            customer_snapshot=customer_snapshot,
            existing_policies_count=existing_policies,
            existing_claims_count=existing_claims
        )
        
        self.assessments[assessment_id] = assessment
        
        self._log_event('bot', 'assessment_started', 'assessment', assessment_id, {
            'underwriting_id': underwriting_id,
            'customer_id': customer_id,
            'existing_policies': existing_policies,
            'existing_claims': existing_claims
        })
        
        return assessment
    
    def add_metadata(self,
                    assessment_id: str,
                    metadata_type: MetadataType,
                    file_name: str,
                    file_path: str,
                    file_content: bytes = None,
                    mime_type: str = "",
                    expiry_date: date = None) -> UnderwritingMetadata:
        """
        Add metadata item to assessment.
        
        This creates a new metadata record - never modifies customer data.
        """
        assessment = self.assessments.get(assessment_id)
        if not assessment:
            raise ValueError(f"Assessment {assessment_id} not found")
        
        # Update assessment status
        if assessment.status == AssessmentStatus.INITIATED:
            assessment.status = AssessmentStatus.COLLECTING_METADATA
        
        # Calculate file hash for integrity
        file_hash = hashlib.sha256(file_content or b'').hexdigest() if file_content else ""
        file_size = len(file_content) if file_content else 0
        
        metadata_id = self._generate_id('META')
        metadata = UnderwritingMetadata(
            id=metadata_id,
            underwriting_id=assessment.underwriting_id,
            customer_id=assessment.customer_id,
            metadata_type=metadata_type,
            file_name=file_name,
            file_path=file_path,
            file_hash=file_hash,
            file_size_bytes=file_size,
            mime_type=mime_type,
            upload_date=datetime.now()
        )
        
        assessment.metadata_items.append(metadata)
        self.metadata_store[metadata_id] = metadata
        
        self._log_event('bot', 'metadata_added', 'metadata', metadata_id, {
            'assessment_id': assessment_id,
            'type': metadata_type.value,
            'file_name': file_name
        })
        
        return metadata
    
    def process_metadata(self, metadata_id: str, file_content: bytes = None) -> Dict[str, Any]:
        """
        Process a single metadata item through appropriate analyzer.
        """
        metadata = self.metadata_store.get(metadata_id)
        if not metadata:
            return {'success': False, 'error': 'Metadata not found'}
        
        metadata.processing_status = ProcessingStatus.PROCESSING
        metadata.updated_date = datetime.now()
        
        try:
            # Route to appropriate analyzer
            if metadata.metadata_type == MetadataType.PHOTO:
                result = self.photo_analyzer.analyze(metadata, file_content)
            elif metadata.metadata_type == MetadataType.MEDICAL_REPORT:
                result = self.medical_analyzer.analyze(metadata, file_content)
            elif metadata.metadata_type in [MetadataType.PASSPORT, MetadataType.DRIVING_LICENCE,
                                            MetadataType.NATIONAL_INSURANCE, MetadataType.DISABILITY_CERTIFICATE]:
                result = self.document_analyzer.analyze(metadata, file_content, 
                                                        metadata.metadata_type.value)
            elif metadata.metadata_type == MetadataType.AUDIO:
                result = self.audio_analyzer.analyze(metadata, file_content)
            elif metadata.metadata_type == MetadataType.VIDEO:
                result = self.video_analyzer.analyze(metadata, file_content)
            else:
                result = {'processing_success': False, 'error': 'Unsupported metadata type'}
            
            # Update metadata with results
            if result.get('processing_success'):
                metadata.processing_status = ProcessingStatus.COMPLETED
                metadata.processing_result = result
                metadata.extracted_data = result.get('extracted_fields', result.get('features', {}))
                metadata.confidence_score = result.get('scores', {}).get('authenticity_score', 0.8)
                
                # Set validation status
                if result.get('flags'):
                    if 'DOCUMENT_EXPIRED' in result['flags'] or 'LIVENESS_FAILED' in result['flags']:
                        metadata.validation_status = ValidationStatus.INVALID
                    elif any('SUSPICIOUS' in f or 'FRAUD' in f for f in result['flags']):
                        metadata.validation_status = ValidationStatus.SUSPICIOUS
                    else:
                        metadata.validation_status = ValidationStatus.VALID
                else:
                    metadata.validation_status = ValidationStatus.VALID
            else:
                metadata.processing_status = ProcessingStatus.FAILED
                metadata.validation_status = ValidationStatus.INVALID
                metadata.validation_notes = result.get('error', 'Processing failed')
            
            metadata.updated_date = datetime.now()
            return {'success': True, 'result': result}
            
        except Exception as e:
            metadata.processing_status = ProcessingStatus.FAILED
            metadata.validation_notes = str(e)
            metadata.updated_date = datetime.now()
            return {'success': False, 'error': str(e)}
    
    def process_all_metadata(self, assessment_id: str) -> Dict[str, Any]:
        """
        Process all metadata items in an assessment.
        """
        assessment = self.assessments.get(assessment_id)
        if not assessment:
            return {'success': False, 'error': 'Assessment not found'}
        
        assessment.status = AssessmentStatus.VALIDATING_METADATA
        
        results = []
        all_passed = True
        
        for metadata in assessment.metadata_items:
            result = self.process_metadata(metadata.id)
            results.append({
                'metadata_id': metadata.id,
                'type': metadata.metadata_type.value,
                'success': result.get('success', False)
            })
            if not result.get('success'):
                all_passed = False
        
        if not all_passed:
            assessment.status = AssessmentStatus.VALIDATION_FAILED
        else:
            assessment.status = AssessmentStatus.PROCESSING
        
        return {
            'success': all_passed,
            'results': results,
            'total_processed': len(results),
            'status': assessment.status.value
        }
    
    # =========================================================================
    # Risk Assessment
    # =========================================================================
    
    def run_risk_assessment(self, assessment_id: str) -> RiskAssessmentReport:
        """
        Run full risk assessment for an assessment.
        
        This aggregates all processed metadata and generates a comprehensive
        risk assessment report. Customer data is READ-ONLY.
        """
        start_time = datetime.now()
        
        assessment = self.assessments.get(assessment_id)
        if not assessment:
            raise ValueError(f"Assessment {assessment_id} not found")
        
        assessment.status = AssessmentStatus.RISK_ASSESSING
        
        # Aggregate scores from processed metadata
        identity_scores = []
        document_scores = []
        medical_scores = []
        behavioral_scores = []
        fraud_indicators = []
        all_flags = []
        
        for metadata in assessment.metadata_items:
            if metadata.processing_status != ProcessingStatus.COMPLETED:
                continue
            
            result = metadata.processing_result
            scores = result.get('scores', {})
            flags = result.get('flags', [])
            all_flags.extend(flags)
            
            if metadata.metadata_type == MetadataType.PHOTO:
                identity_scores.append(scores.get('identity_confidence', 0.5))
            elif metadata.metadata_type == MetadataType.VIDEO:
                identity_scores.append(scores.get('identity_confidence', 0.5))
                behavioral_scores.append(scores.get('behavioral_score', 0.5))
                if not result.get('liveness', {}).get('is_live', True):
                    fraud_indicators.append(0.9)
            elif metadata.metadata_type == MetadataType.MEDICAL_REPORT:
                medical_scores.append(scores.get('medical_risk_score', 0.3))
            elif metadata.metadata_type in [MetadataType.PASSPORT, MetadataType.DRIVING_LICENCE,
                                            MetadataType.NATIONAL_INSURANCE, MetadataType.DISABILITY_CERTIFICATE]:
                document_scores.append(scores.get('authenticity_score', 0.5))
                if 'DOCUMENT_EXPIRED' in flags:
                    document_scores.append(0.0)
            elif metadata.metadata_type == MetadataType.AUDIO:
                behavioral_scores.append(1.0 - scores.get('stress_score', 0.2))
        
        # Calculate average scores
        identity_score = sum(identity_scores) / len(identity_scores) if identity_scores else 0.5
        document_score = sum(document_scores) / len(document_scores) if document_scores else 0.5
        medical_score = sum(medical_scores) / len(medical_scores) if medical_scores else 0.3
        behavioral_score = sum(behavioral_scores) / len(behavioral_scores) if behavioral_scores else 0.7
        fraud_score = sum(fraud_indicators) / len(fraud_indicators) if fraud_indicators else 0.1
        
        # Get claims history risk (READ-ONLY from existing data)
        claims_count = assessment.existing_claims_count
        history_score = min(claims_count * 0.15, 0.6)  # More claims = higher risk
        
        # Get customer age from snapshot
        age = assessment.customer_snapshot.get('age', 0)
        
        # Calculate overall risk
        overall_risk, risk_factors = self.risk_engine.calculate_risk_score(
            identity_score=identity_score,
            document_score=document_score,
            medical_score=medical_score,
            behavioral_score=behavioral_score,
            fraud_score=fraud_score,
            history_score=history_score,
            age=age if age > 0 else None
        )
        
        # Determine risk level
        risk_level = self.risk_engine.determine_risk_level(overall_risk)
        
        # Identity verified check
        identity_verified = identity_score >= 0.7 and not any('IDENTITY' in f or 'FACE' in f for f in all_flags if 'FAILED' in f or 'LOW' in f)
        
        # Make recommendation
        recommendation, confidence, explanation = self.risk_engine.make_recommendation(
            risk_score=overall_risk,
            identity_verified=identity_verified,
            identity_score=identity_score,
            fraud_score=fraud_score,
            document_score=document_score,
            medical_flags=all_flags
        )
        
        # Create report
        report_id = self._generate_id('REPORT')
        report = RiskAssessmentReport(
            id=report_id,
            underwriting_id=assessment.underwriting_id,
            customer_id=assessment.customer_id,
            assessment_date=datetime.now(),
            overall_risk_score=overall_risk,
            risk_level=risk_level,
            identity_verified=identity_verified,
            identity_score=identity_score,
            document_score=document_score,
            medical_score=medical_score,
            behavioral_score=behavioral_score,
            fraud_score=fraud_score,
            recommendation=recommendation,
            confidence_level=confidence,
            risk_factors=risk_factors,
            explanation=explanation,
            metadata_processed=[m.id for m in assessment.metadata_items],
            processing_time_seconds=(datetime.now() - start_time).total_seconds()
        )
        
        # Update risk factor report IDs
        for factor in report.risk_factors:
            factor.report_id = report_id
        
        # Store report
        self.reports[report_id] = report
        assessment.risk_report = report
        assessment.status = AssessmentStatus.DECISION_READY
        
        self._log_event('bot', 'risk_assessment_complete', 'report', report_id, {
            'assessment_id': assessment_id,
            'risk_score': overall_risk,
            'risk_level': risk_level.value,
            'recommendation': recommendation.value
        })
        
        return report
    
    def get_assessment_summary(self, assessment_id: str) -> Dict[str, Any]:
        """Get summary of an assessment"""
        assessment = self.assessments.get(assessment_id)
        if not assessment:
            return {'error': 'Assessment not found'}
        
        summary = assessment.to_dict()
        
        if assessment.risk_report:
            summary['risk_summary'] = assessment.risk_report.get_summary()
            summary['full_explanation'] = self.risk_engine.generate_full_explanation(
                assessment.risk_report,
                assessment.customer_snapshot.get('name', 'Applicant')
            )
        
        return summary
    
    # =========================================================================
    # Decision and Pipeline Integration
    # =========================================================================
    
    def apply_decision(self, 
                      assessment_id: str,
                      decision: str,
                      decided_by: str = "bot",
                      notes: str = "",
                      override_recommendation: bool = False) -> Dict[str, Any]:
        """
        Apply underwriting decision based on assessment.
        
        This updates the underwriting application status and policy status,
        but NEVER modifies customer data, transactions, or history.
        """
        assessment = self.assessments.get(assessment_id)
        if not assessment:
            return {'success': False, 'error': 'Assessment not found'}
        
        if not assessment.risk_report:
            return {'success': False, 'error': 'Risk assessment not completed'}
        
        # Map decision to status
        decision_map = {
            'approve': AssessmentStatus.APPROVED,
            'approved': AssessmentStatus.APPROVED,
            'reject': AssessmentStatus.REJECTED,
            'rejected': AssessmentStatus.REJECTED,
            'decline': AssessmentStatus.REJECTED,
            'refer': AssessmentStatus.REFERRED,
            'referred': AssessmentStatus.REFERRED,
            'conditional': AssessmentStatus.CONDITIONAL_APPROVAL,
            'conditional_approval': AssessmentStatus.CONDITIONAL_APPROVAL
        }
        
        new_status = decision_map.get(decision.lower())
        if not new_status:
            return {'success': False, 'error': f'Invalid decision: {decision}'}
        
        # Check if overriding bot recommendation
        if override_recommendation:
            assessment.risk_report.human_override = True
            assessment.risk_report.human_decision = decision
            assessment.risk_report.human_notes = notes
            assessment.risk_report.updated_date = datetime.now()
        
        # Update assessment status
        assessment.status = new_status
        assessment.completed_at = datetime.now()
        
        # Update underwriting application (additive only, never resets data)
        uw_app = self._underwriting.get(assessment.underwriting_id)
        if uw_app:
            uw_app['status'] = 'approved' if new_status == AssessmentStatus.APPROVED else (
                'rejected' if new_status == AssessmentStatus.REJECTED else (
                    'referred' if new_status == AssessmentStatus.REFERRED else 'conditional'
                )
            )
            uw_app['decision_date'] = datetime.now().isoformat()
            uw_app['decided_by'] = decided_by
            uw_app['bot_assessment_id'] = assessment_id
            uw_app['bot_report_id'] = assessment.risk_report.id
            uw_app['notes'] = notes
            uw_app['updated_date'] = datetime.now().isoformat()
        
        # Integrate with pipeline if available
        if self._pipeline and new_status == AssessmentStatus.APPROVED:
            # Call pipeline approval (which will also update policy status)
            try:
                self._pipeline.approve_underwriting(
                    uw_id=assessment.underwriting_id,
                    approved_by=decided_by,
                    premium_adjustment_pct=0.0,  # Could be based on risk factors
                    notes=f"Bot Assessment: {assessment.risk_report.recommendation.value}. {notes}"
                )
            except:
                pass  # Pipeline integration is optional
        
        self._log_event(decided_by, 'decision_applied', 'assessment', assessment_id, {
            'decision': decision,
            'status': new_status.value,
            'override': override_recommendation
        })
        
        return {
            'success': True,
            'assessment_id': assessment_id,
            'decision': decision,
            'status': new_status.value,
            'report_id': assessment.risk_report.id
        }
    
    def get_pending_assessments(self) -> List[Dict[str, Any]]:
        """Get all assessments pending decision"""
        pending = []
        for assessment in self.assessments.values():
            if assessment.status == AssessmentStatus.DECISION_READY:
                summary = assessment.to_dict()
                if assessment.risk_report:
                    summary['risk_summary'] = assessment.risk_report.get_summary()
                pending.append(summary)
        return pending
    
    def get_report(self, report_id: str) -> Optional[RiskAssessmentReport]:
        """Get a specific report"""
        return self.reports.get(report_id)
    
    def get_report_as_dict(self, report_id: str) -> Dict[str, Any]:
        """Get report as dictionary"""
        report = self.reports.get(report_id)
        if report:
            return report.to_dict()
        return {}


# ============================================================================
# Factory and Singleton
# ============================================================================

_bot_instance: Optional[UnderwritingBotService] = None


def get_underwriting_bot_service(customers: Dict = None,
                                  policies: Dict = None,
                                  underwriting_apps: Dict = None,
                                  claims: Dict = None,
                                  audit_service = None,
                                  pipeline_service = None) -> UnderwritingBotService:
    """Get or create underwriting bot service instance"""
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = UnderwritingBotService(
            customers=customers,
            policies=policies,
            underwriting_apps=underwriting_apps,
            claims=claims,
            audit_service=audit_service,
            pipeline_service=pipeline_service
        )
    return _bot_instance


def init_underwriting_bot_service(customers: Dict,
                                   policies: Dict,
                                   underwriting_apps: Dict,
                                   claims: Dict,
                                   audit_service = None,
                                   pipeline_service = None) -> UnderwritingBotService:
    """Initialize underwriting bot service with dependencies"""
    global _bot_instance
    _bot_instance = UnderwritingBotService(
        customers=customers,
        policies=policies,
        underwriting_apps=underwriting_apps,
        claims=claims,
        audit_service=audit_service,
        pipeline_service=pipeline_service
    )
    return _bot_instance


__all__ = [
    'UnderwritingBotService',
    'get_underwriting_bot_service',
    'init_underwriting_bot_service',
    'MetadataType',
    'ProcessingStatus',
    'ValidationStatus',
    'RiskLevel',
    'DecisionRecommendation',
    'AssessmentStatus',
    'UnderwritingMetadata',
    'ExtractedFeature',
    'RiskFactor',
    'RiskAssessmentReport',
    'BotAssessment',
    'PhotoAnalyzer',
    'MedicalReportAnalyzer',
    'OfficialDocumentAnalyzer',
    'AudioAnalyzer',
    'VideoAnalyzer',
    'RiskAssessmentEngine'
]
