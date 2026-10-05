"""Customer NFT ledger: seal, cash totals, and pipeline affiliation.

The dashboard book must verify, count each external cash movement once, and
refuse to replay a deposit into a balance.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from services.nft_ledger import (
    amount_number,
    cash_direction,
    collect_integrity_issues,
    mint_token,
    present_customer_ledger,
    verify_token,
)
from services.supply_chain_ecosystem_service import (
    SupplierStatus,
    SupplyChainEcosystemService,
)


def _mint(ledger, owner, tx_type, amount, tx_id, **kwargs):
    return mint_token(
        ledger,
        owner_id=owner,
        transaction_type=tx_type,
        transaction_id=tx_id,
        amount=amount,
        description=kwargs.pop("description", tx_type),
        **kwargs,
    )


def test_mint_verifies_and_tamper_breaks_the_seal():
    ledger = {}
    token = _mint(ledger, "CUST-1", "wallet_deposit", 10, "TX-1")
    assert verify_token(token)["valid"] is True
    assert token["integrity_version"] == 2
    assert token["block_number"] >= 1_000_000

    token["amount"] = 10.01
    assert verify_token(token)["reason"] == "hash_mismatch"

    restored = ledger[token["token_id"]]
    restored["amount"] = 10.0
    restored["verification_hash"] = token["verification_hash"]
    # The stored row was mutated in place; remint a clean pair for the chain.
    ledger.clear()
    first = _mint(ledger, "CUST-1", "wallet_deposit", "10", "TX-A")
    second = _mint(ledger, "CUST-1", "premium_payment", 10.0, "TX-B")
    assert verify_token(first)["valid"] is True
    assert verify_token(second)["valid"] is True
    assert second["previous_hash"] == first["verification_hash"]
    assert amount_number("10") == amount_number(10.0) == 10.0


def test_legacy_unsealed_token_is_invalid_and_does_not_raise():
    legacy = {
        "token_id": "NFT-OLD",
        "owner_id": "CUST-1",
        "transaction_type": "wallet_deposit",
        "amount": 25.0,
        "description": "historical",
        "created_at": "2024-01-01T00:00:00",
    }
    check = verify_token(legacy)
    assert check["valid"] is False
    assert check["reason"] == "unsealed"

    view = present_customer_ledger([legacy])
    row = view["ledger"][0]
    assert row["transaction_type"] == "wallet_deposit"
    assert row["amount"] == 25.0
    assert row["transaction_hash"] == ""
    assert view["summary"]["total_inflows"] == 25.0


def test_cash_totals_count_external_money_once():
    ledger = {}
    owner = "CUST-CASH"
    _mint(ledger, owner, "wallet_deposit", 100, "TX-DEP", metadata={"payment_method": "card"})
    _mint(ledger, owner, "premium_payment", 80, "TX-PREM", metadata={"source": "card"})
    _mint(
        ledger, owner, "pipeline_deposit", 40, "TX-PIPE",
        metadata={"source": "premium_payment"},
    )
    _mint(
        ledger, owner, "marketplace_order", 30, "TX-ORD",
        metadata={"order_id": "ORD-1"},
    )
    _mint(
        ledger, owner, "medical_purchase", 30, "TX-PUR",
        metadata={"order_id": "ORD-1"},
    )
    _mint(
        ledger, owner, "supply_chain_order", 30, "ORD-1",
        metadata={"order_id": "ORD-1", "cash_event": False, "origin": "supply_chain"},
    )
    _mint(
        ledger, owner, "wallet_deposit", 1000000, "TX-FAKE",
        metadata={"origin": "customer_action", "cash_event": False},
    )
    _mint(ledger, owner, "claim_payment_received", 20, "TX-CLM")
    _mint(ledger, owner, "password_change", 0, "TX-PWD", metadata={"cash_event": False})
    _mint(ledger, "OTHER", "wallet_deposit", 999, "TX-OTHER")

    view = present_customer_ledger(
        [token for token in ledger.values() if token["owner_id"] == owner]
    )
    summary = view["summary"]
    # In: 100 deposit + 20 claim. Out: 80 premium + 30 purchase.
    # Pipeline sweep, duplicate order, logged deposit, and password are records.
    assert summary["total_inflows"] == 120.0
    assert summary["total_outflows"] == 110.0
    assert summary["net_flow"] == 10.0
    assert summary["total_deposits"] == 100.0
    assert summary["total_purchases"] == 30.0
    assert summary["chain_valid"] is True
    assert summary["invalid_tokens"] == 0

    directions = {row["transaction_type"]: row["direction"] for row in view["ledger"]}
    assert directions["pipeline_deposit"] == "neutral"
    assert directions["marketplace_order"] == "neutral"
    assert directions["supply_chain_order"] == "neutral"
    assert directions["medical_purchase"] == "out"
    assert directions["claim_payment_received"] == "in"


def test_direct_pipeline_deposit_is_money_in():
    token = {
        "transaction_type": "pipeline_deposit",
        "amount": 50,
        "metadata": {"source": "direct_deposit"},
    }
    assert cash_direction(token) == "in"
    internal = {
        "transaction_type": "pipeline_deposit",
        "amount": 50,
        "metadata": {"source": "phinsafe_rider"},
    }
    assert cash_direction(internal) == "neutral"


def test_affiliate_detects_amount_and_owner_drift():
    ledger = {}
    token = _mint(ledger, "CUST-1", "premium_payment", 40, "TX-9")
    transactions = {
        "TX-9": {
            "id": "TX-9",
            "customer_id": "CUST-1",
            "type": "premium_payment",
            "amount": 40,
            "nft_token_id": token["token_id"],
        }
    }
    assert collect_integrity_issues(ledger, transactions) == []

    transactions["TX-9"]["amount"] = 41
    issues = collect_integrity_issues(ledger, transactions)
    assert any("amount" in item["issue"] for item in issues)

    transactions["TX-9"]["amount"] = 40
    transactions["TX-MISSING"] = {
        "id": "TX-MISSING",
        "customer_id": "CUST-1",
        "type": "wallet_deposit",
        "amount": 5,
        "nft_token_id": "NFT-GONE",
        "metadata": {},
    }
    issues = collect_integrity_issues(ledger, transactions)
    assert any("NFT-GONE" in item["issue"] for item in issues)


def test_supply_chain_order_seal_verifies_and_is_not_cash():
    service = SupplyChainEcosystemService(
        suppliers_store={
            "SUP-1": {"id": "SUP-1", "status": SupplierStatus.APPROVED.value, "name": "Clinic"},
        },
        offers_store={
            "OFF-1": {
                "id": "OFF-1",
                "supplier_id": "SUP-1",
                "name": "Visit",
                "price": 40,
                "active": True,
                "category": "consultation",
            },
        },
        health_wallets={"CUST-1": {"balance": 0, "transactions": []}},
        nft_ledger={},
    )
    recorded = []

    def _record(**kwargs):
        recorded.append(kwargs)
        return {"id": "TX-MKT", "nft_token_id": "NFT-FROM-LEDGER"}

    service.record_transaction = _record
    result = service.create_order("CUST-1", "SUP-1", "OFF-1", {"payment_method": "credit_card", "quantity": 1})
    assert result["success"] is True
    order = result["order"]
    token = service.nft_ledger[order["nft_token_id"]]
    assert verify_token(token)["valid"] is True
    assert token["transaction_type"] == "supply_chain_order"
    assert token["asset_id"] == order["id"]
    assert token["metadata"]["cash_event"] is False
    assert recorded and recorded[0]["tx_type"] == "marketplace_order"
    # Platform book seals are not the customer's cash row.
    platform_tokens = [row for row in service.nft_ledger.values() if row.get("owner_id") == "PHINS_PLATFORM"]
    assert platform_tokens
    assert all(verify_token(row)["valid"] for row in platform_tokens)


def _base_url() -> str:
    return os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _request(path: str, token: str | None = None, method: str = "GET", payload: dict | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None if payload is None else json.dumps(payload).encode()
    req = Request(_base_url() + path, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15) as resp:
            body = resp.read().decode()
            return resp.status, json.loads(body) if body else {}
    except HTTPError as exc:
        raw = exc.read().decode()
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"error": raw}
        return exc.code, parsed


@pytest.fixture
def nft_customer(monkeypatch):
    import web_portal.server as portal

    customer_id = "CUST-NFT-LEDGER"
    token = "phins_nft_ledger_token"
    port = int(os.environ.get("TEST_PORT", "0") or 0)
    if port:
        portal._TEST_PORTS_INITIALIZED.add(port)
    portal.SESSIONS[token] = {
        "username": "nft_ledger_customer",
        "role": "customer",
        "customer_id": customer_id,
        "expires": (datetime.now() + timedelta(hours=2)).isoformat(),
    }
    portal.CUSTOMERS[customer_id] = {"id": customer_id, "name": "NFT Ledger Customer", "status": "active"}
    yield portal, customer_id, token
    portal.SESSIONS.pop(token, None)
    for token_id, row in list(portal.NFT_LEDGER.items()):
        if isinstance(row, dict) and (row.get("owner_id") or row.get("customer_id")) == customer_id:
            portal.NFT_LEDGER.pop(token_id, None)
    for tx_id, row in list(portal.TRANSACTION_LEDGER.items()):
        if isinstance(row, dict) and row.get("customer_id") == customer_id:
            portal.TRANSACTION_LEDGER.pop(tx_id, None)


def test_record_transaction_is_visible_and_verifiable(nft_customer):
    portal, customer_id, token = nft_customer
    tx = portal.record_transaction(
        customer_id=customer_id,
        tx_type="wallet_deposit",
        amount=42.5,
        description="Card deposit",
        metadata={"payment_method": "card"},
    )
    assert tx.get("nft_token_id")
    stored = portal.NFT_LEDGER[tx["nft_token_id"]]
    assert verify_token(stored)["valid"] is True
    assert stored.get("ledger_entry_hash") == tx.get("entry_hash")

    status, body = _request(f"/api/nft-ledger?customer_id={customer_id}", token=token)
    assert status == 200, body
    assert body["summary"]["total_inflows"] == 42.5
    assert body["summary"]["chain_valid"] is True
    row = next(item for item in body["ledger"] if item["token_id"] == tx["nft_token_id"])
    assert row["direction"] == "in"
    assert row["counts_as_cash"] is True
    assert row["integrity"]["valid"] is True

    status, verified = _request(
        f"/api/nft-ledger/verify?token_id={tx['nft_token_id']}",
        token=token,
    )
    assert status == 200
    assert verified["valid"] is True
    assert verified["ledger_linked"] is True

    status, denied = _request(f"/api/nft-ledger/verify?token_id={tx['nft_token_id']}")
    assert status == 401
    assert "token" not in denied


def test_customer_action_does_not_inflate_cash_or_balances(nft_customer):
    portal, customer_id, token = nft_customer
    portal.HEALTH_WALLETS[customer_id] = {"customer_id": customer_id, "balance": 15, "transactions": []}
    status, body = _request(
        "/api/customer/action",
        token=token,
        method="POST",
        payload={
            "customer_id": customer_id,
            "action_type": "wallet_deposit",
            "amount": 5000,
            "description": "logged only",
        },
    )
    assert status == 200, body
    assert body.get("nft_token")
    assert body.get("counts_as_cash") is False
    assert portal.HEALTH_WALLETS[customer_id]["balance"] == 15

    status, ledger = _request(f"/api/nft-ledger?customer_id={customer_id}", token=token)
    assert status == 200
    assert ledger["summary"]["total_inflows"] == 0
    assert ledger["summary"]["total_deposits"] == 0
    logged = next(item for item in ledger["ledger"] if item["transaction_type"] == "wallet_deposit")
    assert logged["direction"] == "neutral"
    assert logged["integrity"]["valid"] is True


def test_reactivate_does_not_credit_balances(nft_customer):
    portal, customer_id, token = nft_customer
    tx = portal.record_transaction(
        customer_id=customer_id,
        tx_type="wallet_deposit",
        amount=75,
        description="Already applied deposit",
        metadata={"payment_method": "card"},
    )
    block = portal.NFT_LEDGER[tx["nft_token_id"]]["block_number"]
    if portal.unified_balance_service is not None:
        portal.unified_balance_service.algo_trading_balances[customer_id] = {
            "available": 10, "in_positions": 0, "total_pnl": 0,
        }

    status, denied = _request(
        f"/api/nft-ledger/reactivate?block={block}&customer_id={customer_id}",
        token=token,
    )
    assert status == 403

    admin = "phins_nft_ledger_admin"
    portal.SESSIONS[admin] = {
        "username": "nft_ledger_admin",
        "role": "admin",
        "expires": (datetime.now() + timedelta(hours=2)).isoformat(),
    }
    try:
        status, body = _request(
            f"/api/nft-ledger/reactivate?block={block}&customer_id={customer_id}",
            token=admin,
        )
        assert status == 200, body
        assert body["balance_adjusted"] is False
        assert body["valid"] is True
        assert body["ledger_linked"] is True
        if portal.unified_balance_service is not None:
            assert portal.unified_balance_service.algo_trading_balances[customer_id]["available"] == 10
    finally:
        portal.SESSIONS.pop(admin, None)
