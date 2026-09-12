"""
Revenue forecast: observed growth, lapse churn and p10/p50/p90 bands (item F).

``predict_revenue_forecast`` used to compound current MRR at a 5 %/month
parameter with no churn and no uncertainty. The legacy ``forecast`` key keeps
that meaning (existing consumers unchanged); ``forecast_basis`` and ``bands``
are additive and state where every number came from.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from services import bi_analytics_service as bi
from services.bi_analytics_service import observed_monthly_growth
from web_portal import api_bi_analytics as api

NOW = datetime(2026, 9, 12, 10, 0, 0)


def _book(months_of_history: int, monthly_growth: float = 0.03, base_mrr: float = 1000.0):
    """Policies issued monthly so cumulative gross-adds MRR grows geometrically.

    Last start month is the last *complete* month before NOW (August 2026).
    """
    policies = {}
    cumulative_target = base_mrr
    prev_total = 0.0
    for i in range(months_of_history):
        month_index = (8 - 1) - (months_of_history - 1 - i)  # 0-based month for August = 7
        year, month = 2026 + month_index // 12, month_index % 12 + 1
        add = cumulative_target - prev_total
        policies[f"POL-{i}"] = {
            "status": "active", "monthly_premium": round(add, 4),
            "start_date": f"{year:04d}-{month:02d}-15T09:00:00",
        }
        prev_total = cumulative_target
        cumulative_target *= 1 + monthly_growth
    return policies


def test_legacy_forecast_unchanged_when_rate_is_given():
    svc = bi.BIAnalyticsService()
    policies = {
        "POL-001": {"status": "active", "monthly_premium": 500.0},
        "POL-002": {"status": "active", "monthly_premium": 1000.0},
        "POL-003": {"status": "inactive", "monthly_premium": 300.0},
    }
    out = svc.predict_revenue_forecast(policies, historical_growth_rate=0.05, months_ahead=3, lapse_rate_year1=0.08)
    assert out["current_mrr"] == 1500.0 and out["growth_rate"] == 5.0
    assert [row["forecasted_mrr"] for row in out["forecast"]] == [1575.0, 1653.75, 1736.44]
    basis = out["forecast_basis"]
    assert basis["growth_rate_source"] == "caller_parameter"
    assert basis["churn_source"] == "caller_parameter"
    assert basis["monthly_churn"] == pytest.approx(1 - (1 - 0.08) ** (1 / 12), abs=1e-6)
    # Bands: p50 is net of churn (below the gross point line), p10 < p50 < p90, spread widens.
    assert len(out["bands"]) == 3
    for row, point in zip(out["bands"], out["forecast"]):
        assert row["p10"] < row["p50"] < row["p90"]
        assert row["p50"] < point["forecasted_mrr"]
    widths = [row["p90"] / row["p10"] for row in out["bands"]]
    assert widths == sorted(widths)


def test_short_history_falls_back_to_default_and_says_so():
    svc = bi.BIAnalyticsService()
    policies = _book(months_of_history=4, monthly_growth=0.10)
    out = svc.predict_revenue_forecast(policies, historical_growth_rate=None, months_ahead=2,
                                       lapse_rate_year1=0.08, now=NOW)
    basis = out["forecast_basis"]
    assert basis["growth_rate_source"] == "default_insufficient_history"
    assert basis["observed_history_months"] == 4
    assert basis["monthly_growth_rate"] == pytest.approx(bi.FORECAST_DEFAULT_MONTHLY_GROWTH)
    assert out["growth_rate"] == 5.0
    assert basis["growth_sd_source"] == "default"


def test_sufficient_history_uses_observed_growth():
    svc = bi.BIAnalyticsService()
    policies = _book(months_of_history=9, monthly_growth=0.03)
    obs = observed_monthly_growth(policies, now=NOW)
    assert obs["sufficient"] is True
    assert obs["history_months"] == 9
    assert obs["last_complete_month"] == "2026-08"
    assert obs["monthly_growth"] == pytest.approx(0.03, abs=1e-4)
    assert obs["monthly_growth_sd"] == pytest.approx(0.0, abs=1e-4)  # perfectly geometric series

    out = svc.predict_revenue_forecast(policies, historical_growth_rate=None, months_ahead=12,
                                       lapse_rate_year1=0.08, now=NOW)
    basis = out["forecast_basis"]
    assert basis["growth_rate_source"] == "observed_policy_start_dates"
    assert basis["monthly_growth_rate"] == pytest.approx(0.03, abs=1e-4)
    assert basis["growth_sd_source"] == "observed_month_to_month_growth"
    assert out["growth_rate"] == pytest.approx(3.0, abs=0.01)
    # Explicit rate still overrides observation.
    forced = svc.predict_revenue_forecast(policies, historical_growth_rate=0.05, months_ahead=1, lapse_rate_year1=0.08)
    assert forced["forecast_basis"]["growth_rate_source"] == "caller_parameter"


def test_observed_growth_ignores_current_month_and_undated_policies():
    policies = _book(months_of_history=7)
    policies["POL-now"] = {"status": "active", "monthly_premium": 1e9, "start_date": "2026-09-05"}
    policies["POL-undated"] = {"status": "active", "monthly_premium": 1e9}
    policies["POL-future"] = {"status": "active", "monthly_premium": 1e9, "start_date": "2027-01-01"}
    obs = observed_monthly_growth(policies, now=NOW)
    assert obs["sufficient"] is True
    assert obs["monthly_growth"] == pytest.approx(0.03, abs=1e-4)
    assert observed_monthly_growth({}, now=NOW) == {
        "sufficient": False, "history_months": 0, "monthly_growth": None,
        "reason": "no policies with a start date before the current month",
    }


def test_churn_defaults_to_actuarial_lapse_table(tmp_path, monkeypatch):
    from services import actuarial_service as asvc
    monkeypatch.setenv("PHINS_ACTUARIAL_STATE_PATH", str(tmp_path / "act.json"))
    store = asvc.ActuarialTablesStore()
    monkeypatch.setattr(asvc, "get_actuarial_store", lambda: store)
    svc = bi.BIAnalyticsService()
    out = svc.predict_revenue_forecast({"P": {"status": "active", "monthly_premium": 100.0}}, months_ahead=1)
    basis = out["forecast_basis"]
    assert basis["lapse_rate_year1"] == pytest.approx(store.get_lapse_rate(1))
    assert basis["churn_source"].startswith("actuarial_lapse_table:")


def test_handler_omits_rate_for_observed_and_bounds_months():
    policies = _book(months_of_history=8)
    status, payload = api.handle_revenue_forecast(None, policies, {"months_ahead": "3"})
    assert status == 200
    assert payload["forecast_basis"]["growth_rate_source"] in ("observed_policy_start_dates", "default_insufficient_history")
    assert len(payload["forecast"]) == len(payload["bands"]) == 3
    status, payload = api.handle_revenue_forecast(None, policies, {"growth_rate": "0.02", "months_ahead": "500"})
    assert status == 200
    assert payload["forecast_basis"]["growth_rate_source"] == "caller_parameter"
    assert payload["forecast_months"] == 120
