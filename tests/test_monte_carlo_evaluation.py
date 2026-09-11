"""
Tests for the Monte Carlo methodology evaluation service and its BI route.

The service is diagnostic BI: it must be deterministic, read-only, bounded,
and must report every PHINS assumption it evaluated. These tests pin those
contracts plus the HTTP wiring (``GET /api/bi/monte-carlo-evaluation``).
"""

from __future__ import annotations

import copy
import json
import os

import pytest
import requests

from services import monte_carlo_evaluation_service as mc
from web_portal import api_bi_analytics as bi

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")

_FAST = mc.EvaluationParams(seed=7, lives=300, trials=40, horizon_years=3, bootstrap_samples=20)


@pytest.fixture(scope="module")
def report():
    return mc.run_evaluation(_FAST)


# ── statistics toolkit ───────────────────────────────────────────────────────

def test_auc_perfect_and_random_and_degenerate():
    assert mc.auc_score([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == 1.0
    assert mc.auc_score([0.9, 0.8, 0.2, 0.1], [0, 0, 1, 1]) == 0.0
    assert mc.auc_score([0.5, 0.5, 0.5, 0.5], [0, 1, 0, 1]) == 0.5
    assert mc.auc_score([0.1, 0.2], [1, 1]) is None


def test_brier_and_wilson_bounds():
    assert mc.brier_score([1.0, 0.0], [1, 0]) == 0.0
    assert mc.brier_score([0.0, 1.0], [1, 0]) == 1.0
    lo, hi = mc.wilson_interval(5, 50)
    assert 0.0 <= lo < 0.1 < hi <= 1.0
    assert mc.wilson_interval(0, 0) == (0.0, 0.0)


def test_spearman_monotone_relationships():
    assert mc.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert mc.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


# ── parameter handling ───────────────────────────────────────────────────────

def test_params_from_query_coerces_and_caps():
    p = mc.params_from_query({
        "seed": "42", "lives": "999999999", "trials": "1", "horizon_years": "500",
        "bootstrap": "abc", "modules": "risk,bogus,ai", "world.fraud_rate": "0.2",
        "world.smoker_mortality_rr": "not-a-number",
    })
    assert p.seed == 42
    assert p.lives == mc.MAX_LIVES
    assert p.trials == 20  # floor
    assert p.horizon_years == mc.MAX_HORIZON_YEARS
    assert p.bootstrap_samples == 200  # default when unparsable
    assert p.modules == ("risk", "ai")
    assert p.world.fraud_rate == 0.2
    assert p.world.smoker_mortality_rr == mc.WorldAssumptions().smoker_mortality_rr


def test_params_from_query_defaults_when_empty():
    p = mc.params_from_query(None)
    assert p.modules == mc.ALL_MODULES
    assert p.lives == 2_000 and p.trials == 400


# ── integrity contract ───────────────────────────────────────────────────────

def test_run_is_deterministic_for_same_seed(report):
    again = mc.run_evaluation(_FAST)
    assert again["integrity"]["results_sha256"] == report["integrity"]["results_sha256"]
    assert again["results"] == report["results"]


def test_different_seed_changes_results():
    other = mc.run_evaluation(mc.EvaluationParams(seed=8, lives=300, trials=40, horizon_years=3, bootstrap_samples=20))
    assert other["integrity"]["results_sha256"] != mc.run_evaluation(_FAST)["integrity"]["results_sha256"]


def test_observed_inputs_are_never_mutated():
    observed = {
        "policies": {"P1": {"status": "active", "monthly_premium": 120.0},
                     "P2": {"status": "cancelled", "monthly_premium": 50.0}},
        "claims": {"C1": {"status": "approved", "approved_amount": 900}},
    }
    snapshot = copy.deepcopy(observed)
    out = mc.run_evaluation(mc.EvaluationParams(seed=3, lives=200, trials=30, modules=("sales",)), observed=observed)
    assert observed == snapshot
    assert out["integrity"]["observed_inputs_unchanged"] is True
    assert out["observed_inputs"]["used"] is True
    assert out["observed_inputs"]["observed_mrr"] == 120.0
    assert out["results"]["sales"]["mrr_source"] == "observed_policies"
    assert out["results"]["sales"]["mrr_start"] == 120.0


def test_phins_configuration_is_untouched_by_a_run(report):
    from services.actuarial_service import get_actuarial_store
    store = get_actuarial_store()
    before = json.dumps(store.public_config_dict(), sort_keys=True, default=str)
    tables_before = json.dumps(store.get_current_tables(), sort_keys=True, default=str)
    mc.run_evaluation(_FAST)
    assert json.dumps(store.public_config_dict(), sort_keys=True, default=str) == before
    assert json.dumps(store.get_current_tables(), sort_keys=True, default=str) == tables_before


def test_integrity_block_and_provenance(report):
    integrity = report["integrity"]
    assert integrity["read_only"] is True
    assert integrity["side_effects"] == []
    assert integrity["synthetic_population"] is True
    for key in ("parameters_sha256", "world_assumptions_sha256", "phins_assumptions_sha256", "results_sha256"):
        assert len(integrity[key]) == 64
    assert integrity["phins_assumptions_sha256"] == mc._sha256_of(report["phins_assumptions"])
    assert integrity["results_sha256"] == mc._sha256_of(report["results"])
    sources = {p["source"].split(":")[0] for p in report["assumption_provenance"]}
    assert "services/actuarial_service.py" in sources
    assert "services/underwriting_risk_scoring.py" in sources
    assert "services/claims_bot_service.py" in sources
    assert "services/llm_providers.py" in sources


def test_report_is_json_serialisable(report):
    json.dumps(report, default=str)


# ── module outputs ───────────────────────────────────────────────────────────

def test_all_modules_present_with_core_metrics(report):
    res = report["results"]
    assert set(res) == set(mc.ALL_MODULES)

    risk = res["risk"]
    assert risk["lives"] == 300
    assert risk["auc"] is None or 0.0 <= risk["auc"] <= 1.0
    assert 0.0 <= risk["brier_score_raw"] <= 1.0
    assert risk["score_is_probability"] is False
    assert sum(row["n"] for row in risk["calibration_by_band"]) == 300
    assert abs(sum(risk["recommendation_mix"].values()) - 1.0) < 1e-6

    uw = res["underwriting"]
    assert uw["priced"] + round(uw["declined_share"] * uw["lives"]) == uw["lives"]
    assert uw["portfolio_annual_premium"] > 0
    assert {row["decline_threshold_adl"] for row in uw["decline_threshold_sensitivity"]} == {8, 9, 10}
    assert uw["auto_approval"]["evaluated_as_if_enabled"] is True
    assert uw["reinsurance_band_true_world"] in {"low", "medium", "high", "very_high"}

    actu = res["actuarial"]
    assert actu["trials"] == 40
    assert actu["year1_loss_ratio_pct"]["n"] == 40
    assert 0.0 <= actu["probability_year1_lr_exceeds_100pct"] <= 1.0
    assert 0.0 <= actu["reserve_rule_150pct"]["probability_year1_claims_within_reserve"] <= 1.0
    assert 0.0 <= actu["ibnr"]["probability_reserve_config_ibnr_sufficient"] <= 1.0
    assert actu["ibnr"]["reserve_config_ibnr_pct_of_claims"] == 10.0
    assert actu["ibnr"]["reserves_reporting_ibnr_pct_of_premium"] == pytest.approx(9.75)
    assert len(actu["loss_ratio_by_year_mean_pct"]) == 3
    assert abs(sum(actu["reinsurance_band_distribution_year1"].values()) - 1.0) < 1e-3

    claims = res["claims"]
    assert claims["claims_simulated"] >= 1000
    assert claims["mirror_agreement_with_live_recommender"] == 1.0
    live = claims["live_thresholds"]
    assert abs(live["auto_approve_share"] + live["auto_deny_share"] + live["manual_share"] - 1.0) < 1e-6
    assert len(claims["threshold_sweep"]) == 9

    sales = res["sales"]
    assert sales["phins_forecast"]["monthly_growth"] == 0.05
    assert sales["phins_forecast"]["implied_annual_growth_pct"] == pytest.approx(79.59, abs=0.01)
    assert [c["month"] for c in sales["checkpoints"]] == [3, 6, 12]
    assert sales["mrr_source"] == "synthetic_portfolio"

    ai = res["ai"]
    assert ai["live_thresholds"]["accept"] == 0.90 and ai["live_thresholds"]["review"] == 0.70
    assert ai["advisory_cap_forces_full_human_review"] is True
    capped = ai["review_disposition_with_advisory_cap"]["disposition_mix"]
    assert capped["needs_review"] == 1.0
    assert len(ai["threshold_sweep"]) == 6
    assert 0.0 <= ai["underwriting_automation"]["manual_share"] <= 1.0


def test_claims_mirror_matches_live_recommender_on_edge_cases():
    # Direct check of the movable-threshold mirror against the live rules.
    from services.claims_bot_service import ClaimsBotService, FraudIndicator, FraudIndicatorType, HiddenCondition
    bot = ClaimsBotService.__new__(ClaimsBotService)
    cases = [
        (0.90, [], [], True), (0.72, [], [], False), (0.72, [0.85], [], True),
        (0.50, [], [("causal", 0.6)], True), (0.50, [], [("causal", 0.6)], False),
        (0.40, [0.65], [], False), (0.40, [], [], False), (0.60, [], [], False),
        (0.75, [], [("noncausal", 0.5)], True),
    ]
    for auth, sev, hidden_spec, within in cases:
        indicators = [FraudIndicator(id="x", indicator_type=FraudIndicatorType.AMOUNT_SUSPICIOUS, severity=s,
                                     evidence=[], explanation="", recommendation="",
                                     requires_investigation=s > 0.6) for s in sev]
        hidden = [HiddenCondition(condition_name="c", icd_code="", evidence_source="", detection_confidence=0.8,
                                  estimated_onset_date=None, was_before_policy=True,
                                  causal_link_to_claim=(kind == "causal"), severity="moderate",
                                  deliberate_concealment_score=score) for kind, score in hidden_spec]
        live, _, _ = bot._make_recommendation(auth, indicators, hidden, within, {})
        mirror = mc._recommend_with_thresholds(
            auth, any(s > 0.8 for s in sev), any(s > 0.6 for s in sev), bool(hidden),
            any(kind == "causal" for kind, _ in hidden_spec), within, 0.85, 0.70, 0.45)
        assert mirror == live.value, (auth, sev, hidden_spec, within)


def test_module_selection_limits_output():
    out = mc.run_evaluation(mc.EvaluationParams(seed=1, lives=150, trials=25, modules=("ai",)))
    assert set(out["results"]) == {"ai"}
    assert out["parameters"]["modules"] == ["ai"]
    out = mc.run_evaluation(mc.EvaluationParams(seed=1, lives=150, trials=25, modules=("actuarial",)))
    # actuarial depends on the population + pricing steps but only reports itself
    assert set(out["results"]) == {"actuarial"}


def test_findings_are_structured_and_cover_every_module(report):
    findings = report["findings"]
    assert findings
    areas = {f["area"] for f in findings}
    assert areas == set(mc.ALL_MODULES)
    for f in findings:
        assert f["severity"] in {"info", "warning", "critical"}
        assert f["statement"] and f["recommendation"]


def test_world_assumptions_change_results():
    base = mc.run_evaluation(mc.EvaluationParams(seed=5, lives=300, trials=30, modules=("underwriting",)))
    neutral = mc.WorldAssumptions(smoker_mortality_rr=1.0, smoker_disability_rr=1.0,
                                  former_smoker_mortality_rr=1.0, former_smoker_disability_rr=1.0)
    alt = mc.run_evaluation(mc.EvaluationParams(seed=5, lives=300, trials=30, modules=("underwriting",), world=neutral))
    assert alt["integrity"]["world_assumptions_sha256"] != base["integrity"]["world_assumptions_sha256"]
    assert (alt["results"]["underwriting"]["expected_loss_ratio_true_world_pct"]
            < base["results"]["underwriting"]["expected_loss_ratio_true_world_pct"])


# ── handler + route ──────────────────────────────────────────────────────────

def test_handler_returns_report_and_reads_observed_policies():
    data_sources = {
        "policies": {"P1": {"status": "active", "monthly_premium": 300.0}},
        "claims": {},
    }
    status, payload = bi.handle_monte_carlo_evaluation(
        None, data_sources, {"seed": "11", "lives": "200", "trials": "30", "modules": "sales"})
    assert status == 200
    assert payload["results"]["sales"]["mrr_start"] == 300.0
    assert payload["integrity"]["observed_inputs_unchanged"] is True
    assert data_sources["policies"]["P1"] == {"status": "active", "monthly_premium": 300.0}


def test_handler_returns_500_error_shape_on_failure(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr(mc.MonteCarloEvaluationService, "run", boom)
    status, payload = bi.handle_monte_carlo_evaluation(None, {}, {})
    assert status == 500
    assert set(payload) == {"error"}


def test_route_registered_in_server_source():
    import inspect
    import web_portal.server as server
    src = inspect.getsource(server.PortalHandler.do_GET)
    assert "/api/bi/monte-carlo-evaluation" in src
    assert "handle_monte_carlo_evaluation" in src


class TestHTTP:
    def test_requires_privileged_role(self):
        resp = requests.get(f"{BASE_URL}/api/bi/monte-carlo-evaluation")
        assert resp.status_code == 403
        assert set(resp.json()) == {"error"}

    def test_admin_gets_bounded_report(self):
        login = requests.post(f"{BASE_URL}/api/login", json={"username": "admin", "password": "admin123"})
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        resp = requests.get(
            f"{BASE_URL}/api/bi/monte-carlo-evaluation",
            params={"seed": 5, "lives": 200, "trials": 30, "bootstrap": 10, "modules": "risk,ai"},
            headers=headers, timeout=120,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert set(body["results"]) == {"risk", "ai"}
        assert body["parameters"] == {"seed": 5, "lives": 200, "trials": 30, "horizon_years": 5,
                                      "bootstrap_samples": 10, "modules": ["risk", "ai"]}
        assert body["integrity"]["read_only"] is True
        assert body["integrity"]["observed_inputs_unchanged"] is True
