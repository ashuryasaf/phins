"""Admin AI & BI desk: figures come from stored formulas and books."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from security.access_hierarchy import ACCESS_DENIED, api_denial, surface_decision
from services.actuarial_service import (
    _mortality_terminal_age,
    curtate_life_expectancy,
    get_actuarial_store,
)
from services.adl3_disabled_life_expectancy import adl3_row_at, adl3_rows_for_tables
from services.admin_ai_bi_service import (
    answer_query,
    clear_reports,
    dashboard_catalog,
    get_report,
    numbers_in,
    render_html,
    render_markdown,
)
from web_portal.api_admin_ai_bi import dispatch_get, dispatch_post

QUESTION = (
    "how many 85+ of 100k standard age distribution can be adl "
    "and for how many years they are expected to live"
)
ADMIN = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "admin.html"


def setup_function():
    clear_reports()


def _cohort():
    return answer_query(QUESTION, actor_role="admin")


def test_standard_85_plus_uses_the_published_curve_and_withholds_nothing_invented():
    report = _cohort()
    facts = report["facts"]
    window = facts["portfolio_window"]
    open_n = facts["open_normal"]
    assert report["intent"] == "cohort_adl"
    assert report["integrity"]["read_only"] is True
    assert report["integrity"]["side_effects"] == []
    assert window["lives"] == 0.0
    assert window["outside_draw_window"] is True
    assert window["population_identity"] is True
    assert open_n["lives"] > 0
    assert facts["applied"]["population"] == 100000
    assert facts["applied"]["age_floor"] == 85
    assert facts["applied"]["scenario"] is False
    assert facts["integrity_checks"]["portfolio_window_sums_to_population"] is True

    store = get_actuarial_store()
    tables = store.get_current_tables()
    floor = open_n["at_age_floor"]
    published = adl3_row_at(adl3_rows_for_tables(tables), 85)
    assert floor["average_years"] == published["average_years"]
    assert floor["male_years"] == published["male_years"]
    assert floor["female_years"] == published["female_years"]
    incidence = store.lookup_table_rate("disability_incidence_rates", 85)
    assert floor["disability_incidence_per_life"] == incidence
    terminal = _mortality_terminal_age(tables.get("mortality_rates"))
    healthy = curtate_life_expectancy(
        85, lambda age: store.lookup_table_rate("mortality_rates", age), terminal, 1.0
    )
    assert floor["healthy_curtate_years"] == healthy
    assert open_n["incidence_lives"] is not None
    assert 120 in open_n["incidence_ages_withheld"]
    assert "120" in report["answer"]["en"]
    assert "120" in report["answer"]["he"]
    covered = open_n["lives"] - open_n["incidence_withheld_lives"]
    assert abs(open_n["incidence_lives"] - covered * incidence) < 1e-3


def test_distribution_variant_changes_the_lead_and_keeps_both_counts():
    both = _cohort()
    window = answer_query(QUESTION, variants={"distribution": "portfolio_window"})
    assert "portfolio window" in window["answer"]["en"].lower()
    assert "חלון התיק" in window["answer"]["he"]
    assert window["facts"]["portfolio_window"]["lives"] == both["facts"]["portfolio_window"]["lives"]
    assert window["facts"]["open_normal"]["lives"] == both["facts"]["open_normal"]["lives"]
    assert window["integrity"]["facts_sha256"] != both["integrity"]["facts_sha256"]
    assert numbers_in(window["answer"]["en"]) <= numbers_in(window["facts"])
    assert numbers_in(window["answer"]["he"]) <= numbers_in(window["facts"])


def test_answer_sentences_only_use_numbers_from_the_facts():
    report = _cohort()
    allowed = numbers_in(report["facts"])
    for lang in ("en", "he"):
        extra = numbers_in(report["answer"][lang]) - allowed
        assert not extra, (lang, extra)
    again = _cohort()
    assert again["integrity"]["facts_sha256"] == report["integrity"]["facts_sha256"]
    assert again["report_id"] != report["report_id"]


def test_population_variant_scales_the_open_tail():
    base = answer_query(QUESTION, variants={"population": 1000})
    double = answer_query(QUESTION, variants={"population": 2000})
    first = base["facts"]["open_normal"]["lives"]
    second = double["facts"]["open_normal"]["lives"]
    assert abs(second - 2 * first) < 1e-4


def test_changed_mean_is_marked_as_a_scenario():
    report = answer_query(QUESTION, variants={"mean": 70})
    assert report["facts"]["applied"]["scenario"] is True
    assert "scenario" in report["answer"]["en"].lower()


def test_bad_variant_is_refused():
    try:
        answer_query(QUESTION, variants={"age_floor": 200})
    except Exception as exc:
        assert "age_floor" in str(exc)
    else:
        raise AssertionError("expected a refusal")


def test_customer_report_redacts_secrets_and_does_not_invent_an_age():
    books = {
        "customers": {
            "CUST-1": {
                "customer_id": "CUST-1",
                "name": "Ada Lovelace",
                "email": "ada@example.com",
                "national_id": "123456782",
                "national_id_last4": "6782",
                "national_id_hash": "abc",
                "password": "secret-value",
            }
        },
        "policies": {
            "POL-1": {
                "customer_id": "CUST-1",
                "status": "active",
                "annual_premium": 1200,
                "coverage_amount": 50000,
            }
        },
        "claims": {},
        "underwriting": {},
        "billing": {},
        "ledger": {},
    }
    before = copy.deepcopy(books)
    report = answer_query('full report about "Ada Lovelace"', books=books)
    assert books == before
    customer = report["facts"]["customer"]
    assert customer["matched"] == 1
    assert customer["customer_id"] == "CUST-1"
    assert customer["policies"][0]["annual_premium"] == 1200
    blob = json.dumps(customer)
    assert "123456782" not in blob
    assert "secret-value" not in blob
    assert customer["profile"]["national_id"] == "[redacted]"
    assert customer["profile"]["national_id_last4"] == "6782"
    assert customer["profile"]["password"] == "[redacted]"
    assert customer["projection"]["withheld"]
    assert report["integrity"]["plaintext_national_id_returned"] is False


def test_ambiguous_customer_does_not_dump_a_dossier():
    books = {
        "customers": {
            "CUST-1": {"customer_id": "CUST-1", "name": "Ada One"},
            "CUST-2": {"customer_id": "CUST-2", "name": "Ada Two"},
        },
        "policies": {},
        "claims": {},
        "underwriting": {},
        "billing": {},
        "ledger": {},
    }
    report = answer_query('full report about "Ada"', books=books)
    customer = report["facts"]["customer"]
    assert customer["matched"] == 2
    assert "profile" not in customer
    assert len(customer["candidates"]) == 2


def test_stored_simulation_is_summarised_without_priced_lives():
    simulation = {
        "simulation_id": "SIM-TEST-1",
        "run_at": "2026-10-01T00:00:00",
        "parameters": {
            "customer_count": 10,
            "age_min": 3,
            "age_max": 90,
            "age_mean": 35,
            "age_std": 12,
            "age_distribution": "normal",
        },
        "portfolio_summary": {"accepted_customers": 8, "total_annual_premium": 100},
        "priced_lives": [{"name": "hidden"}],
        "age_adl_matrix": {
            "totals": {"applied": 10, "accepted": 8, "rejected": 2},
            "integrity": {"all_checks_pass": True},
            "distribution": {
                "sample": {"n": 10, "mean": 40},
                "histogram": [
                    {"age": 40, "applied": 3, "accepted": 3, "rejected": 0},
                    {"age": 86, "applied": 2, "accepted": 0, "rejected": 2},
                ],
            },
        },
    }
    report = answer_query("recent simulation aged 85", simulations=[simulation])
    assert report["intent"] == "simulation"
    blob = json.dumps(report)
    assert "hidden" not in blob
    summary = report["facts"]["simulations"]["reports"][0]
    assert summary["lives_at_or_above_floor"]["applied"] == 2
    assert summary["priced_lives_omitted"] is True
    assert summary["matrix_integrity_pass"] is True


def test_missing_simulation_points_at_the_simulator_and_does_not_invent_one():
    report = answer_query("recent simulation", simulations=[])
    assert report["facts"]["simulations"]["matched"] == 0
    assert report["planning"]["needs_planning"] is True
    assert report["planning"]["suggested_agent"] == "portfolio_simulator"
    assert "total_annual_premium" not in json.dumps(report["facts"])


def test_planning_question_does_not_estimate_a_new_product():
    report = answer_query("design a new product and forecast profit in year 10")
    assert report["planning"]["needs_planning"] is True
    assert "year_10" not in json.dumps(report["facts"])
    assert report["integrity"]["side_effects"] == []


def test_llm_narrative_is_dropped_when_it_adds_a_number():
    class Fake:
        def completion(self, system_prompt, user_content):
            return "About 999 people can be ADL."

    plain = _cohort()
    narrated = answer_query(QUESTION, narrate=True, provider=Fake())
    assert narrated["narrative"]["fallback_reason"] == "narrative_introduced_numbers"
    assert narrated["narrative"]["source"] == "deterministic"
    assert narrated["answer"]["en"] == plain["answer"]["en"]


def test_llm_narrative_may_rephrase_without_new_numbers():
    class Fake:
        def completion(self, system_prompt, user_content):
            return "The figures already sealed in this report describe that cohort."

    report = answer_query(QUESTION, narrate=True, provider=Fake())
    assert report["narrative"]["source"] == "llm"
    assert report["answer"]["en"].startswith("The figures already sealed")
    assert numbers_in(report["answer"]["en"]) <= numbers_in(report["facts"])


def test_dashboard_catalog_links_staff_pages_and_the_report_window():
    rows = {row["path"]: row for row in dashboard_catalog()}
    for path in (
        "/admin.html",
        "/admin-ai-report.html",
        "/actuary-dashboard.html",
        "/accountant-dashboard.html",
        "/risk-reports-dashboard.html",
        "/video-agents.html",
        "/cyber-security.html",
        "/admin-media.html",
        "/chat-process-review.html",
    ):
        assert path in rows, path
        assert rows[path]["admin_open"] is True
    assert rows["/regulator-dashboard.html"]["admin_open"] is False
    assert rows["/dashboard.html"]["admin_open"] is False


def test_role_gate_is_admin_and_manager_only():
    assert api_denial("manager", "POST", "/api/admin/ai-bi/query") is None
    assert api_denial("manager", "GET", "/api/admin/customers") == ACCESS_DENIED
    assert api_denial("customer", "POST", "/api/admin/ai-bi/query") == ACCESS_DENIED
    assert api_denial("underwriter", "POST", "/api/admin/ai-bi/query") is None
    assert surface_decision("manager", "/admin-ai-report.html")["allowed"] is True
    assert surface_decision("customer", "/admin-ai-report.html")["allowed"] is False
    assert surface_decision("admin", "/admin-ai-report.html")["allowed"] is True

    status, body = dispatch_post("/api/admin/ai-bi/query", None, {"question": QUESTION})
    assert status == 401
    status, body = dispatch_post(
        "/api/admin/ai-bi/query", {"role": "underwriter"}, {"question": QUESTION}
    )
    assert status == 403
    assert "error" in body
    status, body = dispatch_post(
        "/api/admin/ai-bi/query", {"role": "admin", "username": "admin"}, {"question": QUESTION}
    )
    assert status == 200, body
    assert body["integrity"]["facts_sha256"]
    stored = get_report(body["report_id"])
    assert stored["integrity"]["facts_sha256"] == body["integrity"]["facts_sha256"]
    status, download = dispatch_get(
        f"/api/admin/ai-bi/reports/{body['report_id']}/download",
        {"role": "manager"},
        {"format": ["md"], "lang": ["he"]},
    )
    assert status == 200
    assert "PHINS admin report" in download["content"]
    assert body["integrity"]["facts_sha256"] in download["content"]
    html = render_html(body, "he")
    assert 'lang="he"' in html
    assert "phins-doc-wordmark" in html
    assert "phins-doc-banner" in html
    assert "Personal Health Insurance" in html
    assert "metric-grid" in html
    assert body["facts"]["open_normal"]["at_age_floor"]["average_years"] is None or str(
        body["facts"]["open_normal"]["at_age_floor"]["age"]
    ) in html
    md = render_markdown(body, "en")
    assert "Dashboards" in md


def test_post_extension_gate_includes_the_ai_bi_desk():
    server = Path(__file__).resolve().parents[1] / "web_portal" / "server.py"
    content = server.read_text(encoding="utf-8")
    assert "'/api/admin/ai-bi'" in content


def test_admin_mic_routes_data_questions_and_links_desks():
    content = ADMIN.read_text(encoding="utf-8")
    for needle in (
        "function adminAssistantIsDataQuestion(",
        "async function adminAssistantAskData(",
        "function adminAssistantOpenReport(",
        "async function adminAssistantShowDashboards(",
        "/api/admin/ai-bi/query",
        "/admin-ai-report.html?id=",
        ">Desks<",
        "How many 85+ of 100k can be ADL?",
        'href="/risk-reports-dashboard.html"',
        'href="/video-agents.html"',
        'href="/accountant-dashboard.html"',
        'href="/cyber-security.html"',
        "open_risk_reports:",
    ):
        assert needle in content, needle
    report = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "admin-ai-report.html"
    page = report.read_text(encoding="utf-8")
    assert "phins-doc-return.js" in page
    assert "phins-doc-banner" in page
    assert 'src="/phins-logo.svg"' in page
    assert "phins-doc-wordmark" in page
    assert "Personal Health Insurance" in page
    assert "/api/admin/ai-bi/reports/" in page
    assert "facts_sha256" in page
