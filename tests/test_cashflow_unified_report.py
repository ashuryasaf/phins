"""The unified cash flow statement reads every book once and writes none."""

import copy
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

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
