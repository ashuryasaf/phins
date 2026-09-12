# Monte Carlo Remediation Assessment

Code assessment of the anomalies and inconsistencies reported by the
Monte Carlo evaluation (`GET /api/bi/monte-carlo-evaluation`, engine
`mc-eval-1.0.0`) when run on a live PHINS deployment. This document maps
each finding to its root cause in code, proposes a fix, states the
data-integrity guard the fix must carry, and places it on an
urgent / important matrix.

Sections 1–4 are the assessment as written before any fix. Section 5
records what was then implemented, item by item, in the recommended order
(A → B → G → H → I → C → D → E → F → J → K; L is monitor-only). Every
change is additive or versioned; none rewrites stored ledger, audit,
config-history or policy data, and the evaluation engine still writes
nothing (`proposals_applied_by_engine: false`).

## 0. The run being assessed

| Input / result | Value |
|---|---|
| Eligible lives | 1 939 |
| Live `smoker_mortality_factor` / `smoker_disability_factor` | 1.3 / 1.3 |
| Live `auto_decline_threshold` | 6 |
| Headline | Anomalies detected: 2 anomalies, 4 assumption gaps, 8 next moves, 1 adjustable |
| Loss ratio, PHINS tables vs PHINS simulator | 36.21 % vs 72.87 % |
| 150 % reserve rule (as mirrored by the engine) | covers year-1 claims in 97.7 % of trials; 1.574× needed for 99 % |
| `ReserveConfig` IBNR 10 % sufficient | 58.7 % of trials |
| Smoker vs never-smoker loss ratio | 79.2 % vs 49.2 % |
| Claims manual-review share, simulated vs `AutomationMetrics` | 19 % vs 45 % |
| Sales target 5 %/month met | 22 % of paths; median 3.76 %/month |
| AI accept/review thresholds | consistent |

Two facts frame everything below:

1. **1 939 lives is a small portfolio.** Claim-count volatility scales with
   1/√n, so year-1 loss-ratio and reserve results are dominated by size, not
   by assumption error. Anything that proposes tightening a multiple or a
   factor must be re-checked at the portfolio size it will actually be
   applied to.
2. **One of the two "anomalies" is an engine defect, not a PHINS defect**
   (item A). It must be fixed first, because it is the item the admin is
   currently being asked to act on.

## 1. Priority matrix

Urgent = a wrong or misleading number is being consumed *today* by a
decision path (admin next-move card, reinsurance quote, financial report)
or the fix is trivial and visible. Important = affects the correctness of
pricing, reserving, reporting or the integrity of the evaluation itself.

| | Important | Not important |
|---|---|---|
| **Urgent** | **A** Engine mirrors the 150 % reserve rule on the wrong basis (report-integrity defect) · **B** Two "annual expected claims" definitions feed dashboards and the reinsurance risk band unlabelled | **G** `reserves_reporting_service` hard-codes `0.65` and ignores the config it fetched · **H** Actuary dashboard labels the 1.5× PV number "Regulatory reserve" · **I** §4.3 of the methodology report carries the same mislabel as A |
| **Not urgent** | **C** `reserve_requirement` basis (1.5× full-term PV) is undocumented and consumed by reinsurance `reserve_relief` · **D** Two IBNR rules on two bases, both below the lag-implied need at small n · **E** Smoker factor 1.3 leaves a ~30-pt loss-ratio gap against the world assumption; adjustable, but should be validated against PHINS experience first · **F** Sales forecast is deterministic compounding with no churn or bands | **J** `AutomationMetrics.BASE_RATES` is a fixed mix, not observed behaviour · **K** Claims-bot thresholds 0.85 / 0.70 / 0.45 have no labelled-outcome test · **L** AI thresholds consistent — monitor only |

Recommended order of work: A → B → G → H → I → C → D → E → F → J → K.
A, B, G, H, I together touch the evaluation engine, one `risk_metrics`
dict, one hard-coded constant, one HTML label and one doc section; none of
them changes a stored value.

## 2. Item-by-item assessment

Each item: what the report showed → root cause in code → proposed change →
integrity guard → tests → blast radius.

### A. Engine mirrors the 150 % reserve rule on the wrong basis — Urgent + Important

**Report:** "150 % reserve covers year-1 claims in 97.7 % of trials; 1.574×
needed for 99 % coverage", surfaced as an anomaly and an `investigate`
next-move card.

**Root cause (engine, not PHINS):**

```text
services/monte_carlo_evaluation_service.py : evaluate_actuarial_metrics
    phins_sim_expected_claims = pv_total / avg_term          # annual
    reserve_requirement      = phins_sim_expected_claims * 1.5

services/actuarial_service.py : PortfolioSimulator (risk_metrics)
    'annual_expected_claims': total_expected_claims / avg_term
    'reserve_requirement'   : total_expected_claims * 1.5    # PV over FULL term
```

PHINS holds 1.5 × the present value of all expected claims over the
remaining term. The engine tests 1.5 × *one year* of expected claims. At an
average term of ~17.5 years the real PHINS requirement is roughly 17× the
number the engine stressed, so the true PHINS rule covers year-1 claims in
~100 % of trials. The reported anomaly is a statement about a rule PHINS
does not run. The same mirror sits behind the `reserve_rule_150pct` block,
finding text ("The 1.5× rule covers year-1 claims in only …"), the
`investigate` next move, and rows in
`docs/monte_carlo_methodology_evaluation.md` §4.3 (item I).

**Proposed change (engine only):**

1. Mirror PHINS exactly: `reserve_requirement_pv_basis = pv_total * 1.5`
   and test year-1 claims against it (expected result: ~100 % coverage).
2. Keep the year-1 stress as a *separately labelled* metric —
   `year1_claims_stress`: VaR99 / TVaR99 of year-1 claims as a multiple of
   annual expected claims. This is the useful volatility statistic; it is
   simply not "the 150 % rule".
3. Rename the finding/next move accordingly; the `adjust`/`redirect`
   surface is unchanged (this move never had an `adjust` action).
4. Bump `ENGINE_VERSION` to `mc-eval-1.0.1` so every sealed report states
   which mirror produced it.

**Integrity guard:** the engine stays read-only; `results_sha256` will
change because the results change, which is exactly what the version bump
is for. Keep the `reserve_rule_150pct` key with an explicit `basis` field so
stored/exported reports from 1.0.0 remain parseable.

**Tests:** in `tests/test_monte_carlo_evaluation.py`, build the same lives
through `PortfolioSimulator` and assert the engine's
`reserve_requirement_pv_basis` equals `risk_metrics.reserve_requirement`
within rounding; assert year-1 coverage of the PV-basis rule ≥ 0.99 at
2k lives; keep the existing determinism and no-mutation tests.

**Blast radius:** `services/monte_carlo_evaluation_service.py`,
`tests/test_monte_carlo_evaluation.py`, docs. No PHINS service, config or
ledger path touched.

### B. Two "annual expected claims" definitions, unlabelled — Urgent + Important

**Report:** loss ratio 36.21 % (PHINS tables) vs 72.87 % (PHINS simulator),
flagged as an anomaly (PHINS disagreeing with itself).

**Root cause:** both numbers are internally consistent, they define
"annual" differently:

```text
kpi_definitions / BI            : year-1 expected claims (current ages) ÷ annual premium
PortfolioSimulator (line ~1825) : (PV of claims over full term ÷ avg_term) ÷ annual premium
```

The second bakes ageing into a single "annual" figure, so it is a
level-annualised lifetime loss ratio, not a year-1 loss ratio. Both are
shown to users under the single word "loss ratio". The simulator's figure
also drives `classify_reinsurance_risk_band(loss_ratio_pct)` in
`services/actuarial_service.py` and therefore the reinsurance
`pricing_load` (1.08–1.24), so the choice of definition changes a quote.

**Proposed change (additive):** in `PortfolioSimulator.risk_metrics` add
`loss_ratio_basis: 'lifetime_annualised'` and a second, explicitly named
`loss_ratio_year1` (year-1 tables at current ages ÷ annual premium). Keep
`loss_ratio` unchanged for compatibility. Surface both, labelled, in the
actuary and accountant dashboards and in `kpi_definitions`. The reinsurance
band should state which basis it uses (recommend year-1 for a one-year
treaty, lifetime-annualised for a quota-share over the term) rather than
silently inheriting `loss_ratio`.

**Integrity guard:** new keys only; no stored report is recomputed; the
reinsurance band is *documented*, not changed, in this step. Any later
switch of basis for the band is a separate audited change.

**Tests:** `tests/test_actuarial*` — assert both keys present, assert
`loss_ratio_year1 ≤ loss_ratio` for an ageing portfolio, assert
`reinsurance` output carries `loss_ratio_basis`.

**Blast radius:** `services/actuarial_service.py` (one dict, one
reinsurance field), two HTML labels, `kpi_definitions`, tests.

### C. `reserve_requirement` basis undocumented, consumed downstream — Important, not urgent

**Root cause:** `'reserve_requirement': total_expected_claims * 1.5` is
commented "150 % of expected claims" but is 1.5 × full-term PV. It is
consumed as-is by:

- `services/actuarial_service.py` reinsurance: `reserve_relief =
  reserve_requirement * protected_claims_share`
- `web_portal/static/actuary-dashboard.html` (row "Reserve Requirement
  (150 %) … Regulatory reserve", item H)
- `web_portal/static/accountant-dashboard.html` stat cards
- `web_portal/server.py` CSV/PDF exports

A separate `financial_reporting_service.py` computes its own
`reserve_requirement = total_coverage × 0.05 + savings_liability`, so the
platform has two unrelated quantities under one name.

**Proposed change:** add `reserve_requirement_basis: 'pv_full_term_x1.5'` to
`risk_metrics`; rename the financial-reporting one at the *label* level
(keep the key) to "capital indication" or similar; document both in
`docs/platform_data_architecture.md`. Do not change either value.

**Integrity guard:** additive fields and labels only.

**Tests:** presence of `reserve_requirement_basis`; `reserve_relief` still
equals `reserve_requirement × share`.

### D. Two IBNR rules, two bases, both below the lag-implied need at small n — Important, not urgent

**Report:** `ReserveConfig` IBNR 10 % sufficient in 58.7 % of trials.

**Root cause:**

```text
services/actuarial_service.py : ReserveCalculator
    ibnr = in_force_claims * config.ibnr_pct            # 10 % of expected claims
services/reserves_reporting_service.py
    ibnr = annual_risk_premium * 0.65 * ibnr_factor(0.15) # 9.75 % of premium
```

They disagree by construction (one is % of claims, one is % of premium ×
an assumed loss ratio), and neither is derived from a reporting-lag model.
Under the engine's *world* assumption (45-day mean lag) ≈12.5 % of year-1
claims are unreported at year-end. That lag is an assumption, not PHINS
data — which is why this is not urgent: the right first step is to measure
PHINS's own report-lag distribution from `claims` (`incident_date` vs
`reported_at`/`created_at`) before moving either constant.

**Proposed change:**

1. One IBNR function in `services/actuarial_service.py`
   (`ibnr_provision(expected_claims, lag_model)`) used by both callers;
   `reserves_reporting_service` calls it instead of its own formula.
2. Make `ReserveConfig.ibnr_pct` adjustable through the audited
   `update_config` path (it currently is not, which is why the engine emits
   a `redirect`, not an `adjust`, for this item).
3. Add an observed-lag report (`/api/actuarial/claims-lag`) so the constant
   can be calibrated from data.

**Integrity guard:** the reporting service must keep producing the same
`claims_reserve_ibnr` until the constant is *explicitly* changed through
`update_config` (audit log + `config_history`). Refactor first with a
characterisation test asserting byte-equal output; change the number in a
separate audited step.

**Tests:** characterisation test for `reserves_reporting_service` output
before/after refactor; `update_config({'ibnr_pct': …})` writes audit +
history and is restorable via versions.

### E. Smoker factor 1.3 leaves a ~30-pt gap — Important, not urgent (adjustable, guarded)

**Report:** smoker LR 79.2 % vs never-smoker 49.2 % with both smoker
factors at 1.3; the one `adjust` next-move.

**Root cause:** `services/pricing_kernel.py` applies
`smoker_mortality_factor` / `smoker_disability_factor` multiplicatively to
the hazard; the engine's *world* assigns smokers a materially higher hazard
than 1.3×. The gap is therefore assumption-vs-world, not a code defect. Note
that `services/underwriting_risk_scoring.py` adds `lifestyle_risk = 0.25`
for current smokers, but that feeds acceptance/referral, not price — so
raising the pricing factor does not double-count; it also does not change
who is accepted.

**Proposed change:** none to code. The existing guarded apply flow
(confirm → read-back drift check → `POST /api/actuarial/config` with
`change_reason` → read-back verify → re-run) is the correct instrument.
Before applying, validate the ratio against PHINS's own experience: the
platform does not yet report loss ratio by smoking status from real claims —
add that read-only BI slice first (`bi_analytics_service`, group claims by
`smoking_status`), then adjust to the observed ratio, not the world's.

**Integrity guard:** already in place (audited `update_config`, append-only
`config_history`, engine never writes). Keep `_clamp_factor(1.0, 3.0)`.

**Tests:** existing `tests/test_monte_carlo_evaluation.py` smoker-move tests
and demographic-factor suites.

### F. Sales forecast is deterministic compounding — Important, not urgent

**Report:** 5 %/month target met in 22 % of paths; median 3.76 %/month.

**Root cause:** `services/bi_analytics_service.py:predict_revenue_forecast`
computes `current_mrr × (1 + g)^month` with `g = 0.05` by default, no
churn/lapse, no seasonality, no bands. The default is a parameter, but
callers use the default.

**Proposed change:** derive `historical_growth_rate` from observed policy
start dates when ≥ 6 months of data exist (fall back to the parameter
otherwise, and say so in the response); subtract the lapse-table churn;
return p10/p50/p90 alongside the point forecast. Additive keys
(`forecast_basis`, `bands`), `forecast` unchanged.

**Integrity guard:** additive; no stored KPI is rewritten.

**Tests:** `tests/test_bi_analytics*` — basis field, bands monotone, default
path unchanged when history is short.

### G. Hard-coded `0.65` ignores fetched config — Urgent, not important

`services/reserves_reporting_service.py` fetches `store.config` and then
uses `loss_ratio = Decimal('0.65')  # Standard assumption` regardless. Read
the platform's loss-ratio assumption from config (or from item B's
`loss_ratio_year1`) and keep `0.65` only as the documented fallback. Trivial;
add a characterisation test that output is unchanged while config equals
the default.

### H. "Regulatory reserve" label on a 1.5× PV number — Urgent, not important

`web_portal/static/actuary-dashboard.html` row "Reserve Requirement (150 %)
… Regulatory reserve". It is neither a regulatory figure nor 150 % of the
annual number shown beside it. Relabel to "Reserve indication (1.5 × PV of
expected claims over term)". Label-only change.

### I. Methodology report §4.3 carries the mislabel from A — Urgent, not important

`docs/monte_carlo_methodology_evaluation.md` §4.3 rows "150 % reserve rule
covers year-1 claims" and "Multiple needed for 99 % coverage", and
conclusion 1, describe the engine's annual-basis mirror. Correct alongside A
(see the erratum note added to that section).

### J. `AutomationMetrics.BASE_RATES` is a fixed mix — Neither

`services/actuarial_service.py:AutomationMetrics` advertises claims manual
review 45 %, underwriting manual 30 %, scaled only by portfolio size. The
simulation puts claims manual review at 19 %. This is an investor/BI
display, not a decision path. When convenient, compute the mix from actual
`claims`/`underwriting` decision records and fall back to `BASE_RATES` only
when the sample is small, exposing `source: 'observed'|'assumed'`.

### K. Claims-bot thresholds untested against outcomes — Neither

`services/claims_bot_service.py:_make_recommendation` uses 0.85 / 0.70 /
0.45 authenticity cut-offs. The engine can only show their *mix*, not their
accuracy, because there is no labelled outcome set. Monitor; when reviewer
overrides are recorded, calibrate from them.

### L. AI accept/review thresholds — Neither (monitor)

Reported consistent. No action.

## 3. Data-integrity rules for every fix above

1. **The evaluation engine never writes.** A, I change what it *reports*;
   `proposals_applied_by_engine` stays `False` and the seal hashes are the
   evidence.
2. **Additive before substitutive.** New keys (`*_basis`, `loss_ratio_year1`,
   `reserve_requirement_pv_basis`, `bands`) are added next to existing ones;
   no existing key changes meaning without a version bump.
3. **Constants move only through the audited path.** `ibnr_pct`, smoker
   factors and any loss-ratio assumption change via
   `ActuarialTablesStore.update_config` (audit log, append-only
   `config_history`, `change_reason`), never by editing a default in code
   on a live system.
4. **Characterise, then change.** Refactors (D, G) land with a test that the
   output is byte-equal at default config; the numeric change is a separate
   commit and a separate audit entry.
5. **Re-run after apply.** Any applied adjustment is followed by a fresh
   sealed evaluation so the before/after `results_sha256` pair is on record.
6. **Small-n caveat travels with the number.** Any metric that scales with
   1/√n (reserve coverage, IBNR sufficiency, year-1 LR) is reported with
   `eligible_lives`, and next-move text must not propose tightening a
   multiple on a 2k-life run without saying so.

## 4. What this assessment does not do

- It does not apply any fix; the live deployment's config is unchanged.
- It does not decide the correct reinsurance loss-ratio basis (B) or the
  correct IBNR constant (D); both need PHINS's own experience data first,
  and the recommended first steps are read-only reports that produce it.

## 5. Remediation status

| Item | Status | What landed | Integrity guard in place | Tests |
|---|---|---|---|---|
| **A** | Done | Engine `mc-eval-1.0.1` mirrors the 150 % rule on PHINS's full-term PV basis (`reserve_rule_150pct.basis = pv_full_term_x1.5`); year-1 claim volatility reported separately as `year1_claims_stress` (VaR99/TVaR99, "not a PHINS rule"). `act_reserve_multiple` is an *investigate* move and never proposes a multiple. | Engine read-only; `RESERVE_REQUIREMENT_MULTIPLE` shared constant pinned to `PortfolioSimulator` | `tests/test_monte_carlo_evaluation.py` (PV-basis mirror on isolated store; no-tightening guard) |
| **B** | Done | `risk_metrics` gains `loss_ratio_basis`, `loss_ratio_year1`, `loss_ratio_year1_on_risk`, `expected_claims_year1`; reinsurance output labels its basis; `kpi_definitions.LOSS_RATIO_BASES`; actuary dashboard and export rows relabelled. | Additive keys only; legacy keys numerically unchanged (asserted) | `tests/test_actuarial_metric_bases.py` |
| **C** | Done | `reserve_requirement_basis` / `reserve_requirement_multiple` on `risk_metrics`; `financial_reporting_service` labels its capital indication `coverage_x0.05_plus_savings_liability`; `docs/platform_data_architecture.md` metric-bases table. | Additive | `tests/test_actuarial_metric_bases.py` |
| **D** | Done | One `ibnr_provision()` (basis `share_of_expected_claims`) used by `ReserveCalculator` (`ibnr_basis` block) and labelled in `reserves_reporting`; `ibnr_pct`, `ibnr_reporting_factor`, `loss_ratio_assumption` are audited `UnderwritingConfig` fields (defaults 0.10 / 0.15 / 0.65 = former constants); Reserves form defaults from config; `GET /api/actuarial/claims-lag` observed lag → implied share (≥ 30 claims). `act_ibnr_pct` is a guarded *adjust* move. | `update_config` audit + `config_history` + restore; characterisation: output cent-equal at defaults with and without store; nothing written by the report | `tests/test_ibnr_unification.py` |
| **E** | Done | `GET /api/bi/loss-ratio-by-smoking`: real active policies + incurred claims by kernel smoking cohort, `min_lives` guard (30), implied factor = live × observed LR ratio (clamped 1–3). MC `uw_smoker_demographic_factors` scales by the observed ratio when sufficient (`ratio_basis: observed_experience`), else labels `simulated_world`. | Read-only slice; apply path unchanged (audited `update_config`, drift check) | `tests/test_loss_ratio_by_smoking.py` |
| **F** | Done | `predict_revenue_forecast`: growth observed from policy start dates (≥ 6 complete months, else labelled default), lapse-table year-1 churn, additive `bands` (p10/p50/p90, closed-form) and `forecast_basis`; legacy `forecast` key unchanged. Route omits `growth_rate` → observed. | Additive; explicit `growth_rate` still overrides | `tests/test_revenue_forecast_basis.py` |
| **G** | Done | `reserves_reporting_service` reads `loss_ratio_assumption` / `ibnr_reporting_factor` from the attached store (source `actuarial_config:<version>`), falls back to the same constants; `ibnr_assumptions` and `loss_performance_target_pct` published. | Decimal arithmetic unchanged; characterised cent-equal | `tests/test_ibnr_unification.py` |
| **H** | Done | Actuary dashboard row reads "Reserve Indication (1.5 × PV of expected claims over term)"; accountant dashboard labels the capital indication from `reserve_requirement_label`. | Label only | static integrity suites |
| **I** | Done | Methodology §4.3 split into PHINS PV rule vs year-1 stress rows; correction note; conclusion and recommendation rewritten; §7.1 lists the companion reports. | Docs | — |
| **J** | Done | `AutomationMetrics.observe_automation_mix()` from decided underwriting/claims/billing records; `calculate_automation_rates(count, observed=…)` shows the observed mix per process at ≥ 30 decided records and labels every process `source: observed|assumed` (route, dashboard tag, MC evidence). | Assumed path byte-for-byte legacy (characterised); inputs never mutated | `tests/test_automation_metrics_observed.py` |
| **K** | Done | `calibrate_claims_thresholds()` sweeps the authenticity cut-offs against reviewer decisions on `claims_fraud` assessment records; `GET /api/claims/bot-threshold-calibration`; proposes only below-live disagreement at ≥ 30 labelled decisions. Live constants unchanged. | Recommend-only; `adjust_via` names the code constant | `tests/test_claims_bot_threshold_calibration.py` |
| **L** | Monitor | No change. | — | — |
