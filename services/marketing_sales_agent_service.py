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

B7 additions (see docs/agent_operations_optimization_design.md §B7):

- every plan carries ``input_hash`` — a SHA-256 over the plan-determining
  inputs (scope, networks, BI signals, cohorts, generator version) — inside
  the signed payload, so the signature attests both the output and the
  inputs it was derived from;
- identical inputs return the *same* plan from an in-process cache (same
  campaign id, same signature) instead of minting a near-duplicate;
- optional BI cohort targeting derived from
  ``bi_analytics_service.get_customer_analytics`` output re-orders the sales
  playbooks deterministically and is part of the input hash;
- publishing anchors ``(campaign_id, signature, input_hash)`` on the platform
  event ledger (``PlatformEventLedgerService``), so a published plan can be
  proven against a hash-chained record rather than only ``DESIGN_SETTINGS``.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.agent_metrics import instrument_agent


ALLOWED_VERTICALS = {"insurance", "investments", "health_wallet"}
ALLOWED_OBJECTIVES = {"growth", "retention", "cross_sell", "reactivation"}

# Bump when the generator's output for the same inputs changes, so a cached
# or anchored plan from older code is never mistaken for the current one.
PLAN_VERSION = 2
PLAN_CACHE_MAX_ENTRIES = 64

# Platform-ledger event emitted once per (campaign_id, signature) on publish.
MARKETING_PUBLISH_EVENT_TYPE = "marketing_campaign_published"
MARKETING_LEDGER_ENTITY_TYPE = "marketing_campaign"

# Cohort id -> (label, playbook it should lead with). Sizes come from the BI
# customer-analytics summary; the mapping itself is fixed so the same BI
# output always yields the same targeting.
COHORT_DEFINITIONS: Dict[str, Dict[str, str]] = {
    "wallet_gap": {
        "label": "Customers without a health wallet",
        "playbook": "Wallet First, Coverage Second",
    },
    "investment_gap": {
        "label": "Customers without an investment account",
        "playbook": "Investment Parallel Offer",
    },
    "policy_gap": {
        "label": "Customers without an active policy",
        "playbook": "Lifecycle Trigger Ladder",
    },
    "high_value": {
        "label": "Top transacting customers",
        "playbook": "Trust-to-Upgrade Flywheel",
    },
}

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

    def __init__(self, secret_key: Optional[str] = None, plan_cache_size: int = PLAN_CACHE_MAX_ENTRIES):
        self._secret_key = (
            secret_key
            or os.environ.get("PHINS_MARKETING_AGENT_SECRET")
            or os.environ.get("SESSION_SECRET_KEY")
            or "PHINS_MARKETING_AGENT_2026"
        )
        # input_hash -> generated plan (deep-copied on the way in and out).
        self._plan_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._plan_cache_size = max(0, int(plan_cache_size or 0))
        self._plan_cache_lock = threading.Lock()
        self._plan_cache_hits = 0
        self._plan_cache_misses = 0

    # ------------------------------------------------------------------
    # B7: input hash, plan cache, cohorts
    # ------------------------------------------------------------------

    @staticmethod
    def _canonical(payload: Any) -> str:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)

    def compute_input_hash(
        self,
        *,
        scope: Dict[str, Any],
        networks: List[str],
        bi_signals: Dict[str, Any],
        cohorts: Optional[List[Dict[str, Any]]],
    ) -> str:
        """SHA-256 over everything that determines the plan body.

        ``generated_by``/timestamps are deliberately excluded: they describe
        *when/who*, not *what*; two operators asking for the same plan against
        the same data should get the same plan.
        """
        material = {
            "plan_version": PLAN_VERSION,
            "scope": scope,
            "networks": list(networks),
            "bi_signals": bi_signals,
            "cohorts": cohorts or [],
        }
        return hashlib.sha256(self._canonical(material).encode("utf-8")).hexdigest()

    def _cache_get(self, input_hash: str) -> Optional[Dict[str, Any]]:
        with self._plan_cache_lock:
            hit = self._plan_cache.get(input_hash)
            if hit is None:
                self._plan_cache_misses += 1
                return None
            self._plan_cache.move_to_end(input_hash)
            self._plan_cache_hits += 1
            return copy.deepcopy(hit)

    def _cache_put(self, input_hash: str, result: Dict[str, Any]) -> None:
        if self._plan_cache_size <= 0:
            return
        with self._plan_cache_lock:
            self._plan_cache[input_hash] = copy.deepcopy(result)
            self._plan_cache.move_to_end(input_hash)
            while len(self._plan_cache) > self._plan_cache_size:
                self._plan_cache.popitem(last=False)

    def clear_plan_cache(self) -> None:
        with self._plan_cache_lock:
            self._plan_cache.clear()

    def plan_cache_stats(self) -> Dict[str, Any]:
        with self._plan_cache_lock:
            return {
                "entries": len(self._plan_cache),
                "max_entries": self._plan_cache_size,
                "hits": self._plan_cache_hits,
                "misses": self._plan_cache_misses,
            }

    @staticmethod
    def derive_cohorts(customer_analytics: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deterministic targeting cohorts from a BI customer-analytics payload.

        Input is the dict returned by
        ``BIAnalyticsService.get_customer_analytics`` (only its ``summary``
        and ``top_customers`` sections are read). Output is sorted by size
        (desc) then id, so identical BI output always yields identical
        cohorts — and therefore an identical input hash. Cohorts of size 0
        are dropped; no customer identifiers are copied into the plan.
        """
        if not isinstance(customer_analytics, dict):
            return []
        summary = customer_analytics.get("summary") or {}
        if not isinstance(summary, dict):
            summary = {}
        total = max(_safe_int(summary.get("total_customers")), 0)
        sizes = {
            "wallet_gap": total - _safe_int(summary.get("customers_with_wallets")),
            "investment_gap": total - _safe_int(summary.get("customers_with_investments")),
            "policy_gap": total - _safe_int(summary.get("customers_with_policies")),
            "high_value": len(customer_analytics.get("top_customers") or []),
        }
        cohorts: List[Dict[str, Any]] = []
        for cohort_id, definition in COHORT_DEFINITIONS.items():
            size = max(sizes.get(cohort_id, 0), 0)
            if size <= 0:
                continue
            cohorts.append({
                "cohort_id": cohort_id,
                "label": definition["label"],
                "size": size,
                "share_pct": round((size / total) * 100, 2) if total else 0.0,
                "lead_playbook": definition["playbook"],
            })
        cohorts.sort(key=lambda c: (-c["size"], c["cohort_id"]))
        for priority, cohort in enumerate(cohorts, start=1):
            cohort["priority"] = priority
        return cohorts

    @staticmethod
    def _apply_cohort_targeting(
        playbooks: List[Dict[str, Any]],
        cohorts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Re-order playbooks so the largest cohort's lead playbook comes first.

        Pure function of (playbooks, cohorts); untouched playbooks keep their
        relative order after the targeted ones.
        """
        if not cohorts:
            return playbooks
        lead_for: Dict[str, Dict[str, Any]] = {}
        for cohort in cohorts:
            lead_for.setdefault(str(cohort.get("lead_playbook") or ""), cohort)
        targeted: List[Dict[str, Any]] = []
        rest: List[Dict[str, Any]] = []
        for playbook in playbooks:
            cohort = lead_for.get(str(playbook.get("playbook") or ""))
            if cohort is None:
                rest.append(playbook)
                continue
            item = dict(playbook)
            item["target_cohort"] = {
                "cohort_id": cohort["cohort_id"],
                "size": cohort["size"],
                "share_pct": cohort["share_pct"],
                "priority": cohort["priority"],
            }
            targeted.append(item)
        targeted.sort(key=lambda p: p["target_cohort"]["priority"])
        return targeted + rest

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

        # Non-monetary platform events (signature anchors, publication anchors,
        # audit markers) are not commercial activity; counting them would make
        # publishing a plan change the inputs of the very next plan.
        financial_entries = [
            tx for tx in (transaction_ledger or {}).values()
            if isinstance(tx, dict)
            and not (_status(tx.get("ledger_type")) == "event" and _safe_float(tx.get("amount", 0)) == 0.0)
        ]
        ledger_volume = sum(abs(_safe_float(tx.get("amount", 0))) for tx in financial_entries)

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
                "transaction_count": len(financial_entries),
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

    @instrument_agent('marketing_sales', decision_key='vertical')
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
        customer_analytics: Optional[Dict[str, Any]] = None,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        normalized_vertical = self._normalize_vertical(vertical)
        normalized_objective = self._normalize_objective(objective)
        normalized_networks = self._normalize_networks(social_networks)
        scope = {
            "vertical": normalized_vertical,
            "objective": normalized_objective,
            "persona": str(persona or "families").strip().lower(),
            "region": str(region or "global").strip().lower(),
            "budget_tier": str(budget_tier or "balanced").strip().lower(),
        }

        bi_signals = self._build_bi_signals(
            customers=customers,
            policies=policies,
            billing=billing,
            claims=claims,
            health_wallets=health_wallets,
            investment_accounts=investment_accounts,
            transaction_ledger=transaction_ledger,
        )
        cohorts = self.derive_cohorts(customer_analytics)
        input_hash = self.compute_input_hash(
            scope=scope, networks=normalized_networks, bi_signals=bi_signals, cohorts=cohorts,
        )

        if use_cache:
            cached = self._cache_get(input_hash)
            if cached is not None:
                cached["plan_cache"] = {"hit": True, "input_hash": input_hash}
                return cached

        generated_at = datetime.now(timezone.utc).isoformat()
        # The id is derived from the input hash (not the clock) so the same
        # inputs name the same campaign across processes and restarts.
        campaign_id = f"MKT-{input_hash[:16].upper()}"
        messaging = self._vertical_messaging(normalized_vertical)

        payload = {
            "campaign_id": campaign_id,
            "generated_at": generated_at,
            "generated_by": generated_by or "admin",
            "plan_version": PLAN_VERSION,
            "input_hash": input_hash,
            "scope": scope,
            "value_messaging": messaging,
            "bi_signals": bi_signals,
            "targeting": {
                "mode": "bi_cohorts" if cohorts else "broad",
                "source": "bi_analytics.customer_analytics" if cohorts else None,
                "cohorts": cohorts,
            },
            "sales_playbooks": self._apply_cohort_targeting(
                self._build_sales_playbooks(
                    normalized_vertical,
                    normalized_objective,
                    scope["persona"],
                    bi_signals,
                ),
                cohorts,
            ),
            "story_outlines": self._build_story_outlines(
                normalized_vertical,
                scope["persona"],
                scope["region"],
            ),
            "targeted_articles": self._build_article_briefs(
                normalized_vertical,
                normalized_objective,
                scope["persona"],
            ),
            "ai_video_blueprints": self._build_video_blueprints(
                normalized_vertical,
                scope["persona"],
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
                "Plan inputs hashed (input_hash) and covered by the signature.",
                "BI metrics are generated from live server state snapshots.",
                "Published assets include campaign trace tags.",
                "Integrity verification required before media publication.",
                "Publication anchors campaign id, signature and input hash on the platform event ledger.",
            ],
            "media_dashboard_bridge": {
                "create_briefs": True,
                "asset_source": "ai_campaign",
                "recommended_asset_types": ["story_brief", "article_brief", "video_brief"],
            },
        }

        signature = self._campaign_payload_signature(payload)
        result = {
            "campaign": payload,
            "integrity": {
                "algorithm": "hmac-sha256",
                "signature": signature,
                "input_hash": input_hash,
                "verified": self.verify_campaign_payload(payload, signature),
            },
        }
        if use_cache:
            self._cache_put(input_hash, result)
        result["plan_cache"] = {"hit": False, "input_hash": input_hash}
        return result

    # ------------------------------------------------------------------
    # B7: platform-ledger anchoring of published plans
    # ------------------------------------------------------------------

    @staticmethod
    def publication_entry_id(campaign_id: str, signature: str) -> str:
        """Deterministic ledger entry id for one (campaign, signature) pair.

        Re-publishing the very same signed plan therefore reuses the existing
        anchor (``append_event`` is idempotent on ``entry_id``) instead of
        appending a second, contradictory record.
        """
        digest = hashlib.sha256(f"{campaign_id}|{signature}".encode("utf-8")).hexdigest()
        return f"MKTPUB-{digest}"

    def anchor_publication(
        self,
        ledger: Any,
        campaign_payload: Dict[str, Any],
        integrity_payload: Dict[str, Any],
        *,
        publisher: str,
        assets_created: int = 0,
    ) -> Dict[str, Any]:
        """Append a ``marketing_campaign_published`` event to the platform ledger.

        Fails closed: the signature is re-verified first and any ledger error
        propagates, so a caller must not mark the campaign published (or mint
        media assets) unless this returns. Returns the anchor summary the
        caller should store next to the signature.
        """
        campaign_id = str((campaign_payload or {}).get("campaign_id") or "").strip()
        signature = str((integrity_payload or {}).get("signature") or "").strip()
        if not campaign_id or not signature:
            raise ValueError("campaign_id and signature are required to anchor a publication")
        if not self.verify_campaign_payload(campaign_payload, signature):
            raise ValueError("campaign signature does not verify; refusing to anchor")

        input_hash = str(campaign_payload.get("input_hash") or integrity_payload.get("input_hash") or "")
        entry_id = self.publication_entry_id(campaign_id, signature)
        memory_ledger = getattr(ledger, "transaction_ledger", None)
        reused = bool(memory_ledger is not None and entry_id in memory_ledger)
        scope = campaign_payload.get("scope") or {}

        entry = ledger.append_event(
            event_type=MARKETING_PUBLISH_EVENT_TYPE,
            entity_type=MARKETING_LEDGER_ENTITY_TYPE,
            entity_id=campaign_id,
            actor=publisher or "admin",
            source_system="marketing_sales_agent",
            status="published",
            entry_id=entry_id,
            payload={
                "campaign_id": campaign_id,
                "signature": signature,
                "signature_algorithm": str(integrity_payload.get("algorithm") or "hmac-sha256"),
                "input_hash": input_hash,
                "plan_version": _safe_int(campaign_payload.get("plan_version"), 1),
                "vertical": scope.get("vertical"),
                "objective": scope.get("objective"),
                "assets_created": int(assets_created or 0),
                "published_by": publisher or "admin",
            },
        )
        return {
            "entry_id": str(entry.get("id") or entry_id),
            "entry_hash": str(entry.get("entry_hash") or ""),
            "sequence_no": _safe_int(entry.get("sequence_no")),
            "event_type": MARKETING_PUBLISH_EVENT_TYPE,
            "anchored_at": str(entry.get("recorded_at") or entry.get("timestamp") or ""),
            "reused": reused,
        }

    def verify_publication(
        self,
        transaction_ledger: Any,
        campaign_payload: Dict[str, Any],
        integrity_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Check a stored campaign against its ledger anchor (read-only).

        ``anchored`` is true only when the ledger row exists *and* records the
        same signature and input hash the campaign carries now — a plan
        edited after publication (or a forged signature) fails even if the
        ``DESIGN_SETTINGS`` copy looks consistent with itself.
        """
        campaign_id = str((campaign_payload or {}).get("campaign_id") or "").strip()
        signature = str((integrity_payload or {}).get("signature") or "").strip()
        result: Dict[str, Any] = {
            "anchored": False,
            "entry_id": None,
            "signature_matches": False,
            "input_hash_matches": False,
            "signature_verified": bool(
                campaign_id and signature and self.verify_campaign_payload(campaign_payload, signature)
            ),
        }
        if not campaign_id or not signature:
            return result
        entry_id = self.publication_entry_id(campaign_id, signature)
        result["entry_id"] = entry_id
        try:
            entry = transaction_ledger.get(entry_id)
        except Exception:
            entry = None
        if not isinstance(entry, dict):
            return result
        recorded = entry.get("payload") if isinstance(entry.get("payload"), dict) else entry
        recorded_signature = str(recorded.get("signature") or "")
        recorded_input_hash = str(recorded.get("input_hash") or "")
        current_input_hash = str(campaign_payload.get("input_hash") or integrity_payload.get("input_hash") or "")
        result["signature_matches"] = hmac.compare_digest(recorded_signature, signature)
        result["input_hash_matches"] = hmac.compare_digest(recorded_input_hash, current_input_hash)
        result["entry_hash"] = str(entry.get("entry_hash") or "")
        result["sequence_no"] = _safe_int(entry.get("sequence_no"))
        result["anchored"] = bool(
            result["signature_verified"]
            and result["signature_matches"]
            and result["input_hash_matches"]
        )
        return result

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



# ---------------------------------------------------------------------------
# Agent runtime registration (discovery + health only; no behaviour change).
# ---------------------------------------------------------------------------
def _marketing_agent_health() -> Dict[str, Any]:
    """Read-only probe: reports whether a dedicated signing secret is configured."""
    info: Dict[str, Any] = {
        'status': 'ok',
        'initialized': _marketing_sales_agent_service is not None,
        'dedicated_secret_configured': bool(os.environ.get("PHINS_MARKETING_AGENT_SECRET")),
        'plan_version': PLAN_VERSION,
        'publish_event_type': MARKETING_PUBLISH_EVENT_TYPE,
    }
    if _marketing_sales_agent_service is not None:
        info['plan_cache'] = _marketing_sales_agent_service.plan_cache_stats()
    return info


try:
    from services.agent_runtime import AgentDescriptor as _AgentDescriptor, register as _register_agent
    _register_agent(_AgentDescriptor(
        id='marketing_sales',
        name='Marketing / Sales Agent',
        version='1.0.0',
        module=__name__,
        description=(
            'Generates HMAC-signed AI + BI campaign plans (sales playbooks, story '
            'outlines, article briefs, video blueprints, social distribution) for '
            'insurance, investment, and health-wallet growth.'
        ),
        entry_url='/admin-media.html',
        api={'method': 'GET', 'path': '/api/admin/marketing-sales-agent'},
        roles=('admin', 'media'),
        deterministic=True,
        sample_prompts=(
            'Build a retention campaign for the insurance vertical',
        ),
    ), health_fn=_marketing_agent_health)
except Exception as _reg_exc:  # pragma: no cover
    import logging as _logging
    _logging.getLogger('phins.marketing_sales_agent').warning(
        "marketing/sales agent registration skipped: %s", _reg_exc)
