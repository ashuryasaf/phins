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
import random


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
        self.auto_approve_threshold = 0.85  # 85% confidence for auto-approval
        self.auto_reject_threshold = 0.15   # Below 15% confidence = auto-reject
        
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
        
        return {
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
        
        # Risk assessment
        risk_score = self._assess_risk(application_data)
        fraud_risk = self._detect_fraud(application_data) if self.fraud_detection_enabled else FraudRisk.LOW
        
        # Check for fraud first
        if fraud_risk in [FraudRisk.HIGH, FraudRisk.CRITICAL]:
            self.metrics.fraud_detected += 1
            self.metrics.human_review += 1
            return (
                AutomationDecision.HUMAN_REVIEW,
                {
                    'reason': 'Potential fraud detected',
                    'fraud_risk': fraud_risk.value,
                    'requires_investigation': True
                }
            )
        
        # Auto-decision based on risk score
        if risk_score >= self.auto_approve_threshold:
            self.metrics.auto_approved += 1
            return (
                AutomationDecision.AUTO_APPROVE,
                {
                    'risk_score': risk_score,
                    'premium_adjustment': 1.0,  # No adjustment
                    'conditions': []
                }
            )
        elif risk_score <= self.auto_reject_threshold:
            self.metrics.auto_rejected += 1
            return (
                AutomationDecision.AUTO_REJECT,
                {
                    'risk_score': risk_score,
                    'rejection_reason': 'Risk score too low for coverage'
                }
            )
        else:
            # Mid-range - needs human review
            self.metrics.human_review += 1
            return (
                AutomationDecision.HUMAN_REVIEW,
                {
                    'risk_score': risk_score,
                    'review_priority': 'medium' if risk_score > 0.5 else 'high',
                    'suggested_action': 'approve_with_conditions' if risk_score > 0.5 else 'request_medical_exam'
                }
            )
    
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
        
        # Auto-approve low-value straightforward claims
        if claim_amount < 1000 and claim_type in ['medical', 'dental']:
            return (
                AutomationDecision.AUTO_APPROVE,
                {
                    'approved_amount': claim_amount,
                    'reason': 'Low-value claim with standard documentation',
                    'payment_method': 'direct_deposit'
                }
            )
        
        # Check fraud risk
        fraud_risk = self._detect_claim_fraud(claim_data)
        if fraud_risk in [FraudRisk.HIGH, FraudRisk.CRITICAL]:
            return (
                AutomationDecision.HUMAN_REVIEW,
                {
                    'reason': 'Potential fraud detected in claim',
                    'fraud_risk': fraud_risk.value,
                    'requires_investigation': True
                }
            )
        
        # Check if claim exceeds coverage
        if claim_amount > policy_coverage:
            return (
                AutomationDecision.HUMAN_REVIEW,
                {
                    'reason': 'Claim exceeds policy coverage',
                    'suggested_action': 'approve_partial',
                    'max_approved_amount': policy_coverage
                }
            )
        
        # Complex claims need human review
        if claim_type in ['disability', 'death', 'major_medical']:
            return (
                AutomationDecision.HUMAN_REVIEW,
                {
                    'reason': 'Complex claim type requires adjuster review',
                    'priority': 'high'
                }
            )
        
        # Medium-value claims with complete documentation
        return (
            AutomationDecision.HUMAN_REVIEW,
            {
                'reason': 'Standard review required',
                'priority': 'normal',
                'suggested_action': 'approve',
                'suggested_amount': claim_amount
            }
        )
    
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


# Export public interface
__all__ = [
    'AIAutomationController',
    'AutomationDecision',
    'FraudRisk',
    'AutomationMetrics',
    'get_automation_controller'
]
