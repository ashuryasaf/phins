"""
AI Automation Controller for PHINS
Orchestrates automated insurance operations using AI and ML models.

Features:
- Auto-quote generation using ML models
- Automated risk assessment
- Smart claims processing
- Fraud detection
- Integration with existing engines (underwriting, billing, accounting)
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, date
from enum import Enum
import logging
import random

# AI-1/AI-2/AI-3 wiring. These are light, dependency-free modules; importing them
# never pulls in a numeric/ML stack. All are best-effort: if anything here fails
# the controller still makes its deterministic rule-based decision.
try:
    from services.ai_decision_log import get_ai_decision_log
    from services.ai_threshold_config import get_threshold_config, segment_key
    from services.ai_model_registry import get_model_registry
    _AI_SUPPORT = True
except Exception:  # pragma: no cover - defensive import guard
    _AI_SUPPORT = False

logger = logging.getLogger('phins.ai_automation')

# ---------------------------------------------------------------------------
# PII minimization for the decision log.
#
# The append-only decision log is audit/calibration data, NOT a copy of the
# customer record. We log only the non-PII *features* that actually drive a
# decision (age band inputs, risk indicators, amounts) and deliberately exclude
# direct identifiers and sensitive fields (name, email, phone, address, SSN /
# national id, dates of birth, free-text medical notes, raw documents). This
# upholds data-minimization / HIPAA expectations and keeps the log from becoming
# a concentrated PII target. ``entity_id`` is kept separately for linkage.
# ---------------------------------------------------------------------------

QUOTE_FEATURE_FIELDS = (
    'age', 'occupation', 'health_score', 'coverage_amount', 'coverage_type',
    'smoking', 'complete_medical_history', 'stable_employment',
    'no_pre_existing_conditions',
)
UNDERWRITE_FEATURE_FIELDS = (
    'age', 'occupation', 'smoker', 'pre_existing_conditions', 'health_score',
    'employment_stable', 'employment_stable', 'coverage_amount',
    'recent_claims_count', 'multiple_applications_same_day',
    'inconsistent_information', 'high_coverage_new_customer',
    'suspicious_documents',
)
CLAIM_FEATURE_FIELDS = (
    'claimed_amount', 'amount', 'type', 'claim_type', 'policy_coverage',
    'days_since_policy_start', 'has_complete_documentation', 'has_documents',
    'recent_claims_count', 'average_claim_for_type',
)


class AutomationDecision(Enum):
    """Automation decision types"""
    AUTO_APPROVE = "auto_approve"
    AUTO_REJECT = "auto_reject"
    HUMAN_REVIEW = "human_review"
    NEEDS_MORE_INFO = "needs_more_info"


class FraudRisk(Enum):
    """Fraud risk levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AutomationMetrics:
    """Metrics for automation performance"""
    total_processed: int = 0
    auto_approved: int = 0
    auto_rejected: int = 0
    human_review: int = 0
    fraud_detected: int = 0
    average_processing_time_ms: float = 0.0
    accuracy_rate: float = 0.0
    
    def get_automation_rate(self) -> float:
        """Calculate percentage of automated decisions"""
        if self.total_processed == 0:
            return 0.0
        automated = self.auto_approved + self.auto_rejected
        return (automated / self.total_processed) * 100


class AIAutomationController:
    """Main controller for AI-powered automation"""
    
    def __init__(self):
        """Initialize the automation controller"""
        self.metrics = AutomationMetrics()
        self.fraud_detection_enabled = True
        # Global defaults. Per-segment thresholds (AI-2) default to these exact
        # values, so segmentation changes nothing until an operator explicitly
        # promotes calibrated thresholds.
        self.auto_approve_threshold = 0.85  # 85% confidence for auto-approval
        self.auto_reject_threshold = 0.15   # Below 15% confidence = auto-reject
        # AI-1/AI-2/AI-3 collaborators (None when support is unavailable).
        self._decision_log = get_ai_decision_log() if _AI_SUPPORT else None
        self._thresholds = get_threshold_config() if _AI_SUPPORT else None
        self._model_registry = get_model_registry() if _AI_SUPPORT else None

    # ------------------------------------------------------------------
    # AI-1: append-only decision logging (best-effort, never fatal)
    # ------------------------------------------------------------------

    @staticmethod
    def _feature_snapshot(data: Dict[str, Any], allowed_fields) -> Dict[str, Any]:
        """Return only the allowlisted, non-PII feature fields present in ``data``.

        Everything else (names, emails, addresses, national ids, free-text
        medical notes, raw documents, etc.) is dropped before the decision is
        logged, so the append-only log never accumulates raw PII.
        """
        if not data:
            return {}
        return {k: data[k] for k in allowed_fields if k in data}

    def _log_decision(
        self,
        decision_type: str,
        output: Dict[str, Any],
        inputs: Optional[Dict[str, Any]] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        model_version: str = 'rules-v1',
        confidence: Optional[float] = None,
        segment: Optional[str] = None,
    ) -> Optional[str]:
        if not self._decision_log:
            return None
        try:
            return self._decision_log.record(
                decision_type=decision_type,
                output=output,
                inputs=inputs,
                entity_type=entity_type,
                entity_id=entity_id,
                model_version=model_version,
                confidence=confidence,
                segment=segment,
            )
        except Exception as exc:  # never break decisioning
            logger.warning("decision logging failed: %s", exc)
            return None

    def record_human_override(
        self,
        decision_id: str,
        human_decision: str,
        reason: Optional[str] = None,
        overridden_by: Optional[str] = None,
    ) -> bool:
        """Record that a human overrode an automated decision (feedback loop).

        Append-only: this links an override to the original decision without
        rewriting the original inputs/output.
        """
        if not self._decision_log:
            return False
        return self._decision_log.record_override(
            decision_id, human_decision, reason, overridden_by
        )

    def get_decision_log_summary(self) -> Dict[str, Any]:
        """Aggregate view of logged decisions (counts, override/disagreement rate)."""
        if not self._decision_log:
            return {'total_decisions': 0, 'available': False}
        summary = self._decision_log.summary()
        summary['available'] = True
        return summary

    def _segment_thresholds(self, application_data: Dict[str, Any]) -> Tuple[float, float, str]:
        """Resolve (approve, reject, segment) thresholds for an application.

        Defaults to the controller's global constants, so behavior is identical
        to the pre-segmentation controller unless thresholds were promoted.
        """
        if not self._thresholds:
            return self.auto_approve_threshold, self.auto_reject_threshold, 'global'
        seg = segment_key(application_data)
        approve, reject = self._thresholds.get(seg)
        return approve, reject, seg

    def _model_score(self, name: str, features: Dict[str, Any]) -> Tuple[Optional[float], str]:
        """Consult the model registry. Returns (score_or_None, model_version).

        With no artifact present (the default everywhere today) this returns
        (None, 'rules-v1') and the caller uses the deterministic rule scorer.
        """
        if not self._model_registry:
            return None, 'rules-v1'
        handle = self._model_registry.get_model(name)
        if handle is None:
            return None, 'rules-v1'
        return handle.score(features), handle.registry_id
        
    # =========================================================================
    # AUTO-QUOTE GENERATION
    # =========================================================================
    
    def generate_auto_quote(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Automatically generate insurance quote using ML models.
        
        Args:
            customer_data: Customer information (age, health, occupation, etc.)
            
        Returns:
            Quote with premium, coverage, and confidence score
        """
        age = customer_data.get('age', 30)
        occupation = customer_data.get('occupation', 'office_worker')
        health_score = customer_data.get('health_score', 7)  # 1-10 scale
        coverage_amount = customer_data.get('coverage_amount', 500000)
        smoking = customer_data.get('smoking', False)
        
        # Calculate base premium using simple risk model
        # In production, this would use actual ML models
        base_premium = coverage_amount * 0.0012  # Base rate 0.12%
        
        # Age factor
        if age < 25:
            age_multiplier = 1.2
        elif age < 35:
            age_multiplier = 1.0
        elif age < 45:
            age_multiplier = 1.15
        elif age < 55:
            age_multiplier = 1.35
        else:
            age_multiplier = 1.6
        
        # Health factor
        health_multiplier = 2.0 - (health_score / 10)  # 1.0 to 1.9
        
        # Smoking factor
        smoking_multiplier = 1.5 if smoking else 1.0
        
        # Occupation factor
        occupation_risk = {
            'office_worker': 1.0,
            'healthcare': 1.1,
            'construction': 1.4,
            'transportation': 1.3,
            'emergency_services': 1.5,
            'manual_labor': 1.35
        }
        occupation_multiplier = occupation_risk.get(occupation, 1.2)
        
        # Calculate final premium
        annual_premium = base_premium * age_multiplier * health_multiplier * smoking_multiplier * occupation_multiplier
        monthly_premium = annual_premium / 12
        
        # Calculate confidence score
        confidence = self._calculate_quote_confidence(customer_data)
        
        quote = {
            'quote_id': f"QT-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}",
            'annual_premium': round(annual_premium, 2),
            'monthly_premium': round(monthly_premium, 2),
            'coverage_amount': coverage_amount,
            'confidence_score': confidence,
            'risk_factors': {
                'age': age_multiplier,
                'health': health_multiplier,
                'smoking': smoking_multiplier,
                'occupation': occupation_multiplier
            },
            'generated_at': datetime.now().isoformat(),
            'valid_until': (datetime.now().replace(hour=23, minute=59, second=59)).isoformat()
        }
        # AI-1: log the quote decision (advisory record; no money movement).
        # PII-minimized: only non-PII rating features are logged.
        self._log_decision(
            decision_type='quote',
            inputs=self._feature_snapshot(customer_data, QUOTE_FEATURE_FIELDS),
            output={
                'decision': 'quote_generated',
                'annual_premium': quote['annual_premium'],
                'monthly_premium': quote['monthly_premium'],
                'coverage_amount': coverage_amount,
            },
            entity_type='customer',
            entity_id=customer_data.get('customer_id') or customer_data.get('id'),
            confidence=confidence,
        )
        return quote
    
    def _calculate_quote_confidence(self, customer_data: Dict[str, Any]) -> float:
        """Calculate confidence score for quote"""
        # Factors that increase confidence
        confidence = 0.7  # Base confidence
        
        if customer_data.get('complete_medical_history'):
            confidence += 0.15
        if customer_data.get('stable_employment'):
            confidence += 0.1
        if customer_data.get('no_pre_existing_conditions'):
            confidence += 0.05
        
        return min(confidence, 1.0)
    
    # =========================================================================
    # AUTOMATED UNDERWRITING
    # =========================================================================
    
    def auto_underwrite(self, application_data: Dict[str, Any]) -> Tuple[AutomationDecision, Dict[str, Any]]:
        """
        Automatically assess underwriting application.
        
        Args:
            application_data: Application with customer and health information
            
        Returns:
            (decision, details) tuple
        """
        self.metrics.total_processed += 1
        
        # Risk assessment (deterministic rule scorer — authoritative by default)
        risk_score = self._assess_risk(application_data)
        fraud_risk = self._detect_fraud(application_data) if self.fraud_detection_enabled else FraudRisk.LOW

        # AI-2: per-segment thresholds (default to the global constants).
        approve_threshold, reject_threshold, segment = self._segment_thresholds(application_data)
        # AI-3: a trained model may *inform* (logged for drift) but rules decide.
        model_score, model_version = self._model_score('underwriting', application_data)

        # Check for fraud first
        if fraud_risk in [FraudRisk.HIGH, FraudRisk.CRITICAL]:
            self.metrics.fraud_detected += 1
            self.metrics.human_review += 1
            decision = AutomationDecision.HUMAN_REVIEW
            details = {
                'reason': 'Potential fraud detected',
                'fraud_risk': fraud_risk.value,
                'requires_investigation': True
            }
        # Auto-decision based on risk score
        elif risk_score >= approve_threshold:
            self.metrics.auto_approved += 1
            decision = AutomationDecision.AUTO_APPROVE
            details = {
                'risk_score': risk_score,
                'premium_adjustment': 1.0,  # No adjustment
                'conditions': []
            }
        elif risk_score <= reject_threshold:
            self.metrics.auto_rejected += 1
            decision = AutomationDecision.AUTO_REJECT
            details = {
                'risk_score': risk_score,
                'rejection_reason': 'Risk score too low for coverage'
            }
        else:
            # Mid-range - needs human review
            self.metrics.human_review += 1
            decision = AutomationDecision.HUMAN_REVIEW
            details = {
                'risk_score': risk_score,
                'review_priority': 'medium' if risk_score > 0.5 else 'high',
                'suggested_action': 'approve_with_conditions' if risk_score > 0.5 else 'request_medical_exam'
            }

        # AI-1: persist the decision (append-only, advisory; never moves money).
        # PII-minimized: only non-PII risk features are logged, not the raw
        # application payload.
        decision_id = self._log_decision(
            decision_type='underwrite',
            inputs=self._feature_snapshot(application_data, UNDERWRITE_FEATURE_FIELDS),
            output={
                'decision': decision.value,
                'risk_score': risk_score,
                'approve_threshold': approve_threshold,
                'reject_threshold': reject_threshold,
                'fraud_risk': fraud_risk.value,
                'model_score': model_score,
            },
            entity_type='underwriting_application',
            entity_id=application_data.get('application_id') or application_data.get('id'),
            model_version=model_version,
            confidence=risk_score,
            segment=segment,
        )
        if decision_id:
            details['decision_id'] = decision_id
        details['segment'] = segment
        return (decision, details)
    
    def _assess_risk(self, application_data: Dict[str, Any]) -> float:
        """
        Assess risk score (0.0 to 1.0, higher is better).
        In production, this would use trained ML models.
        """
        score = 0.5  # Start at neutral
        
        # Age factor
        age = application_data.get('age', 30)
        if 25 <= age <= 45:
            score += 0.2
        elif 18 <= age < 25 or 45 < age <= 55:
            score += 0.1
        elif age > 65:
            score -= 0.2
        
        # Health factors
        if not application_data.get('smoker', False):
            score += 0.1
        else:
            score -= 0.15
        
        if not application_data.get('pre_existing_conditions', False):
            score += 0.15
        else:
            score -= 0.2
        
        health_score = application_data.get('health_score', 5)
        score += (health_score - 5) * 0.05  # +/- based on health
        
        # Employment stability
        if application_data.get('employment_stable', False):
            score += 0.1
        
        # Normalize to 0-1 range
        return max(0.0, min(1.0, score))
    
    def _detect_fraud(self, application_data: Dict[str, Any]) -> FraudRisk:
        """
        Detect potential fraud in application.
        Uses pattern matching and anomaly detection.
        """
        fraud_indicators = 0
        
        # Check for suspicious patterns
        if application_data.get('multiple_applications_same_day', False):
            fraud_indicators += 2
        
        if application_data.get('inconsistent_information', False):
            fraud_indicators += 3
        
        if application_data.get('high_coverage_new_customer', False):
            fraud_indicators += 1
        
        if application_data.get('suspicious_documents', False):
            fraud_indicators += 3
        
        # Recent claim history
        recent_claims = application_data.get('recent_claims_count', 0)
        if recent_claims > 2:
            fraud_indicators += 2
        
        # Map indicators to risk level
        if fraud_indicators >= 5:
            return FraudRisk.CRITICAL
        elif fraud_indicators >= 3:
            return FraudRisk.HIGH
        elif fraud_indicators >= 1:
            return FraudRisk.MEDIUM
        else:
            return FraudRisk.LOW
    
    # =========================================================================
    # SMART CLAIMS PROCESSING
    # =========================================================================
    
    def auto_process_claim(self, claim_data: Dict[str, Any]) -> Tuple[AutomationDecision, Dict[str, Any]]:
        """
        Automatically process insurance claim.
        
        Args:
            claim_data: Claim information with amount, type, documentation
            
        Returns:
            (decision, details) tuple
        """
        claim_amount = claim_data.get('claimed_amount', 0)
        claim_type = claim_data.get('type', 'unknown')
        policy_coverage = claim_data.get('policy_coverage', 0)
        fraud_risk = FraudRisk.LOW

        # Auto-approve low-value straightforward claims
        if claim_amount < 1000 and claim_type in ['medical', 'dental']:
            decision = AutomationDecision.AUTO_APPROVE
            details = {
                'approved_amount': claim_amount,
                'reason': 'Low-value claim with standard documentation',
                'payment_method': 'direct_deposit'
            }
        else:
            # Check fraud risk
            fraud_risk = self._detect_claim_fraud(claim_data)
            if fraud_risk in [FraudRisk.HIGH, FraudRisk.CRITICAL]:
                decision = AutomationDecision.HUMAN_REVIEW
                details = {
                    'reason': 'Potential fraud detected in claim',
                    'fraud_risk': fraud_risk.value,
                    'requires_investigation': True
                }
            # Check if claim exceeds coverage
            elif claim_amount > policy_coverage:
                decision = AutomationDecision.HUMAN_REVIEW
                details = {
                    'reason': 'Claim exceeds policy coverage',
                    'suggested_action': 'approve_partial',
                    'max_approved_amount': policy_coverage
                }
            # Complex claims need human review
            elif claim_type in ['disability', 'death', 'major_medical']:
                decision = AutomationDecision.HUMAN_REVIEW
                details = {
                    'reason': 'Complex claim type requires adjuster review',
                    'priority': 'high'
                }
            else:
                # Medium-value claims with complete documentation
                decision = AutomationDecision.HUMAN_REVIEW
                details = {
                    'reason': 'Standard review required',
                    'priority': 'normal',
                    'suggested_action': 'approve',
                    'suggested_amount': claim_amount
                }

        # AI-1: persist the claim decision (append-only; advisory, never posts).
        # PII-minimized: only non-PII claim features are logged.
        decision_id = self._log_decision(
            decision_type='claim',
            inputs=self._feature_snapshot(claim_data, CLAIM_FEATURE_FIELDS),
            output={
                'decision': decision.value,
                'reason': details.get('reason'),
                'fraud_risk': fraud_risk.value,
                'claimed_amount': claim_amount,
                'claim_type': claim_type,
            },
            entity_type='claim',
            entity_id=claim_data.get('claim_id') or claim_data.get('id'),
        )
        if decision_id:
            details['decision_id'] = decision_id
        return (decision, details)
    
    def _detect_claim_fraud(self, claim_data: Dict[str, Any]) -> FraudRisk:
        """Detect potential fraud in claim submission"""
        fraud_score = 0
        
        # Multiple claims in short period
        if claim_data.get('recent_claims_count', 0) > 3:
            fraud_score += 2
        
        # Claim shortly after policy start
        days_since_policy = claim_data.get('days_since_policy_start', 365)
        if days_since_policy < 30:
            fraud_score += 1
        
        # Missing or incomplete documentation
        if not claim_data.get('has_complete_documentation', True):
            fraud_score += 1
        
        # Unusually high amount
        average_claim = claim_data.get('average_claim_for_type', 5000)
        claim_amount = claim_data.get('claimed_amount', 0)
        if claim_amount > average_claim * 3:
            fraud_score += 2
        
        if fraud_score >= 4:
            return FraudRisk.CRITICAL
        elif fraud_score >= 2:
            return FraudRisk.HIGH
        elif fraud_score >= 1:
            return FraudRisk.MEDIUM
        else:
            return FraudRisk.LOW
    
    # =========================================================================
    # BILLING AUTOMATION
    # =========================================================================
    
    def auto_generate_invoice(self, policy_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Automatically generate invoice for policy premium.
        Integrates with billing_engine.py
        """
        policy_id = policy_data.get('policy_id')
        premium_amount = policy_data.get('premium_amount', 0)
        billing_frequency = policy_data.get('billing_frequency', 'monthly')
        
        # Calculate due date based on frequency
        if billing_frequency == 'monthly':
            due_date = datetime.now().replace(day=1)
        elif billing_frequency == 'quarterly':
            # First day of next quarter with proper year rollover
            current_month = datetime.now().month
            current_year = datetime.now().year
            next_quarter_month = ((current_month - 1) // 3 + 1) * 3 + 1
            if next_quarter_month > 12:
                next_quarter_month = 1
            # Calculate next quarter properly (Q1=Jan, Q2=Apr, Q3=Jul, Q4=Oct)
            current_month = datetime.now().month
            current_year = datetime.now().year
            # Get current quarter (0-3) and calculate next quarter
            current_quarter = (current_month - 1) // 3
            next_quarter = (current_quarter + 1) % 4
            # Map quarters to first month: [1, 4, 7, 10]
            quarter_months = [1, 4, 7, 10]
            next_quarter_month = quarter_months[next_quarter]
            # Handle year rollover when going from Q4 to Q1
            if next_quarter == 0:  # Q1 of next year
                current_year += 1
            due_date = datetime.now().replace(year=current_year, month=next_quarter_month, day=1)
        else:  # annual
            due_date = datetime.now().replace(month=1, day=1)
        
        return {
            'invoice_id': f"INV-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}",
            'policy_id': policy_id,
            'amount': premium_amount,
            'due_date': due_date.isoformat(),
            'status': 'pending',
            'generated_at': datetime.now().isoformat()
        }
    
    # =========================================================================
    # METRICS AND MONITORING
    # =========================================================================
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get automation performance metrics"""
        return {
            'total_processed': self.metrics.total_processed,
            'auto_approved': self.metrics.auto_approved,
            'auto_rejected': self.metrics.auto_rejected,
            'human_review': self.metrics.human_review,
            'fraud_detected': self.metrics.fraud_detected,
            'automation_rate': round(self.metrics.get_automation_rate(), 2),
            'average_processing_time_ms': self.metrics.average_processing_time_ms
        }
    
    def reset_metrics(self):
        """Reset metrics (for testing or new period)"""
        self.metrics = AutomationMetrics()


# Singleton instance
_controller_instance = None


def get_automation_controller() -> AIAutomationController:
    """Get singleton automation controller instance"""
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = AIAutomationController()
    return _controller_instance

# =========================================================================
# BACKWARD COMPATIBILITY - Function-based API
# =========================================================================
# These functions provide backward compatibility with the old function-based API
# while using the enhanced class-based implementation internally.

def auto_quote(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate automated insurance quote (backward compatible wrapper).
    
    Args:
        data: Dictionary containing customer information
        
    Returns:
        Quote with premium, coverage, and confidence score
    """
    controller = get_automation_controller()
    result = controller.generate_auto_quote(data)
    
    # Map to old format for compatibility
    return {
        'quote_amount': result['annual_premium'],
        'confidence_score': result['confidence_score'],
        'risk_factors': list(result['risk_factors'].keys()) if isinstance(result['risk_factors'], dict) else [],
        'monthly_premium': result['monthly_premium'],
        'coverage_type': data.get('coverage_type', 'life')
    }


def auto_underwrite(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Automated underwriting decision (backward compatible wrapper).
    
    Args:
        data: Dictionary containing application information
        
    Returns:
        Dictionary with decision, risk_score, risk_level, and reasons
    """
    controller = get_automation_controller()
    decision, details = controller.auto_underwrite(data)
    
    # Map to old format
    risk_score = details.get('risk_score', 0.5)
    
    # Determine risk level from risk score
    if risk_score >= 0.8:
        risk_level = 'low'
    elif risk_score >= 0.6:
        risk_level = 'medium'
    elif risk_score >= 0.4:
        risk_level = 'high'
    else:
        risk_level = 'very_high'
    
    # Map decision to old format
    decision_map = {
        AutomationDecision.AUTO_APPROVE: 'AUTO_APPROVE',
        AutomationDecision.AUTO_REJECT: 'AUTO_REJECT',
        AutomationDecision.HUMAN_REVIEW: 'MANUAL_REVIEW',
        AutomationDecision.NEEDS_MORE_INFO: 'MANUAL_REVIEW'
    }
    
    return {
        'decision': decision_map.get(decision, 'MANUAL_REVIEW'),
        'risk_score': round(risk_score, 2),
        'risk_level': risk_level,
        'reasons': [details.get('reason', 'standard_assessment')],
        'requires_medical_exam': risk_score < 0.7,
        'recommended_premium_adjustment': round((1.0 - risk_score) * 50, 2)
    }


def auto_process_claim(claim: Dict[str, Any]) -> Dict[str, Any]:
    """
    Automated claims processing decision (backward compatible wrapper).
    
    Args:
        claim: Dictionary containing claim information
        
    Returns:
        Dictionary with decision, approved_amount, confidence, and reasons
    """
    # Normalize field names for backward compatibility
    normalized_claim = claim.copy()
    if 'amount' in claim and 'claimed_amount' not in claim:
        normalized_claim['claimed_amount'] = claim['amount']
    if 'has_documents' in claim and 'has_complete_documentation' not in claim:
        normalized_claim['has_complete_documentation'] = claim['has_documents']
    if 'claim_type' in claim and 'type' not in claim:
        normalized_claim['type'] = claim['claim_type']
    # Provide a reasonable default for policy_coverage if missing
    if 'policy_coverage' not in normalized_claim:
        normalized_claim['policy_coverage'] = 1000000  # $1M default coverage
    
    controller = get_automation_controller()
    decision, details = controller.auto_process_claim(normalized_claim)
    
    # Map decision to old format
    decision_map = {
        AutomationDecision.AUTO_APPROVE: 'AUTO_APPROVED',
        AutomationDecision.AUTO_REJECT: 'AUTO_REJECTED',
        AutomationDecision.HUMAN_REVIEW: 'MANUAL_REVIEW',
        AutomationDecision.NEEDS_MORE_INFO: 'MANUAL_REVIEW'
    }
    
    return {
        'decision': decision_map.get(decision, 'MANUAL_REVIEW'),
        'approved_amount': details.get('approved_amount', 0),
        'confidence': 0.9 if decision == AutomationDecision.AUTO_APPROVE else 0.5,
        'reasons': [details.get('reason', 'standard_review')],
        'processing_time_hours': 1 if decision == AutomationDecision.AUTO_APPROVE else 48
    }


def detect_fraud(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Detect potential fraudulent activity patterns (backward compatible wrapper).
    
    Args:
        data: Dictionary containing activity patterns to analyze
        
    Returns:
        Dictionary with fraud_risk_level, fraud_score, flags, and recommended_action
    """
    # Calculate fraud score based on indicators (replicate detection logic)
    fraud_score = 0.0
    flags = []
    
    # Multiple applications from same IP
    multiple_apps = data.get('multiple_applications', 0)
    if multiple_apps >= 5:
        fraud_score += 0.4
        flags.append('multiple_applications_same_ip')
    elif multiple_apps >= 3:
        fraud_score += 0.2
        flags.append('several_applications_same_ip')
    
    # Unrealistic claim amount
    claim_amount = data.get('claim_amount', 0)
    policy_age_days = data.get('policy_age_days', 365)
    
    if claim_amount > 0:
        if claim_amount > 500000:
            fraud_score += 0.3
            flags.append('unusually_high_claim_amount')
        
        # Claim too soon after policy start
        if policy_age_days < 30 and claim_amount > 10000:
            fraud_score += 0.4
            flags.append('claim_shortly_after_policy_start')
    
    # High claim frequency
    claim_frequency = data.get('claim_frequency', 0)
    if claim_frequency >= 5:
        fraud_score += 0.3
        flags.append('excessive_claim_frequency')
    elif claim_frequency >= 3:
        fraud_score += 0.15
        flags.append('high_claim_frequency')
    
    # Data inconsistencies
    if data.get('inconsistent_data', False):
        fraud_score += 0.25
        flags.append('data_inconsistencies_detected')
    
    # Round-number claims
    if claim_amount > 0 and claim_amount % 1000 == 0 and claim_amount >= 5000:
        fraud_score += 0.1
        flags.append('suspicious_round_number_claim')
    
    # Application velocity
    application_velocity = data.get('applications_last_24h', 0)
    if application_velocity >= 10:
        fraud_score += 0.5
        flags.append('suspicious_application_velocity')
    
    # Ensure fraud score is between 0 and 1
    fraud_score = min(1.0, fraud_score)
    
    # Determine risk level
    if fraud_score >= 0.7:
        fraud_risk_level = 'CRITICAL'
        recommended_action = 'BLOCK_AND_INVESTIGATE'
    elif fraud_score >= 0.5:
        fraud_risk_level = 'HIGH'
        recommended_action = 'MANUAL_REVIEW_REQUIRED'
    elif fraud_score >= 0.3:
        fraud_risk_level = 'MEDIUM'
        recommended_action = 'ENHANCED_VERIFICATION'
    else:
        fraud_risk_level = 'LOW'
        recommended_action = 'PROCEED_NORMALLY'
    
    return {
        'fraud_risk_level': fraud_risk_level,
        'fraud_score': round(fraud_score, 2),
        'flags': flags,
        'recommended_action': recommended_action,
        'requires_investigation': fraud_score >= 0.5
    }


# Export public interface
__all__ = [
    # New class-based API
    'AIAutomationController',
    'AutomationDecision',
    'FraudRisk',
    'AutomationMetrics',
    'get_automation_controller',
    # Backward compatible function-based API
    'auto_quote',
    'auto_underwrite',
    'auto_process_claim',
    'detect_fraud'
]
