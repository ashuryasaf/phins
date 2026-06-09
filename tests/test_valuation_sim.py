"""
Tests for the investor valuation simulation (actuarial appraisal).

Covers the deterministic Monte-Carlo appraisal that lets the pitch-dashboard
pre-money valuation optionally derive from an actuarial simulation:
- determinism (same seed/params -> identical distribution + content hash),
- percentile ordering and percentile selection,
- the central (deterministic) case reconciles to the appraisal formula applied
  to the published Israel income model,
- the public, read-only ``/api/investor/valuation-sim`` HTTP endpoint.
"""

from __future__ import annotations

import json
import os
import urllib.request

import web_portal.server as portal


def test_valuation_sim_deterministic():
    p = {"seed": 20270101, "runs": 3000, "percentile": 50}
    a = portal.compute_investor_valuation_sim(dict(p))
    b = portal.compute_investor_valuation_sim(dict(p))
    assert a["content_hash"] == b["content_hash"]
    assert a["pre_money"] == b["pre_money"]
    assert a["deterministic"] is True


def test_valuation_sim_percentiles_ordered_and_selectable():
    base = {"seed": 20270101, "runs": 4000}
    d = portal.compute_investor_valuation_sim(dict(base, percentile=50))["distribution"]
    assert d["p10"] <= d["p25"] <= d["p50"] <= d["p75"] <= d["p90"]
    p25 = portal.compute_investor_valuation_sim(dict(base, percentile=25))["pre_money"]
    p75 = portal.compute_investor_valuation_sim(dict(base, percentile=75))["pre_money"]
    assert p25 <= p75


def test_valuation_sim_central_reconciles_to_income_model():
    # Central (deterministic) pre-money must equal the appraisal formula applied
    # to the exact published IL income-model drivers — no hidden inputs.
    b = portal._INV_VAL_BASE
    expected = portal._inv_appraisal_pre_money(
        b["in_force"], b["premium"], b["take_rate"], b["opex"],
        0.35, 4.0, "net_revenue", 0.15,
    )
    out = portal.compute_investor_valuation_sim({
        "wacc": 0.35, "exit_multiple": 4.0, "exit_metric": "net_revenue", "prudence": 0.15,
    })
    assert out["central"] == round(expected)
    # Sanity band consistent with the ₪24M manual default.
    assert 18_000_000 <= out["central"] <= 28_000_000


def test_valuation_sim_http_endpoint():
    base = os.environ.get("TEST_BASE_URL", "http://localhost:8000")
    url = f"{base}/api/investor/valuation-sim?seed=20270101&runs=2000&percentile=50"
    with urllib.request.urlopen(url, timeout=30) as resp:
        assert resp.status == 200
        d = json.loads(resp.read().decode("utf-8"))
    assert d["pre_money"] > 0
    assert d["currency"] == "ILS"
    assert d["distribution"]["p25"] <= d["distribution"]["p75"]
    assert len(d["content_hash"]) == 64
