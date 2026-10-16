"""Charts for the unified business plan — one layout engine, two backends.

Every chart is a *spec* built from :func:`compute_plan` output by
:func:`chart_specs` (data only: categories, series, values). :func:`layout`
turns a spec into a list of drawing primitives in a fixed 680 × 320 box, and
two backends draw those same primitives: :func:`render_svg` for the HTML page
(and for the live refresh through ``GET /api/business-plan/model?charts=1``)
and :func:`render_reportlab` for the PDF edition. Because geometry and labels
are computed once, the three editions cannot disagree on a bar height or a
label. :func:`chart_table` exposes each chart's data as a table so the
Markdown edition shows the same numbers the chart draws.

Nothing here reads or writes platform data; the module is presentation over
the planning identity only.
"""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

W, H = 680, 320
PAD_L, PAD_R, PAD_T, PAD_B = 62, 18, 46, 44

NAVY = "#0e2f63"
NAVY_DEEP = "#060d1f"
NAVY_MID = "#123f82"
GOLD = "#c9a04e"
GOLD_STRONG = "#f7e2a0"
GOLD_DEEP = "#b8893b"
INK = "#12284c"
MUTED = "#5b6b82"
LINE = "#d5deea"
ICE = "#f3f7fd"
GREY = "#9aa8bd"
GREEN = "#2f7d4f"
RED = "#b23a48"
WHITE = "#ffffff"

Op = Tuple[Any, ...]


# ---------------------------------------------------------------------------
# Label formatting — same rules as business_plan_document.fmt for these kinds
# ---------------------------------------------------------------------------
def label(value: Any, unit: str) -> str:
    if value is None:
        return "—"
    v = float(value)
    if unit == "ilsm":
        neg = v < 0
        a = abs(v)
        s = f"{a / 1e9:.2f}B" if a >= 1e9 else f"{a / 1e6:.1f}M"
        return ("−" if neg else "") + "₪" + s
    if unit == "ilsm0":
        neg = v < 0
        a = abs(v)
        s = f"{a / 1e9:.2f}B" if a >= 1e9 else f"{a / 1e6:.0f}M"
        return ("−" if neg else "") + "₪" + s
    if unit == "int":
        return f"{int(round(v)):,}"
    if unit == "pct":
        return f"{round(v * 100):d}%"
    if unit == "pct1":
        return f"{v * 100:.1f}%"
    if unit == "x":
        return f"{v:.1f}×" if abs(v - round(v)) < 1e-9 else f"{v:g}×"
    return f"{v:g}"


def _n(v: float) -> str:
    """Deterministic coordinate text (two decimals, no trailing zeros)."""
    s = f"{v:.2f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


# ---------------------------------------------------------------------------
# Specs — data only, built from the plan
# ---------------------------------------------------------------------------
def _rows(plan: Mapping[str, Any], table: str) -> List[Mapping[str, Any]]:
    return list(plan[table]["rows"])


def roadmap_items(plan: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Gantt rows derived from the plan: dated gates, Israel sales clock,
    partner cohorts (one bar per launch cohort) and the derived cash gates.
    Times are decimal years (2027.0 = 1 January 2027)."""
    fu = plan["funding"]
    launches = plan["partner_markets"]["launches"]
    il0 = plan["anchor_book"]["rows"][0]["eoy_in_force"]
    end = float(plan["years"][-1]) + 1.0
    items: List[Dict[str, Any]] = [
        {"label": "Regulatory pre-ruling → filing (Israel)", "start": 2026.78, "end": 2027.5, "kind": "bar", "group": "Regulation"},
        {"label": "Seed round " + label(fu["seed"], "ilsm0") + " on " + label(fu["pre_money"], "ilsm0") + " pre", "start": 2026.75, "end": 2027.0, "kind": "bar", "group": "Capital"},
        {"label": "Israel sales on the carrier's paper", "start": 2027.0, "end": end, "kind": "bar", "group": "Israel"},
        {"label": "Gate 6 — first 1,000 policies", "start": 2027.5, "end": 2027.5, "kind": "milestone", "group": "Israel"},
        {"label": f"Gate 7 — {label(il0, 'int')} in force · Series A readiness", "start": 2028.0, "end": 2028.0, "kind": "milestone", "group": "Israel"},
    ]
    if fu["series_a_indicative"] > 0:
        items.append({"label": "Series A " + label(fu["series_a_indicative"], "ilsm") + " (indicative)",
                      "start": 2028.0, "end": 2028.5, "kind": "bar", "group": "Capital"})
    for key in sorted(launches):
        count = int(launches[key])
        if count <= 0:
            continue
        year = int(key)
        items.append({"label": f"Partner cohort {year} — {count} market{'s' if count != 1 else ''} live",
                      "start": float(year), "end": end, "kind": "bar", "group": "Partners"})
    if fu["first_ebitda_positive_year"]:
        y = int(fu["first_ebitda_positive_year"])
        items.append({"label": f"Group EBITDA positive ({y})", "start": y + 1.0, "end": y + 1.0, "kind": "milestone", "group": "Cash"})
    if fu["cumulative_positive_year"]:
        y = int(fu["cumulative_positive_year"])
        items.append({"label": f"Cumulative EBITDA positive ({y})", "start": y + 1.0, "end": y + 1.0, "kind": "milestone", "group": "Cash"})
    items.append({"label": f"{plan['partner_markets']['total_markets_by_2031']} markets on one platform",
                  "start": end, "end": end, "kind": "milestone", "group": "Partners"})
    return items


def chart_specs(plan: Mapping[str, Any]) -> List[Dict[str, Any]]:
    years = [str(y) for y in plan["years"]]
    il = _rows(plan, "anchor_book")
    pm = _rows(plan, "partner_markets")
    g = _rows(plan, "group")
    cv = _rows(plan, "carrier_view")
    fu = plan["funding"]
    ap = plan["appraisal"]
    specs: List[Dict[str, Any]] = []

    specs.append({
        "id": "in_force", "kind": "stacked_bars", "unit": "int",
        "title": "Policies in force at year end",
        "subtitle": "Israel anchor book plus partner-market cohorts; the stack total is the group.",
        "categories": years,
        "series": [
            {"label": "Israel", "color": NAVY, "values": [r["eoy_in_force"] for r in il]},
            {"label": "Partner markets", "color": GOLD, "values": [r["eoy_in_force"] for r in pm]},
        ],
        "source": "anchor_book.rows[].eoy_in_force + partner_markets.rows[].eoy_in_force = group.rows[].eoy_in_force",
    })
    specs.append({
        "id": "revenue_ebitda", "kind": "grouped_bars", "unit": "ilsm",
        "title": "Group PHINS revenue, opex and EBITDA (ILS)",
        "subtitle": "Revenue − opex = EBITDA every year; 2027 is the only loss year at default factors.",
        "categories": years,
        "series": [
            {"label": "PHINS revenue", "color": NAVY, "values": [r["phins_revenue"] for r in g]},
            {"label": "Opex", "color": GREY, "values": [r["opex"] for r in g]},
            {"label": "EBITDA", "color": GOLD, "values": [r["ebitda"] for r in g]},
        ],
        "source": "group.rows[].phins_revenue, opex, ebitda",
    })
    specs.append({
        "id": "gwp_split", "kind": "stacked_bars", "unit": "ilsm",
        "title": "Risk GWP and who keeps it (ILS)",
        "subtitle": "Carrier share + PHINS revenue + partner revenue = group risk GWP; savings flow is outside this bar.",
        "categories": years,
        "series": [
            {"label": "Carrier share", "color": NAVY_MID, "values": [r["carrier_share"] for r in g]},
            {"label": "PHINS revenue", "color": GOLD, "values": [r["phins_revenue"] for r in g]},
            {"label": "Partner revenue", "color": GOLD_DEEP, "values": [r["partner_revenue"] for r in g]},
        ],
        "source": "group.rows[].carrier_share + phins_revenue + partner_revenue = group.rows[].risk_gwp",
    })
    # Funding window: through the first cumulative-positive year (at least
    # three years) so the trough and the reference lines stay legible; the
    # later years are in the revenue chart and Appendix F.
    cum_pos = fu.get("cumulative_positive_year")
    n_fund = max(3, (plan["years"].index(cum_pos) + 1) if cum_pos in plan["years"] else len(years))
    specs.append({
        "id": "cash_curve", "kind": "line", "unit": "ilsm",
        "title": f"Cumulative group EBITDA and the funding path, {years[0]}–{years[n_fund - 1]} (ILS)",
        "subtitle": "The low point of the curve is the peak cumulative need; the seed and the Series A indication are the reference lines.",
        "categories": years[:n_fund],
        "series": [
            {"label": "Cumulative EBITDA (group)", "color": NAVY, "values": [r["cumulative_ebitda"] for r in g[:n_fund]]},
        ],
        "refs": [
            {"label": "Seed " + label(fu["seed"], "ilsm0"), "value": -fu["seed"], "color": GOLD_DEEP},
            {"label": "Seed + Series A " + label(fu["series_a_indicative"], "ilsm"),
             "value": -(fu["seed"] + fu["series_a_indicative"]), "color": RED},
        ],
        "source": "group.rows[].cumulative_ebitda; funding.seed; funding.series_a_indicative",
    })
    c29 = cv[2]
    specs.append({
        "id": "carrier_view", "kind": "waterfall", "unit": "ilsm",
        "title": f"Carrier economics {years[2]} — Israel anchor book (ILS)",
        "subtitle": "What the carrier of record and the quota-share reinsurer see on the same GWP.",
        "steps": [
            {"label": "Risk GWP", "value": c29["risk_gwp"], "kind": "total"},
            {"label": "PHINS fee", "value": -c29["phins_fee"], "kind": "delta"},
            {"label": "Expected claims", "value": -c29["expected_claims"], "kind": "delta"},
            {"label": "Ceded claims", "value": c29["ceded_claims"], "kind": "delta"},
            {"label": "Ceding commission", "value": c29["ceding_commission"], "kind": "delta"},
            {"label": "Ceded premium", "value": -c29["ceded_premium"], "kind": "delta"},
            {"label": "Own expenses", "value": -c29["own_expenses"], "kind": "delta"},
            {"label": "Carrier result", "value": c29["carrier_result"], "kind": "total"},
        ],
        "source": "carrier_view.rows[2]",
    })
    uof = fu["use_of_funds"]
    specs.append({
        "id": "use_of_funds", "kind": "donut", "unit": "ilsm",
        "title": "Use of the seed round (ILS)",
        "subtitle": "Shares are adjustable factors and must sum to 100%.",
        "segments": [
            {"label": "Product & technology", "value": uof["product_technology"]["amount"], "share": uof["product_technology"]["share"], "color": NAVY},
            {"label": "Regulatory, actuarial & reinsurance", "value": uof["regulatory_actuarial"]["amount"], "share": uof["regulatory_actuarial"]["share"], "color": NAVY_MID},
            {"label": "Distribution & local partnerships", "value": uof["distribution_partnerships"]["amount"], "share": uof["distribution_partnerships"]["share"], "color": GOLD},
            {"label": "Operations & reserve", "value": uof["operations_reserve"]["amount"], "share": uof["operations_reserve"]["share"], "color": GOLD_DEEP},
        ],
        "center": label(fu["seed"], "ilsm0"),
        "source": "funding.use_of_funds",
    })
    sens = ap["sensitivity"]
    specs.append({
        "id": "appraisal_sensitivity", "kind": "heatmap", "unit": "ilsm",
        "title": "Actuarial appraisal sensitivity (ILS pre-money)",
        "subtitle": f"Rows: discount rate (WACC). Columns: exit multiple on {years[2]} net revenue. Prudence {label(ap['prudence'], 'pct')} throughout; the highlighted cell is the plan.",
        "rows": [label(w, "pct") for w in sens["wacc"]],
        "cols": [label(x, "x") for x in sens["exit_multiple"]],
        "values": sens["pre_money"],
        "highlight": [sens["wacc"].index(round(ap["wacc"], 4)) if round(ap["wacc"], 4) in sens["wacc"] else -1,
                      sens["exit_multiple"].index(round(ap["exit_multiple"], 4)) if round(ap["exit_multiple"], 4) in sens["exit_multiple"] else -1],
        "source": "appraisal.sensitivity",
    })
    specs.append({
        "id": "roadmap", "kind": "gantt", "unit": "year",
        "title": "Roadmap 2026–2031",
        "subtitle": "Dated gates, the Israel sales clock, one bar per partner-market cohort, and the derived cash gates.",
        "items": roadmap_items(plan),
        "axis": {"start": 2026.5, "end": float(plan["years"][-1]) + 1.0},
        "source": "GATES; partner_markets.launches; funding",
    })
    return specs


def chart_by_id(plan: Mapping[str, Any], chart_id: str) -> Dict[str, Any]:
    for s in chart_specs(plan):
        if s["id"] == chart_id:
            return s
    raise KeyError(chart_id)


# ---------------------------------------------------------------------------
# Data tables (Markdown edition and HTML fallback)
# ---------------------------------------------------------------------------
def chart_table(spec: Mapping[str, Any]) -> Tuple[List[str], List[List[str]]]:
    kind = spec["kind"]
    unit = spec.get("unit", "")
    if kind in ("stacked_bars", "grouped_bars", "line"):
        header = ["Series"] + list(spec["categories"])
        rows = [[s["label"]] + [label(v, unit) for v in s["values"]] for s in spec["series"]]
        if kind == "stacked_bars":
            totals = [sum(s["values"][i] for s in spec["series"]) for i in range(len(spec["categories"]))]
            rows.append(["Total"] + [label(v, unit) for v in totals])
        for ref in spec.get("refs", []):
            rows.append([ref["label"] + " (reference)"] + [label(ref["value"], unit)] * len(spec["categories"]))
        return header, rows
    if kind == "waterfall":
        return ["Step", "Amount"], [[s["label"], label(s["value"], unit)] for s in spec["steps"]]
    if kind == "donut":
        return ["Segment", "Amount", "Share"], [[s["label"], label(s["value"], unit), label(s["share"], "pct")] for s in spec["segments"]]
    if kind == "heatmap":
        header = ["WACC \\ exit multiple"] + list(spec["cols"])
        return header, [[r] + [label(v, unit) for v in row] for r, row in zip(spec["rows"], spec["values"])]
    if kind == "gantt":
        rows = []
        for it in spec["items"]:
            if it["kind"] == "milestone":
                when = _year_text(it["start"], end=True)
            else:
                when = f"{_year_text(it['start'])} → {_year_text(it['end'], end=True)}"
            rows.append([it["group"], it["label"], "milestone" if it["kind"] == "milestone" else "phase", when])
        return ["Track", "Item", "Type", "When"], rows
    raise ValueError(kind)


def _year_text(t: float, end: bool = False) -> str:
    """Decimal year → text. A whole number is the boundary between two
    years: as a start it is the year that begins, as an end (phase end or
    year-end milestone) it is the close of the year before."""
    year = int(math.floor(t + 1e-9))
    frac = t - year
    if abs(frac) < 1e-9:
        return f"end-{year - 1}" if end else str(year)
    if end:
        return f"Q{int(math.ceil(frac * 4 - 1e-9))} {year}"
    return f"Q{int(math.floor(frac * 4 + 1e-9)) + 1} {year}"


# ---------------------------------------------------------------------------
# Layout engine — spec → primitives
# ---------------------------------------------------------------------------
def _nice_ticks(lo: float, hi: float, n: int = 5) -> List[float]:
    if hi <= lo:
        hi = lo + 1.0
    raw = (hi - lo) / n
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1.0
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if raw <= step:
            break
    start = math.floor(lo / step) * step
    ticks = []
    t = start
    while t <= hi + step * 0.5:
        ticks.append(round(t, 10))
        t += step
    return ticks


def _text(x: float, y: float, s: str, anchor: str = "start", size: float = 11, fill: str = INK,
          weight: Optional[str] = None) -> Op:
    return ("text", x, y, s, anchor, size, fill, weight)


def _rect(x: float, y: float, w: float, h: float, fill: str, stroke: Optional[str] = None, rx: float = 0.0) -> Op:
    return ("rect", x, y, w, h, fill, stroke, rx)


def _line(x1: float, y1: float, x2: float, y2: float, stroke: str = LINE, width: float = 1.0, dash: Optional[str] = None) -> Op:
    return ("line", x1, y1, x2, y2, stroke, width, dash)


def _head(spec: Mapping[str, Any]) -> List[Op]:
    return [
        _text(PAD_L - 48, 20, spec["title"], "start", 14, NAVY, "bold"),
        _text(PAD_L - 48, 35, spec.get("subtitle", ""), "start", 9.5, MUTED),
    ]


def _legend(series: Sequence[Mapping[str, Any]], y: float) -> List[Op]:
    ops: List[Op] = []
    x = PAD_L
    for s in series:
        ops.append(_rect(x, y - 8, 10, 10, s["color"], None, 2))
        ops.append(_text(x + 14, y, s["label"], "start", 10, MUTED))
        x += 14 + 6.2 * len(s["label"]) + 22
    return ops


def _axes(lo: float, hi: float, unit: str, plot_h: float, top: float) -> Tuple[List[Op], Any]:
    ticks = _nice_ticks(lo, hi)
    lo, hi = min(ticks[0], lo), max(ticks[-1], hi)
    span = hi - lo if hi > lo else 1.0

    def ypix(v: float) -> float:
        return top + plot_h - (v - lo) / span * plot_h

    ops: List[Op] = []
    for t in ticks:
        y = ypix(t)
        ops.append(_line(PAD_L, y, W - PAD_R, y, LINE if abs(t) > 1e-9 else MUTED, 1 if abs(t) > 1e-9 else 1.2))
        ops.append(_text(PAD_L - 6, y + 3.5, label(t, "ilsm0" if unit in ("ilsm", "ilsm0") else unit), "end", 9.5, MUTED))
    return ops, ypix


def layout(spec: Mapping[str, Any]) -> List[Op]:
    kind = spec["kind"]
    ops: List[Op] = [_rect(0, 0, W, H, WHITE)]
    ops += _head(spec)
    if kind in ("stacked_bars", "grouped_bars"):
        ops += _layout_bars(spec, stacked=(kind == "stacked_bars"))
    elif kind == "line":
        ops += _layout_line(spec)
    elif kind == "waterfall":
        ops += _layout_waterfall(spec)
    elif kind == "donut":
        ops += _layout_donut(spec)
    elif kind == "heatmap":
        ops += _layout_heatmap(spec)
    elif kind == "gantt":
        ops += _layout_gantt(spec)
    else:
        raise ValueError(kind)
    return ops


def _layout_bars(spec: Mapping[str, Any], stacked: bool) -> List[Op]:
    unit = spec["unit"]
    cats = spec["categories"]
    series = spec["series"]
    top = PAD_T + 18
    plot_h = H - top - PAD_B
    if stacked:
        totals = [sum(max(0.0, s["values"][i]) for s in series) for i in range(len(cats))]
        hi, lo = max(totals + [0.0]), 0.0
    else:
        allv = [v for s in series for v in s["values"]]
        hi, lo = max(allv + [0.0]), min(allv + [0.0])
    ops, ypix = _axes(lo, hi, unit, plot_h, top)
    ops += _legend(series, PAD_T + 6)
    plot_w = W - PAD_L - PAD_R
    slot = plot_w / len(cats)
    for i, cat in enumerate(cats):
        x0 = PAD_L + i * slot
        ops.append(_text(x0 + slot / 2, H - PAD_B + 16, cat, "middle", 10.5, INK))
        if stacked:
            bw = slot * 0.52
            x = x0 + (slot - bw) / 2
            base = 0.0
            for s in series:
                v = max(0.0, float(s["values"][i]))
                if v <= 0:
                    continue
                y1, y0 = ypix(base), ypix(base + v)
                ops.append(_rect(x, y0, bw, y1 - y0, s["color"]))
                base += v
            if base > 0:
                ops.append(_text(x + bw / 2, ypix(base) - 5, label(base, unit), "middle", 10, NAVY, "bold"))
        else:
            n = len(series)
            bw = slot * 0.74 / n
            x = x0 + slot * 0.13
            for s in series:
                v = float(s["values"][i])
                y_zero = ypix(0.0)
                y_v = ypix(v)
                top_y, hgt = (y_v, y_zero - y_v) if v >= 0 else (y_zero, y_v - y_zero)
                ops.append(_rect(x, top_y, bw - 2, max(hgt, 0.0), s["color"]))
                ly = top_y - 4 if v >= 0 else top_y + hgt + 11
                ops.append(_text(x + (bw - 2) / 2, ly, label(v, unit), "middle", 8, INK))
                x += bw
    return ops


def _layout_line(spec: Mapping[str, Any]) -> List[Op]:
    unit = spec["unit"]
    cats = spec["categories"]
    series = spec["series"]
    refs = spec.get("refs", [])
    top = PAD_T + 18
    plot_h = H - top - PAD_B
    allv = [v for s in series for v in s["values"]] + [r["value"] for r in refs] + [0.0]
    ops, ypix = _axes(min(allv), max(allv), unit, plot_h, top)
    ops += _legend(series + [{"label": r["label"], "color": r["color"]} for r in refs], PAD_T + 6)
    plot_w = W - PAD_L - PAD_R
    slot = plot_w / len(cats)
    xs = [PAD_L + (i + 0.5) * slot for i in range(len(cats))]
    for i, cat in enumerate(cats):
        ops.append(_text(xs[i], H - PAD_B + 16, cat, "middle", 10.5, INK))
    for k, r in enumerate(refs):
        y = ypix(r["value"])
        ops.append(_line(PAD_L, y, W - PAD_R, y, r["color"], 1.2, "5,4"))
        # Alternate above / below the line so two close references never collide.
        ops.append(_text(W - PAD_R - 4, y - 4 if k % 2 == 0 else y + 11, r["label"], "end", 9, r["color"]))
    for s in series:
        pts = [(xs[i], ypix(float(v))) for i, v in enumerate(s["values"])]
        ops.append(("polyline", pts, s["color"], 2.4))
        for (x, y), v in zip(pts, s["values"]):
            ops.append(("circle", x, y, 4, s["color"], WHITE))
            ops.append(_text(x, y - 9 if float(v) >= 0 else y + 16, label(v, unit), "middle", 9.5, NAVY, "bold"))
    return ops


def _layout_waterfall(spec: Mapping[str, Any]) -> List[Op]:
    unit = spec["unit"]
    steps = spec["steps"]
    top = PAD_T + 8
    plot_h = H - top - PAD_B - 10
    running = 0.0
    bars: List[Tuple[str, float, float, str]] = []  # label, y_from, y_to, color
    peak = 0.0
    for s in steps:
        v = float(s["value"])
        if s["kind"] == "total":
            bars.append((s["label"], 0.0, v, NAVY if s is steps[0] else GOLD))
            running = v
        else:
            bars.append((s["label"], running, running + v, GREEN if v >= 0 else RED))
            running += v
        peak = max(peak, max(abs(b[1]) for b in bars), max(abs(b[2]) for b in bars))
    ops, ypix = _axes(min(0.0, min(min(b[1], b[2]) for b in bars)), peak, unit, plot_h, top)
    plot_w = W - PAD_L - PAD_R
    slot = plot_w / len(bars)
    bw = slot * 0.6
    for i, (lab, a, b, color) in enumerate(bars):
        x = PAD_L + i * slot + (slot - bw) / 2
        y0, y1 = ypix(max(a, b)), ypix(min(a, b))
        ops.append(_rect(x, y0, bw, max(y1 - y0, 1.0), color))
        delta = b - a
        ops.append(_text(x + bw / 2, y0 - 5, label(delta if i not in (0, len(bars) - 1) else b, unit), "middle", 9, INK, "bold"))
        words = lab.split(" ")
        line1 = words[0] if len(words) > 1 else lab
        line2 = " ".join(words[1:]) if len(words) > 1 else ""
        ops.append(_text(x + bw / 2, H - PAD_B + 14, line1, "middle", 9, INK))
        if line2:
            ops.append(_text(x + bw / 2, H - PAD_B + 25, line2, "middle", 9, INK))
        if i + 1 < len(bars):
            ops.append(_line(x + bw, ypix(b), x + slot, ypix(b), GREY, 1, "3,3"))
    return ops


def _layout_donut(spec: Mapping[str, Any]) -> List[Op]:
    unit = spec["unit"]
    segs = spec["segments"]
    cx, cy, r, r_in = 170.0, 190.0, 92.0, 56.0
    total = sum(float(s["value"]) for s in segs) or 1.0
    ops: List[Op] = []
    a0 = -90.0
    for s in segs:
        sweep = 360.0 * float(s["value"]) / total
        ops.append(("wedge", cx, cy, r, r_in, a0, a0 + sweep, s["color"]))
        a0 += sweep
    ops.append(_text(cx, cy - 2, spec.get("center", ""), "middle", 15, NAVY, "bold"))
    ops.append(_text(cx, cy + 14, "seed", "middle", 9.5, MUTED))
    y = 118.0
    for s in segs:
        ops.append(_rect(300, y - 9, 12, 12, s["color"], None, 2))
        ops.append(_text(318, y + 1, s["label"], "start", 11, INK))
        ops.append(_text(W - PAD_R, y + 1, f"{label(s['value'], unit)} · {label(s['share'], 'pct')}", "end", 11, NAVY, "bold"))
        y += 34
    return ops


def _layout_heatmap(spec: Mapping[str, Any]) -> List[Op]:
    unit = spec["unit"]
    rows, cols, vals = spec["rows"], spec["cols"], spec["values"]
    hl = spec.get("highlight", [-1, -1])
    flat = [v for row in vals for v in row]
    lo, hi = min(flat), max(flat)
    top = PAD_T + 26
    left = PAD_L + 30
    cell_w = (W - left - PAD_R) / len(cols)
    cell_h = (H - top - 20) / len(rows)
    ops: List[Op] = []
    for j, c in enumerate(cols):
        ops.append(_text(left + (j + 0.5) * cell_w, top - 8, f"exit {c}", "middle", 10, MUTED, "bold"))
    for i, r in enumerate(rows):
        ops.append(_text(left - 8, top + (i + 0.5) * cell_h + 4, f"WACC {r}", "end", 10, MUTED, "bold"))
        for j, v in enumerate(vals[i]):
            t = (float(v) - lo) / (hi - lo) if hi > lo else 0.5
            fill = _mix(ICE, NAVY_MID, t)
            is_hl = (i == hl[0] and j == hl[1])
            ops.append(_rect(left + j * cell_w + 1, top + i * cell_h + 1, cell_w - 2, cell_h - 2, fill, GOLD if is_hl else None, 3))
            ops.append(_text(left + (j + 0.5) * cell_w, top + (i + 0.5) * cell_h + 4, label(v, unit), "middle", 11,
                             WHITE if t > 0.55 else NAVY, "bold" if is_hl else None))
    return ops


def _layout_gantt(spec: Mapping[str, Any]) -> List[Op]:
    items = spec["items"]
    axis = spec["axis"]
    t0, t1 = float(axis["start"]), float(axis["end"])
    left = 262.0
    top = PAD_T + 14
    plot_w = W - left - PAD_R
    row_h = (H - top - 26) / max(len(items), 1)

    def xpix(t: float) -> float:
        return left + (t - t0) / (t1 - t0) * plot_w

    ops: List[Op] = []
    y_ticks_top = top - 4
    year = int(math.ceil(t0))
    while year <= int(math.floor(t1)):
        x = xpix(float(year))
        ops.append(_line(x, y_ticks_top, x, H - 22, LINE, 1))
        ops.append(_text(x, H - 8, str(year), "middle", 9.5, MUTED))
        year += 1
    colors = {"Regulation": NAVY_MID, "Capital": GOLD_DEEP, "Israel": NAVY, "Partners": GOLD, "Cash": GREEN}
    for i, it in enumerate(items):
        y = top + i * row_h
        if i % 2 == 0:
            ops.append(_rect(PAD_L - 48, y, W - (PAD_L - 48) - PAD_R, row_h, ICE))
        ops.append(_text(left - 8, y + row_h / 2 + 3.5, it["label"], "end", 9, INK))
        color = colors.get(it["group"], GREY)
        if it["kind"] == "milestone":
            x = xpix(float(it["start"]))
            s = min(row_h * 0.32, 7.0)
            ops.append(("polygon", [(x, y + row_h / 2 - s), (x + s, y + row_h / 2), (x, y + row_h / 2 + s), (x - s, y + row_h / 2)], color))
        else:
            x0, x1 = xpix(float(it["start"])), xpix(float(it["end"]))
            bh = min(row_h * 0.56, 12.0)
            ops.append(_rect(x0, y + (row_h - bh) / 2, max(x1 - x0, 2.0), bh, color, None, 3))
    return ops


def _mix(c1: str, c2: str, t: float) -> str:
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    t = max(0.0, min(1.0, t))
    return "#" + "".join(f"{int(round(a[i] + (b[i] - a[i]) * t)):02x}" for i in range(3))


# ---------------------------------------------------------------------------
# SVG backend
# ---------------------------------------------------------------------------
def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _arc_path(cx: float, cy: float, r: float, r_in: float, a0: float, a1: float) -> str:
    def pt(rad: float, ang: float) -> Tuple[float, float]:
        a = math.radians(ang)
        return cx + rad * math.cos(a), cy + rad * math.sin(a)
    if a1 - a0 >= 359.999:
        a1 = a0 + 359.999
    large = 1 if (a1 - a0) > 180 else 0
    x0, y0 = pt(r, a0)
    x1, y1 = pt(r, a1)
    xi1, yi1 = pt(r_in, a1)
    xi0, yi0 = pt(r_in, a0)
    return (f"M{_n(x0)} {_n(y0)} A{_n(r)} {_n(r)} 0 {large} 1 {_n(x1)} {_n(y1)} "
            f"L{_n(xi1)} {_n(yi1)} A{_n(r_in)} {_n(r_in)} 0 {large} 0 {_n(xi0)} {_n(yi0)} Z")


def render_svg(spec: Mapping[str, Any]) -> str:
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" role="img" '
           f'aria-label="{_esc(spec["title"])}" data-chart="{_esc(spec["id"])}" '
           f'style="font-family:Inter,\'Segoe UI\',sans-serif;display:block">']
    for op in layout(spec):
        k = op[0]
        if k == "rect":
            _, x, y, w, h, fill, stroke, rx = op
            s = f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" fill="{fill}"'
            if rx:
                s += f' rx="{_n(rx)}"'
            if stroke:
                s += f' stroke="{stroke}" stroke-width="2"'
            out.append(s + "/>")
        elif k == "text":
            _, x, y, text, anchor, size, fill, weight = op
            s = f'<text x="{_n(x)}" y="{_n(y)}" text-anchor="{anchor}" font-size="{_n(size)}" fill="{fill}"'
            if weight:
                s += f' font-weight="{weight}"'
            out.append(s + f">{_esc(text)}</text>")
        elif k == "line":
            _, x1, y1, x2, y2, stroke, width, dash = op
            s = f'<line x1="{_n(x1)}" y1="{_n(y1)}" x2="{_n(x2)}" y2="{_n(y2)}" stroke="{stroke}" stroke-width="{_n(width)}"'
            if dash:
                s += f' stroke-dasharray="{dash}"'
            out.append(s + "/>")
        elif k == "polyline":
            _, pts, stroke, width = op
            p = " ".join(f"{_n(x)},{_n(y)}" for x, y in pts)
            out.append(f'<polyline points="{p}" fill="none" stroke="{stroke}" stroke-width="{_n(width)}" stroke-linejoin="round"/>')
        elif k == "polygon":
            _, pts, fill = op
            p = " ".join(f"{_n(x)},{_n(y)}" for x, y in pts)
            out.append(f'<polygon points="{p}" fill="{fill}"/>')
        elif k == "circle":
            _, x, y, r, fill, stroke = op
            out.append(f'<circle cx="{_n(x)}" cy="{_n(y)}" r="{_n(r)}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        elif k == "wedge":
            _, cx, cy, r, r_in, a0, a1, fill = op
            out.append(f'<path d="{_arc_path(cx, cy, r, r_in, a0, a1)}" fill="{fill}"/>')
    out.append("</svg>")
    return "".join(out)


# ---------------------------------------------------------------------------
# reportlab backend (PDF edition)
# ---------------------------------------------------------------------------
def render_reportlab(spec: Mapping[str, Any], width: float, font: str = "Helvetica",
                     bold_font: str = "Helvetica-Bold", currency_glyph_ok: bool = False):
    """Return a reportlab Drawing of the same primitives, scaled to ``width``.

    When the registered font lacks the new-shekel glyph (Helvetica does),
    ``₪`` is written as ``ILS `` so the number stays legible; the value is
    unchanged.
    """
    from reportlab.graphics.shapes import (Circle, Drawing, Line, Polygon, PolyLine, Rect,
                                           String, Wedge)
    from reportlab.lib import colors as rl_colors

    scale = width / W
    d = Drawing(width, H * scale)

    def col(c: Optional[str]):
        return rl_colors.HexColor(c) if c else None

    def tx(s: str) -> str:
        return s if currency_glyph_ok else s.replace("₪", "ILS ")

    for op in layout(spec):
        k = op[0]
        if k == "rect":
            _, x, y, w, h, fill, stroke, rx = op
            r = Rect(x * scale, (H - y - h) * scale, w * scale, h * scale, rx=rx * scale, ry=rx * scale)
            r.fillColor = col(fill)
            r.strokeColor = col(stroke)
            r.strokeWidth = 1.6 if stroke else 0
            d.add(r)
        elif k == "text":
            _, x, y, text, anchor, size, fill, weight = op
            s = String(x * scale, (H - y) * scale, tx(text), fontName=bold_font if weight else font,
                       fontSize=size * scale, fillColor=col(fill), textAnchor=anchor)
            d.add(s)
        elif k == "line":
            _, x1, y1, x2, y2, stroke, lw, dash = op
            ln = Line(x1 * scale, (H - y1) * scale, x2 * scale, (H - y2) * scale,
                      strokeColor=col(stroke), strokeWidth=lw * scale)
            if dash:
                ln.strokeDashArray = [float(p) * scale for p in dash.split(",")]
            d.add(ln)
        elif k == "polyline":
            _, pts, stroke, lw = op
            flat: List[float] = []
            for x, y in pts:
                flat += [x * scale, (H - y) * scale]
            d.add(PolyLine(flat, strokeColor=col(stroke), strokeWidth=lw * scale))
        elif k == "polygon":
            _, pts, fill = op
            flat = []
            for x, y in pts:
                flat += [x * scale, (H - y) * scale]
            pg = Polygon(flat)
            pg.fillColor = col(fill)
            pg.strokeColor = None
            d.add(pg)
        elif k == "circle":
            _, x, y, r, fill, stroke = op
            c = Circle(x * scale, (H - y) * scale, r * scale)
            c.fillColor = col(fill)
            c.strokeColor = col(stroke)
            c.strokeWidth = 1.2
            d.add(c)
        elif k == "wedge":
            _, cx, cy, r, r_in, a0, a1, fill = op
            # SVG angles grow clockwise with y down; reportlab's grow
            # counter-clockwise with y up, so the mirrored angles are equal.
            wd = Wedge(cx * scale, (H - cy) * scale, r * scale, -a1, -a0, radius1=r_in * scale, annular=True)
            wd.fillColor = col(fill)
            wd.strokeColor = None
            d.add(wd)
    return d


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------
def render_all(plan: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Specs with their SVG and data table — what the API returns for ?charts=1."""
    out = []
    for spec in chart_specs(plan):
        header, rows = chart_table(spec)
        out.append({"id": spec["id"], "title": spec["title"], "subtitle": spec.get("subtitle", ""),
                    "kind": spec["kind"], "source": spec.get("source", ""),
                    "svg": render_svg(spec), "table": {"header": header, "rows": rows}})
    return out


def directive(spec: Mapping[str, Any]) -> str:
    """Markdown comment carrying the chart data for the PDF generator."""
    return "<!-- phins-chart " + json.dumps(spec, ensure_ascii=False, sort_keys=True).replace("--", "\\u002d\\u002d") + " -->"


def parse_directive(line: str) -> Optional[Dict[str, Any]]:
    s = line.strip()
    if not (s.startswith("<!-- phins-chart ") and s.endswith(" -->")):
        return None
    body = s[len("<!-- phins-chart "):-len(" -->")]
    try:
        return json.loads(body)
    except ValueError:
        return None


__all__ = [
    "H", "W",
    "chart_by_id", "chart_specs", "chart_table", "directive", "label", "layout",
    "parse_directive", "render_all", "render_reportlab", "render_svg", "roadmap_items",
]
