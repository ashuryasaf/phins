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

from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import logging
import random

# Rules live in services/automation/* (design §B2); this module orchestrates
# them with metrics, the append-only decision log, per-segment thresholds and
# the model registry, and keeps every historically importable name.
from services.automation.types import AutomationDecision, FraudRisk, AutomationMetrics
from services.automation import billing_schedule, claims_gate, fraud as fraud_rules, quoting
from services.automation import underwriting_gate

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

# Observation-only instrumentation (services/agent_metrics.py). Guarded so the
# controller keeps working if imported outside the repo root.
try:
    from services.agent_metrics import instrument_agent
except Exception:  # pragma: no cover - defensive import guard
    def instrument_agent(*_args, **_kwargs):
        return lambda fn: fn


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
        seg = segment_key(application_data) if _AI_SUPPORT else 'global'
        if not self._thresholds:
            return self.auto_approve_threshold, self.auto_reject_threshold, seg
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
    
    @instrument_agent('ai_automation_controller', decision_key='decision')
    def generate_auto_quote(self, customer_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Automatically generate insurance quote using ML models.
        
        Args:
            customer_data: Customer information (age, health, occupation, etc.)
            
        Returns:
            Quote with premium, coverage, and confidence score
        """
        computed = quoting.compute_quote(customer_data)
        coverage_amount = computed['coverage_amount']
        confidence = computed['confidence_score']

        quote = {
            'quote_id': f"QT-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}",
            'annual_premium': computed['annual_premium'],
            'monthly_premium': computed['monthly_premium'],
            'coverage_amount': coverage_amount,
            'confidence_score': confidence,
            'risk_factors': computed['risk_factors'],
            'generated_at': datetime.now().isoformat(),
            'valid_until': (datetime.now().replace(hour=23, minute=59, second=59)).isoformat()
        }
        # AI-1: log the quote decision (advisory record; no money movement).
        self._log_decision(
            decision_type='quote',
            inputs=customer_data,
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
        return quoting.quote_confidence(customer_data)

    # =========================================================================
    # AUTOMATED UNDERWRITING
    # =========================================================================
    
    @instrument_agent('ai_automation_controller', decision_fn=lambda r: r[0])
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

        decision, details = underwriting_gate.gate(risk_score, fraud_risk, approve_threshold, reject_threshold)
        fraud_hold = decision == AutomationDecision.HUMAN_REVIEW and details.get('requires_investigation') is True
        if fraud_hold:
            self.metrics.fraud_detected += 1
            self.metrics.human_review += 1
        elif decision == AutomationDecision.AUTO_APPROVE:
            self.metrics.auto_approved += 1
        elif decision == AutomationDecision.AUTO_REJECT:
            self.metrics.auto_rejected += 1
        else:
            self.metrics.human_review += 1
        band = underwriting_gate.confidence_band(risk_score, approve_threshold, reject_threshold,
                                                 fraud_hold=fraud_hold)

        # AI-1: persist the decision (append-only, advisory; never moves money).
        decision_id = self._log_decision(
            decision_type='underwrite',
            inputs=application_data,
            output={
                'decision': decision.value,
                'risk_score': risk_score,
                'approve_threshold': approve_threshold,
                'reject_threshold': reject_threshold,
                'fraud_risk': fraud_risk.value,
                'model_score': model_score,
                'confidence_band': band['band'],
                'threshold_margin': band['margin'],
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
        details['confidence_band'] = band['band']
        details['threshold_margin'] = band['margin']
        return (decision, details)
    
    def _assess_risk(self, application_data: Dict[str, Any]) -> float:
        """Rule risk score (0.0 to 1.0, higher is better)."""
        return underwriting_gate.assess_risk(application_data)

    def _detect_fraud(self, application_data: Dict[str, Any]) -> FraudRisk:
        """Detect potential fraud in application."""
        return fraud_rules.application_fraud_risk(application_data)

    # =========================================================================
    # SMART CLAIMS PROCESSING
    # =========================================================================
    
    @instrument_agent('ai_automation_controller', decision_fn=lambda r: r[0])
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
        decision, details, fraud_risk = claims_gate.gate(claim_data)

        # AI-1: persist the claim decision (append-only; advisory, never posts).
        decision_id = self._log_decision(
            decision_type='claim',
            inputs=claim_data,
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
        return fraud_rules.claim_fraud_risk(claim_data)

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
        
        # One due-date path per frequency (D3 fix); keeps the historical
        # datetime shape (due date at generation time-of-day).
        now = datetime.now()
        due_date = datetime.combine(billing_schedule.invoice_due_date(billing_frequency, now), now.time())

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


# ---------------------------------------------------------------------------
# Agent runtime registration (discovery + health only; no behaviour change).
# The controller is a library consumed in-process (no HTTP route of its own),
# so ``api.method`` is ``LIB``.
# ---------------------------------------------------------------------------
def _controller_health() -> Dict[str, Any]:
    """Read-only probe: never instantiates the controller."""
    instance = _controller_instance
    if instance is None:
        return {'status': 'ok', 'initialized': False, 'ai_support': _AI_SUPPORT}
    return {
        'status': 'ok',
        'initialized': True,
        'ai_support': _AI_SUPPORT,
        'auto_approve_threshold': getattr(instance, 'auto_approve_threshold', None),
        'auto_reject_threshold': getattr(instance, 'auto_reject_threshold', None),
    }


try:
    from services.agent_runtime import AgentDescriptor as _AgentDescriptor, register as _register_agent
    _register_agent(_AgentDescriptor(
        id='ai_automation_controller',
        name='AI Automation Controller',
        version='1.0.0',
        module=__name__,
        description=(
            'Rule-based orchestrator for auto-quotes, automated underwriting '
            'gates, smart claims processing, and fraud heuristics. Rules are '
            'authoritative; a registered model may inform a score but never decides.'
        ),
        entry_url='/admin.html',
        api={'method': 'LIB', 'path': 'ai_automation_controller.get_automation_controller'},
        roles=('admin', 'underwriter', 'claims_adjuster'),
        deterministic=True,
        sample_prompts=(
            'Generate an auto-quote for a 35-year-old non-smoker',
            'Should this application be auto-approved?',
        ),
    ), health_fn=_controller_health)
except Exception as _reg_exc:  # pragma: no cover
    logger.warning("automation controller agent registration skipped: %s", _reg_exc)

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
        'recommended_premium_adjustment': round((1.0 - risk_score) * 50, 2),
        'segment': details.get('segment'),
        'confidence_band': details.get('confidence_band'),
        'threshold_margin': details.get('threshold_margin'),
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
    return fraud_rules.activity_fraud_report(data)


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
