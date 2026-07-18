# PHINS — Regulatory Application Memorandum (Israel)

**To:** The Commissioner of the Capital Market, Insurance and Savings Authority (רשות שוק ההון, ביטוח וחיסכון), Jerusalem
**Re:** Application framework for approval of a new insurance plan under Section 40 of the Supervision of Financial Services (Insurance) Law, 5741-1981 — **PHINS Adjustable Risk Contract: Life Insurance with a Permanent-Disability Mechanism (contract ratio 1:4)**
**Version:** Draft 2.0 (supersedes Draft 1.0, which was framed around a stand-alone LTC product)
**Status:** Regulatory positioning and actuarial filing base. This memorandum is a drafting framework, not a substitute for formal legal advice or a pre-ruling from the Authority.

---

## 1. Executive Regulatory Position

PHINS applies for approval of a single life-insurance plan — the **PHINS Adjustable Risk Contract** — that bundles two benefits in one policy:

1. **Mortality benefit.** On death of the insured at any age, the policy pays the contracted sum insured **L** (100% of the life sum), as a lump sum.
2. **Permanent-disability benefit.** On the first occurrence of a permanent long-term-care-grade disability — inability to perform at least **3 Activities of Daily Living (3+ ADL)** or an equivalent cognitive impairment (תשישות נפש) — the policy pays a lump sum of **D = L ÷ 4** (the contract ratio of disability sum to life sum is **1 : 4**). The disability layer attaches from age 3 and **terminates automatically at age 65**; the life layer continues for life.

The plan is a **pure-risk product**: no savings component, no cash value, no surrender value, no dividend, and no investment component. An optional savings add-on exists in the PHINS platform as a separately administered deposit product and is **excluded from this filing**; if offered in Israel it will be filed separately through a properly licensed entity (Section 9.2).

Unlike the framework addressed by the Authority's consolidated circular, Gate 6, Part 3 (group LTC insurance for health-fund members, as amended December 2023), this plan is an **individual life-insurance policy with a disability mechanism**, not a health-fund group LTC scheme. The circular is used in this filing only as a **regulatory benchmark** for LTC-grade trigger definitions, functional-assessment standards, and morbidity reasonableness (Section 5.6). PHINS notes that the December 2023 amendment removed the fixed 20%-minimum insurer risk-retention requirement in the basic health-fund layer; PHINS does not assume that flexibility extends automatically to individual products and does not rely on it.

**Licensing position.** PHINS Technologies Ltd. is not a licensed insurer and will not describe itself as one. The insurance risk shall be carried by a licensed Israeli insurer (fronting structure) and/or an approved reinsurance structure. PHINS acts as the technology, underwriting-workflow, policy-administration, claims-workflow and distribution platform, subject to applicable licensing (Section 6).

## 2. Product Definition and Classification

### 2.1 Product identity

| Item | Value |
|---|---|
| Commercial name | PHINS Adjustable Risk Contract |
| Hebrew working name | פינס — ביטוח חיים משולב פיצוי נכות תפקודית קבועה |
| Legal classification | Life insurance (ביטוח חיים) with a permanent-disability benefit mechanism |
| Benefit form | Fixed indemnity, lump sum; independent of actual care expenses |
| Life benefit | L (100% of sum insured), death at any age from entry |
| Disability benefit | D = L ÷ 4 (contract ratio 1:4), single payment on first qualifying event |
| Disability trigger | Permanent 3+ ADL dependency or equivalent cognitive impairment |
| Disability cover window | Entry age 3 through age 65 (automatic termination at 65) |
| Entry ages | 3–65 (disability layer); life layer continues beyond 65 |
| Premium | Age-related adjustable risk premium, re-priced at each policy anniversary on a published age curve |
| Savings / investment | None. Pure risk. |
| Claim interaction | Mutually exclusive: one major claim per policy lifetime (Section 5.4) |

### 2.2 Benefit interaction (claims model)

The contract prices and administers mortality and disability as **mutually exclusive** claims: a policyholder can claim either the mortality benefit or the disability benefit within a given policy lifetime, never both. Payment of the disability lump sum D does not terminate the mortality cover; the policy converts to the life-only layer and continues to pay L on subsequent death, priced accordingly in the actuarial basis (the mutually-exclusive present-value model in Section 5.4 is the binding pricing method; the policy wording will state the post-claim status explicitly).

### 2.3 What the product is not

The product shall not be marketed as a savings product, investment product, bank deposit, provident or pension product. Marketing materials will carry an explicit statement that the policy accrues **no cash or surrender value**.

## 3. Regulatory Definitions Adopted

PHINS mirrors the Authority's LTC vocabulary to avoid ambiguity.

### 3.1 Insured event (disability layer)

> "An insured event shall occur where the insured, due to illness, accident, or deterioration of health, is determined to be in a permanent long-term-care condition, based on inability to perform independently and permanently at least three (3) of the six (6) Activities of Daily Living defined in the policy, or due to cognitive impairment / mental frailty (תשישות נפש) requiring substantial supervision — all as defined in the policy and subject to applicable law and the Commissioner's instructions."

### 3.2 ADL list

The six contractual ADL activities follow the standard Israeli LTC definitions: (1) getting up and lying down; (2) dressing and undressing; (3) bathing; (4) eating and drinking; (5) continence control; (6) mobility. The policy avoids non-objective wording such as "difficulty functioning"; every trigger determination is tied to the functional-assessment standard below. For internal severity grading, underwriting and claims administration use a 10-point ADL severity scale (Section 5.3); **the contractual trigger remains 3+ of the 6 defined ADL activities, permanent**.

### 3.3 Functional assessment

> "Functional assessment shall be conducted by a licensed physician, registered nurse, or other professional approved under the claims protocol, trained in LTC assessment and independent from the sales process. The insurer retains the right to an independent assessment; the insured retains the right to submit additional medical evidence."

## 4. Product Structure Submitted for Approval

| Component | Filed structure |
|---|---|
| Trigger — life | Death of the insured, any cause, subject to policy exclusions |
| Trigger — disability | Permanent 3+ ADL / cognitive equivalent, confirmed by medical and functional assessment |
| Benefit type | Lump sum: L on death; L ÷ 4 on qualifying disability |
| Waiting period (disability) | 60–90 days from event, per actuarial filing; no waiting period on death benefit |
| Entry age | 3–65 (disability layer); life layer lifelong |
| Maximum liability | L + no more than one disability payment of L ÷ 4 per policy lifetime |
| Premium | Adjustable, age-banded, unisex or gender-based per final filing; re-priced annually on the published age curve (Section 5.2) |
| Underwriting | Simplified issue with ADL-severity scoring 1–10; declines at severity ≥ 9; loadings per Section 5.7 |
| Claims assessment | Medical documentation + independent functional assessment |
| Policyholder rights | Underwriting transparency, coverage continuity, published re-pricing, 30-day cooling-off, tamper-evident audit trail |

## 5. Actuarial Basis (Filed Tables)

All tables below are the canonical PHINS actuarial tables (central tables version V2.0) applied by a single deterministic pricing kernel. Every premium quoted in marketing, application, billing, and reserving derives from the same kernel and carries a reproducible integrity hash; there is no parallel calculation path.

### 5.1 Base rates

| Layer | Base rate (per 1,000 sum insured, monthly) |
|---|---|
| Life (sum L) | 0.25 |
| Disability (sum D = L ÷ 4) | 0.20 |

Monthly gross premium at attained age x:

```
Premium(x) = (L / 1,000) × 0.25 × f(x)  +  (D / 1,000) × 0.20 × f(x)      for x < 65
Premium(x) = (L / 1,000) × 0.25 × f(x)                                    for x ≥ 65
```

where f(x) is the published age-factor curve in Section 5.2. Because D = L ÷ 4, the combined pre-65 rate equals 0.30 per 1,000 of L per month.

### 5.2 Age-factor curve f(x) — published re-pricing curve

| Age segment | Rule | Anchor values |
|---|---|---|
| 3 → 25 | Linear from 0.30 to 1.00 | f(3) = 0.30; f(25) = 1.00 |
| 25 → 65 | +0.015 per year of age | f(35) = 1.15; f(45) = 1.30; f(55) = 1.45; f(65) = 1.60 |
| 65 → 75 | +0.05 per year (life-only layer) | f(70) = 1.85; f(75) = 2.10 |
| 75 → 80 (cap) | +0.08 per year (life-only layer) | f(80) = 2.50 |

Every premium step is published in advance and tied solely to attained age — never to the individual's claims history.

### 5.3 Mortality and disability-incidence tables (per 1,000 lives per year)

| Age band | Mortality q(x) per 1,000 | Disability incidence i(x) per 1,000 |
|---|---|---|
| 0–29 | 0.5 | 2.0 |
| 30–39 | 1.2 | 4.0 |
| 40–49 | 2.5 | 8.0 |
| 50–59 | 5.0 | 15.0 |
| 60–69 | 12.0 | 30.0 |
| 70–79 | 30.0 | 50.0 |
| 80+ | 75.0 | 80.0 |

Underwriting-severity multipliers applied to the table rates by the applicant's ADL severity score (1 = fully independent, 10 = fully dependent):

| ADL severity | Mortality multiplier | Disability-incidence multiplier |
|---|---|---|
| 1 | 0.80 | 0.30 |
| 2 | 0.85 | 0.50 |
| 3 | 0.90 | 0.70 |
| 4 | 0.95 | 0.90 |
| 5 | 1.00 | 1.00 |
| 6 | 1.10 | 1.50 |
| 7 | 1.20 | 2.00 |
| 8 | 1.35 | 3.00 |
| 9 | 1.50 | 5.00 |
| 10 | 1.80 | 8.00 |

On a qualifying claim the contract pays the **full** disability sum D = L ÷ 4 (benefit percentage fixed at 100% of D once the permanent 3+ ADL trigger fires). There is no fractional or graded scoring of the paid benefit — this removes the "hidden quantitative manipulation" risk flagged in consumer-protection guidance.

### 5.4 Claim-interaction model (present value of claims)

For each policy year t at attained age x:

```
PV_mortality   = Σ  L × P(alive, not disabled at t−1) × q(x+t−1) × v^t
PV_disability  = Σ  D × P(alive, not disabled at t−1) × (1 − q) × i(x+t−1) × v^t   (t while age < 65)
Risk premium   = (PV_mortality + PV_disability) / term
```

with discount factor v = 1 / (1 + 3.5%). Mortality and disability are mutually exclusive per lifetime — the survivorship state "alive and not disabled" is depleted by both decrements.

### 5.5 Lapse assumptions

| Policy year | Annual lapse rate |
|---|---|
| 1 | 8% |
| 2 | 5% |
| 3 | 4% |
| 4–10 | 3% |
| 11–25 | 2% |
| 26+ | 1% |

### 5.6 Loadings, margins and benchmark deviation

| Parameter | Filed value |
|---|---|
| Expense loading | 15% of risk premium |
| Profit margin | 10% of (risk premium + expense) |
| Discount rate | 3.5% |
| Reinsurance | Quota-share / surplus treaty per Section 10; treaty terms filed separately |

> **Benchmark statement.** The PHINS pricing basis uses the Authority's published LTC experience tables (annual LTC entry rates by age group and sex, as annexed to the consolidated circular, Gate 6, Part 3, December 2023 amendment) as a regulatory benchmark and minimum-reasonableness reference for the disability layer. Those tables were constructed for the extended LTC layer of health-fund group insurance; PHINS does not copy them as a pricing table. Any deviation of the filed incidence basis in Section 5.3 from the Authority's benchmark shall be documented, actuarially justified by the appointed actuary, and submitted for prior approval where required.

### 5.7 Underwriting rules (filed)

| ADL severity at issue | Decision | Premium loading | Coverage cap |
|---|---|---|---|
| 1–5 | Standard | — | Per plan schedule |
| 6 | Accept with loading | +15% | 1,000,000 |
| 7 | Accept with loading | +30% | 750,000 |
| 8 | Accept with loading; disability layer excluded | +50% | 500,000 |
| 9–10 | Decline | — | — |

### 5.8 Specimen premium schedule (reference policyholder)

Reference case: L = 500,000; D = L ÷ 4 = 125,000. Monthly premium = 150 × f(x) up to age 64 (combined), 125 × f(x) from 65 (life-only). Amounts in policy currency (₪ specimen).

| Attained age | f(x) | Life premium / month | Disability premium / month | Total / month |
|---|---|---|---|---|
| 3 | 0.30 | 37.50 | 7.50 | 45.00 |
| 25 | 1.00 | 125.00 | 25.00 | 150.00 |
| 35 | 1.15 | 143.75 | 28.75 | 172.50 |
| 45 | 1.30 | 162.50 | 32.50 | 195.00 |
| 55 | 1.45 | 181.25 | 36.25 | 217.50 |
| 64 | 1.585 | 198.13 | 39.62 | 237.75 |
| 65 | 1.60 | 200.00 | — (layer terminated) | 200.00 |
| 70 | 1.85 | 231.25 | — | 231.25 |
| 75 | 2.10 | 262.50 | — | 262.50 |
| 80 | 2.50 | 312.50 | — | 312.50 |

### 5.9 Actuarial filing package

The Section 40 filing shall include: product pricing report signed by the appointed actuary; morbidity and mortality assumptions by age (and sex where used); claim-termination and expected-claim-duration assumptions; IBNR methodology; lapse assumptions (Section 5.5); expense and commission loadings; reinsurance structure and solvency capital impact; sensitivity scenarios (base / adverse / severe adverse); profitability and loss-ratio projections; the consumer premium table by age and benefit amount; and an explanation of any deviation from the Authority's published LTC benchmark assumptions (Section 5.6).

## 6. Approval Path and Licensing Boundaries

PHINS shall not market, sell, or collect premiums before the properly regulated entity receives the Commissioner's approval for the plan.

> "PHINS Technologies Ltd. will act as a technology, underwriting-support, claims-management, policy-administration and distribution platform, subject to applicable licensing, while the insurance risk shall be carried by a licensed Israeli insurer and/or an approved reinsurance structure, as permitted by law."

| Activity | Regulatory boundary respected |
|---|---|
| Carrying insurance risk | Licensed Israeli insurer / approved reinsurer only |
| Selling the policy | Licensed insurer / licensed agents |
| Personal insurance advice | Licensed advice / agency rules only |
| Managing investment allocation | Not offered in this product |
| Holding client funds | Insurer / licensed payment entity only |
| AI underwriting support | Human-reviewed, auditable (Section 11) |

## 7. Claims Governance

1. **Principle.** Claims are decided on objective functional criteria, medical documentation, and — where needed — independent functional assessment. The insured receives a written, reasoned decision (approval, partial approval, request for documents, or rejection) within the time limits in the claims-handling circulars.
2. **No hidden scoring.** The disability benefit is binary at the contractual trigger: once permanent 3+ ADL dependency is confirmed, the full D = L ÷ 4 is paid. Internal severity scores affect underwriting only, never the paid benefit.
3. **Appeals.** Internal appeal right; right to submit additional medical evidence; review by a senior claims officer; escalation to the insurer's ombudsman and to the Authority.
4. **Audit trail.** Every underwriting and claims decision is recorded on the platform's append-only, hash-chained ledger; AI tools recommend but never post a binding decision.

## 8. Consumer Disclosure

The pre-sale consumer summary (Hebrew, plain language) states: what is covered and what is not; the exact insured-event definitions (death; permanent 3+ ADL); the 1:4 contract ratio and worked example (L = 500,000 → D = 125,000); the waiting period; that the benefit is a lump sum; that premiums re-price annually on a published age curve; that the disability layer terminates at age 65 and the disability premium ceases then; that the policy has **no cash, surrender or savings value**; underwriting requirements; claim documents required; who carries the insurance risk; and PHINS's non-insurer platform role. Prohibited representations: "guaranteed approval", "bank-like savings", "government-approved", "covers every disability".

## 9. Adjacent Products (Out of Scope of This Filing)

### 9.1 Health-fund group LTC

This filing does not seek to operate under, or amend, the health-fund group LTC framework of Gate 6, Part 3.

### 9.2 Savings add-on

The PHINS platform supports an optional savings add-on collected as a fixed percentage of the risk premium and held in a segregated account. It is excluded from this product and filing. If offered in Israel it will be structured through a properly licensed entity with separate disclosure, separate fees, and an explicit statement that investment performance does not affect the approved insurance benefits.

## 10. Reinsurance and Risk Transfer

Filed structure: a licensed Israeli insurer fronts the policy; a reinsurance treaty covers catastrophic and accumulation risk on both the mortality and disability layers; PHINS receives technology and service fees only — no unlicensed insurance-risk compensation; any profit-sharing arrangement is submitted for review to avoid unauthorized insurance activity.

## 11. Digital and AI Governance

AI tools support onboarding, ADL-severity scoring, claims triage and customer service. Binding controls: human review of every adverse underwriting or claims decision; a written explanation capability for every decision; full audit trail of AI recommendations on the hash-chained ledger; data minimization and explicit consent for medical-data processing; cybersecurity controls; and no discrimination beyond actuarially justified classification.

## 12. Regulatory Risk Assessment

| Risk | Level | Mitigation |
|---|---|---|
| Product treated as unauthorized insurance activity | High | Fronting by licensed insurer; PHINS platform-only role |
| Disability layer construed as health/LTC class requiring separate filing | Medium–High | File as life insurance with disability mechanism; adopt LTC-grade trigger definitions; pre-ruling if required |
| Misuse of health-fund LTC benchmark tables | Medium–High | Benchmark-only use; appointed-actuary justification of deviations (Section 5.6) |
| Claims disputes over ADL determination | High | Objective 3-of-6 ADL wording; independent assessment; binary benefit |
| AI discrimination / privacy | High | Governance per Section 11; human review; audit trail |
| Misleading marketing | High | Pre-approved scripts; prohibited-representations list (Section 8) |
| Reinsurance not recognized for capital relief | Medium | Solvency review with insurer and reinsurer before filing |

## 13. Filing Package Checklist

A. Legal product memorandum (this document, finalized). B. Full policy wording in Hebrew. C. One-page consumer disclosure sheet in Hebrew. D. Actuarial pricing report per Section 5.9. E. Claims protocol (functional assessment, timelines, appeals). F. AI and digital-governance appendix. G. Distribution compliance manual. H. Reinsurance treaty summary.

## 14. Declaration

> "PHINS seeks to introduce a transparent, actuarially sound life-insurance product with a permanent-disability mechanism, paying a defined lump-sum benefit of the full sum insured L on death and one quarter of the sum insured (L ÷ 4, contract ratio 1:4) on a permanent 3+ ADL long-term-care event, determined through medical documentation and independent functional assessment. PHINS intends to operate only within the scope of applicable Israeli insurance, financial-services, privacy, anti-money-laundering, consumer-protection and digital-governance law. Insurance risk shall be carried solely by a licensed insurer and/or an approved reinsurance structure. The PHINS technology platform supports onboarding, underwriting, policy administration, claims workflow, customer service and compliance monitoring, subject to regulatory approval and appropriate licensing."

---

*Prepared on the PHINS platform. All actuarial figures in Section 5 are produced by the platform's single deterministic pricing kernel from central tables version V2.0 and reconcile to the specimen schedules published on the PHINS actuary dashboard and public risk one-pager.*
