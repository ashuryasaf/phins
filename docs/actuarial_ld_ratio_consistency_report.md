# Risk Product L:D Consistency Report

**Status:** Settled product rule implemented in kernel + dashboard config + durable persistence  
**Date:** 2026-08-07 (updated: post-65 life steps down to face÷4; D stays = life)  
**Scope:** Confirm risk product age bands, no health mechanism, table/version adjustability, and persistence of dashboard actuarial adjustments.

---

## 0. Settled product decision (2026-08-07)

Session-settled by product owner (final “make opposite” clarification):

| Band | Life sum | Disability | Example on $500k face |
|---|---|---|---|
| Until age 65 | **100% of face** | **D = life ÷ 4** (1:4) | Life **$500k**, D **$125k** |
| From age 65+ | **25% of face** (life ÷ 4) | **D = life** (1:1) | Life **$125k**, D **$125k** |
| Pricing source | **Table / actuary-config pricing** | Kernel + versioned tables/config — not flat `$0.25/$1000` |
| Dashboard edits | **Must persist** | Actuarial adjustments survive restart |
| Health | **No health mechanism** on the base risk product | |

Key nuance vs an earlier reading: after 65, disability does **not** step up to the original $500k face. Life steps **down** to $125k and disability **stays** equal to that reduced life sum ($125k).

---

## 1. Target rule (authoritative)

| Band | Life : Face | Disability : Life | Meaning |
|---|---|---|---|
| Ages &lt; 65 | **1 : 1** | **1 : 4** | Life = face; \(D = L/4\) |
| Ages ≥ 65 | **1 : 4** | **1 : 1** | Life = face/4; \(D = L\) |

**No health mechanism** means the base risk contract must not be a medical/health insurance product and must not require health-wallet / medical-expense machinery for pricing or benefits.

---

## 2. Kernel / contract — **PASS** vs settled rule

### 2.1 Config knobs (`UnderwritingConfig` / `PricingConfig`)

| Field | Default | Role |
|---|---|---|
| `life_share_of_coverage` | 1.0 | Pre-65 life = face |
| `life_share_of_coverage_post65` | 0.25 | Post-65 life = face÷4 |
| `disability_share_of_life` | 0.25 | Pre-65 D = life÷4 |
| `disability_share_of_life_post65` | 1.0 | Post-65 D = life |
| `disability_band_age` | 65 | Band boundary |

Surfaced on `GET` contract specification as `contract_ratios` with example pre/post sums for a $500k face.

### 2.2 Product registry (`phins_pure_risk_adjustable`)

Uses `disability_benefit_on_disability_sum=True` so disability is always relative to the **then-current life sum**. Age-banded shares come from `PricingConfig`, not a hard disability cutoff to zero.

### 2.3 Live kernel probe (face = $500,000, term 10–20, ADL 5)

| Issue age | Life sum | D sum | D share | Verdict |
|---|---|---|---|---|
| 35 | $500,000 | $125,000 | 0.25 | PASS |
| 64 | $500,000 | $125,000 | 0.25 | PASS |
| **65** | **$125,000** | **$125,000** | **1.0** | **PASS** |
| 70 | $125,000 | $125,000 | 1.0 | PASS |

---

## 3. Issuance / apply / billing — still not cut over

Issuance still uses flat `$0.25/$1000` for billed amounts. Shadow dual-run (`PHINS_PRICING_SHADOW_ENABLED`) compares kernel vs flat without changing billed premiums. Full cutover remains Phase D.

---

## 4. Persistence

Dashboard saves via `POST /api/actuarial/config` bump `config_version` and write `PHINS_ACTUARIAL_STATE_PATH` / `data/actuarial_store_state.json` through `services/actuarial_persistence.py`.

---

## 5. Tests

- `tests/test_age_banded_disability_and_persistence.py` — issue-age 35/65 sums, life-share adjustability, persistence reload, contract_ratios examples
- `tests/test_pricing_kernel.py` — broader kernel integrity
- `tests/test_pricing_shadow_service.py` — shadow dual-run
