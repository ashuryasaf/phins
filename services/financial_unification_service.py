"""Canonical financial-book unification for PHINS.

Authority (do not invert):

1. Actuarial kernel pricing is the premium *identity* (what should be billed).
2. The customer ledger (``TRANSACTION_LEDGER``) is the cash *identity* for
   premium collections and claim payouts.
3. The accounting book, company balance sheet, and reserves reports must
   equal those cash totals. They never invent amounts.

This module is fail-open: posting helpers never raise into payment flows.

Early PHINS durability was inconsistent (in-memory books, JSON snapshots,
and later a hash-chained ledger). ``repair_financial_books`` reconstructs
missing cash-identity rows from operational evidence (paid bills, paid
claims) and backfills the accounting book from that ledger. It never
rewrites billed ``annual_premium`` / ``Bill.amount`` and never mutates
founding ``seed_claims_reserve``.
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

# Customer-savings cash that landed as an investment/pipeline deposit.
SAVINGS_ALLOCATION_DEPOSIT_TYPES = frozenset({
    "premium_allocation",
    "savings_allocation",
    "savings_premium",
    "pipeline_premium",
})

FOUNDING_CLAIMS_RESERVE = Decimal("3500000.00")
REPAIR_TX_PREFIX = "TX-REPAIR-"

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

    If the same ledger tx was booked as ``UNBILLED-{tx}`` (bills missing at
    post time), a later real ``bill_id`` for that tx must not post again.
    """
    allocations = getattr(engine, "allocations", {}) or {}
    wanted_bill = str(bill_id or "")
    marker = f"ledger_tx={source_tx_id}" if source_tx_id else ""
    unbilled_key = f"UNBILLED-{source_tx_id}" if source_tx_id else ""
    for alloc in allocations.values():
        alloc_bill = str(getattr(alloc, "bill_id", "") or "")
        notes = str(getattr(alloc, "notes", "") or "")
        if unbilled_key and alloc_bill == unbilled_key and marker in notes:
            return True
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
    bill_payments: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Post each paid bill (and any unbilled remainder) to the accounting book.

    ``bill_payments`` optionally maps a bill id to the increment collected in
    *this* payment. When supplied it is used instead of the bill's cumulative
    ``amount_paid`` so a later installment posts only its own increment rather
    than re-posting (and double-counting) the running total.
    """
    split = resolve_premium_split(amount, policy, fallback_risk_pct)
    results: List[Dict[str, Any]] = []
    posted_from_bills = Decimal("0.00")
    remaining_cash = money(amount)
    for bill_id in bills_paid:
        bill = billing.get(bill_id) or billing.get(str(bill_id)) or {}
        if bill_payments is not None:
            bill_amount = money(
                bill_payments.get(bill_id, bill_payments.get(str(bill_id), 0))
            )
        else:
            bill_amount = money(bill.get("amount_paid") or bill.get("amount") or 0)
            # Without an increment map, cap at remaining cash so a later
            # single-bill installment cannot re-post the cumulative total.
            if bill_amount > remaining_cash:
                bill_amount = remaining_cash
        if bill_amount <= 0:
            continue
        bill_split = resolve_premium_split(bill_amount, policy, split["risk_percentage"])
        results.append(
            post_premium_to_accounting_book(
                bill_id=str(bill.get("id") or bill_id),
                policy_id=str(bill.get("policy_id") or policy_id or ""),
                customer_id=customer_id,
                amount=bill_amount,
                risk_percentage=bill_split["risk_percentage"],
                source_tx_id=source_tx_id,
                notes=f"kernel_split={bill_split['split_source']}",
                engine=engine,
            )
        )
        posted_from_bills += bill_amount
        remaining_cash -= bill_amount
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
        savings_total = Decimal("0.00")
        posted_allocations = 0
        for alloc in (engine.allocations or {}).values():
            if getattr(alloc, "status", None) != AllocationStatus.POSTED:
                continue
            if _excluded(alloc):
                continue
            premium_total += money(alloc.total_premium)
            risk_total += money(getattr(alloc, "risk_premium", 0))
            savings_total += money(getattr(alloc, "savings_premium", 0))
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
            "savings_posted": float(savings_total),
            "claims_posted": float(claims_total),
            "allocation_count": posted_allocations,
            "entry_count": entry_count,
        }
    except Exception as exc:
        logger.warning("accounting book totals failed: %s", exc)
        return {
            "premium_posted": 0.0,
            "risk_posted": 0.0,
            "savings_posted": 0.0,
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
    book_premium = money(book.get("premium_posted", 0))
    ledger_premium = money(premium_ledger["total"])
    risk_pct = kernel_portfolio_risk_pct(
        policies, exclude_customer=exclude_customer
    )
    # Premium posting to the accounting book is a partial migration: historical
    # collected premiums still live only on the customer ledger and are not
    # backfilled onto the book. Trust the book's kernel-split risk for the
    # premium it already carries, and cover any not-yet-booked ledger premium
    # with the portfolio kernel risk share so the reserve never collapses to
    # just newly-posted risk minus all claim cash.
    unbooked_premium = ledger_premium - book_premium
    if unbooked_premium < 0:
        unbooked_premium = Decimal("0.00")
    unbooked_risk = (
        unbooked_premium * risk_pct / Decimal("100")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if risk_from_book > 0:
        risk_cash = (risk_from_book + unbooked_risk).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        risk_source = (
            "accounting_book_plus_ledger_backfill"
            if unbooked_risk > 0
            else "accounting_book"
        )
    else:
        risk_cash = unbooked_risk
        risk_source = "kernel_split_of_ledger_premium"
    economic = (risk_cash - claim_cash).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "risk_cash_collected": float(risk_cash),
        "claim_cash_paid": float(claim_cash),
        "economic_claims_reserve": float(economic),
        "risk_cash_source": risk_source,
        "identity": "ledger_risk_cash_minus_claim_cash",
    }


def ensure_seed_claims_reserve(
    balance_sheet: Optional[Dict[str, Any]],
    founding_capital: Any = None,
) -> float:
    """Pin founding capital once. Never derived from later claim deductions."""
    sheet = balance_sheet if isinstance(balance_sheet, dict) else {}
    seed = sheet.get("seed_claims_reserve")
    if seed is None or seed == "":
        fallback = founding_capital
        if fallback is None:
            fallback = FOUNDING_CLAIMS_RESERVE
        sheet["seed_claims_reserve"] = money_float(fallback)
    return money_float(sheet.get("seed_claims_reserve"))


def apply_ledger_derived_balance_sheet(
    balance_sheet: Dict[str, Any],
    ledger_premium: Any,
    ledger_claims: Any,
) -> Dict[str, Any]:
    """Set derived BS counters from customer-ledger cash.

    Updates ``premium_income`` and ``claims_paid`` (and their totals) so
    the General Reserves sheet matches cash identity. Does **not** touch
    ``seed_claims_reserve`` or operational ``claims_reserve``.
    """
    if not isinstance(balance_sheet, dict):
        return {}
    ensure_seed_claims_reserve(balance_sheet)
    premium = money(ledger_premium)
    claims = money(ledger_claims)
    revenue = balance_sheet.setdefault("revenue_breakdown", {})
    expense = balance_sheet.setdefault("expense_breakdown", {})
    if not isinstance(revenue, dict):
        revenue = {}
        balance_sheet["revenue_breakdown"] = revenue
    if not isinstance(expense, dict):
        expense = {}
        balance_sheet["expense_breakdown"] = expense
    revenue["premium_income"] = float(premium)
    expense["claims_paid"] = float(claims)
    balance_sheet["total_revenue"] = round(
        sum(money_float(v) for v in revenue.values()), 2
    )
    balance_sheet["total_expenses"] = round(
        sum(money_float(v) for v in expense.values()), 2
    )
    return {
        "premium_income": float(premium),
        "claims_paid": float(claims),
        "total_revenue": balance_sheet["total_revenue"],
        "total_expenses": balance_sheet["total_expenses"],
        "seed_claims_reserve": money_float(balance_sheet.get("seed_claims_reserve")),
    }


def _tx_metadata(tx: Dict[str, Any]) -> Dict[str, Any]:
    meta = tx.get("metadata")
    return meta if isinstance(meta, dict) else {}


def premium_cash_by_bill_id(
    transactions: Iterable[Dict[str, Any]],
) -> Dict[str, Decimal]:
    """Sum customer-ledger premium cash keyed by bill_id (when present)."""
    totals: Dict[str, Decimal] = {}
    for tx in transactions:
        if not isinstance(tx, dict):
            continue
        if _tx_type(tx) not in PREMIUM_CASH_TYPES:
            continue
        meta = _tx_metadata(tx)
        bill_id = str(meta.get("bill_id") or tx.get("bill_id") or "").strip()
        if not bill_id:
            continue
        totals[bill_id] = totals.get(bill_id, Decimal("0.00")) + _tx_amount(tx)
    return totals


def claim_cash_by_id(
    transactions: Iterable[Dict[str, Any]],
) -> Dict[str, Decimal]:
    """Sum customer-ledger claim cash keyed by claim_id."""
    totals: Dict[str, Decimal] = {}
    for tx in transactions:
        if not isinstance(tx, dict):
            continue
        if _tx_type(tx) not in CLAIM_CASH_TYPES:
            continue
        meta = _tx_metadata(tx)
        claim_id = str(meta.get("claim_id") or tx.get("claim_id") or "").strip()
        if not claim_id:
            continue
        totals[claim_id] = totals.get(claim_id, Decimal("0.00")) + _tx_amount(tx)
    return totals


def accounting_claim_ids(engine: Any = None) -> set:
    ids = set()
    try:
        if engine is None:
            from accounting_engine import get_accounting_engine, EntryType

            engine = get_accounting_engine()
        else:
            from accounting_engine import EntryType
        for entry in getattr(engine, "ledger_entries", []) or []:
            if getattr(entry, "entry_type", None) != EntryType.CLAIM_PAYMENT:
                continue
            cid = str(
                getattr(entry, "reference_no", "")
                or getattr(entry, "allocation_id", "")
                or ""
            ).strip()
            if cid:
                ids.add(cid)
    except Exception:
        return ids
    return ids


def post_claim_to_accounting_book(
    *,
    claim_id: str,
    policy_id: str,
    customer_id: str,
    amount: Any,
    paid_by: str = "books_repair",
    engine: Any = None,
) -> Dict[str, Any]:
    """Idempotently post claim cash onto the shared accounting book."""
    paid = money(amount)
    if paid <= 0:
        return {"posted": False, "reason": "zero_amount"}
    wanted = str(claim_id or "").strip()
    if not wanted:
        return {"posted": False, "reason": "missing_claim_id"}
    try:
        if engine is None:
            from accounting_engine import get_accounting_engine

            engine = get_accounting_engine()
        if wanted in accounting_claim_ids(engine):
            return {"posted": False, "reason": "already_posted", "claim_id": wanted}
        ok, message = engine.post_claim_payment(
            claim_id=wanted,
            policy_id=policy_id or "UNKNOWN",
            customer_id=customer_id or "",
            amount=paid,
            paid_by=paid_by,
        )
        return {
            "posted": bool(ok),
            "claim_id": wanted,
            "amount": float(paid),
            "message": message,
        }
    except Exception as exc:
        logger.warning("accounting claim post failed: %s", exc, exc_info=True)
        return {"posted": False, "reason": "error", "error": str(exc)}


def _policy_for_tx(
    tx: Dict[str, Any],
    policies: Optional[Dict[str, Any]],
    billing: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    policies = policies or {}
    billing = billing or {}
    meta = _tx_metadata(tx)
    policy_id = str(
        meta.get("policy_id") or tx.get("policy_id") or ""
    ).strip()
    if policy_id and policy_id in policies:
        return policies.get(policy_id)
    bill_id = str(meta.get("bill_id") or tx.get("bill_id") or "").strip()
    if bill_id:
        bill = billing.get(bill_id) or billing.get(str(bill_id)) or {}
        policy_id = str(bill.get("policy_id") or "").strip()
        if policy_id and policy_id in policies:
            return policies.get(policy_id)
    customer_id = str(tx.get("customer_id") or "")
    if customer_id:
        for policy in policies.values():
            if isinstance(policy, dict) and str(policy.get("customer_id") or "") == customer_id:
                return policy
    return None


def kernel_savings_cash_from_ledger(
    transactions: Iterable[Dict[str, Any]],
    policies: Optional[Dict[str, Any]] = None,
    billing: Optional[Dict[str, Any]] = None,
    *,
    exclude_customer: Optional[Any] = None,
) -> Dict[str, Any]:
    """Kernel-split savings portion of customer-ledger premium cash."""
    risk = Decimal("0.00")
    savings = Decimal("0.00")
    count = 0
    for tx in transactions:
        if not isinstance(tx, dict):
            continue
        if _tx_type(tx) not in PREMIUM_CASH_TYPES:
            continue
        cid = str(tx.get("customer_id") or "")
        if exclude_customer and cid and exclude_customer(cid):
            continue
        amount = _tx_amount(tx)
        if amount <= 0:
            continue
        policy = _policy_for_tx(tx, policies, billing)
        split = resolve_premium_split(amount, policy, fallback_risk_pct=100)
        risk += money(split["risk_amount"])
        savings += money(split["savings_amount"])
        count += 1
    return {
        "risk_amount": float(risk),
        "savings_amount": float(savings),
        "premium_count": count,
    }


def investment_premium_allocation_total(
    investment_accounts: Optional[Dict[str, Any]] = None,
    *,
    exclude_customer: Optional[Any] = None,
) -> Dict[str, Any]:
    """Sum deposits tagged as premium/savings allocations (cash in, not AUM)."""
    total = Decimal("0.00")
    aum = Decimal("0.00")
    count = 0
    for customer_id, account in (investment_accounts or {}).items():
        if exclude_customer and customer_id and exclude_customer(customer_id):
            continue
        if not isinstance(account, dict):
            continue
        aum += money(account.get("balance", 0))
        for dep in account.get("deposits") or []:
            if not isinstance(dep, dict):
                continue
            kind = str(dep.get("type") or "").strip().lower()
            if kind and kind not in SAVINGS_ALLOCATION_DEPOSIT_TYPES:
                continue
            amount = money(dep.get("amount", 0)).copy_abs()
            if amount <= 0:
                continue
            total += amount
            count += 1
    return {
        "premium_allocations": float(total),
        "aum_balance": float(aum),
        "allocation_count": count,
    }


def pipeline_savings_cash(
    savings_pipeline_accounts: Optional[Any] = None,
    *,
    exclude_customer: Optional[Any] = None,
) -> Dict[str, Any]:
    """Cash sitting in the savings pipeline (not market value)."""
    cash = Decimal("0.00")
    count = 0
    accounts = savings_pipeline_accounts
    if accounts is None:
        return {"cash_balance": 0.0, "account_count": 0}
    values = accounts.values() if hasattr(accounts, "values") else accounts
    for account in values:
        cid = ""
        balance = 0
        if isinstance(account, dict):
            cid = str(account.get("customer_id") or "")
            balance = account.get("cash_balance", 0)
        else:
            cid = str(getattr(account, "customer_id", "") or "")
            balance = getattr(account, "cash_balance", 0)
        if exclude_customer and cid and exclude_customer(cid):
            continue
        cash += money(balance)
        count += 1
    return {"cash_balance": float(cash), "account_count": count}


def savings_and_investments_books(
    *,
    transactions: Iterable[Dict[str, Any]],
    policies: Optional[Dict[str, Any]] = None,
    billing: Optional[Dict[str, Any]] = None,
    investment_accounts: Optional[Dict[str, Any]] = None,
    savings_pipeline_accounts: Optional[Any] = None,
    engine: Any = None,
    exclude_customer: Optional[Any] = None,
) -> Dict[str, Any]:
    """Tie kernel savings cash to the accounting book and portfolio deposits."""
    ledger_split = kernel_savings_cash_from_ledger(
        transactions,
        policies,
        billing,
        exclude_customer=exclude_customer,
    )
    book = accounting_book_totals(engine, exclude_customer=exclude_customer)
    investments = investment_premium_allocation_total(
        investment_accounts, exclude_customer=exclude_customer
    )
    pipeline = pipeline_savings_cash(
        savings_pipeline_accounts, exclude_customer=exclude_customer
    )
    landed = money(investments["premium_allocations"]) + money(pipeline["cash_balance"])
    savings_cash = money(ledger_split["savings_amount"])
    return {
        "kernel_savings_cash": ledger_split["savings_amount"],
        "kernel_risk_cash": ledger_split["risk_amount"],
        "accounting_savings_posted": book.get("savings_posted", 0.0),
        "investment_premium_allocations": investments["premium_allocations"],
        "investment_aum": investments["aum_balance"],
        "pipeline_cash": pipeline["cash_balance"],
        "savings_landed": float(landed),
        "unlanded_savings_cash": float(
            max(Decimal("0.00"), savings_cash - landed)
        ),
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
    investment_accounts: Optional[Dict[str, Any]] = None,
    savings_pipeline_accounts: Optional[Any] = None,
) -> Dict[str, Any]:
    """Compare kernel-priced identity, customer-ledger cash, bills, BS, book, savings.

    Reports discrepancies. Does not mutate historical rows. Use
    ``repair_financial_books`` to reconstruct missing cash-identity rows
    from paid bills/claims and backfill the accounting book.
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
        status = str(claim.get("status") or "").strip().lower().replace(" ", "_")
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
    if (kernel_annual - stored_annual).copy_abs() > TOLERANCE:
        discrepancies.append({
            "check": "kernel_vs_stored_annual_premium",
            "description": (
                "Kernel-priced annual premium differs from stored annual_premium. "
                "Historical billed amounts are not rewritten; pin kernel fields."
            ),
            "left": float(kernel_annual),
            "right": float(stored_annual),
            "difference": _diff(kernel_annual, stored_annual),
        })
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

    bills_missing_ledger = []
    bill_cash = premium_cash_by_bill_id(ledger_list)
    for bill in (billing or {}).values():
        if not isinstance(bill, dict):
            continue
        cid = str(bill.get("customer_id") or "")
        if exclude_customer and cid and exclude_customer(cid):
            continue
        paid = money(bill.get("amount_paid", 0))
        if paid <= 0:
            continue
        bill_id = str(bill.get("id") or bill.get("bill_id") or "")
        if not bill_id:
            continue
        if bill_cash.get(bill_id, Decimal("0.00")) + TOLERANCE < paid:
            bills_missing_ledger.append(bill_id)
    if bills_missing_ledger:
        discrepancies.append({
            "check": "paid_bills_missing_customer_ledger",
            "description": "Paid bills with less customer-ledger cash than amount_paid",
            "bill_ids": bills_missing_ledger[:50],
            "count": len(bills_missing_ledger),
        })

    savings_books = savings_and_investments_books(
        transactions=ledger_list,
        policies=policies,
        billing=billing,
        investment_accounts=investment_accounts,
        savings_pipeline_accounts=savings_pipeline_accounts,
        engine=engine,
        exclude_customer=exclude_customer,
    )
    savings_cash = money(savings_books["kernel_savings_cash"])
    savings_landed = money(savings_books["savings_landed"])
    # Invented savings (portfolio deposits with no matching premium cash).
    if money(savings_books["investment_premium_allocations"]) - savings_cash > TOLERANCE:
        discrepancies.append({
            "check": "investment_allocations_exceed_savings_premium",
            "description": (
                "Investment premium-allocation deposits exceed kernel savings "
                "cash collected on the customer ledger"
            ),
            "left": savings_books["investment_premium_allocations"],
            "right": savings_books["kernel_savings_cash"],
            "difference": _diff(
                money(savings_books["investment_premium_allocations"]),
                savings_cash,
            ),
        })
    # Collected savings premium that never landed in a savings book.
    # Only flag when there is savings cash and nothing at all on the
    # investment or pipeline side (historical durability gap).
    if (
        savings_cash > TOLERANCE
        and savings_landed + TOLERANCE < savings_cash
        and money(savings_books["investment_aum"]) + TOLERANCE < savings_cash
    ):
        discrepancies.append({
            "check": "savings_cash_not_landed_in_portfolios",
            "description": (
                "Kernel savings cash collected is not reflected in investment "
                "premium allocations, pipeline cash, or investment AUM"
            ),
            "left": float(savings_cash),
            "right": float(savings_landed),
            "difference": _diff(savings_cash, savings_landed),
        })

    seed = ensure_seed_claims_reserve(bs) if bs else float(bs_reserve)

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
        "savings": savings_books,
        "reserves": {
            "seed_claims_reserve": float(seed),
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
        "repair_candidates": {
            "paid_bills_missing_ledger": bills_missing_ledger,
            "paid_claims_missing_ledger": claims_missing_ledger,
        },
    }


def repair_financial_books(
    *,
    policies: Dict[str, Any],
    claims: Dict[str, Any],
    billing: Dict[str, Any],
    transactions: Dict[str, Any],
    balance_sheet: Optional[Dict[str, Any]] = None,
    investment_accounts: Optional[Dict[str, Any]] = None,
    savings_pipeline_accounts: Optional[Any] = None,
    exclude_customer: Optional[Any] = None,
    engine: Any = None,
    append_ledger: Optional[Any] = None,
    dry_run: bool = False,
    actor: str = "books_repair",
) -> Dict[str, Any]:
    """Reconstruct missing cash-identity rows from operational evidence.

    Early PHINS durability could drop a customer-ledger row, skip the
    accounting book, or leave the General Reserves sheet on a different
    counter. This repair:

    1. Appends missing ``premium_payment`` rows for paid bills.
    2. Appends missing ``claim_payment_received`` rows for paid/closed claims.
    3. Posts missing accounting-book premiums from the ledger.
    4. Posts missing accounting-book claim entries from the ledger.
    5. Derives balance-sheet ``premium_income`` / ``claims_paid`` from the ledger.

    Never rewrites ``annual_premium``, ``Bill.amount``, or
    ``seed_claims_reserve``. Idempotent. ``dry_run=True`` reports actions
    without mutating.
    """
    if engine is None:
        try:
            from accounting_engine import get_accounting_engine

            engine = get_accounting_engine()
        except Exception:
            engine = None

    ensure_seed_claims_reserve(balance_sheet)
    before = reconcile_financial_books(
        policies=policies,
        claims=claims,
        billing=billing,
        transactions=list(transactions.values()) if hasattr(transactions, "values") else list(transactions),
        balance_sheet=balance_sheet,
        exclude_customer=exclude_customer,
        engine=engine,
        investment_accounts=investment_accounts,
        savings_pipeline_accounts=savings_pipeline_accounts,
    )

    actions: List[Dict[str, Any]] = []
    reconstructed: List[Dict[str, Any]] = []
    ledger_iterable = (
        list(transactions.values()) if hasattr(transactions, "values") else list(transactions)
    )

    def _write_ledger(
        customer_id: str,
        tx_type: str,
        amount: Decimal,
        description: str,
        metadata: Dict[str, Any],
        tx_id: str,
    ) -> Optional[str]:
        payload = {
            "id": tx_id,
            "customer_id": customer_id,
            "type": tx_type,
            "amount": float(amount),
            "description": description,
            "metadata": metadata,
            "timestamp": metadata.get("timestamp") or "",
            "status": "completed",
            "repaired": True,
        }
        reconstructed.append(payload)
        if dry_run:
            return tx_id
        if append_ledger:
            written = append_ledger(
                customer_id=customer_id,
                tx_type=tx_type,
                amount=float(amount),
                description=description,
                metadata=metadata,
            )
            if isinstance(written, dict):
                return str(written.get("id") or written.get("tx_id") or tx_id)
            return tx_id
        if hasattr(transactions, "__setitem__"):
            transactions[tx_id] = payload
        return tx_id

    bill_cash = premium_cash_by_bill_id(ledger_iterable)
    for bill in (billing or {}).values():
        if not isinstance(bill, dict):
            continue
        customer_id = str(bill.get("customer_id") or "")
        if exclude_customer and customer_id and exclude_customer(customer_id):
            continue
        paid = money(bill.get("amount_paid", 0))
        if paid <= 0:
            continue
        bill_id = str(bill.get("id") or bill.get("bill_id") or "").strip()
        if not bill_id:
            continue
        already = bill_cash.get(bill_id, Decimal("0.00"))
        missing = paid - already
        if missing <= TOLERANCE:
            continue
        tx_id = f"{REPAIR_TX_PREFIX}BILL-{bill_id}"
        if hasattr(transactions, "get") and transactions.get(tx_id):
            continue
        meta = {
            "bill_id": bill_id,
            "policy_id": str(bill.get("policy_id") or ""),
            "repair_source": "paid_bill",
            "actor": actor,
        }
        actions.append({
            "action": "append_premium_ledger",
            "bill_id": bill_id,
            "amount": float(missing),
            "tx_id": tx_id,
        })
        written_id = _write_ledger(
            customer_id,
            CANONICAL_PREMIUM_LEDGER_TYPE,
            missing,
            f"Reconstructed premium cash for bill {bill_id}",
            meta,
            tx_id,
        )
        if written_id:
            bill_cash[bill_id] = already + missing

    # Re-read after bill repairs so claim scan sees new rows. Dry-run
    # reconstructed rows live only in ``reconstructed``.
    if dry_run:
        claim_cash = claim_cash_by_id(list(ledger_iterable) + reconstructed)
    elif hasattr(transactions, "values"):
        claim_cash = claim_cash_by_id(list(transactions.values()))
    else:
        claim_cash = claim_cash_by_id(list(transactions))

    for claim in (claims or {}).values():
        if not isinstance(claim, dict):
            continue
        status = str(claim.get("status") or "").strip().lower().replace(" ", "_")
        if status not in ("paid", "closed"):
            continue
        customer_id = str(claim.get("customer_id") or "")
        if exclude_customer and customer_id and exclude_customer(customer_id):
            continue
        paid = money(
            claim.get("paid_amount")
            or claim.get("approved_amount")
            or claim.get("amount_approved")
            or 0
        )
        if paid <= 0:
            continue
        claim_id = str(claim.get("id") or claim.get("claim_id") or "").strip()
        if not claim_id:
            continue
        already = claim_cash.get(claim_id, Decimal("0.00"))
        missing = paid - already
        if missing <= TOLERANCE:
            continue
        tx_id = f"{REPAIR_TX_PREFIX}CLM-{claim_id}"
        if hasattr(transactions, "get") and transactions.get(tx_id):
            continue
        meta = {
            "claim_id": claim_id,
            "policy_id": str(claim.get("policy_id") or ""),
            "repair_source": "paid_claim",
            "actor": actor,
        }
        actions.append({
            "action": "append_claim_ledger",
            "claim_id": claim_id,
            "amount": float(missing),
            "tx_id": tx_id,
        })
        _write_ledger(
            customer_id,
            CANONICAL_CLAIM_LEDGER_TYPE,
            missing,
            f"Reconstructed claim cash for {claim_id}",
            meta,
            tx_id,
        )
        claim_cash[claim_id] = already + missing

    # Refresh iterable after ledger reconstruction. Dry-run must still
    # feed reconstructed rows into accounting-post detection.
    if dry_run:
        ledger_iterable = (
            (list(transactions.values()) if hasattr(transactions, "values") else list(transactions))
            + reconstructed
        )
    else:
        ledger_iterable = (
            list(transactions.values()) if hasattr(transactions, "values") else list(transactions)
        )

    for tx in ledger_iterable:
        if not isinstance(tx, dict):
            continue
        if _tx_type(tx) not in PREMIUM_CASH_TYPES:
            continue
        cid = str(tx.get("customer_id") or "")
        if exclude_customer and cid and exclude_customer(cid):
            continue
        amount = _tx_amount(tx)
        if amount <= 0:
            continue
        source_tx_id = str(tx.get("id") or tx.get("tx_id") or "").strip()
        meta = _tx_metadata(tx)
        bill_id = str(meta.get("bill_id") or tx.get("bill_id") or "").strip()
        policy = _policy_for_tx(tx, policies, billing)
        policy_id = str(
            (policy or {}).get("id")
            or meta.get("policy_id")
            or tx.get("policy_id")
            or ""
        )
        split = resolve_premium_split(amount, policy, fallback_risk_pct=100)
        if dry_run:
            # Approximate: already-posted is detected by the helper when applied.
            if engine is not None and _allocation_already_posted(engine, bill_id or f"UNBILLED-{source_tx_id}", source_tx_id):
                continue
            actions.append({
                "action": "post_premium_accounting",
                "bill_id": bill_id or f"UNBILLED-{source_tx_id}",
                "amount": float(amount),
                "source_tx_id": source_tx_id,
            })
            continue
        result = post_premium_to_accounting_book(
            bill_id=bill_id or f"UNBILLED-{source_tx_id or cid}",
            policy_id=policy_id,
            customer_id=cid,
            amount=amount,
            risk_percentage=split["risk_percentage"],
            posted_by=actor,
            source_tx_id=source_tx_id or None,
            notes=f"repair kernel_split={split['split_source']}",
            engine=engine,
        )
        if result.get("posted"):
            actions.append({
                "action": "post_premium_accounting",
                "bill_id": result.get("bill_id"),
                "amount": result.get("amount"),
                "source_tx_id": source_tx_id,
            })

    booked_claims = accounting_claim_ids(engine)
    for tx in ledger_iterable:
        if not isinstance(tx, dict):
            continue
        if _tx_type(tx) not in CLAIM_CASH_TYPES:
            continue
        cid = str(tx.get("customer_id") or "")
        if exclude_customer and cid and exclude_customer(cid):
            continue
        meta = _tx_metadata(tx)
        claim_id = str(meta.get("claim_id") or tx.get("claim_id") or "").strip()
        if not claim_id or claim_id in booked_claims:
            continue
        amount = _tx_amount(tx)
        if amount <= 0:
            continue
        policy_id = str(meta.get("policy_id") or tx.get("policy_id") or "")
        if not policy_id and claim_id in (claims or {}):
            policy_id = str((claims.get(claim_id) or {}).get("policy_id") or "")
        actions.append({
            "action": "post_claim_accounting",
            "claim_id": claim_id,
            "amount": float(amount),
        })
        if dry_run:
            continue
        posted = post_claim_to_accounting_book(
            claim_id=claim_id,
            policy_id=policy_id,
            customer_id=cid,
            amount=amount,
            paid_by=actor,
            engine=engine,
        )
        if posted.get("posted"):
            booked_claims.add(claim_id)

    if dry_run:
        ledger_iterable = (
            (list(transactions.values()) if hasattr(transactions, "values") else list(transactions))
            + reconstructed
        )
    else:
        ledger_iterable = (
            list(transactions.values()) if hasattr(transactions, "values") else list(transactions)
        )
    premium_total = money(
        ledger_cash_total(
            ledger_iterable, PREMIUM_CASH_TYPES, exclude_customer=exclude_customer
        )["total"]
    )
    claim_total = money(
        ledger_cash_total(
            ledger_iterable, CLAIM_CASH_TYPES, exclude_customer=exclude_customer
        )["total"]
    )
    derived = {}
    if balance_sheet is not None:
        current_premium = money(
            ((balance_sheet.get("revenue_breakdown") or {}) if isinstance(
                balance_sheet.get("revenue_breakdown"), dict
            ) else {}).get("premium_income", 0)
        )
        current_claims = money(
            ((balance_sheet.get("expense_breakdown") or {}) if isinstance(
                balance_sheet.get("expense_breakdown"), dict
            ) else {}).get("claims_paid", 0)
        )
        needs_derive = (
            (current_premium - premium_total).copy_abs() > TOLERANCE
            or (current_claims - claim_total).copy_abs() > TOLERANCE
        )
        if needs_derive:
            if dry_run:
                derived = {
                    "premium_income": float(premium_total),
                    "claims_paid": float(claim_total),
                }
            else:
                derived = apply_ledger_derived_balance_sheet(
                    balance_sheet, premium_total, claim_total
                )
            actions.append({
                "action": "derive_balance_sheet_from_ledger",
                "premium_income": derived.get("premium_income"),
                "claims_paid": derived.get("claims_paid"),
            })

    after = before
    if not dry_run:
        after = reconcile_financial_books(
            policies=policies,
            claims=claims,
            billing=billing,
            transactions=ledger_iterable,
            balance_sheet=balance_sheet,
            exclude_customer=exclude_customer,
            engine=engine,
            investment_accounts=investment_accounts,
            savings_pipeline_accounts=savings_pipeline_accounts,
        )

    return {
        "dry_run": bool(dry_run),
        "actions": actions,
        "action_count": len(actions),
        "before": before,
        "after": after,
        "is_consistent": after.get("is_consistent") if not dry_run else before.get("is_consistent") and not actions,
        "note": (
            "Repair reconstructs missing cash-identity rows from paid bills and "
            "paid claims, then posts the accounting book and derives General "
            "Reserves premium_income / claims_paid from the ledger. Historical "
            "annual_premium, bill amounts, and seed_claims_reserve are never rewritten."
        ),
    }


def _policy_status(policy: Dict[str, Any]) -> str:
    return str(policy.get("status") or "").strip().lower()


def _empty_bucket() -> Dict[str, Any]:
    return {"count": 0, "monthly_premium": Decimal("0.00"), "annual_premium": Decimal("0.00")}


def _add_to_bucket(bucket: Dict[str, Any], monthly: Decimal, annual: Decimal) -> None:
    bucket["count"] += 1
    bucket["monthly_premium"] += monthly
    bucket["annual_premium"] += annual


def _finalize_bucket(bucket: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "count": bucket["count"],
        "monthly_premium": float(bucket["monthly_premium"]),
        "annual_premium": float(bucket["annual_premium"]),
    }


def reconcile_premium_run_rate(
    policies: Iterable[Dict[str, Any]],
    *,
    exclude_customer: Optional[Any] = None,
    known_customer_ids: Optional[Iterable[str]] = None,
    expected_total_revenue: Optional[float] = None,
) -> Dict[str, Any]:
    """Tie the dashboard ``total_revenue`` to Sales Division premium sums.

    The admin dashboard "Total Revenue" is the *annual* premium run-rate of
    ``active`` policies on non-excluded (non-suspended) customers. The Sales
    Division report sums ``monthly_premium`` over every policy attached to a
    listed customer, regardless of status. Both are legitimate views of the
    same book; this function computes both from one pass over the policies
    and lists every reason they differ so they can be tied out to the cent:

    * period basis (annual vs monthly),
    * status basis (active vs all statuses / pipeline),
    * universe (dashboard counts orphaned policies whose customer record is
      missing; a customer-driven report cannot see them),
    * data integrity (``monthly_premium`` missing or not equal to
      ``round(annual_premium / 12, 2)``).

    Nothing is mutated and no discrepancy is silently absorbed: a missing
    monthly premium is derived from the annual figure *and* reported.
    """
    known_ids = set(known_customer_ids) if known_customer_ids is not None else None
    tolerance = TOLERANCE

    dashboard_active = _empty_bucket()
    report_active = _empty_bucket()
    report_pipeline = _empty_bucket()
    suspended = _empty_bucket()
    orphaned_active = _empty_bucket()
    orphaned_other = _empty_bucket()
    by_status: Dict[str, Dict[str, Any]] = {}

    missing_monthly: List[str] = []
    mismatches: List[Dict[str, Any]] = []
    orphaned_ids: List[str] = []

    for policy in policies:
        if not isinstance(policy, dict):
            continue
        policy_id = str(policy.get("id") or policy.get("policy_id") or "")
        customer_id = str(policy.get("customer_id") or "")
        status = _policy_status(policy)
        annual = money(policy.get("annual_premium", 0))
        raw_monthly = policy.get("monthly_premium")
        monthly_missing = raw_monthly in (None, "")
        monthly = money(raw_monthly) if not monthly_missing else money(annual / 12)

        if exclude_customer is not None and customer_id and exclude_customer(customer_id):
            _add_to_bucket(suspended, monthly, annual)
            continue

        if monthly_missing and annual != 0:
            missing_monthly.append(policy_id)
        elif not monthly_missing and annual != 0:
            expected_monthly = money(annual / 12)
            if (monthly - expected_monthly).copy_abs() > tolerance:
                mismatches.append({
                    "policy_id": policy_id,
                    "status": status,
                    "monthly_premium": float(monthly),
                    "annual_premium": float(annual),
                    "expected_monthly": float(expected_monthly),
                    "difference": float(monthly - expected_monthly),
                })

        is_active = status == "active"
        is_orphan = known_ids is not None and customer_id not in known_ids

        if is_active:
            _add_to_bucket(dashboard_active, monthly, annual)

        if is_orphan:
            orphaned_ids.append(policy_id)
            _add_to_bucket(orphaned_active if is_active else orphaned_other, monthly, annual)
            continue

        bucket = by_status.setdefault(status or "<blank>", _empty_bucket())
        _add_to_bucket(bucket, monthly, annual)
        _add_to_bucket(report_active if is_active else report_pipeline, monthly, annual)

    dashboard_total_revenue = dashboard_active["annual_premium"]
    dashboard_monthly_income = money(dashboard_total_revenue / 12) if dashboard_total_revenue else Decimal("0.00")
    report_all_monthly = report_active["monthly_premium"] + report_pipeline["monthly_premium"]
    report_all_annual = report_active["annual_premium"] + report_pipeline["annual_premium"]
    active_monthly_times_12 = dashboard_active["monthly_premium"] * 12
    rounding_drift = dashboard_total_revenue - active_monthly_times_12
    # Each active policy may carry up to half a cent of monthly rounding.
    rounding_allowance = Decimal("0.005") * 12 * dashboard_active["count"] + tolerance

    checks: List[Dict[str, Any]] = []

    if expected_total_revenue is not None:
        expected = money(expected_total_revenue)
        checks.append({
            "check": "active_annual_premium_equals_dashboard_total_revenue",
            "ok": (dashboard_total_revenue - expected).copy_abs() <= tolerance,
            "left": float(dashboard_total_revenue),
            "right": float(expected),
            "difference": _diff(dashboard_total_revenue, expected),
        })

    checks.append({
        "check": "active_monthly_premium_x12_matches_total_revenue_within_rounding",
        "ok": rounding_drift.copy_abs() <= rounding_allowance,
        "left": float(active_monthly_times_12),
        "right": float(dashboard_total_revenue),
        "difference": _diff(active_monthly_times_12, dashboard_total_revenue),
        "allowance": float(rounding_allowance),
    })
    checks.append({
        "check": "monthly_premium_equals_annual_premium_div_12",
        "ok": not mismatches,
        "violations": len(mismatches),
    })
    checks.append({
        "check": "monthly_premium_present_on_every_policy",
        "ok": not missing_monthly,
        "violations": len(missing_monthly),
    })
    checks.append({
        "check": "no_active_policies_without_customer_record",
        "ok": orphaned_active["count"] == 0,
        "violations": orphaned_active["count"],
    })

    bridge = [
        {
            "step": "sales_report_monthly_premium_all_statuses",
            "amount": float(report_all_monthly),
            "note": "Sales Division report: monthly_premium summed over every listed policy",
        },
        {
            "step": "less_pipeline_policies_not_active",
            "amount": float(-report_pipeline["monthly_premium"]),
            "note": "pending / draft / cancelled / other non-active statuses",
        },
        {
            "step": "plus_active_policies_without_customer_record",
            "amount": float(orphaned_active["monthly_premium"]),
            "note": "counted by the dashboard, invisible to a customer-driven report",
        },
        {
            "step": "active_monthly_premium_dashboard_universe",
            "amount": float(dashboard_active["monthly_premium"]),
            "note": "subtotal",
        },
        {
            "step": "times_12_annualize",
            "amount": float(active_monthly_times_12),
            "note": "dashboard Total Revenue is an annual run-rate",
        },
        {
            "step": "plus_rounding_drift",
            "amount": float(rounding_drift),
            "note": "monthly_premium is stored rounded to cents",
        },
        {
            "step": "dashboard_total_revenue",
            "amount": float(dashboard_total_revenue),
            "note": "sum of annual_premium on active, non-suspended policies",
        },
    ]

    return {
        "definitions": {
            "dashboard_total_revenue": "sum(annual_premium) for status=active, non-suspended customers",
            "dashboard_monthly_premium_income": "dashboard_total_revenue / 12",
            "sales_report_monthly_premium": "sum(monthly_premium) over all statuses for listed customers",
        },
        "tolerance": float(tolerance),
        "dashboard": {
            "total_revenue": float(dashboard_total_revenue),
            "monthly_premium_income": float(dashboard_monthly_income),
            "active_policies": dashboard_active["count"],
        },
        "sales_report": {
            "all_statuses": {
                "count": report_active["count"] + report_pipeline["count"],
                "monthly_premium": float(report_all_monthly),
                "annual_premium": float(report_all_annual),
            },
            "active": _finalize_bucket(report_active),
            "pipeline": _finalize_bucket(report_pipeline),
            "by_status": {k: _finalize_bucket(v) for k, v in sorted(by_status.items())},
        },
        "excluded_from_sales_report": {
            "suspended_customers": _finalize_bucket(suspended),
            "orphaned_active": _finalize_bucket(orphaned_active),
            "orphaned_other": _finalize_bucket(orphaned_other),
        },
        "bridge": bridge,
        "integrity": {
            "missing_monthly_premium": missing_monthly,
            "monthly_annual_mismatch": mismatches,
            "orphaned_policies": orphaned_ids,
        },
        "checks": checks,
        "is_consistent": all(c["ok"] for c in checks),
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
