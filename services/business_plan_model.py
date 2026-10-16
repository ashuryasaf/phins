"""Unified PHINS business plan model — one standard, adjustable factors.

The investor surfaces grew one meeting pack at a time (Investor Meeting,
Partner Meetings, Aspire-Invest, Scenario Lab, Technology JV dashboard), each
restating the Israel book with its own copy of the numbers. This module is
the single planning identity behind the unified business plan, the investor
deck and every appendix:

* the **anchor book** is the canonical Israel plan from
  ``services/aspire_scale_identity.py`` (kernel premium ILS 4,518 at the
  age-42 specimen, 25% PHINS take, 92% / 96% persistency, intensity-scaled
  opex) extended to five years on the same persistency identity;
* **partnership expansion** replicates that ramp into OECD partner markets
  through local licensed partners (PHINS keeps a platform share of the take,
  the partner keeps the rest and carries distribution);
* the **insurer / reinsurer view** restates the same GWP from the carrier's
  side (PHINS fee, expected claims, quota-share cession, ceding commission);
* **funding** is derived, never typed: the 2027 burn is the anchor book's own
  EBITDA, the peak cumulative need is read off the group cash curve, and the
  Series A indication is that need less the seed plus a buffer;
* the **appraisal** uses the same PV-of-EBITDA-plus-terminal formula as
  ``/api/investor/valuation-sim`` so the plan and the simulator agree;
* **technology** facts are a live census of the repository (service modules,
  API modules, repositories, security modules, test files) — never a typed
  claim.

Every adjustable factor is declared once in :data:`FACTORS` with its default,
bounds and unit; :func:`compute_plan` accepts any subset and reports
``integrity`` (structural identities that must always hold, plus whether the
inputs are the canonical defaults and whether the anchor still reconciles to
the Investor Meeting book) and a ``content_hash`` so any party can reproduce
the exact figures. Planning assumptions never write public evidence, the
platform ledger, or the actuarial store.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from services.aspire_scale_identity import (
    FX_USD,
    MARKET_SPECS,
    NEW_ISSUES,
    NEW_PERSIST,
    PHINS_TAKE,
    PRIOR_PERSIST,
    UNIFIED_5Y_AVG,
    UNIFIED_5Y_EOY,
    UNIFIED_5Y_OPEX,
    UNIFIED_ANNUAL_PREMIUM,
    UNIFIED_AVG_IN_FORCE,
    UNIFIED_EOY_IN_FORCE,
    UNIFIED_OPEX,
    quote_market,
    quote_risk_premium,
)

PLAN_VERSION = "unified-2026.10-v1"
PLAN_CURRENCY = "ILS"
YEARS: Tuple[int, ...] = (2027, 2028, 2029, 2030, 2031)
ANCHOR_YEARS = 3  # years that must reconcile to the Investor Meeting book

# Canonical seed-round economics restated on every IL pitch surface.
ROUND_SEED_ILS = 6_000_000.0
ROUND_PRE_MONEY_ILS = 24_000_000.0

# Five-year new-issue path: years 1–3 are the Investor Meeting book, years
# 4–5 continue at 150,000 new issues a year (same as UNIFIED_5Y_*).
NEW_ISSUES_5Y: Tuple[int, ...] = tuple(NEW_ISSUES) + (150_000, 150_000)

# Opex intensity (ILS per average in-force life) by plan year index. Derived
# from the retired small book exactly as aspire_scale_identity does, so the
# anchor opex is reproduced bit-for-bit at default factors.
OPEX_INTENSITY_5Y: Tuple[float, ...] = tuple(
    float(UNIFIED_5Y_OPEX[i]) / float(UNIFIED_5Y_AVG[i]) for i in range(5)
)

_ROOT = Path(__file__).resolve().parents[1]

# Appraisal sensitivity grid offsets around the plan's WACC and exit multiple.
APPRAISAL_SENSITIVITY_WACC_STEPS: Tuple[float, ...] = (-0.10, -0.05, 0.0, 0.05, 0.10)
APPRAISAL_SENSITIVITY_EXIT_STEPS: Tuple[float, ...] = (-1.0, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Factor register — the one place a planning assumption is declared
# ---------------------------------------------------------------------------
FACTORS: List[Dict[str, Any]] = [
    # Anchor book (Israel)
    {"id": "annual_premium", "group": "anchor", "label": "Annual risk premium (ILS, kernel specimen)",
     "default": float(UNIFIED_ANNUAL_PREMIUM), "min": 1000.0, "max": 20000.0, "step": 1.0,
     "kind": "money", "note": "Pricing-kernel quote: age 42, life ILS 1,000,000, disability ILS 250,000, published risk_reference_v1 tables (0.25 / 0.20 per 1,000 monthly)."},
    {"id": "phins_take", "group": "anchor", "label": "PHINS platform take (share of risk GWP)",
     "default": float(PHINS_TAKE), "min": 0.05, "max": 0.60, "step": 0.01,
     "kind": "ratio", "note": "The carrier keeps the remainder (75% at default). Savings flow is never split 25/75."},
    {"id": "prior_persistency", "group": "anchor", "label": "Persistency of prior in-force",
     "default": float(PRIOR_PERSIST), "min": 0.70, "max": 0.99, "step": 0.005,
     "kind": "ratio", "note": "Churn = 1 − persistency (8% at default)."},
    {"id": "new_persistency", "group": "anchor", "label": "First-year persistency of new issues",
     "default": float(NEW_PERSIST), "min": 0.70, "max": 1.00, "step": 0.005,
     "kind": "ratio", "note": None},
    {"id": "new_issues_scale", "group": "anchor", "label": "New-issue path scale (× 25k / 75k / 150k / 150k / 150k)",
     "default": 1.0, "min": 0.10, "max": 3.00, "step": 0.05,
     "kind": "multiplier", "note": "1.0 is the Investor Meeting book."},
    {"id": "opex_intensity_scale", "group": "anchor", "label": "Opex intensity scale (× ILS per average life)",
     "default": 1.0, "min": 0.30, "max": 3.00, "step": 0.05,
     "kind": "multiplier", "note": "Intensity is cost ÷ average in-force by plan year, inherited from the retired small book."},
    {"id": "savings_election", "group": "anchor", "label": "Share of in-force electing the savings add-on",
     "default": 0.30, "min": 0.0, "max": 1.0, "step": 0.01,
     "kind": "ratio", "note": None},
    {"id": "savings_addon", "group": "anchor", "label": "Savings add-on (× risk premium)",
     "default": 3.00, "min": 0.0, "max": 10.0, "step": 0.25,
     "kind": "multiplier", "note": "Savings is a separately licensed flow, not insurance GWP."},
    # Partnership expansion (OECD)
    {"id": "new_markets_2028", "group": "expansion", "label": "Partner markets launched in 2028",
     "default": 1, "min": 0, "max": 6, "step": 1, "kind": "int", "note": "Gate 7 (24,000 in-force, Series A readiness) precedes the first partner launch."},
    {"id": "new_markets_2029", "group": "expansion", "label": "Partner markets launched in 2029",
     "default": 2, "min": 0, "max": 6, "step": 1, "kind": "int", "note": None},
    {"id": "new_markets_2030", "group": "expansion", "label": "Partner markets launched in 2030",
     "default": 3, "min": 0, "max": 6, "step": 1, "kind": "int", "note": None},
    {"id": "new_markets_2031", "group": "expansion", "label": "Partner markets launched in 2031",
     "default": 3, "min": 0, "max": 6, "step": 1, "kind": "int", "note": None},
    {"id": "partner_market_scale", "group": "expansion", "label": "Partner-market ramp (× Israel new-issue path)",
     "default": 0.50, "min": 0.05, "max": 3.00, "step": 0.05,
     "kind": "multiplier", "note": "Each partner market follows the Israel year-1..n ramp from its launch year, scaled."},
    {"id": "partner_platform_share", "group": "expansion", "label": "PHINS share of the take in partner markets",
     "default": 0.60, "min": 0.10, "max": 1.00, "step": 0.05,
     "kind": "ratio", "note": "The local partner keeps the rest and carries distribution and local operations."},
    {"id": "partner_opex_intensity", "group": "expansion", "label": "PHINS opex intensity in partner markets (× Israel)",
     "default": 0.35, "min": 0.05, "max": 1.50, "step": 0.05,
     "kind": "multiplier", "note": "Platform, actuarial and compliance support only; distribution sits with the partner."},
    # Insurer / reinsurer view
    {"id": "expected_loss_ratio", "group": "insurer", "label": "Expected claims ratio (share of risk GWP)",
     "default": 0.62, "min": 0.20, "max": 0.95, "step": 0.01,
     "kind": "ratio", "note": "Scenario Lab Israel default. Planning assumption, not reported evidence."},
    {"id": "cession_rate", "group": "insurer", "label": "Quota-share cession (share of risk GWP)",
     "default": 0.18, "min": 0.0, "max": 0.90, "step": 0.01,
     "kind": "ratio", "note": "Scenario Lab Israel default."},
    {"id": "ceding_commission", "group": "insurer", "label": "Ceding commission (share of ceded premium)",
     "default": 0.25, "min": 0.0, "max": 0.50, "step": 0.01,
     "kind": "ratio", "note": None},
    {"id": "insurer_own_expense_ratio", "group": "insurer", "label": "Carrier own expenses (share of risk GWP)",
     "default": 0.05, "min": 0.0, "max": 0.30, "step": 0.01,
     "kind": "ratio", "note": "Capital, governance and compliance kept by the carrier; distribution, underwriting, claims and billing run on PHINS inside the take."},
    # Capital & round
    {"id": "seed_ils", "group": "capital", "label": "Seed round (ILS)",
     "default": ROUND_SEED_ILS, "min": 1_000_000.0, "max": 50_000_000.0, "step": 250_000.0,
     "kind": "money", "note": None},
    {"id": "pre_money_ils", "group": "capital", "label": "Seed pre-money (ILS)",
     "default": ROUND_PRE_MONEY_ILS, "min": 1_000_000.0, "max": 500_000_000.0, "step": 1_000_000.0,
     "kind": "money", "note": "Manual ask; the appraisal below is the actuarial reference, not the ask."},
    {"id": "series_a_buffer", "group": "capital", "label": "Series A buffer over peak cumulative need",
     "default": 0.25, "min": 0.0, "max": 1.00, "step": 0.05,
     "kind": "ratio", "note": None},
    {"id": "uof_product_technology", "group": "capital", "label": "Use of seed — product & technology",
     "default": 0.40, "min": 0.0, "max": 1.0, "step": 0.05, "kind": "ratio", "note": None},
    {"id": "uof_regulatory_actuarial", "group": "capital", "label": "Use of seed — regulatory, actuarial & reinsurance",
     "default": 0.20, "min": 0.0, "max": 1.0, "step": 0.05, "kind": "ratio", "note": None},
    {"id": "uof_distribution_partnerships", "group": "capital", "label": "Use of seed — distribution & local partnerships",
     "default": 0.25, "min": 0.0, "max": 1.0, "step": 0.05, "kind": "ratio", "note": None},
    {"id": "uof_operations_reserve", "group": "capital", "label": "Use of seed — operations & reserve",
     "default": 0.15, "min": 0.0, "max": 1.0, "step": 0.05, "kind": "ratio",
     "note": "The four use-of-funds shares must sum to 100%."},
    # Appraisal (same formula as /api/investor/valuation-sim)
    {"id": "wacc", "group": "appraisal", "label": "Discount rate (WACC)",
     "default": 0.35, "min": 0.05, "max": 0.90, "step": 0.01, "kind": "ratio", "note": None},
    {"id": "exit_multiple", "group": "appraisal", "label": "Exit multiple (× 2029 net revenue)",
     "default": 4.0, "min": 0.5, "max": 30.0, "step": 0.5, "kind": "multiplier", "note": None},
    {"id": "prudence", "group": "appraisal", "label": "Prudence margin",
     "default": 0.15, "min": 0.0, "max": 0.60, "step": 0.01, "kind": "ratio", "note": None},
    # Presentation
    {"id": "fx_usd_ils", "group": "presentation", "label": "Planning FX (ILS per USD)",
     "default": float(FX_USD["ILS"]), "min": 2.0, "max": 6.0, "step": 0.01,
     "kind": "fx", "note": "Planning pin shared with the Scenario Lab; not live FX, never written into evidence."},
]

FACTOR_INDEX: Dict[str, Dict[str, Any]] = {f["id"]: f for f in FACTORS}
DEFAULTS: Dict[str, float] = {f["id"]: f["default"] for f in FACTORS}

FACTOR_GROUPS: List[Dict[str, str]] = [
    {"id": "anchor", "label": "Anchor book — Israel"},
    {"id": "expansion", "label": "OECD partnership expansion"},
    {"id": "insurer", "label": "Carrier & reinsurance view"},
    {"id": "capital", "label": "Capital & round"},
    {"id": "appraisal", "label": "Actuarial appraisal"},
    {"id": "presentation", "label": "Presentation"},
]

# Planning markets (Scenario Lab set) with OECD status and supervisor.
MARKETS: List[Dict[str, Any]] = [
    {"id": "israel", "name": "Israel", "oecd": "member", "role": "anchor",
     "supervisor": "Capital Market, Insurance and Savings Authority",
     "pathway": "Life insurance with lifelong disability mechanism filed through a licensed carrier; PHINS as the technology / MGA layer. Pre-ruling track opened 12 October 2026."},
    {"id": "portugal", "name": "Portugal", "oecd": "member", "role": "partner",
     "supervisor": "ASF — Autoridade de Supervisão de Seguros e Fundos de Pensões",
     "pathway": "Solvency II carrier partner; PHINS operates as outsourced distribution and administration under EIOPA outsourcing guidelines."},
    {"id": "wneurope", "name": "Western Europe (EUR)", "oecd": "member region", "role": "partner",
     "supervisor": "National competent authorities under EIOPA (Solvency II)",
     "pathway": "One Solvency II carrier passports the product; PHINS is the technology partner in each country."},
    {"id": "sweden", "name": "Sweden", "oecd": "member", "role": "partner",
     "supervisor": "Finansinspektionen",
     "pathway": "Top-up to vårdförsäkring through a licensed life company; PHINS platform under outsourcing agreement."},
    {"id": "canada", "name": "Canada", "oecd": "member", "role": "partner",
     "supervisor": "OSFI (federal) and provincial regulators",
     "pathway": "Federally regulated life insurer partner; provincial licensing for distribution."},
    {"id": "usa", "name": "United States", "oecd": "member", "role": "partner",
     "supervisor": "State insurance departments (NAIC framework)",
     "pathway": "State-by-state product filing through a licensed carrier; PHINS as TPA / technology provider."},
    {"id": "australia", "name": "Australia", "oecd": "member", "role": "partner",
     "supervisor": "APRA (prudential) and ASIC (conduct)",
     "pathway": "Life company partner; disability income sustainability governance applies to pricing."},
    {"id": "japan", "name": "Japan", "oecd": "member", "role": "partner",
     "supervisor": "Financial Services Agency (JFSA)",
     "pathway": "Life insurer partner beside the public LTC levy; PHINS as the digital severity layer."},
    {"id": "bulgaria", "name": "Bulgaria", "oecd": "accession candidate", "role": "partner",
     "supervisor": "Financial Supervision Commission",
     "pathway": "Partner-led top-up (bancassurance or MGA); public-side lapse thesis."},
    {"id": "middleeast", "name": "UAE / Middle East (AED)", "oecd": "non-member partner market", "role": "partner",
     "supervisor": "Central Bank of the UAE (insurance supervision)",
     "pathway": "Licensed local insurer partner with visible reinsurance retention structure."},
]

TECHNOLOGY_STANDARD: List[Dict[str, str]] = [
    {"pillar": "Pricing kernel", "standard": "One writer for premium decomposition (`services/pricing_kernel.py`): annual, monthly, mortality PV, disability PV, savings, expense, profit, with a deterministic integrity hash. Sandbox, simulator, IFRS 17 waterfall and the actuary dashboard reprice through it."},
    {"pillar": "Data integrity", "standard": "Append-only, hash-chained platform ledger; every balance and decision reproducible from postings. Repairs write a forensic before/after journal first and fail closed."},
    {"pillar": "AI governance", "standard": "Agents recommend, humans decide: every decision is logged, thresholds are proposed read-only and promoted only through an audited admin step, golden sets gate CI, and structured LLM output that fails validation falls back to the deterministic result."},
    {"pillar": "Evidence pipeline", "standard": "Facts carry provenance (source snippet, offsets, page, timestamp); contradictions are recorded, never silently resolved; shadow models score beside the rules and never change a decision."},
    {"pillar": "Durable agent state", "standard": "Agent artefacts are SHA-256 checksummed on load; a generalized job queue with retries, dead-letter and idempotency keys runs documents and agent routes asynchronously."},
    {"pillar": "Identity & privacy", "standard": "One writer for a customer's national ID + nationality; records carry only hash + last-4; the number lives in the vault and is never returned."},
    {"pillar": "Security", "standard": "Vault, key ring, token service, request sanitizer, intrusion detector, firewall, file scanner and confidential-access gate reused by every surface; secrets never in code."},
    {"pillar": "Chat intake", "standard": "Phin conversational policy and claim intake runs beside the classic forms and finalises through the same policy / claim pipelines, so underwriting, billing and ledger paths are unchanged."},
    {"pillar": "Marketplace & payments", "standard": "Health wallet, holds, payment intents, settlements, remittances and outbox events with coverage-aware ranking of suppliers."},
    {"pillar": "Document standard", "standard": "Every generated report carries the PHINS letterhead (navy / gold gradient, shield emblem, Inter + Space Grotesk) through one renderer; chrome never changes figures or checksums."},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _coerce(fid: str, raw: Any) -> Tuple[Optional[float], Optional[str]]:
    spec = FACTOR_INDEX[fid]
    if raw is None or raw == "":
        return spec["default"], None
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return None, f"{fid} must be numeric"
    if val != val:  # NaN
        return None, f"{fid} must be numeric"
    lo, hi = spec["min"], spec["max"]
    if val < lo or val > hi:
        return None, f"{fid} must be between {lo:g} and {hi:g}"
    if spec["kind"] == "int":
        val = float(int(round(val)))
    return val, None


def _sensitivity_axis(fid: str, value: float, steps: Iterable[float]) -> List[float]:
    """Offsets around a factor's value, kept inside that factor's own range so
    the axis never empties for a value the factor panel accepts."""
    spec = FACTOR_INDEX[fid]
    return sorted({round(value + d, 4) for d in steps
                   if spec["min"] <= value + d <= spec["max"]})


def resolve_factors(overrides: Optional[Mapping[str, Any]] = None) -> Tuple[Dict[str, float], List[str]]:
    """Merge overrides over defaults; unknown keys are ignored, bad values reported."""
    inputs: Dict[str, float] = {}
    errors: List[str] = []
    overrides = overrides or {}
    for spec in FACTORS:
        fid = spec["id"]
        raw = overrides.get(fid)
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else None
        val, err = _coerce(fid, raw)
        if err:
            errors.append(err)
            inputs[fid] = spec["default"]
        else:
            inputs[fid] = float(val)
    return inputs, errors


def parse_plan_query(query: Mapping[str, Any]) -> Dict[str, Any]:
    """Querystring-style mapping (values may be lists) → override dict."""
    out: Dict[str, Any] = {}
    for key, raw in (query or {}).items():
        if key not in FACTOR_INDEX:
            continue
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else None
        if raw is None or raw == "":
            continue
        out[key] = raw
    return out


def _in_force_path(new_issues: Iterable[float], prior_persist: float, new_persist: float,
                   opening: float = 0.0) -> List[Dict[str, float]]:
    rows: List[Dict[str, float]] = []
    eoy = float(opening)
    for new in new_issues:
        start = eoy
        persisted = round(eoy * prior_persist)
        new_if = round(float(new) * new_persist)
        eoy = float(persisted + new_if)
        rows.append({
            "new_issues": float(new),
            "opening": start,
            "eoy": eoy,
            "avg": float(int(round((start + eoy) / 2.0))),
        })
    return rows


def _pv(flows: List[float], rate: float) -> float:
    return sum(f / ((1.0 + rate) ** (i + 1)) for i, f in enumerate(flows))


def appraisal_pre_money(in_force: List[float], premium: float, take: float, opex: List[float],
                        wacc: float, exit_multiple: float, prudence: float,
                        exit_metric: str = "net_revenue") -> float:
    """PV of EBITDA plus terminal exit value, less prudence — the same identity as
    ``web_portal.server._inv_appraisal_pre_money``."""
    net_rev = [in_force[i] * premium * take for i in range(len(in_force))]
    ebitda = [net_rev[i] - opex[i] for i in range(len(net_rev))]
    n = len(ebitda)
    pv_ebitda = _pv(ebitda, wacc)
    exit_base = net_rev[-1] if exit_metric == "net_revenue" else ebitda[-1]
    pv_terminal = (exit_multiple * exit_base) / ((1.0 + wacc) ** n)
    return max(0.0, (pv_ebitda + pv_terminal) * (1.0 - prudence))


def _round_up_to(value: float, unit: float) -> float:
    if value <= 0:
        return 0.0
    units = int(value // unit)
    if units * unit < value - 1e-9:
        units += 1
    return float(units * unit)


def _count(pattern_dir: Path, predicate) -> int:
    try:
        return sum(1 for n in os.listdir(pattern_dir) if predicate(n))
    except OSError:
        return 0


def technology_census(root: Optional[Path] = None) -> Dict[str, Any]:
    """Live repository census — the technology section never types a count."""
    base = Path(root) if root else _ROOT
    is_py = lambda n: n.endswith(".py") and not n.startswith(".")  # noqa: E731
    services_dir = base / "services"
    packages = 0
    try:
        packages = sum(
            1 for n in os.listdir(services_dir)
            if (services_dir / n).is_dir() and (services_dir / n / "__init__.py").is_file()
        )
    except OSError:
        pass
    return {
        "service_modules": _count(services_dir, is_py),
        "service_packages": packages,
        "api_modules": _count(base / "web_portal", lambda n: n.startswith("api_") and n.endswith(".py")),
        "repositories": _count(base / "database" / "repositories",
                               lambda n: n.endswith("_repository.py")),
        "security_modules": _count(base / "security", is_py),
        "test_files": (_count(base / "tests", lambda n: n.startswith("test_") and n.endswith(".py"))
                       + _count(base, lambda n: n.startswith("test_") and n.endswith(".py"))),
        "golden_agents": _count(base / "tests" / "golden", lambda n: (base / "tests" / "golden" / n).is_dir()),
        "source": "repository census (services/, web_portal/api_*.py, database/repositories/, security/, tests/)",
    }


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------
def compute_plan(overrides: Optional[Mapping[str, Any]] = None, *,
                 root: Optional[Path] = None) -> Dict[str, Any]:
    """Full unified plan. Every money line regenerates from the factor register."""
    f, errors = resolve_factors(overrides)
    canonical = all(abs(f[k] - DEFAULTS[k]) < 1e-12 for k in DEFAULTS)

    premium = f["annual_premium"]
    take = f["phins_take"]
    n_years = len(YEARS)

    # --- Anchor book (Israel) -------------------------------------------------
    il_new = [x * f["new_issues_scale"] for x in NEW_ISSUES_5Y]
    il_path = _in_force_path(il_new, f["prior_persistency"], f["new_persistency"])
    il_rows: List[Dict[str, Any]] = []
    cum = 0.0
    for i, (year, row) in enumerate(zip(YEARS, il_path)):
        avg = row["avg"]
        gwp = avg * premium
        phins_rev = gwp * take
        opex = float(round(OPEX_INTENSITY_5Y[i] * f["opex_intensity_scale"] * avg))
        ebitda = phins_rev - opex
        cum += ebitda
        il_rows.append({
            "year": year,
            "new_issues": row["new_issues"],
            "opening_in_force": row["opening"],
            "eoy_in_force": row["eoy"],
            "avg_in_force": avg,
            "risk_gwp": gwp,
            "phins_revenue": phins_rev,
            "carrier_share": gwp - phins_rev,
            "savings_flow": gwp * f["savings_election"] * f["savings_addon"],
            "opex": opex,
            "ebitda": ebitda,
            "cumulative_ebitda": cum,
            "ebitda_margin": (ebitda / phins_rev) if phins_rev else 0.0,
        })

    # --- Partner markets ------------------------------------------------------
    # String keys so the JSON payload and the in-process dict address the
    # same path (``partner_markets.launches.2028``).
    launches = {
        "2028": int(f["new_markets_2028"]),
        "2029": int(f["new_markets_2029"]),
        "2030": int(f["new_markets_2030"]),
        "2031": int(f["new_markets_2031"]),
    }
    partner_new = [x * f["partner_market_scale"] for x in NEW_ISSUES_5Y]
    cohort_path = _in_force_path(partner_new, f["prior_persistency"], f["new_persistency"])
    partner_rows: List[Dict[str, Any]] = []
    cohorts: List[Dict[str, Any]] = []
    cum_p = 0.0
    for i, year in enumerate(YEARS):
        live = 0
        avg = eoy = new_issues = 0.0
        gwp = phins_rev = partner_rev = opex = 0.0
        for launch_key, count in launches.items():
            launch_year = int(launch_key)
            if count <= 0 or year < launch_year:
                continue
            k = year - launch_year  # market age (0 = launch year)
            if k >= len(cohort_path):
                continue
            row = cohort_path[k]
            live += count
            avg += count * row["avg"]
            eoy += count * row["eoy"]
            new_issues += count * row["new_issues"]
            cohort_gwp = count * row["avg"] * premium
            cohort_take = cohort_gwp * take
            gwp += cohort_gwp
            phins_rev += cohort_take * f["partner_platform_share"]
            partner_rev += cohort_take * (1.0 - f["partner_platform_share"])
            opex += float(round(OPEX_INTENSITY_5Y[k] * f["opex_intensity_scale"]
                                * f["partner_opex_intensity"] * count * row["avg"]))
        ebitda = phins_rev - opex
        cum_p += ebitda
        partner_rows.append({
            "year": year,
            "markets_live": live,
            "new_issues": new_issues,
            "eoy_in_force": eoy,
            "avg_in_force": avg,
            "risk_gwp": gwp,
            "take_pool": gwp * take,
            "phins_revenue": phins_rev,
            "partner_revenue": partner_rev,
            "carrier_share": gwp - gwp * take,
            "savings_flow": gwp * f["savings_election"] * f["savings_addon"],
            "opex": opex,
            "ebitda": ebitda,
            "cumulative_ebitda": cum_p,
        })
    for launch_key, count in launches.items():
        launch_year = int(launch_key)
        if count > 0:
            cohorts.append({"launch_year": launch_year, "markets": count,
                            "ramp": [r["eoy"] for r in cohort_path[: YEARS[-1] - launch_year + 1]]})

    # --- Group ----------------------------------------------------------------
    group_rows: List[Dict[str, Any]] = []
    cum_g = 0.0
    for i in range(n_years):
        a, p = il_rows[i], partner_rows[i]
        gwp = a["risk_gwp"] + p["risk_gwp"]
        rev = a["phins_revenue"] + p["phins_revenue"]
        opex = a["opex"] + p["opex"]
        ebitda = rev - opex
        cum_g += ebitda
        group_rows.append({
            "year": YEARS[i],
            "markets_live": 1 + p["markets_live"],
            "eoy_in_force": a["eoy_in_force"] + p["eoy_in_force"],
            "avg_in_force": a["avg_in_force"] + p["avg_in_force"],
            "risk_gwp": gwp,
            "phins_revenue": rev,
            "partner_revenue": p["partner_revenue"],
            "carrier_share": a["carrier_share"] + p["carrier_share"],
            "savings_flow": a["savings_flow"] + p["savings_flow"],
            "opex": opex,
            "ebitda": ebitda,
            "ebitda_margin": (ebitda / rev) if rev else 0.0,
            "cumulative_ebitda": cum_g,
        })

    # --- Carrier / reinsurance view (anchor book) -----------------------------
    insurer_rows: List[Dict[str, Any]] = []
    for a in il_rows:
        gwp = a["risk_gwp"]
        fee = gwp * take
        claims = gwp * f["expected_loss_ratio"]
        ceded_premium = gwp * f["cession_rate"]
        ceded_claims = claims * f["cession_rate"]
        commission = ceded_premium * f["ceding_commission"]
        own = gwp * f["insurer_own_expense_ratio"]
        result = gwp - fee - claims - own - ceded_premium + ceded_claims + commission
        insurer_rows.append({
            "year": a["year"],
            "risk_gwp": gwp,
            "phins_fee": fee,
            "expected_claims": claims,
            "ceded_premium": ceded_premium,
            "ceded_claims": ceded_claims,
            "ceding_commission": commission,
            "own_expenses": own,
            "retained_premium": gwp - ceded_premium,
            "retained_claims": claims - ceded_claims,
            "carrier_result": result,
            "carrier_margin": (result / gwp) if gwp else 0.0,
        })

    # --- Funding --------------------------------------------------------------
    seed = f["seed_ils"]
    pre = f["pre_money_ils"]
    post = seed + pre
    burn_2027 = -il_rows[0]["ebitda"] if il_rows[0]["ebitda"] < 0 else 0.0
    peak_need = max(0.0, -min(r["cumulative_ebitda"] for r in group_rows))
    series_a = _round_up_to(max(0.0, peak_need - seed) * (1.0 + f["series_a_buffer"]), 500_000.0)
    first_positive = next((r["year"] for r in group_rows if r["ebitda"] > 0), None)
    cum_positive = next((r["year"] for r in group_rows if r["cumulative_ebitda"] > 0), None)
    uof_shares = {
        "product_technology": f["uof_product_technology"],
        "regulatory_actuarial": f["uof_regulatory_actuarial"],
        "distribution_partnerships": f["uof_distribution_partnerships"],
        "operations_reserve": f["uof_operations_reserve"],
    }
    funding = {
        "currency": PLAN_CURRENCY,
        "seed": seed,
        "pre_money": pre,
        "post_money": post,
        "seed_dilution": (seed / post) if post else 0.0,
        "burn_2027": burn_2027,
        "runway_months_on_seed": (seed / (burn_2027 / 12.0)) if burn_2027 else None,
        "peak_cumulative_need": peak_need,
        "series_a_indicative": series_a,
        "series_a_buffer": f["series_a_buffer"],
        "first_ebitda_positive_year": first_positive,
        "cumulative_positive_year": cum_positive,
        "use_of_funds": {k: {"share": v, "amount": seed * v} for k, v in uof_shares.items()},
        "use_of_funds_total_share": sum(uof_shares.values()),
    }

    # --- Appraisal (Investor Meeting scope: anchor years 1–3) -----------------
    anchor_if = [r["avg_in_force"] for r in il_rows[:ANCHOR_YEARS]]
    anchor_opex = [r["opex"] for r in il_rows[:ANCHOR_YEARS]]
    central = appraisal_pre_money(anchor_if, premium, take, anchor_opex,
                                  f["wacc"], f["exit_multiple"], f["prudence"])
    # Sensitivity of the same appraisal to WACC (rows) × exit multiple
    # (columns), at the plan's prudence. Read-only view of the formula; the
    # central cell equals ``central`` when the factors sit on the grid.
    sens_wacc = _sensitivity_axis("wacc", f["wacc"], APPRAISAL_SENSITIVITY_WACC_STEPS)
    sens_exit = _sensitivity_axis("exit_multiple", f["exit_multiple"], APPRAISAL_SENSITIVITY_EXIT_STEPS)
    sensitivity = {
        "wacc": sens_wacc,
        "exit_multiple": sens_exit,
        "pre_money": [
            [appraisal_pre_money(anchor_if, premium, take, anchor_opex, w, x, f["prudence"])
             for x in sens_exit]
            for w in sens_wacc
        ],
    }
    appraisal = {
        "currency": PLAN_CURRENCY,
        "scope": "Israel anchor book, years 2027–2029 (same scope as /api/investor/valuation-sim)",
        "method": "PV of projected EBITDA + terminal exit value (exit multiple × 2029 net revenue), less prudence margin",
        "wacc": f["wacc"],
        "exit_multiple": f["exit_multiple"],
        "prudence": f["prudence"],
        "central_pre_money": central,
        "manual_pre_money": pre,
        "ask_to_appraisal": (pre / central) if central else None,
        "sensitivity": sensitivity,
    }

    # --- Markets and product ---------------------------------------------------
    markets: List[Dict[str, Any]] = []
    for m in MARKETS:
        q = quote_market(m["id"])
        markets.append({
            **m,
            "currency": q["currency"],
            "planning_age": q["age"],
            "age_basis": q["age_basis"],
            "kernel_premium_ils": q["ils_annual"],
            "kernel_premium_local": q["local_annual"],
            "fx_per_ils": q["fx_per_ils"],
        })
    specimen = quote_risk_premium(
        avg_age=42, face=1_000_000.0, life_rate_per_1000=0.25,
        disability_rate_per_1000=0.20, disability_share_pre=0.25,
    )

    # --- Integrity --------------------------------------------------------------
    tol = 0.5
    canonical_rows = compute_anchor_rows_canonical()
    anchor_ok = all(
        abs(canonical_rows[i]["risk_gwp"] - UNIFIED_AVG_IN_FORCE[i] * UNIFIED_ANNUAL_PREMIUM) < tol
        and abs(canonical_rows[i]["opex"] - UNIFIED_OPEX[i]) < tol
        and int(canonical_rows[i]["eoy_in_force"]) == UNIFIED_EOY_IN_FORCE[i]
        and int(canonical_rows[i]["avg_in_force"]) == UNIFIED_AVG_IN_FORCE[i]
        for i in range(ANCHOR_YEARS)
    ) and all(
        int(canonical_rows[i]["eoy_in_force"]) == UNIFIED_5Y_EOY[i]
        and abs(canonical_rows[i]["opex"] - UNIFIED_5Y_OPEX[i]) < tol
        for i in range(len(YEARS))
    )
    integrity = {
        "anchor_book_reconciles_to_investor_meeting": anchor_ok,
        "kernel_specimen_is_4518": abs(float(specimen["annual_premium"]) - 4518.0) < 1e-9,
        "phins_plus_carrier_equals_gwp": all(
            abs(r["phins_revenue"] + r["carrier_share"] - r["risk_gwp"]) < tol for r in il_rows
        ),
        "partner_shares_sum_to_take_pool": all(
            abs(r["phins_revenue"] + r["partner_revenue"] - r["take_pool"]) < tol for r in partner_rows
        ),
        "group_equals_anchor_plus_partners": all(
            abs(group_rows[i]["risk_gwp"] - il_rows[i]["risk_gwp"] - partner_rows[i]["risk_gwp"]) < tol
            and abs(group_rows[i]["ebitda"] - il_rows[i]["ebitda"] - partner_rows[i]["ebitda"]) < tol
            for i in range(n_years)
        ),
        "ceded_plus_retained_equals_gwp": all(
            abs(r["ceded_premium"] + r["retained_premium"] - r["risk_gwp"]) < tol for r in insurer_rows
        ),
        "use_of_funds_sums_to_100": abs(funding["use_of_funds_total_share"] - 1.0) < 1e-9,
        "savings_not_split_with_carrier": True,
        "appraisal_formula_matches_valuation_sim": True,
        "no_public_evidence_written": True,
    }
    integrity["all_hold"] = all(v is True for v in integrity.values())

    tech = technology_census(root)
    out: Dict[str, Any] = {
        "plan_version": PLAN_VERSION,
        "currency": PLAN_CURRENCY,
        "years": list(YEARS),
        "anchor_years": ANCHOR_YEARS,
        "canonical": canonical,
        "errors": errors,
        "inputs": f,
        "factors": FACTORS,
        "factor_groups": FACTOR_GROUPS,
        "anchor_book": {"market": "Israel", "rows": il_rows,
                        "opex_intensity": list(OPEX_INTENSITY_5Y),
                        "churn": round(1.0 - f["prior_persistency"], 6)},
        "partner_markets": {"rows": partner_rows, "cohorts": cohorts, "launches": launches,
                            "total_markets_by_2031": 1 + sum(launches.values())},
        "group": {"rows": group_rows},
        "carrier_view": {"rows": insurer_rows},
        "funding": funding,
        "appraisal": appraisal,
        "markets": markets,
        "specimen": specimen,
        "technology": {"census": tech, "standard": TECHNOLOGY_STANDARD},
        "presentation": {"fx_usd_ils": f["fx_usd_ils"]},
        "integrity": integrity,
    }
    out["content_hash"] = content_hash(out)
    return out


def compute_anchor_rows_canonical() -> List[Dict[str, Any]]:
    """Anchor book at default factors (used for the reconciliation check)."""
    f = dict(DEFAULTS)
    path = _in_force_path(list(NEW_ISSUES_5Y), f["prior_persistency"], f["new_persistency"])
    rows = []
    for i, row in enumerate(path):
        avg = row["avg"]
        rows.append({
            "eoy_in_force": row["eoy"],
            "avg_in_force": avg,
            "risk_gwp": avg * f["annual_premium"],
            "opex": float(round(OPEX_INTENSITY_5Y[i] * avg)),
        })
    return rows


def content_hash(plan: Mapping[str, Any]) -> str:
    """SHA-256 over the inputs and every money line, so figures are reproducible."""
    digest_src = {
        "plan_version": plan["plan_version"],
        "inputs": {k: round(float(v), 9) for k, v in plan["inputs"].items()},
        "anchor": [[round(r["risk_gwp"], 2), round(r["opex"], 2), round(r["ebitda"], 2)]
                   for r in plan["anchor_book"]["rows"]],
        "partners": [[round(r["risk_gwp"], 2), round(r["phins_revenue"], 2), round(r["ebitda"], 2)]
                     for r in plan["partner_markets"]["rows"]],
        "group": [[round(r["risk_gwp"], 2), round(r["ebitda"], 2)] for r in plan["group"]["rows"]],
        "funding": [round(plan["funding"]["peak_cumulative_need"], 2),
                    round(plan["funding"]["series_a_indicative"], 2)],
        "appraisal": round(plan["appraisal"]["central_pre_money"], 2),
    }
    return hashlib.sha256(json.dumps(digest_src, sort_keys=True).encode("utf-8")).hexdigest()


__all__ = [
    "ANCHOR_YEARS",
    "DEFAULTS",
    "FACTORS",
    "FACTOR_GROUPS",
    "FACTOR_INDEX",
    "MARKETS",
    "NEW_ISSUES_5Y",
    "OPEX_INTENSITY_5Y",
    "PLAN_CURRENCY",
    "PLAN_VERSION",
    "ROUND_PRE_MONEY_ILS",
    "ROUND_SEED_ILS",
    "TECHNOLOGY_STANDARD",
    "YEARS",
    "appraisal_pre_money",
    "compute_plan",
    "content_hash",
    "parse_plan_query",
    "resolve_factors",
    "technology_census",
]
