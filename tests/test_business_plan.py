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

import json
import os
import re
import shutil
import subprocess
import sys
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
