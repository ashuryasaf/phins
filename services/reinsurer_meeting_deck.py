"""Swiss Re Israel meeting deck — 8 December 2026.

A reinsurer-facing presentation built the way the investor deck is built
(``services/investor_deck_video.py``): one slide list whose bullets are
templates, figures filled from the unified plan at render time, one
15-second scene per paragraph with a short spoken script, presenters from
the shared roster, and a seal that refuses a paragraph the plan cannot fill.

What this deck adds for a reinsurer:

* a reinsurer view derived by identity from the plan's carrier rows —
  ceded premium, ceded claims, ceding commission and the technical result
  (ceded premium − ceded claims − ceding commission) per year and over the
  five years, with the technical margin and break-even claims ratio that
  follow from the expected claims ratio and the ceding commission;
* quota-share scenarios for the Israel pilot computed by the same model
  (``compute_plan`` with the current inputs and a different ``cession_rate``),
  each carrying its own content hash and labelled ``scenario``;
* the group envelope (group risk GWP × cession), labelled arithmetic, not a
  model row.

Every ``{re_*}`` placeholder resolves here; every other placeholder resolves
through the document's own figure registry, so a figure on this deck is the
same figure as on the plan page. The plan, its factors and the media library
are never written by this module. No limit, ticket or price is set.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from services.business_plan_charts import (
    GOLD,
    GOLD_DEEP,
    GREY,
    NAVY,
    chart_by_id,
    render_svg,
)
from services.business_plan_document import _PLACEHOLDER, _fill, fmt
from services.business_plan_model import compute_plan

SCENE_KEY_PREFIX = "re-"
FIGURE_PREFIX = "re_"
DECK_ID = "reinsurer"
SCENE_SECONDS = 15
STORE_NAME = "reinsurer_deck_scenes"
PAGE_PATH = "/reinsurer-deck.html"
PRESENTATION_API = "/api/admin/media/reinsurer-deck/presentation"
LAB_API = "/api/admin/media/reinsurer-deck"

# Quota-share alternatives the pilot conversation can turn on. The plan's own
# cession stays the reference; these are scenarios of the same model.
SCENARIO_CESSIONS: Tuple[float, ...] = (0.30, 0.50)

MEETING: Dict[str, str] = {
    "date": "2026-12-08",
    "date_text": "Tuesday 8 December 2026",
    "counterpart": "Mr. Hillel Damelin",
    "counterpart_role": "Regional CEO, Israel — Swiss Re",
    "organization": "Swiss Re",
    "subject": "Israel pilot and the five-year plan — quota share, options, next steps",
    "phins_side": "Asaf Ashury, Adv. — Founder & CEO, PHINS Technologies",
    "pack": PAGE_PATH,
    "status": "Scheduled",
}

Section = Dict[str, Any]

# Slide title → chart id. ``ceded_line`` is this module's own chart; the rest
# are the plan's charts, drawn by ``business_plan_charts``.
SLIDE_CHARTS: Dict[str, str] = {
    "The pilot in Israel — 2027": "in_force",
    "The ceded line — five years": "ceded_line",
    "Quota-share options for the pilot": "carrier_view",
    "Five-year plan — Israel anchor book": "gwp_split",
    "Five-year plan — the group": "revenue_ebitda",
    "Capital and timeline": "roadmap",
}


def deck_slides() -> List[Section]:
    """The meeting deck. Templates are unfilled; figures are never typed."""
    return [
        {"title": "PHINS × Swiss Re Israel",
         "kicker": "Tuesday 8 December 2026 · Mr. Hillel Damelin, Regional CEO Israel · Israel pilot and the five-year plan",
         "bullets": [
            "One regulated contract family — life with a lifelong ADL-3 disability mechanism, long-term care and a savings flow — carried by a licensed Israeli insurer and reinsured by quota share; PHINS is the technology and the administrator.",
            "A pilot in Israel from 1 January 2027 and a five-year plan to 2031. Every figure in this deck is a default of {plan_version} · hash {hash}…; nothing is typed by hand.",
         ]},
        {"title": "Why a reinsurer, why now", "bullets": [
            "The pre-ruling track with the Capital Market, Insurance and Savings Authority opened on 12 October 2026; carrier and reinsurance term sheets are the Q4 2026 gate before any sale.",
            "Severe disability and long-term care are the protection gap public systems leave open. A quota share on a new, digitally underwritten book is the reinsurer's way into that gap without carrying distribution on its own balance sheet.",
         ]},
        {"title": "The pilot in Israel — 2027", "bullets": [
            "Gate 5 — sales begin on 1 January 2027 on the licensed carrier's paper; Gate 6 — the first 1,000 policies in force with an Appointed Actuary review against the kernel; Gate 7 — {il_eoy_0} policies in force at year end.",
            "Pilot-year risk GWP {il_gwp_0}; ceded premium at the plan's {cession} quota share {cv_ceded_0}; reinsurer technical result {re_result_0} ({re_result_usd_0} at planning FX {fx}).",
         ]},
        {"title": "The contract the reinsurer underwrites", "bullets": [
            "Life {il_face} with a lifelong disability mechanism — 1:4 below 65, 1:1 from 65 — on an objective ADL-3 trigger; published tables 0.25 / 0.20 per ₪1,000 monthly; {premium} a year at the age-42 specimen.",
            "One pricing kernel is the single writer for premium decomposition. Repricing runs through it at every gate, and the carrier view is restated on every plan refresh, so the reinsurer reads the same rows as the carrier and the Appointed Actuary.",
         ]},
        {"title": "The ceded line — five years", "bullets": [
            "Ceded premium {cv_ceded_0} → {cv_ceded_2} → {cv_ceded_4} (2027 / 2029 / 2031); five-year ceded premium {re_ceded_5y} ({re_ceded_5y_usd}).",
            "Reinsurer technical result {re_result_0} → {re_result_2} → {re_result_4}; five years {re_result_5y} ({re_result_5y_usd}) — {re_margin} of ceded premium at the plan's {loss_ratio} expected claims and {ceding_commission} ceding commission; break-even claims ratio {re_breakeven}.",
         ]},
        {"title": "Quota-share options for the pilot", "bullets": [
            "The plan: {cession} cession, {ceding_commission} ceding commission, carrier margin {cv_margin_0}; the reinsurer's five-year technical result {re_result_5y}.",
            "Scenarios from the same model — at {re_qs30_label} cession the five-year ceded premium is {re_qs30_ceded_5y}, the technical result {re_qs30_result_5y} and the carrier margin {re_qs30_carrier_margin}; at {re_qs50_label} cession {re_qs50_ceded_5y}, {re_qs50_result_5y} and {re_qs50_carrier_margin}. PHINS revenue and EBITDA are unchanged in every scenario; the split between carrier and reinsurer is what moves.",
         ]},
        {"title": "Five-year plan — Israel anchor book", "bullets": [
            "Policies in force {il_eoy_0} → {il_eoy_1} → {il_eoy_2} → {il_eoy_3} → {il_eoy_4}; risk GWP {il_gwp_0} → {il_gwp_4}; five-year risk GWP {re_gwp_5y}.",
            "The savings flow — {il_savings_2} in 2029, {il_savings_4} in 2031 — is a separate licensed flow and is never split with the carrier or the reinsurer. The benefit is a lump sum with a fixed sum at risk, not a lifetime care annuity.",
         ]},
        {"title": "Five-year plan — the group", "bullets": [
            "OECD partner markets under local licensed carriers: {pm_live_1} in 2028, {pm_live_2} in 2029, {pm_live_4} by 2031 — {markets_2031} markets on one platform, {g_eoy_4} group lives and {g_gwp_4} group risk GWP.",
            "A reinsurer that leads Israel can follow the same wording into each market. Group risk GWP × {cession} is {re_group_envelope_4} in 2031 ({re_group_envelope_4_usd}) — arithmetic on the group GWP row, not a model row.",
         ]},
        {"title": "What PHINS asks of Swiss Re Israel", "bullets": [
            "Lead quota-share reinsurer for the Israel pilot: a non-binding indication on the plan's {cession} / {ceding_commission} structure by the Q4 2026 gate, and a technical review of the pricing kernel and the published tables under NDA.",
            "Beyond capacity, every option stays on the table — lead reinsurer and technical partner for the first partner market in 2028, a data-access arrangement on the evidence pipeline, or an equity conversation kept separate from the treaty. Never a linked price.",
         ]},
        {"title": "What Swiss Re sees — governance and data", "bullets": [
            "Agents recommend, humans decide. Every underwriting and claims recommendation is logged with evidence provenance; thresholds move only through an audited promotion step; a contradiction between documents is recorded, never resolved by a bot.",
            "One hash-chained ledger, one identity writer, checksummed agent state. The reinsurer's bordereaux read from the same rows the carrier and the Appointed Actuary read.",
         ]},
        {"title": "Capital and timeline", "bullets": [
            "Seed {seed} on {pre} pre-money ({post} post); Series A {series_a} indicative in 2028; group EBITDA positive in {first_positive}. The reinsurer's capacity carries the book; it does not fund PHINS.",
            "12 October 2026 pre-ruling · Q4 2026 seed close and term sheets · 1 January 2027 sales begin · Q4 2027 Gate 7 · 2028 first partner market · 2031 {markets_2031} markets.",
         ]},
        {"title": "Next steps after 8 December", "bullets": [
            "Proposed: within two weeks, NDA, data room and a kernel walkthrough with the Appointed Actuary; within six weeks, a non-binding indication on the quota share; before Gate 5, a signed term sheet with the carrier of record named.",
            "Nothing is bound today. No limit, ticket or price is set in this deck; every figure regenerates from {plan_version}, and the plan is not written by this meeting.",
         ]},
    ]


# ---------------------------------------------------------------------------
# Reinsurer view — derived by identity from the plan's carrier rows
# ---------------------------------------------------------------------------
def _scenario_key(cession: float) -> str:
    return f"qs{int(round(cession * 100)):02d}"


def reinsurer_view(plan: Mapping[str, Any]) -> Dict[str, Any]:
    """Ceded line, totals, margins, group envelope and quota-share scenarios.

    Nothing here is a new assumption: every number is an identity on rows the
    plan already carries, or the same model run with a different cession.
    """
    inputs = plan["inputs"]
    fx = float(plan["presentation"]["fx_usd_ils"])
    cession = float(inputs["cession_rate"])
    loss_ratio = float(inputs["expected_loss_ratio"])
    commission_rate = float(inputs["ceding_commission"])
    carrier_rows = list(plan["carrier_view"]["rows"])
    group_rows = list(plan["group"]["rows"])
    anchor_rows = list(plan["anchor_book"]["rows"])

    rows: List[Dict[str, Any]] = []
    for carrier, group, anchor in zip(carrier_rows, group_rows, anchor_rows):
        ceded_premium = float(carrier["ceded_premium"])
        ceded_claims = float(carrier["ceded_claims"])
        commission = float(carrier["ceding_commission"])
        rows.append({
            "year": int(carrier["year"]),
            "risk_gwp": float(carrier["risk_gwp"]),
            "ceded_premium": ceded_premium,
            "ceded_claims": ceded_claims,
            "ceding_commission": commission,
            "technical_result": ceded_premium - ceded_claims - commission,
            "carrier_result": float(carrier["carrier_result"]),
            "carrier_margin": float(carrier["carrier_margin"]),
            "savings_flow": float(anchor["savings_flow"]),
            "group_risk_gwp": float(group["risk_gwp"]),
            "group_envelope": float(group["risk_gwp"]) * cession,
        })

    def _total(field: str) -> float:
        return float(sum(row[field] for row in rows))

    totals = {
        "risk_gwp": _total("risk_gwp"),
        "ceded_premium": _total("ceded_premium"),
        "ceded_claims": _total("ceded_claims"),
        "ceding_commission": _total("ceding_commission"),
        "technical_result": _total("technical_result"),
        "savings_flow": _total("savings_flow"),
    }

    scenarios: List[Dict[str, Any]] = []
    for alt in SCENARIO_CESSIONS:
        overrides = dict(inputs)
        overrides["cession_rate"] = alt
        alt_plan = compute_plan(overrides)
        alt_rows = alt_plan["carrier_view"]["rows"]
        ceded_5y = float(sum(r["ceded_premium"] for r in alt_rows))
        result_5y = float(sum(
            r["ceded_premium"] - r["ceded_claims"] - r["ceding_commission"] for r in alt_rows
        ))
        scenarios.append({
            "key": _scenario_key(alt),
            "cession_rate": alt,
            "ceded_premium_2027": float(alt_rows[0]["ceded_premium"]),
            "technical_result_2027": float(
                alt_rows[0]["ceded_premium"] - alt_rows[0]["ceded_claims"] - alt_rows[0]["ceding_commission"]
            ),
            "ceded_premium_5y": ceded_5y,
            "technical_result_5y": result_5y,
            "carrier_margin": float(alt_rows[0]["carrier_margin"]),
            "phins_revenue_5y": float(sum(r["phins_revenue"] for r in alt_plan["group"]["rows"])),
            "group_ebitda_5y": float(sum(r["ebitda"] for r in alt_plan["group"]["rows"])),
            "content_hash": str(alt_plan.get("content_hash") or ""),
            "canonical": bool(alt_plan.get("canonical")),
            "integrity_all_hold": (alt_plan.get("integrity") or {}).get("all_hold") is True,
        })

    return {
        "fx_usd_ils": fx,
        "cession_rate": cession,
        "expected_loss_ratio": loss_ratio,
        "ceding_commission": commission_rate,
        # Technical margin on ceded premium and the claims ratio at which the
        # reinsurer's result is zero, both identities on the two ratios.
        "technical_margin": 1.0 - loss_ratio - commission_rate,
        "breakeven_claims_ratio": 1.0 - commission_rate,
        "rows": rows,
        "totals": totals,
        "scenarios": scenarios,
        "phins_revenue_5y": float(sum(r["phins_revenue"] for r in group_rows)),
        "group_ebitda_5y": float(sum(r["ebitda"] for r in group_rows)),
    }


def reinsurer_figures(plan: Mapping[str, Any]) -> Dict[str, Tuple[Any, str]]:
    """``{re_*}`` placeholder → (value, format kind)."""
    view = reinsurer_view(plan)
    figures: Dict[str, Tuple[Any, str]] = {
        "re_margin": (view["technical_margin"], "pct"),
        "re_breakeven": (view["breakeven_claims_ratio"], "pct"),
        "re_gwp_5y": (view["totals"]["risk_gwp"], "ilsm"),
        "re_ceded_5y": (view["totals"]["ceded_premium"], "ilsm"),
        "re_ceded_5y_usd": (view["totals"]["ceded_premium"], "usdm"),
        "re_ceded_claims_5y": (view["totals"]["ceded_claims"], "ilsm"),
        "re_commission_5y": (view["totals"]["ceding_commission"], "ilsm"),
        "re_result_5y": (view["totals"]["technical_result"], "ilsm"),
        "re_result_5y_usd": (view["totals"]["technical_result"], "usdm"),
        "re_savings_5y": (view["totals"]["savings_flow"], "ilsm"),
    }
    for index, row in enumerate(view["rows"]):
        figures[f"re_result_{index}"] = (row["technical_result"], "ilsm")
        figures[f"re_result_usd_{index}"] = (row["technical_result"], "usdm")
        figures[f"re_group_envelope_{index}"] = (row["group_envelope"], "ilsm")
        figures[f"re_group_envelope_{index}_usd"] = (row["group_envelope"], "usdm")
    for scenario in view["scenarios"]:
        key = scenario["key"]
        figures[f"re_{key}_label"] = (scenario["cession_rate"], "pct")
        figures[f"re_{key}_ceded_0"] = (scenario["ceded_premium_2027"], "ilsm")
        figures[f"re_{key}_result_0"] = (scenario["technical_result_2027"], "ilsm")
        figures[f"re_{key}_ceded_5y"] = (scenario["ceded_premium_5y"], "ilsm")
        figures[f"re_{key}_result_5y"] = (scenario["technical_result_5y"], "ilsm")
        figures[f"re_{key}_carrier_margin"] = (scenario["carrier_margin"], "pct1")
        figures[f"re_{key}_hash"] = (scenario["content_hash"], "hash")
    return figures


_RE_PLACEHOLDER = re.compile(r"\{(re_[a-z_0-9]+)\}")


def fill_reinsurer_figures(text: str, plan: Mapping[str, Any]) -> str:
    """Substitute the ``{re_*}`` keys. Unknown ``re_`` keys stay as written."""
    if FIGURE_PREFIX not in text:
        return text
    figures = reinsurer_figures(plan)
    fx = float(plan["presentation"]["fx_usd_ils"])

    def repl(match: "re.Match[str]") -> str:
        key = match.group(1)
        if key not in figures:
            return match.group(0)
        value, kind = figures[key]
        return fmt(value, kind, fx)

    return _RE_PLACEHOLDER.sub(repl, text)


def fill(text: str, plan: Mapping[str, Any]) -> str:
    """Reinsurer keys first, then the document's own registry."""
    return _fill(fill_reinsurer_figures(str(text or ""), plan), plan, False).strip()


def placeholder_keys() -> List[str]:
    keys: set = set()
    for slide in deck_slides():
        keys.update(_PLACEHOLDER.findall(str(slide.get("kicker") or "")))
        for bullet in slide["bullets"]:
            keys.update(_PLACEHOLDER.findall(bullet))
    keys.discard("il_face")
    return sorted(keys)


# ---------------------------------------------------------------------------
# Scene catalog — one row per paragraph, keys ``re-sNNpNN``
# ---------------------------------------------------------------------------
def scene_storage_key(slide_no: int, paragraph_no: int) -> str:
    return f"{SCENE_KEY_PREFIX}s{int(slide_no):02d}p{int(paragraph_no):02d}"


def is_reinsurer_scene_key(key: Any) -> bool:
    return str(key or "").startswith(SCENE_KEY_PREFIX)


def catalog() -> List[Dict[str, Any]]:
    """One row per deck bullet; the shape the investor-deck machinery reads."""
    from services.investor_deck_video import campaign_id_for

    rows: List[Dict[str, Any]] = []
    for slide_no, slide in enumerate(deck_slides(), 1):
        title = str(slide.get("title") or "")
        bullets = list(slide.get("bullets") or [])
        chart_id = str(SLIDE_CHARTS.get(title) or "")
        for paragraph_no, template in enumerate(bullets, 1):
            key = scene_storage_key(slide_no, paragraph_no)
            rows.append({
                "scene_key": key,
                "deck": DECK_ID,
                "lang": "en",
                "slide_no": slide_no,
                "paragraph_no": paragraph_no,
                "paragraph_count": len(bullets),
                "slide_title": title,
                "kicker": str(slide.get("kicker") or ""),
                "template": str(template),
                "chart_id": chart_id,
                "photo": "",
                "campaign_id": campaign_id_for(key),
                "duration_seconds": SCENE_SECONDS,
            })
    return rows


def spec_for(key: str) -> Optional[Dict[str, Any]]:
    wanted = str(key or "").strip()
    if not is_reinsurer_scene_key(wanted):
        return None
    for row in catalog():
        if row["scene_key"] == wanted:
            return dict(row)
    return None


def chart_ids() -> List[str]:
    seen: List[str] = []
    for spec in catalog():
        chart_id = spec.get("chart_id") or ""
        if chart_id and chart_id not in seen:
            seen.append(chart_id)
    return seen


def slide_specs() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: Dict[int, Dict[str, Any]] = {}
    for scene in catalog():
        number = int(scene["slide_no"])
        row = seen.get(number)
        if row is None:
            row = {
                "slide_no": number,
                "title": str(scene.get("slide_title") or ""),
                "kicker": str(scene.get("kicker") or ""),
                "bullets": [],
                "chart_id": str(scene.get("chart_id") or ""),
                "photo": "",
                "lang": "en",
            }
            seen[number] = row
            rows.append(row)
        row["bullets"].append(str(scene.get("template") or ""))
    return rows


# ---------------------------------------------------------------------------
# Charts — the plan's own, plus the ceded line
# ---------------------------------------------------------------------------
def ceded_line_chart(plan: Mapping[str, Any]) -> Dict[str, Any]:
    view = reinsurer_view(plan)
    years = [str(row["year"]) for row in view["rows"]]
    return {
        "id": "ceded_line", "kind": "grouped_bars", "unit": "ilsm",
        "title": "The ceded line — Israel anchor book (ILS)",
        "subtitle": (
            f"Quota share {fmt(view['cession_rate'], 'pct')} · expected claims "
            f"{fmt(view['expected_loss_ratio'], 'pct')} · ceding commission "
            f"{fmt(view['ceding_commission'], 'pct')}; technical result = ceded premium − ceded claims − ceding commission."
        ),
        "categories": years,
        "series": [
            {"label": "Ceded premium", "color": NAVY, "values": [r["ceded_premium"] for r in view["rows"]]},
            {"label": "Ceded claims", "color": GREY, "values": [r["ceded_claims"] for r in view["rows"]]},
            {"label": "Ceding commission", "color": GOLD_DEEP, "values": [r["ceding_commission"] for r in view["rows"]]},
            {"label": "Technical result", "color": GOLD, "values": [r["technical_result"] for r in view["rows"]]},
        ],
        "source": "carrier_view.rows[].ceded_premium, ceded_claims, ceding_commission (identity)",
    }


def chart_spec(plan: Mapping[str, Any], chart_id: str) -> Dict[str, Any]:
    if chart_id == "ceded_line":
        return ceded_line_chart(plan)
    return chart_by_id(plan, chart_id)


def charts(plan: Mapping[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for chart_id in chart_ids():
        spec = chart_spec(plan, chart_id)
        out[chart_id] = {"id": chart_id, "title": str(spec.get("title") or ""), "svg": render_svg(spec)}
    return out


# ---------------------------------------------------------------------------
# Presentation — slides filled here and nowhere written back
# ---------------------------------------------------------------------------
def _scripts_for_slide(slide_no: int, scenes: Optional[Sequence[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in scenes or []:
        if not isinstance(item, Mapping):
            continue
        try:
            number = int(item.get("slide_no") or 0)
        except (TypeError, ValueError):
            continue
        if number != slide_no:
            continue
        rows.append({
            "scene_key": str(item.get("scene_key") or ""),
            "paragraph_no": int(item.get("paragraph_no") or 0),
            "spoken": str(item.get("script") or ""),
            "on_slide": str(item.get("narration") or ""),
            "presenter_label": str(item.get("presenter_label") or ""),
            "duration_seconds": SCENE_SECONDS,
            "in_stream": bool(item.get("in_stream")),
            "playback_url": str(item.get("playback_url") or "") if item.get("in_stream") else "",
            "figures_current": bool(item.get("figures_current")),
            "stored": bool(item.get("stored")),
        })
    rows.sort(key=lambda row: row["paragraph_no"])
    return rows


def presentation_of(
    plan: Mapping[str, Any],
    scenes: Optional[Sequence[Mapping[str, Any]]] = None,
    *,
    chart_svgs: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """The deck as slides, with the film script for each slide."""
    from services.investor_deck_video import _chart_svg, _filmed_for_slide

    slides: List[Dict[str, Any]] = []
    for spec in slide_specs():
        number = int(spec["slide_no"])
        chart_id = str(spec.get("chart_id") or "")
        slides.append({
            "slide_no": number,
            "title": str(spec.get("title") or ""),
            "kicker": fill(str(spec.get("kicker") or ""), plan),
            "bullets": [fill(bullet, plan) for bullet in spec.get("bullets") or []],
            "chart_id": chart_id,
            "chart_svg": _chart_svg(chart_svgs, chart_id),
            "photo": "",
            "photo_url": "",
            "media": {"asset_id": "", "playback_url": "", "name": "", "intact": False, "withheld": False},
            "filmed": _filmed_for_slide(number, scenes),
            "script": _scripts_for_slide(number, scenes),
        })
    view = reinsurer_view(plan)
    # The film is at most one 15-second scene per catalogued paragraph; the
    # stream plays only the scenes that are filmed and still current.
    scene_total = len(catalog())
    return {
        "deck": DECK_ID,
        "part": "Swiss Re Israel · 8 December 2026",
        "lang": "en",
        "meeting": dict(MEETING),
        "slide_count": len(slides),
        "scene_count": scene_total,
        "film_seconds_max": SCENE_SECONDS * scene_total,
        "filmed_count": sum(1 for slide in slides for row in slide["script"] if row["in_stream"]),
        "slides": slides,
        "reinsurer_view": view,
        "watermark": {"images": [], "intact": False, "withheld": False},
    }


# ---------------------------------------------------------------------------
# Markdown edition — the meeting pack, generated, never hand-edited
# ---------------------------------------------------------------------------
def _md_table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_markdown(plan: Mapping[str, Any], scenes: Optional[Sequence[Mapping[str, Any]]] = None) -> str:
    """Slides, spoken scripts, the ceded line and the scenarios as one brief."""
    from services.investor_deck_video import short_script

    view = reinsurer_view(plan)
    fx = view["fx_usd_ils"]
    money = lambda value: fmt(value, "ilsm", fx)  # noqa: E731
    usd = lambda value: fmt(value, "usdm", fx)  # noqa: E731
    pct = lambda value: fmt(value, "pct", fx)  # noqa: E731
    plan_version = str(plan.get("plan_version") or "")
    content_hash = str(plan.get("content_hash") or "")
    canonical = fmt(plan.get("canonical"), "canonical")

    out: List[str] = []
    out.append("# PHINS × Swiss Re Israel — Meeting Deck and Film Script (8 December 2026)")
    out.append("")
    out.append(
        "> **Internal · Confidential.** The presentation for the meeting with "
        f"{MEETING['counterpart']}, {MEETING['counterpart_role']}, on {MEETING['date_text']}: "
        "the Israel pilot from 1 January 2027 and the five-year plan to 2031, read from the "
        "reinsurer's seat. Every figure is a default of plan identity `"
        f"{plan_version}` ({canonical}; content hash `{content_hash[:16]}…`) and regenerates "
        "from the same model as the unified business plan. Nothing is bound by this deck; no "
        "limit, ticket or price is set. The plan is not written by this meeting."
    )
    out.append("")
    out.append("## Meeting facts")
    out.append("")
    out.append(_md_table(
        ["Item", "Detail"],
        [
            ["Date", MEETING["date_text"]],
            ["Counterpart", f"{MEETING['counterpart']} — {MEETING['counterpart_role']}"],
            ["PHINS", MEETING["phins_side"]],
            ["Subject", MEETING["subject"]],
            ["Format", f"{len(slide_specs())} slides · one 15-second scene per paragraph · short film plays the filmed scenes in order"],
            ["Pack", f"`{PAGE_PATH}` (presentation + script sheet) · pitch dashboard — Swiss Re Israel 8.12 section · Group CEO assessment (7 Nov) · unified business plan Appendix B"],
            ["Status", MEETING["status"]],
        ],
    ))
    out.append("")
    out.append("## The ceded line the reinsurer sees — Israel anchor book, default factors")
    out.append("")
    out.append(
        f"Quota share {pct(view['cession_rate'])} · expected claims {pct(view['expected_loss_ratio'])} · "
        f"ceding commission {pct(view['ceding_commission'])}. Technical result = ceded premium − ceded claims − "
        f"ceding commission = {pct(view['technical_margin'])} of ceded premium; break-even claims ratio "
        f"{pct(view['breakeven_claims_ratio'])}."
    )
    out.append("")
    rows = [
        [str(r["year"]), money(r["risk_gwp"]), money(r["ceded_premium"]), money(r["ceded_claims"]),
         money(r["ceding_commission"]), money(r["technical_result"]), usd(r["technical_result"])]
        for r in view["rows"]
    ]
    totals = view["totals"]
    rows.append([
        "Five years", money(totals["risk_gwp"]), money(totals["ceded_premium"]), money(totals["ceded_claims"]),
        money(totals["ceding_commission"]), money(totals["technical_result"]), usd(totals["technical_result"]),
    ])
    out.append(_md_table(
        ["Year", "Risk GWP", "Ceded premium", "Ceded claims", "Ceding commission", "Technical result", "Result (USD, planning FX)"],
        rows,
    ))
    out.append("")
    out.append("## Quota-share options for the pilot — scenarios of the same model")
    out.append("")
    out.append(
        "The plan's cession is the reference. Each alternative is `compute_plan` with the current inputs and a "
        "different `cession_rate`; it carries its own content hash and is labelled a scenario. PHINS revenue and "
        "EBITDA do not move with the cession; the carrier's result does."
    )
    out.append("")
    scenario_rows = [[
        f"{pct(view['cession_rate'])} (plan)", money(view['rows'][0]['ceded_premium']),
        money(view['rows'][0]['technical_result']), money(totals['ceded_premium']), money(totals['technical_result']),
        fmt(view['rows'][0]['carrier_margin'], 'pct1'), money(view['phins_revenue_5y']), f"`{content_hash[:12]}` · {canonical}",
    ]]
    for scenario in view["scenarios"]:
        scenario_rows.append([
            pct(scenario["cession_rate"]), money(scenario["ceded_premium_2027"]), money(scenario["technical_result_2027"]),
            money(scenario["ceded_premium_5y"]), money(scenario["technical_result_5y"]),
            fmt(scenario["carrier_margin"], "pct1"), money(scenario["phins_revenue_5y"]),
            f"`{scenario['content_hash'][:12]}` · {fmt(scenario['canonical'], 'canonical')}",
        ])
    out.append(_md_table(
        ["Cession", "Ceded premium 2027", "Technical result 2027", "Ceded premium 5y", "Technical result 5y",
         "Carrier margin", "PHINS revenue 5y", "Plan identity"],
        scenario_rows,
    ))
    out.append("")
    out.append("## Slides and film script")
    out.append("")
    out.append(
        "One 15-second scene per paragraph. A paragraph with no figure is spoken in full; a paragraph that fills a "
        "figure is spoken as a short line and its figures stay on the slide. Presenters come from the shared roster "
        "and are assigned when a scene is filmed; charts are the plan's own and are shown beside the clip, never drawn "
        "by the generator."
    )
    out.append("")
    scene_lookup = {str(s.get("scene_key") or ""): s for s in (scenes or []) if isinstance(s, Mapping)}
    for spec in catalog():
        if spec["paragraph_no"] == 1:
            out.append(f"### Slide {spec['slide_no']:02d} — {spec['slide_title']}")
            out.append("")
            if spec.get("kicker"):
                out.append(f"*{fill(spec['kicker'], plan)}*")
                out.append("")
            if spec.get("chart_id"):
                out.append(f"Chart beside the clip: `{spec['chart_id']}`.")
                out.append("")
        on_slide = fill(spec["template"], plan)
        spoken = short_script(spec, plan)
        filmed = scene_lookup.get(spec["scene_key"], {})
        presenter = str(filmed.get("presenter_label") or "") if filmed else ""
        out.append(f"**Paragraph {spec['paragraph_no']} · scene `{spec['scene_key']}` · {SCENE_SECONDS} s**")
        out.append("")
        out.append(f"- On the slide: {on_slide}")
        out.append(f"- Spoken: {spoken}")
        if presenter:
            out.append(f"- Presenter: {presenter}")
        out.append("")
    out.append("## Data integrity")
    out.append("")
    cession = view["cession_rate"]
    first = view["rows"][0]
    out.append(
        f"Every PHINS figure in this pack is read from plan identity `{plan_version}` (content hash `{content_hash}`). "
        f"The reinsurer line is an identity on the plan's carrier rows: 2027 ceded premium {money(first['risk_gwp'])} × "
        f"{pct(cession)} = {money(first['ceded_premium'])}; ceded claims {money(first['ceded_claims'])}; ceding commission "
        f"{money(first['ceding_commission'])}; technical result {money(first['technical_result'])}. Technical margin "
        f"1 − {pct(view['expected_loss_ratio'])} − {pct(view['ceding_commission'])} = {pct(view['technical_margin'])}; "
        f"break-even 1 − {pct(view['ceding_commission'])} = {pct(view['breakeven_claims_ratio'])}. The group envelope is "
        "group risk GWP × cession, arithmetic on a model row and not a model row. The quota-share scenarios are the same "
        "model with a different cession and are labelled as scenarios with their own hashes. This pack is generated from "
        "the model by `scripts/build_reinsurer_deck_brief.py` and is never hand-edited. It does not write the platform ledger."
    )
    out.append("")
    return "\n".join(out)
