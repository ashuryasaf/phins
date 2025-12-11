"""
Customer Service Agent for PHINS

Provides customer-facing service operations: inquiry handling, correspondence,
upsell suggestions, interaction logging, and human escalation. Integrates with
NotificationManager and DivisionalReporter from `underwriting_assistant.py`.
"""
from typing import List, Dict, Any, Optional
from datetime import datetime

from underwriting_assistant import NotificationManager, DivisionalReporter
from customer_validation import CustomerValidationService, Customer


class CustomerServiceAgent:
    """Agent focused on client service, correspondence and upsales.

    Basic responsibilities:
    - Handle customer inquiries and send acknowledgements
    - Send templated correspondence (email/SMS/portal)
    - Suggest relevant upsell offers using simple rule engine
    - Log customer interactions for audit and follow-up
    - Escalate complex cases to human teams (generates a report)
    """

    def __init__(
        self,
        agent_id: str,
        notification_mgr: Optional[NotificationManager] = None,
        reporter: Optional[DivisionalReporter] = None,
        customer_service: Optional[CustomerValidationService] = None,
    ):
        self.agent_id = agent_id
        self.notification_mgr = notification_mgr or NotificationManager()
        self.reporter = reporter or DivisionalReporter()
        self.customer_service = customer_service or CustomerValidationService()
        self.interactions: List[Dict[str, Any]] = []

        # Ensure service templates exist
        self._ensure_templates()

    def _ensure_templates(self) -> None:
        """Add or update correspondence templates used by the service agent."""
        nm = self.notification_mgr
        nm.templates.setdefault("service_ack", nm.templates.get("service_ack") or nm.templates.get("uw_pending"))
        nm.templates.setdefault("service_followup", nm.templates.get("service_followup") or nm.templates.get("premium_allocation"))
        # Upsell template
        if "upsell_offer" not in nm.templates:
            nm.templates["upsell_offer"] = nm.templates.get("uw_approved")

    def handle_inquiry(self, customer_id: str, channel: str, message: str) -> Dict[str, Any]:
        """Handle a customer inquiry and send acknowledgement.

        Returns a short activity record.
        """
        customer = self.customer_service.get_customer_by_id(customer_id)
        if not customer:
            raise ValueError(f"Customer {customer_id} not found")

        interaction = {
            "timestamp": datetime.now().isoformat(),
            "customer_id": customer_id,
            "channel": channel,
            "message": message,
            "handled_by": self.agent_id,
        }
        self.log_interaction(interaction)

        # Send simple acknowledgement
        context = {"customer_name": customer.full_name, "message": "We received your inquiry."}
        recipient = customer.email or customer.phone or "unknown"
        delivery = self.notification_mgr.send_notification(
            customer_id=customer_id,
            recipient=recipient,
            template_name="service_ack",
            delivery_method=self.notification_mgr.templates.get("service_ack").delivery_method,
            context=context,
            signature_required=False,
        )

        return {"interaction": interaction, "acknowledgement": delivery}

    def send_correspondence(self, customer_id: str, template_name: str, context: Dict[str, Any]) -> Any:
        """Send templated correspondence via NotificationManager."""
        customer = self.customer_service.get_customer_by_id(customer_id)
        if not customer:
            raise ValueError(f"Customer {customer_id} not found")

        recipient = customer.email or customer.phone or "unknown"
        template = self.notification_mgr.templates.get(template_name)
        if not template:
            raise ValueError(f"Template {template_name} not found")

        return self.notification_mgr.send_notification(
            customer_id=customer_id,
            recipient=recipient,
            template_name=template_name,
            delivery_method=template.delivery_method,
            context=context,
            signature_required=template.signature_required,
        )

    def suggest_upsell(self, customer: Customer) -> List[Dict[str, Any]]:
        """Return a list of simple upsell suggestions based on customer profile.

        This is a rule-based starter engine and meant to be replaced by an ML
        model or richer business rules later.
        """
        suggestions: List[Dict[str, Any]] = []

        # Low-risk customers: offer investment or premium-saver add-ons
        risk = customer.health_assessment.health_risk_score()
        age = customer.age

        if risk < 0.25 and age < 45:
            suggestions.append({
                "offer": "Premium Saver Plus",
                "reason": "Low health risk and younger age — attractive for investment products",
                "estimated_uplift_pct": 6.0,
            })

        # Household upsell: family add-on
        # If the customer has a household in the validation service, promote family cover
        household = self.customer_service.households.get(f"HH_{customer.customer_id}")
        if household and len(household.family_members) > 0:
            suggestions.append({
                "offer": "Family Coverage Bundle",
                "reason": f"Household with {len(household.family_members)} members — bundle discount",
                "estimated_uplift_pct": 12.0,
            })

        # Document-driven upsell: encourage premium allocation (savings) add-ons
        # If identification is valid and customer has email, suggest digital investments
        if customer.identification.is_valid() and customer.email:
            suggestions.append({
                "offer": "Investment Booster",
                "reason": "Verified identity and active contact — good candidate for investment add-ons",
                "estimated_uplift_pct": 4.0,
            })

        # De-duplicate offers by offer name
        seen = set()
        deduped: List[Dict[str, Any]] = []
        for s in suggestions:
            if s["offer"] in seen:
                continue
            seen.add(s["offer"])
            deduped.append(s)

        return deduped

    def log_interaction(self, interaction: Dict[str, Any]) -> None:
        """Append an interaction record for auditing and follow-up."""
        self.interactions.append(interaction)

    def escalate_to_human(self, customer_id: str, reason: str, assigned_team: str = "Service Team") -> Dict[str, Any]:
        """Create an escalation report for human follow-up and return it."""
        customer = self.customer_service.get_customer_by_id(customer_id)
        report_context = {
            "customer_id": customer_id,
            "customer_name": customer.full_name if customer else "Unknown",
            "reason": reason,
            "timestamp": datetime.now().isoformat(),
            "assigned_team": assigned_team,
        }

        # Use DivisionalReporter to create a simple report object
        report = {
            "report_id": f"ESC_{customer_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "report_type": "Service Escalation",
            "report_date": datetime.now().isoformat(),
            "assigned_to": assigned_team,
            "details": report_context,
        }

        self.reporter.reports.append(report)
        return report
