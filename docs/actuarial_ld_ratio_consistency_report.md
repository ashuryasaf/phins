# Risk Product L:D Consistency Report

**Status:** Target rule settled; **implementation landed** for age-banded kernel + durable dashboard config + shadow dual-run (issuance billed amounts still flat until cutover)  
**Date:** 2026-08-07 (updated with settled product decision + implementation note)  
**Scope:** Confirm risk product L:D bands, no health mechanism, table/version adjustability, and **persistence of dashboard actuarial adjustments**; compare kernel vs issuance.

---

## 0. Settled product decision (2026-08-07)

Session-settled by product owner:

| Band | Disability : Life | Meaning |
|---|---|---|
| Until age 65 | **1 : 4** | \(D = L/4\) |
| After age 65 | **1 : 1** | \(D = L\) (disability equals life) |
| Pricing source | **Table / actuary-config pricing** | Kernel + versioned tables/config — not flat `$0.25/$1000` |
| Dashboard edits | **Must persist** | Actuarial adjustments from the dashboard survive restart and remain the active pricing source |
| Health | **No health mechanism** on the base risk product | |

This **supersedes** the earlier provisional reading that “1:1 after 65” meant life-only / disability off. Current `CONTRACT_SPECIFICATION` and kernel cutoff behavior still encode the *old* “disability ceases at 65” rule — that is now a **documented mismatch**, not the target.

---

## 1. Target rule (authoritative)

| Band | Disability : Life | Meaning |
|---|---|---|
| Ages &lt; 65 | **1 : 4** | Disability sum \(D = L/4\) |
| Ages ≥ 65 | **1 : 1** | Disability sum \(D = L\) |

**No health mechanism** means the base risk contract must not be a medical/health insurance product and must not require health-wallet / medical-expense machinery for pricing or benefits.

---

## 2. Kernel / contract — **FAIL** vs settled 1:1-after-65 rule

### 2.1 Contract draft (`CONTRACT_SPECIFICATION` v1.0) — stale vs decision

Source: `services/actuarial_service.py`

- Disability benefit: \(L \div 4\), trigger ages **3–65** only
- Age 65+: “Disability cover ceases automatically” ← **conflicts with settled \(D=L\) after 65**
- Life-only mode 65–∞: age-adjusted death benefit, disability off
- Disclaimer: base product = adjustable risk only — **no wallet, no savings, no investment** (aligned with “no health mechanism”)

Live API enrichment still exposes a **single** global ratio:

```text
contract_ratios = {
  disability_share_of_life: 0.25,
  disability_to_life_ratio_display: "1:4",
  source: UnderwritingConfig.disability_share_of_life,
  adjustable_from_dashboard: True
}
```

There is **no** age-banded `disability_share_of_life_pre65` / `post65` in config today.

### 2.2 Product registry (`pricing_kernel.PRODUCT_REGISTRY`)

| Product id | `disability_share` | `disability_cutoff_age` | vs settled rule |
|---|---|---|---|
| `phins_pure_risk_adjustable` | 0.25 | **65 (zeros disability ≥65)** | Pre-65 OK; **post-65 wrong** (should be 1.0, not cut off) |
| `phins_pure_risk` | 0.25 | 65 | Same |
| `phins_life_only_post65` | 0.0 | 65 | Explicit life-only — **wrong** for settled rule |
| `phins_hybrid_savings` | 0.25 | 65 | Same cutoff issue + savings add-on |

Caveat: product `line` is still labeled `life_health` — blurs “no health mechanism.”

### 2.3 Live kernel probe (L = $500,000, term 20, ADL 5, tables V2.0)

| Issue age | Target D:L | Actual share / D sum | Disability premium | Verdict |
|---|---|---|---|---|
| 35 | 1:4 → D=$125k | 0.25 / $125,000 | $649.36 | PASS |
| 64 | 1:4 → D=$125k | 0.25 / $125,000 | $178.99 | PASS |
| **65** | **1:1 → D=$500k** | stamped 0.25 / $125k; **prem $0** | **$0.00** | **FAIL** (should price disability at \(D=L\)) |
| 66 | 1:1 → D=$500k | same zero-disability path | **$0.00** | **FAIL** |
| 80 | 1:1 → D=$500k | same | **$0.00** | **FAIL** |

Root cause: PV loops skip disability when `current_age >= disability_cutoff_age` (65). That implements “disability ceases,” not “disability steps up to 1:1.”

Dashboard UI binds a **single** slider to `disability_share_of_life` (`Disability ÷ Life = 1 : 4`) — cannot express a post-65 1:1 band without a schema change.

**Kernel verdict vs settled rule:** **FAIL** after 65. Pre-65 1:4 matches.

---

## 3. Issuance / apply / billing — not consistent

### 3.1 No L:D concept at all

| Surface | Behavior |
|---|---|
| `apply.html` | Hidden `policy-type = phins_unified`; UI copy is disability + wealth building |
| `apply.js` `calculateBasePremium` | Flat `$0.25 / $1000 × age_factor` — **no** \(D=L/4\), **no** age-65 disability cliff |
| `server.calculate_premium` | Same flat formula for `life` / `health` / `phins_unified` |
| `Policy` model | Stores `type` + premium scalars only — **no** `product_id`, `disability_share`, `tables_version`, `contract_version` |
| Billing | Charges stored flat amount; never applies L:D |

Flat probe (same L=$500k — issuance path):

| Age | Monthly | Annual | Disability layer |
|---|---|---|---|
| 35 | $143.75 | $1,725 | none |
| 64 | $198.12 | $2,377.50 | none |
| 65 | $200.00 | $2,400 | none (no cliff) |
| 80 | $228.12 | $2,737.50 | none |

Same inputs as kernel age 35: issuance **~$1.7k/yr** vs kernel **~$15.6k/yr** (~9×), and issuance never encodes 1:4 vs life-only.

### 3.2 Health / non-risk mechanisms on the issue path (violates “no health mechanism”)

| Mechanism | Where | Conflict |
|---|---|---|
| Policy type `health` | `calculate_premium` base rates | Treated as insurable line equal to life flat rate |
| `phins_unified` apply flow | `apply.html` | Protection **25%** + Savings **75%** default split |
| Health Wallet / investment / algo | `apply.html` / `apply.js` | Wallet & wealth UI on the “risk” application |
| `health_wallet` on policy dict | `server.py` create path | Persisted beside premiums |
| Kernel product `line='life_health'` | `pricing_kernel.py` | Naming implies health LOB |

Contract draft forbids wallet/savings/investment on the **base** risk product; issuance UI is built around them.

**Issuance verdict:** **FAIL** vs intended risk product (no 1:4, no 65 disability stop, health/wealth mechanisms present, no version pins).

---

## 4. Adjustability + **persistence** of dashboard actuarial changes

### 4.1 What *is* adjustable today (kernel / actuary world)

| Knob | Where | Effect | Versioned? | Persists across restart? |
|---|---|---|---|---|
| `UnderwritingConfig.disability_share_of_life` (default 0.25) | Dashboard → `POST /api/actuarial/config` → `ActuarialTablesStore.update_config` | Single global \(D/L\) for all ages; integrity hash changes | Config only — does **not** bump `tables_version` / `config_version` | **No** — in-process memory + change log only |
| Mortality / disability rate tables | Store versions / uploads | Changes incidence → premiums | Yes — `tables_version` | Partial — uploads can hit `actuarial_tables` ORM; **active** store is still the singleton |
| Product cutoff / shares | Code constants | Structural rules | Code deploy | N/A |
| `CONTRACT_SPECIFICATION.version` | `'v1.0'` constant | Document identity | Not on policies | N/A |

`update_config` (see `actuarial_service.py`) mutates `self.config`, stamps `last_modified` / `modified_by`, and `_log_change` — it does **not** write UW config to Postgres/SQLite. `database/` has **no** model for actuarial underwriting config. Comment elsewhere notes simulations/fee schedules “DB schema not yet extended.”

**Settled requirement:** “keep changes persistence after actuarial adjustments from dashboard” → **FAIL today**. A process restart (or multi-worker) loses dashboard L:D / UW knobs unless re-entered. Table uploads have a better (but still incomplete) persistence story than config.

### 4.2 Age-band gap for 1:1 after 65

Even if the global slider were persisted at `1.0`, that would set **all ages** to 1:1, breaking pre-65 1:4. Target needs an **age-banded** (or schedule) control, e.g.:

```text
disability_share_schedule = [
  { age_min: 3,  age_max: 64, share: 0.25 },   # 1:4
  { age_min: 65, age_max: null, share: 1.0 },  # 1:1
]
```

…versioned with `tables_version` / `config_version`, applied inside kernel PV by attained age (instead of `disability_cutoff_age` zeroing), and persisted from the dashboard.

### 4.3 What issuance cannot adjust

- No path from dashboard L:D → `calculate_premium` / `apply.js`
- No pin of age-banded shares + `tables_version` + `contract_version` on `Policy`
- Flat premiums ignore all actuarial persistence anyway

### 4.4 Target adjustability + persistence (report-only)

```text
Stable Product Version (SPV) should freeze at least:
  product_id                 = phins_pure_risk_adjustable
  contract_version           = successor of v1.0 (text must say D=L after 65)
  disability_share_schedule  = 1:4 until 65; 1:1 after 65 (dashboard-editable)
  tables_version             = V2.x (mortality + disability incidence)
  config_version             = explicit revision id bumped on dashboard save
  integrity_hash             = PremiumComponents hash
```

Persistence requirements (settled):

1. Dashboard `update_config` / table activate → durable store (DB or versioned artifact), reloadable on boot.
2. Each save bumps a visible `config_version` (or SPV id), not only `last_modified`.
3. Kernel prices from the **persisted active** version; shadow/issue snapshots pin that version.
4. Restart / redeploy must restore the last actuary-published ratios and tables without manual re-entry.

---

## 5. Consistency matrix (after settled decision)

| Requirement | Kernel / contract | Issuance / billing | Dashboard persist + versions |
|---|---|---|---|
| 1:4 until 65 | Yes | No | Global slider only; not age-banded; not durable |
| **1:1 (D=L) after 65** | **No** — cutoff zeros disability | No | Cannot express post-65 band |
| Table pricing as source of truth | Kernel yes; contract text stale | Flat formula | Active store mostly in-memory |
| Persist dashboard actuarial adjustments | Change log in memory | N/A | **FAIL** — no UW-config DB row |
| No health mechanism | Contract text yes; `line=life_health` | **No** — wallet / unified wealth UI | N/A |
| Pin on issued policy | Components hash only (ephemeral) | Missing | Gap |

---

## 6. Ambiguity — resolved

Settled as **(2)**: after 65, **disability sum equals life sum** (\(D:L = 1:1\)).  
Not life-only. Kernel/contract “disability ceases at 65” is now explicitly **out of date** relative to product intent.

Remaining non-blocking design choices for a future implementation plan (not decided here):

- Q-A: Is post-65 1:1 a fixed product constant, or a dashboard-editable band defaulting to 1.0?
- Q-B: When term crosses 65, does each future year reprice disability sum on attained age (schedule), or lock issue-age band for the whole term?
- Q-C: Persistence backend — extend `actuarial_tables` / new `actuarial_config_versions` table vs file artifact (recommendation: versioned DB row + boot load into store).

---

## 7. Bottom line

- **Target risk product:** 1:4 until 65, **1:1 (D=L) after 65**, table/kernel priced, **dashboard adjustments must persist**, no health mechanism on the base contract.
- **Kernel today:** implements 1:4 then **turns disability off** at 65 — opposite of the settled post-65 rule; single global L:D knob; config edits are **not durable**.
- **Issuance today:** flat `$0.25/$1000` with health/wealth UI — neither L:D band nor persistence applies.
- **No code was changed for this report.** Next implementation slice (when approved) should include: age-banded share schedule + remove/repurpose cutoff-to-zero, durable config/table versioning from dashboard, then shadow SPV pins before any billed cutover.

### Sources

- `services/pricing_kernel.py` — `Product`, `_resolve_disability_share`, cutoff in PV loops, `PremiumComponents`
- `services/actuarial_service.py` — `CONTRACT_SPECIFICATION`, `UnderwritingConfig.disability_share_of_life`, `get_contract_specification`
- `web_portal/static/actuary-dashboard.html` — L:D display / config binding
- `web_portal/static/apply.html`, `apply.js` — `phins_unified`, allocation, health wallet
- `web_portal/server.py` — `calculate_premium`
- `tests/test_pricing_kernel.py` — L:D adjustability tests
- Live in-process probe 2026-08-07 (tables `V2.0`, config `kernel_v1`)
