"""Israel-pilot Aspire-Invest scale identity.

Closed-form planning math used by the pitch-dashboard configurator, the
printed pack, and tests. Risk premiums follow the published
``risk_reference_v1`` tables:

- life: ILS 0.25 per 1,000 of life sum per month
- disability: ILS 0.20 per 1,000 of disability sum per month
  (the switched disability table — not the life rate)

times the locked age curve ``f(x)``. Savings is a separate licensed flow:
it is not insurance GWP and is not split 25/75.

Default planning specimen: average age 42, issue ages 3–65, life face
ILS 1,000,000 (disability ILS 250,000 below 65), 30% of in-force elects
a 300% savings add-on.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from services.actuarial_service import (
    contract_benefit_sums_at_age,
    get_risk_reference_profile,
)
from services.pricing_kernel import risk_reference_v1_factor

NEW_ISSUES: Tuple[int, int, int] = (25_000, 75_000, 150_000)
YEARS: Tuple[int, int, int] = (2027, 2028, 2029)
PRIOR_PERSIST = 0.92
NEW_PERSIST = 0.96
PHINS_TAKE = 0.25

DEFAULTS: Dict[str, float] = {
    "avg_age": 42,
    "min_age": 3,
    "max_age": 65,
    "face": 1_000_000.0,
    "disability_share_pre": 0.25,
    "life_rate_per_1000": 0.25,
    "disability_rate_per_1000": 0.20,
    "savings_election": 0.30,
    "savings_addon": 3.00,
    "phins_take": PHINS_TAKE,
}


def published_table_rates(profile_id: Optional[str] = None) -> Dict[str, float]:
    """Rates currently filed on the risk-reference profile (live tables)."""
    profile = get_risk_reference_profile(profile_id)
    return {
        "life_rate_per_1000": float(profile["life_base_rate_per_1000_monthly"]),
        "disability_rate_per_1000": float(profile["disability_base_rate_per_1000_monthly"]),
        "profile_id": profile.get("id") or "phins_published_v1",
        "version": profile.get("version") or "",
    }


def quote_risk_premium(
    *,
    avg_age: float,
    face: float,
    life_rate_per_1000: float,
    disability_rate_per_1000: float,
    disability_share_pre: float = 0.25,
    max_age: float = 65,
) -> Dict[str, Any]:
    """Monthly / annual risk premium at the planning average age."""
    age = int(round(float(avg_age)))
    band = int(round(float(max_age)))
    sums = contract_benefit_sums_at_age(
        float(face),
        age,
        life_share_pre=1.0,
        life_share_post=0.25,
        disability_share_pre=float(disability_share_pre),
        disability_share_post=1.0,
        band_age=band,
    )
    factor = float(risk_reference_v1_factor(age))
    life_monthly = (
        (float(sums["life_sum"]) / 1000.0) * float(life_rate_per_1000) * factor
    )
    disability_monthly = 0.0
    if float(sums["disability_share"]) > 0.0:
        disability_monthly = (
            (float(sums["disability_sum"]) / 1000.0)
            * float(disability_rate_per_1000)
            * factor
        )
    total_monthly = life_monthly + disability_monthly
    annual = round(total_monthly * 12.0, 2)
    life_annual = round(life_monthly * 12.0, 2)
    disability_annual = round(disability_monthly * 12.0, 2)
    return {
        "avg_age": age,
        "age_factor": round(factor, 4),
        "face": round(float(face), 2),
        "life_sum": round(float(sums["life_sum"]), 2),
        "disability_sum": round(float(sums["disability_sum"]), 2),
        "life_rate_per_1000": float(life_rate_per_1000),
        "disability_rate_per_1000": float(disability_rate_per_1000),
        "life_monthly": round(life_monthly, 2),
        "disability_monthly": round(disability_monthly, 2),
        "total_monthly": round(total_monthly, 2),
        "annual_premium": annual,
        "life_annual": life_annual,
        "disability_annual": disability_annual,
    }


def _in_force_path(new_issues: Tuple[int, int, int] = NEW_ISSUES) -> List[Dict[str, int]]:
    eoy = 0
    rows: List[Dict[str, int]] = []
    for new in new_issues:
        opening = eoy
        persist = round(eoy * PRIOR_PERSIST)
        new_if = round(new * NEW_PERSIST)
        eoy = persist + new_if
        avg = int(round((opening + eoy) / 2.0))
        rows.append({
            "new_issues": int(new),
            "opening": int(opening),
            "eoy": int(eoy),
            "avg": avg,
        })
    return rows


def _shekel(value: float) -> int:
    """Nearest shekel (Python 3 half-even, matching the printed 2029 take split)."""
    return int(round(float(value)))


def compute_aspire_identity(
    *,
    avg_age: float = DEFAULTS["avg_age"],
    min_age: float = DEFAULTS["min_age"],
    max_age: float = DEFAULTS["max_age"],
    face: float = DEFAULTS["face"],
    disability_share_pre: float = DEFAULTS["disability_share_pre"],
    life_rate_per_1000: Optional[float] = None,
    disability_rate_per_1000: Optional[float] = None,
    savings_election: float = DEFAULTS["savings_election"],
    savings_addon: float = DEFAULTS["savings_addon"],
    phins_take: float = DEFAULTS["phins_take"],
    use_published_tables: bool = True,
) -> Dict[str, Any]:
    """Full closed-form identity. Every money line regenerates from inputs."""
    published = published_table_rates()
    life_rate = (
        float(published["life_rate_per_1000"])
        if life_rate_per_1000 is None and use_published_tables
        else float(
            DEFAULTS["life_rate_per_1000"]
            if life_rate_per_1000 is None
            else life_rate_per_1000
        )
    )
    dis_rate = (
        float(published["disability_rate_per_1000"])
        if disability_rate_per_1000 is None and use_published_tables
        else float(
            DEFAULTS["disability_rate_per_1000"]
            if disability_rate_per_1000 is None
            else disability_rate_per_1000
        )
    )

    errors: List[str] = []
    if face <= 0:
        errors.append("face must be positive")
    if life_rate < 0 or dis_rate < 0:
        errors.append("table rates must be non-negative")
    if not (0.0 <= float(savings_election) <= 1.0):
        errors.append("savings_election must be between 0 and 1")
    if float(savings_addon) < 0:
        errors.append("savings_addon must be non-negative")
    if not (0.0 < float(phins_take) < 1.0):
        errors.append("phins_take must be between 0 and 1")
    if float(min_age) > float(max_age):
        errors.append("min_age must be <= max_age")
    if errors:
        return {"error": errors[0], "errors": errors}

    quote = quote_risk_premium(
        avg_age=avg_age,
        face=face,
        life_rate_per_1000=life_rate,
        disability_rate_per_1000=dis_rate,
        disability_share_pre=disability_share_pre,
        max_age=max_age,
    )
    annual = float(quote["annual_premium"])
    path = _in_force_path()
    years: List[Dict[str, Any]] = []
    for year, row in zip(YEARS, path):
        gwp = float(row["avg"]) * annual
        phins = _shekel(gwp * float(phins_take))
        ins = _shekel(gwp) - phins if gwp == int(gwp) else _shekel(gwp - phins)
        # Keep PHINS + insurance = risk GWP in shekels.
        gwp_ils = _shekel(gwp) if abs(gwp - round(gwp)) < 1e-9 else _shekel(gwp)
        if phins + ins != gwp_ils:
            ins = gwp_ils - phins
        life_gwp = _shekel(gwp * (quote["life_annual"] / annual)) if annual else 0
        dis_gwp = gwp_ils - life_gwp
        sav = _shekel(gwp_ils * float(savings_election) * float(savings_addon))
        years.append({
            "year": year,
            "new_issues": row["new_issues"],
            "eoy_in_force": row["eoy"],
            "avg_in_force": row["avg"],
            "risk_gwp": gwp_ils,
            "life_gwp": life_gwp,
            "disability_gwp": dis_gwp,
            "phins_take": phins,
            "insurance_take": ins,
            "savings_flow": sav,
        })

    election = float(savings_election)
    addon = float(savings_addon)
    savings_multiple = round(election * addon, 6)
    electing_savings = round(annual * addon, 2)
    blended_outlay = round(annual * (1.0 + savings_multiple), 2)

    integrity = {
        "issued_sum": sum(NEW_ISSUES) == 250_000,
        "in_force_path": [r["eoy"] for r in path] == [24_000, 94_080, 230_554],
        "takes_sum_to_gwp": all(
            y["phins_take"] + y["insurance_take"] == y["risk_gwp"] for y in years
        ),
        "life_plus_disability_equals_gwp": all(
            y["life_gwp"] + y["disability_gwp"] == y["risk_gwp"] for y in years
        ),
        "savings_is_election_times_addon_times_gwp": all(
            y["savings_flow"] == _shekel(y["risk_gwp"] * savings_multiple)
            for y in years
        ),
        "avg_age_within_issue_band": float(min_age) <= float(avg_age) <= float(max_age),
        "disability_table_is_not_life_table": abs(life_rate - dis_rate) > 1e-12,
        "savings_not_split_25_75": True,
    }
    integrity["all_hold"] = all(integrity.values())

    return {
        "defaults": dict(DEFAULTS),
        "inputs": {
            "avg_age": int(round(float(avg_age))),
            "min_age": int(round(float(min_age))),
            "max_age": int(round(float(max_age))),
            "face": float(face),
            "disability_share_pre": float(disability_share_pre),
            "life_rate_per_1000": life_rate,
            "disability_rate_per_1000": dis_rate,
            "savings_election": election,
            "savings_addon": addon,
            "phins_take": float(phins_take),
        },
        "tables": published,
        "quote": quote,
        "years": years,
        "savings": {
            "election": election,
            "addon": addon,
            "portfolio_multiple": savings_multiple,
            "electing_policy_annual": electing_savings,
            "blended_customer_outlay": blended_outlay,
        },
        "data_integrity": integrity,
    }


def parse_identity_query(query: Dict[str, Any]) -> Dict[str, Any]:
    """Build compute() kwargs from a querystring-style dict of lists or scalars."""

    def _one(name: str) -> Optional[str]:
        raw = query.get(name)
        if raw is None:
            return None
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else None
        if raw is None or raw == "":
            return None
        return str(raw)

    def _float(name: str, default: Optional[float] = None) -> Optional[float]:
        raw = _one(name)
        if raw is None:
            return default
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    kwargs: Dict[str, Any] = {}
    mapping = {
        "avg_age": "avg_age",
        "min_age": "min_age",
        "max_age": "max_age",
        "face": "face",
        "disability_share_pre": "disability_share_pre",
        "life_rate_per_1000": "life_rate_per_1000",
        "disability_rate_per_1000": "disability_rate_per_1000",
        "savings_election": "savings_election",
        "savings_addon": "savings_addon",
        "phins_take": "phins_take",
    }
    for qname, kw in mapping.items():
        val = _float(qname, None)
        if val is not None:
            kwargs[kw] = val
        elif qname in ("life_rate_per_1000", "disability_rate_per_1000"):
            # omit so compute() pulls live published tables
            pass
        else:
            kwargs[kw] = DEFAULTS[kw]

    # Percent conveniences: savings_election_pct=30 → 0.30
    pct = _float("savings_election_pct", None)
    if pct is not None:
        kwargs["savings_election"] = pct / 100.0
    addon_pct = _float("savings_addon_pct", None)
    if addon_pct is not None:
        kwargs["savings_addon"] = addon_pct / 100.0
    return kwargs
