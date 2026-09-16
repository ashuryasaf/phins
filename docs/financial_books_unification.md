# Financial Books Unification

**Status:** Implemented (ledger cash identity + accounting posting + reconcile + repair)  
**Date:** 2026-09-16  
**Authority:** Actuarial kernel pricing (premium identity) → customer ledger (cash identity) → accounting book / reserves / General Reserves balance sheet

---

## 1. Verdict

PHINS had a declared pricing contract (`services/pricing_kernel.py`) and several parallel money books that did not post the same events. Early durability was inconsistent (in-memory dicts, JSON snapshots, later a hash-chained ledger), so a paid bill or paid claim could exist as an operational record without a customer-ledger cash row or an accounting-book entry.

| Book / surface | What it counted | Gap |
|---|---|---|
| Actuarial kernel / PremiumSnapshot | What *should* be billed | Pinned on classic apply; not used for accounting split |
| Policy / bills (`billing.html`) | Issued and collected amounts | Create stored versions but dropped risk/savings scalars |
| Customer ledger (`TRANSACTION_LEDGER`) | Cash events | Premiums posted; claims posted as `claim_payment_received` |
| Accounting engine (`accountant-dashboard.html`) | Risk/savings allocations | Historical premium collections never posted (claims did) |
| General Reserves (`/api/admin/balance-sheet`) | `premium_income` / `claims_paid` / reserves | Separate counters; GET used cumulative not ledger cash |
| Savings / investments (`savings-portfolio.html`) | Pipeline cash + AUM | Kernel savings cash was not compared to landed deposits |
| Claims paid (`dashboard.html#claims`) | Claim *records* | Displayed claimed/approved amount, not ledger cash |
| Seed `claims_reserve` | Founding capital | Fix-reserve and GET could rewrite it from deducted operations |

Issuance now uses the actuarial kernel on every channel (classic apply, chat, unlabeled). Chat finalize also binds the issued premium to `quote_provenance` so the amount the applicant accepted cannot drift from a later table edit. Flat formula remains only as a fail-open fallback or when `PHINS_KERNEL_BILLING_ENABLED=0`. Historical billed premiums are never rewritten.

Cash posting and reconciliation require every collected premium and every paid claim to hit the customer ledger and the accounting book with the same number. When early durability dropped those rows, `POST /api/finance/repair` reconstructs them from paid bills and paid claims. It never invents investment deposits, never mutates `annual_premium` / `Bill.amount`, and never rewrites `seed_claims_reserve`.

---

## 2. Canonical rules

1. **Premium identity** — `price_policy` / pinned `risk_premium_annual` + `savings_premium_annual` on the policy (or the latest `PremiumSnapshot`). Bills consume the issued amount; they do not invent a new premium.
2. **Cash identity** — the customer ledger. Premium cash types: `premium_payment`, `bill_payment`, `bill_paid`, `premium_received`, `premium_deposit`, `bulk_premium_payment`. `auto_pay_execution` is an audit twin written after the payment and is **not** cash. Claim cash types: `claim_payment_received` (canonical), plus legacy `claim_payment` / `claim_paid` / `claims_paid`.
3. **Accounting book** — posts the same cash, split by the kernel pin when present, otherwise the customer allocation preference. Claim posts are idempotent on `claim_id`.
4. **Claims** — every paid/closed claim must have a customer-ledger cash row. Reconcile flags paid records with no ledger row; repair reconstructs from `paid_amount` / `approved_amount`. GET never invents payouts.
5. **General Reserves** — displayed `premium_income` / `claims_paid` are **derived** from ledger cash. Displayed `claims_reserve` is `economic_claims_reserve` (collected risk cash minus claim cash). `seed_claims_reserve` is founding capital and is never rewritten.
6. **Savings / investments** — kernel-split savings cash on the ledger is the identity. Portfolio AUM and pipeline cash are *landed* books. Unlanded savings is a reported discrepancy. Repair does **not** mint investment deposits.
7. **No silent rewrite** — reconcile reports discrepancies only. Historical `annual_premium` / `Bill.amount` / seed capital are never mutated.

---

## 3. What changed

- `services/financial_unification_service.py` — split resolver, idempotent accounting posts, book totals, savings books, derived balance sheet, reconcile report, `repair_financial_books`.
- `process_customer_premium_payment` now posts each paid bill (and unbilled remainder) to the shared `AccountingEngine`.
- Policy create persists kernel decomposition (`risk_premium_annual`, `savings_premium_annual`, loadings, sums).
- `compute_unified_financial_metrics` exposes `ledger_premium_collected`, `ledger_claims_paid`, `accounting_*`, and `books_reconcile`.
- `GET /api/finance/reconcile` (admin / accountant / underwriter / actuary).
- `POST /api/finance/repair` (admin / accountant) — `{"dry_run": true}` previews; apply reconstructs missing cash-identity rows, posts the accounting book, and derives General Reserves counters from the ledger. Audited as `finance.books_repair`.
- `GET /api/admin/balance-sheet` derives `premium_income` / `claims_paid` from the customer ledger. Response `claims_reserve` is economic; `seed_claims_reserve` is separate.
- `/api/admin/balance-sheet/fix-reserve?auto_fix=true` derives the same counters; it no longer rewrites seed capital.
- Billing stats (`/api/billing/stats`, `billing.html`) prefer `ledger_premium_collected` / `ledger_claims_paid`.
- Claims APIs enrich `ledger_paid_amount`; `dashboard.html#claims` displays ledger cash when present.
- Pipeline auto-approve writes `claim_payment_received` onto the attached customer ledger so a wallet credit cannot skip cash identity.
- Accountant FRS `claims_paid` / `total_collected` use ledger cash when a ledger is attached.
- Accountant control tower shows kernel savings cash vs landed investments/pipeline, plus Preview / Repair books.
- `try_get_statement_from_engine` reads the **shared** accounting engine (it previously constructed an empty one).
- Gateway `/api/payment/process`, per-bill pay, wallet bulk pay, and `BillingService.record_payment` now write the customer ledger and the accounting book.
- FRS projection rates (`get_mortality_rate` and siblings) read the central actuarial store.
- `calculate_age_adjusted_premium` calls `price_application_with_kernel` — no private ADL table or `inline_quote_v2` config.
- Reserves reporting without an allocation tracker uses accounting-book risk cash or the kernel pin, not a 75% card.

---

## 4. Repair (early durability)

Assume a paid bill or paid claim may exist without a ledger row. `repair_financial_books`:

1. Appends missing `premium_payment` rows for paid bills (`amount_paid` minus ledger cash already tagged with that `bill_id`).
2. Appends missing `claim_payment_received` rows for paid/closed claims.
3. Posts missing accounting-book premiums from the ledger (kernel split).
4. Posts missing accounting-book claim entries (idempotent on `claim_id`).
5. Derives balance-sheet `premium_income` / `claims_paid` from the ledger **only when they differ**.

Idempotent. `dry_run=True` reports the same actions without mutating. Repair IDs use prefix `TX-REPAIR-`. Seed capital and billed premiums are never rewritten. Unlanded savings stays a discrepancy until a real allocation lands on the savings pipeline or investment book.

Accountant dashboard → Data Integrity → **Preview repair** / **Repair books**.

---

## 5. Still intentionally dual

- Unmapped products (auto / property / business) still use the type-rate card because they have no kernel product.
- Balance-sheet **seed** `claims_reserve` remains founding capital. Reconcile and `/api/admin/balance-sheet` display `economic_claims_reserve` as the claims-reserve identity and never rewrite the seed.
- Savings-portfolio AUM is market value of landed cash, not company premium income. Company identity for savings is kernel-split ledger cash on the accountant control tower.
- Set `PHINS_KERNEL_BILLING_ENABLED=0` only for shadow-only experiments that must keep the flat card.

Age-adjusted quotes, FRS premiums, and FRS year-by-year projection rates now read the central actuarial store / `price_application_with_kernel` path. Reserves reporting no longer invents a 75% risk card when the allocation tracker is empty.

---

## 6. How to verify

```bash
pytest tests/test_financial_unification.py tests/test_accounting_engine.py tests/test_balance_sheet_integrity.py tests/test_accountant_dashboard_ifrs.py tests/test_process_pipeline_orchestrator.py -q
```

Accountant dashboard → Control / Data Integrity → **Reconcile Books** (`GET /api/finance/reconcile`) then **Preview repair** / **Repair books** (`POST /api/finance/repair`).
Billing, claims dashboard, and General Reserves all read `ledger_*` cash fields from the same unification metrics.
