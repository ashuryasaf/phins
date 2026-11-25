"""ADL 3 premium release cost: years on the table times the annual premium.

The test reads the registered policies and the active tables. It writes none
of them, and a figure it cannot read is withheld rather than filled in.
"""

import copy
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from services import adl3_release_cost as release
from services.adl3_disabled_life_expectancy import (
    TABLE_NAME,
    adl3_disabled_life_expectancy_rows,
    adl3_row_at,
)

AS_OF = date(2026, 11, 25)

TABLES = {
    TABLE_NAME: adl3_disabled_life_expectancy_rows(),
    "mortality_rates": [
        {"age_min": 0, "age_max": 50, "rate_per_1000": 2.0},
        {"age_min": 50, "age_max": 120, "rate_per_1000": 10.0},
    ],
    "disability_incidence_rates": [
        {"age_min": 0, "age_max": 50, "rate_per_1000": 8.0},
        {"age_min": 50, "age_max": 120, "rate_per_1000": 20.0},
    ],
}


def _years(age, column):
    return adl3_row_at(TABLES[TABLE_NAME], age)[column]


def _books():
    policies = {
        # Woman born 1980-05-01: 46 on the as-of date. Two full years paid.
        "POL-R1": {"id": "POL-R1", "customer_id": "CUST-R1", "status": "active", "type": "life",
                   "annual_premium": 1200.00, "start_date": "2024-01-10",
                   "disability_sum_used": 25000.00, "disability_premium_annual": 280.00,
                   "risk_premium_annual": 700.00},
        # Man, issue age 60 five years ago: 65 today.
        "POL-R2": {"id": "POL-R2", "customer_id": "CUST-R2", "status": "active", "type": "life",
                   "annual_premium": 3000.50, "start_date": "2021-06-01", "age": 60,
                   "gender": "male"},
        # Age on the application, no sex anywhere: the published average.
        "POL-R3": {"id": "POL-R3", "customer_id": "CUST-R3", "status": "approved", "type": "life",
                   "annual_premium": 640.00, "start_date": "2026-03-01", "underwriting_id": "UW-R3"},
        # No age on any record: withheld.
        "POL-R4": {"id": "POL-R4", "customer_id": "CUST-R4", "status": "active",
                   "annual_premium": 900.00, "start_date": "2025-01-01"},
        # Not in force: out of scope, counted by status.
        "POL-R5": {"id": "POL-R5", "customer_id": "CUST-R1", "status": "pending_underwriting",
                   "annual_premium": 500.00, "age": 30},
        # No premium: withheld.
        "POL-R6": {"id": "POL-R6", "customer_id": "CUST-R2", "status": "active",
                   "annual_premium": 0, "age": 40},
        # A sandbox account is left out of the book.
        "POL-R7": {"id": "POL-R7", "customer_id": "TESTSIM-9", "status": "active",
                   "annual_premium": 700.00, "age": 40},
    }
    customers = {
        "CUST-R1": {"id": "CUST-R1", "name": "Dana Levi", "dob": "1980-05-01", "gender": "Female"},
        "CUST-R2": {"id": "CUST-R2", "name": "Omer Katz", "gender": "M"},
        "CUST-R3": {"id": "CUST-R3", "name": "Sam Gold"},
        "CUST-R4": {"id": "CUST-R4", "name": "No Age"},
        "TESTSIM-9": {"id": "TESTSIM-9", "name": "Sandbox"},
    }
    applications = {"UW-R3": {"id": "UW-R3", "policy_id": "POL-R3", "age": 52}}
    return policies, customers, applications


def _book(**overrides):
    policies, customers, applications = _books()
    arguments = dict(
        policies=policies, customers=customers, applications=applications,
        tables=TABLES, tables_version="V-TEST", discount_rate=0.035, as_of=AS_OF,
        exclude_customer=lambda customer_id: "TESTSIM" in customer_id.upper(),
    )
    arguments.update(overrides)
    return release.build_release_cost_book(**arguments)


def _row(book, policy_id):
    return next(row for row in book["policies"] if row["policy_id"] == policy_id)


def _check(book, name):
    return next(check for check in book["integrity"]["checks"] if check["name"] == name)


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------

def test_release_cost_is_table_years_times_annual_premium():
    book = _book()

    woman = _row(book, "POL-R1")
    assert woman["attained_age"] == 46
    assert woman["age_source"] == "customer_date_of_birth"
    assert (woman["sex_used"], woman["sex_basis"]) == ("female", "customer_record")
    assert woman["expectancy_years"] == _years(46, "female_years")
    assert woman["released_years"] == woman["expectancy_years"]
    assert woman["release_cost"] == round(_years(46, "female_years") * 1200.00, 2)

    man = _row(book, "POL-R2")
    assert man["attained_age"] == 65
    assert man["age_source"] == "policy_issue_age_plus_years_in_force"
    assert man["sex_used"] == "male"
    # 4.41 x 3000.50 = 13232.205: half a cent rounds up, as the books do.
    expected = (Decimal(str(_years(65, "male_years"))) * Decimal("3000.50")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert Decimal(str(man["release_cost"])) == expected == Decimal("13232.21")

    unknown_sex = _row(book, "POL-R3")
    assert unknown_sex["attained_age"] == 52
    assert unknown_sex["age_source"] == "application_age_plus_years_in_force"
    assert (unknown_sex["sex_used"], unknown_sex["sex_basis"]) == ("average", "average_sex_not_recorded")
    assert unknown_sex["expectancy_years"] == round(_years(52, "average_years"), 6)

    total = sum(Decimal(str(row["release_cost"])) for row in book["policies"])
    assert Decimal(str(book["totals"]["release_cost"])) == total
    assert book["totals"]["annual_premium"] == 1200.00 + 3000.50 + 640.00


def test_registered_book_is_counted_and_missing_figures_are_withheld():
    book = _book()
    summary = book["summary"]

    assert summary["customers_registered"] == 4
    assert summary["policies_registered"] == 6
    assert summary["policies_on_suspended_accounts"] == 1
    assert summary["policies_in_force"] == 5
    assert summary["policies_assessed"] == 3
    assert summary["policies_withheld"] == 2
    assert summary["withheld_reasons"] == {"no_age_on_record": 1, "no_annual_premium": 1}
    assert summary["policies_not_in_force_by_status"] == {"pending_underwriting": 1}

    withheld = {item["policy_id"]: item["reason"] for item in book["withheld"]}
    assert withheld == {"POL-R4": "no_age_on_record", "POL-R6": "no_annual_premium"}
    assert all(row["policy_id"] not in ("POL-R5", "POL-R7") for row in book["policies"])
    assert book["integrity"]["ok"] is True
    assert all(check["ok"] for check in book["integrity"]["checks"])


def test_years_of_premium_payment_cap_the_released_years():
    whole = _book()
    capped = _book(premium_payment_years=4)

    # Two full years paid of four: two years of premium are still due.
    woman = _row(capped, "POL-R1")
    assert woman["years_paid"] == 2
    assert woman["remaining_payment_years"] == 2
    assert woman["released_years"] == 2.0
    assert woman["release_cost"] == 2400.00
    assert woman["projection_years_run"] == 2

    # Five years paid of four: no premium is left to release.
    man = _row(capped, "POL-R2")
    assert man["remaining_payment_years"] == 0
    assert man["release_cost"] == 0.0
    assert man["projection_years_run"] == 0

    # A term longer than the table years does not add any.
    long_term = _book(premium_payment_years=60)
    assert _row(long_term, "POL-R1")["release_cost"] == _row(whole, "POL-R1")["release_cost"]

    assert capped["totals"]["release_cost"] < whole["totals"]["release_cost"]
    assert capped["parameters"]["payment_basis"] == "premium_payment_term"
    assert whole["parameters"]["payment_basis"] == "whole_expectancy"
    assert capped["integrity"]["ok"] is True
    assert capped["integrity"]["result_hash"] != whole["integrity"]["result_hash"]


def test_projection_weights_the_release_cost_by_the_active_tables():
    book = _book(only_customer_id="CUST-R1", include_projections=True, projection_years=3)
    row = _row(book, "POL-R1")
    years = row["projection"]
    assert [year["attained_age"] for year in years] == [46, 47, 48]

    in_force = 1.0
    for year in years:
        cost = round(_years(year["attained_age"], "female_years") * 1200.00, 2)
        assert year["release_cost"] == cost
        assert year["in_force_probability"] == round(in_force, 8)
        probability = round(in_force * (1 - 0.002) * 0.008, 10)
        assert year["event_probability"] == probability
        assert year["expected_release_cost"] == pytest.approx(cost * probability, abs=0.006)
        in_force = in_force * (1 - 0.002) * (1 - 0.008)

    assert row["expected_release_cost_year1"] == years[0]["expected_release_cost"]
    assert row["expected_release_cost_projected"] == pytest.approx(
        sum(year["expected_release_cost"] for year in years), abs=0.001)
    assert row["expected_release_cost_pv"] == pytest.approx(
        sum(year["discounted_expected_release_cost"] for year in years), abs=0.001)
    assert years[0]["discounted_expected_release_cost"] == pytest.approx(
        years[0]["expected_release_cost"] / 1.035, abs=0.006)
    assert book["projection"][0]["release_cost_at_risk"] == row["release_cost"]


def test_adjusted_risk_adds_the_expected_release_cost_to_the_priced_premium():
    book = _book()
    row = _row(book, "POL-R1")
    expected = row["expected_release_cost_year1"]

    assert row["disability_premium_annual"] == 280.00
    assert row["priced_risk_basis"] == "kernel_pin"
    assert row["adjusted_disability_premium_annual"] == pytest.approx(280.00 + expected, abs=0.001)
    assert row["disability_premium_uplift_pct"] == round(expected / 280.00 * 100, 4)
    assert row["adjusted_risk_premium_annual"] == pytest.approx(700.00 + expected, abs=0.001)
    assert row["risk_premium_uplift_pct"] == round(expected / 700.00 * 100, 4)

    # No pin: the priced premium is not estimated.
    unpinned = _row(book, "POL-R2")
    assert unpinned["disability_premium_annual"] is None
    assert unpinned["priced_risk_basis"] == "not_pinned"
    assert unpinned["adjusted_disability_premium_annual"] is None

    adjusted = book["adjusted_risk"]
    assert adjusted["policies_with_priced_disability_premium"] == 1
    assert adjusted["policies_without_priced_disability_premium"] == 2
    assert adjusted["disability_premium_annual"] == 280.00
    assert adjusted["expected_release_cost_on_those_policies"] == expected
    assert adjusted["adjusted_disability_premium_annual"] == pytest.approx(280.00 + expected, abs=0.001)
    assert adjusted["risk_premium_annual"] == 700.00
    assert _check(book, "adjusted_risk_is_priced_risk_plus_release_cost")["ok"] is True


def test_adjusted_risk_adds_the_release_cost_to_the_pinned_disability_sum():
    book = _book()
    row = _row(book, "POL-R1")

    assert row["disability_sum"] == 25000.00
    assert row["adjusted_disability_exposure"] == 25000.00 + row["release_cost"]
    assert row["risk_uplift_pct"] == round(row["release_cost"] / 25000.00 * 100, 4)
    assert row["adjusted_expected_disability_year1"] == pytest.approx(
        row["expected_disability_claim_year1"] + row["expected_release_cost_year1"], abs=0.001)

    # No pin: the sum is not estimated.
    unpinned = _row(book, "POL-R2")
    assert unpinned["disability_sum"] is None
    assert unpinned["disability_sum_basis"] == "not_pinned"
    assert unpinned["adjusted_disability_exposure"] is None

    adjusted = book["adjusted_risk"]
    assert adjusted["policies_with_disability_sum"] == 1
    assert adjusted["policies_without_disability_sum"] == 2
    assert adjusted["disability_sum"] == 25000.00
    assert adjusted["release_cost_on_those_policies"] == row["release_cost"]
    assert adjusted["adjusted_disability_exposure"] == 25000.00 + row["release_cost"]


def test_a_broken_pin_seal_is_not_read():
    policies, customers, applications = _books()
    policies["POL-R1"]["kernel_pin_intact"] = False
    book = _book(policies=policies, customers=customers, applications=applications)
    row = _row(book, "POL-R1")
    assert row["disability_sum"] is None
    assert row["disability_sum_basis"] == "pin_seal_broken"
    assert row["disability_premium_annual"] is None
    assert row["priced_risk_basis"] == "pin_seal_broken"
    assert row["adjusted_disability_premium_annual"] is None
    assert row["release_cost"] > 0


# ---------------------------------------------------------------------------
# Integrity
# ---------------------------------------------------------------------------

def test_the_read_changes_no_record_and_is_deterministic():
    policies, customers, applications = _books()
    tables = copy.deepcopy(TABLES)
    before = copy.deepcopy((policies, customers, applications, tables))

    first = _book(policies=policies, customers=customers, applications=applications, tables=tables)
    second = _book(policies=policies, customers=customers, applications=applications, tables=tables)

    assert (policies, customers, applications, tables) == before
    assert first == second
    assert first["writes_nothing"] is True
    assert len(first["integrity"]["result_hash"]) == 64
    assert all(len(row["integrity_hash"]) == 64 for row in first["policies"])


def test_a_changed_premium_or_table_changes_the_seals():
    base = _book()

    policies, customers, applications = _books()
    policies["POL-R1"]["annual_premium"] = 1200.01
    moved = _book(policies=policies, customers=customers, applications=applications)
    assert _row(moved, "POL-R1")["integrity_hash"] != _row(base, "POL-R1")["integrity_hash"]
    assert _row(moved, "POL-R2")["integrity_hash"] == _row(base, "POL-R2")["integrity_hash"]
    assert moved["integrity"]["result_hash"] != base["integrity"]["result_hash"]

    tables = copy.deepcopy(TABLES)
    for row in tables[TABLE_NAME]:
        if row["age"] == 46:
            row["female_years"] = row["female_years"] + 1
    replaced = _book(tables=tables)
    assert replaced["table"]["integrity_hash"] != base["table"]["integrity_hash"]
    assert _row(replaced, "POL-R1")["release_cost"] == pytest.approx(
        _row(base, "POL-R1")["release_cost"] + 1200.00, abs=0.001)
    assert replaced["integrity"]["ok"] is True


def test_table_fingerprint_is_the_one_the_registry_shows():
    from services.actuarial_service import build_rate_tables_registry, get_actuarial_store

    tables, version, discount_rate = release.load_actuarial_basis()
    book = release.build_release_cost_book(
        policies={}, tables=tables, tables_version=version, discount_rate=discount_rate, as_of=AS_OF)
    entry = next(
        item for item in build_rate_tables_registry([], include_rows=False)
        if item["id"] == f"global:{TABLE_NAME}"
    )
    assert book["table"]["integrity_hash"] == entry["integrity_hash"]
    assert book["table"]["tables_version"] == get_actuarial_store().current_version
    assert book["table"]["used_in_pricing"] is False
    assert book["integrity"]["ok"] is True
    assert book["totals"]["release_cost"] == 0.0


def test_a_hole_in_the_table_is_withheld_and_not_filled_from_a_neighbour():
    tables = copy.deepcopy(TABLES)
    tables[TABLE_NAME] = [row for row in tables[TABLE_NAME] if row["age"] != 46]
    book = _book(tables=tables)
    withheld = {item["policy_id"]: item["reason"] for item in book["withheld"]}
    assert withheld["POL-R1"] == "no_expectancy_row"
    assert all(row["policy_id"] != "POL-R1" for row in book["policies"])
    assert book["integrity"]["ok"] is True


def test_a_missing_rate_stops_the_projection_and_keeps_the_release_cost():
    tables = copy.deepcopy(TABLES)
    tables["disability_incidence_rates"] = [{"age_min": 0, "age_max": 48, "rate_per_1000": 8.0}]
    book = _book(tables=tables, only_customer_id="CUST-R1", include_projections=True)
    row = _row(book, "POL-R1")
    assert row["release_cost"] == round(_years(46, "female_years") * 1200.00, 2)
    assert row["projection_years_run"] == 2
    assert row["projection_stopped"] == {"age": 48, "reason": "no_disability_incidence_rate"}


def test_records_that_disagree_on_sex_use_the_average_and_say_so():
    policies, customers, applications = _books()
    policies["POL-R1"]["gender"] = "male"
    book = _book(policies=policies, customers=customers, applications=applications)
    row = _row(book, "POL-R1")
    assert (row["sex_used"], row["sex_basis"]) == ("average", "average_records_disagree")
    assert row["expectancy_years"] == round(_years(46, "average_years"), 6)


def test_reference_grid_and_single_case_use_the_same_table():
    book = _book(
        reference_annual_premium=Decimal("1000.00"),
        case={"age": 40, "sex": "female", "annual_premium": Decimal("2000.00"), "years_paid": 3},
        premium_payment_years=5,
    )
    grid = {row["age"]: row for row in book["reference"]["rows"]}
    assert grid[40]["male_years"] == _years(40, "male_years")
    assert grid[40]["male_released_years"] == min(_years(40, "male_years"), 5.0)
    assert grid[40]["female_release_cost"] == round(min(_years(40, "female_years"), 5.0) * 1000.00, 2)

    case = book["case"]
    assert case["status"] == "assessed"
    assert case["remaining_payment_years"] == 2
    assert case["released_years"] == 2.0
    assert case["release_cost"] == 4000.00


def test_parameters_are_validated():
    assert release.parse_premium_payment_years("") is None
    assert release.parse_premium_payment_years(" 20 ") == 20
    for bad in ("0", "111", "2.5", "abc", "-3"):
        with pytest.raises(ValueError):
            release.parse_premium_payment_years(bad)
    assert release.parse_projection_years(None) == release.PROJECTION_YEARS_DEFAULT
    with pytest.raises(ValueError):
        release.parse_projection_years("61")
    assert release.parse_case(None, None, None, None) is None
    with pytest.raises(ValueError):
        release.parse_case("40", "female", None, None)
    with pytest.raises(ValueError):
        release.parse_case("40", "other", "100", None)
    with pytest.raises(ValueError):
        release.parse_case("0", "male", "100", None)
    with pytest.raises(ValueError):
        release.parse_reference_premium("-5")


def test_customer_book_carries_only_that_customer_and_only_the_release_cost():
    book = _book(only_customer_id="CUST-R1")
    own = release.customer_release_cost(book, "CUST-R1")

    assert [row["policy_id"] for row in own["policies"]] == ["POL-R1"]
    assert own["totals"] == {"policies": 1, "annual_premium": 1200.00,
                             "release_cost": _row(book, "POL-R1")["release_cost"]}
    assert own["integrity"]["ok"] is True
    text = json.dumps(own)
    for other in ("CUST-R2", "POL-R2", "Omer Katz", "disability_incidence_ix",
                  "expected_release_cost", "disability_sum", "disability_premium",
                  "risk_premium", "customer_name"):
        assert other not in text


# ---------------------------------------------------------------------------
# Through the portal
# ---------------------------------------------------------------------------

def _http(path, token=None):
    base = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with urlopen(Request(base + path, headers=headers), timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


@pytest.fixture
def portal_books():
    import web_portal.server as portal

    policies, customers, applications = _books()
    # The portal route reads UTC today. Hold POL-R1 at two full years in force
    # so a four-year premium term still releases two years.
    today = datetime.now(timezone.utc).date()
    policies["POL-R1"]["start_date"] = date(today.year - 2, 1, 1).isoformat()
    for customer_id, customer in customers.items():
        portal.CUSTOMERS[customer_id] = customer
    for policy_id, policy in policies.items():
        portal.POLICIES[policy_id] = policy
    for app_id, app in applications.items():
        portal.UNDERWRITING_APPLICATIONS[app_id] = app
    sessions = {
        "phins_adl3rc-admin": {"username": "admin", "role": "admin"},
        "phins_adl3rc-actuary": {"username": "actuary", "role": "actuary"},
        "phins_adl3rc-accountant": {"username": "accountant", "role": "accountant"},
        "phins_adl3rc-cust1": {"username": "dana@test", "role": "customer", "customer_id": "CUST-R1"},
        "phins_adl3rc-cust2": {"username": "omer@test", "role": "customer", "customer_id": "CUST-R2"},
    }
    for token, payload in sessions.items():
        portal.SESSIONS[token] = portal._stamp_session_payload(
            dict(payload, expires="2099-01-01T00:00:00"))
    init_set = getattr(portal, "_TEST_PORTS_INITIALIZED", None)
    if isinstance(init_set, set):
        init_set.add(int(os.environ.get("TEST_PORT", "8000")))
    try:
        yield portal
    finally:
        for token in sessions:
            portal.SESSIONS.pop(token, None)
        for policy_id in policies:
            portal.POLICIES.pop(policy_id, None)
        for customer_id in customers:
            portal.CUSTOMERS.pop(customer_id, None)
        for app_id in applications:
            portal.UNDERWRITING_APPLICATIONS.pop(app_id, None)


def test_actuarial_route_serves_the_book_to_admin_and_actuary_only(portal_books):
    portal = portal_books
    stores = (portal.POLICIES, portal.CUSTOMERS, portal.UNDERWRITING_APPLICATIONS,
              portal.BILLING, portal.TRANSACTION_LEDGER, portal.NFT_LEDGER)
    before = copy.deepcopy([dict(store) for store in stores])

    for token in ("phins_adl3rc-admin", "phins_adl3rc-actuary"):
        status, body = _http("/api/actuarial/adl3-release-cost", token)
        assert status == 200, body
        book = body["release_cost"]
        assert book["integrity"]["ok"] is True
        ids = {row["policy_id"] for row in book["policies"]}
        assert {"POL-R1", "POL-R2", "POL-R3"} <= ids
        assert "POL-R7" not in ids and "POL-R5" not in ids
        assert "projection" not in book["policies"][0]

    status, body = _http(
        "/api/actuarial/adl3-release-cost?premium_payment_years=4&projection_years=5"
        "&customer_id=CUST-R1&case_age=40&case_sex=male&case_annual_premium=1000", "phins_adl3rc-actuary")
    assert status == 200, body
    book = body["release_cost"]
    assert [row["policy_id"] for row in book["policies"]] == ["POL-R1"]
    assert book["policies"][0]["projection"]
    assert book["parameters"]["premium_payment_years"] == 4
    assert book["parameters"]["projection_years"] == 5
    assert book["case"]["released_years"] == 4.0
    assert book["case"]["release_cost"] == 4000.00

    for query in ("premium_payment_years=0", "premium_payment_years=abc", "projection_years=99",
                  "case_age=40", "reference_annual_premium=0"):
        status, body = _http(f"/api/actuarial/adl3-release-cost?{query}", "phins_adl3rc-admin")
        assert status == 400 and "error" in body, query

    for token in ("phins_adl3rc-accountant", "phins_adl3rc-cust1", None):
        status, body = _http("/api/actuarial/adl3-release-cost", token)
        assert status in (401, 403) and "error" in body
        assert "release_cost" not in body

    assert [dict(store) for store in stores] == before


def test_customer_route_serves_only_the_callers_own_book(portal_books):
    portal = portal_books
    before = copy.deepcopy(dict(portal.POLICIES))

    status, body = _http("/api/customer/adl3-release-cost", "phins_adl3rc-cust1")
    assert status == 200, body
    own = body["release_cost"]
    assert own["customer_id"] == "CUST-R1"
    assert [row["policy_id"] for row in own["policies"]] == ["POL-R1"]
    assert own["writes_nothing"] is True
    assert "CUST-R2" not in json.dumps(own) and "POL-R2" not in json.dumps(own)

    status, body = _http("/api/customer/adl3-release-cost?premium_payment_years=4", "phins_adl3rc-cust1")
    assert status == 200, body
    assert body["release_cost"]["policies"][0]["released_years"] == 2.0
    assert body["release_cost"]["totals"]["release_cost"] == 2400.00

    # Another customer's id in the query is refused, not answered with their book.
    status, body = _http("/api/customer/adl3-release-cost?customer_id=CUST-R2", "phins_adl3rc-cust1")
    assert status == 403 and "error" in body

    # The second customer sees the withheld policy with its reason, and no figure for it.
    status, body = _http("/api/customer/adl3-release-cost", "phins_adl3rc-cust2")
    assert status == 200, body
    own = body["release_cost"]
    assert [row["policy_id"] for row in own["policies"]] == ["POL-R2"]
    assert [(item["policy_id"], item["reason"]) for item in own["withheld"]] == [
        ("POL-R6", "no_annual_premium")]

    status, body = _http("/api/customer/adl3-release-cost?premium_payment_years=200", "phins_adl3rc-cust1")
    assert status == 400 and "error" in body

    status, body = _http("/api/customer/adl3-release-cost")
    assert status in (401, 403) and "error" in body

    assert dict(portal.POLICIES) == before


def test_dashboards_carry_the_release_cost_surfaces():
    static = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "web_portal", "static")
    with open(os.path.join(static, "actuary-dashboard.html"), encoding="utf-8") as handle:
        actuary = handle.read()
    assert 'id="section-adl3-release"' in actuary
    assert "showSection('adl3-release')" in actuary
    assert 'id="adl3rc-payment-years"' in actuary
    assert '<script src="/adl3-release-cost.js"></script>' in actuary

    with open(os.path.join(static, "adl3-release-cost.js"), encoding="utf-8") as handle:
        script = handle.read()
    assert "/api/actuarial/adl3-release-cost" in script
    assert "method: 'POST'" not in script

    with open(os.path.join(static, "dashboard.html"), encoding="utf-8") as handle:
        customer = handle.read()
    assert 'id="premium-release-card"' in customer
    assert 'id="premium-release-years"' in customer
    assert "/api/customer/adl3-release-cost" in customer
    assert "await loadPremiumRelease();" in customer
