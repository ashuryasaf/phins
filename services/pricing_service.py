"""
Pricing logic for PHINS products.

This file provides production-shaped pricing primitives while remaining
dependency-free for the current codebase.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional

from services.actuarial_disability_tables import Jurisdiction, get_adl_disability_rate


@dataclass(frozen=True)
class PhiPricingResult:
    product: str
    jurisdiction: Jurisdiction
    age: int
    coverage_amount: float
    annual_risk_rate: float  # fraction
    operational_reinsurance_load: float  # fraction (0.5 = 50%)
    savings_percentage: float  # fraction (0.9 = 90%)

    annual_risk_cost: float
    annual_total_premium: float
    annual_risk_allocation: float
    annual_savings_allocation: float

    monthly_total_premium: float
    monthly_risk_allocation: float
    monthly_savings_allocation: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product": self.product,
            "jurisdiction": self.jurisdiction,
            "age": self.age,
            "coverage_amount": self.coverage_amount,
            "annual_risk_rate": self.annual_risk_rate,
            "annual_risk_rate_percent": self.annual_risk_rate * 100.0,
            "operational_reinsurance_load": self.operational_reinsurance_load,
            "operational_reinsurance_load_percent": self.operational_reinsurance_load * 100.0,
            "savings_percentage": self.savings_percentage,
            "savings_percentage_percent": self.savings_percentage * 100.0,
            "risk_percentage": 1.0 - self.savings_percentage,
            "risk_percentage_percent": (1.0 - self.savings_percentage) * 100.0,
            "annual_risk_cost": self.annual_risk_cost,
            "annual_total_premium": self.annual_total_premium,
            "annual_risk_allocation": self.annual_risk_allocation,
            "annual_savings_allocation": self.annual_savings_allocation,
            "monthly_total_premium": self.monthly_total_premium,
            "monthly_risk_allocation": self.monthly_risk_allocation,
            "monthly_savings_allocation": self.monthly_savings_allocation,
        }


def _to_fraction(value: Any, *, assume_percent_if_gt_1: bool = True) -> float:
    """
    Normalize a user-provided value into a fraction.

    Examples:
      - 0.5 -> 0.5
      - 50  -> 0.5 (when assume_percent_if_gt_1=True)
    """
    try:
        v = float(value)
    except Exception:
        return 0.0
    if assume_percent_if_gt_1 and v > 1.0:
        return v / 100.0
    return v


def price_phi_permanent_disability(
    *,
    coverage_amount: float,
    age: int,
    jurisdiction: Jurisdiction = "US",
    operational_reinsurance_load: float = 0.50,
    savings_percentage: float = 0.25,
    product: Literal["phi_disability"] = "phi_disability",
) -> PhiPricingResult:
    """
    PHI pricing with an investable savings component.

    Requirements implemented:
      - Disability/ADL annual risk rate comes from a UK/US actuarial table.
      - Example logic: if age 50 risk rate = 3% and coverage=100,000 then:
          risk_cost = 0.03 * 100,000
          total_risk_cost_with_load = risk_cost * (1 + load_factor)
        Annual premium then depends on desired savings split:
          total_premium = total_risk_cost_with_load / risk_percentage
          savings_allocation = total_premium - total_risk_cost_with_load

    Where:
      risk_percentage = 1 - savings_percentage
    """
    age_i = int(age)
    cov = float(coverage_amount)
    cov = max(0.0, cov)

    load = float(operational_reinsurance_load)
    load = max(0.0, load)

    savings = float(savings_percentage)
    # allow up to 95% savings; keep at least 5% risk allocation so the math stays sane
    if savings < 0.0:
        savings = 0.0
    if savings > 0.95:
        savings = 0.95
    risk_pct = max(0.05, 1.0 - savings)

    annual_risk_rate = get_adl_disability_rate(jurisdiction, age_i)

    # Risk cost (pure expected risk) and loaded cost
    annual_risk_cost = cov * annual_risk_rate
    annual_risk_cost_loaded = annual_risk_cost * (1.0 + load)

    # Total premium must fund the loaded risk cost, while allowing savings allocation.
    annual_total_premium = annual_risk_cost_loaded / risk_pct if risk_pct > 0 else annual_risk_cost_loaded

    annual_risk_allocation = annual_risk_cost_loaded
    annual_savings_allocation = max(0.0, annual_total_premium - annual_risk_allocation)

    monthly_total = annual_total_premium / 12.0
    monthly_risk = annual_risk_allocation / 12.0
    monthly_savings = annual_savings_allocation / 12.0

    # Round only for presentation; keep floats in the result for JSON friendliness.
    def r2(x: float) -> float:
        return round(float(x), 2)

    return PhiPricingResult(
        product=product,
        jurisdiction=jurisdiction,
        age=age_i,
        coverage_amount=r2(cov),
        annual_risk_rate=float(annual_risk_rate),
        operational_reinsurance_load=float(load),
        savings_percentage=float(savings),
        annual_risk_cost=r2(annual_risk_cost_loaded),
        annual_total_premium=r2(annual_total_premium),
        annual_risk_allocation=r2(annual_risk_allocation),
        annual_savings_allocation=r2(annual_savings_allocation),
        monthly_total_premium=r2(monthly_total),
        monthly_risk_allocation=r2(monthly_risk),
        monthly_savings_allocation=r2(monthly_savings),
    )


def price_policy(policy_data: Dict[str, Any], *, default_jurisdiction: Jurisdiction = "US") -> Dict[str, Any]:
    """
    Unified pricing entry point used by the web server.
    """
    policy_type = (policy_data.get("type") or "disability").lower()
    age = int(policy_data.get("age", 30))
    coverage_amount = float(policy_data.get("coverage_amount", 100000))
    jurisdiction = (policy_data.get("jurisdiction") or policy_data.get("country") or default_jurisdiction)
    jurisdiction = "UK" if str(jurisdiction).upper() in ("UK", "GB", "GBR") else "US"

    # Savings/investment adjustable split (supports 25, 50, 90 etc)
    savings_percentage = _to_fraction(policy_data.get("savings_percentage", 25))
    operational_reinsurance_load = _to_fraction(policy_data.get("operational_reinsurance_load", 50))

    if policy_type in ("disability", "phi", "phi_disability", "permanent_disability"):
        result = price_phi_permanent_disability(
            coverage_amount=coverage_amount,
            age=age,
            jurisdiction=jurisdiction,  # type: ignore[arg-type]
            operational_reinsurance_load=operational_reinsurance_load,
            savings_percentage=savings_percentage,
        )
        return {
            "annual": result.annual_total_premium,
            "monthly": result.monthly_total_premium,
            "quarterly": round(result.annual_total_premium / 4.0, 2),
            "breakdown": result.to_dict(),
        }

    # Fallback for other policy types (kept simple for now)
    base_premium = {
        "life": 1200,
        "health": 800,
        "auto": 600,
        "property": 1500,
        "business": 3000,
    }.get(policy_type, 1000)
    age_factor = 1.0 + (max(0, age - 25) * 0.02)
    coverage_factor = coverage_amount / 100000
    annual = base_premium * age_factor * coverage_factor
    return {
        "annual": round(annual, 2),
        "monthly": round(annual / 12.0, 2),
        "quarterly": round(annual / 4.0, 2),
        "breakdown": {
            "product": policy_type,
            "jurisdiction": jurisdiction,
            "age": age,
            "coverage_amount": coverage_amount,
        },
    }


__all__ = [
    "PhiPricingResult",
    "price_phi_permanent_disability",
    "price_policy",
]

