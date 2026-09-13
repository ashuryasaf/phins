# Monte Carlo Evaluation of PHINS Methodology and Assumptions

Statistical evaluation of how well PHINS's *own* rules — risk assessment,
underwriting, actuarial metrics, claims triage, sales forecasting and AI
thresholds — perform under a transparent stochastic world, with concrete
recommendations for the methodology, the assumptions, and how BI and AI
should consume the results.

Engine: `services/monte_carlo_evaluation_service.py` (`mc-eval-1.0.2`;
1.0.0/1.0.1 numbers are retained below where noted).
API: `GET /api/bi/monte-carlo-evaluation`. CLI:
`scripts/run_monte_carlo_evaluation.py`. Tests:
`tests/test_monte_carlo_evaluation.py`.

## 1. Scope and data-integrity contract

The evaluation is **diagnostic BI**: it recommends, it never changes a rule.

| Guarantee | How it is enforced |
|---|---|
| Read-only | No writes to stores, DB, ledger, BI snapshots or audit logs. PHINS assumptions are *read* from the live objects (`ActuarialTablesStore`, `UnderwritingConfig`, `ClaimsBotService`, env thresholds) and snapshotted into the report with a SHA-256. A test asserts the actuarial config and tables are byte-identical after a run. |
| Deterministic | One `random.Random(seed)`; identical seed + parameters ⇒ identical `results_sha256` (verified across processes: `30dd1328…` for the deep run below). The population is synthetic; live data enters only as labelled evidence (`observed_inputs`: MRR start, growth basis, smoking experience, automation mix). A re-run with the same seed against unchanged rules therefore returns the same numbers by design — that is the seal working, not stale or mock data. The admin panel draws a fresh seed per click and pins the seed only for like-for-like re-runs after a config change. |
| Synthetic population | Lives are generated, never taken from customer records. Optional live `policies`/`claims` are read only for aggregate MRR, fingerprinted before/after, and the report carries `observed_inputs_unchanged`. |
| Explicit world model | Every "truth" that is not a PHINS assumption lives in `WorldAssumptions`, is adjustable (`world.<name>` query params, `--world name=value`) and hashed into `world_assumptions_sha256`. |
| Bounded compute | `lives ≤ 50 000`, `trials ≤ 20 000`, `bootstrap ≤ 2 000`, `horizon ≤ 30` years. Default API call (2 000 lives, 400 trials) runs in ≈2–4 s. |

Note on `/model-deployment`: that skill deploys LoRA models fine-tuned through
SageMaker Serverless Model Customization. PHINS has no such training job — its
AI surfaces are deterministic rules plus an optional *advisory* LLM (see
`docs/ai_surface_design_principles.md`) — so the skill does not apply. The
evaluation below is the statistically meaningful substitute: it measures the
rules themselves.

## 2. Method

### 2.1 Generative world (adjustable, documented, not PHINS config)

Applicants: age ~ N(35, 12) clipped to 18–75; smoking 15 % current / 10 %
former (the `SimulationParams` mix); ADL by the simulator's age weights;
BMI ~ N(26.5, 4.5); conditions drawn from an age-dependent catalog and
translated into scorer inputs by the production
`chat_application_service.parse_conditions_text`; prior claims ~ Poisson(0.25);
coverage lognormal (median $250k, clipped $50k–$2M); term 5–30 years.

Hazards start from the **PHINS V2.0 tables** (mortality × ADL mortality
multiplier, disability incidence × ADL disability multiplier) and the world
applies relative risks that PHINS prices at 1.0 by default:

| World assumption | Default | Rationale |
|---|---|---|
| Smoker mortality / disability RR | 2.0 / 1.4 | Conservative literature-style magnitudes |
| Former-smoker RR | 1.3 / 1.15 | |
| Condition hazard | 1 + 2.5 × Σ scorer `risk_impact` | Ties world severity to the loadings PHINS already assigns |
| BMI | +3 % hazard per point over 30 | |
| Prior claim | ×1.15 per claim | |
| Reporting lag | lognormal, mean 45 d, σ 0.8 | Drives IBNR need |
| Anti-selective lapse | healthy tercile ×1.3, impaired tercile ×0.7 | |
| Fraud rate | 5 % of claims | |
| MRR growth volatility | σ 4 %/month, AR(1) 0.3, 3 %/month chance of −15 % shock | |
| AI accuracy | 85 %; error cost 50 : review cost 1 | |

A **neutral-world control** sets every RR to 1.0 and the condition/BMI/claims
effects to zero, so the world equals the PHINS tables exactly. Differences
between the two runs isolate *assumption mismatch* from *rule quality*.

### 2.2 What each module measures

| Module | PHINS surface evaluated | Statistics |
|---|---|---|
| `risk` | `underwriting_risk_scoring.assess_application` (production extraction + scoring path) | AUC vs realised horizon claims with bootstrap CI, oracle AUC on true hazard, Spearman vs hazard, Brier, band calibration with Wilson CIs, loading adequacy per band, recommendation mix vs `AutomationMetrics.BASE_RATES` |
| `underwriting` | `UnderwritingConfig` decline/loading/caps/exclusion, auto-approval gates, `pricing_kernel.price_policy` | Expected loss ratio by ADL and smoking status (tables vs world), decline-threshold sensitivity, hypothetical auto-approval pass rate and hazard profile, reinsurance band |
| `actuarial` | Tables, 150 % reserve rule, `ReserveConfig.ibnr_pct`, `reserves_reporting` IBNR rule, lapse table | Year-1 and 5-year loss-ratio distributions (p05…p99, VaR, TVaR), P(LR>100 %), reserve-rule coverage probability and multiple needed for 99 %, IBNR sufficiency, deterministic anti-selection drift |
| `claims` | `ClaimsBotService` weights, penalties and `_make_recommendation` (called directly) | Fraud leakage rate/amount, legitimate false-denial and friction rates, denial precision, decision mix vs base rates, threshold sweep through a mirror whose agreement with the live recommender is reported (1.000) |
| `sales` | `bi_analytics_service.predict_revenue_forecast` (5 %/month compound) | MC MRR multiples at 3/6/12 months vs deterministic, P(meets forecast), P(below start), mean shortfall |
| `ai` | `llm_providers.review_disposition` (0.90/0.70), `_MAX_ADVISORY_CONFIDENCE` cap, `ai_threshold_config` (0.85/0.15) | Disposition mix, error rate among accepted, share of errors routed to humans, cost-weighted threshold sweep, UW automation false-approve/false-reject rates |

## 3. Runs

All runs: seed `20260911`, horizon 5 years, 300 bootstrap resamples.

| Run | Lives | Trials | World | `results_sha256` |
|---|---|---|---|---|
| Deep | 20 000 | 2 000 | default | `30dd1328bef2a4e1cb4d3cdf71d58372af5456baf3ed2c74a2d231314cfa1e6c` |
| Neutral control | 20 000 | 2 000 | RR = 1, no condition/BMI/claims effects | `10c9309dc79603d523d11084359c534ae89719f3a567103216389186a92557f2` |
| Small portfolio | 2 000 | 2 000 | default (actuarial + underwriting) | `6e7c01a84ab0af370c88319726bbd181d7ba7e7bf9c5c15cbf764a1370f47b71` |

Reproduce: `python3 scripts/run_monte_carlo_evaluation.py --lives 20000 --trials 2000 --bootstrap 300 --seed 20260911 --summary`.

## 4. Findings

### 4.1 Risk assessment (`underwriting_risk_scoring`)

| Metric | Deep run | Neutral control |
|---|---|---|
| AUC (5-year claim) | **0.712** [0.694, 0.730] | 0.652 [0.631, 0.674] |
| Oracle AUC (true hazard) | 0.781 | 0.753 |
| Spearman score vs hazard | 0.62 | 0.42 |
| Brier (score as probability) | 0.106 | 0.106 |
| Brier (base rate) | 0.032 | 0.024 |
| Bands monotonic in outcomes | yes | yes |

Band calibration (deep run, n = 20 000):

| Band | Share | Observed 5-yr claim rate (95 % CI) | Applied loading | Loading needed vs tables |
|---|---|---|---|---|
| very_low → auto_approve | 19.2 % | 0.8 % (0.6–1.1) | 0 % | +2 % |
| low → approve_standard | 36.1 % | 2.0 % (1.7–2.3) | 0 % | +10 % |
| moderate → loading | 25.9 % | 3.9 % (3.4–4.4) | 28 % | 36 % |
| elevated → exclusions | 13.2 % | 5.9 % (5.0–6.8) | 51 % | 74 % |
| high → refer senior UW | 4.1 % | 10.9 % (8.9–13.2) | 85 % | 117 % |
| very_high → decline | 1.5 % | 16.9 % (13.1–21.6) | n/a | n/a |

What this says:

1. The scorer **ranks** risk usefully (AUC 0.71) and its bands are monotonic
   with tight, non-overlapping CIs from `low` upward — the banding is sound.
2. It is an **additive index, not a probability**: its Brier score (0.106) is
   three times worse than simply predicting the base rate (0.032). Anything
   in BI that treats `overall_risk` as "probability of claim" is wrong.
3. The gap to the oracle (0.07) comes mostly from what the scorer ignores that
   the tables use: it does not see ADL 1–5 gradations or coverage, and its age
   steps (>35/45/55/65) are coarser than the table brackets. In the neutral
   control — where only age and ADL matter — AUC falls to 0.65 because the
   condition/smoking/BMI components then add noise.
4. Fixed loading steps (15/30/50 % + condition loadings) **under-cover** the
   world's excess hazard in every priced band above `low` by 8–33 points.

### 4.2 Underwriting rules and pricing

| Metric | Deep run | Neutral control |
|---|---|---|
| Expected year-1 loss ratio, PHINS tables | 51.1 % | 51.1 % |
| Expected year-1 loss ratio, world hazards | **75.5 %** | 51.1 % |
| Loss ratio — current smokers | 124.3 % | 50.2 % |
| Loss ratio — former smokers | 83.5 % | 50.5 % |
| Loss ratio — never smokers | 64.8 % | 51.4 % |
| Declined (ADL ≥ 9) | 0.0 % | 0.0 % |
| Coverage capped / disability excluded | 0.08 % / 0.21 % | same |
| Reinsurance band (world LR) | high | medium |

Auto-approval gates (evaluated *as if enabled*; live flag is `False`):
32.9 % of applicants pass every gate; their mean annual hazard is 0.28 % vs
0.91 % for the manual queue — the gates select well on average. But 7 lives
(107 in the neutral control) that pass all gates sit in the **top hazard
decile**: mean age 52–53, ADL ≤ 3, clean history. The `max_age = 60` gate
is loose relative to the table breakpoint at 50 (mortality 2.5 → 5.0/1000).

Decline-threshold sensitivity (8 / 9 / 10) changes the declined share by
≤ 0.2 % and the portfolio loss ratio by ≤ 0.01 points: for an adult
applicant population the ADL ≥ 9 rule is essentially inactive, because the
simulator's ADL weights give ADL 9–10 zero mass. The rule protects against a
population that the demographic model never generates.

Key structural finding: **the scorer penalises smoking (+0.25) but pricing
does not** (`smoker_mortality_factor = 1.0`). If smokers carry any excess
mortality at all, PHINS's price is systematically below cost for 15 % of
the book while the underwriting decision already knows they are riskier.

### 4.3 Actuarial metrics

Three different "loss ratios" coexist in the platform and the evaluation
makes them explicit:

| Definition | Where | Value (deep run) |
|---|---|---|
| Paid claims / premium (year-1 expected, tables) | `kpi_definitions.loss_ratio_pct` basis | 51.1 % |
| PV claims / term ÷ premium | `PortfolioSimulator` | 78.7 % (= 1 / (1.15 × 1.10), the loadings) |
| Fixed assumption | `reserves_reporting_service` | 65 % |

Stochastic results:

| Metric | Deep (20k lives) | Neutral (20k) | Small (2k lives) |
|---|---|---|---|
| Year-1 LR mean ± sd | 74.7 ± 12.1 % | 51.4 ± 10.1 % | 76.7 ± 38.8 % |
| Year-1 LR p95 / p99 / TVaR99 | 95.4 / 103.5 / 108.1 % | 68.6 / 76.7 / 82.9 % | 147.8 / 181.2 / 200.0 % |
| P(year-1 LR > 100 %) | 2.4 % | 0.0 % | **25.1 %** |
| P(year-1 LR > 65 % assumption) | 79.0 % | 9.0 % | 57.4 % |
| 5-yr cumulative LR p05–p95 | 65.4–83.8 % | 42.7–58.6 % | 46.6–104.8 % |
| PHINS reserve rule (1.5 × PV of expected claims over full term) covers year-1 claims | 100 % | 100 % | 100 % |
| Year-1 volatility stress: 1.5 × *annual* expected claims covers year-1 claims (`year1_claims_stress`, not a PHINS rule) | 100 % | 100 % | **85.0 %** |
| Year-1 claims VaR99 as multiple of annual expected claims | 1.31× | 0.97× | **2.28×** |
| Unreported share of year-1 claims (mean / p95) | 12.5 % / 22.1 % | 12.3 % / 24.6 % | 12.4 % / 45.9 % |
| `ReserveConfig` IBNR 10 % sufficient | 35.6 % | 41.5 % | 60.8 % |
| `reserves_reporting` 9.75 %-of-premium sufficient | 58.6 % | 83.4 % | 66.2 % |
| Anti-selective lapse drift, 5-yr cumulative LR | +0.34 pts | +0.14 pts | +0.31 pts |
| Year-1 reinsurance band mix | 51 % medium, 43 % high, 5 % very_high | 71 % medium, 27 % low | 29 % very_high |

> **Correction (engine `mc-eval-1.0.1`).** Engine 1.0.0 reported the
> year-1 stress row as "the 150 % reserve rule". PHINS's `PortfolioSimulator`
> actually sets `reserve_requirement = total_expected_claims × 1.5` where
> `total_expected_claims` is the PV over the full term (`avg_term` times the
> annual figure), and that rule covers year-1 claims in every trial at every
> size tested. Since 1.0.1 the report carries both: `reserve_rule_150pct`
> (`basis: pv_full_term_x1.5`, mirrors PHINS) and `year1_claims_stress`
> (annual-basis volatility diagnostic). See
> `docs/monte_carlo_remediation_assessment.md`, item A.

What this says:

1. The **year-1 volatility stress is a portfolio-size statement**. At 20k
   lives 1.5 × annual expected claims covers 99 % of years (VaR99 1.31×); at
   2k lives it fails in 15 % of years and VaR99 is 2.28×. Claims volatility
   scales ~1/√n. PHINS's full-term reserve is not at risk from this, but the
   figure shown on dashboards must say what it is (a 1.5 × full-term PV, not
   150 % of a year's claims) so that year-1 volatility is not read off it.
2. Both IBNR rules are **below the lag-implied need** under a 45-day mean
   reporting lag (≈12.5 % of claims unreported at year-end), and they
   disagree with each other by construction (one is % of claims, one is % of
   premium × an assumed 65 % LR).
3. Under world hazards the platform's 65 % loss-ratio assumption is exceeded
   in 79 % of years; under neutral hazards it is exceeded in 9 %. The
   assumption is neither the table basis (51 %) nor the loading basis (79 %).
4. Anti-selective lapse is a second-order effect here (< 0.4 pts) because the
   lapse table is low (8 % → 1 %); it matters more if lapses rise.

### 4.4 Claims triage (`ClaimsBotService`)

Live thresholds (approve_full ≥ 0.85, approve_partial ≥ 0.70, deny < 0.45),
20 000 simulated claims, 5 % fraud, authenticity AUC 0.978:

| Metric | Value |
|---|---|
| Decision mix | 6.6 % full, 71.6 % partial, 16.0 % pending, 3.7 % investigation, 0.3 % medical review, 1.8 % deny |
| Fraud leakage (paid) | 1.8 % of fraudulent claims, 1.7 % of fraudulent $ |
| Legitimate false denial | 0.63 % |
| Legitimate friction (manual) | 16.9 % |
| Denial precision | 66.7 % |
| Manual share vs `AutomationMetrics` (45 %) | 20.0 % (−25 pts) |
| Mirror agreement with live recommender | 100 % |

Threshold sweep (approve_full held ≥ 0.85):

| approve_partial | Fraud leakage | Legit friction | Manual share |
|---|---|---|---|
| 0.65 | 7.0 % | 7.4 % | 11 % |
| **0.70 (live)** | **1.8 %** | **16.9 %** | **20 %** |
| 0.75 | 0.4 % | 39.0 % | 41 % |
| 0.80 | 0.1 % | 70.5 % | 71 % |

Changing `deny` between 0.40 and 0.50 moves legitimate false denials from
0.5 % to 0.95 % and leaves leakage unchanged.

What this says: `approve_full` is **inert for fraud leakage** — every
non-critical claim at ≥ 0.70 is paid (fully or partially); the
partial-approval cut-off is the real lever, and it trades leakage against
friction steeply (0.70 → 0.75 cuts leakage 4.5× but more than doubles manual
work). The 0.85/0.70/0.45 constants have never been fitted to outcomes.

### 4.5 Sales assumptions (`predict_revenue_forecast`)

The BI forecast compounds 5 %/month with no churn: ×1.80 at 12 months
(**≈ 80 %/year**), while other surfaces quote 3/5/8 % *annual* growth
scenarios. Under the world (same 5 % mean, σ 4 %, mild shocks, churn from the
year-1 lapse table = 0.69 %/month):

| Month | Deterministic ×MRR | MC p05 / p50 / p95 | P(meets forecast) | P(below start) | Mean shortfall |
|---|---|---|---|---|---|
| 3 | 1.158 | 0.95 / 1.12 / 1.28 | 35.9 % | 12.3 % | 3.3 % |
| 6 | 1.340 | 0.98 / 1.26 / 1.56 | 32.3 % | 6.4 % | 6.0 % |
| 12 | 1.796 | 1.08 / 1.56 / 2.14 | **25.1 %** | 2.3 % | 11.7 % |

The deterministic path is roughly the p75 of the distribution: a point
forecast that ignores churn and volatility is met one year in four.

### 4.6 AI usage thresholds

`review_disposition` at accept ≥ 0.90 / review ≥ 0.70 with 85 % model
accuracy:

| Accept threshold | Accepted | Error rate among accepted | Errors routed to humans | Human load | Cost units / 1000 (50 : 1) |
|---|---|---|---|---|---|
| 0.70 | 66.8 % | 5.6 % | 75 % | 33 % | 2 197 |
| 0.80 | 43.6 % | 3.3 % | 90 % | 56 % | 1 289 |
| 0.85 | 29.6 % | 2.2 % | 96 % | 70 % | 1 031 |
| **0.90 (live)** | **15.9 %** | **1.4 %** | **98.6 %** | **84 %** | **951** |
| 0.95 | 4.8 % | 0.5 % | 99.8 % | 95 % | 964 |

At a 50 : 1 error-to-review cost ratio the live 0.90 is the cost minimum; the
optimum moves to 0.85 at ~20 : 1 and to 0.80 at ~10 : 1. The
`_MAX_ADVISORY_CONFIDENCE = 0.4` cap routes **100 %** of advisory LLM output
to `needs_review`, so the accept/review thresholds are currently inert for
that surface — appropriate until accepted-error telemetry exists.

AI underwriting gates (approve ≥ 0.85, reject ≤ 0.15, 15 % bad applicants):
23.6 % auto-approved with 0.13 % of bad applicants slipping through, 3.4 %
auto-rejected with 0.01 % of good applicants wrongly rejected, 73 % manual.
The gates are safe and conservative; the cost is manual load.

## 5. Recommendations

### 5.1 Methodology and assumptions

1. **Align pricing and underwriting on smoking.** Set
   `smoker_mortality_factor` / `smoker_disability_factor` (and former-smoker
   factors) from experience or a published table instead of 1.0. Today the
   scorer charges for smoking and the kernel does not.
2. **Label the reserve basis and publish year-1 volatility next to it.**
   `reserve_requirement` is 1.5 × PV of expected claims over the full term
   (`risk_metrics.reserve_requirement_basis`); show year-1 VaR99/TVaR99 from
   `year1_claims_stress` beside it so claim-count volatility at the current
   portfolio size is visible without misreading the full-term figure.
3. **Unify IBNR.** One lag-based estimate (fit reporting lag from
   `filed_date − incident_date` on real claims) feeding both `ReserveConfig`
   and `reserves_reporting_service`; retire the 10 %-of-claims vs
   9.75 %-of-premium pair.
4. **Name the loss ratios.** Publish `loss_ratio_year1_tables`,
   `loss_ratio_lifetime_pv` and `loss_ratio_assumption` as separate KPIs in
   `kpi_definitions`; stop letting 51 %, 65 % and 79 % all be "the loss
   ratio".
5. **Make the scorer table-aware.** Add a component derived from the
   age/ADL table hazard (or reuse the kernel's expected loss) so the scorer's
   ranking cannot fall below what pricing already knows; keep the additive
   experience factors on top.
6. **Calibrate loadings by band.** Replace fixed 15/30/50 % steps with
   band-level observed excess (the `required_loading_vs_tables` column),
   reviewed against real claim experience once it exists.
7. **Tighten auto-approval before enabling it.** Lower `max_age` toward the
   table breakpoint (50) or add a table-hazard gate; gate on BMI and prior
   claims, which are scored but not gated.
8. **Treat `approve_partial` as the claims lever.** Sweep it against
   observed override/fraud outcomes; `approve_full` and `deny` are
   second-order.
9. **Model churn in the revenue forecast** from the lapse table and return
   p10/p50/p90 bands; reconcile the 5 %/month default with the 3/5/8 % annual
   scenarios used elsewhere.
10. **Retire fixed automation base rates.** `AutomationMetrics.BASE_RATES`
    (45 % UW auto-approve, 45 % claims manual) disagree with the rules'
    actual decision mix (19 % / 20 %); compute them from decisions.

### 5.2 BI usage

- Run the evaluation on the BI snapshot cadence (`entrypoint.sh bi-snapshot`
  is the natural neighbour) and persist `auc`, `year1_loss_ratio_pct.p95`,
  `multiple_needed_for_99pct_coverage`, `fraud_leakage_rate` and
  `probability_meets_deterministic` as trend metrics — the point estimates
  alone hide the risk.
- Show the score as a **band with an observed rate and CI** (the
  `calibration_by_band` table), never as a probability.
- Show table-basis and experience-adjusted loss ratios side by side, and the
  reinsurance band as a *distribution* (51 % medium / 43 % high / 5 %
  very_high), not a label.
- Every published number should carry `results_sha256`,
  `phins_assumptions_sha256` and `world_assumptions_sha256` so an investor or
  regulator can reproduce it.

### 5.3 AI usage

- Keep the advisory confidence cap until `ai_usage_service` meters
  *accepted-error rate*; then set accept/review thresholds from an explicit
  error : review cost ratio and store the ratio next to the thresholds.
- Feed human override pairs into `ai_threshold_config.calibrate_thresholds`
  (≥ 20 samples per segment) and re-run this evaluation with the recommended
  thresholds as `world.*` overrides before promoting them.
- Use the LLM to *explain* the findings table (it is already structured with
  `statement`, `metric`, `recommendation`), not to choose thresholds — in
  line with `docs/ai_surface_design_principles.md`.

### 5.4 BI conclusions and admin next moves (in the report)

Each report now carries two derived blocks so the dashboard does not have to
interpret raw findings:

- `conclusions` — `overall_status` (`consistent`, `inconsistencies_detected`,
  `anomalies_detected`), a headline, counts, one row per evaluated area with a
  status chip, a one-sentence `bi_conclusion`, the BI snapshot metrics that
  area should persist, and short `bi_usage` / `ai_usage` guidance lists.
  An *anomaly* is PHINS disagreeing with itself (pricing factors neutral while
  the scorer penalises smoking; the live automation-metrics KPI still
  labelling its mix `assumed` although ≥ 30 decided claims are on record; the
  evaluation mirror disagreeing with the live recommender; observed inputs
  mutating during a run). An *inconsistency* is a PHINS assumption
  disagreeing with the simulated world (reserve coverage, IBNR sufficiency,
  the configured loss-ratio assumption, sales attainment, AI cost-minimum
  threshold, claims leakage, band loadings below the world excess hazard,
  assumed automation mix vs the simulated mix while observed data is still
  insufficient).

  **Verdicts follow the remediated source (engine `mc-eval-1.0.2`).** The
  engine's own advice must be able to clear its own verdict, otherwise the
  report keeps flagging what was already fixed:

  - *Year-1 vs lifetime loss ratio.* 1.0.1 raised a P1 anomaly asking to
    "label both bases explicitly". Since remediation item B/C
    `PortfolioSimulator.risk_metrics` carries `loss_ratio_basis`,
    `loss_ratio_year1_basis` and `reserve_requirement_basis`; the engine reads
    those labels (`phins_assumptions.loss_ratio_bases.labelled_at_source`) and
    reports the 33.7 % vs 72.5 % gap as a P3 `monitor` move
    (`act_method_bases_labelled`): two labelled quantities that differ by the
    ageing of the book inside the term. The anomaly (`act_method_disagreement`)
    only returns if the labels disappear from source.
  - *IBNR probability of sufficiency.* The p75 unreported share is proposed as
    the provision (best estimate + prudence margin), so the verdict is judged
    at the same 75 % probability-of-sufficiency target
    (`IBNR_PROBABILITY_OF_SUFFICIENCY_TARGET`), not at an unreachable 90 %.
    The trial frequency is compared with the target through its Wilson 95 %
    interval (`probability_reserve_config_ibnr_sufficient_ci95`,
    `reserve_config_ibnr_meets_target`): 74.7 % of 300 trials is
    indistinguishable from 75 % and passes; 57 % fails and proposes p75.
  - *Claims automation mix.* Simulated vs assumed is an assumption gap
    (`inconsistency`, P2) until PHINS has ≥ 30 decided claims; once it has,
    the move is `monitor` if `GET /api/actuarial/automation-metrics` already
    labels the mix `observed` (item J) and an `anomaly` only if the live KPI
    ignores that data. The evidence carries the label the endpoint would
    show, computed by the same call.
  - *Sales growth basis.* `predict_revenue_forecast` derives its rate from
    observed policy history when ≥ 6 complete months exist (item F), so the
    module evaluates whichever basis the live endpoint uses and says which
    (`phins_forecast.growth_basis`: `observed_policy_history` or
    `legacy_default`, with `observed_growth` and the attainment of the legacy
    5 %/month line under the evaluated drift).
  - *Band loadings.* The risk warning "applied loadings under-cover the world
    excess hazard" now has a matching P2 `investigate` move
    (`risk_band_loadings`) so the risk area's `inconsistent` status is never
    left without a next move; it proposes nothing to apply because the
    "required" figure comes from the simulated world.
  - Conclusions quote the live loss-ratio assumption and one decimal (99.7 %
    is not "100 %"); AI accepted-error figures are marked counterfactual while
    the 0.4 advisory cap forces full human review.
- `next_moves` — deterministic, priority-sorted advisories. Every move names
  its `source_ref` (the code that owns the assumption) and an `action.kind`:
  `adjust` when PHINS exposes an audited config path, `redirect` when the
  value is a per-run input or a code constant, `investigate` for anomalies,
  `monitor` when the evidence supports the current rule.

The advisories are rule-based on purpose. An LLM narrative would be
non-deterministic, break the hash seal, and add no evidence; PHINS's existing
"AI insights" (balance-sheet) follow the same rule-based pattern.

**Apply contract (data integrity).** Only `adjust` moves can be applied, and
only through `POST /api/actuarial/config`, the existing audited, versioned
underwriting/pricing endpoint (`ActuarialTablesStore.update_config` writes an
audit entry and an append-only `config_history` revision, so every change is
restorable from the Actuary dashboard versions bar). The proposal carries the
`current` live values it was derived from; the admin UI

1. shows a confirmation with current → proposed values,
2. re-reads `GET /api/actuarial/config` and aborts if any `current` value
   drifted since the evaluation ("configuration drifted"),
3. posts the payload with `change_reason` = engine version + `results_sha256`
   + move id, which `update_config` stores in the audit entry,
4. verifies the read-back equals the proposal and offers a re-run.

The engine itself never writes (`integrity.proposals_applied_by_engine` is
always `false`; `next_moves_sha256` seals the advisories). Everything not
reachable through that endpoint — the 150% reserve constant, claims-bot
cut-offs, AI env-var thresholds, IBNR on the reserve projection form, the
revenue-forecast growth parameter — is a `redirect` with a proposed value and
a deep link (`/actuary-dashboard.html#section-reserves`, etc.); the admin
changes it at source.

## 6. Limitations

- The world is a model. Relative risks, condition prevalence, fraud
  separability and growth volatility are assumptions; the neutral control
  shows which findings survive when they are switched off (reserve scaling,
  IBNR lag, scorer-vs-table ranking, forecast optimism, claims lever) and
  which depend on them (smoker mispricing magnitude, loading gaps).
- Multi-year paths keep cell hazards fixed at issue age and treat disability
  claimants as exits; both understate later-year loss ratios slightly.
- Fraud is simulated through the recommender's *inputs* (component scores,
  indicators, hidden conditions), not through document analysis, so AUC 0.978
  measures the decision logic, not detection quality.
- Pure-Python Monte Carlo: 20 000 lives × 2 000 trials × 2 scenarios runs in
  ≈21 s; larger runs should use the CLI, not the HTTP route.

## 7. How to run

```bash
# API (admin / accountant / underwriter session)
GET /api/bi/monte-carlo-evaluation?seed=20260911&lives=2000&trials=400
GET /api/bi/monte-carlo-evaluation?modules=actuarial,claims&world.fraud_rate=0.08

# CLI
python3 scripts/run_monte_carlo_evaluation.py --lives 20000 --trials 2000 --summary
python3 scripts/run_monte_carlo_evaluation.py --world smoker_mortality_rr=1.5 --out /tmp/mc.json

# Tests
pytest tests/test_monte_carlo_evaluation.py -q
```

Response shape: `engine_version`, `parameters`, `world_assumptions`,
`phins_assumptions`, `assumption_provenance`, `observed_inputs`, `results`
(one key per module), `findings` (area / severity / statement / metric /
recommendation), `conclusions`, `next_moves` (§5.4) and `integrity` (hashes,
`read_only`, `side_effects: []`, `observed_inputs_unchanged`,
`proposals_applied_by_engine: false`).

Dashboard: Admin → Admin AI Mic → **Monte Carlo Eval** (or say/type "run
monte carlo evaluation"). The panel renders the metric cards, BI conclusions,
the next-move cards with **Review & apply fix** / **Open source** buttons, and
the findings list.

### 7.1 Companion read-only reports (remediation items D, E, J, K)

These exist so that an advisory can be checked against PHINS's own
experience before anything is applied. None of them writes; each states the
audited path that would change the underlying value and refuses to propose
below its minimum sample.

| Report | Route (roles) | What it reads | Proposes when |
|---|---|---|---|
| Observed claims reporting lag → implied IBNR share | `GET /api/actuarial/claims-lag` (admin, actuary, accountant) | claims with incident and reported dates | ≥ 30 claims with both dates |
| Loss ratio by smoking cohort | `GET /api/bi/loss-ratio-by-smoking[?min_lives=30]` (admin, accountant, underwriter) | active policies, incurred claims, customer / application smoking status | ≥ 30 active lives in both smoker and nonsmoker cohorts |
| Observed automation mix | `GET /api/actuarial/automation-metrics` (admin, actuary) — `metrics.<process>.source` is `observed` or `assumed` | decided underwriting applications, claims, bills | ≥ 30 decided records per process |
| Claims-bot threshold calibration | `GET /api/claims/bot-threshold-calibration` (admin, claims_adjuster, actuary) | `claims_fraud` assessment records with reviewer decisions | ≥ 30 labelled (approved/rejected) decisions |
| Revenue forecast basis | `GET /api/bi/revenue-forecast` without `growth_rate` — `forecast_basis.growth_rate_source` | policy start dates, lapse table year 1 | ≥ 6 complete months of policy history (else labelled default) |

Reserving assumptions are now audited config fields on `UnderwritingConfig`
(`ibnr_pct` 0.10, `ibnr_reporting_factor` 0.15, `loss_ratio_assumption`
0.65), changed only via `POST /api/actuarial/config` with a `change_reason`,
versioned in `config_history` and restorable from the Actuary versions bar.
Defaults equal the previous hard-coded constants, so no figure moves until an
actuary saves a new assumption. The engine's `act_ibnr_pct` and
`act_lr_assumption` advisories are therefore guarded **adjust** moves, and the
`uw_smoker_demographic_factors` proposal scales by PHINS's observed
smoker/nonsmoker loss-ratio ratio whenever the smoking slice is sufficient
(`evidence.ratio_basis` = `observed_experience`), otherwise by the simulated
world and says so.
