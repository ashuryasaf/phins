"""Unified business plan — model, document and surface contracts.

Covers:
- the anchor book of ``services/business_plan_model.py`` reconciles to the
  Investor Meeting book served by ``/api/platform/facts`` and to the
  valuation simulator's appraisal formula (one identity, no second model);
- structural integrity identities hold at defaults and under overrides;
  out-of-range factors fall back and are reported, never silently applied;
- the plan is deterministic (content hash) and the technology section is a
  live census, not a typed claim;
- the committed ``business-plan.html`` / ``phins-unified-business-plan.md``
  equal a fresh render (``scripts/build_business_plan.py --check``) and carry
  the PHINS letterhead standard (shield emblem, tagline, navy / gold, Inter +
  Space Grotesk, return bar, live module binding);
- the Python and browser formatters agree, so the no-JS fallback equals the
  live render;
- the public, read-only ``GET /api/business-plan/model`` endpoint and the
  pitch-dashboard card that links the plan.
"""

from __future__ import annotations

import html as html_lib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

import web_portal.server as portal
from services import business_plan_document as doc
from services import business_plan_model as bpm
from services.aspire_scale_identity import UNIFIED_5Y_EOY, UNIFIED_5Y_OPEX

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web_portal" / "static"
HTML = STATIC / "business-plan.html"
MD = STATIC / "investor-docs" / "phins-unified-business-plan.md"
PDF = STATIC / "investor-docs" / "phins-unified-business-plan.pdf"
BASE = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# One identity: anchor book == Investor Meeting book == valuation simulator
# ---------------------------------------------------------------------------
def test_anchor_book_reconciles_to_platform_facts_book():
    plan = bpm.compute_plan()
    book = portal.build_investor_book()
    rows = plan["anchor_book"]["rows"]
    assert plan["canonical"] is True
    assert plan["integrity"]["all_hold"] is True
    for i in range(3):
        assert rows[i]["year"] == book["years"][i]
        assert int(rows[i]["eoy_in_force"]) == book["eoy_in_force"][i]
        assert int(rows[i]["avg_in_force"]) == book["avg_in_force"][i]
        assert rows[i]["risk_gwp"] == book["gwp"][i]
        assert rows[i]["phins_revenue"] == book["net_revenue"][i]
        assert rows[i]["opex"] == book["opex"][i]
        assert rows[i]["ebitda"] == book["ebitda"][i]
    assert plan["inputs"]["annual_premium"] == book["premium"] == 4518.0
    assert plan["inputs"]["phins_take"] == book["take_rate"] == 0.25
    assert plan["anchor_book"]["churn"] == book["churn"]
    assert plan["funding"]["seed"] == book["seed"]
    assert plan["funding"]["pre_money"] == book["pre_money"]
    assert plan["funding"]["post_money"] == book["post_money"]


def test_anchor_book_five_year_extension_matches_identity_module():
    rows = bpm.compute_plan()["anchor_book"]["rows"]
    assert [int(r["eoy_in_force"]) for r in rows] == list(UNIFIED_5Y_EOY)
    assert [r["opex"] for r in rows] == [float(x) for x in UNIFIED_5Y_OPEX]


def test_round_constants_have_one_writer():
    assert portal._INV_ROUND_SEED == bpm.ROUND_SEED_ILS == 6_000_000.0
    assert portal._INV_ROUND_PRE_MONEY == bpm.ROUND_PRE_MONEY_ILS == 24_000_000.0


def test_appraisal_uses_the_valuation_sim_formula():
    plan = bpm.compute_plan()
    b = portal._INV_VAL_BASE
    expected = portal._inv_appraisal_pre_money(
        b["in_force"], b["premium"], b["take_rate"], b["opex"], 0.35, 4.0, "net_revenue", 0.15,
    )
    assert plan["appraisal"]["central_pre_money"] == pytest.approx(expected, abs=1e-6)
    sim = portal.compute_investor_valuation_sim({
        "wacc": 0.35, "exit_multiple": 4.0, "exit_metric": "net_revenue", "prudence": 0.15,
    })
    assert round(plan["appraisal"]["central_pre_money"]) == sim["central"]


# ---------------------------------------------------------------------------
# Integrity, overrides, determinism
# ---------------------------------------------------------------------------
def test_funding_is_derived_from_the_cash_curve():
    plan = bpm.compute_plan()
    fu = plan["funding"]
    rows = plan["group"]["rows"]
    assert fu["burn_2027"] == -plan["anchor_book"]["rows"][0]["ebitda"] == 18_846_000.0
    assert fu["peak_cumulative_need"] == -min(r["cumulative_ebitda"] for r in rows)
    need = (fu["peak_cumulative_need"] - fu["seed"]) * 1.25
    assert fu["series_a_indicative"] >= need
    assert fu["series_a_indicative"] - need < 500_000.0
    assert fu["series_a_indicative"] % 500_000.0 == 0
    assert fu["first_ebitda_positive_year"] == 2029
    assert abs(fu["use_of_funds_total_share"] - 1.0) < 1e-9
    assert sum(v["amount"] for v in fu["use_of_funds"].values()) == pytest.approx(fu["seed"])


def test_group_is_anchor_plus_partners_and_collapses_without_launches():
    plan = bpm.compute_plan()
    for i in range(5):
        a, p, g = (plan["anchor_book"]["rows"][i], plan["partner_markets"]["rows"][i],
                   plan["group"]["rows"][i])
        assert g["risk_gwp"] == pytest.approx(a["risk_gwp"] + p["risk_gwp"])
        assert g["ebitda"] == pytest.approx(a["ebitda"] + p["ebitda"])
        assert p["phins_revenue"] + p["partner_revenue"] == pytest.approx(p["take_pool"])
    solo = bpm.compute_plan({"new_markets_2028": 0, "new_markets_2029": 0,
                             "new_markets_2030": 0, "new_markets_2031": 0})
    assert solo["canonical"] is False
    assert solo["integrity"]["all_hold"] is True
    assert solo["partner_markets"]["total_markets_by_2031"] == 1
    for i in range(5):
        assert solo["group"]["rows"][i]["risk_gwp"] == solo["anchor_book"]["rows"][i]["risk_gwp"]
        assert solo["partner_markets"]["rows"][i]["risk_gwp"] == 0.0


def test_overrides_scale_exactly_and_keep_identities():
    base = bpm.compute_plan()
    adj = bpm.compute_plan({"phins_take": "0.30"})
    assert adj["canonical"] is False
    assert adj["errors"] == []
    assert adj["integrity"]["all_hold"] is True
    assert adj["integrity"]["anchor_book_reconciles_to_investor_meeting"] is True
    for i in range(5):
        assert adj["anchor_book"]["rows"][i]["phins_revenue"] == pytest.approx(
            base["anchor_book"]["rows"][i]["phins_revenue"] * 1.2)
        assert adj["anchor_book"]["rows"][i]["risk_gwp"] == base["anchor_book"]["rows"][i]["risk_gwp"]
    assert adj["content_hash"] != base["content_hash"]


def test_out_of_range_and_unknown_factors_are_reported_not_applied():
    plan = bpm.compute_plan({"phins_take": 5, "not_a_factor": 1, "new_markets_2028": "2.6"})
    assert plan["inputs"]["phins_take"] == 0.25
    assert plan["errors"] == ["phins_take must be between 0.05 and 0.6"]
    assert plan["inputs"]["new_markets_2028"] == 3.0  # int factor rounds
    assert "not_a_factor" not in plan["inputs"]
    bad = bpm.compute_plan({"annual_premium": "abc"})
    assert bad["inputs"]["annual_premium"] == 4518.0
    assert bad["errors"] == ["annual_premium must be numeric"]


def test_plan_is_deterministic_and_hash_covers_money_lines():
    a = bpm.compute_plan()
    b = bpm.compute_plan()
    assert a["content_hash"] == b["content_hash"]
    assert len(a["content_hash"]) == 64
    assert bpm.content_hash(a) == a["content_hash"]


def test_factor_register_is_well_formed():
    ids = [f["id"] for f in bpm.FACTORS]
    assert len(ids) == len(set(ids))
    groups = {g["id"] for g in bpm.FACTOR_GROUPS}
    for f in bpm.FACTORS:
        assert f["group"] in groups
        assert f["min"] <= f["default"] <= f["max"], f["id"]
        assert f["kind"] in {"money", "ratio", "int", "multiplier", "fx"}
    assert set(bpm.parse_plan_query({"phins_take": ["0.3"], "x": ["1"], "wacc": [""]})) == {"phins_take"}


def test_technology_section_is_a_live_census():
    census = bpm.technology_census()
    assert census["service_modules"] == portal.count_service_modules()
    assert census["service_modules"] == len(list((ROOT / "services").glob("*.py")))
    assert census["api_modules"] == len(list((ROOT / "web_portal").glob("api_*.py")))
    assert census["repositories"] == len(list((ROOT / "database" / "repositories").glob("*_repository.py")))
    assert census["security_modules"] == len(list((ROOT / "security").glob("*.py")))
    assert census["test_files"] == (len(list((ROOT / "tests").glob("test_*.py")))
                                    + len(list(ROOT.glob("test_*.py"))))


# ---------------------------------------------------------------------------
# Document: narrative placeholders, renderers, committed outputs
# ---------------------------------------------------------------------------
def test_every_narrative_placeholder_resolves():
    plan = bpm.compute_plan()
    for key in doc.placeholder_keys():
        path, kind, text = doc.resolve_figure(plan, key)
        assert text and text != "—", (key, path)


def test_markdown_carries_headline_identity():
    md = doc.render_markdown(bpm.compute_plan())
    for needle in ("₪4,518", "25% / 75%", "230,554 / 471,621", "₪6.0M / ₪24M / ₪30M",
                   "# Part I — Business plan", "# Part II — Investor deck", "# Part III — Appendices",
                   "## Appendix A", "## Appendix H", "all identities hold"):
        assert needle in md, needle
    assert "SOC 2" not in md and "SOC2" not in md


def test_committed_outputs_equal_a_fresh_render():
    """Data integrity: the served plan is exactly what the model renders now."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_business_plan as build

    for path, text in build.outputs().items():
        assert path.is_file(), path
        assert _read(path) == text, f"{path.name} is stale; run scripts/build_business_plan.py"


def test_html_carries_the_phins_letterhead_standard():
    html = _read(HTML)
    assert 'class="phins-letterhead"' in html
    assert "/phins-logo.svg" in html
    assert doc.BRAND_TAGLINE.replace("&", "&amp;") in html
    assert "#c9a04e" in html and "#0e2f63" in html
    assert "linear-gradient(135deg, #060d1f 0%, #0e2f63 46%, #123f82 100%)" in html
    assert "Space+Grotesk" in html and "family=Inter" in html
    assert "print-color-adjust: exact" in html
    assert "ui-clarity.js" in html  # injector skip marker
    assert "phins-doc-return.js" in html
    assert html.rfind("phins-doc-return.js") < html.rfind("</body>")
    assert "/platform-facts.js" in html
    assert "printWindow.document.write" not in html
    assert "SOC 2" not in html and "SOC2" not in html


def test_html_binds_live_facts_and_bakes_canonical_fallbacks():
    html = _read(HTML)
    plan = bpm.compute_plan()
    live = portal.count_service_modules()
    assert f"<span data-live-modules>{live}</span>" in html
    assert 'data-bp="content_hash" data-fmt="hash"' in html
    assert plan["content_hash"][:16] in html
    # a few baked fallbacks equal the Python formatter at defaults
    fx = plan["presentation"]["fx_usd_ils"]
    g = plan["group"]["rows"][4]
    assert (f'<span data-bp="group.rows.4.phins_revenue" data-fmt="ilsm">'
            f'{doc.fmt(g["phins_revenue"], "ilsm", fx)}</span>') in html
    assert (f'<span data-bp="anchor_book.rows.2.eoy_in_force" data-fmt="int">'
            f'{doc.fmt(plan["anchor_book"]["rows"][2]["eoy_in_force"], "int")}</span>') in html
    # the factor register is embedded for the panel
    embedded = json.loads(re.search(r'<script type="application/json" id="bp-factors">(.*?)</script>',
                                    html, re.S).group(1))
    assert [f["id"] for f in embedded] == [f["id"] for f in bpm.FACTORS]
    assert "/api/business-plan/model" in html


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available for formatter parity")
def test_browser_and_python_formatters_agree():
    html = _read(HTML)
    js = re.search(r"<script>\s*(\(function \(\) \{\s+'use strict';.*?)</script>", html, re.S).group(1)
    fmt_src = re.search(r"(function moneyM.*?)\n  function getPath", js, re.S).group(1)
    samples = [
        (54216000.0, "ilsm"), (-18846000.0, "ilsm"), (3747265344.0, "ilsm"), (24000000.0, "ilsm0"),
        (749074460.0, "usdm"), (4518.0, "ils"), (376.5, "ils2"), (230554.0, "int"), (0.25, "pct"),
        (-1.39, "pct"), (0.0566, "pct1"), (4.0, "x"), (2.5, "x"), (3.68, "num2"), (1.255, "num3"),
        (3.82, "months"), (2029, "year"), (True, "bool"), (False, "canonical"),
        ("9128223e1c2223881e0eca64ae6922654b79d52bb2eed151beb726f3c4c1589f", "hash"),
    ]
    script = (
        "var fx = 3.68;\n" + fmt_src + "\n"
        + "var samples = " + json.dumps(samples) + ";\n"
        + "process.stdout.write(JSON.stringify(samples.map(function (s) { return fmt(s[0], s[1]); })));"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [doc.fmt(v, k, 3.68) for v, k in samples]


def test_pdf_edition_is_registered_and_present():
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_investor_pdfs as gen

    pairs = {(src, pdf) for src, pdf, _ in gen.DOCUMENTS}
    assert ("investor-docs/phins-unified-business-plan.md",
            "investor-docs/phins-unified-business-plan.pdf") in pairs
    assert PDF.is_file() and PDF.stat().st_size > 50_000
    assert _read(PDF.with_suffix(".md")).startswith("# PHINS — Unified Business Plan")


# ---------------------------------------------------------------------------
# Surfaces: HTTP endpoint, static page, pitch-dashboard card
# ---------------------------------------------------------------------------
def _get_json(url: str):
    with urllib.request.urlopen(url, timeout=30) as resp:
        assert resp.status == 200
        return json.loads(resp.read().decode("utf-8"))


def test_business_plan_model_http_endpoint():
    payload = _get_json(f"{BASE}/api/business-plan/model")
    local = bpm.compute_plan()
    assert payload["canonical"] is True
    assert payload["integrity"]["all_hold"] is True
    assert payload["content_hash"] == local["content_hash"]
    assert payload["anchor_book"]["rows"][2]["eoy_in_force"] == 230554
    assert payload["partner_markets"]["launches"]["2028"] == 1
    assert "error" not in payload
    q = urllib.parse.urlencode({"phins_take": "0.30", "new_markets_2028": "2", "bogus": "1"})
    scenario = _get_json(f"{BASE}/api/business-plan/model?{q}")
    assert scenario["canonical"] is False
    assert scenario["errors"] == []
    assert scenario["inputs"]["phins_take"] == 0.3
    assert scenario["inputs"]["new_markets_2028"] == 2.0
    assert scenario["integrity"]["all_hold"] is True
    fallback = _get_json(f"{BASE}/api/business-plan/model?phins_take=9")
    assert fallback["inputs"]["phins_take"] == 0.25
    assert fallback["errors"] == ["phins_take must be between 0.05 and 0.6"]


def test_business_plan_page_and_editions_are_served():
    for rel in ("/business-plan.html", "/investor-docs/phins-unified-business-plan.md",
                "/investor-docs/phins-unified-business-plan.pdf"):
        with urllib.request.urlopen(f"{BASE}{rel}", timeout=30) as resp:
            assert resp.status == 200, rel
            body = resp.read()
    with urllib.request.urlopen(f"{BASE}/business-plan.html", timeout=30) as resp:
        body = resp.read().decode("utf-8")
    assert 'class="phins-letterhead"' in body
    assert "Unified business plan" in body


def test_pitch_dashboard_links_the_unified_plan_in_investor_documents():
    text = _read(STATIC / "pitch-dashboard.html")
    assert 'id="unified-business-plan-card"' in text
    card = text.index('id="unified-business-plan-card"')
    assert text.index('id="investor-documents-section"') < card
    assert card < text.index("Unicorn · Series A · Institutional")
    for href in ("/business-plan.html", "/business-plan.html#part-deck",
                 "/business-plan.html#part-appendices",
                 "/investor-docs/phins-unified-business-plan.pdf",
                 "/investor-docs/phins-unified-business-plan.md",
                 "/api/business-plan/model"):
        assert f'href="{href}"' in text, href
    # the card restates this page's Israel identity verbatim
    assert "ILS 4,518 · 25% / 75% · 24,000 / 94,080 / 230,554" in text


# ---------------------------------------------------------------------------
# Charts: one layout engine, same data in HTML, live API and PDF
# ---------------------------------------------------------------------------
from services import business_plan_charts as charts  # noqa: E402
from services import business_plan_portrait as portrait  # noqa: E402
from services import business_plan_sources as sources  # noqa: E402

CHART_IDS = ["in_force", "revenue_ebitda", "gwp_split", "cash_curve", "carrier_view",
             "use_of_funds", "appraisal_sensitivity", "roadmap"]


def test_chart_specs_read_the_plan_not_a_second_model():
    plan = bpm.compute_plan()
    specs = {s["id"]: s for s in charts.chart_specs(plan)}
    assert list(specs) == CHART_IDS
    g = plan["group"]["rows"]
    il = plan["anchor_book"]["rows"]
    pm = plan["partner_markets"]["rows"]
    inf = specs["in_force"]["series"]
    assert inf[0]["values"] == [r["eoy_in_force"] for r in il]
    assert inf[1]["values"] == [r["eoy_in_force"] for r in pm]
    assert [a + b for a, b in zip(inf[0]["values"], inf[1]["values"])] == [r["eoy_in_force"] for r in g]
    rev = {s["label"]: s["values"] for s in specs["revenue_ebitda"]["series"]}
    assert rev["PHINS revenue"] == [r["phins_revenue"] for r in g]
    assert rev["EBITDA"] == [r["ebitda"] for r in g]
    split = specs["gwp_split"]["series"]
    for i, r in enumerate(g):
        assert sum(s["values"][i] for s in split) == pytest.approx(r["risk_gwp"])
    steps = specs["carrier_view"]["steps"]
    assert steps[0]["value"] == plan["carrier_view"]["rows"][2]["risk_gwp"]
    assert sum(s["value"] for s in steps[:-1]) == pytest.approx(steps[-1]["value"])
    uof = specs["use_of_funds"]["segments"]
    assert sum(s["value"] for s in uof) == pytest.approx(plan["funding"]["seed"])
    assert sum(s["share"] for s in uof) == pytest.approx(1.0)
    cash = specs["cash_curve"]
    assert cash["series"][0]["values"] == [r["cumulative_ebitda"] for r in g[:len(cash["categories"])]]
    assert cash["refs"][0]["value"] == -plan["funding"]["seed"]


def test_appraisal_sensitivity_grid_is_the_same_formula():
    plan = bpm.compute_plan()
    sens = plan["appraisal"]["sensitivity"]
    assert sens["wacc"] == [0.25, 0.3, 0.35, 0.4, 0.45]
    assert sens["exit_multiple"] == [3.0, 4.0, 5.0]
    assert sens["pre_money"][2][1] == pytest.approx(plan["appraisal"]["central_pre_money"])
    # monotone: higher WACC lowers, higher exit raises
    for row in sens["pre_money"]:
        assert row == sorted(row)
    for j in range(3):
        col = [row[j] for row in sens["pre_money"]]
        assert col == sorted(col, reverse=True)
    spec = charts.chart_by_id(plan, "appraisal_sensitivity")
    assert spec["highlight"] == [2, 1]
    # the grid never enters the content hash — it is a view, not an input
    assert plan["content_hash"] == bpm.content_hash(plan)


def test_appraisal_sensitivity_grid_holds_at_the_factor_extremes():
    """Every value the factor panel accepts keeps the plan on the grid, so the
    heatmap always has a cell to render."""
    for overrides in ({"exit_multiple": 30.0}, {"exit_multiple": 0.5},
                      {"wacc": 0.90}, {"wacc": 0.05},
                      {"wacc": 0.90, "exit_multiple": 30.0}):
        plan = bpm.compute_plan(overrides)
        assert plan["errors"] == []
        sens = plan["appraisal"]["sensitivity"]
        assert round(plan["appraisal"]["wacc"], 4) in sens["wacc"]
        assert round(plan["appraisal"]["exit_multiple"], 4) in sens["exit_multiple"]
        assert all(len(row) == len(sens["exit_multiple"]) for row in sens["pre_money"])
        spec = charts.chart_by_id(plan, "appraisal_sensitivity")
        assert spec["highlight"] != [-1, -1]
        rendered = {c["id"]: c for c in charts.render_all(plan)}
        assert rendered["appraisal_sensitivity"]["svg"]


def test_roadmap_gantt_follows_the_factors():
    plan = bpm.compute_plan()
    items = charts.roadmap_items(plan)
    labels = [i["label"] for i in items]
    assert "Partner cohort 2028 — 1 market live" in labels
    assert "Partner cohort 2029 — 2 markets live" in labels
    assert "Gate 7 — 24,000 in force · Series A readiness" in labels
    assert "Series A ₪18.0M (indicative)" in labels
    assert "Group EBITDA positive (2029)" in labels
    assert "10 markets on one platform" in labels
    none = bpm.compute_plan({"new_markets_2028": 0, "new_markets_2029": 0,
                             "new_markets_2030": 0, "new_markets_2031": 0})
    labels0 = [i["label"] for i in charts.roadmap_items(none)]
    assert not any(l.startswith("Partner cohort") for l in labels0)
    assert "1 markets on one platform" in labels0


def test_chart_svg_and_reportlab_share_one_layout():
    plan = bpm.compute_plan()
    for spec in charts.chart_specs(plan):
        ops = charts.layout(spec)
        svg = charts.render_svg(spec)
        assert svg.startswith("<svg") and svg.endswith("</svg>")
        assert f'data-chart="{spec["id"]}"' in svg
        texts = [op[3] for op in ops if op[0] == "text"]
        for t in texts:
            assert charts._esc(t) in svg
        drawing = charts.render_reportlab(spec, 480)
        assert len(drawing.contents) == len(ops)
        header, rows = charts.chart_table(spec)
        assert rows and all(len(r) == len(header) for r in rows)
    # labels equal the document formatter for the kinds the charts use
    assert charts.label(54216000.0, "ilsm") == doc.fmt(54216000.0, "ilsm")
    assert charts.label(-18846000.0, "ilsm") == doc.fmt(-18846000.0, "ilsm")
    assert charts.label(230554, "int") == doc.fmt(230554, "int")
    assert charts.label(0.35, "pct") == doc.fmt(0.35, "pct")
    assert charts.label(4.0, "x") == doc.fmt(4.0, "x")


def test_chart_directive_round_trips_for_the_pdf():
    plan = bpm.compute_plan()
    for spec in charts.chart_specs(plan):
        line = charts.directive(spec)
        assert line.startswith("<!-- phins-chart ") and line.endswith(" -->")
        assert "--" not in line[len("<!-- phins-chart "):-len(" -->")]
        assert charts.parse_directive(line) == json.loads(json.dumps(spec))
    assert charts.parse_directive("<!-- not a chart -->") is None


def test_document_places_every_chart_once_per_surface():
    plan = bpm.compute_plan()
    html = doc.render_html(plan)
    md = doc.render_markdown(plan)
    placed = (set(sum(doc.SECTION_CHARTS.values(), [])) | set(doc.SLIDE_CHARTS.values())
              | set(sum(doc.APPENDIX_CHARTS.values(), [])))
    assert placed == set(CHART_IDS)
    for cid in CHART_IDS:
        assert f'data-chart-id="{cid}"' in html
        assert f'data-chart="{cid}"' in html
        assert f'"id": "{cid}"' in md
    assert html.count('<figure class="bp-chart"') == md.count("<!-- phins-chart ")
    # the Markdown shows the chart data as a table beside each directive
    assert "| Series | 2027 | 2028 | 2029 | 2030 | 2031 |" in md
    expected_total = "| Total | " + " | ".join(
        f"{int(round(r['eoy_in_force'])):,}" for r in plan["group"]["rows"]) + " |"
    assert expected_total in md
    assert "| WACC \\ exit multiple | 3.0× | 4.0× | 5.0× |" in md
    # the page swaps server SVG on refresh and the API supplies it
    assert "charts=1" in html and "function applyCharts" in html


def test_model_endpoint_returns_charts_on_request():
    base = _get_json(f"{BASE}/api/business-plan/model")
    assert "charts" not in base
    payload = _get_json(f"{BASE}/api/business-plan/model?charts=1&phins_take=0.30")
    assert [c["id"] for c in payload["charts"]] == CHART_IDS
    local = bpm.compute_plan({"phins_take": 0.30})
    for c, spec in zip(payload["charts"], charts.chart_specs(local)):
        assert c["svg"] == charts.render_svg(spec)
        header, rows = charts.chart_table(spec)
        assert c["table"] == {"header": header, "rows": rows}


def test_pdf_generator_draws_chart_directives_and_skips_comments():
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_investor_pdfs as gen
    from reportlab.graphics.shapes import Drawing

    plan = bpm.compute_plan()
    spec = charts.chart_by_id(plan, "in_force")
    md = "\n".join(["# T", "", charts.directive(spec), "", "<!-- plain comment -->", "", "Body."])
    story = gen.markdown_to_story(md, "T", gen._styles())
    drawings = [f for f in story if isinstance(f, Drawing)]
    assert len(drawings) == 1
    assert not any("plain comment" in getattr(f, "text", "") for f in story)


# ---------------------------------------------------------------------------
# Data sources (Appendix I) stay in sync with the Scenario Lab registry
# ---------------------------------------------------------------------------
def _dashboard_registry():
    text = _read(STATIC / "pitch-dashboard.html")
    pat = re.compile(r"(\w+): \{\s*title: \"([^\"]+)\",\s*url: \"([^\"]+)\",\s*note: \"([^\"]*)\",\s*"
                     r"sourceType: \"([^\"]+)\",\s*evidenceStrength: \"([^\"]+)\"")
    return {m.group(1): {"title": m.group(2), "url": m.group(3), "note": m.group(4),
                         "type": m.group(5), "strength": m.group(6)} for m in pat.finditer(text)}


def test_research_registry_equals_the_scenario_lab_registry():
    dash = _dashboard_registry()
    assert dash, "sourceRegistry not found on the pitch dashboard"
    assert set(sources.RESEARCH_SOURCES) == set(dash)
    for key, entry in dash.items():
        assert sources.RESEARCH_SOURCES[key] == entry, key
    linked = {k for keys in sources.MARKET_SOURCES.values() for k in keys}
    assert linked <= set(sources.RESEARCH_SOURCES)
    assert set(sources.MARKET_SOURCES) == {m["id"] for m in bpm.MARKETS}


def test_lineage_marks_research_as_reference_only_and_lists_every_market():
    plan = bpm.compute_plan()
    research = [r for r in sources.LINEAGE if r["kind"].startswith("External research")]
    assert research and all(r["feeds_model"] is False for r in research)
    assert all(r["feeds_model"] is False for r in sources.LINEAGE if "census" in r["figure"].lower())
    rows = doc.data_source_rows(plan)
    assert {r["market"] for r in rows} == {m["name"] for m in plan["markets"]}
    html = doc.render_html(plan)
    md = doc.render_markdown(plan)
    for r in rows:
        assert r["url"] in md
        assert f'href="{html_lib.escape(r["url"], quote=True)}"' in html
    assert 'id="appendix-i"' in html and "## Appendix I — Data sources and figure lineage" in md


# ---------------------------------------------------------------------------
# Founder credentials and the processed portrait
# ---------------------------------------------------------------------------
def test_founder_section_and_slide_carry_credentials():
    plan = bpm.compute_plan()
    html = doc.render_html(plan)
    md = doc.render_markdown(plan)
    assert [s["id"] for s in doc.plan_sections()][-1] == "founder"
    assert "Founder" in [s["title"] for s in doc.deck_slides()]
    for text in (html, md):
        assert doc.FOUNDER["name"] in text
        assert "Licensed insurance broker" in text and "Advocate (Adv.)" in text
        assert "26 May 2026" in text and "12 October 2026" in text
        assert doc.FOUNDER_PORTRAIT_URL in text
    live = portal.count_service_modules()
    assert f"{live:,} service modules" in md  # credential placeholders are filled
    assert 'class="bp-founder-photo' in html and 'class="bp-monogram"' in html


def _image_bytes(w=600, h=900, orientation=None, mode="RGB"):
    from io import BytesIO
    from PIL import Image
    img = Image.new(mode, (w, h), (40, 60, 120) if mode == "RGB" else (40, 60, 120, 255))
    buf = BytesIO()
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        img.convert("RGB").save(buf, "JPEG", exif=exif.tobytes())
    else:
        img.save(buf, "PNG" if mode == "RGBA" else "JPEG")
    return buf.getvalue()


def test_process_portrait_squares_resizes_and_honours_exif():
    from io import BytesIO
    from PIL import Image
    out, mime = portrait.process_portrait(_image_bytes(600, 900))
    assert mime == "image/jpeg"
    img = Image.open(BytesIO(out))
    assert img.size == (portrait.PORTRAIT_SIZE, portrait.PORTRAIT_SIZE) and img.format == "JPEG"
    out2, _ = portrait.process_portrait(_image_bytes(600, 900, orientation=6))
    assert Image.open(BytesIO(out2)).size == (portrait.PORTRAIT_SIZE, portrait.PORTRAIT_SIZE)
    out3, _ = portrait.process_portrait(_image_bytes(400, 400, mode="RGBA"))
    assert Image.open(BytesIO(out3)).mode == "RGB"
    with pytest.raises(portrait.PortraitError):
        portrait.process_portrait(b"not an image")
    with pytest.raises(portrait.PortraitError):
        portrait.process_portrait(b"")
    assert portrait.portrait_cache_key("a", "x") != portrait.portrait_cache_key("a", "y")


def test_founder_portrait_placement_is_an_image_slot_served_processed():
    assert portal.MEDIA_PLACEMENT_SLOTS["founder_portrait_id"] == "image"
    assert portal.PAGE_MEDIA_PUBLIC_URLS["founder_portrait_id"] == "founder_portrait_url"
    assert "founder_portrait_id" in portal.DESIGN_SETTINGS
    admin = _read(STATIC / "admin-media.html")
    assert "field: 'founder_portrait_id', kind: 'image'" in admin
    assert 'id="assign-founder-portrait"' in admin

    import tempfile
    from io import BytesIO
    from PIL import Image

    saved = portal.DESIGN_SETTINGS.get("founder_portrait_id", "")
    asset_id = "media-test-founder-portrait"
    payload = _image_bytes(300, 500)
    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, dir=portal.MEDIA_STORAGE_DIR)
    try:
        tmp.write(payload)
        tmp.close()
        portal.MEDIA_ASSETS[asset_id] = {
            "id": asset_id, "name": "IMG_4538.jpeg", "type": "image", "format": "image/jpeg",
            "url": f"/media-files/{asset_id}/IMG_4538_jpeg", "data": "", "source": "upload",
            "file_path": tmp.name, "checksum": portal.compute_media_checksum(payload),
        }
        portal.DESIGN_SETTINGS["founder_portrait_id"] = ""
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"{BASE}/api/business-plan/founder-portrait", timeout=30)
        assert exc.value.code == 404
        portal.DESIGN_SETTINGS["founder_portrait_id"] = asset_id
        with urllib.request.urlopen(f"{BASE}/api/business-plan/founder-portrait", timeout=30) as resp:
            assert resp.status == 200
            assert resp.headers["Content-Type"] == "image/jpeg"
            etag = resp.headers["ETag"]
            body = resp.read()
        assert Image.open(BytesIO(body)).size == (portrait.PORTRAIT_SIZE, portrait.PORTRAIT_SIZE)
        req = urllib.request.Request(f"{BASE}/api/business-plan/founder-portrait",
                                     headers={"If-None-Match": etag})
        with pytest.raises(urllib.error.HTTPError) as not_modified:
            urllib.request.urlopen(req, timeout=30)
        assert not_modified.value.code == 304
        public = _get_json(f"{BASE}/api/design/settings")
        assert public["founder_portrait_url"] == f"/media-files/{asset_id}/IMG_4538_jpeg"
        assert "founder_portrait_id" not in public
        # the stored original is untouched
        assert Path(tmp.name).read_bytes() == payload
    finally:
        portal.DESIGN_SETTINGS["founder_portrait_id"] = saved
        portal.MEDIA_ASSETS.pop(asset_id, None)
        portal._FOUNDER_PORTRAIT_CACHE.clear()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
