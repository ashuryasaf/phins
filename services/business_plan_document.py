"""Unified business plan document — narrative, deck and appendices.

One narrative, two renderers. ``render_markdown`` writes the portable plan
(``investor-docs/phins-unified-business-plan.md`` → branded PDF) and
``render_html`` writes ``/business-plan.html`` with the PHINS letterhead
(navy / gold gradient, shield emblem, Inter + Space Grotesk), a factor panel
and ``data-bp`` bindings so the page re-renders from
``GET /api/business-plan/model`` when a factor changes. Every figure in the
text is a ``{key}`` placeholder resolved from :func:`compute_plan` through
:data:`FIGURES`; the Python formatter here and the browser formatter in the
page follow the same rules, so the no-JS / print fallback equals the live
render at default factors. Nothing in this module reads or writes platform
data — it renders the planning identity only.
"""

from __future__ import annotations

import html as _html
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from services.business_plan_charts import (
    chart_by_id,
    chart_specs,
    chart_table,
    directive as chart_directive,
    render_svg,
)
from services.business_plan_model import (
    FACTORS,
    FACTOR_GROUPS,
    PLAN_VERSION,
    YEARS,
    compute_plan,
)
from services.business_plan_sources import LINEAGE, research_rows

BRAND_TAGLINE = "Personal Health Insurance & Savings · AI-Operated Insurance Platform"
DOCUMENT_TITLE = "PHINS — Unified Business Plan, Investor Deck & Appendices"
DOCUMENT_EDITION = "October 2026 · one standard · adjustable factors"
CONTACT = "asaf@phins.ai · phins.ai"

# Processed founder portrait (media-library placement ``founder_portrait_id``;
# see services/business_plan_portrait.py). The PDF edition embeds the same
# route's output when the generator can reach it; otherwise the monogram.
FOUNDER_PORTRAIT_URL = "/api/business-plan/founder-portrait"

# Founder credentials — facts already stated on the investor surfaces
# (Investor Meeting pack, partner business plans, Aspire-Invest plan).
FOUNDER: Dict[str, Any] = {
    "name": "Asaf Ashury, Adv.",
    "role": "Founder & CEO · PHINS Technologies",
    "monogram": "AA",
    "summary": (
        "Insurance broker and lawyer who designed the PHINS contract family and built the operating platform "
        "end-to-end. The first conversations that matter — supervisor, appointed actuary, carrier of record, "
        "reinsurer, distribution house — require one person who can hold insurance law, actuarial form and "
        "production software at the same time; that is the founder's role in every market PHINS enters."
    ),
    "credentials": [
        ("Licensed insurance broker", "Life, disability and long-term-care distribution practice in Israel; the anchor contract's 1:4 / 1:1 disability mechanism and the ADL-3 trigger are his product design."),
        ("Advocate (Adv.)", "Israeli Bar; drafted the regulatory application memorandum in actuarial form (Draft 3.1, EN + HE) and opened the pre-ruling track with the Capital Market, Insurance and Savings Authority (12 October 2026)."),
        ("Platform author", "Built the production platform at www.phins.ai — {modules} service modules, {api_modules} API modules, {repositories} repositories, {security_modules} security modules, {test_files} test files at this render — including the pricing kernel, the hash-chained ledger and the AI agents that recommend while humans decide."),
        ("Actuarial validation", "An IAA-recognised executive actuary (IL / CA / US) reviewed the pricing model and the actuarial service layer on 26 May 2026 and is engaged on the Chief-Actuary path; appointed-actuary sign-off remains an open gate."),
        ("Capital-markets and partner relations", "Leads the carrier, reinsurance, distribution-house and OECD partner conversations; author of the Investor Meeting book this plan reconciles to."),
    ],
    "principles": [
        "AI recommends, the ledger posts, people supervise.",
        "One factor register behind every investor figure; integrity identities on every render.",
        "Technology, not balance sheet: carried by licensed insurers, reinsured by quota share, distributed with local partners.",
    ],
}

# ---------------------------------------------------------------------------
# Figures: placeholder key → (plan path, format)
# ---------------------------------------------------------------------------
FIGURES: Dict[str, Tuple[str, str]] = {
    "premium": ("inputs.annual_premium", "ils"),
    "take": ("inputs.phins_take", "pct"),
    "carrier_share_pct": ("derived.carrier_share_pct", "pct"),
    "churn": ("anchor_book.churn", "pct"),
    "savings_election": ("inputs.savings_election", "pct"),
    "savings_addon": ("inputs.savings_addon", "x"),
    "specimen_monthly": ("specimen.total_monthly", "ils2"),
    "specimen_life_monthly": ("specimen.life_monthly", "ils2"),
    "specimen_dis_monthly": ("specimen.disability_monthly", "ils2"),
    "specimen_age_factor": ("specimen.age_factor", "num3"),
    "seed": ("funding.seed", "ilsm"),
    "pre": ("funding.pre_money", "ilsm0"),
    "post": ("funding.post_money", "ilsm0"),
    "dilution": ("funding.seed_dilution", "pct"),
    "burn_2027": ("funding.burn_2027", "ilsm"),
    "peak_need": ("funding.peak_cumulative_need", "ilsm"),
    "series_a": ("funding.series_a_indicative", "ilsm"),
    "series_a_buffer": ("funding.series_a_buffer", "pct"),
    "first_positive": ("funding.first_ebitda_positive_year", "year"),
    "cum_positive": ("funding.cumulative_positive_year", "year"),
    "uof_tech": ("funding.use_of_funds.product_technology.amount", "ilsm"),
    "uof_tech_pct": ("funding.use_of_funds.product_technology.share", "pct"),
    "uof_reg": ("funding.use_of_funds.regulatory_actuarial.amount", "ilsm"),
    "uof_reg_pct": ("funding.use_of_funds.regulatory_actuarial.share", "pct"),
    "uof_dist": ("funding.use_of_funds.distribution_partnerships.amount", "ilsm"),
    "uof_dist_pct": ("funding.use_of_funds.distribution_partnerships.share", "pct"),
    "uof_ops": ("funding.use_of_funds.operations_reserve.amount", "ilsm"),
    "uof_ops_pct": ("funding.use_of_funds.operations_reserve.share", "pct"),
    "appraisal": ("appraisal.central_pre_money", "ilsm"),
    "wacc": ("appraisal.wacc", "pct"),
    "exit_multiple": ("appraisal.exit_multiple", "x"),
    "prudence": ("appraisal.prudence", "pct"),
    "ask_to_appraisal": ("appraisal.ask_to_appraisal", "pct"),
    "markets_2031": ("partner_markets.total_markets_by_2031", "int"),
    "launch_2028": ("partner_markets.launches.2028", "int"),
    "launch_2029": ("partner_markets.launches.2029", "int"),
    "launch_2030": ("partner_markets.launches.2030", "int"),
    "launch_2031": ("partner_markets.launches.2031", "int"),
    "partner_scale": ("inputs.partner_market_scale", "pct"),
    "partner_share": ("inputs.partner_platform_share", "pct"),
    "partner_local_share": ("derived.partner_local_share", "pct"),
    "partner_opex": ("inputs.partner_opex_intensity", "pct"),
    "loss_ratio": ("inputs.expected_loss_ratio", "pct"),
    "cession": ("inputs.cession_rate", "pct"),
    "ceding_commission": ("inputs.ceding_commission", "pct"),
    "carrier_own": ("inputs.insurer_own_expense_ratio", "pct"),
    "carrier_margin_2029": ("carrier_view.rows.2.carrier_margin", "pct1"),
    "fx": ("presentation.fx_usd_ils", "num2"),
    "modules": ("technology.census.service_modules", "int"),
    "packages": ("technology.census.service_packages", "int"),
    "api_modules": ("technology.census.api_modules", "int"),
    "repositories": ("technology.census.repositories", "int"),
    "security_modules": ("technology.census.security_modules", "int"),
    "test_files": ("technology.census.test_files", "int"),
    "hash": ("content_hash", "hash"),
    "plan_version": ("plan_version", "text"),
    "integrity_all": ("integrity.all_hold", "bool"),
    "canonical": ("canonical", "canonical"),
}
# Per-year figures: {key}_{i} → rows[i]
_ROW_FIGURES: Dict[str, Tuple[str, str, str]] = {
    # key: (table, field, fmt)
    "il_new": ("anchor_book", "new_issues", "int"),
    "il_eoy": ("anchor_book", "eoy_in_force", "int"),
    "il_avg": ("anchor_book", "avg_in_force", "int"),
    "il_gwp": ("anchor_book", "risk_gwp", "ilsm"),
    "il_rev": ("anchor_book", "phins_revenue", "ilsm"),
    "il_carrier": ("anchor_book", "carrier_share", "ilsm"),
    "il_savings": ("anchor_book", "savings_flow", "ilsm"),
    "il_opex": ("anchor_book", "opex", "ilsm"),
    "il_ebitda": ("anchor_book", "ebitda", "ilsm"),
    "il_cum": ("anchor_book", "cumulative_ebitda", "ilsm"),
    "il_margin": ("anchor_book", "ebitda_margin", "pct"),
    "pm_live": ("partner_markets", "markets_live", "int"),
    "pm_eoy": ("partner_markets", "eoy_in_force", "int"),
    "pm_avg": ("partner_markets", "avg_in_force", "int"),
    "pm_gwp": ("partner_markets", "risk_gwp", "ilsm"),
    "pm_pool": ("partner_markets", "take_pool", "ilsm"),
    "pm_rev": ("partner_markets", "phins_revenue", "ilsm"),
    "pm_partner": ("partner_markets", "partner_revenue", "ilsm"),
    "pm_opex": ("partner_markets", "opex", "ilsm"),
    "pm_ebitda": ("partner_markets", "ebitda", "ilsm"),
    "g_live": ("group", "markets_live", "int"),
    "g_eoy": ("group", "eoy_in_force", "int"),
    "g_gwp": ("group", "risk_gwp", "ilsm"),
    "g_gwp_usd": ("group", "risk_gwp", "usdm"),
    "g_rev": ("group", "phins_revenue", "ilsm"),
    "g_rev_usd": ("group", "phins_revenue", "usdm"),
    "g_partner": ("group", "partner_revenue", "ilsm"),
    "g_savings": ("group", "savings_flow", "ilsm"),
    "g_opex": ("group", "opex", "ilsm"),
    "g_ebitda": ("group", "ebitda", "ilsm"),
    "g_margin": ("group", "ebitda_margin", "pct"),
    "g_cum": ("group", "cumulative_ebitda", "ilsm"),
    "cv_gwp": ("carrier_view", "risk_gwp", "ilsm"),
    "cv_fee": ("carrier_view", "phins_fee", "ilsm"),
    "cv_claims": ("carrier_view", "expected_claims", "ilsm"),
    "cv_ceded": ("carrier_view", "ceded_premium", "ilsm"),
    "cv_ceded_claims": ("carrier_view", "ceded_claims", "ilsm"),
    "cv_commission": ("carrier_view", "ceding_commission", "ilsm"),
    "cv_own": ("carrier_view", "own_expenses", "ilsm"),
    "cv_result": ("carrier_view", "carrier_result", "ilsm"),
    "cv_margin": ("carrier_view", "carrier_margin", "pct1"),
}
_PLACEHOLDER = re.compile(r"\{([a-z_0-9]+)\}")


def _derived(plan: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "carrier_share_pct": 1.0 - float(plan["inputs"]["phins_take"]),
        "partner_local_share": 1.0 - float(plan["inputs"]["partner_platform_share"]),
    }


def get_path(plan: Mapping[str, Any], path: str) -> Any:
    cur: Any = plan
    for part in path.split("."):
        if isinstance(cur, Mapping):
            cur = cur.get(part)
        elif isinstance(cur, (list, tuple)):
            cur = cur[int(part)]
        else:
            return None
        if cur is None:
            return None
    return cur


def figure_ref(key: str) -> Tuple[str, str]:
    """(path, fmt) for a placeholder key, including per-year keys like il_gwp_2."""
    if key in FIGURES:
        return FIGURES[key]
    m = re.match(r"^(.*)_(\d)$", key)
    if m and m.group(1) in _ROW_FIGURES:
        table, field, fmt = _ROW_FIGURES[m.group(1)]
        return f"{table}.rows.{m.group(2)}.{field}", fmt
    raise KeyError(f"unknown business-plan figure: {key}")


# ---------------------------------------------------------------------------
# Formatting — mirrored by the browser formatter in the HTML page
# ---------------------------------------------------------------------------
def _money_m(value: float, symbol: str, decimals: int) -> str:
    neg = value < 0
    a = abs(value)
    if a >= 1e9:
        s = f"{a / 1e9:.2f}B"
    else:
        s = f"{a / 1e6:.{decimals}f}M"
    return ("−" if neg else "") + symbol + s


def fmt(value: Any, kind: str, fx: float = 3.68) -> str:
    if value is None:
        return "—"
    if kind == "text":
        return str(value)
    if kind == "bool":
        return "all identities hold" if value is True else "integrity check failed"
    if kind == "canonical":
        return "canonical" if value is True else "scenario"
    if kind == "hash":
        return str(value)[:16]
    if kind == "year":
        return str(int(value))
    v = float(value)
    if kind == "ilsm":
        return _money_m(v, "₪", 1)
    if kind == "ilsm0":
        return _money_m(v, "₪", 0)
    if kind == "usdm":
        return _money_m(v / fx, "$", 1)
    if kind == "ils":
        return ("−₪" if v < 0 else "₪") + f"{abs(v):,.0f}"
    if kind == "ils2":
        return ("−₪" if v < 0 else "₪") + f"{abs(v):,.2f}"
    if kind == "int":
        return f"{int(round(v)):,}"
    if kind == "pct":
        return f"{round(v * 100):d}%"
    if kind == "pct1":
        return f"{v * 100:.1f}%"
    if kind == "x":
        return f"{v:.1f}×" if abs(v - round(v)) < 1e-9 else f"{v:g}×"
    if kind == "num2":
        return f"{v:.2f}"
    if kind == "num3":
        return f"{v:.3f}"
    if kind == "months":
        return f"{v:.1f} months"
    return str(value)


def resolve_figure(plan: Mapping[str, Any], key: str) -> Tuple[str, str, str]:
    """(path, fmt, formatted text)."""
    path, kind = figure_ref(key)
    source: Any = plan
    if path.startswith("derived."):
        source = {"derived": _derived(plan)}
    value = get_path(source, path)
    return path, kind, fmt(value, kind, float(plan["presentation"]["fx_usd_ils"]))


# ---------------------------------------------------------------------------
# Narrative — the one standard
# ---------------------------------------------------------------------------
Section = Dict[str, Any]

GATES: List[Tuple[str, str]] = [
    ("12 Oct 2026", "Regulatory pre-ruling meeting with the Capital Market, Insurance and Savings Authority (Jerusalem); MGA bridge and filing scope."),
    ("Q4 2026", "Seed close ({seed} on {pre} pre-money); carrier and reinsurance term sheets for the first contract."),
    ("1 Jan 2027", "Gate 5 — sales begin on the licensed carrier's paper through the PHINS platform (Phin chat intake and classic forms)."),
    ("H1 2027", "Gate 6 — first 1,000 policies in force; Appointed Actuary review of experience against the kernel."),
    ("Q4 2027", "Gate 7 — {il_eoy_0} end-of-year in-force; Series A readiness; first partner-market preparation."),
    ("2028", "First partner market live under a local licensed carrier; Series A ({series_a} indicative) funds scale, not survival."),
    ("2029", "{il_eoy_2} in force in Israel; group EBITDA positive ({first_positive}); {pm_live_2} partner markets live."),
    ("2031", "{markets_2031} markets on one platform; {g_eoy_4} lives; {g_rev_4} PHINS revenue at a {g_margin_4} EBITDA margin."),
]

RISKS: List[Tuple[str, str, str]] = [
    ("Regulatory timing", "A filing slips or a jurisdiction requires a different carrier structure.",
     "Pre-ruling track opened before sales; carrier-of-record model in every market; the pathway table in Appendix C is maintained per jurisdiction."),
    ("Claims experience above plan", "The lifelong ADL-3 trigger runs above the {loss_ratio} expected claims ratio.",
     "Quota-share cession ({cession}) with ceding commission; kernel repricing through the one writer; the carrier view (Appendix B) is restated on every plan refresh."),
    ("Persistency below plan", "Churn runs above {churn}.",
     "Persistency is an explicit factor; the plan is recomputed, never patched. Savings add-on raises retention and is outside risk GWP."),
    ("Partner dependence", "A local partner underdelivers on distribution.",
     "Partner ramp is set at {partner_scale} of the Israel path by default; PHINS keeps {partner_share} of the take and carries only platform opex ({partner_opex} of Israel intensity)."),
    ("Technology and AI governance", "An agent decision is wrong or unexplainable.",
     "Agents recommend, humans decide; every decision is logged with evidence provenance; thresholds are promoted only through an audited step; golden sets gate CI."),
    ("Data integrity", "A figure on an investor surface disagrees with another.",
     "One factor register; integrity identities computed on every render; content hash {hash}… reproduces the exact figures."),
    ("Capital", "The seed does not reach cash break-even on its own.",
     "It is not meant to: {seed} funds the build and the first {burn_2027} year of sales; the peak cumulative need of {peak_need} is covered by the Series A indication of {series_a} ({series_a_buffer} buffer)."),
]

GLOSSARY: List[Tuple[str, str]] = [
    ("ADL-3", "Three or more activities of daily living permanently lost — the objective severity trigger of the lifelong disability mechanism."),
    ("Anchor book", "The Israel plan that every surface reconciles to: kernel premium, 25% / 75% split, persistency path, intensity-scaled opex."),
    ("Carrier of record", "The locally licensed insurer whose paper the contract is written on; PHINS is the technology / MGA layer."),
    ("Content hash", "SHA-256 over the factor inputs and every money line; identical inputs reproduce identical figures."),
    ("Kernel", "`services/pricing_kernel.py`, the single writer for premium decomposition."),
    ("Persistency", "Share of in-force that remains after a year (92% prior book, 96% first-year at default)."),
    ("PHINS take", "The platform share of risk GWP (25% at default) that pays for distribution, underwriting, claims, billing and the agents."),
    ("Quota share", "Proportional reinsurance: the reinsurer takes the cession share of premium and claims and pays a ceding commission."),
    ("Savings flow", "The separately licensed savings add-on (30% election × 3.0 at default); never insurance GWP, never split with the carrier."),
    ("Series A indication", "Peak cumulative cash need less the seed, plus the buffer factor, rounded up to ₪0.5M — derived, not typed."),
]


def _years_label(i: int) -> str:
    return str(YEARS[i])


def plan_sections() -> List[Section]:
    """Part I — the business plan."""
    return [
        {"id": "exec", "num": "1", "title": "Executive summary", "paragraphs": [
            "PHINS is an AI-operated insurance and savings platform. It writes a new regulated contract — life insurance with a lifelong severe-disability (ADL-3) mechanism — on the paper of a licensed carrier, runs the whole operation (chat intake, underwriting, claims, billing, actuarial, reinsurance reporting, marketplace, savings flow) on one platform, and enters every market through a local partnership. The platform is the company; the Israel contract is the first use of it.",
            "The anchor plan is a single, table-driven identity: {premium} annual risk premium at the age-42 specimen, {take} PHINS take / {carrier_share_pct} carrier share, {churn} churn, {il_new_0} / {il_new_1} / {il_new_2} new issues in 2027–2029 and {il_new_4} a year after. It produces {il_eoy_2} policies in force by end-2029 and {il_eoy_4} by end-2031 in Israel alone, with PHINS revenue of {il_rev_2} in 2029 and {il_rev_4} in 2031.",
            "The expansion plan replicates that ramp into OECD partner markets — {markets_2031} markets on one platform by 2031. Each partner market follows the Israel path at {partner_scale} scale from its launch year; PHINS keeps {partner_share} of the platform take and carries only platform opex. Group PHINS revenue reaches {g_rev_4} ({g_rev_usd_4} at the planning FX) in 2031 at a {g_margin_4} EBITDA margin; group risk GWP reaches {g_gwp_4}.",
            "The round is {seed} seed on {pre} pre-money ({post} post, {dilution} dilution). 2027 is the only loss year in the anchor book ({burn_2027} burn); the group's peak cumulative need is {peak_need}, which sets a Series A indication of {series_a} in 2028 to fund scale, not survival. The actuarial appraisal of the same anchor book at a {wacc} discount rate, {exit_multiple} 2029 net revenue and {prudence} prudence is {appraisal}; the ask is {ask_to_appraisal} of it.",
            "Every figure in this document, the deck and the appendices regenerates from one factor register ({plan_version}) and is checked by structural identities on every render; the content hash {hash}… reproduces them. Public evidence is never written by a planning assumption.",
        ]},
        {"id": "company", "num": "2", "title": "Company and method — one platform, local partnerships", "paragraphs": [
            "PHINS builds technology, not balance sheet. In every market the contract is carried by a licensed insurer, reinsured through a quota-share treaty, and distributed with a local partner; PHINS supplies the product design, the pricing kernel, the AI agents and the operating platform as a one-stop shop. The method is identical everywhere — only the carrier, the supervisor and the partner change.",
            "Four flows run on the platform: protection (life + ADL-3, long-term-care solutions), savings (a separately licensed add-on managed as part of the solution), consumption (a health marketplace with coverage-aware ranking and a wallet) and intelligence (underwriting, claims, risk-report and customer agents that recommend while humans decide). The same ledger, identity master and document standard sit under all four.",
            "The organisation is sized to the take: the anchor book's opex is cost-per-average-life by year, so the plan grows headcount with lives rather than ahead of them. Partner markets add platform, actuarial and compliance capacity only ({partner_opex} of Israel intensity); distribution and local operations are the partner's.",
        ]},
        {"id": "market", "num": "3", "title": "Market and OECD partnership map", "paragraphs": [
            "Israel is the anchor: high home-care orientation, a large private long-term-care base, visible public spend and a supervisor already engaged (pre-ruling track, 12 October 2026). From there the plan sequences OECD members where a Solvency II or equivalent carrier can carry the contract and a local partner wants a digital severity layer beside public provision: Portugal and Western Europe, Sweden, Canada, the United States, Australia and Japan, with Bulgaria (accession candidate) and the UAE as partner-led top-up markets.",
            "Market evidence stays in the Scenario Lab, locked and separate. This plan does not restate TAM: it plans lives. The kernel premium is the same ILS-denominated specimen in every market, converted at planning FX pins (Appendix A), so a partner market is comparable with Israel line by line.",
            "Launch schedule: {launch_2028} partner market(s) in 2028, {launch_2029} in 2029, {launch_2030} in 2030 and {launch_2031} in 2031 ({markets_2031} markets including Israel). Every launch count, the ramp scale and the platform share are adjustable factors; the regulatory pathway per market is in Appendix C.",
        ]},
        {"id": "product", "num": "4", "title": "Products and solutions", "paragraphs": [
            "First contract — life insurance with a lifelong disability mechanism. Life face {il_face} with a disability sum of ₪250,000 below 65 (1:4) and a 1:1 mechanism from 65; the disability trigger is permanent loss of three or more activities of daily living. The kernel prices the specimen at {specimen_monthly} a month ({specimen_life_monthly} life + {specimen_dis_monthly} disability at the 1.255 age-42 factor), {premium} a year, from the published risk_reference_v1 tables (0.25 / 0.20 per ₪1,000 monthly).",
            "Long-term-care solutions. The same severity trigger funds a care benefit delivered through the marketplace (home care, residential care, equipment) with coverage-aware ranking, so the benefit buys care rather than cash alone.",
            "Savings flow. {savings_election} of in-force elects a {savings_addon} savings add-on at default, producing {il_savings_2} of savings flow in Israel in 2029 and {g_savings_4} across the group in 2031. Savings is a separately licensed flow managed as part of the solution; it is not insurance GWP and is not split with the carrier. Its fee economics are upside to this plan, not inside it.",
            "Marketplace and wallet. Suppliers are invited, network-governed participants; the health wallet is the checkout and reimbursement centre; delivery bidding and supplier settlement run on the platform ledger.",
        ]},
        {"id": "technology", "num": "5", "title": "Technology — the one standard", "paragraphs": [
            "The technology section is the same in every PHINS document because it is read from the repository, not written: {modules} service modules in {packages} packages, {api_modules} API modules, {repositories} repositories, {security_modules} security modules and {test_files} test files at the time of rendering. The platform is a single Python service with a database-backed durable layer (PostgreSQL / SQLite), a generalized job queue, and a hash-chained ledger.",
            "Ten standards define what 'PHINS technology' means in a partner market, listed in Appendix D: one pricing kernel, append-only integrity, AI governance (agents recommend, humans decide), an evidence pipeline with provenance, durable checksummed agent state, one identity writer, shared security utilities, chat intake beside classic forms, marketplace and payments on the ledger, and one document standard. A partner receives the whole set; nothing is forked per market.",
        ]},
        {"id": "gtm", "num": "6", "title": "Go-to-market and partnership model", "paragraphs": [
            "Israel: direct digital intake (Phin chat and classic application) on the carrier's paper, agents and bancassurance as additional channels, the Authority's pre-ruling track for the filing. The gates are dated (Appendix G): sales 1 January 2027, 1,000 policies, {il_eoy_0} in force by year-end.",
            "Partner markets: PHINS signs a local licensed carrier and a distribution partner, deploys the platform unchanged, and shares the take — {partner_share} to PHINS, {partner_local_share} to the partner at default. The partner carries distribution and local operations; PHINS carries platform, actuarial and compliance support. A partner market is live when its supervisor has the filing and the carrier has the treaty.",
            "Reinsurance: a quota-share treaty ({cession} cession, {ceding_commission} ceding commission at default) sits behind every carrier from day one; the carrier view in Appendix B is what the reinsurer sees.",
        ]},
        {"id": "financials", "num": "7", "title": "Financial plan (ILS, five years)", "paragraphs": [
            "Anchor book (Israel). Risk GWP {il_gwp_0} → {il_gwp_2} → {il_gwp_4}; PHINS revenue {il_rev_0} → {il_rev_2} → {il_rev_4}; opex {il_opex_0} → {il_opex_2} → {il_opex_4}; EBITDA {il_ebitda_0} → {il_ebitda_2} → {il_ebitda_4}. 2028 is already EBITDA-positive ({il_ebitda_1}).",
            "Partner markets. {pm_live_1} market in 2028, {pm_live_2} in 2029, {pm_live_4} in 2031; PHINS revenue {pm_rev_2} in 2029 and {pm_rev_4} in 2031 after the partner's share of {pm_partner_4}.",
            "Group. Risk GWP {g_gwp_4} and PHINS revenue {g_rev_4} in 2031 ({g_rev_usd_4} at {fx} ILS/USD), EBITDA {g_ebitda_4} ({g_margin_4} margin), cumulative EBITDA {g_cum_4}. Full tables are in Appendix F.",
        ]},
        {"id": "capital", "num": "8", "title": "Capital plan and the round", "paragraphs": [
            "Seed {seed} on {pre} pre-money, {post} post ({dilution}). Use of funds: product and technology {uof_tech} ({uof_tech_pct}); regulatory, actuarial and reinsurance {uof_reg} ({uof_reg_pct}); distribution and local partnerships {uof_dist} ({uof_dist_pct}); operations and reserve {uof_ops} ({uof_ops_pct}).",
            "Funding path. The anchor book's 2027 burn is {burn_2027}; the group's cumulative cash low point is {peak_need} (2028, as the first partner market ramps). The Series A indication is that need less the seed plus a {series_a_buffer} buffer: {series_a}, rounded up to ₪0.5M. Group EBITDA turns positive in {first_positive} and cumulative EBITDA in {cum_positive}.",
            "Valuation reference. The actuarial appraisal of the anchor book (PV of 2027–2029 EBITDA plus {exit_multiple} 2029 net revenue, discounted at {wacc}, less {prudence} prudence) is {appraisal}. The {pre} ask is {ask_to_appraisal} of that appraisal; the same formula drives the Monte-Carlo simulator on the pitch dashboard.",
        ]},
        {"id": "risks", "num": "9", "title": "Risks and mitigations", "table": "risks"},
        {"id": "governance", "num": "10", "title": "Governance, milestones and team", "paragraphs": [
            "Decisions that move money or risk are human: underwriting and claims agents recommend, the underwriter and adjuster apply; thresholds are proposed read-only and promoted only through an audited admin step; the regulator has a sealed read-only outline that reconciles to the financial books.",
            "The team is sized by the opex intensity of the anchor book (platform, actuarial, underwriting, claims, customer operations, compliance) and extended per partner market by platform, actuarial and compliance support only. An Appointed Actuary reviews experience against the kernel at each gate.",
        ], "table": "gates"},
        {"id": "founder", "num": "11", "title": "Founder credentials", "paragraphs": [
            FOUNDER["summary"],
        ], "founder": True},
    ]


# Charts placed in the plan sections (section id → chart ids). The same
# specs feed the deck and the appendices; see SECTION_CHARTS consumers.
SECTION_CHARTS: Dict[str, List[str]] = {
    "exec": ["in_force"],
    "financials": ["revenue_ebitda", "gwp_split"],
    "capital": ["cash_curve", "use_of_funds", "appraisal_sensitivity"],
    "governance": ["roadmap"],
}
# Deck slides that carry a chart (slide title → chart id).
SLIDE_CHARTS: Dict[str, str] = {
    "Market and expansion": "in_force",
    "Financials (ILS)": "revenue_ebitda",
    "The round": "use_of_funds",
    "Milestones": "roadmap",
}
# Appendix charts (appendix letter → chart ids).
APPENDIX_CHARTS: Dict[str, List[str]] = {
    "B": ["carrier_view"],
    "F": ["gwp_split", "cash_curve"],
    "G": ["roadmap"],
}


def deck_slides() -> List[Section]:
    """Part II — the investor deck."""
    return [
        {"title": "PHINS", "kicker": "AI insurtech platform · one-stop-shop technology · local OECD partnerships", "bullets": [
            "Life + lifelong ADL-3 disability, long-term care, savings flow and a health marketplace — one regulated contract family, one platform.",
            "Carried by licensed insurers, reinsured by quota share, distributed with local partners; PHINS is the technology.",
            "Seed {seed} on {pre} pre-money. {plan_version} · hash {hash}…",
        ]},
        {"title": "The problem", "bullets": [
            "Severe disability and long-term care are the protection gap that public systems and legacy carriers leave open; savings sit in a separate silo.",
            "Carriers cannot ship a digital severity product: pricing, underwriting, claims and distribution live in different systems with no shared integrity.",
            "Partners in each OECD market want the product and the technology, not a new balance sheet.",
        ]},
        {"title": "The solution", "bullets": [
            "A life contract with a lifelong disability mechanism (1:4 below 65, 1:1 from 65) priced by one kernel: {premium} a year at the age-42 specimen.",
            "Phin chat intake, underwriting bot, claims bot, risk reports, customer agents — all recommend, humans decide, every decision logged with evidence.",
            "Savings add-on ({savings_election} election × {savings_addon}) and a coverage-aware marketplace turn the benefit into care and wealth.",
        ]},
        {"title": "Why now", "bullets": [
            "Supervisor engaged: pre-ruling track with the Capital Market, Insurance and Savings Authority opened 12 October 2026.",
            "Demographics and public spend make the gap legible to regulators, partners and customers.",
            "AI operating model is built: {modules} service modules, {test_files} test files, golden sets gating CI.",
        ]},
        {"title": "Founder", "kicker": FOUNDER["name"] + " · " + FOUNDER["role"], "founder": True, "bullets": [
            "Licensed insurance broker and advocate; designed the contract family (1:4 / 1:1 disability mechanism, ADL-3 trigger) and drafted the regulatory memorandum in actuarial form.",
            "Built the production platform end-to-end — {modules} service modules, {test_files} test files at this render; pricing kernel, hash-chained ledger, AI agents that recommend while humans decide.",
            "Pricing model reviewed by an IAA-recognised executive actuary (26 May 2026); pre-ruling track opened with the Authority on 12 October 2026.",
        ]},
        {"title": "Product and pricing", "bullets": [
            "Kernel specimen: {specimen_life_monthly} life + {specimen_dis_monthly} disability = {specimen_monthly} a month at the 1.255 age-42 factor.",
            "Risk GWP splits {take} PHINS / {carrier_share_pct} carrier; savings flow is a separate licensed flow, never split.",
            "Published tables 0.25 / 0.20 per ₪1,000 monthly; same specimen in every market, converted at planning FX.",
        ]},
        {"title": "Market and expansion", "bullets": [
            "Israel anchor: {il_eoy_0} → {il_eoy_2} → {il_eoy_4} policies in force (2027 / 2029 / 2031).",
            "OECD partner markets: {pm_live_1} in 2028, {pm_live_2} in 2029, {pm_live_4} by 2031 — {markets_2031} markets on one platform.",
            "Group lives {g_eoy_4} and risk GWP {g_gwp_4} in 2031.",
        ]},
        {"title": "Business model", "bullets": [
            "PHINS take {take} of risk GWP pays for distribution, underwriting, claims, billing and the agents.",
            "Partner markets: {partner_share} of the take to PHINS, {partner_local_share} to the local partner who carries distribution.",
            "Opex is cost per average life by year; partner markets add {partner_opex} of Israel intensity.",
        ]},
        {"title": "Technology — one standard", "bullets": [
            "{modules} service modules · {api_modules} API modules · {repositories} repositories · {security_modules} security modules (live census).",
            "One pricing kernel, hash-chained ledger, AI governance, evidence provenance, durable checksummed agent state, one identity writer.",
            "One document standard: navy / gold letterhead, shield emblem, Inter + Space Grotesk — chrome never changes figures.",
        ]},
        {"title": "Milestones", "bullets": [
            "12 Oct 2026 pre-ruling · Q4 2026 seed close · 1 Jan 2027 sales begin.",
            "Gate 6 first 1,000 policies · Gate 7 {il_eoy_0} in force and Series A readiness (Q4 2027).",
            "2028 first partner market · {first_positive} group EBITDA positive · 2031 {markets_2031} markets.",
        ]},
        {"title": "Financials (ILS)", "bullets": [
            "PHINS revenue: {g_rev_0} (2027) → {g_rev_2} (2029) → {g_rev_4} (2031); EBITDA {g_ebitda_0} → {g_ebitda_2} → {g_ebitda_4}.",
            "2031 EBITDA margin {g_margin_4}; cumulative EBITDA {g_cum_4}.",
            "Anchor book alone: {il_rev_4} revenue and {il_ebitda_4} EBITDA in 2031.",
        ]},
        {"title": "The round", "bullets": [
            "Seed {seed} on {pre} pre ({post} post, {dilution}). Use of funds: tech {uof_tech_pct} · regulatory & actuarial {uof_reg_pct} · partnerships {uof_dist_pct} · operations {uof_ops_pct}.",
            "2027 burn {burn_2027}; peak cumulative need {peak_need}; Series A indication {series_a} (2028) funds scale, not survival.",
            "Actuarial appraisal {appraisal} ({wacc} WACC, {exit_multiple} 2029 net revenue, {prudence} prudence); the ask is {ask_to_appraisal} of it.",
        ]},
        {"title": "Integrity", "bullets": [
            "Every figure regenerates from one factor register; structural identities are checked on every render: {integrity_all}.",
            "Anchor book reconciles to the Investor Meeting book and the pitch-dashboard simulator; planning never writes public evidence.",
            "Content hash {hash}… — same inputs, same figures, for any party.",
        ]},
    ]


# ---------------------------------------------------------------------------
# Tables (shared by both renderers)
# ---------------------------------------------------------------------------
def _year_table(plan: Mapping[str, Any], table: str, columns: Sequence[Tuple[str, str, str]],
                html_mode: bool) -> Tuple[List[str], List[List[str]]]:
    """columns: (label, field, fmt). Returns header + rows (one row per metric)."""
    fx = float(plan["presentation"]["fx_usd_ils"])
    rows = plan[table]["rows"]
    header = ["Metric"] + [str(r["year"]) for r in rows]
    body: List[List[str]] = []
    for label, field, kind in columns:
        cells = [label]
        for i, r in enumerate(rows):
            text = fmt(r.get(field), kind, fx)
            if html_mode:
                cells.append(f'<span data-bp="{table}.rows.{i}.{field}" data-fmt="{kind}">{_html.escape(text)}</span>')
            else:
                cells.append(text)
        body.append(cells)
    return header, body


ANCHOR_COLUMNS = [
    ("New issues", "new_issues", "int"),
    ("End-of-year in force", "eoy_in_force", "int"),
    ("Average in force", "avg_in_force", "int"),
    ("Risk GWP", "risk_gwp", "ilsm"),
    ("PHINS revenue (take)", "phins_revenue", "ilsm"),
    ("Carrier share", "carrier_share", "ilsm"),
    ("Savings flow (separate)", "savings_flow", "ilsm"),
    ("Opex", "opex", "ilsm"),
    ("EBITDA", "ebitda", "ilsm"),
    ("EBITDA margin", "ebitda_margin", "pct"),
    ("Cumulative EBITDA", "cumulative_ebitda", "ilsm"),
]
PARTNER_COLUMNS = [
    ("Partner markets live", "markets_live", "int"),
    ("End-of-year in force", "eoy_in_force", "int"),
    ("Average in force", "avg_in_force", "int"),
    ("Risk GWP", "risk_gwp", "ilsm"),
    ("Take pool", "take_pool", "ilsm"),
    ("PHINS revenue", "phins_revenue", "ilsm"),
    ("Partner revenue", "partner_revenue", "ilsm"),
    ("PHINS opex", "opex", "ilsm"),
    ("EBITDA", "ebitda", "ilsm"),
]
GROUP_COLUMNS = [
    ("Markets live (incl. Israel)", "markets_live", "int"),
    ("End-of-year in force", "eoy_in_force", "int"),
    ("Risk GWP", "risk_gwp", "ilsm"),
    ("Risk GWP (USD, planning FX)", "risk_gwp", "usdm"),
    ("PHINS revenue", "phins_revenue", "ilsm"),
    ("PHINS revenue (USD)", "phins_revenue", "usdm"),
    ("Partner revenue", "partner_revenue", "ilsm"),
    ("Savings flow (separate)", "savings_flow", "ilsm"),
    ("Opex", "opex", "ilsm"),
    ("EBITDA", "ebitda", "ilsm"),
    ("EBITDA margin", "ebitda_margin", "pct"),
    ("Cumulative EBITDA", "cumulative_ebitda", "ilsm"),
]
CARRIER_COLUMNS = [
    ("Risk GWP", "risk_gwp", "ilsm"),
    ("PHINS fee", "phins_fee", "ilsm"),
    ("Expected claims", "expected_claims", "ilsm"),
    ("Ceded premium", "ceded_premium", "ilsm"),
    ("Ceded claims", "ceded_claims", "ilsm"),
    ("Ceding commission", "ceding_commission", "ilsm"),
    ("Carrier own expenses", "own_expenses", "ilsm"),
    ("Retained premium", "retained_premium", "ilsm"),
    ("Carrier result", "carrier_result", "ilsm"),
    ("Carrier margin", "carrier_margin", "pct1"),
]

INTEGRITY_LABELS: Dict[str, str] = {
    "anchor_book_reconciles_to_investor_meeting": "Anchor book equals the Investor Meeting book (in-force path, GWP, opex, 5-year extension)",
    "kernel_specimen_is_4518": "Kernel specimen (age 42, published tables) prices at ₪4,518",
    "phins_plus_carrier_equals_gwp": "PHINS take + carrier share = risk GWP, every year",
    "partner_shares_sum_to_take_pool": "PHINS share + partner share = take pool, every year",
    "group_equals_anchor_plus_partners": "Group = anchor book + partner markets, every year",
    "ceded_plus_retained_equals_gwp": "Ceded + retained premium = risk GWP, every year",
    "use_of_funds_sums_to_100": "Use-of-funds shares sum to 100%",
    "savings_not_split_with_carrier": "Savings flow is outside risk GWP and never split 25 / 75",
    "appraisal_formula_matches_valuation_sim": "Appraisal uses the pitch-dashboard simulator's formula",
    "no_public_evidence_written": "No planning assumption writes public evidence, the ledger or the actuarial store",
    "all_hold": "All identities hold",
}


# ---------------------------------------------------------------------------
# Placeholder substitution
# ---------------------------------------------------------------------------
def _fill(text: str, plan: Mapping[str, Any], html_mode: bool) -> str:
    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key == "il_face":  # fixed product term, not a factor
            return "₪1,000,000"
        path, kind, value = resolve_figure(plan, key)
        if not html_mode:
            return value
        return f'<span data-bp="{path}" data-fmt="{kind}">{_html.escape(value)}</span>'
    if html_mode:
        # escape the prose first, then substitute (values are escaped inside repl)
        text = _html.escape(text, quote=False)
    return _PLACEHOLDER.sub(repl, text)


def placeholder_keys() -> List[str]:
    """Every placeholder used by the narrative (for the contract test)."""
    keys: set = set()
    for sec in plan_sections():
        for p in sec.get("paragraphs", []):
            keys.update(_PLACEHOLDER.findall(p))
    for s in deck_slides():
        for b in s["bullets"]:
            keys.update(_PLACEHOLDER.findall(b))
    for _, text in GATES:
        keys.update(_PLACEHOLDER.findall(text))
    for _, a, b in RISKS:
        keys.update(_PLACEHOLDER.findall(a))
        keys.update(_PLACEHOLDER.findall(b))
    for _, text in FOUNDER["credentials"]:
        keys.update(_PLACEHOLDER.findall(text))
    keys.discard("il_face")
    return sorted(keys)


# ---------------------------------------------------------------------------
# Charts, founder block and data-source rows shared by both renderers
# ---------------------------------------------------------------------------
def _chart_caption(spec: Mapping[str, Any]) -> str:
    return f"Figure {spec['id'].replace('_', ' ')} — source: {spec.get('source', '')}"


def _md_chart(plan: Mapping[str, Any], chart_id: str) -> List[str]:
    """Directive (drawn by the PDF generator) + the same data as a table."""
    spec = chart_by_id(plan, chart_id)
    header, rows = chart_table(spec)
    return [
        chart_directive(spec),
        f"**{spec['title']}.** {spec.get('subtitle', '')}",
        "",
        _md_table(header, rows),
        "",
        f"*{_chart_caption(spec)}*",
        "",
    ]


def _html_chart(plan: Mapping[str, Any], chart_id: str) -> str:
    spec = chart_by_id(plan, chart_id)
    return (
        f'<figure class="bp-chart" data-chart-id="{_html.escape(chart_id)}">'
        f'<div class="bp-chart-svg">{render_svg(spec)}</div>'
        f'<figcaption>{_html.escape(_chart_caption(spec))}</figcaption></figure>'
    )


def founder_rows(plan: Mapping[str, Any], html_mode: bool) -> List[List[str]]:
    return [[title, _fill(text, plan, html_mode)] for title, text in FOUNDER["credentials"]]


def data_source_rows(plan: Mapping[str, Any]) -> List[Dict[str, str]]:
    """Appendix I research rows following the plan's market order."""
    return research_rows(plan["markets"])


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------
def _md_table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(c).replace("|", "\\|") for c in r) + " |")
    return "\n".join(out)


def render_markdown(plan: Optional[Mapping[str, Any]] = None) -> str:
    plan = plan or compute_plan()
    f = lambda t: _fill(t, plan, False)  # noqa: E731
    fx = float(plan["presentation"]["fx_usd_ils"])
    L: List[str] = []
    L.append(f"# {DOCUMENT_TITLE}")
    L.append("")
    L.append(f"**Edition:** {DOCUMENT_EDITION}  ")
    L.append(f"**Plan identity:** `{plan['plan_version']}` · content hash `{plan['content_hash']}`  ")
    L.append(f"**Audience:** venture and angel investors, carriers, reinsurers, supervisors and local partners.  ")
    L.append(f"**Companion:** the live, adjustable edition is `/business-plan.html`; the model is `GET /api/business-plan/model`. "
             f"This file is generated from the same model by `scripts/build_business_plan.py` and must not be edited by hand.")
    L.append("")
    L.append("> Planning identity only. Public market evidence stays in the Scenario Lab, locked and separate; "
             "no figure here writes the platform ledger, the actuarial store or any statistic.")
    L.append("")
    L.append("## Headline figures")
    L.append("")
    L.append(_md_table(["Figure", "Value"], [
        ["Annual risk premium (kernel specimen, age 42)", f("{premium}")],
        ["PHINS take / carrier share", f("{take} / {carrier_share_pct}")],
        ["Israel in force, end-2029 / end-2031", f("{il_eoy_2} / {il_eoy_4}")],
        ["Markets on the platform by 2031", f("{markets_2031}")],
        ["Group PHINS revenue 2031 (ILS / USD at planning FX)", f("{g_rev_4} / {g_rev_usd_4}")],
        ["Group EBITDA margin 2031", f("{g_margin_4}")],
        ["Seed / pre-money / post-money", f("{seed} / {pre} / {post}")],
        ["Series A indication (2028)", f("{series_a}")],
        ["Actuarial appraisal (anchor book)", f("{appraisal}")],
        ["Integrity", f("{integrity_all}")],
    ]))
    L.append("")
    L.append("---")
    L.append("")
    L.append("# Part I — Business plan")
    L.append("")
    for sec in plan_sections():
        L.append(f"## {sec['num']}. {sec['title']}")
        L.append("")
        for p in sec.get("paragraphs", []):
            L.append(f(p))
            L.append("")
        if sec.get("table") == "risks":
            L.append(_md_table(["Risk", "What could go wrong", "Mitigation in the plan"],
                               [[r[0], f(r[1]), f(r[2])] for r in RISKS]))
            L.append("")
        if sec.get("table") == "gates":
            L.append(_md_table(["When", "Gate"], [[g[0], f(g[1])] for g in GATES]))
            L.append("")
        if sec.get("founder"):
            L.append(f"![{FOUNDER['name']} — founder portrait]({FOUNDER_PORTRAIT_URL})")
            L.append("")
            L.append(f"**{FOUNDER['name']}** — {FOUNDER['role']}")
            L.append("")
            L.append(_md_table(["Credential", "Detail"], founder_rows(plan, False)))
            L.append("")
            for pr in FOUNDER["principles"]:
                L.append(f"- {pr}")
            L.append("")
        for chart_id in SECTION_CHARTS.get(sec["id"], []):
            L.extend(_md_chart(plan, chart_id))
    L.append("---")
    L.append("")
    L.append("# Part II — Investor deck")
    L.append("")
    for i, s in enumerate(deck_slides(), 1):
        L.append(f"## Slide {i} — {s['title']}")
        if s.get("kicker"):
            L.append(f"*{s['kicker']}*")
        L.append("")
        for b in s["bullets"]:
            L.append(f"- {f(b)}")
        L.append("")
        if s["title"] in SLIDE_CHARTS:
            spec = chart_by_id(plan, SLIDE_CHARTS[s["title"]])
            L.append(chart_directive(spec))
            L.append(f"*Chart: {spec['title']} — data in Part I and Appendix F.*")
            L.append("")
    L.append("---")
    L.append("")
    L.append("# Part III — Appendices")
    L.append("")
    # A
    L.append("## Appendix A — Actuarial basis and pricing kernel")
    L.append("")
    L.append(f("The specimen is priced by `services/pricing_kernel.py` from the published `risk_reference_v1` tables: "
               "life 0.25 and disability 0.20 per ₪1,000 monthly, times the locked age curve (factor {specimen_age_factor} at age 42). "
               "Life face ₪1,000,000; disability sum ₪250,000 below 65 (1:4) and 1:1 from 65. Issue ages 3–65."))
    L.append("")
    sp = plan["specimen"]
    L.append(_md_table(["Specimen line", "Value"], [
        ["Age / age factor", f"{sp['avg_age']} / {sp['age_factor']:.3f}"],
        ["Life sum / disability sum", f"₪{sp['life_sum']:,.0f} / ₪{sp['disability_sum']:,.0f}"],
        ["Life monthly / disability monthly", f"₪{sp['life_monthly']:,.2f} / ₪{sp['disability_monthly']:,.2f}"],
        ["Total monthly / annual", f"₪{sp['total_monthly']:,.2f} / ₪{sp['annual_premium']:,.0f}"],
    ]))
    L.append("")
    L.append("Same specimen in every planning market (ILS face, local currency at the planning FX pin — never live FX, never evidence):")
    L.append("")
    L.append(_md_table(["Market", "OECD", "Currency", "Planning age", "Kernel premium (ILS)", "Kernel premium (local)"],
                       [[m["name"], m["oecd"], m["currency"], str(m["planning_age"]),
                         f"₪{m['kernel_premium_ils']:,.0f}", f"{m['kernel_premium_local']:,} {m['currency']}"]
                        for m in plan["markets"]]))
    L.append("")
    # B
    L.append("## Appendix B — Carrier and reinsurance view (Israel anchor book)")
    L.append("")
    L.append(f("The carrier books 100% of risk GWP, pays the PHINS fee ({take}), expects claims of {loss_ratio} of GWP, "
               "cedes {cession} by quota share, receives a {ceding_commission} ceding commission on ceded premium and keeps "
               "{carrier_own} of GWP for capital, governance and compliance. Carrier margin in 2029: {carrier_margin_2029}. "
               "All five are adjustable factors; the table restates on every change."))
    L.append("")
    h, b = _year_table(plan, "carrier_view", CARRIER_COLUMNS, False)
    L.append(_md_table(h, b))
    L.append("")
    for chart_id in APPENDIX_CHARTS["B"]:
        L.extend(_md_chart(plan, chart_id))
    # C
    L.append("## Appendix C — Regulatory pathway by market")
    L.append("")
    L.append(_md_table(["Market", "OECD status", "Supervisor", "Pathway"],
                       [[m["name"], m["oecd"], m["supervisor"], m["pathway"]] for m in plan["markets"]]))
    L.append("")
    # D
    L.append("## Appendix D — Technology architecture and security standard")
    L.append("")
    c = plan["technology"]["census"]
    L.append(_md_table(["Census (live)", "Count"], [
        ["Service modules (`services/*.py`)", f"{c['service_modules']:,}"],
        ["Service packages", f"{c['service_packages']:,}"],
        ["API modules (`web_portal/api_*.py`)", f"{c['api_modules']:,}"],
        ["Repositories (`database/repositories/*_repository.py`)", f"{c['repositories']:,}"],
        ["Security modules (`security/*.py`)", f"{c['security_modules']:,}"],
        ["Test files", f"{c['test_files']:,}"],
        ["Agents with golden sets", f"{c['golden_agents']:,}"],
    ]))
    L.append("")
    L.append(_md_table(["Pillar", "Standard"], [[t["pillar"], t["standard"]] for t in plan["technology"]["standard"]]))
    L.append("")
    # E
    L.append("## Appendix E — Data integrity and methodology")
    L.append("")
    L.append("Identities computed on this render:")
    L.append("")
    L.append(_md_table(["Identity", "Holds"], [[INTEGRITY_LABELS.get(k, k), "yes" if v is True else "NO"]
                                               for k, v in plan["integrity"].items()]))
    L.append("")
    L.append("Factor register (every adjustable assumption, its default and bounds):")
    L.append("")
    L.append(_md_table(["Group", "Factor", "Default", "Min", "Max", "Note"],
                       [[next(g["label"] for g in FACTOR_GROUPS if g["id"] == fa["group"]), fa["label"],
                         _factor_text(fa, fa["default"]), _factor_text(fa, fa["min"]), _factor_text(fa, fa["max"]),
                         fa.get("note") or ""] for fa in FACTORS]))
    L.append("")
    L.append("Method: in-force follows `eoy = round(prior × persistency) + round(new × first-year persistency)`, average in force is the mid-point, "
             "risk GWP = average in force × premium, PHINS revenue = GWP × take, opex = intensity (ILS per average life, by plan year) × average in force. "
             "Partner cohorts follow the same recursion from their launch year at the ramp scale; group = anchor + partners. "
             "Funding is derived from the group cash curve. The appraisal is PV(EBITDA 2027–2029) + exit multiple × 2029 net revenue, discounted at WACC, less prudence.")
    L.append("")
    # F
    L.append("## Appendix F — Financial tables (ILS)")
    L.append("")
    for title, table, cols in (("F.1 Anchor book — Israel", "anchor_book", ANCHOR_COLUMNS),
                               ("F.2 Partner markets", "partner_markets", PARTNER_COLUMNS),
                               ("F.3 Group", "group", GROUP_COLUMNS)):
        L.append(f"### {title}")
        L.append("")
        h, b = _year_table(plan, table, cols, False)
        L.append(_md_table(h, b))
        L.append("")
    L.append("### F.4 Funding")
    L.append("")
    fu = plan["funding"]
    L.append(_md_table(["Line", "Value"], [
        ["Seed / pre-money / post-money", f("{seed} / {pre} / {post}")],
        ["Seed dilution", f("{dilution}")],
        ["2027 burn (anchor book EBITDA)", f("{burn_2027}")],
        ["Runway on seed at the 2027 burn rate", fmt(fu["runway_months_on_seed"], "months")],
        ["Peak cumulative need (group)", f("{peak_need}")],
        [f("Series A indication (need − seed, + {series_a_buffer} buffer)"), f("{series_a}")],
        ["First EBITDA-positive year (group)", f("{first_positive}")],
        ["Cumulative EBITDA positive (group)", f("{cum_positive}")],
        ["Use of seed — product & technology", f("{uof_tech} ({uof_tech_pct})")],
        ["Use of seed — regulatory, actuarial & reinsurance", f("{uof_reg} ({uof_reg_pct})")],
        ["Use of seed — distribution & local partnerships", f("{uof_dist} ({uof_dist_pct})")],
        ["Use of seed — operations & reserve", f("{uof_ops} ({uof_ops_pct})")],
        ["Actuarial appraisal (anchor book)", f("{appraisal} at {wacc} WACC, {exit_multiple} 2029 net revenue, {prudence} prudence")],
    ]))
    L.append("")
    L.append("### F.5 Charts")
    L.append("")
    for chart_id in APPENDIX_CHARTS["F"]:
        L.extend(_md_chart(plan, chart_id))
    # G
    L.append("## Appendix G — Milestone and governance calendar")
    L.append("")
    L.append(_md_table(["When", "Gate"], [[g[0], f(g[1])] for g in GATES]))
    L.append("")
    for chart_id in APPENDIX_CHARTS["G"]:
        L.extend(_md_chart(plan, chart_id))
    # H
    L.append("## Appendix H — Glossary")
    L.append("")
    for term, text in GLOSSARY:
        L.append(f"- **{term}** — {text}")
    L.append("")
    # I
    L.append("## Appendix I — Data sources and figure lineage")
    L.append("")
    L.append("Every class of figure in this document, where it comes from and whether it feeds the model. "
             "External research is reference only: the plan counts lives (not market size) from the kernel premium and the persistency identity, "
             "so no statistic moves a planning figure and no planning figure rewrites a statistic.")
    L.append("")
    L.append(_md_table(["Figure class", "Source", "Kind", "Feeds the model", "Note"],
                       [[r["figure"], r["source"], r["kind"], "yes" if r["feeds_model"] else "reference only", r["note"]]
                        for r in LINEAGE]))
    L.append("")
    L.append("External research registry behind the market section — the same registry the Scenario Lab cites on the pitch dashboard, by planning market:")
    L.append("")
    L.append(_md_table(["Market", "Source", "Type · strength", "Used for", "URL"],
                       [[r["market"], r["title"], f"{r['type']} · {r['strength']}", r["note"], r["url"]]
                        for r in data_source_rows(plan)]))
    L.append("")
    L.append("---")
    L.append("")
    L.append(f"*{CONTACT} · Confidential — prepared for investors, carriers, reinsurers and supervisors. "
             f"Generated from `services/business_plan_model.py` ({plan['plan_version']}); content hash `{plan['content_hash']}`.*")
    L.append("")
    return "\n".join(L)


def _factor_text(spec: Mapping[str, Any], value: float) -> str:
    kind = spec["kind"]
    if kind == "ratio":
        return f"{value * 100:g}%"
    if kind == "money":
        return f"₪{value:,.0f}"
    if kind == "int":
        return f"{int(value)}"
    if kind == "multiplier":
        return f"{value:g}×"
    return f"{value:g}"


# ---------------------------------------------------------------------------
# HTML renderer — PHINS letterhead standard
# ---------------------------------------------------------------------------
_CSS = """
:root {
  --phins-navy: #0e2f63; --phins-navy-deep: #060d1f; --phins-navy-mid: #123f82;
  --phins-gold: #c9a04e; --phins-gold-strong: #f7e2a0; --phins-gold-deep: #b8893b;
  --phins-ink: #12284c; --phins-muted: #5b6b82; --phins-ice: #f3f7fd; --phins-line: #d5deea;
  --bp-grad: linear-gradient(135deg, #060d1f 0%, #0e2f63 46%, #123f82 100%);
  --bp-gold-rule: linear-gradient(90deg, #b8893b 0%, #f7e2a0 42%, #e3bf6f 100%);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; background: #e8eef6; color: var(--phins-ink); font-family: Inter, "Segoe UI", sans-serif; line-height: 1.55;
       -webkit-font-smoothing: antialiased; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
h1, h2, h3, h4, .bp-display { font-family: "Space Grotesk", Inter, "Segoe UI", sans-serif; color: var(--phins-navy); margin: 0 0 8px; letter-spacing: 0.005em; }
h1 { font-size: 30px; line-height: 1.15; } h2 { font-size: 21px; margin-top: 6px; } h3 { font-size: 16px; } h4 { font-size: 13.5px; color: var(--phins-navy-mid); }
p { margin: 8px 0; } a { color: var(--phins-navy-mid); }
code { font-size: 12px; color: var(--phins-navy-mid); word-break: break-all; }
.bp-topbar { position: sticky; top: 0; z-index: 40; background: var(--bp-grad); color: #fff; display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 22px; flex-wrap: wrap; box-shadow: 0 8px 30px rgba(2,8,23,0.35); border-bottom: 1px solid rgba(127,178,255,0.16); }
.bp-brand { display: flex; align-items: center; gap: 12px; text-decoration: none; color: #fff; }
.bp-brand img { width: 40px; height: 40px; display: block; filter: drop-shadow(0 4px 14px rgba(79,216,255,0.3)); }
.bp-wordmark { font-family: "Space Grotesk", Inter, sans-serif; font-weight: 700; letter-spacing: 0.1em; font-size: 19px; line-height: 1; }
.bp-tagline { font-size: 10.5px; letter-spacing: 0.04em; opacity: 0.84; margin-top: 3px; }
.bp-nav { display: flex; gap: 4px; flex-wrap: wrap; }
.bp-nav a { color: rgba(234,241,255,0.88); text-decoration: none; font-size: 12.5px; font-weight: 600; padding: 6px 10px; border-radius: 999px; }
.bp-nav a:hover { background: rgba(255,255,255,0.1); color: #fff; }
.bp-tools { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.bp-btn { font-family: inherit; font-size: 12px; font-weight: 700; cursor: pointer; border: 1px solid rgba(255,255,255,0.3); background: rgba(255,255,255,0.08); color: #fff; border-radius: 999px; padding: 7px 13px; text-decoration: none; }
.bp-btn:hover { background: rgba(255,255,255,0.18); }
.bp-btn.gold { background: linear-gradient(180deg, #f7e2a0 0%, #e3bf6f 100%); color: #071022; border-color: transparent; }
.bp-shell { max-width: 1080px; margin: 24px auto; background: #fff; border-radius: 18px; overflow: hidden; box-shadow: 0 16px 40px rgba(6,13,31,0.12); }
.bp-banner { background: var(--bp-grad); color: #fff; padding: 34px 34px 28px; position: relative; overflow: hidden; }
.bp-banner::after { content: ""; position: absolute; inset: auto -10% -60% auto; width: 520px; height: 520px; border-radius: 50%; background: radial-gradient(closest-side, rgba(21,68,155,0.55), transparent 70%); pointer-events: none; }
.bp-banner .bp-eyebrow { font-size: 11.5px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--phins-gold-strong); font-weight: 700; }
.bp-banner h1 { color: #fff; margin-top: 10px; max-width: 760px; }
.bp-banner p { color: rgba(234,241,255,0.9); max-width: 760px; font-size: 15px; }
.bp-banner .bp-meta { font-size: 12px; opacity: 0.82; margin-top: 14px; }
.bp-gold { height: 5px; background: var(--bp-gold-rule); }
.bp-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; padding: 20px 34px 4px; }
.bp-kpi { position: relative; overflow: hidden; border-radius: 12px; padding: 14px 14px 12px; color: #eaf1ff; background: radial-gradient(130% 110% at 100% 0%, rgba(21,68,155,0.38), transparent 62%), #071022; border: 1px solid rgba(127,178,255,0.16); }
.bp-kpi .bp-kpi-label { font-size: 10.5px; letter-spacing: 0.08em; text-transform: uppercase; opacity: 0.78; }
.bp-kpi .bp-kpi-value { font-family: "Space Grotesk", Inter, sans-serif; font-size: 22px; font-weight: 700; margin-top: 4px; color: var(--phins-gold-strong); }
.bp-kpi .bp-kpi-note { font-size: 11px; opacity: 0.74; margin-top: 2px; }
.bp-body { padding: 18px 34px 10px; }
.bp-part { margin: 30px 0 8px; padding-top: 18px; border-top: 1px solid var(--phins-line); }
.bp-part .bp-eyebrow { font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--phins-gold-deep); font-weight: 700; }
section.bp-section { margin: 20px 0 6px; page-break-inside: avoid; }
section.bp-section h2 .secno { color: var(--phins-gold-deep); margin-right: 8px; }
.bp-chip { display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; padding: 3px 9px; border-radius: 999px; background: var(--phins-ice); color: var(--phins-navy); border: 1px solid var(--phins-line); }
.bp-chip.ok { background: #eef8f1; color: #15603a; border-color: #bfe3cc; }
.bp-chip.warn { background: #fff5e6; color: #8a4b00; border-color: #f3d7a6; }
.bp-chip.gold { background: linear-gradient(180deg, #f7e2a0 0%, #e3bf6f 100%); color: #071022; border-color: transparent; }
[data-bp] { font-variant-numeric: tabular-nums; font-weight: 600; color: var(--phins-navy); }
.bp-kpi [data-bp], .bp-banner [data-bp], .bp-slide-head [data-bp] { color: inherit; }
table.bp-table { width: 100%; border-collapse: collapse; margin: 12px 0 18px; font-size: 13.5px; }
.bp-table th, .bp-table td { border: 1px solid var(--phins-line); padding: 7px 10px; text-align: left; vertical-align: top; }
.bp-table th { background: var(--phins-ice); color: var(--phins-navy); font-weight: 600; }
.bp-table td.num, .bp-table th.num { text-align: right; }
.bp-table tr:nth-child(even) td { background: #fafcff; }
.bp-deck { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; margin-top: 12px; }
.bp-slide { border-radius: 14px; overflow: hidden; border: 1px solid var(--phins-line); background: #fff; display: flex; flex-direction: column; page-break-inside: avoid; }
.bp-slide-head { background: var(--bp-grad); color: #fff; padding: 14px 16px 12px; }
.bp-slide-head .bp-slide-no { font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--phins-gold-strong); font-weight: 700; }
.bp-slide-head h3 { color: #fff; margin: 4px 0 0; font-size: 17px; }
.bp-slide-head .bp-kicker { font-size: 12px; opacity: 0.86; margin-top: 4px; }
.bp-slide-gold { height: 3px; background: var(--bp-gold-rule); }
.bp-slide ul { margin: 10px 16px 14px 32px; padding: 0; font-size: 13.5px; } .bp-slide li { margin: 5px 0; }
.bp-factors { margin: 18px 34px 0; border: 1px solid var(--phins-line); border-radius: 14px; background: linear-gradient(180deg, #fbfdff 0%, #fff 100%); }
.bp-factors summary { cursor: pointer; padding: 14px 18px; font-family: "Space Grotesk", Inter, sans-serif; font-weight: 700; color: var(--phins-navy); display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; list-style: none; }
.bp-factors summary::-webkit-details-marker { display: none; }
.bp-factors-body { padding: 0 18px 16px; }
.bp-factor-group { margin-top: 12px; } .bp-factor-group h4 { margin-bottom: 6px; }
.bp-factor-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 10px; }
.bp-factor label { display: block; font-size: 11.5px; color: var(--phins-muted); margin-bottom: 3px; }
.bp-factor input { width: 100%; font-family: inherit; font-size: 13px; padding: 7px 9px; border: 1px solid var(--phins-line); border-radius: 9px; color: var(--phins-ink); }
.bp-factor input:focus { outline: 2px solid rgba(201,160,78,0.55); border-color: var(--phins-gold); }
.bp-factor.changed input { border-color: var(--phins-gold); background: #fffaf0; }
.bp-status { font-size: 12px; color: var(--phins-muted); }
.bp-chips { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.bp-foot { padding: 16px 34px 22px; border-top: 1px solid var(--phins-line); font-size: 12px; color: var(--phins-muted); display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.phins-letterhead { display: none; align-items: center; gap: 12px; padding: 0 0 10px; margin-bottom: 14px; border-bottom: 2.4px solid #c9a04e; position: relative; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
.phins-letterhead::after { content: ''; position: absolute; inset-inline: 0; bottom: -4px; height: 1px; background: #0e2f63; }
.phins-letterhead img { width: 40px; height: 40px; object-fit: contain; }
.phins-letterhead .lh-name { font-family: "Space Grotesk", Inter, sans-serif; font-size: 15pt; font-weight: 700; color: #0e2f63; letter-spacing: 0.08em; line-height: 1.1; }
.phins-letterhead .lh-tag { font-size: 7pt; color: #5b6b82; letter-spacing: 0.08em; text-transform: uppercase; }
.bp-glossary dt { font-weight: 700; color: var(--phins-navy); margin-top: 8px; } .bp-glossary dd { margin: 2px 0 0 0; }
figure.bp-chart { margin: 14px 0 18px; padding: 10px 12px 8px; border: 1px solid var(--phins-line); border-radius: 14px; background: #fff; page-break-inside: avoid; }
figure.bp-chart .bp-chart-svg svg { width: 100%; height: auto; display: block; }
figure.bp-chart figcaption { font-size: 11px; color: var(--phins-muted); margin-top: 6px; }
figure.bp-chart.updating { opacity: 0.55; transition: opacity .15s; }
.bp-slide figure.bp-chart { margin: 0 12px 12px; padding: 6px 8px 4px; }
.bp-founder { display: grid; grid-template-columns: 200px 1fr; gap: 20px; align-items: start; margin: 12px 0 16px; padding: 18px; border-radius: 14px; border: 1px solid var(--phins-line); background: linear-gradient(180deg, #fbfdff 0%, #fff 100%); page-break-inside: avoid; }
.bp-founder-photo { position: relative; width: 200px; height: 200px; border-radius: 16px; overflow: hidden; background: var(--bp-grad); box-shadow: 0 10px 28px rgba(6,13,31,0.22); border: 3px solid #fff; outline: 1px solid var(--phins-gold); }
.bp-founder-photo img { width: 100%; height: 100%; object-fit: cover; display: block; }
.bp-founder-photo .bp-monogram { display: none; width: 100%; height: 100%; align-items: center; justify-content: center; font-family: "Space Grotesk", Inter, sans-serif; font-size: 64px; font-weight: 700; color: var(--phins-gold-strong); letter-spacing: 0.06em; }
.bp-founder-photo.fallback img { display: none; } .bp-founder-photo.fallback .bp-monogram { display: flex; }
.bp-founder h3 { margin: 0; font-size: 20px; } .bp-founder .bp-founder-role { color: var(--phins-gold-deep); font-weight: 700; font-size: 12.5px; letter-spacing: 0.06em; text-transform: uppercase; margin: 2px 0 10px; }
.bp-founder ul.bp-principles { margin: 10px 0 0 18px; padding: 0; font-size: 13px; color: var(--phins-muted); }
.bp-slide .bp-slide-founder { display: flex; gap: 12px; align-items: center; padding: 12px 16px 0; }
.bp-slide .bp-slide-founder .bp-founder-photo { width: 72px; height: 72px; border-radius: 12px; flex: none; }
.bp-slide .bp-slide-founder .bp-monogram { font-size: 24px; }
.bp-source-url { font-size: 11px; word-break: break-all; }
@media (max-width: 720px) { .bp-founder { grid-template-columns: 1fr; } .bp-founder-photo { width: 160px; height: 160px; } }
@page { size: A4; margin: 16mm 14mm 18mm 14mm; }
@media print {
  body { background: #fff; }
  .bp-topbar, .bp-factors, .phins-doc-return, .bp-noprint { display: none !important; }
  .bp-shell { box-shadow: none; border-radius: 0; margin: 0; max-width: none; }
  .phins-letterhead { display: flex; }
  .bp-banner, .bp-kpi, .bp-slide-head, .bp-gold, .bp-slide-gold { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  .bp-part { page-break-before: always; border-top: none; }
  a { color: inherit; text-decoration: none; }
}
@media (max-width: 720px) { .bp-banner, .bp-body, .bp-kpis, .bp-foot { padding-left: 18px; padding-right: 18px; } .bp-factors { margin-left: 18px; margin-right: 18px; } h1 { font-size: 24px; } }
"""

_JS = r"""
(function () {
  'use strict';
  var FACTORS = JSON.parse(document.getElementById('bp-factors').textContent);
  var DEFAULTS = {}; FACTORS.forEach(function (f) { DEFAULTS[f.id] = f.default; });
  var state = {};
  var fx = 3.68;

  function moneyM(v, sym, dp) {
    var neg = v < 0, a = Math.abs(v), s;
    if (a >= 1e9) s = (a / 1e9).toFixed(2) + 'B'; else s = (a / 1e6).toFixed(dp) + 'M';
    return (neg ? '\u2212' : '') + sym + s;
  }
  function intFmt(v) { return Math.round(v).toLocaleString('en-US'); }
  function fmt(v, kind) {
    if (v === null || v === undefined) return '\u2014';
    if (kind === 'text') return String(v);
    if (kind === 'bool') return v === true ? 'all identities hold' : 'integrity check failed';
    if (kind === 'canonical') return v === true ? 'canonical' : 'scenario';
    if (kind === 'hash') return String(v).slice(0, 16);
    if (kind === 'year') return String(Math.round(v));
    var n = Number(v);
    if (kind === 'ilsm') return moneyM(n, '\u20AA', 1);
    if (kind === 'ilsm0') return moneyM(n, '\u20AA', 0);
    if (kind === 'usdm') return moneyM(n / fx, '$', 1);
    if (kind === 'ils') return (n < 0 ? '\u2212\u20AA' : '\u20AA') + Math.abs(Math.round(n)).toLocaleString('en-US');
    if (kind === 'ils2') return (n < 0 ? '\u2212\u20AA' : '\u20AA') + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (kind === 'int') return intFmt(n);
    if (kind === 'pct') return Math.round(n * 100) + '%';
    if (kind === 'pct1') return (n * 100).toFixed(1) + '%';
    if (kind === 'x') return (Math.abs(n - Math.round(n)) < 1e-9 ? n.toFixed(1) : String(n)) + '\u00D7';
    if (kind === 'num2') return n.toFixed(2);
    if (kind === 'num3') return n.toFixed(3);
    if (kind === 'months') return n.toFixed(1) + ' months';
    return String(v);
  }
  function getPath(obj, path) {
    var cur = obj, parts = path.split('.');
    for (var i = 0; i < parts.length; i++) {
      if (cur === null || cur === undefined) return null;
      cur = Array.isArray(cur) ? cur[Number(parts[i])] : cur[parts[i]];
    }
    return cur === undefined ? null : cur;
  }
  function derived(plan) {
    return { carrier_share_pct: 1 - Number(plan.inputs.phins_take), partner_local_share: 1 - Number(plan.inputs.partner_platform_share) };
  }
  function apply(plan) {
    fx = Number(plan.presentation && plan.presentation.fx_usd_ils) || fx;
    var d = { derived: derived(plan) };
    var nodes = document.querySelectorAll('[data-bp]');
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i], path = el.getAttribute('data-bp'), kind = el.getAttribute('data-fmt') || 'text';
      var src = path.indexOf('derived.') === 0 ? d : plan;
      var text = fmt(getPath(src, path), kind);
      if (el.textContent !== text) el.textContent = text;
    }
    var canon = document.getElementById('bp-canonical');
    if (canon) { canon.textContent = plan.canonical ? 'Canonical plan' : 'Scenario (factors adjusted)'; canon.className = 'bp-chip ' + (plan.canonical ? 'gold' : 'warn'); }
    var integ = document.getElementById('bp-integrity');
    if (integ) { var ok = plan.integrity && plan.integrity.all_hold === true; integ.textContent = ok ? 'Integrity: all identities hold' : 'Integrity: check failed'; integ.className = 'bp-chip ' + (ok ? 'ok' : 'warn'); }
    var rows = document.querySelectorAll('[data-bp-integrity]');
    for (var r = 0; r < rows.length; r++) { var k = rows[r].getAttribute('data-bp-integrity'); var v = plan.integrity ? plan.integrity[k] : null; rows[r].textContent = v === true ? 'yes' : 'NO'; }
    var err = document.getElementById('bp-errors');
    if (err) err.textContent = (plan.errors && plan.errors.length) ? ('Out-of-range values reset to default: ' + plan.errors.join('; ')) : '';
    var link = document.getElementById('bp-json-link');
    if (link) link.setAttribute('href', '/api/business-plan/model' + query());
    applyCharts(plan);
    try { window.dispatchEvent(new CustomEvent('phins:business-plan', { detail: plan })); } catch (e) {}
  }
  // Charts are drawn by the server from the same plan (one layout engine for
  // the page, the live refresh and the PDF); the browser only swaps the SVG.
  function applyCharts(plan) {
    var figures = document.querySelectorAll('figure.bp-chart[data-chart-id]');
    var byId = {};
    (plan.charts || []).forEach(function (c) { byId[c.id] = c; });
    for (var i = 0; i < figures.length; i++) {
      var fig = figures[i], chart = byId[fig.getAttribute('data-chart-id')];
      fig.classList.remove('updating');
      if (!chart || !chart.svg) continue;
      var host = fig.querySelector('.bp-chart-svg');
      if (host && host.innerHTML !== chart.svg) host.innerHTML = chart.svg;
    }
  }
  function markChartsUpdating() {
    var figures = document.querySelectorAll('figure.bp-chart');
    for (var i = 0; i < figures.length; i++) figures[i].classList.add('updating');
  }
  function query() {
    var parts = [];
    Object.keys(state).forEach(function (k) { if (state[k] !== DEFAULTS[k]) parts.push(encodeURIComponent(k) + '=' + encodeURIComponent(state[k])); });
    return parts.length ? '?' + parts.join('&') : '';
  }
  var timer = null;
  function refresh() {
    if (timer) clearTimeout(timer);
    timer = setTimeout(function () {
      var q = query();
      try { history.replaceState(null, '', location.pathname + q + location.hash); } catch (e) {}
      markChartsUpdating();
      fetch('/api/business-plan/model' + (q ? q + '&' : '?') + 'charts=1', { credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(apply)
        .catch(function () { applyCharts({}); });
    }, 120);
  }
  function portraitFallback() {
    var photos = document.querySelectorAll('.bp-founder-photo img');
    for (var i = 0; i < photos.length; i++) {
      photos[i].addEventListener('error', function (ev) { var box = ev.target.parentNode; if (box) box.classList.add('fallback'); });
      if (photos[i].complete && photos[i].naturalWidth === 0) photos[i].parentNode.classList.add('fallback');
    }
  }
  function buildPanel() {
    var host = document.getElementById('bp-factor-groups');
    if (!host) return;
    var groups = JSON.parse(document.getElementById('bp-factor-groups-json').textContent);
    groups.forEach(function (g) {
      var items = FACTORS.filter(function (f) { return f.group === g.id; });
      if (!items.length) return;
      var wrap = document.createElement('div'); wrap.className = 'bp-factor-group';
      var h = document.createElement('h4'); h.textContent = g.label; wrap.appendChild(h);
      var grid = document.createElement('div'); grid.className = 'bp-factor-grid';
      items.forEach(function (f) {
        var box = document.createElement('div'); box.className = 'bp-factor'; box.id = 'bp-factor-' + f.id;
        var label = document.createElement('label'); label.setAttribute('for', 'bp-input-' + f.id); label.textContent = f.label; box.appendChild(label);
        var input = document.createElement('input'); input.type = 'number'; input.id = 'bp-input-' + f.id;
        input.min = f.min; input.max = f.max; input.step = f.step; input.value = state[f.id];
        if (f.note) input.title = f.note;
        input.addEventListener('input', function () {
          var v = parseFloat(input.value);
          if (!isFinite(v)) return;
          if (v < f.min) v = f.min; if (v > f.max) v = f.max;
          if (f.kind === 'int') v = Math.round(v);
          state[f.id] = v; box.classList.toggle('changed', v !== DEFAULTS[f.id]); refresh();
        });
        box.appendChild(input); grid.appendChild(box);
      });
      wrap.appendChild(grid); host.appendChild(wrap);
    });
  }
  function readUrl() {
    var params = new URLSearchParams(location.search);
    FACTORS.forEach(function (f) {
      var raw = params.get(f.id), v = raw === null ? NaN : parseFloat(raw);
      state[f.id] = (isFinite(v) && v >= f.min && v <= f.max) ? v : f.default;
    });
  }
  function reset() {
    FACTORS.forEach(function (f) { state[f.id] = f.default; var el = document.getElementById('bp-input-' + f.id); if (el) el.value = f.default; var box = document.getElementById('bp-factor-' + f.id); if (box) box.classList.remove('changed'); });
    refresh();
  }
  document.addEventListener('DOMContentLoaded', function () {
    readUrl(); buildPanel(); portraitFallback();
    FACTORS.forEach(function (f) { var box = document.getElementById('bp-factor-' + f.id); if (box && state[f.id] !== f.default) box.classList.add('changed'); });
    var rb = document.getElementById('bp-reset'); if (rb) rb.addEventListener('click', reset);
    var pb = document.getElementById('bp-print'); if (pb) pb.addEventListener('click', function () { window.print(); });
    refresh();
  });
  window.PhinsBusinessPlan = { apply: apply, refresh: refresh, state: state, fmt: fmt };
})();
"""


def _html_table(header: Sequence[str], rows: Sequence[Sequence[str]], numeric_from: int = 1,
                raw_cells: bool = False) -> str:
    head = "".join(
        f'<th{" class=\"num\"" if i >= numeric_from else ""}>{_html.escape(h)}</th>' for i, h in enumerate(header)
    )
    body = []
    for r in rows:
        cells = []
        for i, c in enumerate(r):
            content = c if raw_cells else _html.escape(str(c))
            cells.append(f'<td{" class=\"num\"" if i >= numeric_from else ""}>{content}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<table class="bp-table"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def render_html(plan: Optional[Mapping[str, Any]] = None) -> str:
    plan = plan or compute_plan()
    f = lambda t: _fill(t, plan, True)  # noqa: E731
    e = _html.escape
    census = plan["technology"]["census"]

    kpis = [
        ("Kernel premium", "{premium}", "age-42 specimen · published tables"),
        ("Seed · pre-money", "{seed} · {pre}", "{dilution} dilution · {post} post"),
        ("Israel in force 2029", "{il_eoy_2}", "{il_eoy_4} by end-2031"),
        ("Markets by 2031", "{markets_2031}", "Israel + OECD partner markets"),
        ("Group PHINS revenue 2031", "{g_rev_4}", "{g_rev_usd_4} at {fx} ILS/USD"),
        ("Group EBITDA margin 2031", "{g_margin_4}", "cumulative {g_cum_4}"),
    ]
    kpi_html = "".join(
        f'<div class="bp-kpi"><div class="bp-kpi-label">{e(label)}</div>'
        f'<div class="bp-kpi-value">{f(val)}</div><div class="bp-kpi-note">{f(note)}</div></div>'
        for label, val, note in kpis
    )

    def founder_photo(cls: str = "") -> str:
        return (f'<div class="bp-founder-photo {cls}"><img src="{FOUNDER_PORTRAIT_URL}" alt="{e(FOUNDER["name"])} — founder portrait" loading="lazy">'
                f'<div class="bp-monogram" aria-hidden="true">{e(FOUNDER["monogram"])}</div></div>')

    founder_html = (
        '<div class="bp-founder">' + founder_photo()
        + f'<div><h3>{e(FOUNDER["name"])}</h3><div class="bp-founder-role">{e(FOUNDER["role"])}</div>'
        + _html_table(["Credential", "Detail"], [[e(t), d] for t, d in founder_rows(plan, True)], numeric_from=99, raw_cells=True)
        + '<ul class="bp-principles">' + "".join(f"<li>{e(p)}</li>" for p in FOUNDER["principles"]) + "</ul></div></div>"
    )

    sections_html: List[str] = []
    for sec in plan_sections():
        parts = [f'<section class="bp-section" id="plan-{sec["id"]}"><h2><span class="secno">{sec["num"]}.</span>{e(sec["title"])}</h2>']
        for p in sec.get("paragraphs", []):
            parts.append(f"<p>{f(p)}</p>")
        if sec.get("founder"):
            parts.append(founder_html)
        if sec.get("table") == "risks":
            parts.append(_html_table(["Risk", "What could go wrong", "Mitigation in the plan"],
                                     [[e(r[0]), f(r[1]), f(r[2])] for r in RISKS], numeric_from=99, raw_cells=True))
        if sec.get("table") == "gates":
            parts.append(_html_table(["When", "Gate"], [[e(g[0]), f(g[1])] for g in GATES], numeric_from=99, raw_cells=True))
        if sec["id"] == "financials":
            for title, table, cols in (("Anchor book — Israel", "anchor_book", ANCHOR_COLUMNS),
                                       ("Partner markets", "partner_markets", PARTNER_COLUMNS),
                                       ("Group", "group", GROUP_COLUMNS)):
                h, b = _year_table(plan, table, cols, True)
                parts.append(f"<h3>{e(title)}</h3>" + _html_table(h, b, raw_cells=True))
        if sec["id"] == "technology":
            parts.append(_html_table(["Census (live)", "Count"], [
                ["Service modules", f'<span data-bp="technology.census.service_modules" data-fmt="int">{census["service_modules"]:,}</span>'],
                ["Service packages", f'<span data-bp="technology.census.service_packages" data-fmt="int">{census["service_packages"]:,}</span>'],
                ["API modules", f'<span data-bp="technology.census.api_modules" data-fmt="int">{census["api_modules"]:,}</span>'],
                ["Repositories", f'<span data-bp="technology.census.repositories" data-fmt="int">{census["repositories"]:,}</span>'],
                ["Security modules", f'<span data-bp="technology.census.security_modules" data-fmt="int">{census["security_modules"]:,}</span>'],
                ["Test files", f'<span data-bp="technology.census.test_files" data-fmt="int">{census["test_files"]:,}</span>'],
            ], raw_cells=True))
        for chart_id in SECTION_CHARTS.get(sec["id"], []):
            parts.append(_html_chart(plan, chart_id))
        parts.append("</section>")
        sections_html.append("".join(parts))

    slides_html = []
    for i, s in enumerate(deck_slides(), 1):
        kicker = f'<div class="bp-kicker">{e(s["kicker"])}</div>' if s.get("kicker") else ""
        bullets = "".join(f"<li>{f(b)}</li>" for b in s["bullets"])
        extra = ""
        if s.get("founder"):
            extra = f'<div class="bp-slide-founder">{founder_photo()}<div><strong>{e(FOUNDER["name"])}</strong><br><span class="bp-status">{e(FOUNDER["role"])}</span></div></div>'
        chart_html = _html_chart(plan, SLIDE_CHARTS[s["title"]]) if s["title"] in SLIDE_CHARTS else ""
        slides_html.append(
            f'<article class="bp-slide"><div class="bp-slide-head"><div class="bp-slide-no">Slide {i:02d}</div>'
            f'<h3>{e(s["title"])}</h3>{kicker}</div><div class="bp-slide-gold"></div>{extra}<ul>{bullets}</ul>{chart_html}</article>'
        )
    n_slides = len(deck_slides())

    sp = plan["specimen"]
    appendix_a = (
        '<section class="bp-section" id="appendix-a"><h2><span class="secno">A.</span>Actuarial basis and pricing kernel</h2>'
        + f"<p>{f('The specimen is priced by the pricing kernel from the published risk_reference_v1 tables: life 0.25 and disability 0.20 per ₪1,000 monthly, times the locked age curve (factor {specimen_age_factor} at age 42). Life face ₪1,000,000; disability sum ₪250,000 below 65 (1:4) and 1:1 from 65. Issue ages 3–65.')}</p>"
        + _html_table(["Specimen line", "Value"], [
            ["Age / age factor", f"{sp['avg_age']} / {sp['age_factor']:.3f}"],
            ["Life sum / disability sum", f"₪{sp['life_sum']:,.0f} / ₪{sp['disability_sum']:,.0f}"],
            ["Life monthly / disability monthly", f"₪{sp['life_monthly']:,.2f} / ₪{sp['disability_monthly']:,.2f}"],
            ["Total monthly / annual", f"₪{sp['total_monthly']:,.2f} / ₪{sp['annual_premium']:,.0f}"],
        ])
        + "<p>Same specimen in every planning market (ILS face, local currency at the planning FX pin — never live FX, never evidence):</p>"
        + _html_table(["Market", "OECD", "Currency", "Planning age", "Kernel premium (ILS)", "Kernel premium (local)"],
                      [[m["name"], m["oecd"], m["currency"], str(m["planning_age"]),
                        f"₪{m['kernel_premium_ils']:,.0f}", f"{m['kernel_premium_local']:,} {m['currency']}"]
                       for m in plan["markets"]], numeric_from=3)
        + "</section>"
    )
    h, b = _year_table(plan, "carrier_view", CARRIER_COLUMNS, True)
    appendix_b = (
        '<section class="bp-section" id="appendix-b"><h2><span class="secno">B.</span>Carrier and reinsurance view (Israel anchor book)</h2>'
        + f"<p>{f('The carrier books 100% of risk GWP, pays the PHINS fee ({take}), expects claims of {loss_ratio} of GWP, cedes {cession} by quota share, receives a {ceding_commission} ceding commission on ceded premium and keeps {carrier_own} of GWP for capital, governance and compliance. Carrier margin in 2029: {carrier_margin_2029}. All five are adjustable factors; the table restates on every change.')}</p>"
        + _html_table(h, b, raw_cells=True)
        + "".join(_html_chart(plan, c) for c in APPENDIX_CHARTS["B"]) + "</section>"
    )
    appendix_c = (
        '<section class="bp-section" id="appendix-c"><h2><span class="secno">C.</span>Regulatory pathway by market</h2>'
        + _html_table(["Market", "OECD status", "Supervisor", "Pathway"],
                      [[m["name"], m["oecd"], m["supervisor"], m["pathway"]] for m in plan["markets"]], numeric_from=99)
        + "</section>"
    )
    appendix_d = (
        '<section class="bp-section" id="appendix-d"><h2><span class="secno">D.</span>Technology architecture and security standard</h2>'
        + "<p>" + f("Live census at render time: {modules} service modules in {packages} packages, {api_modules} API modules, {repositories} repositories, {security_modules} security modules, {test_files} test files. The deployed service layer reports ")
        + f'<span data-live-modules>{census["service_modules"]}</span> modules through <code>/api/platform/facts</code>.</p>'
        + _html_table(["Pillar", "Standard"], [[t["pillar"], t["standard"]] for t in plan["technology"]["standard"]], numeric_from=99)
        + "</section>"
    )
    integrity_rows = [
        [e(INTEGRITY_LABELS.get(k, k)), f'<span data-bp-integrity="{e(k)}">{"yes" if v is True else "NO"}</span>']
        for k, v in plan["integrity"].items()
    ]
    factor_rows = [[e(next(g["label"] for g in FACTOR_GROUPS if g["id"] == fa["group"])), e(fa["label"]),
                    e(_factor_text(fa, fa["default"])), e(_factor_text(fa, fa["min"])), e(_factor_text(fa, fa["max"])),
                    e(fa.get("note") or "")] for fa in FACTORS]
    appendix_e = (
        '<section class="bp-section" id="appendix-e"><h2><span class="secno">E.</span>Data integrity and methodology</h2>'
        + f"<p>Plan identity <code>{e(plan['plan_version'])}</code> · content hash <code data-bp=\"content_hash\" data-fmt=\"text\">{e(plan['content_hash'])}</code>. Identities computed on this render:</p>"
        + _html_table(["Identity", "Holds"], integrity_rows, raw_cells=True)
        + "<p>Factor register — every adjustable assumption, its default and bounds. The panel at the top edits the same register; the API accepts the same ids as query parameters.</p>"
        + _html_table(["Group", "Factor", "Default", "Min", "Max", "Note"], factor_rows, numeric_from=2, raw_cells=True)
        + "<p>Method: in-force follows <code>eoy = round(prior × persistency) + round(new × first-year persistency)</code>, average in force is the mid-point, risk GWP = average in force × premium, PHINS revenue = GWP × take, opex = intensity (ILS per average life, by plan year) × average in force. Partner cohorts follow the same recursion from their launch year at the ramp scale; group = anchor + partners. Funding is derived from the group cash curve. The appraisal is PV(EBITDA 2027–2029) + exit multiple × 2029 net revenue, discounted at WACC, less prudence.</p>"
        + "</section>"
    )
    fu = plan["funding"]
    funding_rows = [
        ["Seed / pre-money / post-money", f("{seed} / {pre} / {post}")],
        ["Seed dilution", f("{dilution}")],
        ["2027 burn (anchor book EBITDA)", f("{burn_2027}")],
        ["Runway on seed at the 2027 burn rate", f'<span data-bp="funding.runway_months_on_seed" data-fmt="months">{e(fmt(fu["runway_months_on_seed"], "months"))}</span>'],
        ["Peak cumulative need (group)", f("{peak_need}")],
        ["Series A indication (need − seed, + buffer)", f("{series_a} ({series_a_buffer} buffer)")],
        ["First EBITDA-positive year (group)", f("{first_positive}")],
        ["Cumulative EBITDA positive (group)", f("{cum_positive}")],
        ["Use of seed — product &amp; technology", f("{uof_tech} ({uof_tech_pct})")],
        ["Use of seed — regulatory, actuarial &amp; reinsurance", f("{uof_reg} ({uof_reg_pct})")],
        ["Use of seed — distribution &amp; local partnerships", f("{uof_dist} ({uof_dist_pct})")],
        ["Use of seed — operations &amp; reserve", f("{uof_ops} ({uof_ops_pct})")],
        ["Actuarial appraisal (anchor book)", f("{appraisal} at {wacc} WACC, {exit_multiple} 2029 net revenue, {prudence} prudence")],
    ]
    fin_tables = []
    for title, table, cols in (("F.1 Anchor book — Israel", "anchor_book", ANCHOR_COLUMNS),
                               ("F.2 Partner markets", "partner_markets", PARTNER_COLUMNS),
                               ("F.3 Group", "group", GROUP_COLUMNS)):
        h, b = _year_table(plan, table, cols, True)
        fin_tables.append(f"<h3>{e(title)}</h3>" + _html_table(h, b, raw_cells=True))
    appendix_f = (
        '<section class="bp-section" id="appendix-f"><h2><span class="secno">F.</span>Financial tables (ILS)</h2>'
        + "".join(fin_tables) + "<h3>F.4 Funding</h3>" + _html_table(["Line", "Value"], funding_rows, raw_cells=True)
        + "<h3>F.5 Charts</h3>" + "".join(_html_chart(plan, c) for c in APPENDIX_CHARTS["F"])
        + "</section>"
    )
    appendix_g = (
        '<section class="bp-section" id="appendix-g"><h2><span class="secno">G.</span>Milestone and governance calendar</h2>'
        + _html_table(["When", "Gate"], [[e(g[0]), f(g[1])] for g in GATES], numeric_from=99, raw_cells=True)
        + "".join(_html_chart(plan, c) for c in APPENDIX_CHARTS["G"]) + "</section>"
    )
    appendix_h = (
        '<section class="bp-section" id="appendix-h"><h2><span class="secno">H.</span>Glossary</h2><dl class="bp-glossary">'
        + "".join(f"<dt>{e(t)}</dt><dd>{e(d)}</dd>" for t, d in GLOSSARY) + "</dl></section>"
    )
    lineage_rows = [[e(r["figure"]), e(r["source"]), e(r["kind"]),
                     '<span class="bp-chip ok">model input</span>' if r["feeds_model"] else '<span class="bp-chip">reference only</span>',
                     e(r["note"])] for r in LINEAGE]
    source_rows = [[e(r["market"]), e(r["title"]), e(f"{r['type']} · {r['strength']}"), e(r["note"]),
                    f'<a class="bp-source-url" href="{e(r["url"])}" target="_blank" rel="noopener">{e(r["url"])}</a>']
                   for r in data_source_rows(plan)]
    appendix_i = (
        '<section class="bp-section" id="appendix-i"><h2><span class="secno">I.</span>Data sources and figure lineage</h2>'
        + "<p>Every class of figure in this document, where it comes from and whether it feeds the model. External research is reference only: the plan counts lives (not market size) from the kernel premium and the persistency identity, so no statistic moves a planning figure and no planning figure rewrites a statistic.</p>"
        + _html_table(["Figure class", "Source", "Kind", "Feeds the model", "Note"], lineage_rows, numeric_from=99, raw_cells=True)
        + "<p>External research registry behind the market section — the same registry the Scenario Lab cites on the pitch dashboard, by planning market:</p>"
        + _html_table(["Market", "Source", "Type · strength", "Used for", "URL"], source_rows, numeric_from=99, raw_cells=True)
        + "</section>"
    )

    factors_json = json.dumps(FACTORS, ensure_ascii=False).replace("</", "<\\/")
    groups_json = json.dumps(FACTOR_GROUPS, ensure_ascii=False).replace("</", "<\\/")

    return f"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{e(DOCUMENT_TITLE)}</title>
<meta name="description" content="PHINS unified business plan, investor deck and appendices — one adjustable-factor identity for investors, carriers, reinsurers and supervisors.">
<!--
  Generated by scripts/build_business_plan.py from services/business_plan_model.py
  ({e(plan['plan_version'])}). Do not edit by hand; regenerate.
  Counterparty-facing document. Marker: ui-clarity.js — keep this token in the
  file so the server-side injector skips the shared assistant widget.
-->
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&amp;family=Space+Grotesk:wght@500;600;700&amp;display=swap" rel="stylesheet">
<style>{_CSS}</style>
</head>
<body>
<header class="bp-topbar">
  <a class="bp-brand" href="#bp-top" aria-label="PHINS">
    <img src="/phins-logo.svg" alt="PHINS emblem">
    <div><div class="bp-wordmark">PHINS</div><div class="bp-tagline">{e(BRAND_TAGLINE)}</div></div>
  </a>
  <nav class="bp-nav" aria-label="Document parts">
    <a href="#part-plan">Business plan</a><a href="#plan-founder">Founder</a><a href="#part-deck">Investor deck</a><a href="#part-appendices">Appendices</a><a href="#appendix-i">Sources</a><a href="#bp-factor-panel">Factors</a>
  </nav>
  <div class="bp-tools">
    <a class="bp-btn" id="bp-json-link" href="/api/business-plan/model">Model JSON</a>
    <a class="bp-btn" href="/investor-docs/phins-unified-business-plan.pdf">PDF edition</a>
    <a class="bp-btn" href="/investor-docs/phins-unified-business-plan.md">Markdown</a>
    <button type="button" class="bp-btn" id="bp-reset">Reset factors</button>
    <button type="button" class="bp-btn gold" id="bp-print">Print / Save PDF</button>
  </div>
</header>

<main class="bp-shell" id="bp-top">
  <div class="phins-letterhead" aria-hidden="true">
    <img src="/phins-logo.svg" alt="PHINS emblem">
    <div><div class="lh-name">PHINS</div><div class="lh-tag">{e(BRAND_TAGLINE)}</div></div>
  </div>
  <section class="bp-banner">
    <div class="bp-eyebrow">Unified business plan · investor deck · appendices</div>
    <h1>AI insurtech platform. One-stop-shop technology. Local OECD partnerships.</h1>
    <p>Life insurance with a lifelong severe-disability mechanism, long-term care, savings flow and a health marketplace — written on licensed carriers' paper, reinsured by quota share, distributed with a local partner in every market, and run end-to-end on one platform.</p>
    <div class="bp-meta">{e(DOCUMENT_EDITION)} · plan identity <code style="color:#f7e2a0">{e(plan['plan_version'])}</code> · hash <code style="color:#f7e2a0" data-bp="content_hash" data-fmt="hash">{e(plan['content_hash'][:16])}</code>… · {e(CONTACT)}</div>
  </section>
  <div class="bp-gold"></div>
  <div class="bp-kpis">{kpi_html}</div>

  <details class="bp-factors" id="bp-factor-panel" open>
    <summary><span>Adjustable factors — one register behind every figure</span>
      <span class="bp-chips"><span class="bp-chip gold" id="bp-canonical">Canonical plan</span><span class="bp-chip ok" id="bp-integrity">Integrity: all identities hold</span></span></summary>
    <div class="bp-factors-body">
      <p class="bp-status">Change any factor and every figure in the plan, the deck and the appendices re-renders from <code>/api/business-plan/model</code>. Defaults are the Investor Meeting book; the URL carries your scenario so it can be shared. Planning assumptions never write public evidence, the ledger or the actuarial store.</p>
      <div id="bp-factor-groups"></div>
      <p class="bp-status" id="bp-errors"></p>
    </div>
  </details>

  <div class="bp-body">
    <div class="bp-part" id="part-plan"><div class="bp-eyebrow">Part I</div><h2>Business plan</h2></div>
    {"".join(sections_html)}

    <div class="bp-part" id="part-deck"><div class="bp-eyebrow">Part II</div><h2>Investor deck</h2>
      <p>{n_slides} slides, same figures. Print this part alone for a meeting; the factor panel above re-tunes it for any investor or scenario.</p></div>
    <div class="bp-deck">{"".join(slides_html)}</div>

    <div class="bp-part" id="part-appendices"><div class="bp-eyebrow">Part III</div><h2>Appendices</h2>
      <p>A — actuarial basis and pricing kernel · B — carrier and reinsurance view · C — regulatory pathway by market · D — technology architecture and security standard · E — data integrity and methodology · F — financial tables and charts · G — milestone and governance calendar (roadmap) · H — glossary · I — data sources and figure lineage.</p></div>
    {appendix_a}{appendix_b}{appendix_c}{appendix_d}{appendix_e}{appendix_f}{appendix_g}{appendix_h}{appendix_i}
  </div>
  <footer class="bp-foot">
    <span>PHINS — Confidential. Prepared for investors, carriers, reinsurers and supervisors. Planning identity; not an offer of securities or insurance.</span>
    <span>{e(CONTACT)} · generated from <code>services/business_plan_model.py</code></span>
  </footer>
</main>

<script type="application/json" id="bp-factors">{factors_json}</script>
<script type="application/json" id="bp-factor-groups-json">{groups_json}</script>
<script>{_JS}</script>
<script src="/platform-facts.js"></script>
<script src="/phins-doc-return.js"></script>
</body>
</html>
"""


__all__ = [
    "APPENDIX_CHARTS",
    "BRAND_TAGLINE",
    "DOCUMENT_TITLE",
    "FIGURES",
    "FOUNDER",
    "FOUNDER_PORTRAIT_URL",
    "GATES",
    "GLOSSARY",
    "INTEGRITY_LABELS",
    "RISKS",
    "SECTION_CHARTS",
    "SLIDE_CHARTS",
    "data_source_rows",
    "deck_slides",
    "founder_rows",
    "figure_ref",
    "fmt",
    "get_path",
    "placeholder_keys",
    "plan_sections",
    "render_html",
    "render_markdown",
    "resolve_figure",
]
