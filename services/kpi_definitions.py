"""
PHINS Canonical KPI Definitions
===============================
Single source of truth for cross-cutting KPI math (BI-1 in
``docs/INVESTOR_AI_BI_OPTIMIZATION_REVIEW.md``).

Historically the same KPI (e.g. "loss ratio") was recomputed in several places
with subtly different denominators:
- ``services/bi_analytics_service.py``
- ``services/financial_reporting_service.py``
- ``services/reserves_reporting_service.py``

Diverging definitions make it impossible to answer "which number is true?" for
investors and regulators. These pure functions are the canonical definitions;
every caller should import from here rather than re-deriving the formula.

Design rules:
- **Pure functions only.** No state, no I/O, no mutation. Safe to call anywhere,
  including inside cached BI paths and integrity checks.
- **Defensive division.** A zero or missing denominator returns ``0.0`` rather
  than raising, matching the platform's existing defensive numeric style.
- Formulas are intentionally identical to the values these dashboards already
  return, so adopting this module is a *refactor with no numeric change*.
"""

from typing import Any, Dict, Optional


def _num(value: Any, default: float = 0.0) -> float:
    """Best-effort numeric coercion (mirrors ``safe_float`` semantics)."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def loss_ratio_pct(total_claims_paid: Any, annual_premium_revenue: Any) -> float:
    """Loss ratio as a percentage: claims paid / earned premium.

    Canonical denominator is **annual premium revenue**. Returns ``0.0`` when
    there is no premium base.
    """
    paid = _num(total_claims_paid)
    premium = _num(annual_premium_revenue)
    if premium <= 0:
        return 0.0
    return (paid / premium) * 100.0


def approval_rate_pct(total_approved_amount: Any, total_claimed_amount: Any) -> float:
    """Claims approval rate by value: approved amount / claimed amount, in %."""
    approved = _num(total_approved_amount)
    claimed = _num(total_claimed_amount)
    if claimed <= 0:
        return 0.0
    return (approved / claimed) * 100.0


def receivables_ratio_pct(outstanding_receivables: Any, annual_revenue: Any) -> float:
    """Outstanding receivables as a percentage of annual revenue."""
    outstanding = _num(outstanding_receivables)
    revenue = _num(annual_revenue)
    if revenue <= 0:
        return 0.0
    return (outstanding / revenue) * 100.0


def net_worth(total_assets: Any, total_liabilities: Any) -> float:
    """Net worth = total assets - total liabilities."""
    return _num(total_assets) - _num(total_liabilities)


def monthly_recurring_revenue(
    policies: Dict[str, Any],
    active_status: str = "active",
    premium_field: str = "monthly_premium",
) -> float:
    """Sum of monthly premium across active policies (MRR)."""
    return sum(
        _num(p.get(premium_field, 0))
        for p in policies.values()
        if p.get("status") == active_status
    )


def annual_recurring_revenue(monthly_recurring: Any) -> float:
    """ARR derived from MRR."""
    return _num(monthly_recurring) * 12.0


def reserve_adequacy_ratio(claims_reserve: Any, monthly_revenue: Any, months: int = 3) -> float:
    """Claims reserve coverage relative to ``months`` of revenue.

    Used by the financial health score. Returns ``0.0`` when there is no
    revenue base.
    """
    reserve = _num(claims_reserve)
    monthly = _num(monthly_revenue)
    if monthly <= 0:
        return 0.0
    return reserve / (monthly * months)


__all__ = [
    "loss_ratio_pct",
    "approval_rate_pct",
    "receivables_ratio_pct",
    "net_worth",
    "monthly_recurring_revenue",
    "annual_recurring_revenue",
    "reserve_adequacy_ratio",
]
