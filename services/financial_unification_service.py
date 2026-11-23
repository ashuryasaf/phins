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
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

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


def _component_present(mapping: Any, *keys: str) -> bool:
    """True when a mapping carries a non-null value for one of ``keys``."""
    if not isinstance(mapping, dict):
        return False
    return any(key in mapping and mapping.get(key) is not None for key in keys)


def kernel_components_from_policy(policy: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Read pinned kernel components from a policy or its latest snapshot.

    Reads the pin. Does not reprice the life and does not invent expense or
    profit from the product registry.
    """
    policy = policy or {}
    risk = policy.get("risk_premium_annual")
    savings = policy.get("savings_premium_annual")
    if savings is None and _component_present(policy, "savings_premium"):
        savings = policy.get("savings_premium")
    annual = policy.get("annual_premium")
    source = "policy"
    integrity_hash = policy.get("integrity_hash")
    product_id = policy.get("product_id")
    pricing_source = policy.get("pricing_source")
    savings_pin_present = _component_present(
        policy, "savings_premium_annual", "savings_premium"
    )
    expense = policy.get("expense_loading_annual") if _component_present(
        policy, "expense_loading_annual"
    ) else None
    profit = policy.get("profit_margin_annual") if _component_present(
        policy, "profit_margin_annual"
    ) else None

    if risk is None or (money(annual) > 0 and money(risk) == 0 and money(savings or 0) == 0):
        try:
            from services.pricing_shadow_service import get_snapshots_for_policy

            snaps = get_snapshots_for_policy(str(policy.get("id") or ""))
            if snaps:
                latest = snaps[-1]
                components = latest.get("components") or {}
                risk = components.get("risk_premium_annual", latest.get("kernel_annual"))
                if _component_present(components, "savings_premium_annual"):
                    savings = components.get("savings_premium_annual")
                    savings_pin_present = True
                elif savings is None:
                    savings = 0
                annual = latest.get("kernel_annual") or annual
                if _component_present(components, "expense_loading_annual"):
                    expense = components.get("expense_loading_annual")
                if _component_present(components, "profit_margin_annual"):
                    profit = components.get("profit_margin_annual")
                integrity_hash = latest.get("integrity_hash") or integrity_hash
                product_id = latest.get("product_id") or product_id
                source = "premium_snapshot"
                pricing_source = "pricing_kernel"
        except Exception:
            pass

    return {
        "risk_premium_annual": money_float(risk, 0.0),
        "savings_premium_annual": money_float(savings, 0.0),
        "expense_loading_annual": None if expense is None else money_float(expense, 0.0),
        "profit_margin_annual": None if profit is None else money_float(profit, 0.0),
        "annual_premium": money_float(annual, 0.0),
        "savings_pin_present": savings_pin_present,
        "integrity_hash": integrity_hash,
        "product_id": product_id,
        "pricing_source": pricing_source or source,
        "source": source,
    }


_ADDON_RATES = {
    "none": Decimal("0"),
    "light": Decimal("0.25"),
    "balanced": Decimal("0.50"),
    "growth": Decimal("1"),
}
_LAYER_ORDER = ("risk", "underwriting_fee", "expense", "profit", "savings")


def _waterfall_cash(collected: Decimal, layers: Mapping[str, Decimal]) -> Dict[str, Decimal]:
    """Fill risk, then expense, then profit, then the savings add-on.

    A short payment leaves the later layers at zero. Risk is not reduced
    to keep a savings percentage. Cash above the stack is excess, not savings.
    """
    left = collected if collected > 0 else Decimal("0.00")
    landed: Dict[str, Decimal] = {}
    for name in _LAYER_ORDER:
        target = money(layers.get(name) or 0)
        if target < 0:
            target = Decimal("0.00")
        take = target if target <= left else left
        landed[name] = take
        left = (left - take).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    landed["excess"] = left if left > 0 else Decimal("0.00")
    return landed


def _scale_layers(layers: Mapping[str, Decimal], numerator: Decimal, denominator: Decimal) -> Dict[str, Decimal]:
    if denominator <= 0:
        return {name: Decimal("0.00") for name in _LAYER_ORDER}
    return {
        name: (money(layers.get(name) or 0) * numerator / denominator).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        for name in _LAYER_ORDER
    }


def _land_unfitted(collected: Decimal, annual_layers: Mapping[str, Decimal]) -> Dict[str, Decimal]:
    """Land cash when the annual pins do not fit the annual premium.

    A payment that matches a monthly, quarterly, or annual stack uses that
    stack. Any other amount fills whole months first, then waterfalls the
    remainder against one more month. A dollar over a finished month stays
    on the next month's risk and does not erase the add-on already earned.
    """
    for divisor in (12, 4, 1):
        scaled = _scale_layers(annual_layers, Decimal(1), Decimal(divisor))
        stack = sum((scaled[name] for name in _LAYER_ORDER), Decimal("0.00"))
        if abs(collected - stack) <= Decimal("0.01"):
            return _waterfall_cash(collected, scaled)
    monthly = _scale_layers(annual_layers, Decimal(1), Decimal(12))
    month_stack = sum((monthly[name] for name in _LAYER_ORDER), Decimal("0.00"))
    if month_stack <= 0:
        return _waterfall_cash(
            collected,
            {name: money(annual_layers.get(name) or 0) for name in _LAYER_ORDER},
        )
    landed = {name: Decimal("0.00") for name in (*_LAYER_ORDER, "excess")}
    left = collected
    whole = (left / month_stack).to_integral_value(rounding=ROUND_DOWN)
    if whole > 0:
        step = _waterfall_cash(month_stack, monthly)
        for name in _LAYER_ORDER:
            landed[name] = (step[name] * whole).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        left = (left - month_stack * whole).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rest = _waterfall_cash(left, monthly)
    for name in (*_LAYER_ORDER, "excess"):
        landed[name] = (landed[name] + rest[name]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return landed


def _elected_savings(policy: Optional[Dict[str, Any]], kernel: Mapping[str, Any]) -> Tuple[Decimal, str, str]:
    """Savings add-on only. The kernel risk premium is never elected as savings.

    A stored savings pin wins. Otherwise ``savings_addon`` (light, balanced,
    growth) or ``savings_rate`` prices the add-on as a multiple of the risk
    premium. No election means no savings.
    """
    if kernel.get("savings_pin_present"):
        return (
            money(kernel.get("savings_premium_annual")),
            "kernel",
            f"kernel:{kernel.get('source') or 'policy'}",
        )
    policy = policy or {}
    addon = str(policy.get("savings_addon") or "").strip().lower()
    risk = money(kernel.get("risk_premium_annual"))
    if addon in _ADDON_RATES:
        rate = _ADDON_RATES[addon]
        if rate <= 0:
            return Decimal("0.00"), "no_savings_election", "no_savings_election"
        label = "growth" if addon == "growth" else "addon"
        return (risk * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), label, f"addon:{addon}"
    if policy.get("savings_rate") is not None:
        rate = money(policy.get("savings_rate"))
        if rate <= 0:
            return Decimal("0.00"), "no_savings_election", "no_savings_election"
        label = "growth" if rate >= 1 else "addon"
        source = "addon:growth" if rate >= 1 else "addon:rate"
        return (risk * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), label, source
    return Decimal("0.00"), "no_savings_election", "no_savings_election"


def _loading_fraction(value: Any) -> Decimal:
    """A loading may be stored as 0.35 or as 35. Zero and junk are no fee."""
    try:
        number = Decimal(str(value))
    except Exception:
        return Decimal("0")
    if not number.is_finite() or number <= 0:
        return Decimal("0")
    if number >= 1:
        number = number / Decimal("100")
    return number


def underwriting_fee_annual(policy: Optional[Dict[str, Any]], kernel: Optional[Mapping[str, Any]] = None) -> Decimal:
    """Company fee from an underwriting decision. It is not a savings add-on.

    The chat quote already folds ``underwriting_loading`` into the kernel risk
    pin. When the pins sum to the annual premium, the fee is already inside
    risk and is not charged again. A later decision that grossed the bill up
    leaves the extra as this fee. An earlier sealed savings allocation is not
    read and is not changed here.
    """
    policy = policy or {}
    if policy.get("underwriting_fee_annual") is not None:
        return money(policy.get("underwriting_fee_annual"))
    kernel = kernel or {}
    fraction = _loading_fraction(
        policy.get("underwriting_loading")
        if policy.get("underwriting_loading") is not None
        else policy.get("premium_adjustment")
    )
    if fraction <= 0:
        return Decimal("0.00")
    risk = money(kernel.get("risk_premium_annual"))
    annual = money(kernel.get("annual_premium"))
    expense = (
        money(kernel.get("expense_loading_annual"))
        if kernel.get("expense_loading_annual") is not None
        else Decimal("0.00")
    )
    profit = (
        money(kernel.get("profit_margin_annual"))
        if kernel.get("profit_margin_annual") is not None
        else Decimal("0.00")
    )
    savings = money(kernel.get("savings_premium_annual")) if kernel.get("savings_pin_present") else Decimal("0.00")
    explained = risk + expense + profit + savings
    if annual > 0 and abs(explained - annual) <= Decimal("0.05"):
        return Decimal("0.00")
    chat_priced = (
        str(policy.get("allocation_version") or "").strip().lower() in ("chat", "kernel")
        or str(policy.get("application_channel") or "").strip().lower() == "chat"
        or bool(str(policy.get("savings_addon") or "").strip())
    )
    actuarial = policy.get("actuarial_annual_premium")
    if actuarial is not None and annual > money(actuarial) > 0:
        return (annual - money(actuarial)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    # The application chat folds the loading into the kernel risk pin.
    # Do not charge that loading a second time when no gross-up was stored.
    if chat_priced:
        return Decimal("0.00")
    if risk > 0:
        return (risk * fraction).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return Decimal("0.00")


def legacy_annual_layers(
    policy: Optional[Dict[str, Any]],
    kernel: Optional[Mapping[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """An earlier contract's risk and savings percentages.

    A chat application, a kernel pin, or ``allocation_version`` of ``chat``
    or ``kernel`` uses the current waterfall instead. The stored percentages
    apply to the pre-fee premium. An underwriting fee is not given a share
    of that older split.
    """
    if not isinstance(policy, dict):
        return None
    version = str(policy.get("allocation_version") or "").strip().lower()
    if version in ("chat", "kernel"):
        return None
    if str(policy.get("application_channel") or "").strip().lower() == "chat":
        return None
    if str(policy.get("savings_addon") or "").strip():
        return None
    kernel = kernel or {}
    if kernel.get("savings_pin_present"):
        return None
    if money(kernel.get("risk_premium_annual")) > 0 and str(
        policy.get("pricing_source") or ""
    ) == "pricing_kernel":
        return None
    try:
        risk_pct = Decimal(str(policy.get("risk_allocation")))
        savings_pct = Decimal(str(policy.get("savings_allocation")))
    except Exception:
        return None
    if savings_pct <= 0 or abs((risk_pct + savings_pct) - Decimal("100")) > Decimal("0.6"):
        return None
    annual = money(kernel.get("annual_premium") if kernel.get("annual_premium") is not None else policy.get("annual_premium"))
    fee = underwriting_fee_annual(policy, kernel)
    actuarial = policy.get("actuarial_annual_premium")
    if actuarial is not None:
        base = money(actuarial)
    elif fee > 0 and annual > fee:
        base = (annual - fee).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        base = annual
    savings = (base * savings_pct / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    risk = (base - savings).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if risk < 0:
        risk = Decimal("0.00")
    return {
        "risk": risk,
        "underwriting_fee": fee,
        "expense": Decimal("0.00"),
        "profit": Decimal("0.00"),
        "savings": savings,
        "split_label": "historical",
        "split_source": "historical",
    }


_LAYER_AMOUNT_KEYS = (
    "risk_amount",
    "underwriting_fee_amount",
    "savings_amount",
    "expense_amount",
    "profit_amount",
    "company_remainder",
)


def partition_money(total: Any, weights: Sequence[Tuple[str, Any]]) -> Dict[str, float]:
    """Split cash across named weights. The parts sum to the total, to the cent."""
    collected = money(total)
    parsed: List[Tuple[str, Decimal]] = []
    weight_sum = Decimal("0")
    for name, weight in weights:
        part = money(weight)
        parsed.append((str(name), part))
        weight_sum += part
    if collected == 0 or weight_sum <= 0:
        return {name: 0.0 for name, _ in parsed}
    cents = int((collected * 100).to_integral_value(rounding=ROUND_HALF_UP))
    floors: List[List[Any]] = []
    used = 0
    for name, weight in parsed:
        amount = collected * weight / weight_sum
        truncated = int(amount * 100)
        floors.append([name, truncated, amount * 100 - Decimal(truncated)])
        used += truncated
    remainder = cents - used
    order = sorted(range(len(floors)), key=lambda i: (floors[i][2], -i), reverse=True)
    step = 1 if remainder > 0 else -1
    left = abs(remainder)
    cursor = 0
    while left > 0 and floors:
        slot = order[cursor % len(order)]
        floors[slot][1] += step
        left -= 1
        cursor += 1
    return {name: float(Decimal(part_cents) / Decimal(100)) for name, part_cents, _ in floors}


def collected_layer_delta(
    previous_paid: Any,
    new_paid: Any,
    policy: Optional[Dict[str, Any]] = None,
    stored: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Change in the waterfall between two collected totals on one bill.

    Stored paid layers win once they are non-zero. Cash that was collected
    without those layers uses the waterfall of the earlier total, so a second
    installment does not start the stack over and does not count the first
    installment again.
    """
    after = resolve_premium_split(new_paid, policy)
    stored = stored or {}
    stored_risk = stored.get("risk_amount_paid")
    stored_savings = stored.get("savings_amount_paid")
    stored_used = (
        stored_risk not in (None, "") or stored_savings not in (None, "")
    ) and (float(stored_risk or 0) != 0 or float(stored_savings or 0) != 0)
    if stored_used:
        prior = {
            "risk_amount": float(stored_risk or 0),
            "underwriting_fee_amount": float(stored.get("underwriting_fee_amount_paid") or 0),
            "savings_amount": float(stored_savings or 0),
            "expense_amount": float(stored.get("expense_amount_paid") or 0),
            "profit_amount": float(stored.get("profit_amount_paid") or 0),
            "company_remainder": float(stored.get("company_remainder_paid") or 0),
        }
    elif money(previous_paid) > 0:
        before = resolve_premium_split(previous_paid, policy)
        prior = {key: float(before[key]) for key in _LAYER_AMOUNT_KEYS}
    else:
        prior = {key: 0.0 for key in _LAYER_AMOUNT_KEYS}
    delta = {key: round(float(after[key]) - prior[key], 2) for key in _LAYER_AMOUNT_KEYS}
    delta["after"] = after
    return delta


def resolve_premium_split(
    amount: Any,
    policy: Optional[Dict[str, Any]] = None,
    fallback_risk_pct: Any = 100,
) -> Dict[str, Any]:
    """Split collected premium into risk, savings, expense, and profit.

    The kernel risk premium is filled first and is never credited as savings.
    An underwriting fee (a decision such as +35%) is filled next and stays
    on the company book. Only a savings pin, a savings add-on, or a growth
    add is savings. Expense and profit stay on the company book. A missing
    election is pure risk: the old 50/50 carve is not applied.
    ``fallback_risk_pct`` is ignored. A policy that already carries an
    earlier risk and savings percentage keeps that contract. A chat
    application or a kernel pin uses the waterfall instead.

    A consistent annual pin is shared across the cash in the same proportions,
    so a full installment still lands its add-on. When the pins do not fit
    the annual premium, or the payment is short of that installment, later
    layers wait. Risk is not scaled down to manufacture savings. The four
    credits never exceed the cash collected.
    """
    del fallback_risk_pct  # retained so existing callers keep working
    collected = money(amount)
    kernel = kernel_components_from_policy(policy)
    savings_annual, split_label, source = _elected_savings(policy, kernel)
    risk_annual = money(kernel.get("risk_premium_annual"))
    fee_annual = underwriting_fee_annual(policy, kernel)
    expense_annual = (
        money(kernel.get("expense_loading_annual"))
        if kernel.get("expense_loading_annual") is not None
        else Decimal("0.00")
    )
    profit_annual = (
        money(kernel.get("profit_margin_annual"))
        if kernel.get("profit_margin_annual") is not None
        else Decimal("0.00")
    )
    annual_layers = {
        "risk": risk_annual,
        "underwriting_fee": fee_annual,
        "expense": expense_annual,
        "profit": profit_annual,
        "savings": savings_annual,
    }
    annual = money(kernel.get("annual_premium"))
    legacy = legacy_annual_layers(policy, kernel)
    if legacy is not None:
        split_label = str(legacy.pop("split_label"))
        source = str(legacy.pop("split_source"))
        annual_layers = legacy
        fee_annual = money(annual_layers.get("underwriting_fee"))
    stack = sum(annual_layers.values(), Decimal("0.00"))
    pinned_loadings = (
        kernel.get("expense_loading_annual") is not None
        or kernel.get("profit_margin_annual") is not None
        or kernel.get("savings_pin_present")
        or split_label in ("addon", "growth", "historical")
        or fee_annual > 0
    )
    if collected <= 0:
        landed = {name: Decimal("0.00") for name in _LAYER_ORDER}
        landed["excess"] = Decimal("0.00")
    elif not pinned_loadings:
        # The premium collected is the risk key. None of it is savings.
        landed = {
            "risk": collected,
            "underwriting_fee": Decimal("0.00"),
            "expense": Decimal("0.00"),
            "profit": Decimal("0.00"),
            "savings": Decimal("0.00"),
            "excess": Decimal("0.00"),
        }
    elif annual > 0 and abs(stack - annual) <= Decimal("0.01"):
        # The pins explain the whole annual premium, so the cash is shared in
        # those proportions to the cent. Rounding each layer on its own would
        # leave a cent over, or take it from the add-on at the end of the line.
        shares = partition_money(
            collected, [(name, annual_layers[name]) for name in _LAYER_ORDER]
        )
        landed = {name: money(shares[name]) for name in _LAYER_ORDER}
        landed["excess"] = Decimal("0.00")
    elif annual > 0 and stack <= annual + Decimal("0.01"):
        targets = _scale_layers(annual_layers, collected, annual)
        landed = _waterfall_cash(collected, targets)
    else:
        landed = _land_unfitted(collected, annual_layers)
    risk_amount = landed["risk"]
    fee_amount = landed["underwriting_fee"]
    savings_amount = landed["savings"]
    expense_amount = landed["expense"]
    profit_amount = landed["profit"]
    if collected > 0:
        risk_pct = (risk_amount / collected * Decimal("100")).quantize(Decimal("0.01"))
        savings_pct = (savings_amount / collected * Decimal("100")).quantize(Decimal("0.01"))
    else:
        risk_pct = Decimal("0.00")
        savings_pct = Decimal("0.00")
    company_remainder = money(landed["excess"])
    return {
        "amount": float(collected),
        "risk_percentage": float(risk_pct),
        "savings_percentage": float(savings_pct),
        "risk_amount": float(risk_amount),
        "underwriting_fee_amount": float(fee_amount),
        "savings_amount": float(savings_amount),
        "expense_amount": float(expense_amount),
        "profit_amount": float(profit_amount),
        "company_remainder": float(company_remainder),
        "split_source": source,
        "split_label": split_label,
        "integrity_hash": kernel.get("integrity_hash"),
        "product_id": kernel.get("product_id"),
        "pricing_source": kernel.get("pricing_source"),
    }


def _allocation_is_reversed(alloc: Any) -> bool:
    status = getattr(alloc, "status", None)
    return str(getattr(status, "name", status) or "").upper() == "REVERSED"


def _matching_allocation(engine: Any, bill_id: str, source_tx_id: Optional[str]) -> Any:
    """The allocation that already carries this cash slice, or ``None``.

    Key is (bill_id, source_tx_id). The same bill can receive several
    partial payments — each ledger tx must post. Missing source_tx_id
    falls back to bill_id only so a retry without a tx id stays idempotent.

    If the same ledger tx was booked as ``UNBILLED-{tx}`` (bills missing at
    post time), a later real ``bill_id`` for that tx must not post again.

    A reversed allocation no longer carries the cash, so it does not match.
    """
    allocations = getattr(engine, "allocations", {}) or {}
    wanted_bill = str(bill_id or "")
    marker = f"ledger_tx={source_tx_id}" if source_tx_id else ""
    unbilled_key = f"UNBILLED-{source_tx_id}" if source_tx_id else ""
    for alloc in allocations.values():
        if _allocation_is_reversed(alloc):
            continue
        alloc_bill = str(getattr(alloc, "bill_id", "") or "")
        notes = str(getattr(alloc, "notes", "") or "")
        if unbilled_key and alloc_bill == unbilled_key and marker in notes:
            return alloc
        if not wanted_bill or alloc_bill != wanted_bill:
            continue
        if source_tx_id:
            if marker in notes:
                return alloc
            continue
        return alloc
    return None


def _allocation_already_posted(engine: Any, bill_id: str, source_tx_id: Optional[str]) -> bool:
    """True when this cash slice is already on the book."""
    return _matching_allocation(engine, bill_id, source_tx_id) is not None


def post_premium_to_accounting_book(
    *,
    bill_id: str,
    policy_id: str,
    customer_id: str,
    amount: Any,
    risk_percentage: Any,
    savings_percentage: Any = None,
    posted_by: str = "billing_system",
    source_tx_id: Optional[str] = None,
    notes: str = "",
    engine: Any = None,
    risk_amount: Any = None,
    savings_amount: Any = None,
) -> Dict[str, Any]:
    """Idempotently post a collected premium into the shared accounting book.

    ``risk_amount`` and ``savings_amount`` are the cents the split landed.
    Given together, the book carries those cents and not a rounded percentage.
    """
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
        savings_arg = None
        if savings_percentage is not None:
            savings_arg = Decimal(str(savings_percentage))
        allocation = engine.create_allocation(
            bill_id=bill_id or source_tx_id or "UNBILLED",
            policy_id=policy_id or "UNKNOWN",
            customer_id=customer_id,
            total_premium=collected,
            risk_percentage=Decimal(str(risk_percentage)),
            allocation_notes="; ".join(note_bits),
            savings_percentage=savings_arg,
            **(
                {
                    "risk_amount": money(risk_amount),
                    "savings_amount": money(savings_amount),
                }
                if risk_amount is not None and savings_amount is not None
                else {}
            ),
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
    risk_percentage: Any = None,
    savings_percentage: Any = None,
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
        if risk_percentage is not None and savings_percentage is not None:
            # This slice is the change in the running waterfall, not a new stack.
            bill_split = {
                "risk_percentage": float(risk_percentage),
                "savings_percentage": float(savings_percentage),
                "split_source": "payment_delta",
            }
        else:
            bill_split = resolve_premium_split(bill_amount, policy, split["risk_percentage"])
        results.append(
            post_premium_to_accounting_book(
                bill_id=str(bill.get("id") or bill_id),
                policy_id=str(bill.get("policy_id") or policy_id or ""),
                customer_id=customer_id,
                amount=bill_amount,
                risk_percentage=bill_split["risk_percentage"],
                savings_percentage=bill_split["savings_percentage"],
                source_tx_id=source_tx_id,
                notes=f"kernel_split={bill_split['split_source']}",
                engine=engine,
                risk_amount=bill_split.get("risk_amount"),
                savings_amount=bill_split.get("savings_amount"),
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
                savings_percentage=leftover_split["savings_percentage"],
                source_tx_id=source_tx_id,
                notes=f"unbilled kernel_split={leftover_split['split_source']}",
                engine=engine,
                risk_amount=leftover_split.get("risk_amount"),
                savings_amount=leftover_split.get("savings_amount"),
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


def ledger_derived_balance_sheet_view(
    balance_sheet: Optional[Dict[str, Any]],
    ledger_premium: Any,
    ledger_claims: Any,
) -> Dict[str, Any]:
    """Return a GET-safe copy of the General Reserves sheet derived from ledger cash.

    Does not mutate the stored ``PHINS_BALANCE_SHEET``. Seed capital is
    copied, never rewritten.
    """
    source = balance_sheet if isinstance(balance_sheet, dict) else {}
    view = dict(source)
    revenue = source.get("revenue_breakdown")
    expense = source.get("expense_breakdown")
    view["revenue_breakdown"] = dict(revenue) if isinstance(revenue, dict) else {}
    view["expense_breakdown"] = dict(expense) if isinstance(expense, dict) else {}
    apply_ledger_derived_balance_sheet(view, ledger_premium, ledger_claims)
    return view


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


def premium_revenue_rows_on_sheet(balance_sheet: Optional[Mapping[str, Any]]) -> Decimal:
    """Premium the stored sheet added, in full, to its operating counter.

    Every ``revenue`` row raises ``operating_reserve`` by its whole amount,
    so the premium rows are exactly what that counter took in from premiums.
    """
    total = Decimal("0.00")
    rows = (balance_sheet or {}).get("transactions") if isinstance(balance_sheet, Mapping) else None
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("type") or "") != "revenue":
            continue
        if str(row.get("category") or "") != "premium_income":
            continue
        total += money(row.get("amount"))
    return total


def premium_cash_position(
    *,
    transactions: Iterable[Dict[str, Any]],
    policies: Optional[Dict[str, Any]] = None,
    billing: Optional[Dict[str, Any]] = None,
    engine: Any = None,
    exclude_customer: Optional[Any] = None,
    balance_sheet: Optional[Mapping[str, Any]] = None,
    with_accounting_book: bool = True,
) -> Dict[str, Any]:
    """Where collected premium cash sits, by the book that holds it.

    One reading of the customer ledger through the kernel pins. Kernel risk,
    and premium on a policy with no pin, is the claims reserve once claim
    cash is taken off. The underwriting fee, the PHINS share of the expense
    loading, the profit margin, and cash above a pinned stack are the
    company's. The savings add-on is the customers' money. The carrier share
    and the reinsurance ceding reserve are held for those parties. The lines
    add up to premium cash less claim cash.

    With ``balance_sheet``, the operating reserve is restated: the stored
    counter took in every premium whole, so those rows come off and the
    company's own part of the premium goes on. Nothing is written.
    """
    from services.premium_flow_reconciliation import _EXPENSE_WEIGHTS, _partition

    rows = [tx for tx in transactions if isinstance(tx, dict)]
    split = kernel_savings_cash_from_ledger(
        rows, policies, billing, exclude_customer=exclude_customer
    )
    streams = {name: money(value) for name, value in (split.get("streams") or {}).items()}
    premium_cash = money(
        ledger_cash_total(rows, PREMIUM_CASH_TYPES, exclude_customer=exclude_customer)["total"]
    )
    claim_cash = money(
        ledger_cash_total(rows, CLAIM_CASH_TYPES, exclude_customer=exclude_customer)["total"]
    )
    risk = streams.get("risk", Decimal("0.00"))
    unpinned = money((split.get("without_kernel_pin") or {}).get("booked_as_risk"))
    fee = streams.get("underwriting_fee", Decimal("0.00"))
    expense = streams.get("expense_loading", Decimal("0.00"))
    profit = streams.get("profit", Decimal("0.00"))
    savings = streams.get("savings", Decimal("0.00"))
    above = streams.get("above_kernel_stack", Decimal("0.00"))
    shares = {name: money(value) for name, value in _partition(expense, _EXPENSE_WEIGHTS).items()}
    operations = shares.get("phins_operations", Decimal("0.00"))
    carrier = shares.get("carrier_share", Decimal("0.00"))
    ceding = shares.get("reinsurance_ceding_reserve", Decimal("0.00"))

    claims_reserve = risk - claim_cash
    company = fee + operations + profit + above
    held_for_others = savings + carrier + ceding
    own_funds = claims_reserve + company
    net_cash = premium_cash - claim_cash
    total = own_funds + held_for_others


    lines = [
        {
            "key": "claims_reserve",
            "label": "Claims reserve · kernel risk premium less claims paid",
            "holder": "risk book",
            "amount": float(claims_reserve),
        },
        {
            "key": "company",
            "label": "Operating reserve · fee, PHINS share of the expense loading, profit margin",
            "holder": "company",
            "amount": float(company),
        },
        {
            "key": "customer_savings",
            "label": "Held for customers · savings add-on",
            "holder": "customers",
            "amount": float(savings),
        },
        {
            "key": "carrier_share",
            "label": "Held for the carrier · share of the expense loading",
            "holder": "carrier",
            "amount": float(carrier),
        },
        {
            "key": "reinsurance_ceding_reserve",
            "label": "Reinsurance ceding reserve",
            "holder": "reinsurance",
            "amount": float(ceding),
        },
    ]
    position: Dict[str, Any] = {
        "premium_cash": float(premium_cash),
        "claim_cash": float(claim_cash),
        "net_cash": float(net_cash),
        "risk_premium": float(risk - unpinned),
        "premium_without_kernel_pin": float(unpinned),
        "claims_reserve": float(claims_reserve),
        "company_income": float(company),
        "company_lines": {
            "underwriting_fee": float(fee),
            "phins_operations": float(operations),
            "profit": float(profit),
            "above_kernel_stack": float(above),
        },
        "customer_savings": float(savings),
        "carrier_share": float(carrier),
        "reinsurance_ceding_reserve": float(ceding),
        "own_funds": float(own_funds),
        "held_for_others": float(held_for_others),
        "total": float(total),
        "difference": _diff(total, net_cash),
        "ties_to_cash": (total - net_cash).copy_abs() <= TOLERANCE,
        "lines": lines,
        "identity": "premium_cash_less_claim_cash",
    }
    if with_accounting_book:
        # The sheet shows the reserve the accounting book carries. A posting
        # split before its policy was pinned can leave the two apart until
        # the repair re-books it; each posting may round by a cent.
        economic = economic_claims_reserve(
            transactions=rows, policies=policies, engine=engine, exclude_customer=exclude_customer
        )
        book_reserve = money(economic["economic_claims_reserve"])
        book = accounting_book_totals(engine, exclude_customer=exclude_customer)
        rounding = TOLERANCE * max(1, int(book.get("allocation_count") or 0))
        position["accounting_book_claims_reserve"] = float(book_reserve)
        position["reserve_difference"] = _diff(book_reserve, claims_reserve)
        position["reserve_ties_to_book"] = (book_reserve - claims_reserve).copy_abs() <= rounding
    if isinstance(balance_sheet, Mapping):
        stored = money(balance_sheet.get("operating_reserve"))
        premium_rows = premium_revenue_rows_on_sheet(balance_sheet)
        position["operating_reserve"] = {
            "stored": float(stored),
            "premium_taken_in_whole": float(premium_rows),
            "company_part_of_premium": float(company),
            "restated": float(stored - premium_rows + company),
        }
    return position


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
        # Only an unambiguous owner can lend its kernel split to this cash.
        # With several policies on the customer, guessing one would apply
        # another policy's risk/savings pin to this row.
        owned = [
            policy
            for policy in policies.values()
            if isinstance(policy, dict) and str(policy.get("customer_id") or "") == customer_id
        ]
        if len(owned) == 1:
            return owned[0]
    return None


# Where one premium dollar can land. The six streams add up to the cash.
_STREAM_KEYS = {
    "risk": "risk_amount",
    "underwriting_fee": "underwriting_fee_amount",
    "expense_loading": "expense_amount",
    "profit": "profit_amount",
    "savings": "savings_amount",
    "above_kernel_stack": "company_remainder",
}


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
    streams = {name: Decimal("0.00") for name in _STREAM_KEYS}
    savings_by_customer: Dict[str, Decimal] = {}
    unpinned_cash = Decimal("0.00")
    unpinned_risk = Decimal("0.00")
    unpinned_ids: List[str] = []
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
        if isinstance(policy, dict) and split.get("split_label") != "historical" and (
            policy.get("risk_premium_annual") is None and policy.get("risk_premium") is None
        ):
            # No kernel pin: the writer books this cash as risk because it
            # has nothing else to go on. It is counted so it can be seen.
            unpinned_cash += money(amount)
            unpinned_risk += money(split["risk_amount"])
            policy_id = str(policy.get("id") or policy.get("policy_id") or "")
            if policy_id and policy_id not in unpinned_ids:
                unpinned_ids.append(policy_id)
        for name, key in _STREAM_KEYS.items():
            streams[name] += money(split.get(key))
        if money(split["savings_amount"]) > 0:
            savings_by_customer[cid] = savings_by_customer.get(cid, Decimal("0.00")) + money(
                split["savings_amount"]
            )
        count += 1
    return {
        "risk_amount": float(risk),
        "savings_amount": float(savings),
        "premium_count": count,
        "streams": {name: float(value) for name, value in streams.items()},
        "savings_by_customer": {cid: float(value) for cid, value in savings_by_customer.items()},
        "without_kernel_pin": {
            "premium_cash": float(unpinned_cash),
            "booked_as_risk": float(unpinned_risk),
            "policy_count": len(unpinned_ids),
            "policy_ids": unpinned_ids[:25],
        },
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
    savings_landed_by_customer: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Tie kernel savings cash to the accounting book and portfolio deposits.

    ``savings_landed_by_customer`` is what each customer's health wallet,
    investments, and algo already hold from premium savings. With it the
    comparison is made customer by customer, which is where the money sits
    once the pipeline has allocated it 30/65/5. Without it only tagged
    investment deposits and unallocated pipeline cash are visible.
    """
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
    savings_cash = money(ledger_split["savings_amount"])
    unlanded_customers: List[Dict[str, Any]] = []
    if savings_landed_by_customer is not None:
        landed = Decimal("0.00")
        unlanded = Decimal("0.00")
        for cid, charged in sorted(ledger_split["savings_by_customer"].items()):
            charged_cash = money(charged)
            held = money(savings_landed_by_customer.get(cid) or 0)
            counted = held if held < charged_cash else charged_cash
            landed += counted
            gap = charged_cash - counted
            if gap > TOLERANCE:
                unlanded += gap
                unlanded_customers.append({
                    "customer_id": cid,
                    "savings_charged": float(charged_cash),
                    "savings_landed": float(counted),
                    "not_landed": float(gap),
                })
        landed_basis = "customer_books"
    else:
        landed = money(investments["premium_allocations"]) + money(pipeline["cash_balance"])
        unlanded = max(Decimal("0.00"), savings_cash - landed)
        landed_basis = "tagged_deposits"
    return {
        "kernel_savings_cash": ledger_split["savings_amount"],
        "kernel_risk_cash": ledger_split["risk_amount"],
        "streams": ledger_split["streams"],
        "without_kernel_pin": ledger_split["without_kernel_pin"],
        "accounting_savings_posted": book.get("savings_posted", 0.0),
        "investment_premium_allocations": investments["premium_allocations"],
        "investment_aum": investments["aum_balance"],
        "pipeline_cash": pipeline["cash_balance"],
        "savings_landed": float(landed),
        "savings_landed_basis": landed_basis,
        "unlanded_savings_cash": float(unlanded),
        "unlanded_customers": unlanded_customers,
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
    savings_landed_by_customer: Optional[Mapping[str, Any]] = None,
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
        savings_landed_by_customer=savings_landed_by_customer,
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
    if savings_landed_by_customer is not None:
        if money(savings_books["unlanded_savings_cash"]) > TOLERANCE:
            discrepancies.append({
                "check": "savings_cash_not_landed_in_portfolios",
                "description": (
                    "Savings add-on cash was collected and is not on that "
                    "customer's health wallet, investments, or algo"
                ),
                "left": float(savings_cash),
                "right": float(savings_landed),
                "difference": _diff(savings_cash, savings_landed),
                "customers": savings_books["unlanded_customers"][:50],
                "count": len(savings_books["unlanded_customers"]),
            })
    elif (
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

    # The accounting book splits a premium when the cash is posted. When the
    # policy pin changes afterwards (a restored pin, a reprice) the book still
    # carries the earlier split until the repair re-books it. Compared only
    # when the premium totals tie, so a missing posting is reported once.
    # Each posting may round by a cent.
    book_premium = money(book["premium_posted"])
    if (book_premium - ledger_premium).copy_abs() <= TOLERANCE and book_premium > 0:
        rounding = TOLERANCE * max(1, int(book.get("allocation_count") or 0))
        book_risk = money(book.get("risk_posted", 0))
        book_savings = money(book.get("savings_posted", 0))
        ledger_risk = money(savings_books["kernel_risk_cash"])
        if (
            (book_risk - ledger_risk).copy_abs() > rounding
            or (book_savings - savings_cash).copy_abs() > rounding
        ):
            discrepancies.append({
                "check": "accounting_book_split_vs_kernel_pins",
                "description": (
                    "The accounting book's risk and savings split of premium "
                    "cash differs from the kernel pins now on the policies. "
                    "Repair re-books the split; no premium or customer balance moves"
                ),
                "left": float(book_savings),
                "right": float(savings_cash),
                "difference": _diff(book_savings, savings_cash),
                "book": {"risk": float(book_risk), "savings": float(book_savings)},
                "kernel": {"risk": float(ledger_risk), "savings": float(savings_cash)},
            })

    seed = ensure_seed_claims_reserve(bs) if bs else float(bs_reserve)

    # The books can tie while a premium is still unexplained. That is a
    # warning beside the totals: it does not move a book out of balance.
    warnings: List[Dict[str, Any]] = []
    unpinned = savings_books.get("without_kernel_pin") or {}
    if money(unpinned.get("premium_cash")) > TOLERANCE:
        warnings.append({
            "check": "premium_cash_without_kernel_pin",
            "description": (
                "Premium cash was collected on policies that carry no kernel "
                "pin, so it is booked as risk and is not split into streams"
            ),
            "amount": float(money(unpinned.get("premium_cash"))),
            "policy_count": int(unpinned.get("policy_count") or 0),
            "policy_ids": list(unpinned.get("policy_ids") or []),
        })
    above_stack = money((savings_books.get("streams") or {}).get("above_kernel_stack"))
    if above_stack > TOLERANCE:
        warnings.append({
            "check": "premium_cash_above_kernel_stack",
            "description": (
                "Premium cash was collected above the pinned kernel stack "
                "and stays on the company book"
            ),
            "amount": float(above_stack),
        })

    # Cash on a policy with no pin sits on the risk book only because the
    # writer has nothing else to go on. It is shown as its own stream.
    premium_streams = dict(savings_books.get("streams") or {})
    unpinned_as_risk = money(unpinned.get("booked_as_risk"))
    premium_streams["risk"] = float(money(premium_streams.get("risk")) - unpinned_as_risk)
    premium_streams["without_kernel_pin"] = float(unpinned_as_risk)

    return {
        "is_consistent": len(discrepancies) == 0,
        "warnings": warnings,
        "premium_streams": premium_streams,
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


def reconstruct_accounting_book_from_ledger(
    *,
    policies: Dict[str, Any],
    claims: Dict[str, Any],
    billing: Dict[str, Any],
    transactions: Any,
    exclude_customer: Optional[Any] = None,
    engine: Any = None,
    dry_run: bool = False,
    actor: str = "boot_reconstruct",
) -> Dict[str, Any]:
    """Post missing accounting-book entries from existing customer-ledger cash.

    Used on boot so the in-memory accounting engine matches the durable
    ledger without waiting for a GET. Does not append ledger rows, does
    not rewrite billed premiums, and does not mutate the stored balance
    sheet. Idempotent.
    """
    if engine is None:
        try:
            from accounting_engine import get_accounting_engine

            engine = get_accounting_engine()
        except Exception:
            engine = None

    ledger_iterable = (
        list(transactions.values()) if hasattr(transactions, "values") else list(transactions)
    )
    actions: List[Dict[str, Any]] = []
    posted_count = 0

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
            if engine is not None and _allocation_already_posted(
                engine, bill_id or f"UNBILLED-{source_tx_id}", source_tx_id
            ):
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
            savings_percentage=split["savings_percentage"],
            posted_by=actor,
            source_tx_id=source_tx_id or None,
            notes=f"reconstruct kernel_split={split['split_source']}",
            engine=engine,
            risk_amount=split.get("risk_amount"),
            savings_amount=split.get("savings_amount"),
        )
        if result.get("posted"):
            posted_count += 1
            actions.append({
                "action": "post_premium_accounting",
                "bill_id": result.get("bill_id"),
                "amount": result.get("amount"),
                "source_tx_id": source_tx_id,
            })

    booked_claims = accounting_claim_ids(engine)
    ledger_claim_cash = claim_cash_by_id(ledger_iterable)
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
        amount = ledger_claim_cash.get(claim_id) or _tx_amount(tx)
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
            booked_claims.add(claim_id)
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
            posted_count += 1
            booked_claims.add(claim_id)

    return {
        "posted_count": posted_count,
        "action_count": len(actions),
        "actions": actions,
        "dry_run": bool(dry_run),
    }


def resplit_accounting_book_premiums(
    *,
    policies: Dict[str, Any],
    billing: Dict[str, Any],
    transactions: Any,
    policy_ids: Optional[Iterable[str]] = None,
    exclude_customer: Optional[Any] = None,
    engine: Any = None,
    dry_run: bool = False,
    actor: str = "books_repair",
) -> Dict[str, Any]:
    """Re-book premium cash whose risk/savings split no longer matches the policy pin.

    The accounting book splits a premium when the cash is posted. A policy
    whose kernel pin was restored afterwards still carries the earlier split
    (usually all risk). This reverses that allocation with contra entries
    and posts the cash again under the pin, which is what the boot
    reconstruction would book. ``policy_ids`` limits it to those policies.

    Only the accounting book moves. The customer ledger, bills, premiums, and
    customer balances are not written. A difference of a cent or less is
    rounding and is left as booked.
    """
    if engine is None:
        try:
            from accounting_engine import get_accounting_engine

            engine = get_accounting_engine()
        except Exception:
            engine = None
    wanted = None if policy_ids is None else {str(pid) for pid in policy_ids if pid}
    ledger_iterable = (
        list(transactions.values()) if hasattr(transactions, "values") else list(transactions)
    )
    rows: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    if engine is None:
        return {"resplit_count": 0, "resplit": rows, "failed": failed, "dry_run": bool(dry_run)}
    for tx in ledger_iterable:
        if not isinstance(tx, dict) or _tx_type(tx) not in PREMIUM_CASH_TYPES:
            continue
        cid = str(tx.get("customer_id") or "")
        if exclude_customer and cid and exclude_customer(cid):
            continue
        amount = _tx_amount(tx)
        if amount <= 0:
            continue
        policy = _policy_for_tx(tx, policies, billing)
        if not isinstance(policy, dict):
            continue
        meta = _tx_metadata(tx)
        policy_id = str(policy.get("id") or meta.get("policy_id") or tx.get("policy_id") or "")
        if wanted is not None and policy_id not in wanted:
            continue
        source_tx_id = str(tx.get("id") or tx.get("tx_id") or "").strip()
        bill_id = str(meta.get("bill_id") or tx.get("bill_id") or "").strip()
        book_bill = bill_id or f"UNBILLED-{source_tx_id or cid}"
        alloc = _matching_allocation(engine, book_bill, source_tx_id or None)
        if alloc is None or money(getattr(alloc, "total_premium", 0)) != money(amount):
            # Not on the book as this one cash slice: the missing-post repair owns it.
            continue
        split = resolve_premium_split(amount, policy, fallback_risk_pct=100)
        before_risk = money(getattr(alloc, "risk_premium", 0))
        before_savings = money(getattr(alloc, "savings_premium", 0))
        after_risk = money(split["risk_amount"])
        after_savings = money(split["savings_amount"])
        if (
            (before_risk - after_risk).copy_abs() <= TOLERANCE
            and (before_savings - after_savings).copy_abs() <= TOLERANCE
        ):
            continue
        row = {
            "action": "resplit_premium_accounting",
            "bill_id": book_bill,
            "policy_id": policy_id,
            "customer_id": cid,
            "source_tx_id": source_tx_id,
            "amount": float(amount),
            "before": {"risk": float(before_risk), "savings": float(before_savings)},
            "after": {"risk": float(after_risk), "savings": float(after_savings)},
            "split_source": split.get("split_source"),
        }
        if dry_run:
            rows.append(row)
            continue
        ok, message = engine.reverse_allocation(
            alloc.allocation_id, actor, "kernel pin on the policy changed"
        )
        if not ok:
            failed.append({**row, "error": message})
            continue
        posted = post_premium_to_accounting_book(
            bill_id=book_bill,
            policy_id=policy_id,
            customer_id=cid,
            amount=amount,
            risk_percentage=split["risk_percentage"],
            savings_percentage=split["savings_percentage"],
            posted_by=actor,
            source_tx_id=source_tx_id or None,
            notes=f"resplit kernel_split={split['split_source']}",
            engine=engine,
            risk_amount=split.get("risk_amount"),
            savings_amount=split.get("savings_amount"),
        )
        if not posted.get("posted"):
            failed.append({**row, "error": posted.get("message") or posted.get("reason") or "not_posted"})
            continue
        row["reversed_allocation_id"] = alloc.allocation_id
        row["allocation_id"] = posted.get("allocation_id")
        rows.append(row)
    return {
        "resplit_count": len(rows),
        "resplit": rows,
        "failed": failed,
        "dry_run": bool(dry_run),
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
    savings_landed_by_customer: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Reconstruct missing cash-identity rows from operational evidence.

    Early PHINS durability could drop a customer-ledger row, skip the
    accounting book, or leave the General Reserves sheet on a different
    counter. This repair:

    1. Appends missing ``premium_payment`` rows for paid bills.
    2. Appends missing ``claim_payment_received`` rows for paid/closed claims.
    3. Posts missing accounting-book premiums from the ledger.
    4. Posts missing accounting-book claim entries from the ledger.
    5. Re-books a premium whose risk/savings split no longer matches the
       policy's kernel pin (reversal plus a new posting on the book only).
    6. Derives balance-sheet ``premium_income`` / ``claims_paid`` from the ledger.

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
        savings_landed_by_customer=savings_landed_by_customer,
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

    book_posts = reconstruct_accounting_book_from_ledger(
        policies=policies,
        claims=claims,
        billing=billing,
        transactions=ledger_iterable,
        exclude_customer=exclude_customer,
        engine=engine,
        dry_run=dry_run,
        actor=actor,
    )
    actions.extend(book_posts.get("actions") or [])

    book_resplit = resplit_accounting_book_premiums(
        policies=policies,
        billing=billing,
        transactions=ledger_iterable,
        exclude_customer=exclude_customer,
        engine=engine,
        dry_run=dry_run,
        actor=actor,
    )
    actions.extend(book_resplit.get("resplit") or [])
    actions.extend(
        {**row, "action": "resplit_premium_accounting_failed"}
        for row in book_resplit.get("failed") or []
    )

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
            savings_landed_by_customer=savings_landed_by_customer,
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
        "expense_loading_annual",
        "profit_margin_annual",
        "mortality_premium_annual",
        "disability_premium_annual",
        "savings_rate_used",
        "savings_formula",
        "adl_level",
        "adl_level_source",
        "adl_loading",
        "underwriting_loading",
        "life_sum_used",
        "disability_sum_used",
    ):
        if key == "adl_level" and "adl_clinical_level" in premium_data:
            # The kernel's adl_level is the multiplier it priced. When the
            # applicant was never functionally assessed that number is the
            # published baseline, not a clinical finding — leave the column
            # empty and keep the priced level beside it.
            if policy.get("adl_level") in (None, ""):
                clinical = premium_data.get("adl_clinical_level")
                if clinical is not None:
                    policy["adl_level"] = clinical
            if premium_data.get("adl_level") is not None:
                policy.setdefault("adl_pricing_level", premium_data.get("adl_level"))
            continue
        if premium_data.get(key) is not None and policy.get(key) in (None, ""):
            policy[key] = premium_data[key]
    return policy


_KERNEL_MONEY_PINS = (
    "risk_premium_annual",
    "savings_premium_annual",
    "expense_loading_annual",
    "profit_margin_annual",
    "mortality_premium_annual",
    "disability_premium_annual",
)


def repin_kernel_fields_on_policy(policy: Dict[str, Any], premium_data: Dict[str, Any]) -> Dict[str, Any]:
    """Replace the money pins after the policy's premium was repriced.

    A new annual premium with the earlier decomposition would leave the pins
    summing to a premium that is no longer billed. A kernel reprice replaces
    all of them together. A reprice the kernel did not produce clears them,
    so that premium is reported unpinned instead of split by the old stack.
    """
    if not isinstance(policy, dict) or not isinstance(premium_data, dict):
        return policy
    kernel_priced = (
        str(premium_data.get("pricing_source") or "") == "pricing_kernel"
        and premium_data.get("risk_premium_annual") is not None
    )
    for key in _KERNEL_MONEY_PINS:
        # None is the cleared pin: the database copy drops that key too.
        policy[key] = premium_data.get(key) if kernel_priced else None
    for key in (
        "pricing_source", "integrity_hash", "product_id", "tables_version",
        "config_version", "savings_rate_used", "savings_formula",
    ):
        if premium_data.get(key) is not None:
            policy[key] = premium_data[key]
    return policy


# ---------------------------------------------------------------------------
# Restoring a kernel pin that was never stored
# ---------------------------------------------------------------------------

# The savings add-ons and terms the application forms offer. The restore tries
# only these, so a premium is matched against what could have been sold.
RESTORE_SAVINGS_ADDONS: Tuple[Tuple[str, float], ...] = (
    ("none", 0.0),
    ("light", 0.25),
    ("balanced", 0.50),
    ("growth", 1.00),
)
RESTORE_TERM_YEARS: Tuple[int, ...] = (10, 15, 20, 25, 30)

_RESTORE_PIN_KEYS = (
    "pricing_source",
    "integrity_hash",
    "product_id",
    "tables_version",
    "config_version",
    "risk_premium_annual",
    "mortality_premium_annual",
    "disability_premium_annual",
    "savings_premium_annual",
    "expense_loading_annual",
    "profit_margin_annual",
    "savings_rate_used",
    "savings_formula",
)


def _restore_loading(policy: Mapping[str, Any], application: Optional[Mapping[str, Any]]) -> Decimal:
    """Underwriter loading on the billed premium, as a fraction."""
    raw = (application or {}).get("premium_adjustment")
    if raw in (None, ""):
        raw = policy.get("premium_adjustment")
    try:
        value = Decimal(str(raw if raw not in (None, "") else 0))
    except Exception:
        value = Decimal("0")
    if abs(value) >= 1:
        value = value / Decimal("100")
    return value


def _restore_pricing_payload(
    policy: Mapping[str, Any],
    application: Optional[Mapping[str, Any]],
    customer: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    app = application or {}
    person = customer or {}
    payload: Dict[str, Any] = {
        "type": policy.get("type") or app.get("policy_type") or "life",
        "coverage_amount": policy.get("coverage_amount") or app.get("coverage_amount"),
        "risk_score": app.get("risk_score") or policy.get("risk_score") or "medium",
    }
    age = app.get("age")
    if age in (None, ""):
        age = person.get("age")
    if age not in (None, ""):
        payload["age"] = age
    else:
        dob = person.get("dob") or person.get("date_of_birth")
        if dob:
            payload["dob"] = dob
    for key, sources in (
        ("gender", (app.get("gender"), person.get("gender"))),
        ("smoking_status", (app.get("smoking_status"),)),
        ("ethnicity", (app.get("ethnicity"), person.get("ethnicity"))),
        ("adl_level", (app.get("adl_level"), policy.get("adl_level"))),
    ):
        for value in sources:
            if value not in (None, ""):
                payload[key] = value
                break
    questionnaire = app.get("questionnaire") or app.get("questionnaire_responses")
    if isinstance(questionnaire, Mapping):
        payload["questionnaire"] = dict(questionnaire)
    return payload


def kernel_pin_restore_candidate(
    policy: Mapping[str, Any],
    *,
    application: Optional[Mapping[str, Any]] = None,
    customer: Optional[Mapping[str, Any]] = None,
    pricer: Any = None,
) -> Dict[str, Any]:
    """Find the one kernel decomposition that reproduces a stored premium.

    The policy is repriced from its stored application for each savings
    add-on and term the forms offer. A pin is offered only when exactly one
    decomposition gives the billed annual premium to the cent (and the
    monthly premium when one is stored). Anything else is refused: no match,
    more than one match, a discounted premium, or a seal that fails its
    checksum. Nothing is written here.
    """
    policy_id = str(policy.get("id") or policy.get("policy_id") or "")
    annual = money(policy.get("annual_premium"))
    result: Dict[str, Any] = {
        "policy_id": policy_id,
        "customer_id": str(policy.get("customer_id") or ""),
        "annual_premium": float(annual),
        "status": "refused",
        "reason": "",
        "pins": {},
        "matches": [],
    }
    if policy.get("kernel_pin_intact") is False:
        result["reason"] = "pin_seal_broken"
        return result
    if policy.get("risk_premium_annual") is not None or policy.get("risk_premium") is not None:
        result["status"] = "pinned"
        result["reason"] = "already_pinned"
        return result
    if annual <= 0:
        result["reason"] = "no_annual_premium"
        return result
    if legacy_annual_layers(dict(policy), {}) is not None:
        # An earlier contract's stored percentages are its allocation.
        result["status"] = "pinned"
        result["reason"] = "earlier_sealed_allocation"
        return result
    if pricer is None:
        from services.pricing_shadow_service import price_application_with_kernel as pricer

    loading = _restore_loading(policy, application)
    if loading < 0:
        result["reason"] = "discounted_premium"
        return result
    base_payload = _restore_pricing_payload(policy, application, customer)
    stored_monthly = money(policy.get("monthly_premium"))
    factor = Decimal("1") + loading
    found: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for addon, rate in RESTORE_SAVINGS_ADDONS:
        for term in RESTORE_TERM_YEARS:
            payload = dict(base_payload)
            payload["savings_rate"] = rate
            payload["term_years"] = term
            try:
                quote = pricer(payload)
            except Exception:
                quote = None
            if not isinstance(quote, Mapping) or quote.get("risk_premium_annual") is None:
                continue
            if quote.get("eligible") is False:
                continue
            base_annual = money(quote.get("annual"))
            if money(base_annual * factor) != annual:
                continue
            if stored_monthly > 0 and money(money(quote.get("monthly")) * factor) != stored_monthly:
                continue
            layers = tuple(
                str(money(quote.get(key)))
                for key in (
                    "risk_premium_annual",
                    "savings_premium_annual",
                    "expense_loading_annual",
                    "profit_margin_annual",
                )
            )
            if sum((Decimal(value) for value in layers), Decimal("0")) != base_annual:
                continue
            entry = found.setdefault(layers, {"quote": dict(quote), "addon": addon, "rate": rate, "terms": []})
            entry["terms"].append(term)
            result["matches"].append({"savings_addon": addon, "savings_rate": rate, "term_years": term})
    if not found:
        result["reason"] = "no_kernel_price_reproduces_the_premium"
        return result
    if len(found) > 1:
        result["reason"] = "more_than_one_decomposition"
        return result

    entry = next(iter(found.values()))
    quote = entry["quote"]
    pins: Dict[str, Any] = {
        key: quote[key] for key in _RESTORE_PIN_KEYS if quote.get(key) is not None
    }
    if entry["rate"] > 0:
        pins["savings_addon"] = entry["addon"]
        pins["savings_rate"] = entry["rate"]
    if loading > 0:
        base_annual = money(quote.get("annual"))
        pins["actuarial_annual_premium"] = float(base_annual)
        pins["underwriting_loading"] = float(loading)
        pins["underwriting_fee_annual"] = float(annual - base_annual)
    pins["kernel_pin_source"] = "restored_by_reprice"
    result["status"] = "restorable"
    result["reason"] = "one_decomposition_reproduces_the_premium"
    result["pins"] = pins
    return result


# Read-time classification of credits that still sit in the live health wallet.
# Nothing here writes a ledger row, a wallet, an application, or a seal.
_WALLET_CLAIM_TYPES = CLAIM_CASH_TYPES | frozenset({"claim_payout"})
_AUM_PLATFORM_IDS = frozenset({"PHINS-CORPORATE", "PHINS", "SYSTEM"})
_CENT = Decimal("0.01")
# Percents the code stamps itself. They are not a customer-written mix.
_KNOWN_ALLOCATION_TEMPLATES = (
    (Decimal("30"), Decimal("65"), Decimal("5")),    # later savings default
    (Decimal("15"), Decimal("60"), Decimal("25")),   # AI recommendation
    (Decimal("75"), Decimal("25"), Decimal("0")),    # retired 75/25 card
)


def submitted_savings_distribution(phins_allocation: Any) -> Optional[Dict[str, Any]]:
    """The distribution object the application sent, with no percent filled in.

    A missing key stays missing. This does not substitute 30/65/5, 15/60/25,
    or 75/25.
    """
    if not isinstance(phins_allocation, Mapping):
        return None
    dist = phins_allocation.get("distribution")
    if not isinstance(dist, Mapping):
        return None
    if "wallet_pct" not in dist or "investment_pct" not in dist:
        return None
    if "algo_trading_pct" not in dist and "algo_pct" not in dist:
        return None
    algo = dist.get("algo_trading_pct", dist.get("algo_pct"))
    return {
        "wallet_pct": dist.get("wallet_pct"),
        "investment_pct": dist.get("investment_pct"),
        "algo_trading_pct": algo,
    }


def _as_mapping(value: Any) -> Optional[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            import json
            parsed = json.loads(value)
        except Exception:
            return None
        if isinstance(parsed, dict):
            return parsed
    return None


def _distribution_on_application(application: Mapping[str, Any]) -> Optional[Mapping[str, Any]]:
    """A distribution object the application itself carries, if any."""
    health = _as_mapping(application.get("health_wallet"))
    if health is not None and isinstance(health.get("written_distribution"), Mapping):
        return health["written_distribution"]
    allocation = _as_mapping(application.get("phins_allocation"))
    if allocation is not None and isinstance(allocation.get("distribution"), Mapping):
        return allocation["distribution"]
    questionnaire = _as_mapping(application.get("questionnaire_responses"))
    if questionnaire is not None and isinstance(questionnaire.get("savings_distribution"), Mapping):
        return questionnaire["savings_distribution"]
    return None


def _percent_triple(distribution: Mapping[str, Any]) -> Tuple[str, Optional[Tuple[Decimal, Decimal, Decimal]]]:
    """Three percents. ``missing`` when a key was not written, ``invalid`` when it does not parse."""
    if "wallet_pct" not in distribution or "investment_pct" not in distribution:
        return "missing", None
    if "algo_trading_pct" not in distribution and "algo_pct" not in distribution:
        return "missing", None
    try:
        wallet = Decimal(str(distribution.get("wallet_pct")))
        investment = Decimal(str(distribution.get("investment_pct")))
        algo_raw = distribution.get("algo_trading_pct", distribution.get("algo_pct"))
        algo = Decimal(str(algo_raw))
    except Exception:
        return "invalid", None
    parts = (wallet, investment, algo)
    if any(part != part or part == Decimal("Infinity") or part == Decimal("-Infinity") for part in parts):
        return "invalid", None
    return "ok", parts


def _is_known_template(parts: Tuple[Decimal, Decimal, Decimal]) -> bool:
    for template in _KNOWN_ALLOCATION_TEMPLATES:
        if all(abs(part - expected) <= Decimal("0.05") for part, expected in zip(parts, template)):
            return True
    return False


def _judge_mix(distribution: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """Decide whether a stored distribution is a written custom mix."""
    if not isinstance(distribution, Mapping):
        return {"status": "no_written_mix", "parts": None}
    state, parts = _percent_triple(distribution)
    if state == "missing":
        return {"status": "no_written_mix", "parts": None}
    if state != "ok" or parts is None:
        return {"status": "mix_not_valid", "parts": None}
    wallet, investment, algo = parts
    if any(part < 0 or part > 100 for part in parts):
        return {"status": "mix_not_valid", "parts": None}
    if abs((wallet + investment + algo) - Decimal("100")) > Decimal("0.05"):
        return {"status": "mix_not_valid", "parts": None}
    if _is_known_template(parts):
        return {"status": "known_template", "parts": None}
    return {"status": "ok", "parts": parts}


_MIX_REASONS = {
    "no_written_mix": "No written mix on the original application. Left unallocated.",
    "mix_not_valid": (
        "The written mix is not each percent in 0–100 summing to 100. Left unallocated."
    ),
    "known_template": (
        "The stored percents are the 30/65/5 default, the 15/60/25 recommendation, "
        "or the retired 75/25 card. Left unallocated."
    ),
}


def _application_rows(applications: Any) -> List[Mapping[str, Any]]:
    if isinstance(applications, Mapping):
        values = list(applications.values())
    else:
        values = list(applications or [])
    return [row for row in values if isinstance(row, Mapping)]


def _original_application(customer_id: str, applications: Any) -> Optional[Mapping[str, Any]]:
    rows = [
        row for row in _application_rows(applications)
        if str(row.get("customer_id") or "") == customer_id
    ]
    if not rows:
        return None

    def _when(row: Mapping[str, Any]) -> str:
        return str(
            row.get("submitted_date")
            or row.get("created_date")
            or row.get("application_date")
            or row.get("id")
            or ""
        )

    rows.sort(key=_when)
    return rows[0]


def _allocation_distribution(customer_id: str, allocations: Any) -> Optional[Mapping[str, Any]]:
    """Nested distribution the application create path stored.

    A later flat preference (wallet_pct on the row itself) and a reconciled
    default row are not the original application.
    """
    if not isinstance(allocations, Mapping):
        return None
    row = allocations.get(customer_id)
    if not isinstance(row, Mapping) or row.get("_reconciled"):
        return None
    dist = row.get("distribution")
    if isinstance(dist, Mapping):
        return dist
    return None


def non_claim_wallet_credit(wallet: Any) -> Decimal:
    """Health-wallet cash that is not a claim posting and is still in the balance.

    Claim lines are left as they are. A claim amount is not subtracted past
    the live balance, and a negative claim line is not used to enlarge the credit.
    """
    if not isinstance(wallet, Mapping):
        return Decimal("0.00")
    balance = money(wallet.get("balance"))
    if balance <= 0:
        return Decimal("0.00")
    claim = Decimal("0.00")
    for tx in wallet.get("transactions") or []:
        if not isinstance(tx, Mapping):
            continue
        if str(tx.get("type") or "") not in _WALLET_CLAIM_TYPES:
            continue
        amount = money(tx.get("amount"))
        if amount > 0:
            claim += amount
    if claim > balance:
        claim = balance
    return (balance - claim).quantize(_CENT)


def _split_credit(credit: Decimal, parts: Tuple[Decimal, Decimal, Decimal]) -> Tuple[Decimal, Decimal, Decimal]:
    wallet = (credit * parts[0] / Decimal("100")).quantize(_CENT, rounding=ROUND_HALF_UP)
    investment = (credit * parts[1] / Decimal("100")).quantize(_CENT, rounding=ROUND_HALF_UP)
    algo = (credit - wallet - investment).quantize(_CENT)
    return wallet, investment, algo


def classify_legacy_wallet_credits(
    wallets: Optional[Mapping[str, Any]] = None,
    applications: Any = (),
    allocations: Optional[Mapping[str, Any]] = None,
    *,
    exclude_customer: Optional[Any] = None,
    retired_allocations: Any = None,
    recommendations: Any = None,
) -> Dict[str, Any]:
    """Split live health-wallet credits by the original application's written mix.

    Read-time only. Retired allocation rows and an AI or default recommendation
    passed in are not added. A credit with no valid custom mix stays unallocated.
    """
    del retired_allocations, recommendations
    wallets_map = wallets if isinstance(wallets, Mapping) else {}
    rows: List[Dict[str, Any]] = []
    totals = {
        "wallets": Decimal("0.00"),
        "investments": Decimal("0.00"),
        "algo": Decimal("0.00"),
        "unallocated": Decimal("0.00"),
    }
    for key, wallet in wallets_map.items():
        if not isinstance(wallet, Mapping):
            continue
        customer_id = str(wallet.get("customer_id") or key or "")
        if not customer_id or customer_id in _AUM_PLATFORM_IDS:
            continue
        if exclude_customer is not None:
            try:
                if exclude_customer(customer_id):
                    continue
            except Exception:
                continue
        credit = non_claim_wallet_credit(wallet)
        if credit <= 0:
            continue
        application = _original_application(customer_id, applications)
        distribution = _distribution_on_application(application) if application else None
        source = "application"
        if distribution is None:
            distribution = _allocation_distribution(customer_id, allocations)
            source = "application_allocation"
        judged = _judge_mix(distribution)
        if judged["status"] == "ok" and judged["parts"] is not None:
            wallet_amt, investment_amt, algo_amt = _split_credit(credit, judged["parts"])
            unallocated = Decimal("0.00")
            basis = "application_distribution" if source == "application" else "application_allocation"
            reason = None
        else:
            wallet_amt = investment_amt = algo_amt = Decimal("0.00")
            unallocated = credit
            basis = "unallocated"
            reason = _MIX_REASONS[judged["status"]]
        totals["wallets"] += wallet_amt
        totals["investments"] += investment_amt
        totals["algo"] += algo_amt
        totals["unallocated"] += unallocated
        rows.append({
            "customer_id": customer_id,
            "application_id": None if application is None else application.get("id"),
            "credit": float(credit),
            "wallets": float(wallet_amt),
            "investments": float(investment_amt),
            "algo": float(algo_amt),
            "unallocated": float(unallocated),
            "basis": basis,
            "reason": reason,
        })
    rows.sort(key=lambda row: row["customer_id"])
    allocated = totals["wallets"] + totals["investments"] + totals["algo"]
    return {
        "writes": False,
        "wallets": float(totals["wallets"]),
        "investments": float(totals["investments"]),
        "algo": float(totals["algo"]),
        "allocated": float(allocated),
        "unallocated": float(totals["unallocated"]),
        "credits": float(allocated + totals["unallocated"]),
        "unallocated_count": sum(1 for row in rows if row["unallocated"]),
        "rows": rows,
        "not_added_to_balance_sheet_totals": True,
        "retired_allocations_included": False,
        "note": (
            "Live health-wallet credits other than claim postings, split by the "
            "written mix on the original application. A missing, invalid, or "
            "template mix stays unallocated. Retired allocation rows are not added. "
            "No historical row is rewritten."
        ),
    }
