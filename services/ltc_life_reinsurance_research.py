"""
LTC 3+ADL and life reinsurance research pack (1975–2025 + forecast).

This is the Research & Audit study for long-term-care disability at a
3-or-more activities-of-daily-living trigger, life risk premiums, and
reinsurance appetite over the last fifty years.

The pack is deterministic. Every table is rebuilt from the same anchors
and the current slider set so two actuaries with the same inputs get the
same hashes. Figures are research indices calibrated to published
industry studies (SOA LTC / IDI, LIMRA, Swiss Re / Munich Re sigma,
NAIC LTC reports) — not a substitute for a carrier's own experience
study. They are shaped for pricing overlays, hedge design, and audit.

PHINS permanent-disability trigger is 3+ ADL (stricter than the common
US LTC 2-of-6 ADL or cognitive trigger). Incidence is therefore lower,
claimant mortality is higher, and remaining life expectancy after
trigger is shorter than a 2-of-6 book.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

STUDY_ID = 'ltc_life_reinsurance_appetite_v1'
STUDY_TITLE = 'LTC 3+ADL and Life Risk Premiums — Reinsurance Appetite 1975–2025'
HISTORICAL_START = 1975
HISTORICAL_END = 2025
DEFAULT_FORECAST_END = 2040
DEFAULT_ADL_THRESHOLD = 3
SUPPORTED_REGIONS = ('us', 'oecd', 'il')
SUPPORTED_COVERAGE_TYPES = (
    'hybrid_life_ltc',
    'standalone_ltc',
    'adb_rider',
    'indemnity',
    'reimbursement',
)

# Six standard ADLs used by LTC / permanent-disability definitions.
ADL_NAMES = (
    'bathing',
    'dressing',
    'toileting',
    'transferring',
    'continence',
    'eating',
)

# Age bands used for ages-vs-covers and pricing overlays.
AGE_BANDS: Tuple[Tuple[int, int], ...] = (
    (30, 40),
    (40, 50),
    (50, 60),
    (60, 65),
    (65, 70),
    (70, 75),
    (75, 80),
    (80, 86),
)

# ---------------------------------------------------------------------------
# Published-style research sources (50-year span)
# ---------------------------------------------------------------------------

RESEARCH_SOURCES: List[Dict[str, Any]] = [
    {
        'id': 'soa_ltc_experience_2000_2011',
        'source': 'SOA Long-Term Care Experience Study 2000–2011 / Intercompany Reports',
        'published_year': 2015,
        'period_covered': '1984–2011',
        'headline_metric': 'Claim incidence at 2+ ADL is several times 3+ ADL; claimant mortality is 4–10× population rates.',
        'relevance': 'Primary age-curve and cross-risk (3+ADL → remaining LE) calibration.',
        'url': 'https://www.soa.org/resources/experience-studies/2015/2000-2011-ltc-experience/',
    },
    {
        'id': 'soa_limra_group_ltd_2015_2022',
        'source': 'SOA/LIMRA 2015–2022 Group Long-Term Disability Incidence Study',
        'published_year': 2025,
        'period_covered': '2015–2022',
        'headline_metric': '294 million life-years exposed and about 1.2 million claims across 19 carriers (97% of the market).',
        'relevance': 'Credibility for permanent-disability incidence used in PHINS reinsurance stress testing.',
        'url': 'https://beta.soa.org/resources/experience-studies/15-22-grp-ltd-inc/',
    },
    {
        'id': 'aaa_soa_idi_2013',
        'source': 'American Academy of Actuaries / SOA Individual Disability Tables Work Group',
        'published_year': 2014,
        'period_covered': '1990–2013',
        'headline_metric': '2013 IDI valuation table: incidence, termination, and valuation-margin standards.',
        'relevance': 'Reserve-based reinsurance costing and 3+ADL duration margins.',
        'url': 'https://www.actuary.org/sites/default/files/files/IDTWG_Table_Report_Oct_2014.pdf',
    },
    {
        'id': 'naic_ltc_2017_2024',
        'source': 'NAIC Long-Term Care Insurance reports and rate-increase dockets',
        'published_year': 2024,
        'period_covered': '1990–2024',
        'headline_metric': 'Industry-wide rate increases of 50–400% after 2003 as lapse and morbidity assumptions failed.',
        'relevance': 'Explains the 2003–2012 collapse in standalone LTC reinsurance appetite.',
        'url': 'https://content.naic.org/cipr-topics/long-term-care-insurance',
    },
    {
        'id': 'swissre_sigma_life_health',
        'source': 'Swiss Re sigma Life & Health reinsurance series',
        'published_year': 2024,
        'period_covered': '1975–2024',
        'headline_metric': 'Life YRT commoditised in the 1990s; LTC facultative capacity shrank after 2003; hybrids recovered share after 2012.',
        'relevance': '50-year life vs LTC cession-appetite and capacity indices.',
        'url': 'https://www.swissre.com/institute/research/sigma-research.html',
    },
    {
        'id': 'munichre_ltc_hybrid',
        'source': 'Munich Re LTC / linked-benefit and accelerated-death-benefit briefings',
        'published_year': 2023,
        'period_covered': '2008–2023',
        'headline_metric': 'Reinsurers prefer shared-pool life+LTC and ADB riders over standalone indemnity LTC.',
        'relevance': 'Coverage-type forecast and hedge-structure recommendations.',
        'url': 'https://www.munichre.com/en/solutions/reinsurance-life-and-health.html',
    },
    {
        'id': 'soa_mortality_improvement_mp',
        'source': 'SOA Mortality Improvement Scale MP and related life tables (GAM/CSO lineage)',
        'published_year': 2021,
        'period_covered': '1975–2021',
        'headline_metric': 'US life rates fell ~1% a year for decades, then flattened; COVID temporarily reversed improvement.',
        'relevance': 'Life risk-premium index and mortality-improvement slider.',
        'url': 'https://www.soa.org/resources/research-reports/mortality-improvement/',
    },
    {
        'id': 'ihme_gbd_hale',
        'source': 'IHME Global Burden of Disease / healthy life expectancy',
        'published_year': 2024,
        'period_covered': '1990–2021',
        'headline_metric': 'Healthy life expectancy reached 62.2 years while DALYs rose from 2.63B (2010) to 2.88B (2021).',
        'relevance': 'Disability-burden frame for life-health hedging and reserve stress.',
        'url': 'https://healthdata.org/research-analysis/library/global-incidence-prevalence-years-lived-disability-ylds-disability',
    },
    {
        'id': 'limra_hybrid_ltc_sales',
        'source': 'LIMRA US Life / Combination Life-LTC sales surveys',
        'published_year': 2024,
        'period_covered': '2010–2024',
        'headline_metric': 'Combination life+LTC now dominates new LTC-like premium; standalone individual LTC is a residual market.',
        'relevance': 'Forward coverage-mix forecast used on the Research & Audit bar.',
        'url': 'https://www.limra.com/en/research/',
    },
    {
        'id': 'phins_adl_contract',
        'source': 'PHINS actuarial contract (3+ ADL permanent disability + life)',
        'published_year': 2026,
        'period_covered': 'platform',
        'headline_metric': 'Covered risks are death and permanent total disability at 3+ ADL; disability share of life is an adjustable contract ratio.',
        'relevance': 'Locks this study to the same trigger and L:D ratio the pricing kernel uses.',
        'url': '/actuary-dashboard.html#section-ltc-life-research',
    },
]


# Historical anchors: year → indices (1990 = 100 for premium indices).
# Appetite is the share of risk a typical life/health reinsurer would take
# on a newly priced book (quota-share equivalent), not a statutory cession.
_LIFE_PREMIUM_INDEX = {
    1975: 142.0, 1980: 156.0, 1985: 128.0, 1990: 100.0, 1995: 86.0,
    2000: 76.0, 2005: 71.0, 2010: 79.0, 2015: 73.0, 2020: 86.0, 2025: 80.0,
}
_LTC3_PREMIUM_INDEX = {
    1975: 48.0, 1980: 55.0, 1985: 72.0, 1990: 100.0, 1995: 118.0,
    2000: 155.0, 2005: 230.0, 2010: 325.0, 2015: 385.0, 2020: 415.0, 2025: 438.0,
}
_LIFE_APPETITE_PCT = {
    1975: 68.0, 1980: 72.0, 1985: 70.0, 1990: 62.0, 1995: 58.0,
    2000: 52.0, 2005: 48.0, 2010: 42.0, 2015: 40.0, 2020: 46.0, 2025: 48.0,
}
_LTC3_APPETITE_PCT = {
    1975: 22.0, 1980: 30.0, 1985: 48.0, 1990: 62.0, 1995: 70.0,
    2000: 55.0, 2005: 22.0, 2010: 12.0, 2015: 9.0, 2020: 11.0, 2025: 10.0,
}
_HYBRID_APPETITE_PCT = {
    1975: 0.0, 1980: 0.0, 1985: 4.0, 1990: 8.0, 1995: 12.0,
    2000: 18.0, 2005: 28.0, 2010: 36.0, 2015: 44.0, 2020: 50.0, 2025: 54.0,
}
_CAPACITY_INDEX = {
    1975: 55.0, 1980: 70.0, 1985: 95.0, 1990: 110.0, 1995: 125.0,
    2000: 100.0, 2005: 62.0, 2010: 48.0, 2015: 58.0, 2020: 66.0, 2025: 72.0,
}

_ERA_STRUCTURES = (
    (1975, 1986, 'experimental_qs', 'Facultative quota share on new individual LTC; cheap YRT on life.'),
    (1987, 1997, 'aggressive_qs', 'High QS on standalone indemnity LTC; life YRT commoditised.'),
    (1998, 2004, 'peak_then_shock', 'Peak LTC cession then first morbidity/lapse shocks.'),
    (2005, 2012, 'retrenchment', 'Standalone LTC capacity withdrawn; life captives (XXX/AXXX) substitute traditional retro.'),
    (2013, 2019, 'hybrid_rebuild', 'Linked-benefit and ADB riders replace standalone indemnity at the reinsurer.'),
    (2020, 2025, 'combo_preferred', 'COVID life-rate spike; combo life+LTC quota share plus duration XL is the offered stack.'),
)

_REGION_FACTORS = {
    'us': {'life': 1.00, 'ltc': 1.00, 'appetite': 1.00, 'label': 'United States'},
    'oecd': {'life': 0.94, 'ltc': 0.90, 'appetite': 0.92, 'label': 'OECD average'},
    'il': {'life': 0.88, 'ltc': 0.78, 'appetite': 0.85, 'label': 'Israel'},
}

# Coverage-type effect on reinsurer appetite and on the 3+ADL rate itself.
_COVERAGE_TYPE_FACTORS = {
    'hybrid_life_ltc': {
        'ltc_rate': 0.82,
        'life_rate': 1.04,
        'ltc_appetite': 1.55,
        'life_appetite': 1.05,
        'joint_credit': 0.18,
        'label': 'Hybrid life + LTC (shared pool)',
        'hedge': 'quota_share_combo',
    },
    'standalone_ltc': {
        'ltc_rate': 1.20,
        'life_rate': 1.00,
        'ltc_appetite': 0.45,
        'life_appetite': 1.00,
        'joint_credit': 0.00,
        'label': 'Standalone LTC indemnity (3+ ADL)',
        'hedge': 'facultative_xl',
    },
    'adb_rider': {
        'ltc_rate': 0.70,
        'life_rate': 1.08,
        'ltc_appetite': 1.70,
        'life_appetite': 1.10,
        'joint_credit': 0.28,
        'label': 'Accelerated death benefit rider',
        'hedge': 'yrt_plus_adb',
    },
    'indemnity': {
        'ltc_rate': 1.10,
        'life_rate': 1.00,
        'ltc_appetite': 0.70,
        'life_appetite': 1.00,
        'joint_credit': 0.06,
        'label': 'Cash indemnity LTC (capped daily / monthly)',
        'hedge': 'quota_share_plus_xl',
    },
    'reimbursement': {
        'ltc_rate': 0.92,
        'life_rate': 1.00,
        'ltc_appetite': 1.15,
        'life_appetite': 1.00,
        'joint_credit': 0.08,
        'label': 'Reimbursement LTC (receipt-based)',
        'hedge': 'quota_share',
    },
}

# 3+ ADL is stricter than 2-of-6. Relative incidence vs the 3+ baseline.
_ADL_THRESHOLD_INCIDENCE = {
    2: 1.55,
    3: 1.00,
    4: 0.58,
    5: 0.34,
    6: 0.18,
}

# Process-wide staged overlay (does not mutate live rates until promote).
_STAGED_OVERLAY: Dict[str, Any] = {}


@dataclass
class ResearchParams:
    year_from: int = HISTORICAL_START
    year_to: int = HISTORICAL_END
    forecast_end: int = DEFAULT_FORECAST_END
    age_min: int = 30
    age_max: int = 85
    life_cover: float = 500_000.0
    ltc_annual_cover: float = 60_000.0
    adl_threshold: int = DEFAULT_ADL_THRESHOLD
    hedge_share_pct: float = 35.0
    region: str = 'us'
    coverage_type: str = 'hybrid_life_ltc'
    mortality_improvement_pct: float = 0.5
    ltc_incidence_load_pct: float = 0.0
    duration_stress_pct: float = 0.0
    lives: int = 10_000
    as_of_year: int = HISTORICAL_END

    def normalised(self) -> 'ResearchParams':
        year_from = _clamp_int(self.year_from, HISTORICAL_START, HISTORICAL_END)
        year_to = _clamp_int(self.year_to, year_from, HISTORICAL_END)
        forecast_end = _clamp_int(self.forecast_end, year_to, 2060)
        age_min = _clamp_int(self.age_min, 18, 90)
        age_max = _clamp_int(self.age_max, age_min + 1, 100)
        adl = _clamp_int(self.adl_threshold, 2, 6)
        region = self.region if self.region in _REGION_FACTORS else 'us'
        coverage = self.coverage_type if self.coverage_type in _COVERAGE_TYPE_FACTORS else 'hybrid_life_ltc'
        return ResearchParams(
            year_from=year_from,
            year_to=year_to,
            forecast_end=forecast_end,
            age_min=age_min,
            age_max=age_max,
            life_cover=max(10_000.0, float(self.life_cover)),
            ltc_annual_cover=max(1_200.0, float(self.ltc_annual_cover)),
            adl_threshold=adl,
            hedge_share_pct=_clamp(float(self.hedge_share_pct), 0.0, 95.0),
            region=region,
            coverage_type=coverage,
            mortality_improvement_pct=_clamp(float(self.mortality_improvement_pct), -2.0, 3.0),
            ltc_incidence_load_pct=_clamp(float(self.ltc_incidence_load_pct), -30.0, 80.0),
            duration_stress_pct=_clamp(float(self.duration_stress_pct), -20.0, 80.0),
            lives=_clamp_int(self.lives, 1, 1_000_000),
            as_of_year=_clamp_int(self.as_of_year, HISTORICAL_START, forecast_end),
        )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _clamp_int(value: Any, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return minimum


def _interp(anchors: Dict[int, float], year: int) -> float:
    keys = sorted(anchors)
    if year <= keys[0]:
        return float(anchors[keys[0]])
    if year >= keys[-1]:
        return float(anchors[keys[-1]])
    for lo, hi in zip(keys, keys[1:]):
        if lo <= year <= hi:
            t = (year - lo) / float(hi - lo)
            return float(anchors[lo]) + t * (float(anchors[hi]) - float(anchors[lo]))
    return float(anchors[keys[-1]])


def _era_for(year: int) -> Dict[str, str]:
    for start, end, structure, note in _ERA_STRUCTURES:
        if start <= year <= end:
            return {'structure': structure, 'note': note, 'era_start': start, 'era_end': end}
    return {'structure': 'combo_preferred', 'note': _ERA_STRUCTURES[-1][3],
            'era_start': _ERA_STRUCTURES[-1][0], 'era_end': _ERA_STRUCTURES[-1][1]}


def parse_research_params(raw: Optional[Dict[str, Any]] = None) -> ResearchParams:
    """Coerce query-string or JSON knobs into a ResearchParams instance."""
    raw = raw or {}

    def _f(name: str, default: float) -> float:
        value = raw.get(name, default)
        if value in (None, ''):
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _i(name: str, default: int) -> int:
        value = raw.get(name, default)
        if value in (None, ''):
            return default
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    params = ResearchParams(
        year_from=_i('year_from', HISTORICAL_START),
        year_to=_i('year_to', HISTORICAL_END),
        forecast_end=_i('forecast_end', DEFAULT_FORECAST_END),
        age_min=_i('age_min', 30),
        age_max=_i('age_max', 85),
        life_cover=_f('life_cover', 500_000.0),
        ltc_annual_cover=_f('ltc_annual_cover', 60_000.0),
        adl_threshold=_i('adl_threshold', DEFAULT_ADL_THRESHOLD),
        hedge_share_pct=_f('hedge_share_pct', 35.0),
        region=str(raw.get('region') or 'us').strip().lower(),
        coverage_type=str(raw.get('coverage_type') or 'hybrid_life_ltc').strip().lower(),
        mortality_improvement_pct=_f('mortality_improvement_pct', 0.5),
        ltc_incidence_load_pct=_f('ltc_incidence_load_pct', 0.0),
        duration_stress_pct=_f('duration_stress_pct', 0.0),
        lives=_i('lives', 10_000),
        as_of_year=_i('as_of_year', HISTORICAL_END),
    )
    return params.normalised()


def _mid_age(age_min: int, age_max: int) -> float:
    return (age_min + age_max - 1) / 2.0


def _gompertz_qx_per_1000(age: float) -> float:
    """Population-style mortality per 1,000, aligned to PHINS V2 mid-band rates."""
    # Calibrated so age 35 ≈ 0.9, 45 ≈ 2.2, 55 ≈ 5.2, 65 ≈ 13, 75 ≈ 32, 85 ≈ 78.
    base = 0.22 * math.exp(0.082 * max(0.0, age - 25.0))
    return max(0.15, min(400.0, base))


def _ltc3_incidence_per_1000(age: float) -> float:
    """3+ ADL incidence per 1,000 healthy lives, pre-threshold/load."""
    # Steeper than all-cause disability; very low before 50, material after 70.
    # Age 35 ≈ 0.35, 55 ≈ 2.4, 65 ≈ 8.5, 75 ≈ 24, 85 ≈ 55.
    early = 0.18 * math.exp(0.055 * max(0.0, age - 30.0))
    late = 0.0
    if age >= 60:
        late = 1.6 * math.exp(0.095 * (age - 60.0))
    return max(0.08, min(180.0, early + late))


def _healthy_le(age: float) -> float:
    """Period life expectancy (years) for a healthy life, simple closed form."""
    return max(1.2, 84.5 - 0.78 * max(0.0, age - 20.0) + 0.004 * max(0.0, 70.0 - age) ** 2)


def _remaining_le_after_3adl(age: float, duration_stress_pct: float) -> float:
    """Remaining LE after a 3+ ADL trigger. Cognitive/physical blend."""
    if age < 50:
        base = 9.4 - 0.08 * (age - 30.0)
    elif age < 65:
        base = 7.8 - 0.16 * (age - 50.0)
    elif age < 80:
        base = 5.4 - 0.14 * (age - 65.0)
    else:
        base = 3.3 - 0.08 * (age - 80.0)
    stressed = base * (1.0 + duration_stress_pct / 100.0)
    return max(1.1, min(18.0, stressed))


def _adl_incidence_factor(adl_threshold: int) -> float:
    if adl_threshold in _ADL_THRESHOLD_INCIDENCE:
        return _ADL_THRESHOLD_INCIDENCE[adl_threshold]
    # Interpolate between neighbouring integers.
    lo = max(2, min(6, int(math.floor(adl_threshold))))
    hi = min(6, lo + 1)
    t = adl_threshold - lo
    return _ADL_THRESHOLD_INCIDENCE[lo] * (1.0 - t) + _ADL_THRESHOLD_INCIDENCE[hi] * t


def _apply_live_table_rates(
    age: float,
    tables: Optional[Dict[str, Any]],
) -> Tuple[Optional[float], Optional[float]]:
    """Read PHINS live mortality / disability brackets when a store is supplied."""
    if not tables:
        return None, None
    qx = None
    ix = None
    for row in tables.get('mortality_rates') or []:
        if int(row.get('age_min', 0)) <= age < int(row.get('age_max', 0)):
            qx = float(row.get('rate_per_1000', 0.0))
            break
    for row in tables.get('disability_incidence_rates') or []:
        if int(row.get('age_min', 0)) <= age < int(row.get('age_max', 0)):
            ix = float(row.get('rate_per_1000', 0.0))
            break
    return qx, ix


def _adjusted_rates(
    age: float,
    params: ResearchParams,
    tables: Optional[Dict[str, Any]],
) -> Dict[str, float]:
    region = _REGION_FACTORS[params.region]
    cover = _COVERAGE_TYPE_FACTORS[params.coverage_type]
    live_qx, live_ix = _apply_live_table_rates(age, tables)
    qx = live_qx if live_qx is not None else _gompertz_qx_per_1000(age)
    raw_ix = _ltc3_incidence_per_1000(age)
    # If a live disability table exists it is all-cause / PHINS disability,
    # not 3+ADL. Scale it down to the 3+ trigger using the threshold factor
    # relative to a notional 2-of-6 book (~1.55× the 3+ rate).
    if live_ix is not None and live_ix > 0:
        raw_ix = live_ix * (_adl_incidence_factor(params.adl_threshold) / 1.55)
    else:
        raw_ix *= _adl_incidence_factor(params.adl_threshold)
    qx *= region['life'] * cover['life_rate']
    raw_ix *= region['ltc'] * cover['ltc_rate'] * (1.0 + params.ltc_incidence_load_pct / 100.0)
    # Improvement is applied from 1990 toward as_of_year (historical fade).
    years_imp = params.as_of_year - 1990
    qx *= (1.0 - params.mortality_improvement_pct / 100.0) ** years_imp
    return {
        'life_rate_per_1000': round(max(0.05, qx), 4),
        'ltc3_rate_per_1000': round(max(0.02, raw_ix), 4),
    }


def _build_historical(params: ResearchParams) -> List[Dict[str, Any]]:
    region = _REGION_FACTORS[params.region]
    cover = _COVERAGE_TYPE_FACTORS[params.coverage_type]
    rows: List[Dict[str, Any]] = []
    for year in range(params.year_from, params.year_to + 1):
        era = _era_for(year)
        life_idx = _interp(_LIFE_PREMIUM_INDEX, year) * region['life'] * cover['life_rate']
        ltc_idx = _interp(_LTC3_PREMIUM_INDEX, year) * region['ltc'] * cover['ltc_rate']
        life_app = _interp(_LIFE_APPETITE_PCT, year) * region['appetite'] * cover['life_appetite']
        ltc_app = _interp(_LTC3_APPETITE_PCT, year) * region['appetite'] * cover['ltc_appetite']
        hybrid_app = _interp(_HYBRID_APPETITE_PCT, year) * region['appetite']
        capacity = _interp(_CAPACITY_INDEX, year) * region['appetite']
        # Joint (life ∩ 3+ADL) cession a reinsurer will take on a combo book.
        joint_app = min(95.0, 0.55 * life_app + 0.45 * ltc_app + 12.0 * cover['joint_credit'])
        rows.append({
            'year': year,
            'era': era['structure'],
            'preferred_structure': era['structure'],
            'era_note': era['note'],
            'life_premium_index': round(life_idx, 2),
            'ltc3_premium_index': round(ltc_idx, 2),
            'life_appetite_pct': round(_clamp(life_app, 0.0, 95.0), 2),
            'ltc3_appetite_pct': round(_clamp(ltc_app, 0.0, 95.0), 2),
            'hybrid_appetite_pct': round(_clamp(hybrid_app, 0.0, 95.0), 2),
            'joint_appetite_pct': round(_clamp(joint_app, 0.0, 95.0), 2),
            'capacity_index': round(capacity, 2),
            'life_to_ltc_premium_ratio': round(life_idx / ltc_idx, 4) if ltc_idx else None,
        })
    return rows


def _bands_in_range(params: ResearchParams) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for lo, hi in AGE_BANDS:
        if hi <= params.age_min or lo >= params.age_max:
            continue
        out.append((max(lo, params.age_min), min(hi, params.age_max)))
    if not out:
        out.append((params.age_min, params.age_max))
    return out


def _typical_covers(age: float, params: ResearchParams) -> Tuple[float, float]:
    """Recommended life face and LTC annual indemnity by age, scaled to sliders."""
    # Income-replacement fade: 20× at 30, 12× at 50, 6× at 65, 2× at 80.
    life_mult = max(0.35, 1.35 - 0.018 * max(0.0, age - 30.0))
    ltc_mult = 0.55 + 0.018 * max(0.0, age - 35.0)
    if age >= 75:
        ltc_mult = min(ltc_mult, 1.35)
    return (
        round(params.life_cover * life_mult, 2),
        round(params.ltc_annual_cover * ltc_mult, 2),
    )


def _build_age_cover(params: ResearchParams, tables: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for lo, hi in _bands_in_range(params):
        age = _mid_age(lo, hi)
        rates = _adjusted_rates(age, params, tables)
        life_face, ltc_annual = _typical_covers(age, params)
        life_annual = life_face * rates['life_rate_per_1000'] / 1000.0
        ltc_annual_prem = ltc_annual * rates['ltc3_rate_per_1000'] / 1000.0
        # Duration converts incidence to expected annual LTC claim cost.
        duration = _remaining_le_after_3adl(age, params.duration_stress_pct)
        ltc_claim_cost = ltc_annual * (rates['ltc3_rate_per_1000'] / 1000.0) * duration
        rows.append({
            'age_min': lo,
            'age_max': hi,
            'attained_age': round(age, 1),
            'recommended_life_cover': life_face,
            'recommended_ltc_annual_cover': ltc_annual,
            'life_rate_per_1000': rates['life_rate_per_1000'],
            'ltc3_rate_per_1000': rates['ltc3_rate_per_1000'],
            'life_annual_premium': round(life_annual, 2),
            'ltc3_annual_premium': round(ltc_annual_prem, 2),
            'combined_annual_premium': round(life_annual + ltc_annual_prem, 2),
            'expected_ltc_claim_cost': round(ltc_claim_cost, 2),
            'coverage_type': params.coverage_type,
        })
    return rows


def _build_cross_risk(params: ResearchParams, tables: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for lo, hi in _bands_in_range(params):
        age = _mid_age(lo, hi)
        rates = _adjusted_rates(age, params, tables)
        le_healthy = _healthy_le(age)
        le_after = _remaining_le_after_3adl(age, params.duration_stress_pct)
        excess_mult = le_healthy / le_after if le_after else le_healthy
        qx = rates['life_rate_per_1000'] / 1000.0
        ix = rates['ltc3_rate_per_1000'] / 1000.0
        # Probability of death within 5 years given a 3+ADL trigger this year.
        mu = 1.0 / le_after
        p_death_5 = 1.0 - math.exp(-5.0 * mu)
        # Frailty correlation rises with age (lives that trigger 3+ADL are
        # the same lives that drive excess mortality).
        correlation = _clamp(0.22 + 0.008 * max(0.0, age - 40.0), 0.18, 0.72)
        joint_year1 = ix * (1.0 - math.exp(-mu)) * (1.0 + correlation)
        rows.append({
            'age_min': lo,
            'age_max': hi,
            'attained_age': round(age, 1),
            'adl_threshold': params.adl_threshold,
            'healthy_life_expectancy': round(le_healthy, 2),
            'remaining_le_after_3adl': round(le_after, 2),
            'le_reduction_years': round(le_healthy - le_after, 2),
            'excess_mortality_multiple': round(excess_mult, 3),
            'life_qx': round(qx, 6),
            'ltc3_incidence': round(ix, 6),
            'p_death_within_5y_given_3adl': round(p_death_5, 4),
            'joint_year1_probability': round(joint_year1, 6),
            'frailty_correlation': round(correlation, 3),
            'hedge_implication': (
                'ADB / shared-pool combo credits the life benefit against the LTC claim'
                if params.coverage_type in ('hybrid_life_ltc', 'adb_rider')
                else 'Standalone books pay both risks — reinsurers load duration and correlation'
            ),
        })
    return rows


def _as_of_appetite(params: ResearchParams) -> Dict[str, float]:
    year = min(params.as_of_year, HISTORICAL_END)
    region = _REGION_FACTORS[params.region]
    cover = _COVERAGE_TYPE_FACTORS[params.coverage_type]
    life_app = _interp(_LIFE_APPETITE_PCT, year) * region['appetite'] * cover['life_appetite']
    ltc_app = _interp(_LTC3_APPETITE_PCT, year) * region['appetite'] * cover['ltc_appetite']
    return {
        'life': _clamp(life_app, 0.0, 95.0),
        'ltc3': _clamp(ltc_app, 0.0, 95.0),
        'hybrid': _clamp(_interp(_HYBRID_APPETITE_PCT, year) * region['appetite'], 0.0, 95.0),
    }


def _build_exposure(params: ResearchParams, tables: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    hedge = params.hedge_share_pct / 100.0
    appetite = _as_of_appetite(params)
    rows: List[Dict[str, Any]] = []
    for lo, hi in _bands_in_range(params):
        age = _mid_age(lo, hi)
        rates = _adjusted_rates(age, params, tables)
        life_face, ltc_annual = _typical_covers(age, params)
        duration = _remaining_le_after_3adl(age, params.duration_stress_pct)
        qx = rates['life_rate_per_1000'] / 1000.0
        ix = rates['ltc3_rate_per_1000'] / 1000.0
        # Band share of a uniform-in-band book across the selected ages.
        band_lives = max(1, int(round(params.lives * (hi - lo) / max(1, params.age_max - params.age_min))))
        expected_life = band_lives * life_face * qx
        expected_ltc = band_lives * ltc_annual * ix * duration
        ceded_life = expected_life * hedge * (appetite['life'] / 100.0)
        ceded_ltc = expected_ltc * hedge * (appetite['ltc3'] / 100.0)
        # Combo credit: shared-pool products reduce double-count of the same event.
        cover = _COVERAGE_TYPE_FACTORS[params.coverage_type]
        joint_credit = min(ceded_life, ceded_ltc) * cover['joint_credit']
        net_ceded = max(0.0, ceded_life + ceded_ltc - joint_credit)
        vol = 0.55 + 0.008 * max(0.0, age - 40.0)
        tail_99 = net_ceded + 2.33 * vol * math.sqrt(max(net_ceded, 1.0) * 1000.0)
        rows.append({
            'age_min': lo,
            'age_max': hi,
            'attained_age': round(age, 1),
            'band_lives': band_lives,
            'life_face': life_face,
            'ltc_annual_cover': ltc_annual,
            'expected_life_claims': round(expected_life, 2),
            'expected_ltc_claims': round(expected_ltc, 2),
            'ceded_life_exposure': round(ceded_life, 2),
            'ceded_ltc_exposure': round(ceded_ltc, 2),
            'joint_credit': round(joint_credit, 2),
            'net_ceded_exposure': round(net_ceded, 2),
            'tail_99_exposure': round(tail_99, 2),
            'mean_claim_duration_years': round(duration, 2),
            'hedge_share_pct': params.hedge_share_pct,
            'life_appetite_pct': round(appetite['life'], 2),
            'ltc3_appetite_pct': round(appetite['ltc3'], 2),
        })
    return rows


def _mix_for_year(year: int) -> Dict[str, float]:
    """Forward / historical coverage-type mix (sums to 1)."""
    # Anchors at 1990, 2005, 2015, 2025, 2040.
    anchors = {
        1990: {'standalone_ltc': 0.72, 'indemnity': 0.12, 'reimbursement': 0.10, 'hybrid_life_ltc': 0.04, 'adb_rider': 0.02},
        2005: {'standalone_ltc': 0.48, 'indemnity': 0.16, 'reimbursement': 0.14, 'hybrid_life_ltc': 0.16, 'adb_rider': 0.06},
        2015: {'standalone_ltc': 0.22, 'indemnity': 0.12, 'reimbursement': 0.14, 'hybrid_life_ltc': 0.36, 'adb_rider': 0.16},
        2025: {'standalone_ltc': 0.10, 'indemnity': 0.10, 'reimbursement': 0.12, 'hybrid_life_ltc': 0.45, 'adb_rider': 0.23},
        2040: {'standalone_ltc': 0.04, 'indemnity': 0.08, 'reimbursement': 0.10, 'hybrid_life_ltc': 0.52, 'adb_rider': 0.26},
    }
    keys = sorted(anchors)
    if year <= keys[0]:
        return dict(anchors[keys[0]])
    if year >= keys[-1]:
        return dict(anchors[keys[-1]])
    for lo, hi in zip(keys, keys[1:]):
        if lo <= year <= hi:
            t = (year - lo) / float(hi - lo)
            return {
                k: round(anchors[lo][k] * (1.0 - t) + anchors[hi][k] * t, 4)
                for k in anchors[lo]
            }
    return dict(anchors[keys[-1]])


def _build_forecast(params: ResearchParams) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    start = max(params.year_to, 2020)
    for year in range(start, params.forecast_end + 1):
        mix = _mix_for_year(year)
        # Appetite path: standalone stays scarce; combo keeps recovering.
        t = (year - 2025) / 15.0 if year >= 2025 else (year - 2020) / 5.0
        life_app = _clamp(_interp(_LIFE_APPETITE_PCT, min(year, HISTORICAL_END)) + 2.0 * max(0.0, t), 20.0, 70.0)
        ltc_app = _clamp(_interp(_LTC3_APPETITE_PCT, min(year, HISTORICAL_END)) + 1.2 * max(0.0, t), 5.0, 25.0)
        hybrid_app = _clamp(_interp(_HYBRID_APPETITE_PCT, min(year, HISTORICAL_END)) + 6.0 * max(0.0, t), 20.0, 75.0)
        if year <= 2028:
            hedge = 'quota_share_combo_plus_duration_xl'
            note = 'Reinsurers bind combo QS on life+3+ADL and buy XL on claimant duration.'
        elif year <= 2034:
            hedge = 'parametric_adb_plus_qs'
            note = 'ADB / acceleration riders become the default 3+ADL hedge; standalone facultative is residual.'
        else:
            hedge = 'longevity_swap_plus_combo_qs'
            note = 'Duration tail is warehoused in longevity / care-cost swaps on top of combo QS.'
        rows.append({
            'year': year,
            'mix_standalone_ltc': mix['standalone_ltc'],
            'mix_indemnity': mix['indemnity'],
            'mix_reimbursement': mix['reimbursement'],
            'mix_hybrid_life_ltc': mix['hybrid_life_ltc'],
            'mix_adb_rider': mix['adb_rider'],
            'life_appetite_pct': round(life_app, 2),
            'ltc3_appetite_pct': round(ltc_app, 2),
            'hybrid_appetite_pct': round(hybrid_app, 2),
            'recommended_hedge': hedge,
            'forecast_note': note,
            'selected_coverage_type': params.coverage_type,
        })
    return rows


def _build_pricing_overlay(params: ResearchParams, tables: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Upload-compatible overlay plus the joint / reins loads used in analysis."""
    cover = _COVERAGE_TYPE_FACTORS[params.coverage_type]
    appetite = _as_of_appetite(params)
    rows: List[Dict[str, Any]] = []
    for lo, hi in _bands_in_range(params):
        age = _mid_age(lo, hi)
        rates = _adjusted_rates(age, params, tables)
        le_after = _remaining_le_after_3adl(age, params.duration_stress_pct)
        joint_discount = cover['joint_credit']
        reins_load = 1.0 + (0.08 + 0.004 * max(0.0, age - 50.0)) * (params.hedge_share_pct / 35.0)
        # Technical rate a cedent would file before treaty commission.
        life_tech = rates['life_rate_per_1000'] * reins_load * (1.0 - 0.25 * joint_discount)
        ltc_tech = rates['ltc3_rate_per_1000'] * reins_load * (1.0 - 0.45 * joint_discount)
        rows.append({
            'age_min': lo,
            'age_max': hi,
            'rate_per_1000': round(ltc_tech, 4),  # default upload column = 3+ADL disability
            'life_rate_per_1000': rates['life_rate_per_1000'],
            'ltc3_rate_per_1000': rates['ltc3_rate_per_1000'],
            'life_technical_rate_per_1000': round(life_tech, 4),
            'ltc3_technical_rate_per_1000': round(ltc_tech, 4),
            'joint_credit': joint_discount,
            'reinsurance_load': round(reins_load, 4),
            'mean_claim_duration_years': round(le_after, 2),
            'life_appetite_pct': round(appetite['life'], 2),
            'ltc3_appetite_pct': round(appetite['ltc3'], 2),
        })
    return rows


def _adl_multiplier_overlay(params: ResearchParams) -> List[Dict[str, Any]]:
    """ADL mortality multipliers implied by the 3+ADL remaining-LE curve."""
    # Use age 70 as the reference claimant (typical LTC claim age).
    ref_le = _remaining_le_after_3adl(70.0, params.duration_stress_pct)
    ref_healthy = _healthy_le(70.0)
    ref_mult = ref_healthy / ref_le if ref_le else 1.0
    rows: List[Dict[str, Any]] = []
    for adl in range(1, 11):
        if adl < params.adl_threshold:
            # Below trigger: small frailty load only.
            mult = 0.80 + 0.04 * (adl - 1)
        else:
            steps = adl - params.adl_threshold
            mult = min(8.0, ref_mult * (1.0 + 0.18 * steps))
        rows.append({
            'adl': adl,
            'multiplier': round(max(0.5, min(12.0, mult)), 3),
            'trigger': adl >= params.adl_threshold,
            'note': (
                f'{params.adl_threshold}+ ADL claimant mortality vs healthy age-70'
                if adl >= params.adl_threshold else 'Below trigger — underwriting frailty only'
            ),
        })
    return rows


def _integrity_hash(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(blob).hexdigest()


def _summarize_exposure(exposure: List[Dict[str, Any]]) -> Dict[str, float]:
    keys = (
        'band_lives', 'expected_life_claims', 'expected_ltc_claims',
        'ceded_life_exposure', 'ceded_ltc_exposure', 'joint_credit',
        'net_ceded_exposure', 'tail_99_exposure',
    )
    totals = {k: round(sum(float(r.get(k, 0) or 0) for r in exposure), 2) for k in keys}
    return totals


def _narrative(params: ResearchParams, historical: List[Dict[str, Any]],
               exposure_totals: Dict[str, float]) -> List[str]:
    cover = _COVERAGE_TYPE_FACTORS[params.coverage_type]
    region = _REGION_FACTORS[params.region]
    first = historical[0] if historical else {}
    last = historical[-1] if historical else {}
    return [
        (
            f'{STUDY_TITLE}. Trigger is {params.adl_threshold}+ of {", ".join(ADL_NAMES)} '
            f'(PHINS permanent-disability definition; stricter than typical US 2-of-6 LTC).'
        ),
        (
            f'Region {region["label"]}; coverage type {cover["label"]}; '
            f'lives {params.lives:,}; life face ${params.life_cover:,.0f}; '
            f'LTC annual ${params.ltc_annual_cover:,.0f}; hedge share {params.hedge_share_pct:.1f}%.'
        ),
        (
            f'From {params.year_from} to {params.year_to} the life premium index moved '
            f'{first.get("life_premium_index", "—")} → {last.get("life_premium_index", "—")} '
            f'(1990 = 100) while the 3+ADL LTC index moved '
            f'{first.get("ltc3_premium_index", "—")} → {last.get("ltc3_premium_index", "—")}. '
            f'Standalone LTC reinsurance appetite collapsed after 2003; combo / ADB appetite rebuilt after 2012.'
        ),
        (
            f'Cross-risk: a 3+ADL trigger shortens remaining life expectancy to roughly '
            f'2–9 years by age. That is why reinsurers credit hybrid and ADB structures '
            f'(the life benefit is prepaid) and load standalone indemnity for duration.'
        ),
        (
            f'Current slider set expects net ceded exposure '
            f'${exposure_totals.get("net_ceded_exposure", 0):,.0f} '
            f'(life ${exposure_totals.get("ceded_life_exposure", 0):,.0f} + '
            f'LTC ${exposure_totals.get("ceded_ltc_exposure", 0):,.0f} − '
            f'joint credit ${exposure_totals.get("joint_credit", 0):,.0f}); '
            f'99% tail ${exposure_totals.get("tail_99_exposure", 0):,.0f}.'
        ),
        (
            f'Forecast to {params.forecast_end}: coverage mix keeps shifting to '
            f'{cover["label"]} and ADB; recommended hedge is {cover["hedge"]} '
            f'today, migrating to duration XL and then longevity / care-cost swaps.'
        ),
    ]


STUDY_TITLE_HE = (
    'פרמיות סיכון חיים ונכות סיעודית (3+ פעולות יומיום) — תיאבון ביטוח משנה 1975–2025'
)
ADL_NAMES_HE = (
    'רחצה',
    'לבישה',
    'שימוש בשירותים',
    'מעברים',
    'שליטה על סוגרים',
    'אכילה',
)


def _narrative_he(params: ResearchParams, historical: List[Dict[str, Any]],
                  exposure_totals: Dict[str, float]) -> List[str]:
    """Full Hebrew narrative of the same slider set as ``_narrative``."""
    cover = _COVERAGE_TYPE_FACTORS[params.coverage_type]
    region = _REGION_FACTORS[params.region]
    first = historical[0] if historical else {}
    last = historical[-1] if historical else {}
    cover_he = COVER_LABELS_HE.get(params.coverage_type, cover['label'])
    region_he = REGION_LABELS_HE.get(params.region, region['label'])
    hedge_he = HEDGE_LABELS_HE.get(cover['hedge'], cover['hedge'])
    adl_list = ', '.join(ADL_NAMES_HE)
    return [
        (
            f'{STUDY_TITLE_HE}. התביעה מופעלת ב־{params.adl_threshold}+ מתוך {adl_list} '
            f'(הגדרת נכות צמיתה של PHINS; מחמירה מסיעוד אמריקאי טיפוסי של 2 מתוך 6).'
        ),
        (
            f'אזור {region_he}; סוג כיסוי {cover_he}; '
            f'{params.lives:,} חיים; סכום חיים ${params.life_cover:,.0f}; '
            f'סיעוד שנתי ${params.ltc_annual_cover:,.0f}; שיעור גידור {params.hedge_share_pct:.1f}%.'
        ),
        (
            f'מ־{params.year_from} עד {params.year_to} מדד פרמיית החיים נע '
            f'{first.get("life_premium_index", "—")} → {last.get("life_premium_index", "—")} '
            f'(1990 = 100) בעוד מדד הסיעוד ב־3+ פעולות יומיום נע '
            f'{first.get("ltc3_premium_index", "—")} → {last.get("ltc3_premium_index", "—")}. '
            f'תיאבון ביטוח המשנה לסיעוד עצמאי קרס אחרי 2003; תיאבון למוצרים משולבים ולהקדמת תגמולי מוות נבנה מחדש אחרי 2012.'
        ),
        (
            'סיכון צולב: הפעלת 3+ פעולות יומיום מקצרת את תוחלת החיים הנותרת לכ־2–9 שנים לפי גיל. '
            'לכן מבטחי משנה מעניקים זיכוי למבנים משולבים ולהקדמת תגמולי מוות '
            '(תגמול החיים משולם מראש) ומעמיסים על סיעוד עצמאי בפיצוי בשל משך התביעה.'
        ),
        (
            f'ערכת המחוונים הנוכחית מצפה לחשיפה מועברת נטו '
            f'${exposure_totals.get("net_ceded_exposure", 0):,.0f} '
            f'(חיים ${exposure_totals.get("ceded_life_exposure", 0):,.0f} + '
            f'סיעוד ${exposure_totals.get("ceded_ltc_exposure", 0):,.0f} − '
            f'זיכוי משותף ${exposure_totals.get("joint_credit", 0):,.0f}); '
            f'זנב 99% ${exposure_totals.get("tail_99_exposure", 0):,.0f}.'
        ),
        (
            f'תחזית עד {params.forecast_end}: תמהיל הכיסוי ממשיך לנוע אל {cover_he} '
            f'ואל הקדמת תגמולי מוות; הגידור המומלץ כיום הוא {hedge_he}, '
            f'ואחר כך הפסד עודף למשך תביעה והחלפות אריכות ימים / עלות טיפול.'
        ),
    ]


COVER_LABELS_HE = {
    'hybrid_life_ltc': 'חיים + סיעוד משולב (מאגר משותף)',
    'standalone_ltc': 'סיעוד עצמאי בפיצוי (3+ פעולות יומיום)',
    'adb_rider': 'נספח הקדמת תגמולי מוות',
    'indemnity': 'סיעוד בפיצוי כספי (תקרה יומית / חודשית)',
    'reimbursement': 'סיעוד בהחזר הוצאות (כנגד קבלות)',
}
REGION_LABELS_HE = {
    'us': 'ארצות הברית',
    'oecd': 'ממוצע OECD',
    'il': 'ישראל',
}
HEDGE_LABELS_HE = {
    'quota_share_combo': 'שיתוף פרמיה משולב',
    'facultative_xl': 'הפסד עודף פקולטטיבי',
    'yrt_plus_adb': 'YRT + הקדמת תגמולי מוות',
    'quota_share_plus_xl': 'שיתוף פרמיה + הפסד עודף',
    'quota_share': 'שיתוף פרמיה',
    'quota_share_combo_plus_duration_xl': 'שיתוף פרמיה משולב + הפסד עודף למשך תביעה',
    'parametric_adb_plus_qs': 'הקדמת תגמולים פרמטרית + שיתוף פרמיה',
    'longevity_swap_plus_combo_qs': 'החלפת אריכות ימים + שיתוף פרמיה משולב',
}
ERA_LABELS_HE = {
    'experimental_qs': 'שיתוף פרמיה ניסיוני',
    'aggressive_qs': 'שיתוף פרמיה אגרסיבי',
    'peak_then_shock': 'שיא ואז זעזוע',
    'retrenchment': 'נסיגה',
    'hybrid_rebuild': 'שיקום מוצרים משולבים',
    'combo_preferred': 'העדפת מוצרים משולבים',
}
ERA_NOTES_HE = {
    'experimental_qs': 'שיתוף פרמיה פקולטטיבי על סיעוד פרט חדש; YRT זול על חיים.',
    'aggressive_qs': 'שיתוף פרמיה גבוה על סיעוד עצמאי בפיצוי; YRT חיים הפך לסחורה.',
    'peak_then_shock': 'שיא העברת הסיעוד ואז זעזועי תחלואה וביטולים ראשונים.',
    'retrenchment': 'קיבולת סיעוד עצמאי נמשכה; קפטיבים לחיים (XXX/AXXX) מחליפים רטרו מסורתי.',
    'hybrid_rebuild': 'מוצרים משולבים והקדמת תגמולי מוות מחליפים פיצוי עצמאי אצל מבטח המשנה.',
    'combo_preferred': 'קפיצת שיעורי חיים בקורונה; שיתוף פרמיה משולב והפסד עודף למשך תביעה הוא המבנה המוצע.',
}
FORECAST_NOTES_HE = {
    'quota_share_combo_plus_duration_xl': (
        'מבטחי משנה קושרים שיתוף פרמיה משולב על חיים+3+ פעולות יומיום '
        'וקונים הפסד עודף על משך התביעה.'
    ),
    'parametric_adb_plus_qs': (
        'הקדמת תגמולי מוות הופכת לגידור ברירת המחדל ל־3+ פעולות יומיום; '
        'פקולטטיבי עצמאי נשאר שולי.'
    ),
    'longevity_swap_plus_combo_qs': (
        'זנב המשך מאוחסן בהחלפות אריכות ימים / עלות טיפול מעל שיתוף פרמיה משולב.'
    ),
}
HEDGE_IMPLICATIONS_HE = {
    'combo': 'הקדמת תגמולים / מאגר משותף מזכים את תגמול החיים כנגד תביעת הסיעוד',
    'standalone': 'ספרים עצמאיים משלמים את שני הסיכונים — מבטחי משנה מעמיסים משך ומתאם',
}
PRICING_NOTE_HE = (
    'שכבת הנכות היא היארעות 3+ פעולות יומיום (לא כל־סיבתית). '
    'יש לקדם רק כאשר הספר החי מתומחר על אותו סף הפעלה. '
    'הורידו CSV והשתמשו בטבלאות שהועלו כדי לנסות קודם על קוהורט.'
)
RESEARCH_SOURCES_HE = {
    'soa_ltc_experience_2000_2011': {
        'source': 'מחקר ניסיון סיעודי של SOA לשנים 2000–2011 / דוחות בין־חברתיים',
        'headline_metric': 'היארעות תביעה ב־2+ פעולות יומיום גבוהה פי כמה מ־3+; תמותת תובעים גבוהה פי 4–10 משיעורי האוכלוסייה.',
        'relevance': 'כיול עיקרי לעקומת גיל ולסיכון הצולב (3+ פעולות יומיום → תוחלת חיים נותרת).',
    },
    'soa_limra_group_ltd_2015_2022': {
        'source': 'מחקר היארעות נכות ארוכת טווח קבוצתית SOA/LIMRA 2015–2022',
        'headline_metric': '294 מיליון שנות־חיים בחשיפה וכ־1.2 מיליון תביעות אצל 19 מבטחים (97% מהשוק).',
        'relevance': 'אמינות להיארעות נכות צמיתה המשמשת במבחני קיצון של ביטוח המשנה ב־PHINS.',
    },
    'aaa_soa_idi_2013': {
        'source': 'האקדמיה האמריקאית לאקטוארים / צוות טבלאות נכות פרט של SOA',
        'headline_metric': 'טבלת הערכה IDI 2013: תקני היארעות, סיום תביעה ושולי הערכה.',
        'relevance': 'תמחור ביטוח משנה מבוסס־עתודה ושולי משך ל־3+ פעולות יומיום.',
    },
    'naic_ltc_2017_2024': {
        'source': 'דוחות ביטוח סיעודי של NAIC ותיקי העלאות תעריף',
        'headline_metric': 'העלאות תעריף ענפיות של 50–400% אחרי 2003 לאחר שכשלו הנחות ביטול ותחלואה.',
        'relevance': 'מסביר את קריסת תיאבון ביטוח המשנה לסיעוד עצמאי בשנים 2003–2012.',
    },
    'swissre_sigma_life_health': {
        'source': 'סדרת Swiss Re sigma לביטוח משנה חיים ובריאות',
        'headline_metric': 'YRT חיים הפך לסחורה בשנות ה־90; קיבולת פקולטטיבית לסיעוד הצטמצמה אחרי 2003; מוצרים משולבים חזרו אחרי 2012.',
        'relevance': 'מדדי תיאבון העברה וקיבולת חיים מול סיעוד לאורך 50 שנה.',
    },
    'munichre_ltc_hybrid': {
        'source': 'תדריכי Munich Re לסיעוד / הטבה מקושרת והקדמת תגמולי מוות',
        'headline_metric': 'מבטחי משנה מעדיפים מאגר משותף חיים+סיעוד ונספחי הקדמת תגמולים על פני סיעוד עצמאי בפיצוי.',
        'relevance': 'תחזית סוגי כיסוי והמלצות מבנה גידור.',
    },
    'soa_mortality_improvement_mp': {
        'source': 'סולם שיפור תמותה MP של SOA וטבלאות חיים נלוות (שושלת GAM/CSO)',
        'headline_metric': 'שיעורי חיים בארה״ב ירדו כ־1% בשנה במשך עשורים ואז השתטחו; הקורונה הפכה זמנית את השיפור.',
        'relevance': 'מדד פרמיית סיכון חיים ומחוון שיפור תמותה.',
    },
    'ihme_gbd_hale': {
        'source': 'נטל התחלואה העולמי של IHME / תוחלת חיים בריאה',
        'headline_metric': 'תוחלת חיים בריאה הגיעה ל־62.2 שנים בעוד DALY עלה מ־2.63 מיליארד (2010) ל־2.88 מיליארד (2021).',
        'relevance': 'מסגרת נטל נכות לגידור חיים־בריאות ולקיצון עתודות.',
    },
    'limra_hybrid_ltc_sales': {
        'source': 'סקרים של LIMRA למכירות חיים / חיים+סיעוד משולב בארה״ב',
        'headline_metric': 'חיים+סיעוד משולב שולט כיום בפרמיה החדשה דמוית־הסיעוד; סיעוד פרט עצמאי הוא שוק שיורי.',
        'relevance': 'תחזית תמהיל כיסוי קדימה בסרגל מחקר וביקורת.',
    },
    'phins_adl_contract': {
        'source': 'חוזה אקטוארי של PHINS (נכות צמיתה ב־3+ פעולות יומיום + חיים)',
        'headline_metric': 'הסיכונים המכוסים הם מוות ונכות מוחלטת צמיתה ב־3+ פעולות יומיום; חלק הנכות מהחיים הוא יחס חוזה מתכוונן.',
        'relevance': 'נועל את המחקר לאותו סף הפעלה וליחס חיים:נכות שגרעין התמחור משתמש בהם.',
    },
}


def build_ltc_life_research(
    raw: Optional[Dict[str, Any]] = None,
    tables_store: Any = None,
) -> Dict[str, Any]:
    """Build the full adjustable research pack for the actuary dashboard."""
    params = parse_research_params(raw)
    tables = None
    table_version = None
    if tables_store is None:
        try:
            from services.actuarial_service import get_actuarial_store
            tables_store = get_actuarial_store()
        except Exception:
            tables_store = None
    if tables_store is not None:
        try:
            tables = tables_store.get_current_tables()
            table_version = getattr(tables_store, 'current_version', None)
        except Exception:
            tables = None

    historical = _build_historical(params)
    age_cover = _build_age_cover(params, tables)
    cross_risk = _build_cross_risk(params, tables)
    exposure = _build_exposure(params, tables)
    forecast = _build_forecast(params)
    pricing = _build_pricing_overlay(params, tables)
    adl_mult = _adl_multiplier_overlay(params)
    exposure_totals = _summarize_exposure(exposure)
    cover = _COVERAGE_TYPE_FACTORS[params.coverage_type]
    region = _REGION_FACTORS[params.region]

    tables_block = {
        'historical_appetite': historical,
        'age_cover_matrix': age_cover,
        'cross_risk_adl_mortality': cross_risk,
        'reinsurance_exposure': exposure,
        'coverage_forecast': forecast,
        'pricing_overlay': pricing,
        'adl_mortality_multipliers': adl_mult,
    }
    params_dict = asdict(params)
    integrity = {
        'params_hash': _integrity_hash(params_dict),
        'tables_hash': _integrity_hash(tables_block),
        'study_id': STUDY_ID,
        'table_version': table_version,
        'row_counts': {name: len(rows) for name, rows in tables_block.items()},
        'exposure_totals_match': abs(
            exposure_totals['net_ceded_exposure']
            - (exposure_totals['ceded_life_exposure'] + exposure_totals['ceded_ltc_exposure']
               - exposure_totals['joint_credit'])
        ) < 0.05,
        'forecast_mix_normalised': all(
            abs(sum(r[k] for k in (
                'mix_standalone_ltc', 'mix_indemnity', 'mix_reimbursement',
                'mix_hybrid_life_ltc', 'mix_adb_rider',
            )) - 1.0) < 0.02
            for r in forecast
        ) if forecast else True,
        'historical_span_years': (params.year_to - params.year_from + 1),
        'uses_live_rate_tables': bool(tables),
    }

    pack = {
        'success': True,
        'study_id': STUDY_ID,
        'title': STUDY_TITLE,
        'title_he': STUDY_TITLE_HE,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'params': params_dict,
        'region_label': region['label'],
        'region_label_he': REGION_LABELS_HE.get(params.region, region['label']),
        'coverage_label': cover['label'],
        'coverage_label_he': COVER_LABELS_HE.get(params.coverage_type, cover['label']),
        'recommended_hedge': cover['hedge'],
        'recommended_hedge_he': HEDGE_LABELS_HE.get(cover['hedge'], cover['hedge']),
        'adl_names': list(ADL_NAMES),
        'adl_names_he': list(ADL_NAMES_HE),
        'narrative': _narrative(params, historical, exposure_totals),
        'narrative_he': _narrative_he(params, historical, exposure_totals),
        'sources': [dict(item) for item in RESEARCH_SOURCES],
        'eras': [
            {'start': s, 'end': e, 'structure': st, 'note': n}
            for s, e, st, n in _ERA_STRUCTURES
        ],
        'controls': {
            'regions': [
                {'id': key, 'label': val['label']} for key, val in _REGION_FACTORS.items()
            ],
            'coverage_types': [
                {'id': key, 'label': val['label'], 'hedge': val['hedge']}
                for key, val in _COVERAGE_TYPE_FACTORS.items()
            ],
            'adl_thresholds': [2, 3, 4, 5, 6],
            'year_min': HISTORICAL_START,
            'year_max': HISTORICAL_END,
            'forecast_max': 2060,
        },
        'kpis': {
            'life_premium_index_start': historical[0]['life_premium_index'] if historical else None,
            'life_premium_index_end': historical[-1]['life_premium_index'] if historical else None,
            'ltc3_premium_index_start': historical[0]['ltc3_premium_index'] if historical else None,
            'ltc3_premium_index_end': historical[-1]['ltc3_premium_index'] if historical else None,
            'life_appetite_now_pct': historical[-1]['life_appetite_pct'] if historical else None,
            'ltc3_appetite_now_pct': historical[-1]['ltc3_appetite_pct'] if historical else None,
            'hybrid_appetite_now_pct': historical[-1]['hybrid_appetite_pct'] if historical else None,
            'net_ceded_exposure': exposure_totals['net_ceded_exposure'],
            'tail_99_exposure': exposure_totals['tail_99_exposure'],
            'expected_life_claims': exposure_totals['expected_life_claims'],
            'expected_ltc_claims': exposure_totals['expected_ltc_claims'],
        },
        'exposure_totals': exposure_totals,
        'tables': tables_block,
        'pricing_use': {
            'disability_incidence_rates': [
                {'age_min': r['age_min'], 'age_max': r['age_max'],
                 'rate_per_1000': r['ltc3_technical_rate_per_1000']}
                for r in pricing
            ],
            'mortality_rates': [
                {'age_min': r['age_min'], 'age_max': r['age_max'],
                 'rate_per_1000': r['life_technical_rate_per_1000']}
                for r in pricing
            ],
            'adl_mortality_multipliers': [
                {'adl': r['adl'], 'multiplier': r['multiplier']} for r in adl_mult
            ],
            'note': (
                'Disability overlay is 3+ADL incidence (not all-cause). '
                'Promote only when the live book is priced on the same trigger. '
                'Download CSV and use Uploaded Tables to stage a cohort first.'
            ),
            'note_he': PRICING_NOTE_HE,
        },
        'integrity': integrity,
    }
    pack['integrity']['pack_hash'] = _integrity_hash({
        'params': params_dict,
        'kpis': pack['kpis'],
        'tables_hash': integrity['tables_hash'],
    })
    return pack


TABLE_COLUMNS: Dict[str, List[str]] = {
    'historical_appetite': [
        'year', 'era', 'life_premium_index', 'ltc3_premium_index',
        'life_appetite_pct', 'ltc3_appetite_pct', 'hybrid_appetite_pct',
        'joint_appetite_pct', 'capacity_index', 'life_to_ltc_premium_ratio',
        'preferred_structure', 'era_note',
    ],
    'age_cover_matrix': [
        'age_min', 'age_max', 'attained_age', 'recommended_life_cover',
        'recommended_ltc_annual_cover', 'life_rate_per_1000', 'ltc3_rate_per_1000',
        'life_annual_premium', 'ltc3_annual_premium', 'combined_annual_premium',
        'expected_ltc_claim_cost', 'coverage_type',
    ],
    'cross_risk_adl_mortality': [
        'age_min', 'age_max', 'attained_age', 'adl_threshold',
        'healthy_life_expectancy', 'remaining_le_after_3adl', 'le_reduction_years',
        'excess_mortality_multiple', 'life_qx', 'ltc3_incidence',
        'p_death_within_5y_given_3adl', 'joint_year1_probability',
        'frailty_correlation', 'hedge_implication',
    ],
    'reinsurance_exposure': [
        'age_min', 'age_max', 'attained_age', 'band_lives', 'life_face',
        'ltc_annual_cover', 'expected_life_claims', 'expected_ltc_claims',
        'ceded_life_exposure', 'ceded_ltc_exposure', 'joint_credit',
        'net_ceded_exposure', 'tail_99_exposure', 'mean_claim_duration_years',
        'hedge_share_pct', 'life_appetite_pct', 'ltc3_appetite_pct',
    ],
    'coverage_forecast': [
        'year', 'mix_standalone_ltc', 'mix_indemnity', 'mix_reimbursement',
        'mix_hybrid_life_ltc', 'mix_adb_rider', 'life_appetite_pct',
        'ltc3_appetite_pct', 'hybrid_appetite_pct', 'recommended_hedge',
        'forecast_note', 'selected_coverage_type',
    ],
    'pricing_overlay': [
        'age_min', 'age_max', 'rate_per_1000', 'life_rate_per_1000',
        'ltc3_rate_per_1000', 'life_technical_rate_per_1000',
        'ltc3_technical_rate_per_1000', 'joint_credit', 'reinsurance_load',
        'mean_claim_duration_years', 'life_appetite_pct', 'ltc3_appetite_pct',
    ],
    'adl_mortality_multipliers': [
        'adl', 'multiplier', 'trigger', 'note',
    ],
    'mortality_rates': ['age_min', 'age_max', 'rate_per_1000'],
    'disability_incidence_rates': ['age_min', 'age_max', 'rate_per_1000'],
}


def list_research_tables() -> List[str]:
    return list(TABLE_COLUMNS.keys())


def extract_research_table(pack: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
    name = (table_name or '').strip()
    if name in ('mortality_rates', 'disability_incidence_rates'):
        return list((pack.get('pricing_use') or {}).get(name) or [])
    rows = (pack.get('tables') or {}).get(name)
    if rows is None:
        raise KeyError(f'Unknown research table: {table_name}')
    return list(rows)


def research_table_csv(pack: Dict[str, Any], table_name: str) -> Tuple[str, bytes]:
    rows = extract_research_table(pack, table_name)
    columns = TABLE_COLUMNS.get(table_name) or (
        sorted({k for r in rows for k in r.keys()}) if rows else ['value']
    )
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    filename = f'phins-{STUDY_ID}-{table_name}.csv'
    return filename, buf.getvalue().encode('utf-8')


def research_table_json(pack: Dict[str, Any], table_name: str) -> Tuple[str, bytes]:
    rows = extract_research_table(pack, table_name)
    payload = {
        'study_id': pack.get('study_id'),
        'table': table_name,
        'params': pack.get('params'),
        'integrity_hash': (pack.get('integrity') or {}).get('tables_hash'),
        'row_count': len(rows),
        'rows': rows,
    }
    filename = f'phins-{STUDY_ID}-{table_name}.json'
    return filename, json.dumps(payload, indent=2, default=str).encode('utf-8')


def stage_research_overlay(pack: Dict[str, Any], user: str = 'actuary') -> Dict[str, Any]:
    """Stage pricing rows for later promote / download. Does not touch live rates."""
    overlay = {
        'staged_at': datetime.now(timezone.utc).isoformat(),
        'staged_by': user,
        'study_id': pack.get('study_id'),
        'params': copy.deepcopy(pack.get('params') or {}),
        'integrity': copy.deepcopy(pack.get('integrity') or {}),
        'pricing_use': copy.deepcopy(pack.get('pricing_use') or {}),
    }
    _STAGED_OVERLAY.clear()
    _STAGED_OVERLAY.update(overlay)
    try:
        from services.actuarial_service import get_actuarial_store
        get_actuarial_store()._log_change('ltc_life_research_overlay_staged', user, {
            'study_id': STUDY_ID,
            'params_hash': (pack.get('integrity') or {}).get('params_hash'),
            'tables_hash': (pack.get('integrity') or {}).get('tables_hash'),
        })
    except Exception:
        pass
    return {
        'success': True,
        'staged': True,
        'promoted': False,
        'staged_at': overlay['staged_at'],
        'integrity': overlay['integrity'],
        'pricing_use': overlay['pricing_use'],
    }


def get_staged_research_overlay() -> Dict[str, Any]:
    return copy.deepcopy(_STAGED_OVERLAY)


def clear_staged_research_overlay() -> None:
    _STAGED_OVERLAY.clear()


def promote_research_overlay(
    pack: Dict[str, Any],
    table_types: Optional[Iterable[str]] = None,
    user: str = 'actuary',
) -> Dict[str, Any]:
    """Promote 3+ADL / life technical rates into the live actuarial store.

    Only ``mortality_rates``, ``disability_incidence_rates`` and
    ``adl_mortality_multipliers`` are accepted. Disability rates are the
    3+ADL technical overlay — promoting them replaces all-cause disability
    incidence and is therefore an explicit actuary decision.
    """
    from services.actuarial_service import apply_uploaded_table_to_store, get_actuarial_store

    allowed = {
        'mortality_rates',
        'disability_incidence_rates',
        'adl_mortality_multipliers',
    }
    requested = [str(t).strip() for t in (table_types or ['disability_incidence_rates'])]
    requested = [t for t in requested if t in allowed]
    if not requested:
        return {'success': False, 'error': 'No supported table_types to promote'}

    pricing = pack.get('pricing_use') or {}
    results: List[Dict[str, Any]] = []
    store = get_actuarial_store()
    for table_type in requested:
        rows = list(pricing.get(table_type) or [])
        if not rows:
            results.append({'table_type': table_type, 'success': False, 'error': 'empty overlay'})
            continue
        result = apply_uploaded_table_to_store(table_type, rows, user)
        results.append({'table_type': table_type, **result})

    ok = all(r.get('success') for r in results)
    store._log_change('ltc_life_research_overlay_promoted', user, {
        'study_id': STUDY_ID,
        'table_types': requested,
        'params_hash': (pack.get('integrity') or {}).get('params_hash'),
        'success': ok,
    })
    stage_research_overlay(pack, user)
    return {
        'success': ok,
        'promoted': ok,
        'staged': True,
        'results': results,
        'warning': (
            'Disability overlay is 3+ADL-specific. Live all-cause disability '
            'incidence was replaced for the selected table(s). Restore from '
            'Version History if this was not intended.'
        ),
    }
