# PHINS Health Marketplace Implementation Specification

## Purpose

This document converts `docs/health_marketplace_architecture.md` into an
execution-ready implementation plan for the current PHINS repository.

It is intentionally grounded in the existing codebase:

- HTTP entrypoint: `web_portal/server.py`
- extension handlers: `web_portal/api_extensions.py`
- customer UI: `web_portal/static/dashboard.html`
- supplier UI: `web_portal/static/supplier-portal.html`
- admin UIs: `web_portal/static/admin.html`,
  `web_portal/static/admin-supplier-dashboard.html`
- current marketplace and supplier services:
  `services/marketplace_service.py`,
  `services/supplier_management_service.py`,
  `services/payment_gateway_service.py`
- current DB layer: `database/models.py`, `database/manager.py`,
  `database/repositories/`
- current integrity and BI: `services/platform_integrity_service.py`,
  `services/bi_analytics_service.py`,
  `docs/platform_data_architecture.md`

The goal is to connect customer demand and supplier supply through a durable,
ledger-safe marketplace that supports:

- customer wallet checkout
- PHINS markup accounting
- supplier settlements
- external supplier APIs
- external insurer eligibility, claims, remittance, refund, and recovery flows
- BI and AI analytics
- reconciliation with zero silent balance mutation

## Execution principles

1. Preserve the current portal topology.
   - Keep `web_portal/server.py` as the HTTP surface.
   - Move new write logic behind services and repositories.

2. Preserve backward compatibility for demo and test flows where practical.
   - Existing in-memory flows may remain as adapters during rollout.
   - New marketplace money movement must be DB-first.

3. Preserve error response conventions.
   - JSON errors remain `{ "error": "..." }`.

4. Make money movement append-only.
   - No mutation of balances without corresponding ledger postings.
   - Corrections are compensating entries, never destructive rewrites.

5. Introduce new domains incrementally.
   - Wallet persistence before settlement.
   - Settlement before external payer recovery.
   - Recovery before advanced BI/AI automation.

## Delivery streams

The implementation should be organized into six workstreams that can be run in
parallel after the wallet foundation is in place.

### Stream A - Durable financial core

- wallet accounts
- wallet holds
- wallet ledger
- payment intents
- refunds
- accounting journal entries

### Stream B - Marketplace order core

- quotes
- order orchestration
- supplier offer snapshots
- delivery and appointment hooks
- order lifecycle controls

### Stream C - Supplier settlement and connectivity

- supplier payout workflows
- reserve holdbacks
- payout reconciliation
- connector registry
- catalog and order sync

### Stream D - External payer recovery

- eligibility checks
- pre-authorization
- marketplace claims
- remittance ingestion
- payer receivables

### Stream E - Dashboards and operator tooling

- customer wallet and reimbursement UX
- supplier settlement and payout UX
- admin governance and exception queues
- finance and actuarial reporting

### Stream F - Integrity, BI, and AI

- outbox events
- reconciliation jobs
- executive and finance metrics
- fraud, leakage, and ranking features

## Release sequence

### Release 1 - Source-of-truth and wallet integrity

Primary outcome:
- all marketplace money movement becomes repository-backed

Includes:
- new wallet and payment schema
- new wallet repositories and services
- balance sheet posting rules for markup and supplier payable
- compatibility adapters from current `HEALTH_WALLETS` and transaction dicts

### Release 2 - Quote, checkout, and order orchestration

Primary outcome:
- `dashboard.html` purchases run through quote -> hold -> capture -> order

Includes:
- quote persistence
- order snapshots
- order lifecycle APIs
- supplier order acceptance hooks

### Release 3 - Supplier settlement and external supplier APIs

Primary outcome:
- supplier payouts become durable and reconcilable

Includes:
- settlement runs
- payout records
- connector configs
- catalog sync and order callback APIs

### Release 4 - External payer eligibility and reimbursement

Primary outcome:
- PHINS can recover from external insurers and process refund/reimbursement flows

Includes:
- eligibility and preauth
- marketplace claims and receivables
- remittance import
- denial and appeal queues

### Release 5 - BI, AI, and operational control plane

Primary outcome:
- finance, ops, supplier, and payer dashboards run off canonical events and
  reconciled facts

Includes:
- outbox events
- warehouse-facing contracts
- anomaly detection
- profitability and leakage metrics

## Database schema changes

## 1. Extend existing tables

These changes should be implemented in `database/models.py` and wired into the
existing compatibility bootstrapping in `database/__init__.py`.

### `supplier_orders`

Existing model already provides:

- `platform_fee`
- `supplier_payout`
- `payment_method`
- `wallet_transaction_id`
- `payment_status`

Add:

- `quote_id` - nullable, indexed
- `payment_intent_id` - nullable, indexed
- `wallet_hold_id` - nullable, indexed
- `marketplace_claim_id` - nullable, indexed
- `pricing_explanation_id` - nullable, indexed
- `gross_sales_amount` - float, non-null, default `0.0`
- `supplier_cost_amount` - float, non-null, default `0.0`
- `markup_amount` - float, non-null, default `0.0`
- `markup_percent` - float, non-null, default `0.0`
- `covered_amount` - float, non-null, default `0.0`
- `customer_responsibility_amount` - float, non-null, default `0.0`
- `payer_responsibility_amount` - float, non-null, default `0.0`
- `currency` - string(10), default `USD`
- `capture_policy` - string(50), default `on_supplier_accept`
- `fulfillment_mode` - string(50), nullable
- `idempotency_key` - string(100), nullable, indexed
- `external_order_reference` - string(100), nullable
- `external_fulfillment_reference` - string(100), nullable

Constraints:

- `total_amount >= 0`
- `supplier_payout >= 0`
- `markup_amount = total_amount - supplier_cost_amount` at service layer
- `covered_amount + customer_responsibility_amount >= total_amount` only for
  captured orders when mixed tender or payer flows are active

Indexes:

- `(customer_id, created_date desc)`
- `(supplier_id, status, created_date desc)`
- `(payment_status, status)`
- `(marketplace_claim_id)`

### `suppliers`

Keep the current supplier onboarding model and add:

- `network_contract_id` - nullable, indexed
- `connector_mode` - string(50), default `portal`
- `connector_status` - string(50), default `inactive`
- `payout_method` - string(50), default `bank_transfer`
- `reserve_holdback_rate` - float, default `0.0`
- `settlement_currency` - string(10), default `USD`
- `last_catalog_sync_at` - datetime, nullable
- `last_order_sync_at` - datetime, nullable
- `connector_metadata` - text/json

### `supplier_offers`

Add:

- `external_offer_reference` - nullable, indexed
- `catalog_version_id` - nullable, indexed
- `coverage_eligible` - boolean, default `true`
- `prescription_required` - boolean, default `false`
- `preauth_required` - boolean, default `false`
- `sla_tier` - string(50), nullable
- `inventory_count` - integer, nullable
- `price_effective_from` - datetime, nullable
- `price_effective_to` - datetime, nullable
- `normalization_hash` - string(64), nullable

## 2. New tables

The names below should be used directly in `database/models.py` unless there is
an existing repo naming standard that requires plural/singular adjustment.

### Wallet and payment tables

#### `wallet_accounts`

Purpose:
- canonical wallet balance source for health and later other wallet domains

Columns:
- `id` PK
- `customer_id` indexed, FK to `customers.id`
- `wallet_type` string(50) indexed
- `currency` string(10) default `USD`
- `available_balance` float default `0.0`
- `held_balance` float default `0.0`
- `posted_balance` float default `0.0`
- `status` string(50) default `active`
- `version_no` integer default `1`
- `created_date`, `updated_date`

Constraints:
- unique `(customer_id, wallet_type, currency)`
- non-negative `available_balance`, `held_balance`

#### `wallet_holds`

Purpose:
- authorize wallet funds before supplier confirmation and capture

Columns:
- `id` PK
- `wallet_account_id` indexed, FK
- `customer_id` indexed
- `order_id` indexed, nullable
- `payment_intent_id` indexed
- `amount`
- `currency`
- `status` string(50) indexed (`held`, `captured`, `released`, `expired`)
- `expires_at`
- `capture_reference`
- `release_reason`
- `idempotency_key` string(100) indexed
- `created_date`, `updated_date`

Constraints:
- unique `(idempotency_key)` for create-hold operation

#### `wallet_ledger_entries`

Purpose:
- customer wallet sub-ledger with append-only postings

Columns:
- `id` PK
- `wallet_account_id` indexed
- `customer_id` indexed
- `entry_group_id` indexed
- `entry_type` string(50) indexed
- `direction` string(10) (`debit`/`credit`)
- `amount`
- `currency`
- `reference_type` string(50)
- `reference_id` string(100) indexed
- `counterparty_type` string(50)
- `counterparty_id` string(100)
- `status` string(50)
- `posted_at`
- `metadata_json` text
- `previous_hash`
- `entry_hash`

Constraints:
- immutable after insert
- no update endpoint

Indexes:
- `(wallet_account_id, posted_at desc)`
- `(reference_type, reference_id)`
- `(entry_group_id)`

#### `payment_intents`

Purpose:
- single payment object binding wallet, card, payer, or mixed-tender strategy

Columns:
- `id` PK
- `customer_id` indexed
- `order_id` indexed
- `quote_id` indexed, nullable
- `funding_strategy` string(50)
- `status` string(50) indexed
- `currency`
- `total_amount`
- `wallet_amount`
- `external_amount`
- `payer_amount`
- `psp_reference`
- `payer_authorization_reference`
- `idempotency_key` indexed
- `created_date`, `updated_date`

#### `payment_attempts`

Purpose:
- one-to-many detail records for PSP or alternative payment attempts

Columns:
- `id` PK
- `payment_intent_id` indexed
- `attempt_no`
- `gateway`
- `payment_method`
- `status`
- `external_reference`
- `request_payload_hash`
- `response_payload_json`
- `error_message`
- `created_date`

#### `refunds`

Purpose:
- durable reversal workflow for customer, supplier, and payer-driven refunds

Columns:
- `id` PK
- `order_id` indexed
- `payment_intent_id` indexed
- `wallet_ledger_entry_id` nullable
- `funding_source` string(50)
- `reason_code` string(50)
- `status` string(50) indexed
- `amount`
- `currency`
- `requested_by`
- `approved_by`
- `external_refund_reference`
- `created_date`, `processed_date`

### Accounting and settlement tables

#### `journal_entries`

Purpose:
- accounting view for recognized revenue, payables, receivables, and liabilities

Columns:
- `id` PK
- `entry_group_id` indexed
- `account_code` indexed
- `direction`
- `amount`
- `currency`
- `reference_type`
- `reference_id`
- `journal_date`
- `description`
- `metadata_json`

Recommended account codes:
- `wallet_cash`
- `wallet_holds`
- `marketplace_clearing`
- `supplier_payable`
- `marketplace_revenue`
- `deferred_marketplace_revenue`
- `marketplace_contra_revenue`
- `payer_receivable`
- `refund_liability`
- `claims_reserve`
- `supplier_reserve_holdback`

#### `supplier_settlement_runs`

Purpose:
- batch execution boundary for supplier payouts

Columns:
- `id` PK
- `supplier_id` indexed
- `run_date`
- `settlement_period_start`
- `settlement_period_end`
- `status` indexed
- `gross_amount`
- `net_amount`
- `holdback_amount`
- `adjustment_amount`
- `currency`
- `executed_by`
- `external_payout_reference`
- `created_date`, `updated_date`

#### `supplier_settlement_items`

Purpose:
- order-level settlement rows under a settlement run

Columns:
- `id` PK
- `settlement_run_id` indexed
- `supplier_id` indexed
- `order_id` indexed
- `gross_sales_amount`
- `markup_amount`
- `supplier_payout_amount`
- `holdback_amount`
- `penalty_amount`
- `adjustment_amount`
- `status` indexed
- `created_date`

### Supplier connector and catalog tables

#### `supplier_connectors`

Purpose:
- durable connector registry and health state

Columns:
- `id` PK
- `supplier_id` indexed
- `connector_type` string(50) (`portal`, `api`, `edi`, `aggregator`)
- `status` string(50)
- `base_url`
- `auth_scheme`
- `secret_reference`
- `webhook_secret_reference`
- `capabilities_json`
- `last_health_check_at`
- `last_health_status`
- `created_date`, `updated_date`

#### `supplier_catalog_versions`

Purpose:
- immutable catalog import/version snapshot

Columns:
- `id` PK
- `supplier_id` indexed
- `source_type`
- `source_reference`
- `version_hash`
- `row_count`
- `status`
- `imported_at`
- `metadata_json`

#### `supplier_inventory_snapshots`

Purpose:
- latest imported availability/inventory view for external suppliers

Columns:
- `id` PK
- `supplier_id` indexed
- `offer_id` indexed
- `snapshot_at`
- `inventory_count`
- `availability_json`
- `source_reference`

### External payer tables

#### `external_payers`

Purpose:
- payer directory for insurers, TPAs, employers, and sponsors

Columns:
- `id` PK
- `payer_name`
- `payer_type`
- `country`
- `currency`
- `status`
- `eligibility_endpoint`
- `preauth_endpoint`
- `claims_endpoint`
- `remittance_import_mode`
- `connector_config_json`
- `created_date`, `updated_date`

#### `coverage_checks`

Purpose:
- persisted result of eligibility and benefit lookup

Columns:
- `id` PK
- `customer_id` indexed
- `payer_id` indexed
- `quote_id` indexed, nullable
- `order_id` indexed, nullable
- `status`
- `coverage_percent`
- `covered_amount`
- `deductible_amount`
- `copay_amount`
- `coinsurance_amount`
- `network_status`
- `response_payload_json`
- `checked_at`
- `expires_at`

#### `pre_authorizations`

Purpose:
- payer approval state before order capture

Columns:
- `id` PK
- `customer_id` indexed
- `payer_id` indexed
- `order_id` indexed
- `status` indexed
- `approved_amount`
- `authorization_code`
- `submitted_payload_json`
- `response_payload_json`
- `submitted_at`
- `decision_at`
- `expires_at`

#### `marketplace_claims`

Purpose:
- claim-as-a-service record created from marketplace orders

Columns:
- `id` PK
- `order_id` indexed
- `customer_id` indexed
- `payer_id` indexed
- `claim_type`
- `status` indexed
- `claimed_amount`
- `approved_amount`
- `denied_amount`
- `submission_reference`
- `diagnosis_code`
- `service_date`
- `submitted_at`
- `adjudicated_at`
- `metadata_json`

#### `payer_submissions`

Purpose:
- immutable submission attempts to external insurers

Columns:
- `id` PK
- `marketplace_claim_id` indexed
- `submission_type` (`eligibility`, `preauth`, `claim`, `appeal`)
- `status`
- `idempotency_key` indexed
- `request_payload_hash`
- `response_payload_json`
- `submitted_at`

#### `remittance_advices`

Purpose:
- import header for payer remittance

Columns:
- `id` PK
- `payer_id` indexed
- `remittance_reference` indexed
- `status`
- `received_at`
- `total_paid_amount`
- `total_denied_amount`
- `raw_payload_json`

#### `remittance_lines`

Purpose:
- one remittance row per claim or order line

Columns:
- `id` PK
- `remittance_advice_id` indexed
- `marketplace_claim_id` indexed
- `order_id` indexed, nullable
- `line_status`
- `paid_amount`
- `denied_amount`
- `adjustment_reason_code`
- `created_date`

#### `payer_receivables`

Purpose:
- open recovery ledger for PHINS-advanced or customer-reimbursable funds

Columns:
- `id` PK
- `payer_id` indexed
- `marketplace_claim_id` indexed
- `order_id` indexed
- `expected_amount`
- `open_amount`
- `received_amount`
- `writeoff_amount`
- `status` indexed
- `due_date`
- `last_activity_at`
- `created_date`, `updated_date`

### Integrity and platform-control tables

#### `idempotency_keys`

Purpose:
- durable request replay protection for all write endpoints

Columns:
- `id` PK
- `scope` indexed
- `idempotency_key` indexed unique
- `request_hash`
- `resource_type`
- `resource_id`
- `response_snapshot_json`
- `status`
- `created_date`

#### `outbox_events`

Purpose:
- transactional outbox for BI/AI/event publication

Columns:
- `id` PK
- `aggregate_type`
- `aggregate_id`
- `event_type` indexed
- `event_version`
- `payload_json`
- `status` indexed
- `published_at`
- `created_date`

#### `reconciliation_runs`

Purpose:
- auditable reconciliation run history

Columns:
- `id` PK
- `run_type` indexed
- `status`
- `started_at`
- `finished_at`
- `variance_amount`
- `summary_json`

#### `reconciliation_findings`

Purpose:
- one finding per mismatch or invariant breach

Columns:
- `id` PK
- `reconciliation_run_id` indexed
- `severity` indexed
- `entity_type`
- `entity_id`
- `finding_code`
- `expected_value`
- `actual_value`
- `details_json`
- `resolved`
- `resolved_at`

#### `pricing_explanations`

Purpose:
- reproducible quote and pricing rationale

Columns:
- `id` PK
- `quote_id` indexed
- `order_id` indexed, nullable
- `pricing_version`
- `fee_schedule_version`
- `actuarial_version`
- `ranking_model_version`
- `markup_percent`
- `explanation_json`
- `created_date`

## 3. Repository and model migration sequence

### Migration order

1. Extend `database/models.py`
2. Add new repositories under `database/repositories/`
3. Wire repositories into `database/repositories/__init__.py`
4. Wire manager accessors into `database/manager.py`
5. Extend `database/__init__.py` compatibility DDL bootstrap
6. Add migration helpers in `database/migrate_data.py`
7. Add seed data only where required for tests

### Backfill rules

Backfill from in-memory structures in this order:

1. `HEALTH_WALLETS` -> `wallet_accounts`
2. purchase transactions -> `wallet_ledger_entries`
3. `SUPPLIERS` -> `suppliers`
4. `SUPPLIER_OFFERS` -> `supplier_offers`
5. `SUPPLIER_ORDERS` -> `supplier_orders`
6. existing marketplace payment metadata -> `payment_intents`
7. existing supplier payout fields -> `supplier_settlement_items`

Backfill must:

- preserve original timestamps when present
- preserve legacy IDs
- emit `platform_ledger_entries` replay events where practical
- produce a migration report with skipped or malformed rows

## Service and repository breakdown

## 1. Repository additions

Add the following files under `database/repositories/`.

### New repositories

- `supplier_repository.py`
  - CRUD + approval queue + connector health queries
- `supplier_offer_repository.py`
  - active offers, search filters, latest catalog version lookup
- `supplier_order_repository.py`
  - customer order history, supplier work queue, status transitions
- `wallet_account_repository.py`
  - get by `(customer_id, wallet_type)`, optimistic version checks
- `wallet_hold_repository.py`
  - create/release/capture holds, expiry sweep
- `wallet_ledger_repository.py`
  - append-only posting, balance rollup queries
- `payment_intent_repository.py`
  - idempotent create, status lookup, mixed-tender breakdown
- `refund_repository.py`
  - refund workflows and pending refunds
- `journal_repository.py`
  - account-code summaries and journal views
- `supplier_settlement_repository.py`
  - settlement runs and payout aging
- `supplier_connector_repository.py`
  - connector configuration and health tracking
- `external_payer_repository.py`
  - payer directory and connectivity metadata
- `coverage_check_repository.py`
  - current coverage result and validity window lookup
- `preauth_repository.py`
  - payer approval state
- `marketplace_claim_repository.py`
  - claim lifecycle and denial queue
- `remittance_repository.py`
  - remittance header + line import
- `payer_receivable_repository.py`
  - open receivable aging
- `idempotency_repository.py`
  - request replay protection
- `outbox_repository.py`
  - pending event polling
- `reconciliation_repository.py`
  - reconciliation run + finding persistence
- `pricing_explanation_repository.py`
  - quote and order explanation snapshots

### Existing repositories to update

- `platform_ledger_repository.py`
  - add event lookup by `reference_type/reference_id`
- `audit_repository.py`
  - standardized details payload helpers
- `claim_repository.py`
  - add marketplace-claim linking when the claim maps to order recovery

### `DatabaseManager` changes

Add properties for all new repositories to `database/manager.py`, keeping the
current lazy-loading pattern.

## 2. Service layer target structure

The current services already contain useful behavior, but responsibilities need
to be separated so financial integrity is enforceable.

### Services to create

#### `services/wallet_ledger_service.py`

Owns:
- wallet creation
- deposit
- hold creation
- hold capture
- hold release
- wallet refunds
- wallet balance derivation

Depends on:
- `wallet_account_repository`
- `wallet_hold_repository`
- `wallet_ledger_repository`
- `journal_repository`
- `platform_event_ledger_service`
- `audit_service`

Must expose:
- `get_or_create_wallet(customer_id, wallet_type)`
- `create_hold(...)`
- `capture_hold(...)`
- `release_hold(...)`
- `post_credit(...)`
- `post_debit(...)`
- `recompute_balances(...)`

#### `services/marketplace_checkout_service.py`

Owns:
- quote acceptance
- payment intent creation
- order creation
- supplier routing
- capture policy application

Depends on:
- `marketplace_catalog_service`
- `coverage_eligibility_service`
- `wallet_ledger_service`
- `marketplace_accounting_service`
- `supplier_order_service`
- `idempotency_repository`

Must expose:
- `create_quote(...)`
- `create_order(...)`
- `cancel_order(...)`
- `accept_supplier_confirmation(...)`

#### `services/marketplace_accounting_service.py`

Owns:
- markup computation
- journal postings
- balance sheet projection inputs
- supplier payable posting
- refund reversal posting

Depends on:
- `journal_repository`
- `wallet_ledger_repository`
- `supplier_settlement_repository`

Must expose:
- `calculate_order_financials(...)`
- `post_capture_entries(...)`
- `post_refund_entries(...)`
- `get_marketplace_finance_summary(...)`

#### `services/supplier_settlement_service.py`

Owns:
- settlement run creation
- order inclusion rules
- payout remittance generation
- clawbacks and holdbacks

Depends on:
- `supplier_settlement_repository`
- `supplier_order_repository`
- `journal_repository`
- `payment_gateway_service`
- `reconciliation_service`

Must expose:
- `build_settlement_run(supplier_id, period_start, period_end)`
- `execute_settlement_run(run_id)`
- `record_payout_result(...)`
- `apply_clawback(...)`

#### `services/coverage_eligibility_service.py`

Owns:
- coverage lookup
- network and benefit validation
- checkout coverage decision

Depends on:
- `external_payer_service`
- `coverage_check_repository`
- `pricing_explanation_repository`

Must expose:
- `check_eligibility(customer_id, items, payer_context)`
- `apply_coverage_to_quote(...)`

#### `services/external_payer_service.py`

Owns:
- payer connector calls
- preauth submission
- claim submission
- remittance import normalization

Depends on:
- `external_payer_repository`
- `marketplace_claim_repository`
- `remittance_repository`
- `payer_receivable_repository`
- `idempotency_repository`

Must expose:
- `submit_preauth(...)`
- `submit_marketplace_claim(...)`
- `import_remittance(...)`
- `apply_remittance(...)`

#### `services/supplier_connector_service.py`

Owns:
- supplier API registration
- catalog sync
- inventory sync
- order callbacks

Depends on:
- `supplier_connector_repository`
- `supplier_repository`
- `supplier_offer_repository`
- `supplier_order_repository`
- `idempotency_repository`

Must expose:
- `sync_catalog(...)`
- `handle_order_callback(...)`
- `run_health_check(...)`

#### `services/reconciliation_service.py`

Owns:
- scheduled and on-demand reconciliations
- variance detection
- finding severity classification

Depends on:
- `reconciliation_repository`
- wallet, journal, settlement, receivable, remittance repos
- `platform_integrity_service`

Must expose:
- `run_wallet_reconciliation()`
- `run_settlement_reconciliation()`
- `run_payer_reconciliation()`
- `run_marketplace_integrity_summary()`

#### `services/marketplace_event_service.py`

Owns:
- outbox event construction
- event versioning
- BI/AI payload contracts

Depends on:
- `outbox_repository`
- `platform_event_ledger_service`

Must expose:
- `publish_order_created(...)`
- `publish_capture_posted(...)`
- `publish_remittance_received(...)`

### Existing services to refactor

#### `services/supplier_management_service.py`

Keep, but narrow to:
- onboarding
- approval workflow
- supplier profile and compliance

Move out:
- financial capture logic
- payout logic
- wallet posting logic

#### `services/marketplace_service.py`

Keep, but narrow to:
- category taxonomy
- search
- ranking
- quote shaping
- compatibility adapters for old marketplace APIs

Move out:
- external connector concerns
- payment execution
- refund posting

#### `services/payment_gateway_service.py`

Keep as PSP adapter layer only.

Add responsibilities:
- payout execution hooks for supplier settlement
- refund execution for external card/PSP flows
- webhook verification helpers

#### `services/platform_integrity_service.py`

Extend with new validations:
- wallet hold coverage
- order -> payment_intent -> hold -> capture linkage
- settlement aging
- payer receivable aging
- remittance application completeness
- markup consistency against journal

#### `services/bi_analytics_service.py`

Extend with new marts:
- marketplace executive KPI
- supplier settlement KPI
- payer recovery KPI
- refund and denial leakage KPI

## 3. HTTP routing breakdown

`web_portal/server.py` should remain the entrypoint, but new handlers should use
thin wrappers that call services.

Recommended internal organization:

- existing supplier routes remain under current route families
- new wallet and payer routes can be added in `server.py`
- helper parsing/serialization functions can be added in
  `web_portal/api_extensions.py` if route density grows

Thin-handler rule:

- request parse
- auth/role check
- call service
- serialize response
- preserve `{ "error": "..." }` on failure

## API contract list

All new write APIs require:

- bearer token auth unless explicitly admin/system scoped
- `Idempotency-Key` header for create/update financial writes
- JSON request and response

All list endpoints should preserve or adopt:

`{ "items": [], "page": 1, "page_size": 50, "total": 0 }`

## 1. Customer marketplace APIs

### `GET /api/marketplace/search`

Auth:
- customer or admin acting on behalf of customer

Query:
- `category`
- `sub_category`
- `wallet`
- `location`
- `page`
- `page_size`
- `sort`

Response:
- paginated offers
- current coverage and wallet context summary
- ranking metadata

Example success fields:
- `items`
- `coverage_summary`
- `wallet_summary`
- `ranking_version`
- `page`
- `page_size`
- `total`

### `POST /api/marketplace/quotes`

Auth:
- customer

Purpose:
- produce a reproducible quote before order creation

Request:
```json
{
  "customer_id": "CUST-001",
  "wallet_type": "health",
  "items": [
    {
      "offer_id": "OFF-001",
      "quantity": 2
    }
  ],
  "location": {
    "country": "US",
    "city": "Austin"
  },
  "payer_context": {
    "payer_id": "PAY-001",
    "use_external_coverage": true
  }
}
```

Response:
```json
{
  "quote": {
    "id": "QUO-001",
    "status": "quoted",
    "total_amount": 145.0,
    "covered_amount": 80.0,
    "customer_responsibility_amount": 65.0,
    "supplier_cost_amount": 120.0,
    "markup_amount": 25.0,
    "markup_percent": 20.83,
    "expires_at": "2026-03-25T10:00:00Z"
  },
  "pricing_explanation": {
    "id": "PEX-001",
    "ranking_version": "marketplace-ranking-v1",
    "actuarial_version": "health-fee-2026-03",
    "reason_codes": ["coverage_applied", "best_price"]
  }
}
```

### `POST /api/marketplace/orders`

Auth:
- customer

Purpose:
- create order and payment intent from an existing quote or direct selection

Request:
```json
{
  "quote_id": "QUO-001",
  "payment_strategy": {
    "wallet_type": "health",
    "fallback_method": "credit_card"
  },
  "capture_policy": "on_supplier_accept",
  "delivery_selection": {
    "mode": "delivery",
    "address": "123 Main St"
  }
}
```

Response:
```json
{
  "order": {
    "id": "ORD-001",
    "status": "pending_supplier_acceptance",
    "payment_status": "authorized",
    "total_amount": 145.0
  },
  "payment_intent": {
    "id": "PAYINT-001",
    "status": "authorized"
  },
  "wallet_hold": {
    "id": "HOLD-001",
    "status": "held",
    "amount": 65.0
  }
}
```

### `GET /api/marketplace/orders/{order_id}`

Auth:
- customer owner, supplier owner, admin

Response:
- order header
- item list
- payment state
- settlement summary if supplier/admin
- reimbursement summary if present

### `POST /api/marketplace/orders/{order_id}/cancel`

Auth:
- customer owner or admin

Behavior:
- releases hold if uncaptured
- creates refund if captured

### `GET /api/marketplace/orders`

Auth:
- customer owner or admin

Query:
- `status`
- `from`
- `to`
- `page`
- `page_size`

## 2. Wallet and payment APIs

### `GET /api/wallets/health`

Auth:
- customer or admin

Response:
- `available_balance`
- `held_balance`
- `posted_balance`
- recent ledger entries

### `POST /api/wallet/payment-intents`

Auth:
- customer or service call from order flow

Purpose:
- create standalone intent for wallet/card/payer mixed tender

### `POST /api/wallet/holds`

Auth:
- internal/service path only

### `POST /api/wallet/holds/{hold_id}/capture`

Auth:
- internal/service path only

### `POST /api/wallet/holds/{hold_id}/release`

Auth:
- internal/service path only

### `POST /api/wallet/refunds`

Auth:
- admin, accountant, or system refund workflow

Request:
- `order_id`
- `amount`
- `reason_code`
- `funding_source`

## 3. Supplier APIs

Maintain current supplier routes and extend them rather than replacing them.

### Keep and harden current routes

- `POST /api/supplier/register`
- `POST /api/supplier/login`
- `GET /api/supplier/profile`
- `GET /api/supplier/offers`
- `POST /api/supplier/offers/upsert`
- `POST /api/supplier/offers/delete`
- `GET /api/supplier/orders`
- `POST /api/supplier/orders/update-status`

### Add new supplier operations

#### `GET /api/supplier/settlements`

Auth:
- supplier

Response:
- paginated settlement runs and aging

#### `GET /api/supplier/settlements/{run_id}`

Auth:
- supplier owner or admin

#### `GET /api/supplier/connectors`

Auth:
- supplier owner or admin

#### `POST /api/supplier/connectors`

Auth:
- supplier owner or admin

Request:
- `connector_type`
- `base_url`
- `auth_scheme`
- `capabilities`

#### `POST /api/supplier/connectors/catalog-sync`

Auth:
- supplier owner, admin, or system

Behavior:
- import or refresh external supplier catalog

#### `POST /api/supplier/connectors/order-callback`

Auth:
- system, verified via connector secret/signature

Behavior:
- update status, tracking, appointment, or fulfillment evidence

## 4. Admin supplier and marketplace ops APIs

Maintain current admin routes:

- `GET /api/admin/suppliers`
- `GET /api/admin/suppliers/pending`
- `GET /api/admin/suppliers/{id}`
- `POST /api/admin/suppliers/{id}/approve`
- `POST /api/admin/suppliers/{id}/reject`
- `POST /api/admin/suppliers/{id}/suspend`
- `POST /api/admin/suppliers/{id}/reactivate`
- `GET /api/admin/suppliers/analytics`
- `GET /api/admin/suppliers/insights`
- `GET /api/admin/suppliers/orders`

Add:

- `GET /api/admin/marketplace/settlements`
- `POST /api/admin/marketplace/settlements/run`
- `GET /api/admin/marketplace/connectors`
- `GET /api/admin/marketplace/reconciliation`
- `GET /api/admin/marketplace/reimbursement-exceptions`
- `POST /api/admin/marketplace/refunds/{refund_id}/approve`

## 5. External payer APIs

### `POST /api/payers/eligibility/check`

Auth:
- customer service flow, admin, or claims role

Request:
```json
{
  "customer_id": "CUST-001",
  "payer_id": "PAY-001",
  "items": [
    {
      "offer_id": "OFF-001",
      "service_date": "2026-03-25"
    }
  ]
}
```

Response:
```json
{
  "eligibility_check": {
    "id": "ELIG-001",
    "status": "eligible",
    "coverage_percent": 80.0,
    "covered_amount": 80.0,
    "deductible_amount": 10.0,
    "copay_amount": 5.0,
    "network_status": "in_network"
  }
}
```

### `POST /api/payers/preauth`

Auth:
- system, claims, admin

Purpose:
- submit pre-authorization before capture when required

### `POST /api/payers/claims`

Auth:
- claims, admin, or system

Purpose:
- create claim-as-a-service request from marketplace order

### `POST /api/payers/remittances/import`

Auth:
- admin or accountant

Purpose:
- import remittance payload, create remittance lines, apply receivable clearing

### `GET /api/payers/receivables`

Auth:
- admin, accountant, claims

Query:
- `payer_id`
- `status`
- `aging_bucket`

## 6. BI, AI, and integrity APIs

### `GET /api/integrity/marketplace`

Auth:
- admin, accountant, actuary

Response:
- wallet reconciliation status
- settlement reconciliation status
- payer reconciliation status
- unresolved findings summary

### `GET /api/bi/marketplace-executive`

Auth:
- admin

Metrics:
- GMV
- net revenue
- active suppliers
- payer recovery rate
- refund rate

### `GET /api/bi/marketplace-finance`

Auth:
- admin, accountant

Metrics:
- markup recognized
- deferred revenue
- supplier payable
- open payer receivables
- refund liability

### `GET /api/bi/marketplace-supplier`

Auth:
- admin and filtered supplier self-view

Metrics:
- fill rate
- order acceptance rate
- on-time fulfillment
- payout aging

### `GET /api/ai/marketplace-insights`

Auth:
- admin, actuary, risk

Metrics:
- abnormal margin alerts
- reimbursement leakage alerts
- supplier fraud risk alerts
- inventory and demand anomalies

## Dashboard-by-dashboard feature map

## 1. `web_portal/static/dashboard.html` - customer experience

Current anchors:
- health wallet section
- marketplace category shortcuts
- medical marketplace overlay
- activity log

Add and wire:

### Wallet panel

- available balance
- held balance
- pending reimbursements
- insurer-covered pending amount
- recent wallet ledger entries

API dependencies:
- `GET /api/wallets/health`
- `GET /api/marketplace/orders`

### Marketplace search and quote

- current categories stay: consultation, devices, supplies, pharmacy, home care
- add quote summary drawer:
  - supplier price
  - coverage amount
  - customer payable
  - markup visibility not shown to customer unless product policy requires fee
    explanation
  - reason codes if a cheaper offer is excluded

API dependencies:
- `GET /api/marketplace/search`
- `POST /api/marketplace/quotes`

### Checkout state

- order confirmation
- hold status
- supplier acceptance status
- delivery or appointment tracking

API dependencies:
- `POST /api/marketplace/orders`
- `GET /api/marketplace/orders/{id}`

### Reimbursement tracker

- claim submitted
- preauth decision
- remittance received
- refund credited to wallet/card

API dependencies:
- `GET /api/marketplace/orders/{id}`
- `GET /api/payers/receivables` filtered to customer-safe shape via dedicated
  customer endpoint if needed

## 2. `web_portal/static/supplier-portal.html` - supplier operations

Current anchors:
- own offers
- own orders
- supplier stats

Add and wire:

### Supplier profile and compliance

- KYB status
- connector status
- payout method
- settlement frequency
- reserve holdback rate

### Offer and catalog operations

- portal offers
- external catalog sync status
- inventory freshness timestamp
- last connector import errors

APIs:
- current offer endpoints
- `GET /api/supplier/connectors`
- `POST /api/supplier/connectors/catalog-sync`

### Order operations

- accept/reject order
- update status
- tracking upload
- appointment schedule confirmation
- proof of delivery / completion

APIs:
- existing supplier order endpoints
- `POST /api/supplier/connectors/order-callback`

### Settlement tab

- settlement run history
- pending payout
- holdbacks
- clawbacks
- remittance download

APIs:
- `GET /api/supplier/settlements`
- `GET /api/supplier/settlements/{id}`

## 3. `web_portal/static/admin-supplier-dashboard.html` - supplier governance

Current anchors:
- pending supplier queue
- approval actions
- supplier analytics

Add and wire:

### Approval and governance

- current approval workflow remains
- add connector health and payout-readiness indicators
- highlight suppliers with expired compliance docs or failed settlement

### Marketplace supply operations

- catalog freshness
- inventory anomalies
- failed order callbacks
- supplier dispute rate

### Settlement operations

- pending settlement runs
- payout exceptions
- holdback release queue

APIs:
- existing admin supplier endpoints
- `GET /api/admin/marketplace/settlements`
- `GET /api/admin/marketplace/connectors`
- `GET /api/admin/marketplace/reconciliation`

## 4. `web_portal/static/admin.html` - platform-wide marketplace control plane

Add sections:

### Executive marketplace KPIs

- GMV
- net marketplace revenue
- supplier payable
- payer receivable
- open refunds
- integrity score

### Exception queues

- failed captures
- orders with missing settlement
- remittance mismatches
- duplicate reimbursement alerts

### Connector and payer health

- external supplier connector uptime
- payer import failures
- webhook replay anomalies

APIs:
- `GET /api/bi/marketplace-executive`
- `GET /api/bi/marketplace-finance`
- `GET /api/integrity/marketplace`

## 5. `web_portal/static/accountant-dashboard.html` - finance operations

Expected additions:

- markup recognized by period
- deferred revenue
- supplier payable aging
- payer receivable aging
- refund liability
- reconciliation run results
- downloadable settlement and remittance detail

APIs:
- `GET /api/bi/marketplace-finance`
- `GET /api/admin/marketplace/settlements`
- `GET /api/payers/receivables`
- `GET /api/integrity/marketplace`

## 6. `web_portal/static/claims-adjuster-dashboard.html` - recovery and denial ops

Expected additions:

- marketplace-claim queue
- preauth exceptions
- denied reimbursement queue
- appeal workflow
- claim packet completeness

APIs:
- `POST /api/payers/claims`
- `GET /api/payers/receivables`
- claim detail endpoints extended with `order_id` linkage

## 7. `web_portal/static/actuary-dashboard.html` and `risk-dashboard.html`

Expected additions:

- reimbursement recovery rate by category
- coverage-aware ranking performance
- supplier quality score inputs
- margin leakage
- utilization and denial trend analysis

APIs:
- `GET /api/bi/marketplace-executive`
- `GET /api/ai/marketplace-insights`

## 8. `web_portal/static/underwriter-dashboard.html`

Expected additions:

- benefit rule and network design feedback loops
- category loss and recovery profile
- preauth rule tuning support

## Test and reconciliation strategy

## 1. Test strategy by layer

### Unit tests

Add focused tests for pure business rules:

- `tests/test_wallet_ledger_service.py`
- `tests/test_marketplace_checkout_service.py`
- `tests/test_marketplace_accounting_service.py`
- `tests/test_supplier_settlement_service.py`
- `tests/test_external_payer_service.py`
- `tests/test_reconciliation_service.py`

Required assertions:

- hold/capture/release transitions are valid
- markup computation is deterministic
- refunds create compensating entries
- settlement formula is reproducible
- payer receivable closes correctly on remittance

### Repository tests

Add:

- `tests/test_marketplace_repositories.py`

Required assertions:

- unique wallet per customer/wallet type
- immutable ledger append behavior
- settlement run item retrieval
- receivable aging filters
- idempotency key replay storage

### API integration tests

Add:

- `tests/test_marketplace_checkout_api.py`
- `tests/test_supplier_settlement_api.py`
- `tests/test_external_payer_api.py`

Required scenarios:

1. quote -> hold -> supplier accept -> capture -> settlement pending
2. customer cancel before capture -> hold release
3. supplier cancel after capture -> refund pending -> refunded
4. external insurer remittance -> receivable cleared -> customer reimbursement if
   applicable
5. duplicate callback with same idempotency key -> no duplicate order mutation

### End-to-end tests

Extend:
- `tests/test_supply_chain_marketplace_pipeline.py`

New E2E flows:

1. pharmacy order paid from health wallet
2. consultation order with preauth requirement
3. PHINS advance then insurer reimburse later
4. supplier settlement batch after fulfillment
5. refund after failed delivery

### UI/static integrity tests

Add lightweight presence and routing tests for new dashboard modules:

- `tests/test_customer_marketplace_dashboard_integrity.py`
- `tests/test_supplier_settlement_dashboard_integrity.py`
- `tests/test_admin_marketplace_ops_dashboard_integrity.py`

### Regression coverage to preserve

Existing suites that must remain green:

- `tests/test_balance_sheet_integrity.py`
- `tests/test_platform_integrity.py`
- `tests/test_supply_chain_marketplace_pipeline.py`
- `tests/test_bi_analytics.py`
- `tests/test_database.py`

## 2. Reconciliation strategy

Reconciliation is not a reporting afterthought. It is an explicit operating
control.

### Reconciliation types

#### A. Wallet reconciliation

Compare:
- derived wallet posted balance from `wallet_ledger_entries`
- cached `wallet_accounts.posted_balance`
- held amount from open `wallet_holds`

Frequency:
- on every capture/release in-process
- hourly background scan
- nightly full recompute

Failure conditions:
- negative available balance
- mismatched posted balance
- captured hold without matching ledger entry group

#### B. Order-to-payment reconciliation

Compare:
- order state
- payment intent state
- wallet hold state
- payment attempts

Frequency:
- on capture transition
- hourly retry and variance scan

Failure conditions:
- captured order with no successful payment intent
- released hold with order still paid
- payment intent completed but order still pending

#### C. Settlement reconciliation

Compare:
- fulfilled orders eligible for payout
- settlement items included
- journal supplier payable
- payout execution result

Frequency:
- before settlement run execution
- after payout import
- nightly aging scan

Failure conditions:
- fulfilled order absent from settlement after SLA window
- payout executed but payable still open
- holdback exceeds configured supplier threshold

#### D. Payer reconciliation

Compare:
- marketplace claims submitted
- remittance lines received
- payer receivable open amounts
- customer reimbursement/refund postings

Frequency:
- on remittance import
- nightly aging and denial scan

Failure conditions:
- remittance line with unknown claim
- closed receivable with no matching remittance
- reimbursed customer with no receivable reduction

#### E. Balance sheet reconciliation

Compare:
- journal summaries
- `PHINS_BALANCE_SHEET` rollups
- marketplace revenue / contra revenue / supplier payment totals

Frequency:
- nightly
- pre-close and month-end

Failure conditions:
- markup-recognized revenue not matching journal entries
- supplier payment expense mismatch
- refund liability negative or missing

## 3. Invariants to enforce

These invariants must be encoded in tests and reconciliation:

1. `wallet.available_balance + wallet.held_balance = wallet.posted_balance`
   for single-currency wallet accounts after normalization.
2. No order can move to captured without a successful payment intent and
   matching hold or external payment success.
3. Every captured order must produce:
   - wallet ledger entries or payment attempt result
   - journal entries
   - platform ledger event
4. Every fulfilled order eligible for payout must appear in settlement within
   the supplier settlement SLA.
5. Every payer remittance must reduce either:
   - payer receivable
   - customer reimbursement payable
   - both, depending on flow
6. Refunds must reverse revenue and payable impact through compensating entries.
7. No admin or service job may directly edit balance totals without ledger and
   journal support.

## 4. Test data and fixtures

Add deterministic fixtures for:

- customer with active health wallet
- supplier with approved pharmacy offer
- supplier with approved consultation offer
- external payer with 80 percent coverage
- order requiring preauth
- order with mixed tender wallet + card
- remittance import file with one paid and one denied line

## 5. Rollout safeguards

### Feature flags

Add environment or runtime flags for:

- `MARKETPLACE_DB_WALLET_ENABLED`
- `MARKETPLACE_SETTLEMENT_ENABLED`
- `MARKETPLACE_PAYER_RECOVERY_ENABLED`
- `MARKETPLACE_CONNECTORS_ENABLED`

### Shadow mode

Before switching off in-memory financial truth:

- write new wallet/journal records in parallel
- compare shadow balances
- alert on variance
- cut over only when variance remains zero across agreed test windows

### Operational dashboards required before cutover

- wallet reconciliation summary
- settlement exception queue
- payer receivable aging
- failed idempotency replay queue

## File-by-file implementation targets

### Data layer

- `database/models.py`
- `database/manager.py`
- `database/__init__.py`
- `database/migrate_data.py`
- `database/seeds.py`
- `database/repositories/*.py` for new marketplace repos

### Service layer

- new services listed above under `services/`
- update `services/platform_integrity_service.py`
- update `services/bi_analytics_service.py`
- update `services/payment_gateway_service.py`
- narrow `services/supplier_management_service.py`
- narrow `services/marketplace_service.py`

### HTTP layer

- `web_portal/server.py`
- `web_portal/api_extensions.py` if route extraction is needed

### UI layer

- `web_portal/static/dashboard.html`
- `web_portal/static/supplier-portal.html`
- `web_portal/static/admin-supplier-dashboard.html`
- `web_portal/static/admin.html`
- `web_portal/static/accountant-dashboard.html`
- `web_portal/static/claims-adjuster-dashboard.html`
- `web_portal/static/actuary-dashboard.html`
- `web_portal/static/risk-dashboard.html`
- `web_portal/static/underwriter-dashboard.html`

### Tests

- new tests listed above under `tests/`
- extend existing marketplace, integrity, and balance sheet suites

## Definition of done

The PHINS health marketplace implementation is ready for production-grade
rollout when all of the following are true:

1. customer marketplace orders no longer depend on in-memory wallet state as the
   system of record
2. supplier payouts are generated only from settlement runs backed by journal
   and ledger records
3. markup is visible in finance views and reconciles to journal postings
4. external insurer remittance can close payer receivables and reimburse the
   correct party
5. dashboard users can see their required operational state without privileged
   data leakage
6. nightly reconciliation completes with zero unresolved critical findings
7. E2E tests cover quote, checkout, fulfillment, settlement, remittance, and
   refund flows

This specification is the implementation companion to
`docs/health_marketplace_architecture.md`.
