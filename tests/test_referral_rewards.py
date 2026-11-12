"""Referral acquisition rewards: one fee, three adjustable layers, destination choice.

The fee is snapshotted in cents. Upper layers take their dollars from that fee
and the rest stays with the direct affiliate. Agent commission stays on the
AGI rail and is not paid from this book.
"""
import base64
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import web_portal.server as portal
from services import referral_reward_service as rewards
from services.referral_reward_service import RewardError


BASE = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


def _post(path, payload, token=None, headers=None):
    data = json.dumps(payload).encode("utf-8")
    merged = {"Content-Type": "application/json"}
    if headers:
        merged.update(headers)
    if token:
        merged["Authorization"] = f"Bearer {token}"
    req = Request(BASE + path, data=data, headers=merged)
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")), resp.status
    except HTTPError as exc:
        return json.loads(exc.read().decode("utf-8")), exc.code


def _open(path, payload=None, token=None, cookie=None, method=None):
    headers = {}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if cookie:
        headers["Cookie"] = cookie
    req = Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            cookies = list(resp.headers.get_all("Set-Cookie") or [])
            return json.loads(raw) if raw else {}, resp.status, cookies
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        cookies = list(exc.headers.get_all("Set-Cookie") or [])
        return json.loads(raw) if raw else {}, exc.code, cookies


def _get(path, token=None, cookie=None):
    body, status, _cookies = _open(path, token=token, cookie=cookie, method="GET")
    return body, status


def _cookie_value(headers, name):
    prefix = name + "="
    for header in headers:
        part = header.split(";", 1)[0].strip()
        if part.startswith(prefix):
            return part[len(prefix):]
    return ""


def _inquiry_set_cookie(headers):
    """Return name, secret, and the full Set-Cookie header for one inquiry."""
    for header in headers:
        part = header.split(";", 1)[0].strip()
        name, _, value = part.partition("=")
        if name.startswith("phins_inquiry_"):
            return name, value, header
    return "", "", ""


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


def _finish_inquiry(filed, *, name="Applicant", company=None):
    token = filed["inquiry_path"].split("t=", 1)[1]
    prefill, status = _get("/api/professional-inquiry?t=" + token)
    assert status == 200, prefill
    assert "national_id_hash" not in json.dumps(prefill)
    assert "id_number" not in json.dumps(prefill)
    assert prefill["known"]["email"]
    body = {
        "token": token,
        "personal": {
            "name": name,
            "phone": "555-0100",
            "address": "1 Herzl",
            "city": "Tel Aviv",
            "country": "IL",
        },
        "has_company": bool(company),
    }
    if company:
        body["company"] = company
    saved, status = _post("/api/professional-inquiry", body)
    assert status == 200, saved
    assert saved["status"] == "pending"
    assert "token_sha256" not in json.dumps(saved)
    return saved


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
    assert filed["status"] == "inquiry"
    assert filed["inquiry_path"].startswith("/") or filed["inquiry_path"].startswith("http")
    assert filed["email_sent"] is True
    admin, _ = _login("admin", "admin123")
    early, status = _post("/api/admin/professional-requests/review", {
        "id": filed["id"], "decision": "approve",
    }, token=admin)
    assert status == 409, early
    assert early.get("code") == "inquiry_open"
    saved = _finish_inquiry(filed, name="Pro Agent")
    reviewed, status = _post("/api/admin/professional-requests/review", {
        "id": saved["id"], "decision": "approve",
    }, token=admin)
    assert status == 200, reviewed
    assert reviewed["agent_id"]
    assert reviewed["supplier_id"]
    supplier = portal.supply_chain_service.suppliers[reviewed["supplier_id"]]
    assert supplier["customer_id"] == customer_id
    assert "agent" in supplier["roles"] and "supplier" in supplier["roles"]
    assert supplier["agent_id"] == reviewed["agent_id"]
    assert rewards.invitation_cap_for(customer_id) == 100
    switched, status = _post("/api/customer/role-switch", {"role": "agent"}, token=token)
    assert status == 200, switched
    me, status = _get("/api/agent/me", token=switched["token"])
    assert status == 200, me
    assert me["agent"]["id"] == reviewed["agent_id"]
    desk, status = _post("/api/customer/role-switch", {"role": "supplier"}, token=token)
    assert status == 200, desk
    assert desk["supplier_id"] == reviewed["supplier_id"]


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
    assert filed["status"] == "inquiry"
    saved = _finish_inquiry(filed, name="Pro Clinic", company={
        "company_name": "North Clinic",
        "supplier_type": "clinic",
        "registration_number": "REG-1",
        "city": "Haifa",
        "country": "IL",
    })
    admin, _ = _login("admin", "admin123")
    reviewed, status = _post("/api/admin/professional-requests/review", {
        "id": saved["id"], "decision": "approve",
    }, token=admin)
    assert status == 200, reviewed
    assert "known-secret-password-value" not in json.dumps(reviewed)
    supplier = portal.supply_chain_service.suppliers[reviewed["supplier_id"]]
    assert supplier["status"] == "approved"
    assert supplier["portal_active"] is True
    assert supplier["customer_id"] == customer_id
    assert "known-secret-password-value" not in json.dumps(supplier)
    assert portal.CUSTOMERS[customer_id]["supplier_id"] == reviewed["supplier_id"]


def test_agent_and_supplier_share_one_record_and_keep_a_conflicting_name():
    email = "one-supplier-rewards@example.com"
    customer_id = _register("One Person", email)
    token, _role = _login(email, "secure123456")
    supplier_filed, status = _post("/api/customer/professional-requests", {"role": "supplier"}, token=token)
    assert status == 200, supplier_filed
    _finish_inquiry(supplier_filed, name="One Person", company={
        "company_name": "North Clinic",
        "supplier_type": "clinic",
    })
    admin, _ = _login("admin", "admin123")
    opened, status = _post("/api/admin/professional-requests/review", {
        "id": supplier_filed["id"], "decision": "approve",
    }, token=admin)
    assert status == 200, opened
    agent_filed, status = _post("/api/customer/professional-requests", {"role": "agent"}, token=token)
    assert status == 200, agent_filed
    _finish_inquiry(agent_filed, name="One Person", company={
        "company_name": "Other Clinic",
        "supplier_type": "pharmacy",
    })
    reviewed, status = _post("/api/admin/professional-requests/review", {
        "id": agent_filed["id"], "decision": "approve",
    }, token=admin)
    assert status == 200, reviewed
    assert reviewed["supplier_id"] == opened["supplier_id"]
    assert len([s for s in portal.supply_chain_service.suppliers.values()
                if s.get("customer_id") == customer_id]) == 1
    supplier = portal.supply_chain_service.suppliers[opened["supplier_id"]]
    assert supplier["company_name"] == "North Clinic"
    assert supplier["pipeline_detail_conflict"] is True
    assert supplier["agent_id"] == reviewed["agent_id"]
    again, status = _post("/api/professional-inquiry", {"token": "inq_" + "ab" * 16})
    assert status == 404, again


def test_pipeline_report_reads_existing_fees_and_seals_without_a_second_posting():
    email = "pipeline-rewards@example.com"
    customer_id = _register("Pipeline", email)
    token, _role = _login(email, "secure123456")
    filed, status = _post("/api/customer/professional-requests", {"role": "supplier"}, token=token)
    _finish_inquiry(filed, name="Pipeline", company={
        "company_name": "Pipeline Clinic",
        "supplier_type": "clinic",
    })
    admin, _ = _login("admin", "admin123")
    reviewed, status = _post("/api/admin/professional-requests/review", {
        "id": filed["id"], "decision": "approve",
    }, token=admin)
    assert status == 200, reviewed
    portal.SUPPLIER_ORDERS["ORD-PIPE"] = {
        "id": "ORD-PIPE",
        "supplier_id": reviewed["supplier_id"],
        "customer_id": "CUST-BUYER",
        "platform_fee": 11.0,
        "commission": 11.0,
        "supplier_payout": 89.0,
        "total_amount": 100.0,
        "status": "completed",
        "payment_method": "health_wallet",
    }
    _customer("BUYER", customer_id, "Buyer")
    _pay("BUYER", "BILL-PIPE")
    rewards.on_customer_paying("BUYER")
    before = float(portal.PHINS_BALANCE_SHEET["expense_breakdown"].get("customer_acquisition") or 0)
    report, status = _get("/api/admin/supplier-agent-pipeline?audience=supplier", token=admin)
    assert status == 200, report
    row = next(item for item in report["rows"] if item["supplier_id"] == reviewed["supplier_id"])
    assert row["sales_fees"] == pytest.approx(11.0)
    assert row["acquisition_rewards"] == pytest.approx(650.0)
    assert row["agent_commissions"] == pytest.approx(0.0)
    tax, status = _get("/api/admin/supplier-agent-pipeline?audience=tax", token=admin)
    assert status == 200, tax
    dumped = json.dumps(tax)
    assert email not in dumped
    assert "555-0100" not in dumped
    regulator, status = _get("/api/admin/supplier-agent-pipeline?audience=regulator", token=admin)
    assert status == 200, regulator
    assert regulator["personal_data"] is False
    assert email not in json.dumps(regulator)
    sealed, status = _post("/api/admin/supplier-agent-pipeline/seal", {}, token=admin)
    assert status == 200, sealed
    assert float(portal.PHINS_BALANCE_SHEET["expense_breakdown"].get("customer_acquisition") or 0) == pytest.approx(before)
    again, status = _post("/api/admin/supplier-agent-pipeline/seal", {
        "supplier_id": reviewed["supplier_id"],
    }, token=admin)
    assert status == 200, again
    assert again["sealed"][0]["reused"] is True
    assert again["cash_event"] is False
    statements = [
        entry for entry in portal.supply_chain_service.ledger.values()
        if entry.get("entry_type") == "pipeline_statement"
        and entry.get("supplier_id") == reviewed["supplier_id"]
    ]
    assert len(statements) == 1
    assert statements[0]["amount"] == 0
    portal.SUPPLIER_ORDERS.pop("ORD-PIPE", None)


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
    saved = _finish_inquiry(filed, name="Cap Customer")
    admin, _ = _login("admin", "admin123")
    reviewed, status = _post("/api/admin/professional-requests/review", {
        "id": saved["id"], "decision": "approve",
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
        db.referral_rewards.upsert_request({
            "id": "PRO-CUST-DB-supplier",
            "customer_id": "CUST-DB",
            "requested_role": "supplier",
            "status": "inquiry",
            "created_at": "2026-10-19T00:00:00Z",
            "inquiry": {"has_company": True, "token_sha256": "abc", "personal": {"name": "Dee"}},
        })
        stored_request = {row["id"]: row for row in db.referral_rewards.list_requests()}
    assert links["CUST-DB-REF"]["notified_join"] is True
    assert stored["RWRD-DB1-L1"]["amount_cents"] == 39000
    assert stored["RWRD-DB1-L1"]["program_shares"] == [6000, 2500, 1500]
    assert settlements["CUST-DB-REF"]["allocated_cents"] == 39000
    assert settlements["CUST-DB-REF"]["hold_months"] == 3
    assert settlements["CUST-DB-REF"]["release_at"] == "2027-01-19T00:00:00Z"
    assert stored_request["PRO-CUST-DB-supplier"]["inquiry"]["personal"]["name"] == "Dee"
    assert stored_request["PRO-CUST-DB-supplier"]["inquiry"]["token_sha256"] == "abc"


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


def _chat(token, step, value):
    body, status = _post("/api/professional-inquiry/chat", {
        "token": token, "step": step, "value": value,
    })
    assert status == 200, body
    return body


def test_professional_chat_discloses_every_step_and_keeps_the_id_in_the_vault():
    email = "chat-supplier@example.com"
    customer_id = _register("Chat Supplier", email)
    session, _role = _login(email, "secure123456")
    filed, status = _post("/api/customer/professional-requests", {"role": "supplier"}, token=session)
    assert status == 200, filed
    parts = urlparse(filed["inquiry_path"])
    query = parse_qs(parts.query)
    assert parts.path.endswith("/professional-inquiry-chat.html")
    assert query["r"] == [filed["id"]]
    assert query["t"][0].startswith("inq_")
    assert filed["id"] not in query["t"][0]
    link = query["t"][0]
    prefill, status = _get("/api/professional-inquiry?t=" + link)
    assert status == 200, prefill
    assert prefill["agent"] == "Phin"
    assert prefill["chat"]["disclosed"] is True
    assert [step["id"] for step in prefill["process"]] == [
        "confirm_person", "identity", "company", "evidence", "review",
    ]
    assert prefill["process"][2]["optional"] is True
    assert prefill["process"][3]["optional"] is True
    assert prefill["chat"]["cursor"] == "confirm_person"
    early, status = _post("/api/professional-inquiry/chat", {
        "token": link, "step": "identity", "value": "skip",
    })
    assert status == 409, early
    assert early["code"] == "step_mismatch"
    moved = _chat(link, "confirm_person", {
        "personal": {
            "name": "Chat Supplier",
            "phone": "555-0199",
            "address": "2 Herzl",
            "city": "Haifa",
            "country": "IL",
        },
    })
    assert moved["chat"]["cursor"] == "identity"
    national_id = "123456782"
    blocked, status = _post("/api/professional-inquiry/chat", {
        "token": link, "step": "identity",
        "value": {"nationality": "IL", "national_id": national_id},
    })
    assert status == 403, blocked
    assert blocked["code"] == "otp_required"
    opened, status, set_cookies = _open("/api/professional-inquiry/session", {"token": link})
    assert status == 200, opened
    cookie_name, secret, cookie_header = _inquiry_set_cookie(set_cookies)
    assert secret.startswith("inqs_")
    assert "HttpOnly" in cookie_header
    assert secret not in json.dumps(opened)
    cookie = cookie_name + "=" + secret
    otp, status = _post("/api/professional-inquiry/otp/request", {"token": link})
    assert status == 200, otp
    assert otp.get("demo_otp_code")
    assert national_id not in json.dumps(otp)
    checked, status, _cookies = _open("/api/professional-inquiry/otp/verify", {
        "request_id": opened["request_id"],
        "verification_id": otp["verification_id"],
        "otp_code": otp["demo_otp_code"],
    }, cookie=cookie)
    assert status == 200, checked
    stolen, status = _post("/api/professional-inquiry/chat", {
        "token": link, "step": "identity",
        "value": {"nationality": "IL", "national_id": national_id},
    })
    assert status == 403, stolen
    assert stolen["code"] == "otp_required"
    assert portal.CUSTOMERS[customer_id].get("national_id_last4") in (None, "")
    recorded, status, _cookies = _open("/api/professional-inquiry/chat", {
        "request_id": opened["request_id"],
        "step": "identity",
        "value": {"nationality": "IL", "national_id": national_id},
    }, cookie=cookie)
    assert status == 200, recorded
    dumped = json.dumps(recorded)
    assert national_id not in dumped
    assert recorded["chat"]["identity"]["complete"] is True
    assert recorded["chat"]["identity"]["national_id_masked"].endswith("6782")
    again, status = _get("/api/professional-inquiry?t=" + link)
    assert national_id not in json.dumps(again)
    assert portal.CUSTOMERS[customer_id]["national_id_last4"] == "6782"
    assert "national_id" not in portal.CUSTOMERS[customer_id]
    _chat(link, "company", "no")
    payload = base64.b64encode(b"professional-evidence").decode("ascii")
    media, status = _post("/api/professional-inquiry/media", {
        "token": link,
        "kind": "document",
        "name": "licence.txt",
        "mime_type": "text/plain",
        "data_b64": payload,
    })
    assert status == 200, media
    assert media["media"]["sha256"] == hashlib.sha256(b"professional-evidence").hexdigest()
    assert "data_b64" not in json.dumps(media)
    assert national_id not in json.dumps(media)
    _chat(link, "evidence", "done")
    submitted = _chat(link, "review", "submit")
    assert submitted["status"] == "pending"
    assert submitted["chat"]["cursor"] == "filed"
    assert submitted["request"]["status"] == "pending"
    stored = rewards.REQUESTS[filed["id"]]
    assert national_id not in json.dumps(stored)
    assert stored["inquiry"]["chat"]["media"][0]["document_id"]

    fresh_email = "chat-skip@example.com"
    _register("Chat Skip", fresh_email)
    skip_session, _role = _login(fresh_email, "secure123456")
    opened, status = _post("/api/customer/professional-requests", {"role": "agent"}, token=skip_session)
    assert status == 200, opened
    skip_link = opened["inquiry_path"].split("t=", 1)[1]
    _chat(skip_link, "confirm_person", {"name": "Chat Skip"})
    os.environ["PHINS_IDENTITY_REQUIRED"] = "true"
    try:
        refused, status = _post("/api/professional-inquiry/chat", {
            "token": skip_link, "step": "identity", "value": "skip",
        })
    finally:
        os.environ.pop("PHINS_IDENTITY_REQUIRED", None)
    assert status == 400, refused
    assert refused["code"] == "identity_required"
    os.environ.pop("PHINS_IDENTITY_REQUIRED", None)
    _chat(skip_link, "identity", "skip")
    _chat(skip_link, "company", "no")
    _chat(skip_link, "evidence", "skip")
    filed_skip = _chat(skip_link, "review", "submit")
    assert filed_skip["status"] == "pending"
    assert filed_skip["chat"]["media"] == []

    page = (Path(__file__).resolve().parents[1] / "web_portal" / "static" / "professional-inquiry-chat.html").read_text(encoding="utf-8")
    script = (Path(__file__).resolve().parents[1] / "web_portal" / "static" / "professional-inquiry-chat.js").read_text(encoding="utf-8")
    classic = (Path(__file__).resolve().parents[1] / "web_portal" / "static" / "professional-inquiry.html").read_text(encoding="utf-8")
    assert "Phin" in page
    assert "disclosed" in page
    assert 'name="referrer" content="same-origin"' in page
    assert 'name="referrer" content="same-origin"' in classic
    assert "/api/professional-inquiry/chat" in script
    assert "/api/professional-inquiry/media" in script
    assert "/api/professional-inquiry/session" in script
    assert "/api/professional-inquiry/otp/request" in script
    assert "/api/professional-inquiry/session" in classic
    assert 'id="email"' in classic
    assert "readonly" in classic
    assert "You do not type it again" in script
    assert "getUserMedia" in script


def test_inquiry_email_and_identity_code_use_the_chat_notification_service(monkeypatch):
    """The inquiry email and the identity code share NotificationService and the Phin chat.

    Customer outreach is a different mail path. The chat records both sends and
    does not store the email token or the verification code.
    """
    def _outreach(*_args, **_kwargs):
        raise AssertionError("professional inquiry must not use a second mail path")

    monkeypatch.setattr(
        "services.customer_agent.communication.CustomerCommunicationAgent.send_customer_outreach",
        _outreach,
    )
    monkeypatch.setenv("BASE_URL", "https://portal.example.test")
    email = "inquiry-notify@example.com"
    _register("Inquiry Notify", email)
    token, _role = _login(email, "secure123456")
    filed, status = _post("/api/customer/professional-requests", {"role": "agent"}, token=token)
    assert status == 200, filed
    assert filed["email_sent"] is True

    from services.notification_service import get_notification_service
    provider = get_notification_service()._email_provider
    sent = [item for item in getattr(provider, "sent_emails", []) if item.get("to") == email]
    assert sent, "inquiry email was not sent by NotificationService"
    body = sent[-1]["body"]
    absolute = "https://portal.example.test/professional-inquiry-chat.html"
    assert absolute in body
    assert absolute in (sent[-1].get("html_body") or "")
    assert filed["inquiry_path"].startswith(absolute + "?")
    assert ".html/?" not in filed["inquiry_path"]
    assert ".html/?" not in body
    assert "one disclosed chat" in body
    assert "Open your PHINS portal" not in (sent[-1].get("body") or "")
    assert "Open your PHINS portal" not in (sent[-1].get("html_body") or "")
    parts = urlparse(filed["inquiry_path"])
    query = parse_qs(parts.query)
    link = query["t"][0]
    assert link in body
    prefill, status = _get("/api/professional-inquiry?t=" + link)
    assert status == 200, prefill
    messages = json.dumps(prefill["chat"]["messages"])
    assert email in messages
    assert "same email" in messages
    assert link not in messages
    assert "inq_" not in messages
    note = prefill["chat"]["notification"]
    assert note["template"] == "professional_inquiry_chat"
    assert note["sent"] is True
    assert note["notification_id"]

    otp, status = _post("/api/professional-inquiry/otp/request", {"token": link})
    assert status == 200, otp
    assert otp.get("notification_sent") is True
    assert otp.get("demo_otp_code")
    otp_messages = json.dumps((otp.get("chat") or {}).get("messages") or [])
    assert "6-digit code" in otp_messages
    assert otp["demo_otp_code"] not in otp_messages
    again, status = _get("/api/professional-inquiry?t=" + link)
    assert status == 200, again
    stored = json.dumps(again["chat"]["messages"])
    assert "6-digit code" in stored
    assert otp["demo_otp_code"] not in stored


def test_inquiry_email_is_absolute_when_only_webhook_base_url_is_set(monkeypatch):
    """WEBHOOK_BASE_URL is the second origin. A mail client can open that link."""
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.setenv("WEBHOOK_BASE_URL", "https://hooks.example.test")
    email = "inquiry-webhook-origin@example.com"
    _register("Webhook Origin", email)
    token, _role = _login(email, "secure123456")
    filed, status = _post("/api/customer/professional-requests", {"role": "supplier"}, token=token)
    assert status == 200, filed
    assert filed["email_sent"] is True
    from services.notification_service import get_notification_service
    provider = get_notification_service()._email_provider
    sent = [item for item in getattr(provider, "sent_emails", []) if item.get("to") == email]
    assert sent
    absolute = "https://hooks.example.test/professional-inquiry-chat.html"
    assert absolute in sent[-1]["body"]
    assert filed["inquiry_path"].startswith(absolute + "?")
    assert ".html/?" not in filed["inquiry_path"]
    assert ".html/?" not in sent[-1]["body"]
    link = parse_qs(urlparse(filed["inquiry_path"]).query)["t"][0]
    prefill, status = _get("/api/professional-inquiry?t=" + link)
    assert status == 200, prefill
    assert email in json.dumps(prefill["chat"]["messages"])
    assert "same email" in json.dumps(prefill["chat"]["messages"])
    assert link not in json.dumps(prefill["chat"]["messages"])


def _assert_openable_inquiry_link(url, request_id):
    """A mail client can open this: absolute, and `.html?` with no slash."""
    assert ".html/?" not in url
    assert url.split("?", 1)[0].endswith(".html")
    parts = urlparse(url)
    query = parse_qs(parts.query)
    assert parts.scheme in ("http", "https")
    assert parts.netloc
    assert parts.path == "/professional-inquiry-chat.html"
    assert query["r"] == [request_id]
    assert query["t"][0].startswith("inq_")
    return query["t"][0]


def _clear_inquiry_origins(monkeypatch):
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    monkeypatch.delenv("TEST_BASE_URL", raising=False)


def _mailed_inquiry(email, name, role="supplier", host=None):
    _register(name, email)
    token, _role = _login(email, "secure123456")
    extra = {"Host": host} if host else None
    filed, status = _post(
        "/api/customer/professional-requests",
        {"role": role},
        token=token,
        headers=extra,
    )
    assert status == 200, filed
    from services.notification_service import get_notification_service
    provider = get_notification_service()._email_provider
    sent = [item for item in getattr(provider, "sent_emails", []) if item.get("to") == email]
    assert sent, "inquiry email was not sent by NotificationService"
    return filed, sent[-1]


def test_inquiry_email_link_uses_the_live_site_when_no_origin_is_configured(monkeypatch, caplog):
    """No configured origin: the mailed link is the live site, not the request host.

    A relative `professional-inquiry-chat.html/?r=` link does not open in a
    mail client. The mailed URL is absolute and has no slash before `?`.
    """
    _clear_inquiry_origins(monkeypatch)
    caplog.set_level("DEBUG")
    email = "inquiry-live-site@example.com"
    filed, message = _mailed_inquiry(email, "Live Site")
    prefix = "https://www.phins.ai/professional-inquiry-chat.html?"
    assert filed["inquiry_path"].startswith(prefix)
    request_host = urlparse(BASE).netloc
    assert request_host not in filed["inquiry_path"]
    link = _assert_openable_inquiry_link(filed["inquiry_path"], filed["id"])
    body = message["body"]
    html = message.get("html_body") or ""
    assert filed["inquiry_path"] in body
    assert filed["inquiry_path"] in html
    assert ".html/?" not in body
    assert ".html/?" not in html
    assert link not in caplog.text


def test_inquiry_email_link_ignores_a_foreign_host(monkeypatch):
    """A spoofed Host must not receive the inquiry token."""
    _clear_inquiry_origins(monkeypatch)
    foreign = "attacker.example"
    email = "inquiry-foreign-host@example.com"
    filed, message = _mailed_inquiry(email, "Foreign Host", host=foreign)
    prefix = "https://www.phins.ai/professional-inquiry-chat.html?"
    assert filed["inquiry_path"].startswith(prefix)
    _assert_openable_inquiry_link(filed["inquiry_path"], filed["id"])
    mailed = message["body"] + (message.get("html_body") or "")
    assert filed["inquiry_path"] in mailed
    assert foreign not in filed["inquiry_path"]
    assert foreign not in mailed
    assert ".html/?" not in mailed

    lookalike = "evil.phins.ai"
    look_email = "inquiry-lookalike-host@example.com"
    look, look_message = _mailed_inquiry(look_email, "Lookalike Host", host=lookalike)
    assert look["inquiry_path"].startswith(prefix)
    look_mail = look_message["body"] + (look_message.get("html_body") or "")
    assert lookalike not in look["inquiry_path"]
    assert lookalike not in look_mail

    allowed, allowed_message = _mailed_inquiry(
        "inquiry-apex-host@example.com", "Apex Host", host="phins.ai",
    )
    apex = "https://phins.ai/professional-inquiry-chat.html?"
    assert allowed["inquiry_path"].startswith(apex)
    _assert_openable_inquiry_link(allowed["inquiry_path"], allowed["id"])
    assert allowed["inquiry_path"] in allowed_message["body"]
    assert "www.phins.ai" not in allowed["inquiry_path"]


def test_inquiry_email_link_drops_a_page_path_on_the_configured_origin(monkeypatch):
    """A BASE_URL that already names the page must not become `.html/?r=`."""
    monkeypatch.setenv(
        "BASE_URL",
        "https://portal.example.test/professional-inquiry-chat.html/",
    )
    monkeypatch.delenv("WEBHOOK_BASE_URL", raising=False)
    email = "inquiry-origin-path@example.com"
    _register("Origin Path", email)
    token, _role = _login(email, "secure123456")
    filed, status = _post("/api/customer/professional-requests", {"role": "agent"}, token=token)
    assert status == 200, filed
    assert filed["inquiry_path"].startswith(
        "https://portal.example.test/professional-inquiry-chat.html?"
    )
    _assert_openable_inquiry_link(filed["inquiry_path"], filed["id"])
    assert "/professional-inquiry-chat.html/professional-inquiry-chat.html" not in filed["inquiry_path"]


def test_inquiry_identity_records_through_a_database_style_store():
    """Record my identity uses the customer store even when it is not a dict.

    Production CUSTOMERS is a DatabaseDict. The inquiry path used to refuse
    that store after the verification code. The national ID stays off the
    transcript, and the email-link token still cannot record it.
    """
    class _CopyStore:
        def __init__(self, inner):
            self._inner = inner

        def __getitem__(self, key):
            value = self._inner[key]
            return dict(value) if isinstance(value, dict) else value

        def __setitem__(self, key, value):
            self._inner[key] = value

        def get(self, key, default=None):
            try:
                return self[key]
            except KeyError:
                return default

        def items(self):
            return list(self._inner.items())

    email = "inquiry-vault@example.com"
    customer_id = _register("Inquiry Vault", email)
    session, _role = _login(email, "secure123456")
    filed, status = _post("/api/customer/professional-requests", {"role": "supplier"}, token=session)
    assert status == 200, filed
    link = parse_qs(urlparse(filed["inquiry_path"]).query)["t"][0]
    _chat(link, "confirm_person", {
        "personal": {
            "name": "Inquiry Vault",
            "phone": "555-0142",
            "address": "4 Herzl",
            "city": "Tel Aviv",
            "country": "IL",
        },
    })
    national_id = "123456782"
    opened, status, set_cookies = _open("/api/professional-inquiry/session", {"token": link})
    assert status == 200, opened
    cookie_name, secret, _header = _inquiry_set_cookie(set_cookies)
    cookie = cookie_name + "=" + secret
    otp, status = _post("/api/professional-inquiry/otp/request", {"token": link})
    assert status == 200, otp
    checked, status, _cookies = _open("/api/professional-inquiry/otp/verify", {
        "request_id": opened["request_id"],
        "verification_id": otp["verification_id"],
        "otp_code": otp["demo_otp_code"],
    }, cookie=cookie)
    assert status == 200, checked
    store = _CopyStore(portal.CUSTOMERS)
    assert not isinstance(store, dict)
    previous = portal.CUSTOMERS
    portal.CUSTOMERS = store
    try:
        stolen, status = _post("/api/professional-inquiry/chat", {
            "token": link, "step": "identity",
            "value": {"nationality": "IL", "national_id": national_id},
        })
        assert status == 403, stolen
        assert stolen["code"] == "otp_required"
        recorded, status, _cookies = _open("/api/professional-inquiry/chat", {
            "request_id": opened["request_id"],
            "step": "identity",
            "value": {"nationality": "IL", "national_id": national_id},
        }, cookie=cookie)
    finally:
        portal.CUSTOMERS = previous
    assert status == 200, recorded
    dumped = json.dumps(recorded)
    assert national_id not in dumped
    assert "Identity vault is unavailable" not in dumped
    assert recorded["chat"]["identity"]["complete"] is True
    assert recorded["chat"]["identity"]["national_id_masked"].endswith("6782")
    assert portal.CUSTOMERS[customer_id]["national_id_last4"] == "6782"
    assert "national_id" not in portal.CUSTOMERS[customer_id]
    stored = json.dumps(rewards.REQUESTS[filed["id"]])
    assert national_id not in stored
    assert "Identity recorded" in stored


def test_inquiry_email_retries_when_the_first_provider_fails(monkeypatch):
    """A failed first NotificationService send must not be the end of the delivery.

    The identity code already builds a fresh service and tries the next
    configured provider. The inquiry email uses that same retry.
    """
    monkeypatch.setenv("BASE_URL", "https://portal.example.test")
    monkeypatch.setenv("SENDGRID_API_KEY", "sg-test-not-a-real-key")
    email = "inquiry-fallback@example.com"
    _register("Fallback", email)
    token, _role = _login(email, "secure123456")
    monkeypatch.setattr(
        "services.notification_service.should_use_mock_notifications",
        lambda: False,
    )
    sent = []

    class _Fail:
        def send(self, to, subject, body, html_body=None, **_kwargs):
            return False, None, "first provider rejected the message"

    class _Record:
        def send(self, to, subject, body, html_body=None, **_kwargs):
            sent.append({"to": to, "body": body, "html_body": html_body})
            return True, "fallback-msg", None

    def _fresh(use_mock=False, email_provider=None, sms_provider=None):
        from services.notification_service import MockSMSProvider, NotificationService
        provider = _Fail() if email_provider is None else _Record()
        return NotificationService(
            email_provider=provider,
            sms_provider=sms_provider or MockSMSProvider(),
        )

    monkeypatch.setattr("services.notification_service.create_notification_service", _fresh)
    filed, status = _post("/api/customer/professional-requests", {"role": "agent"}, token=token)
    assert status == 200, filed
    assert filed["email_sent"] is True
    assert sent, "the fallback provider was not asked to send"
    absolute = "https://portal.example.test/professional-inquiry-chat.html"
    assert absolute in sent[-1]["body"]
    link = parse_qs(urlparse(filed["inquiry_path"]).query)["t"][0]
    assert link in sent[-1]["body"]
    prefill, status = _get("/api/professional-inquiry?t=" + link)
    assert status == 200, prefill
    assert email in json.dumps(prefill["chat"]["messages"])
    assert "same email" in json.dumps(prefill["chat"]["messages"])
    assert link not in json.dumps(prefill["chat"]["messages"])


def test_inquiry_email_uses_the_login_when_the_record_has_no_email(monkeypatch):
    """A record with no email uses the login for the inquiry mail and the identity code."""
    from services.notification_service import MockEmailProvider

    email = "inquiry-login-mail@example.com"
    other = "other-inbox@example.com"
    customer_id = _register("Login Mail", email)
    portal.CUSTOMERS[customer_id]["email"] = ""
    token, _role = _login(email, "secure123456")
    portal.CUSTOMERS[customer_id]["email"] = ""
    recorded = []
    original = MockEmailProvider.send

    def _record(self, to, subject, body, html_body=None, *args, **kwargs):
        recorded.append({"to": to, "subject": subject, "body": body})
        return original(self, to, subject, body, html_body, *args, **kwargs)

    monkeypatch.setattr(MockEmailProvider, "send", _record)
    filed, status = _post("/api/customer/professional-requests", {"role": "agent"}, token=token)
    assert status == 200, filed
    assert filed["email_sent"] is True
    link = parse_qs(urlparse(filed["inquiry_path"]).query)["t"][0]
    inquiry_mail = [item for item in recorded if "/professional-inquiry-chat.html" in item["body"]]
    assert inquiry_mail, "inquiry email was not handed to NotificationService"
    assert inquiry_mail[-1]["to"] == email
    otp, status = _post("/api/professional-inquiry/otp/request", {"token": link, "email": other})
    assert status == 200, otp
    assert otp.get("notification_sent") is True
    assert otp.get("verification_id")
    assert otp.get("demo_otp_code")
    code_mail = [item for item in recorded if "Verification Code" in item["subject"]]
    assert code_mail, "identity code was not handed to NotificationService"
    assert code_mail[-1]["to"] == email
    assert other not in {item["to"] for item in recorded}
    assert otp["demo_otp_code"] in code_mail[-1]["body"]
    messages = json.dumps((otp.get("chat") or {}).get("messages") or [])
    assert "6-digit code" in messages
    assert otp["demo_otp_code"] not in messages
    assert link not in messages
    prefill, status = _get("/api/professional-inquiry?t=" + link)
    assert status == 200, prefill
    assert prefill["known"]["email"] == email
    assert prefill["chat"]["email"] == email
    assert prefill["chat"]["step"]["input"]["email"] == email
    shown = json.dumps(prefill["chat"]["messages"])
    assert email in shown
    assert other not in shown
    assert portal.CUSTOMERS[customer_id]["email"] == ""
    moved = _chat(link, "confirm_person", {
        "email": other,
        "personal": {
            "name": "Login Mail",
            "email": other,
            "phone": "555-0100",
            "address": "1 Herzl",
            "city": "Tel Aviv",
            "country": "IL",
        },
    })
    assert moved["request_id"] == filed["id"]
    assert moved["chat"]["email"] == email
    assert other not in json.dumps(moved)
    _chat(link, "identity", "skip")
    still, status = _get("/api/professional-inquiry?t=" + link)
    assert status == 200, still
    assert still["known"]["email"] == email
    assert portal.CUSTOMERS[customer_id]["email"] == ""
    _chat(link, "company", "no")
    _chat(link, "evidence", "skip")
    submitted = _chat(link, "review", "submit")
    assert submitted["request_id"] == filed["id"]
    assert submitted["status"] == "pending"
    assert submitted["request"]["id"] == filed["id"]
    assert [key for key, row in rewards.REQUESTS.items() if row.get("customer_id") == customer_id] == [filed["id"]]
    assert portal.CUSTOMERS[customer_id]["email"] == ""


def test_a_failed_chat_note_still_returns_the_emailed_code(monkeypatch):
    """The transcript write is after the email. Its failure must not hide the code."""
    def _boom(*_args, **_kwargs):
        raise rewards.RewardError(
            "This application was already submitted",
            status=409,
            code="inquiry_submitted",
        )

    monkeypatch.setattr(rewards, "note_inquiry_delivery", _boom)
    email = "inquiry-note-fail@example.com"
    _register("Note Fail", email)
    session, _role = _login(email, "secure123456")
    filed, status = _post("/api/customer/professional-requests", {"role": "agent"}, token=session)
    assert status == 200, filed
    link = parse_qs(urlparse(filed["inquiry_path"]).query)["t"][0]
    opened, status, set_cookies = _open("/api/professional-inquiry/session", {"token": link})
    assert status == 200, opened
    cookie_name, secret, _header = _inquiry_set_cookie(set_cookies)
    cookie = cookie_name + "=" + secret
    otp, status = _post("/api/professional-inquiry/otp/request", {"token": link})
    assert status == 200, otp
    assert otp.get("success") is True
    assert otp.get("verification_id")
    assert otp.get("demo_otp_code")
    assert otp.get("notification_sent") is True
    assert "chat" not in otp
    again, status = _get("/api/professional-inquiry?t=" + link)
    assert status == 200, again
    assert otp["demo_otp_code"] not in json.dumps(again["chat"]["messages"])
    checked, status, _cookies = _open("/api/professional-inquiry/otp/verify", {
        "request_id": opened["request_id"],
        "verification_id": otp["verification_id"],
        "otp_code": otp["demo_otp_code"],
    }, cookie=cookie)
    assert status == 200, checked
    assert checked.get("otp_verified") is True


def test_demo_code_stays_visible_after_a_failed_verify():
    node = shutil.which("node")
    assert node, "node is required to check the inquiry code bubble"
    script = Path(__file__).resolve().parent / "professional_inquiry_otp.test.js"
    completed = subprocess.run([node, str(script)], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize("closed_status", ["rejected", "suspended"])
def test_approval_does_not_reopen_a_closed_supplier(closed_status):
    email = f"closed-{closed_status}@example.com"
    _register("Closed Desk", email)
    token, _role = _login(email, "secure123456")
    filed, status = _post("/api/customer/professional-requests", {
        "role": "supplier",
        "supplier_type": "clinic",
        "company_name": "Closed Clinic",
    }, token=token)
    assert status == 200, filed
    saved = _finish_inquiry(filed, name="Closed Desk", company={
        "company_name": "Closed Clinic",
        "supplier_type": "clinic",
        "city": "Haifa",
        "country": "IL",
    })
    admin, _ = _login("admin", "admin123")
    opened, status = _post("/api/admin/professional-requests/review", {
        "id": saved["id"], "decision": "approve",
    }, token=admin)
    assert status == 200, opened
    supplier = portal.supply_chain_service.suppliers[opened["supplier_id"]]
    supplier["status"] = closed_status
    supplier["portal_active"] = False

    agent_filed, status = _post("/api/customer/professional-requests", {"role": "agent"}, token=token)
    assert status == 200, agent_filed
    agent_saved = _finish_inquiry(agent_filed, name="Closed Desk")
    refused, status = _post("/api/admin/professional-requests/review", {
        "id": agent_saved["id"], "decision": "approve",
    }, token=admin)
    assert status == 409, refused
    assert refused["code"] == "supplier_closed"
    assert rewards.REQUESTS[agent_saved["id"]]["status"] == "pending"
    assert supplier["status"] == closed_status
    assert supplier["portal_active"] is False


def test_classic_form_requires_identity_when_the_platform_does():
    email = "classic-identity@example.com"
    customer_id = _register("Classic Identity", email)
    token, _role = _login(email, "secure123456")
    filed, status = _post("/api/customer/professional-requests", {"role": "supplier"}, token=token)
    assert status == 200, filed
    link = filed["inquiry_path"].split("t=", 1)[1]
    os.environ["PHINS_IDENTITY_REQUIRED"] = "true"
    try:
        refused, status = _post("/api/professional-inquiry", {
            "token": link,
            "personal": {
                "name": "Classic Identity",
                "phone": "555-0142",
                "address": "4 Herzl",
                "city": "Haifa",
                "country": "IL",
            },
            "has_company": False,
        })
        assert status == 400, refused
        assert refused["code"] == "identity_required"
        assert rewards.REQUESTS[filed["id"]]["status"] == "inquiry"
        from services.customer_identity_service import set_identity
        set_identity(
            portal.CUSTOMERS, customer_id, "123456782", "IL",
            source="chat", actor="professional_inquiry",
        )
        saved, status = _post("/api/professional-inquiry", {
            "token": link,
            "personal": {
                "name": "Classic Identity",
                "phone": "555-0142",
                "address": "4 Herzl",
                "city": "Haifa",
                "country": "IL",
            },
            "has_company": False,
        })
    finally:
        os.environ.pop("PHINS_IDENTITY_REQUIRED", None)
    assert status == 200, saved
    assert saved["status"] == "pending"
    assert "123456782" not in json.dumps(saved)


def test_declined_company_is_not_the_supplier_name():
    email = "declined-company@example.com"
    _register("Declined Person", email)
    token, _role = _login(email, "secure123456")
    filed, status = _post("/api/customer/professional-requests", {
        "role": "supplier",
        "supplier_type": "clinic",
        "company_name": "North Clinic",
    }, token=token)
    assert status == 200, filed
    saved = _finish_inquiry(filed, name="Declined Person")
    stored = rewards.REQUESTS[saved["id"]]
    assert stored["inquiry"]["has_company"] is False
    assert stored["company_name"] is None
    assert stored["supplier_type"] is None
    stored["company_name"] = "North Clinic"
    stored["supplier_type"] = "clinic"
    stored["inquiry"]["company"] = {
        "company_name": "North Clinic",
        "supplier_type": "clinic",
    }
    admin, _ = _login("admin", "admin123")
    reviewed, status = _post("/api/admin/professional-requests/review", {
        "id": saved["id"], "decision": "approve",
    }, token=admin)
    assert status == 200, reviewed
    supplier = portal.supply_chain_service.suppliers[reviewed["supplier_id"]]
    assert supplier["company_name"] == "Declined Person"
    assert supplier["company_name_source"] == "placeholder"
    assert supplier["supplier_type"] == "other"
    assert "North Clinic" not in json.dumps(supplier["company_name"])


def _file_professional_chat(session, role, *, name, company=None, confirm_identity=False):
    filed, status = _post("/api/customer/professional-requests", {"role": role}, token=session)
    assert status == 200, filed
    link = parse_qs(urlparse(filed["inquiry_path"]).query)["t"][0]
    _chat(link, "confirm_person", {
        "personal": {
            "name": name,
            "phone": "555-0177",
            "address": "8 Herzl",
            "city": "Haifa",
            "country": "IL",
        },
    })
    _chat(link, "identity", "confirm" if confirm_identity else "skip")
    if company:
        _chat(link, "company", company)
    else:
        _chat(link, "company", "no")
    _chat(link, "evidence", "skip")
    submitted = _chat(link, "review", "submit")
    assert submitted.get("status") == "pending"
    assert (submitted.get("request") or {}).get("id") == filed["id"]
    return filed["id"]


def test_filed_chat_is_pending_on_the_supplier_and_agent_desks():
    """Staff see the same filed request, then the existing fee ledger."""
    supplier_email = "desk-supplier@example.com"
    supplier_customer = _register("Desk Clinic", supplier_email)
    supplier_session, _role = _login(supplier_email, "secure123456")
    from services.customer_identity_service import set_identity
    set_identity(
        portal.CUSTOMERS, supplier_customer, "123456782", "IL",
        source="chat", actor="professional_inquiry",
    )
    master = {
        "name": portal.CUSTOMERS[supplier_customer]["name"],
        "email": portal.CUSTOMERS[supplier_customer]["email"],
    }
    supplier_request = _file_professional_chat(
        supplier_session, "supplier", name="Desk Clinic", confirm_identity=True,
        company={"company_name": "Desk Clinic", "supplier_type": "clinic"},
    )
    assert portal.CUSTOMERS[supplier_customer]["name"] == master["name"]
    assert portal.CUSTOMERS[supplier_customer]["email"] == master["email"]
    assert "supplier_id" not in portal.CUSTOMERS[supplier_customer]
    assert "national_id" not in portal.CUSTOMERS[supplier_customer]
    stored = rewards.REQUESTS[supplier_request]
    assert "123456782" not in json.dumps(stored)

    agent_email = "desk-agent@example.com"
    agent_customer = _register("Desk Agent", agent_email)
    agent_session, _role = _login(agent_email, "secure123456")
    agent_request = _file_professional_chat(
        agent_session, "agent", name="Desk Agent",
    )
    agent_stored = rewards.REQUESTS[agent_request]
    assert agent_stored["inquiry"]["has_company"] is False
    assert agent_stored["company_name"] is None
    assert agent_stored["supplier_type"] is None
    assert agent_stored["inquiry"]["company"] is None
    agent_suppliers = [
        item for item in portal.supply_chain_service.suppliers.values()
        if item.get("customer_id") == agent_customer
    ]
    assert len(agent_suppliers) == 1
    assert agent_suppliers[0]["status"] == "pending"
    assert agent_suppliers[0]["company_name"] == "Desk Agent"
    assert agent_suppliers[0]["company_name_source"] == "placeholder"
    assert agent_suppliers[0]["supplier_type"] == "other"
    assert not agent_suppliers[0].get("business_registration_number")
    assert agent_request in agent_suppliers[0]["professional_request_ids"]
    assert "123456782" not in json.dumps(agent_suppliers[0])
    assert "supplier_id" not in portal.CUSTOMERS[agent_customer]
    assert "agent_id" not in portal.CUSTOMERS[agent_customer]

    admin, _ = _login("admin", "admin123")
    pending, status = _get("/api/admin/suppliers/pending", token=admin)
    assert status == 200, pending
    supplier_row = next(
        item for item in pending["items"]
        if supplier_request in (item.get("professional_request_ids") or [])
        or item.get("professional_request_id") == supplier_request
    )
    assert supplier_row["status"] == "pending"
    assert supplier_row["customer_id"] == supplier_customer
    assert "123456782" not in json.dumps(pending)
    stats, status = _get("/api/admin/suppliers/analytics", token=admin)
    assert status == 200, stats
    assert stats["pending_applications"] >= 2

    invitations, status = _get("/api/admin/agent-invitations", token=admin)
    assert status == 200, invitations
    agent_row = next(item for item in invitations["items"] if item.get("code") == agent_request)
    assert agent_row["status"] == "pending_approval"
    assert agent_row["professional_request_id"] == agent_request
    assert "123456782" not in json.dumps(invitations)
    pending_codes = [
        item.get("code") for item in invitations["items"] if item.get("status") == "pending_approval"
    ]
    assert len(pending_codes) == len(set(pending_codes))
    overview, status = _get("/api/admin/agents/overview", token=admin)
    assert status == 200, overview
    assert overview["invitations_pending_approval"] == len(pending_codes)

    approved, status = _post(
        f"/api/admin/suppliers/{supplier_row['id']}/approve",
        {"notes": "Same request"},
        token=admin,
    )
    assert status == 200, approved
    assert approved["request"]["id"] == supplier_request
    assert approved["request"]["status"] == "approved"
    assert portal.CUSTOMERS[supplier_customer]["name"] == master["name"]
    assert portal.CUSTOMERS[supplier_customer]["supplier_id"] == approved["supplier_id"]
    assert "national_id" not in portal.CUSTOMERS[supplier_customer]
    clinic = portal.supply_chain_service.suppliers[approved["supplier_id"]]
    assert clinic["status"] == "approved"
    assert clinic["company_name"] == "Desk Clinic"
    assert "supplier_id" not in portal.CUSTOMERS[agent_customer]

    still, status = _get("/api/admin/agent-invitations", token=admin)
    assert any(item.get("code") == agent_request for item in still["items"])
    agent_approved, status = _post("/api/admin/agent-invitations/approve", {
        "code": agent_request,
        "commission_rate": 25,
    }, token=admin)
    assert status == 200, agent_approved
    assert agent_approved["request"]["id"] == agent_request
    assert agent_approved["request"]["status"] == "approved"
    assert agent_approved["request"]["supplier_id"] == agent_suppliers[0]["id"]
    assert len([
        item for item in portal.supply_chain_service.suppliers.values()
        if item.get("customer_id") == agent_customer
    ]) == 1
    shared = portal.supply_chain_service.suppliers[agent_suppliers[0]["id"]]
    assert shared["status"] == "approved"
    assert "agent" in shared["roles"] and "supplier" in shared["roles"]
    assert shared["agent_id"] == agent_approved["request"]["agent_id"]
    from services.agent_ecosystem_service import get_agent
    assert get_agent(shared["agent_id"])["default_commission_rate"] == pytest.approx(0.1)
    assert portal.CUSTOMERS[agent_customer]["email"] == agent_email
    assert "national_id" not in portal.CUSTOMERS[agent_customer]

    portal.SUPPLIER_ORDERS["ORD-DESK-FEE"] = {
        "id": "ORD-DESK-FEE",
        "supplier_id": approved["supplier_id"],
        "customer_id": "CUST-DESK-BUYER",
        "platform_fee": 11.0,
        "commission": 11.0,
        "supplier_payout": 89.0,
        "total_amount": 100.0,
        "status": "completed",
    }
    before = float(portal.PHINS_BALANCE_SHEET["expense_breakdown"].get("customer_acquisition") or 0)
    report, status = _get("/api/admin/supplier-agent-pipeline?audience=supplier", token=admin)
    assert status == 200, report
    fee_row = next(item for item in report["rows"] if item["supplier_id"] == approved["supplier_id"])
    assert fee_row["sales_fees"] == pytest.approx(11.0)
    sealed, status = _post("/api/admin/supplier-agent-pipeline/seal", {
        "supplier_id": approved["supplier_id"],
    }, token=admin)
    assert status == 200, sealed
    assert sealed["cash_event"] is False
    assert float(portal.PHINS_BALANCE_SHEET["expense_breakdown"].get("customer_acquisition") or 0) == pytest.approx(before)
    statements = [
        entry for entry in portal.supply_chain_service.ledger.values()
        if entry.get("entry_type") == "pipeline_statement"
        and entry.get("supplier_id") == approved["supplier_id"]
    ]
    assert len(statements) == 1
    assert statements[0]["amount"] == 0
    portal.SUPPLIER_ORDERS.pop("ORD-DESK-FEE", None)


def test_unrelated_supplier_desk_action_leaves_the_filed_request_pending():
    """A supplier that only shares the customer is not the staged application."""
    email = "unrelated-desk@example.com"
    customer_id = _register("Unrelated Desk", email)
    session, _role = _login(email, "secure123456")
    request_id = _file_professional_chat(session, "supplier", name="Unrelated Desk", company={
        "company_name": "Unrelated Clinic",
        "supplier_type": "clinic",
    })
    staged = next(
        item for item in portal.supply_chain_service.suppliers.values()
        if request_id in (item.get("professional_request_ids") or [])
    )
    service = portal.supply_chain_service
    service.suppliers["SUP-UNRELATED-APPROVE"] = {
        "id": "SUP-UNRELATED-APPROVE",
        "company_name": "Separate Approve",
        "contact_email": "separate-approve@example.com",
        "contact_name": "Separate",
        "supplier_type": "clinic",
        "status": "pending",
        "customer_id": customer_id,
        "portal_active": False,
        "application_date": "2026-01-01T00:00:00",
    }
    service.suppliers["SUP-UNRELATED-REJECT"] = {
        "id": "SUP-UNRELATED-REJECT",
        "company_name": "Separate Reject",
        "contact_email": "separate-reject@example.com",
        "contact_name": "Separate",
        "supplier_type": "clinic",
        "status": "pending",
        "customer_id": customer_id,
        "portal_active": False,
        "application_date": "2026-01-02T00:00:00",
    }
    admin, _ = _login("admin", "admin123")
    approved, status = _post("/api/admin/suppliers/SUP-UNRELATED-APPROVE/approve", {
        "notes": "Classic supplier",
    }, token=admin)
    assert status == 200, approved
    assert "request" not in approved
    assert service.suppliers["SUP-UNRELATED-APPROVE"]["status"] == "approved"
    assert rewards.REQUESTS[request_id]["status"] == "pending"
    assert staged["status"] == "pending"
    assert "supplier_id" not in portal.CUSTOMERS[customer_id]
    rejected, status = _post("/api/admin/suppliers/SUP-UNRELATED-REJECT/reject", {
        "reason": "Not this application",
    }, token=admin)
    assert status == 200, rejected
    assert "request" not in rejected
    assert service.suppliers["SUP-UNRELATED-REJECT"]["status"] == "rejected"
    assert rewards.REQUESTS[request_id]["status"] == "pending"
    assert staged["status"] == "pending"


def test_agent_overview_counts_a_professional_request_once():
    email = "overview-once@example.com"
    _register("Overview Once", email)
    session, _role = _login(email, "secure123456")
    request_id = _file_professional_chat(session, "agent", name="Overview Once")
    admin, _ = _login("admin", "admin123")
    before_items, status = _get("/api/admin/agent-invitations", token=admin)
    assert status == 200, before_items
    before_codes = [item.get("code") for item in before_items["items"]]
    assert before_codes.count(request_id) == 1
    before, status = _get("/api/admin/agents/overview", token=admin)
    assert status == 200, before
    pending_before = [
        item.get("code") for item in before_items["items"] if item.get("status") == "pending_approval"
    ]
    assert before["invitations_pending_approval"] == len(pending_before)

    from services.agent_ecosystem_service import INVITATIONS
    INVITATIONS[request_id] = {
        "code": request_id,
        "agent_id": "AGT-OVERVIEW",
        "invitee_type": "agent",
        "status": "pending_approval",
        "proposed_rate": 0.1,
        "commission_rate": None,
        "created_at": "2026-01-01T00:00:00",
    }
    try:
        after_items, status = _get("/api/admin/agent-invitations", token=admin)
        assert status == 200, after_items
        assert [item.get("code") for item in after_items["items"]].count(request_id) == 1
        after, status = _get("/api/admin/agents/overview", token=admin)
        assert status == 200, after
        pending_after = [
            item.get("code") for item in after_items["items"] if item.get("status") == "pending_approval"
        ]
        assert after["invitations_pending_approval"] == len(set(pending_after))
        assert after["invitations_pending_approval"] == before["invitations_pending_approval"]
    finally:
        INVITATIONS.pop(request_id, None)


def test_declined_application_can_be_filed_again_on_the_same_supplier():
    """A decline withdraws the staged row. It does not close the person."""
    email = "decline-again@example.com"
    customer_id = _register("Decline Again", email)
    session, _role = _login(email, "secure123456")
    request_id = _file_professional_chat(session, "supplier", name="Decline Again", company={
        "company_name": "Decline Clinic",
        "supplier_type": "clinic",
    })
    staged_id = rewards.REQUESTS[request_id]["supplier_id"]
    admin, _ = _login("admin", "admin123")
    declined, status = _post("/api/admin/professional-requests/review", {
        "id": request_id, "decision": "reject", "note": "Not this time",
    }, token=admin)
    assert status == 200, declined
    supplier = portal.supply_chain_service.suppliers[staged_id]
    assert supplier["status"] == "withdrawn"
    assert supplier["status"] not in ("rejected", "suspended", "terminated")
    assert supplier["portal_active"] is False
    assert "supplier_id" not in portal.CUSTOMERS[customer_id]
    pending, status = _get("/api/admin/suppliers/pending", token=admin)
    assert status == 200, pending
    assert all(item.get("id") != staged_id for item in pending["items"])

    again = _file_professional_chat(session, "supplier", name="Decline Again", company={
        "company_name": "Decline Clinic",
        "supplier_type": "clinic",
    })
    assert again == request_id
    assert rewards.REQUESTS[request_id]["status"] == "pending"
    assert rewards.REQUESTS[request_id]["supplier_id"] == staged_id
    assert portal.supply_chain_service.suppliers[staged_id]["status"] == "pending"
    assert len([
        item for item in portal.supply_chain_service.suppliers.values()
        if item.get("customer_id") == customer_id
    ]) == 1
    approved, status = _post("/api/admin/professional-requests/review", {
        "id": request_id, "decision": "approve",
    }, token=admin)
    assert status == 200, approved
    assert portal.supply_chain_service.suppliers[staged_id]["status"] == "approved"
    assert portal.CUSTOMERS[customer_id]["supplier_id"] == staged_id
    assert portal.CUSTOMERS[customer_id]["name"] == "Decline Again"
    assert "national_id" not in portal.CUSTOMERS[customer_id]


def test_declining_supplier_request_keeps_an_approved_agent_role():
    email = "keep-agent@example.com"
    customer_id = _register("Keep Agent", email)
    session, _role = _login(email, "secure123456")
    supplier_request = _file_professional_chat(session, "supplier", name="Keep Agent", company={
        "company_name": "Keep Clinic",
        "supplier_type": "clinic",
    })
    agent_request = _file_professional_chat(session, "agent", name="Keep Agent", company={
        "company_name": "Keep Clinic",
        "supplier_type": "clinic",
    })
    admin, _ = _login("admin", "admin123")
    opened, status = _post("/api/admin/agent-invitations/approve", {
        "code": agent_request,
        "commission_rate": 40,
    }, token=admin)
    assert status == 200, opened
    supplier_id = opened["request"]["supplier_id"]
    supplier = portal.supply_chain_service.suppliers[supplier_id]
    assert supplier["status"] == "pending"
    assert "agent" in supplier["roles"]
    declined, status = _post("/api/admin/professional-requests/review", {
        "id": supplier_request, "decision": "reject", "note": "Supplier application declined",
    }, token=admin)
    assert status == 200, declined
    assert rewards.REQUESTS[supplier_request]["status"] == "rejected"
    assert rewards.REQUESTS[agent_request]["status"] == "approved"
    supplier = portal.supply_chain_service.suppliers[supplier_id]
    assert supplier["status"] == "approved"
    assert supplier["status"] not in ("rejected", "suspended", "terminated")
    assert supplier["agent_id"] == opened["request"]["agent_id"]
    assert len([
        item for item in portal.supply_chain_service.suppliers.values()
        if item.get("customer_id") == customer_id
    ]) == 1
    from services.agent_ecosystem_service import get_agent
    assert get_agent(supplier["agent_id"])["default_commission_rate"] == pytest.approx(0.1)


def test_staging_failure_leaves_the_inquiry_resubmittable(monkeypatch):
    email = "stage-fail@example.com"
    _register("Stage Fail", email)
    session, _role = _login(email, "secure123456")
    filed, status = _post("/api/customer/professional-requests", {"role": "supplier"}, token=session)
    assert status == 200, filed
    link = parse_qs(urlparse(filed["inquiry_path"]).query)["t"][0]
    _chat(link, "confirm_person", {
        "personal": {
            "name": "Stage Fail",
            "phone": "555-0177",
            "address": "8 Herzl",
            "city": "Haifa",
            "country": "IL",
        },
    })
    _chat(link, "identity", "skip")
    _chat(link, "company", {"company_name": "Stage Clinic", "supplier_type": "clinic"})
    _chat(link, "evidence", "skip")
    real = rewards._stage_staff_application
    calls = {"n": 0}

    def fail_once(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("supplier service unavailable")
        return real(req)

    monkeypatch.setattr(rewards, "_stage_staff_application", fail_once)
    failed, status = _post("/api/professional-inquiry/chat", {
        "token": link, "step": "review", "value": "submit",
    })
    assert status == 503, failed
    assert failed["code"] == "application_not_staged"
    assert rewards.REQUESTS[filed["id"]]["status"] == "inquiry"
    assert not rewards.REQUESTS[filed["id"]].get("supplier_id")
    submitted = _chat(link, "review", "submit")
    assert submitted.get("status") == "pending"
    assert rewards.REQUESTS[filed["id"]]["supplier_id"]
    assert portal.supply_chain_service.suppliers[
        rewards.REQUESTS[filed["id"]]["supplier_id"]
    ]["status"] == "pending"


def test_agent_desk_persists_the_staged_supplier(monkeypatch):
    email = "persist-agent@example.com"
    _register("Persist Agent", email)
    session, _role = _login(email, "secure123456")
    request_id = _file_professional_chat(session, "agent", name="Persist Agent")
    supplier_id = rewards.REQUESTS[request_id]["supplier_id"]
    saved = []

    def remember(sid, data):
        saved.append((sid, data.get("status")))

    monkeypatch.setattr(portal, "_persist_supplier", remember)
    admin, _ = _login("admin", "admin123")
    approved, status = _post("/api/admin/agent-invitations/approve", {
        "code": request_id,
    }, token=admin)
    assert status == 200, approved
    assert saved == [(supplier_id, "approved")]
    assert portal.supply_chain_service.suppliers[supplier_id]["status"] == "approved"


def test_filed_inquiry_link_returns_status_only_and_expires_in_every_status():
    email = "filed-link@example.com"
    _register("Filed Link", email)
    token, _role = _login(email, "secure123456")
    filed, status = _post("/api/customer/professional-requests", {"role": "supplier"}, token=token)
    assert status == 200, filed
    link = filed["inquiry_path"].split("t=", 1)[1]
    saved = _finish_inquiry(filed, name="Filed Link")
    view, status = _get("/api/professional-inquiry?t=" + link)
    assert status == 200, view
    assert view == {
        "request_id": saved["id"],
        "role": "supplier",
        "status": "pending",
        "editable": False,
    }
    dumped = json.dumps(view)
    assert email not in dumped
    assert "555-0100" not in dumped
    assert "1 Herzl" not in dumped
    assert "national_id_masked" not in dumped
    admin, _ = _login("admin", "admin123")
    reviewed, status = _post("/api/admin/professional-requests/review", {
        "id": saved["id"], "decision": "approve",
    }, token=admin)
    assert status == 200, reviewed
    approved, status = _get("/api/professional-inquiry?t=" + link)
    assert status == 200, approved
    assert approved["status"] == "approved"
    assert email not in json.dumps(approved)
    rewards.REQUESTS[saved["id"]]["inquiry"]["expires_at"] = "2000-01-01T00:00:00Z"
    expired, status = _get("/api/professional-inquiry?t=" + link)
    assert status == 410, expired
    assert expired["code"] == "inquiry_expired"


def test_inquiry_link_exchanges_for_a_cookie_and_leaves_the_token_off_the_body():
    email = "inquiry-session@example.com"
    _register("Session Person", email)
    token, _role = _login(email, "secure123456")
    filed, status = _post("/api/customer/professional-requests", {"role": "supplier"}, token=token)
    assert status == 200, filed
    link = filed["inquiry_path"].split("t=", 1)[1]
    opened, status, cookies = _open("/api/professional-inquiry/session", {"token": link})
    assert status == 200, opened
    cookie_name, secret, cookie_header = _inquiry_set_cookie(cookies)
    assert secret.startswith("inqs_")
    assert "HttpOnly" in cookie_header
    assert secret not in json.dumps(opened)
    assert "token_sha256" not in json.dumps(opened)
    cookie = cookie_name + "=" + secret
    via_cookie, status = _get("/api/professional-inquiry", cookie=cookie)
    assert status == 200, via_cookie
    assert via_cookie["known"]["email"] == email
    missing, status = _get("/api/professional-inquiry")
    assert status == 400, missing
    via_link, status = _get("/api/professional-inquiry?t=" + link)
    assert status == 200, via_link
    assert via_link["known"]["email"] == email
    rewards.REQUESTS[filed["id"]]["inquiry"]["browser_session"]["expires_at"] = "2000-01-01T00:00:00Z"
    stale, status = _get("/api/professional-inquiry", cookie=cookie)
    assert status == 410, stale
    assert stale["code"] == "inquiry_session_expired"
    still, status = _get("/api/professional-inquiry?t=" + link)
    assert status == 200, still


def test_two_open_inquiries_keep_separate_cookies():
    email = "two-inquiries@example.com"
    _register("Two Inquiries", email)
    token, _role = _login(email, "secure123456")
    supplier, status = _post("/api/customer/professional-requests", {"role": "supplier"}, token=token)
    assert status == 200, supplier
    agent, status = _post("/api/customer/professional-requests", {"role": "agent"}, token=token)
    assert status == 200, agent
    supplier_link = supplier["inquiry_path"].split("t=", 1)[1]
    agent_link = agent["inquiry_path"].split("t=", 1)[1]
    supplier_open, status, supplier_cookies = _open(
        "/api/professional-inquiry/session", {"token": supplier_link},
    )
    assert status == 200, supplier_open
    agent_open, status, agent_cookies = _open(
        "/api/professional-inquiry/session", {"token": agent_link},
    )
    assert status == 200, agent_open
    supplier_name, supplier_secret, supplier_header = _inquiry_set_cookie(supplier_cookies)
    agent_name, agent_secret, agent_header = _inquiry_set_cookie(agent_cookies)
    assert supplier_name != agent_name
    assert "HttpOnly" in supplier_header
    assert "HttpOnly" in agent_header
    assert supplier_secret not in json.dumps(supplier_open)
    assert agent_secret not in json.dumps(agent_open)
    both = f"{supplier_name}={supplier_secret}; {agent_name}={agent_secret}"
    supplier_view, status = _get(
        "/api/professional-inquiry?r=" + supplier_open["request_id"], cookie=both,
    )
    assert status == 200, supplier_view
    assert supplier_view["request_id"] == supplier_open["request_id"]
    assert supplier_view["role"] == "supplier"
    agent_view, status = _get(
        "/api/professional-inquiry?r=" + agent_open["request_id"], cookie=both,
    )
    assert status == 200, agent_view
    assert agent_view["request_id"] == agent_open["request_id"]
    assert agent_view["role"] == "agent"
    explicit, status = _get(
        "/api/professional-inquiry?t=" + supplier_link,
        cookie=f"{agent_name}={agent_secret}",
    )
    assert status == 200, explicit
    assert explicit["request_id"] == supplier_open["request_id"]
    assert explicit["role"] == "supplier"
    moved, status, _cookies = _open("/api/professional-inquiry/chat", {
        "request_id": supplier_open["request_id"],
        "step": "confirm_person",
        "value": {"name": "Two Inquiries"},
    }, cookie=both)
    assert status == 200, moved
    assert moved["request_id"] == supplier_open["request_id"]
    assert moved["role"] == "supplier"
    assert moved["chat"]["cursor"] == "identity"
    untouched, status = _get(
        "/api/professional-inquiry?r=" + agent_open["request_id"], cookie=both,
    )
    assert status == 200, untouched
    assert untouched["chat"]["cursor"] == "confirm_person"


def test_access_log_redacts_the_inquiry_token_on_both_pages():
    secret = "inq_" + "cd" * 16
    for path in ("/professional-inquiry-chat.html", "/professional-inquiry.html"):
        line = f"GET {path}?t={secret}&token=tok-live&resume_code=PHINS-CHAT-LIVE&x=1 HTTP/1.1"
        redacted = portal._redact_access_log_line(line)
        assert secret not in redacted
        assert "tok-live" not in redacted
        assert "PHINS-CHAT-LIVE" not in redacted
        assert "t=REDACTED" in redacted
        assert "token=REDACTED" in redacted
        assert "resume_code=REDACTED" in redacted
        assert "x=1" in redacted
    api = portal._redact_access_log_line(
        f"GET /api/professional-inquiry?t={secret} HTTP/1.1"
    )
    assert secret not in api
    assert "t=REDACTED" in api
    other = portal._redact_access_log_line(f"GET /dashboard.html?t={secret} HTTP/1.1")
    assert secret in other


def test_identity_code_does_not_open_the_vault_for_the_email_link():
    email = "otp-session@example.com"
    customer_id = _register("OTP Session", email)
    token, _role = _login(email, "secure123456")
    filed, status = _post("/api/customer/professional-requests", {"role": "supplier"}, token=token)
    assert status == 200, filed
    link = filed["inquiry_path"].split("t=", 1)[1]
    _chat(link, "confirm_person", {"name": "OTP Session"})
    opened, status, set_cookies = _open("/api/professional-inquiry/session", {"token": link})
    assert status == 200, opened
    cookie_name, secret, cookie_header = _inquiry_set_cookie(set_cookies)
    assert "HttpOnly" in cookie_header
    cookie = cookie_name + "=" + secret
    otp, status = _post("/api/professional-inquiry/otp/request", {
        "request_id": opened["request_id"],
    })
    assert status == 400, otp
    otp, status, _cookies = _open("/api/professional-inquiry/otp/request", {
        "request_id": opened["request_id"],
    }, cookie=cookie)
    assert status == 200, otp
    burned, status = _post("/api/professional-inquiry/otp/verify", {
        "token": link,
        "verification_id": otp["verification_id"],
        "otp_code": otp["demo_otp_code"],
    })
    assert status == 403, burned
    assert burned["code"] == "otp_session_required"
    national_id = "123456782"
    refused, status = _post("/api/professional-inquiry/chat", {
        "token": link, "step": "identity",
        "value": {"nationality": "IL", "national_id": national_id},
    })
    assert status == 403, refused
    assert refused["code"] == "otp_required"
    assert portal.CUSTOMERS[customer_id].get("national_id_last4") in (None, "")
    fresh, status, _cookies = _open("/api/professional-inquiry/otp/request", {
        "request_id": opened["request_id"],
    }, cookie=cookie)
    assert status == 200, fresh
    checked, status, _cookies = _open("/api/professional-inquiry/otp/verify", {
        "request_id": opened["request_id"],
        "verification_id": fresh["verification_id"],
        "otp_code": fresh["demo_otp_code"],
    }, cookie=cookie)
    assert status == 200, checked
    still_refused, status = _post("/api/professional-inquiry/chat", {
        "token": link, "step": "identity",
        "value": {"nationality": "IL", "national_id": national_id},
    })
    assert status == 403, still_refused
    assert still_refused["code"] == "otp_required"
    assert portal.CUSTOMERS[customer_id].get("national_id_last4") in (None, "")
    recorded, status, _cookies = _open("/api/professional-inquiry/chat", {
        "request_id": opened["request_id"],
        "step": "identity",
        "value": {"nationality": "IL", "national_id": national_id},
    }, cookie=cookie)
    assert status == 200, recorded
    assert national_id not in json.dumps(recorded)
    assert portal.CUSTOMERS[customer_id]["national_id_last4"] == "6782"


def test_two_inquiries_in_one_tab_follow_the_new_email_link():
    node = shutil.which("node")
    assert node, "node is required to check the inquiry cross-link"
    script = Path(__file__).resolve().parent / "professional_inquiry_link.test.js"
    completed = subprocess.run([node, str(script)], check=False, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
