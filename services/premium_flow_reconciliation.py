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
from services.nft_ledger import mint_token, verify_token

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

# Same multiples the cash writer uses. A named add-on is savings even when
# the policy has no savings_premium pin.
_ADDON_RATES = {
    "none": Decimal("0"),
    "light": Decimal("0.25"),
    "balanced": Decimal("0.50"),
    "growth": Decimal("1"),
}

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
# `closed` is a completed payout in the claims book (`paid` and `closed`
# are the paid totals). `approved` is still a reserve, not a wallet credit.
_PAID_STATUSES = frozenset({
    "paid",
    "settled",
    "closed",
    "closed_paid",
    "approved_paid",
})
_UNPAID_STATUSES = frozenset({
    "unpaid",
    "pending",
    "under_review",
    "medical_assessment",
    "open",
    "denied",
    "rejected",
    "draft",
    "submitted",
    "approved",
})

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
    """Return ``YYYY-MM`` only when the month is 01–12.

    A value such as ``2026-13`` is not a month. The range filler used to
    accept it and then increment forever, because it only wraps at 13.
    """
    text = str(value or "").strip()
    if len(text) < 7 or text[4] != "-":
        return None
    year, month = text[:4], text[5:7]
    if not (year.isdigit() and month.isdigit()):
        return None
    month_number = int(month)
    if month_number < 1 or month_number > 12:
        return None
    return f"{int(year):04d}-{month_number:02d}"


def _fill_months(start: str, end: str) -> List[str]:
    """Inclusive month list. Stops rather than looping on a bad endpoint."""
    start_y, start_m = int(start[:4]), int(start[5:7])
    end_y, end_m = int(end[:4]), int(end[5:7])
    if not (1 <= start_m <= 12 and 1 <= end_m <= 12):
        return [start] if start == end else [start, end]
    filled: List[str] = []
    cursor_y, cursor_m = start_y, start_m
    # Fifty years is longer than any policy term this table is asked to show.
    for _ in range(12 * 50 + 1):
        filled.append(f"{cursor_y:04d}-{cursor_m:02d}")
        if (cursor_y, cursor_m) >= (end_y, end_m):
            return filled
        cursor_m += 1
        if cursor_m == 13:
            cursor_m = 1
            cursor_y += 1
    return filled


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


def _first_present(record: Mapping[str, Any], *keys: str) -> Any:
    """First stored value. Issued quotes use the short annual names."""
    for key in keys:
        if record.get(key) is not None:
            return record.get(key)
    return None


def _kernel_month(policy: Mapping[str, Any]) -> Dict[str, Any]:
    """One month of the issued kernel pin. Missing loadings are not invented.

    ``risk_premium_annual`` is the canonical pin. Issued quotes store that
    same annual amount as ``risk_premium``, and the same for expense and
    profit. A missing pin stays zero. It is not replaced by a 50/25 split.
    """
    risk_value = _first_present(policy, "risk_premium_annual", "risk_premium")
    risk = _monthly(risk_value) if risk_value is not None else Decimal("0.00")
    addon = str(policy.get("savings_addon") or "").strip().lower()
    savings_value = _first_present(policy, "savings_premium_annual", "savings_premium")
    if savings_value is not None:
        savings = _monthly(savings_value)
        savings_source = "kernel_pin"
    elif addon in _ADDON_RATES:
        addon_rate = _ADDON_RATES[addon]
        if addon_rate > 0 and risk_value is not None:
            savings = _monthly(_money(risk_value) * addon_rate)
            savings_source = "growth" if addon == "growth" else "addon"
        else:
            savings = Decimal("0.00")
            savings_source = "no_savings_election"
    else:
        rate = policy.get("savings_rate")
        if rate is None:
            savings = Decimal("0.00")
            savings_source = "no_savings_election"
        else:
            savings = (risk * _money(rate)).quantize(_CENT, rounding=ROUND_HALF_UP)
            savings_source = "addon_rate"
    if savings > 0 and addon == "growth" and savings_source != "growth":
        savings_source = "growth"
    elif savings > 0 and addon in ("light", "balanced") and savings_source == "kernel_pin":
        savings_source = "addon"
    expense_value = _first_present(policy, "expense_loading_annual", "expense_loading")
    profit_value = _first_present(policy, "profit_margin_annual", "profit_margin")
    expense_pinned = expense_value is not None
    profit_pinned = profit_value is not None
    expense = _monthly(expense_value) if expense_pinned else Decimal("0.00")
    profit = _monthly(profit_value) if profit_pinned else Decimal("0.00")
    fee = Decimal("0.00")
    historical = False
    try:
        from services.financial_unification_service import (
            kernel_components_from_policy,
            legacy_annual_layers,
            underwriting_fee_annual,
        )

        kernel = kernel_components_from_policy(dict(policy))
        fee = _monthly(underwriting_fee_annual(dict(policy), kernel))
        legacy = legacy_annual_layers(dict(policy), kernel)
        if legacy is not None:
            historical = True
            risk = _monthly(legacy["risk"])
            savings = _monthly(legacy["savings"])
            fee = _monthly(legacy["underwriting_fee"])
            expense = Decimal("0.00")
            profit = Decimal("0.00")
            savings_source = "historical"
    except Exception:
        fee = Decimal("0.00")
    return {
        "risk": risk,
        "underwriting_fee": fee,
        "expense": expense,
        "profit": profit,
        "savings": savings,
        "expense_pinned": expense_pinned,
        "profit_pinned": profit_pinned,
        "savings_source": savings_source,
        "historical": historical,
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
    risk = expense = profit = savings = fee = Decimal("0.00")
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
        fee += part.get("underwriting_fee") or Decimal("0.00")
        expense += part["expense"]
        profit += part["profit"]
        savings += part["savings"]
        expense_pinned = expense_pinned and part["expense_pinned"]
        profit_pinned = profit_pinned and part["profit_pinned"]
        sources.append(part["savings_source"])
    stack = (risk + fee + expense + profit + savings).quantize(_CENT)
    return {
        "policies": active,
        "risk": risk,
        "underwriting_fee": fee,
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
    paid_risk = record.get("risk_amount_paid", metadata.get("risk_amount_paid"))
    paid_savings = record.get("savings_amount_paid", metadata.get("savings_amount_paid"))
    if paid_risk is not None or paid_savings is not None:
        if _money(paid_risk) > 0 or _money(paid_savings) > 0:
            return _money(paid_risk), _money(paid_savings)
    risk = allocation.get("risk_amount", record.get("risk_amount", metadata.get("risk_amount")))
    savings = allocation.get("savings_amount", record.get("savings_amount", metadata.get("savings_amount")))
    if risk is None and savings is None:
        sealed_risk = metadata.get("risk_allocation", record.get("risk_allocation"))
        sealed_savings = metadata.get("savings_allocation", record.get("savings_allocation"))
        if sealed_risk is not None and sealed_savings is not None:
            cash = _money(record.get("amount") if record.get("amount") is not None else record.get("amount_paid"))
            if cash > 0 and abs(_money(sealed_risk) + _money(sealed_savings) - cash) <= _CENT:
                risk, savings = sealed_risk, sealed_savings
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
    status = str(claim.get("status") or "").strip().lower().replace(" ", "_").replace("-", "_")
    if status in _UNPAID_STATUSES:
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
    for name in ("risk", "underwriting_fee", "expense", "profit", "savings"):
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


def _picture(
    rows: Sequence[Mapping[str, Any]],
    claim_rows: Sequence[Mapping[str, Any]],
    withheld: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """One customer's premiums: kernel risk stays out of savings."""
    collected = landed_risk = landed_savings = landed_fee = Decimal("0.00")
    kernel_risk = kernel_savings = Decimal("0.00")
    expense = profit = Decimal("0.00")
    flags: List[str] = []
    sources = set()
    for row in rows:
        collected += _money(row.get("collected"))
        landed_risk += _money(row.get("landed_risk"))
        landed_fee += _money(row.get("landed_underwriting_fee"))
        landed_savings += _money(row.get("landed_savings"))
        kernel_risk += _money(row.get("kernel_risk"))
        kernel_savings += _money(row.get("savings_addon"))
        expense += _money(row.get("expense_loading"))
        profit += _money(row.get("profit"))
        sources.add(str(row.get("savings_source") or ""))
        for flag in row.get("flags") or []:
            if flag not in flags:
                flags.append(str(flag))
    unposted = sum((_money(row.get("unposted_reserve_transfer")) for row in claim_rows), Decimal("0.00"))
    sealed = sum((_money(row.get("sealed_wallet_credit")) for row in claim_rows), Decimal("0.00"))
    if unposted > 0 and "unposted_claim" not in flags:
        flags.append("unposted_claim")
    if withheld and "withheld_seal" not in flags:
        flags.append("withheld_seal")
    if "growth" in sources:
        savings_kind = "growth"
    elif "addon" in sources or "addon_rate" in sources or "kernel_pin" in sources:
        savings_kind = "addon"
    else:
        savings_kind = "none"
    return {
        "premiums_collected": float(collected.quantize(_CENT)),
        "kernel_risk": float(kernel_risk.quantize(_CENT)),
        "landed_risk": float(landed_risk.quantize(_CENT)),
        "underwriting_fee": float(landed_fee.quantize(_CENT)),
        "expense_loading": float(expense.quantize(_CENT)),
        "profit": float(profit.quantize(_CENT)),
        "savings_addon": float(kernel_savings.quantize(_CENT)),
        "landed_savings": float(landed_savings.quantize(_CENT)),
        "savings_kind": savings_kind,
        "risk_sent_to_savings": 0.0,
        "sealed_claim_credits": float(sealed.quantize(_CENT)),
        "unposted_claim_transfers": float(unposted.quantize(_CENT)),
        "withheld_seal_count": len(withheld),
        "flags": flags,
    }


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
    for token in tokens:
        check = verify_token(token)
        if not check.get("valid"):
            metadata = token.get("metadata") if isinstance(token.get("metadata"), dict) else {}
            tx_type = str(token.get("transaction_type") or "")
            withheld.append({
                "token_id": str(token.get("token_id") or ""),
                "reason": str(check.get("reason") or "invalid"),
                "claim_id": (
                    str(metadata.get("claim_id") or token.get("transaction_id") or "")
                    if tx_type in _CLAIM_CREDIT_TYPES
                    else ""
                ),
            })
            continue
        month = _token_month(token)
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

    ordered = sorted(months)
    if len(ordered) >= 2:
        ordered = _fill_months(ordered[0], ordered[-1])

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
            "underwriting_fee": float(kernel.get("underwriting_fee") or 0),
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
            "landed_underwriting_fee": float(landed.get("underwriting_fee") or 0),
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
    picture = _picture(rows, claim_rows, withheld)
    return {
        "customer_id": customer_id,
        "writes": False,
        "first_month": ordered[0] if ordered else None,
        "months": rows,
        "withheld_seals": withheld,
        "claims": claim_rows,
        "picture": picture,
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


# Named platform customers. The roster still learns every other id that
# appears on a policy, bill, claim, wallet, investment, algo book, or NFT.
PLATFORM_WATCH: Tuple[Dict[str, str], ...] = (
    {"customer_id": "CUST-ASAF-001", "name": "Asaf Assurance", "role": "primary"},
    {"customer_id": "CUST-EFRAT-001", "name": "Efrat PHINS", "role": "platform"},
    {"customer_id": "CUST-ASI-001", "name": "Asi PHINS", "role": "platform"},
    {"customer_id": "CUST-SHOSH-001", "name": "Shosh PHINS", "role": "platform"},
)

_WATCH_FLAGS = frozenset({
    "risk_cut",
    "savings_carved_from_premium",
    "unposted_claim",
    "withheld_seal",
    "balance_differs",
})
_PLATFORM_IDS = frozenset({"PHINS-CORPORATE", "PHINS", "SYSTEM"})


def _ids_from(rows: Iterable[Any], *keys: str) -> List[str]:
    found: List[str] = []
    seen = set()
    for row in rows or ():
        if not isinstance(row, Mapping):
            continue
        for key in keys:
            value = str(row.get(key) or "").strip()
            if value and value not in seen:
                seen.add(value)
                found.append(value)
            break
    return found


def _live_money(balances: Optional[Mapping[str, Any]], customer_id: str, *keys: str) -> float:
    row = (balances or {}).get(customer_id)
    if not isinstance(row, Mapping):
        return 0.0
    for key in keys:
        if row.get(key) is not None:
            return float(_money(row.get(key)))
    return 0.0


def claim_postings_due(report: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Paid claims with no intact wallet seal. A broken seal is not posted."""
    broken = {
        str(row.get("claim_id") or "")
        for row in report.get("withheld_seals") or []
        if str(row.get("claim_id") or "")
    }
    due = []
    for row in report.get("claims") or []:
        amount = _money(row.get("unposted_reserve_transfer"))
        claim_id = str(row.get("claim_id") or "")
        if amount <= 0 or not claim_id or claim_id in broken:
            continue
        due.append({
            "customer_id": str(report.get("customer_id") or ""),
            "claim_id": claim_id,
            "amount": float(amount),
            "stays_on_books": True,
            "destination": "health_wallet",
            "source": "claims_reserve",
        })
    return due


def monitoring_report(
    *,
    customers: Optional[Mapping[str, Any]] = None,
    policies: Iterable[Mapping[str, Any]] = (),
    bills: Iterable[Mapping[str, Any]] = (),
    claims: Iterable[Mapping[str, Any]] = (),
    nft_ledger: Optional[Mapping[str, Any]] = None,
    wallets: Optional[Mapping[str, Any]] = None,
    investments: Optional[Mapping[str, Any]] = None,
    algo: Optional[Mapping[str, Any]] = None,
    watch: Sequence[Mapping[str, str]] = PLATFORM_WATCH,
) -> Dict[str, Any]:
    """Customer monitoring list learned from ledgers, NFTs, and live balances.

    Reads only. Live wallet, investment, and algo figures are compared with
    the savings add-on that the waterfall says landed, plus sealed claim
    credits on the health wallet. A difference is flagged and not repaired.
    """
    policy_rows = [row for row in policies if isinstance(row, Mapping)]
    bill_rows = [row for row in bills if isinstance(row, Mapping)]
    claim_rows = [row for row in claims if isinstance(row, Mapping)]
    ledger = nft_ledger or {}
    names = {
        str(row.get("customer_id") or ""): str(row.get("name") or "")
        for row in watch
    }
    roles = {
        str(row.get("customer_id") or ""): str(row.get("role") or "watch")
        for row in watch
    }
    ordered: List[str] = []
    seen = set()

    def _add(customer_id: str) -> None:
        if not customer_id or customer_id in _PLATFORM_IDS or customer_id in seen:
            return
        seen.add(customer_id)
        ordered.append(customer_id)

    for row in watch:
        _add(str(row.get("customer_id") or ""))
    for customer_id in _ids_from(policy_rows, "customer_id"):
        _add(customer_id)
    for customer_id in _ids_from(bill_rows, "customer_id"):
        _add(customer_id)
    for customer_id in _ids_from(claim_rows, "customer_id"):
        _add(customer_id)
    for token in ledger.values():
        if isinstance(token, Mapping):
            _add(_owner(token))
    for store in (wallets, investments, algo, customers):
        if isinstance(store, Mapping):
            for customer_id in store.keys():
                _add(str(customer_id))

    customer_rows = []
    funds = {
        "health_wallet": Decimal("0.00"),
        "investments": Decimal("0.00"),
        "algo": Decimal("0.00"),
        "learned_savings": Decimal("0.00"),
        "sealed_claim_credits": Decimal("0.00"),
        "unposted_claim_transfers": Decimal("0.00"),
    }
    attention = 0
    for customer_id in ordered:
        record = customers.get(customer_id) if isinstance(customers, Mapping) else None
        name = ""
        if isinstance(record, Mapping):
            name = str(record.get("name") or record.get("full_name") or "")
        if not name:
            name = names.get(customer_id, "")
        report = reconcile_customer(
            customer_id,
            policies=policy_rows,
            bills=bill_rows,
            claims=claim_rows,
            nft_ledger=ledger,
        )
        wallet = _money(_live_money(wallets, customer_id, "balance"))
        investment = _money(_live_money(investments, customer_id, "position", "balance"))
        algo_balance = _money(_live_money(algo, customer_id, "available", "balance"))
        learned = report["admin_balances_from_landed_savings"]
        learned_wallet = _money(learned["health_wallet_savings"]) + _money(learned["sealed_claim_credits"])
        gap = (wallet - learned_wallet).copy_abs()
        invest_gap = (investment - _money(learned["investments"])).copy_abs()
        algo_gap = (algo_balance - _money(learned["algo"])).copy_abs()
        flags = list(report["picture"]["flags"])
        if gap > _CENT or invest_gap > _CENT or algo_gap > _CENT:
            flags.append("balance_differs")
        priority = "attention" if any(flag in _WATCH_FLAGS for flag in flags) else "clear"
        if customer_id in roles and priority == "clear" and not report["months"]:
            priority = "watch"
        if priority == "attention":
            attention += 1
        funds["health_wallet"] += wallet
        funds["investments"] += investment
        funds["algo"] += algo_balance
        funds["learned_savings"] += _money(learned["savings_landed"])
        funds["sealed_claim_credits"] += _money(learned["sealed_claim_credits"])
        funds["unposted_claim_transfers"] += _money(learned["unposted_claim_transfers"])
        customer_rows.append({
            "customer_id": customer_id,
            "name": name,
            "role": roles.get(customer_id, "learned"),
            "on_watch_list": customer_id in roles,
            "priority": priority,
            "picture": report["picture"],
            "live": {
                "health_wallet": float(wallet),
                "investments": float(investment),
                "algo": float(algo_balance),
            },
            "learned": learned,
            "claim_postings_due": claim_postings_due(report),
            "flags": flags,
            "month_count": len(report["months"]),
        })
    customer_rows.sort(key=lambda row: (
        0 if row["priority"] == "attention" else 1 if row["priority"] == "watch" else 2,
        row["name"] or row["customer_id"],
    ))
    return {
        "writes": False,
        "customers": customer_rows,
        "customer_count": len(customer_rows),
        "attention_count": attention,
        "accumulated_funds": {key: float(value.quantize(_CENT)) for key, value in funds.items()},
        "rules": [
            "Kernel risk premium is filled first and is never credited to savings.",
            "Only a savings add-on or a growth add lands in the health wallet, investments, and algo, and it stays there.",
            "A paid claim stays on the claims book. Unposted cash moves from the claims reserve to the health wallet once, and only when the seal is intact or absent.",
            "A broken NFT seal is withheld and is not repaired.",
        ],
    }


def worked_specimen() -> Dict[str, Any]:
    """CUST-X cash-flow assessment. The sealed example is not written to a book."""
    policy = {
        "id": "POL-X",
        "customer_id": "CUST-X",
        "name": "Worked assessment",
        "start_date": "2026-01-01",
        "risk_premium_annual": 2400.00,
        "savings_premium_annual": 2400.00,
        "savings_addon": "growth",
        "expense_loading_annual": 360.00,
        "profit_margin_annual": 516.00,
        "annual_premium": 5676.00,
    }
    bills = [
        {
            "id": "BILL-X-01",
            "customer_id": "CUST-X",
            "payment_period": "2026-01",
            "amount_paid": 200.00,
            "premium_allocation": {"risk_amount": 100.00, "savings_amount": 100.00},
        },
        {
            "id": "BILL-X-02",
            "customer_id": "CUST-X",
            "payment_period": "2026-02",
            "amount_paid": 350.00,
            "premium_allocation": {"risk_amount": 262.50, "savings_amount": 87.50},
        },
        {
            "id": "BILL-X-03",
            "customer_id": "CUST-X",
            "payment_period": "2026-03",
            "amount_paid": 500.00,
            "premium_allocation": {"risk_amount": 250.00, "savings_amount": 250.00},
        },
    ]
    claims = [
        {"id": "CLM-X-1", "customer_id": "CUST-X", "status": "paid", "paid_amount": 800.00},
        {"id": "CLM-X-2", "customer_id": "CUST-X", "status": "paid", "paid_amount": 120.00},
        {"id": "CLM-X-3", "customer_id": "CUST-X", "status": "pending", "amount": 50.00},
    ]
    ledger: Dict[str, Any] = {}
    for month, amount, risk, savings, bill_id in (
        ("2026-01", 200.00, 100.00, 100.00, "BILL-X-01"),
        ("2026-02", 350.00, 262.50, 87.50, "BILL-X-02"),
        ("2026-03", 500.00, 250.00, 250.00, "BILL-X-03"),
    ):
        mint_token(
            ledger,
            owner_id="CUST-X",
            transaction_type="bill_payment",
            transaction_id=bill_id,
            amount=amount,
            description=f"Premium {month}",
            created_at=f"{month}-02T00:00:00+00:00",
            metadata={
                "payment_period": month,
                "premium_allocation": {"risk_amount": risk, "savings_amount": savings},
            },
        )
    mint_token(
        ledger,
        owner_id="CUST-X",
        transaction_type="claim_payment_received",
        transaction_id="CLM-X-2",
        amount=120.00,
        description="Claim CLM-X-2",
        created_at="2026-02-15T00:00:00+00:00",
        metadata={"claim_id": "CLM-X-2"},
    )
    report = reconcile_customer(
        "CUST-X",
        policies=[policy],
        bills=bills,
        claims=claims,
        nft_ledger=ledger,
    )
    report["specimen"] = True
    report["name"] = "Worked assessment"
    report["writes"] = False
    return report
