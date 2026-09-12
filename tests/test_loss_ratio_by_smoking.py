"""
Read-only loss-ratio-by-smoking-status slice (remediation item E).

The Monte Carlo evaluation proposes smoker pricing factors from its synthetic
world. Before applying them PHINS needs its own experience: this slice groups
real active policies and their incurred claims by the pricing kernel's
smoking cohorts, guards every comparison behind a minimum cohort size, and
reports the factor the observed ratio would imply without writing anything.
"""

from __future__ import annotations

import os

import pytest
import requests

from services import bi_analytics_service as bi
from services.bi_analytics_service import loss_ratio_by_smoking_status
from web_portal import api_bi_analytics as api

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")


def _book(n_smokers=40, n_nonsmokers=40, smoker_claim=900.0, nonsmoker_claim=500.0):
    customers, policies, claims = {}, {}, {}
    for i in range(n_smokers):
        cid, pid = f"CUST-S{i}", f"POL-S{i}"
        customers[cid] = {"id": cid, "smoking_status": "current"}
        policies[pid] = {"id": pid, "customer_id": cid, "status": "active", "annual_premium": 1300.0}
        if i % 2 == 0:
            claims[f"CLM-S{i}"] = {"policy_id": pid, "customer_id": cid, "status": "paid", "approved_amount": smoker_claim}
    for i in range(n_nonsmokers):
        cid, pid = f"CUST-N{i}", f"POL-N{i}"
        customers[cid] = {"id": cid, "smoking_status": "never"}
        policies[pid] = {"id": pid, "customer_id": cid, "status": "active", "annual_premium": 1000.0}
        if i % 2 == 0:
            claims[f"CLM-N{i}"] = {"policy_id": pid, "customer_id": cid, "status": "approved", "approved_amount": nonsmoker_claim}
    return customers, policies, claims


def test_cohorts_and_ratio_from_observed_book():
    customers, policies, claims = _book()
    out = loss_ratio_by_smoking_status(customers, policies, claims,
                                       pricing_factors={"smoker_mortality_factor": 1.3, "smoker_disability_factor": 1.3})
    assert out["read_only"] is True
    by = {row["cohort"]: row for row in out["cohorts"]}
    assert set(by) == {"smoker", "former", "nonsmoker", "unknown"}
    s, n = by["smoker"], by["nonsmoker"]
    assert (s["lives"], n["lives"]) == (40, 40)
    assert s["annual_premium"] == 40 * 1300.0
    # 20 paid claims × 900 on 52 000 premium = 34.62 %; nonsmoker 20 × 500 on 40 000 = 25 %.
    assert s["incurred_loss_ratio_pct"] == pytest.approx(34.62, abs=0.01)
    assert s["loss_ratio_pct"] == pytest.approx(34.62, abs=0.01)  # all smoker claims are 'paid'
    assert n["incurred_loss_ratio_pct"] == pytest.approx(25.0)
    assert n["loss_ratio_pct"] == 0.0  # 'approved' is incurred but not yet paid
    cmp = out["comparison"]
    assert cmp["sufficient"] is True
    assert cmp["smoker_to_nonsmoker_loss_ratio_ratio"] == pytest.approx(34.62 / 25.0, abs=0.001)
    assert cmp["implied_factors"]["smoker_mortality_factor"] == pytest.approx(1.3 * 34.62 / 25.0, abs=0.002)
    assert cmp["live_factors"] == {"smoker_mortality_factor": 1.3, "smoker_disability_factor": 1.3}
    assert out["adjust_via"].startswith("POST /api/actuarial/config")


def test_small_cohorts_are_reported_but_never_compared():
    customers, policies, claims = _book(n_smokers=5, n_nonsmokers=40)
    out = loss_ratio_by_smoking_status(customers, policies, claims)
    by = {row["cohort"]: row for row in out["cohorts"]}
    assert by["smoker"]["insufficient_data"] is True
    assert by["nonsmoker"]["insufficient_data"] is False
    assert out["comparison"]["sufficient"] is False
    assert "implied_factors" not in out["comparison"]
    assert "30" in out["comparison"]["reason"]
    # Threshold is a parameter, not a constant.
    assert loss_ratio_by_smoking_status(customers, policies, claims, min_lives=5)["comparison"]["sufficient"] is True


def test_status_resolution_falls_back_to_customer_and_application_and_unknown():
    customers = {"C1": {"smoking_status": "former"}, "C2": {}, "C3": {"tobacco": "no"}}
    applications = {"APP-1": {"customer_id": "C2", "smoking_status": "yes", "submitted_at": "2026-01-01"}}
    policies = {
        "P1": {"customer_id": "C1", "status": "active", "annual_premium": 100},
        "P2": {"customer_id": "C2", "status": "active", "annual_premium": 100},
        "P3": {"customer_id": "C3", "status": "active", "annual_premium": 100},
        "P4": {"customer_id": "C9", "status": "active", "annual_premium": 100},
        "P5": {"customer_id": "C1", "status": "cancelled", "annual_premium": 100},  # no premium base
        "P6": {"customer_id": "C1", "status": "active", "annual_premium": 100, "smoking_status": "current"},  # policy wins
    }
    claims = {
        "K1": {"policy_id": "P5", "status": "paid", "approved_amount": 10},   # cancelled policy → cohort still known
        "K2": {"customer_id": "C3", "status": "closed", "approved_amount": 20},  # no policy_id → via customer
        "K3": {"status": "paid", "approved_amount": 30},                        # nothing → unknown
        "K4": {"policy_id": "P1", "status": "pending", "claimed_amount": 999},  # not incurred
    }
    out = loss_ratio_by_smoking_status(customers, policies, claims, underwriting_applications=applications)
    by = {row["cohort"]: row for row in out["cohorts"]}
    assert by["former"]["lives"] == 1 and by["former"]["claims_incurred"] == 10.0
    assert by["smoker"]["lives"] == 2  # C2 via application + P6 via policy field
    assert by["nonsmoker"]["lives"] == 1 and by["nonsmoker"]["claims_incurred"] == 20.0
    assert by["unknown"]["lives"] == 1 and by["unknown"]["claims_incurred"] == 30.0
    assert out["claims_unattributed_to_policy_or_customer"] == 1


def test_service_wrapper_is_cached_and_invalidated_by_data_change():
    svc = bi.BIAnalyticsService()
    customers, policies, claims = _book()
    first = svc.get_loss_ratio_by_smoking_status(customers, policies, claims)
    assert svc.get_loss_ratio_by_smoking_status(customers, policies, claims) is first
    claims["CLM-extra"] = {"policy_id": "POL-S0", "status": "paid", "approved_amount": 1.0}
    assert svc.get_loss_ratio_by_smoking_status(customers, policies, claims) is not first


def test_handler_reads_live_factors_and_validates_params(tmp_path, monkeypatch):
    from services import actuarial_service as asvc
    monkeypatch.setenv("PHINS_ACTUARIAL_STATE_PATH", str(tmp_path / "act.json"))
    store = asvc.ActuarialTablesStore()
    monkeypatch.setattr(asvc, "get_actuarial_store", lambda: store)
    customers, policies, claims = _book()
    sources = {"customers": customers, "policies": policies, "claims": claims, "underwriting_applications": {}}
    status, payload = api.handle_loss_ratio_by_smoking(None, sources, {"min_lives": "10"})
    assert status == 200
    assert payload["comparison"]["min_lives_per_cohort"] == 10
    assert payload["comparison"]["live_factors"]["smoker_mortality_factor"] == store.config.smoker_mortality_factor
    status, payload = api.handle_loss_ratio_by_smoking(None, sources, {"min_lives": "abc"})
    assert status == 400 and set(payload) == {"error"}


def test_monte_carlo_smoker_move_prefers_observed_experience(tmp_path, monkeypatch):
    """With a sufficient observed book the proposal scales by the OBSERVED ratio."""
    from services import actuarial_service as asvc
    from services import monte_carlo_evaluation_service as mc
    monkeypatch.setenv("PHINS_ACTUARIAL_STATE_PATH", str(tmp_path / "act.json"))
    store = asvc.ActuarialTablesStore()
    monkeypatch.setattr(asvc, "get_actuarial_store", lambda: store)

    params = mc.EvaluationParams(seed=3, lives=400, trials=40, bootstrap_samples=10, modules=("underwriting",))
    customers, policies, claims = _book(n_smokers=60, n_nonsmokers=60)
    report = mc.run_evaluation(params, observed={"policies": policies, "claims": claims, "customers": customers})
    exp = report["observed_inputs"]["smoking_experience"]
    assert exp["used"] is True and exp["sufficient"] is True
    assert exp["endpoint"] == "GET /api/bi/loss-ratio-by-smoking"
    move = next((m for m in report["next_moves"] if m["id"] == "uw_smoker_demographic_factors"), None)
    if move is not None:
        ev = move["evidence"]
        assert ev["ratio_basis"] == "observed_experience"
        assert ev["ratio"] == pytest.approx(exp["smoker_to_nonsmoker_loss_ratio_ratio"], abs=0.001)
        assert "OBSERVED" in move["why"]
        live = store.config.smoker_mortality_factor
        assert move["action"]["target"]["proposed"]["smoker_mortality_factor"] == pytest.approx(
            max(1.0, min(3.0, live * ev["ratio"])), abs=0.006)  # engine rounds factors to 2 dp
    assert report["integrity"]["observed_inputs_unchanged"] is True
    assert report["integrity"]["proposals_applied_by_engine"] is False

    # Without observed data the move falls back to the simulated world and says so.
    report2 = mc.run_evaluation(params, observed={"policies": {}, "claims": {}})
    assert report2["observed_inputs"]["smoking_experience"]["sufficient"] is False
    move2 = next((m for m in report2["next_moves"] if m["id"] == "uw_smoker_demographic_factors"), None)
    if move2 is not None:
        assert move2["evidence"]["ratio_basis"] == "simulated_world"
        assert "GET /api/bi/loss-ratio-by-smoking" in move2["why"]


class TestRoute:
    def test_requires_privileged_role(self):
        resp = requests.get(f"{BASE_URL}/api/bi/loss-ratio-by-smoking")
        assert resp.status_code == 403
        assert set(resp.json()) == {"error"}

    def test_admin_gets_read_only_slice(self):
        login = requests.post(f"{BASE_URL}/api/login", json={"username": "admin", "password": "admin123"})
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        resp = requests.get(f"{BASE_URL}/api/bi/loss-ratio-by-smoking", headers=headers, timeout=30)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["read_only"] is True
        assert {row["cohort"] for row in body["cohorts"]} == {"smoker", "former", "nonsmoker", "unknown"}
        assert "sufficient" in body["comparison"]
        assert body["adjust_via"].startswith("POST /api/actuarial/config")
