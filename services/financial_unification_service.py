"""Canonical financial-book unification for PHINS.

Authority (do not invert):

1. Actuarial kernel pricing is the premium *identity* (what should be billed).
2. The customer ledger (``TRANSACTION_LEDGER``) is the cash *identity* for
   premium collections and claim payouts.
3. The accounting book, company balance sheet, and reserves reports must
   equal those cash totals. They never invent amounts.

This module is fail-open: posting helpers never raise into payment flows.
"""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger("phins.financial_unification")

# Customer-ledger cash types. Premium collections and claim payouts both
# land on the customer ledger; aliases exist because older writers used
# different strings for the same economic event.
PREMIUM_CASH_TYPES = frozenset({
    "premium_payment",
    "bill_payment",
    "bill_paid",
    "premium_received",
    "premium_deposit",
    "bulk_premium_payment",
})

# Companion audit rows written *after* process_customer_premium_payment.
# They must not be summed as cash — the premium_payment already is.
PREMIUM_AUDIT_TYPES = frozenset({
    "auto_pay_execution",
})

CLAIM_CASH_TYPES = frozenset({
    "claim_payment_received",  # canonical customer-ledger claim cash
    "claim_payment",
    "claim_paid",
    "claims_paid",
})

CANONICAL_CLAIM_LEDGER_TYPE = "claim_payment_received"
CANONICAL_PREMIUM_LEDGER_TYPE = "premium_payment"

TOLERANCE = Decimal("0.01")


def money(value: Any, default: float = 0.0) -> Decimal:
    """Parse a numeric value to cents-rounded Decimal."""
    if value is None or value == "":
        return Decimal(str(default)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return Decimal(str(default)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def money_float(value: Any, default: float = 0.0) -> float:
    return float(money(value, default))


def _tx_type(tx: Dict[str, Any]) -> str:
    return str(tx.get("type") or tx.get("tx_type") or "").strip().lower()


def _tx_amount(tx: Dict[str, Any]) -> Decimal:
    # Wallet-funded premium rows sometimes store a negative (wallet debit).
    # Cash identity is the magnitude collected or paid.
    return money(tx.get("amount", 0)).copy_abs()


def ledger_cash_total(
    transactions: Iterable[Dict[str, Any]],
    types: Iterable[str],
    *,
    customer_id: Optional[str] = None,
    exclude_customer: Optional[Any] = None,
) -> Dict[str, Any]:
    """Sum customer-ledger cash for the given transaction types.

    ``exclude_customer`` is an optional callable ``(customer_id) -> bool``.
    """
    wanted = {str(t).strip().lower() for t in types}
    total = Decimal("0.00")
    count = 0
    by_type: Dict[str, Decimal] = {}
    by_customer: Dict[str, Decimal] = {}
    for tx in transactions:
        if not isinstance(tx, dict):
            continue
        kind = _tx_type(tx)
        if kind not in wanted:
            continue
        cid = str(tx.get("customer_id") or "")
        if customer_id and cid != customer_id:
            continue
        if exclude_customer and cid and exclude_customer(cid):
            continue
        amount = _tx_amount(tx)
        if amount <= 0:
            continue
        total += amount
        count += 1
        by_type[kind] = by_type.get(kind, Decimal("0.00")) + amount
        if cid:
            by_customer[cid] = by_customer.get(cid, Decimal("0.00")) + amount
    return {
        "total": float(total),
        "count": count,
        "by_type": {k: float(v) for k, v in by_type.items()},
        "by_customer": {k: float(v) for k, v in by_customer.items()},
    }


def sum_paid_claim_records(claims: Iterable[Dict[str, Any]]) -> Decimal:
    """Cash expected from claim *records* that have already been disbursed."""
    total = Decimal("0.00")
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        status = str(claim.get("status") or "").strip().lower().replace(" ", "_")
        if status not in ("paid", "closed"):
            continue
        amount = money(
            claim.get("paid_amount")
            or claim.get("approved_amount")
            or claim.get("amount_approved")
            or 0
        )
        if amount > 0:
            total += amount
    return total


def kernel_components_from_policy(policy: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Read pinned kernel components from a policy or its latest snapshot."""
    policy = policy or {}
    risk = policy.get("risk_premium_annual")
    savings = policy.get("savings_premium_annual")
    annual = policy.get("annual_premium")
    source = "policy"
    integrity_hash = policy.get("integrity_hash")
    product_id = policy.get("product_id")
    pricing_source = policy.get("pricing_source")

    if risk is None or (money(annual) > 0 and money(risk) == 0 and money(savings or 0) == 0):
        try:
            from services.pricing_shadow_service import get_snapshots_for_policy

            snaps = get_snapshots_for_policy(str(policy.get("id") or ""))
            if snaps:
                latest = snaps[-1]
                components = latest.get("components") or {}
                risk = components.get("risk_premium_annual", latest.get("kernel_annual"))
                savings = components.get("savings_premium_annual", 0)
                annual = latest.get("kernel_annual") or annual
                integrity_hash = latest.get("integrity_hash") or integrity_hash
                product_id = latest.get("product_id") or product_id
                source = "premium_snapshot"
                pricing_source = "pricing_kernel"
        except Exception:
            pass

    return {
        "risk_premium_annual": money_float(risk, 0.0),
        "savings_premium_annual": money_float(savings, 0.0),
        "annual_premium": money_float(annual, 0.0),
        "integrity_hash": integrity_hash,
        "product_id": product_id,
        "pricing_source": pricing_source or source,
        "source": source,
    }


def resolve_premium_split(
    amount: Any,
    policy: Optional[Dict[str, Any]] = None,
    fallback_risk_pct: Any = 100,
) -> Dict[str, Any]:
    """Split a collected premium into risk vs savings.

    Prefers the actuarial kernel pin on the policy (or its snapshot). Falls
    back to the caller-supplied portfolio risk percentage only when no kernel
    identity exists.
    """
    collected = money(amount)
    kernel = kernel_components_from_policy(policy)
    risk_ann = money(kernel["risk_premium_annual"])
    sav_ann = money(kernel["savings_premium_annual"])
    annual = money(kernel["annual_premium"])
    if annual > 0 and (risk_ann > 0 or sav_ann > 0):
        risk_pct = (risk_ann / annual * Decimal("100")).quantize(Decimal("0.01"))
        source = f"kernel:{kernel['source']}"
    else:
        try:
            risk_pct = Decimal(str(fallback_risk_pct or 100))
        except Exception:
            risk_pct = Decimal("100")
        if risk_pct < 0:
            risk_pct = Decimal("0")
        if risk_pct > 100:
            risk_pct = Decimal("100")
        source = "allocation_prefs"
    savings_pct = Decimal("100") - risk_pct
    risk_amount = (collected * risk_pct / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    savings_amount = (collected - risk_amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "amount": float(collected),
        "risk_percentage": float(risk_pct),
        "savings_percentage": float(savings_pct),
        "risk_amount": float(risk_amount),
        "savings_amount": float(savings_amount),
        "split_source": source,
        "integrity_hash": kernel.get("integrity_hash"),
        "product_id": kernel.get("product_id"),
        "pricing_source": kernel.get("pricing_source"),
    }


def _allocation_already_posted(engine: Any, bill_id: str, source_tx_id: Optional[str]) -> bool:
    """True when this cash slice is already on the book.

    Key is (bill_id, source_tx_id). The same bill can receive several
    partial payments — each ledger tx must post. Missing source_tx_id
    falls back to bill_id only so a retry without a tx id stays idempotent.
    """
    allocations = getattr(engine, "allocations", {}) or {}
    wanted_bill = str(bill_id or "")
    marker = f"ledger_tx={source_tx_id}" if source_tx_id else ""
    for alloc in allocations.values():
        alloc_bill = str(getattr(alloc, "bill_id", "") or "")
        notes = str(getattr(alloc, "notes", "") or "")
        if not wanted_bill or alloc_bill != wanted_bill:
            continue
        if source_tx_id:
            if marker in notes:
                return True
            continue
        return True
    return False


def post_premium_to_accounting_book(
    *,
    bill_id: str,
    policy_id: str,
    customer_id: str,
    amount: Any,
    risk_percentage: Any,
    posted_by: str = "billing_system",
    source_tx_id: Optional[str] = None,
    notes: str = "",
    engine: Any = None,
) -> Dict[str, Any]:
    """Idempotently post a collected premium into the shared accounting book."""
    collected = money(amount)
    if collected <= 0:
        return {"posted": False, "reason": "zero_amount"}
    try:
        if engine is None:
            from accounting_engine import get_accounting_engine

            engine = get_accounting_engine()
        if _allocation_already_posted(engine, bill_id, source_tx_id):
            return {"posted": False, "reason": "already_posted", "bill_id": bill_id}
        note_bits = [n for n in (notes, f"ledger_tx={source_tx_id}" if source_tx_id else "") if n]
        allocation = engine.create_allocation(
            bill_id=bill_id or source_tx_id or "UNBILLED",
            policy_id=policy_id or "UNKNOWN",
            customer_id=customer_id,
            total_premium=collected,
            risk_percentage=Decimal(str(risk_percentage)),
            allocation_notes="; ".join(note_bits),
        )
        ok, message = engine.post_allocation(allocation.allocation_id, posted_by)
        return {
            "posted": bool(ok),
            "allocation_id": allocation.allocation_id,
            "message": message,
            "bill_id": bill_id,
            "amount": float(collected),
        }
    except Exception as exc:
        logger.warning("accounting premium post failed: %s", exc, exc_info=True)
        return {"posted": False, "reason": "error", "error": str(exc)}


def post_collected_premiums_to_accounting(
    *,
    customer_id: str,
    policy_id: Optional[str],
    policy: Optional[Dict[str, Any]],
    amount: Any,
    bills_paid: Sequence[str],
    billing: Dict[str, Any],
    source_tx_id: Optional[str],
    fallback_risk_pct: Any,
    unbilled_amount: Any = 0,
    engine: Any = None,
) -> List[Dict[str, Any]]:
    """Post each paid bill (and any unbilled remainder) to the accounting book."""
    split = resolve_premium_split(amount, policy, fallback_risk_pct)
    results: List[Dict[str, Any]] = []
    posted_from_bills = Decimal("0.00")
    remaining_cash = money(amount)
    for bill_id in bills_paid:
        bill = billing.get(bill_id) or billing.get(str(bill_id)) or {}
        bill_amount = money(bill.get("amount_paid") or bill.get("amount") or 0)
        # Post this payment's slice, not cumulative amount_paid — a later
        # partial on the same bill must not re-post the earlier cash.
        slice_amount = bill_amount if bill_amount <= remaining_cash else remaining_cash
        if slice_amount <= 0:
            continue
        bill_split = resolve_premium_split(slice_amount, policy, split["risk_percentage"])
        results.append(
            post_premium_to_accounting_book(
                bill_id=str(bill.get("id") or bill_id),
                policy_id=str(bill.get("policy_id") or policy_id or ""),
                customer_id=customer_id,
                amount=slice_amount,
                risk_percentage=bill_split["risk_percentage"],
                source_tx_id=source_tx_id,
                notes=f"kernel_split={bill_split['split_source']}",
                engine=engine,
            )
        )
        posted_from_bills += slice_amount
        remaining_cash -= slice_amount
    leftover = money(unbilled_amount)
    remaining_cash = money(amount) - posted_from_bills
    if leftover <= 0 and remaining_cash > 0:
        leftover = remaining_cash
    if leftover > 0:
        leftover_split = resolve_premium_split(leftover, policy, split["risk_percentage"])
        results.append(
            post_premium_to_accounting_book(
                bill_id=f"UNBILLED-{source_tx_id or customer_id}",
                policy_id=str(policy_id or ""),
                customer_id=customer_id,
                amount=leftover,
                risk_percentage=leftover_split["risk_percentage"],
                source_tx_id=source_tx_id,
                notes=f"unbilled kernel_split={leftover_split['split_source']}",
                engine=engine,
            )
        )
    return results


def accounting_book_totals(
    engine: Any = None,
    *,
    exclude_customer: Optional[Any] = None,
) -> Dict[str, float]:
    """Sum posted premiums and claim entries on the shared accounting book.

    ``exclude_customer`` is an optional callable ``(customer_id) -> bool``.
    It mirrors the customer-ledger exclusion so reconcile compares like
    with like (sandbox / suspended accounts filtered on both sides).
    """
    def _excluded(obj: Any) -> bool:
        if not exclude_customer:
            return False
        cid = str(getattr(obj, "customer_id", "") or "")
        return bool(cid and exclude_customer(cid))

    try:
        if engine is None:
            from accounting_engine import get_accounting_engine

            engine = get_accounting_engine()
        from accounting_engine import AllocationStatus, EntryType

        premium_total = Decimal("0.00")
        risk_total = Decimal("0.00")
        posted_allocations = 0
        for alloc in (engine.allocations or {}).values():
            if getattr(alloc, "status", None) != AllocationStatus.POSTED:
                continue
            if _excluded(alloc):
                continue
            premium_total += money(alloc.total_premium)
            risk_total += money(getattr(alloc, "risk_premium", 0))
            posted_allocations += 1
        claims_total = Decimal("0.00")
        entry_count = 0
        for entry in getattr(engine, "ledger_entries", []) or []:
            if _excluded(entry):
                continue
            entry_count += 1
            if getattr(entry, "entry_type", None) == EntryType.CLAIM_PAYMENT:
                claims_total += money(entry.credit_amount or entry.debit_amount)
        return {
            "premium_posted": float(premium_total),
            "risk_posted": float(risk_total),
            "claims_posted": float(claims_total),
            "allocation_count": posted_allocations,
            "entry_count": entry_count,
        }
    except Exception as exc:
        logger.warning("accounting book totals failed: %s", exc)
        return {
            "premium_posted": 0.0,
            "risk_posted": 0.0,
            "claims_posted": 0.0,
            "allocation_count": 0,
            "entry_count": 0,
        }


def accounting_risk_cash(
    engine: Any = None,
    *,
    exclude_customer: Optional[Any] = None,
) -> Decimal:
    """Posted risk-premium cash on the shared accounting book."""
    return money(
        accounting_book_totals(engine, exclude_customer=exclude_customer).get(
            "risk_posted", 0
        )
    )


def kernel_portfolio_risk_pct(
    policies: Optional[Dict[str, Any]] = None,
    *,
    exclude_customer: Optional[Any] = None,
) -> Decimal:
    """Portfolio risk share from pinned kernel components.

    Policies without a pin count as 100% risk so the fallback never invents
    a 75% card that disagrees with the ledger.
    """
    risk = Decimal("0.00")
    annual = Decimal("0.00")
    for policy in (policies or {}).values():
        if not isinstance(policy, dict):
            continue
        cid = str(policy.get("customer_id") or "")
        if exclude_customer and cid and exclude_customer(cid):
            continue
        kernel = kernel_components_from_policy(policy)
        ann = money(kernel.get("annual_premium") or policy.get("annual_premium", 0))
        if ann <= 0:
            continue
        rsk = money(kernel.get("risk_premium_annual"))
        annual += ann
        risk += rsk if rsk > 0 else ann
    if annual <= 0:
        return Decimal("100")
    return (risk / annual * Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def economic_claims_reserve(
    *,
    transactions: Iterable[Dict[str, Any]],
    policies: Optional[Dict[str, Any]] = None,
    engine: Any = None,
    exclude_customer: Optional[Any] = None,
) -> Dict[str, Any]:
    """Displayed claims-reserve identity: risk cash collected minus claim cash.

    Prefers accounting-book risk postings (already kernel-split). Falls back
    to customer-ledger premium cash times the portfolio kernel risk share.
    Does not mutate seed capital on the balance sheet.
    """
    claim_ledger = ledger_cash_total(
        transactions, CLAIM_CASH_TYPES, exclude_customer=exclude_customer
    )
    premium_ledger = ledger_cash_total(
        transactions, PREMIUM_CASH_TYPES, exclude_customer=exclude_customer
    )
    claim_cash = money(claim_ledger["total"])
    book = accounting_book_totals(engine, exclude_customer=exclude_customer)
    risk_from_book = money(book.get("risk_posted", 0))
    if risk_from_book > 0:
        risk_cash = risk_from_book
        risk_source = "accounting_book"
    else:
        risk_pct = kernel_portfolio_risk_pct(
            policies, exclude_customer=exclude_customer
        )
        risk_cash = (
            money(premium_ledger["total"]) * risk_pct / Decimal("100")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        risk_source = "kernel_split_of_ledger_premium"
    economic = (risk_cash - claim_cash).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "risk_cash_collected": float(risk_cash),
        "claim_cash_paid": float(claim_cash),
        "economic_claims_reserve": float(economic),
        "risk_cash_source": risk_source,
        "identity": "ledger_risk_cash_minus_claim_cash",
    }


def _diff(left: Decimal, right: Decimal) -> float:
    return float((left - right).quantize(Decimal("0.01")))


def reconcile_financial_books(
    *,
    policies: Dict[str, Any],
    claims: Dict[str, Any],
    billing: Dict[str, Any],
    transactions: Iterable[Dict[str, Any]],
    balance_sheet: Optional[Dict[str, Any]] = None,
    exclude_customer: Optional[Any] = None,
    engine: Any = None,
) -> Dict[str, Any]:
    """Compare kernel-priced identity, customer-ledger cash, bills, BS, and book.

    Reports discrepancies. Does not mutate historical rows.
    """
    ledger_list = list(transactions)
    premium_ledger = ledger_cash_total(
        ledger_list, PREMIUM_CASH_TYPES, exclude_customer=exclude_customer
    )
    claim_ledger = ledger_cash_total(
        ledger_list, CLAIM_CASH_TYPES, exclude_customer=exclude_customer
    )

    bills_collected = Decimal("0.00")
    for bill in (billing or {}).values():
        if not isinstance(bill, dict):
            continue
        cid = str(bill.get("customer_id") or "")
        if exclude_customer and cid and exclude_customer(cid):
            continue
        bills_collected += money(bill.get("amount_paid", 0))

    claims_records = Decimal("0.00")
    claims_missing_ledger = []
    claim_ids_on_ledger = set()
    for tx in ledger_list:
        if _tx_type(tx) not in CLAIM_CASH_TYPES:
            continue
        meta = tx.get("metadata") if isinstance(tx.get("metadata"), dict) else {}
        cid = str(meta.get("claim_id") or tx.get("claim_id") or "")
        if cid:
            claim_ids_on_ledger.add(cid)
    for claim in (claims or {}).values():
        if not isinstance(claim, dict):
            continue
        status = str(claim.get("status") or "").strip().lower()
        if status not in ("paid", "closed"):
            continue
        cid = str(claim.get("customer_id") or "")
        if exclude_customer and cid and exclude_customer(cid):
            continue
        paid = money(
            claim.get("paid_amount")
            or claim.get("approved_amount")
            or claim.get("amount_approved")
            or 0
        )
        claims_records += paid
        claim_id = str(claim.get("id") or "")
        if claim_id and claim_id not in claim_ids_on_ledger:
            claims_missing_ledger.append(claim_id)

    kernel_annual = Decimal("0.00")
    stored_annual = Decimal("0.00")
    kernel_priced_count = 0
    for policy in (policies or {}).values():
        if not isinstance(policy, dict):
            continue
        cid = str(policy.get("customer_id") or "")
        if exclude_customer and cid and exclude_customer(cid):
            continue
        stored_annual += money(policy.get("annual_premium", 0))
        components = kernel_components_from_policy(policy)
        if components.get("pricing_source") == "pricing_kernel" or components.get("source") == "premium_snapshot":
            kernel_annual += money(components["annual_premium"] or policy.get("annual_premium", 0))
            kernel_priced_count += 1
        else:
            kernel_annual += money(policy.get("annual_premium", 0))

    book = accounting_book_totals(engine, exclude_customer=exclude_customer)
    bs = balance_sheet or {}
    bs_premium = money((bs.get("revenue_breakdown") or {}).get("premium_income", 0))
    bs_claims = money((bs.get("expense_breakdown") or {}).get("claims_paid", 0))
    bs_reserve = money(bs.get("claims_reserve", 0))
    economic = economic_claims_reserve(
        transactions=ledger_list,
        policies=policies,
        engine=engine,
        exclude_customer=exclude_customer,
    )

    ledger_premium = money(premium_ledger["total"])
    ledger_claims = money(claim_ledger["total"])

    discrepancies: List[Dict[str, Any]] = []

    def _check(name: str, left: Decimal, right: Decimal, description: str) -> None:
        delta = left - right
        if delta.copy_abs() > TOLERANCE:
            discrepancies.append({
                "check": name,
                "description": description,
                "left": float(left),
                "right": float(right),
                "difference": _diff(left, right),
            })

    # Ledger may include unbilled prepayments. Only fail when bills were
    # marked paid without a matching customer-ledger cash entry.
    if bills_collected - ledger_premium > TOLERANCE:
        discrepancies.append({
            "check": "bills_vs_ledger_premiums",
            "description": "Paid bill amounts exceed customer-ledger premium cash",
            "left": float(bills_collected),
            "right": float(ledger_premium),
            "difference": _diff(bills_collected, ledger_premium),
        })

    _check(
        "claims_records_vs_customer_ledger",
        claims_records,
        ledger_claims,
        "Paid claim records must equal customer-ledger claim cash",
    )
    _check(
        "accounting_book_vs_ledger_premiums",
        money(book["premium_posted"]),
        ledger_premium,
        "Accounting book posted premiums must equal customer-ledger premium cash",
    )
    _check(
        "accounting_book_vs_ledger_claims",
        money(book["claims_posted"]),
        ledger_claims,
        "Accounting book claim entries must equal customer-ledger claim cash",
    )
    if bs:
        _check(
            "balance_sheet_vs_ledger_premiums",
            bs_premium,
            ledger_premium,
            "Balance-sheet premium_income should match customer-ledger premium cash",
        )
        _check(
            "balance_sheet_vs_ledger_claims",
            bs_claims,
            ledger_claims,
            "Balance-sheet claims_paid should match customer-ledger claim cash",
        )

    if claims_missing_ledger:
        discrepancies.append({
            "check": "paid_claims_missing_customer_ledger",
            "description": "Paid claims with no customer-ledger cash entry",
            "claim_ids": claims_missing_ledger[:50],
            "count": len(claims_missing_ledger),
        })

    return {
        "is_consistent": len(discrepancies) == 0,
        "tolerance": float(TOLERANCE),
        "authority": {
            "premium_identity": "actuarial_kernel_or_issued_policy",
            "cash_identity": "customer_ledger",
            "claim_cash_types": sorted(CLAIM_CASH_TYPES),
            "premium_cash_types": sorted(PREMIUM_CASH_TYPES),
        },
        "premiums": {
            "kernel_or_issued_annual": float(kernel_annual),
            "stored_annual": float(stored_annual),
            "kernel_priced_policies": kernel_priced_count,
            "bills_collected": float(bills_collected),
            "customer_ledger": premium_ledger,
            "accounting_book": book["premium_posted"],
            "balance_sheet": float(bs_premium),
        },
        "claims": {
            "records_paid": float(claims_records),
            "customer_ledger": claim_ledger,
            "accounting_book": book["claims_posted"],
            "balance_sheet": float(bs_claims),
            "missing_ledger_claim_ids": claims_missing_ledger,
        },
        "reserves": {
            "seed_claims_reserve": float(bs_reserve),
            "balance_sheet_claims_reserve": float(bs_reserve),
            "economic_claims_reserve": economic["economic_claims_reserve"],
            "risk_cash_collected": economic["risk_cash_collected"],
            "claim_cash_paid": economic["claim_cash_paid"],
            "risk_cash_source": economic["risk_cash_source"],
            "identity": economic["identity"],
            "note": (
                "Displayed claims reserve is collected risk cash minus claim cash. "
                "Seed capital is reported separately and is never rewritten."
            ),
        },
        "discrepancies": discrepancies,
        "discrepancy_count": len(discrepancies),
    }


def pin_kernel_fields_on_policy(policy: Dict[str, Any], premium_data: Dict[str, Any]) -> Dict[str, Any]:
    """Copy kernel decomposition onto the issued policy (additive, no reprice)."""
    if not isinstance(policy, dict) or not isinstance(premium_data, dict):
        return policy
    for key in (
        "pricing_source",
        "integrity_hash",
        "product_id",
        "tables_version",
        "config_version",
        "risk_premium_annual",
        "savings_premium_annual",
        "mortality_premium_annual",
        "disability_premium_annual",
        "savings_rate_used",
        "savings_formula",
        "adl_level",
        "adl_loading",
        "underwriting_loading",
        "life_sum_used",
        "disability_sum_used",
    ):
        if premium_data.get(key) is not None and policy.get(key) in (None, ""):
            policy[key] = premium_data[key]
    return policy
