import copy

import web_portal.server as portal


def test_build_customer_nft_ledger_view_joins_transactions_and_nfts():
    original_transactions = copy.deepcopy(portal.TRANSACTION_LEDGER)
    original_nfts = copy.deepcopy(portal.NFT_LEDGER)
    try:
        portal.TRANSACTION_LEDGER.clear()
        portal.NFT_LEDGER.clear()

        portal.TRANSACTION_LEDGER["TX-100"] = {
            "id": "TX-100",
            "customer_id": "CUST-100",
            "type": "wallet_deposit",
            "amount": 125.0,
            "description": "Wallet funded",
            "timestamp": "2026-03-20T10:00:00",
            "status": "completed",
            "nft_token_id": "NFT-100",
        }
        portal.NFT_LEDGER["NFT-100"] = {
            "token_id": "NFT-100",
            "owner_id": "CUST-100",
            "transaction_type": "wallet_deposit",
            "transaction_id": "TX-100",
            "amount": 125.0,
            "description": "Wallet funded",
            "created_at": "2026-03-20T10:00:01",
            "status": "confirmed",
            "transaction_hash": "abc12345hash",
            "verification_hash": "verify123",
            "block_number": 1001,
        }
        portal.TRANSACTION_LEDGER["TX-200"] = {
            "id": "TX-200",
            "customer_id": "CUST-100",
            "type": "policy_activated",
            "amount": 0.0,
            "description": "Policy activated",
            "timestamp": "2026-03-20T11:00:00",
            "status": "completed",
        }

        view = portal.build_customer_nft_ledger_view("CUST-100")

        assert view["summary"]["total_transactions"] == 2
        assert view["summary"]["total_tokens"] == 1
        assert view["summary"]["activated_tokens"] == 1
        assert view["summary"]["pending_tokens"] == 1

        entries = view["ledger"]
        assert entries[0]["ledger_tx_id"] == "TX-200"
        assert entries[0]["has_nft"] is False
        assert entries[0]["status"] == "transaction_only"
        assert entries[1]["token_id"] == "NFT-100"
        assert entries[1]["activated"] is True
        assert entries[1]["signed_amount"] == 125.0
    finally:
        portal.TRANSACTION_LEDGER.clear()
        portal.TRANSACTION_LEDGER.update(original_transactions)
        portal.NFT_LEDGER.clear()
        portal.NFT_LEDGER.update(original_nfts)


def test_build_customer_nft_ledger_view_treats_reactivated_token_as_active():
    original_transactions = copy.deepcopy(portal.TRANSACTION_LEDGER)
    original_nfts = copy.deepcopy(portal.NFT_LEDGER)
    try:
        portal.TRANSACTION_LEDGER.clear()
        portal.NFT_LEDGER.clear()

        portal.NFT_LEDGER["NFT-REACT"] = {
            "token_id": "NFT-REACT",
            "owner_id": "CUST-200",
            "transaction_type": "investment_deposit",
            "transaction_id": "TX-REACT",
            "amount": 250.0,
            "description": "Investment transfer",
            "created_at": "2026-03-20T12:00:00",
            "status": "reactivated",
            "transaction_hash": "hashreact",
            "verification_hash": "verifyreact",
            "block_number": 2001,
        }

        view = portal.build_customer_nft_ledger_view("CUST-200")

        assert view["summary"]["total_tokens"] == 1
        assert view["summary"]["activated_tokens"] == 1
        assert view["ledger"][0]["activated"] is True
        assert view["ledger"][0]["source"] == "nft_only"
    finally:
        portal.TRANSACTION_LEDGER.clear()
        portal.TRANSACTION_LEDGER.update(original_transactions)
        portal.NFT_LEDGER.clear()
        portal.NFT_LEDGER.update(original_nfts)
