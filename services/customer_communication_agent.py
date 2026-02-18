"""
PHINS Customer Communication Agent
==================================

High-level customer communication agent focused on:
- Branded welcome communication
- Diversified executive report generation
- Multi-channel delivery (email + WhatsApp)
- Optional OTP-gated delivery for sensitive notifications
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.notification_service import (
    NotificationChannel,
    NotificationPriority,
    NotificationRequest,
    VerificationType,
    create_notification_service,
)


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert arbitrary values to float safely."""
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return float(int(value))
        return float(str(value).replace(",", "").strip())
    except Exception:
        return default


def _status(value: Any) -> str:
    """Normalize status-like values for comparisons."""
    if value is None:
        return ""
    return str(value).strip().lower()


@dataclass
class ExecutiveReport:
    """Structured executive summary used by welcome communication."""

    customer_id: str
    generated_at: str
    total_policies: int
    active_policies: int
    policy_mix: Dict[str, int]
    total_coverage: float
    total_annual_premium: float
    total_monthly_premium: float
    outstanding_bills: int
    overdue_bills: int
    outstanding_amount: float
    paid_amount: float
    accounts_count: int
    total_account_value: float
    communities_count: int
    diversification_index: float
    highlights: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "generated_at": self.generated_at,
            "total_policies": self.total_policies,
            "active_policies": self.active_policies,
            "policy_mix": self.policy_mix,
            "total_coverage": self.total_coverage,
            "total_annual_premium": self.total_annual_premium,
            "total_monthly_premium": self.total_monthly_premium,
            "outstanding_bills": self.outstanding_bills,
            "overdue_bills": self.overdue_bills,
            "outstanding_amount": self.outstanding_amount,
            "paid_amount": self.paid_amount,
            "accounts_count": self.accounts_count,
            "total_account_value": self.total_account_value,
            "communities_count": self.communities_count,
            "diversification_index": self.diversification_index,
            "highlights": self.highlights,
        }


class CustomerCommunicationAgent:
    """
    Communication agent connecting PHINS to customers.

    The agent packages policy, billing, and account data into a branded welcome
    report and sends it using the core notification service.
    """

    def __init__(self, notification_service=None):
        self._notification_service = notification_service or create_notification_service(use_mock=True)

    def build_diversified_executive_report(
        self,
        customer_id: str,
        policies: Optional[List[Dict[str, Any]]] = None,
        bills: Optional[List[Dict[str, Any]]] = None,
        accounts: Optional[List[Dict[str, Any]]] = None,
        communities: Optional[List[Dict[str, Any]]] = None,
    ) -> ExecutiveReport:
        """Build an executive report from customer portfolio and billing data."""
        policies = policies or []
        bills = bills or []
        accounts = accounts or []
        communities = communities or []

        policy_mix: Dict[str, int] = {}
        active_policies = 0
        total_coverage = 0.0
        total_annual_premium = 0.0
        total_monthly_premium = 0.0

        for policy in policies:
            policy_type = str(policy.get("type") or policy.get("policy_type") or "other").lower()
            policy_mix[policy_type] = policy_mix.get(policy_type, 0) + 1

            status = _status(policy.get("status"))
            if status in {"active", "approved", "paid"}:
                active_policies += 1

            total_coverage += _safe_float(policy.get("coverage_amount"))
            total_annual_premium += _safe_float(policy.get("annual_premium"))
            monthly_premium = _safe_float(policy.get("monthly_premium"))
            if monthly_premium <= 0:
                monthly_premium = _safe_float(policy.get("annual_premium")) / 12.0
            total_monthly_premium += monthly_premium

        outstanding_bills = 0
        overdue_bills = 0
        outstanding_amount = 0.0
        paid_amount = 0.0
        now = datetime.now(timezone.utc)

        for bill in bills:
            status = _status(bill.get("status"))
            amount = _safe_float(bill.get("amount_due"))
            if amount <= 0:
                amount = _safe_float(bill.get("amount"))
            amount_paid = _safe_float(bill.get("amount_paid"))

            if status in {"paid", "closed"}:
                paid_amount += amount_paid if amount_paid > 0 else amount
                continue

            if status in {"outstanding", "pending", "partial", "overdue"}:
                outstanding_bills += 1
                balance = amount - amount_paid
                if balance <= 0:
                    balance = amount
                outstanding_amount += max(balance, 0.0)

                due_raw = bill.get("due_date")
                if due_raw:
                    try:
                        due = datetime.fromisoformat(str(due_raw).replace("Z", "+00:00"))
                        if due.tzinfo is None:
                            due = due.replace(tzinfo=timezone.utc)
                        if due < now:
                            overdue_bills += 1
                    except Exception:
                        pass

        accounts_count = 0
        total_account_value = 0.0
        non_zero_account_buckets = 0
        for account in accounts:
            value = _safe_float(account.get("value", account.get("balance", account.get("amount", 0.0))))
            total_account_value += value
            accounts_count += 1
            if value > 0:
                non_zero_account_buckets += 1

        policy_diversity = min(len(policy_mix) / 4.0, 1.0)
        account_diversity = min(max(non_zero_account_buckets, len(accounts)) / 4.0, 1.0) if accounts else 0.0
        billing_signal = min(outstanding_amount / max(total_monthly_premium * 3.0, 1.0), 1.0)
        billing_health = 1.0 - billing_signal
        diversification_index = round(
            (policy_diversity * 0.50 + account_diversity * 0.30 + billing_health * 0.20) * 100.0,
            2
        )

        highlights = [
            f"{active_policies}/{len(policies)} policies are currently active",
            f"Total portfolio coverage: ${total_coverage:,.2f}",
            f"Outstanding billing: ${outstanding_amount:,.2f} across {outstanding_bills} bill(s)",
            f"Tracked account value: ${total_account_value:,.2f}",
        ]
        if communities:
            highlights.append(f"Connected communities: {len(communities)}")
        if overdue_bills > 0:
            highlights.append(f"Action needed: {overdue_bills} bill(s) are past due")

        return ExecutiveReport(
            customer_id=customer_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            total_policies=len(policies),
            active_policies=active_policies,
            policy_mix=policy_mix,
            total_coverage=round(total_coverage, 2),
            total_annual_premium=round(total_annual_premium, 2),
            total_monthly_premium=round(total_monthly_premium, 2),
            outstanding_bills=outstanding_bills,
            overdue_bills=overdue_bills,
            outstanding_amount=round(outstanding_amount, 2),
            paid_amount=round(paid_amount, 2),
            accounts_count=accounts_count,
            total_account_value=round(total_account_value, 2),
            communities_count=len(communities),
            diversification_index=diversification_index,
            highlights=highlights,
        )

    def render_executive_report_text(self, customer_name: str, report: ExecutiveReport) -> str:
        """Render plain text executive summary for email and logs."""
        lines = [
            f"Welcome to PHINS, {customer_name}.",
            "",
            "Your executive portfolio summary:",
            f"- Policies: {report.active_policies}/{report.total_policies} active",
            f"- Coverage: ${report.total_coverage:,.2f}",
            f"- Premium (monthly): ${report.total_monthly_premium:,.2f}",
            f"- Outstanding bills: {report.outstanding_bills} (${report.outstanding_amount:,.2f})",
            f"- Accounts tracked: {report.accounts_count} (${report.total_account_value:,.2f})",
            f"- Communities: {report.communities_count}",
            f"- Diversification index: {report.diversification_index:.2f}/100",
            "",
            "Highlights:",
        ]
        lines.extend([f"  * {item}" for item in report.highlights])
        lines.append("")
        lines.append("Thank you for choosing PHINS.")
        return "\n".join(lines)

    def render_executive_report_html(self, customer_name: str, report: ExecutiveReport, login_url: str) -> str:
        """Render branded HTML report for sophisticated onboarding communication."""
        # Escape user-controlled values to prevent HTML injection
        safe_customer_name = html.escape(str(customer_name))
        safe_login_url = html.escape(str(login_url))
        
        policy_mix_html = "".join(
            f"<li><strong>{html.escape(str(kind))}</strong>: {count}</li>"
            for kind, count in sorted(report.policy_mix.items(), key=lambda item: item[0])
        ) or "<li><strong>n/a</strong>: 0</li>"
        highlights_html = "".join(f"<li>{html.escape(str(item))}</li>" for item in report.highlights)

        return f"""
<html>
<body style="margin:0;background:#f4f7fd;font-family:Arial,sans-serif;color:#102342;">
  <div style="max-width:860px;margin:24px auto;background:#ffffff;border:1px solid #dae4f7;border-radius:16px;overflow:hidden;">
    <div style="padding:30px;background:linear-gradient(120deg,#0b1730,#2455b5);color:#ffffff;">
      <div style="font-size:12px;letter-spacing:2px;opacity:0.8;">PHINS CUSTOMER EXECUTIVE BRIEF</div>
      <h1 style="margin:8px 0 0 0;font-size:28px;">Welcome, {safe_customer_name}</h1>
      <p style="margin:8px 0 0 0;opacity:0.9;">Branded portfolio intelligence for your first PHINS session.</p>
    </div>
    <div style="padding:26px;">
      <div style="display:flex;flex-wrap:wrap;gap:12px;">
        <div style="flex:1 1 250px;background:#f7f9ff;border:1px solid #dbe5fb;border-radius:10px;padding:14px;">
          <div style="font-size:12px;color:#5f6d85;">Active policies</div>
          <div style="font-size:24px;font-weight:700;">{report.active_policies}/{report.total_policies}</div>
        </div>
        <div style="flex:1 1 250px;background:#f7f9ff;border:1px solid #dbe5fb;border-radius:10px;padding:14px;">
          <div style="font-size:12px;color:#5f6d85;">Total coverage</div>
          <div style="font-size:24px;font-weight:700;">${report.total_coverage:,.2f}</div>
        </div>
        <div style="flex:1 1 250px;background:#f7f9ff;border:1px solid #dbe5fb;border-radius:10px;padding:14px;">
          <div style="font-size:12px;color:#5f6d85;">Outstanding billing</div>
          <div style="font-size:24px;font-weight:700;">${report.outstanding_amount:,.2f}</div>
        </div>
      </div>
      <div style="margin-top:18px;display:flex;gap:20px;flex-wrap:wrap;">
        <div style="flex:1 1 260px;">
          <h3 style="margin:0 0 8px 0;color:#17386c;">Portfolio mix</h3>
          <ul style="margin:0 0 0 18px;padding:0;line-height:1.6;">{policy_mix_html}</ul>
        </div>
        <div style="flex:2 1 360px;">
          <h3 style="margin:0 0 8px 0;color:#17386c;">Highlights</h3>
          <ul style="margin:0 0 0 18px;padding:0;line-height:1.6;">{highlights_html}</ul>
        </div>
      </div>
      <div style="margin-top:20px;padding:14px;background:#eef4ff;border-radius:8px;border:1px solid #d6e4ff;">
        Diversification index: <strong>{report.diversification_index:.2f}/100</strong><br/>
        Accounts tracked: <strong>{report.accounts_count}</strong> (${report.total_account_value:,.2f})<br/>
        Communities connected: <strong>{report.communities_count}</strong>
      </div>
      <p style="margin-top:18px;">Open your dashboard: <a href="{safe_login_url}">{safe_login_url}</a></p>
    </div>
    <div style="padding:12px 26px;background:#0f1a2e;color:#94a6c7;font-size:12px;">
      PHINS | Branded Advanced Insurance Experience
    </div>
  </div>
</body>
</html>
""".strip()

    def send_welcome_package(
        self,
        *,
        customer_id: str,
        customer_name: str,
        email: str,
        policies: Optional[List[Dict[str, Any]]] = None,
        bills: Optional[List[Dict[str, Any]]] = None,
        accounts: Optional[List[Dict[str, Any]]] = None,
        communities: Optional[List[Dict[str, Any]]] = None,
        whatsapp_phone: Optional[str] = None,
        login_url: str = "/login.html",
        require_otp_validation: bool = False,
        otp_code: Optional[str] = None,
        otp_identifier: Optional[str] = None,
        otp_verification_type: VerificationType = VerificationType.ACCOUNT_ACTIVATION,
    ) -> Dict[str, Any]:
        """Send a branded welcome communication bundle with an executive report."""
        if require_otp_validation:
            otp_code_value = str(otp_code or "").strip()
            if not otp_code_value:
                return {
                    "success": False,
                    "error": "otp_code is required when require_otp_validation is true",
                    "code": "OTP_CODE_REQUIRED",
                }

            # Validate once at bundle-level so a single OTP can authorize the
            # paired welcome package (email + optional WhatsApp).
            otp_identifier_value = str(otp_identifier or whatsapp_phone or email).strip()
            if not otp_identifier_value:
                return {
                    "success": False,
                    "error": "otp_identifier is required when require_otp_validation is true",
                    "code": "OTP_IDENTIFIER_REQUIRED",
                }

            otp_verification = self._notification_service.verify_otp(
                identifier=otp_identifier_value,
                code=otp_code_value,
                verification_type=otp_verification_type,
            )
            if not otp_verification.success:
                return {
                    "success": False,
                    "error": otp_verification.error_message or "OTP verification failed",
                    "code": otp_verification.error_code or "OTP_VALIDATION_FAILED",
                }

        report = self.build_diversified_executive_report(
            customer_id=customer_id,
            policies=policies,
            bills=bills,
            accounts=accounts,
            communities=communities,
        )
        report_dict = report.to_dict()

        common_metadata: Dict[str, Any] = {
            "agent": "customer_communication_agent",
            "executive_report": report_dict,
            "brand_style": "advanced_sophisticated",
        }
        if require_otp_validation:
            common_metadata.update(
                {
                    "otp_validated": True,
                    "otp_identifier": otp_identifier or whatsapp_phone or email,
                    "otp_verification_type": otp_verification_type.value,
                }
            )

        text_body = self.render_executive_report_text(customer_name, report)
        html_body = self.render_executive_report_html(customer_name, report, login_url=login_url)

        email_request = NotificationRequest(
            channel=NotificationChannel.EMAIL,
            recipient=email,
            subject="Welcome to PHINS | Executive Portfolio Brief",
            content=text_body,
            html_content=html_body,
            priority=NotificationPriority.HIGH,
            customer_id=customer_id,
            metadata=common_metadata.copy(),
        )
        email_result = self._notification_service.send(email_request)

        whatsapp_result_dict: Optional[Dict[str, Any]] = None
        if whatsapp_phone:
            highlights = "; ".join(report.highlights[:3])
            whatsapp_message = (
                f"Welcome to PHINS, {customer_name}. "
                f"Executive summary: {report.active_policies}/{report.total_policies} policies active, "
                f"coverage ${report.total_coverage:,.2f}, outstanding ${report.outstanding_amount:,.2f}. "
                f"{highlights}"
            )
            whatsapp_metadata = common_metadata.copy()
            if require_otp_validation:
                # Use phone identifier for WhatsApp OTP verification when available.
                whatsapp_metadata["otp_identifier"] = otp_identifier or whatsapp_phone

            whatsapp_request = NotificationRequest(
                channel=NotificationChannel.WHATSAPP,
                recipient=whatsapp_phone,
                content=whatsapp_message,
                priority=NotificationPriority.HIGH,
                customer_id=customer_id,
                metadata=whatsapp_metadata,
            )
            whatsapp_result = self._notification_service.send(whatsapp_request)
            whatsapp_result_dict = whatsapp_result.to_dict()

        success = bool(email_result.success and (whatsapp_result_dict is None or whatsapp_result_dict.get("success")))
        return {
            "success": success,
            "customer_id": customer_id,
            "report": report_dict,
            "email": email_result.to_dict(),
            "whatsapp": whatsapp_result_dict,
        }


def get_customer_communication_agent(notification_service=None) -> CustomerCommunicationAgent:
    """Factory helper for customer communication agent."""
    return CustomerCommunicationAgent(notification_service=notification_service)

