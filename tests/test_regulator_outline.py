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


def test_basic_premiums_follow_the_active_kernel_version():
    store = _store()
    first = build_regulator_outline(actuarial_store=store)
    rows = first["pricing"]["basic_premiums"]["rows"]
    assert [row["age"] for row in rows] == [30, 40, 50, 60]
    assert {row["tables_version"] for row in rows} == {store.current_version}
    assert {row["config_version"] for row in rows} == {store.config.config_version}
    assert all(row["annual_premium"] > 0 for row in rows)
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
