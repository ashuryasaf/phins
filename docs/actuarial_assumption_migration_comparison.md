# Actuarial Assumption Migration — Before / After Comparison

**Settled product rule (Draft 3.1 / kernel defaults on a $500k / ₪500k face):**

| Attained age | Life sum | Disability sum | Ratio |
|---|---|---|---|
| **&lt; 65** | Face (100%) — e.g. $500k | Life ÷ 4 — e.g. $125k | D : Life = **1 : 4** |
| **≥ 65** | Face ÷ 4 — e.g. $125k | = Life — e.g. $125k | D : Life = **1 : 1** |

Disability **does not terminate** at 65. Demographic multipliers (smoking / sex / ethnicity) default to **1.0** (neutral) and are adjustable from Pricing Parameters.

This document lists every surface that previously carried a stale assumption (Draft 2.0 life-only post-65, or Draft 3.0 full-face D=L post-65) and what it now says.

---

## 1. Prior assumption lineages (what we migrated away from)

| Lineage | Post-65 life | Post-65 disability | Where it lived |
|---|---|---|---|
| **Draft 2.0 / life-only** | Face ($500k) | **$0 (ceases)** | Risk 1-pagers, risk-reference API, actuary annual-report copy |
| **Draft 3.0** | Face ($500k) | **= Face ($500k)** at 1:1 | Israel regulatory EN/HE (+ PDFs), pitch / unicorn decks |
| **Draft 3.1 (current)** | **Face ÷ 4 ($125k)** | **= Life ($125k)** at 1:1 | Kernel, Pricing Parameters, all updated surfaces below |

---

## 2. Surface → change map

### A. Pricing kernel & valuations (source of truth)

| Surface | File(s) | Before | After |
|---|---|---|---|
| Pricing kernel age bands | `services/pricing_kernel.py` | Flat / life-only or full-face senior D | `life_share_*` + `disability_share_*` pre/post 65; PV stamps `life_sum_used` / `disability_sum_used` |
| Underwriting / Pricing Parameters | `services/actuarial_service.py` (`UnderwritingConfig`) | Single L:D share; optional cut-off | Age-banded life & disability shares; durable persist via `actuarial_persistence.py` |
| Contract specification API | `get_contract_specification()` | Static copy; Draft 2.0 rights text | Live `contract_ratios` + `demographic_risk_factors` with worked $500k examples |
| Benefit-sum helper | `contract_benefit_sums_at_age()` / `_from_config()` | *(new)* | Canonical attained-age L/D for every consumer |
| Risk-reference valuations | `risk_reference_monthly_premiums`, `build_risk_reference` | Disability monthly **0** at age 65 | Disability continues; age-65 monthly **life $50 / disability $40 / total $90** on $500k face (rates 0.25 / 0.20 × f=1.60) |
| Risk-reference profile | `RISK_REFERENCE_PROFILES['phins_published_v1']` | `disability_cut_off_age: 65` | `disability_cut_off_age: None`; post-65 life share 0.25 |
| Shadow / application pricing | `services/pricing_shadow_service.py`, `web_portal/server.py` | Legacy billing formula | Shadow dual-run always available; **billed** kernel path opt-in via `PHINS_KERNEL_BILLING_ENABLED` (default off); demographics on create |

### B. Meetings / presentations / 1-pagers

| Surface | File(s) | Before | After |
|---|---|---|---|
| Fefferman risk 1-pager | `web_portal/static/phins-risk-1pager-fefferman.html` | Life-only / D ceases at 65 | Pre-65 face & D÷4; from 65 life÷4 & D=life; JS model + liability copy |
| Goldsobel risk 1-pager | `web_portal/static/phins-risk-1pager-goldsobel.html` | Same as Fefferman | Same Draft 3.1 rule |
| Actuary dashboard (sandbox, annual report, contract blurb) | `web_portal/static/actuary-dashboard.html` | “Disability ceases / trigger to 65”; sandbox zeroed disability claims at 65 | Age-banded contract copy; Pricing Parameters show life share post-65 + D share post-65; sandbox pays attained-age L/D sums lifelong |
| Pitch dashboard (Israel memo card) | `web_portal/static/pitch-dashboard.html` | Draft 3.0 “D = L from 65” (full face) | Draft 3.1 wording + card label `post-65 life÷4 & D=life` |
| Unicorn investor deck | `web_portal/static/unicorn-investor-deck.html` | Draft 3.0 | Draft 3.1 bullet |
| Unicorn executive summary | `web_portal/static/unicorn-executive-summary.html` | Draft 3.0 | Draft 3.1 |

### C. Business plans / regulatory filings

| Surface | File(s) | Before (Draft 3.0 specimen @65) | After (Draft 3.1 specimen @65) |
|---|---|---|---|
| Israel regulatory memo EN | `web_portal/static/investor-docs/israel-regulatory-application-en.md` | Life 200 / D 160 / **Total 360**; D = ₪500k | Life **50** / D **40** / **Total 90**; L=D=₪125k |
| Israel regulatory memo HE | `…/israel-regulatory-application-he.md` | Same 360 table | Same 90 table (Hebrew) |
| Israel regulatory PDFs | `…-en.pdf`, `…-he.pdf` | Generated from Draft 3.0 MD | Regenerated from Draft 3.1 MD |

### D. Tests (integrity locks)

| Test | Before expectation | After expectation |
|---|---|---|
| `tests/test_actuarial_reserves.py` | `disability_monthly == 0` at 65 | `> 0`; life/disability sums 125k; monthly 50 / 40 |
| `tests/test_israel_regulatory_application_docs.py` | Draft 3.0 needles (`0.75 × L`, full-face senior D) | Draft 3.1 (`0.75 × F`, `56.25`, forbids `D = L = ₪500,000`) |
| `tests/test_document_branding.py` | Deck mentions `Draft 3.0` | `Draft 3.1` |
| Age-band / demographics / sim suites | *(added earlier on this branch)* | Kernel band + factor integrity |

---

## 3. Numeric comparison — reference policyholder (face $500k / ₪500k)

Illustrative monthly premiums using filed rates (life 0.25 / disability 0.20 per 1,000 × age factor). Pre-65 rows are unchanged across Draft 3.0 → 3.1; the break is at 65+.

| Age | f(x) | Draft 3.0 total / mo | Draft 3.1 total / mo | Δ |
|---|---|---|---|---|
| 35 | 1.15 | 172.50 | 172.50 | 0 |
| 64 | 1.585 | 237.75 | 237.75 | 0 |
| **65** | 1.60 | **360.00** (L=500k, D=500k) | **90.00** (L=125k, D=125k) | **−270.00** |
| 70 | 1.85 | 416.25 | 104.06 | −312.19 |
| 80 | 2.50 | 562.50 | 140.63 | −421.87 |

Draft 2.0 at 65 would have been life-only ≈ 200.00 with disability 0 — also superseded.

---

## 4. Integrity guarantees

1. **Single benefit-sum function** — `contract_benefit_sums_at_age` / `_from_config` feeds risk-reference, contract-spec examples, and docs.
2. **Risk-reference payload** includes `life_sum_post65`, `disability_sum_post65`, `disability_sum_matches_age_band`, and `disability_cut_off_age: null`.
3. **Kernel integrity hash** includes age-band shares and demographic factors so priced rows cannot silently drift from Pricing Parameters.
4. **Docs ↔ PDF** — Israel PDFs are regenerated from the markdown sources (`scripts/generate_investor_pdfs.py`); tests assert MD needles and PDF validity.
5. **Future data** — new policies / simulations / applications resolve sums from live `UnderwritingConfig` (persisted), not hard-coded Draft 2.0/3.0 constants.

---

## 5. Operator flags (unchanged semantics)

| Flag | Role |
|---|---|
| `PHINS_ACTUARIAL_STATE_PATH` | Local file cache of Pricing Parameters + rate tables (default `data/actuarial_store_state.json`). Saves also write a checksummed snapshot row to the `actuarial_tables` DB table (`table_type='actuarial_store_state'`) when `USE_DATABASE` is on, so central pricing control survives restarts **and redeploys**; the DB snapshot is loaded first on boot. |
| `PHINS_PRICING_SHADOW_ENABLED` | Dual-run shadow snapshots on create |
| `PHINS_KERNEL_BILLING_ENABLED` | Force kernel (`1`) or legacy flat (`0`). Unset defaults to kernel billing for mapped products. |

---

*Last updated: 2026-08-07 — migration of stale Draft 2.0 / 3.0 surfaces to Draft 3.1 age bands.*
