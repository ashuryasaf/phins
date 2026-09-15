"""Automation controller rules, split by concern (design §B2).

``ai_automation_controller`` (repo root) keeps the orchestrating class,
singleton accessor and the function-based API; the pure rules live here so
each ladder can be unit-tested and golden-tested without the controller's
metrics, decision-log or model-registry collaborators:

- ``quoting``          premium multipliers and quote confidence
- ``underwriting_gate`` rule risk score, decision ladder, ``confidence_band``
- ``fraud``            application / claim / activity fraud heuristics
- ``claims_gate``      smart claims processing ladder
- ``billing_schedule`` invoice due dates (``next_quarter_start`` fixes D3)
- ``types``            ``AutomationDecision``, ``FraudRisk``, ``AutomationMetrics``
"""

from services.automation.types import AutomationDecision, AutomationMetrics, FraudRisk  # noqa: F401
from services.automation import billing_schedule, claims_gate, fraud, quoting, underwriting_gate  # noqa: F401

__all__ = [
    'AutomationDecision', 'AutomationMetrics', 'FraudRisk',
    'billing_schedule', 'claims_gate', 'fraud', 'quoting', 'underwriting_gate',
]
