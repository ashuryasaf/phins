# Financial Books Unification

**Status:** Implemented (ledger + accounting posting + reconcile API)  
**Date:** 2026-09-04  
**Authority:** Actuarial kernel pricing (premium identity) → customer ledger (cash identity) → accounting book / reserves / balance sheet

---

## 1. Verdict

PHINS had a declared pricing contract (`services/pricing_kernel.py`) and several parallel money books that did not post the same events:

| Book | What it counted | Gap |
|---|---|---|
| Actuarial kernel / PremiumSnapshot | What *should* be billed | Pinned on classic apply; not used for accounting split |
| Policy / bills | Issued and collected amounts | Create stored versions but dropped risk/savings scalars |
| Customer ledger (`TRANSACTION_LEDGER`) | Cash events | Premiums posted; claims posted as `claim_payment_received` |
| Accounting engine | Risk/savings allocations | **Premium collections never posted** (claims did) |
| Balance sheet | `premium_income` / `claims_paid` / reserves | Separate counters; reserve formula ignored collected risk premium |
| Reserves reporting | Allocations + claim *records* | Paid claims ignored customer-ledger cash |

The 2026-08-06 contract assessment remains correct on issuance: chat/unlabeled creates stay on the flat formula unless `PHINS_KERNEL_BILLING_ENABLED` is on. This change does **not** silently reprice history. It unifies *cash posting* and *reconciliation* so every collected premium and every paid claim hits the customer ledger and the accounting book with the same number.

---

## 2. Canonical rules

1. **Premium identity** — `price_policy` / pinned `risk_premium_annual` + `savings_premium_annual` on the policy (or the latest `PremiumSnapshot`). Bills consume the issued amount; they do not invent a new premium.
2. **Cash identity** — the customer ledger. Premium cash types: `premium_payment`, `bill_payment`, `bill_paid`, `premium_received`, `premium_deposit`, `bulk_premium_payment`. `auto_pay_execution` is an audit twin written after the payment and is **not** cash. Claim cash types: `claim_payment_received` (canonical), plus legacy `claim_payment` / `claim_paid` / `claims_paid`.
3. **Accounting book** — posts the same cash, split by the kernel pin when present, otherwise the customer allocation preference.
4. **Claims** — every paid claim is assumed to have been (or must be) written to the customer ledger. Reconcile flags paid records with no ledger row; it does not invent payouts.
5. **No silent rewrite** — reconcile reports discrepancies only. Historical `annual_premium` / `Bill.amount` are never mutated.

---

## 3. What changed

- `services/financial_unification_service.py` — split resolver, idempotent accounting posts, book totals, reconcile report.
- `process_customer_premium_payment` now posts each paid bill (and unbilled remainder) to the shared `AccountingEngine`.
- Policy create persists kernel decomposition (`risk_premium_annual`, `savings_premium_annual`, loadings, sums).
- `compute_unified_financial_metrics` exposes `ledger_premium_collected`, `ledger_claims_paid`, `accounting_*`, and `books_reconcile`.
- `GET /api/finance/reconcile` (admin / accountant / underwriter / actuary).
- Reserves paid-claims path prefers customer-ledger cash when a ledger is attached.
- `try_get_statement_from_engine` reads the **shared** accounting engine (it previously constructed an empty one).
- Gateway `/api/payment/process`, per-bill pay, wallet bulk pay, and `BillingService.record_payment` now write the customer ledger and the accounting book.
- Accountant FRS `claims_paid` uses ledger cash when a ledger is attached; approved-but-unpaid claims are not cash.

---

## 4. Still intentionally dual

- Chat / unlabeled `calculate_premium` remains flat unless `PHINS_KERNEL_BILLING_ENABLED=1` (tests and the chat loopback depend on this).
- `calculate_age_adjusted_premium` still applies a legacy savings override for quote compatibility.
- Balance-sheet `claims_reserve` is still seed capital minus expenses; it is reported, not auto-rewritten, by reconcile.

---

## 5. How to verify

```bash
pytest tests/test_financial_unification.py tests/test_accounting_engine.py tests/test_balance_sheet_integrity.py -q
```

Accountant dashboard → Data Integrity → **Reconcile Books** calls `/api/finance/reconcile`.
