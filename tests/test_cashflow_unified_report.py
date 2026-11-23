"""The unified cash flow statement reads every book once and writes none."""

import copy
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from services.cashflow_unified_report import management_fee_rate, unified_cashflow_report
from services.nft_ledger import mint_token


def _books():
    """One customer: $200 risk, $30 expense, $43 profit, $200 savings a month."""
    policy = {
        "id": "POL-U1",
        "customer_id": "CUST-U1",
        "status": "active",
        "start_date": "2026-01-01",
        "risk_premium_annual": 2400.00,
        "savings_premium_annual": 2400.00,
        "expense_loading_annual": 360.00,
        "profit_margin_annual": 516.00,
        "annual_premium": 5676.00,
    }
    bills = [
        {"id": "BILL-U1-01", "customer_id": "CUST-U1", "policy_id": "POL-U1",
         "payment_period": "2026-01", "status": "paid", "amount_paid": 473.00},
        {"id": "BILL-U1-02", "customer_id": "CUST-U1", "policy_id": "POL-U1",
         "payment_period": "2026-02", "status": "paid", "amount_paid": 473.00},
    ]
    claims = [
        {"id": "CLM-U1-1", "customer_id": "CUST-U1", "status": "paid", "paid_amount": 150.00},
        {"id": "CLM-U1-2", "customer_id": "CUST-U1", "status": "approved", "amount": 90.00},
    ]
    ledger = {}
    mint_token(
        ledger,
        owner_id="CUST-U1",
        transaction_type="claim_payment_received",
        transaction_id="TX-CLM-U1-1",
        amount=150.00,
        description="Claim CLM-U1-1",
        created_at="2026-02-10T00:00:00+00:00",
        metadata={"claim_id": "CLM-U1-1"},
    )
    return policy, bills, claims, ledger


def _triple_reported_claim():
    """The fault: one $150 claim written three times on each of three books."""
    transactions = [
        {"id": f"TX-{n}", "customer_id": "CUST-U1", "type": "claim_payment_received",
         "amount": 150.00, "metadata": {"claim_id": "CLM-U1-1"}}
        for n in range(3)
    ]
    wallets = {
        "CUST-U1": {
            "balance": 450.00,
            "transactions": [
                {"id": f"HW-{n}", "type": "claim_payment", "claim_id": "CLM-U1-1", "amount": 150.00}
                for n in range(3)
            ],
        }
    }
    sheet = {
        "claims_reserve": 1000.00,
        "revenue_breakdown": {"management_fees": 0.0},
        "expense_breakdown": {"claims_paid": 450.00},
        "transactions": [
            {"tx_id": f"BS-{n}", "category": "claims_paid", "claim_id": "CLM-U1-1", "amount": 150.00}
            for n in range(3)
        ],
    }
    return transactions, wallets, sheet


def _check(report, check_id):
    return next(row for row in report["integrity"]["checks"] if row["id"] == check_id)


def test_premium_waterfall_fills_kernel_risk_first_and_ties_to_the_cent():
    policy, bills, claims, ledger = _books()
    report = unified_cashflow_report(policies=[policy], bills=bills, claims=claims, nft_ledger=ledger)
    premiums = report["premiums"]
    assert premiums["collected"] == 946.00
    assert premiums["landed"] == {
        "risk": 400.00,
        "underwriting_fee": 0.0,
        "expense_loading": 60.00,
        "profit": 86.00,
        "savings": 400.00,
        "above_stack": 0.0,
        "without_kernel_pin": 0.0,
    }
    assert premiums["savings_destinations"] == {
        "health_wallet": 120.00, "investments": 260.00, "algo": 20.00,
    }
    assert round(sum(premiums["expense_loading_shares"].values()), 2) == 60.00
    assert _check(report, "premium_waterfall_ties")["ok"] is True
    assert _check(report, "kernel_risk_not_saved")["ok"] is True
    kernel = report["kernel"]
    assert kernel["policies_in_force"] == 1 and kernel["kernel_pinned"] == 1
    assert kernel["annual"]["risk"] == 2400.00
    assert kernel["annual"]["savings_addon"] == 2400.00
    assert report["writes"] is False


def _ledger_cash():
    """The same two premiums and the one paid claim, as the customer ledger holds them."""
    return [
        {"id": "TX-U1-01", "customer_id": "CUST-U1", "type": "bill_payment", "amount": 473.00,
         "metadata": {"bill_id": "BILL-U1-01", "policy_id": "POL-U1"}},
        {"id": "TX-U1-02", "customer_id": "CUST-U1", "type": "bill_payment", "amount": 473.00,
         "metadata": {"bill_id": "BILL-U1-02", "policy_id": "POL-U1"}},
        {"id": "TX-CLM-U1-1", "customer_id": "CUST-U1", "type": "claim_payment_received", "amount": 150.00,
         "metadata": {"claim_id": "CLM-U1-1"}},
    ]


def _section(report, name):
    return next(row for row in report["statement"] if row["section"].startswith(name))


def test_the_statement_ties_to_the_balance_sheet_line_by_line():
    policy, bills, claims, ledger = _books()
    report = unified_cashflow_report(
        policies=[policy], bills=bills, claims=claims, nft_ledger=ledger, transactions=_ledger_cash(),
    )
    balance = report["balance_sheet"]
    assert balance["ties"] is True and balance["largest_difference"] == 0.0
    assert _check(report, "balance_sheet_ties")["ok"] is True
    compared = {row["key"]: row for row in balance["compared"]}
    assert all(row["ok"] and row["difference"] == 0.0 for row in compared.values())
    assert compared["premium_cash"]["balance_sheet"] == 946.00
    assert compared["claim_cash"]["balance_sheet"] == 150.00
    assert compared["claims_reserve"]["balance_sheet"] == 250.00
    assert compared["customer_savings"]["balance_sheet"] == 400.00
    assert report["underwriting"]["surplus_label"] == "Underwriting surplus"
    # Own funds are the risk book and the company's premium income, nothing else.
    assert balance["own_funds"] == _section(report, "Risk book")["total"] + report["company"]["premium_income"]
    assert round(balance["own_funds"] + balance["held_for_others"], 2) == balance["net_cash"] == 796.00
    closing = _section(report, "Balance sheet")
    assert closing["total"] == 796.00
    assert round(sum(line["amount"] for line in closing["lines"]), 2) == 796.00


def test_premium_with_no_kernel_pin_is_held_on_the_risk_book_and_is_not_company_income():
    policy, bills, claims, ledger = _books()
    unpinned = {
        "id": "POL-U2", "customer_id": "CUST-U2", "status": "active", "start_date": "2026-01-01",
        "annual_premium": 2100.60,
    }
    bills = bills + [{
        "id": "BILL-U2-01", "customer_id": "CUST-U2", "policy_id": "POL-U2",
        "payment_period": "2026-01", "status": "paid", "amount_paid": 175.05,
    }]
    transactions = _ledger_cash() + [{
        "id": "TX-U2-01", "customer_id": "CUST-U2", "type": "bill_payment", "amount": 175.05,
        "metadata": {"bill_id": "BILL-U2-01", "policy_id": "POL-U2"},
    }]
    report = unified_cashflow_report(
        policies=[policy, unpinned], bills=bills, claims=claims, nft_ledger=ledger, transactions=transactions,
    )
    landed = report["premiums"]["landed"]
    assert landed["without_kernel_pin"] == 175.05 and landed["above_stack"] == 0.0
    assert _check(report, "premium_waterfall_ties")["ok"] is True
    assert _check(report, "kernel_pins_present")["ok"] is False
    risk_book = _section(report, "Risk book")
    assert risk_book["total"] == 425.05
    assert {"label": "Premium with no kernel pin, held until the policy is pinned", "amount": 175.05, "book": "risk"} in risk_book["lines"]
    # The company keeps its loading and margin on the pinned policy only.
    assert report["company"]["premium_income"] == 117.25
    assert report["underwriting"]["premium_without_kernel_pin"] == 175.05
    row = next(row for row in report["customers"] if row["customer_id"] == "CUST-U2")
    assert (row["premiums_collected"], row["risk"], row["without_kernel_pin"]) == (175.05, 0.0, 175.05)
    # The balance sheet holds the same cash in the claims reserve, so the two tie.
    balance = report["balance_sheet"]
    assert balance["ties"] is True
    assert balance["premium_without_kernel_pin"] == 175.05
    compared = {row["key"]: row for row in balance["compared"]}
    assert compared["claims_reserve"]["statement"] == compared["claims_reserve"]["balance_sheet"] == 425.05
    assert compared["company_income"]["statement"] == compared["company_income"]["balance_sheet"] == 117.25
    assert report["underwriting"]["surplus_label"] == "Held on the risk book, premium with no kernel pin included"
    assert risk_book["lines"][-1]["label"] == report["underwriting"]["surplus_label"]
    # Loss ratio stays on kernel risk. The surplus figure also holds the unpinned cash.
    assert report["underwriting"]["loss_ratio_pct"] == 37.5


def test_unpinned_cash_on_a_customer_who_also_has_a_pinned_policy_stays_on_the_risk_book():
    policy, bills, claims, ledger = _books()
    unpinned = {
        "id": "POL-U1B", "customer_id": "CUST-U1", "status": "active", "start_date": "2026-01-01",
        "annual_premium": 2100.60,
    }
    bills = bills + [{
        "id": "BILL-U1B-01", "customer_id": "CUST-U1", "policy_id": "POL-U1B",
        "payment_period": "2026-01", "status": "paid", "amount_paid": 175.05,
    }]
    transactions = _ledger_cash() + [{
        "id": "TX-U1B-01", "customer_id": "CUST-U1", "type": "bill_payment", "amount": 175.05,
        "metadata": {"bill_id": "BILL-U1B-01", "policy_id": "POL-U1B"},
    }]
    report = unified_cashflow_report(
        policies=[policy, unpinned], bills=bills, claims=claims, nft_ledger=ledger, transactions=transactions,
    )
    landed = report["premiums"]["landed"]
    assert landed["risk"] == 400.00
    assert landed["without_kernel_pin"] == 175.05
    assert landed["above_stack"] == 0.0
    assert _check(report, "premium_waterfall_ties")["ok"] is True
    assert report["company"]["premium_income"] == 117.25
    assert report["underwriting"]["surplus"] == 425.05
    assert report["underwriting"]["surplus_label"] == "Held on the risk book, premium with no kernel pin included"
    assert report["underwriting"]["loss_ratio_pct"] == 37.5
    row = next(row for row in report["customers"] if row["customer_id"] == "CUST-U1")
    assert row["without_kernel_pin"] == 175.05 and row["risk"] == 400.00
    balance = report["balance_sheet"]
    assert balance["ties"] is True
    assert balance["premium_without_kernel_pin"] == 175.05
    compared = {row["key"]: row for row in balance["compared"]}
    assert compared["claims_reserve"]["statement"] == compared["claims_reserve"]["balance_sheet"] == 425.05
    assert compared["company_income"]["statement"] == compared["company_income"]["balance_sheet"] == 117.25
    assert _check(report, "balance_sheet_ties")["ok"] is True


def test_cash_the_customer_ledger_does_not_carry_fails_the_balance_sheet_tie():
    policy, bills, claims, ledger = _books()
    # One of the two premiums never reached the customer ledger.
    report = unified_cashflow_report(
        policies=[policy], bills=bills, claims=claims, nft_ledger=ledger, transactions=_ledger_cash()[1:],
    )
    check = _check(report, "balance_sheet_ties")
    assert check["ok"] is False and check["amount"] == 473.00
    assert "balance_sheet_ties" in report["integrity"]["failed"]
    compared = {row["key"]: row for row in report["balance_sheet"]["compared"]}
    assert compared["premium_cash"] == {
        "key": "premium_cash", "label": "Premium cash collected",
        "statement": 946.00, "balance_sheet": 473.00, "difference": 473.00, "ok": False,
    }


def test_a_claim_reported_three_times_is_counted_once():
    policy, bills, claims, ledger = _books()
    transactions, wallets, sheet = _triple_reported_claim()
    report = unified_cashflow_report(
        policies=[policy], bills=bills, claims=claims, nft_ledger=ledger,
        transactions=transactions, wallets=wallets, balance_sheet=sheet,
    )
    section = report["claims"]
    assert section["paid_claims"] == 1
    assert section["paid_once"] == 150.00
    assert section["by_book"] == {
        "ledger": 450.00, "wallet": 450.00, "balance_sheet": 450.00, "sealed": 150.00,
    }
    assert section["if_books_were_added"] == 1350.00
    assert section["repeated_by_book"]["balance_sheet"] == 300.00
    assert section["repeated_total"] == 900.00
    assert section["unposted"] == 0.0
    assert section["approved_in_reserve"] == 90.00
    row = section["rows"][0]
    assert row["counted"] == 150.00 and row["books_recording"] == 4
    assert report["underwriting"]["claims_paid"] == 150.00
    assert report["underwriting"]["surplus"] == 250.00
    assert report["underwriting"]["loss_ratio_pct"] == 37.5
    check = _check(report, "claims_counted_once")
    assert check["ok"] is False and check["amount"] == 900.00
    assert "claims_counted_once" in report["integrity"]["failed"]
    risk_book = next(s for s in report["statement"] if s["section"] == "Risk book")
    assert risk_book["total"] == 250.00


def test_the_report_does_not_write_a_book():
    policy, bills, claims, ledger = _books()
    transactions, wallets, sheet = _triple_reported_claim()
    before = copy.deepcopy((policy, bills, claims, ledger, transactions, wallets, sheet))
    unified_cashflow_report(
        policies=[policy], bills=bills, claims=claims, nft_ledger=ledger,
        transactions=transactions, wallets=wallets, balance_sheet=sheet,
    )
    assert (policy, bills, claims, ledger, transactions, wallets, sheet) == before


def test_paid_claim_with_no_transfer_is_unposted_and_orphan_cash_is_named():
    policy, bills, claims, _ledger = _books()
    sheet = {"transactions": [
        {"tx_id": "BS-9", "category": "claims_paid", "claim_id": "CLM-GONE", "amount": 75.00},
    ]}
    report = unified_cashflow_report(policies=[policy], bills=bills, claims=claims, balance_sheet=sheet)
    assert report["claims"]["unposted"] == 150.00
    assert report["claims"]["cash_without_claim_record"] == 75.00
    assert report["claims"]["cash_without_claim_record_ids"] == ["CLM-GONE"]
    assert _check(report, "claims_posted")["ok"] is False
    assert _check(report, "claim_cash_has_a_claim")["ok"] is False


def test_management_fee_is_an_accrual_on_investments_and_algo():
    report = unified_cashflow_report(
        wallets={"CUST-U1": {"balance": 500.00, "transactions": []}},
        investments={"CUST-U1": {"position": 10000.00}},
        algo={"CUST-U1": {"available": 2000.00}},
        balance_sheet={"revenue_breakdown": {"management_fees": 0.0}},
    )
    funds = report["customer_funds"]
    assert funds["assets_under_management"] == 12000.00
    assert funds["health_wallet"] == 500.00
    fee = funds["management_fee"]
    assert fee["annual_rate_pct"] == 1.0
    assert fee["annual_at_current_aum"] == 120.00
    assert fee["monthly_accrual"] == 10.00
    assert fee["charged_by_this_report"] is False
    scenario = unified_cashflow_report(
        investments={"CUST-U1": {"position": 10000.00}}, management_fee_pct=0.02,
    )
    assert scenario["customer_funds"]["management_fee"]["annual_at_current_aum"] == 200.00


def test_management_fee_rate_stays_inside_the_reserve_range():
    assert float(management_fee_rate()) == 0.01
    assert float(management_fee_rate(0.025)) == 0.025
    assert float(management_fee_rate(2)) == 0.02
    assert float(management_fee_rate(0.5)) == 0.10
    assert float(management_fee_rate(-1)) == 0.01
    assert float(management_fee_rate("nope")) == 0.01


def test_marketplace_commission_comes_out_of_the_bid():
    orders = [
        {"id": "ORD-1", "customer_id": "CUST-U1", "supplier_id": "SUP-1", "status": "completed",
         "total_amount": 100.00, "commission": 15.00, "supplier_payout": 85.00,
         "wallet_deduction": 60.00, "external_payment_amount": 40.00, "settlement_status": "settled"},
        {"id": "ORD-2", "customer_id": "CUST-U1", "supplier_id": "SUP-1", "status": "delivered",
         "total_amount": 200.00, "commission": 30.00, "supplier_payout": 170.00,
         "wallet_deduction": 200.00, "settlement_status": "pending_admin_payout"},
        {"id": "ORD-3", "customer_id": "CUST-U1", "supplier_id": "SUP-2", "status": "cancelled",
         "total_amount": 999.00, "commission": 149.85, "supplier_payout": 849.15},
        {"id": "ORD-4", "customer_id": "CUST-U1", "supplier_id": "SUP-2", "status": "completed",
         "total_amount": 50.00, "commission": 7.50, "supplier_payout": 50.00,
         "settlement_status": "settlement_dispute"},
    ]
    report = unified_cashflow_report(orders=orders, suppliers={"SUP-1": {"company_name": "Clinic One"}})
    market = report["marketplace"]
    assert market["orders"] == 3
    assert market["customer_price"] == 350.00
    assert market["commission"] == 52.50
    assert market["supplier_payout"] == 305.00
    assert market["cancelled_or_refunded"] == 999.00
    assert market["paid_from_health_wallet"] == 260.00
    assert market["suppliers"]["settled"] == 85.00
    assert market["suppliers"]["pending"] == 170.00
    assert market["suppliers"]["disputed"] == 50.00
    assert market["orders_not_tying"] == ["ORD-4"]
    assert market["suppliers"]["rows"][0]["name"] == "Clinic One"
    assert _check(report, "marketplace_orders_tie")["ok"] is False
    income = next(s for s in report["statement"] if s["section"] == "Company income")
    assert {"label": "Marketplace commission", "amount": 52.50, "book": "company"} in income["lines"]


def test_agent_commission_leaves_referral_rows_to_the_referral_book():
    commissions = [
        {"id": "COMM-1", "agent_id": "AGT-1", "amount": 40.00, "status": "accrued"},
        {"id": "COMM-2", "agent_id": "AGT-1", "amount": 25.00, "status": "payable"},
        {"id": "COMM-3", "agent_id": "AGT-2", "amount": 10.00, "status": "paid"},
        {"id": "COMM-4", "agent_id": "AGT-2", "amount": 650.00, "status": "accrued",
         "invitation_code": "REF-ABC123"},
    ]
    payouts = [
        {"id": "APAY-1", "agent_id": "AGT-2", "status": "settled", "gross_amount": 10.00},
        {"id": "APAY-2", "agent_id": "AGT-1", "status": "calculated", "gross_amount": 25.00},
    ]
    settlements = [
        {"id": "CACSET-CUST-A", "allocated_cents": 65000, "retained_cents": 0, "status": "held"},
        {"id": "CACSET-CUST-B", "allocated_cents": 55000, "retained_cents": 10000, "status": "settled"},
        {"id": "CACSET-CUST-C", "allocated_cents": 65000, "retained_cents": 0, "status": "reversed"},
    ]
    sheet = {"expense_breakdown": {"customer_acquisition": 1200.00}}
    report = unified_cashflow_report(
        commissions=commissions, payouts=payouts,
        referral_settlements=settlements, balance_sheet=sheet,
    )
    agents = report["agents"]
    assert agents["commission_owed"] == 65.00
    assert agents["commission_paid"] == 10.00
    assert agents["commission_lifetime"] == 75.00
    assert agents["referral_rows_left_to_referral_book"] == 650.00
    assert agents["payout_runs_settled"] == 10.00
    acquisition = report["acquisition"]
    assert acquisition["allocated"] == 1200.00
    assert acquisition["blocked"] == 650.00
    assert acquisition["settled"] == 550.00
    assert acquisition["reversed"] == 650.00
    assert acquisition["retained_by_company"] == 100.00
    assert _check(report, "acquisition_expense_ties")["ok"] is True
    assert report["company"]["owed_to_third_parties"] == 715.00


def test_withdrawals_tie_to_the_wallet_lines():
    wallets = {"CUST-U1": {"balance": 300.00, "transactions": [
        {"id": "HW-1", "type": "withdrawal_hold", "amount": 200.00, "withdrawal_id": "WDR-1"},
        {"id": "HW-2", "type": "withdrawal_hold", "amount": 80.00, "withdrawal_id": "WDR-2"},
        {"id": "HW-3", "type": "withdrawal_reversal", "amount": 80.00, "withdrawal_id": "WDR-2"},
    ]}}
    withdrawals = [
        {"id": "WDR-1", "customer_id": "CUST-U1", "status": "held", "amount": 200.00,
         "retention": {"flag": True}},
        {"id": "WDR-2", "customer_id": "CUST-U1", "status": "reversed", "amount": 0.0,
         "requested_amount": 80.00},
    ]
    report = unified_cashflow_report(wallets=wallets, withdrawals=withdrawals)
    assert report["withdrawals"]["held"] == 200.00
    assert report["withdrawals"]["returned_to_wallet"] == 80.00
    assert report["withdrawals"]["flagged_for_retention"] == 1
    assert report["customer_funds"]["total"] == 500.00
    assert _check(report, "withdrawals_tie")["ok"] is True
    broken = unified_cashflow_report(wallets=wallets, withdrawals=withdrawals[:0])
    assert _check(broken, "withdrawals_tie")["ok"] is False


def test_platform_and_specimen_ids_are_not_customers():
    report = unified_cashflow_report(
        wallets={
            "PHINS-CORPORATE": {"balance": 9999.00, "transactions": []},
            "CUST-X": {"balance": 111.00, "transactions": []},
            "CUST-U1": {"balance": 5.00, "transactions": []},
        },
    )
    assert report["customer_funds"]["health_wallet"] == 5.00
    assert [row["customer_id"] for row in report["customers"]] == ["CUST-U1"]


def test_unified_report_route_is_staff_only_and_reads_the_live_books():
    import web_portal.server as portal

    policy, bills, claims, _ledger = _books()
    transactions, wallets, sheet = _triple_reported_claim()
    portal.POLICIES[policy["id"]] = policy
    for bill in bills:
        portal.BILLING[bill["id"]] = bill
    for claim in claims:
        portal.CLAIMS[claim["id"]] = claim
    for tx in transactions:
        portal.TRANSACTION_LEDGER[tx["id"]] = tx
    portal.HEALTH_WALLETS.update(wallets)
    sheet_before = copy.deepcopy(portal.PHINS_BALANCE_SHEET)
    portal.PHINS_BALANCE_SHEET.setdefault("transactions", []).extend(sheet["transactions"])
    # Stamped like a login, so an earlier crisis-drop test does not close them.
    portal.SESSIONS["phins_unified-admin"] = portal._stamp_session_payload({
        "username": "admin", "role": "admin", "expires": "2099-01-01T00:00:00",
    })
    portal.SESSIONS["phins_unified-cust"] = portal._stamp_session_payload({
        "username": "u1@test", "role": "customer", "customer_id": "CUST-U1",
        "expires": "2099-01-01T00:00:00",
    })
    init_set = getattr(portal, "_TEST_PORTS_INITIALIZED", None)
    if isinstance(init_set, set):
        init_set.add(int(os.environ.get("TEST_PORT", "8000")))
    base = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")

    def call(path, token):
        req = Request(base + path, headers={"Authorization": f"Bearer {token}"})
        try:
            with urlopen(req, timeout=20) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8") or "{}")

    try:
        wallet_before = copy.deepcopy(portal.HEALTH_WALLETS["CUST-U1"])
        status, body = call("/api/admin/cashflow/unified-report", "phins_unified-admin")
        assert status == 200, body
        report = body["report"]
        assert report["claims"]["paid_once"] == 150.00
        assert report["claims"]["by_book"]["balance_sheet"] == 450.00
        assert report["premiums"]["landed"]["risk"] == 400.00
        assert report["customer_funds"]["management_fee"]["annual_rate_pct"] == 1.0
        assert portal.HEALTH_WALLETS["CUST-U1"] == wallet_before

        status, body = call("/api/admin/cashflow/unified-report?management_fee_pct=2.5", "phins_unified-admin")
        assert status == 200
        assert body["report"]["customer_funds"]["management_fee"]["annual_rate_pct"] == 2.5

        status, body = call("/api/admin/cashflow/unified-report?management_fee_pct=40", "phins_unified-admin")
        assert status == 400 and "error" in body

        status, body = call("/api/admin/cashflow/unified-report", "phins_unified-cust")
        assert status in (401, 403) and "error" in body
    finally:
        portal.SESSIONS.pop("phins_unified-admin", None)
        portal.SESSIONS.pop("phins_unified-cust", None)
        portal.PHINS_BALANCE_SHEET.clear()
        portal.PHINS_BALANCE_SHEET.update(sheet_before)


# ---------------------------------------------------------------------------
# Issued through the real routes: the books and the customer agree
# ---------------------------------------------------------------------------

_MONEY_PINS = (
    "risk_premium_annual", "savings_premium_annual",
    "expense_loading_annual", "profit_margin_annual",
)


def _http(method, path, token=None, body=None):
    base = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body or {}).encode("utf-8") if method == "POST" else None
    req = Request(base + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8") or "{}")


def _session(portal, token, role, username, customer_id=None):
    payload = {"username": username, "role": role, "expires": "2099-01-01T00:00:00"}
    if customer_id:
        payload["customer_id"] = customer_id
    portal.SESSIONS[token] = portal._stamp_session_payload(payload)
    init_set = getattr(portal, "_TEST_PORTS_INITIALIZED", None)
    if isinstance(init_set, set):
        init_set.add(int(os.environ.get("TEST_PORT", "8000")))
    return token


def _issue_and_pay(portal, email, pay=True):
    """Apply with the balanced savings add-on, approve, and pay the first bill."""
    admin = _session(portal, "phins_streams-admin", "admin", "admin")
    underwriter = _session(portal, "phins_streams-uw", "underwriter", "underwriter")
    status, created = _http("POST", "/api/policies/create", body={
        "customer_name": "Noa Barak", "customer_email": email, "customer_phone": "555-0456",
        "type": "life", "coverage_amount": 500000, "risk_score": "medium", "age": 40,
        "savings_addon": "balanced", "savings_rate": 0.5,
    })
    assert status in (200, 201), created
    customer_id = created["customer"]["id"]
    policy_id = created["policy"]["id"]
    status, body = _http("POST", "/api/underwriting/approve", underwriter, {
        "id": created["underwriting"]["id"], "approved_by": "underwriter",
    })
    assert status == 200, body
    paid = 0.0
    if pay:
        for bill in [b for b in portal.BILLING.values() if b.get("customer_id") == customer_id]:
            amount = bill.get("amount_due") or bill.get("amount")
            status, body = _http("POST", "/api/billing/pay", admin, {"bill_id": bill["id"], "amount": amount})
            assert status == 200, body
            paid += float(amount)
    return admin, customer_id, policy_id, round(paid, 2)


@pytest.fixture
def live_books():
    """The balance sheet is process-wide, so each journey hands it back as found."""
    import web_portal.server as portal

    sheet_before = copy.deepcopy(dict(portal.PHINS_BALANCE_SHEET))
    portal.initialize_balance_sheet()
    sheet = portal.PHINS_BALANCE_SHEET
    # Cash an earlier test left on the sheet is not this journey's premium.
    sheet.setdefault("revenue_breakdown", {})["premium_income"] = 0.0
    sheet.setdefault("expense_breakdown", {})["claims_paid"] = 0.0
    sheet["claims_reserve"] = sheet.get("seed_claims_reserve", 3_500_000.0)
    try:
        yield portal
    finally:
        portal.PHINS_BALANCE_SHEET.clear()
        portal.PHINS_BALANCE_SHEET.update(sheet_before)
        for token in [t for t in portal.SESSIONS if str(t).startswith(("phins_streams-", "phins_restore-"))]:
            portal.SESSIONS.pop(token, None)


def test_issued_policy_books_every_premium_dollar_on_a_kernel_stream(live_books):
    portal = live_books

    admin, customer_id, policy_id, paid = _issue_and_pay(portal, "noa.streams@example.com")
    policy = portal.POLICIES[policy_id]
    stack = sum(round(float(policy[key]), 2) for key in _MONEY_PINS)
    assert abs(stack - float(policy["annual_premium"])) <= 0.011, policy
    assert float(policy["savings_premium_annual"]) > 0

    status, body = _http("GET", "/api/finance/reconcile", admin)
    assert status == 200, body
    reconcile = body["reconcile"]
    assert reconcile["is_consistent"] is True, reconcile["discrepancies"]
    assert reconcile["warnings"] == []
    streams = reconcile["premium_streams"]
    assert streams["above_kernel_stack"] == 0.0
    assert round(sum(streams.values()), 2) == paid
    assert streams["savings"] > 0
    assert reconcile["savings"]["unlanded_savings_cash"] == 0.0
    assert reconcile["savings"]["accounting_savings_posted"] == streams["savings"]

    status, body = _http("GET", "/api/admin/cashflow/unified-report", admin)
    assert status == 200, body
    report = body["report"]
    # Seals from earlier tests stay in the shared NFT ledger, so read this customer's row.
    own = next(row for row in report["customers"] if row["customer_id"] == customer_id)
    assert own["premiums_collected"] == paid
    assert own["risk"] == streams["risk"]
    assert own["expense_loading"] == streams["expense_loading"]
    assert own["profit"] == streams["profit"]
    assert own["savings"] == streams["savings"]
    assert own["flags"] == []
    assert _check(report, "kernel_pins_present")["ok"] is True
    assert _check(report, "premium_waterfall_ties")["ok"] is True

    customer = _session(portal, "phins_streams-cust", "customer", "noa.streams@example.com", customer_id)
    status, body = _http("GET", "/api/customer/premium-picture", customer)
    assert status == 200, body
    flow = body["picture"]["cash_flow"]
    assert flow["writes"] is False
    assert flow["collected"] == paid
    assert flow["ties"] is True and flow["streams_total"] == paid
    by_key = {row["key"]: row["amount"] for row in flow["streams"]}
    assert by_key["risk"] == streams["risk"]
    assert by_key["savings"] == streams["savings"]
    assert "not_split" not in by_key
    assert flow["savings"]["charged"] == streams["savings"]
    assert flow["savings"]["on_accounts"] == streams["savings"]
    assert flow["savings"]["not_yet_on_accounts"] == 0.0
    held = flow["balances"]
    assert round(held["health_wallet"] + held["investments"] + held["algo"], 2) == streams["savings"]


def test_kernel_pin_restore_reproduces_the_premium_and_journals_first(live_books, monkeypatch):
    portal = live_books

    admin, customer_id, policy_id, _paid = _issue_and_pay(portal, "noa.restore@example.com", pay=False)
    policy = portal.POLICIES[policy_id]
    issued = {key: policy[key] for key in _MONEY_PINS}
    annual = policy["annual_premium"]
    # The policy as the database kept it before the pin was durable.
    for key in list(policy):
        if key in _MONEY_PINS or key in (
            "integrity_hash", "product_id", "savings_addon", "savings_rate", "savings_rate_used",
            "savings_formula", "allocation_version", "pricing_source",
        ):
            policy.pop(key)
    for bill in [b for b in portal.BILLING.values() if b.get("customer_id") == customer_id]:
        status, body = _http("POST", "/api/billing/pay", admin, {
            "bill_id": bill["id"], "amount": bill.get("amount_due") or bill.get("amount"),
        })
        assert status == 200, body

    status, body = _http("GET", "/api/finance/reconcile", admin)
    warning = next(w for w in body["reconcile"]["warnings"] if w["check"] == "premium_cash_without_kernel_pin")
    assert policy_id in warning["policy_ids"]
    # With nothing to split it by, the cash sits on the risk book and is shown apart.
    unsplit = body["reconcile"]["premium_streams"]
    assert unsplit["without_kernel_pin"] == warning["amount"] > 0
    assert unsplit["risk"] == 0.0 and unsplit["savings"] == 0.0
    assert body["reconcile"]["savings"]["accounting_savings_posted"] == 0.0

    journal = []
    monkeypatch.setattr(portal, "_append_cashflow_repair_journal", journal.append)
    customer = _session(portal, "phins_restore-cust", "customer", "noa.restore@example.com", customer_id)
    claims = _session(portal, "phins_restore-claims", "claims", "claims_adjuster")
    for token in (customer, claims, None):
        status, body = _http("GET", "/api/admin/cashflow/kernel-pins", token)
        assert status in (401, 403) and "error" in body
        status, body = _http("POST", "/api/admin/cashflow/restore-kernel-pins", token)
        assert status in (401, 403) and "error" in body

    status, body = _http("GET", "/api/admin/cashflow/kernel-pins", admin)
    assert status == 200, body
    preview = body["kernel_pins"]
    assert preview["applied"] is False
    row = next(r for r in preview["policies"] if r["policy_id"] == policy_id)
    assert row["status"] == "restorable"
    assert {key: row["pins"][key] for key in _MONEY_PINS} == issued
    # Reading the preview pins nothing and journals nothing.
    assert portal.POLICIES[policy_id].get("risk_premium_annual") is None
    assert journal == []

    def _refuse(_record):
        raise OSError("journal volume is read-only")

    monkeypatch.setattr(portal, "_append_cashflow_repair_journal", _refuse)
    status, body = _http("POST", "/api/admin/cashflow/restore-kernel-pins", admin)
    assert status == 503 and body["error"] == "repair_journal_failed"
    assert portal.POLICIES[policy_id].get("risk_premium_annual") is None

    monkeypatch.setattr(portal, "_append_cashflow_repair_journal", journal.append)
    status, body = _http("POST", "/api/admin/cashflow/restore-kernel-pins", admin)
    assert status == 200, body
    assert policy_id in body["kernel_pins"]["restored_policy_ids"]
    restored = portal.POLICIES[policy_id]
    assert {key: restored[key] for key in _MONEY_PINS} == issued
    assert restored["annual_premium"] == annual
    assert restored["kernel_pin_source"] == "restored_by_reprice"
    assert [line["phase"] for line in journal] == ["before", "after"]
    before = next(p for p in journal[0]["policies"] if p["policy_id"] == policy_id)
    assert before["before"]["risk_premium_annual"] is None
    assert before["after"]["risk_premium_annual"] == issued["risk_premium_annual"]
    assert journal[0]["actor"] == "admin"
    # The cash already booked all-risk is re-split on the accounting book.
    book = body["kernel_pins"]["accounting_book"]
    assert book["resplit_count"] == 1 and book["failed_count"] == 0
    assert book["resplit"][0]["before"] == {"risk": warning["amount"], "savings": 0.0}
    assert journal[1]["accounting_book_resplit"] == book["resplit"]

    # The streams are known now, and the savings that never landed are named.
    status, body = _http("GET", "/api/finance/reconcile", admin)
    reconcile = body["reconcile"]
    assert not [w for w in reconcile["warnings"] if w["check"] == "premium_cash_without_kernel_pin"]
    assert [d["check"] for d in reconcile["discrepancies"]] == ["savings_cash_not_landed_in_portfolios"]
    streams = reconcile["premium_streams"]
    assert streams["without_kernel_pin"] == 0.0 and streams["savings"] > 0
    assert reconcile["savings"]["accounting_savings_posted"] == streams["savings"]
    assert reconcile["reserves"]["risk_cash_collected"] == streams["risk"]
    assert book["resplit"][0]["after"] == {"risk": streams["risk"], "savings": streams["savings"]}
    gap = next(d for d in reconcile["discrepancies"] if d["check"] == "savings_cash_not_landed_in_portfolios")
    assert gap["customers"][0]["customer_id"] == customer_id
    owed = gap["customers"][0]["not_landed"]
    assert owed > 0

    status, body = _http("GET", "/api/customer/premium-picture", customer)
    assert body["picture"]["cash_flow"]["savings"]["not_yet_on_accounts"] == owed

    # The existing repair credits them once, 30 / 65 / 5, and the books tie.
    status, body = _http("POST", "/api/admin/cashflow/post-claim-transfers", admin)
    assert status == 200, body
    assert body["transfers"]["savings"]["credited_total"] == owed
    status, body = _http("GET", "/api/finance/reconcile", admin)
    assert body["reconcile"]["is_consistent"] is True, body["reconcile"]["discrepancies"]
    status, body = _http("GET", "/api/customer/premium-picture", customer)
    assert body["picture"]["cash_flow"]["savings"]["not_yet_on_accounts"] == 0.0

    # A second restore finds nothing to do.
    lines = len(journal)
    status, body = _http("POST", "/api/admin/cashflow/restore-kernel-pins", admin)
    assert status == 200 and body["kernel_pins"]["applied"] is False
    assert len([line for line in journal if line.get("action") == "cashflow.kernel_pin_restore"]) == 2
    assert lines >= 2


def _balance_sheet(admin):
    status, body = _http("GET", "/api/admin/balance-sheet", admin)
    assert status == 200, body
    return body["balance_sheet"]


def test_balance_sheet_holds_premium_cash_on_the_lines_the_statement_reports(live_books):
    portal = live_books

    admin, customer_id, policy_id, _ = _issue_and_pay(portal, "noa.balance@example.com", pay=False)
    stored_before = copy.deepcopy(dict(portal.PHINS_BALANCE_SHEET))
    before = _balance_sheet(admin)
    assert before["premium_position"]["premium_cash"] == 0.0
    paid = 0.0
    for bill in [b for b in portal.BILLING.values() if b.get("customer_id") == customer_id]:
        amount = bill.get("amount_due") or bill.get("amount")
        status, body = _http("POST", "/api/billing/pay", admin, {"bill_id": bill["id"], "amount": amount})
        assert status == 200, body
        paid = round(paid + float(amount), 2)
    assert paid > 0

    status, body = _http("GET", "/api/finance/reconcile", admin)
    streams = body["reconcile"]["premium_streams"]
    sheet = _balance_sheet(admin)
    position = sheet["premium_position"]
    assert position["premium_cash"] == paid == sheet["ledger_premium_collected"]
    assert position["ties_to_cash"] is True and position["reserve_ties_to_book"] is True
    assert position["claims_reserve"] == streams["risk"] == sheet["claims_reserve"]
    assert position["customer_savings"] == streams["savings"] > 0
    assert round(position["own_funds"] + position["held_for_others"], 2) == paid

    # The stored counter took the premium in whole. The sheet shows the company's part.
    stored = portal.PHINS_BALANCE_SHEET["operating_reserve"]
    assert round(stored - stored_before["operating_reserve"], 2) == paid
    assert sheet["stored_operating_reserve"] == stored
    assert round(sheet["operating_reserve"] - before["operating_reserve"], 2) == position["company_income"]
    # Own funds rise by the risk premium and the company's part, not by the whole premium twice.
    assert round(sheet["total_balance"] - before["total_balance"], 2) == position["own_funds"]
    assert position["own_funds"] < paid
    # Savings, the carrier share, and the ceding reserve are held, not earned.
    assert sheet["held_for_others"] == position["held_for_others"]
    assert round(sheet["net_income"] - before["net_income"], 2) == position["own_funds"]
    assert round(
        sheet["net_income_before_amounts_held_for_others"] - sheet["net_income"], 2
    ) == position["held_for_others"]
    # Premium income stays the ledger cash identity.
    assert sheet["revenue_breakdown"]["premium_income"] == paid
    # Wallet-credit classification is a read. It is not added to reserves or Claims Paid.
    aum = sheet["accumulated_aum"]
    assert aum["writes"] is False
    assert aum["retired_allocations_included"] is False
    assert aum["not_added_to_balance_sheet_totals"] is True
    assert "accumulated_aum" not in portal.PHINS_BALANCE_SHEET
    assert sheet["ledger_claims_paid"] == position["claim_cash"]

    status, body = _http("GET", "/api/admin/cashflow/unified-report", admin)
    assert status == 200, body
    own = next(row for row in body["report"]["customers"] if row["customer_id"] == customer_id)
    assert own["risk"] == position["claims_reserve"]
    assert own["savings"] == position["customer_savings"]
    compared = {row["key"]: row for row in body["report"]["balance_sheet"]["compared"]}
    assert compared["claims_reserve"]["balance_sheet"] == sheet["claims_reserve"]
    assert compared["customer_savings"]["balance_sheet"] == position["customer_savings"]

    # The tie-out sheet shows the cash net position beside who it belongs to.
    status, body = _http("GET", "/api/admin/balance-sheet/reconcile?auto_correct=false", admin)
    assert status == 200, body
    totals = body["summary_totals"]
    assert (totals["own_funds"], totals["held_for_others"]) == (position["own_funds"], position["held_for_others"])
    assert round(totals["own_funds"] + totals["held_for_others"], 2) == round(totals["net_position"], 2) == paid
