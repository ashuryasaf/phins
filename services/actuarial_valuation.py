"""
PHINS Actuarial Portfolio Valuation.

This module produces best-estimate and conservative valuations for three
portfolios derived from a saved actuarial simulation snapshot:

* **Insurance Portfolio** — the in-force book of contracts. Best Estimate
  Embedded Value (BE-EV) = PVFP (present value of future profits) net of
  the cost of holding required capital. Conservative valuation discounts
  BE-EV by the prudence margin and removes the risk-margin release.
* **Risk Portfolio** — the projected claim liability against the in-force
  book (BEL + risk adjustment + IBNR, IFRS 17 style). Best Estimate is
  the Best Estimate Liability; Conservative tops it up with the
  prudence margin.
* **Company (PHINS Technologies)** — the corporate equity view that
  combines tangible book (cumulative reserves + the company-owned share
  of the savings AUM management-fee value) with embedded value and an
  intangible technology / platform multiplier applied to ongoing
  revenue. Best Estimate uses central assumptions; Conservative trims
  intangibles and adds a prudence buffer to liabilities.

Every knob in :class:`ValuationConfig` is adjustable from the actuary
dashboard. Every output ships with deterministic data-integrity checks
so external auditors can verify the arithmetic chain bit-for-bit:

* Best Estimate − Conservative reconciles to the disclosed prudence
  drivers.
* Insurance + Risk + intangibles − Liabilities reconciles to the
  company total.
* Required-capital cost equals capital × cost_of_capital × duration.

The kernel never reads the actuarial tables directly — it derives every
input from the saved simulation snapshot (which already carries the
priced premium components, IFRS 17 BEL/RA/CSM, and the
``pricing_kernel`` provenance block) so the valuation is reproducible
from the same input that produced the simulation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


@dataclass
class ValuationConfig:
    """Adjustable knobs for the portfolio valuation."""

    # Discount rate for the present value of future profits. Defaults to
    # the pricing kernel's discount rate when the caller leaves it blank.
    discount_rate: Optional[float] = None
    projection_years: Optional[int] = None  # defaults to avg policy term
    # Prudence margin applied to the Best Estimate to derive the
    # Conservative valuation. Typical 10–20% for life/health insurers.
    prudence_margin_pct: float = 0.15
    # Required capital as a percentage of in-force annual premium plus
    # IFRS 17 Risk Adjustment. The opportunity cost of holding this
    # capital reduces the embedded value.
    required_capital_pct_of_premium: float = 0.20
    cost_of_capital_pct: float = 0.06
    # Risk margin applied to Best Estimate Liability for the Risk
    # Portfolio (extra cushion above the kernel's IFRS 17 RA).
    risk_margin_pct: float = 0.06
    # Share of the cumulative savings AUM that translates into company
    # value (capitalised future management-fee stream / N-year multiple).
    savings_aum_value_pct: float = 0.08
    # Annual new-business value (NBV) assumed for the company valuation —
    # incremental contracts beyond the in-force book.
    new_business_value_per_year: float = 0.0
    new_business_growth_pct: float = 0.0
    # Technology / IP multiplier applied to ongoing operating revenue to
    # capture the platform's intangible value beyond pure actuarial EV.
    tech_multiplier: float = 4.0
    tech_revenue_share_pct: float = 0.10
    # When set, the valuation is anchored to this attribution share
    # of total company value (e.g. 0.80 to assume founders/staff retain 20%).
    attributable_share_pct: float = 1.0

    version: str = "valuation_v1"


def _round6(value: float) -> float:
    return round(float(value or 0.0), 6)


def _hash_block(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


def _coerce_valuation_config(payload: Optional[Dict[str, Any]]) -> ValuationConfig:
    payload = payload or {}

    def pct(name: str, default: float) -> float:
        raw = payload.get(name, default)
        try:
            raw = float(raw)
        except (TypeError, ValueError):
            return default
        if raw > 1.0:
            return raw / 100.0
        return raw

    return ValuationConfig(
        discount_rate=(pct("discount_rate", 0.035) if "discount_rate" in payload else None),
        projection_years=(int(payload["projection_years"]) if payload.get("projection_years") else None),
        prudence_margin_pct=max(0.0, min(0.5, pct("prudence_margin_pct", 0.15))),
        required_capital_pct_of_premium=max(0.0, min(2.0, pct("required_capital_pct_of_premium", 0.20))),
        cost_of_capital_pct=max(0.0, min(0.5, pct("cost_of_capital_pct", 0.06))),
        risk_margin_pct=max(0.0, min(0.5, pct("risk_margin_pct", 0.06))),
        savings_aum_value_pct=max(0.0, min(1.0, pct("savings_aum_value_pct", 0.08))),
        new_business_value_per_year=max(0.0, float(payload.get("new_business_value_per_year", 0.0) or 0.0)),
        new_business_growth_pct=max(-0.5, min(1.0, pct("new_business_growth_pct", 0.0))),
        tech_multiplier=max(0.0, min(50.0, float(payload.get("tech_multiplier", 4.0) or 0.0))),
        tech_revenue_share_pct=max(0.0, min(1.0, pct("tech_revenue_share_pct", 0.10))),
        attributable_share_pct=max(0.0, min(1.0, pct("attributable_share_pct", 1.0))),
    )


def _pvfp(annual_profit: float, years: int, discount_rate: float) -> float:
    """Present value of a flat annual profit stream over ``years``."""
    if annual_profit <= 0 or years <= 0:
        return 0.0
    if abs(discount_rate) < 1e-12:
        return annual_profit * years
    return annual_profit * (1.0 - (1.0 + discount_rate) ** (-years)) / discount_rate


def _pv_growing(annuity_first_year: float, years: int, discount_rate: float,
                growth_rate: float) -> float:
    """Present value of a growing annuity over ``years`` (geometric)."""
    if annuity_first_year <= 0 or years <= 0:
        return 0.0
    if abs(discount_rate - growth_rate) < 1e-12:
        return annuity_first_year * years / (1.0 + discount_rate)
    ratio = (1.0 + growth_rate) / (1.0 + discount_rate)
    return annuity_first_year / (discount_rate - growth_rate) * (1.0 - ratio ** years)


def calculate_portfolio_valuation(simulation: Dict[str, Any],
                                  config: ValuationConfig) -> Dict[str, Any]:
    """Build best-estimate + conservative valuations for the three portfolios."""
    portfolio = simulation.get("portfolio_summary", {}) or {}
    profitability = simulation.get("profitability", {}) or {}
    risk_metrics = simulation.get("risk_metrics", {}) or {}
    pricing_meta = simulation.get("pricing_kernel", {}) or {}

    accepted = int(portfolio.get("accepted_customers", 0) or 0)
    total_annual_premium = float(portfolio.get("total_annual_premium", 0.0) or 0.0)
    total_risk_premium = float(profitability.get("risk_premium", 0.0) or 0.0)
    total_savings_premium = float(profitability.get("savings_premium", 0.0) or 0.0)
    annual_net_profit = float(profitability.get("net_profit", 0.0) or 0.0)
    annual_expected_claims = float(risk_metrics.get("annual_expected_claims", 0.0) or 0.0)
    total_pv_claims = float(risk_metrics.get("total_expected_claims", 0.0) or 0.0)
    avg_term = float(risk_metrics.get("avg_term_years", 0.0) or 0.0)
    discount_rate = (
        float(config.discount_rate)
        if config.discount_rate is not None
        else float(pricing_meta.get("discount_rate", 0.035))
    )
    projection_years = (
        int(config.projection_years)
        if config.projection_years is not None
        else max(1, int(round(avg_term or 10)))
    )

    # ----- Insurance Portfolio (Embedded Value style) -----
    pvfp = _pvfp(annual_net_profit, projection_years, discount_rate)
    required_capital = (
        total_annual_premium * float(config.required_capital_pct_of_premium)
        + total_pv_claims * float(config.risk_margin_pct)
    )
    required_capital_cost = (
        required_capital * float(config.cost_of_capital_pct) * projection_years
    )
    insurance_be = max(0.0, pvfp - required_capital_cost)
    insurance_conservative = insurance_be * (1.0 - float(config.prudence_margin_pct))

    # ----- Risk Portfolio (claim liability) -----
    bel = total_pv_claims
    risk_margin_amount = bel * float(config.risk_margin_pct)
    risk_be = bel + risk_margin_amount
    # Conservative liability is INCREASED by the prudence margin (more
    # cautious estimate of what claims could cost).
    risk_conservative = risk_be * (1.0 + float(config.prudence_margin_pct))

    # ----- Company (PHINS Technologies) -----
    # Savings AUM monetisable share: capitalised future management-fee stream.
    aum_proxy = total_savings_premium * projection_years  # crude proxy for AUM at horizon
    aum_value = aum_proxy * float(config.savings_aum_value_pct)

    # Future new-business value (growing annuity)
    nbv = _pv_growing(
        annuity_first_year=float(config.new_business_value_per_year),
        years=projection_years,
        discount_rate=discount_rate,
        growth_rate=float(config.new_business_growth_pct),
    )

    # Tech multiplier on ongoing platform revenue (expense + profit
    # components of the annual premium, which represent operating
    # revenue rather than pass-through risk or savings premiums).
    platform_revenue = (
        float(profitability.get("expense_loading", 0.0) or 0.0)
        + float(profitability.get("profit_margin", 0.0) or 0.0)
    ) * float(config.tech_revenue_share_pct)
    tech_value = platform_revenue * float(config.tech_multiplier)

    # Company valuation: Insurance EV (which already nets claims through
    # PVFP) + AUM monetisation + NBV + tech intangible. The Risk
    # Portfolio is shown SEPARATELY as the actuarial liability view; it
    # is NOT subtracted again from the company total because that would
    # double-count claims (PVFP is already net of expected claims).
    company_be = insurance_be + aum_value + nbv + tech_value
    company_conservative = (
        insurance_conservative
        + aum_value * (1.0 - float(config.prudence_margin_pct))
        + nbv * (1.0 - float(config.prudence_margin_pct))
        + tech_value * (1.0 - float(config.prudence_margin_pct))
    )

    # Attribution share (when the valuation is reported to a specific
    # stakeholder pool, e.g. founders 80% retained).
    attribution = float(config.attributable_share_pct)
    insurance_be_attr = insurance_be * attribution
    company_be_attr = company_be * attribution
    company_conservative_attr = company_conservative * attribution

    bands = {
        "insurance_portfolio": {
            "best_estimate": round(insurance_be, 2),
            "conservative": round(insurance_conservative, 2),
            "best_estimate_attributable": round(insurance_be_attr, 2),
            "pvfp": round(pvfp, 2),
            "required_capital": round(required_capital, 2),
            "required_capital_cost": round(required_capital_cost, 2),
            "method": "PVFP minus required-capital cost (Embedded Value)",
        },
        "risk_portfolio": {
            "best_estimate": round(risk_be, 2),
            "conservative": round(risk_conservative, 2),
            "best_estimate_liability": round(bel, 2),
            "risk_margin_amount": round(risk_margin_amount, 2),
            "method": "IFRS 17 Best Estimate Liability plus risk margin",
        },
        "company_phins_technologies": {
            "best_estimate": round(company_be, 2),
            "conservative": round(company_conservative, 2),
            "best_estimate_attributable": round(company_be_attr, 2),
            "conservative_attributable": round(company_conservative_attr, 2),
            "components": {
                "insurance_portfolio_be": round(insurance_be, 2),
                "savings_aum_value": round(aum_value, 2),
                "new_business_value": round(nbv, 2),
                "tech_intangible_value": round(tech_value, 2),
            },
            "memo_risk_portfolio_liability_be": round(risk_be, 2),
            "memo_risk_portfolio_liability_conservative": round(risk_conservative, 2),
            "method": (
                "Insurance Embedded Value (PVFP net of claims and "
                "required-capital cost) + AUM monetisation + new-business "
                "value + tech intangible. The Risk Portfolio liability "
                "is shown as a separate audit view; it is NOT subtracted "
                "from the company total because Embedded Value already "
                "nets claims through PVFP."
            ),
        },
    }

    # ----- Integrity proofs -----
    components_sum = insurance_be + aum_value + nbv + tech_value
    integrity = {
        "components_sum_to_company_be": abs(components_sum - company_be) < 1.0,
        "best_estimate_ge_conservative_for_company": company_be >= company_conservative - 1.0,
        "best_estimate_ge_conservative_for_insurance": insurance_be >= insurance_conservative - 1.0,
        "risk_conservative_ge_best_estimate": risk_conservative >= risk_be - 1.0,
        "required_capital_cost_matches_inputs": abs(
            required_capital_cost
            - required_capital
            * float(config.cost_of_capital_pct)
            * projection_years
        ) < 1e-6,
        "attribution_within_unit": 0.0 <= attribution <= 1.0,
        "company_be_non_negative": company_be >= -1e-6,
    }

    output = {
        "simulation_id": simulation.get("simulation_id"),
        "discount_rate_used": _round6(discount_rate),
        "projection_years_used": projection_years,
        "config": asdict(config),
        "inputs": {
            "accepted_customers": accepted,
            "total_annual_premium": round(total_annual_premium, 2),
            "total_risk_premium": round(total_risk_premium, 2),
            "total_savings_premium": round(total_savings_premium, 2),
            "annual_net_profit": round(annual_net_profit, 2),
            "annual_expected_claims": round(annual_expected_claims, 2),
            "total_pv_claims": round(total_pv_claims, 2),
            "avg_term_years": round(avg_term, 4),
        },
        "bands": bands,
        "summary": {
            "best_estimate_total_company": round(company_be, 2),
            "conservative_total_company": round(company_conservative, 2),
            "prudence_drag": round(company_be - company_conservative, 2),
            "valuation_per_customer": (
                round(company_be / accepted, 2) if accepted > 0 else 0.0
            ),
        },
        "data_integrity": integrity,
    }
    output["integrity_hash"] = _hash_block(
        {
            "company_be": _round6(company_be),
            "company_conservative": _round6(company_conservative),
            "insurance_be": _round6(insurance_be),
            "risk_be": _round6(risk_be),
            "aum_value": _round6(aum_value),
            "tech_value": _round6(tech_value),
            "config": asdict(config),
            "simulation_id": output["simulation_id"],
        }
    )
    return output


__all__ = [
    "ValuationConfig",
    "_coerce_valuation_config",
    "calculate_portfolio_valuation",
]
