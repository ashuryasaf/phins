"""Customer NFT transaction ledger.

The customer dashboard ("My Transaction Ledger (NFT)") is the per-customer
seal over PHINS-CHAIN. Every cash-moving pipeline event is minted here by
``record_transaction``; this module owns the seal, the per-owner hash chain,
and the cash classification the dashboard totals use.

Integrity rules:

- A version-2 token's verification hash covers the owner, type, linked
  transaction id, canonical amount, description, timestamp, block number,
  previous owner-chain hash, and metadata. Changing any of those fails
  verification. Operational annotations (status, ledger sequence) sit outside
  the seal so a later status note cannot break it.
- Legacy tokens that already carry a verification hash keep the original
  four-field hash. Tokens with no hash are reported as unsealed; they are
  not treated as valid.
- Money-in and money-out totals count external cash once. Internal moves
  (premium savings swept into the pipeline, a marketplace order that already
  has a medical-purchase receipt, customer-logged actions) stay on the
  ledger as records and do not change the net.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import threading
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Tuple

INTEGRITY_VERSION = 2
CHAIN_TYPE = "PHINS-CHAIN"
GENESIS_BLOCK = 1_000_000

# External cash received by the customer.
INFLOW_TYPES = frozenset({
    "wallet_deposit",
    "claim_payment_received",
    "premium_refund",
    "refund",
    "investment_deposit",
    "algo_trading_profit",
    "algo_profit_activated",
    "credit_refund",
})

# External cash paid by the customer.
OUTFLOW_TYPES = frozenset({
    "medical_purchase",
    "health_wallet_purchase",
    "premium_payment",
    "bill_payment",
    "bulk_premium_payment",
    "credit_withdrawal",
    "supplier_payment",
})

# Pipeline deposits that only relocate premium already recorded as cash out.
PIPELINE_EXTERNAL_SOURCES = frozenset({
    "direct_deposit",
    "external",
    "card",
    "bank_transfer",
    "wallet_deposit",
})

# Owners that are platform books, not a customer dashboard.
PLATFORM_OWNERS = frozenset({
    "PHINS-CORPORATE",
    "PHINS_PLATFORM",
    "SYSTEM",
})

_MINT_LOCK = threading.Lock()


def canonical_amount(value: Any) -> str:
    """Stable two-decimal amount string. ``10``, ``10.0`` and ``10.00`` match."""
    try:
        number = round(float(value), 2)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number:.2f}"


def amount_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if number != number or number in (float("inf"), float("-inf")):
        return 0.0
    return round(number, 2)


def canonical_metadata(metadata: Any) -> Dict[str, Any]:
    """Deep snapshot so a later mutation of the caller's dict cannot move the seal."""
    if not isinstance(metadata, dict):
        return {}
    try:
        return json.loads(json.dumps(metadata, sort_keys=True, default=str))
    except (TypeError, ValueError):
        return {}


def _sealed_body(token: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "v": INTEGRITY_VERSION,
        "token_id": str(token.get("token_id") or ""),
        "owner_id": str(token.get("owner_id") or ""),
        "transaction_type": str(token.get("transaction_type") or ""),
        "transaction_id": str(token.get("transaction_id") or ""),
        "amount": canonical_amount(token.get("amount")),
        "description": str(token.get("description") or ""),
        "created_at": str(token.get("created_at") or ""),
        "block_number": int(token.get("block_number") or 0),
        "previous_hash": str(token.get("previous_hash") or ""),
        "metadata": canonical_metadata(token.get("metadata")),
    }


def _seal_digest(token: Mapping[str, Any], domain: str) -> str:
    raw = domain + json.dumps(_sealed_body(token), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verification_hash(token: Mapping[str, Any]) -> str:
    return _seal_digest(token, "nft|")


def transaction_hash(token: Mapping[str, Any]) -> str:
    return _seal_digest(token, "tx|")


def legacy_verification_hash(token: Mapping[str, Any]) -> str:
    """Original four-field hash. Amount is used as stored so historical seals still match."""
    owner = token.get("owner_id") or token.get("customer_id") or ""
    payload = {
        "token_id": token.get("token_id"),
        "customer_id": owner,
        "transaction_type": token.get("transaction_type"),
        "amount": token.get("amount"),
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha3_256(raw.encode("utf-8")).hexdigest()[:32]


def verify_token(token: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Check a token's seal. Does not raise on legacy or partial rows."""
    if not isinstance(token, dict) or not token.get("token_id"):
        return {"valid": False, "reason": "missing", "version": None}

    stored = str(token.get("verification_hash") or "")
    version = token.get("integrity_version")
    if version == INTEGRITY_VERSION:
        expected = verification_hash(token)
        tx_expected = transaction_hash(token)
        hash_ok = stored == expected and str(token.get("transaction_hash") or "") == tx_expected
        return {
            "valid": hash_ok,
            "reason": "ok" if hash_ok else "hash_mismatch",
            "version": INTEGRITY_VERSION,
            "computed_hash": expected,
            "stored_hash": stored,
        }

    if not stored:
        return {"valid": False, "reason": "unsealed", "version": 1, "computed_hash": "", "stored_hash": ""}

    expected = legacy_verification_hash(token)
    hash_ok = stored == expected
    return {
        "valid": hash_ok,
        "reason": "legacy" if hash_ok else "hash_mismatch",
        "version": 1,
        "computed_hash": expected,
        "stored_hash": stored,
    }


def _owner_of(token: Mapping[str, Any]) -> str:
    return str(token.get("owner_id") or token.get("customer_id") or "")


def _block_of(token: Mapping[str, Any]) -> int:
    try:
        return int(token.get("block_number") or 0)
    except (TypeError, ValueError):
        return 0


def _allocate_block_and_previous(ledger: Mapping[str, Any], owner_id: str) -> Tuple[int, str]:
    highest = GENESIS_BLOCK - 1
    used = set()
    previous = ""
    previous_block = -1
    for token in list(ledger.values()):
        if not isinstance(token, dict):
            continue
        block = _block_of(token)
        if block:
            used.add(block)
            if block > highest:
                highest = block
        if (
            token.get("integrity_version") == INTEGRITY_VERSION
            and _owner_of(token) == owner_id
            and block >= previous_block
        ):
            previous_block = block
            previous = str(token.get("verification_hash") or "")
    block_number = max(highest + 1, GENESIS_BLOCK)
    while block_number in used:
        block_number += 1
    return block_number, previous


def _new_token_id(ledger: Mapping[str, Any], explicit: Optional[str]) -> str:
    if explicit:
        if explicit in ledger:
            raise ValueError(f"NFT token id already exists: {explicit}")
        return explicit
    while True:
        token_id = (
            f"NFT-{datetime.now().strftime('%Y%m%d%H%M%S')}-"
            f"{secrets.token_hex(4).upper()}"
        )
        if token_id not in ledger:
            return token_id


def mint_token(
    ledger: MutableMapping[str, Dict[str, Any]],
    *,
    owner_id: str,
    transaction_type: str,
    transaction_id: str,
    amount: Any,
    description: str,
    metadata: Optional[Dict[str, Any]] = None,
    token_id: Optional[str] = None,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Mint a version-2 token into ``ledger`` and return the stored row.

    The stored metadata is a snapshot. Callers may keep mutating the dict they
    passed in; the seal does not follow those writes.
    """
    owner_id = str(owner_id or "").strip()
    if not owner_id:
        raise ValueError("owner_id is required")
    transaction_type = str(transaction_type or "").strip() or "record"
    with _MINT_LOCK:
        assigned_id = _new_token_id(ledger, token_id)
        block_number, previous_hash = _allocate_block_and_previous(ledger, owner_id)
        token: Dict[str, Any] = {
            "token_id": assigned_id,
            "chain_type": CHAIN_TYPE,
            "owner_id": owner_id,
            "owner_type": "platform" if owner_id in PLATFORM_OWNERS else "customer",
            "transaction_type": transaction_type,
            "transaction_id": str(transaction_id or ""),
            "amount": amount_number(amount),
            "description": str(description or ""),
            "metadata": canonical_metadata(metadata),
            "created_at": created_at or datetime.now().isoformat(),
            "status": "confirmed",
            "block_number": block_number,
            "previous_hash": previous_hash,
            "gas_fee": 0.0,
            "integrity_version": INTEGRITY_VERSION,
            "smart_contract_ref": f"PHINS-SC-{datetime.now().strftime('%Y%m')}-LEDGER",
        }
        token["verification_hash"] = verification_hash(token)
        token["transaction_hash"] = transaction_hash(token)
        ledger[assigned_id] = token
        return token


def _purchase_order_ids(tokens: Iterable[Mapping[str, Any]]) -> set:
    order_ids = set()
    for token in tokens:
        if str(token.get("transaction_type") or "") != "medical_purchase":
            continue
        metadata = token.get("metadata") if isinstance(token.get("metadata"), dict) else {}
        order_id = str(metadata.get("order_id") or "").strip()
        if order_id:
            order_ids.add(order_id)
    return order_ids


def cash_direction(token: Mapping[str, Any], purchase_order_ids: Optional[set] = None) -> str:
    """``in``, ``out``, or ``neutral``.

    Neutral rows stay on the customer's ledger (they are real events) and are
    excluded from money-in / money-out so the same cash is not counted twice.
    """
    metadata = token.get("metadata") if isinstance(token.get("metadata"), dict) else {}
    if metadata.get("cash_event") is False or metadata.get("origin") == "customer_action":
        return "neutral"
    if metadata.get("internal") is True:
        return "neutral"

    tx_type = str(token.get("transaction_type") or "")
    if tx_type == "marketplace_order":
        order_id = str(metadata.get("order_id") or "").strip()
        if order_id and purchase_order_ids and order_id in purchase_order_ids:
            return "neutral"
        return "out"
    if tx_type == "pipeline_deposit":
        source = str(metadata.get("source") or "").strip().lower()
        if source in PIPELINE_EXTERNAL_SOURCES:
            return "in"
        return "neutral"
    if tx_type in INFLOW_TYPES:
        return "in"
    if tx_type in OUTFLOW_TYPES:
        return "out"
    return "neutral"


def chain_status(tokens: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Per-owner version-2 chain. Legacy rows are ignored and do not break the link."""
    versioned = [
        token for token in tokens
        if isinstance(token, dict) and token.get("integrity_version") == INTEGRITY_VERSION
    ]
    versioned.sort(key=lambda token: (_block_of(token), str(token.get("created_at") or ""), str(token.get("token_id") or "")))
    previous = ""
    broken: List[str] = []
    for token in versioned:
        token_id = str(token.get("token_id") or "")
        if str(token.get("previous_hash") or "") != previous:
            broken.append(token_id)
        elif not verify_token(token)["valid"]:
            broken.append(token_id)
        previous = str(token.get("verification_hash") or "")
    return {
        "valid": not broken,
        "checked": len(versioned),
        "broken_token_ids": broken,
    }


def _display_amount(token: Mapping[str, Any]) -> float:
    if token.get("amount") not in (None, ""):
        return amount_number(token.get("amount"))
    metadata = token.get("metadata") if isinstance(token.get("metadata"), dict) else {}
    if metadata.get("total_amount") not in (None, ""):
        return amount_number(metadata.get("total_amount"))
    return 0.0


def present_token(token: Mapping[str, Any], direction: str) -> Dict[str, Any]:
    """JSON row for the customer dashboard. Missing legacy fields are filled, not invented as valid."""
    metadata = token.get("metadata") if isinstance(token.get("metadata"), dict) else {}
    integrity = verify_token(token)
    return {
        "token_id": str(token.get("token_id") or ""),
        "chain_type": token.get("chain_type") or CHAIN_TYPE,
        "transaction_hash": str(token.get("transaction_hash") or ""),
        "verification_hash": str(token.get("verification_hash") or ""),
        "owner_id": _owner_of(token),
        "transaction_type": str(token.get("transaction_type") or token.get("asset_type") or "record"),
        "transaction_id": str(token.get("transaction_id") or token.get("asset_id") or ""),
        "amount": _display_amount(token),
        "description": str(token.get("description") or token.get("asset_id") or ""),
        "metadata": metadata,
        "created_at": str(token.get("created_at") or token.get("timestamp") or ""),
        "status": token.get("status") or ("confirmed" if integrity["valid"] else "unsealed"),
        "block_number": token.get("block_number") if token.get("block_number") not in (None, "") else "",
        "previous_hash": str(token.get("previous_hash") or ""),
        "integrity_version": token.get("integrity_version") or (INTEGRITY_VERSION if integrity["version"] == INTEGRITY_VERSION else 1),
        "direction": direction,
        "counts_as_cash": direction in ("in", "out"),
        "integrity": {
            "valid": integrity["valid"],
            "reason": integrity["reason"],
            "version": integrity["version"],
        },
        "asset_type": token.get("asset_type"),
        "asset_id": token.get("asset_id"),
    }


def present_customer_ledger(tokens: Iterable[Mapping[str, Any]], *, limit: int = 200) -> Dict[str, Any]:
    """Summary over the full book, plus the newest rows for the table."""
    rows_in = [token for token in tokens if isinstance(token, dict)]
    order_ids = _purchase_order_ids(rows_in)
    directions = [cash_direction(token, order_ids) for token in rows_in]

    inflows = 0.0
    outflows = 0.0
    deposits = 0.0
    purchases = 0.0
    by_type: Dict[str, int] = {}
    invalid = 0
    for token, direction in zip(rows_in, directions):
        tx_type = str(token.get("transaction_type") or token.get("asset_type") or "record")
        by_type[tx_type] = by_type.get(tx_type, 0) + 1
        signed = _display_amount(token)
        if direction == "in":
            inflows += signed
        elif direction == "out":
            outflows += abs(signed)
        if tx_type == "wallet_deposit" and direction == "in":
            deposits += abs(signed)
        if tx_type == "medical_purchase" and direction == "out":
            purchases += abs(signed)
        if not verify_token(token)["valid"]:
            invalid += 1

    presented = [
        present_token(token, direction)
        for token, direction in zip(rows_in, directions)
    ]
    presented.sort(key=lambda row: (str(row.get("created_at") or ""), str(row.get("token_id") or "")), reverse=True)
    shown = presented[: max(0, int(limit))]
    chain = chain_status(rows_in)
    return {
        "ledger": shown,
        "summary": {
            "total_tokens": len(rows_in),
            "returned": len(shown),
            "truncated": len(rows_in) > len(shown),
            "total_inflows": round(inflows, 2),
            "total_outflows": round(outflows, 2),
            "net_flow": round(inflows - outflows, 2),
            # Kept for existing clients. These are the cash deposits and
            # medical purchases, not the full in/out book.
            "total_deposits": round(deposits, 2),
            "total_purchases": round(purchases, 2),
            "by_type": by_type,
            "invalid_tokens": invalid,
            "chain_valid": chain["valid"],
        },
        "chain": chain,
    }


def affiliate_issues(token: Mapping[str, Any], transaction: Optional[Mapping[str, Any]]) -> List[str]:
    """Differences between a customer NFT and the platform transaction it seals."""
    issues: List[str] = []
    if not isinstance(token, dict):
        return ["nft is not an object"]
    token_id = str(token.get("token_id") or "")
    if transaction is None:
        issues.append(f"{token_id} has no platform transaction {token.get('transaction_id')}")
        return issues
    tx_id = str(transaction.get("id") or transaction.get("tx_id") or "")
    linked = str(token.get("transaction_id") or "")
    if linked and tx_id and linked != tx_id:
        issues.append(f"{token_id} transaction_id {linked} != ledger id {tx_id}")
    owner = _owner_of(token)
    customer_id = str(transaction.get("customer_id") or "")
    if owner and customer_id and owner != customer_id:
        issues.append(f"{token_id} owner {owner} != transaction customer {customer_id}")
    if abs(amount_number(token.get("amount")) - amount_number(transaction.get("amount"))) > 0.01:
        issues.append(f"{token_id} amount does not match the platform transaction")
    tx_type = str(transaction.get("type") or transaction.get("event_type") or "")
    if tx_type and str(token.get("transaction_type") or "") not in ("", tx_type):
        issues.append(f"{token_id} type does not match the platform transaction")
    nft_on_tx = str(transaction.get("nft_token_id") or "")
    if not nft_on_tx:
        metadata = transaction.get("metadata") if isinstance(transaction.get("metadata"), dict) else {}
        nft_on_tx = str(metadata.get("nft_token_id") or "")
    if nft_on_tx and token_id and nft_on_tx != token_id:
        issues.append(f"{token_id} is not the nft_token_id stored on {tx_id}")
    check = verify_token(token)
    if not check["valid"]:
        issues.append(f"{token_id} seal {check['reason']}")
    return issues


def collect_integrity_issues(
    nft_ledger: Mapping[str, Any],
    transaction_ledger: Mapping[str, Any],
) -> List[Dict[str, str]]:
    """Cross-check customer seals against the platform transaction ledger."""
    issues: List[Dict[str, str]] = []
    transactions = transaction_ledger if isinstance(transaction_ledger, Mapping) else {}
    tokens = nft_ledger if isinstance(nft_ledger, Mapping) else {}

    for tx_id, entry in list(transactions.items()):
        if not isinstance(entry, dict):
            continue
        metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
        nft_ref = str(entry.get("nft_token_id") or metadata.get("nft_token_id") or "")
        if not nft_ref:
            continue
        token = tokens.get(nft_ref)
        if not isinstance(token, dict):
            issues.append({"tx_id": str(tx_id), "issue": f"Missing NFT token reference: {nft_ref}"})
            continue
        for message in affiliate_issues(token, entry):
            issues.append({"tx_id": str(tx_id), "issue": message})

    for token_id, token in list(tokens.items()):
        if not isinstance(token, dict):
            continue
        owner = _owner_of(token)
        if owner in PLATFORM_OWNERS or not owner:
            continue
        check = verify_token(token)
        if not check["valid"]:
            issues.append({"token_id": str(token_id), "issue": f"NFT seal {check['reason']}"})
            continue
        if token.get("integrity_version") != INTEGRITY_VERSION:
            continue
        linked = str(token.get("transaction_id") or "")
        # record_transaction seals use TX- ids. Order and asset ids are
        # affiliated on the supply-chain row and must not be reported as
        # missing platform transactions.
        if linked.startswith("TX-") and linked not in transactions:
            issues.append({
                "token_id": str(token_id),
                "issue": f"Customer NFT is not linked to platform transaction {linked}",
            })
    return issues
