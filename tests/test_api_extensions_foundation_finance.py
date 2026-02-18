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
from web_portal.api_extensions import dispatch_get, dispatch_post


@pytest.fixture(autouse=True)
def _reset_services():
    test_data_dir = tempfile.mkdtemp(prefix="phins_api_ext_foundation_finance_")
    reset_foundation_service()
    reset_persistence_service()
    reset_backup_service()
    reset_billing_integration()
    try:
        yield test_data_dir
    finally:
        reset_foundation_service()
        reset_persistence_service()
        reset_backup_service()
        reset_billing_integration()
        if os.path.exists(test_data_dir):
            shutil.rmtree(test_data_dir)


def _bootstrap_foundation(data_dir: str) -> str:
    service = get_foundation_service(
        enable_persistence=True,
        enable_backup=False,
        enable_billing_integration=False,
        data_dir=data_dir,
    )
    result = service.create_foundation(FoundationCreateRequest(
        name="API Finance Foundation",
        foundation_type="friends",
        founder_id="CUST-API-FOUNDER",
    ))
    assert result.success
    fund_id = service.get_foundation_funds(result.foundation_id)[0]["id"]
    contribution = service.make_contribution(
        foundation_id=result.foundation_id,
        fund_id=fund_id,
        member_id="CUST-API-FOUNDER",
        amount=600.0,
        notes="Bootstrap for API tests",
    )
    assert contribution.get("success")
    return result.foundation_id


def test_dispatch_foundation_finance_routes(_reset_services):
    data_dir = _reset_services
    foundation_id = _bootstrap_foundation(data_dir)
    founder_session = {"customer_id": "CUST-API-FOUNDER", "role": "customer"}

    status, payload = dispatch_post(
        path=f"/api/foundations/{foundation_id}/assets",
        session=founder_session,
        body_data={
            "asset_symbol": "BOND-1",
            "asset_name": "Treasury Bond",
            "asset_type": "bond",
            "transaction_type": "buy",
            "amount": 120.0,
            "quantity": 1.0,
            "unit_price": 120.0,
        },
        client_ip="127.0.0.1",
        user_agent="pytest",
    )
    assert status == 200, payload
    assert payload.get("success") is True

    status, sheet = dispatch_get(
        path=f"/api/foundations/{foundation_id}/balance-sheet",
        session=founder_session,
        query_params={},
        client_ip="127.0.0.1",
    )
    assert status == 200, sheet
    assert sheet.get("success") is True
    assert sheet["assets"]["cash"] == pytest.approx(480.0)
    assert sheet["assets"]["investments"] == pytest.approx(120.0)


def test_dispatch_seed_sync_route(_reset_services):
    data_dir = _reset_services
    _bootstrap_foundation(data_dir)
    admin_session = {"username": "admin", "role": "admin"}
    custom_seed_path = os.path.join(data_dir, "seed_snapshot.json")

    status, payload = dispatch_post(
        path="/api/foundations/seeds/sync",
        session=admin_session,
        body_data={"seed_path": custom_seed_path, "auto_correct_integrity": True},
        client_ip="127.0.0.1",
        user_agent="pytest",
    )
    assert status == 200, payload
    assert payload.get("success") is True
    assert payload.get("seed_path") == custom_seed_path
    assert os.path.exists(custom_seed_path)
