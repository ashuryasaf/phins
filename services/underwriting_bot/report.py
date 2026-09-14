"""
Underwriting Bot — report model and risk engine (B1 split).

Enums and dataclasses that make up an assessment (metadata items, extracted
features, risk factors, the risk report, the assessment envelope) and the
deterministic :class:`RiskAssessmentEngine` that turns analyzer scores into a
risk score, level, recommendation and explanation. Pure data + rules: no
stores, no audit, no I/O.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional, Tuple

import uuid
import logging

_logger = logging.getLogger('phins.underwriting_bot')


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
    # Document Intelligence linkage (B1): when the evidence was ingested via
    # the document service, its facts (with provenance) are consumed instead
    # of re-parsing the bytes here.
    document_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            'id': self.id,
            'document_id': self.document_id,
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
    # Calibration loop (B1/A6): the AI decision-log id of this recommendation
    # (human counter-decisions are recorded against it) and the shadow model
    # comparison. ``rule_score`` is the authoritative ``overall_risk_score``.
    decision_id: str = ""
    model_shadow: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'underwriting_id': self.underwriting_id,
            'customer_id': self.customer_id,
            'assessment_date': self.assessment_date.isoformat() if self.assessment_date else None,
            'decision_id': self.decision_id,
            'model_shadow': dict(self.model_shadow),
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
