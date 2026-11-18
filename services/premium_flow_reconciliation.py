"""Read-only premium and savings reconciliation from sealed customer ledgers.

The pricing kernel's risk premium is taken as given. Expense loading sits
on top of that risk and is not reduced to make a savings percentage fit.
The savings layer is an add-on (a multiple of the risk premium), and only
that add-on is split across the health wallet, investments, and algo.

This module does not write wallets, bills, policies, claims, or NFT seals.
A paid claim with no sealed wallet credit is reported as an unposted
reserve-to-wallet transfer. It is not added to a balance.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from services.aspire_scale_identity import PHINS_TAKE
from services.nft_ledger import verify_token

# Plan factors, used only as weights on the expense loading. They are
# renormalized so the three shares sum to the loading. Risk premium is
# not a source for these shares.
# carrier own-expense ratio and quota-share cession: business_plan_model defaults.
_EXPENSE_WEIGHTS: Tuple[Tuple[str, Decimal], ...] = (
    ("phins_operations", Decimal(str(PHINS_TAKE))),
    ("carrier_share", Decimal("0.05")),
    ("reinsurance_ceding_reserve", Decimal("0.18")),
)

# Canonical savings destination split. Applied to the savings add-on only.
_SAVINGS_SPLIT: Tuple[Tuple[str, Decimal], ...] = (
    ("health_wallet", Decimal("30")),
    ("investments", Decimal("65")),
    ("algo", Decimal("5")),
)

_PREMIUM_TYPES = frozenset({
    "premium_payment",
    "bill_payment",
    "bulk_premium_payment",
})
_CLAIM_CREDIT_TYPES = frozenset({
    "claim_payment_received",
    "claim_payout",
    "claim_payment",
})
_PAID_STATUSES = frozenset({
    "paid",
    "settled",
    "closed_paid",
    "approved_paid",
})
_UNPAID_HINTS = ("unpaid", "pending", "open", "denied", "rejected", "draft")

_CENT = Decimal("0.01")


def _money(value: Any, default: str = "0") -> Decimal:
    try:
        number = Decimal(str(value if value is not None else default))
    except Exception:
        number = Decimal(default)
    if not number.is_finite():
        return Decimal(default)
    return number.quantize(_CENT, rounding=ROUND_HALF_UP)


def _month_of(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if len(text) >= 7 and text[4] == "-" and text[:4].isdigit() and text[5:7].isdigit():
        return text[:7]
    return None


def _partition(total: Decimal, weights: Sequence[Tuple[str, Decimal]]) -> Dict[str, float]:
    """Split ``total`` across named weights. The parts sum to ``total``."""
    weight_sum = sum((weight for _, weight in weights), Decimal("0"))
    if total == 0 or weight_sum <= 0:
        return {name: 0.0 for name, _ in weights}
    raw = [(name, (total * weight / weight_sum)) for name, weight in weights]
    cents = int((total * 100).to_integral_value(rounding=ROUND_HALF_UP))
    floors = []
    used = 0
    for name, amount in raw:
        floor_cents = int((amount * 100).to_integral_value(rounding=ROUND_HALF_UP))
        # Largest-remainder starts from the truncated cent, then repairs.
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
    return {name: float(Decimal(cents) / Decimal(100)) for name, cents, _ in floors}


def _monthly(annual: Any) -> Decimal:
    return (_money(annual) / Decimal(12)).quantize(_CENT, rounding=ROUND_HALF_UP)


def _kernel_month(policy: Mapping[str, Any]) -> Dict[str, Any]:
    """One month of the issued kernel pin. Missing loadings are not invented."""
    risk = _monthly(policy.get("risk_premium_annual"))
    savings_pinned = (
        policy.get("savings_premium_annual") is not None
        or policy.get("savings_premium") is not None
    )
    if savings_pinned:
        savings = _monthly(
            policy.get("savings_premium_annual")
            if policy.get("savings_premium_annual") is not None
            else policy.get("savings_premium")
        )
        savings_source = "kernel_pin"
    else:
        rate = policy.get("savings_rate")
        if rate is None:
            savings = Decimal("0.00")
            savings_source = "no_savings_election"
        else:
            savings = (risk * _money(rate)).quantize(_CENT, rounding=ROUND_HALF_UP)
            savings_source = "addon_rate"
    expense_pinned = policy.get("expense_loading_annual") is not None
    profit_pinned = policy.get("profit_margin_annual") is not None
    expense = _monthly(policy.get("expense_loading_annual")) if expense_pinned else Decimal("0.00")
    profit = _monthly(policy.get("profit_margin_annual")) if profit_pinned else Decimal("0.00")
    return {
        "risk": risk,
        "expense": expense,
        "profit": profit,
        "savings": savings,
        "expense_pinned": expense_pinned,
        "profit_pinned": profit_pinned,
        "savings_source": savings_source,
    }


def _policy_active(policy: Mapping[str, Any], month: str) -> bool:
    start = _month_of(policy.get("start_date") or policy.get("issued_at") or policy.get("created_at"))
    end = _month_of(policy.get("end_date") or policy.get("expiry_date"))
    if start and month < start:
        return False
    if end and month > end:
        return False
    return True


def _sum_kernel(policies: Iterable[Mapping[str, Any]], month: str) -> Dict[str, Any]:
    risk = expense = profit = savings = Decimal("0.00")
    expense_pinned = True
    profit_pinned = True
    sources = []
    active = 0
    for policy in policies:
        if not isinstance(policy, Mapping) or not _policy_active(policy, month):
            continue
        active += 1
        part = _kernel_month(policy)
        risk += part["risk"]
        expense += part["expense"]
        profit += part["profit"]
        savings += part["savings"]
        expense_pinned = expense_pinned and part["expense_pinned"]
        profit_pinned = profit_pinned and part["profit_pinned"]
        sources.append(part["savings_source"])
    stack = (risk + expense + profit + savings).quantize(_CENT)
    return {
        "policies": active,
        "risk": risk,
        "expense": expense,
        "profit": profit,
        "savings": savings,
        "correct_total": stack,
        "expense_pinned": expense_pinned and active > 0,
        "profit_pinned": profit_pinned and active > 0,
        "savings_source": sources[0] if len(set(sources)) == 1 and sources else "mixed",
    }


def _owner(token: Mapping[str, Any]) -> str:
    return str(token.get("owner_id") or token.get("customer_id") or "")


def _token_month(token: Mapping[str, Any]) -> Optional[str]:
    metadata = token.get("metadata") if isinstance(token.get("metadata"), dict) else {}
    return (
        _month_of(metadata.get("payment_period"))
        or _month_of(metadata.get("period"))
        or _month_of(token.get("created_at"))
    )


def _token_amount(token: Mapping[str, Any]) -> Decimal:
    return _money(token.get("amount")).copy_abs()


def _booked_split(record: Mapping[str, Any]) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    allocation = record.get("premium_allocation")
    if not isinstance(allocation, dict):
        allocation = metadata.get("premium_allocation") if isinstance(metadata.get("premium_allocation"), dict) else {}
    risk = allocation.get("risk_amount", record.get("risk_amount", metadata.get("risk_amount")))
    savings = allocation.get("savings_amount", record.get("savings_amount", metadata.get("savings_amount")))
    risk_value = _money(risk) if risk is not None else None
    savings_value = _money(savings) if savings is not None else None
    return risk_value, savings_value


def _bill_cash(bill: Mapping[str, Any]) -> Decimal:
    for key in ("amount_paid", "paid_amount", "final_amount", "total_amount", "amount"):
        if bill.get(key) is not None:
            return _money(bill.get(key))
    return Decimal("0.00")


def _bill_month(bill: Mapping[str, Any]) -> Optional[str]:
    return (
        _month_of(bill.get("payment_period"))
        or _month_of(bill.get("period"))
        or _month_of(bill.get("payment_date"))
        or _month_of(bill.get("paid_date"))
        or _month_of(bill.get("due_date"))
        or _month_of(bill.get("created_at"))
    )


def _claim_paid(claim: Mapping[str, Any]) -> bool:
    status = str(claim.get("status") or "").strip().lower().replace(" ", "_")
    if any(hint in status for hint in _UNPAID_HINTS):
        return False
    if status in _PAID_STATUSES or claim.get("paid_date") or claim.get("settled_date"):
        return True
    return False


def _claim_amount(claim: Mapping[str, Any]) -> Decimal:
    for key in ("paid_amount", "amount_paid", "approved_amount", "payout_amount", "amount"):
        if claim.get(key) is not None:
            return _money(claim.get(key))
    return Decimal("0.00")


def _claim_id(claim: Mapping[str, Any]) -> str:
    return str(claim.get("id") or claim.get("claim_id") or "")


def _waterfall(cash: Decimal, kernel: Mapping[str, Decimal]) -> Dict[str, Decimal]:
    """Apply collected cash in order: risk, expense, profit, savings.

    Nothing above the kernel stack is treated as savings. A short collection
    leaves later layers at zero instead of cutting an earlier layer.
    """
    left = cash if cash > 0 else Decimal("0.00")
    landed: Dict[str, Decimal] = {}
    for name in ("risk", "expense", "profit", "savings"):
        take = min(left, kernel[name])
        landed[name] = take.quantize(_CENT)
        left = (left - take).quantize(_CENT)
    landed["overbooked_excess"] = left
    return landed


def _flags(
    cash: Decimal,
    kernel: Mapping[str, Any],
    booked_risk: Optional[Decimal],
    booked_savings: Optional[Decimal],
) -> List[str]:
    flags: List[str] = []
    correct = kernel["correct_total"]
    if cash > correct + _CENT:
        flags.append("overbooked")
    elif cash + _CENT < correct:
        flags.append("underbooked")
    if booked_risk is not None and booked_risk + _CENT < kernel["risk"]:
        flags.append("risk_cut")
    if booked_risk is not None and booked_risk > kernel["risk"] + _CENT:
        flags.append("risk_overstated")
    if booked_savings is not None and booked_savings + _CENT < kernel["savings"]:
        flags.append("savings_short")
    if (
        booked_risk is not None
        and booked_savings is not None
        and booked_risk + _CENT < kernel["risk"]
        and abs((booked_risk + booked_savings) - cash) <= _CENT
    ):
        flags.append("savings_carved_from_premium")
    return flags


def _customer_tokens(nft_ledger: Mapping[str, Any], customer_id: str) -> List[Dict[str, Any]]:
    rows = []
    for token in nft_ledger.values():
        if isinstance(token, dict) and _owner(token) == customer_id:
            rows.append(token)
    rows.sort(key=lambda row: (str(row.get("created_at") or ""), str(row.get("token_id") or "")))
    return rows


def reconcile_customer(
    customer_id: str,
    *,
    policies: Iterable[Mapping[str, Any]] = (),
    bills: Iterable[Mapping[str, Any]] = (),
    claims: Iterable[Mapping[str, Any]] = (),
    nft_ledger: Optional[Mapping[str, Any]] = None,
    savings_split: Sequence[Tuple[str, Decimal]] = _SAVINGS_SPLIT,
) -> Dict[str, Any]:
    """Monthly risk, expense, and savings table for one customer.

    Cash comes from sealed premium NFTs. A bill is used for a month only
    when that month has no sealed premium token. Broken seals are withheld
    and are not repaired.
    """
    ledger = nft_ledger or {}
    own_policies = [
        policy for policy in policies
        if isinstance(policy, Mapping) and str(policy.get("customer_id") or "") == customer_id
    ]
    own_bills = [
        bill for bill in bills
        if isinstance(bill, Mapping) and str(bill.get("customer_id") or "") == customer_id
    ]
    own_claims = [
        claim for claim in claims
        if isinstance(claim, Mapping) and str(claim.get("customer_id") or "") == customer_id
    ]
    tokens = _customer_tokens(ledger, customer_id)

    withheld: List[Dict[str, str]] = []
    premium_by_month: Dict[str, Decimal] = {}
    booked_by_month: Dict[str, Tuple[Optional[Decimal], Optional[Decimal]]] = {}
    first_token_month: Optional[str] = None
    for token in tokens:
        check = verify_token(token)
        if not check.get("valid"):
            withheld.append({
                "token_id": str(token.get("token_id") or ""),
                "reason": str(check.get("reason") or "invalid"),
            })
            continue
        month = _token_month(token)
        if month and (first_token_month is None or month < first_token_month):
            first_token_month = month
        tx_type = str(token.get("transaction_type") or "")
        if tx_type not in _PREMIUM_TYPES or not month:
            continue
        premium_by_month[month] = (premium_by_month.get(month, Decimal("0.00")) + _token_amount(token)).quantize(_CENT)
        risk_booked, savings_booked = _booked_split(token)
        if risk_booked is not None or savings_booked is not None:
            previous = booked_by_month.get(month, (None, None))
            booked_by_month[month] = (
                (previous[0] or Decimal("0.00")) + risk_booked if risk_booked is not None else previous[0],
                (previous[1] or Decimal("0.00")) + savings_booked if savings_booked is not None else previous[1],
            )

    bill_cash_by_month: Dict[str, Decimal] = {}
    bill_ids_by_month: Dict[str, List[str]] = {}
    for bill in own_bills:
        month = _bill_month(bill)
        if not month:
            continue
        bill_cash_by_month[month] = (bill_cash_by_month.get(month, Decimal("0.00")) + _bill_cash(bill)).quantize(_CENT)
        bill_ids_by_month.setdefault(month, []).append(str(bill.get("id") or bill.get("bill_id") or ""))
        if month not in booked_by_month:
            booked_by_month[month] = _booked_split(bill)

    months = set(premium_by_month) | set(bill_cash_by_month)
    for policy in own_policies:
        start = _month_of(policy.get("start_date") or policy.get("issued_at") or policy.get("created_at"))
        if start:
            months.add(start)
    if first_token_month:
        months.add(first_token_month)
    if not months:
        months = set()

    ordered = sorted(months)
    if ordered:
        start_month, end_month = ordered[0], ordered[-1]
        cursor_y, cursor_m = int(start_month[:4]), int(start_month[5:7])
        end_y, end_m = int(end_month[:4]), int(end_month[5:7])
        filled: List[str] = []
        while (cursor_y, cursor_m) <= (end_y, end_m):
            filled.append(f"{cursor_y:04d}-{cursor_m:02d}")
            cursor_m += 1
            if cursor_m == 13:
                cursor_m = 1
                cursor_y += 1
        ordered = filled

    rows: List[Dict[str, Any]] = []
    landed_savings = Decimal("0.00")
    landed_wallet = Decimal("0.00")
    landed_investments = Decimal("0.00")
    landed_algo = Decimal("0.00")
    for month in ordered:
        kernel = _sum_kernel(own_policies, month)
        nft_cash = premium_by_month.get(month, Decimal("0.00"))
        if nft_cash > 0:
            cash = nft_cash
            cash_source = "nft"
        else:
            cash = bill_cash_by_month.get(month, Decimal("0.00"))
            cash_source = "bill" if cash > 0 else "none"
        booked_risk, booked_savings = booked_by_month.get(month, (None, None))
        landed = _waterfall(cash, kernel)
        savings_parts = _partition(landed["savings"], savings_split)
        landed_savings += landed["savings"]
        landed_wallet += _money(savings_parts["health_wallet"])
        landed_investments += _money(savings_parts["investments"])
        landed_algo += _money(savings_parts["algo"])
        expense_parts = _partition(kernel["expense"], _EXPENSE_WEIGHTS)
        retired_half = (cash * Decimal("0.50")).quantize(_CENT) if cash else Decimal("0.00")
        retired_risk_75 = (cash * Decimal("0.75")).quantize(_CENT) if cash else Decimal("0.00")
        rows.append({
            "month": month,
            "cash_source": cash_source,
            "nft_premium_cash": float(nft_cash),
            "bill_cash": float(bill_cash_by_month.get(month, Decimal("0.00"))),
            "collected": float(cash),
            "bill_ids": bill_ids_by_month.get(month, []),
            "kernel_risk": float(kernel["risk"]),
            "expense_loading": float(kernel["expense"]),
            "expense_pinned": kernel["expense_pinned"],
            "phins_operations": expense_parts["phins_operations"],
            "carrier_share": expense_parts["carrier_share"],
            "reinsurance_ceding_reserve": expense_parts["reinsurance_ceding_reserve"],
            "profit": float(kernel["profit"]),
            "profit_pinned": kernel["profit_pinned"],
            "savings_addon": float(kernel["savings"]),
            "savings_source": kernel["savings_source"],
            "savings_wallet": savings_parts["health_wallet"],
            "savings_investments": savings_parts["investments"],
            "savings_algo": savings_parts["algo"],
            "correct_total": float(kernel["correct_total"]),
            "landed_risk": float(landed["risk"]),
            "landed_expense": float(landed["expense"]),
            "landed_profit": float(landed["profit"]),
            "landed_savings": float(landed["savings"]),
            "overbooked_excess": float(landed["overbooked_excess"]),
            "booked_risk": None if booked_risk is None else float(booked_risk),
            "booked_savings": None if booked_savings is None else float(booked_savings),
            "retired_50_50_risk": float(retired_half),
            "retired_50_50_savings": float((cash - retired_half).quantize(_CENT) if cash else Decimal("0.00")),
            "retired_75_25_risk": float(retired_risk_75),
            "retired_75_25_savings": float((cash - retired_risk_75).quantize(_CENT) if cash else Decimal("0.00")),
            "variance": float((cash - kernel["correct_total"]).quantize(_CENT)),
            "flags": _flags(cash, kernel, booked_risk, booked_savings),
        })

    claim_rows = _claim_rows(own_claims, tokens)
    sealed_claim_credits = sum(
        (_money(row["sealed_wallet_credit"]) for row in claim_rows),
        Decimal("0.00"),
    )
    unposted_claims = sum(
        (_money(row["unposted_reserve_transfer"]) for row in claim_rows),
        Decimal("0.00"),
    )
    return {
        "customer_id": customer_id,
        "writes": False,
        "first_month": ordered[0] if ordered else None,
        "months": rows,
        "withheld_seals": withheld,
        "claims": claim_rows,
        "admin_balances_from_landed_savings": {
            "health_wallet_savings": float(landed_wallet.quantize(_CENT)),
            "investments": float(landed_investments.quantize(_CENT)),
            "algo": float(landed_algo.quantize(_CENT)),
            "savings_landed": float(landed_savings.quantize(_CENT)),
            "sealed_claim_credits": float(sealed_claim_credits.quantize(_CENT)),
            "unposted_claim_transfers": float(unposted_claims.quantize(_CENT)),
        },
        "notes": [
            "Risk premium is the kernel pin and is not scaled down to fit a smaller bill.",
            "Expense loading is partitioned in full across PHINS operations, the carrier, and the reinsurance ceding reserve.",
            "Savings is the add-on layer. Only cash left after risk, expense, and profit lands in wallet, investments, and algo.",
            "A paid claim with no sealed wallet credit is an unposted reserve transfer and is not added to a balance.",
        ],
    }


def _claim_rows(claims: Sequence[Mapping[str, Any]], tokens: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    credits: List[Dict[str, Any]] = []
    for token in tokens:
        if not verify_token(token).get("valid"):
            continue
        if str(token.get("transaction_type") or "") not in _CLAIM_CREDIT_TYPES:
            continue
        metadata = token.get("metadata") if isinstance(token.get("metadata"), dict) else {}
        credits.append({
            "token_id": str(token.get("token_id") or ""),
            "claim_id": str(metadata.get("claim_id") or token.get("transaction_id") or ""),
            "amount": _token_amount(token),
            "used": False,
        })
    rows = []
    for claim in claims:
        if not _claim_paid(claim):
            continue
        amount = _claim_amount(claim)
        claim_id = _claim_id(claim)
        matched = Decimal("0.00")
        for credit in credits:
            if credit["used"]:
                continue
            if credit["claim_id"] and claim_id and credit["claim_id"] == claim_id:
                matched += credit["amount"]
                credit["used"] = True
        unposted = (amount - matched).quantize(_CENT)
        if unposted < 0:
            unposted = Decimal("0.00")
        rows.append({
            "claim_id": claim_id,
            "paid_amount": float(amount),
            "sealed_wallet_credit": float(matched.quantize(_CENT)),
            "unposted_reserve_transfer": float(unposted),
            "posted": unposted == 0 and matched > 0,
        })
    return rows


def reconcile_customers(
    customer_ids: Iterable[str],
    **books: Any,
) -> Dict[str, Any]:
    """Reconcile each customer. The books are read and not written."""
    reports = [
        reconcile_customer(str(customer_id), **books)
        for customer_id in customer_ids
    ]
    return {
        "writes": False,
        "customers": reports,
        "customer_count": len(reports),
    }
