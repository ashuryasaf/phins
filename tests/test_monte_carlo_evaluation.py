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
    assert len(claims["threshold_sweep"]) == 12
    assert {row["approve_partial"] for row in claims["threshold_sweep"]} == {0.65, 0.70, 0.75, 0.80}

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


def test_reserve_rule_mirrors_phins_portfolio_simulator_basis(tmp_path, monkeypatch):
    """Engine 1.0.1: the 150% rule is 1.5 × PV over the full term, exactly as
    PortfolioSimulator.risk_metrics defines it; the year-1 stress is separate."""
    import services.actuarial_service as asvc
    from services.actuarial_service import ActuarialTablesStore, PortfolioSimulator, SimulationParams

    # Isolated default store: other suites replace the global mortality table.
    monkeypatch.setenv("PHINS_ACTUARIAL_STATE_PATH", str(tmp_path / "act.json"))
    store = ActuarialTablesStore()
    monkeypatch.setattr(asvc, "get_actuarial_store", lambda: store)
    report = mc.run_evaluation(mc.EvaluationParams(seed=7, lives=300, trials=40, horizon_years=2,
                                                   bootstrap_samples=5, modules=("actuarial",)))

    # Pin the PHINS rule itself so a change there forces the mirror to be revisited.
    sim = PortfolioSimulator(store).generate_portfolio(SimulationParams(
        customer_count=60, age_min=25, age_max=55, coverage_min=100_000, coverage_max=300_000,
        coverage_median=200_000, policy_term_mode="fixed", policy_term_fixed=10))
    rm = sim["risk_metrics"]
    assert rm["reserve_requirement"] == pytest.approx(round(rm["total_expected_claims"] * 1.5, 2), abs=0.02)
    assert rm["annual_expected_claims"] * rm["avg_term_years"] == pytest.approx(rm["total_expected_claims"], rel=0.02)

    actu = report["results"]["actuarial"]
    rr = actu["reserve_rule_150pct"]
    assert rr["basis"] == mc.RESERVE_REQUIREMENT_BASIS == "pv_full_term_x1.5"
    assert rr["reserve_requirement"] == pytest.approx(round(actu["phins_simulator_pv_total_claims"] * 1.5, 2), abs=0.02)
    # PV over ~17 years ÷ 1 year of claims: the full-term reserve dwarfs year-1 claims.
    assert rr["reserve_to_annual_expected_claims_multiple"] > 5
    assert rr["probability_year1_claims_within_reserve"] >= 0.99

    st = actu["year1_claims_stress"]
    assert "not a PHINS rule" in st["basis"]
    assert st["stress_requirement"] == pytest.approx(round(st["annual_expected_claims"] * 1.5, 2), abs=0.02)
    assert st["stress_requirement"] < rr["reserve_requirement"]
    assert st["tvar99_multiple_of_annual_expected"] >= st["var99_multiple_of_annual_expected"]
    assert report["engine_version"] == "mc-eval-1.0.1"
    assert report["phins_assumptions"]["reserve_requirement_basis"] == "pv_full_term_x1.5"


def test_reserve_next_move_never_proposes_tightening_a_multiple(report):
    for m in report["next_moves"]:
        if m["id"] in {"act_reserve_multiple", "act_year1_volatility"}:
            assert m["action"]["kind"] in {"investigate", "monitor"}
            assert not ((m["action"].get("target") or {}).get("proposed") or {}).get("reserve_multiple")


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


# ── conclusions and next moves ───────────────────────────────────────────────

def test_conclusions_summarise_every_evaluated_area(report):
    c = report["conclusions"]
    assert c["overall_status"] in {"consistent", "inconsistencies_detected", "anomalies_detected"}
    assert c["headline"]
    assert {a["area"] for a in c["areas"]} == set(report["results"])
    for area in c["areas"]:
        assert area["status"] in {"consistent", "inconsistent", "anomalous"}
        assert area["bi_conclusion"]
        assert area["snapshot_metrics"], "each area must name BI snapshot metrics"
        for mid in area["next_move_ids"]:
            assert any(m["id"] == mid for m in report["next_moves"])
    counts = c["counts"]
    assert counts["next_moves"] == len(report["next_moves"])
    assert counts["adjustable_in_phins"] == sum(1 for m in report["next_moves"] if m["action"]["kind"] == "adjust")
    assert c["bi_usage"] and c["ai_usage"]


def test_next_moves_never_apply_anything_and_declare_how_to_act(report):
    moves = report["next_moves"]
    assert moves, "the evaluated defaults are known to raise advisories"
    assert report["integrity"]["proposals_applied_by_engine"] is False
    assert report["integrity"]["next_moves_sha256"] == mc._sha256_of(moves)
    for m in moves:
        assert m["trigger"] in {"anomaly", "inconsistency", "none"}
        assert m["action"]["kind"] in {"adjust", "redirect", "investigate", "monitor"}
        assert m["action"]["source_ref"], "every advisory must point at the owning code"
        assert m["integrity"]["applied_by_engine"] is False
        if m["action"]["kind"] == "adjust":
            assert m["action"]["adjustable_in_phins"] is True
            assert m["integrity"]["requires_admin_confirmation"] is True
            assert m["integrity"]["verify_live_values_before_apply"] is True
            target = m["action"]["target"]
            assert target["api"] == mc.UW_CONFIG_API
            assert set(target["payload"]) == set(target["proposed"])
            assert set(target["current"]) == set(target["proposed"]), "each proposed key must carry its live value"
        else:
            assert m["action"]["adjustable_in_phins"] is False
            assert m["integrity"]["requires_admin_confirmation"] is False
    # Sorted by priority so the dashboard shows the most urgent first.
    assert [m["priority"] for m in moves] == sorted(m["priority"] for m in moves)


def test_smoker_factor_proposal_is_derived_from_live_config_and_capped(report):
    move = next((m for m in report["next_moves"] if m["id"] == "uw_smoker_demographic_factors"), None)
    assert move is not None, "neutral smoker factors + scorer penalty is a known PHINS anomaly"
    assert move["trigger"] == "anomaly"
    live_cfg = report["phins_assumptions"]["underwriting_config"]
    target = move["action"]["target"]
    for key, value in target["current"].items():
        assert value == live_cfg[key]
    for key, value in target["proposed"].items():
        assert 1.0 <= value <= 3.0
        assert value > target["current"][key]
    assert move["action"]["ui_link"].startswith("/actuary-dashboard.html#section-")


def test_smoker_advisory_scales_live_factor_until_gap_closes():
    def _results(smoker_lr, neutral):
        return {"underwriting": {
            "loss_ratio_by_smoking_status": [
                {"key": "current", "expected_loss_ratio_true_world_pct": smoker_lr},
                {"key": "never", "expected_loss_ratio_true_world_pct": 65.0},
            ],
            "demographic_factors_neutral": neutral, "auto_approval": {}, "decline_threshold_sensitivity": [],
            "expected_loss_ratio_phins_tables_pct": 60.0, "expected_loss_ratio_true_world_pct": 70.0,
            "reinsurance_band_true_world": "standard",
        }}
    ctx = {"assumptions": {"underwriting_config": {
        "smoker_mortality_factor": 1.25, "smoker_disability_factor": 1.25, "decline_threshold": 9}}}

    # A partially set factor with a residual gap is still surfaced, as an assumption gap not an anomaly,
    # and the proposal scales the live factor rather than assuming it is 1.0.
    moves = mc.derive_next_moves(_results(110.0, False), [], ctx, observed_unchanged=True)
    move = next(m for m in moves if m["id"] == "uw_smoker_demographic_factors")
    assert move["trigger"] == "inconsistency"
    assert move["action"]["target"]["current"]["smoker_mortality_factor"] == 1.25
    assert move["action"]["target"]["proposed"]["smoker_mortality_factor"] == round(1.25 * 110.0 / 65.0, 2)

    # Once the gap is inside tolerance no adjustment is proposed.
    moves = mc.derive_next_moves(_results(72.0, False), [], ctx, observed_unchanged=True)
    assert not any(m["id"] == "uw_smoker_demographic_factors" for m in moves)

    # The finding must agree with the advisory: a closed gap is not reported as unclosed.
    def _gap_finding(smoker_lr):
        return next(f for f in mc.derive_findings(_results(smoker_lr, False), ctx)
                    if "loss-ratio gap" in f["statement"])

    closed = _gap_finding(72.0)
    assert closed["severity"] == "info"
    assert "do not close the gap" not in closed["statement"]
    assert "no material gap" in closed["statement"]

    residual = _gap_finding(110.0)
    assert residual["severity"] == "warning"
    assert "do not close the gap" in residual["statement"]


def test_mutated_observed_inputs_raise_a_blocking_anomaly():
    ctx = {"assumptions": {"underwriting_config": {}}}
    moves = mc.derive_next_moves({}, [], ctx, observed_unchanged=False)
    assert moves[0]["id"] == "integrity_observed_inputs_mutated"
    assert moves[0]["priority"] == 0 and moves[0]["action"]["kind"] == "investigate"
    conclusions = mc.derive_conclusions({}, [], moves, _FAST, observed_unchanged=False)
    assert conclusions["overall_status"] == "anomalies_detected"
    assert any(a["area"] == "integrity" and a["status"] == "anomalous" for a in conclusions["areas"])


def test_no_findings_yields_consistent_conclusion():
    conclusions = mc.derive_conclusions({}, [], [], _FAST, observed_unchanged=True)
    assert conclusions["overall_status"] == "consistent"
    assert conclusions["counts"]["next_moves"] == 0


def test_update_config_records_change_reason_in_audit_without_changing_behaviour():
    from services.actuarial_service import ActuarialTablesStore
    store = ActuarialTablesStore()
    before = store.public_config_dict()
    result = store.update_config(
        {"smoker_mortality_factor": before["smoker_mortality_factor"], "change_reason": "  mc-eval results_sha256=abc  "},
        "tester",
    )
    assert result["success"] is True
    entry = store.get_audit_log()[-1]
    assert entry["action"] == "update_config"
    assert entry["details"]["change_reason"] == "mc-eval results_sha256=abc"
    # Unknown/empty reasons are ignored and never stored.
    store.update_config({"smoker_mortality_factor": before["smoker_mortality_factor"], "change_reason": "   "}, "tester")
    assert "change_reason" not in store.get_audit_log()[-1]["details"]
    after = store.public_config_dict()
    volatile = {"config_version", "last_modified", "modified_by", "state_revision"}
    assert {k: v for k, v in after.items() if k not in volatile} == \
        {k: v for k, v in before.items() if k not in volatile}


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
        assert body["integrity"]["proposals_applied_by_engine"] is False
        assert {a["area"] for a in body["conclusions"]["areas"]} == {"risk", "ai"}
        assert isinstance(body["next_moves"], list)
