"""
Long-term care residential services — market, regulation and hedging strategy.

Deterministic research pack for the actuary dashboard (Research & Audit bar).
It sits beside ``ltc_life_reinsurance_research`` and reuses that study's 3+ADL
incidence and duration curves so the hedge model is priced on the same trigger
the PHINS contract uses.

Scope (private institutions vs public institutions vs home care):

* a 50-year history (1975–2025) of spending, cost of care, payer mix and
  market structure anchored on published series (CMS NHE, OECD Health at a
  Glance, KFF, CareScout/Genworth, MedPAC, Taub Center, NII/State Comptroller,
  company filings);
* a 50-year outlook (2026–2075) built from UN population shares, healthy
  ageing, setting mix and relative care-cost inflation, under four scenarios;
* market structure, workforce, accommodation standards and regulation across
  the main OECD jurisdictions;
* main operators, REITs and home-care platforms with revenue and margin;
* TAM / SAM / SOM by setting and milestone year;
* a hedge model that offsets a PHINS 3+ADL book with operator, care real
  estate and home-care exposure;
* SWOT, case studies and the source register.

Every figure carries a ``figure_basis`` (``published``, ``derived``,
``estimate``, ``projection`` or ``model``) and ``source_ids`` that resolve to
``RESEARCH_SOURCES``. Tables are rebuilt from the same parameters each time
and sealed with sha256 hashes; the integrity block records every arithmetic
identity the pack must satisfy (TAM ≥ SAM ≥ SOM, payer shares sum to 100,
setting mix sums to 100, hedge allocation sums to 100, source ids resolve).

Nothing in this module writes to live rate tables; it is research only.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.ltc_life_reinsurance_research import (
    AGE_BANDS,
    _adl_incidence_factor,
    _clamp,
    _clamp_int,
    _interp,
    _ltc3_incidence_per_1000,
    _mid_age,
    _remaining_le_after_3adl,
)

STUDY_ID = 'ltc_residential_market_strategy_v1'
STUDY_TITLE = (
    'Long-Term Care Residential Services — Market, Regulation and Hedging Strategy 1975–2075'
)
STUDY_TITLE_HE = 'שירותי סיעוד מוסדיים — שוק, רגולציה ואסטרטגיית גידור 1975–2075'
HISTORICAL_START = 1975
HISTORICAL_END = 2025
FORECAST_MAX = 2075
DEFAULT_FORECAST_END = 2075
DEFAULT_ADL_THRESHOLD = 3

BASIS_PUBLISHED = 'published'
BASIS_DERIVED = 'derived'
BASIS_ESTIMATE = 'estimate'
BASIS_PROJECTION = 'projection'
BASIS_MODEL = 'model'

# ---------------------------------------------------------------------------
# Source register
# ---------------------------------------------------------------------------

RESEARCH_SOURCES: List[Dict[str, Any]] = [
    {
        'id': 'oecd_haag_2025',
        'source': 'OECD Health at a Glance 2025 — long-term care chapter',
        'published_year': 2025,
        'period_covered': '2005–2023',
        'headline_metric': 'LTC spending 1.8% of GDP across the OECD (2023); four of five LTC dollars are public; 5 LTC workers and 41 beds per 100 / 1,000 people aged 65+.',
        'relevance': 'Cross-country spend, workforce, bed and public-share anchors.',
        'url': 'https://www.oecd.org/en/publications/health-at-a-glance-2025_8f9e3f98-en.html',
    },
    {
        'id': 'cms_nhe_2024',
        'source': 'CMS National Health Expenditure Accounts — Tables 14 (home health) and 15 (nursing care facilities & CCRCs)',
        'published_year': 2025,
        'period_covered': '1960–2024',
        'headline_metric': 'Nursing care $219.9bn (+7.3%) and home health $169.4bn (+10.2%) in 2024; Medicaid pays 35.9% of nursing care, Medicare 21.5%, out of pocket 22.1%.',
        'relevance': 'US 50-year spending and payer-mix history.',
        'url': 'https://www.cms.gov/data-research/statistics-trends-and-reports/national-health-expenditure-data/historical',
    },
    {
        'id': 'kff_nursing_facilities_2025',
        'source': 'KFF — A Look at Nursing Facility Characteristics (July 2025)',
        'published_year': 2025,
        'period_covered': '2015–2025',
        'headline_metric': '14,742 certified facilities, 1.24 million residents, 79% occupancy; 73% for-profit, 20% non-profit, 7% government; Medicaid primary payer for 63% of residents.',
        'relevance': 'US ownership, occupancy, payer and resident-count anchors.',
        'url': 'https://www.kff.org/medicaid/a-look-at-nursing-facility-characteristics/',
    },
    {
        'id': 'carescout_cost_of_care_2025',
        'source': 'CareScout (Genworth) Cost of Care Survey 2025',
        'published_year': 2026,
        'period_covered': '2024–2025',
        'headline_metric': 'US medians: home care $80,080/yr (44 h/wk), assisted living $74,400/yr, nursing home semi-private $114,975/yr, private room $129,575/yr.',
        'relevance': 'Unit cost of care by setting, 2024–2025.',
        'url': 'https://www.carescout.com/cost-of-care',
    },
    {
        'id': 'genworth_cost_of_care_series',
        'source': 'Genworth Cost of Care Survey series 2004–2020',
        'published_year': 2021,
        'period_covered': '2004–2020',
        'headline_metric': 'Nursing-home private room rose from about $70,000 (2004) to $105,850 (2020); assisted living from about $30,000 to $51,600.',
        'relevance': 'Twenty-year cost-of-care history by setting.',
        'url': 'https://www.genworth.com/aging-and-you/finances/cost-of-care',
    },
    {
        'id': 'medpac_march_2025',
        'source': 'MedPAC Report to the Congress: Medicare Payment Policy (March 2025)',
        'published_year': 2025,
        'period_covered': '2019–2023',
        'headline_metric': 'Freestanding SNF Medicare margin 22.0% against an all-payer total margin near 0.4% (2023); home health agency Medicare margin 20.2%.',
        'relevance': 'Segment margin benchmarks and payer cross-subsidy.',
        'url': 'https://www.medpac.gov/document/march-2025-report-to-the-congress-medicare-payment-policy/',
    },
    {
        'id': 'cms_staffing_rule_2024_2025',
        'source': 'CMS Minimum Staffing Standards for LTC Facilities — final rule (May 2024), vacatur (2025), Public Law 119-21 §71111 and the December 2025 interim final rule',
        'published_year': 2025,
        'period_covered': '2024–2034',
        'headline_metric': '3.48 total nurse HPRD (0.55 RN, 2.45 NA) plus 24/7 RN was vacated in April and June 2025; enforcement barred until 30 September 2034; repeal effective 2 February 2026.',
        'relevance': 'US staffing standard trajectory and regulatory risk.',
        'url': 'https://www.federalregister.gov/documents/2024/05/10/2024-08273/medicare-and-medicaid-programs-minimum-staffing-standards-for-long-term-care-facilities-and-medicaid',
    },
    {
        'id': 'ec_ageing_report_2024',
        'source': 'European Commission — 2024 Ageing Report (EU-27, 2022–2070)',
        'published_year': 2024,
        'period_covered': '2022–2070',
        'headline_metric': 'Public LTC 1.7% of GDP in 2022; total ageing cost rises from 24.4% to 25.6% of GDP by 2070 in the reference scenario and by a further 2.7 points in the risk scenario.',
        'relevance': 'EU fiscal outlook and the cost-convergence risk case.',
        'url': 'https://economy-finance.ec.europa.eu/publications/2024-ageing-report-economic-and-budgetary-projections-eu-member-states-2022-2070_en',
    },
    {
        'id': 'un_wpp_2024',
        'source': 'United Nations World Population Prospects 2024 (medium variant)',
        'published_year': 2024,
        'period_covered': '1950–2100',
        'headline_metric': 'People aged 80+ reach 265 million by the mid-2030s and outnumber infants; the 65+ population reaches 2.2 billion by the late 2070s.',
        'relevance': '80+ population shares that drive the 50-year demand index.',
        'url': 'https://population.un.org/wpp/',
    },
    {
        'id': 'taub_ltc_2024',
        'source': 'Taub Center — Long-Term Care in Israel: expenditure, insurance and settings (2024)',
        'published_year': 2024,
        'period_covered': '2012–2022',
        'headline_metric': 'National LTC spend NIS 23.6bn (2022): community 18.7, nursing hospitalisation 3.8; 71% public; ~30,000 people in out-of-home frameworks; private LTC insurance covers 60% of the population.',
        'relevance': 'Israel market size, settings and private insurance penetration.',
        'url': 'https://www.taubcenter.org.il/en/',
    },
    {
        'id': 'israel_comptroller_2026',
        'source': 'State Comptroller of Israel — audit of the National Insurance long-term care benefit (2026)',
        'published_year': 2026,
        'period_covered': '2018–2025',
        'headline_metric': 'NII LTC spend NIS 7bn (2018) → 21.1bn (2025); recipients ~180,000 → 392,000; 30% of retirement-age Israelis receive the benefit; NIS 6.7bn paid as cash.',
        'relevance': 'Post-2018 reform demand and cash-benefit shift in Israel.',
        'url': 'https://www.mevaker.gov.il/',
    },
    {
        'id': 'ensign_fy2025',
        'source': 'The Ensign Group — fourth-quarter and full-year 2025 results',
        'published_year': 2026,
        'period_covered': '2024–2025',
        'headline_metric': 'Revenue $5.06bn (+18.7%), adjusted EBITDA $602m (11.9%), EBITDAR $842m, 373 operations, occupancy 82.2%; 2026 guidance $5.77–5.84bn.',
        'relevance': 'US skilled-nursing operator benchmark.',
        'url': 'https://investor.ensigngroup.net/',
    },
    {
        'id': 'clariane_fy2025',
        'source': 'Clariane (ex-Korian) — full-year 2025 results',
        'published_year': 2026,
        'period_covered': '2024–2025',
        'headline_metric': 'Revenue €5.31bn (+4.5% organic), EBITDAR €1,146.5m (21.6%), pre-IFRS 16 EBITDA €594m, LTC 76% of revenue, occupancy 91.0%.',
        'relevance': 'European nursing-home operator benchmark.',
        'url': 'https://www.clariane.com/en/investors',
    },
    {
        'id': 'emeis_fy2025',
        'source': 'emeis (ex-Orpea) — full-year 2025 results',
        'published_year': 2026,
        'period_covered': '2023–2025',
        'headline_metric': 'Revenue ≈€5.9bn (+6.1% organic), EBITDAR margin 14.8% (13.1% in 2024), net debt €3.78bn, leverage 9.9× (19.5× in 2024), nursing-home occupancy 87.2%.',
        'relevance': 'Post-scandal recovery path and leverage risk.',
        'url': 'https://www.emeis-group.com/en/investors',
    },
    {
        'id': 'brookdale_fy2025',
        'source': 'Brookdale Senior Living — full-year 2025 results',
        'published_year': 2026,
        'period_covered': '2024–2025',
        'headline_metric': 'Weighted-average occupancy 82.5% and RevPAR +5.7% in 2025 for the largest US senior-living operator.',
        'relevance': 'US private-pay senior living benchmark.',
        'url': 'https://brookdaleinvestors.com/',
    },
    {
        'id': 'gao_pe_nursing_homes_2023',
        'source': 'GAO-23-106127 — Private equity and other ownership of nursing homes',
        'published_year': 2023,
        'period_covered': '2016–2022',
        'headline_metric': 'About 5% of US nursing homes were private-equity owned in 2022; ownership transparency and related-party leases flagged.',
        'relevance': 'Private-equity footprint and governance risk.',
        'url': 'https://www.gao.gov/products/gao-23-106127',
    },
    {
        'id': 'bls_projections_2023_2033',
        'source': 'US Bureau of Labor Statistics — Employment Projections 2023–2033 (home health and personal care aides)',
        'published_year': 2024,
        'period_covered': '2023–2033',
        'headline_metric': 'About 3.9 million home health and personal care aides in 2023, projected to grow 21% to 2033 with roughly 820,000 openings a year.',
        'relevance': 'Workforce demand and wage-pressure outlook.',
        'url': 'https://www.bls.gov/ooh/healthcare/home-health-aides-and-personal-care-aides.htm',
    },
    {
        'id': 'aus_royal_commission_2021',
        'source': 'Royal Commission into Aged Care Quality and Safety — final report (March 2021) and the Aged Care Act 2024',
        'published_year': 2021,
        'period_covered': '2018–2025',
        'headline_metric': '148 recommendations; mandatory 24/7 RN cover and care-minute targets (200+ minutes per resident day) introduced from 2022–2023; new Act in force November 2025.',
        'relevance': 'How a quality inquiry becomes a binding staffing standard.',
        'url': 'https://www.royalcommission.gov.au/aged-care',
    },
    {
        'id': 'japan_mhlw_kaigo',
        'source': 'Japan Ministry of Health, Labour and Welfare — Long-Term Care Insurance (Kaigo Hoken) statistics',
        'published_year': 2025,
        'period_covered': '2000–2025',
        'headline_metric': 'Universal mandatory LTC insurance since 2000; certified recipients grew from ~2.2 million (2000) to ~7 million; benefits ≈¥12–13 trillion a year.',
        'relevance': 'Oldest super-aged market and its community-first design.',
        'url': 'https://www.mhlw.go.jp/english/policy/care-welfare/care-welfare-elderly/',
    },
    {
        'id': 'germany_bmg_pflege',
        'source': 'German Federal Ministry of Health — social long-term care insurance (Pflegeversicherung) statistics',
        'published_year': 2025,
        'period_covered': '1995–2025',
        'headline_metric': 'Mandatory since 1995; about 5.7 million beneficiaries, four in five cared for at home; nursing-home residents pay rising co-payments despite 2022–2024 relief grants.',
        'relevance': 'Partial-cover social insurance and cash-for-care design.',
        'url': 'https://www.bundesgesundheitsministerium.de/en/topics/long-term-care',
    },
    {
        'id': 'uk_cma_care_homes_2017',
        'source': 'UK Competition and Markets Authority — Care Homes Market Study (2017) and subsequent Care Quality Commission reports',
        'published_year': 2017,
        'period_covered': '2010–2024',
        'headline_metric': 'Self-funders pay about 41% more than local authorities for the same bed; council fees sat below the full cost of care, undermining investment.',
        'relevance': 'Two-tier pricing and the Four Seasons / Southern Cross failures.',
        'url': 'https://www.gov.uk/cma-cases/care-homes-market-study',
    },
    {
        'id': 'nl_wlz_statistics',
        'source': 'Statistics Netherlands (CBS) and the Dutch Healthcare Authority (NZa) — Wlz long-term care statistics',
        'published_year': 2025,
        'period_covered': '2015–2024',
        'headline_metric': 'Highest LTC spend in the OECD (4.1% of GDP); 2015 reform moved lighter care to municipalities and insurers and cut institutional beds.',
        'relevance': 'Upper bound for public LTC spend and de-institutionalisation.',
        'url': 'https://www.cbs.nl/en-gb',
    },
    {
        'id': 'nic_map_2025',
        'source': 'NIC MAP Vision — US senior housing occupancy and supply tracker',
        'published_year': 2025,
        'period_covered': '2006–2025',
        'headline_metric': 'Primary-market senior housing occupancy recovered from a 78% pandemic trough (2021) to about 88–89% by late 2025 while new construction starts fell to decade lows.',
        'relevance': 'Private-pay accommodation cycle and real-estate supply.',
        'url': 'https://www.nic.org/',
    },
    {
        'id': 'phins_ltc_life_study',
        'source': 'PHINS — LTC 3+ADL and Life Risk Premiums study (Research & Audit)',
        'published_year': 2026,
        'period_covered': 'platform',
        'headline_metric': 'Same 3+ADL incidence and remaining-life-expectancy curves used for the hedge model in this study.',
        'relevance': 'Keeps the hedge priced on the PHINS contract trigger.',
        'url': '/actuary-dashboard.html#section-ltc-life-research',
    },
]

_SOURCE_IDS = {item['id'] for item in RESEARCH_SOURCES}


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

# residential_share_reduction_pct is relative: a region with 25% of recipients
# in residential care and a 20% reduction lands at 20% by 2050 and holds.
_SCENARIOS: Dict[str, Dict[str, Any]] = {
    'baseline': {
        'label': 'Baseline — demographic drift, gradual home shift',
        'residential_share_reduction_pct': 20.0,
        'recipient_factor_2050': 1.00,
        'recipient_factor_2075': 1.00,
        'public_share_delta_2075': -3.0,
        'relative_cost_delta_pct': 0.0,
        'note': 'UN medium-variant ageing, healthy-ageing offset, residential share of recipients falls one-fifth by 2050.',
    },
    'home_shift': {
        'label': 'Home-first — policy and technology move care home',
        'residential_share_reduction_pct': 45.0,
        'recipient_factor_2050': 1.02,
        'recipient_factor_2075': 1.03,
        'public_share_delta_2075': 0.0,
        'relative_cost_delta_pct': -0.3,
        'note': 'Cash-for-care, remote monitoring and family-carer support; residential share of recipients falls 45% by 2050.',
    },
    'fiscal_squeeze': {
        'label': 'Fiscal squeeze — public payers cap rates, private pay rises',
        'residential_share_reduction_pct': 30.0,
        'recipient_factor_2050': 0.98,
        'recipient_factor_2075': 0.97,
        'public_share_delta_2075': -12.0,
        'relative_cost_delta_pct': -0.4,
        'note': 'Public fee schedules lag costs; means tests tighten; self-funders and private insurance carry more of the bill.',
    },
    'dementia_breakthrough': {
        'label': 'Dementia breakthrough — disease-modifying therapy at scale',
        'residential_share_reduction_pct': 30.0,
        'recipient_factor_2050': 0.85,
        'recipient_factor_2075': 0.75,
        'public_share_delta_2075': -2.0,
        'relative_cost_delta_pct': 0.0,
        'note': 'Severe-disability prevalence falls 15% by 2050 and 25% by 2075; residential demand falls most.',
    },
}

_HEDGE_PRESETS: Dict[str, Dict[str, float]] = {
    'balanced': {'operator_equity': 35.0, 'care_real_estate': 35.0, 'home_care_platform': 20.0, 'liquidity_reserve': 10.0},
    'real_estate': {'operator_equity': 15.0, 'care_real_estate': 60.0, 'home_care_platform': 10.0, 'liquidity_reserve': 15.0},
    'home_care': {'operator_equity': 20.0, 'care_real_estate': 20.0, 'home_care_platform': 50.0, 'liquidity_reserve': 10.0},
    'operator': {'operator_equity': 55.0, 'care_real_estate': 20.0, 'home_care_platform': 15.0, 'liquidity_reserve': 10.0},
}

# Yield = expected cash yield on invested capital; claim beta = % change in
# hedge income for a 1% change in 3+ADL incidence (occupancy and volume
# elasticity after operating leverage). Research assumptions, flagged as model.
_HEDGE_ASSETS: Dict[str, Dict[str, Any]] = {
    'operator_equity': {
        'label': 'Care operator equity (SNF / nursing-home operators)',
        'yield_pct': 7.0, 'claim_beta': 0.50, 'liquidity': 'listed / private', 'volatility': 'high',
        'rationale': 'Occupancy and skilled mix rise with disability incidence; margins lever the revenue change.',
    },
    'care_real_estate': {
        'label': 'Care real estate (SNF / senior-housing leases and REITs)',
        'yield_pct': 8.5, 'claim_beta': 0.30, 'liquidity': 'listed REIT / direct', 'volatility': 'medium',
        'rationale': 'Triple-net rent and SHOP NOI track occupancy with a lag; coverage improves when beds fill.',
    },
    'home_care_platform': {
        'label': 'Home-care and home-health platforms',
        'yield_pct': 9.5, 'claim_beta': 0.80, 'liquidity': 'private / listed', 'volatility': 'medium-high',
        'rationale': 'Hours billed scale almost one-for-one with new ADL-dependent clients; low capital intensity.',
    },
    'liquidity_reserve': {
        'label': 'Liquidity reserve (government and investment-grade bonds)',
        'yield_pct': 4.5, 'claim_beta': 0.0, 'liquidity': 'daily', 'volatility': 'low',
        'rationale': 'Pays early claims while operating assets re-price; no claim correlation.',
    },
}


@dataclass(frozen=True)
class ResidentialResearchParams:
    region: str = 'us'
    scenario: str = 'baseline'
    forecast_end: int = DEFAULT_FORECAST_END
    care_cost_inflation_pct: float = 3.5
    gdp_growth_pct: float = 3.5
    healthy_ageing_pct: float = 0.5
    home_care_share_target_pct: float = -1.0  # <0 → scenario default
    lives: int = 10_000
    age_min: int = 30
    age_max: int = 85
    ltc_annual_cover: float = 60_000.0
    adl_threshold: int = DEFAULT_ADL_THRESHOLD
    hedge_capital: float = 25_000_000.0
    hedge_allocation: str = 'balanced'
    incidence_stress_pct: float = 30.0
    discount_rate_pct: float = 6.0
    som_share_pct: float = 0.5

    def normalised(self) -> 'ResidentialResearchParams':
        region = self.region if self.region in _REGIONS else 'us'
        scenario = self.scenario if self.scenario in _SCENARIOS else 'baseline'
        age_min = _clamp_int(self.age_min, 18, 90)
        age_max = _clamp_int(self.age_max, age_min + 1, 100)
        allocation = self.hedge_allocation if self.hedge_allocation in _HEDGE_PRESETS else 'balanced'
        target = float(self.home_care_share_target_pct)
        if target >= 0:
            target = _clamp(target, 30.0, 95.0)
        else:
            target = -1.0
        return ResidentialResearchParams(
            region=region,
            scenario=scenario,
            forecast_end=_clamp_int(self.forecast_end, 2030, FORECAST_MAX),
            care_cost_inflation_pct=_clamp(float(self.care_cost_inflation_pct), 0.0, 10.0),
            gdp_growth_pct=_clamp(float(self.gdp_growth_pct), 0.0, 8.0),
            healthy_ageing_pct=_clamp(float(self.healthy_ageing_pct), -1.0, 2.0),
            home_care_share_target_pct=target,
            lives=_clamp_int(self.lives, 1, 1_000_000),
            age_min=age_min,
            age_max=age_max,
            ltc_annual_cover=max(1_200.0, float(self.ltc_annual_cover)),
            adl_threshold=_clamp_int(self.adl_threshold, 2, 6),
            hedge_capital=max(0.0, float(self.hedge_capital)),
            hedge_allocation=allocation,
            incidence_stress_pct=_clamp(float(self.incidence_stress_pct), 0.0, 100.0),
            discount_rate_pct=_clamp(float(self.discount_rate_pct), 0.0, 15.0),
            som_share_pct=_clamp(float(self.som_share_pct), 0.01, 25.0),
        )


def parse_residential_params(raw: Optional[Dict[str, Any]] = None) -> ResidentialResearchParams:
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

    params = ResidentialResearchParams(
        region=str(raw.get('region') or 'us').strip().lower(),
        scenario=str(raw.get('scenario') or 'baseline').strip().lower(),
        forecast_end=_i('forecast_end', DEFAULT_FORECAST_END),
        care_cost_inflation_pct=_f('care_cost_inflation_pct', 3.5),
        gdp_growth_pct=_f('gdp_growth_pct', 3.5),
        healthy_ageing_pct=_f('healthy_ageing_pct', 0.5),
        home_care_share_target_pct=_f('home_care_share_target_pct', -1.0),
        lives=_i('lives', 10_000),
        age_min=_i('age_min', 30),
        age_max=_i('age_max', 85),
        ltc_annual_cover=_f('ltc_annual_cover', 60_000.0),
        adl_threshold=_i('adl_threshold', DEFAULT_ADL_THRESHOLD),
        hedge_capital=_f('hedge_capital', 25_000_000.0),
        hedge_allocation=str(raw.get('hedge_allocation') or 'balanced').strip().lower(),
        incidence_stress_pct=_f('incidence_stress_pct', 30.0),
        discount_rate_pct=_f('discount_rate_pct', 6.0),
        som_share_pct=_f('som_share_pct', 0.5),
    )
    return params.normalised()


# ---------------------------------------------------------------------------
# Region anchors
# ---------------------------------------------------------------------------
# ltc_spend_gdp_pct: total LTC spend as % GDP (latest year). US and Israel are
# derived from the national accounts (NHE tables 14+15 ÷ GDP; Taub NIS 23.6bn
# ÷ GDP) because the OECD health-LTC boundary excludes much social care.
# pop80_share: UN WPP 2024 medium variant, rounded (projection).
# private_provision_share_pct: share of LTC spend flowing to privately operated
# providers (for-profit or non-profit) regardless of who pays — the investible
# boundary for SAM.

_REGIONS: Dict[str, Dict[str, Any]] = {
    'us': {
        'label': 'United States', 'currency': 'USD', 'gdp_2025_usd_bn': 29_200.0,
        'ltc_spend_gdp_pct': 1.33, 'ltc_spend_basis': BASIS_DERIVED, 'ltc_spend_year': 2024,
        'public_share_pct': 61.0, 'public_share_basis': BASIS_DERIVED,
        'residential_recipient_share_pct': 25.0, 'residential_basis': BASIS_ESTIMATE,
        'beds_per_1000_65plus': 32.0, 'workers_per_100_65plus': 4.0,
        'for_profit_share_pct': 73.0, 'for_profit_basis': BASIS_PUBLISHED,
        'private_provision_share_pct': 80.0,
        'residential_cost_factor': 1.00, 'residential_cost_basis': BASIS_PUBLISHED,
        'pop80_share': {2025: 4.1, 2050: 8.3, 2075: 9.5},
        'source_ids': ['cms_nhe_2024', 'kff_nursing_facilities_2025', 'carescout_cost_of_care_2025', 'oecd_haag_2025', 'un_wpp_2024'],
        'note': 'Spend = CMS NHE nursing care + home health ($389.3bn, 2024) ÷ GDP. OECD health-LTC boundary alone is nearer 1.0%.',
    },
    'oecd': {
        'label': 'OECD average', 'currency': 'USD', 'gdp_2025_usd_bn': 70_000.0,
        'ltc_spend_gdp_pct': 1.8, 'ltc_spend_basis': BASIS_PUBLISHED, 'ltc_spend_year': 2023,
        'public_share_pct': 80.0, 'public_share_basis': BASIS_PUBLISHED,
        'residential_recipient_share_pct': 30.0, 'residential_basis': BASIS_ESTIMATE,
        'beds_per_1000_65plus': 41.0, 'workers_per_100_65plus': 5.0,
        'for_profit_share_pct': 40.0, 'for_profit_basis': BASIS_ESTIMATE,
        'private_provision_share_pct': 55.0,
        'residential_cost_factor': 0.75, 'residential_cost_basis': BASIS_ESTIMATE,
        'pop80_share': {2025: 5.2, 2050: 9.8, 2075: 11.5},
        'source_ids': ['oecd_haag_2025', 'un_wpp_2024'],
        'note': 'Unweighted OECD average; beds 41 per 1,000 aged 65+ (40 in facilities + 3 in hospitals).',
    },
    'eu': {
        'label': 'European Union (EU-27)', 'currency': 'EUR', 'gdp_2025_usd_bn': 19_500.0,
        'ltc_spend_gdp_pct': 1.7, 'ltc_spend_basis': BASIS_PUBLISHED, 'ltc_spend_year': 2022,
        'public_share_pct': 80.0, 'public_share_basis': BASIS_ESTIMATE,
        'residential_recipient_share_pct': 32.0, 'residential_basis': BASIS_ESTIMATE,
        'beds_per_1000_65plus': 45.0, 'workers_per_100_65plus': 5.0,
        'for_profit_share_pct': 35.0, 'for_profit_basis': BASIS_ESTIMATE,
        'private_provision_share_pct': 50.0,
        'residential_cost_factor': 0.70, 'residential_cost_basis': BASIS_ESTIMATE,
        'pop80_share': {2025: 6.3, 2050: 11.5, 2075: 13.5},
        'source_ids': ['ec_ageing_report_2024', 'oecd_haag_2025', 'un_wpp_2024'],
        'note': 'Public LTC only in the Ageing Report; private top-ups add roughly 0.3–0.4 points.',
    },
    'il': {
        'label': 'Israel', 'currency': 'ILS', 'gdp_2025_usd_bn': 540.0,
        'ltc_spend_gdp_pct': 1.33, 'ltc_spend_basis': BASIS_DERIVED, 'ltc_spend_year': 2022,
        'public_share_pct': 71.0, 'public_share_basis': BASIS_PUBLISHED,
        'residential_recipient_share_pct': 8.0, 'residential_basis': BASIS_DERIVED,
        'beds_per_1000_65plus': 22.0, 'workers_per_100_65plus': 6.0,
        'for_profit_share_pct': 55.0, 'for_profit_basis': BASIS_ESTIMATE,
        'private_provision_share_pct': 65.0,
        'residential_cost_factor': 0.45, 'residential_cost_basis': BASIS_DERIVED,
        'pop80_share': {2025: 3.4, 2050: 5.5, 2075: 7.5},
        'source_ids': ['taub_ltc_2024', 'israel_comptroller_2026', 'oecd_haag_2025', 'un_wpp_2024'],
        'note': 'NIS 23.6bn ÷ GDP ≈ NIS 1.78tn (2022). ~30,000 in out-of-home frameworks vs ~390,000 NII home-benefit recipients → residential share ≈ 8%.',
    },
    'jp': {
        'label': 'Japan', 'currency': 'JPY', 'gdp_2025_usd_bn': 4_200.0,
        'ltc_spend_gdp_pct': 2.1, 'ltc_spend_basis': BASIS_ESTIMATE, 'ltc_spend_year': 2023,
        'public_share_pct': 90.0, 'public_share_basis': BASIS_ESTIMATE,
        'residential_recipient_share_pct': 28.0, 'residential_basis': BASIS_ESTIMATE,
        'beds_per_1000_65plus': 38.0, 'workers_per_100_65plus': 6.5,
        'for_profit_share_pct': 45.0, 'for_profit_basis': BASIS_ESTIMATE,
        'private_provision_share_pct': 60.0,
        'residential_cost_factor': 0.45, 'residential_cost_basis': BASIS_ESTIMATE,
        'pop80_share': {2025: 10.8, 2050: 16.0, 2075: 17.0},
        'source_ids': ['japan_mhlw_kaigo', 'oecd_haag_2025', 'un_wpp_2024'],
        'note': 'Kaigo Hoken: 10–30% co-payment; facility board and lodging paid privately.',
    },
    'de': {
        'label': 'Germany', 'currency': 'EUR', 'gdp_2025_usd_bn': 4_700.0,
        'ltc_spend_gdp_pct': 2.2, 'ltc_spend_basis': BASIS_ESTIMATE, 'ltc_spend_year': 2023,
        'public_share_pct': 70.0, 'public_share_basis': BASIS_ESTIMATE,
        'residential_recipient_share_pct': 20.0, 'residential_basis': BASIS_PUBLISHED,
        'beds_per_1000_65plus': 54.0, 'workers_per_100_65plus': 5.5,
        'for_profit_share_pct': 43.0, 'for_profit_basis': BASIS_ESTIMATE,
        'private_provision_share_pct': 65.0,
        'residential_cost_factor': 0.60, 'residential_cost_basis': BASIS_ESTIMATE,
        'pop80_share': {2025: 7.5, 2050: 12.5, 2075: 14.0},
        'source_ids': ['germany_bmg_pflege', 'oecd_haag_2025', 'un_wpp_2024'],
        'note': 'Partial-cover social insurance; four in five beneficiaries at home, many on cash benefit (Pflegegeld).',
    },
    'uk': {
        'label': 'United Kingdom', 'currency': 'GBP', 'gdp_2025_usd_bn': 3_600.0,
        'ltc_spend_gdp_pct': 1.8, 'ltc_spend_basis': BASIS_ESTIMATE, 'ltc_spend_year': 2023,
        'public_share_pct': 60.0, 'public_share_basis': BASIS_ESTIMATE,
        'residential_recipient_share_pct': 35.0, 'residential_basis': BASIS_ESTIMATE,
        'beds_per_1000_65plus': 40.0, 'workers_per_100_65plus': 4.5,
        'for_profit_share_pct': 84.0, 'for_profit_basis': BASIS_ESTIMATE,
        'private_provision_share_pct': 85.0,
        'residential_cost_factor': 0.70, 'residential_cost_basis': BASIS_ESTIMATE,
        'pop80_share': {2025: 5.3, 2050: 9.5, 2075: 11.0},
        'source_ids': ['uk_cma_care_homes_2017', 'oecd_haag_2025', 'un_wpp_2024'],
        'note': 'Means-tested; self-funders cross-subsidise council-funded residents.',
    },
    'nl': {
        'label': 'Netherlands', 'currency': 'EUR', 'gdp_2025_usd_bn': 1_200.0,
        'ltc_spend_gdp_pct': 4.1, 'ltc_spend_basis': BASIS_PUBLISHED, 'ltc_spend_year': 2023,
        'public_share_pct': 93.0, 'public_share_basis': BASIS_ESTIMATE,
        'residential_recipient_share_pct': 35.0, 'residential_basis': BASIS_ESTIMATE,
        'beds_per_1000_65plus': 55.0, 'workers_per_100_65plus': 10.0,
        'for_profit_share_pct': 10.0, 'for_profit_basis': BASIS_ESTIMATE,
        'private_provision_share_pct': 20.0,
        'residential_cost_factor': 0.90, 'residential_cost_basis': BASIS_ESTIMATE,
        'pop80_share': {2025: 5.0, 2050: 10.5, 2075: 12.0},
        'source_ids': ['nl_wlz_statistics', 'oecd_haag_2025', 'un_wpp_2024'],
        'note': 'Wlz universal cover delivered mostly by non-profit foundations; small for-profit niche.',
    },
}

_HOME_COST_FACTOR = 0.55       # blended home-care package ÷ residential cost per recipient-year (model)
_ASSISTED_COST_FACTOR = 0.65   # assisted living ÷ nursing semi-private (CareScout 2025: 74,400 / 114,975)
_US_RESIDENTIAL_COST_2025 = 114_975.0  # CareScout 2025 nursing-home semi-private, annual


# ---------------------------------------------------------------------------
# Published history blocks
# ---------------------------------------------------------------------------

# CMS NHE Table 15 (nursing care facilities & CCRCs) and Table 14 (home health), $bn.
_US_NHE_NURSING_BN = {
    1970: 4.0, 1980: 15.3, 1990: 44.7, 2000: 85.0, 2005: 111.4, 2010: 140.5,
    2015: 156.8, 2019: 172.6, 2020: 192.3, 2021: 179.0, 2022: 188.6, 2023: 205.0, 2024: 219.9,
}
_US_NHE_HOME_HEALTH_BN = {
    1970: 0.2, 1980: 2.4, 1990: 12.5, 2000: 32.3, 2005: 49.3, 2010: 70.5,
    2015: 89.7, 2019: 113.9, 2020: 126.2, 2021: 127.4, 2022: 138.2, 2023: 153.6, 2024: 169.4,
}

# Payer shares (%). public = Medicare + Medicaid + other health insurance programmes.
_PAYER_MIX_ROWS: List[Dict[str, Any]] = [
    {'region': 'us', 'segment': 'nursing_care', 'year': 1980, 'public_pct': 48.2, 'medicare_pct': 2.0, 'medicaid_pct': 46.2,
     'private_insurance_pct': None, 'out_of_pocket_pct': 40.5, 'other_pct': 11.3,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['cms_nhe_2024'], 'note': 'other = residual (incl. private insurance and other third parties)'},
    {'region': 'us', 'segment': 'nursing_care', 'year': 2024, 'public_pct': 60.6, 'medicare_pct': 21.5, 'medicaid_pct': 35.9,
     'private_insurance_pct': 8.8, 'out_of_pocket_pct': 22.1, 'other_pct': 8.5,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['cms_nhe_2024'], 'note': 'other health insurance programmes 3.2 inside public'},
    {'region': 'us', 'segment': 'home_health', 'year': 2024, 'public_pct': 56.4, 'medicare_pct': 32.9, 'medicaid_pct': 22.5,
     'private_insurance_pct': 22.0, 'out_of_pocket_pct': 17.9, 'other_pct': 3.7,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['cms_nhe_2024'], 'note': 'other health insurance programmes 1.0 inside public'},
    {'region': 'us', 'segment': 'nursing_facility_residents', 'year': 2025, 'public_pct': 77.0, 'medicare_pct': 14.0, 'medicaid_pct': 63.0,
     'private_insurance_pct': None, 'out_of_pocket_pct': None, 'other_pct': 23.0,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['kff_nursing_facilities_2025'], 'note': 'primary payer by resident count; other = private pay and other'},
    {'region': 'oecd', 'segment': 'all_ltc', 'year': 2023, 'public_pct': 80.0, 'medicare_pct': None, 'medicaid_pct': None,
     'private_insurance_pct': None, 'out_of_pocket_pct': 20.0, 'other_pct': 0.0,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['oecd_haag_2025'], 'note': 'private = household out-of-pocket plus voluntary insurance'},
    {'region': 'il', 'segment': 'all_ltc', 'year': 2022, 'public_pct': 71.0, 'medicare_pct': None, 'medicaid_pct': None,
     'private_insurance_pct': None, 'out_of_pocket_pct': 29.0, 'other_pct': 0.0,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['taub_ltc_2024'], 'note': 'NIS 16.7bn public of 23.6bn; NIS 4.4bn of the private 7.0bn is home care'},
    {'region': 'eu', 'segment': 'all_ltc', 'year': 2022, 'public_pct': 80.0, 'medicare_pct': None, 'medicaid_pct': None,
     'private_insurance_pct': None, 'out_of_pocket_pct': 20.0, 'other_pct': 0.0,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['ec_ageing_report_2024', 'oecd_haag_2025'], 'note': 'public 1.7% GDP; private top-ups estimated'},
]

# Genworth / CareScout annual medians (USD). Settings × year.
_COST_OF_CARE_ROWS: List[Tuple[int, str, float, str, List[str]]] = [
    (2004, 'home_health_aide', 37_440.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2004, 'assisted_living', 30_288.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2004, 'nursing_semi_private', 61_685.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2004, 'nursing_private', 70_080.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2010, 'home_health_aide', 43_472.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2010, 'adult_day', 17_420.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2010, 'assisted_living', 39_516.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2010, 'nursing_semi_private', 74_825.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2010, 'nursing_private', 83_585.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2015, 'home_health_aide', 45_760.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2015, 'adult_day', 17_904.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2015, 'assisted_living', 43_200.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2015, 'nursing_semi_private', 80_300.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2015, 'nursing_private', 91_250.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2020, 'home_health_aide', 54_912.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2020, 'adult_day', 19_240.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2020, 'assisted_living', 51_600.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2020, 'nursing_semi_private', 93_075.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2020, 'nursing_private', 105_850.0, BASIS_PUBLISHED, ['genworth_cost_of_care_series']),
    (2024, 'home_health_aide', 77_792.0, BASIS_PUBLISHED, ['carescout_cost_of_care_2025']),
    (2024, 'assisted_living', 70_800.0, BASIS_PUBLISHED, ['carescout_cost_of_care_2025']),
    (2024, 'nursing_semi_private', 111_325.0, BASIS_PUBLISHED, ['carescout_cost_of_care_2025']),
    (2024, 'nursing_private', 127_750.0, BASIS_PUBLISHED, ['carescout_cost_of_care_2025']),
    (2025, 'home_health_aide', 80_080.0, BASIS_PUBLISHED, ['carescout_cost_of_care_2025']),
    (2025, 'adult_day', 24_700.0, BASIS_PUBLISHED, ['carescout_cost_of_care_2025']),
    (2025, 'assisted_living', 74_400.0, BASIS_PUBLISHED, ['carescout_cost_of_care_2025']),
    (2025, 'nursing_semi_private', 114_975.0, BASIS_PUBLISHED, ['carescout_cost_of_care_2025']),
    (2025, 'nursing_private', 129_575.0, BASIS_PUBLISHED, ['carescout_cost_of_care_2025']),
]

_SETTING_LABELS = {
    'home_health_aide': 'Home health aide (44 h/week)',
    'adult_day': 'Adult day health care',
    'assisted_living': 'Assisted living (private one-bedroom)',
    'nursing_semi_private': 'Nursing home — semi-private room',
    'nursing_private': 'Nursing home — private room',
}

# Fifty-year market eras (US-centred, with the OECD pattern noted).
_ERAS: Tuple[Tuple[int, int, str, str, str], ...] = (
    (1965, 1980, 'medicaid_build_out',
     'Medicare/Medicaid (1965) turn board-and-care homes into a licensed nursing-home industry; for-profit chains form; bed supply doubles.',
     'Public insurance creates the market.'),
    (1981, 1990, 'cost_control_and_obra',
     'Certificate-of-need caps beds; scandals lead to OBRA 1987 (Nursing Home Reform Act): resident rights, assessments, survey & certification.',
     'Quality regulation becomes federal.'),
    (1991, 2000, 'hcbs_rise_and_pps',
     'Medicaid HCBS waivers scale; Balanced Budget Act 1997 PPS for SNFs and home health; Japan (2000) and Germany (1995) launch social LTC insurance.',
     'Payers begin steering care away from beds.'),
    (2001, 2010, 'assisted_living_and_reit',
     'Private-pay assisted living grows fastest; REIT/opco-propco separation and private equity enter; Southern Cross (UK) collapses 2011.',
     'Real estate capital arrives; leverage risk appears.'),
    (2011, 2019, 'rebalancing_and_consolidation',
     'US HCBS passes institutional Medicaid LTSS spend; Netherlands Wlz reform (2015); Korea/Japan community-first; Israel 2018 reform expands home benefit.',
     'Home care is the growth segment.'),
    (2020, 2025, 'pandemic_reset',
     'COVID-19: >200,000 US nursing-home deaths; occupancy troughs (US 72%, senior housing 78%); Orpea scandal (2022) and Australian Royal Commission reset standards; staffing rules proposed then repealed.',
     'Quality, staffing and transparency re-regulated.'),
)

_FORECAST_ERAS: Tuple[Tuple[int, int, str, str], ...] = (
    (2026, 2035, 'home_first_scaling',
     'Technology-enabled home care scales; residential demand grows below the 80+ population; capital goes to higher-acuity beds.'),
    (2036, 2050, 'peak_boomer_demand',
     'US and EU 80+ populations peak in growth; bed shortages in high-acuity care; public payers rebalance toward cash and home.'),
    (2051, 2075, 'steady_state_longevity',
     'Demographic growth slows; the market turns on longevity, dementia therapy and workforce productivity.'),
)

# ---------------------------------------------------------------------------
# Market structure, operators, margins, workforce, regulation
# ---------------------------------------------------------------------------

_SETTING_COMPARISON_ROWS: List[Dict[str, Any]] = [
    {
        'setting': 'for_profit_nursing_home', 'label': 'Private for-profit nursing home',
        'us_share_of_facilities_pct': 73.0, 'typical_occupancy_pct': 79.0,
        'median_annual_cost_usd': 114_975.0, 'nurse_hprd_typical': 3.6, 'rn_hprd_typical': 0.55,
        'medicaid_share_pct': 65.0, 'deficiencies_per_survey': 9.0, 'ebitdar_margin_pct': 14.0,
        'labor_cost_share_pct': 65.0, 'capital_intensity': 'high', 'regulatory_intensity': 'high',
        'typical_acuity': 'post-acute + long-stay 3+ADL',
        'figure_basis': BASIS_ESTIMATE, 'source_ids': ['kff_nursing_facilities_2025', 'medpac_march_2025', 'carescout_cost_of_care_2025'],
        'note': 'Medicare post-acute margin (22%) subsidises Medicaid long-stay; staffing below non-profit peers.',
    },
    {
        'setting': 'non_profit_nursing_home', 'label': 'Private non-profit nursing home',
        'us_share_of_facilities_pct': 20.0, 'typical_occupancy_pct': 82.0,
        'median_annual_cost_usd': 118_000.0, 'nurse_hprd_typical': 4.1, 'rn_hprd_typical': 0.75,
        'medicaid_share_pct': 55.0, 'deficiencies_per_survey': 6.5, 'ebitdar_margin_pct': 9.0,
        'labor_cost_share_pct': 68.0, 'capital_intensity': 'high', 'regulatory_intensity': 'high',
        'typical_acuity': 'long-stay, faith/community based',
        'figure_basis': BASIS_ESTIMATE, 'source_ids': ['kff_nursing_facilities_2025', 'medpac_march_2025'],
        'note': 'Higher staffing and star ratings; thin margins; philanthropy and CCRC entry fees.',
    },
    {
        'setting': 'public_nursing_home', 'label': 'Public (government) nursing home',
        'us_share_of_facilities_pct': 7.0, 'typical_occupancy_pct': 84.0,
        'median_annual_cost_usd': 125_000.0, 'nurse_hprd_typical': 4.3, 'rn_hprd_typical': 0.80,
        'medicaid_share_pct': 70.0, 'deficiencies_per_survey': 7.0, 'ebitdar_margin_pct': 2.0,
        'labor_cost_share_pct': 72.0, 'capital_intensity': 'high', 'regulatory_intensity': 'high',
        'typical_acuity': 'highest-need, safety-net, veterans',
        'figure_basis': BASIS_ESTIMATE, 'source_ids': ['kff_nursing_facilities_2025', 'oecd_haag_2025'],
        'note': 'County, state and veterans homes; tax-subsidised; dominant model in Nordic and Dutch systems.',
    },
    {
        'setting': 'assisted_living', 'label': 'Assisted living / senior housing (private pay)',
        'us_share_of_facilities_pct': None, 'typical_occupancy_pct': 88.0,
        'median_annual_cost_usd': 74_400.0, 'nurse_hprd_typical': 1.2, 'rn_hprd_typical': 0.10,
        'medicaid_share_pct': 18.0, 'deficiencies_per_survey': None, 'ebitdar_margin_pct': 28.0,
        'labor_cost_share_pct': 55.0, 'capital_intensity': 'very high', 'regulatory_intensity': 'medium (state)',
        'typical_acuity': '1–2 ADL, memory care',
        'figure_basis': BASIS_ESTIMATE, 'source_ids': ['carescout_cost_of_care_2025', 'nic_map_2025', 'brookdale_fy2025'],
        'note': 'About 30,000 US communities and ~1 million beds; occupancy 88–89% late 2025; state licensure only.',
    },
    {
        'setting': 'home_care_agency', 'label': 'Home care / home health (private agency)',
        'us_share_of_facilities_pct': None, 'typical_occupancy_pct': None,
        'median_annual_cost_usd': 80_080.0, 'nurse_hprd_typical': None, 'rn_hprd_typical': None,
        'medicaid_share_pct': 22.5, 'deficiencies_per_survey': None, 'ebitdar_margin_pct': 11.0,
        'labor_cost_share_pct': 75.0, 'capital_intensity': 'low', 'regulatory_intensity': 'medium (Medicare CoPs)',
        'typical_acuity': '1–3 ADL, post-acute, dementia at home',
        'figure_basis': BASIS_ESTIMATE, 'source_ids': ['cms_nhe_2024', 'medpac_march_2025', 'carescout_cost_of_care_2025'],
        'note': 'Medicare home-health margin 20.2% (2023); non-medical home care margins 8–12%; cost for 44 h/week nears a semi-private bed.',
    },
    {
        'setting': 'public_home_care', 'label': 'Public / social-insurance home care (cash or in-kind)',
        'us_share_of_facilities_pct': None, 'typical_occupancy_pct': None,
        'median_annual_cost_usd': 35_000.0, 'nurse_hprd_typical': None, 'rn_hprd_typical': None,
        'medicaid_share_pct': 100.0, 'deficiencies_per_survey': None, 'ebitdar_margin_pct': 6.0,
        'labor_cost_share_pct': 80.0, 'capital_intensity': 'low', 'regulatory_intensity': 'medium',
        'typical_acuity': 'ADL-assessed benefit (NII, Pflegegeld, Kaigo levels 1–5)',
        'figure_basis': BASIS_ESTIMATE, 'source_ids': ['israel_comptroller_2026', 'germany_bmg_pflege', 'japan_mhlw_kaigo'],
        'note': 'Typical public package well below full-time private care; Israel pays ~NIS 5,000–7,000/month at the top level.',
    },
]

_OPERATOR_ROWS: List[Dict[str, Any]] = [
    {'player': 'The Ensign Group', 'country': 'US', 'segment': 'skilled nursing operator', 'ownership': 'listed (NASDAQ: ENSG)',
     'revenue_bn': 5.06, 'currency': 'USD', 'fiscal_year': 2025, 'margin_metric': 'adjusted EBITDA', 'margin_pct': 11.9,
     'beds_or_units': 373, 'unit_label': 'operations', 'countries': 1, 'occupancy_pct': 82.2,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['ensign_fy2025'], 'note': 'EBITDAR $842m (16.6%); 160 owned properties.'},
    {'player': 'Clariane (ex-Korian)', 'country': 'FR', 'segment': 'nursing homes, clinics, home care', 'ownership': 'listed (Euronext: CLARI)',
     'revenue_bn': 5.31, 'currency': 'EUR', 'fiscal_year': 2025, 'margin_metric': 'EBITDAR', 'margin_pct': 21.6,
     'beds_or_units': 1_200, 'unit_label': 'facilities', 'countries': 6, 'occupancy_pct': 91.0,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['clariane_fy2025'], 'note': 'LTC 76% of revenue; disposals and rights issue 2023–2025.'},
    {'player': 'emeis (ex-Orpea)', 'country': 'FR', 'segment': 'nursing homes, clinics', 'ownership': 'listed; Caisse des Dépôts-led consortium',
     'revenue_bn': 5.90, 'currency': 'EUR', 'fiscal_year': 2025, 'margin_metric': 'EBITDAR', 'margin_pct': 14.8,
     'beds_or_units': 1_000, 'unit_label': 'facilities', 'countries': 20, 'occupancy_pct': 87.6,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['emeis_fy2025'], 'note': 'Leverage 9.9× after €3.9bn restructuring; 83,500 staff.'},
    {'player': 'Brookdale Senior Living', 'country': 'US', 'segment': 'senior living (IL/AL/memory care)', 'ownership': 'listed (NYSE: BKD)',
     'revenue_bn': 3.1, 'currency': 'USD', 'fiscal_year': 2025, 'margin_metric': 'adjusted EBITDA', 'margin_pct': 13.0,
     'beds_or_units': 640, 'unit_label': 'communities', 'countries': 1, 'occupancy_pct': 82.5,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['brookdale_fy2025'], 'note': 'Largest US senior-living operator; occupancy still below 2019.'},
    {'player': 'Welltower', 'country': 'US', 'segment': 'healthcare REIT (senior housing, post-acute)', 'ownership': 'listed (NYSE: WELL)',
     'revenue_bn': 8.0, 'currency': 'USD', 'fiscal_year': 2024, 'margin_metric': 'SHOP NOI margin', 'margin_pct': 27.0,
     'beds_or_units': 2_000, 'unit_label': 'properties', 'countries': 3, 'occupancy_pct': 86.0,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['nic_map_2025'], 'note': 'Largest care landlord; SHOP same-store NOI growth >20% in 2024–2025.'},
    {'player': 'Ventas', 'country': 'US', 'segment': 'healthcare REIT', 'ownership': 'listed (NYSE: VTR)',
     'revenue_bn': 4.9, 'currency': 'USD', 'fiscal_year': 2024, 'margin_metric': 'SHOP NOI margin', 'margin_pct': 26.0,
     'beds_or_units': 1_350, 'unit_label': 'properties', 'countries': 3, 'occupancy_pct': 85.0,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['nic_map_2025'], 'note': 'Shifting from triple-net to operating senior housing.'},
    {'player': 'Omega Healthcare Investors', 'country': 'US', 'segment': 'SNF triple-net REIT', 'ownership': 'listed (NYSE: OHI)',
     'revenue_bn': 1.05, 'currency': 'USD', 'fiscal_year': 2024, 'margin_metric': 'EBITDAR rent coverage (×)', 'margin_pct': 1.5,
     'beds_or_units': 900, 'unit_label': 'facilities', 'countries': 2, 'occupancy_pct': 80.0,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['medpac_march_2025'], 'note': 'Margin column holds tenant rent coverage, not a % margin.'},
    {'player': 'National HealthCare Corp', 'country': 'US', 'segment': 'skilled nursing, home care, hospice', 'ownership': 'listed (NYSE American: NHC)',
     'revenue_bn': 1.35, 'currency': 'USD', 'fiscal_year': 2024, 'margin_metric': 'operating margin', 'margin_pct': 6.0,
     'beds_or_units': 80, 'unit_label': 'SNFs', 'countries': 1, 'occupancy_pct': 89.0,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['medpac_march_2025'], 'note': 'Owner-operator model; low leverage.'},
    {'player': 'PACS Group', 'country': 'US', 'segment': 'skilled nursing operator', 'ownership': 'listed (NYSE: PACS)',
     'revenue_bn': 4.0, 'currency': 'USD', 'fiscal_year': 2024, 'margin_metric': 'adjusted EBITDA', 'margin_pct': 9.0,
     'beds_or_units': 300, 'unit_label': 'facilities', 'countries': 1, 'occupancy_pct': 90.0,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['medpac_march_2025'], 'note': '2024 IPO; restated results after billing-practice allegations (2024–2025).'},
    {'player': 'Genesis HealthCare', 'country': 'US', 'segment': 'skilled nursing operator', 'ownership': 'private; Chapter 11 (July 2025)',
     'revenue_bn': None, 'currency': 'USD', 'fiscal_year': 2025, 'margin_metric': None, 'margin_pct': None,
     'beds_or_units': 175, 'unit_label': 'facilities', 'countries': 1, 'occupancy_pct': None,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['gao_pe_nursing_homes_2023'], 'note': 'Once the largest US SNF chain (>500 sites); sale-leaseback rent burden.'},
    {'player': 'Addus HomeCare', 'country': 'US', 'segment': 'personal care, hospice, home health', 'ownership': 'listed (NASDAQ: ADUS)',
     'revenue_bn': 1.15, 'currency': 'USD', 'fiscal_year': 2024, 'margin_metric': 'adjusted EBITDA', 'margin_pct': 12.0,
     'beds_or_units': None, 'unit_label': 'clients ~80,000', 'countries': 1, 'occupancy_pct': None,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['bls_projections_2023_2033'], 'note': 'Medicaid personal-care led; state rate dependence.'},
    {'player': 'Aveanna Healthcare', 'country': 'US', 'segment': 'home health, private-duty nursing', 'ownership': 'listed (NASDAQ: AVAH)',
     'revenue_bn': 2.0, 'currency': 'USD', 'fiscal_year': 2024, 'margin_metric': 'adjusted EBITDA', 'margin_pct': 9.0,
     'beds_or_units': None, 'unit_label': 'locations ~340', 'countries': 1, 'occupancy_pct': None,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['bls_projections_2023_2033'], 'note': 'Paediatric and adult home care; preferred-payer strategy.'},
    {'player': 'Amedisys (Optum / UnitedHealth)', 'country': 'US', 'segment': 'home health, hospice', 'ownership': 'acquired by UnitedHealth (2025)',
     'revenue_bn': 2.35, 'currency': 'USD', 'fiscal_year': 2024, 'margin_metric': 'adjusted EBITDA', 'margin_pct': 11.0,
     'beds_or_units': None, 'unit_label': 'care centres ~500', 'countries': 1, 'occupancy_pct': None,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['medpac_march_2025'], 'note': 'With LHC Group (2023) makes Optum the largest US home-health owner — payer-provider integration.'},
    {'player': 'Attendo', 'country': 'SE', 'segment': 'nursing homes, Nordic outsourcing', 'ownership': 'listed (Nasdaq Stockholm)',
     'revenue_bn': 19.3, 'currency': 'SEK', 'fiscal_year': 2024, 'margin_metric': 'EBITA', 'margin_pct': 7.0,
     'beds_or_units': 700, 'unit_label': 'units', 'countries': 3, 'occupancy_pct': 86.0,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['oecd_haag_2025'], 'note': 'Municipal outsourcing model; own-operated beds in Sweden and Finland.'},
    {'player': 'Ambea', 'country': 'SE', 'segment': 'elderly care, disability care', 'ownership': 'listed (Nasdaq Stockholm)',
     'revenue_bn': 14.0, 'currency': 'SEK', 'fiscal_year': 2024, 'margin_metric': 'EBITA', 'margin_pct': 9.5,
     'beds_or_units': 1_000, 'unit_label': 'units', 'countries': 3, 'occupancy_pct': None,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['oecd_haag_2025'], 'note': 'Vardaga / Nytida / Stendi brands.'},
    {'player': 'DomusVi', 'country': 'FR', 'segment': 'nursing homes, home care', 'ownership': 'private equity (ICG)',
     'revenue_bn': 2.0, 'currency': 'EUR', 'fiscal_year': 2024, 'margin_metric': 'EBITDAR', 'margin_pct': 18.0,
     'beds_or_units': 500, 'unit_label': 'facilities', 'countries': 6, 'occupancy_pct': 88.0,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['oecd_haag_2025'], 'note': 'France, Spain, Portugal, Latin America.'},
    {'player': 'Colisée', 'country': 'FR', 'segment': 'nursing homes', 'ownership': 'private equity (EQT)',
     'revenue_bn': 1.8, 'currency': 'EUR', 'fiscal_year': 2024, 'margin_metric': 'EBITDAR', 'margin_pct': 19.0,
     'beds_or_units': 400, 'unit_label': 'facilities', 'countries': 5, 'occupancy_pct': 89.0,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['oecd_haag_2025'], 'note': 'B-Corp certified; France, Belgium, Spain, Italy, China.'},
    {'player': 'Alloheim', 'country': 'DE', 'segment': 'nursing homes', 'ownership': 'private equity (Nordic Capital)',
     'revenue_bn': 1.3, 'currency': 'EUR', 'fiscal_year': 2024, 'margin_metric': 'EBITDAR', 'margin_pct': 17.0,
     'beds_or_units': 270, 'unit_label': 'facilities', 'countries': 1, 'occupancy_pct': 90.0,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['germany_bmg_pflege'], 'note': 'Largest German private chain; insolvency wave hit smaller German operators 2023–2024.'},
    {'player': 'HC-One', 'country': 'UK', 'segment': 'care homes', 'ownership': 'private (Safanad / Welltower-linked)',
     'revenue_bn': 1.0, 'currency': 'GBP', 'fiscal_year': 2024, 'margin_metric': 'EBITDAR', 'margin_pct': 16.0,
     'beds_or_units': 280, 'unit_label': 'homes', 'countries': 1, 'occupancy_pct': 88.0,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['uk_cma_care_homes_2017'], 'note': 'Formed from Southern Cross assets (2011); largest UK operator.'},
    {'player': 'Barchester Healthcare', 'country': 'UK', 'segment': 'care homes (premium)', 'ownership': 'private (Grove Ltd)',
     'revenue_bn': 1.0, 'currency': 'GBP', 'fiscal_year': 2024, 'margin_metric': 'EBITDAR', 'margin_pct': 24.0,
     'beds_or_units': 250, 'unit_label': 'homes', 'countries': 1, 'occupancy_pct': 90.0,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['uk_cma_care_homes_2017'], 'note': 'Self-funder weighted; highest UK margins.'},
    {'player': 'Bupa (care services)', 'country': 'UK', 'segment': 'care homes, retirement villages', 'ownership': 'mutual (provident)',
     'revenue_bn': 2.5, 'currency': 'GBP', 'fiscal_year': 2024, 'margin_metric': 'operating margin', 'margin_pct': 6.0,
     'beds_or_units': 300, 'unit_label': 'homes', 'countries': 5, 'occupancy_pct': 89.0,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['aus_royal_commission_2021'], 'note': 'UK, Australia, New Zealand, Spain, Poland; insurer-owned provider.'},
    {'player': 'Nichii Holdings', 'country': 'JP', 'segment': 'home care, nursing homes, staffing', 'ownership': 'private (Nippon Life, 2024)',
     'revenue_bn': 320.0, 'currency': 'JPY', 'fiscal_year': 2024, 'margin_metric': 'operating margin', 'margin_pct': 6.0,
     'beds_or_units': None, 'unit_label': 'branches ~1,400', 'countries': 1, 'occupancy_pct': None,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['japan_mhlw_kaigo'], 'note': 'Largest Japanese care provider; bought by a life insurer in 2024 — the insurer-provider hedge in practice.'},
    {'player': 'Sompo Care', 'country': 'JP', 'segment': 'nursing homes, home care', 'ownership': 'Sompo Holdings (insurer)',
     'revenue_bn': 150.0, 'currency': 'JPY', 'fiscal_year': 2024, 'margin_metric': 'operating margin', 'margin_pct': 5.0,
     'beds_or_units': 450, 'unit_label': 'facilities', 'countries': 1, 'occupancy_pct': 92.0,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['japan_mhlw_kaigo'], 'note': 'P&C insurer that bought Watami and Message care units (2015–2016).'},
    {'player': 'Danel (Adir Yeoshua)', 'country': 'IL', 'segment': 'home care, nursing homes, staffing', 'ownership': 'listed (TASE: DANE)',
     'revenue_bn': 2.5, 'currency': 'ILS', 'fiscal_year': 2024, 'margin_metric': 'operating margin', 'margin_pct': 7.0,
     'beds_or_units': None, 'unit_label': 'NII clients ~60,000', 'countries': 1, 'occupancy_pct': None,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['israel_comptroller_2026'], 'note': 'Largest NII home-care contractor (Matav); growth tracks the 2018 reform.'},
    {'player': 'Bayit Balev (Maccabi)', 'country': 'IL', 'segment': 'geriatric and rehabilitation hospitals, home care', 'ownership': 'HMO-owned',
     'revenue_bn': 0.9, 'currency': 'ILS', 'fiscal_year': 2024, 'margin_metric': 'operating margin', 'margin_pct': 4.0,
     'beds_or_units': 3_000, 'unit_label': 'beds', 'countries': 1, 'occupancy_pct': 93.0,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['taub_ltc_2024'], 'note': 'Vertically integrated with an HMO that also sells group LTC insurance.'},
]

_MARGIN_BENCHMARK_ROWS: List[Dict[str, Any]] = [
    {'segment': 'US skilled nursing — Medicare FFS margin', 'metric': 'Medicare margin', 'low_pct': 18.0, 'mid_pct': 22.0, 'high_pct': 25.0, 'year': 2023,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['medpac_march_2025'], 'note': 'Freestanding SNFs; 22nd consecutive year above 10%.'},
    {'segment': 'US skilled nursing — all-payer total margin', 'metric': 'total margin', 'low_pct': -2.0, 'mid_pct': 0.4, 'high_pct': 3.0, 'year': 2023,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['medpac_march_2025'], 'note': 'Medicaid long-stay rates below cost in most states.'},
    {'segment': 'US home health — Medicare margin', 'metric': 'Medicare margin', 'low_pct': 15.0, 'mid_pct': 20.2, 'high_pct': 24.0, 'year': 2023,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['medpac_march_2025'], 'note': 'Freestanding agencies; PDGM since 2020.'},
    {'segment': 'US non-medical home care (private pay / Medicaid)', 'metric': 'adjusted EBITDA', 'low_pct': 8.0, 'mid_pct': 11.0, 'high_pct': 14.0, 'year': 2024,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['bls_projections_2023_2033'], 'note': 'Addus 12%, Aveanna 9%; labour 70–80% of revenue.'},
    {'segment': 'US senior housing operating (SHOP) — NOI margin', 'metric': 'NOI margin', 'low_pct': 22.0, 'mid_pct': 27.0, 'high_pct': 33.0, 'year': 2025,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['nic_map_2025'], 'note': 'Welltower/Ventas SHOP; margins expand ~100 bp per 1 pt occupancy.'},
    {'segment': 'European nursing-home operators — EBITDAR', 'metric': 'EBITDAR margin', 'low_pct': 14.0, 'mid_pct': 18.0, 'high_pct': 24.0, 'year': 2025,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['clariane_fy2025', 'emeis_fy2025'], 'note': 'Clariane 21.6%, emeis 14.8%; rent takes 10–12 points.'},
    {'segment': 'European nursing-home operators — EBITDA after rent', 'metric': 'EBITDA margin (pre-IFRS 16)', 'low_pct': 5.0, 'mid_pct': 9.0, 'high_pct': 12.0, 'year': 2025,
     'figure_basis': BASIS_DERIVED, 'source_ids': ['clariane_fy2025'], 'note': 'Clariane €594m ÷ €5,310m = 11.2%.'},
    {'segment': 'UK care homes — self-funder weighted', 'metric': 'EBITDAR margin', 'low_pct': 18.0, 'mid_pct': 24.0, 'high_pct': 30.0, 'year': 2024,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['uk_cma_care_homes_2017'], 'note': 'Self-funders pay ~41% more than councils for the same bed.'},
    {'segment': 'UK care homes — council-funded weighted', 'metric': 'EBITDAR margin', 'low_pct': 8.0, 'mid_pct': 13.0, 'high_pct': 17.0, 'year': 2024,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['uk_cma_care_homes_2017'], 'note': 'Below sustainable return on new build.'},
    {'segment': 'Nordic municipal outsourcing', 'metric': 'EBITA margin', 'low_pct': 5.0, 'mid_pct': 8.0, 'high_pct': 10.0, 'year': 2024,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['oecd_haag_2025'], 'note': 'Attendo, Ambea; tender-price driven.'},
    {'segment': 'Japan Kaigo Hoken providers', 'metric': 'operating margin', 'low_pct': 2.0, 'mid_pct': 4.5, 'high_pct': 7.0, 'year': 2024,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['japan_mhlw_kaigo'], 'note': 'Triennial fee revisions; record provider bankruptcies 2024.'},
    {'segment': 'Israel NII home-care contractors', 'metric': 'operating margin', 'low_pct': 4.0, 'mid_pct': 7.0, 'high_pct': 9.0, 'year': 2024,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['israel_comptroller_2026'], 'note': 'Hourly tariff set by NII; cash-benefit option competes with agencies.'},
    {'segment': 'Care real estate — triple-net SNF lease yield', 'metric': 'cap rate', 'low_pct': 8.5, 'mid_pct': 10.0, 'high_pct': 12.0, 'year': 2025,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['nic_map_2025'], 'note': 'Rent coverage 1.3–1.8× EBITDAR is the covenant that matters.'},
    {'segment': 'Care real estate — senior housing cap rate', 'metric': 'cap rate', 'low_pct': 6.0, 'mid_pct': 7.0, 'high_pct': 8.0, 'year': 2025,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['nic_map_2025'], 'note': 'Construction starts at decade lows → pricing power 2025–2030.'},
]

_WORKFORCE_ROWS: List[Dict[str, Any]] = [
    {'region': 'oecd', 'metric': 'LTC workers per 100 people aged 65+', 'value': 5.0, 'unit': 'workers', 'year': 2023,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['oecd_haag_2025'], 'note': 'Norway 13.0, Greece 0.2; falling in the US, Denmark, Estonia, Belgium.'},
    {'region': 'us', 'metric': 'LTC workers per 100 people aged 65+', 'value': 4.0, 'unit': 'workers', 'year': 2023,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['oecd_haag_2025'], 'note': 'Declining ratio since 2011.'},
    {'region': 'us', 'metric': 'Nursing-care facility employment', 'value': 1.42, 'unit': 'million', 'year': 2025,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['bls_projections_2023_2033'], 'note': 'Still ~10% below the February 2020 peak of 1.59 million.'},
    {'region': 'us', 'metric': 'Home health and personal care aides', 'value': 3.9, 'unit': 'million', 'year': 2023,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['bls_projections_2023_2033'], 'note': '+21% to 2033; ~820,000 openings a year.'},
    {'region': 'us', 'metric': 'Nursing-home nursing staff turnover (median)', 'value': 53.0, 'unit': '% per year', 'year': 2022,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['cms_staffing_rule_2024_2025'], 'note': 'CMS Payroll-Based Journal; for-profit chains higher.'},
    {'region': 'us', 'metric': 'Median nursing-home total nurse staffing', 'value': 3.6, 'unit': 'HPRD', 'year': 2024,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['cms_staffing_rule_2024_2025'], 'note': 'About 75% of facilities were below the vacated 3.48 + 24/7 RN package once RN rules applied.'},
    {'region': 'us', 'metric': 'Home health aide median hourly wage', 'value': 35.0, 'unit': 'USD/hour billed', 'year': 2025,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['carescout_cost_of_care_2025'], 'note': 'Agency billing rate; aide take-home ≈ 50–55% of it.'},
    {'region': 'il', 'metric': 'NII home-care benefit recipients', 'value': 392_000.0, 'unit': 'people', 'year': 2025,
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['israel_comptroller_2026'], 'note': 'From ~180,000 in 2018; ~59% combine cash with personal care hours.'},
    {'region': 'il', 'metric': 'Foreign care workers in home care', 'value': 70_000.0, 'unit': 'people', 'year': 2024,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['taub_ltc_2024'], 'note': 'Live-in migrant carers are the backbone of 24/7 home care.'},
    {'region': 'jp', 'metric': 'Care workers (kaigo shokuin)', 'value': 2.15, 'unit': 'million', 'year': 2023,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['japan_mhlw_kaigo'], 'note': 'MHLW projects a 570,000 shortfall by 2040.'},
    {'region': 'de', 'metric': 'Nursing-care employees (Pflegestatistik)', 'value': 1.7, 'unit': 'million', 'year': 2023,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['germany_bmg_pflege'], 'note': 'Collective-bargaining pay mandate since September 2022 lifted costs ~10%.'},
    {'region': 'uk', 'metric': 'Adult social care filled posts', 'value': 1.7, 'unit': 'million', 'year': 2024,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['uk_cma_care_homes_2017'], 'note': 'Vacancy rate fell from 10% to ~8% after the 2022 health-and-care visa; route closed to new overseas recruits in 2025.'},
    {'region': 'nl', 'metric': 'LTC workers per 100 people aged 65+', 'value': 10.0, 'unit': 'workers', 'year': 2023,
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['oecd_haag_2025', 'nl_wlz_statistics'], 'note': 'High formal-care intensity; one in six workers needed in care by 2040.'},
]

_REGULATION_ROWS: List[Dict[str, Any]] = [
    {'jurisdiction': 'United States', 'code': 'us', 'financing_model': 'Medicaid means-tested + Medicare post-acute + private pay',
     'founding_statute': 'Social Security Amendments 1965; OBRA 1987', 'key_reform': 'Minimum staffing rule 2024 → vacated 2025 → repeal IFR effective 2 Feb 2026; enforcement barred to 2034',
     'staffing_standard': 'OBRA "sufficient staff"; RN 8 h/day; state minimums (e.g. NY 3.5 HPRD, CA 3.5)', 'quality_regime': 'CMS survey & certification, Five-Star, Payroll-Based Journal',
     'accommodation_standard': 'Life Safety Code; ≤2 beds per room for new construction', 'direction': 'federal retreat on staffing; state and litigation pressure persists',
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['cms_staffing_rule_2024_2025', 'kff_nursing_facilities_2025']},
    {'jurisdiction': 'Japan', 'code': 'jp', 'financing_model': 'Mandatory social LTC insurance (age 40+ premiums + tax), 10–30% co-pay',
     'founding_statute': 'Long-Term Care Insurance Act 2000', 'key_reform': 'Community-based integrated care (2012–2025); fee revision every 3 years',
     'staffing_standard': '3:1 resident-to-care-staff minimum; ICT-enabled 4:1 pilots', 'quality_regime': 'Prefectural licensing; third-party evaluation',
     'accommodation_standard': 'Unit-care private rooms standard since 2002 for new special nursing homes', 'direction': 'cost containment, productivity, foreign workers',
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['japan_mhlw_kaigo']},
    {'jurisdiction': 'Germany', 'code': 'de', 'financing_model': 'Mandatory partial-cover social LTC insurance (SGB XI) + resident co-payment',
     'founding_statute': 'Pflegeversicherungsgesetz 1995', 'key_reform': 'PSG II 2017 (five care grades); PUEG 2023 (contribution rise, relief grants)',
     'staffing_standard': 'Personnel-assessment procedure (PeBeM) phased in from 2023', 'quality_regime': 'MD quality audits; indicator-based public reporting',
     'accommodation_standard': 'State building codes; single-room quotas (e.g. NRW 80%)', 'direction': 'co-payments rising; contribution rate pressure',
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['germany_bmg_pflege']},
    {'jurisdiction': 'Netherlands', 'code': 'nl', 'financing_model': 'Universal Wlz (payroll-funded) for intensive care; Wmo municipalities; Zvw insurers',
     'founding_statute': 'AWBZ 1968 → Wlz 2015', 'key_reform': '2015 decentralisation cut institutional entitlement to the highest care profiles',
     'staffing_standard': 'Quality Framework Nursing Home Care 2017 (2 staff per 8 residents in daytime)', 'quality_regime': 'IGJ inspectorate; mandatory quality plans',
     'accommodation_standard': 'Small-scale living; private rooms', 'direction': 'care at home by default; bed cap',
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['nl_wlz_statistics']},
    {'jurisdiction': 'United Kingdom (England)', 'code': 'uk', 'financing_model': 'Means-tested local authority funding; NHS continuing care; self-funders',
     'founding_statute': 'National Assistance Act 1948; Care Act 2014', 'key_reform': 'Care-cost cap (£86,000) legislated 2021, deferred 2022, scrapped 2024',
     'staffing_standard': 'No numeric minimum; CQC "sufficient numbers" regulation 18', 'quality_regime': 'CQC ratings; Market Sustainability and Fair Cost of Care (2022)',
     'accommodation_standard': 'Care Home Regulations; en-suite single rooms for new build', 'direction': 'fair-cost-of-care funding; immigration tightening',
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['uk_cma_care_homes_2017']},
    {'jurisdiction': 'France', 'code': 'fr', 'financing_model': 'APA departmental allowance + health insurance care tariff + resident lodging fee',
     'founding_statute': 'APA 2002; Loi ASV 2015', 'key_reform': 'Post-Orpea controls 2022–2023; "Bien vieillir" law 2024',
     'staffing_standard': 'Target 0.8 staff per resident (2030 trajectory)', 'quality_regime': 'ARS/departmental inspections; HAS evaluation',
     'accommodation_standard': 'EHPAD authorisation; single rooms', 'direction': 'public-interest reporting of profits; staffing ratios',
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['emeis_fy2025', 'clariane_fy2025']},
    {'jurisdiction': 'Israel', 'code': 'il', 'financing_model': 'NII home benefit (payroll) + MoH nursing-hospital code (means-tested) + private insurance (60% covered)',
     'founding_statute': 'LTC Insurance Law 1986 (in force 1988); 2018 reform (six levels, cash option)', 'key_reform': '2018 reform tripled NII spend by 2025; cash benefit NIS 6.7bn',
     'staffing_standard': 'MoH geriatric licensing: nurse and aide ratios by ward type', 'quality_regime': 'MoH supervision; NII contractor tenders',
     'accommodation_standard': 'MoH "Program 2000" ward standards; ≤2–3 beds per room', 'direction': 'home-first; private insurance claims rising 7k → 18k a year',
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['taub_ltc_2024', 'israel_comptroller_2026']},
    {'jurisdiction': 'Australia', 'code': 'au', 'financing_model': 'Commonwealth subsidy (AN-ACC) + means-tested resident fees + refundable deposits',
     'founding_statute': 'Aged Care Act 1997 → Aged Care Act 2024 (in force 1 Nov 2025)', 'key_reform': 'Royal Commission 2021: 24/7 RN (2023), care-minute targets 200→215 per resident-day',
     'staffing_standard': '215 care minutes incl. 44 RN minutes per resident-day (from Oct 2024)', 'quality_regime': 'Star Ratings; Quality and Safety Commission',
     'accommodation_standard': 'Refundable Accommodation Deposit model; single rooms', 'direction': 'higher consumer contributions; rights-based act',
     'figure_basis': BASIS_PUBLISHED, 'source_ids': ['aus_royal_commission_2021']},
    {'jurisdiction': 'Korea', 'code': 'kr', 'financing_model': 'Mandatory LTC insurance (2008) alongside NHI; 15–20% co-pay',
     'founding_statute': 'Long-Term Care Insurance Act 2007', 'key_reform': 'Integrated community care act 2024',
     'staffing_standard': '2.1 residents per care worker (2025 target)', 'quality_regime': 'NHIS evaluations every 3 years',
     'accommodation_standard': 'Max 4 beds per room', 'direction': 'fastest-ageing OECD member; rapid bed growth',
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['oecd_haag_2025']},
    {'jurisdiction': 'Sweden', 'code': 'se', 'financing_model': 'Municipal tax-funded; income-related fees capped',
     'founding_statute': 'Social Services Act 1982; Ädel reform 1992', 'key_reform': 'Post-COVID inquiry 2020; elderly-care law proposal 2022–2025',
     'staffing_standard': 'No national ratio; municipal plans', 'quality_regime': 'IVO inspectorate; open comparisons',
     'accommodation_standard': 'Single apartments standard', 'direction': 'formal home care first; outsourcing ~20% of beds',
     'figure_basis': BASIS_ESTIMATE, 'source_ids': ['oecd_haag_2025']},
]

_SWOT_ROWS: List[Dict[str, Any]] = [
    {'quadrant': 'strength', 'item': 'Demand is demographic, not cyclical: the 80+ population doubles by 2050 in every region studied.', 'weight': 5, 'applies_to': 'all', 'source_ids': ['un_wpp_2024']},
    {'quadrant': 'strength', 'item': 'Public payers fund 60–93% of spend; revenue is government-backed even when rates lag.', 'weight': 4, 'applies_to': 'operator,real_estate', 'source_ids': ['oecd_haag_2025', 'cms_nhe_2024']},
    {'quadrant': 'strength', 'item': 'Operator revenue and 3+ADL claim frequency move together, giving an insurer a natural hedge.', 'weight': 5, 'applies_to': 'insurer', 'source_ids': ['phins_ltc_life_study']},
    {'quadrant': 'strength', 'item': 'Senior-housing supply is at decade lows while occupancy is back near 89%, supporting rate growth.', 'weight': 4, 'applies_to': 'real_estate', 'source_ids': ['nic_map_2025']},
    {'quadrant': 'strength', 'item': 'Home care needs little capital and bills by the hour; margins of 8–12% scale with volume.', 'weight': 3, 'applies_to': 'home_care', 'source_ids': ['medpac_march_2025']},
    {'quadrant': 'weakness', 'item': 'Labour is 55–80% of cost; turnover above 50% a year and wage inflation erode margins first.', 'weight': 5, 'applies_to': 'all', 'source_ids': ['cms_staffing_rule_2024_2025', 'bls_projections_2023_2033']},
    {'quadrant': 'weakness', 'item': 'All-payer nursing-home margins near zero; profits depend on Medicare/self-funder cross-subsidy.', 'weight': 4, 'applies_to': 'operator', 'source_ids': ['medpac_march_2025', 'uk_cma_care_homes_2017']},
    {'quadrant': 'weakness', 'item': 'Opco-propco leverage (sale-leaseback rents) has broken Southern Cross, Four Seasons, Genesis and nearly Orpea.', 'weight': 5, 'applies_to': 'operator,real_estate', 'source_ids': ['emeis_fy2025', 'gao_pe_nursing_homes_2023']},
    {'quadrant': 'weakness', 'item': 'Reputation risk is binary: one abuse scandal re-prices a whole national sector (Orpea 2022, Australia 2018).', 'weight': 4, 'applies_to': 'operator', 'source_ids': ['aus_royal_commission_2021', 'emeis_fy2025']},
    {'quadrant': 'weakness', 'item': 'Private LTC insurance penetration is low outside Israel (60%) and Germany (mandatory); hedge sizing is small relative to national spend.', 'weight': 2, 'applies_to': 'insurer', 'source_ids': ['taub_ltc_2024']},
    {'quadrant': 'opportunity', 'item': 'Home-first policy shifts 8–20 points of recipients to home care; platforms with nursing capability win share.', 'weight': 5, 'applies_to': 'home_care', 'source_ids': ['israel_comptroller_2026', 'germany_bmg_pflege']},
    {'quadrant': 'opportunity', 'item': 'High-acuity beds (dementia, ventilator, post-acute) stay scarce as light-care beds close.', 'weight': 4, 'applies_to': 'operator,real_estate', 'source_ids': ['nl_wlz_statistics', 'oecd_haag_2025']},
    {'quadrant': 'opportunity', 'item': 'Insurer-provider integration (Nippon Life–Nichii, Sompo Care, Optum–Amedisys, Maccabi–Bayit Balev) converts claims cost into owned revenue.', 'weight': 5, 'applies_to': 'insurer', 'source_ids': ['japan_mhlw_kaigo', 'medpac_march_2025', 'taub_ltc_2024']},
    {'quadrant': 'opportunity', 'item': 'Distressed European and German portfolios trade below replacement cost after the 2022–2024 insolvency wave.', 'weight': 3, 'applies_to': 'real_estate', 'source_ids': ['emeis_fy2025', 'germany_bmg_pflege']},
    {'quadrant': 'opportunity', 'item': 'Remote monitoring and care robotics lift aide productivity 10–20%, the only durable margin lever.', 'weight': 3, 'applies_to': 'home_care,operator', 'source_ids': ['japan_mhlw_kaigo']},
    {'quadrant': 'threat', 'item': 'Fiscal squeeze: public fee schedules capped below cost inflation (Japan triennial, Medicaid, UK councils).', 'weight': 5, 'applies_to': 'operator,home_care', 'source_ids': ['japan_mhlw_kaigo', 'medpac_march_2025']},
    {'quadrant': 'threat', 'item': 'Staffing mandates return (Australia 215 minutes, France 0.8, US states) and lift cost 8–15% without rate relief.', 'weight': 4, 'applies_to': 'operator', 'source_ids': ['aus_royal_commission_2021', 'cms_staffing_rule_2024_2025']},
    {'quadrant': 'threat', 'item': 'Immigration limits (UK 2025 visa closure, Israel quotas) choke the care labour supply.', 'weight': 4, 'applies_to': 'all', 'source_ids': ['uk_cma_care_homes_2017', 'taub_ltc_2024']},
    {'quadrant': 'threat', 'item': 'A disease-modifying dementia therapy at scale cuts severe-disability prevalence 15–25% and strands residential capacity.', 'weight': 3, 'applies_to': 'operator,real_estate', 'source_ids': ['un_wpp_2024']},
    {'quadrant': 'threat', 'item': 'Pandemic-type shocks: occupancy fell 10+ points in 2020–2021 and took four years to recover.', 'weight': 3, 'applies_to': 'operator,real_estate', 'source_ids': ['kff_nursing_facilities_2025', 'nic_map_2025']},
]

_CASE_STUDY_ROWS: List[Dict[str, Any]] = [
    {'id': 'orpea_emeis', 'title': 'Orpea → emeis (France, 2022–2025)', 'jurisdiction': 'FR/EU', 'period': '2022–2025', 'segment': 'private nursing homes',
     'what_happened': '"Les Fossoyeurs" exposed rationing and misuse of public funds; shares fell >90%, €9.5bn debt restructured, Caisse des Dépôts took control.',
     'lesson': 'Quality failure is a solvency event; leverage above ~6× EBITDA leaves no cushion for a reputational shock.',
     'metric': 'leverage 19.5× (2024) → 9.9× (2025); EBITDAR margin 13.1% → 14.8%', 'source_ids': ['emeis_fy2025']},
    {'id': 'southern_cross_four_seasons', 'title': 'Southern Cross (2011) and Four Seasons (2019), UK', 'jurisdiction': 'UK', 'period': '2006–2019', 'segment': 'private care homes',
     'what_happened': 'Sale-and-leaseback with upward-only rents met falling council fees; both largest UK chains collapsed, 750+ homes re-homed.',
     'lesson': 'Property yield extracted up-front becomes a fixed cost the public payer will not fund.',
     'metric': 'councils paid ~41% less than self-funders for the same bed', 'source_ids': ['uk_cma_care_homes_2017']},
    {'id': 'genesis_2025', 'title': 'Genesis HealthCare Chapter 11 (US, July 2025)', 'jurisdiction': 'US', 'period': '2017–2025', 'segment': 'skilled nursing chain',
     'what_happened': 'Once >500 facilities; rent burden, Medicaid shortfalls and post-COVID census losses ended in bankruptcy with ~175 sites.',
     'lesson': 'Scale without local density and owned real estate does not protect a Medicaid-heavy operator.',
     'metric': 'US all-payer SNF margin ≈0.4% (2023)', 'source_ids': ['medpac_march_2025', 'gao_pe_nursing_homes_2023']},
    {'id': 'ensign_model', 'title': 'Ensign Group — decentralised turnaround model (US)', 'jurisdiction': 'US', 'period': '2010–2025', 'segment': 'skilled nursing operator',
     'what_happened': 'Buys under-performing facilities, keeps local leadership, owns an increasing share of real estate; revenue 2024 $4.26bn → 2025 $5.06bn.',
     'lesson': 'Operator skill plus owned property outperforms financial engineering; the best-in-class margin is ~12% EBITDA.',
     'metric': 'occupancy 82.2%, adj. EBITDA 11.9%, 373 operations', 'source_ids': ['ensign_fy2025']},
    {'id': 'japan_kaigo', 'title': 'Japan Kaigo Hoken (2000–2025)', 'jurisdiction': 'JP', 'period': '2000–2025', 'segment': 'public social insurance',
     'what_happened': 'Universal LTC insurance tripled recipients while holding institutional share flat through community-based integrated care and triennial fee cuts.',
     'lesson': 'A super-aged society can cap bed growth, but provider margins fall to 2–5% and bankruptcies rise.',
     'metric': '80+ share 10.8% (2025) → 16% (2050)', 'source_ids': ['japan_mhlw_kaigo', 'un_wpp_2024']},
    {'id': 'germany_pflege', 'title': 'Germany Pflegeversicherung (1995–2025)', 'jurisdiction': 'DE', 'period': '1995–2025', 'segment': 'partial-cover social insurance',
     'what_happened': 'Cash benefit (Pflegegeld) kept four in five beneficiaries at home; nursing-home co-payments rose past €2,800/month, prompting 2022–2024 relief grants.',
     'lesson': 'Partial cover shifts cost to residents and creates a private top-up insurance and operator-margin squeeze at the same time.',
     'metric': '~5.7 million beneficiaries; 80% at home', 'source_ids': ['germany_bmg_pflege']},
    {'id': 'netherlands_wlz', 'title': 'Netherlands Wlz reform (2015)', 'jurisdiction': 'NL', 'period': '2015–2024', 'segment': 'universal public LTC',
     'what_happened': 'Lighter care moved to municipalities and insurers; institutional entitlement limited to the highest profiles; beds per 1,000 65+ fell steadily.',
     'lesson': 'Even the highest-spending system (4.1% of GDP) de-institutionalises when cost pressure bites.',
     'metric': 'LTC 4.1% of GDP, highest in OECD', 'source_ids': ['nl_wlz_statistics', 'oecd_haag_2025']},
    {'id': 'israel_2018_reform', 'title': 'Israel NII reform (2018–2025)', 'jurisdiction': 'IL', 'period': '2018–2025', 'segment': 'public home-care benefit',
     'what_happened': 'Six benefit levels and a cash option tripled spend (NIS 7bn → 21.1bn) and doubled recipients (180k → 392k); 93% of private-insurance claimants stay home.',
     'lesson': 'A cash option expands take-up fastest; residential demand stays flat while home-care contractors and private insurers both grow.',
     'metric': '30% of retirement-age Israelis receive the benefit', 'source_ids': ['israel_comptroller_2026', 'taub_ltc_2024']},
    {'id': 'covid_19', 'title': 'COVID-19 in residential care (2020–2024)', 'jurisdiction': 'global', 'period': '2020–2024', 'segment': 'all residential',
     'what_happened': 'Residents were ~40% of early deaths in many OECD countries; US nursing-home residents fell from 1.32m to 1.10m; senior-housing occupancy troughed at 78%.',
     'lesson': 'Tail risk is correlated across operators; insurers saw mortality offsets while operators lost census — the hedge works both ways.',
     'metric': 'US residents 1.37m (2015) → 1.10m (2021) → 1.24m (2025)', 'source_ids': ['kff_nursing_facilities_2025', 'nic_map_2025']},
    {'id': 'optum_home_health', 'title': 'Payer-provider integration: Optum–LHC–Amedisys (US, 2023–2025)', 'jurisdiction': 'US', 'period': '2023–2025', 'segment': 'home health',
     'what_happened': 'UnitedHealth bought LHC Group ($5.4bn) and Amedisys ($3.3bn after DOJ divestitures), making an insurer the largest home-health owner.',
     'lesson': 'The insurer that owns the care path captures the Medicare home-health margin (20%) instead of paying it.',
     'metric': 'home-health Medicare margin 20.2%', 'source_ids': ['medpac_march_2025']},
    {'id': 'pe_nursing_homes', 'title': 'Private equity in US nursing homes (2004–2023)', 'jurisdiction': 'US', 'period': '2004–2023', 'segment': 'private nursing homes',
     'what_happened': 'HCR ManorCare (Carlyle, 2007 → bankruptcy 2018) and others; GAO counts ~5% PE ownership; studies link PE deals to lower staffing and higher mortality.',
     'lesson': 'Regulators now demand ownership transparency; the discount for opaque structures will widen.',
     'metric': '~5% of US nursing homes PE-owned (2022)', 'source_ids': ['gao_pe_nursing_homes_2023']},
    {'id': 'australia_royal_commission', 'title': 'Australian Royal Commission → Aged Care Act 2024', 'jurisdiction': 'AU', 'period': '2018–2025', 'segment': 'public-subsidised private providers',
     'what_happened': '"Neglect" report drove 24/7 RN cover, 215 care minutes, star ratings and a rights-based Act with higher consumer co-contributions.',
     'lesson': 'Quality inquiries end in numeric staffing law; the cost is shared between taxpayer and resident, not absorbed by the operator alone.',
     'metric': '215 care minutes per resident-day incl. 44 RN minutes', 'source_ids': ['aus_royal_commission_2021']},
    {'id': 'insurer_owned_care_japan', 'title': 'Insurer-owned care in Japan: Sompo Care and Nippon Life–Nichii', 'jurisdiction': 'JP', 'period': '2015–2024', 'segment': 'insurer–provider',
     'what_happened': 'Sompo bought Watami and Message (2015–2016); Nippon Life acquired Nichii Holdings (2024) for ~¥210bn.',
     'lesson': 'Japanese insurers treat care operators as a longevity hedge and a distribution channel — the template for the PHINS hedge model.',
     'metric': 'Nichii revenue ≈¥320bn; Sompo Care ≈¥150bn', 'source_ids': ['japan_mhlw_kaigo']},
]

_ILLUSTRATIONS: List[Dict[str, str]] = [
    {'id': 'care_settings_spectrum', 'title': 'The care-setting spectrum', 'kind': 'image',
     'url': '/research/ltc-residential/care-settings-spectrum.svg',
     'caption': 'From family and home care through assisted living to nursing homes and geriatric hospitals — acuity, cost and regulation rise left to right.'},
    {'id': 'payer_flows', 'title': 'Who pays for long-term care', 'kind': 'image',
     'url': '/research/ltc-residential/payer-flows.svg',
     'caption': 'Public insurance and means-tested budgets carry four of five dollars in the OECD; households and private insurance fill the gap.'},
    {'id': 'hedge_architecture', 'title': 'PHINS hedge architecture', 'kind': 'image',
     'url': '/research/ltc-residential/hedge-architecture.svg',
     'caption': 'A 3+ADL book pays claims when disability rises; operator, care-property and home-care income rise with the same event.'},
    {'id': 'fifty_year_timeline', 'title': 'Fifty years back, fifty years forward', 'kind': 'image',
     'url': '/research/ltc-residential/fifty-year-timeline.svg',
     'caption': 'Market eras 1965–2075: from Medicaid build-out to the longevity steady state.'},
]

_EXTERNAL_PUBLICATIONS: List[Dict[str, str]] = [
    {'title': 'OECD Health at a Glance 2025 — long-term care', 'url': 'https://www.oecd.org/en/publications/health-at-a-glance-2025_8f9e3f98-en.html', 'kind': 'report'},
    {'title': 'CMS National Health Expenditure historical tables', 'url': 'https://www.cms.gov/data-research/statistics-trends-and-reports/national-health-expenditure-data/historical', 'kind': 'dataset'},
    {'title': 'KFF nursing facility characteristics', 'url': 'https://www.kff.org/medicaid/a-look-at-nursing-facility-characteristics/', 'kind': 'brief'},
    {'title': 'CareScout Cost of Care Survey', 'url': 'https://www.carescout.com/cost-of-care', 'kind': 'survey'},
    {'title': 'MedPAC March 2025 report', 'url': 'https://www.medpac.gov/document/march-2025-report-to-the-congress-medicare-payment-policy/', 'kind': 'report'},
    {'title': 'European Commission 2024 Ageing Report', 'url': 'https://economy-finance.ec.europa.eu/publications/2024-ageing-report-economic-and-budgetary-projections-eu-member-states-2022-2070_en', 'kind': 'report'},
    {'title': 'Royal Commission into Aged Care Quality and Safety', 'url': 'https://www.royalcommission.gov.au/aged-care', 'kind': 'inquiry'},
    {'title': 'UN World Population Prospects 2024', 'url': 'https://population.un.org/wpp/', 'kind': 'dataset'},
]

_MEDIA_KEYWORDS = (
    'long-term care', 'long term care', 'ltc', 'nursing home', 'nursing-home', 'care home',
    'home care', 'homecare', 'assisted living', 'senior living', 'geriatric', 'elder care',
    'eldercare', 'aged care', 'סיעוד', 'דיור מוגן', 'בית אבות', 'קשיש',
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _integrity_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _r(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def _cagr(start: float, end: float, years: int) -> Optional[float]:
    if start <= 0 or end <= 0 or years <= 0:
        return None
    return _r(100.0 * ((end / start) ** (1.0 / years) - 1.0), 2)


def _era_for(year: int) -> Tuple[str, str]:
    for start, end, key, _desc, _theme in _ERAS:
        if start <= year <= end:
            return key, _theme
    for start, end, key, desc in _FORECAST_ERAS:
        if start <= year <= end:
            return key, desc
    return _ERAS[0][2], _ERAS[0][4]


def _pop80_share(region: Dict[str, Any], year: int) -> float:
    anchors = region['pop80_share']
    return _interp(anchors, year)


def _scenario_recipient_factor(scenario: Dict[str, Any], year: int) -> float:
    anchors = {2025: 1.0, 2050: scenario['recipient_factor_2050'], 2075: scenario['recipient_factor_2075']}
    return _interp(anchors, year)


def _home_share_target(params: ResidentialResearchParams, region: Dict[str, Any], scenario: Dict[str, Any]) -> float:
    base_res = region['residential_recipient_share_pct']
    if params.home_care_share_target_pct >= 0:
        return _clamp(params.home_care_share_target_pct, 30.0, 95.0)
    target_res = base_res * (1.0 - scenario['residential_share_reduction_pct'] / 100.0)
    return _clamp(100.0 - target_res, 30.0, 95.0)


def _home_share(params: ResidentialResearchParams, region: Dict[str, Any], scenario: Dict[str, Any], year: int) -> float:
    base_home = 100.0 - region['residential_recipient_share_pct']
    target = _home_share_target(params, region, scenario)
    return _interp({2025: base_home, 2050: target, 2075: target}, year)


# ---------------------------------------------------------------------------
# Table builders — history
# ---------------------------------------------------------------------------

def _build_spending_history() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    years = sorted(set(_US_NHE_NURSING_BN) | set(_US_NHE_HOME_HEALTH_BN))
    prev_total = None
    prev_year = None
    for year in years:
        nursing = _US_NHE_NURSING_BN[year]
        home = _US_NHE_HOME_HEALTH_BN[year]
        total = nursing + home
        era_key, era_theme = _era_for(year)
        growth = None
        if prev_total is not None and prev_year is not None:
            growth = _cagr(prev_total, total, year - prev_year)
        rows.append({
            'year': year,
            'era': era_key,
            'nursing_care_bn': _r(nursing, 1),
            'home_health_bn': _r(home, 1),
            'total_ltc_bn': _r(total, 1),
            'home_health_share_pct': _r(100.0 * home / total, 1),
            'cagr_since_prior_row_pct': growth,
            'figure_basis': BASIS_PUBLISHED,
            'source_ids': ['cms_nhe_2024'],
            'era_theme': era_theme,
        })
        prev_total, prev_year = total, year
    return rows


def _build_cost_of_care() -> List[Dict[str, Any]]:
    by_setting: Dict[str, Dict[int, float]] = {}
    for year, setting, cost, _basis, _src in _COST_OF_CARE_ROWS:
        by_setting.setdefault(setting, {})[year] = cost
    rows: List[Dict[str, Any]] = []
    for year, setting, cost, basis, sources in _COST_OF_CARE_ROWS:
        series = by_setting[setting]
        first_year = min(series)
        cagr = _cagr(series[first_year], cost, year - first_year) if year > first_year else None
        semi = by_setting['nursing_semi_private'].get(year)
        rows.append({
            'year': year,
            'setting': setting,
            'setting_label': _SETTING_LABELS.get(setting, setting),
            'annual_cost_usd': _r(cost, 0),
            'monthly_cost_usd': _r(cost / 12.0, 0),
            'relative_to_semi_private': _r(cost / semi, 3) if semi else None,
            'cagr_since_first_survey_pct': cagr,
            'figure_basis': basis,
            'source_ids': list(sources),
        })
    return rows


def _build_payer_mix() -> List[Dict[str, Any]]:
    rows = []
    for item in _PAYER_MIX_ROWS:
        row = dict(item)
        parts = [row.get(k) for k in ('public_pct', 'private_insurance_pct', 'out_of_pocket_pct', 'other_pct')]
        known = [p for p in parts if p is not None]
        row['shares_total_pct'] = _r(sum(known), 1) if known else None
        row['shares_complete'] = all(p is not None for p in parts)
        rows.append(row)
    return rows


def _build_market_structure() -> List[Dict[str, Any]]:
    rows = []
    for code, region in _REGIONS.items():
        pop80_2025 = _pop80_share(region, 2025)
        pop80_2050 = _pop80_share(region, 2050)
        rows.append({
            'region': code,
            'label': region['label'],
            'ltc_spend_gdp_pct': region['ltc_spend_gdp_pct'],
            'ltc_spend_year': region['ltc_spend_year'],
            'ltc_spend_basis': region['ltc_spend_basis'],
            'public_share_pct': region['public_share_pct'],
            'public_share_basis': region['public_share_basis'],
            'residential_recipient_share_pct': region['residential_recipient_share_pct'],
            'home_recipient_share_pct': _r(100.0 - region['residential_recipient_share_pct'], 1),
            'beds_per_1000_65plus': region['beds_per_1000_65plus'],
            'workers_per_100_65plus': region['workers_per_100_65plus'],
            'for_profit_share_pct': region['for_profit_share_pct'],
            'private_provision_share_pct': region['private_provision_share_pct'],
            'pop80_share_2025_pct': pop80_2025,
            'pop80_share_2050_pct': pop80_2050,
            'pop80_growth_to_2050_pct': _r(100.0 * (pop80_2050 / pop80_2025 - 1.0), 1),
            'ltc_spend_2025_usd_bn': _r(region['gdp_2025_usd_bn'] * region['ltc_spend_gdp_pct'] / 100.0, 1),
            'figure_basis': BASIS_DERIVED,
            'source_ids': list(region['source_ids']),
            'note': region['note'],
        })
    return rows


def _build_eras() -> List[Dict[str, Any]]:
    rows = []
    for start, end, key, desc, theme in _ERAS:
        rows.append({'start': start, 'end': end, 'era': key, 'kind': 'history', 'description': desc, 'theme': theme,
                     'figure_basis': BASIS_PUBLISHED})
    for start, end, key, desc in _FORECAST_ERAS:
        rows.append({'start': start, 'end': end, 'era': key, 'kind': 'forecast', 'description': desc, 'theme': desc.split(';')[0],
                     'figure_basis': BASIS_PROJECTION})
    return rows


# ---------------------------------------------------------------------------
# Table builders — forecast, TAM/SAM/SOM, scenarios
# ---------------------------------------------------------------------------

def _forecast_row(params: ResidentialResearchParams, region: Dict[str, Any], scenario: Dict[str, Any], year: int,
                  base_cost_weight: float) -> Dict[str, Any]:
    t = year - 2025
    pop_ratio = _pop80_share(region, year) / _pop80_share(region, 2025)
    healthy = (1.0 - params.healthy_ageing_pct / 100.0) ** max(0, t)
    recipients_index = 100.0 * pop_ratio * healthy * _scenario_recipient_factor(scenario, year)
    home_share = _home_share(params, region, scenario, year)
    residential_share = 100.0 - home_share
    base_res_share = region['residential_recipient_share_pct']
    base_home_share = 100.0 - base_res_share
    residential_index = recipients_index * residential_share / base_res_share
    home_index = recipients_index * home_share / base_home_share
    cost_weight = (residential_share / 100.0) * 1.0 + (home_share / 100.0) * _HOME_COST_FACTOR
    relative_cost = (1.0 + (params.care_cost_inflation_pct - params.gdp_growth_pct
                            + scenario['relative_cost_delta_pct']) / 100.0) ** max(0, t)
    spend_gdp = region['ltc_spend_gdp_pct'] * (recipients_index / 100.0) * (cost_weight / base_cost_weight) * relative_cost
    gdp = region['gdp_2025_usd_bn'] * (1.0 + params.gdp_growth_pct / 100.0) ** max(0, t)
    nominal = gdp * spend_gdp / 100.0
    public_share = _clamp(region['public_share_pct'] + _interp({2025: 0.0, 2075: scenario['public_share_delta_2075']}, year), 20.0, 98.0)
    residential_spend_share = (residential_share / 100.0) / cost_weight
    era_key, era_note = _era_for(year)
    nominal_r = _r(nominal, 1)
    residential_r = _r(nominal * residential_spend_share, 1)
    home_r = _r(nominal_r - residential_r, 1)
    home_share_r = _r(home_share, 1)
    return {
        'year': year,
        'era': era_key,
        'pop80_share_pct': _r(_pop80_share(region, year), 2),
        'recipients_index': _r(recipients_index, 1),
        'home_share_pct': home_share_r,
        'residential_share_pct': _r(100.0 - home_share_r, 1),
        'residential_demand_index': _r(residential_index, 1),
        'home_demand_index': _r(home_index, 1),
        'ltc_spend_gdp_pct': _r(spend_gdp, 3),
        'gdp_usd_bn': _r(gdp, 0),
        'ltc_spend_usd_bn': nominal_r,
        'ltc_spend_at_2025_gdp_usd_bn': _r(region['gdp_2025_usd_bn'] * spend_gdp / 100.0, 1),
        'residential_spend_usd_bn': residential_r,
        'home_spend_usd_bn': home_r,
        'public_share_pct': _r(public_share, 1),
        'private_spend_usd_bn': _r(nominal * (1.0 - public_share / 100.0), 1),
        'relative_cost_index': _r(100.0 * relative_cost, 1),
        'figure_basis': BASIS_PROJECTION if year > 2025 else BASIS_DERIVED,
        'era_note': era_note,
    }


def _build_demand_forecast(params: ResidentialResearchParams) -> List[Dict[str, Any]]:
    region = _REGIONS[params.region]
    scenario = _SCENARIOS[params.scenario]
    base_res = region['residential_recipient_share_pct'] / 100.0
    base_cost_weight = base_res * 1.0 + (1.0 - base_res) * _HOME_COST_FACTOR
    rows = []
    for year in range(2025, params.forecast_end + 1):
        rows.append(_forecast_row(params, region, scenario, year, base_cost_weight))
    return rows


def _build_tam_som(params: ResidentialResearchParams, forecast: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    region = _REGIONS[params.region]
    private_provision = region['private_provision_share_pct'] / 100.0
    som_share = params.som_share_pct / 100.0
    milestones = [y for y in (2025, 2030, 2035, 2040, 2050, 2060, 2075) if y <= params.forecast_end]
    if params.forecast_end not in milestones:
        milestones.append(params.forecast_end)
    by_year = {row['year']: row for row in forecast}
    rows = []
    for year in milestones:
        row = by_year.get(year)
        if not row:
            continue
        scale_2025 = row['ltc_spend_at_2025_gdp_usd_bn'] / row['ltc_spend_usd_bn'] if row['ltc_spend_usd_bn'] else 0.0
        for segment, spend in (
            ('residential', row['residential_spend_usd_bn']),
            ('home_care', row['home_spend_usd_bn']),
            ('total', row['ltc_spend_usd_bn']),
        ):
            tam = float(spend)
            sam = tam * private_provision
            som = sam * som_share
            rows.append({
                'year': year,
                'segment': segment,
                'tam_usd_bn': _r(tam, 2),
                'tam_at_2025_gdp_usd_bn': _r(tam * scale_2025, 2),
                'sam_usd_bn': _r(sam, 2),
                'som_usd_bn': _r(som, 3),
                'private_provision_share_pct': region['private_provision_share_pct'],
                'som_share_of_sam_pct': params.som_share_pct,
                'public_share_pct': row['public_share_pct'],
                'figure_basis': BASIS_PROJECTION if year > 2025 else BASIS_DERIVED,
            })
    return rows


def _build_scenarios(params: ResidentialResearchParams) -> List[Dict[str, Any]]:
    rows = []
    for key in _SCENARIOS:
        alt = ResidentialResearchParams(**{**asdict(params), 'scenario': key})
        fc = _build_demand_forecast(alt)
        by_year = {r['year']: r for r in fc}
        y2050 = by_year.get(2050) or fc[-1]
        yend = fc[-1]
        rows.append({
            'scenario': key,
            'label': _SCENARIOS[key]['label'],
            'selected': key == params.scenario,
            'home_share_target_pct': _r(_home_share_target(alt, _REGIONS[alt.region], _SCENARIOS[key]), 1),
            'recipients_index_2050': y2050['recipients_index'],
            'residential_demand_index_2050': y2050['residential_demand_index'],
            'ltc_spend_gdp_pct_2050': y2050['ltc_spend_gdp_pct'],
            'ltc_spend_usd_bn_2050': y2050['ltc_spend_usd_bn'],
            'recipients_index_end': yend['recipients_index'],
            'residential_demand_index_end': yend['residential_demand_index'],
            'ltc_spend_gdp_pct_end': yend['ltc_spend_gdp_pct'],
            'ltc_spend_usd_bn_end': yend['ltc_spend_usd_bn'],
            'public_share_pct_end': yend['public_share_pct'],
            'end_year': yend['year'],
            'note': _SCENARIOS[key]['note'],
            'figure_basis': BASIS_PROJECTION,
        })
    return rows


# ---------------------------------------------------------------------------
# Hedge model (3+ADL book vs care-sector income)
# ---------------------------------------------------------------------------

def _bands_in_range(params: ResidentialResearchParams) -> List[Tuple[int, int]]:
    bands = []
    for lo, hi in AGE_BANDS:
        if hi <= params.age_min or lo >= params.age_max:
            continue
        bands.append((max(lo, params.age_min), min(hi, params.age_max)))
    return bands


def _build_hedge_book(params: ResidentialResearchParams) -> List[Dict[str, Any]]:
    bands = _bands_in_range(params)
    if not bands:
        return []
    total_width = sum(hi - lo for lo, hi in bands)
    factor = _adl_incidence_factor(params.adl_threshold)
    rows = []
    allocated = 0
    for index, (lo, hi) in enumerate(bands):
        if index == len(bands) - 1:
            band_lives = params.lives - allocated
        else:
            band_lives = int(round(params.lives * (hi - lo) / float(total_width)))
            allocated += band_lives
        mid = _mid_age(lo, hi)
        incidence = _ltc3_incidence_per_1000(mid) * factor / 1000.0
        duration = _remaining_le_after_3adl(mid, 0.0)
        prevalence = min(0.95, incidence * duration)
        annual_claims = band_lives * prevalence * params.ltc_annual_cover
        new_claim_cost = band_lives * incidence * params.ltc_annual_cover * duration
        rows.append({
            'age_min': lo,
            'age_max': hi,
            'attained_age': _r(mid, 1),
            'band_lives': band_lives,
            'adl_threshold': params.adl_threshold,
            'incidence_per_1000': _r(incidence * 1000.0, 3),
            'mean_claim_duration_years': _r(duration, 2),
            'steady_state_prevalence_pct': _r(100.0 * prevalence, 3),
            'expected_annual_claims': _r(annual_claims, 0),
            'expected_new_claim_cost': _r(new_claim_cost, 0),
            'stressed_annual_claims': _r(annual_claims * (1.0 + params.incidence_stress_pct / 100.0), 0),
            'figure_basis': BASIS_MODEL,
            'source_ids': ['phins_ltc_life_study'],
        })
    return rows


def _build_hedge_allocation(params: ResidentialResearchParams, expected_claims: float) -> List[Dict[str, Any]]:
    preset = _HEDGE_PRESETS[params.hedge_allocation]
    stress = params.incidence_stress_pct / 100.0
    rows = []
    for key, weight in preset.items():
        asset = _HEDGE_ASSETS[key]
        capital = params.hedge_capital * weight / 100.0
        income = capital * asset['yield_pct'] / 100.0
        stressed_income = income * (1.0 + stress * asset['claim_beta'])
        rows.append({
            'asset_class': key,
            'label': asset['label'],
            'allocation_pct': weight,
            'capital': _r(capital, 0),
            'yield_pct': asset['yield_pct'],
            'claim_beta': asset['claim_beta'],
            'expected_income': _r(income, 0),
            'stressed_income': _r(stressed_income, 0),
            'income_uplift_under_stress': _r(stressed_income - income, 0),
            'income_to_claims_pct': _r(100.0 * income / expected_claims, 2) if expected_claims > 0 else None,
            'liquidity': asset['liquidity'],
            'volatility': asset['volatility'],
            'rationale': asset['rationale'],
            'figure_basis': BASIS_MODEL,
        })
    return rows


def _hedge_summary(params: ResidentialResearchParams, book: List[Dict[str, Any]],
                   allocation: List[Dict[str, Any]]) -> Dict[str, Any]:
    expected = sum(r['expected_annual_claims'] for r in book)
    stressed = sum(r['stressed_annual_claims'] for r in book)
    income = sum(r['expected_income'] for r in allocation)
    stressed_income = sum(r['stressed_income'] for r in allocation)
    claim_delta = stressed - expected
    income_delta = stressed_income - income
    pv_factor = 0.0
    rate = params.discount_rate_pct / 100.0
    for year in range(1, 11):
        pv_factor += 1.0 / ((1.0 + rate) ** year)
    return {
        'book_lives': params.lives,
        'expected_annual_claims': _r(expected, 0),
        'stressed_annual_claims': _r(stressed, 0),
        'claims_delta_under_stress': _r(claim_delta, 0),
        'hedge_capital': _r(params.hedge_capital, 0),
        'hedge_income': _r(income, 0),
        'stressed_hedge_income': _r(stressed_income, 0),
        'income_delta_under_stress': _r(income_delta, 0),
        'hedge_ratio_pct': _r(100.0 * income / expected, 2) if expected > 0 else None,
        'stress_offset_pct': _r(100.0 * income_delta / claim_delta, 2) if claim_delta > 0 else None,
        'capital_to_annual_claims_multiple': _r(params.hedge_capital / expected, 2) if expected > 0 else None,
        'pv_10y_claims': _r(expected * pv_factor, 0),
        'pv_10y_hedge_income': _r(income * pv_factor, 0),
        'incidence_stress_pct': params.incidence_stress_pct,
        'allocation_preset': params.hedge_allocation,
        'allocation_total_pct': _r(sum(r['allocation_pct'] for r in allocation), 2),
        'weighted_yield_pct': _r(sum(r['allocation_pct'] * r['yield_pct'] for r in allocation) / 100.0, 2),
        'weighted_claim_beta': _r(sum(r['allocation_pct'] * r['claim_beta'] for r in allocation) / 100.0, 3),
    }


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------

def _build_timeline(forecast: List[Dict[str, Any]], spending: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    frames: List[Dict[str, Any]] = []
    for row in spending:
        if row['year'] < HISTORICAL_START - 5:
            continue
        frames.append({
            'year': row['year'], 'phase': 'history', 'era': row['era'],
            'headline': f"US LTC spend ${row['total_ltc_bn']:,.1f}bn — home health {row['home_health_share_pct']:.0f}%",
            'value': row['total_ltc_bn'], 'value_label': 'US nursing + home health, $bn (CMS NHE)',
            'theme': row['era_theme'],
        })
    for row in forecast:
        if row['year'] % 5 != 0 and row['year'] != forecast[-1]['year']:
            continue
        if row['year'] == 2025:
            continue
        frames.append({
            'year': row['year'], 'phase': 'forecast', 'era': row['era'],
            'headline': f"LTC spend {row['ltc_spend_gdp_pct']:.2f}% of GDP — residential index {row['residential_demand_index']:.0f}, home {row['home_demand_index']:.0f}",
            'value': row['ltc_spend_usd_bn'], 'value_label': 'Selected-region LTC spend, $bn nominal (projection)',
            'theme': row['era_note'],
        })
    return frames


def select_research_media(assets: Any, limit: int = 12) -> List[Dict[str, Any]]:
    """Pick media-library assets that relate to long-term care.

    ``assets`` is the server's serialised media list (dicts with ``name``,
    ``type``, ``url``, ``thumbnail``, ``source``). Only same-origin playback
    URLs are returned so the dashboard never embeds a third-party player.
    """
    picked: List[Dict[str, Any]] = []
    if not assets:
        return picked
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        haystack = ' '.join(str(asset.get(k) or '') for k in ('name', 'source', 'title', 'description', 'tags')).lower()
        if not any(word in haystack for word in _MEDIA_KEYWORDS):
            continue
        url = str(asset.get('url') or '')
        if not url.startswith('/'):
            continue
        kind = str(asset.get('type') or '').lower()
        if kind not in ('video', 'image'):
            continue
        picked.append({
            'id': asset.get('id'),
            'title': asset.get('name'),
            'kind': kind,
            'url': url,
            'thumbnail': asset.get('thumbnail') if str(asset.get('thumbnail') or '').startswith('/') else None,
            'source': asset.get('source'),
            'uploaded_at': asset.get('uploaded_at'),
            'checksum': asset.get('checksum'),
        })
        if len(picked) >= limit:
            break
    return picked


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------

def _narrative(params: ResidentialResearchParams, region: Dict[str, Any], forecast: List[Dict[str, Any]],
               tam_rows: List[Dict[str, Any]], hedge: Dict[str, Any]) -> List[str]:
    scenario = _SCENARIOS[params.scenario]
    end = forecast[-1]
    y2050 = next((r for r in forecast if r['year'] == 2050), end)
    tam_total_end = next((r for r in tam_rows if r['year'] == end['year'] and r['segment'] == 'total'), None)
    lines = [
        (f"Long-term care is a {region['ltc_spend_gdp_pct']:.1f}%-of-GDP market in {region['label']} "
         f"(≈${region['gdp_2025_usd_bn'] * region['ltc_spend_gdp_pct'] / 100.0:,.0f}bn in 2025), "
         f"{region['public_share_pct']:.0f}% publicly funded, with {region['residential_recipient_share_pct']:.0f}% of recipients "
         f"in residential settings and {region['beds_per_1000_65plus']:.0f} beds per 1,000 people aged 65+."),
        ("Fifty years of history: public insurance created the nursing-home industry (1965–1980), scandals produced federal quality law "
         "(OBRA 1987), prospective payment and HCBS waivers steered money away from beds (1990s), real-estate capital and private equity "
         "arrived (2000s), home care overtook institutional spend (2010s), and the pandemic plus the Orpea and Australian inquiries "
         "re-regulated staffing and transparency (2020–2025). US nursing care reached $219.9bn and home health $169.4bn in 2024."),
        (f"Private for-profit institutions run 73% of US nursing homes on all-payer margins near zero, cross-subsidised by a 22% Medicare "
         f"post-acute margin; non-profit and public homes staff 0.5–0.7 more nurse hours per resident day; private home care bills "
         f"$80,080 a year for 44 hours a week, close to a $114,975 semi-private bed, while public home-care packages run at a third of that."),
        (f"Outlook under the {scenario['label'].lower()} scenario: recipients index {y2050['recipients_index']:.0f} by 2050 and "
         f"{end['recipients_index']:.0f} by {end['year']} (2025 = 100); the home share moves from "
         f"{forecast[0]['home_share_pct']:.0f}% to {end['home_share_pct']:.0f}%, so residential demand reaches "
         f"{end['residential_demand_index']:.0f} and home demand {end['home_demand_index']:.0f}. Spend rises to "
         f"{end['ltc_spend_gdp_pct']:.2f}% of GDP with care-cost inflation {params.care_cost_inflation_pct:.1f}% against GDP growth "
         f"{params.gdp_growth_pct:.1f}% and healthy ageing {params.healthy_ageing_pct:.1f}% a year."),
    ]
    if tam_total_end:
        lines.append(
            f"TAM / SAM / SOM in {end['year']}: ${tam_total_end['tam_usd_bn']:,.0f}bn total spend, "
            f"${tam_total_end['sam_usd_bn']:,.0f}bn flowing to privately operated providers "
            f"({region['private_provision_share_pct']:.0f}%), and ${tam_total_end['som_usd_bn']:,.1f}bn at a "
            f"{params.som_share_pct:.2f}% obtainable share."
        )
    if hedge.get('hedge_ratio_pct') is not None:
        lines.append(
            f"Hedge: a {params.lives:,}-life 3+ADL book paying ${params.ltc_annual_cover:,.0f} a year expects "
            f"${hedge['expected_annual_claims']:,.0f} of annual claims; ${hedge['hedge_capital']:,.0f} in the "
            f"{params.hedge_allocation.replace('_', ' ')} care-sector allocation yields ${hedge['hedge_income']:,.0f} "
            f"({hedge['hedge_ratio_pct']:.1f}% of claims) and, under a +{params.incidence_stress_pct:.0f}% incidence shock, "
            f"offsets {hedge['stress_offset_pct'] or 0:.1f}% of the extra claims through higher occupancy and hours."
        )
    lines.append(
        "Strategic reading: own operators and property only with low leverage and local density; favour home-care platforms "
        "and high-acuity beds; treat staffing mandates and public fee caps as the dominant threats; use insurer–provider "
        "integration (Japan, Optum, Maccabi) as the template for converting claim cost into owned revenue."
    )
    return lines


def _narrative_he(params: ResidentialResearchParams, region: Dict[str, Any], forecast: List[Dict[str, Any]],
                  hedge: Dict[str, Any]) -> List[str]:
    end = forecast[-1]
    return [
        (f"שוק הסיעוד ב{region['label']} מהווה {region['ltc_spend_gdp_pct']:.1f}% מהתמ\"ג, "
         f"{region['public_share_pct']:.0f}% ממנו במימון ציבורי; {region['residential_recipient_share_pct']:.0f}% מהמקבלים במסגרות מוסדיות."),
        (f"תחזית ל-{end['year']}: מדד מקבלי שירות {end['recipients_index']:.0f} (2025=100), חלק הטיפול הביתי {end['home_share_pct']:.0f}%, "
         f"הוצאה {end['ltc_spend_gdp_pct']:.2f}% מהתמ\"ג."),
        (f"גידור: תיק של {params.lives:,} מבוטחים בטריגר 3+ADL צופה תביעות שנתיות של ${hedge['expected_annual_claims']:,.0f}; "
         f"הכנסות הגידור מכסות {hedge.get('hedge_ratio_pct') or 0:.1f}% מהן."),
    ]


# ---------------------------------------------------------------------------
# Pack
# ---------------------------------------------------------------------------

TABLE_COLUMNS: Dict[str, List[str]] = {
    'spending_history': [
        'year', 'era', 'nursing_care_bn', 'home_health_bn', 'total_ltc_bn', 'home_health_share_pct',
        'cagr_since_prior_row_pct', 'figure_basis', 'source_ids', 'era_theme',
    ],
    'cost_of_care': [
        'year', 'setting', 'setting_label', 'annual_cost_usd', 'monthly_cost_usd', 'relative_to_semi_private',
        'cagr_since_first_survey_pct', 'figure_basis', 'source_ids',
    ],
    'payer_mix': [
        'region', 'segment', 'year', 'public_pct', 'medicare_pct', 'medicaid_pct', 'private_insurance_pct',
        'out_of_pocket_pct', 'other_pct', 'shares_total_pct', 'shares_complete', 'figure_basis', 'source_ids', 'note',
    ],
    'market_structure': [
        'region', 'label', 'ltc_spend_gdp_pct', 'ltc_spend_year', 'ltc_spend_basis', 'public_share_pct',
        'public_share_basis', 'residential_recipient_share_pct', 'home_recipient_share_pct', 'beds_per_1000_65plus',
        'workers_per_100_65plus', 'for_profit_share_pct', 'private_provision_share_pct', 'pop80_share_2025_pct',
        'pop80_share_2050_pct', 'pop80_growth_to_2050_pct', 'ltc_spend_2025_usd_bn', 'figure_basis', 'source_ids', 'note',
    ],
    'setting_comparison': [
        'setting', 'label', 'us_share_of_facilities_pct', 'typical_occupancy_pct', 'median_annual_cost_usd',
        'nurse_hprd_typical', 'rn_hprd_typical', 'medicaid_share_pct', 'deficiencies_per_survey', 'ebitdar_margin_pct',
        'labor_cost_share_pct', 'capital_intensity', 'regulatory_intensity', 'typical_acuity', 'figure_basis', 'source_ids', 'note',
    ],
    'operators': [
        'player', 'country', 'segment', 'ownership', 'revenue_bn', 'currency', 'fiscal_year', 'margin_metric', 'margin_pct',
        'beds_or_units', 'unit_label', 'countries', 'occupancy_pct', 'figure_basis', 'source_ids', 'note',
    ],
    'margin_benchmarks': [
        'segment', 'metric', 'low_pct', 'mid_pct', 'high_pct', 'year', 'figure_basis', 'source_ids', 'note',
    ],
    'workforce': ['region', 'metric', 'value', 'unit', 'year', 'figure_basis', 'source_ids', 'note'],
    'regulation': [
        'jurisdiction', 'code', 'financing_model', 'founding_statute', 'key_reform', 'staffing_standard',
        'quality_regime', 'accommodation_standard', 'direction', 'figure_basis', 'source_ids',
    ],
    'demand_forecast': [
        'year', 'era', 'pop80_share_pct', 'recipients_index', 'home_share_pct', 'residential_share_pct',
        'residential_demand_index', 'home_demand_index', 'ltc_spend_gdp_pct', 'gdp_usd_bn', 'ltc_spend_usd_bn',
        'ltc_spend_at_2025_gdp_usd_bn', 'residential_spend_usd_bn', 'home_spend_usd_bn', 'public_share_pct',
        'private_spend_usd_bn', 'relative_cost_index', 'figure_basis', 'era_note',
    ],
    'tam_sam_som': [
        'year', 'segment', 'tam_usd_bn', 'tam_at_2025_gdp_usd_bn', 'sam_usd_bn', 'som_usd_bn', 'private_provision_share_pct',
        'som_share_of_sam_pct', 'public_share_pct', 'figure_basis',
    ],
    'scenarios': [
        'scenario', 'label', 'selected', 'home_share_target_pct', 'recipients_index_2050', 'residential_demand_index_2050',
        'ltc_spend_gdp_pct_2050', 'ltc_spend_usd_bn_2050', 'recipients_index_end', 'residential_demand_index_end',
        'ltc_spend_gdp_pct_end', 'ltc_spend_usd_bn_end', 'public_share_pct_end', 'end_year', 'note', 'figure_basis',
    ],
    'hedge_book': [
        'age_min', 'age_max', 'attained_age', 'band_lives', 'adl_threshold', 'incidence_per_1000',
        'mean_claim_duration_years', 'steady_state_prevalence_pct', 'expected_annual_claims', 'expected_new_claim_cost',
        'stressed_annual_claims', 'figure_basis', 'source_ids',
    ],
    'hedge_allocation': [
        'asset_class', 'label', 'allocation_pct', 'capital', 'yield_pct', 'claim_beta', 'expected_income',
        'stressed_income', 'income_uplift_under_stress', 'income_to_claims_pct', 'liquidity', 'volatility', 'rationale',
        'figure_basis',
    ],
    'swot': ['quadrant', 'item', 'weight', 'applies_to', 'source_ids', 'figure_basis'],
    'case_studies': ['id', 'title', 'jurisdiction', 'period', 'segment', 'what_happened', 'lesson', 'metric', 'source_ids', 'figure_basis'],
    'eras': ['start', 'end', 'era', 'kind', 'description', 'theme', 'figure_basis'],
}


def list_research_tables() -> List[str]:
    return list(TABLE_COLUMNS.keys())


def _collect_source_ids(tables: Dict[str, List[Dict[str, Any]]]) -> List[str]:
    found = set()
    for rows in tables.values():
        for row in rows:
            for sid in row.get('source_ids') or []:
                found.add(sid)
    return sorted(found)


def build_ltc_residential_research(
    raw: Optional[Dict[str, Any]] = None,
    media_assets: Any = None,
) -> Dict[str, Any]:
    """Build the full research pack. ``media_assets`` is the server's serialised media library (optional)."""
    params = parse_residential_params(raw)
    region = _REGIONS[params.region]
    scenario = _SCENARIOS[params.scenario]

    spending = _build_spending_history()
    cost_of_care = _build_cost_of_care()
    payer_mix = _build_payer_mix()
    market_structure = _build_market_structure()
    forecast = _build_demand_forecast(params)
    tam_rows = _build_tam_som(params, forecast)
    scenarios = _build_scenarios(params)
    hedge_book = _build_hedge_book(params)
    expected_claims = sum(r['expected_annual_claims'] for r in hedge_book)
    hedge_allocation = _build_hedge_allocation(params, expected_claims)
    hedge = _hedge_summary(params, hedge_book, hedge_allocation)

    tables_block: Dict[str, List[Dict[str, Any]]] = {
        'spending_history': spending,
        'cost_of_care': cost_of_care,
        'payer_mix': payer_mix,
        'market_structure': market_structure,
        'setting_comparison': [dict(r) for r in _SETTING_COMPARISON_ROWS],
        'operators': [dict(r) for r in _OPERATOR_ROWS],
        'margin_benchmarks': [dict(r) for r in _MARGIN_BENCHMARK_ROWS],
        'workforce': [dict(r) for r in _WORKFORCE_ROWS],
        'regulation': [dict(r) for r in _REGULATION_ROWS],
        'demand_forecast': forecast,
        'tam_sam_som': tam_rows,
        'scenarios': scenarios,
        'hedge_book': hedge_book,
        'hedge_allocation': hedge_allocation,
        # SWOT items are analyst judgements anchored to the cited sources;
        # case studies restate published events.
        'swot': [dict(r, figure_basis=BASIS_ESTIMATE) for r in _SWOT_ROWS],
        'case_studies': [dict(r, figure_basis=BASIS_PUBLISHED) for r in _CASE_STUDY_ROWS],
        'eras': _build_eras(),
    }

    used_sources = _collect_source_ids(tables_block)
    unresolved = [sid for sid in used_sources if sid not in _SOURCE_IDS]
    us_2024 = next((r for r in spending if r['year'] == 2024), None)
    params_dict = asdict(params)
    integrity = {
        'study_id': STUDY_ID,
        'params_hash': _integrity_hash(params_dict),
        'tables_hash': _integrity_hash(tables_block),
        'row_counts': {name: len(rows) for name, rows in tables_block.items()},
        'tam_sam_som_monotone': all(
            r['tam_usd_bn'] + 1e-9 >= r['sam_usd_bn'] >= r['som_usd_bn'] >= 0 for r in tam_rows
        ),
        'tam_segments_reconcile': all(
            abs(sum(r['tam_usd_bn'] for r in tam_rows if r['year'] == y and r['segment'] in ('residential', 'home_care'))
                - next(r['tam_usd_bn'] for r in tam_rows if r['year'] == y and r['segment'] == 'total')) < 0.05
            for y in sorted({r['year'] for r in tam_rows})
        ) if tam_rows else True,
        'payer_shares_sum_to_100': all(
            abs(r['shares_total_pct'] - 100.0) <= 0.5 for r in payer_mix if r['shares_complete']
        ),
        'setting_mix_sums_to_100': all(
            abs(r['home_share_pct'] + r['residential_share_pct'] - 100.0) < 0.05 for r in forecast
        ),
        'forecast_spend_segments_reconcile': all(
            abs(r['residential_spend_usd_bn'] + r['home_spend_usd_bn'] - r['ltc_spend_usd_bn']) < 0.011 for r in forecast
        ),
        'hedge_allocation_sums_to_100': abs(hedge['allocation_total_pct'] - 100.0) < 0.01,
        'hedge_book_lives_match': sum(r['band_lives'] for r in hedge_book) == params.lives if hedge_book else True,
        'spending_history_totals_match': all(
            abs(r['nursing_care_bn'] + r['home_health_bn'] - r['total_ltc_bn']) < 0.05 for r in spending
        ),
        'source_ids_resolve': not unresolved,
        'unresolved_source_ids': unresolved,
        'sources_used': used_sources,
        'forecast_years': len(forecast),
        'figure_basis_values': sorted({
            str(row.get('figure_basis')) for rows in tables_block.values() for row in rows if row.get('figure_basis')
        }),
    }
    integrity['all_checks_pass'] = all(
        integrity[key] for key in (
            'tam_sam_som_monotone', 'tam_segments_reconcile', 'payer_shares_sum_to_100', 'setting_mix_sums_to_100',
            'forecast_spend_segments_reconcile', 'hedge_allocation_sums_to_100', 'hedge_book_lives_match',
            'spending_history_totals_match', 'source_ids_resolve',
        )
    )

    end = forecast[-1]
    tam_end_total = next((r for r in tam_rows if r['year'] == end['year'] and r['segment'] == 'total'), None)
    tam_2025_total = next((r for r in tam_rows if r['year'] == 2025 and r['segment'] == 'total'), None)
    kpis = {
        'region_ltc_spend_gdp_pct': region['ltc_spend_gdp_pct'],
        'region_public_share_pct': region['public_share_pct'],
        'region_residential_share_pct': region['residential_recipient_share_pct'],
        'us_ltc_spend_2024_bn': us_2024['total_ltc_bn'] if us_2024 else None,
        'us_nursing_home_residents_2025': 1_241_727,
        'us_nursing_home_occupancy_2025_pct': 79.0,
        'oecd_ltc_spend_gdp_pct': 1.8,
        'tam_2025_usd_bn': tam_2025_total['tam_usd_bn'] if tam_2025_total else None,
        'tam_end_usd_bn': tam_end_total['tam_usd_bn'] if tam_end_total else None,
        'sam_end_usd_bn': tam_end_total['sam_usd_bn'] if tam_end_total else None,
        'som_end_usd_bn': tam_end_total['som_usd_bn'] if tam_end_total else None,
        'end_year': end['year'],
        'ltc_spend_gdp_pct_end': end['ltc_spend_gdp_pct'],
        'residential_demand_index_end': end['residential_demand_index'],
        'home_demand_index_end': end['home_demand_index'],
        'expected_annual_claims': hedge['expected_annual_claims'],
        'hedge_ratio_pct': hedge['hedge_ratio_pct'],
        'stress_offset_pct': hedge['stress_offset_pct'],
    }

    pack = {
        'success': True,
        'study_id': STUDY_ID,
        'title': STUDY_TITLE,
        'title_he': STUDY_TITLE_HE,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'params': params_dict,
        'region_label': region['label'],
        'region_note': region['note'],
        'scenario_label': scenario['label'],
        'scenario_note': scenario['note'],
        'home_share_target_pct': _r(_home_share_target(params, region, scenario), 1),
        'narrative': _narrative(params, region, forecast, tam_rows, hedge),
        'narrative_he': _narrative_he(params, region, forecast, hedge),
        'sources': [dict(item) for item in RESEARCH_SOURCES],
        'controls': {
            'regions': [{'id': key, 'label': val['label']} for key, val in _REGIONS.items()],
            'scenarios': [{'id': key, 'label': val['label'], 'note': val['note']} for key, val in _SCENARIOS.items()],
            'hedge_allocations': [
                {'id': key, 'label': key.replace('_', ' ').title(), 'weights': dict(val)} for key, val in _HEDGE_PRESETS.items()
            ],
            'adl_thresholds': [2, 3, 4, 5, 6],
            'forecast_min': 2030,
            'forecast_max': FORECAST_MAX,
            'history_start': HISTORICAL_START,
            'history_end': HISTORICAL_END,
        },
        'kpis': kpis,
        'hedge_summary': hedge,
        'tables': tables_block,
        'media': {
            'illustrations': [dict(item) for item in _ILLUSTRATIONS],
            'timeline_player': _build_timeline(forecast, spending),
            'library': select_research_media(media_assets),
            'external_publications': [dict(item) for item in _EXTERNAL_PUBLICATIONS],
            'note': (
                'Illustrations are PHINS-branded vector graphics served from this origin. The timeline player renders '
                'the pack data in the browser and can be recorded as a video file. Library items are same-origin media '
                'assets whose name or source matches long-term care keywords. External publications open in a new tab; '
                'nothing third-party is embedded.'
            ),
        },
        'integrity': integrity,
    }
    pack['integrity']['pack_hash'] = _integrity_hash({
        'params': params_dict,
        'kpis': kpis,
        'tables_hash': integrity['tables_hash'],
    })
    return pack


# ---------------------------------------------------------------------------
# Table extraction / downloads
# ---------------------------------------------------------------------------

def extract_research_table(pack: Dict[str, Any], table_name: str) -> List[Dict[str, Any]]:
    name = (table_name or '').strip()
    rows = (pack.get('tables') or {}).get(name)
    if rows is None:
        raise KeyError(f'Unknown research table: {table_name}')
    return list(rows)


def _csv_cell(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return '|'.join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return value


def research_table_csv(pack: Dict[str, Any], table_name: str) -> Tuple[str, bytes]:
    rows = extract_research_table(pack, table_name)
    columns = TABLE_COLUMNS.get(table_name) or (
        sorted({k for r in rows for k in r.keys()}) if rows else ['value']
    )
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        writer.writerow({k: _csv_cell(row.get(k)) for k in columns})
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


__all__ = [
    'STUDY_ID', 'STUDY_TITLE', 'STUDY_TITLE_HE', 'RESEARCH_SOURCES', 'TABLE_COLUMNS',
    'ResidentialResearchParams', 'parse_residential_params', 'build_ltc_residential_research',
    'list_research_tables', 'extract_research_table', 'research_table_csv', 'research_table_json',
    'select_research_media',
]
