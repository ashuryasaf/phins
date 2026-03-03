"""
PHINS Marketing + Sales Agent Service
=====================================

Generates AI + BI campaign plans for:
- Insurance growth
- Investment growth
- Health wallet growth

The service focuses on practical campaign artifacts:
- Sales playbooks
- Story outlines
- Targeted article briefs
- AI video blueprints
- Social distribution plans

All generated plans include an HMAC signature for integrity verification.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


ALLOWED_VERTICALS = {"insurance", "investments", "health_wallet"}
ALLOWED_OBJECTIVES = {"growth", "retention", "cross_sell", "reactivation"}

SUPPORTED_NETWORKS = {
    "linkedin",
    "x",
    "facebook",
    "instagram",
    "youtube",
    "tiktok",
    "whatsapp",
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely coerce arbitrary values into float."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """Safely coerce arbitrary values into int."""
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _status(value: Any) -> str:
    """Normalize status strings for comparisons."""
    return str(value or "").strip().lower().replace(" ", "_")


class MarketingSalesAgentService:
    """AI + BI campaign generation service with signed payloads."""

    def __init__(self, secret_key: Optional[str] = None):
        self._secret_key = (
            secret_key
            or os.environ.get("PHINS_MARKETING_AGENT_SECRET")
            or os.environ.get("SESSION_SECRET_KEY")
            or "PHINS_MARKETING_AGENT_2026"
        )

    def _normalize_vertical(self, vertical: Optional[str]) -> str:
        value = str(vertical or "insurance").strip().lower()
        return value if value in ALLOWED_VERTICALS else "insurance"

    def _normalize_objective(self, objective: Optional[str]) -> str:
        value = str(objective or "growth").strip().lower()
        return value if value in ALLOWED_OBJECTIVES else "growth"

    def _normalize_networks(self, networks: Optional[List[str]]) -> List[str]:
        if not networks:
            return ["linkedin", "x", "facebook", "instagram", "youtube", "whatsapp"]
        cleaned: List[str] = []
        for value in networks:
            normalized = str(value or "").strip().lower()
            if normalized in SUPPORTED_NETWORKS and normalized not in cleaned:
                cleaned.append(normalized)
        return cleaned or ["linkedin", "x", "facebook", "instagram", "youtube", "whatsapp"]

    def _build_bi_signals(
        self,
        customers: Dict[str, Dict[str, Any]],
        policies: Dict[str, Dict[str, Any]],
        billing: Dict[str, Dict[str, Any]],
        claims: Dict[str, Dict[str, Any]],
        health_wallets: Dict[str, Dict[str, Any]],
        investment_accounts: Dict[str, Dict[str, Any]],
        transaction_ledger: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        total_customers = len(customers or {})
        total_policies = len(policies or {})
        active_policies = sum(1 for p in (policies or {}).values() if _status(p.get("status")) == "active")

        total_billed = 0.0
        total_collected = 0.0
        outstanding_bills = 0
        for bill in (billing or {}).values():
            amount_due = _safe_float(bill.get("amount_due", bill.get("amount", 0)))
            amount_paid = _safe_float(bill.get("amount_paid", 0))
            total_billed += max(amount_due, 0.0)
            total_collected += max(amount_paid, 0.0)
            if _status(bill.get("status")) != "paid":
                outstanding_bills += 1

        paid_claims = 0
        total_claims_amount = 0.0
        for claim in (claims or {}).values():
            status = _status(claim.get("status"))
            if status in {"paid", "approved"}:
                paid_claims += 1
            total_claims_amount += _safe_float(claim.get("approved_amount", claim.get("paid_amount", claim.get("claimed_amount", 0))))

        wallet_customers = len(health_wallets or {})
        wallet_total_balance = sum(_safe_float(w.get("balance", 0)) for w in (health_wallets or {}).values())

        investment_customers = len(investment_accounts or {})
        investment_total_balance = sum(_safe_float(a.get("balance", 0)) for a in (investment_accounts or {}).values())

        ledger_volume = sum(abs(_safe_float(tx.get("amount", 0))) for tx in (transaction_ledger or {}).values())

        customer_base = max(total_customers, 1)
        conversion_rate = round((active_policies / customer_base) * 100, 2)
        wallet_adoption_rate = round((wallet_customers / customer_base) * 100, 2)
        investment_adoption_rate = round((investment_customers / customer_base) * 100, 2)
        collection_rate = round((total_collected / max(total_billed, 1.0)) * 100, 2)

        return {
            "total_customers": total_customers,
            "total_policies": total_policies,
            "active_policies": active_policies,
            "conversion_rate_pct": conversion_rate,
            "billing": {
                "total_billed": round(total_billed, 2),
                "total_collected": round(total_collected, 2),
                "collection_rate_pct": collection_rate,
                "outstanding_bills": outstanding_bills,
            },
            "claims": {
                "paid_or_approved_count": paid_claims,
                "total_claims_amount": round(total_claims_amount, 2),
            },
            "health_wallet": {
                "active_wallets": wallet_customers,
                "adoption_rate_pct": wallet_adoption_rate,
                "total_balance": round(wallet_total_balance, 2),
            },
            "investments": {
                "active_accounts": investment_customers,
                "adoption_rate_pct": investment_adoption_rate,
                "total_balance": round(investment_total_balance, 2),
            },
            "ledger": {
                "transaction_count": len(transaction_ledger or {}),
                "volume": round(ledger_volume, 2),
            },
        }

    def _vertical_messaging(self, vertical: str) -> Dict[str, str]:
        if vertical == "investments":
            return {
                "value_prop": "Turn passive reserves into tax-smart, risk-aware growth outcomes.",
                "hero_angle": "From idle balances to measurable wealth momentum.",
                "cta": "Book a 15-minute portfolio acceleration review.",
            }
        if vertical == "health_wallet":
            return {
                "value_prop": "Make care spending predictable with proactive wallet funding and partner offers.",
                "hero_angle": "Prevent out-of-pocket shocks before they happen.",
                "cta": "Activate your wallet autopilot and preventive care bundle.",
            }
        return {
            "value_prop": "Protect families while improving affordability through data-driven insurance design.",
            "hero_angle": "Coverage confidence with transparent outcomes.",
            "cta": "Start a precision underwriting checkup today.",
        }

    def _build_sales_playbooks(
        self,
        vertical: str,
        objective: str,
        persona: str,
        bi_signals: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        collection_rate = _safe_float(bi_signals.get("billing", {}).get("collection_rate_pct", 0))
        wallet_adoption = _safe_float(bi_signals.get("health_wallet", {}).get("adoption_rate_pct", 0))
        investment_adoption = _safe_float(bi_signals.get("investments", {}).get("adoption_rate_pct", 0))

        return [
            {
                "playbook": "Lifecycle Trigger Ladder",
                "how_it_works": "Detect life events and launch a timed three-step message sequence: pain, proof, offer.",
                "script_hook": f"For {persona}, trigger personalized outreach within 24h of underwriting/billing events.",
                "kpi_target": "Lead-to-meeting conversion +18%",
            },
            {
                "playbook": "Trust-to-Upgrade Flywheel",
                "how_it_works": "Use claim transparency and payout reliability stories to upgrade policy tiers.",
                "script_hook": "Publish anonymized outcomes and route best-fit upsell within 48h.",
                "kpi_target": "Average premium per customer +12%",
            },
            {
                "playbook": "Wallet First, Coverage Second",
                "how_it_works": "Offer health wallet activation before full policy expansion to reduce adoption friction.",
                "script_hook": f"Current wallet adoption is {wallet_adoption:.1f}%; prioritize non-wallet cohorts.",
                "kpi_target": "Wallet adoption +20%",
            },
            {
                "playbook": "Investment Parallel Offer",
                "how_it_works": "Attach investment nudges to policy and wallet milestones with explicit risk framing.",
                "script_hook": f"Current investment adoption is {investment_adoption:.1f}%; run advisor co-sell tracks.",
                "kpi_target": "Investment account activation +10%",
            },
            {
                "playbook": "Collection Recovery Narratives",
                "how_it_works": "Convert outstanding balances using empathetic scripts + split-payment options.",
                "script_hook": f"Collection rate baseline is {collection_rate:.1f}%; launch recovery sequence by risk bucket.",
                "kpi_target": "Collection rate +8%",
            },
            {
                "playbook": "Objective-Specific Closing Motion",
                "how_it_works": "Mirror closing language to objective mode: growth, retention, cross-sell, or reactivation.",
                "script_hook": f"Objective is {objective}; use dedicated objection handling matrix.",
                "kpi_target": "Close rate +15%",
            },
        ]

    def _build_story_outlines(self, vertical: str, persona: str, region: str) -> List[Dict[str, Any]]:
        vertical_label = vertical.replace("_", " ").title()
        return [
            {
                "title": f"{vertical_label} Story 1: The 90-Day Confidence Arc",
                "persona": persona,
                "outline": "Problem snapshot -> first measurable win -> long-term confidence loop.",
                "distribution": "LinkedIn carousel + YouTube short + sales email follow-up",
            },
            {
                "title": f"{vertical_label} Story 2: From Chaos to Control in {region.title()}",
                "persona": persona,
                "outline": "Unpredictable costs -> AI guidance -> disciplined allocation -> positive outcome.",
                "distribution": "Blog long-form + podcast snippet + webinar intro",
            },
            {
                "title": f"{vertical_label} Story 3: Advisor + AI Co-Pilot",
                "persona": persona,
                "outline": "Human advisor empathy paired with BI signal precision for better decisions.",
                "distribution": "Case-study PDF + WhatsApp summary + X thread",
            },
        ]

    def _build_article_briefs(self, vertical: str, objective: str, persona: str) -> List[Dict[str, Any]]:
        return [
            {
                "title": f"{vertical.replace('_', ' ').title()} Growth Blueprint for {persona}",
                "angle": "Data-backed playbook with measurable milestones and risk controls.",
                "seo_focus": [vertical, objective, "ai insurance", "bi analytics"],
                "cta": "Schedule a strategic planning call",
            },
            {
                "title": "7 High-Conversion Scripts Top Insurance Teams Use",
                "angle": "Actionable scripts mapped to buyer maturity stages and objections.",
                "seo_focus": ["insurance sales scripts", "conversion playbook", "sales enablement"],
                "cta": "Download script deck",
            },
            {
                "title": "How AI + BI Reduce Customer Acquisition Waste",
                "angle": "Attribution model, audience pruning, and channel-level ROI control.",
                "seo_focus": ["marketing attribution", "insurance ai", "bi dashboard"],
                "cta": "Open the campaign diagnostics dashboard",
            },
            {
                "title": "Health Wallet + Investment Bundling Without Compliance Drift",
                "angle": "Cross-sell architecture with transparent disclosure and consent checkpoints.",
                "seo_focus": ["health wallet", "investment cross sell", "compliance marketing"],
                "cta": "Activate bundled campaign mode",
            },
        ]

    def _build_video_blueprints(self, vertical: str, persona: str) -> List[Dict[str, Any]]:
        vertical_label = vertical.replace("_", " ").title()
        return [
            {
                "title": f"{vertical_label} AI Explainer (45s)",
                "format": "Vertical short video",
                "storyboard": [
                    "Hook: one painful customer scenario",
                    "Reveal: PHINS AI+BI recommendation moment",
                    "Outcome: quantified improvement",
                    "CTA: book advisor call",
                ],
                "voiceover_style": "Confident, plain-language, evidence-based",
            },
            {
                "title": f"{persona.title()} Testimonial Narrative (60s)",
                "format": "Interview + motion graphics",
                "storyboard": [
                    "Before state and friction",
                    "Onboarding and guidance",
                    "Results in premium/wallet/investment metrics",
                    "CTA for matching profile",
                ],
                "voiceover_style": "Human, empathetic, trustworthy",
            },
            {
                "title": "Advisor Playbook Teaser (30s)",
                "format": "Social ad cutdown",
                "storyboard": [
                    "Fast montage of insights dashboard",
                    "Three bullet outcomes",
                    "Offer and urgency trigger",
                ],
                "voiceover_style": "High-energy sales enablement",
            },
        ]

    def _build_social_plan(
        self,
        networks: List[str],
        objective: str,
        campaign_id: str,
    ) -> List[Dict[str, Any]]:
        network_styles = {
            "linkedin": ("Thought-leadership post + carousel", "3 posts/week"),
            "x": ("Thread + proof-point snippets", "5 posts/week"),
            "facebook": ("Community story + retargeting ad", "4 posts/week"),
            "instagram": ("Reels + story polls", "6 stories/week"),
            "youtube": ("Educational short + testimonial", "2 videos/week"),
            "tiktok": ("Explainer clips + hooks", "4 videos/week"),
            "whatsapp": ("Advisor broadcast + micro-brief", "2 campaigns/week"),
        }
        result: List[Dict[str, Any]] = []
        for network in networks:
            format_name, cadence = network_styles.get(network, ("Campaign post", "2 posts/week"))
            result.append(
                {
                    "network": network,
                    "format": format_name,
                    "cadence": cadence,
                    "objective_alignment": objective,
                    "tracking_tag": f"{campaign_id}:{network}",
                }
            )
        return result

    def _campaign_payload_signature(self, payload: Dict[str, Any]) -> str:
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hmac.new(self._secret_key.encode("utf-8"), serialized.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify_campaign_payload(self, payload: Dict[str, Any], signature: str) -> bool:
        expected = self._campaign_payload_signature(payload)
        return hmac.compare_digest(expected, str(signature or ""))

    def generate_campaign(
        self,
        *,
        customers: Dict[str, Dict[str, Any]],
        policies: Dict[str, Dict[str, Any]],
        billing: Dict[str, Dict[str, Any]],
        claims: Dict[str, Dict[str, Any]],
        health_wallets: Dict[str, Dict[str, Any]],
        investment_accounts: Dict[str, Dict[str, Any]],
        transaction_ledger: Dict[str, Dict[str, Any]],
        vertical: str,
        objective: str,
        persona: str,
        region: str,
        budget_tier: str,
        social_networks: Optional[List[str]],
        generated_by: str,
    ) -> Dict[str, Any]:
        normalized_vertical = self._normalize_vertical(vertical)
        normalized_objective = self._normalize_objective(objective)
        normalized_networks = self._normalize_networks(social_networks)
        generated_at = datetime.now(timezone.utc).isoformat()
        campaign_id = f"MKT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        bi_signals = self._build_bi_signals(
            customers=customers,
            policies=policies,
            billing=billing,
            claims=claims,
            health_wallets=health_wallets,
            investment_accounts=investment_accounts,
            transaction_ledger=transaction_ledger,
        )
        messaging = self._vertical_messaging(normalized_vertical)

        payload = {
            "campaign_id": campaign_id,
            "generated_at": generated_at,
            "generated_by": generated_by or "admin",
            "scope": {
                "vertical": normalized_vertical,
                "objective": normalized_objective,
                "persona": str(persona or "families").strip().lower(),
                "region": str(region or "global").strip().lower(),
                "budget_tier": str(budget_tier or "balanced").strip().lower(),
            },
            "value_messaging": messaging,
            "bi_signals": bi_signals,
            "sales_playbooks": self._build_sales_playbooks(
                normalized_vertical,
                normalized_objective,
                str(persona or "families").strip().lower(),
                bi_signals,
            ),
            "story_outlines": self._build_story_outlines(
                normalized_vertical,
                str(persona or "families").strip().lower(),
                str(region or "global").strip().lower(),
            ),
            "targeted_articles": self._build_article_briefs(
                normalized_vertical,
                normalized_objective,
                str(persona or "families").strip().lower(),
            ),
            "ai_video_blueprints": self._build_video_blueprints(
                normalized_vertical,
                str(persona or "families").strip().lower(),
            ),
            "social_network_plan": self._build_social_plan(
                normalized_networks,
                normalized_objective,
                campaign_id,
            ),
            "funnel_orchestration": {
                "awareness": "Story-led social + high-intent article SEO",
                "consideration": "Advisor webinar + interactive calculator + targeted follow-up",
                "conversion": "Risk-adjusted offer matrix + objection playbook + urgency windows",
                "retention": "Milestone messaging + wallet/investment expansion offers",
            },
            "compliance_guardrails": [
                "No guaranteed return claims in investment communication.",
                "Every campaign artifact must include eligibility and disclosure language.",
                "Customer-level personalization requires consent and role-based data scope.",
                "Keep audit log references for campaign-generated assets and social posts.",
            ],
            "data_integrity_controls": [
                "Campaign payload signed with HMAC-SHA256.",
                "BI metrics are generated from live server state snapshots.",
                "Published assets include campaign trace tags.",
                "Integrity verification required before media publication.",
            ],
            "media_dashboard_bridge": {
                "create_briefs": True,
                "asset_source": "ai_campaign",
                "recommended_asset_types": ["story_brief", "article_brief", "video_brief"],
            },
        }

        signature = self._campaign_payload_signature(payload)
        return {
            "campaign": payload,
            "integrity": {
                "algorithm": "hmac-sha256",
                "signature": signature,
                "verified": self.verify_campaign_payload(payload, signature),
            },
        }

    def build_media_briefs(self, campaign_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Convert a campaign into concise briefs suitable for media assets."""
        campaign_id = str(campaign_payload.get("campaign_id") or "MKT-UNKNOWN")
        briefs: List[Dict[str, Any]] = []

        for idx, story in enumerate(campaign_payload.get("story_outlines", [])[:3], start=1):
            text = (
                f"Campaign: {campaign_id}\n"
                f"Type: Story Outline\n"
                f"Title: {story.get('title', '')}\n"
                f"Persona: {story.get('persona', '')}\n"
                f"Outline: {story.get('outline', '')}\n"
                f"Distribution: {story.get('distribution', '')}\n"
            )
            briefs.append(
                {
                    "name": f"{campaign_id} Story Brief {idx}.txt",
                    "content": text,
                    "brief_type": "story",
                }
            )

        for idx, video in enumerate(campaign_payload.get("ai_video_blueprints", [])[:3], start=1):
            storyboard = video.get("storyboard", [])
            storyboard_text = "\n".join(f"- {item}" for item in storyboard)
            text = (
                f"Campaign: {campaign_id}\n"
                f"Type: AI Video Blueprint\n"
                f"Title: {video.get('title', '')}\n"
                f"Format: {video.get('format', '')}\n"
                f"Voiceover: {video.get('voiceover_style', '')}\n"
                f"Storyboard:\n{storyboard_text}\n"
            )
            briefs.append(
                {
                    "name": f"{campaign_id} Video Brief {idx}.txt",
                    "content": text,
                    "brief_type": "video",
                }
            )

        for idx, article in enumerate(campaign_payload.get("targeted_articles", [])[:2], start=1):
            seo_list = article.get("seo_focus", [])
            seo_text = ", ".join(str(item) for item in seo_list)
            text = (
                f"Campaign: {campaign_id}\n"
                f"Type: Targeted Article Brief\n"
                f"Title: {article.get('title', '')}\n"
                f"Angle: {article.get('angle', '')}\n"
                f"SEO Focus: {seo_text}\n"
                f"CTA: {article.get('cta', '')}\n"
            )
            briefs.append(
                {
                    "name": f"{campaign_id} Article Brief {idx}.txt",
                    "content": text,
                    "brief_type": "article",
                }
            )

        return briefs


_marketing_sales_agent_service: Optional[MarketingSalesAgentService] = None


def get_marketing_sales_agent_service(secret_key: Optional[str] = None) -> MarketingSalesAgentService:
    """Get or create singleton marketing sales agent service."""
    global _marketing_sales_agent_service
    if _marketing_sales_agent_service is None:
        _marketing_sales_agent_service = MarketingSalesAgentService(secret_key=secret_key)
    return _marketing_sales_agent_service

