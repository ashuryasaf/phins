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
    assert report["engine_version"] == "mc-eval-1.0.2"
    assert report["phins_assumptions"]["reserve_requirement_basis"] == "pv_full_term_x1.5"


def test_reserve_next_move_never_proposes_tightening_a_multiple(report):
    for m in report["next_moves"]:
        if m["id"] in {"act_reserve_multiple", "act_year1_volatility"}:
            assert m["action"]["kind"] in {"investigate", "monitor"}
            assert not ((m["action"].get("target") or {}).get("proposed") or {}).get("reserve_multiple")


# ── engine 1.0.2: verdicts follow the remediated source ──────────────────────

def test_ibnr_verdict_uses_75pct_target_within_sampling_error():
    """Production run: 23% IBNR sufficient in 74.7% of 300 trials must pass the
    75% probability-of-sufficiency target (the same quantile the p75 proposal
    targets); 57% of 300 must fail; the two rules are judged the same way."""
    assert mc.IBNR_PROBABILITY_OF_SUFFICIENCY_TARGET == 0.75
    # 224/300 = 74.67% sufficient
    shares = [0.10] * 224 + [0.40] * 76
    prem = [0.05] * 222 + [0.20] * 78  # 74.0% under a 9.75%-of-premium rule
    block = mc._ibnr_block(shares, prem, ibnr_pct=0.23, reserves_reporting_ibnr_pct=9.75,
                           unreported_pct_of_premium_p95=12.0)
    assert block["probability_reserve_config_ibnr_sufficient"] == pytest.approx(0.7467, abs=1e-4)
    lo, hi = block["probability_reserve_config_ibnr_sufficient_ci95"]
    assert lo < 0.75 < hi
    assert block["probability_of_sufficiency_target"] == 0.75
    assert block["reserve_config_ibnr_meets_target"] is True
    assert block["probability_reserves_reporting_ibnr_sufficient"] == pytest.approx(0.74, abs=1e-4)
    assert block["reserves_reporting_ibnr_meets_target"] is True

    weak = mc._ibnr_block([0.10] * 172 + [0.40] * 128, prem, 0.23, 9.75, 12.0)  # 57.3%
    assert weak["reserve_config_ibnr_meets_target"] is False
    assert weak["probability_reserve_config_ibnr_sufficient_ci95"][1] < 0.75

    # The finding and the move agree with the verdict.
    def _actu(ib):
        return {"actuarial": {
            "reserve_rule_150pct": {"probability_year1_claims_within_reserve": 1.0,
                                    "reserve_to_annual_expected_claims_multiple": 26.0},
            "year1_claims_stress": {"probability_year1_claims_within_stress": 0.997, "var99_multiple_of_annual_expected": 1.47,
                                    "tvar99_multiple_of_annual_expected": 1.6},
            "eligible_lives": 1939, "ibnr": ib,
            "probability_year1_lr_exceeds_100pct": 0.023, "loss_ratio_assumption_pct": 65.0,
            "probability_year1_lr_exceeds_65pct_assumption": 0.22,
            "year1_loss_ratio_pct": {"p50": 40.0, "p95": 70.0},
            "antiselection_stress": {"cumulative_lr_drift_pct_points": 0.3}, "horizon_years": 5,
        }}
    ctx = {"assumptions": {"loss_ratio_bases": {"labelled_at_source": True}}}
    ok_findings = mc.derive_findings(_actu(block), ctx)
    ibnr_finding = next(f for f in ok_findings if "IBNR" in f["statement"])
    assert ibnr_finding["severity"] == "info"
    assert "target 75%" in ibnr_finding["statement"] and "met within sampling error" in ibnr_finding["statement"]
    assert not any(m["id"] == "act_ibnr_pct" for m in mc.derive_next_moves(_actu(block), ok_findings, ctx, True))

    weak_findings = mc.derive_findings(_actu(weak), ctx)
    assert next(f for f in weak_findings if "IBNR" in f["statement"])["severity"] == "warning"
    move = next(m for m in mc.derive_next_moves(_actu(weak), weak_findings, ctx, True) if m["id"] == "act_ibnr_pct")
    # p75 of the weak sample is 0.40 → proposal 40% > current 23%, quoted with the target.
    assert move["action"]["target"]["proposed"] == {"ibnr_pct": 0.4}
    assert "75% probability-of-sufficiency target" in move["why"]


def test_method_gap_is_labelled_difference_when_source_carries_basis_labels():
    """The 1.0.1 anomaly asked to 'label both bases explicitly'; now that
    risk_metrics carries loss_ratio_basis / loss_ratio_year1_basis /
    reserve_requirement_basis the gap is monitored, not an anomaly."""
    import services.actuarial_service as asvc
    assert asvc.LOSS_RATIO_BASIS_YEAR1 and asvc.LOSS_RATIO_BASIS_LIFETIME_ANNUALISED and asvc.RESERVE_REQUIREMENT_BASIS

    results = {"actuarial": {"expected_loss_ratio_phins_tables_pct": 33.66, "phins_simulator_loss_ratio_pct": 72.45,
                             "ibnr": {}}}
    labelled = {"assumptions": {"loss_ratio_bases": {
        "labelled_at_source": True, "year1": "year1_attained_age", "lifetime_annualised": "lifetime_annualised",
        "reserve_requirement": "pv_full_term_x1.5", "source": "services/actuarial_service.py:PortfolioSimulator.risk_metrics"}}}
    moves = mc.derive_next_moves(results, [], labelled, True)
    ids = {m["id"]: m for m in moves}
    assert "act_method_disagreement" not in ids
    m = ids["act_method_bases_labelled"]
    assert m["trigger"] == "none" and m["action"]["kind"] == "monitor" and m["priority"] == 3
    assert "38.8 pts apart" in m["why"] and "year1_attained_age" in m["why"]
    conclusions = mc.derive_conclusions(results, [], moves, _FAST, True)
    assert next(a for a in conclusions["areas"] if a["area"] == "actuarial")["status"] == "consistent"

    unlabelled = {"assumptions": {"loss_ratio_bases": {"labelled_at_source": False}}}
    moves = mc.derive_next_moves(results, [], unlabelled, True)
    assert any(m["id"] == "act_method_disagreement" and m["trigger"] == "anomaly" for m in moves)


def test_live_context_reports_bases_labelled_at_source():
    ctx = mc._load_phins_context()
    bases = ctx["assumptions"]["loss_ratio_bases"]
    assert bases["labelled_at_source"] is True
    assert bases["year1"] == "year1_attained_age"
    assert bases["reserve_requirement"] == mc.RESERVE_REQUIREMENT_BASIS
    assert ctx["assumptions"]["ibnr_probability_of_sufficiency_target"] == 0.75


def _claims_results(manual_share=0.19, assumed_manual=0.45):
    return {"claims": {
        "live_thresholds": {"fraud_leakage_rate": 0.035, "legit_false_denial_rate": 0.0064, "manual_share": manual_share},
        "authenticity_auc_legit_vs_fraud": 0.97,
        "manual_share_vs_assumed": manual_share - assumed_manual,
        "assumed_automation_mix": {"manual_review": assumed_manual},
        "threshold_sweep": [], "mirror_agreement_with_live_recommender": 1.0,
    }}


def _mix_ctx(sample_size, sufficient, source):
    return {"assumptions": {}, "observed_automation_mix": {
        "used": True, "min_sample": 30,
        "claims": {"sample_size": sample_size, "sufficient": sufficient, "source": source,
                   "rates": {"manual_review": 1.0, "auto_approve": 0.0}}}}


def test_claims_mix_gap_is_assumption_gap_until_observed_data_is_sufficient():
    """Production run: 19 decided claims (<30) — simulated 19% vs assumed 45%
    is an assumption gap, not PHINS disagreeing with itself."""
    results, ctx = _claims_results(), _mix_ctx(19, False, "assumed")
    findings = mc.derive_findings(results, ctx)
    assert next(f for f in findings if "manual-review share" in f["statement"])["severity"] == "warning"
    moves = mc.derive_next_moves(results, findings, ctx, True)
    m = next(m for m in moves if m["id"] == "claims_automation_base_rates")
    assert m["trigger"] == "inconsistency" and m["action"]["kind"] == "investigate" and m["priority"] == 2
    assert "Only 19 decided claims are on record (need 30)" in m["why"]
    conclusions = mc.derive_conclusions(results, findings, moves, _FAST, True)
    area = next(a for a in conclusions["areas"] if a["area"] == "claims")
    assert area["status"] == "inconsistent"
    assert "once 30 decided claims are on record (19 now)" in area["bi_conclusion"]


def test_claims_mix_gap_is_monitor_when_live_kpi_already_observed_and_anomaly_when_ignored():
    results, ctx = _claims_results(), _mix_ctx(40, True, "observed")
    findings = mc.derive_findings(results, ctx)
    mix_finding = next(f for f in findings if "manual-review share" in f["statement"])
    assert mix_finding["severity"] == "info"
    assert "40 observed decisions" in mix_finding["statement"]
    moves = mc.derive_next_moves(results, findings, ctx, True)
    m = next(m for m in moves if m["id"] == "claims_automation_base_rates")
    assert m["trigger"] == "none" and m["action"]["kind"] == "monitor"
    conclusions = mc.derive_conclusions(results, findings, moves, _FAST, True)
    area = next(a for a in conclusions["areas"] if a["area"] == "claims")
    assert area["status"] == "consistent" and conclusions["overall_status"] == "consistent"
    assert "already follow the observed mix (40 decided claims)" in area["bi_conclusion"]

    ctx = _mix_ctx(40, True, "assumed")
    findings = mc.derive_findings(results, ctx)
    assert next(f for f in findings if "manual-review share" in f["statement"])["severity"] == "warning"
    moves = mc.derive_next_moves(results, findings, ctx, True)
    m = next(m for m in moves if m["id"] == "claims_automation_base_rates")
    assert m["trigger"] == "anomaly" and m["priority"] == 1
    assert "ignores sufficient observed data" in m["why"]


def test_observed_automation_mix_reports_the_live_endpoint_source():
    """The evidence carries the label GET /api/actuarial/automation-metrics
    would show, computed by the same call the endpoint makes."""
    empty = mc._observed_automation_mix({"claims": {}, "underwriting_applications": {}, "billing": {}, "customers": {}})
    assert empty["used"] is True
    assert empty["claims"]["sufficient"] is False and empty["claims"]["source"] == "assumed"
    claims = {f"CLM{i}": {"status": "approved", "decided_by": "claims_bot", "approved_by": "claims_bot",
                          "reviewed_by": "claims_bot", "amount": 100} for i in range(40)}
    full = mc._observed_automation_mix({"claims": claims, "underwriting_applications": {}, "billing": {}, "customers": {}})
    assert full["claims"]["sample_size"] == 40
    assert full["claims"]["source"] == ("observed" if full["claims"]["sufficient"] else "assumed")


def test_risk_loading_gap_yields_an_investigate_move_and_conclusion():
    risk = {"auc": 0.722, "oracle_auc_true_hazard": 0.787, "auc_bootstrap_ci95": [0.69, 0.77],
            "band_monotonic_in_outcomes": True, "brier_score_raw": 0.109, "brier_score_base_rate": 0.055,
            "calibration_by_band": [
                {"band": "low", "n": 500, "loading_gap": 0.0, "applied_premium_adjustment_mean": 0.0,
                 "required_loading_vs_tables": 0.0, "observed_claim_rate": 0.02},
                {"band": "moderate", "n": 300, "loading_gap": -0.12, "applied_premium_adjustment_mean": 0.15,
                 "required_loading_vs_tables": 0.27, "observed_claim_rate": 0.05},
                {"band": "high", "n": 10, "loading_gap": -0.40, "applied_premium_adjustment_mean": 0.50,
                 "required_loading_vs_tables": 0.90, "observed_claim_rate": 0.2},  # too small to count
            ]}
    results = {"risk": risk}
    findings = mc.derive_findings(results, {"assumptions": {}})
    assert any(f["severity"] == "warning" and "under-cover" in f["statement"] for f in findings)
    moves = mc.derive_next_moves(results, findings, {"assumptions": {}}, True)
    m = next(m for m in moves if m["id"] == "risk_band_loadings")
    assert m["trigger"] == "inconsistency" and m["action"]["kind"] == "investigate"
    assert not m["action"]["adjustable_in_phins"]
    assert [e["band"] for e in m["evidence"]] == ["moderate"]
    assert "moderate applies 15% vs 27% required" in m["why"]
    area = next(a for a in mc.derive_conclusions(results, findings, moves, _FAST, True)["areas"] if a["area"] == "risk")
    assert area["status"] == "inconsistent" and "1 band loading(s)" in area["bi_conclusion"]
    assert area["next_move_ids"] == ["risk_band_loadings"]


def test_actuarial_conclusion_quotes_live_assumption_and_one_decimal():
    res = {"reserve_rule_150pct": {"probability_year1_claims_within_reserve": 1.0},
           "year1_claims_stress": {"probability_year1_claims_within_stress": 0.997},
           "ibnr": {"probability_reserve_config_ibnr_sufficient": 0.7467, "probability_of_sufficiency_target": 0.75,
                    "reserve_config_ibnr_meets_target": True},
           "loss_ratio_assumption_pct": 60.0}
    text = mc._bi_conclusion_for("actuarial", "consistent", res, [])
    assert "volatility stress 99.7%" in text  # not rounded up to 100%
    assert "IBNR is sufficient in 74.7% (meets the 75% target)" in text
    assert "the 60% point assumption" in text and "65%" not in text


def test_sales_module_evaluates_the_basis_the_live_forecast_uses():
    """With ≥ 6 complete months of policy history the live endpoint derives its
    rate from observed history; the module must evaluate that rate and say so.
    Without history it evaluates (and labels) the legacy 5% default."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    def _month(offset):
        y, m = now.year, now.month - offset
        while m <= 0:
            y, m = y - 1, m + 12
        return f"{y:04d}-{m:02d}-15"

    # Gross adds growing ~10%/month over the last 12 complete months.
    policies = {}
    for k, offset in enumerate(range(12, 0, -1)):
        policies[f"POL{k}"] = {"status": "active", "monthly_premium": round(100 * (1.10 ** k), 2),
                               "start_date": _month(offset)}
    observed = {"policies": policies, "claims": {}, "customers": {}, "underwriting_applications": {}, "billing": {}}
    params = mc.EvaluationParams(seed=3, lives=200, trials=30, horizon_years=2, bootstrap_samples=5, modules=("sales",))

    with_history = mc.run_evaluation(params, observed=observed)["results"]["sales"]["phins_forecast"]
    assert with_history["growth_basis"] == "observed_policy_history"
    assert with_history["observed_growth"]["sufficient"] is True
    assert with_history["observed_growth"]["history_months"] >= 6
    assert with_history["monthly_growth"] == pytest.approx(0.10, abs=0.02)
    assert with_history["legacy_default_monthly_growth"] == 0.05
    assert 0.0 <= with_history["legacy_default_probability_met_at_horizon"] <= 1.0

    no_history = mc.run_evaluation(params, observed=None)["results"]["sales"]["phins_forecast"]
    assert no_history["growth_basis"] == "legacy_default"
    assert no_history["monthly_growth"] == 0.05

    report = mc.run_evaluation(params, observed=observed)
    sales_finding = next(f for f in report["findings"] if f["area"] == "sales")
    assert "basis: observed policy history" in sales_finding["statement"]
    area = next(a for a in report["conclusions"]["areas"] if a["area"] == "sales")
    assert "observed-history forecast" in area["bi_conclusion"]
    for m in report["next_moves"]:
        if m["id"] == "sales_growth_assumption":
            assert "already uses the observed rate" in m["why"]


def test_ai_finding_states_counterfactual_when_cap_forces_review(report):
    ai_findings = [f for f in report["findings"] if f["area"] == "ai"]
    if report["results"]["ai"].get("advisory_cap_forces_full_human_review"):
        assert any("counterfactual figures without the advisory confidence cap" in f["statement"] for f in ai_findings)


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
