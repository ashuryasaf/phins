"""
PHINS Reinsurance Service (Scaffolding)
======================================

Provides a consistent interface for connecting to reinsurance providers (e.g. Swiss Re, Munich Re)
for risk hedging and portfolio protection.

This module intentionally ships with:
- Provider adapter interfaces
- Mock implementations (no external credentials required)
- Deterministic quoting logic for testing/BI demonstrations

Production integrations should:
- Use provider-specific APIs (OAuth/mTLS, signed payloads, etc.)
- Store only references to secrets (never hardcode)
- Persist bound contracts in the database with full audit trail
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
import hashlib
import os
from typing import Any, Dict, List, Optional, Protocol


def _now_iso() -> str:
    return datetime.now().isoformat()


def _stable_float(seed: str, low: float, high: float) -> float:
    """Deterministic pseudo-random float in [low, high] based on seed."""
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    # Use first 8 hex chars as integer
    n = int(h[:8], 16)
    r = (n % 10_000_000) / 10_000_000.0
    return low + (high - low) * r


@dataclass(frozen=True)
class ReinsuranceQuoteRequest:
    customer_id: Optional[str]
    portfolio_id: Optional[str]
    currency: str
    total_exposure: float
    expected_annual_premium: float
    expected_loss_ratio: float  # 0..1
    risk_band: str  # low/medium/high/very_high
    region: str
    line_of_business: str  # health/life/auto/property/business/multi


@dataclass
class ReinsuranceQuote:
    quote_id: str
    provider: str
    product: str  # quota_share / stop_loss / excess_of_loss
    currency: str
    attachment_point: float
    limit: float
    ceded_share_pct: float
    annual_premium: float
    fees: Dict[str, float]
    terms: Dict[str, Any]
    status: str  # indicative / firm / rejected
    created_at: str
    provider_request_id: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ReinsuranceProviderAdapter(Protocol):
    name: str

    def is_configured(self) -> bool:
        """Return True if provider credentials/config are present."""

    def quote(self, req: ReinsuranceQuoteRequest) -> List[ReinsuranceQuote]:
        """Return one or more reinsurance quote options."""


class BaseMockAdapter:
    """Base adapter with deterministic mock quoting."""

    name: str = "provider"

    def __init__(self):
        self._mode = os.environ.get(f"REINSURANCE_{self.name.upper().replace(' ', '_')}_MODE", "mock").lower()

    def is_configured(self) -> bool:
        # In mock mode, always "configured". In prod mode, require an API key placeholder.
        if self._mode == "mock":
            return True
        return bool(os.environ.get(f"REINSURANCE_{self.name.upper().replace(' ', '_')}_API_KEY"))

    def quote(self, req: ReinsuranceQuoteRequest) -> List[ReinsuranceQuote]:
        seed = f"{self.name}|{req.currency}|{req.total_exposure}|{req.expected_loss_ratio}|{req.risk_band}|{req.region}|{req.line_of_business}"
        provider_request_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]  # short deterministic ref

        # Simple, deterministic pricing model:
        # base rate increases with loss ratio and risk band, and provider "spread".
        risk_mult = {
            "low": 0.85,
            "medium": 1.0,
            "high": 1.25,
            "very_high": 1.55,
        }.get(req.risk_band, 1.0)
        provider_spread = _stable_float(seed + "|spread", 0.9, 1.15)
        base_rate = max(0.002, min(0.03, req.expected_loss_ratio * 0.04))  # 0.2%..3%
        annual_premium_base = req.total_exposure * base_rate * risk_mult * provider_spread

        # Offer 2 products: stop-loss and quota-share.
        attachment = req.total_exposure * _stable_float(seed + "|att", 0.02, 0.08)
        limit = req.total_exposure * _stable_float(seed + "|lim", 0.08, 0.20)
        ceded = round(_stable_float(seed + "|ceded", 0.15, 0.40) * 100, 2)

        def mk_quote(product: str, modifier: float) -> ReinsuranceQuote:
            quote_id = f"REQ-{provider_request_id}-{product[:3].upper()}"
            annual_premium = round(annual_premium_base * modifier, 2)
            fees = {
                "broker_fee": round(annual_premium * 0.01, 2),
                "platform_fee": round(annual_premium * 0.0025, 2),
            }
            terms = {
                "territory": req.region,
                "lob": req.line_of_business,
                "risk_band": req.risk_band,
                "confidence": round(_stable_float(seed + f"|conf|{product}", 0.65, 0.92), 3),
                "mode": self._mode,
            }
            return ReinsuranceQuote(
                quote_id=quote_id,
                provider=self.name,
                product=product,
                currency=req.currency,
                attachment_point=round(attachment, 2) if product != "quota_share" else 0.0,
                limit=round(limit, 2) if product != "quota_share" else round(req.total_exposure * (ceded / 100.0), 2),
                ceded_share_pct=ceded if product == "quota_share" else 0.0,
                annual_premium=annual_premium,
                fees=fees,
                terms=terms,
                status="indicative",
                created_at=_now_iso(),
                provider_request_id=provider_request_id,
            )

        return [
            mk_quote("stop_loss", modifier=1.00),
            mk_quote("quota_share", modifier=0.85),
        ]


class SwissReAdapter(BaseMockAdapter):
    name = "swiss_re"


class MunichReAdapter(BaseMockAdapter):
    name = "munich_re"


class ReinsuranceService:
    """
    Orchestrates multi-provider quoting and recommendation.
    """

    def __init__(self, adapters: Optional[List[ReinsuranceProviderAdapter]] = None):
        self.adapters: List[ReinsuranceProviderAdapter] = adapters or [
            SwissReAdapter(),
            MunichReAdapter(),
        ]

    def providers(self) -> List[Dict[str, Any]]:
        out = []
        for a in self.adapters:
            out.append({
                "name": a.name,
                "configured": bool(a.is_configured()),
            })
        return out

    def quote_all(self, req: ReinsuranceQuoteRequest) -> List[ReinsuranceQuote]:
        quotes: List[ReinsuranceQuote] = []
        for a in self.adapters:
            if not a.is_configured():
                continue
            quotes.extend(a.quote(req))
        # sort lowest premium first as a default “best price” view
        quotes.sort(key=lambda q: (q.annual_premium, q.provider, q.product))
        return quotes

    def recommend(self, quotes: List[ReinsuranceQuote], objective: str = "min_cost") -> Dict[str, Any]:
        """
        Recommend a quote based on objective:
        - min_cost: choose lowest annual_premium
        - best_confidence: choose highest confidence then lowest cost
        """
        if not quotes:
            return {"success": False, "error": "No quotes available"}

        def conf(q: ReinsuranceQuote) -> float:
            try:
                return float(q.terms.get("confidence", 0))
            except Exception:
                return 0.0

        if objective == "best_confidence":
            best = sorted(quotes, key=lambda q: (-conf(q), q.annual_premium))[0]
        else:
            best = sorted(quotes, key=lambda q: q.annual_premium)[0]

        return {
            "success": True,
            "objective": objective,
            "recommended_quote_id": best.quote_id,
            "recommended": best.to_dict(),
        }


_svc: Optional[ReinsuranceService] = None


def get_reinsurance_service() -> ReinsuranceService:
    global _svc
    if _svc is None:
        _svc = ReinsuranceService()
    return _svc

