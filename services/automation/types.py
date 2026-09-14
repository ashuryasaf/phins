"""Shared enums and metrics for the automation controller package."""

from dataclasses import dataclass
from enum import Enum


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


__all__ = ['AutomationDecision', 'FraudRisk', 'AutomationMetrics']
