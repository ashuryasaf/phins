"""
AutomationMetrics: observed decision mix with labelled fallback (item J).

``AutomationMetrics.BASE_RATES`` is an assumed mix (claims manual review
45 %, underwriting manual 30 %). Real decision records now drive the display
whenever a process has at least ``OBSERVED_MIN_SAMPLE`` decided records;
otherwise the assumed rates are shown unchanged and labelled ``assumed``.
"""

from __future__ import annotations

import os

import pytest
import requests

from services.actuarial_service import AutomationMetrics

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")


def _legacy_rates(customer_count: int) -> dict:
    """The pre-change computation, reproduced verbatim as a characterisation oracle."""
    scale = AutomationMetrics.get_scale_factor(customer_count)
    result = {'scale_factor': scale, 'customer_count': customer_count}
    for process, rates in AutomationMetrics.BASE_RATES.items():
        result[process] = {}
        total_auto = 0
        for action, base_rate in rates.items():
            if action != 'manual_review':
                scaled_rate = min(base_rate * scale, 0.95)
                result[process][action] = round(scaled_rate, 4)
                total_auto += scaled_rate
        result[process]['manual_review'] = round(max(0.05, 1 - total_auto), 4)
        result[process]['total_automation_pct'] = round(1 - result[process]['manual_review'], 4)
    result['overall_automation_pct'] = round(
        result['underwriting']['total_automation_pct'] * 0.4
        + result['claims']['total_automation_pct'] * 0.35
        + result['billing']['total_automation_pct'] * 0.25, 4)
    return result


@pytest.mark.parametrize("count", [500, 1000, 100_000, 10_000_000])
def test_assumed_path_is_byte_for_byte_legacy(count):
    got = AutomationMetrics.calculate_automation_rates(count)
    legacy = _legacy_rates(count)
    for process in ('underwriting', 'claims', 'billing'):
        shown = dict(got[process])
        assert shown.pop('source') == 'assumed'
        assert shown == legacy[process]
    assert got['overall_automation_pct'] == legacy['overall_automation_pct']
    assert got['sources'] == {'underwriting': 'assumed', 'claims': 'assumed', 'billing': 'assumed'}


def _decided_book(n_uw=40, n_claims=40, n_bills=40):
    apps, claims, bills = {}, {}, {}
    for i in range(n_uw):
        if i % 4 == 0:
            apps[f"APP-{i}"] = {"status": "approved", "approved_by": "system_auto_approve"}
        elif i % 4 == 1:
            apps[f"APP-{i}"] = {"status": "referred", "referred_by": "admin_pipeline"}
        elif i % 4 == 2:
            apps[f"APP-{i}"] = {"status": "approved", "approved_by": "underwriter"}
        else:
            apps[f"APP-{i}"] = {"status": "rejected", "rejected_by": "underwriter"}
    apps["APP-pending"] = {"status": "pending"}  # not decided → ignored
    for i in range(n_claims):
        if i % 5 == 0:
            claims[f"CLM-{i}"] = {"status": "approved", "approved_by": "claims_bot", "claimed_amount": 100, "approved_amount": 100}
        elif i % 5 == 1:
            claims[f"CLM-{i}"] = {"status": "paid", "approved_by": "claims_bot", "claimed_amount": 100, "approved_amount": 60}
        elif i % 5 == 2:
            claims[f"CLM-{i}"] = {"status": "rejected", "rejected_by": "system_fraud_rules"}
        else:
            claims[f"CLM-{i}"] = {"status": "approved", "approved_by": "claims_adjuster", "claimed_amount": 100, "approved_amount": 100}
    claims["CLM-open"] = {"status": "pending"}
    for i in range(n_bills):
        if i % 2 == 0:
            bills[f"BILL-{i}"] = {"status": "paid", "auto_pay": True}
        elif i % 4 == 1:
            bills[f"BILL-{i}"] = {"status": "overdue", "reminder_sent": True}
        else:
            bills[f"BILL-{i}"] = {"status": "overdue"}
    return apps, claims, bills


def test_observed_mix_counts_only_decided_records_and_platform_actors():
    apps, claims, bills = _decided_book()
    mix = AutomationMetrics.observe_automation_mix(apps, claims, bills)
    assert mix["read_only"] is True
    uw = mix["underwriting"]
    assert uw["sample_size"] == 40 and uw["sufficient"] is True
    assert uw["counts"] == {"auto_approve": 10, "auto_decline": 0, "auto_refer": 10, "manual_review": 20}
    assert uw["rates"]["manual_review"] == 0.5
    cl = mix["claims"]
    assert cl["sample_size"] == 40
    assert cl["counts"] == {"auto_approve": 8, "auto_decline": 8, "auto_partial": 8, "manual_review": 16}
    bl = mix["billing"]
    assert bl["counts"] == {"auto_collect": 20, "auto_reminder": 10, "manual_followup": 10}
    assert sum(cl["rates"].values()) == pytest.approx(1.0)


def test_small_sample_falls_back_to_assumed_and_is_labelled():
    apps, claims, bills = _decided_book(n_uw=5, n_claims=40, n_bills=3)
    mix = AutomationMetrics.observe_automation_mix(apps, claims, bills)
    out = AutomationMetrics.calculate_automation_rates(100_000, observed=mix)
    legacy = _legacy_rates(100_000)
    assert out["sources"] == {"underwriting": "assumed", "claims": "observed", "billing": "assumed"}
    uw = dict(out["underwriting"])
    assert uw.pop("source") == "assumed"
    assert uw.pop("observed_insufficient") is True
    assert uw.pop("sample_size") == 5
    assert uw == legacy["underwriting"]
    cl = out["claims"]
    assert cl["source"] == "observed" and cl["sample_size"] == 40
    assert cl["manual_review"] == 0.4
    assert cl["total_automation_pct"] == pytest.approx(0.6)
    assert cl["assumed"] == legacy["claims"]  # the assumed mix stays visible for comparison
    # Overall score blends observed claims with assumed underwriting/billing.
    expected_overall = round(legacy["underwriting"]["total_automation_pct"] * 0.4 + 0.6 * 0.35
                             + legacy["billing"]["total_automation_pct"] * 0.25, 4)
    assert out["overall_automation_pct"] == expected_overall


def test_manually_collected_and_human_named_decisions_are_not_automated():
    """A paid bill or a human reviewer must not be counted as platform work."""
    bills = {f"BILL-{i}": {"status": "paid", "paid_by": "accountant"} for i in range(40)}
    apps = {f"APP-{i}": {"status": "approved", "approved_by": "Autumn Reid"} for i in range(40)}
    mix = AutomationMetrics.observe_automation_mix(apps, {}, bills)
    assert mix["billing"]["counts"] == {"auto_collect": 0, "auto_reminder": 0, "manual_followup": 40}
    assert mix["underwriting"]["counts"]["manual_review"] == 40
    # Platform actors still register, including a suffixed identifier.
    assert AutomationMetrics._is_system_actor("bot_3") is True
    assert AutomationMetrics._is_system_actor("Botros") is False


def test_observed_mix_never_mutates_inputs():
    apps, claims, bills = _decided_book()
    before = (repr(sorted(apps.items())), repr(sorted(claims.items())), repr(sorted(bills.items())))
    AutomationMetrics.observe_automation_mix(apps, claims, bills)
    assert (repr(sorted(apps.items())), repr(sorted(claims.items())), repr(sorted(bills.items()))) == before


class TestRoute:
    def test_route_reports_sources_and_observed_block(self):
        login = requests.post(f"{BASE_URL}/api/login", json={"username": "admin", "password": "admin123"})
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        resp = requests.get(f"{BASE_URL}/api/actuarial/automation-metrics", params={"customer_count": 1000},
                            headers=headers, timeout=30)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        assert set(body["metrics"]["sources"]) == {"underwriting", "claims", "billing"}
        assert set(body["metrics"]["sources"].values()) <= {"observed", "assumed"}
        assert body["observed"]["read_only"] is True
        for process in ("underwriting", "claims", "billing"):
            assert body["metrics"][process]["source"] == body["metrics"]["sources"][process]
