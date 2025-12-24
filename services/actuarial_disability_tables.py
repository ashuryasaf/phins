"""
Actuarial tables for PHINS PHI product (Permanent Disability, ADL-based claims).

This module intentionally uses no external dependencies so it can run in the
current lightweight demo server and in constrained environments.

The rates here are *illustrative* but shaped to realistic monotonic behavior
and anchored to the requirement:
  - Age 50 has 3.0% annual probability of ADL-based permanent disability claim.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal

Jurisdiction = Literal["US", "UK"]


@dataclass(frozen=True)
class DisabilityRateRow:
    age: int
    annual_adl_claim_rate: float  # fraction (0.03 == 3%)

    @property
    def annual_adl_claim_rate_percent(self) -> float:
        return self.annual_adl_claim_rate * 100.0


def _linear_interpolate(x: float, x0: float, y0: float, x1: float, y1: float) -> float:
    if x1 == x0:
        return y0
    t = (x - x0) / (x1 - x0)
    return y0 + t * (y1 - y0)


def _rate_from_anchors(age: int, anchors: Dict[int, float]) -> float:
    """
    Piecewise-linear interpolation over anchor points.

    Args:
        age: integer age
        anchors: map age -> annual rate (fraction)
    """
    if age in anchors:
        return anchors[age]

    keys = sorted(anchors.keys())
    if age <= keys[0]:
        return anchors[keys[0]]
    if age >= keys[-1]:
        return anchors[keys[-1]]

    # Find surrounding anchors
    lo = keys[0]
    hi = keys[-1]
    for i in range(len(keys) - 1):
        a0 = keys[i]
        a1 = keys[i + 1]
        if a0 <= age <= a1:
            lo, hi = a0, a1
            break

    return _linear_interpolate(age, lo, anchors[lo], hi, anchors[hi])


def get_adl_disability_rate(jurisdiction: Jurisdiction, age: int) -> float:
    """
    Get annual probability (fraction) of a permanent disability ADL-based claim.

    Notes:
    - Rates are anchored so that age 50 is 3.0% for both US and UK.
    - UK rates are slightly higher at older ages to reflect different population assumptions
      (illustrative).
    """
    age = int(age)
    age = max(0, min(100, age))

    us_anchors: Dict[int, float] = {
        18: 0.0020,  # 0.20%
        25: 0.0040,  # 0.40%
        30: 0.0060,  # 0.60%
        35: 0.0090,  # 0.90%
        40: 0.0150,  # 1.50%
        45: 0.0220,  # 2.20%
        50: 0.0300,  # 3.00% (requirement)
        55: 0.0400,  # 4.00%
        60: 0.0550,  # 5.50%
        65: 0.0750,  # 7.50%
        70: 0.1000,  # 10.00%
        75: 0.1300,  # 13.00%
        80: 0.1600,  # 16.00%
        85: 0.1900,  # 19.00%
        90: 0.2200,  # 22.00%
        100: 0.2500,  # 25.00%
    }

    uk_anchors: Dict[int, float] = {
        18: 0.0018,  # 0.18%
        25: 0.0038,  # 0.38%
        30: 0.0058,  # 0.58%
        35: 0.0088,  # 0.88%
        40: 0.0145,  # 1.45%
        45: 0.0215,  # 2.15%
        50: 0.0300,  # 3.00% (requirement)
        55: 0.0410,  # 4.10%
        60: 0.0570,  # 5.70%
        65: 0.0780,  # 7.80%
        70: 0.1050,  # 10.50%
        75: 0.1370,  # 13.70%
        80: 0.1680,  # 16.80%
        85: 0.2000,  # 20.00%
        90: 0.2320,  # 23.20%
        100: 0.2650,  # 26.50%
    }

    anchors = us_anchors if jurisdiction.upper() == "US" else uk_anchors
    return float(_rate_from_anchors(age, anchors))


def build_disability_table(jurisdiction: Jurisdiction, age_min: int = 18, age_max: int = 100) -> List[DisabilityRateRow]:
    age_min = int(age_min)
    age_max = int(age_max)
    if age_min < 0:
        age_min = 0
    if age_max > 100:
        age_max = 100
    if age_max < age_min:
        age_min, age_max = age_max, age_min

    rows: List[DisabilityRateRow] = []
    for age in range(age_min, age_max + 1):
        rows.append(DisabilityRateRow(age=age, annual_adl_claim_rate=get_adl_disability_rate(jurisdiction, age)))
    return rows


__all__ = [
    "Jurisdiction",
    "DisabilityRateRow",
    "get_adl_disability_rate",
    "build_disability_table",
]

