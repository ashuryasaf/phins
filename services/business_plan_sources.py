"""Data sources and figure lineage for the unified business plan (Appendix I).

Two registers, both read-only:

* :data:`LINEAGE` — every class of figure the plan presents, where it comes
  from, and whether it is an **input to the model** or a **reference only**.
  Market research never feeds the model: the plan plans lives from the kernel
  premium and the persistency identity, so an external statistic cannot move
  a planning figure (and a planning figure never rewrites a statistic).
* :data:`RESEARCH_SOURCES` / :data:`MARKET_SOURCES` — the external research
  registry behind the market section, by market. It is the same registry the
  pitch-dashboard Scenario Lab cites (``sourceRegistry`` in
  ``web_portal/static/pitch-dashboard.html``); ``tests/test_business_plan.py``
  keeps the two in sync so the appendix can never cite a source the Scenario
  Lab does not, or vice versa.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

# Figure class, source, source kind, feeds the model?, note.
LINEAGE: List[Dict[str, Any]] = [
    {"figure": "Kernel premium (ILS 4,518) and the specimen decomposition",
     "source": "`services/pricing_kernel.py` with the published `risk_reference_v1` tables (life 0.25 / disability 0.20 per ILS 1,000 monthly, locked age curve)",
     "kind": "Platform — published table", "feeds_model": True,
     "note": "Integrity identity `kernel_specimen_is_4518` fails the render if the kernel quote moves."},
    {"figure": "Anchor-book path: new issues 25k / 75k / 150k, persistency 92% / 96%, 25% take, opex intensity by year",
     "source": "`services/aspire_scale_identity.py` — the Investor Meeting book restated on every Israel pitch surface",
     "kind": "Planning identity (reviewed)", "feeds_model": True,
     "note": "Identity `anchor_book_reconciles_to_investor_meeting` compares every year, including the five-year extension."},
    {"figure": "Seed ILS 6M on ILS 24M pre-money",
     "source": "`ROUND_SEED_ILS` / `ROUND_PRE_MONEY_ILS` in `services/business_plan_model.py` — the one writer, imported by the portal",
     "kind": "Round terms", "feeds_model": True,
     "note": "Dilution, post-money and use of funds are derived from these two numbers."},
    {"figure": "Actuarial appraisal (WACC, exit multiple on 2029 net revenue, prudence) and its sensitivity grid",
     "source": "Same formula as `GET /api/investor/valuation-sim` (`_inv_appraisal_pre_money`) over the anchor years 2027–2029",
     "kind": "Planning assumption", "feeds_model": True,
     "note": "Identity `appraisal_formula_matches_valuation_sim`; the grid is the formula evaluated at ±5 / ±10 pt WACC and ±1× exit."},
    {"figure": "Planning FX pins and per-market specimen quotes (local currency)",
     "source": "`MARKET_SPECS` in `services/aspire_scale_identity.py` — pinned planning rates, never live FX",
     "kind": "Planning pin", "feeds_model": True,
     "note": "Used only to show the same ILS specimen in local currency; no market-size inference."},
    {"figure": "Insurer / reinsurer economics: expected claims 62%, cession 18%, ceding commission 25%, carrier own expenses 5%",
     "source": "Factor register defaults (`insurer` group) — to be replaced by the carrier's and the reinsurer's term sheets",
     "kind": "Planning assumption", "feeds_model": True,
     "note": "Appendix B and the carrier waterfall restate on every change; identity `ceded_plus_retained_equals_gwp`."},
    {"figure": "OECD partnership expansion: launch counts by year, 50% ramp scale, 60% platform share, 35% opex intensity",
     "source": "Factor register defaults (`expansion` group)",
     "kind": "Planning assumption", "feeds_model": True,
     "note": "Zero launches collapse the group to the anchor book exactly (identity `group_equals_anchor_plus_partners`)."},
    {"figure": "Technology census: service modules, packages, API modules, repositories, security modules, test files",
     "source": "Repository census at render time (`technology_census`) and `GET /api/platform/facts` in the browser",
     "kind": "Platform fact (live)", "feeds_model": False,
     "note": "Displayed, never typed; rebuilding the plan after a code change refreshes it."},
    {"figure": "Regulatory and commercial gates: pre-ruling 12 Oct 2026, seed close Q4 2026, sales clock 1 Jan 2027, Gates 6–7",
     "source": "Internal meeting records (`investor-docs/regulatory-preruling-avi-ovadia-brief.md`, `investor-docs/regulatory-meeting-27jul-brief.md`) and the Investor Meeting pack",
     "kind": "Internal record", "feeds_model": False,
     "note": "Dates drive the roadmap chart only; the in-force path is independent of them."},
    {"figure": "Actuarial validation: IAA-recognised executive actuary cleared the pricing model on 26 May 2026",
     "source": "Investor Meeting record and partner business plans (`internal/phins-ai-tech-partner-business-plan.html`)",
     "kind": "Internal record", "feeds_model": False,
     "note": "Narrative only; appointed-actuary sign-off remains an open gate."},
    {"figure": "Market context: demographics, long-term-care spend, disability prevalence, insurance market sizes by market",
     "source": "External research registry below — the Scenario Lab's `sourceRegistry` on the pitch dashboard",
     "kind": "External research (reference only)", "feeds_model": False,
     "note": "The plan plans lives, not TAM; no statistic here moves a planning figure and no planning figure rewrites a statistic."},
]

# Plan market id → research registry keys (same keys the Scenario Lab uses).
MARKET_SOURCES: Dict[str, List[str]] = {
    "israel": ["israel_nii_2024", "taub_2024", "israel_cbs_2024", "oecd_2025"],
    "portugal": ["asf_portugal_2024", "bde_portugal_2024", "oecd_portugal_ltc_2024", "ine_portugal_2024"],
    "wneurope": ["destatis_2024", "bundesrat_2025", "oecd_2025"],
    "sweden": ["socialstyrelsen_elderly_2024", "socialstyrelsen_elderly_cost", "svensk_forsakring_2024", "svensk_forsakring_vard_2024", "oecd_2025"],
    "canada": ["statcan_2024", "clhia_2024", "clhia_benefits_2024", "clhia_ltc_guide"],
    "usa": ["ssa_2024", "milliman_ltci_2024", "genre_idi_2024", "limra_2024"],
    "australia": ["aihw_2024", "apra_2024", "apra_dii"],
    "japan": ["japan_mhlw_2024", "japan_ltc_english"],
    "bulgaria": ["nsi_bulgaria_2025", "fsc_bulgaria_2025", "xprimm_bulgaria_fy2025", "nssi_bulgaria_2025", "economic_bg_bulgaria_2025", "oecd_2025"],
    "middleeast": ["cbuae_2024", "cbuae_h1_2024"],
}

# Verbatim copy of the Scenario Lab registry (title, url, note, type, strength).
RESEARCH_SOURCES: Dict[str, Dict[str, str]] = {
    "oecd_2025": {
        "title": 'OECD Health at a Glance 2025',
        "url": 'https://www.oecd.org/en/publications/health-at-a-glance-2025_8f9e3f98-en.html',
        "note": 'Used for OECD long-term care comparisons, including average LTC spending, home-care orientation, and cross-country care-system benchmarks.',
        "type": 'official',
        "strength": 'benchmark',
    },
    "israel_nii_2024": {
        "title": 'Israel National Insurance Institute — Long-term care annual report chapter',
        "url": 'http://www.btl.gov.il/Publications/Skira_shnatit/2024/Documents/chap-3-04-siud.pdf',
        "note": 'Direct official PDF chapter for Israel long-term care program context and public-benefit framing.',
        "type": 'official',
        "strength": 'direct pdf',
    },
    "taub_2024": {
        "title": 'Taub Center — Long Term Care in Israel (2024)',
        "url": 'https://www.taubcenter.org.il/en/research/ltc/',
        "note": 'Used for Israel private LTC insured lives, public LTC beneficiary counts, and annual public LTC spend references.',
        "type": 'analysis',
        "strength": 'synthesis',
    },
    "israel_cbs_2024": {
        "title": 'Israel CBS Social Survey 2023 release (2024)',
        "url": 'https://www.cbs.gov.il/he/mediarelease/DocLib/2024/377/19_24_377b.pdf',
        "note": 'Used for Israel severe functional disability prevalence among adults.',
        "type": 'official',
        "strength": 'direct pdf',
    },
    "ssa_2024": {
        "title": 'U.S. SSA Disability Statistical Reports 2024',
        "url": 'https://www.ssa.gov/policy/docs/statcomps/di_asr/2024/di_asr24.pdf',
        "note": 'Direct official SSA PDF used for U.S. disability beneficiary counts and disabled-worker benefit statistics.',
        "type": 'official',
        "strength": 'direct pdf',
    },
    "milliman_ltci_2024": {
        "title": 'Milliman — LTCI industry through 2024',
        "url": 'https://www.milliman.com/en/insight/ltci-2024-statistics-experience-reporting-forms',
        "note": 'Used for U.S. stand-alone LTC insured lives and incurred-claims anchor.',
        "type": 'analysis',
        "strength": 'industry analysis',
    },
    "genre_idi_2024": {
        "title": 'Gen Re — 2024 U.S. Individual Disability Market Survey',
        "url": 'https://www.genre.com/us/knowledge/publications/2025/may/surveylhidisum25-en',
        "note": 'Used for U.S. IDI new sales premium and in-force premium reference points.',
        "type": 'industry',
        "strength": 'market survey',
    },
    "limra_2024": {
        "title": 'LIMRA — Workplace disability sales release (Q3 2024)',
        "url": 'https://www.limra.com/en/newsroom/news-releases/2024/limra-workplace-life-insurance-and-supplemental-health-product-sales-continue-to-rise-in-third-quarter-2024/',
        "note": 'Used for U.S. workplace disability new premium signal.',
        "type": 'industry',
        "strength": 'market release',
    },
    "statcan_2024": {
        "title": 'Statistics Canada — Disability profile (released 2024)',
        "url": 'https://www150.statcan.gc.ca/n1/pub/89-654-x/89-654-x2024001-eng.htm',
        "note": 'Used for Canadian disability prevalence among people aged 15+.',
        "type": 'official',
        "strength": 'official release',
    },
    "clhia_2024": {
        "title": 'CLHIA — Canadian Life and Health Insurance Facts 2024',
        "url": 'https://www.clhia.ca/web/CLHIA_LP4W_LND_Webstation.nsf/resources/Factbook2024/$file/CLHIA-2024Facts.pdf',
        "note": 'Direct industry PDF used for Canada premium mix, insured population, and health-insurance scale.',
        "type": 'industry',
        "strength": 'direct pdf',
    },
    "clhia_benefits_2024": {
        "title": 'CLHIA — 2024 benefits release',
        "url": 'https://www.clhia.ca/web/CLHIA_LP4W_LND_Webstation.nsf/page/4554DF09386ECB0985258D080051020B!OpenDocument',
        "note": 'Used for 2024 disability benefits paid and aggregate claims flow.',
        "type": 'industry',
        "strength": 'news release',
    },
    "clhia_ltc_guide": {
        "title": 'CLHIA Consumer Guide — Long-Term Care Insurance',
        "url": 'https://www.clhia.ca/web/CLHIA_LP4W_LND_Webstation.nsf/resources/Consumer+Brochures/$file/Brochure_Guide_Long_Term_Care_ENG.pdf',
        "note": 'Used for the common 2-of-6 ADL consumer trigger reference point.',
        "type": 'industry',
        "strength": 'consumer guide',
    },
    "aihw_2024": {
        "title": 'AIHW — People with disability in Australia (updated 2024)',
        "url": 'https://www.aihw.gov.au/reports/disability/people-with-disability-in-australia/contents/summary',
        "note": 'Used for Australia disability prevalence and severe/profound disability statistics.',
        "type": 'official',
        "strength": 'official summary',
    },
    "apra_2024": {
        "title": 'APRA — Private health insurance membership summary (Dec 2024)',
        "url": 'https://www.apra.gov.au/quarterly-private-health-insurance-membership-and-benefits-summary-december-2024',
        "note": 'Used for Australia insured-pool scale and current membership benchmark.',
        "type": 'official',
        "strength": 'official release',
    },
    "apra_dii": {
        "title": 'APRA — Thematic review of individual disability income insurance',
        "url": 'https://handbook.apra.gov.au/letter/372/letter-life-insurers-thematic-review-individual-disability-income-insurance',
        "note": 'Used to frame Australian pricing discipline and sustainability risk in DII.',
        "type": 'official',
        "strength": 'regulatory letter',
    },
    "japan_mhlw_2024": {
        "title": 'MHLW Japan — Long-term care insurance and FY2024-26 premium release',
        "url": 'https://www.mhlw.go.jp/content/12303500/001253798.pdf',
        "note": 'Direct official PDF used for Japan average monthly LTC premium and service planning references.',
        "type": 'official',
        "strength": 'direct pdf',
    },
    "japan_ltc_english": {
        "title": 'MHLW Japan — Long-term Care Insurance in Japan',
        "url": 'https://www.mhlw.go.jp/english/topics/elderly/care/2.html',
        "note": 'Used for Japan LTC system eligibility and service-user scale.',
        "type": 'official',
        "strength": 'official summary',
    },
    "destatis_2024": {
        "title": 'Destatis — 5.7 million people needing long-term care (end-2023)',
        "url": 'https://www.destatis.de/DE/Presse/Pressemitteilungen/2024/12/PD24_478_224.html',
        "note": 'Used for Germany long-term care scale and home-vs-institution split.',
        "type": 'official',
        "strength": 'official release',
    },
    "bundesrat_2025": {
        "title": 'Bundesrat / Germany — Pflegebeitrag 2025',
        "url": 'https://www.bundesrat.de/DE/plenum/bundesrat-kompakt/24/1050/31.html?nn=5492626&view=main%5BDrucken%5D',
        "note": 'Used for German social LTC contribution-rate change reference.',
        "type": 'official',
        "strength": 'official release',
    },
    "cbuae_2024": {
        "title": 'CBUAE — Annual Statistical Report for the Insurance Sector 2024',
        "url": 'https://www.centralbank.ae/media/jubnwh13/annual-statistical-report-for-the-insurance-sector-2024-en.pdf',
        "note": 'Used for UAE health-insurance turnover and sector mix.',
        "type": 'official',
        "strength": 'direct pdf',
    },
    "cbuae_h1_2024": {
        "title": 'CBUAE — June 2024 Quarterly Economic Review',
        "url": 'https://www.centralbank.ae/media/yxlb5sot/qer_june_2024.pdf',
        "note": 'Used for UAE retention ratio and implied cession benchmark.',
        "type": 'official',
        "strength": 'direct pdf',
    },
    "socialstyrelsen_elderly_2024": {
        "title": 'Socialstyrelsen — Statistics on Care and Services for the Elderly 2024',
        "url": 'https://www.socialstyrelsen.se/publikationer/statistics-on-care-and-services-for-the-elderly-2024-2025-4-9537/',
        "note": "Used for Sweden's official 31 October 2024 counts of people aged 65+ with municipal social-service decisions, home care, and special housing.",
        "type": 'official',
        "strength": 'official release',
    },
    "socialstyrelsen_elderly_cost": {
        "title": 'Socialstyrelsen — Elderly receive care later (lägesrapport press note)',
        "url": 'https://www.socialstyrelsen.se/om-socialstyrelsen/pressrum/press/aldre-far-omsorg-allt-senare/',
        "note": 'Used for Sweden municipal elderly-care cost (SEK 166 billion in 2024; 2.6% of GDP) as a public-funding pressure marker.',
        "type": 'official',
        "strength": 'official release',
    },
    "svensk_forsakring_2024": {
        "title": 'Svensk Försäkring — Premiums, claims, and market shares (2024)',
        "url": 'https://www.svenskforsakring.se/om-forsakring/forsakringar-i-sverige/utbetalningar-premier-och-marknadsandelar/',
        "note": "Used for Sweden's 2024 total insurance premiums and the life/pension versus non-life split.",
        "type": 'industry',
        "strength": 'industry release',
    },
    "svensk_forsakring_vard_2024": {
        "title": 'Svensk Försäkring — Private health insurance (vårdförsäkring) 2024',
        "url": 'https://www.svenskforsakring.se/om-forsakring/forsakringar-i-sverige/skadeforsakring/allt-fler-har-en-vardforsakring/',
        "note": 'Used for year-end 2024 private health-insurance lives and premium volume as a private overlay anchor, not as a PHINS product price.',
        "type": 'industry',
        "strength": 'industry release',
    },
    "asf_portugal_2024": {
        "title": 'ASF Portugal — Insurance and Pension Funds Supervisory Report 2024',
        "url": 'https://www.asf.com.pt/en/entities/insurance/statistics',
        "note": 'Used for Portugal insurance market size, life and non-life premium split, penetration rate, and regulatory structure under Solvency II framework.',
        "type": 'official',
        "strength": 'official report',
    },
    "bde_portugal_2024": {
        "title": 'Banco de Portugal — Financial Stability Report 2024',
        "url": 'https://www.bportugal.pt/en/publications/banco-de-portugal/all/381',
        "note": 'Used for Portuguese financial sector structure, macroeconomic context, household insurance holdings, and long-term care financing outlook.',
        "type": 'official',
        "strength": 'official report',
    },
    "oecd_portugal_ltc_2024": {
        "title": 'OECD — Long-term Care Resources and Utilisation: Portugal',
        "url": 'https://www.oecd.org/en/data/indicators/long-term-care-resources-and-utilisation.html',
        "note": 'Used for Portuguese LTC bed capacity, home-care orientation, and public expenditure benchmarking against OECD averages.',
        "type": 'official',
        "strength": 'benchmark',
    },
    "ine_portugal_2024": {
        "title": 'INE Portugal — Demographic and Social Statistics 2024',
        "url": 'https://www.ine.pt/xportal/xmain?xpgid=ine_main&xpid=INE',
        "note": 'Used for Portuguese population aging profile, disability prevalence estimates, and demographic dependency ratio.',
        "type": 'official',
        "strength": 'official release',
    },
    "nsi_bulgaria_2025": {
        "title": 'NSI Bulgaria — Population and Demographic processes 2025 (final)',
        "url": 'https://www.nsi.bg/en/press-release/population-and-demographic-processes-9002',
        "note": "Used for Bulgaria's 31 December 2025 population (6,423,207), share aged 65+ (1,557,851 / 24.3%), working-age stock (3,764,842), mean age 45.4, and the 61.6% age-dependency ratio.",
        "type": 'official',
        "strength": 'official release',
    },
    "fsc_bulgaria_2025": {
        "title": 'FSC Bulgaria — Insurance statistics (2025 non-life files and hub)',
        "url": 'https://www.fsc.bg/en/insurance-activity/statistics/',
        "note": 'Official supervisory statistics hub. FY2025 market totals used in the evidence table are the FSC figures as published through this series and relayed by XPRIMM.',
        "type": 'official',
        "strength": 'official release',
    },
    "xprimm_bulgaria_fy2025": {
        "title": 'XPRIMM — Bulgaria FY2025 GWP (citing FSC)',
        "url": 'https://www.xprimm.com/life/involvement/STATISTICS--BULGARIA-FY2025-Motor-insurance-remained-the-market-driver-both-in-GWP-and-paid-claims-terms-articol-15-24665.htm',
        "note": "Used for the FY2025 FSC totals: BGN 5.25 billion GWP, life BGN 870 million, non-life BGN 4.38 billion, property BGN 542.13 million, and DZI Life's 29.44% life share.",
        "type": 'industry',
        "strength": 'market release',
    },
    "nssi_bulgaria_2025": {
        "title": 'NSSI — October 2025 social-security budget execution',
        "url": 'https://noi.bg/news-budget-october-05122025/',
        "note": 'Used for the public-funded lapse layer: 2,061,409 pensioners in October 2025, average pension BGN 1,006.92, and BGN 19,859.2 million pension outlays for January–October 2025.',
        "type": 'official',
        "strength": 'official release',
    },
    "economic_bg_bulgaria_2025": {
        "title": "Economic.bg RATE — Largest players in Bulgaria's insurance market in 2025",
        "url": 'https://www.economic.bg/en/a/view/rate-the-largest-players-in-bulgaria-s-insurance-market-in-2025',
        "note": 'Used for the 2025 non-life ranking (Euroins, Bulstrad VIG, DZI, Lev Ins, Armeec, Generali, OZK, Allianz, Bul Ins, Groupama) and ABZ comments on motor concentration and missing income-protection depth. Not a substitute for FSC line-level files.',
        "type": 'industry',
        "strength": 'industry analysis',
    },
}


def sources_for_market(market_id: str) -> List[Dict[str, str]]:
    """Registry entries for a plan market, in the Scenario Lab's order."""
    return [{"key": k, **RESEARCH_SOURCES[k]} for k in MARKET_SOURCES.get(market_id, []) if k in RESEARCH_SOURCES]


def research_rows(markets: Sequence[Mapping[str, Any]]) -> List[Dict[str, str]]:
    """One row per (market, source) for the appendix, following the plan's market order."""
    rows: List[Dict[str, str]] = []
    for m in markets:
        for s in sources_for_market(m["id"]):
            rows.append({"market": m["name"], **s})
    return rows


__all__ = ["LINEAGE", "MARKET_SOURCES", "RESEARCH_SOURCES", "research_rows", "sources_for_market"]
