---
artifact_contract: ce-unified-plan/v1
title: PHINS ERP/MGA Integrity 58 → 100
date: 2026-11-27
product_contract_source: ce-plan
execution: code
authority: AGENTS.md + docs/financial_books_unification.md + architecture-analyze Pass 1 (exec_8804bae8ade03d2ec6dfc3f4e165d29e)
baseline_score: 58
target_score: 100
integrity_north_star: fail-closed checksums; single pricing_kernel writer; single platform_ledger hash chain; never invent a second money store
---

# PHINS ERP/MGA Integrity 58 → 100

## Goal Capsule

**Objective.** Raise PHINS from integrity maturity **58 → 100** so it is an ERP-grade MGA system of record: every fiduciary dollar is durable, reconcilable, period-locked, remittable, and fail-closed — without breaking the existing kernel-pin / cash-identity / hash-ledger spine.

**Means.** Stay in the monorepo. Add first-class DB repositories and service packages for fiduciary money, GL/period close, trust, remittance, and clawbacks. Add integrity agents that *gate* money moves (never silently repair). Extract write paths out of `web_portal/server.py` behind explicit units of work. Optimize queues, snapshots, and CI so production dual-path is continuously proven.

**Authority hierarchy.**
1. Data integrity rules in `docs/financial_books_unification.md` and `AGENTS.md` §10 (fail-closed, no silent rewrite of billed premium / seed capital / broken checksums).
2. Single writers already declared (`pricing_kernel`, `customer_identity_service`, platform ledger).
3. This plan’s Implementation Units.
4. Convenience refactors.

**Stop conditions.**
- Do **not** create a second deployable money microservice or a second hash ledger.
- Do **not** invent a parallel pricing writer or rewrite historical `annual_premium` / `Bill.amount` / seed claims reserve.
- Do **not** auto-overwrite a checksum-mismatched snapshot, referral row, withdrawal seal, or kernel pin.
- Stop a phase if a named reconcile check that was green goes red without a forensic journal.

---

## Product Contract

### Actors
- MGA ops (admin, accountant, actuary)
- Carrier / reinsurer (bordereaux & remittance consumers)
- Agents / affiliates (commission + clawback)
- Customers (wallet, premium picture — read own cash only)
- Integrity agents (system actors that refuse unsafe money moves)

### Requirements

- R1. Production never soft-falls to empty in-memory books (`PHINS_REQUIRE_DATABASE` default on when `PHINS_ENVIRONMENT=production`).
- R2. Health wallets, withdrawals, NFT ledger, investment accounts, and balance-sheet counters are first-class DB tables with SHA seals; JSON file is cache only.
- R3. Every `AccountingEngine` post is durable in an accounting journal table before the in-memory book updates.
- R4. Money-moving POSTs (payout, commission settle, withdrawal release, remittance) refuse when critical reconcile / unified-statement checks are red.
- R5. Chart of accounts + fiscal period close (open → soft → hard); posts into a hard-closed period are refused.
- R6. Carrier remittance and premium/claims/commission bordereaux are generated from kernel pins + ledger cash (binder, period, currency).
- R7. Trust / fiduciary sub-ledger separates premium held for carrier vs company operating funds and ties to bank recon.
- R8. Reinsurance cession is a cash book (treaty → ceded premium/claims/commission), not analytical expense weights alone.
- R9. Agent commission clawbacks on lapse / unpaid premium are hash-chained reversals (parity with supplier `apply_clawback`).
- R10. Multi-entity / multi-binder tenancy keys policies, bills, remittances without forking the platform ledger chain.
- R11. Continuous `USE_DATABASE=true` financial CI proves the production path; in-memory remains demo/test-only.
- R12. New integrity agents are read-first / gate-first; they never silently invent cash or rewrite seals.

### Acceptance examples

- AE1. Kill Postgres at boot with `PHINS_ENVIRONMENT=production` → process exits non-zero; no HTTP serve on empty dicts.
- AE2. Redeploy without mounted volume but with intact DB fiduciary tables → wallets and BS counters restore; checksum intact.
- AE3. Force a red `claims_counted_once` → withdrawal release and commission settle return 409 with check name; no cash moves.
- AE4. Soft-close month M → hard-close → attempt premium post dated in M → refused; open M+1 succeeds.
- AE5. Bordereau for binder B / period M sums to ledger premium cash for B’s policies to the cent; seal matches.
- AE6. Lapse mid-term → agent clawback reversal row on commission ledger; integrity endpoint green.

### Out of scope (this plan)
- Rewriting the HTTP framework (Flask/FastAPI) as a prerequisite — strangler extraction of money handlers is enough for 100.
- Buying an external PAS (H3 “buy”) — optional later; this plan builds the modular Python core.
- Changing actuarial table science or Monte Carlo methodology except where labels/pins already gate integrity.

---

## Planning Contract

### Score model (how 58 becomes 100)

| Band | Points | What unlocks it | Cumulative |
|---|---|---|---|
| Baseline today | 58 | Kernel pins, reconcile surfaces, fail-closed seals, identity vault | 58 |
| P0 Durable foundation | +14 | Hard DB, fiduciary tables, volume fail-boot, DB financial CI | **72** |
| P1 Operational close of books | +10 | Money gates, durable GL journal, daily books-tied cert, agent clawbacks | **82** |
| P2 MGA ERP | +11 | CoA, period close, remittance, trust, RI cash, premium tax | **93** |
| P3 Architecture / scale | +7 | Extracted money UoW, multi-entity, incremental snapshots, prod queue SLOs | **100** |

A band only scores when its Verification Contract gates are green. Partial credit is not claimed.

### Current vs target (system picture)

**Today (58).**
```text
PortalHandler (server.py ~69.5k) owns HTTP + globals + many money posts
  POLICIES/CLAIMS/BILLING ── DatabaseDict (when DB up) or volatile dicts
  HEALTH_WALLETS / WITHDRAWALS / NFT / BS ── JSON file + agent_artifacts snapshot
  AccountingEngine ── 4 funds in process memory (boot hydrate)
  pricing_kernel ── sealed pins (strong)
  reconcile / unified-report ── read-only detectors (strong)
  Soft DB fallback ── split-brain risk
```

**After 100.**
```text
Thin PortalHandler / api_finance_* ── call services only
  FiduciaryStore (DB repos) ── wallets, withdrawals, NFT, investments, BS counters
  GlService + PeriodClose ── CoA accounts + durable journal + locked periods
  TrustLedger + RemittanceService + CessionLedger ── MGA cash to carrier/RI
  pricing_kernel + platform_ledger ── unchanged single writers / single chain
  IntegrityAgent swarm ── gate money; emit books-tied certificates; never silent repair
  PHINS_REQUIRE_DATABASE + volume fail-boot + USE_DATABASE=true CI ── always on in prod
```

### New repositories (database + package boundaries)

Interpret “new repositories” as **first-class persistence modules inside the monorepo**, not a second git money repo.

| New repository module | Table(s) | Owns | Replaces |
|---|---|---|---|
| `database/repositories/fiduciary_wallet_repository.py` | `health_wallets`, `wallet_transactions`, `wallet_withdrawals` | Balances, holds, withdrawal lifecycle | `HEALTH_WALLETS` / `WALLET_WITHDRAWALS` globals |
| `database/repositories/nft_ledger_repository.py` | `nft_ledger_entries` | Sealed NFT mint/transfer | in-snapshot `NFT_LEDGER` |
| `database/repositories/investment_account_repository.py` | `investment_accounts`, `investment_allocations` | Landed savings AUM | snapshot investments |
| `database/repositories/balance_sheet_repository.py` | `balance_sheet_counters` | Seed + derived counters (seed never rewritten by reconcile) | `PHINS_BALANCE_SHEET` file key |
| `database/repositories/accounting_journal_repository.py` | `accounting_journal_entries`, `fiscal_periods`, `coa_accounts` | Durable GL + periods | boot-only `AccountingEngine` memory |
| `database/repositories/trust_ledger_repository.py` | `trust_balances`, `trust_movements` | Fiduciary premium held | analytical `held_for_others` only |
| `database/repositories/remittance_repository.py` | `remittance_runs`, `bordereaux` | Carrier payables + sealed exports | none (new) |
| `database/repositories/cession_repository.py` | `treaties`, `cession_entries` | RI cash | `_EXPENSE_WEIGHTS` as sole truth |
| `database/repositories/period_close_repository.py` | `period_close_packs` | Soft/hard close certificates | none (new) |

`DatabaseManager` gains matching properties. JSON `phins_ledger_data.json` becomes a **read-through cache** of fiduciary tables (or is retired once migration seals).

**Package boundaries (new service packages, still one deployable):**
- `services/erp/` — CoA, journal, period close, books-tied certificate
- `services/mga/` — remittance, bordereaux, trust, cession, binder tenancy
- `services/fiduciary/` — wallet, withdrawal, NFT, investment durability
- Existing facades (`financial_unification_service`, `pricing_kernel`, `platform_event_ledger_service`) stay the spine; new packages call into them, never around them.

**Anti-pattern.** Do not open `phins-erp` / `phins-mga` as separate deployables with their own ledgers. One DB, one `platform_ledger_entries` chain, division/binder in payload (same rule as `docs/phins_ryders_general_insurance_architecture.md`).

### New / upgraded agents

| Agent | Role | Writes? | Integrity contract |
|---|---|---|---|
| **Books Integrity Agent** | Continuous reconcile + unified checks; publishes `books_tied` cert | Ledger certificate only | Red critical check → refuse money gate |
| **Money Gate Agent** | Middleware for payout / settle / release / remittance | No (blocks) | 409 `{error, failed_checks[]}` |
| **Period Close Agent** | Soft/hard close pack; seals checksum of TB + remittance digests | Period pack + ledger event | Hard close immutable |
| **Bordereaux Agent** | Builds premium/claims/commission bordereaux per binder/period | Sealed bordereau artifact | Must tie to ledger cash to the cent |
| **Trust Recon Agent** | Trust TB vs bank import; flags deficit | Findings only (fail-closed) | Never invents cash to balance |
| **Commission Clawback Agent** | On lapse / unpaid premium, proposes then posts hash-chained clawback | Commission reversal | Idempotent on `(policy, commission_id)` |
| **Durability Guard Agent** | Extends document durability probe to fiduciary tables + snapshot | Probe lane only | Fingerprint before/after; never rewrite customer money |
| Existing bots (UW/Claims/Assessment) | Unchanged decision rules | As today | Still never decide cash identity |

All new agents enqueue via `services/agent_job_queue.py` with handlers registered in `services/jobs/`; under `PHINS_AGENT_ASYNC` they answer 202 + poll. Golden sets under `tests/golden/<agent>/` freeze expected keys.

### Optimisations (integrity-preserving)

- O1. Incremental / sharded ledger snapshots (or drop file snapshot once fiduciary tables are authoritative) so `PHINS_LEDGER_SNAPSHOT_DB_MAX_BYTES` cannot freeze durability.
- O2. Extract money write routes from `server.py` into `web_portal/api_finance.py` / `api_fiduciary.py` / `api_mga.py` (thin handlers).
- O3. Explicit `session_scope()` UoW around (ledger cash + accounting journal + fiduciary table) so partial posts cannot land.
- O4. Prod-only: DB job queue required; alert on pending age / DLQ depth via `/api/health` + Books Integrity Agent.
- O5. CI matrix: `USE_DATABASE=true` financial suite + existing in-memory suite; forbid claiming green without both.
- O6. Read-path caching for reconcile reports with content-version invalidation (`DatabaseDict.content_version`) — cache never authorises a money move without a fresh critical-check digest.

### Key technical decisions (KTDs)

- KTD1. Monorepo + single ledger chain (not multi-repo money split).
- KTD2. Fiduciary tables are authoritative; file snapshot is cache or retired.
- KTD3. Money Gate Agent is fail-closed; operator override requires admin + audited break-glass with forensic journal first.
- KTD4. CoA maps onto existing four-fund semantics as rollups first (Risk / Savings / Reinsurance / Operating) so historical cash still ties; natural accounts added underneath.
- KTD5. Analytical `_EXPENSE_WEIGHTS` remain for planning/pitch until cession cash book is live; live remittance never reads them as cash truth.
- KTD6. Strangler extraction of handlers; no big-bang rewrite of PortalHandler.

### Assumptions
- A1. Postgres is available in production (Railway/Render).
- A2. One primary web process or sticky DB-backed state is acceptable until multi-entity phase; multi-instance safety comes from DB authority.
- A3. Carrier/binder identifiers can be introduced as optional columns defaulting to `PHINS-DEFAULT` without rewriting historical pins.

### Sequencing
P0 → P1 → P2 → P3. Do not start CoA/bordereaux before fiduciary durability and money gates, or the ERP layer will reconcile against volatile books.

---

## Implementation Units

### U1. Hard database + boot fail-closed (→ toward 72)
- Files: `web_portal/server.py`, `scripts/entrypoint.sh`, `render.yaml`, `railway.json` / Railway env docs, `tests/test_security_hardening.py`, `tests/test_post_deploy_integrity.py`
- Work: default `PHINS_REQUIRE_DATABASE=true` when `PHINS_ENVIRONMENT=production`; fatal exit if DB unavailable or ledger path is tempdir in production; keep soft fallback for `PHINS_TEST_MODE` / explicit demo.
- Integrity: no empty-book serve in prod.
- Verify: AE1; boot tests for require-DB.

### U2. Fiduciary DB repositories + migration (→ 72)
- Files: new repos listed above; `database/models.py`; `database/manager.py`; `database/migrate_data.py`; `services/fiduciary/`; `services/wallet_withdrawal_service.py`; `services/ledger_snapshot_store.py`; `web_portal/server.py` (remove “always in-memory” path)
- Work: schema + repository CRUD with SHA seals; one-shot migrate from snapshot → tables (journal-first); dual-read then dual-write then DB-authoritative; snapshot omits migrated keys or becomes pure cache.
- Integrity: checksum mismatch withholds row (never overwrite); migration writes before/after journal on platform ledger.
- Verify: AE2; `tests/test_wallet_withdrawal.py`, new `tests/test_fiduciary_store.py`, redeploy simulation.

### U3. USE_DATABASE=true financial CI (→ 72)
- Files: `.github/workflows/*`, new job or matrix in existing CI; targeted suites `tests/test_financial_unification.py`, `tests/test_cashflow_unified_report.py`, `tests/test_balance_sheet_integrity.py`, `tests/test_money_flow_integrity.py`, `tests/test_wallet_withdrawal.py`
- Work: CI job with Postgres service + `USE_DATABASE=true`; block merge if red.
- Integrity: production path continuously proven.
- Verify: job green on main; document in `AGENTS.md` testing playbook.

### U4. Money Gate Agent + reconcile gate (→ 82)
- Files: `services/jobs/books_integrity_job.py`; `services/erp/money_gate.py`; wire in withdrawal release, commission settle, claim payout, remittance APIs; `web_portal/api_wallet_withdrawal.py`; `web_portal/api_agent_ecosystem.py`
- Work: compute critical-check digest from `reconcile_financial_books` + unified report; refuse with 409 listing failed checks; optional break-glass audited path.
- Integrity: AE3; gate never mutates books.
- Verify: new golden + API tests for 409 on forced red; green path unchanged.

### U5. Durable accounting journal (→ 82)
- Files: `accounting_journal_repository.py`; refactor `accounting_engine.py` to post through journal; boot hydrate from journal not only ledger cash; `hydrate_accounting_book_from_ledger` remains reconciler
- Work: every post = insert journal row (idempotent key) inside `session_scope` with ledger cash when applicable.
- Integrity: peer instances share journal; no memory-only money.
- Verify: multi-process smoke; repair still idempotent.

### U6. Books-tied daily certificate (→ 82)
- Files: Books Integrity Agent; `platform_event_ledger_service.py` event type `finance.books_tied`; accountant UI badge on `/cashflow-integrity.html`
- Work: once per UTC day after green critical checks, append sealed certificate; Money Gate may require today’s cert age < N hours for high-value moves.
- Integrity: certificate is evidence, not a rewrite.
- Verify: ledger event present; tamper fails verify.

### U7. Agent commission clawback (→ 82)
- Files: `services/agent_ecosystem_service.py`; Commission Clawback Agent; mirror patterns from `supplier_settlement_service.apply_clawback`
- Work: on lapse / unpaid premium, post hash-chained reversal; integrity endpoint includes clawback coverage.
- Integrity: AE6; never double-clawback.
- Verify: `tests/test_agent_ecosystem.py` extensions.

### U8. CoA + period close (→ 93)
- Files: `services/erp/coa.py`, `services/erp/period_close.py`; Period Close Agent; accountant UI
- Work: natural accounts rolled under four funds; open/soft/hard close; refuse posts into hard-closed period.
- Integrity: AE4; close pack seals TB + check digests.
- Verify: period close tests; attempt post after hard close → 409.

### U9. Remittance + bordereaux (→ 93)
- Files: `services/mga/remittance.py`, `services/mga/bordereaux.py`; Bordereaux Agent; remittance repository
- Work: generate sealed bordereaux from kernel pins + ledger cash + claims paid; remittance run creates payable; settle posts cash and marks run.
- Integrity: AE5; bordereau seal; remittance refuses if books red (U4).
- Verify: cent-tie tests per binder fixture.

### U10. Trust ledger + RI cession cash (→ 93)
- Files: `services/mga/trust.py`, `services/mga/cession.py`; Trust Recon Agent; cession repository
- Work: trust movements on premium collect / remittance; treaty-driven cession entries; planning weights remain labelled non-cash.
- Integrity: trust deficit flagged, never auto-filled; cession cash ≠ `_EXPENSE_WEIGHTS`.
- Verify: trust TB tests; cession vs analytical divergence report.

### U11. Premium tax engine (→ 93)
- Files: `services/mga/premium_tax.py`; jurisdiction rules table; accrual posts to GL
- Work: accrue on collect; remittance schedule; no rewrite of billed premium.
- Integrity: tax is additive GL, not a silent premium change.
- Verify: jurisdiction fixture tests.

### U12. Extract money APIs + UoW (→ 100)
- Files: new `web_portal/api_finance.py`, `api_fiduciary.py`, `api_mga.py`; thin dispatch from `server.py`; shared `services/erp/unit_of_work.py`
- Work: strangler-move finance/fiduciary/mga routes; every money write goes through UoW.
- Integrity: behaviour parity tests before/after move; no second writer.
- Verify: route parity suite; LOC in `server.py` money sections drops.

### U13. Multi-entity / binder tenancy (→ 100)
- Files: models columns `binder_id` / `entity_id`; remittance/bordereaux filters; access hierarchy
- Work: default historical rows to platform entity; new binders scoped; still one ledger chain with binder in payload.
- Integrity: cross-binder leakage tests; single chain invariant.
- Verify: `tests/test_tenant_isolation.py` extensions.

### U14. Snapshot strategy + queue SLOs (→ 100)
- Files: `ledger_snapshot_store.py`; job queue health; Durability Guard Agent; alerts
- Work: incremental snapshots or retire file snapshot; require DB queue in prod; pending-age / DLQ alerts.
- Integrity: no silent durability freeze; AE2 still holds.
- Verify: over-cap behaviour tests; queue SLO tests.

---

## Verification Contract

### Commands (repo-relative)
```bash
# P0/P1 financial integrity (extend with USE_DATABASE=true job in CI)
pytest tests/test_financial_unification.py tests/test_cashflow_unified_report.py \
  tests/test_balance_sheet_integrity.py tests/test_money_flow_integrity.py \
  tests/test_wallet_withdrawal.py tests/test_accounting_engine.py \
  tests/test_premium_flow_reconciliation.py -q

# Agent goldens after new agents land
python3 scripts/run_agent_eval.py golden

# System validation
python3 validate_system.py
bash quick_smoke_test.sh
```

### Quality gates per band
- 72: AE1, AE2, DB financial CI green, no “always in-memory” wallet path in prod code.
- 82: AE3, AE6, journal durable, daily `finance.books_tied` event under green books.
- 93: AE4, AE5, trust deficit fail-closed, cession cash book live, tax additive only.
- 100: Money routes extracted, multi-entity leakage tests green, snapshot/queue SLOs green, scorecard checklist all checked.

### Integrity invariants (every PR)
- No second `price_policy` writer.
- No rewrite of billed premium / seed claims reserve / broken checksum rows.
- Platform ledger repair remains journal-first.
- New tables expose checksum + withhold-on-mismatch.
- Money Gate cannot be bypassed except audited break-glass.

---

## Definition of Done

**Global.** Scorecard reaches 100 only when P0–P3 Verification gates pass, `AGENTS.md` Preferred file-by-task table lists the new packages/repos, and `/cashflow-integrity.html` shows books-tied certificate + period status.

**Per unit.** Each U1–U14 has: migration or code landed, tests green (including `USE_DATABASE=true` where money is touched), no integrity invariant broken, and a short note in the PR that names which score band points are claimed.

**Rollback.** Every fiduciary migration is journal-first and reversible by restoring from forensic journal + previous sealed snapshot/DB backup; hard-closed periods are never “reopened” by delete — only compensating entries in an open period.

---

## Appendix

### Research breadcrumbs
- Architecture Pass 1 + ERP/MGA deep dive: `/opt/cursor/artifacts/phins-erp-mga-integrity-report.md` (agent artifact); Opsera `exec_8804bae8ade03d2ec6dfc3f4e165d29e` (score 58).
- `docs/financial_books_unification.md` — cash identity rules.
- `docs/phins_ryders_general_insurance_architecture.md` — one ledger, division in payload.
- `docs/insurtech_landscape_and_techno_plan_2026.md` — H0 harden → H3 CoA/period close.
- `docs/platform_data_architecture.md` — hash-chained spine.
- Hotspot: `web_portal/server.py` (401 edits / 6 months).

### Scorecard checklist (claim 100 only when all true)
- [x] Prod require-DB + volume fail-boot
- [x] Fiduciary tables authoritative
- [x] DB financial CI
- [x] Money Gate on all payout paths
- [x] Durable accounting journal
- [x] Daily books-tied certificate
- [x] Agent clawbacks
- [x] CoA + hard period close
- [x] Bordereaux + remittance sealed & tied
- [x] Trust TB + RI cession cash
- [x] Premium tax additive
- [x] Money APIs extracted + UoW
- [x] Multi-entity leakage-proof
- [x] Snapshot/queue cannot freeze durability
