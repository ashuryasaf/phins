"""Referral acquisition rewards: one fee, three adjustable layers, destination choice.

The fee is snapshotted in cents. Upper layers take their dollars from that fee
and the rest stays with the direct affiliate. Agent commission stays on the
AGI rail and is not paid from this book.
"""
import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal
from services import referral_reward_service as rewards
from services.referral_reward_service import RewardError


BASE = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


def _post(path, payload, token=None):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(BASE + path, data=data, headers=headers)
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except HTTPError as exc:
        return json.loads(exc.read().decode("utf-8")), exc.code


def _get(path, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(BASE + path, headers=headers)
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except HTTPError as exc:
        return json.loads(exc.read().decode("utf-8")), exc.code


def _login(username, password):
    body, status = _post("/api/login", {"username": username, "password": password})
    assert status == 200, body
    return body["token"], body.get("role")


def _register(name, email, code="TESTCODE2026"):
    body, status = _post("/api/register", {
        "name": name,
        "email": email,
        "password": "secure123456",
        "invitation_code": code,
    })
    assert status == 201, body
    return body["customer_id"]


def _customer(customer_id, referred_by=None, name="Member"):
    rec = {
        "id": customer_id,
        "name": name,
        "email": f"{customer_id.lower()}@example.com",
        "role": "customer",
    }
    if referred_by:
        rec["referred_by"] = referred_by
    portal.CUSTOMERS[customer_id] = rec
    return rec


def _pay(customer_id, bill_id):
    portal.BILLING[bill_id] = {
        "id": bill_id,
        "customer_id": customer_id,
        "status": "paid",
        "amount": 120.0,
        "amount_paid": 120.0,
    }


@pytest.fixture(autouse=True)
def _clean_book():
    sheet = portal.PHINS_BALANCE_SHEET
    snap = {
        "operating_reserve": sheet.get("operating_reserve"),
        "total_expenses": sheet.get("total_expenses"),
        "total_revenue": sheet.get("total_revenue"),
        "expense": dict(sheet.get("expense_breakdown") or {}),
        "revenue": dict(sheet.get("revenue_breakdown") or {}),
        "tx": len(sheet.get("transactions") or []),
        "audit": len(sheet.get("audit_log") or []),
    }
    rewards.reset_referral_rewards()
    yield
    rewards.reset_referral_rewards()
    sheet["operating_reserve"] = snap["operating_reserve"]
    sheet["total_expenses"] = snap["total_expenses"]
    sheet["total_revenue"] = snap["total_revenue"]
    sheet["expense_breakdown"] = snap["expense"]
    sheet["revenue_breakdown"] = snap["revenue"]
    sheet["transactions"][:] = sheet["transactions"][:snap["tx"]]
    sheet["audit_log"][:] = sheet["audit_log"][:snap["audit"]]


def test_default_fee_splits_evenly_across_three_layers():
    parts = rewards.allocate_cents(65000, [6000, 2500, 1500])
    assert parts == [39000, 16250, 9750]
    assert sum(parts) == 65000
    remainder = rewards.allocate_cents(100, [3333, 3333, 3334])
    assert remainder == [33, 33, 34]
    assert sum(remainder) == 100


def _cac_settlement_amounts(referee):
    amounts = []
    for tx in portal.PHINS_BALANCE_SHEET.get("transactions") or []:
        meta = tx.get("metadata") if isinstance(tx, dict) else None
        if not isinstance(meta, dict):
            continue
        if meta.get("kind") == "cac_settlement" and meta.get("referee_customer_id") == referee:
            amounts.append(tx.get("amount"))
    return amounts


def test_three_layer_chain_pays_referrers_and_not_the_referee():
    _customer("C0", name="Root")
    _customer("C1", "C0", "One")
    _customer("C2", "C1", "Two")
    _customer("C3", "C2", "Three")
    _pay("C3", "BILL-C3")
    created = rewards.on_customer_paying("C3")
    by_layer = {item["layer"]: item for item in created}
    assert by_layer[1]["beneficiary_customer_id"] == "C2"
    assert by_layer[1]["amount_cents"] == 50000
    assert by_layer[2]["beneficiary_customer_id"] == "C1"
    assert by_layer[2]["amount_cents"] == 10000
    assert by_layer[3]["beneficiary_customer_id"] == "C0"
    assert by_layer[3]["amount_cents"] == 5000
    assert all(item["beneficiary_customer_id"] != "C3" for item in created)
    assert {item["settlement_id"] for item in created} == {"CACSET-C3"}
    assert {item["status"] for item in created} == {"held"}
    settlement = rewards.SETTLEMENTS["C3"]
    assert settlement["allocated_cents"] == 65000
    assert settlement["status"] == "held"
    assert settlement["books_tx_id"]
    assert settlement["ledger_entry_id"]
    booked = portal.PHINS_BALANCE_SHEET["expense_breakdown"]["customer_acquisition"]
    assert booked == pytest.approx(650.0)
    assert _cac_settlement_amounts("C3") == [pytest.approx(650.0)]
    again = rewards.on_customer_paying("C3")
    assert again == []
    assert portal.PHINS_BALANCE_SHEET["expense_breakdown"]["customer_acquisition"] == pytest.approx(650.0)
    assert _cac_settlement_amounts("C3") == [pytest.approx(650.0)]


def test_short_chain_pays_the_rest_to_the_direct_affiliate():
    _customer("C1", name="Direct")
    _customer("C2", "C1", "New")
    _pay("C2", "BILL-C2")
    created = rewards.on_customer_paying("C2")
    assert len(created) == 1
    assert created[0]["amount_cents"] == 65000
    assert portal.PHINS_BALANCE_SHEET["expense_breakdown"]["customer_acquisition"] == pytest.approx(650.0)
    summary = rewards.book_summary()
    assert summary["totals"]["retained"] == pytest.approx(0.0)
    assert summary["integrity"]["ok"] is True
    assert summary["affiliated_plan"]["preview"]["alone"] == [650.0, 0.0, 0.0]
    assert summary["affiliated_plan"]["preview"]["three_layers"] == [500.0, 100.0, 50.0]


def test_cycle_and_self_referral_do_not_pay_the_referee():
    _customer("CX", "CY", "Cycle")
    _customer("CY", "CX", "Other")
    _pay("CX", "BILL-CX")
    created = rewards.on_customer_paying("CX")
    assert [item["beneficiary_customer_id"] for item in created] == ["CY"]
    _customer("SELF", "SELF", "Self")
    _pay("SELF", "BILL-SELF")
    assert rewards.on_customer_paying("SELF") == []


def test_join_without_payment_creates_a_link_and_no_reward():
    _customer("REF", name="Referrer")
    _customer("NEW", "REF", "New")
    joined = rewards.on_customer_joined(
        referee_customer_id="NEW", referrer_customer_id="REF",
        invitation_code="REF-NEW", referee_name="New",
    )
    assert joined["recorded"] is True
    assert rewards.on_customer_paying("NEW") == []
    assert "RWRD-NEW-L1" not in rewards.REWARDS


def test_accept_posts_once_and_a_second_accept_is_rejected():
    rewards.update_config({"hold_months": 0})
    _customer("C1", name="Direct")
    _customer("C2", "C1", "New")
    _pay("C2", "BILL-ACC")
    rewards.on_customer_paying("C2")
    accepted = rewards.accept_reward("RWRD-C2-L1", "C1")
    assert accepted["status"] == "dispatched"
    wallet = portal.HEALTH_WALLETS["C1"]
    health_tx = next(tx for tx in wallet["transactions"] if tx["id"] == "REFREWARD-RWRD-C2-L1-health")
    assert health_tx["amount"] == pytest.approx(325.0)
    assert "savings" in rewards.REWARDS["RWRD-C2-L1"]["posted"]
    with pytest.raises(RewardError) as exc:
        rewards.accept_reward("RWRD-C2-L1", "C1", {"health_wallet": 50, "savings": 50, "premium": 0, "cash": 0})
    assert exc.value.status == 409


def test_layer_three_rejects_cash():
    rewards.update_config({"hold_months": 0})
    _customer("C0")
    _customer("C1", "C0")
    _customer("C2", "C1")
    _customer("C3", "C2")
    _pay("C3", "BILL-CASH")
    rewards.on_customer_paying("C3")
    with pytest.raises(RewardError) as exc:
        rewards.accept_reward("RWRD-C3-L3", "C0", {
            "premium": 0, "health_wallet": 0, "savings": 0, "cash": 100,
        })
    assert exc.value.code in {"cash_cap", "destination_not_allowed"}
    assert rewards.REWARDS["RWRD-C3-L3"]["status"] == "earned"


def test_bad_shares_leave_the_program_unchanged_and_history_is_snapshotted():
    _customer("C1")
    _customer("C2", "C1")
    _pay("C2", "BILL-SNAP")
    rewards.on_customer_paying("C2")
    original = rewards.REWARDS["RWRD-C2-L1"]["amount_cents"]
    before = rewards.get_config()["fee_cents"]
    with pytest.raises(RewardError):
        rewards.update_config({
            "layers": [
                {"layer": 1, "amount": 650},
                {"layer": 2, "amount": 400},
                {"layer": 3, "amount": 400},
            ]
        })
    assert rewards.get_config()["fee_cents"] == before
    rewards.update_config({
        "fee": 100,
        "layers": [
            {"layer": 1, "amount": 100},
            {"layer": 2, "amount": 15},
            {"layer": 3, "amount": 5},
        ],
    })
    assert rewards.REWARDS["RWRD-C2-L1"]["amount_cents"] == original
    assert rewards.get_config()["fee"] == pytest.approx(100.0)


def test_tampered_checksum_is_not_paid_and_a_bad_file_is_not_loaded():
    rewards.update_config({"hold_months": 0})
    _customer("C1")
    _customer("C2", "C1")
    _pay("C2", "BILL-TAMPER")
    rewards.on_customer_paying("C2")
    rewards.REWARDS["RWRD-C2-L1"]["checksum"] = "0" * 64
    with pytest.raises(RewardError) as exc:
        rewards.accept_reward("RWRD-C2-L1", "C1")
    assert exc.value.status == 409
    assert rewards.verify_integrity()["ok"] is False
    rewards.REWARDS["RWRD-C2-L1"]["checksum"] = rewards._reward_checksum(rewards.REWARDS["RWRD-C2-L1"])
    rewards._save_file()
    path = rewards._state_path()
    blob = json.loads(path.read_text(encoding="utf-8"))
    blob["checksum"] = "dead"
    path.write_text(json.dumps(blob), encoding="utf-8")
    rewards.REWARDS.clear()
    rewards.LINKS.clear()
    rewards._loaded = False
    rewards.get_config()
    assert "state_checksum_mismatch" in rewards.FLAGS
    assert rewards.REWARDS == {}


def test_disabled_program_records_the_join_and_does_not_earn():
    rewards.update_config({"enabled": False})
    _customer("REF")
    _customer("NEW", "REF")
    rewards.on_customer_joined(
        referee_customer_id="NEW", referrer_customer_id="REF", invitation_code="REF-X",
    )
    _pay("NEW", "BILL-OFF")
    assert rewards.on_customer_paying("NEW") == []
    assert "NEW" in rewards.LINKS


def test_professional_agent_opens_a_switchable_portal_and_raises_the_cap():
    email = "pro-agent-rewards@example.com"
    customer_id = _register("Pro Agent", email)
    token, _role = _login(email, "secure123456")
    filed, status = _post("/api/customer/professional-requests", {"role": "agent"}, token=token)
    assert status == 200, filed
    assert filed["status"] == "pending"
    admin, _ = _login("admin", "admin123")
    reviewed, status = _post("/api/admin/professional-requests/review", {
        "id": filed["id"], "decision": "approve",
    }, token=admin)
    assert status == 200, reviewed
    assert reviewed["agent_id"]
    assert rewards.invitation_cap_for(customer_id) == 100
    switched, status = _post("/api/customer/role-switch", {"role": "agent"}, token=token)
    assert status == 200, switched
    me, status = _get("/api/agent/me", token=switched["token"])
    assert status == 200, me
    assert me["agent"]["id"] == reviewed["agent_id"]


def test_supplier_approval_stamps_the_customer_and_hides_the_password(monkeypatch):
    monkeypatch.setattr(rewards.secrets, "token_urlsafe", lambda _n: "known-secret-password-value")
    email = "pro-supplier-rewards@example.com"
    customer_id = _register("Pro Clinic", email)
    token, _role = _login(email, "secure123456")
    filed, status = _post("/api/customer/professional-requests", {
        "role": "supplier",
        "supplier_type": "clinic",
        "company_name": "North Clinic",
    }, token=token)
    assert status == 200, filed
    admin, _ = _login("admin", "admin123")
    reviewed, status = _post("/api/admin/professional-requests/review", {
        "id": filed["id"], "decision": "approve",
    }, token=admin)
    assert status == 200, reviewed
    assert "known-secret-password-value" not in json.dumps(reviewed)
    supplier = portal.supply_chain_service.suppliers[reviewed["supplier_id"]]
    assert supplier["status"] == "approved"
    assert supplier["portal_active"] is True
    assert supplier["customer_id"] == customer_id
    assert "known-secret-password-value" not in json.dumps(supplier)
    assert portal.CUSTOMERS[customer_id]["supplier_id"] == reviewed["supplier_id"]


def test_customer_cannot_read_the_book_or_accept_someone_elses_reward():
    _customer("C1")
    _customer("C2", "C1")
    _pay("C2", "BILL-SCOPE")
    rewards.on_customer_paying("C2")
    email = "scope-rewards@example.com"
    _register("Scope", email)
    token, _role = _login(email, "secure123456")
    book, status = _get("/api/admin/referral-rewards", token=token)
    assert status == 403, book
    stolen, status = _post("/api/customer/referral-rewards/accept", {
        "reward_id": "RWRD-C2-L1",
    }, token=token)
    assert status == 404, stolen
    admin, _ = _login("admin", "admin123")
    book, status = _get("/api/admin/referral-rewards", token=admin)
    assert status == 200, book
    assert book["integrity"]["ok"] is True
    accountant, _ = _login("accountant", "acct123")
    denied, status = _post("/api/admin/referral-rewards/config", {"fee": 10}, token=accountant)
    assert status == 403, denied


def test_invitation_cap_stays_at_ten_until_the_agent_role_is_approved():
    email = "cap-rewards@example.com"
    customer_id = _register("Cap Customer", email)
    token, _role = _login(email, "secure123456")
    for _ in range(10):
        body, status = _post("/api/customer/invitations/generate", {}, token=token)
        assert status == 201, body
    blocked, status = _post("/api/customer/invitations/generate", {}, token=token)
    assert status == 400, blocked
    filed, status = _post("/api/customer/professional-requests", {"role": "agent"}, token=token)
    assert status == 200, filed
    admin, _ = _login("admin", "admin123")
    reviewed, status = _post("/api/admin/professional-requests/review", {
        "id": filed["id"], "decision": "approve",
    }, token=admin)
    assert status == 200, reviewed
    opened, status = _post("/api/customer/invitations/generate", {}, token=token)
    assert status == 201, opened
    listing, status = _get("/api/customer/invitations", token=token)
    assert status == 200, listing
    assert listing["max_allowed"] == 100
    assert rewards.invitation_cap_for(customer_id) == 100


def test_registration_with_a_customer_code_earns_on_the_first_payment():
    referrer_email = "referrer-rewards@example.com"
    referrer = _register("Referrer", referrer_email)
    token, _role = _login(referrer_email, "secure123456")
    issued, status = _post("/api/customer/invitations/generate", {}, token=token)
    assert status == 201, issued
    code = issued["invitation"]["code"]
    assert f"/join.html?code={code}" in issued["registration_link"]
    referee = _register("Referee", "referee-rewards@example.com", code=code)
    assert portal.CUSTOMERS[referee]["referred_by"] == referrer
    assert referee in rewards.LINKS
    _pay(referee, "BILL-HTTP-REF")
    portal.notify_referral_reward_for_paid_customer(referee)
    reward = rewards.REWARDS[f"RWRD-{referee}-L1"]
    assert reward["beneficiary_customer_id"] == referrer
    assert reward["amount_cents"] == 65000
    sheet, status = _get("/api/admin/balance-sheet", token=_login("admin", "admin123")[0])
    assert status == 200, sheet
    assert sheet["balance_sheet"]["expense_breakdown"]["customer_acquisition"] == pytest.approx(650.0)
    assert sheet["referral_rewards"]["earned"] == pytest.approx(650.0)


def test_repository_round_trip():
    from database import init_database
    from database.manager import DatabaseManager

    init_database()
    with DatabaseManager() as db:
        db.referral_rewards.upsert_link({
            "id": "REFL-DB1",
            "referee_customer_id": "CUST-DB-REF",
            "referrer_customer_id": "CUST-DB-FROM",
            "invitation_code": "REF-DB",
            "referee_name": "Dee",
            "joined_at": "2026-10-19T00:00:00Z",
            "paying_at": None,
            "notified_join": True,
        })
        db.referral_rewards.upsert_reward({
            "id": "RWRD-DB1-L1",
            "referee_customer_id": "CUST-DB-REF",
            "beneficiary_customer_id": "CUST-DB-FROM",
            "layer": 1,
            "status": "earned",
            "fee_cents": 65000,
            "share_bps": 6000,
            "amount_cents": 39000,
            "currency": "USD",
            "program_shares": [6000, 2500, 1500],
            "policy": {"allowed": ["premium"]},
            "allocation": None,
            "posted": {},
            "checksum": "abc",
            "earned_at": "2026-10-19T00:00:00Z",
        })
        links = {row["referee_customer_id"]: row for row in db.referral_rewards.list_links()}
        stored = {row["id"]: row for row in db.referral_rewards.list_rewards()}
        db.referral_rewards.upsert_settlement({
            "id": "CACSET-CUST-DB-REF",
            "referee_customer_id": "CUST-DB-REF",
            "fee_cents": 65000,
            "allocated_cents": 39000,
            "retained_cents": 26000,
            "status": "held",
            "hold_months": 3,
            "paying_at": "2026-10-19T00:00:00Z",
            "release_at": "2027-01-19T00:00:00Z",
            "books_tx_id": "BS-1",
            "ledger_entry_id": "CACSET-CUST-DB-REF",
            "checksum": "settlement-checksum",
        })
        settlements = {row["referee_customer_id"]: row for row in db.referral_rewards.list_settlements()}
    assert links["CUST-DB-REF"]["notified_join"] is True
    assert stored["RWRD-DB1-L1"]["amount_cents"] == 39000
    assert stored["RWRD-DB1-L1"]["program_shares"] == [6000, 2500, 1500]
    assert settlements["CUST-DB-REF"]["allocated_cents"] == 39000
    assert settlements["CUST-DB-REF"]["hold_months"] == 3
    assert settlements["CUST-DB-REF"]["release_at"] == "2027-01-19T00:00:00Z"


def test_hold_months_clamps_to_the_end_of_the_month():
    assert rewards._add_months("2026-01-31T00:00:00Z", 1) == "2026-02-28T00:00:00Z"
    assert rewards._add_months("2024-01-31T00:00:00Z", 1) == "2024-02-29T00:00:00Z"
    assert rewards._add_months("2026-03-15T12:00:00Z", 0) == "2026-03-15T12:00:00Z"


def test_affiliated_cac_plan_blocks_the_fee_until_the_balance_holds(monkeypatch):
    monkeypatch.setattr(rewards, "_now", lambda: "2026-01-15T00:00:00Z")
    _customer("C1", name="Direct")
    _customer("C2", "C1", "New")
    _pay("C2", "BILL-PLAN")
    rewards.on_customer_paying("C2")
    plan = rewards.affiliated_cac_plan()
    assert plan["hold_months"] == 3
    assert plan["paying"] == 1
    assert plan["affiliated_customers"] == 1
    assert plan["allocated"] == pytest.approx(650.0)
    assert plan["blocked"] == pytest.approx(650.0)
    assert plan["projected_release"] == pytest.approx(650.0)
    assert plan["releasable"] == pytest.approx(0.0)
    assert plan["reversed"] == pytest.approx(0.0)
    assert plan["per_paying_customer"] == pytest.approx(650.0)
    with pytest.raises(RewardError) as exc:
        rewards.accept_reward("RWRD-C2-L1", "C1")
    assert exc.value.code == "held"
    assert exc.value.to_dict()["release_at"] == "2026-04-15T00:00:00Z"
    monkeypatch.setattr(rewards, "_now", lambda: "2026-04-15T00:00:00Z")
    accepted = rewards.accept_reward("RWRD-C2-L1", "C1")
    assert accepted["status"] == "dispatched"
    assert rewards.SETTLEMENTS["C2"]["status"] == "settled"
    assert rewards.SETTLEMENTS["C2"]["released_ledger_id"]
    assert _cac_settlement_amounts("C2") == [650.0]
    released = rewards.affiliated_cac_plan()
    assert released["blocked"] == pytest.approx(0.0)
    assert released["settled"] == pytest.approx(650.0)


def test_lapsed_balance_reverses_the_single_settlement_once():
    before = float(portal.PHINS_BALANCE_SHEET["expense_breakdown"].get("customer_acquisition") or 0)
    _customer("C1", name="Direct")
    _customer("C2", "C1", "New")
    _pay("C2", "BILL-LAPSE")
    rewards.on_customer_paying("C2")
    assert portal.PHINS_BALANCE_SHEET["expense_breakdown"]["customer_acquisition"] == pytest.approx(before + 650.0)
    portal.BILLING["BILL-LAPSE"]["status"] = "open"
    rewards.on_customer_paying("C2")
    assert portal.PHINS_BALANCE_SHEET["expense_breakdown"]["customer_acquisition"] == pytest.approx(before)
    assert rewards.SETTLEMENTS["C2"]["status"] == "reversed"
    assert rewards.REWARDS["RWRD-C2-L1"]["status"] == "forfeited"
    with pytest.raises(RewardError) as exc:
        rewards.accept_reward("RWRD-C2-L1", "C1")
    assert exc.value.code == "forfeited"
    portal.BILLING["BILL-LAPSE"]["status"] = "paid"
    assert rewards.on_customer_paying("C2") == []
    assert rewards.SETTLEMENTS["C2"]["status"] == "reversed"
    assert portal.PHINS_BALANCE_SHEET["expense_breakdown"]["customer_acquisition"] == pytest.approx(before)
    assert rewards.verify_integrity()["ok"] is True
    plan = rewards.affiliated_cac_plan()
    assert plan["reversed"] == pytest.approx(650.0)
    assert plan["allocated"] == pytest.approx(0.0)


def test_settlement_survives_a_reload_and_a_bad_checksum_is_not_paid():
    _customer("C1", name="Direct")
    _customer("C2", "C1", "New")
    _pay("C2", "BILL-DURABLE")
    rewards.on_customer_paying("C2")
    release_at = rewards.SETTLEMENTS["C2"]["release_at"]
    rewards.REWARDS.clear()
    rewards.SETTLEMENTS.clear()
    rewards.LINKS.clear()
    rewards.QUARANTINE.clear()
    rewards.FLAGS.clear()
    rewards._loaded = False
    rewards._ensure_loaded()
    assert rewards.SETTLEMENTS["C2"]["status"] == "held"
    assert rewards.SETTLEMENTS["C2"]["release_at"] == release_at
    assert rewards.REWARDS["RWRD-C2-L1"]["status"] == "held"
    assert rewards.REWARDS["RWRD-C2-L1"]["settlement_id"] == "CACSET-C2"
    rewards.SETTLEMENTS["C2"]["checksum"] = "0" * 64
    with pytest.raises(RewardError) as exc:
        rewards.accept_reward("RWRD-C2-L1", "C1")
    assert exc.value.code == "checksum"
    assert rewards.verify_integrity()["ok"] is False


def test_actuary_sets_the_hold_and_a_customer_cannot():
    token, role = _login("actuary", "actuary123")
    assert role == "actuary"
    saved, status = _post("/api/admin/referral-rewards/hold", {"hold_months": 6}, token=token)
    assert status == 200, saved
    assert saved["hold_months"] == 6
    assert saved["fee_cents"] == 65000
    denied, status = _post("/api/admin/referral-rewards/config", {"fee": 10}, token=token)
    assert status == 403, denied
    book, status = _get("/api/admin/referral-rewards", token=token)
    assert status == 200, book
    assert book["affiliated_plan"]["hold_months"] == 6
    assert "allocated" in book["affiliated_plan"]
    accountant, _role = _login("accountant", "acct123")
    denied, status = _post("/api/admin/referral-rewards/hold", {"hold_months": 1}, token=accountant)
    assert status == 403, denied
    email = "hold-customer@example.com"
    _register("Hold Customer", email)
    customer, _role = _login(email, "secure123456")
    denied, status = _post("/api/admin/referral-rewards/hold", {"hold_months": 1}, token=customer)
    assert status == 403, denied
    assert rewards.get_config()["hold_months"] == 6


def test_affiliated_join_link_is_the_admin_page_and_keeps_the_chain():
    assert rewards.affiliated_join_link("bad code") == ""
    assert rewards.affiliated_join_link("../join") == ""
    sender_email = "affil-sender@example.com"
    sender = _register("Affil Sender", sender_email)
    token, _role = _login(sender_email, "secure123456")
    issued, status = _post("/api/customer/invitations/generate", {}, token=token)
    assert status == 201, issued
    code = issued["invitation"]["code"]
    link = issued["join_link"]
    assert link == issued["registration_link"]
    assert link.endswith("/join.html?code=" + code)
    assert list(parse_qs(urlparse(link).query)) == ["code"]
    assert "join_link" not in portal.CUSTOMER_INVITATIONS[code]
    assert issued["affiliation"]["invite_places_you_at_layer"] == 1
    assert issued["affiliation"]["layers_above"] == []

    middle_email = "affil-middle@example.com"
    middle = _register("Affil Middle", middle_email, code=code)
    assert portal.CUSTOMERS[middle]["referred_by"] == sender
    middle_token, _role = _login(middle_email, "secure123456")
    child_issue, status = _post("/api/customer/invitations/generate", {}, token=middle_token)
    assert status == 201, child_issue
    child_code = child_issue["invitation"]["code"]
    child_link = child_issue["join_link"]
    assert child_link.endswith("/join.html?code=" + child_code)
    assert sender not in child_link
    above = child_issue["affiliation"]["layers_above"]
    assert above[0]["layer"] == 1
    assert above[0]["customer_id"] == sender
    listing, status = _get("/api/customer/invitations", token=middle_token)
    assert status == 200, listing
    assert listing["codes"][0]["join_link"] == child_link
    assert listing["affiliation"]["layers_above"][0]["customer_id"] == sender
    book = rewards.customer_dashboard(middle)
    assert book["affiliation"]["layers_above"][0]["customer_id"] == sender

    grandchild = _register("Affil Grand", "affil-grand@example.com", code=child_code)
    assert portal.CUSTOMERS[grandchild]["referred_by"] == middle
    _pay(grandchild, "BILL-AFFIL-CHAIN")
    portal.notify_referral_reward_for_paid_customer(grandchild)
    assert rewards.REWARDS[f"RWRD-{grandchild}-L1"]["beneficiary_customer_id"] == middle
    assert rewards.REWARDS[f"RWRD-{grandchild}-L2"]["beneficiary_customer_id"] == sender
    assert f"RWRD-{grandchild}-L3" not in rewards.REWARDS

    static = Path(__file__).resolve().parents[1] / "web_portal" / "static"
    dashboard = (static / "dashboard.html").read_text(encoding="utf-8")
    agent = (static / "agent-portal.html").read_text(encoding="utf-8")
    supplier = (static / "supplier-portal.html").read_text(encoding="utf-8")
    assert "Copy join link" in dashboard
    assert "function absoluteJoinLink" in dashboard
    assert "window.location.origin" in dashboard
    assert 'id="affiliated-join-link"' in agent
    assert "function absoluteJoinLink" in agent
    assert 'id="affiliated-join-link"' in supplier
    assert "function absoluteJoinLink" in supplier
    assert "/join.html?code=" in dashboard
    assert rewards.REWARDS[f"RWRD-{grandchild}-L1"]["amount_cents"] == 55000
    assert rewards.REWARDS[f"RWRD-{grandchild}-L2"]["amount_cents"] == 10000


def test_legacy_share_config_becomes_a_waterfall_and_old_rewards_still_tie():
    legacy = {
        "version": 1,
        "enabled": True,
        "currency": "USD",
        "fee_cents": 65000,
        "max_layers": 3,
        "customer_invitation_cap": 10,
        "agent_invitation_cap": 100,
        "agent_default_rate_percent": 10,
        "hold_months": 3,
        "auto_dispatch": False,
        "layers": [
            {"layer": 1, "share_bps": 6000, "allowed": ["premium"], "cash_cap_bps": 0,
             "default_bps": {"premium": 10000, "health_wallet": 0, "savings": 0, "cash": 0}},
            {"layer": 2, "share_bps": 2500, "allowed": ["premium"], "cash_cap_bps": 0,
             "default_bps": {"premium": 10000, "health_wallet": 0, "savings": 0, "cash": 0}},
            {"layer": 3, "share_bps": 1500, "allowed": ["premium"], "cash_cap_bps": 0,
             "default_bps": {"premium": 10000, "health_wallet": 0, "savings": 0, "cash": 0}},
        ],
    }
    loaded = rewards._validate_config(legacy)
    assert loaded["layers"][0]["amount_cents"] == 65000
    assert loaded["layers"][1]["amount_cents"] == 16250
    assert loaded["layers"][2]["amount_cents"] == 9750
    assert rewards.waterfall_amounts(65000, [65000, 16250, 9750], [1, 2, 3]) == [39000, 16250, 9750]
    old = {
        "id": "RWRD-OLD-L1",
        "referee_customer_id": "OLD",
        "beneficiary_customer_id": "PARENT",
        "layer": 1,
        "status": "earned",
        "fee_cents": 65000,
        "share_bps": 6000,
        "amount_cents": 39000,
        "currency": "USD",
        "program_shares": [6000, 2500, 1500],
        "policy": {"allowed": ["premium"], "cash_cap_bps": 0, "default_bps": {"premium": 10000}},
        "allocation": None,
        "posted": {},
        "books_tx_id": None,
        "ledger_entry_id": None,
        "earned_at": "2026-01-01T00:00:00Z",
        "dispatched_at": None,
    }
    rewards._seal(old)
    assert rewards._reward_intact(old)
    assert "allocation_method" not in (old.get("policy") or {})


def test_premium_percent_uses_annual_premium_and_the_layer_proportions():
    rewards.update_config({
        "fee_mode": "premium_percent",
        "premium_percent": 10,
        "fee": 650,
        "layers": [
            {"layer": 1, "amount": 650},
            {"layer": 2, "amount": 100},
            {"layer": 3, "amount": 50},
        ],
    })
    _customer("C0")
    _customer("C1", "C0")
    _customer("C2", "C1")
    _customer("C3", "C2")
    _pay("C3", "BILL-PCT")
    assert rewards.on_customer_paying("C3") == []
    portal.POLICIES["POL-PCT"] = {
        "id": "POL-PCT",
        "customer_id": "C3",
        "status": "active",
        "annual_premium": 2000,
    }
    created = rewards.on_customer_paying("C3")
    expected = rewards.waterfall_amounts(20000, [65000, 10000, 5000], [1, 2, 3])
    by_layer = {item["layer"]: item["amount_cents"] for item in created}
    assert by_layer == {1: expected[0], 2: expected[1], 3: expected[2]}
    assert sum(expected) == 20000
    assert rewards.SETTLEMENTS["C3"]["fee_cents"] == 20000
    assert rewards.SETTLEMENTS["C3"]["retained_cents"] == 0
    assert rewards.REWARDS["RWRD-C3-L1"]["policy"]["premium_cents"] == 200000
    assert rewards.verify_integrity()["ok"] is True
    rewards.update_config({"fee_mode": "fixed", "fee": 700, "layers": [
        {"layer": 1, "amount": 700},
        {"layer": 2, "amount": 100},
        {"layer": 3, "amount": 50},
    ]})
    assert rewards.REWARDS["RWRD-C3-L1"]["amount_cents"] == expected[0]


def test_affiliate_book_totals_layers_blocked_and_destination_links(monkeypatch):
    _customer("ROOT", name="Root Affiliate")
    for index in range(3):
        referee = f"D{index}"
        _customer(referee, "ROOT", f"Direct {index}")
        _pay(referee, f"BILL-{referee}")
        rewards.on_customer_paying(referee)
    _customer("MID", "ROOT", "Middle")
    for index in range(5):
        referee = f"S{index}"
        _customer(referee, "MID", f"Second {index}")
        _pay(referee, f"BILL-{referee}")
        rewards.on_customer_paying(referee)
    _customer("LOW", "MID", "Low")
    for index in range(8):
        referee = f"T{index}"
        _customer(referee, "LOW", f"Third {index}")
        _pay(referee, f"BILL-{referee}")
        rewards.on_customer_paying(referee)
    book = rewards.customer_dashboard("ROOT")["affiliation_book"]
    assert book["affiliated_customers"] == 16
    assert book["by_layer"]["1"] == {
        "customers": 3, "amount": 1950.0, "blocked": 1950.0, "available": 0.0, "dispatched": 0.0,
    }
    assert book["by_layer"]["2"]["customers"] == 5
    assert book["by_layer"]["2"]["amount"] == pytest.approx(500.0)
    assert book["by_layer"]["3"]["customers"] == 8
    assert book["by_layer"]["3"]["amount"] == pytest.approx(400.0)
    assert book["blocked"] == pytest.approx(2850.0)
    assert book["available"] == pytest.approx(0.0)
    direct = next(row for row in book["rows"] if row["referee_customer_id"] == "D0")
    assert direct["blocked_amount"] == pytest.approx(650.0)
    assert {link["href"] for link in direct["links"]} >= {
        "/dashboard.html#billing",
        "/dashboard.html#health-wallet",
        "/dashboard.html#investment-portfolio",
    }
    monkeypatch.setattr(rewards, "_now", lambda: "2099-01-01T00:00:00Z")
    rewards._refresh_all_locked()
    accepted = rewards.accept_reward("RWRD-D0-L1", "ROOT", {
        "premium": 0, "health_wallet": 0, "savings": 100, "cash": 0,
    })
    assert accepted["distribution"] == "savings"
    refreshed = rewards.customer_dashboard("ROOT")["affiliation_book"]
    sent = next(row for row in refreshed["rows"] if row["referee_customer_id"] == "D0")
    assert sent["status"] == "dispatched"
    assert sent["available_amount"] == pytest.approx(0.0)
    assert sent["dispatched_amount"] == pytest.approx(650.0)
    assert sent["links"] == [{
        "destination": "savings",
        "label": "Investments",
        "href": "/dashboard.html#investment-portfolio",
        "staff_href": "/savings-portfolio.html",
    }]
    plan = rewards.affiliated_cac_plan()
    assert plan["by_layer"]["1"]["amount"] == pytest.approx(1950.0 + 5 * 550 + 8 * 500)
    assert any(row["reward_id"] == "RWRD-D0-L1" and row["distribution"] == "savings" for row in plan["rows"])
    assert rewards.verify_integrity()["ok"] is True


def test_actuary_adjusts_the_layer_schedule_and_other_roles_cannot():
    token, role = _login("actuary", "actuary123")
    assert role == "actuary"
    saved, status = _post("/api/admin/referral-rewards/plan", {
        "fee_mode": "fixed",
        "fee": 650,
        "premium_percent": 12,
        "layers": [
            {"layer": 1, "amount": 650},
            {"layer": 2, "amount": 80},
            {"layer": 3, "amount": 40},
        ],
    }, token=token)
    assert status == 200, saved
    assert saved["fee_cents"] == 65000
    assert saved["premium_percent"] == pytest.approx(12.0)
    assert [layer["amount"] for layer in saved["layers"]] == [650.0, 80.0, 40.0]
    assert saved["preview"]["three_layers"] == [530.0, 80.0, 40.0]
    denied, status = _post("/api/admin/referral-rewards/config", {"fee": 10}, token=token)
    assert status == 403, denied
    accountant, _role = _login("accountant", "acct123")
    denied, status = _post("/api/admin/referral-rewards/plan", {"fee": 10}, token=accountant)
    assert status == 403, denied
    email = "plan-customer@example.com"
    _register("Plan Customer", email)
    customer, _role = _login(email, "secure123456")
    denied, status = _post("/api/admin/referral-rewards/plan", {"fee": 10}, token=customer)
    assert status == 403, denied
    book, status = _get("/api/admin/referral-rewards", token=token)
    assert status == 200, book
    assert book["affiliated_plan"]["schedule"][1]["amount"] == pytest.approx(80.0)
    assert rewards.get_config()["layers"][2]["amount"] == pytest.approx(40.0)

    static = Path(__file__).resolve().parents[1] / "web_portal" / "static"
    actuary = (static / "actuary-dashboard.html").read_text(encoding="utf-8")
    admin = (static / "admin.html").read_text(encoding="utf-8")
    dashboard = (static / "dashboard.html").read_text(encoding="utf-8")
    agent = (static / "agent-portal.html").read_text(encoding="utf-8")
    supplier = (static / "supplier-portal.html").read_text(encoding="utf-8")
    assert 'id="cac-plan-table"' in actuary
    assert 'id="cac-plan-amount-2"' in actuary
    assert "/api/admin/referral-rewards/plan" in actuary
    assert 'id="cac-amount-1"' in admin
    assert 'id="affiliation-book-table"' in dashboard
    assert 'id="affiliation-book-table"' in agent
    assert 'id="affiliation-book-table"' in supplier
    assert "/savings-portfolio.html" in dashboard
    assert "/billing.html" in dashboard
