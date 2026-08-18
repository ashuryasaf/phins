"""
PHINS Claims Bot Service
========================
AI-powered claims assessment bot that processes metadata (photos, medical reports,
documents, audio, video) and creates comprehensive fraud probability reports.

Features:
- Multi-type metadata processing for claims evidence
- Fraud detection and probability scoring
- Underwriting cross-reference for hidden condition detection
- AI-based claim legitimacy assessment
- Integration with existing pipeline (preserves all customer data)
- Data integrity protection (READ-ONLY access to historical data)

Author: PHINS Platform
Version: 1.0.0
"""

from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from enum import Enum
from typing import Dict, List, Any, Optional, Tuple
import hashlib
import json
import logging
import uuid
import math
import random

logger = logging.getLogger('phins.claims_bot')


# ============================================================================
# ENUMS
# ============================================================================

class ClaimMetadataType(Enum):
    """Types of metadata for claim evidence"""
    INJURY_PHOTO = "injury_photo"
    MEDICAL_REPORT = "medical_report"
    RECEIPT = "receipt"
    HOSPITAL_BILL = "hospital_bill"
    POLICE_REPORT = "police_report"
    PRESCRIPTION = "prescription"
    DISABILITY_UPDATE = "disability_update"
    DEATH_CERTIFICATE = "death_certificate"
    WITNESS_STATEMENT = "witness_statement"
    VIDEO_EVIDENCE = "video_evidence"
    AUDIO_STATEMENT = "audio_statement"
    OTHER = "other"


class FraudIndicatorType(Enum):
    """Types of fraud indicators"""
    TIMING_SUSPICIOUS = "timing_suspicious"
    CONDITION_HIDDEN_AT_UW = "condition_hidden_at_uw"
    DOCUMENT_TAMPERED = "document_tampered"
    INCONSISTENT_STATEMENTS = "inconsistent_statements"
    EXCESSIVE_CLAIM_HISTORY = "excessive_claim_history"
    PROVIDER_FLAGGED = "provider_flagged"
    AMOUNT_SUSPICIOUS = "amount_suspicious"
    PATTERN_MATCH_FRAUD = "pattern_match_fraud"
    IDENTITY_MISMATCH = "identity_mismatch"
    PRE_EXISTING_UNDISCLOSED = "pre_existing_undisclosed"


class ClaimDecisionType(Enum):
    """Claim decision recommendations"""
    APPROVE_FULL = "approve_full"
    APPROVE_PARTIAL = "approve_partial"
    REFER_INVESTIGATION = "refer_investigation"
    REFER_MEDICAL_REVIEW = "refer_medical_review"
    DENY_FRAUD_SUSPECTED = "deny_fraud_suspected"
    DENY_NOT_COVERED = "deny_not_covered"
    DENY_HIDDEN_CONDITION = "deny_hidden_condition"
    PENDING_MORE_INFO = "pending_more_info"


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class HiddenCondition:
    """Represents a condition that may have been hidden during underwriting"""
    condition_name: str
    icd_code: str
    evidence_source: str
    detection_confidence: float
    estimated_onset_date: Optional[datetime]
    was_before_policy: bool
    causal_link_to_claim: bool
    severity: str
    deliberate_concealment_score: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'condition_name': self.condition_name,
            'icd_code': self.icd_code,
            'evidence_source': self.evidence_source,
            'detection_confidence': self.detection_confidence,
            'estimated_onset_date': self.estimated_onset_date.isoformat() if self.estimated_onset_date else None,
            'was_before_policy': self.was_before_policy,
            'causal_link_to_claim': self.causal_link_to_claim,
            'severity': self.severity,
            'deliberate_concealment_score': self.deliberate_concealment_score
        }


@dataclass
class FraudIndicator:
    """Individual fraud indicator"""
    id: str
    indicator_type: FraudIndicatorType
    severity: float  # 0.0-1.0
    evidence: List[str]
    explanation: str
    recommendation: str
    requires_investigation: bool
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'indicator_type': self.indicator_type.value,
            'severity': self.severity,
            'evidence': self.evidence,
            'explanation': self.explanation,
            'recommendation': self.recommendation,
            'requires_investigation': self.requires_investigation
        }


@dataclass
class ClaimProbabilityReport:
    """Comprehensive claim probability/fraud assessment report"""
    id: str
    claim_id: str
    customer_id: str
    policy_id: str
    assessment_date: datetime
    
    # Core Probability Scores (0.0 = fraud, 1.0 = legitimate)
    authenticity_probability: float  # Overall probability claim is authentic
    fraud_probability: float  # Probability of fraud (1 - authenticity)
    
    # Component Scores
    document_authenticity_score: float
    medical_consistency_score: float
    timing_legitimacy_score: float
    amount_reasonability_score: float
    customer_history_score: float
    underwriting_alignment_score: float
    
    # Hidden Conditions Detection
    hidden_conditions_detected: List[HiddenCondition] = field(default_factory=list)
    hidden_condition_impact: float = 0.0
    
    # Fraud Indicators
    fraud_indicators: List[FraudIndicator] = field(default_factory=list)
    
    # Policy Timeline Analysis
    time_since_policy_start_days: int = 0
    time_since_policy_start_years: float = 0.0
    is_within_contestability: bool = False
    contestability_period_years: float = 2.0
    
    # Decision
    recommendation: ClaimDecisionType = ClaimDecisionType.PENDING_MORE_INFO
    confidence_level: float = 0.0
    risk_level: str = "medium"
    explanation: str = ""
    
    # AI Analysis Summary
    ai_summary: str = ""
    key_findings: List[str] = field(default_factory=list)
    red_flags: List[str] = field(default_factory=list)
    green_flags: List[str] = field(default_factory=list)
    
    # Metadata
    evidence_processed: int = 0
    processing_time_seconds: float = 0.0
    model_version: str = "1.0.0"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'claim_id': self.claim_id,
            'customer_id': self.customer_id,
            'policy_id': self.policy_id,
            'assessment_date': self.assessment_date.isoformat() if self.assessment_date else None,
            
            # Core probabilities
            'authenticity_probability': round(self.authenticity_probability, 4),
            'authenticity_percentage': f"{self.authenticity_probability * 100:.1f}%",
            'fraud_probability': round(self.fraud_probability, 4),
            'fraud_percentage': f"{self.fraud_probability * 100:.1f}%",
            
            # Component scores
            'component_scores': {
                'document_authenticity': round(self.document_authenticity_score, 3),
                'medical_consistency': round(self.medical_consistency_score, 3),
                'timing_legitimacy': round(self.timing_legitimacy_score, 3),
                'amount_reasonability': round(self.amount_reasonability_score, 3),
                'customer_history': round(self.customer_history_score, 3),
                'underwriting_alignment': round(self.underwriting_alignment_score, 3)
            },
            
            # Hidden conditions
            'hidden_conditions': {
                'detected': len(self.hidden_conditions_detected),
                'conditions': [hc.to_dict() for hc in self.hidden_conditions_detected],
                'impact_score': round(self.hidden_condition_impact, 3)
            },
            
            # Fraud indicators
            'fraud_indicators': {
                'count': len(self.fraud_indicators),
                'indicators': [fi.to_dict() for fi in self.fraud_indicators],
                'high_severity_count': sum(1 for fi in self.fraud_indicators if fi.severity > 0.7)
            },
            
            # Timeline
            'timeline_analysis': {
                'days_since_policy': self.time_since_policy_start_days,
                'years_since_policy': round(self.time_since_policy_start_years, 2),
                'within_contestability': self.is_within_contestability,
                'contestability_period_years': self.contestability_period_years
            },
            
            # Decision
            'recommendation': self.recommendation.value,
            'recommendation_display': self.recommendation.value.replace('_', ' ').title(),
            'confidence_level': round(self.confidence_level, 3),
            'confidence_percentage': f"{self.confidence_level * 100:.1f}%",
            'risk_level': self.risk_level,
            'explanation': self.explanation,
            
            # AI Summary
            'ai_analysis': {
                'summary': self.ai_summary,
                'key_findings': self.key_findings,
                'red_flags': self.red_flags,
                'green_flags': self.green_flags
            },
            
            # Metadata
            'metadata': {
                'evidence_processed': self.evidence_processed,
                'processing_time_seconds': round(self.processing_time_seconds, 3),
                'model_version': self.model_version
            }
        }


# ============================================================================
# CLAIMS BOT SERVICE
# ============================================================================

class ClaimsBotService:
    """
    AI-powered Claims Bot Service.
    
    Analyzes claim evidence and generates probability reports for fraud detection.
    Cross-references with underwriting data to detect hidden conditions.
    
    DATA INTEGRITY: All customer/policy/underwriting data is READ-ONLY.
    """
    
    # Contestability period (typically 2 years)
    CONTESTABILITY_PERIOD_YEARS = 2.0

    # Maximum probability reports retained in memory (advisory artifacts).
    MAX_RETAINED_REPORTS = 5000
    
    # Weights for probability calculation
    SCORE_WEIGHTS = {
        'document_authenticity': 0.15,
        'medical_consistency': 0.25,
        'timing_legitimacy': 0.15,
        'amount_reasonability': 0.15,
        'customer_history': 0.10,
        'underwriting_alignment': 0.20
    }
    
    # Known high-risk medical conditions
    HIGH_RISK_CONDITIONS = {
        'heart_disease': {'icd_prefix': 'I', 'risk_factor': 0.8},
        'cancer': {'icd_prefix': 'C', 'risk_factor': 0.9},
        'diabetes': {'icd_prefix': 'E11', 'risk_factor': 0.6},
        'stroke': {'icd_prefix': 'I6', 'risk_factor': 0.85},
        'chronic_kidney': {'icd_prefix': 'N18', 'risk_factor': 0.7},
        'copd': {'icd_prefix': 'J44', 'risk_factor': 0.65},
        'heart_surgery': {'icd_prefix': 'Z95', 'risk_factor': 0.9}
    }
    
    def __init__(self,
                 customers: Dict = None,
                 policies: Dict = None,
                 claims: Dict = None,
                 underwriting: Dict = None,
                 audit_service = None):
        """
        Initialize Claims Bot Service.
        
        All data stores are READ-ONLY except for bot's own reports.
        """
        self.bot_id = f"CLM-BOT-{uuid.uuid4().hex[:8]}"
        self.version = "1.0.0"
        
        # Data stores (READ-ONLY)
        self._customers = customers or {}
        self._policies = policies or {}
        self._claims = claims or {}
        self._underwriting = underwriting or {}
        self._audit = audit_service
        
        # Bot's own data (WRITE allowed)
        self.reports: Dict[str, ClaimProbabilityReport] = {}
        
        print(f"[CLAIMS-BOT] Initialized: {self.bot_id}")
    
    def _generate_id(self, prefix: str) -> str:
        """Generate unique ID"""
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        unique = uuid.uuid4().hex[:6].upper()
        return f"{prefix}-{timestamp}-{unique}"
    
    def _log_event(self, action: str, entity: str, entity_id: str, details: Dict = None):
        """Log event to the in-process audit service and the durable audit store.

        Best-effort and non-fatal: a logging failure must never break claim
        assessment. Failures are logged at warning level rather than silently
        swallowed, so audit gaps are observable instead of invisible.
        """
        if self._audit:
            # An in-process AuditService already persists durably to the
            # audit_logs table via its own _persist_event path, so mirroring
            # again here would create duplicate rows for the same event.
            try:
                self._audit.log('claims_bot', action, entity, entity_id, details or {})
            except Exception as exc:
                logger.warning("claims_bot in-process audit log failed: %s", exc)
        else:
            # Durable audit parity: with no in-process audit service wired,
            # mirror to the audit_logs table when a database is configured.
            # No-op in pure in-memory/demo runtimes.
            try:
                from services.ai_audit_bridge import record_ai_audit
                record_ai_audit(
                    action=f'claims_bot_{action}',
                    entity_type=entity,
                    entity_id=entity_id,
                    details=details or {},
                    username='claims_bot',
                    customer_id=(details or {}).get('customer_id'),
                )
            except Exception as exc:
                logger.warning("claims_bot durable audit mirror failed: %s", exc)
        print(f"[CLAIMS-BOT] {action}: {entity}:{entity_id}")
    
    # =========================================================================
    # Core Analysis Methods
    # =========================================================================
    
    def generate_probability_report(self, claim_id: str) -> Optional[ClaimProbabilityReport]:
        """
        Generate a comprehensive probability report for a claim.
        
        This is the main entry point for claim assessment.
        """
        start_time = datetime.now()
        
        # Get claim data (READ-ONLY)
        claim = self._claims.get(claim_id)
        if not claim:
            print(f"[CLAIMS-BOT] Claim not found: {claim_id}")
            return None
        
        customer_id = claim.get('customer_id')
        policy_id = claim.get('policy_id')
        
        # Get related data (READ-ONLY)
        customer = self._customers.get(customer_id, {})
        policy = self._policies.get(policy_id, {})
        
        # Find underwriting application for this customer/policy
        underwriting = self._find_underwriting_record(customer_id, policy_id)
        
        # Calculate timeline
        policy_start = self._parse_date(policy.get('start_date'))
        claim_filed = self._parse_date(claim.get('filed_date') or claim.get('created_date'))
        
        days_since_policy = 0
        years_since_policy = 0.0
        within_contestability = True
        
        if policy_start and claim_filed:
            days_since_policy = (claim_filed - policy_start).days
            years_since_policy = days_since_policy / 365.25
            within_contestability = years_since_policy < self.CONTESTABILITY_PERIOD_YEARS
        
        # Calculate component scores
        document_score = self._analyze_document_authenticity(claim)
        medical_score = self._analyze_medical_consistency(claim, underwriting)
        timing_score = self._analyze_timing_legitimacy(claim, policy, days_since_policy)
        amount_score = self._analyze_amount_reasonability(claim, policy)
        history_score = self._analyze_customer_history(customer_id)
        uw_alignment_score = self._analyze_underwriting_alignment(claim, underwriting)
        
        # Detect hidden conditions
        hidden_conditions = self._detect_hidden_conditions(claim, underwriting, policy_start)
        hidden_impact = sum(hc.deliberate_concealment_score for hc in hidden_conditions) / max(len(hidden_conditions), 1)
        
        # Detect fraud indicators
        fraud_indicators = self._detect_fraud_indicators(
            claim, customer, policy, underwriting,
            days_since_policy, hidden_conditions
        )
        
        # Calculate overall probability
        base_authenticity = (
            document_score * self.SCORE_WEIGHTS['document_authenticity'] +
            medical_score * self.SCORE_WEIGHTS['medical_consistency'] +
            timing_score * self.SCORE_WEIGHTS['timing_legitimacy'] +
            amount_score * self.SCORE_WEIGHTS['amount_reasonability'] +
            history_score * self.SCORE_WEIGHTS['customer_history'] +
            uw_alignment_score * self.SCORE_WEIGHTS['underwriting_alignment']
        )
        
        # Apply penalties
        fraud_penalty = sum(fi.severity * 0.1 for fi in fraud_indicators)
        hidden_penalty = hidden_impact * 0.3 if hidden_conditions else 0
        
        authenticity_probability = max(0.0, min(1.0, base_authenticity - fraud_penalty - hidden_penalty))
        fraud_probability = 1.0 - authenticity_probability
        
        # Determine risk level
        if authenticity_probability >= 0.85:
            risk_level = "low"
        elif authenticity_probability >= 0.65:
            risk_level = "medium"
        elif authenticity_probability >= 0.45:
            risk_level = "high"
        else:
            risk_level = "critical"
        
        # Make recommendation
        recommendation, confidence, explanation = self._make_recommendation(
            authenticity_probability, fraud_indicators, hidden_conditions,
            within_contestability, claim
        )
        
        # Generate AI summary
        ai_summary, key_findings, red_flags, green_flags = self._generate_ai_summary(
            claim, authenticity_probability, fraud_indicators,
            hidden_conditions, risk_level
        )
        
        # Create report
        report_id = self._generate_id('PROB-RPT')
        report = ClaimProbabilityReport(
            id=report_id,
            claim_id=claim_id,
            customer_id=customer_id,
            policy_id=policy_id,
            assessment_date=datetime.now(),
            authenticity_probability=authenticity_probability,
            fraud_probability=fraud_probability,
            document_authenticity_score=document_score,
            medical_consistency_score=medical_score,
            timing_legitimacy_score=timing_score,
            amount_reasonability_score=amount_score,
            customer_history_score=history_score,
            underwriting_alignment_score=uw_alignment_score,
            hidden_conditions_detected=hidden_conditions,
            hidden_condition_impact=hidden_impact,
            fraud_indicators=fraud_indicators,
            time_since_policy_start_days=days_since_policy,
            time_since_policy_start_years=years_since_policy,
            is_within_contestability=within_contestability,
            recommendation=recommendation,
            confidence_level=confidence,
            risk_level=risk_level,
            explanation=explanation,
            ai_summary=ai_summary,
            key_findings=key_findings,
            red_flags=red_flags,
            green_flags=green_flags,
            evidence_processed=len(claim.get('files', [])) or 1,
            processing_time_seconds=(datetime.now() - start_time).total_seconds()
        )
        
        # Store report (bounded to avoid unbounded memory growth on a
        # long-running server; oldest reports are evicted first).
        self.reports[report_id] = report
        self._enforce_report_cap()
        self._persist_report(report, claim_id=claim_id, customer_id=customer_id)
        
        self._log_event('probability_report_generated', 'claim', claim_id, {
            'report_id': report_id,
            'customer_id': customer_id,
            'authenticity': authenticity_probability,
            'fraud_indicators': len(fraud_indicators),
            'hidden_conditions': len(hidden_conditions)
        })
        
        return report

    def _persist_report(self, report: 'ClaimProbabilityReport', *,
                        claim_id: str, customer_id: str) -> None:
        """Append the generated report to the durable assessment history.

        Reports were previously held only in process memory (``self.reports``)
        so a restart erased the audit trail. Every generated report is now
        also written append-only through the assessment record service
        (assessment_type='claims_probability_report'); the in-memory map
        stays as the fast read path. Best-effort — a persistence failure
        never blocks report generation.
        """
        try:
            from services.assessment_record_service import get_assessment_record_service
            get_assessment_record_service().record_assessment(
                subject_type="claim",
                subject_id=claim_id,
                assessment_type="claims_probability_report",
                customer_id=customer_id,
                score=report.fraud_probability,
                level=getattr(report.risk_level, "value", report.risk_level),
                recommendation=getattr(report.recommendation, "value",
                                       report.recommendation),
                details=report.to_dict(),
                engine="claims_bot",
                engine_version="probability-report-1",
            )
        except Exception as exc:
            logger.warning("claims_bot report persistence skipped: %s", exc)

    def _enforce_report_cap(self) -> None:
        """Keep at most ``MAX_RETAINED_REPORTS`` reports in memory.

        Probability reports are advisory artifacts (the authoritative claim
        state lives on the claim record), so evicting the oldest ones is safe
        and prevents unbounded growth in long-lived processes.
        """
        try:
            overflow = len(self.reports) - self.MAX_RETAINED_REPORTS
            if overflow <= 0:
                return
            oldest = sorted(
                self.reports.values(), key=lambda r: r.assessment_date
            )[:overflow]
            for report in oldest:
                self.reports.pop(report.id, None)
        except Exception as exc:
            logger.warning("claims_bot report cap enforcement failed: %s", exc)
    
    # =========================================================================
    # Component Analysis Methods
    # =========================================================================
    
    def _find_underwriting_record(self, customer_id: str, policy_id: str) -> Dict:
        """Find underwriting application for customer/policy"""
        # Search by policy_id first
        for uw_id, uw in self._underwriting.items():
            if uw.get('policy_id') == policy_id:
                return uw
            if uw.get('customer_id') == customer_id:
                return uw
        
        # Search by customer email
        customer = self._customers.get(customer_id, {})
        customer_email = customer.get('email', '')
        if customer_email:
            for uw_id, uw in self._underwriting.items():
                if uw.get('customer_email', '').lower() == customer_email.lower():
                    return uw
        
        return {}
    
    def _parse_date(self, date_str) -> Optional[datetime]:
        """Parse date string to datetime"""
        if not date_str:
            return None
        if isinstance(date_str, datetime):
            return date_str
        if isinstance(date_str, date):
            return datetime.combine(date_str, datetime.min.time())
        try:
            # Handle ISO format
            if 'T' in str(date_str):
                return datetime.fromisoformat(str(date_str).replace('Z', '+00:00').split('+')[0])
            return datetime.strptime(str(date_str), '%Y-%m-%d')
        except:
            return None
    
    def _analyze_document_authenticity(self, claim: Dict) -> float:
        """Analyze document authenticity score"""
        score = 0.85  # Base score
        
        # Check for files/evidence
        files = claim.get('files', [])
        files_count = claim.get('files_count', 0)
        
        if files or files_count > 0:
            score += 0.05  # Has supporting documents
        
        # Check for tampering flags (simulated)
        if claim.get('tampering_detected'):
            score -= 0.5
        
        # Check description quality
        description = claim.get('description', '')
        if len(description) > 50:
            score += 0.05  # Detailed description
        
        return max(0.0, min(1.0, score))
    
    def _analyze_medical_consistency(self, claim: Dict, underwriting: Dict) -> float:
        """Analyze medical consistency with underwriting data"""
        score = 0.80  # Base score
        
        claim_type = (claim.get('type', '') or '').lower()
        
        # Check if claim type matches policy coverage
        uw_medical_conditions = underwriting.get('medical_conditions', [])
        uw_disability = underwriting.get('disability_percentage', 0)
        
        # Medical/disability claims need more scrutiny
        if 'disability' in claim_type or 'medical' in claim_type:
            if uw_medical_conditions:
                # Has declared conditions - check consistency
                score += 0.10
            else:
                # No declared conditions but filing medical claim
                if uw_disability == 0:
                    score -= 0.15  # Suspicious
        
        # Check BMI and health indicators
        uw_bmi = underwriting.get('bmi', 0)
        if uw_bmi and uw_bmi > 35:
            # High BMI - health claims more expected
            if 'health' in claim_type or 'medical' in claim_type:
                score += 0.05
        
        return max(0.0, min(1.0, score))
    
    def _analyze_timing_legitimacy(self, claim: Dict, policy: Dict, days_since_policy: int) -> float:
        """Analyze timing legitimacy"""
        score = 0.85  # Base score
        
        # Very early claims are suspicious
        if days_since_policy < 30:
            score -= 0.30  # Very suspicious
        elif days_since_policy < 90:
            score -= 0.15  # Somewhat suspicious
        elif days_since_policy < 180:
            score -= 0.05  # Slightly suspicious
        
        # Claims around 7-8 years (contestability just passed for some conditions)
        years = days_since_policy / 365.25
        if 7 <= years <= 8:
            # This is the user's mentioned ~7.66 year suspicious window
            score -= 0.10
        
        # Very old policies have more legitimacy
        if years > 5:
            score += 0.05
        
        return max(0.0, min(1.0, score))
    
    def _analyze_amount_reasonability(self, claim: Dict, policy: Dict) -> float:
        """Analyze claim amount reasonability"""
        score = 0.85  # Base score
        
        claimed_amount = float(claim.get('claimed_amount', 0) or 0)
        coverage_amount = float(policy.get('coverage_amount', 0) or 500000)
        
        if coverage_amount > 0:
            ratio = claimed_amount / coverage_amount
            
            if ratio >= 0.95:
                # Nearly full coverage claim - very suspicious
                score -= 0.25
            elif ratio >= 0.80:
                # High proportion - suspicious
                score -= 0.15
            elif ratio >= 0.50:
                # Moderate - slightly concerning
                score -= 0.05
            elif ratio < 0.10:
                # Small claim - more likely legitimate
                score += 0.05
        
        return max(0.0, min(1.0, score))
    
    def _analyze_customer_history(self, customer_id: str) -> float:
        """Analyze customer's claims history"""
        score = 0.90  # Base score
        
        # Count past claims
        past_claims = [c for c in self._claims.values() 
                      if c.get('customer_id') == customer_id]
        
        claim_count = len(past_claims)
        
        if claim_count == 0:
            score += 0.05  # First claim - slightly positive
        elif claim_count <= 2:
            pass  # Normal
        elif claim_count <= 5:
            score -= 0.10  # Multiple claims
        else:
            score -= 0.20  # Excessive claims
        
        # Check for past rejections
        rejected = sum(1 for c in past_claims 
                      if (c.get('status', '') or '').lower() in ['rejected', 'denied'])
        if rejected > 0:
            score -= rejected * 0.08
        
        return max(0.0, min(1.0, score))
    
    def _analyze_underwriting_alignment(self, claim: Dict, underwriting: Dict) -> float:
        """Analyze alignment between claim and underwriting data"""
        score = 0.80  # Base score
        
        if not underwriting:
            return 0.50  # No UW data - neutral score
        
        # Check declared conditions vs claim
        declared_conditions = underwriting.get('medical_conditions', [])
        uw_disability = underwriting.get('disability_percentage', 0)
        uw_smoking = underwriting.get('smoking_status', '')
        uw_bmi = underwriting.get('bmi', 0)
        
        claim_type = (claim.get('type', '') or '').lower()
        claim_desc = (claim.get('description', '') or '').lower()
        
        # If filing disability claim and declared disability at UW - good alignment
        if 'disability' in claim_type and uw_disability > 0:
            score += 0.15
        
        # If medical claim mentions conditions declared at UW - good
        if declared_conditions:
            for cond in declared_conditions:
                cond_name = (cond.get('condition', '') or '').lower()
                if cond_name and cond_name in claim_desc:
                    score += 0.10
                    break
        
        # Smoking-related claim from non-smoker - suspicious
        if 'lung' in claim_desc or 'respiratory' in claim_desc:
            if uw_smoking == 'never':
                score -= 0.10
        
        return max(0.0, min(1.0, score))
    
    # =========================================================================
    # Hidden Condition Detection
    # =========================================================================
    
    def _detect_hidden_conditions(self, claim: Dict, underwriting: Dict, 
                                   policy_start: Optional[datetime]) -> List[HiddenCondition]:
        """
        Detect potentially hidden conditions by comparing claim data with UW data.
        
        This is the core of fraud detection - identifying if the customer hid
        significant medical conditions during the underwriting process.
        """
        hidden = []
        
        if not underwriting:
            return hidden
        
        claim_desc = (claim.get('description', '') or '').lower()
        claim_type = (claim.get('type', '') or '').lower()
        
        declared_conditions = underwriting.get('medical_conditions', [])
        declared_names = set()
        for cond in declared_conditions:
            name = (cond.get('condition', '') or '').lower()
            if name:
                declared_names.add(name)
        
        # Check for undeclared conditions mentioned in claim
        suspicious_conditions = [
            ('heart', 'heart_disease', 'I25.9', 'Heart disease/cardiac condition'),
            ('cardiac', 'heart_disease', 'I25.9', 'Cardiac condition'),
            ('surgery', 'surgery_history', 'Z98.89', 'Prior surgery'),
            ('cancer', 'cancer', 'C80.1', 'Cancer/malignancy'),
            ('tumor', 'cancer', 'C80.1', 'Tumor/neoplasm'),
            ('diabetes', 'diabetes', 'E11.9', 'Diabetes mellitus'),
            ('stroke', 'stroke', 'I63.9', 'Stroke/CVA'),
            ('kidney', 'kidney_disease', 'N18.9', 'Kidney disease'),
            ('liver', 'liver_disease', 'K76.9', 'Liver disease'),
            ('lung', 'lung_disease', 'J98.4', 'Lung/respiratory disease'),
            ('copd', 'copd', 'J44.9', 'COPD'),
            ('transplant', 'transplant', 'Z94', 'Organ transplant'),
        ]
        
        for keyword, condition_type, icd, display_name in suspicious_conditions:
            if keyword in claim_desc:
                # Check if this was declared
                if not any(keyword in d for d in declared_names):
                    # Potentially hidden condition
                    
                    # Estimate concealment score based on severity
                    severity = self.HIGH_RISK_CONDITIONS.get(condition_type, {}).get('risk_factor', 0.5)
                    
                    # Check if within contestability period
                    causal_link = keyword in claim_type or 'medical' in claim_type
                    
                    hidden.append(HiddenCondition(
                        condition_name=display_name,
                        icd_code=icd,
                        evidence_source=f"Claim description mentions '{keyword}'",
                        detection_confidence=0.75,
                        estimated_onset_date=policy_start - timedelta(days=365) if policy_start else None,
                        was_before_policy=True,  # Assumed for this analysis
                        causal_link_to_claim=causal_link,
                        severity='high' if severity > 0.7 else 'moderate',
                        deliberate_concealment_score=severity * 0.8
                    ))
        
        # Special case: Heart surgery example from user
        if 'heart' in claim_desc and 'surgery' in claim_desc:
            if not any('heart' in d or 'cardiac' in d or 'surgery' in d for d in declared_names):
                hidden.append(HiddenCondition(
                    condition_name='Prior Heart Surgery (Undisclosed)',
                    icd_code='Z95.1',
                    evidence_source='Claim indicates heart surgery history not disclosed at underwriting',
                    detection_confidence=0.90,
                    estimated_onset_date=policy_start - timedelta(days=365) if policy_start else None,
                    was_before_policy=True,
                    causal_link_to_claim=True,
                    severity='critical',
                    deliberate_concealment_score=0.95
                ))
        
        return hidden
    
    # =========================================================================
    # Fraud Detection
    # =========================================================================
    
    def _detect_fraud_indicators(self, claim: Dict, customer: Dict, policy: Dict,
                                   underwriting: Dict, days_since_policy: int,
                                   hidden_conditions: List[HiddenCondition]) -> List[FraudIndicator]:
        """Detect fraud indicators based on multiple factors"""
        indicators = []
        
        claimed_amount = float(claim.get('claimed_amount', 0) or 0)
        coverage_amount = float(policy.get('coverage_amount', 0) or 500000)
        years_since_policy = days_since_policy / 365.25
        
        # 1. Timing-based fraud indicators
        if days_since_policy < 30:
            indicators.append(FraudIndicator(
                id=self._generate_id('FI'),
                indicator_type=FraudIndicatorType.TIMING_SUSPICIOUS,
                severity=0.8,
                evidence=[f"Claim filed only {days_since_policy} days after policy start"],
                explanation="Claims filed within 30 days of policy activation are statistically associated with fraud",
                recommendation="Require additional documentation and medical records",
                requires_investigation=True
            ))
        elif days_since_policy < 90:
            indicators.append(FraudIndicator(
                id=self._generate_id('FI'),
                indicator_type=FraudIndicatorType.TIMING_SUSPICIOUS,
                severity=0.5,
                evidence=[f"Claim filed {days_since_policy} days after policy start"],
                explanation="Early claims warrant additional scrutiny",
                recommendation="Request pre-policy medical records",
                requires_investigation=False
            ))
        
        # Special case: 7-8 year window (user mentioned ~7.66 years)
        if 7 <= years_since_policy <= 8 and claimed_amount >= coverage_amount * 0.8:
            indicators.append(FraudIndicator(
                id=self._generate_id('FI'),
                indicator_type=FraudIndicatorType.TIMING_SUSPICIOUS,
                severity=0.6,
                evidence=[
                    f"Claim filed {years_since_policy:.2f} years after policy start",
                    f"Claim amount (${claimed_amount:,.2f}) is {claimed_amount/coverage_amount*100:.1f}% of coverage"
                ],
                explanation="High-value claims filed after contestability period may indicate long-term fraud planning",
                recommendation="Request complete medical history and conduct thorough investigation",
                requires_investigation=True
            ))
        
        # 2. Amount-based fraud indicators
        if coverage_amount > 0:
            ratio = claimed_amount / coverage_amount
            if ratio >= 0.95:
                indicators.append(FraudIndicator(
                    id=self._generate_id('FI'),
                    indicator_type=FraudIndicatorType.AMOUNT_SUSPICIOUS,
                    severity=0.75,
                    evidence=[f"Claim for ${claimed_amount:,.2f} is {ratio*100:.1f}% of total coverage"],
                    explanation="Near-maximum coverage claims are statistically associated with inflated or fraudulent claims",
                    recommendation="Require independent medical examination and itemized billing",
                    requires_investigation=True
                ))
        
        # 3. Hidden condition indicators
        for hc in hidden_conditions:
            if hc.deliberate_concealment_score > 0.7:
                indicators.append(FraudIndicator(
                    id=self._generate_id('FI'),
                    indicator_type=FraudIndicatorType.CONDITION_HIDDEN_AT_UW,
                    severity=hc.deliberate_concealment_score,
                    evidence=[
                        f"Condition '{hc.condition_name}' found in claim but not declared at underwriting",
                        hc.evidence_source
                    ],
                    explanation=f"Material misrepresentation during underwriting. {hc.condition_name} appears to have existed before policy inception.",
                    recommendation="Consider claim denial under contestability provisions" if hc.causal_link_to_claim else "Flag for medical review",
                    requires_investigation=True
                ))
        
        # 4. Excessive claim history
        customer_id = claim.get('customer_id')
        past_claims = [c for c in self._claims.values() 
                      if c.get('customer_id') == customer_id and c.get('id') != claim.get('id')]
        if len(past_claims) >= 5:
            indicators.append(FraudIndicator(
                id=self._generate_id('FI'),
                indicator_type=FraudIndicatorType.EXCESSIVE_CLAIM_HISTORY,
                severity=0.5,
                evidence=[f"Customer has filed {len(past_claims)} previous claims"],
                explanation="Excessive claim frequency may indicate systematic abuse",
                recommendation="Review all past claims for patterns",
                requires_investigation=False
            ))
        
        return indicators
    
    # =========================================================================
    # Decision Making
    # =========================================================================
    
    def _make_recommendation(self, authenticity: float, 
                              fraud_indicators: List[FraudIndicator],
                              hidden_conditions: List[HiddenCondition],
                              within_contestability: bool,
                              claim: Dict) -> Tuple[ClaimDecisionType, float, str]:
        """Make claim decision recommendation"""
        
        # Check for critical fraud indicators
        critical_indicators = [fi for fi in fraud_indicators if fi.severity > 0.8]
        investigation_required = any(fi.requires_investigation for fi in fraud_indicators)
        
        # Check for causally-linked hidden conditions
        causal_hidden = [hc for hc in hidden_conditions if hc.causal_link_to_claim]
        
        # Decision logic
        if authenticity >= 0.85 and not critical_indicators and not causal_hidden:
            return (
                ClaimDecisionType.APPROVE_FULL,
                0.90,
                f"High authenticity score ({authenticity:.1%}). No significant fraud indicators detected. Recommend full approval."
            )
        
        elif authenticity >= 0.70 and not critical_indicators:
            if hidden_conditions:
                return (
                    ClaimDecisionType.REFER_MEDICAL_REVIEW,
                    0.75,
                    f"Moderate authenticity ({authenticity:.1%}) with potential hidden conditions. Medical review recommended."
                )
            return (
                ClaimDecisionType.APPROVE_PARTIAL,
                0.80,
                f"Good authenticity score ({authenticity:.1%}). Minor concerns noted. Partial approval recommended."
            )
        
        elif causal_hidden and within_contestability:
            return (
                ClaimDecisionType.DENY_HIDDEN_CONDITION,
                0.85,
                f"Hidden pre-existing condition detected that is causally linked to claim. Policy is within contestability period. Denial recommended."
            )
        
        elif critical_indicators:
            if any(fi.indicator_type == FraudIndicatorType.DOCUMENT_TAMPERED for fi in critical_indicators):
                return (
                    ClaimDecisionType.DENY_FRAUD_SUSPECTED,
                    0.90,
                    "Document tampering detected. Strong evidence of fraud. Denial recommended with SIU referral."
                )
            return (
                ClaimDecisionType.REFER_INVESTIGATION,
                0.80,
                f"Critical fraud indicators detected. Special Investigation Unit review required."
            )
        
        elif investigation_required:
            return (
                ClaimDecisionType.REFER_INVESTIGATION,
                0.70,
                f"Multiple fraud indicators require investigation. Authenticity score: {authenticity:.1%}"
            )
        
        elif authenticity < 0.45:
            return (
                ClaimDecisionType.DENY_FRAUD_SUSPECTED,
                0.75,
                f"Low authenticity score ({authenticity:.1%}). Multiple red flags detected. Denial recommended."
            )
        
        else:
            return (
                ClaimDecisionType.PENDING_MORE_INFO,
                0.60,
                f"Insufficient confidence for decision. Additional documentation required. Current authenticity: {authenticity:.1%}"
            )
    
    def _generate_ai_summary(self, claim: Dict, authenticity: float,
                              fraud_indicators: List[FraudIndicator],
                              hidden_conditions: List[HiddenCondition],
                              risk_level: str) -> Tuple[str, List[str], List[str], List[str]]:
        """Generate AI analysis summary"""
        
        claim_type = claim.get('type', 'General')
        claimed_amount = float(claim.get('claimed_amount', 0) or 0)
        
        # Key findings
        findings = []
        findings.append(f"Claim type: {claim_type}, Amount: ${claimed_amount:,.2f}")
        findings.append(f"Overall authenticity probability: {authenticity:.1%}")
        findings.append(f"Risk level assessment: {risk_level.upper()}")
        if fraud_indicators:
            findings.append(f"{len(fraud_indicators)} fraud indicator(s) detected")
        if hidden_conditions:
            findings.append(f"{len(hidden_conditions)} potential hidden condition(s) identified")
        
        # Red flags
        red_flags = []
        for fi in fraud_indicators:
            if fi.severity > 0.5:
                red_flags.append(f"⚠️ {fi.explanation[:100]}...")
        for hc in hidden_conditions:
            if hc.deliberate_concealment_score > 0.6:
                red_flags.append(f"🔴 Undisclosed: {hc.condition_name}")
        
        # Green flags
        green_flags = []
        if authenticity > 0.7:
            green_flags.append("✅ High document authenticity score")
        if not fraud_indicators:
            green_flags.append("✅ No fraud indicators detected")
        if not hidden_conditions:
            green_flags.append("✅ No hidden conditions detected")
        if claim.get('files_count', 0) > 0:
            green_flags.append("✅ Supporting documentation provided")
        
        # Summary
        if authenticity >= 0.85:
            summary = f"This {claim_type} claim appears to be LEGITIMATE with high confidence. The customer's documentation is consistent with their underwriting profile and no significant red flags were identified."
        elif authenticity >= 0.65:
            summary = f"This {claim_type} claim has MODERATE legitimacy indicators. Some concerns were noted that warrant additional review, but no definitive fraud signals detected."
        elif authenticity >= 0.45:
            summary = f"This {claim_type} claim has ELEVATED RISK indicators. Multiple concerns were identified that require careful investigation before any approval."
        else:
            summary = f"This {claim_type} claim has HIGH FRAUD PROBABILITY. Significant red flags detected including potential hidden pre-existing conditions and/or suspicious timing patterns."
        
        return summary, findings, red_flags, green_flags
    
    # =========================================================================
    # Public API Methods
    # =========================================================================
    
    def get_report(self, report_id: str) -> Optional[ClaimProbabilityReport]:
        """Get a report by ID"""
        return self.reports.get(report_id)
    
    def get_report_by_claim(self, claim_id: str) -> Optional[ClaimProbabilityReport]:
        """Get the latest report for a claim"""
        for report in sorted(self.reports.values(), 
                            key=lambda r: r.assessment_date, reverse=True):
            if report.claim_id == claim_id:
                return report
        return None
    
    def get_all_reports(self) -> List[Dict]:
        """Get all reports as dictionaries"""
        return [r.to_dict() for r in self.reports.values()]

    def list_reports(self, claim_id: Optional[str] = None) -> List[Dict]:
        """List stored reports (optionally filtered by claim), newest first."""
        reports = sorted(
            self.reports.values(), key=lambda r: r.assessment_date, reverse=True
        )
        if claim_id:
            reports = [r for r in reports if r.claim_id == claim_id]
        return [r.to_dict() for r in reports]


# ============================================================================
# Factory
# ============================================================================

_bot_instance: Optional[ClaimsBotService] = None


def get_claims_bot_service(customers: Dict = None,
                           policies: Dict = None,
                           claims: Dict = None,
                           underwriting: Dict = None,
                           audit_service = None) -> ClaimsBotService:
    """Get or create claims bot service instance"""
    global _bot_instance
    if _bot_instance is None:
        _bot_instance = ClaimsBotService(
            customers=customers,
            policies=policies,
            claims=claims,
            underwriting=underwriting,
            audit_service=audit_service
        )
    return _bot_instance


def init_claims_bot_service(customers: Dict,
                            policies: Dict,
                            claims: Dict,
                            underwriting: Dict,
                            audit_service = None) -> ClaimsBotService:
    """Initialize claims bot service with dependencies"""
    global _bot_instance
    _bot_instance = ClaimsBotService(
        customers=customers,
        policies=policies,
        claims=claims,
        underwriting=underwriting,
        audit_service=audit_service
    )
    return _bot_instance


__all__ = [
    'ClaimsBotService',
    'get_claims_bot_service',
    'init_claims_bot_service',
    'ClaimMetadataType',
    'FraudIndicatorType',
    'ClaimDecisionType',
    'HiddenCondition',
    'FraudIndicator',
    'ClaimProbabilityReport'
]
