"""Read-only regulation viewer: redacted outline, book integrity, access gate."""

from __future__ import annotations

import os

import pytest
import requests

from services.actuarial_service import ActuarialTablesStore
from services.regulator_outline import (
    RegulatorIntegrityError,
    aggregate_claims,
    build_regulator_outline,
)

BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")


def _store() -> ActuarialTablesStore:
    return ActuarialTablesStore()


def _books():
    policies = [{
        "id": "POL-SECRET-1",
        "customer_id": "CUST-SECRET-1",
        "customer_name": "Jane Secret",
        "email": "jane@example.com",
        "phone": "+15551212",
        "type": "health",
        "status": "active",
        "annual_premium": 1200,
        "coverage_amount": 50000,
        "investment_value": 300,
    }, {
        "id": "POL-SECRET-2",
        "customer_id": "CUST-SECRET-2",
        "type": "life",
        "status": "active",
        "annual_premium": 800,
        "coverage_amount": 20000,
        "investment_value": 50,
    }]
    claims = [{
        "id": "CLM-SECRET-1",
        "customer_id": "CUST-SECRET-1",
        "status": "paid",
        "claimed_amount": 400,
        "approved_amount": 250,
        "paid_amount": 250,
        "diagnosis": "private condition",
    }, {
        "id": "CLM-SECRET-2",
        "customer_id": "CUST-SECRET-2",
        "status": "pending",
        "claimed_amount": 125,
        "approved_amount": 0,
    }]
    underwriting = [{
        "customer_id": "CUST-SECRET-1",
        "applicant_name": "Jane Secret",
        "status": "approved",
        "risk_assessment": "low",
        "medical_notes": "do not disclose",
    }, {
        "customer_id": "CUST-SECRET-2",
        "status": "rejected",
        "risk_score": 90,
    }]
    wallets = [{
        "customer_id": "CUST-SECRET-1",
        "balance": 80,
        "transactions": [{"type": "deposit", "amount": 80, "note": "jane@example.com"}],
    }]
    investments = [{
        "customer_id": "CUST-SECRET-1",
        "balance": 1000,
        "investment_route": "basic_savings",
        "account_number": "SECRET-ACCT",
    }]
    agents = [{
        "id": "AGT-SECRET-1",
        "email": "agent@example.com",
        "display_name": "Named Agent",
        "username": "named.agent",
        "status": "active",
        "default_commission_rate": 0.1,
    }]
    commissions = [{
        "id": "COMM-SECRET-1",
        "agent_id": "AGT-SECRET-1",
        "principal_id": "CUST-SECRET-1",
        "status": "accrued",
        "amount": 40,
    }]
    canonical = {
        "claims_disbursed_amount": 250,
        "claims_paid_amount": 250,
        "pending_claims_liability": 125,
        "total_claims": 2,
        "total_policies": 2,
        "active_policies": 2,
        "total_revenue": 2000,
        "total_coverage_amount": 70000,
        "total_investment_value": 350,
        "total_applications": 2,
        "pending_applications": 0,
        "approved_applications": 1,
        "rejected_applications": 1,
    }
    return {
        "policies": policies,
        "claims": claims,
        "underwriting": underwriting,
        "health_wallets": wallets,
        "investment_accounts": investments,
        "agents": agents,
        "commissions": commissions,
        "canonical": canonical,
    }


def _outline(**overrides):
    books = _books()
    books.update(overrides)
    canonical = books.pop("canonical")
    return build_regulator_outline(actuarial_store=_store(), canonical=canonical, **books)


def test_outline_drops_customer_secrets():
    outline = _outline()
    blob = str(outline).lower()
    for needle in (
        "jane@example.com",
        "cust-secret",
        "pol-secret",
        "clm-secret",
        "agt-secret",
        "comm-secret",
        "jane secret",
        "private condition",
        "do not disclose",
        "named agent",
        "secret-acct",
        "+15551212",
    ):
        assert needle not in blob
    assert outline["access"] == "read_only"
    assert outline["integrity"]["reconciled"] is True
    assert len(outline["integrity"]["outline_sha256"]) == 64


def test_totals_match_the_books():
    outline = _outline()
    assert outline["claims"]["disbursed_amount"] == 250
    assert outline["claims"]["pending_liability"] == 125
    assert outline["claims"]["claimed_amount"] == 525
    assert outline["policies"]["annual_premium_active"] == 2000
    assert outline["health"]["health_policies"] == 1
    assert outline["health"]["wallet_balance"] == 80
    assert outline["health"]["health_annual_premium"] == 1200
    assert outline["investments"]["account_balance"] == 1000
    assert outline["investments"]["by_route"]["basic_savings"] == 1000
    assert outline["investments"]["policy_investment_value"] == 350
    assert outline["agents"]["agent_count"] == 1
    assert outline["agents"]["commission_amount"] == 40
    assert outline["underwriting"]["approved"] == 1
    assert outline["underwriting"]["rejected"] == 1
    assert outline["underwriting"]["risk_bands"]["low"] == 1
    assert outline["underwriting"]["risk_bands"]["76_100"] == 1
    assert outline["policies"]["coverage_active"] == 70000


def test_basic_premiums_follow_the_active_kernel_version():
    store = _store()
    first = build_regulator_outline(actuarial_store=store)
    rows = first["pricing"]["basic_premiums"]["rows"]
    assert [row["age"] for row in rows] == [30, 40, 50, 60]
    assert {row["tables_version"] for row in rows} == {store.current_version}
    assert {row["config_version"] for row in rows} == {store.config.config_version}
    assert all(row["annual_premium"] > 0 for row in rows)
    premiums = first["pricing"]["basic_premiums"]
    assert premiums["product_id"] == "phins_pure_risk_adjustable"
    assert premiums["coverage"] == 100000
    assert premiums["term_years"] == 20
    assert "adl_level" not in premiums
    assert "internal_score_disclaimer" not in premiums
    assert "adl_level" not in rows[0]
    disability = first["pricing"]["rate_bands"]["disability_incidence_rates"]
    source_disability = store.get_current_tables()["disability_incidence_rates"]
    assert [row["rate_per_1000"] for row in disability] == [
        row["rate_per_1000"] for row in source_disability
    ]
    assert [row["age_min"] for row in disability] == [row["age_min"] for row in source_disability]
    published = str(first).lower()
    assert "internal underwriting score" not in published
    assert "fully disabled" not in published
    assert "not the average" not in published
    age_40 = rows[1]["annual_premium"]

    band = next(
        row for row in store.versions[store.current_version]["mortality_rates"]
        if row["age_min"] <= 40 < row["age_max"]
    )
    band["rate_per_1000"] = 80
    second = build_regulator_outline(actuarial_store=store)
    assert second["pricing"]["basic_premiums"]["rows"][1]["annual_premium"] != age_40
    assert second["pricing"]["versions"][0]["integrity_hash"] != first["pricing"]["versions"][0]["integrity_hash"]
    assert second["pricing"]["current_version"] == store.current_version


def test_outline_omits_underwriting_score_detail_and_keeps_the_tariff():
    from services.pricing_kernel import (
        PricingCustomer,
        get_product,
        price_policy,
        pricing_config_from_underwriting,
        table_set_from_store,
    )

    store = _store()
    outline = build_regulator_outline(
        actuarial_store=store,
        policies=[{
            "type": "life",
            "status": "active",
            "annual_premium": 100,
            "coverage_amount": 250000,
        }, {
            "type": "life",
            "status": "lapsed",
            "annual_premium": 80,
            "coverage_amount": 900000,
        }],
        underwriting=[{
            "status": "approved",
            "adl_level": 8,
            "adl_level_source": "stated",
            "risk_assessment": "low",
        }],
    )
    assert outline["policies"]["coverage_active"] == 250000
    assert outline["underwriting"]["approved"] == 1
    assert "internal_score_mean" not in outline["underwriting"]
    assert "decline_threshold" not in outline["pricing"]["rules_in_force"]
    priced = price_policy(
        PricingCustomer(age=40, coverage=100000, term_years=20, adl_level=5, smoking_status="nonsmoker"),
        get_product("phins_pure_risk_adjustable"),
        table_set_from_store(store),
        pricing_config_from_underwriting(store.config),
    )
    age_40 = outline["pricing"]["basic_premiums"]["rows"][1]["annual_premium"]
    assert age_40 == round(priced.annual_premium, 2)


def test_regulator_dashboard_captions_omit_score_detail():
    """The published view describes each chart in one sentence and keeps scores off it."""
    page = os.path.join(
        os.path.dirname(__file__), "..", "web_portal", "static", "regulator-dashboard.html"
    )
    text = open(page, encoding="utf-8").read().lower()
    for needle in (
        "internal underwriting score",
        "fully disabled",
        "not the average",
        "highest score still accepted",
        "decline line",
        "adl 6+",
    ):
        assert needle not in text
    assert "total coverage" in text
    assert "policies.coverage_active" in text
    assert "basic disability rates" in text
    assert "disability_incidence_rates" in text
    assert "underwriting decisions by status." in text
    assert "not a customer quote." in text


def test_divergent_books_are_refused():
    books = _books()
    books["canonical"]["total_claims"] = 99
    with pytest.raises(RegulatorIntegrityError):
        build_regulator_outline(actuarial_store=_store(), **books)


def test_identifier_in_a_status_is_refused():
    books = _books()
    books["claims"][0]["status"] = "paid CUST-SECRET-1"
    with pytest.raises(RegulatorIntegrityError):
        build_regulator_outline(
            actuarial_store=_store(),
            claims=books["claims"],
        )


def test_open_claims_match_the_claims_dashboard_set():
    totals = aggregate_claims([
        {"status": "pending", "claimed_amount": 10, "approved_amount": 0},
        {"status": "under_review", "claimed_amount": 5, "approved_amount": 0},
        {"status": "medical_assessment", "claimed_amount": 80, "approved_amount": 0},
        {"status": "paid", "claimed_amount": 20, "approved_amount": 12, "paid_amount": 12},
    ])
    assert totals["pending"] == 2
    assert totals["pending_liability"] == 15
    assert totals["disbursed_amount"] == 12
    assert totals["claimed_amount"] == 115


def test_claims_paid_follows_the_admin_total_paid_out():
    """Admin Claims Paid is ledger cash, not the approved amount on paid files."""
    books = _books()
    books["ledger"] = {
        "ledger_premium_collected": 0,
        "ledger_claims_paid": 127450,
        "accounting_premium_posted": 0,
        "accounting_claims_posted": 708950,
        "economic_claims_reserve": 0,
    }
    books["canonical"]["ledger_claims_paid"] = 127450
    outline = build_regulator_outline(
        actuarial_store=_store(),
        policies=books["policies"],
        claims=books["claims"],
        underwriting=books["underwriting"],
        health_wallets=books["health_wallets"],
        investment_accounts=books["investment_accounts"],
        agents=books["agents"],
        commissions=books["commissions"],
        ledger=books["ledger"],
        canonical=books["canonical"],
    )
    assert outline["claims"]["disbursed_amount"] == 250
    assert outline["claims"]["paid_out"] == 127450
    assert outline["books"]["ledger_claims_paid"] == 127450
    assert outline["claims_loss_ratio"] == round(127450 / 2000, 2)

    books["canonical"]["ledger_claims_paid"] = 708950
    with pytest.raises(RegulatorIntegrityError):
        build_regulator_outline(
            actuarial_store=_store(),
            policies=books["policies"],
            claims=books["claims"],
            ledger=books["ledger"],
            canonical=books["canonical"],
        )


def test_billing_and_aum_must_match_the_canonical_books():
    books = _books()
    books["billing"] = [{
        "amount": 100,
        "amount_paid": 40,
        "status": "partial",
    }, {
        "amount": 50,
        "amount_paid": 50,
        "status": "paid",
    }]
    books["ledger"] = {
        "ledger_premium_collected": 40,
        "ledger_claims_paid": 250,
        "accounting_premium_posted": 40,
        "accounting_claims_posted": 250,
        "economic_claims_reserve": 10,
    }
    books["canonical"].update({
        "pending_claims": 1,
        "approved_claims": 0,
        "rejected_claims": 0,
        "total_investment_balance": 1000,
        "total_algo_balance": 0,
        "total_pipeline_cash": 0,
        "total_health_wallet": 80,
        "total_deposits": 80,
        "active_wallets": 1,
        "total_aum": 350 + 80 + 1000,
        "total_billed": 150,
        "total_collected": 90,
        "outstanding_balance": 60,
        "collection_rate": 60.0,
        "paid_count": 1,
        "pending_count": 0,
        "overdue_count": 0,
        "total_transactions": 2,
        **books["ledger"],
    })
    outline = build_regulator_outline(actuarial_store=_store(), **{
        key: books[key] for key in (
            "policies", "claims", "underwriting", "health_wallets",
            "investment_accounts", "billing", "agents", "commissions", "ledger",
        )
    }, canonical=books["canonical"])
    assert outline["billing"]["outstanding_balance"] == 60
    assert outline["billing"]["total_collected"] == 90
    assert outline["books"]["ledger_claims_paid"] == 250
    assert outline["investments"]["assets_under_management"] == 1430
    assert outline["claims"]["pending"] == 1

    books["canonical"]["total_aum"] = 1
    with pytest.raises(RegulatorIntegrityError):
        build_regulator_outline(actuarial_store=_store(), **{
            key: books[key] for key in (
                "policies", "claims", "underwriting", "health_wallets",
                "investment_accounts", "billing", "agents", "commissions", "ledger",
            )
        }, canonical=books["canonical"])


def test_live_outline_matches_admin_accounting_and_billing_books():
    import web_portal.server as portal

    metrics = portal.compute_unified_financial_metrics(exclude_suspended=True)
    outline = portal.build_live_regulator_outline()
    assert outline["claims"]["disbursed_amount"] == metrics["claims_disbursed_amount"]
    assert outline["claims"]["paid_amount"] == metrics["claims_paid_amount"]
    assert outline["claims"]["pending_liability"] == metrics["pending_claims_liability"]
    assert outline["claims"]["pending"] == metrics["pending_claims"]
    assert outline["investments"]["account_balance"] == metrics["total_investment_balance"]
    assert outline["investments"]["assets_under_management"] == metrics["total_aum"]
    assert outline["health"]["wallet_balance"] == metrics["total_health_wallet"]
    assert outline["health"]["wallet_deposits"] == metrics["total_deposits"]
    assert outline["billing"]["total_billed"] == metrics["total_billed"]
    assert outline["billing"]["total_collected"] == metrics["total_collected"]
    assert outline["billing"]["outstanding_balance"] == metrics["outstanding_balance"]
    assert outline["claims"]["paid_out"] == metrics["ledger_claims_paid"]
    assert outline["books"]["ledger_claims_paid"] == metrics["ledger_claims_paid"]
    assert outline["claims_loss_ratio"] == round(
        (metrics["ledger_claims_paid"] / metrics["total_revenue"]) if metrics["total_revenue"] else 0.0,
        2,
    )
    assert outline["books"]["ledger_premium_collected"] == metrics["ledger_premium_collected"]
    assert outline["integrity"]["reconciled"] is True


def test_suspended_wallet_and_investment_balances_stay_out_of_the_books():
    import web_portal.server as portal

    customer_id = "CUST-SUSPEND-BOOK-77"
    added = customer_id not in portal.SUSPENDED_TEST_ACCOUNTS
    previous_wallet = portal.HEALTH_WALLETS.get(customer_id)
    previous_account = portal.INVESTMENT_ACCOUNTS.get(customer_id)
    portal.SUSPENDED_TEST_ACCOUNTS.add(customer_id)
    try:
        before = portal.compute_unified_financial_metrics(exclude_suspended=True)
        portal.HEALTH_WALLETS[customer_id] = {
            "customer_id": customer_id,
            "balance": 999,
            "transactions": [{"type": "deposit", "amount": 999}],
        }
        portal.INVESTMENT_ACCOUNTS[customer_id] = {
            "customer_id": customer_id,
            "balance": 888,
        }
        hidden = portal.compute_unified_financial_metrics(exclude_suspended=True)
        assert hidden["total_health_wallet"] == before["total_health_wallet"]
        assert hidden["total_deposits"] == before["total_deposits"]
        assert hidden["total_investment_balance"] == before["total_investment_balance"]
        assert hidden["total_aum"] == before["total_aum"]
        portal.SUSPENDED_TEST_ACCOUNTS.discard(customer_id)
        shown = portal.compute_unified_financial_metrics(exclude_suspended=True)
        assert round(shown["total_health_wallet"] - before["total_health_wallet"], 2) == 999
        assert round(shown["total_investment_balance"] - before["total_investment_balance"], 2) == 888
    finally:
        if previous_wallet is None:
            portal.HEALTH_WALLETS.pop(customer_id, None)
        else:
            portal.HEALTH_WALLETS[customer_id] = previous_wallet
        if previous_account is None:
            portal.INVESTMENT_ACCOUNTS.pop(customer_id, None)
        else:
            portal.INVESTMENT_ACCOUNTS[customer_id] = previous_account
        if added:
            portal.SUSPENDED_TEST_ACCOUNTS.discard(customer_id)


def test_claim_buckets_match_the_running_total():
    totals = aggregate_claims([
        {"status": "paid", "claimed_amount": 10, "approved_amount": 4},
        {"status": "approved", "claimed_amount": 3, "approved_amount": 3},
    ])
    assert totals["claimed_amount"] == 13
    assert sum(totals["claimed_by_status"].values()) == 13


def _login(username, password):
    response = requests.post(f"{BASE_URL}/api/login", json={
        "username": username,
        "password": password,
    }, timeout=30)
    return response


def test_regulator_login_lands_on_the_outline():
    page = requests.get(f"{BASE_URL}/regulator-dashboard.html", timeout=30)
    assert page.status_code == 200
    assert "READ ONLY" in page.text
    assert "viewerRole" in page.text
    admin_page = requests.get(f"{BASE_URL}/admin.html", timeout=30)
    assert admin_page.status_code == 200
    assert 'href="/regulator-dashboard.html"' in admin_page.text
    actuary_page = requests.get(f"{BASE_URL}/actuary-dashboard.html", timeout=30)
    assert actuary_page.status_code == 200
    assert 'href="/regulator-dashboard.html"' in actuary_page.text
    assert "/api/regulator/outline" in page.text
    assert "Download report" in page.text
    assert "chart-type" in page.text
    assert "/api/regulator/credentials" in page.text

    login = _login("regulator", "regulator123")
    assert login.status_code == 200, login.text
    body = login.json()
    assert body["role"] == "regulator"
    headers = {"Authorization": f"Bearer {body['token']}"}

    outline = requests.get(f"{BASE_URL}/api/regulator/outline", headers=headers, timeout=60)
    assert outline.status_code == 200, outline.text
    payload = outline.json()
    assert payload["access"] == "read_only"
    assert payload["pricing"]["current_version"]
    assert payload["pricing"]["basic_premiums"]["rows"]
    assert payload["integrity"]["reconciled"] is True
    blob = outline.text.lower()
    assert "cust-" not in blob
    assert "@" not in blob

    denied = requests.post(
        f"{BASE_URL}/api/regulator/outline",
        headers=headers,
        json={"status": "approved"},
        timeout=30,
    )
    assert denied.status_code == 403

    other = requests.get(f"{BASE_URL}/api/bi/executive-dashboard", headers=headers, timeout=30)
    assert other.status_code == 403

    admin = _login("admin", "admin123")
    assert admin.status_code == 200, admin.text
    admin_headers = {"Authorization": f"Bearer {admin.json()['token']}"}
    admin_outline = requests.get(f"{BASE_URL}/api/regulator/outline", headers=admin_headers, timeout=60)
    assert admin_outline.status_code == 200, admin_outline.text
    actuary = _login("actuary", "actuary123")
    assert actuary.status_code == 200, actuary.text
    actuary_outline = requests.get(
        f"{BASE_URL}/api/regulator/outline",
        headers={"Authorization": f"Bearer {actuary.json()['token']}"},
        timeout=60,
    )
    assert actuary_outline.status_code == 200, actuary_outline.text

    def _book(body):
        copied = dict(body)
        copied.pop("generated_at", None)
        copied.pop("integrity", None)
        return copied

    assert _book(admin_outline.json()) == _book(payload)
    assert _book(actuary_outline.json()) == _book(payload)
    assert admin_outline.json()["integrity"]["reconciled"] is True
    assert actuary_outline.json()["integrity"]["reconciled"] is True

    outsider = _login("underwriter", "under123")
    assert outsider.status_code == 200, outsider.text
    blocked = requests.get(
        f"{BASE_URL}/api/regulator/outline",
        headers={"Authorization": f"Bearer {outsider.json()['token']}"},
        timeout=30,
    )
    assert blocked.status_code == 403
    stolen = requests.post(
        f"{BASE_URL}/api/regulator/credentials",
        headers=admin_headers,
        json={"current_password": "admin123", "new_password": "admin-pass-1", "new_username": "regulator"},
        timeout=30,
    )
    assert stolen.status_code == 403


def test_regulator_gate_covers_the_apis_handled_before_it():
    login = _login("regulator", "regulator123")
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['token']}"}

    for path in (
        "/api/confidential/shares",
        "/api/meetings/notes",
        "/api/legal-docs/registry?doc_id=founders-agreement",
    ):
        response = requests.get(f"{BASE_URL}{path}", headers=headers, timeout=30)
        assert response.status_code == 403, f"{path}: {response.text}"
        assert "read-only outline" in response.json()["error"]


def test_a_replaced_regulator_login_is_retired_not_deleted():
    import web_portal.server as portal

    old_name = "regulator.rotation-probe"
    new_name = "regulator.rotation-probe2"
    record = {
        **portal.hash_password("rotation-pass-1"),
        "role": "regulator",
        "name": "Rotation Probe",
    }
    portal.USERS[old_name] = record
    portal._FALLBACK_USERS[old_name] = record
    try:
        status, payload = portal.update_regulator_credentials(
            {"username": old_name, "role": "regulator"},
            {
                "current_password": "rotation-pass-1",
                "new_password": "rotation-pass-2",
                "new_username": new_name,
            },
        )
        assert status == 200, payload
        assert payload["username"] == new_name

        # The replaced login keeps a record (so a seed pass or a fallback lookup
        # cannot resurrect it) that no password opens.
        retired = portal.USERS.get(old_name)
        assert retired is not None
        assert not portal.verify_password("rotation-pass-1", retired["hash"], retired["salt"])
        assert not portal.verify_password("rotation-pass-2", retired["hash"], retired["salt"])
        assert old_name in portal._regulator_legacy_retired()

        rotated = portal.USERS.get(new_name)
        assert portal.verify_password("rotation-pass-2", rotated["hash"], rotated["salt"])
    finally:
        for name in (old_name, new_name):
            portal._FALLBACK_USERS.pop(name, None)
            try:
                del portal.USERS[name]
            except Exception:
                pass
            portal._REGULATOR_LEGACY_RETIRED.discard(name)


def test_regulator_can_rotate_credentials_and_restore_them():
    login = _login("regulator", "regulator123")
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    replacement = "regulator-pass-1"
    try:
        weak = requests.post(
            f"{BASE_URL}/api/regulator/credentials",
            headers=headers,
            json={"current_password": "regulator123", "new_password": "short", "new_username": "regulator"},
            timeout=30,
        )
        assert weak.status_code == 400

        taken = requests.post(
            f"{BASE_URL}/api/regulator/credentials",
            headers=headers,
            json={"current_password": "regulator123", "new_password": replacement, "new_username": "admin"},
            timeout=30,
        )
        assert taken.status_code == 409

        changed = requests.post(
            f"{BASE_URL}/api/regulator/credentials",
            headers=headers,
            json={"current_password": "regulator123", "new_password": replacement, "new_username": "regulator"},
            timeout=30,
        )
        assert changed.status_code == 200, changed.text
        body = changed.json()
        assert body["username"] == "regulator"
        assert body["role"] == "regulator"
        assert body["token"]
        assert "password" not in body

        stale = _login("regulator", "regulator123")
        assert stale.status_code == 401

        fresh = _login("regulator", replacement)
        assert fresh.status_code == 200, fresh.text
        outline = requests.get(
            f"{BASE_URL}/api/regulator/outline",
            headers={"Authorization": f"Bearer {fresh.json()['token']}"},
            timeout=60,
        )
        assert outline.status_code == 200, outline.text
        denied = requests.post(
            f"{BASE_URL}/api/customers",
            headers={"Authorization": f"Bearer {fresh.json()['token']}"},
            json={"name": "nope"},
            timeout=30,
        )
        assert denied.status_code == 403
    finally:
        current = _login("regulator", replacement)
        if current.status_code != 200:
            current = _login("regulator", "regulator123")
        if current.status_code == 200:
            requests.post(
                f"{BASE_URL}/api/regulator/credentials",
                headers={"Authorization": f"Bearer {current.json()['token']}"},
                json={"current_password": replacement, "new_password": "regulator123", "new_username": "regulator"},
                timeout=30,
            )


def test_regulator_demo_password_works_until_an_operator_password_is_set(monkeypatch):
    """Production has no demo flag, but the regulation account stays usable."""
    import web_portal.server as portal

    original = dict(portal.USERS["regulator"])
    fallback_original = dict(portal._FALLBACK_USERS.get("regulator") or original)
    monkeypatch.setattr(portal, "ALLOW_LEGACY_DEMO_PASSWORDS", False)
    monkeypatch.delenv("PHINS_REGULATOR_PASSWORD", raising=False)
    portal._REGULATOR_LEGACY_RETIRED.discard("regulator")
    try:
        demo = _login("regulator", "regulator123")
        assert demo.status_code == 200, demo.text
        assert demo.json()["role"] == "regulator"

        operator_password = "operator-regulator-password"
        monkeypatch.setenv("PHINS_REGULATOR_PASSWORD", operator_password)
        stale = dict(original)
        hashed = portal.hash_password("unusable-random-secret")
        stale["hash"] = hashed["hash"]
        stale["salt"] = hashed["salt"]
        # Login accepts the fallback record when the primary hash does not
        # match. A credential rotation copies that record, so both stores have
        # to carry the unusable hash or the demo secret still opens the view.
        portal.USERS["regulator"] = stale
        portal._FALLBACK_USERS["regulator"] = dict(stale)

        rejected = _login("regulator", "regulator123")
        assert rejected.status_code == 401

        opened = _login("regulator", operator_password)
        assert opened.status_code == 200, opened.text
        assert opened.json()["role"] == "regulator"

        retired_demo = _login("regulator", "regulator123")
        assert retired_demo.status_code == 401
        again = _login("regulator", operator_password)
        assert again.status_code == 200, again.text
    finally:
        portal.USERS["regulator"] = original
        portal._FALLBACK_USERS["regulator"] = fallback_original
        portal._REGULATOR_LEGACY_RETIRED.discard("regulator")


def test_regulator_credential_change_accepts_the_operator_password(monkeypatch):
    """The configured password retires both secrets from the regulation view."""
    import web_portal.server as portal

    operator_password = "operator-regulator-password"
    monkeypatch.setenv("PHINS_REGULATOR_PASSWORD", operator_password)
    monkeypatch.setattr(portal, "ALLOW_LEGACY_DEMO_PASSWORDS", False)
    was_retired = "regulator" in portal._REGULATOR_LEGACY_RETIRED
    portal._REGULATOR_LEGACY_RETIRED.discard("regulator")
    try:
        stale = portal.hash_password("unusable-random-secret")
        record = {"hash": stale["hash"], "salt": stale["salt"], "role": "regulator"}

        assert portal._regulator_password_matches("regulator", operator_password, record)
        assert not portal._regulator_password_matches("regulator", "regulator123", record)
    finally:
        if was_retired:
            portal._REGULATOR_LEGACY_RETIRED.add("regulator")
        else:
            portal._REGULATOR_LEGACY_RETIRED.discard("regulator")
