import json
import os
import shutil
import tempfile

import pytest

from services.foundation_service import (
    FoundationCreateRequest,
    get_foundation_service,
    reset_foundation_service,
)
from services.foundation_persistence_service import reset_persistence_service
from services.ledger_backup_service import reset_backup_service
from services.foundation_billing_integration import reset_billing_integration


@pytest.fixture(autouse=True)
def _reset_foundation_singletons():
    temp_data_dir = tempfile.mkdtemp(prefix="phins_foundation_finance_test_")
    reset_foundation_service()
    reset_persistence_service()
    reset_backup_service()
    reset_billing_integration()
    try:
        yield temp_data_dir
    finally:
        reset_foundation_service()
        reset_persistence_service()
        reset_backup_service()
        reset_billing_integration()
        if os.path.exists(temp_data_dir):
            shutil.rmtree(temp_data_dir)


def _create_foundation_with_founder(data_dir: str):
    service = get_foundation_service(
        enable_persistence=True,
        enable_backup=False,
        enable_billing_integration=False,
        data_dir=data_dir,
    )
    result = service.create_foundation(FoundationCreateRequest(
        name="Governance Foundation",
        foundation_type="family",
        founder_id="CUST-FOUNDER",
        description="Financial governance test",
    ))
    assert result.success
    return service, result.foundation_id


def _add_second_active_member(service, foundation_id: str, member_user_id: str = "CUST-MEMBER"):
    invite = service.create_invitation(
        foundation_id=foundation_id,
        invited_by="CUST-FOUNDER",
        invited_email=f"{member_user_id.lower()}@example.com",
    )
    assert invite.get("success"), invite

    joined = service.join_foundation(
        code=invite["code"],
        member_id=member_user_id,
        member_type="customer",
        display_name="Second Member",
    )
    assert joined.success, joined.error_message

    approved = service.approve_member(
        foundation_id=foundation_id,
        member_record_id=joined.member_id,
        approver_id="CUST-FOUNDER",
    )
    assert approved.success, approved.error_message
    return joined.member_id


def test_vote_creation_is_persisted(_reset_foundation_singletons):
    data_dir = _reset_foundation_singletons
    service, foundation_id = _create_foundation_with_founder(data_dir)

    vote_result = service.create_vote(
        foundation_id=foundation_id,
        created_by="CUST-FOUNDER",
        proposal_type="general",
        title="Persist this vote",
        description="Persistence verification",
    )
    assert vote_result.get("success"), vote_result

    votes_file = os.path.join(data_dir, "votes.json")
    assert os.path.exists(votes_file)
    with open(votes_file, "r", encoding="utf-8") as handle:
        persisted_votes = json.load(handle)
    assert vote_result["vote_id"] in persisted_votes


def test_balance_sheet_with_assets_liabilities_and_internal_loan(_reset_foundation_singletons):
    data_dir = _reset_foundation_singletons
    service, foundation_id = _create_foundation_with_founder(data_dir)
    _add_second_active_member(service, foundation_id, member_user_id="CUST-MEMBER")

    fund_id = service.get_foundation_funds(foundation_id)[0]["id"]
    contribution = service.make_contribution(
        foundation_id=foundation_id,
        fund_id=fund_id,
        member_id="CUST-FOUNDER",
        amount=1000.0,
        notes="Seed liquidity",
    )
    assert contribution.get("success"), contribution

    asset = service.record_asset_transaction(
        foundation_id=foundation_id,
        actor_id="CUST-FOUNDER",
        asset_symbol="ETF-USD",
        asset_name="Core ETF",
        asset_type="etf",
        transaction_type="buy",
        amount=300.0,
        quantity=3.0,
        unit_price=100.0,
        notes="Portfolio allocation",
    )
    assert asset.get("success"), asset

    liability = service.record_liability(
        foundation_id=foundation_id,
        actor_id="CUST-FOUNDER",
        liability_type="vendor_payable",
        amount=150.0,
        creditor_id="VENDOR-1",
        notes="Service invoice",
    )
    assert liability.get("success"), liability

    loan = service.lend_funds(
        foundation_id=foundation_id,
        lender_user_id="CUST-FOUNDER",
        borrower_user_id="CUST-MEMBER",
        amount=100.0,
        interest_rate=3.5,
        due_days=45,
        notes="Internal support loan",
    )
    assert loan.get("success"), loan

    balance_sheet = service.get_foundation_balance_sheet(foundation_id)
    assert balance_sheet.get("success"), balance_sheet
    assert balance_sheet["assets"]["cash"] == pytest.approx(700.0)
    assert balance_sheet["assets"]["investments"] == pytest.approx(300.0)
    assert balance_sheet["assets"]["total_assets"] == pytest.approx(1000.0)
    assert balance_sheet["liabilities"]["total_liabilities"] == pytest.approx(250.0)
    assert balance_sheet["equity"]["net_equity"] == pytest.approx(750.0)


def test_vote_driven_asset_purchase_execution(_reset_foundation_singletons):
    data_dir = _reset_foundation_singletons
    service, foundation_id = _create_foundation_with_founder(data_dir)

    fund_id = service.get_foundation_funds(foundation_id)[0]["id"]
    service.make_contribution(
        foundation_id=foundation_id,
        fund_id=fund_id,
        member_id="CUST-FOUNDER",
        amount=500.0,
        notes="Fund vote-based asset purchase",
    )

    vote_result = service.create_vote(
        foundation_id=foundation_id,
        created_by="CUST-FOUNDER",
        proposal_type="asset_purchase",
        title="Buy ETH reserve",
        description="Acquire ETH for reserve diversification",
        proposal_payload={
            "asset_symbol": "ETH",
            "asset_name": "Ethereum",
            "asset_type": "crypto",
            "amount": 200.0,
            "quantity": 0.2,
            "unit_price": 1000.0,
            "notes": "Voted allocation",
        },
    )
    assert vote_result.get("success"), vote_result
    vote_id = vote_result["vote_id"]

    cast = service.cast_vote(vote_id=vote_id, member_id="CUST-FOUNDER", choice="for", reason="approved")
    assert cast.get("success"), cast

    closed = service.close_vote(vote_id, closer_id="CUST-FOUNDER")
    assert closed.get("success"), closed
    assert closed.get("result") == "passed"

    vote = service.get_vote(vote_id)
    decision = vote.get("decision_record") or {}
    if isinstance(decision, str):
        decision = json.loads(decision)
    execution_result = decision.get("execution_result", {})
    assert execution_result.get("proposal_type") == "asset_purchase"
    assert execution_result.get("result", {}).get("success") is True

    balance_sheet = service.get_foundation_balance_sheet(foundation_id)
    assert balance_sheet["assets"]["cash"] == pytest.approx(300.0)
    assert balance_sheet["assets"]["investments"] == pytest.approx(200.0)


def test_integrity_autocorrect_and_seed_sync_export(_reset_foundation_singletons):
    data_dir = _reset_foundation_singletons
    service, foundation_id = _create_foundation_with_founder(data_dir)
    _add_second_active_member(service, foundation_id, member_user_id="CUST-CONNECT")

    foundation = service.get_foundation(foundation_id)
    foundation["current_members"] = 99

    integrity = service.validate_foundation_integrity(foundation_id, auto_correct=True)
    assert integrity.get("success"), integrity
    report = integrity.get("report", {})
    assert "current_members_reconciled" in report.get("corrections", [])
    assert service.get_foundation(foundation_id)["current_members"] == 2

    seed_path = os.path.join(data_dir, "foundation_seed_data.json")
    sync_result = service.sync_foundations_to_seed_snapshot(seed_path=seed_path, auto_correct_integrity=True)
    assert sync_result.get("success"), sync_result
    assert os.path.exists(seed_path)

    with open(seed_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["counts"]["foundations"] >= 1
    first_foundation = payload["foundations"][0]
    assert "connections" in first_foundation
    assert first_foundation["connections"]["totals"]["nodes"] >= 1
