"""
PHINS Marketing + Sales Agent Service
=====================================

Advanced AI + BI growth service for:
- Insurance
- Investments
- Health wallet
- Supplier ecosystem (lawyers, doctors, pharmacies, delivery)

Capabilities:
- Campaign generation with sales playbooks
- Story/article/video social assets
- Viral short-ad content packages for Veo/Kling-style providers
- Social learning ingestion and BI feedback loops
- Strong integrity controls for every generated payload
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


ALLOWED_VERTICALS = {"insurance", "investments", "health_wallet", "suppliers"}
ALLOWED_OBJECTIVES = {"growth", "retention", "cross_sell", "reactivation"}
ALLOWED_AUDIENCE_MODES = {"customer", "supplier", "hybrid"}

SUPPORTED_NETWORKS = {
    "linkedin",
    "x",
    "facebook",
    "instagram",
    "youtube",
    "tiktok",
    "whatsapp",
    "telegram",
}

SUPPLIER_SEGMENT_ALIASES = {
    "lawyer": "lawyers",
    "lawyers": "lawyers",
    "legal": "lawyers",
    "attorney": "lawyers",
    "doctor": "doctors",
    "doctors": "doctors",
    "physician": "doctors",
    "medical": "doctors",
    "pharmacy": "pharmacies",
    "pharmacies": "pharmacies",
    "pharma": "pharmacies",
    "delivery": "delivery",
    "deliveries": "delivery",
    "logistics": "delivery",
    "courier": "delivery",
}
SUPPORTED_SUPPLIER_SEGMENTS = {"lawyers", "doctors", "pharmacies", "delivery"}

VIDEO_AI_PROVIDERS: Dict[str, Dict[str, str]] = {
    "veo": {
        "display_name": "Google Veo",
        "api_key_env": "VEO_API_KEY",
        "endpoint_env": "VEO_API_ENDPOINT",
        "default_endpoint": "https://api.veo.example/v1/generate",
    },
    "kling": {
        "display_name": "Kling AI",
        "api_key_env": "KLING_API_KEY",
        "endpoint_env": "KLING_API_ENDPOINT",
        "default_endpoint": "https://api.kling.example/v1/generate",
    },
    "runway": {
        "display_name": "Runway",
        "api_key_env": "RUNWAY_API_KEY",
        "endpoint_env": "RUNWAY_API_ENDPOINT",
        "default_endpoint": "https://api.runway.example/v1/generate",
    },
    "pika": {
        "display_name": "Pika",
        "api_key_env": "PIKA_API_KEY",
        "endpoint_env": "PIKA_API_ENDPOINT",
        "default_endpoint": "https://api.pika.example/v1/generate",
    },
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


def _now_iso() -> str:
    """UTC ISO timestamp helper."""
    return datetime.now(timezone.utc).isoformat()


class MarketingSalesAgentService:
    """AI + BI campaign generation and social growth intelligence service."""

    def __init__(self, secret_key: Optional[str] = None):
        self._secret_key = (
            secret_key
            or os.environ.get("PHINS_MARKETING_AGENT_SECRET")
            or os.environ.get("SESSION_SECRET_KEY")
            or "PHINS_MARKETING_AGENT_2026"
        )

    # ---------------------------------------------------------------------
    # Integrity helpers
    # ---------------------------------------------------------------------
    def _serialize(self, payload: Dict[str, Any]) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def _payload_sha256(self, payload: Dict[str, Any]) -> str:
        serialized = self._serialize(payload)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _sign_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        serialized = self._serialize(payload)
        signature = hmac.new(
            self._secret_key.encode("utf-8"),
            serialized.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        integrity = {
            "algorithm": "hmac-sha256",
            "signature": signature,
            "payload_sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            "signed_at": _now_iso(),
        }
        integrity["verified"] = self.verify_payload_integrity(payload, integrity)
        return integrity

    def verify_payload_integrity(self, payload: Dict[str, Any], integrity: Dict[str, Any]) -> bool:
        """Verify both payload hash and signature."""
        if not isinstance(integrity, dict):
            return False

        provided_sig = str(integrity.get("signature", ""))
        provided_hash = str(integrity.get("payload_sha256", ""))
        serialized = self._serialize(payload)
        expected_sig = hmac.new(
            self._secret_key.encode("utf-8"),
            serialized.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        expected_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        sig_valid = hmac.compare_digest(expected_sig, provided_sig)
        # Backward compatibility: earlier payloads may not include payload_sha256.
        hash_valid = hmac.compare_digest(expected_hash, provided_hash) if provided_hash else True
        return sig_valid and hash_valid

    # Backward compatibility for existing call sites/tests.
    def _campaign_payload_signature(self, payload: Dict[str, Any]) -> str:
        return self._sign_payload(payload)["signature"]

    def verify_campaign_payload(self, payload: Dict[str, Any], signature: str) -> bool:
        expected = self._campaign_payload_signature(payload)
        return hmac.compare_digest(expected, str(signature or ""))

    # ---------------------------------------------------------------------
    # Normalization helpers
    # ---------------------------------------------------------------------
    def _normalize_vertical(self, vertical: Optional[str]) -> str:
        value = str(vertical or "insurance").strip().lower()
        return value if value in ALLOWED_VERTICALS else "insurance"

    def _normalize_objective(self, objective: Optional[str]) -> str:
        value = str(objective or "growth").strip().lower()
        return value if value in ALLOWED_OBJECTIVES else "growth"

    def _normalize_audience_mode(self, mode: Optional[str]) -> str:
        value = str(mode or "hybrid").strip().lower()
        return value if value in ALLOWED_AUDIENCE_MODES else "hybrid"

    def _normalize_networks(self, networks: Optional[List[str]]) -> List[str]:
        if not networks:
            return ["linkedin", "x", "facebook", "instagram", "youtube", "whatsapp"]
        cleaned: List[str] = []
        for value in networks:
            normalized = str(value or "").strip().lower()
            if normalized in SUPPORTED_NETWORKS and normalized not in cleaned:
                cleaned.append(normalized)
        return cleaned or ["linkedin", "x", "facebook", "instagram", "youtube", "whatsapp"]

    def _normalize_supplier_type(self, supplier_type: Any) -> str:
        value = str(supplier_type or "").strip().lower().replace(" ", "_")
        return SUPPLIER_SEGMENT_ALIASES.get(value, "other")

    def _normalize_supplier_segments(self, segments: Optional[List[str]]) -> List[str]:
        if not segments:
            return sorted(SUPPORTED_SUPPLIER_SEGMENTS)
        normalized = []
        for value in segments:
            mapped = self._normalize_supplier_type(value)
            if mapped in SUPPORTED_SUPPLIER_SEGMENTS and mapped not in normalized:
                normalized.append(mapped)
        return normalized or sorted(SUPPORTED_SUPPLIER_SEGMENTS)

    # ---------------------------------------------------------------------
    # Provider and social network capability maps
    # ---------------------------------------------------------------------
    def get_provider_status(self) -> Dict[str, Any]:
        """Return provider connection status without exposing secrets."""
        result: Dict[str, Any] = {}
        for provider, cfg in VIDEO_AI_PROVIDERS.items():
            api_key = os.environ.get(cfg["api_key_env"], "")
            endpoint = os.environ.get(cfg["endpoint_env"], cfg["default_endpoint"])
            connected = bool(api_key and endpoint)
            result[provider] = {
                "provider": provider,
                "display_name": cfg["display_name"],
                "endpoint": endpoint,
                "api_key_configured": bool(api_key),
                "connected": connected,
                "status": "ready" if connected else "missing_credentials",
            }
        return result

    def get_social_network_adapters(self) -> Dict[str, Dict[str, Any]]:
        """Social network format guidance for ad packaging."""
        return {
            "linkedin": {"primary_format": "text + carousel/video", "video_max_seconds": 90},
            "x": {"primary_format": "thread + short clip", "video_max_seconds": 140},
            "facebook": {"primary_format": "community post + video", "video_max_seconds": 120},
            "instagram": {"primary_format": "reel + stories", "video_max_seconds": 90},
            "youtube": {"primary_format": "short + long explainers", "video_max_seconds": 180},
            "tiktok": {"primary_format": "short vertical", "video_max_seconds": 60},
            "whatsapp": {"primary_format": "broadcast + status clip", "video_max_seconds": 60},
            "telegram": {"primary_format": "channel post + short clip", "video_max_seconds": 90},
        }

    # ---------------------------------------------------------------------
    # BI signals
    # ---------------------------------------------------------------------
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
            total_claims_amount += _safe_float(
                claim.get("approved_amount", claim.get("paid_amount", claim.get("claimed_amount", 0)))
            )

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

    def _build_supplier_signals(
        self,
        suppliers: Dict[str, Dict[str, Any]],
        supplier_orders: Dict[str, Dict[str, Any]],
        selected_segments: List[str],
    ) -> Dict[str, Any]:
        by_segment: Dict[str, Dict[str, Any]] = {
            segment: {
                "total_suppliers": 0,
                "active_suppliers": 0,
                "pending_suppliers": 0,
                "orders": 0,
                "order_value": 0.0,
            }
            for segment in selected_segments
        }

        supplier_to_segment: Dict[str, str] = {}
        for supplier_id, supplier in (suppliers or {}).items():
            segment = self._normalize_supplier_type(
                supplier.get("supplier_type", supplier.get("type", supplier.get("category", "")))
            )
            if segment not in by_segment:
                continue

            supplier_to_segment[supplier_id] = segment
            by_segment[segment]["total_suppliers"] += 1
            status = _status(supplier.get("status"))
            if status in {"approved", "active", "onboarded"}:
                by_segment[segment]["active_suppliers"] += 1
            elif status in {"pending", "under_review"}:
                by_segment[segment]["pending_suppliers"] += 1

        for order in (supplier_orders or {}).values():
            supplier_id = str(order.get("supplier_id") or "")
            segment = supplier_to_segment.get(supplier_id)
            if not segment:
                continue
            amount = _safe_float(order.get("total_amount", order.get("amount", 0)))
            by_segment[segment]["orders"] += 1
            by_segment[segment]["order_value"] += max(amount, 0.0)

        total_suppliers = sum(item["total_suppliers"] for item in by_segment.values())
        total_orders = sum(item["orders"] for item in by_segment.values())
        total_order_value = sum(item["order_value"] for item in by_segment.values())

        return {
            "selected_segments": selected_segments,
            "total_suppliers": total_suppliers,
            "total_orders": total_orders,
            "total_order_value": round(total_order_value, 2),
            "by_segment": {
                segment: {
                    **values,
                    "order_value": round(values["order_value"], 2),
                    "activation_rate_pct": round(
                        (values["active_suppliers"] / max(values["total_suppliers"], 1)) * 100,
                        2,
                    ),
                }
                for segment, values in by_segment.items()
            },
        }

    # ---------------------------------------------------------------------
    # Campaign building blocks
    # ---------------------------------------------------------------------
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
        if vertical == "suppliers":
            return {
                "value_prop": "Acquire higher-value service demand with trust-first partner storytelling.",
                "hero_angle": "From underutilized capacity to predictable lead flow.",
                "cta": "Activate supplier growth campaigns across your primary channels.",
            }
        return {
            "value_prop": "Protect families while improving affordability through data-driven insurance design.",
            "hero_angle": "Coverage confidence with transparent outcomes.",
            "cta": "Start a precision underwriting checkup today.",
        }

    def _build_sales_playbooks(
        self,
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
                "how_it_works": "Detect lifecycle events and launch a timed three-step sequence: pain, proof, offer.",
                "script_hook": f"For {persona}, trigger personalized outreach within 24h of underwriting/billing events.",
                "kpi_target": "Lead-to-meeting conversion +18%",
            },
            {
                "playbook": "Trust-to-Upgrade Flywheel",
                "how_it_works": "Use payout transparency and outcomes stories to drive tier upgrades and referral intent.",
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
                "how_it_works": "Convert outstanding balances using empathetic scripts and split-payment options.",
                "script_hook": f"Collection rate baseline is {collection_rate:.1f}%; launch recovery sequence by risk bucket.",
                "kpi_target": "Collection rate +8%",
            },
            {
                "playbook": "Objective-Specific Closing Motion",
                "how_it_works": "Mirror closing language to objective mode: growth, retention, cross-sell, reactivation.",
                "script_hook": f"Objective is {objective}; use dedicated objection handling matrix.",
                "kpi_target": "Close rate +15%",
            },
        ]

    def _build_supplier_playbooks(self, supplier_signals: Dict[str, Any]) -> List[Dict[str, Any]]:
        segments = supplier_signals.get("selected_segments", [])
        segment_label = ", ".join(segments) if segments else "supplier network"
        return [
            {
                "playbook": "Trust Badge Ladder",
                "how_it_works": "Use verified service outcomes and response-time badges in every ad creative.",
                "script_hook": f"Primary segments: {segment_label}. Lead with trust before pricing.",
                "kpi_target": "Qualified supplier leads +22%",
            },
            {
                "playbook": "Geo-Intent Capture",
                "how_it_works": "Run hyperlocal short ads keyed to urgent service moments.",
                "script_hook": "Pair social hooks with one-click booking and callback automation.",
                "kpi_target": "Cost per supplier acquisition -15%",
            },
            {
                "playbook": "Provider Authority Content",
                "how_it_works": "Publish legal/medical/pharmacy/delivery authority explainers as micro-campaigns.",
                "script_hook": "Convert educational content into retargeting cohorts.",
                "kpi_target": "Return visitor rate +20%",
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
                "distribution": "Blog long-form + webinar intro + short clip",
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
                "title": "7 High-Conversion Scripts Elite Sales Teams Use",
                "angle": "Actionable scripts mapped to buyer maturity stages and objections.",
                "seo_focus": ["sales scripts", "conversion playbook", "sales enablement"],
                "cta": "Download script deck",
            },
            {
                "title": "How AI + BI Reduce Customer Acquisition Waste",
                "angle": "Attribution model, audience pruning, and channel-level ROI control.",
                "seo_focus": ["marketing attribution", "insurance ai", "bi dashboard"],
                "cta": "Open campaign diagnostics dashboard",
            },
            {
                "title": "Cross-Sell Expansion Without Compliance Drift",
                "angle": "Bundle architecture with clear disclosures and consent checkpoints.",
                "seo_focus": ["cross sell", "compliance marketing", "retention playbook"],
                "cta": "Activate bundled campaign mode",
            },
        ]

    def _build_video_blueprints(self, vertical: str, persona: str) -> List[Dict[str, Any]]:
        vertical_label = vertical.replace("_", " ").title()
        return [
            {
                "title": f"{vertical_label} Viral Hook Explainer (20s)",
                "format": "Vertical short video",
                "storyboard": [
                    "Hook: painful scenario in 3 seconds",
                    "Insight: AI + BI recommendation moment",
                    "Proof: quantified outcome",
                    "CTA: one action close",
                ],
                "voiceover_style": "Confident, plain-language, evidence-based",
            },
            {
                "title": f"{persona.title()} Testimonial Narrative (45s)",
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
                "title": "Offer Countdown Teaser (15s)",
                "format": "Social ad cutdown",
                "storyboard": [
                    "High-energy open",
                    "Three bullet outcomes",
                    "Urgency + scarcity cue",
                ],
                "voiceover_style": "High-energy conversion push",
            },
        ]

    def _hashtags_for(self, vertical: str, supplier_segments: List[str]) -> List[str]:
        base = ["#PHINS", "#AIMarketing", "#SalesEnablement", "#BIInsights"]
        if vertical == "insurance":
            base.extend(["#InsuranceInnovation", "#RiskProtection"])
        elif vertical == "investments":
            base.extend(["#SmartInvesting", "#PortfolioGrowth"])
        elif vertical == "health_wallet":
            base.extend(["#HealthWallet", "#PreventiveCare"])
        elif vertical == "suppliers":
            base.extend(["#SupplierGrowth", "#ServiceMarketplace"])

        if "lawyers" in supplier_segments:
            base.append("#LegalServices")
        if "doctors" in supplier_segments:
            base.append("#MedicalServices")
        if "pharmacies" in supplier_segments:
            base.append("#PharmacyCare")
        if "delivery" in supplier_segments:
            base.append("#DeliveryNetwork")
        return base

    def _build_social_plan(
        self,
        networks: List[str],
        objective: str,
        campaign_id: str,
        vertical: str,
        supplier_segments: List[str],
    ) -> List[Dict[str, Any]]:
        network_styles = {
            "linkedin": ("Thought leadership + carousel/video", "3 posts/week"),
            "x": ("Thread + proof-point snippets", "5 posts/week"),
            "facebook": ("Community story + retargeting ad", "4 posts/week"),
            "instagram": ("Reels + story polls", "6 stories/week"),
            "youtube": ("Educational short + testimonial", "2 videos/week"),
            "tiktok": ("Explainer clips + hooks", "4 videos/week"),
            "whatsapp": ("Advisor broadcast + micro-brief", "2 campaigns/week"),
            "telegram": ("Channel post + compact explainer", "3 posts/week"),
        }
        hashtags = self._hashtags_for(vertical, supplier_segments)
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
                    "hashtags": hashtags[:8],
                }
            )
        return result

    # ---------------------------------------------------------------------
    # Public campaign generation
    # ---------------------------------------------------------------------
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
        suppliers: Optional[Dict[str, Dict[str, Any]]] = None,
        supplier_orders: Optional[Dict[str, Dict[str, Any]]] = None,
        audience_mode: str = "hybrid",
        supplier_segments: Optional[List[str]] = None,
        social_provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_vertical = self._normalize_vertical(vertical)
        normalized_objective = self._normalize_objective(objective)
        normalized_networks = self._normalize_networks(social_networks)
        normalized_audience_mode = self._normalize_audience_mode(audience_mode)
        normalized_supplier_segments = self._normalize_supplier_segments(supplier_segments)
        provider_key = str(social_provider or "veo").strip().lower()
        if provider_key not in VIDEO_AI_PROVIDERS:
            provider_key = "veo"

        generated_at = _now_iso()
        campaign_id = f"MKT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:4].upper()}"

        bi_signals = self._build_bi_signals(
            customers=customers,
            policies=policies,
            billing=billing,
            claims=claims,
            health_wallets=health_wallets,
            investment_accounts=investment_accounts,
            transaction_ledger=transaction_ledger,
        )
        supplier_signals = self._build_supplier_signals(
            suppliers=suppliers or {},
            supplier_orders=supplier_orders or {},
            selected_segments=normalized_supplier_segments,
        )
        messaging = self._vertical_messaging(normalized_vertical)
        provider_status = self.get_provider_status()

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
                "audience_mode": normalized_audience_mode,
                "supplier_segments": normalized_supplier_segments,
                "social_provider": provider_key,
            },
            "value_messaging": messaging,
            "bi_signals": bi_signals,
            "supplier_signals": supplier_signals,
            "sales_playbooks": self._build_sales_playbooks(
                normalized_objective,
                str(persona or "families").strip().lower(),
                bi_signals,
            ),
            "supplier_sales_playbooks": self._build_supplier_playbooks(supplier_signals),
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
                normalized_vertical,
                normalized_supplier_segments,
            ),
            "social_ai_providers": {
                "recommended": provider_key,
                "status": provider_status.get(provider_key, {}),
                "available": provider_status,
            },
            "funnel_orchestration": {
                "awareness": "Story-led social + high-intent article SEO + short viral ads",
                "consideration": "Advisor webinar + supplier authority clips + targeted follow-up",
                "conversion": "Risk-adjusted offer matrix + objection playbook + urgency windows",
                "retention": "Milestone messaging + wallet/investment expansion + supplier referrals",
            },
            "learning_loop": {
                "enabled": True,
                "feedback_sources": ["facebook_groups", "instagram_communities", "linkedin_posts", "youtube_shorts"],
                "core_metrics": ["impressions", "views", "likes", "comments", "shares", "clicks", "leads", "conversions"],
            },
            "compliance_guardrails": [
                "No guaranteed return claims in investment communication.",
                "Every campaign artifact must include eligibility and disclosure language.",
                "Customer-level personalization requires consent and role-based data scope.",
                "Keep audit-log references for campaign-generated assets and social posts.",
                "Supplier campaigns must avoid professional misrepresentation claims.",
            ],
            "data_integrity_controls": [
                "Campaign payload signed with HMAC-SHA256 and payload hash.",
                "BI metrics generated from live server state snapshots.",
                "Published assets include campaign trace tags.",
                "Integrity verification required before media publication.",
                "Social learning events are individually signed and validated.",
            ],
            "media_dashboard_bridge": {
                "create_briefs": True,
                "asset_source": "ai_campaign",
                "recommended_asset_types": ["story_brief", "article_brief", "video_brief", "social_brief"],
            },
        }

        integrity = self._sign_payload(payload)
        return {"campaign": payload, "integrity": integrity}

    # ---------------------------------------------------------------------
    # Media brief helpers
    # ---------------------------------------------------------------------
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
            briefs.append({"name": f"{campaign_id} Story Brief {idx}.txt", "content": text, "brief_type": "story"})

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
            briefs.append({"name": f"{campaign_id} Video Brief {idx}.txt", "content": text, "brief_type": "video"})

        for idx, article in enumerate(campaign_payload.get("targeted_articles", [])[:2], start=1):
            seo_text = ", ".join(str(item) for item in article.get("seo_focus", []))
            text = (
                f"Campaign: {campaign_id}\n"
                f"Type: Targeted Article Brief\n"
                f"Title: {article.get('title', '')}\n"
                f"Angle: {article.get('angle', '')}\n"
                f"SEO Focus: {seo_text}\n"
                f"CTA: {article.get('cta', '')}\n"
            )
            briefs.append({"name": f"{campaign_id} Article Brief {idx}.txt", "content": text, "brief_type": "article"})

        social_plan = campaign_payload.get("social_network_plan", [])
        if social_plan:
            plan_lines = []
            for row in social_plan:
                plan_lines.append(
                    f"- {row.get('network', '').upper()}: {row.get('format', '')} | {row.get('cadence', '')} | Tag {row.get('tracking_tag', '')}"
                )
            text = (
                f"Campaign: {campaign_id}\n"
                "Type: Social Distribution Brief\n"
                "Plan:\n"
                + "\n".join(plan_lines)
                + "\n"
            )
            briefs.append({"name": f"{campaign_id} Social Plan Brief.txt", "content": text, "brief_type": "social"})

        return briefs

    # ---------------------------------------------------------------------
    # Social short-ad generation (Veo/Kling/etc)
    # ---------------------------------------------------------------------
    def _build_video_prompt(
        self,
        campaign_payload: Dict[str, Any],
        hook: str,
        offer: str,
        cta: str,
        target_group: str,
        duration_seconds: int,
        aspect_ratio: str,
    ) -> str:
        scope = campaign_payload.get("scope", {})
        vertical = scope.get("vertical", "insurance")
        objective = scope.get("objective", "growth")
        persona = scope.get("persona", "audience")
        return (
            f"Create a {duration_seconds}s {aspect_ratio} high-energy ad for {vertical}.\n"
            f"Objective: {objective}. Persona: {persona}. Target group: {target_group}.\n"
            f"Hook: {hook}\nOffer: {offer}\nCTA: {cta}\n"
            "Style: modern, trustworthy, premium, high conversion.\n"
            "Include captions, dynamic transitions, and a strong final action frame."
        )

    def _build_network_packages(
        self,
        ad_id: str,
        networks: List[str],
        hook: str,
        offer: str,
        cta: str,
        hashtags: List[str],
    ) -> List[Dict[str, Any]]:
        adapters = self.get_social_network_adapters()
        result = []
        for network in networks:
            adapter = adapters.get(network, {})
            caption = f"{hook} {offer} {cta}".strip()
            result.append(
                {
                    "network": network,
                    "caption": caption,
                    "hashtags": hashtags[:10],
                    "format": adapter.get("primary_format", "short clip"),
                    "video_max_seconds": adapter.get("video_max_seconds", 60),
                    "tracking_tag": f"{ad_id}:{network}",
                }
            )
        return result

    def _submit_provider_job(
        self,
        provider: str,
        content_payload: Dict[str, Any],
        execution_mode: str,
    ) -> Dict[str, Any]:
        provider_key = provider if provider in VIDEO_AI_PROVIDERS else "veo"
        provider_status = self.get_provider_status().get(provider_key, {})
        endpoint = provider_status.get("endpoint", "")
        job_id = f"VID-{provider_key.upper()}-{uuid.uuid4().hex[:10]}"

        if execution_mode != "provider_call":
            return {
                "job_id": job_id,
                "provider": provider_key,
                "submitted": False,
                "status": "dry_run",
                "endpoint": endpoint,
                "message": "Dry run mode. No external provider call executed.",
            }

        if not provider_status.get("connected", False):
            return {
                "job_id": job_id,
                "provider": provider_key,
                "submitted": False,
                "status": "credentials_missing",
                "endpoint": endpoint,
                "message": "Provider credentials are not configured.",
            }

        enable_calls = str(os.environ.get("PHINS_MARKETING_PROVIDER_ENABLE_CALLS", "")).lower() in {"1", "true", "yes", "y"}
        if not enable_calls:
            return {
                "job_id": job_id,
                "provider": provider_key,
                "submitted": True,
                "status": "simulated",
                "endpoint": endpoint,
                "message": "Provider call simulation (enable PHINS_MARKETING_PROVIDER_ENABLE_CALLS=1 for real calls).",
            }

        cfg = VIDEO_AI_PROVIDERS.get(provider_key, {})
        api_key = os.environ.get(cfg.get("api_key_env", ""), "")
        payload = {
            "prompt": content_payload.get("video_prompt", ""),
            "duration_seconds": content_payload.get("duration_seconds", 20),
            "aspect_ratio": content_payload.get("aspect_ratio", "9:16"),
            "metadata": {
                "ad_id": content_payload.get("ad_id"),
                "campaign_id": content_payload.get("campaign_id"),
            },
        }

        try:
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as response:
                raw = response.read().decode("utf-8", errors="replace")
                parsed: Any
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = {"raw_response": raw}
                return {
                    "job_id": job_id,
                    "provider": provider_key,
                    "submitted": True,
                    "status": "submitted",
                    "endpoint": endpoint,
                    "provider_response": parsed,
                }
        except urllib.error.HTTPError as exc:
            return {
                "job_id": job_id,
                "provider": provider_key,
                "submitted": False,
                "status": "provider_http_error",
                "endpoint": endpoint,
                "error": f"HTTP {exc.code}",
            }
        except Exception as exc:
            return {
                "job_id": job_id,
                "provider": provider_key,
                "submitted": False,
                "status": "provider_error",
                "endpoint": endpoint,
                "error": str(exc),
            }

    def build_social_content_package(
        self,
        *,
        campaign_payload: Dict[str, Any],
        provider: str,
        social_networks: Optional[List[str]],
        hook: str,
        offer: str,
        cta: str,
        target_group: str,
        duration_seconds: int = 20,
        aspect_ratio: str = "9:16",
        execution_mode: str = "dry_run",
        created_by: str = "admin",
    ) -> Dict[str, Any]:
        """Create social ad package and optional provider render job."""
        provider_key = str(provider or "veo").strip().lower()
        if provider_key not in VIDEO_AI_PROVIDERS:
            provider_key = "veo"

        networks = self._normalize_networks(social_networks)
        scope = campaign_payload.get("scope", {})
        supplier_segments = scope.get("supplier_segments", [])
        if not isinstance(supplier_segments, list):
            supplier_segments = []

        ad_id = f"AD-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
        safe_duration = max(6, min(_safe_int(duration_seconds, 20), 180))
        safe_aspect = str(aspect_ratio or "9:16").strip() or "9:16"

        video_prompt = self._build_video_prompt(
            campaign_payload=campaign_payload,
            hook=str(hook or "Unlock better outcomes in seconds."),
            offer=str(offer or "Personalized protection and growth plans."),
            cta=str(cta or "Book a strategy call now."),
            target_group=str(target_group or "high-intent audience"),
            duration_seconds=safe_duration,
            aspect_ratio=safe_aspect,
        )

        hashtags = self._hashtags_for(str(scope.get("vertical", "insurance")), supplier_segments)
        network_packages = self._build_network_packages(
            ad_id=ad_id,
            networks=networks,
            hook=str(hook or ""),
            offer=str(offer or ""),
            cta=str(cta or ""),
            hashtags=hashtags,
        )

        social_payload = {
            "ad_id": ad_id,
            "campaign_id": campaign_payload.get("campaign_id", ""),
            "provider": provider_key,
            "execution_mode": execution_mode,
            "created_at": _now_iso(),
            "created_by": created_by,
            "duration_seconds": safe_duration,
            "aspect_ratio": safe_aspect,
            "target_group": str(target_group or "high-intent audience"),
            "video_prompt": video_prompt,
            "viral_triggers": [
                "3-second problem hook",
                "clear quantified outcome",
                "single action CTA",
                "social proof framing",
            ],
            "script_variants": [
                {"variant": "A", "hook": hook, "body": offer, "cta": cta},
                {
                    "variant": "B",
                    "hook": f"Stop losing time on {scope.get('vertical', 'campaign')} guesswork.",
                    "body": offer,
                    "cta": cta,
                },
                {
                    "variant": "C",
                    "hook": f"Trusted results for {target_group}.",
                    "body": offer,
                    "cta": cta,
                },
            ],
            "network_packages": network_packages,
            "hashtags": hashtags,
            "compliance_notes": [
                "Avoid unverified guarantees or unsupported claims.",
                "Disclose eligibility/limitations where required.",
                "Keep campaign trace tags in post metadata.",
            ],
        }
        integrity = self._sign_payload(social_payload)
        provider_job = self._submit_provider_job(provider_key, social_payload, execution_mode=execution_mode)
        provider_job_integrity = self._sign_payload(provider_job)

        return {
            "social_content": social_payload,
            "integrity": integrity,
            "provider_job": provider_job,
            "provider_job_integrity": provider_job_integrity,
        }

    def build_social_content_media_briefs(self, social_payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Create media-asset friendly briefs from social package."""
        ad_id = str(social_payload.get("ad_id") or "AD-UNKNOWN")
        briefs: List[Dict[str, Any]] = []

        prompt_text = (
            f"Ad ID: {ad_id}\n"
            f"Campaign ID: {social_payload.get('campaign_id', '')}\n"
            f"Provider: {social_payload.get('provider', '')}\n"
            f"Duration: {social_payload.get('duration_seconds', 20)}s\n"
            f"Aspect Ratio: {social_payload.get('aspect_ratio', '9:16')}\n\n"
            f"Video Prompt:\n{social_payload.get('video_prompt', '')}\n"
        )
        briefs.append({"name": f"{ad_id} Render Prompt.txt", "content": prompt_text, "brief_type": "social_video_prompt"})

        scripts = social_payload.get("script_variants", [])
        for script in scripts:
            text = (
                f"Ad ID: {ad_id}\n"
                f"Variant: {script.get('variant', '')}\n"
                f"Hook: {script.get('hook', '')}\n"
                f"Body: {script.get('body', '')}\n"
                f"CTA: {script.get('cta', '')}\n"
            )
            briefs.append(
                {
                    "name": f"{ad_id} Script Variant {script.get('variant', 'X')}.txt",
                    "content": text,
                    "brief_type": "social_script",
                }
            )

        network_packages = social_payload.get("network_packages", [])
        for package in network_packages:
            tag_text = ", ".join(package.get("hashtags", []))
            text = (
                f"Ad ID: {ad_id}\n"
                f"Network: {package.get('network', '').upper()}\n"
                f"Format: {package.get('format', '')}\n"
                f"Caption: {package.get('caption', '')}\n"
                f"Hashtags: {tag_text}\n"
                f"Tracking Tag: {package.get('tracking_tag', '')}\n"
            )
            briefs.append(
                {
                    "name": f"{ad_id} {str(package.get('network', '')).upper()} Caption Brief.txt",
                    "content": text,
                    "brief_type": "social_caption",
                }
            )

        return briefs

    # ---------------------------------------------------------------------
    # Social learning ingestion + BI outputs
    # ---------------------------------------------------------------------
    def record_social_learning_event(
        self,
        *,
        campaign_id: str,
        platform: str,
        group_name: str,
        content_id: str,
        metrics: Dict[str, Any],
        recorded_by: str,
        observed_at: Optional[str] = None,
        source_note: str = "",
    ) -> Dict[str, Any]:
        """Create a signed social-learning event envelope."""
        safe_metrics = {
            "impressions": max(0, _safe_int(metrics.get("impressions", 0))),
            "views": max(0, _safe_int(metrics.get("views", 0))),
            "likes": max(0, _safe_int(metrics.get("likes", 0))),
            "comments": max(0, _safe_int(metrics.get("comments", 0))),
            "shares": max(0, _safe_int(metrics.get("shares", 0))),
            "clicks": max(0, _safe_int(metrics.get("clicks", 0))),
            "leads": max(0, _safe_int(metrics.get("leads", 0))),
            "conversions": max(0, _safe_int(metrics.get("conversions", 0))),
            "spend": round(max(0.0, _safe_float(metrics.get("spend", 0.0))), 2),
        }
        event_payload = {
            "event_id": f"LRN-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}",
            "campaign_id": str(campaign_id or "").strip(),
            "platform": str(platform or "unknown").strip().lower(),
            "group_name": str(group_name or "").strip(),
            "content_id": str(content_id or "").strip(),
            "metrics": safe_metrics,
            "source_note": str(source_note or "").strip(),
            "observed_at": str(observed_at or _now_iso()),
            "recorded_at": _now_iso(),
            "recorded_by": str(recorded_by or "admin"),
        }
        integrity = self._sign_payload(event_payload)
        return {"event": event_payload, "integrity": integrity}

    def _event_rates(self, metrics: Dict[str, Any]) -> Dict[str, float]:
        impressions = max(_safe_float(metrics.get("impressions", 0)), 1.0)
        clicks = max(_safe_float(metrics.get("clicks", 0)), 1.0)
        leads = max(_safe_float(metrics.get("leads", 0)), 1.0)
        engagement = _safe_float(metrics.get("likes", 0)) + _safe_float(metrics.get("comments", 0)) + _safe_float(metrics.get("shares", 0))
        return {
            "engagement_rate_pct": round((engagement / impressions) * 100, 2),
            "ctr_pct": round((_safe_float(metrics.get("clicks", 0)) / impressions) * 100, 2),
            "lead_rate_pct": round((_safe_float(metrics.get("leads", 0)) / clicks) * 100, 2),
            "conversion_rate_pct": round((_safe_float(metrics.get("conversions", 0)) / leads) * 100, 2),
            "cpl": round(_safe_float(metrics.get("spend", 0)) / leads, 2),
        }

    def aggregate_social_learning(self, learning_events: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate signed social-learning events and produce BI insights."""
        total = len(learning_events or [])
        verified_count = 0
        invalid_count = 0

        platform_agg: Dict[str, Dict[str, float]] = {}
        group_agg: Dict[str, Dict[str, float]] = {}

        for raw in (learning_events or []):
            payload = raw.get("event", raw) if isinstance(raw, dict) else {}
            integrity = raw.get("integrity") if isinstance(raw, dict) else None
            if integrity and not self.verify_payload_integrity(payload, integrity):
                invalid_count += 1
                continue
            verified_count += 1 if integrity else 0

            platform = str(payload.get("platform", "unknown")).strip().lower()
            group = str(payload.get("group_name", "unknown")).strip().lower()
            metrics = payload.get("metrics", {}) if isinstance(payload, dict) else {}

            for key in ["impressions", "views", "likes", "comments", "shares", "clicks", "leads", "conversions", "spend"]:
                value = _safe_float(metrics.get(key, 0))
                if platform not in platform_agg:
                    platform_agg[platform] = {k: 0.0 for k in ["impressions", "views", "likes", "comments", "shares", "clicks", "leads", "conversions", "spend"]}
                if group not in group_agg:
                    group_agg[group] = {k: 0.0 for k in ["impressions", "views", "likes", "comments", "shares", "clicks", "leads", "conversions", "spend"]}
                platform_agg[platform][key] += value
                group_agg[group][key] += value

        platform_rows = []
        for platform, metrics in platform_agg.items():
            row = {"platform": platform, **{k: round(v, 2) for k, v in metrics.items()}}
            row.update(self._event_rates(metrics))
            platform_rows.append(row)
        platform_rows.sort(key=lambda item: item.get("engagement_rate_pct", 0), reverse=True)

        group_rows = []
        for group, metrics in group_agg.items():
            row = {"group_name": group, **{k: round(v, 2) for k, v in metrics.items()}}
            row.update(self._event_rates(metrics))
            group_rows.append(row)
        group_rows.sort(key=lambda item: item.get("conversion_rate_pct", 0), reverse=True)

        total_metrics = {k: 0.0 for k in ["impressions", "views", "likes", "comments", "shares", "clicks", "leads", "conversions", "spend"]}
        for row in platform_agg.values():
            for key in total_metrics:
                total_metrics[key] += _safe_float(row.get(key, 0))
        summary = {k: round(v, 2) for k, v in total_metrics.items()}
        summary.update(self._event_rates(total_metrics))

        insights: List[str] = []
        if platform_rows:
            best_platform = platform_rows[0]
            insights.append(
                f"Top engagement platform: {best_platform['platform']} ({best_platform['engagement_rate_pct']:.2f}% engagement)."
            )
            best_conversion = max(platform_rows, key=lambda item: item.get("conversion_rate_pct", 0))
            insights.append(
                f"Top conversion platform: {best_conversion['platform']} ({best_conversion['conversion_rate_pct']:.2f}% conversion)."
            )
        if group_rows:
            best_group = group_rows[0]
            insights.append(
                f"Highest converting group: {best_group['group_name']} ({best_group['conversion_rate_pct']:.2f}% conversion)."
            )
        if summary.get("ctr_pct", 0) < 1.0 and summary.get("impressions", 0) > 0:
            insights.append("CTR is low; refresh opening hooks and tighten first 3 seconds of short-video creatives.")
        if summary.get("engagement_rate_pct", 0) > 4.0:
            insights.append("Strong engagement: scale winning creatives into additional similar communities.")

        return {
            "generated_at": _now_iso(),
            "total_events": total,
            "verified_events": verified_count,
            "invalid_events": invalid_count,
            "summary": summary,
            "by_platform": platform_rows,
            "by_group": group_rows[:20],
            "insights": insights,
        }


_marketing_sales_agent_service: Optional[MarketingSalesAgentService] = None


def get_marketing_sales_agent_service(secret_key: Optional[str] = None) -> MarketingSalesAgentService:
    """Get or create singleton marketing sales agent service."""
    global _marketing_sales_agent_service
    if _marketing_sales_agent_service is None:
        _marketing_sales_agent_service = MarketingSalesAgentService(secret_key=secret_key)
    return _marketing_sales_agent_service

