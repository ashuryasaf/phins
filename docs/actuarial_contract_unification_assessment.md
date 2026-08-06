# Actuarial Contract Unification Assessment

**Status:** Analysis only — no code changes  
**Date:** 2026-08-06  
**Scope:** Actuarial dashboard as central pricing model; connectivity to product stable versions, billing, risk assessments, new policy application, risk valuations, and pipelines  
**Integrity constraint:** Preserve existing issued premiums, bills, and ledger history; any future cutover must pin versions before reprice

---

## 1. Verdict

PHINS already has a **declared** central pricing contract — `services/pricing_kernel.py` (`price_policy` → `PremiumComponents`) plus the actuary dashboard’s `CONTRACT_SPECIFICATION` (`phins_pure_risk_adjustable` v1.0) and versioned `ActuarialTablesStore`. That stack is **not** the operational path for new policy applications or billing.

Operational issuance still uses the flat-rate formula documented in `ACTUARIAL_PRICING_MODEL.md` (`calculate_premium` / `apply.js`). Billing and `billing_engine` consume **stored amounts**, not actuarial recomputation. Risk assessments / Assessment Center produce loadings and scores that are **not pinned** into the kernel at issue time.

**Net:** two pricing worlds, three table sources, and no durable product→tables→premium pin on issued policies. Unification is primarily a **contract and lineage** problem inside the existing Python platform; Durable Objects are optional later for edge coordination, not the first integrity fix.

---

## 2. Current architecture (as implemented)

```text
┌─────────────────────────────────────────────────────────────────┐
│ ACTUARY WORLD (governance / sandbox)                            │
│  actuary-dashboard.html                                         │
│    → ActuarialTablesStore (in-process V2.x)                     │
│    → PRODUCT_REGISTRY + CONTRACT_SPECIFICATION                  │
│    → pricing_kernel.price_policy → PremiumComponents + hash     │
│    → ACTUARIAL_SIMULATIONS → valuation / reserves / reconcile   │
│    → optional Push-to-Pipeline → CUST-TESTSIM-* (demo only)     │
└─────────────────────────────────────────────────────────────────┘
                              ✗ not wired to live issue

┌─────────────────────────────────────────────────────────────────┐
│ OPERATIONAL WORLD (application → UW → bill → pay)               │
│  apply.js calculateBasePremium                                  │
│    → POST /api/policies/create → calculate_premium ($0.25/1000) │
│    → Policy.annual/monthly_premium (scalars only)               │
│    → PipelineService (+ optional premium_adjustment_pct)        │
│    → BILLING amount → billing_engine.process_payment(amount)    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ RISK / ASSESSMENT WORLD (parallel)                              │
│  underwriting_risk_scoring → premium_adjustment recommendation  │
│  Assessment Center → scores / facts (engine_version)            │
│  actuarial_valuation → EV on simulation books (not applicants)  │
└─────────────────────────────────────────────────────────────────┘
```

### Key surfaces

| Layer | Location | Role today |
|---|---|---|
| Dashboard | `web_portal/static/actuary-dashboard.html` | Admin/actuary sandbox; tables, sim, valuation, contract-spec, push-to-pipeline |
| Kernel | `services/pricing_kernel.py` | Declared SSOT for premium decomposition |
| Tables store | `services/actuarial_service.py` (`ActuarialTablesStore`) | In-memory versioned rates (`current_version` e.g. `V2.0`) |
| Contract draft | `CONTRACT_SPECIFICATION` / `GET /api/actuarial/contract-spec` | Product `phins_pure_risk_adjustable` `v1.0` |
| Upload catalog | `database.models.ActuarialTable` + `ActuarialRepository` | Encrypted uploaded blobs; not auto-active for every pricer |
| Flat-rate doc | `ACTUARIAL_PRICING_MODEL.md` | “Unified” app↔billing formula (different system from kernel) |
| Issuance | `server.py` `calculate_premium`, `/api/policies/create` | Live premium truth for customers |
| Billing | `billing_engine.py`, portal bill generation | Payment plumbing; amount is an input |
| Pipeline | `PipelineService`, `PipelineIntegrityService` | Lifecycle + arithmetic checks; no kernel hash |
| Ledger | `PlatformEventLedgerService` | Tamper-evident events; no `premium.priced` snapshot yet |
| Spec gap | `docs/health_marketplace_implementation_spec.md` `pricing_explanations` | Designed `actuarial_version` pin; not implemented for insurance |

---

## 3. Where the contract is not unified

### 3.1 Dual “single source of truth”

| Claim | Source | Reality |
|---|---|---|
| Kernel is the only place premiums are decomposed | `pricing_kernel.py` docstring | True for actuary/sim/FRS callers |
| App↔billing unified on `$0.25/1000` | `ACTUARIAL_PRICING_MODEL.md` | True for `/api/policies/create` and bills |
| Adjustable Risk is the published contract | `CONTRACT_SPECIFICATION` | Not what issuance stores or prices |

Historical “3.3× mismatch” was fixed by aligning frontend and backend to the **flat-rate** path — leaving the actuarial kernel as a parallel governance system.

### 3.2 Product identity drift

| Surface | Product / type identity |
|---|---|
| Contract + actuary simulate (default) | `phins_pure_risk_adjustable` |
| `calculate_age_adjusted_premium` / FRS quote | Often `phins_hybrid_savings` (with savings overrides / private tables) |
| Issued `Policy.type` | `life` / `health` / `phins_unified` / `auto` / … |
| Marketplace catalog | `PROS-001`, `MED-001`, … (different namespace) |

There is **no** durable product catalog row, **no** `stable_version` on policies, and **no** FK from policy → kernel product → tables version.

### 3.3 Three rate-table sources

1. `ActuarialTablesStore` singleton (dashboard edits, simulator, age-adjusted wrapper)  
2. `FinancialReportingService` module constants → `TableSet(version='financial_reporting_v2')`  
3. DB `actuarial_tables` uploads + in-memory `ACTUARIAL_TABLES` (activation via separate “use” API)

Dashboard edits do not reliably affect every pricing call site.

### 3.4 Risk loadings not one contract

| System | Risk signal | Effect on premium |
|---|---|---|
| Flat-rate `calculate_premium` | String band → `risk_factor` | Multiplies base rate at create |
| Kernel | ADL + `underwriting_loading` | PV / loading inside `price_policy` |
| `underwriting_risk_scoring` | `premium_adjustment` % | Recommendation; not kernel input at create |
| Assessment Center / records | Float score + `engine_version` | Decision lineage; not priced snapshot |
| Actuarial valuation | Portfolio EV from simulation | Not applicant UW |

Same words (“risk score”, “premium adjustment”) mean different units and paths.

### 3.5 Missing pins on issued artifacts

`Policy` stores coverage + premium scalars + string `risk_score`. It does **not** store:

- `product_id` / `contract_version` / `stable_version`
- `tables_version` / `config_version`
- `integrity_hash` / full `PremiumComponents`
- UW loading provenance

`Bill.amount` is opaque relative to the pricing model. Simulations note that DB schema for sim snapshots / fee schedules is “not yet extended.”

### 3.6 Pipeline bridges that are demo-only or incomplete

| Bridge | Production readiness |
|---|---|
| Sandbox push-to-pipeline | Explicitly TESTSIM / suspended / Clean Demo Data |
| Process / savings pipelines | Consume stored amounts |
| Platform ledger / marketplace outbox | Strong integrity patterns; not insurance pricing vocabulary |
| Simulation reconcile | Kernel ↔ sim agreement **inside** actuarial domain only |
| No event | “tables V2.1 activated → reprice in-force book” |

---

## 4. Data-integrity risks if left disconnected

1. **Quote ≠ application ≠ actuary dashboard ≠ bill identity** — amounts may match by luck on flat-rate, but cannot prove Adjustable Risk contract math.  
2. **Silent reprice drift** — table upload / store bump changes new kernel quotes; in-force policies have no pin; admin recalculate can rewrite using flat-rate, not kernel.  
3. **Product semantics wrong** — pure-risk vs hybrid-savings vs `phins_unified` type changes disability share / savings rights vs `CONTRACT_SPECIFICATION`.  
4. **UW loading double-count or miss** — string risk_factor at create vs post-hoc `%` in pipeline vs kernel ADL loadings.  
5. **Quarterly inconsistency** — discounted quarterly in `calculate_premium` vs `annual/4` expectations in pipeline integrity.  
6. **Ledger blind spot** — financial lineage without a hashed `premium.priced` event cannot support regulatory “right to audit trail” from the contract draft.  
7. **Cutover hazard** — naive switch of `/api/policies/create` to kernel without version pins and dual-run comparison would rewrite economics and confuse existing bills.

**Integrity rule for any future work:** never mutate historical premium identity without a forensic before/after journal (same spirit as ledger chain repair). Prefer **pin + dual-run + selective cutover**.

---

## 5. What to reuse (built system first)

These already exist and should form the unification spine **before** introducing new infrastructure:

| Pattern | Location | Use for pricing unification |
|---|---|---|
| Pricing kernel + `integrity_hash` | `services/pricing_kernel.py` | Sole premium calculator at quote/issue/anniversary |
| `PremiumComponents` version fields | `product_id`, `tables_version`, `config_version` | Persist snapshot on quote/policy/bill |
| `CONTRACT_SPECIFICATION` | `actuarial_service.py` | Canonical product rights/semantics; promote to versioned catalog |
| Rate tables registry | `build_rate_tables_registry`, upload/use APIs | Governance of what a stable product version pins |
| Platform event ledger | `PlatformEventLedgerService` | Append `premium.priced` / `policy.issued` with full snapshot |
| Outbox + idempotency | marketplace repos | Async BI/actuarial consumers; safe retries |
| Assessment records | `AssessmentRecord` + `payload_sha256` / `engine_version` | Template for “priced quote records” |
| AI model registry / decision log | `ai_model_registry`, `ai_decision_log` | Parallel versioning for risk engines feeding loadings |
| Pipeline integrity | `PipelineIntegrityService` | Extend checks: bill ↔ pinned hash, not only monthly×12 |
| Spec’d `pricing_explanations` | marketplace implementation spec | Implement for **insurance** quotes (not only health SKUs) |
| `phins_system.PricingModel` + `pricing_model_id` | legacy prototype | Conceptual pin model; do not revive in parallel — migrate ideas into kernel catalog |

---

## 6. Target unified contract (long-term)

### 6.1 One pricing atom

Define a durable **Stable Product Version** (SPV):

```text
SPV = {
  product_id,                 # e.g. phins_pure_risk_adjustable
  contract_version,           # e.g. v1.0  (CONTRACT_SPECIFICATION)
  tables_version,             # e.g. V2.1  (ActuarialTablesStore / frozen snapshot)
  config_version,             # e.g. kernel_v1 + UW config hash
  claim_model, savings_formula,
  effective_from / effective_to,
  status: draft | approved | stable | retired
}
```

**Rule:** Quote, issue, anniversary reprice, and actuary “publish” all resolve the same SPV. Policies store the SPV id (or the four version fields + `integrity_hash`). Bills reference the priced snapshot id, not a free-floating amount.

### 6.2 Canonical pipeline (target)

```text
Actuary publishes SPV (tables + contract + kernel config)
        ↓
Quote / Application → price_policy(SPV) → PremiumSnapshot (hash)
        ↓
Risk / Assessment → loading recommendation → applied inside kernel inputs (ADL / UW loading)
        ↓
Underwriting decision → optional loading change → re-price with same SPV → new snapshot
        ↓
Policy issued with SPV + snapshot hash pinned
        ↓
Billing schedule generated from snapshot amounts (engine still pays; does not invent premium)
        ↓
platform_ledger: premium.priced → policy.issued → bill.generated (hash-chained)
        ↓
Anniversary / published curve change → new SPV or same SPV + age step → re-price → ledger
```

### 6.3 Mapping operational types → products

Introduce an explicit map (config or table), e.g. `phins_unified` / `life` / `health` → `phins_pure_risk_adjustable` (+ optional savings add-on), so dashboard contract language and issued policies share one product id. Auto/property/business remain out-of-scope or get their own SPVs later — do not silently force life kernel math onto them.

### 6.4 Dual-run cutover (integrity-preserving)

1. Persist SPV + `PremiumSnapshot` beside existing flat-rate fields (additive columns / side table).  
2. Run kernel on every create; store both results; do **not** change billed amount until parity gates pass.  
3. Extend `PipelineIntegrityService` and tests (`test_pricing_kernel`, e2e pipeline) for snapshot equality / tolerances.  
4. Cut over issuance to kernel for product lines that pass; keep flat-rate only as legacy reader for historical rows.  
5. Never bulk-recalculate in-force without an explicit, journaled migration job.

---

## 7. Durable Objects — when (and when not)

Per Cloudflare Durable Objects guidance: use DOs for **coordination atoms**, strong consistency, per-entity storage, WebSockets, and per-entity alarms — not for stateless API fan-out, and never as one global bottleneck DO.

### Fit for PHINS pricing

| Need | Prefer built system | Consider DO later |
|---|---|---|
| Single premium formula | `pricing_kernel` in Python | — |
| Persist SPV + snapshots | Postgres/SQLite models + repositories | — |
| Hash-chained audit | `PlatformEventLedgerService` | — |
| Actuary collaborative editing of draft tables | Optional | DO per `draft-session` or per `product_id` for realtime collab |
| Serialized “publish SPV” / activate tables | DB transaction + outbox | DO per `product_id` if multi-writer race at edge |
| Anniversary reprice schedule per policy | Scheduler / alarms in existing `scheduler/` | DO per policy (or shard) with `setAlarm` if edge-native renewals |
| Live actuary dashboard multiplayer | Polling today | Hibernatable WebSockets DO per room |

### Recommendation

**Do not introduce Durable Objects as the first unification step.** PHINS is a Python `BaseHTTPRequestHandler` monolith with Postgres/SQLite; the integrity gap is missing pins and dual calculators, not missing edge coordination.

**Phase DO in only after** SPV + snapshot + ledger events exist in the core DB, and only for atoms that need single-threaded coordination:

- `ProductVersionCoordinator` DO named `product:{product_id}` — serialize publish/retire of SPVs; SQLite holds approved version pointers.  
- Optional `PolicyPricingAtom` DO named `policy:{policy_id}` — anniversary alarms and reprice coordination for edge deployments.  
- Workers remain thin routers; **source of economic truth stays the hashed snapshot in the platform ledger / DB**, with DO state as a coordination cache that is rebuilt from ledger if needed.

Anti-patterns to avoid: one global “PricingDO”; holding `blockConcurrencyWhile` across external billing I/O; storing premiums only in DO memory without DB/ledger persistence.

---

## 8. Recommended sequencing (no code in this assessment)

### Phase A — Contract freeze (read-only / additive)

- Inventory all `price_policy` / `calculate_premium` / `calculate_age_adjusted_premium` call sites (tests already cover kernel heavily).  
- Document SPV field set and product-type map.  
- Treat `CONTRACT_SPECIFICATION` + kernel product registry as normative for life/health Adjustable Risk.

### Phase B — Persist without behavior change

- Add `PremiumSnapshot` (or insurance `pricing_explanations`) + policy pin columns.  
- On create: compute kernel snapshot in shadow mode; keep flat-rate billed amount.  
- Emit ledger `premium.priced` (shadow) with hash.

### Phase C — Connect risk → kernel inputs

- Map Assessment / UW `premium_adjustment` and ADL into kernel `underwriting_loading` / customer fields.  
- Stop applying opaque post-hoc % after issue without re-hash.

### Phase D — Cutover issuance + billing consumers

- Switch create path to kernel for mapped products.  
- Bills continue to read pinned snapshot amounts.  
- Extend pipeline integrity to verify hash + versions.  
- Retire or clearly mark `ACTUARIAL_PRICING_MODEL.md` flat-rate as legacy.

### Phase E — Optional edge coordination (DO)

- Only if multi-region actuary publish races or per-policy edge renewals require it.  
- Bind DO version pointers to the same SPV ids already in Postgres.

---

## 9. Explicit non-goals (for integrity)

- No silent rewrite of historical `Policy` / `Bill` premiums.  
- No deleting sandbox / demo paths until production pin path exists.  
- No forcing marketplace health SKUs into life kernel IDs.  
- No replacing `billing_engine` payment responsibilities with actuarial math.  
- No single global Durable Object for all pricing traffic.

---

## 10. Confidence and coverage notes

Findings were corroborated by parallel codebase exploration of actuarial services, policy models, billing, assessment APIs, and docs (`ACTUARIAL_PRICING_MODEL.md`, marketplace pricing_explanations spec, platform ledger architecture). Granola meeting context was unavailable (auth required); this assessment is code/doc grounded only.

**Highest-confidence gaps:** dual calculator; missing policy pins; billing amount-as-input; sandbox-only actuary→billing bridge.  
**Execution-time unknowns (defer):** exact dual-run tolerance bands, regulatory filing constraints on reprice language, whether auto/property lines need separate kernels.

---

## 11. Suggested next decision

Choose one of:

1. **Deepen into an implementation-ready plan** for Phase A–B only (shadow snapshots, zero bill impact).  
2. **Prototype SPV schema + shadow pricing tests** behind a feature flag (still no customer-facing amount change).  
3. **Hold** — keep this assessment as the architectural baseline until product/actuary sign-off on Adjustable Risk as the sole life/health issue contract.
