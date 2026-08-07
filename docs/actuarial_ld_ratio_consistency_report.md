# Risk Product L:D Consistency Report

**Status:** Analysis only — no code changes  
**Date:** 2026-08-07  
**Scope:** Confirm risk product = life + disability at **1:4 until age 65**, **life 1:1 (disability off) after 65**, **no health mechanism**; compare kernel vs issuance; assess adjustability via tables/versions.

---

## 1. Intended product rule (as checked)

| Band | Disability : Life | Meaning |
|---|---|---|
| Ages 3–65 | **1 : 4** | Disability sum \(D = L/4\) |
| Ages 65+ | **Life 1 : 1, disability 0** | Full life sum \(L\) continues; disability cover ceases |

Reading of “1:1 disability / life after age 65” used here (aligned with `CONTRACT_SPECIFICATION`): after 65 the contract is **life-only at full L** (1:1 with sum insured), not “disability equals life.” If the literal intent were \(D=L\) after 65, that would be a **different product** — see §6.

**No health mechanism** means the base risk contract must not be a medical/health insurance product and must not require health-wallet / medical-expense machinery for pricing or benefits.

---

## 2. Kernel / contract — mostly consistent with the rule

### 2.1 Contract draft (`CONTRACT_SPECIFICATION` v1.0)

Source: `services/actuarial_service.py`

- Disability benefit: \(L \div 4\), trigger ages **3–65**
- Age 65+: “Disability cover ceases automatically”
- Life-only mode 65–∞: age-adjusted death benefit
- Disclaimer: base product = adjustable risk only — **no wallet, no savings, no investment** (savings add-on optional and separate)

Live API enrichment via `get_contract_specification()`:

```text
contract_ratios = {
  disability_share_of_life: 0.25,
  disability_to_life_ratio_display: "1:4",
  source: UnderwritingConfig.disability_share_of_life,
  adjustable_from_dashboard: True
}
```

### 2.2 Product registry (`pricing_kernel.PRODUCT_REGISTRY`)

| Product id | `disability_share` | `disability_cutoff_age` | Notes |
|---|---|---|---|
| `phins_pure_risk_adjustable` | 0.25 | 65 | Canonical; `fixed_disability_benefit_pct=1.0` (full \(D\) on trigger) |
| `phins_pure_risk` | 0.25 | 65 | Alias |
| `phins_life_only_post65` | 0.0 | 65 | Senior life-only helper |
| `phins_hybrid_savings` | 0.25 | 65 | Risk + savings add-on (not pure base) |

Caveat: product `line` is still labeled `life_health` / `life_health_savings` — naming only, but it blurs “no health mechanism.”

### 2.3 Live kernel probe (L = $500,000, term 20, ADL 5, tables V2.0)

| Issue age | `disability_share_used` | `disability_sum_used` | Disability premium | Mortality premium | Annual total |
|---|---|---|---|---|---|
| 35 | 0.25 (1:4) | $125,000 | $649.36 | $826.40 | $15,616.84 |
| 64 | 0.25 (1:4) | $125,000 | $178.99 | $7,924.57 | $24,000.99 |
| **65** | 0.25* | $125,000* | **$0.00** | $8,724.18 | $24,786.09 |
| 66 | 0.25* | $125,000* | **$0.00** | $9,283.93 | $25,494.18 |
| 80 | 0.25* | $125,000* | **$0.00** | $15,243.95 | $33,033.59 |

\*Stamp fields: for issue ages ≥65, PV logic correctly **zeros disability premium** (`current_age < disability_cutoff_age`), but `disability_share_used` / `disability_sum_used` still echo the config ratio \(0.25\) / \(L/4\). Benefit **economics** match “disability off”; **metadata** still looks like 1:4.

For ages &lt;65 with multi-year terms that cross 65, disability incidence is only accrued while `current_age < 65` inside the PV loop — consistent with the cliff.

Dashboard UI shows `Disability ÷ Life = 1 : 4` bound to `disability_share_of_life`.

**Kernel verdict vs intended rule:** **PASS** on economics (1:4 until 65; disability premium off at/after 65; life continues). Soft fails: `line=life_health` naming; post-65 stamp fields still show 1:4; no separate version id when only the ratio changes (see §4).

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

## 4. Adjustability via tables and versions

### 4.1 What *is* adjustable today (kernel / actuary world)

| Knob | Where | Effect | Versioned? |
|---|---|---|---|
| `UnderwritingConfig.disability_share_of_life` (default 0.25) | Actuary dashboard UW config → `PricingConfig` | Changes \(D/L\) for all kernel prices; integrity hash changes | **Config value only** — does **not** bump `tables_version` (stays e.g. `V2.0`) or `config_version` (`kernel_v1`) |
| Mortality / disability rate tables | `ActuarialTablesStore` versions (`V2.0`, uploads) | Changes incidence → premiums | Yes — `tables_version` on `PremiumComponents` |
| Product registry shares / cutoff | Code constants | Structural product rules | Code deploy only — not a durable SPV row |
| `CONTRACT_SPECIFICATION.version` | `'v1.0'` constant | Document identity | Not linked to issued policies |

Probe: setting `disability_share_of_life=1.0` at age 35 → `disability_sum=$500,000`, new integrity hash, **same** `tables_version=V2.0` / `config_version=kernel_v1`.

So the L:D ratio **is** actuary-adjustable and hashed on each price, but **ratio changes are not first-class version artifacts** the way rate-table uploads are. Issuance never reads the knob.

### 4.2 What issuance cannot adjust

- No path from dashboard L:D slider → `calculate_premium` / `apply.js`
- No pin of `disability_share_of_life` + `tables_version` + `contract_version` on `Policy`
- Changing tables V2.0 → V2.1 does not re-label in-force flat premiums (they were never kernel-priced)

### 4.3 Target adjustability (report-only recommendation)

For the risk product to stay “adjustable with relevant tables and versions” while preserving integrity:

```text
Stable Product Version (SPV) should freeze at least:
  product_id              = phins_pure_risk_adjustable
  contract_version        = v1.0 (or successor)
  disability_share_of_life / L:D band rules (1:4 to 65; life-only after 65)
  disability_cutoff_age   = 65
  tables_version          = V2.x (mortality + disability incidence)
  config_version          = kernel_v1 + hash of UW knobs
  integrity_hash          = PremiumComponents hash
```

Ratio edits should either (a) require a new `contract_version` / config revision id, or (b) be recorded on every `PremiumSnapshot` so history is reconstructible even if `tables_version` is unchanged.

---

## 5. Consistency matrix

| Requirement | Kernel / contract | Issuance / billing | Adjustable via tables/versions |
|---|---|---|---|
| 1:4 disability/life until 65 | Yes (share 0.25, D=L/4) | No | Kernel: yes via `disability_share_of_life`; issuance: no |
| Life full L after 65; disability off | Yes economically (dis prem = 0); stamp fields still show 0.25 | No age-65 benefit cliff | Cutoff is code constant (65), not table-versioned |
| No health mechanism | Contract text yes; product `line` still `life_health` | **No** — health type, wallet, 25/75 wealth split | N/A |
| Version pin on issued policy | Hash + versions on `PremiumComponents` only | Missing | Gap |

---

## 6. Ambiguity to confirm before any implementation

**Q (blocking for product wording only):** Does “1:1 disability / life after age 65” mean:

1. **Life-only at 1:1 with L** (disability ceases) — matches current contract + kernel economics, **or**
2. **Disability sum equals life sum after 65** (\(D:L = 1:1\)) — kernel does **not** do this today (disability goes to 0).

This report assumes **(1)**. If **(2)** is intended, kernel, contract draft, dashboard copy, and tests (`test_disability_share_from_config_drives_priced_disability`, cutoff behavior) would all need a deliberate product-change plan — still not done here.

---

## 7. Bottom line

- The **actuarial kernel + contract draft** already encode the risk product as **1:4 to 65 / life-only after 65 / no base health-wallet product**, with L:D adjustable from the actuary config (hashed, but not given its own version bump).
- The **issuance and billing path** does **not** implement that product: flat `$0.25/$1000`, no L:D, no disability cliff at 65, and active **health/wealth** mechanisms on apply (`phins_unified`, health wallet, savings split).
- Until issuance pins SPV fields (`product_id`, `disability_share_of_life`, `tables_version`, `contract_version`, `integrity_hash`) and stops treating health/wallet as the risk contract, the “central” risk product is governance-only.

**No code was changed for this report.** Follow-on work (when approved) should stay behind shadow dual-run / SPV pins before any billed cutover.

### Sources

- `services/pricing_kernel.py` — `Product`, `_resolve_disability_share`, cutoff in PV loops, `PremiumComponents`
- `services/actuarial_service.py` — `CONTRACT_SPECIFICATION`, `UnderwritingConfig.disability_share_of_life`, `get_contract_specification`
- `web_portal/static/actuary-dashboard.html` — L:D display / config binding
- `web_portal/static/apply.html`, `apply.js` — `phins_unified`, allocation, health wallet
- `web_portal/server.py` — `calculate_premium`
- `tests/test_pricing_kernel.py` — L:D adjustability tests
- Live in-process probe 2026-08-07 (tables `V2.0`, config `kernel_v1`)
