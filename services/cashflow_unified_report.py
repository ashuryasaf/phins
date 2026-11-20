"""One read-only cash-flow statement across premiums, claims, customer money,
the marketplace, suppliers, and agents.

Authority, in order:

1. The pricing kernel pin is the premium identity. Collected premium fills
   kernel risk first, then an underwriting decision fee, then the expense
   loading and the profit margin, and only then an elected savings add-on.
2. A claim is one payment. The claims book carries the paid amount. The
   customer ledger, the health wallet, the balance sheet, and the NFT seal
   are four records of that one transfer, so the claim is counted once and
   any book that repeats it is listed beside the figure.
3. Savings divide 30 / 65 / 5 across the health wallet, investments, and algo.
4. A marketplace bid is the customer price. Commission comes out of that bid
   and the rest is the supplier payout.
5. The management fee is the reserve configuration's annual rate on assets
   under management (investments and algo). It is shown as an accrual and is
   not charged here.

This module reads the books it is given. It does not write a wallet, a bill,
a claim, a seal, a settlement, or a balance sheet.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from services.premium_flow_reconciliation import (
    _EXPENSE_WEIGHTS,
    _PLATFORM_IDS,
    _SAVINGS_SPLIT,
    _claim_amount,
    _claim_id,
    _claim_paid,
    _partition,
    claim_cash_books,
    reconcile_customer,
    transferred_claim_amounts,
)

_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_SPECIMEN_IDS = frozenset({"CUST-X"})
_IN_FORCE = frozenset({"active", "in_force", "issued", "approved"})
_ORDER_VOID = frozenset({"cancelled", "refunded"})
_WITHDRAWAL_HELD = frozenset({"held"})
_WITHDRAWAL_PAID = frozenset({"paid_out"})
_CLAIM_RESERVED = frozenset({"approved"})
DEFAULT_MANAGEMENT_FEE_PCT = Decimal("0.01")
_MAX_MANAGEMENT_FEE_PCT = Decimal("0.10")


def _dec(value: Any) -> Decimal:
    try:
        number = Decimal(str(value if value is not None else "0"))
    except Exception:
        return _ZERO
    if not number.is_finite():
        return _ZERO
    return number.quantize(_CENT, rounding=ROUND_HALF_UP)


def _f(value: Decimal) -> float:
    return float(value.quantize(_CENT, rounding=ROUND_HALF_UP))


def _rows(store: Any) -> List[Mapping[str, Any]]:
    if store is None:
        return []
    if isinstance(store, Mapping):
        return [row for row in store.values() if isinstance(row, Mapping)]
    return [row for row in store if isinstance(row, Mapping)]


def _status(row: Mapping[str, Any], key: str = "status") -> str:
    return str(row.get(key) or "").strip().lower().replace(" ", "_").replace("-", "_")


def _group(rows: Iterable[Mapping[str, Any]], key: str) -> Dict[str, List[Mapping[str, Any]]]:
    grouped: Dict[str, List[Mapping[str, Any]]] = {}
    for row in rows:
        owner = str(row.get(key) or "").strip()
        if owner:
            grouped.setdefault(owner, []).append(row)
    return grouped


def management_fee_rate(value: Any = None) -> Decimal:
    """Annual fee on assets under management, as a fraction.

    The default is the reserve configuration's own figure. A value above one
    is read as a percentage. The rate stays inside the range the reserve
    configuration accepts.
    """
    if value is None:
        try:
            from services.actuarial_service import ReserveCalculationConfig

            value = ReserveCalculationConfig().management_fee_pct_of_aum
        except Exception:
            value = DEFAULT_MANAGEMENT_FEE_PCT
    try:
        rate = Decimal(str(value))
    except Exception:
        return DEFAULT_MANAGEMENT_FEE_PCT
    if not rate.is_finite() or rate < 0:
        return DEFAULT_MANAGEMENT_FEE_PCT
    if rate > 1:
        rate = rate / Decimal("100")
    return min(rate, _MAX_MANAGEMENT_FEE_PCT)


def _kernel_section(policies: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Annual premium of the in-force book, layered by the cash writer's rule."""
    from services.financial_unification_service import resolve_premium_split

    layers = {name: _ZERO for name in (
        "risk", "underwriting_fee", "expense_loading", "profit", "savings_addon", "above_stack",
    )}
    premium = _ZERO
    labels: Dict[str, int] = {}
    in_force = pinned = sealed = 0
    unpinned: List[str] = []
    for policy in policies:
        if _status(policy) not in _IN_FORCE:
            continue
        annual = _dec(policy.get("annual_premium"))
        if annual <= 0:
            continue
        in_force += 1
        split = resolve_premium_split(float(annual), dict(policy))
        premium += annual
        layers["risk"] += _dec(split.get("risk_amount"))
        layers["underwriting_fee"] += _dec(split.get("underwriting_fee_amount"))
        layers["expense_loading"] += _dec(split.get("expense_amount"))
        layers["profit"] += _dec(split.get("profit_amount"))
        layers["savings_addon"] += _dec(split.get("savings_amount"))
        layers["above_stack"] += _dec(split.get("company_remainder"))
        label = str(split.get("split_label") or "none")
        labels[label] = labels.get(label, 0) + 1
        has_pin = policy.get("risk_premium_annual") is not None or policy.get("risk_premium") is not None
        if has_pin:
            pinned += 1
        elif label != "historical":
            unpinned.append(str(policy.get("id") or policy.get("policy_id") or ""))
        if policy.get("integrity_hash") or split.get("integrity_hash"):
            sealed += 1
    return {
        "policies_in_force": in_force,
        "kernel_pinned": pinned,
        "kernel_sealed": sealed,
        "without_kernel_pin": len(unpinned),
        "without_kernel_pin_ids": [pid for pid in unpinned if pid][:25],
        "allocation_basis": labels,
        "annual_premium": _f(premium),
        "annual": {name: _f(value) for name, value in layers.items()},
    }


def _claims_section(
    claims: Sequence[Mapping[str, Any]],
    books: Mapping[str, Mapping[str, Decimal]],
) -> Dict[str, Any]:
    """Each paid claim once, with what every book says about it."""
    ledger = books.get("ledger") or {}
    wallet = books.get("wallet") or {}
    sheet = books.get("balance_sheet") or {}
    sealed = books.get("sealed") or {}
    rows: List[Dict[str, Any]] = []
    paid_once = transferred_total = unposted_total = reserved = _ZERO
    by_book = {"ledger": _ZERO, "wallet": _ZERO, "balance_sheet": _ZERO, "sealed": _ZERO}
    repeated = {"ledger": _ZERO, "wallet": _ZERO, "balance_sheet": _ZERO, "sealed": _ZERO}
    seen = set()
    for claim in claims:
        claim_id = _claim_id(claim)
        if not claim_id or claim_id in seen:
            continue
        seen.add(claim_id)
        if not _claim_paid(claim):
            if _status(claim) in _CLAIM_RESERVED:
                reserved += _claim_amount(claim)
            continue
        paid = _claim_amount(claim)
        evidence = {
            "ledger": _dec(ledger.get(claim_id)),
            "wallet": _dec(wallet.get(claim_id)),
            "balance_sheet": _dec(sheet.get(claim_id)),
            "sealed": _dec(sealed.get(claim_id)),
        }
        covered = min(paid, max(evidence.values()))
        unposted = max(_ZERO, paid - covered)
        over = {name: max(_ZERO, amount - paid) for name, amount in evidence.items()}
        paid_once += paid
        transferred_total += covered
        unposted_total += unposted
        for name in by_book:
            by_book[name] += evidence[name]
            repeated[name] += over[name]
        rows.append({
            "claim_id": claim_id,
            "customer_id": str(claim.get("customer_id") or ""),
            "status": _status(claim),
            "paid_amount": _f(paid),
            "counted": _f(paid),
            "ledger": _f(evidence["ledger"]),
            "health_wallet": _f(evidence["wallet"]),
            "balance_sheet": _f(evidence["balance_sheet"]),
            "sealed": _f(evidence["sealed"]),
            "transferred": _f(covered),
            "unposted": _f(unposted),
            "repeated": _f(sum(over.values(), _ZERO)),
            "books_recording": sum(1 for amount in evidence.values() if amount > 0),
        })
    orphan = _ZERO
    orphan_ids: List[str] = []
    for claim_id in set(ledger) | set(wallet) | set(sheet):
        if claim_id in seen:
            continue
        orphan += max(_dec(ledger.get(claim_id)), _dec(wallet.get(claim_id)), _dec(sheet.get(claim_id)))
        orphan_ids.append(claim_id)
    rows.sort(key=lambda row: (-row["repeated"], -row["unposted"], row["claim_id"]))
    summed = by_book["ledger"] + by_book["wallet"] + by_book["balance_sheet"]
    return {
        "paid_claims": len(rows),
        "paid_once": _f(paid_once),
        "transferred_to_wallets": _f(transferred_total),
        "unposted": _f(unposted_total),
        "approved_in_reserve": _f(reserved),
        "by_book": {name: _f(value) for name, value in by_book.items()},
        "if_books_were_added": _f(summed),
        "repeated_by_book": {name: _f(value) for name, value in repeated.items()},
        "repeated_total": _f(sum(repeated.values(), _ZERO)),
        "cash_without_claim_record": _f(orphan),
        "cash_without_claim_record_ids": sorted(orphan_ids)[:25],
        "rows": rows[:200],
        "row_count": len(rows),
    }


def _marketplace_section(
    orders: Sequence[Mapping[str, Any]],
    suppliers: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    gross = commission = payout = wallet_funded = external = _ZERO
    void_gross = _ZERO
    settled = pending = disputed = _ZERO
    mismatched: List[str] = []
    counted = 0
    by_supplier: Dict[str, Dict[str, Decimal]] = {}
    for order in orders:
        total = _dec(order.get("total_amount") if order.get("total_amount") is not None else order.get("base_amount"))
        if _status(order) in _ORDER_VOID:
            void_gross += total
            continue
        fee = _dec(order.get("commission"))
        due = _dec(order.get("supplier_payout"))
        counted += 1
        gross += total
        commission += fee
        payout += due
        wallet_funded += _dec(order.get("wallet_deduction"))
        external += _dec(order.get("external_payment_amount"))
        if abs(total - fee - due) > _CENT:
            mismatched.append(str(order.get("id") or ""))
        phase = _status(order, "settlement_status")
        if phase == "settled":
            settled += due
            bucket = "settled"
        elif phase in ("settlement_dispute", "settlement_rejected"):
            disputed += due
            bucket = "disputed"
        else:
            pending += due
            bucket = "pending"
        supplier_id = str(order.get("supplier_id") or "")
        if supplier_id:
            slot = by_supplier.setdefault(supplier_id, {
                "gross": _ZERO, "commission": _ZERO, "settled": _ZERO, "pending": _ZERO, "disputed": _ZERO,
            })
            slot["gross"] += total
            slot["commission"] += fee
            slot[bucket] += due
    supplier_rows = []
    for supplier_id, slot in by_supplier.items():
        record = (suppliers or {}).get(supplier_id) if isinstance(suppliers, Mapping) else None
        name = ""
        if isinstance(record, Mapping):
            name = str(record.get("company_name") or record.get("name") or "")
        supplier_rows.append({
            "supplier_id": supplier_id,
            "name": name,
            **{key: _f(value) for key, value in slot.items()},
        })
    supplier_rows.sort(key=lambda row: (-row["gross"], row["supplier_id"]))
    return {
        "orders": counted,
        "customer_price": _f(gross),
        "commission": _f(commission),
        "supplier_payout": _f(payout),
        "paid_from_health_wallet": _f(wallet_funded),
        "paid_externally": _f(external),
        "cancelled_or_refunded": _f(void_gross),
        "price_minus_commission_and_payout": _f(gross - commission - payout),
        "orders_not_tying": [oid for oid in mismatched if oid][:25],
        "orders_not_tying_count": len(mismatched),
        "suppliers": {
            "settled": _f(settled),
            "pending": _f(pending),
            "disputed": _f(disputed),
            "rows": supplier_rows[:100],
            "supplier_count": len(supplier_rows),
        },
    }


def _referral_code(item: Mapping[str, Any]) -> str:
    for key in ("invitation_code", "code", "source_invitation_code"):
        code = str(item.get(key) or "")
        if code.startswith("REF-"):
            return code
    return ""


def _agents_section(
    commissions: Sequence[Mapping[str, Any]],
    payouts: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    totals = {"accrued": _ZERO, "payable": _ZERO, "paid": _ZERO}
    referral_rail = _ZERO
    agents = set()
    for item in commissions:
        amount = _dec(item.get("amount"))
        if _referral_code(item):
            # A REF- code is paid on the referral book. It is not a second
            # commission, so it is listed and left out of the totals.
            referral_rail += amount
            continue
        status = _status(item)
        if status in totals:
            totals[status] += amount
        agents.add(str(item.get("agent_id") or ""))
    calculated = settled = _ZERO
    for pay in payouts:
        amount = _dec(pay.get("gross_amount") if pay.get("gross_amount") is not None else pay.get("amount"))
        if _status(pay) == "settled":
            settled += amount
        elif _status(pay) == "calculated":
            calculated += amount
    lifetime = totals["accrued"] + totals["payable"] + totals["paid"]
    return {
        "agents": len([agent for agent in agents if agent]),
        "commission_accrued": _f(totals["accrued"]),
        "commission_payable": _f(totals["payable"]),
        "commission_paid": _f(totals["paid"]),
        "commission_lifetime": _f(lifetime),
        "commission_owed": _f(totals["accrued"] + totals["payable"]),
        "payout_runs_calculated": _f(calculated),
        "payout_runs_settled": _f(settled),
        "referral_rows_left_to_referral_book": _f(referral_rail),
    }


def _acquisition_section(
    settlements: Sequence[Mapping[str, Any]],
    balance_sheet: Optional[Mapping[str, Any]],
    expected_expense: Any = None,
) -> Dict[str, Any]:
    """Referral acquisition settlements beside the expense the sheet carries.

    ``expected_expense`` is the referral book's own recomputed expense. It
    includes a reward that was booked before settlements existed. When it is
    absent the allocated settlements are the expectation.
    """
    allocated = blocked = releasable = settled = reversed_cents = retained = 0
    for settlement in settlements:
        if settlement.get("_quarantined"):
            continue
        cents = int(settlement.get("allocated_cents") or 0)
        status = _status(settlement)
        if status == "reversed":
            reversed_cents += cents
            continue
        allocated += cents
        retained += int(settlement.get("retained_cents") or 0)
        if status == "settled":
            settled += cents
        elif status == "releasable":
            releasable += cents
        else:
            blocked += cents
    booked = _dec(((balance_sheet or {}).get("expense_breakdown") or {}).get("customer_acquisition"))
    allocated_amount = Decimal(allocated) / Decimal(100)
    expected = allocated_amount if expected_expense is None else _dec(expected_expense)
    return {
        "settlements": len(settlements),
        "allocated": _f(allocated_amount),
        "expense_expected": _f(expected),
        "blocked": _f(Decimal(blocked) / Decimal(100)),
        "releasable": _f(Decimal(releasable) / Decimal(100)),
        "settled": _f(Decimal(settled) / Decimal(100)),
        "reversed": _f(Decimal(reversed_cents) / Decimal(100)),
        "retained_by_company": _f(Decimal(retained) / Decimal(100)),
        "expense_on_balance_sheet": _f(booked),
        "expense_minus_expected": _f(booked - expected),
    }


def _withdrawals_section(withdrawals: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    held = paid = reversed_amount = declined = _ZERO
    counts = {"held": 0, "paid_out": 0, "reversed": 0, "declined": 0}
    flagged = 0
    for row in withdrawals:
        status = _status(row)
        amount = _dec(row.get("amount"))
        if status in _WITHDRAWAL_HELD:
            held += amount
            counts["held"] += 1
            if (row.get("retention") or {}).get("flag"):
                flagged += 1
        elif status in _WITHDRAWAL_PAID:
            paid += amount
            counts["paid_out"] += 1
        elif status == "reversed":
            reversed_amount += _dec(row.get("requested_amount") if row.get("requested_amount") is not None else row.get("amount"))
            counts["reversed"] += 1
        elif status == "declined":
            declined += _dec(row.get("requested_amount") if row.get("requested_amount") is not None else row.get("amount"))
            counts["declined"] += 1
        released_back = _dec(row.get("released_back"))
        if status in _WITHDRAWAL_HELD | _WITHDRAWAL_PAID and released_back > 0:
            reversed_amount += released_back
    return {
        "held": _f(held),
        "paid_out": _f(paid),
        "returned_to_wallet": _f(reversed_amount),
        "declined": _f(declined),
        "counts": counts,
        "flagged_for_retention": flagged,
    }


_BALANCE_LINES: Tuple[Tuple[str, str], ...] = (
    ("premium_cash", "Premium cash collected"),
    ("claim_cash", "Claims paid"),
    ("claims_reserve", "Claims reserve"),
    ("company_income", "Operating reserve, the company's part of the premium"),
    ("customer_savings", "Held for customers"),
    ("carrier_share", "Held for the carrier"),
    ("reinsurance_ceding_reserve", "Reinsurance ceding reserve"),
)


def _balance_sheet_tie(
    *,
    transactions: Sequence[Mapping[str, Any]],
    policies: Sequence[Mapping[str, Any]],
    bills: Sequence[Mapping[str, Any]],
    paid_months: int,
    statement: Mapping[str, Decimal],
) -> Optional[Dict[str, Any]]:
    """This statement beside the balance sheet's reading of the same cash.

    The statement reads sealed premiums and bills month by month. The balance
    sheet reads the customer ledger payment by payment. Both use the kernel
    pins, so each line is the same amount; a paid month may round by a cent.
    """
    try:
        from services.financial_unification_service import premium_cash_position

        position = premium_cash_position(
            transactions=[dict(row) for row in transactions],
            policies={
                str(row.get("id") or row.get("policy_id") or index): dict(row)
                for index, row in enumerate(policies)
            },
            billing={
                str(row.get("id") or row.get("bill_id") or index): dict(row)
                for index, row in enumerate(bills)
            },
            with_accounting_book=False,
        )
    except Exception:
        return None
    allowance = _CENT * max(1, int(paid_months or 0))
    rows: List[Dict[str, Any]] = []
    largest = _ZERO
    ties = bool(position.get("ties_to_cash"))
    for key, label in _BALANCE_LINES:
        on_statement = _dec(statement.get(key))
        on_sheet = _dec(position.get(key))
        difference = on_statement - on_sheet
        # Cash totals are exact. A split line may round once per paid month.
        limit = _CENT if key in ("premium_cash", "claim_cash") else allowance
        ok = abs(difference) <= limit
        ties = ties and ok
        if abs(difference) > abs(largest):
            largest = difference
        rows.append({
            "key": key,
            "label": label,
            "statement": _f(on_statement),
            "balance_sheet": _f(on_sheet),
            "difference": _f(difference),
            "ok": ok,
        })
    return {
        "ties": ties,
        "largest_difference": _f(largest),
        "rounding_allowance": _f(allowance),
        "total": position.get("total"),
        "net_cash": position.get("net_cash"),
        "own_funds": position.get("own_funds"),
        "held_for_others": position.get("held_for_others"),
        "premium_without_kernel_pin": position.get("premium_without_kernel_pin"),
        "lines": position.get("lines") or [],
        "compared": rows,
    }


def _check(check_id: str, ok: bool, detail: str, amount: Any = None) -> Dict[str, Any]:
    row: Dict[str, Any] = {"id": check_id, "ok": bool(ok), "detail": detail}
    if amount is not None:
        row["amount"] = _f(_dec(amount))
    return row


def unified_cashflow_report(
    *,
    customers: Optional[Mapping[str, Any]] = None,
    policies: Any = (),
    bills: Any = (),
    claims: Any = (),
    nft_ledger: Optional[Mapping[str, Any]] = None,
    transactions: Any = (),
    wallets: Optional[Mapping[str, Any]] = None,
    investments: Optional[Mapping[str, Any]] = None,
    algo: Optional[Mapping[str, Any]] = None,
    balance_sheet: Optional[Mapping[str, Any]] = None,
    orders: Any = (),
    suppliers: Optional[Mapping[str, Any]] = None,
    commissions: Any = (),
    payouts: Any = (),
    referral_settlements: Any = (),
    acquisition_expected_expense: Any = None,
    withdrawals: Any = (),
    management_fee_pct: Any = None,
    exclude_customer: Optional[Callable[[str], bool]] = None,
    as_of: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the unified statement. Every figure is read; nothing is written.

    ``wallets`` is the health-wallet store (rows with ``balance`` and
    ``transactions``). ``investments`` and ``algo`` map a customer id to
    ``{"position": ...}`` and ``{"available": ...}``.
    """

    def _excluded(customer_id: str) -> bool:
        if not customer_id or customer_id in _PLATFORM_IDS or customer_id in _SPECIMEN_IDS:
            return True
        if exclude_customer is None:
            return False
        try:
            return bool(exclude_customer(customer_id))
        except Exception:
            return False

    policy_rows = [row for row in _rows(policies) if not _excluded(str(row.get("customer_id") or ""))]
    bill_rows = [row for row in _rows(bills) if not _excluded(str(row.get("customer_id") or ""))]
    claim_rows = [row for row in _rows(claims) if not _excluded(str(row.get("customer_id") or ""))]
    tx_rows = [row for row in _rows(transactions) if not _excluded(str(row.get("customer_id") or ""))]
    order_rows = [row for row in _rows(orders) if not _excluded(str(row.get("customer_id") or ""))]
    withdrawal_rows = [row for row in _rows(withdrawals) if not _excluded(str(row.get("customer_id") or ""))]
    ledger = nft_ledger or {}
    tokens_by_owner: Dict[str, Dict[str, Any]] = {}
    for token_id, token in ledger.items():
        if not isinstance(token, Mapping):
            continue
        owner = str(token.get("owner_id") or token.get("customer_id") or "")
        if owner and not _excluded(owner):
            tokens_by_owner.setdefault(owner, {})[str(token_id)] = token
    wallet_store = {
        str(customer_id): row for customer_id, row in (wallets or {}).items()
        if isinstance(row, Mapping) and not _excluded(str(customer_id))
    }
    sheet = balance_sheet if isinstance(balance_sheet, Mapping) else {}

    policies_by = _group(policy_rows, "customer_id")
    bills_by = _group(bill_rows, "customer_id")
    claims_by = _group(claim_rows, "customer_id")
    tx_by = _group(tx_rows, "customer_id")

    customer_ids: List[str] = []
    seen = set()
    for source in (policies_by, bills_by, claims_by, tokens_by_owner, wallet_store, investments or {}, algo or {}):
        for customer_id in source.keys():
            customer_id = str(customer_id)
            if customer_id not in seen and not _excluded(customer_id):
                seen.add(customer_id)
                customer_ids.append(customer_id)

    claim_transfers = transferred_claim_amounts(
        transactions=tx_rows, wallets=wallet_store, balance_sheet=sheet,
    )

    landed = {
        name: _ZERO
        for name in (
            "risk", "underwriting_fee", "expense_loading", "profit", "savings",
            "above_stack", "without_kernel_pin",
        )
    }
    due = {name: _ZERO for name in ("risk", "underwriting_fee", "expense_loading", "profit", "savings")}
    collected = booked_risk = booked_savings = savings_paid = _ZERO
    month_count = paid_months = withheld = 0
    flag_counts: Dict[str, int] = {}
    customer_rows: List[Dict[str, Any]] = []
    for customer_id in customer_ids:
        report = reconcile_customer(
            customer_id,
            policies=policies_by.get(customer_id, ()),
            bills=bills_by.get(customer_id, ()),
            claims=claims_by.get(customer_id, ()),
            nft_ledger=tokens_by_owner.get(customer_id, {}),
            claim_transfers=claim_transfers,
            premium_transactions=tx_by.get(customer_id, ()),
        )
        own = {name: _ZERO for name in landed}
        own_collected = _ZERO
        for month in report["months"]:
            month_count += 1
            cash = _dec(month.get("collected"))
            own_collected += cash
            own["risk"] += _dec(month.get("landed_risk"))
            own["underwriting_fee"] += _dec(month.get("landed_underwriting_fee"))
            own["expense_loading"] += _dec(month.get("landed_expense"))
            own["profit"] += _dec(month.get("landed_profit"))
            own["savings"] += _dec(month.get("landed_savings"))
            # Cash on a month with no kernel stack is held on the risk book,
            # where the writer posts it. Cash above a pinned stack is not.
            unpinned = _dec(month.get("no_kernel_pin_cash"))
            own["without_kernel_pin"] += unpinned
            own["above_stack"] += _dec(month.get("overbooked_excess")) - unpinned
            if cash > 0:
                paid_months += 1
                due["risk"] += _dec(month.get("kernel_risk"))
                due["underwriting_fee"] += _dec(month.get("underwriting_fee"))
                due["expense_loading"] += _dec(month.get("expense_loading"))
                due["profit"] += _dec(month.get("profit"))
                due["savings"] += _dec(month.get("savings_addon"))
            if month.get("booked_risk") is not None:
                booked_risk += _dec(month.get("booked_risk"))
            if month.get("booked_savings") is not None:
                booked_savings += _dec(month.get("booked_savings"))
            for flag in month.get("flags") or []:
                flag_counts[str(flag)] = flag_counts.get(str(flag), 0) + 1
        collected += own_collected
        for name in landed:
            landed[name] += own[name]
        withheld += len(report.get("withheld_seals") or [])
        own_paid = _dec((report.get("picture") or {}).get("savings_premiums_paid"))
        savings_paid += own_paid
        wallet_row = wallet_store.get(customer_id) or {}
        investment_row = (investments or {}).get(customer_id) or {}
        algo_row = (algo or {}).get(customer_id) or {}
        # The database-backed store answers ``get`` without being a Mapping.
        record = customers.get(customer_id) if hasattr(customers, "get") else None
        name = ""
        if isinstance(record, Mapping):
            name = str(record.get("name") or record.get("full_name") or "")
        if own_collected > 0 or wallet_row or investment_row or algo_row or claims_by.get(customer_id):
            customer_rows.append({
                "customer_id": customer_id,
                "name": name,
                "premiums_collected": _f(own_collected),
                "risk": _f(own["risk"]),
                "underwriting_fee": _f(own["underwriting_fee"]),
                "expense_loading": _f(own["expense_loading"]),
                "profit": _f(own["profit"]),
                "savings": _f(own["savings"]),
                "savings_premiums_paid": _f(own_paid),
                "health_wallet": _f(_dec(wallet_row.get("balance"))),
                "investments": _f(_dec(investment_row.get("position", investment_row.get("balance")))),
                "algo": _f(_dec(algo_row.get("available", algo_row.get("balance")))),
                "flags": list((report.get("picture") or {}).get("flags") or []),
            })
    customer_rows.sort(key=lambda row: (-row["premiums_collected"], row["customer_id"]))

    landed_total = sum(landed.values(), _ZERO)
    expense_parts = _partition(landed["expense_loading"], _EXPENSE_WEIGHTS)
    savings_parts = _partition(landed["savings"], _SAVINGS_SPLIT)

    books = claim_cash_books(
        transactions=tx_rows,
        wallets=wallet_store,
        balance_sheet=sheet,
        nft_ledger={tid: tok for owner in tokens_by_owner.values() for tid, tok in owner.items()},
    )
    claims_section = _claims_section(claim_rows, books)
    claims_once = _dec(claims_section["paid_once"])

    wallet_total = sum((_dec(row.get("balance")) for row in wallet_store.values()), _ZERO)
    investment_total = _ZERO
    for customer_id, row in (investments or {}).items():
        if isinstance(row, Mapping) and not _excluded(str(customer_id)):
            investment_total += _dec(row.get("position", row.get("balance")))
    algo_total = _ZERO
    for customer_id, row in (algo or {}).items():
        if isinstance(row, Mapping) and not _excluded(str(customer_id)):
            algo_total += _dec(row.get("available", row.get("balance")))
    withdrawals_section = _withdrawals_section(withdrawal_rows)
    held = _dec(withdrawals_section["held"])

    rate = management_fee_rate(management_fee_pct)
    aum = investment_total + algo_total
    annual_fee = (aum * rate).quantize(_CENT, rounding=ROUND_HALF_UP)
    monthly_fee = (annual_fee / Decimal(12)).quantize(_CENT, rounding=ROUND_HALF_UP)
    revenue = sheet.get("revenue_breakdown") if isinstance(sheet.get("revenue_breakdown"), Mapping) else {}
    booked_fee = _dec(revenue.get("management_fees"))

    marketplace = _marketplace_section(order_rows, suppliers)
    agents = _agents_section(_rows(commissions), _rows(payouts))
    acquisition = _acquisition_section(_rows(referral_settlements), sheet, acquisition_expected_expense)
    kernel = _kernel_section(policy_rows)

    # Premium on a policy with no kernel pin is held on the risk book, where
    # the cash writer posts it. It is not company income.
    risk_held = landed["risk"] + landed["without_kernel_pin"]
    surplus = risk_held - claims_once
    loss_ratio = None
    if landed["risk"] > 0:
        loss_ratio = float((claims_once / landed["risk"] * Decimal(100)).quantize(_CENT))
    company_premium_income = (
        landed["underwriting_fee"]
        + _dec(expense_parts["phins_operations"])
        + landed["profit"]
        + landed["above_stack"]
    )
    company_income = company_premium_income + _dec(marketplace["commission"])
    balance = _balance_sheet_tie(
        transactions=tx_rows,
        policies=policy_rows,
        bills=bill_rows,
        paid_months=paid_months,
        statement={
            "premium_cash": collected,
            "claim_cash": claims_once,
            "claims_reserve": surplus,
            "company_income": company_premium_income,
            "customer_savings": landed["savings"],
            "carrier_share": _dec(expense_parts["carrier_share"]),
            "reinsurance_ceding_reserve": _dec(expense_parts["reinsurance_ceding_reserve"]),
        },
    )
    third_party_owed = (
        _dec(marketplace["suppliers"]["pending"])
        + _dec(agents["commission_owed"])
        + _dec(acquisition["blocked"])
        + _dec(acquisition["releasable"])
    )

    if surplus < 0:
        surplus_label = "Drawn from the claims reserve"
    elif landed["without_kernel_pin"] > 0:
        surplus_label = "Held on the risk book, premium with no kernel pin included"
    else:
        surplus_label = "Underwriting surplus"
    statement = [
        {
            "section": "Premium cash collected",
            "total": _f(collected),
            "lines": [
                {"label": "Kernel risk premium", "amount": _f(landed["risk"]), "book": "risk"},
                {"label": "Underwriting decision fee", "amount": _f(landed["underwriting_fee"]), "book": "company"},
                {"label": "Expense loading · PHINS operations", "amount": expense_parts["phins_operations"], "book": "company"},
                {"label": "Expense loading · carrier share", "amount": expense_parts["carrier_share"], "book": "carrier"},
                {"label": "Expense loading · reinsurance ceding reserve", "amount": expense_parts["reinsurance_ceding_reserve"], "book": "reinsurance"},
                {"label": "Profit margin", "amount": _f(landed["profit"]), "book": "company"},
                {"label": "Savings add-on · health wallet (30%)", "amount": savings_parts["health_wallet"], "book": "customer"},
                {"label": "Savings add-on · investments (65%)", "amount": savings_parts["investments"], "book": "customer"},
                {"label": "Savings add-on · algo (5%)", "amount": savings_parts["algo"], "book": "customer"},
                {"label": "Collected above the kernel stack", "amount": _f(landed["above_stack"]), "book": "company"},
                {"label": "Premium on a policy with no kernel pin", "amount": _f(landed["without_kernel_pin"]), "book": "risk"},
            ],
        },
        {
            "section": "Risk book",
            "total": _f(surplus),
            "lines": [
                {"label": "Kernel risk premium collected", "amount": _f(landed["risk"]), "book": "risk"},
                {"label": "Premium with no kernel pin, held until the policy is pinned", "amount": _f(landed["without_kernel_pin"]), "book": "risk"},
                {"label": "Claims paid, each claim once", "amount": _f(-claims_once), "book": "risk"},
                {"label": surplus_label, "amount": _f(surplus), "book": "risk"},
            ],
        },
        {
            "section": "Company income",
            "total": _f(company_income),
            "lines": [
                {"label": "Underwriting decision fee", "amount": _f(landed["underwriting_fee"]), "book": "company"},
                {"label": "Operational cost loading (PHINS share)", "amount": expense_parts["phins_operations"], "book": "company"},
                {"label": "Profit margin", "amount": _f(landed["profit"]), "book": "company"},
                {"label": "Collected above the kernel stack", "amount": _f(landed["above_stack"]), "book": "company"},
                {"label": "Marketplace commission", "amount": marketplace["commission"], "book": "company"},
            ],
            "accruals": [
                {"label": "Management fee on assets under management, per year", "amount": _f(annual_fee)},
                {"label": "Management fee, one month", "amount": _f(monthly_fee)},
            ],
        },
        {
            "section": "Customer money",
            "total": _f(wallet_total + investment_total + algo_total + held),
            "lines": [
                {"label": "Health wallets", "amount": _f(wallet_total), "book": "customer"},
                {"label": "Investments", "amount": _f(investment_total), "book": "customer"},
                {"label": "Algo", "amount": _f(algo_total), "book": "customer"},
                {"label": "Withdrawals held before payout", "amount": _f(held), "book": "customer"},
            ],
        },
        {
            "section": "Owed to suppliers, agents, and affiliates",
            "total": _f(third_party_owed),
            "lines": [
                {"label": "Supplier payouts not yet settled", "amount": marketplace["suppliers"]["pending"], "book": "supplier"},
                {"label": "Agent commission accrued and payable", "amount": agents["commission_owed"], "book": "agent"},
                {"label": "Acquisition rewards blocked", "amount": acquisition["blocked"], "book": "affiliate"},
                {"label": "Acquisition rewards ready to release", "amount": acquisition["releasable"], "book": "affiliate"},
            ],
        },
    ]

    if balance is not None:
        statement.append({
            "section": "Balance sheet · where the premium cash sits",
            "total": balance["total"],
            "lines": [
                {"label": line["label"], "amount": line["amount"], "book": line["holder"]}
                for line in balance["lines"]
            ],
        })

    carved = flag_counts.get("savings_carved_from_premium", 0)
    held_rows = sum(
        (
            _dec(tx.get("amount"))
            for row in wallet_store.values()
            for tx in (row.get("transactions") or [])
            if isinstance(tx, Mapping) and str(tx.get("type") or "") == "withdrawal_hold"
        ),
        _ZERO,
    )
    returned_rows = sum(
        (
            _dec(tx.get("amount"))
            for row in wallet_store.values()
            for tx in (row.get("transactions") or [])
            if isinstance(tx, Mapping) and str(tx.get("type") or "") == "withdrawal_reversal"
        ),
        _ZERO,
    )
    withdrawn_net = held + _dec(withdrawals_section["paid_out"])
    checks = [
        _check(
            "premium_waterfall_ties",
            abs(collected - landed_total) <= _CENT,
            "Collected premium equals risk, fee, expense, profit, savings, and cash above the stack.",
            collected - landed_total,
        ),
        _check(
            "expense_loading_ties",
            abs(sum((_dec(v) for v in expense_parts.values()), _ZERO) - landed["expense_loading"]) <= _CENT,
            "The expense loading is shared in full across operations, the carrier, and the reinsurance ceding reserve.",
        ),
        _check(
            "savings_destinations_tie",
            abs(sum((_dec(v) for v in savings_parts.values()), _ZERO) - landed["savings"]) <= _CENT,
            "The savings add-on is shared in full 30 / 65 / 5.",
        ),
        _check(
            "kernel_risk_not_saved",
            carved == 0,
            "No month booked savings by cutting the kernel risk premium.",
            carved,
        ),
        _check(
            "claims_counted_once",
            _dec(claims_section["repeated_total"]) <= _CENT,
            "No book records a claim above its paid amount. The statement counts each claim once either way.",
            claims_section["repeated_total"],
        ),
        _check(
            "claims_posted",
            _dec(claims_section["unposted"]) <= _CENT,
            "Every paid claim has reached the health wallet.",
            claims_section["unposted"],
        ),
        _check(
            "claim_cash_has_a_claim",
            _dec(claims_section["cash_without_claim_record"]) <= _CENT,
            "Every claim payment on a book belongs to a claim on the claims book.",
            claims_section["cash_without_claim_record"],
        ),
        _check(
            "seals_intact",
            withheld == 0,
            "No customer seal was withheld for a broken checksum.",
            withheld,
        ),
        _check(
            "kernel_pins_present",
            kernel["without_kernel_pin"] == 0,
            "Every in-force policy carries a kernel risk pin or an earlier sealed allocation.",
            kernel["without_kernel_pin"],
        ),
        _check(
            "marketplace_orders_tie",
            marketplace["orders_not_tying_count"] == 0,
            "Each order's customer price equals commission plus supplier payout.",
            marketplace["price_minus_commission_and_payout"],
        ),
        _check(
            "acquisition_expense_ties",
            abs(_dec(acquisition["expense_minus_expected"])) <= _CENT,
            "The acquisition expense on the balance sheet equals the referral book.",
            acquisition["expense_minus_expected"],
        ),
        _check(
            "withdrawals_tie",
            abs((held_rows - returned_rows) - withdrawn_net) <= _CENT,
            "Wallet withdrawal lines equal the withdrawals held and paid out.",
            (held_rows - returned_rows) - withdrawn_net,
        ),
    ]
    if balance is not None:
        checks.append(_check(
            "balance_sheet_ties",
            balance["ties"],
            "Premium cash less claims paid sits on the same balance sheet lines as this statement: "
            "claims reserve, operating reserve, and money held for customers, the carrier, and reinsurance.",
            balance["largest_difference"],
        ))

    return {
        "writes": False,
        "currency": "USD",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of or datetime.now(timezone.utc).date().isoformat(),
        "customer_count": len(customer_ids),
        "basis": [
            "The kernel risk premium is filled first and is never credited to savings.",
            "An underwriting decision fee, the expense loading, and the profit margin stay on company and carrier books.",
            "Only an elected savings add-on reaches the health wallet, investments, and algo, 30 / 65 / 5.",
            "A claim is counted once, at the amount the claims book paid. A second line on any book is listed and not added.",
            "A marketplace bid is the customer price. Commission is taken out of it and the rest is the supplier payout.",
            "The management fee is an accrual on investments and algo. This report does not charge it.",
        ],
        "kernel": kernel,
        "premiums": {
            "collected": _f(collected),
            "months": month_count,
            "kernel_due_for_paid_months": {name: _f(value) for name, value in due.items()},
            "landed": {name: _f(value) for name, value in landed.items()},
            "expense_loading_shares": expense_parts,
            "savings_destinations": savings_parts,
            "savings_premiums_paid": _f(savings_paid),
            "booked_on_bills": {"risk": _f(booked_risk), "savings": _f(booked_savings)},
            "flags": flag_counts,
            "withheld_seals": withheld,
        },
        "claims": claims_section,
        "underwriting": {
            "risk_premium": _f(landed["risk"]),
            "underwriting_fee": _f(landed["underwriting_fee"]),
            "claims_paid": _f(claims_once),
            "premium_without_kernel_pin": _f(landed["without_kernel_pin"]),
            "surplus": _f(surplus),
            "loss_ratio_pct": loss_ratio,
            "claims_reserve": _f(_dec(sheet.get("claims_reserve"))),
            "seed_claims_reserve": _f(_dec(sheet.get("seed_claims_reserve"))),
            "approved_in_reserve": claims_section["approved_in_reserve"],
        },
        "customer_funds": {
            "health_wallet": _f(wallet_total),
            "investments": _f(investment_total),
            "algo": _f(algo_total),
            "withdrawals_held": _f(held),
            "total": _f(wallet_total + investment_total + algo_total + held),
            "assets_under_management": _f(aum),
            "management_fee": {
                "annual_rate_pct": float((rate * Decimal(100)).quantize(Decimal("0.0001"))),
                "basis": "investments_and_algo",
                "annual_at_current_aum": _f(annual_fee),
                "monthly_accrual": _f(monthly_fee),
                "booked_on_balance_sheet": _f(booked_fee),
                "charged_by_this_report": False,
            },
        },
        "marketplace": marketplace,
        "agents": agents,
        "acquisition": acquisition,
        "withdrawals": withdrawals_section,
        "company": {
            "income": _f(company_income),
            "premium_income": _f(company_premium_income),
            "owed_to_third_parties": _f(third_party_owed),
        },
        "balance_sheet": balance,
        "statement": statement,
        "integrity": {
            "ok": all(check["ok"] for check in checks),
            "failed": [check["id"] for check in checks if not check["ok"]],
            "checks": checks,
        },
        "customers": customer_rows[:500],
    }
