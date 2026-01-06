# Supplier Ecosystem + Wallets + Actuary + AI/BI — Phased Implementation Plan

This plan translates the architecture vision into a concrete, buildable sequence that keeps **wallet integrity**, **pricing integrity**, and **actuarial / financial regulations** intact while expanding into:

- **Health suppliers** (consultations, devices, daily supplies, pharmacy, home care)
- **Investment** (trading fees, best execution routing, reporting)
- **Banking/Custody** (holding funds, transfers, custody fees, interest)
- **Advisory** (doctors/lawyers/consultants marketplace + scheduling)
- **Delivery** (courier quotes, tracking, proof-of-delivery)

---

## Guiding constraints (acceptance gates for every phase)

- **Ledger-first money movement**: no “balance mutations” without corresponding **immutable ledger entries**; all wallet actions are **idempotent**.
- **Quote reproducibility**: every quote can be reproduced later via recorded **inputs + versions** (offer snapshot, fee schedule version, actuarial table version, risk inputs hash, delivery quote id).
- **Audit completeness**: every admin/supplier action affecting price, eligibility, settlement, or actuarial rules is audited with actor + timestamp + before/after + reason.
- **Regulated separation of duties**:
  - Actuarial updates require **approval workflow** and immutable versioning.
  - Investment/banking actions require KYC/AML, suitability/best-execution controls, and restricted access.

---

## Phase 0 — Baseline hardening (1–2 weeks)

### Goals
- Make the current platform safe to extend: stable transactions, consistent sessions, enforce audit + data classification.

### Deliverables
- **Move “operational correctness” to shared storage**
  - Sessions: use the existing `sessions` table + repository (`database/repositories/session_repository.py`) everywhere (no in-process session truth).
  - Rate limiting: one implementation (DB or Redis), consistent across API.
- **Transaction boundaries**
  - Introduce explicit transaction scopes for writes (order, wallet, billing, supplier updates).
- **Idempotency**
  - Add a durable `idempotency_keys` table for write endpoints.
- **Audit payload standard**
  - Standardize structured audit details: `{request_id, actor, action, entity_type, entity_id, before, after, reason_codes, versions}`.

### Acceptance checks
- Concurrent writes do not corrupt wallet balances or order status.
- Replay of identical requests with same idempotency key is safe.

---

## Phase 1 — Unified Wallet & Ledger (2–4 weeks)

### Goals
- Make wallet flows production-grade (deposits, holds, capture, refund) and usable for all domains (health/investment/banking/advisory).

### Deliverables
- **Database schema**
  - `wallets`, `ledger_entries`, `wallet_holds`, `external_payments`, `reconciliation_runs`.
- **Wallet API**
  - Deposit (card/bank/claim), create hold, capture hold, release hold, refund/reversal.
- **Reconciliation**
  - Daily reconciliation job: recompute balances from ledger, compare to cached balance, flag anomalies.
- **Security**
  - PCI: do not store card PAN; store PSP tokens only.
  - Ledger entries immutable; reversals are separate entries.

### Acceptance checks
- Hold/capture/refund never results in negative available balance.
- Ledger sums match wallet balance within a strict invariant (no “auto-correct” without explicit audit + admin action).

---

## Phase 2 — Supplier onboarding + catalog + offers (Health first) (3–5 weeks)

### Goals
- Enable suppliers to list products/services and update prices; ensure governance and fraud prevention.

### Deliverables
- **Supplier model**
  - Onboarding status (pending/approved/suspended), payout/settlement account, SLA tier, compliance flags.
- **Supplier Dashboard (MVP)**
  - Manage catalog entries and offers (price, region, availability, capacity).
  - View orders and operational metrics.
- **Admin Dashboard controls**
  - Approve/suspend suppliers; set platform fee schedules (non-actuarial).
- **Data integrity**
  - Every offer update is versioned and audited (supplier actor, timestamp).

### Acceptance checks
- Only approved suppliers appear in client search.
- Supplier cannot edit historical orders or settled pricing.

---

## Phase 3 — Quote, ranking, and “least expensive qualified” (3–6 weeks)

### Goals
- Implement the ranking engine so clients always see the **least expensive eligible** option, with explainability.

### Deliverables
- **Fee schedules by domain**
  - `fee_schedules` table with versions, effective dates, rules JSON.
  - Domains: `HEALTH`, `INVESTMENT`, `BANKING`, `ADVISORY`, `DELIVERY`.
- **Quote & Ranking Service**
  - Inputs: customer context, region, constraints, offer list.
  - Output: ranked offers + computed final price + explanation + versions + expiry.
- **Client Portal updates**
  - “Best price” and alternates; show why a cheaper offer might be ineligible (reason codes).

### Actuarial special care (regulatory controls)
- **Actuarial rules are separately governed**:
  - versioned, immutable after activation
  - role-limited write access (actuary/admin only)
  - approval workflow (maker/checker)
  - explainability: reason codes + factor contributions
  - retention & audit export support

### Acceptance checks
- For any quote, you can reproduce the exact total using stored versions and snapshots.
- Actuarial fee/risk adjustments are traceable and exportable (audit package).

---

## Phase 4 — Cart/Checkout/Orders + Delivery quotes + Settlement (4–8 weeks)

### Goals
- Full commerce flow: cart → delivery quote → checkout (wallet hold/capture) → fulfillment → settlement.

### Deliverables
- **Cart + Order service**
  - Order state machine; idempotent order creation.
- **Delivery service**
  - Courier quote aggregation, shipment creation, tracking, proof-of-delivery.
- **Billing**
  - Invoice/receipt generation and linkage to wallet capture.
- **Settlement**
  - Settlement batches to suppliers derived from ledger + delivered/confirmed status.

### Acceptance checks
- Wallet hold created before supplier confirmation; capture only per configured policy (on confirm or dispatch).
- Settlement uses auditable fee breakdown and is reconcilable to ledger.

---

## Phase 5 — Investment marketplace (fees + best execution) (6–10 weeks)

### Goals
- Add investment as a regulated domain: show lowest fees/spread, route trades compliantly, and produce required reporting.

### Deliverables
- **Investment providers**
  - Broker/exchange integrations; fee schedules and availability.
- **Best execution / routing controls**
  - Route selection based on price/fees + policy constraints (venue eligibility, instrument type).
- **Suitability + risk controls**
  - Customer risk profile gating, leverage limits, restricted instruments.
- **Reporting**
  - Trade confirmations, fee breakdowns, holdings, P&L, audit logs.

### Regulatory special care (investment)
- KYC/AML requirements and transaction monitoring hooks.
- Best-execution evidence: store venue options considered + selection rationale.
- Access segregation: who can modify routing policies/fee tables is restricted and audited.

### Acceptance checks
- Every executed trade can be traced to a routing decision record + policy version.

---

## Phase 6 — Banking/Custody (holding funds + fees + transfers) (6–10 weeks, can overlap Phase 5)

### Goals
- Turn “keeping funds” into a proper custody domain: deposits, withdrawals, transfers, custody fees/interest.

### Deliverables
- **Banking providers**
  - ACH/wire rails integrations (or mocked provider adapters for MVP).
- **Custody fee schedules**
  - Tiered fees; net yield (interest - fees) visibility.
- **Controls**
  - Withdrawal limits, beneficiary allow-list, fraud checks, reconciliation.

### Regulatory special care (banking/custody)
- AML monitoring, sanctions screening (at onboarding and transactions).
- Strong audit and approvals for beneficiary changes and large withdrawals.

### Acceptance checks
- Custody balances reconcile to provider statements and platform ledger.

---

## Phase 7 — Advisory marketplace (doctors/lawyers/consultants) (4–8 weeks)

### Goals
- Enable booking + payment + rating and integrate with Health Wallet and/or Advisory Wallet.

### Deliverables
- Scheduling, availability windows, cancellation policies.
- Advisory fee schedules, ranking by price and SLA.
- Compliance: data minimization for medical/legal details; strong access controls.

---

## Phase 8 — AI/BI platform (evented analytics + governance) (ongoing; begin after Phase 2)

### Goals
- Build an AI/BI layer that can power dashboards and regulated decisioning without breaking integrity.

### Deliverables
- **Event bus + outbox**
  - Append-only domain events for orders, offers, quotes, ledger postings, underwriting, claims.
- **Lakehouse + BI**
  - Curated marts: supplier performance, pricing competitiveness, wallet flows, fraud signals.
- **Feature store**
  - Online/offline parity for underwriting/pricing and marketplace ranking.
- **Model governance**
  - Model registry, versioning, monitoring, drift/fairness checks, human override logging.

### Acceptance checks
- BI is read-only from operational sources; no write-back into OLTP without explicit workflow.
- Model and rule changes are versioned and auditable.

---

## Suggested build order (practical)

1) Phase 0 → Phase 1 (integrity base)
2) Phase 2 (suppliers + offers)
3) Phase 3 (ranking + actuarial governance)
4) Phase 4 (checkout + delivery + settlement)
5) Phase 5 and 6 (investment + banking/custody)
6) Phase 7 (advisory)
7) Phase 8 (AI/BI continuous)

