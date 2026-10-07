# PHINS — Regulatory Application Memorandum (Israel)

**To:** The Commissioner of the Capital Market, Insurance and Savings Authority (רשות שוק ההון, ביטוח וחיסכון), Jerusalem
**Re:** Application framework for approval of a new insurance plan under Section 40 of the Supervision of Financial Services (Insurance) Law, 5741-1981 — **PHINS Adjustable Risk Contract: Life Insurance with a Lifelong Permanent-Disability Mechanism (pre-65: life = face & D = life ÷ 4; from 65: life = face ÷ 4 & D = life)**
**Version:** Draft 3.1 (supersedes Draft 3.0, in which the post-65 disability sum equalled the full face at 1:1; Draft 3.1 keeps lifelong disability but steps the life sum to face ÷ 4 from age 65 so that D = life at the reduced life sum — e.g. face ₪500,000 → life ₪125,000 and disability ₪125,000 — and retains post-claim continuation with a one-quarter cover deduction on the pre-65 face). **Pre-ruling supplement:** 12 October 2026, Section 15. Sections 1–5 are unchanged.
**Status:** Regulatory positioning and actuarial filing base. This memorandum is a drafting framework, not a substitute for formal legal advice or a pre-ruling from the Authority.

---

## 1. Executive Regulatory Position

PHINS applies for approval of a single life-insurance plan — the **PHINS Adjustable Risk Contract** — that bundles two benefits in one policy:

1. **Mortality benefit — age-banded life sum.** Let **F** be the contracted face amount at issue (maximum **₪1,000,000** below age 65). On death at attained age x the policy pays the in-force life sum **L(x)**: **L(x) = F** below age 65; **L(x) = F ÷ 4** from age 65 (subject to the post-claim deduction in item 3), as a lump sum.
2. **Permanent-disability benefit — lifelong, age-banded ratio.** On the first occurrence of a permanent long-term-care-grade disability — inability to perform at least **3 Activities of Daily Living (3+ ADL)** or an equivalent cognitive impairment (תשישות נפש) — the policy pays a lump sum of **D(x)** at the attained age of the insured event: **D(x) = L(x) ÷ 4 = F ÷ 4** below age 65 (contract ratio **1 : 4**, capped at **₪250,000**); **D(x) = L(x) = F ÷ 4** from age 65 (contract ratio **1 : 1** at the stepped-down life sum). Worked example on F = ₪500,000: below 65 → life ₪500,000 / disability ₪125,000; from 65 → life ₪125,000 / disability ₪125,000. The disability layer attaches from age 3 and **does not terminate at age 65**: it continues for insureds aged 65+ for as long as premiums are paid, with a separately identified premium charged for each risk (Section 5.1).
3. **Post-claim continuation with cover deduction.** Payment of the disability benefit does not terminate the policy. Where disability occurs before death, the policy **may continue**: below age 65 the life sum is reduced by **one quarter of face** — L′ = 0.75 × F — from the first premium due date following the disability payment; from age 65 the then-current stepped-down life sum L(x) = F ÷ 4 continues (life risk only). The disability layer terminates upon its single payment. Below age 65 the disability benefit (F ÷ 4) therefore operates as an acceleration of one quarter of face, so the lifetime aggregate below 65 never exceeds F.

The plan is a **pure-risk product**: no savings component, no cash value, no surrender value, no dividend, and no investment component. An optional savings add-on exists in the PHINS platform as a separately administered deposit product and is **excluded from this filing**; if offered in Israel it will be filed separately through a properly licensed entity (Section 9.2).

Unlike the framework addressed by the Authority's consolidated circular, Gate 6, Part 3 (group LTC insurance for health-fund members, as amended December 2023), this plan is an **individual life-insurance policy with a disability mechanism**, not a health-fund group LTC scheme. The circular is used in this filing only as a **regulatory benchmark** for LTC-grade trigger definitions, functional-assessment standards, and morbidity reasonableness (Section 5.6). PHINS notes that the December 2023 amendment removed the fixed 20%-minimum insurer risk-retention requirement in the basic health-fund layer; PHINS does not assume that flexibility extends automatically to individual products and does not rely on it.

**Licensing position.** PHINS Technologies Ltd. is not a licensed insurer and will not describe itself as one. The insurance risk shall be carried by a licensed Israeli insurer (fronting structure) and/or an approved reinsurance structure. PHINS acts as the technology, underwriting-workflow, policy-administration, claims-workflow and distribution platform, subject to applicable licensing (Section 6).

**Pre-ruling use.** Section 15 maps this contract onto the five decisions requested at the 12 October 2026 meeting in Jerusalem. It also records the supervision controls the platform can already demonstrate: one pricing kernel, a read-only regulation outline, an ADL 3 remaining-life table that does not price the contract, and decision logs in which a model score never replaces the rule. Those controls do not alter the sums, rates, caps, or claim model in Sections 1–5.

## 2. Product Definition and Classification

### 2.1 Product identity

| Item | Value |
|---|---|
| Commercial name | PHINS Adjustable Risk Contract |
| Hebrew working name | פינס — ביטוח חיים משולב פיצוי נכות תפקודית קבועה |
| Legal classification | Life insurance (ביטוח חיים) with a permanent-disability benefit mechanism |
| Benefit form | Fixed indemnity, lump sum; independent of actual care expenses |
| Life benefit | L(x) = F below 65; L(x) = F ÷ 4 from 65; after a paid disability claim below 65 reduced to 0.75 × F |
| Disability benefit | D(x) = L(x) ÷ 4 = F ÷ 4 below age 65 (ratio 1:4); D(x) = L(x) = F ÷ 4 from age 65 (ratio 1:1 at reduced life); single payment on first qualifying event |
| Disability trigger | Permanent 3+ ADL dependency or equivalent cognitive impairment |
| Disability cover window | From age 3, lifelong while premiums are paid (no age-65 termination) |
| Sum-insured caps (issue below 65) | Life: ₪1,000,000 maximum; disability: ₪250,000 maximum (= cap ÷ 4) |
| Entry ages | 3–65; both layers continue beyond 65 |
| Premium | Age-related adjustable risk premium, re-priced at each policy anniversary on a published age curve; a separately identified premium is charged for each risk (life / disability) at every age |
| Savings / investment | None. Pure risk. |
| Claim interaction | Disability accelerates one quarter of face below 65 (policy continues at 0.75 × F); from 65 disability equals the stepped-down life sum; one disability claim per lifetime (Section 5.4) |

### 2.2 Benefit interaction (claims model)

The contract prices and administers the two benefits as a **three-state continuation model** (Section 5.4):

1. **Death without prior disability** pays the full in-force life sum L; the policy terminates.
2. **Disability before death** pays D(x) — F ÷ 4 below age 65, F ÷ 4 from age 65 — and the policy **continues**: below 65 the life sum becomes L′ = 0.75 × F from the next premium due date; from 65 the stepped-down life sum L(x) = F ÷ 4 continues (life risk only). The disability layer terminates with its single payment; no second disability claim is possible.
3. **Death after a paid disability claim** pays the then-current reduced life sum (0.75 × F if the disability claim was below 65; otherwise the stepped-down L(x)); the policy terminates.

The three-state present-value model in Section 5.4 is the binding pricing method; the policy wording will state the post-claim sum insured, premium basis, and termination rules explicitly.

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
| Benefit type | Lump sum: L(x) on death (0.75 × F after a paid disability claim below 65; F ÷ 4 from 65); D(x) on qualifying disability — F ÷ 4 at every age (1:4 to face below 65; 1:1 to stepped-down life from 65) |
| Waiting period (disability) | 60–90 days from event, per actuarial filing; no waiting period on death benefit |
| Entry age | 3–65; both layers lifelong while premiums are paid |
| Sum-insured caps (issue below 65) | Life ₪1,000,000; disability ₪250,000 |
| Maximum liability | One disability payment of D(x) plus one death payment of the in-force life sum; below 65 the aggregate never exceeds F (acceleration structure); from 65 the aggregate never exceeds F ÷ 2 (life F÷4 + disability F÷4) |
| Premium | Adjustable, age-banded, unisex or gender-based per final filing; re-priced annually on the published age curve (Section 5.2); separately identified premium per risk at every age |
| Underwriting | Simplified issue with ADL-severity scoring 1–10; declines at severity ≥ 9; loadings per Section 5.7 |
| Claims assessment | Medical documentation + independent functional assessment |
| Policyholder rights | Underwriting transparency, coverage continuity, published re-pricing, 30-day cooling-off, tamper-evident audit trail |

## 5. Actuarial Basis (Filed Tables)

All tables below are the canonical PHINS actuarial tables (central tables version V2.0) applied by a single deterministic pricing kernel. Every premium quoted in marketing, application, billing, and reserving derives from the same kernel and carries a reproducible integrity hash; there is no parallel calculation path.

### 5.1 Base rates

| Layer | Base rate (per 1,000 sum insured, monthly) |
|---|---|
| Life (sum L(x); 0.75 × F after a paid disability claim below 65) | 0.25 |
| Disability (sum D(x): F ÷ 4 at every age under Draft 3.1) | 0.20 |

Monthly gross premium at attained age x — a separately identified premium is charged for each risk at every age:

```
L(x) = F          [x < 65] ;  L(x) = F / 4   [x >= 65]
D(x) = L(x) / 4   [x < 65] ;  D(x) = L(x)    [x >= 65]   (= F / 4 at every age)
Premium(x) = (L(x) / 1,000) × 0.25 × f(x)  +  (D(x) / 1,000) × 0.20 × f(x)
After a paid disability claim below 65 (from the next premium due date):
Premium(x) = (0.75 × F / 1,000) × 0.25 × f(x)          [life risk only]
After a paid disability claim from 65:
Premium(x) = (L(x) / 1,000) × 0.25 × f(x)              [life risk only on F/4]
```

where f(x) is the published age-factor curve in Section 5.2. Because D = F ÷ 4 below 65, the combined pre-65 rate equals 0.30 per 1,000 of F per month; from age 65 both sums equal F ÷ 4 so the combined rate equals 0.1125 per 1,000 of F per month (equivalently 0.45 per 1,000 of the stepped-down life sum), with each component disclosed separately on the premium notice.

### 5.2 Age-factor curve f(x) — published re-pricing curve

| Age segment | Rule | Anchor values |
|---|---|---|
| 3 → 25 | Linear from 0.30 to 1.00 | f(3) = 0.30; f(25) = 1.00 |
| 25 → 65 | +0.015 per year of age | f(35) = 1.15; f(45) = 1.30; f(55) = 1.45; f(65) = 1.60 |
| 65 → 75 | +0.05 per year (both layers, senior segment) | f(70) = 1.85; f(75) = 2.10 |
| 75 → 80 (cap) | +0.08 per year (both layers, senior segment) | f(80) = 2.50 |

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

On a qualifying claim the contract pays the **full** disability sum D(x) — F ÷ 4 below age 65 and F ÷ 4 from age 65 (equal to the stepped-down life sum) — with the benefit percentage fixed at 100% of D(x) once the permanent 3+ ADL trigger fires. There is no fractional or graded scoring of the paid benefit — this removes the "hidden quantitative manipulation" risk flagged in consumer-protection guidance.

### 5.4 Claim-interaction model (present value of claims)

The redesigned contract is priced on a **three-state continuation model** — healthy → disabled (policy continues at the post-claim life sum) → dead — instead of the mutually-exclusive model of Draft 2.0. For each policy year t at attained age x, with P_h = probability the insured is alive with no prior disability claim and P_d = probability the insured is alive after a paid disability claim:

```
PV_disability  = Σ  D(x+t−1) × P_h(t−1) × (1 − q(x+t−1)) × i(x+t−1) × v^t
PV_mortality   = Σ  [ L(x+t−1) × P_h(t−1) × q(x+t−1)
                      + L_post(x+t−1) × P_d(t−1) × q_d(x+t−1) ] × v^t
Risk premium   = (PV_mortality + PV_disability) / term

L(x) = F      [x < 65] ;  L(x) = F / 4  [x >= 65]
D(x) = L(x)/4 [x < 65] ;  D(x) = L(x)   [x >= 65]
L_post(x) = 0.75 × F if disability claimed below 65; else L(x)
q_d(x) = q(x) × 1.80    (disabled-lives mortality: filed ADL-10 multiplier, Section 5.3)
```

with discount factor v = 1 / (1 + 3.5%). State transitions: the healthy state is depleted by death (pays L(x)) and by disability incidence (pays D(x) and moves the insured to the disabled state); the disabled state is depleted by death, which pays L_post(x). Premiums collected in the disabled state are the life-risk component only, computed on L_post(x).

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

> **Benchmark statement.** The PHINS pricing basis uses the Authority's published LTC experience tables (annual LTC entry rates by age group and sex, as annexed to the consolidated circular, Gate 6, Part 3, December 2023 amendment) as a regulatory benchmark and minimum-reasonableness reference for the disability layer. Those tables were constructed for the extended LTC layer of health-fund group insurance; PHINS does not copy them as a pricing table. Any deviation of the filed incidence basis in Section 5.3 from the Authority's benchmark shall be documented, actuarially justified by the appointed actuary, and submitted for prior approval where required. A separate published ADL 3 remaining-life table is stored for duration reference (Section 15.3). That table does not price q(x), i(x), or the ADL-10 mortality multiplier, and it is not this benchmark.

### 5.7 Underwriting rules (filed)

| ADL severity at issue | Decision | Premium loading | Life coverage cap (₪) |
|---|---|---|---|
| 1–5 | Standard | — | 1,000,000 |
| 6 | Accept with loading | +15% | 1,000,000 |
| 7 | Accept with loading | +30% | 750,000 |
| 8 | Accept with loading; disability layer excluded | +50% | 500,000 |
| 9–10 | Decline | — | — |

For issue below age 65 the plan-level maxima are **₪1,000,000 face / life** and **₪250,000 disability** (the 1:4 ratio applied to the life cap); the severity-based caps above apply within those maxima. From age 65 the in-force life sum steps to face ÷ 4 and the disability sum equals that reduced life sum (1:1).

### 5.8 Specimen premium schedule (reference policyholder)

Reference case: face F = ₪500,000 (within the ₪1,000,000 cap). Below age 65: life L = F = ₪500,000 and D = L ÷ 4 = ₪125,000 (within the ₪250,000 cap); combined monthly premium = 150 × f(x). From age 65: life steps to F ÷ 4 = ₪125,000 and D = life = ₪125,000 (1:1 at the reduced life sum); combined monthly premium = 56.25 × f(x), with each risk premium disclosed separately. Amounts in ₪.

| Attained age | f(x) | Life premium / month | Disability premium / month | Total / month |
|---|---|---|---|---|
| 3 | 0.30 | 37.50 | 7.50 | 45.00 |
| 25 | 1.00 | 125.00 | 25.00 | 150.00 |
| 35 | 1.15 | 143.75 | 28.75 | 172.50 |
| 45 | 1.30 | 162.50 | 32.50 | 195.00 |
| 55 | 1.45 | 181.25 | 36.25 | 217.50 |
| 64 | 1.585 | 198.13 | 39.62 | 237.75 |
| 65 | 1.60 | 50.00 (L = F÷4) | 40.00 (D = L, 1:1) | 90.00 |
| 70 | 1.85 | 57.81 | 46.25 | 104.06 |
| 75 | 2.10 | 65.63 | 52.50 | 118.13 |
| 80 | 2.50 | 78.13 | 62.50 | 140.63 |

**Post-claim continuation example.** If the disability benefit is paid at age 68 (D = ₪125,000 = F ÷ 4 at the post-65 1:1 ratio), the policy continues with the stepped-down life sum L = ₪125,000; from the next premium due date the monthly premium is the life component only, e.g. at age 70: (125,000 / 1,000) × 0.25 × 1.85 = ₪57.81. If the disability benefit is paid at age 60 (D = ₪125,000), the aggregate exposure remains F: ₪125,000 paid plus ₪375,000 in-force death benefit (0.75 × F).

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
2. **No hidden scoring.** The disability benefit is binary at the contractual trigger: once permanent 3+ ADL dependency is confirmed, the full D(x) is paid — F ÷ 4 below age 65 and F ÷ 4 from age 65 (D = stepped-down life). Internal severity scores affect underwriting only, never the paid benefit.
3. **Appeals.** Internal appeal right; right to submit additional medical evidence; review by a senior claims officer; escalation to the insurer's ombudsman and to the Authority.
4. **Audit trail.** Every underwriting and claims decision is recorded on the platform's append-only, hash-chained ledger; AI tools recommend but never post a binding decision.

## 8. Consumer Disclosure

The pre-sale consumer summary (Hebrew, plain language) states: what is covered and what is not; the exact insured-event definitions (death; permanent 3+ ADL); the age-banded contract sums with worked examples (below 65: face F = ₪500,000 → life ₪500,000 and D = ₪125,000 at 1:4; from 65: life = F ÷ 4 = ₪125,000 and D = life = ₪125,000 at 1:1); the sum-insured caps at issue below 65 (life ₪1,000,000; disability ₪250,000); the waiting period; that the benefit is a lump sum; that premiums re-price annually on a published age curve and that a separate premium is charged for each risk; that after a paid disability claim below 65 the policy continues with the life sum reduced by one quarter of face (to 0.75 × F) from the next premium due date, with the premium recalculated accordingly; that the policy has **no cash, surrender or savings value**; underwriting requirements; claim documents required; who carries the insurance risk; and PHINS's non-insurer platform role. Prohibited representations: "guaranteed approval", "bank-like savings", "government-approved", "covers every disability".

## 9. Adjacent Products (Out of Scope of This Filing)

### 9.1 Health-fund group LTC

This filing does not seek to operate under, or amend, the health-fund group LTC framework of Gate 6, Part 3.

### 9.2 Savings add-on

The PHINS platform supports an optional savings add-on collected as a fixed percentage of the risk premium and held in a segregated account. It is excluded from this product and filing. If offered in Israel it will be structured through a properly licensed entity with separate disclosure, separate fees, and an explicit statement that investment performance does not affect the approved insurance benefits.

## 10. Reinsurance and Risk Transfer

Filed structure: a licensed Israeli insurer fronts the policy; a reinsurance treaty covers catastrophic and accumulation risk on both the mortality and disability layers; PHINS receives technology and service fees only — no unlicensed insurance-risk compensation; any profit-sharing arrangement is submitted for review to avoid unauthorized insurance activity.

## 11. Digital and AI Governance

AI tools support onboarding, ADL-severity scoring, claims triage and customer service. Binding controls: human review of every adverse underwriting or claims decision; a written explanation capability for every decision; full audit trail of AI recommendations on the hash-chained ledger; data minimization and explicit consent for medical-data processing; cybersecurity controls; and no discrimination beyond actuarially justified classification. A shadow model score is recorded beside the rule score and does not change the decision. A threshold change is an admin act that writes the before-and-after record first and rolls back if that record cannot be written (Section 15.3).

## 12. Regulatory Risk Assessment

| Risk | Level | Mitigation |
|---|---|---|
| Product treated as unauthorized insurance activity | High | Fronting by licensed insurer; PHINS platform-only role |
| Disability layer construed as health/LTC class requiring separate filing | Medium–High | File as life insurance with disability mechanism; adopt LTC-grade trigger definitions; pre-ruling if required |
| Misuse of health-fund LTC benchmark tables | Medium–High | Benchmark-only use; appointed-actuary justification of deviations (Section 5.6) |
| Claims disputes over ADL determination | High | Objective 3-of-6 ADL wording; independent assessment; binary benefit |
| AI discrimination / privacy | High | Governance per Section 11; human review; audit trail |
| Misleading marketing | High | Pre-approved scripts; prohibited-representations list (Section 8) |
| Senior life step-down with 1:1 disability at F÷4 — morbidity accumulation and anti-selection at 65+ | Medium | Separately identified senior risk premium on the reduced sums; disabled-lives mortality basis (Section 5.4); senior morbidity monitoring; reinsurance of the senior layer (Section 10) |
| Reinsurance not recognized for capital relief | Medium | Solvency review with insurer and reinsurer before filing |

## 13. Filing Package Checklist

A. Legal product memorandum (this document, finalized). B. Full policy wording in Hebrew. C. One-page consumer disclosure sheet in Hebrew. D. Actuarial pricing report per Section 5.9. E. Claims protocol (functional assessment, timelines, appeals). F. AI and digital-governance appendix. G. Distribution compliance manual. H. Reinsurance treaty summary.

## 14. Declaration

> "PHINS seeks to introduce a transparent, actuarially sound life-insurance product with a lifelong permanent-disability mechanism, paying a defined lump-sum benefit of the in-force sum insured on death, and — on a permanent 3+ ADL long-term-care event determined through medical documentation and independent functional assessment — one quarter of the sum insured below age 65 (contract ratio 1:4, capped at ₪250,000 against a ₪1,000,000 life cap) or the full sum insured from age 65 (contract ratio 1:1). Following a paid disability claim the policy continues with the life sum reduced by one quarter, effective from the next premium due date, with a separately identified premium charged for each risk. PHINS intends to operate only within the scope of applicable Israeli insurance, financial-services, privacy, anti-money-laundering, consumer-protection and digital-governance law. Insurance risk shall be carried solely by a licensed insurer and/or an approved reinsurance structure. The PHINS technology platform supports onboarding, underwriting, policy administration, claims workflow, customer service and compliance monitoring, subject to regulatory approval and appropriate licensing."

## 15. Pre-ruling supplement — 12 October 2026

This supplement is the annex for the meeting with the Capital Market, Insurance and Savings Authority on 12 October 2026 in Jerusalem. Sections 1–5 are unchanged. The sums, the 1:4 and post-65 1:1 ratios, the ₪1,000,000 / ₪250,000 issue caps, the V2.0 rates, the age curve, and the three-state claim model remain the filing. Market figures below are copied from the named public sources. They are not PHINS forecasts and they are not pricing assumptions.

### 15.1 Five decisions, each tied to a section of this memorandum

1. **Classification.** A pre-ruling that this Draft 3.1 contract is life insurance with a lifelong permanent-disability mechanism under Section 40, and that the permanent 3+ ADL lump sum does not by itself reclassify the policy as health-fund group long-term care (Sections 1, 2 and 3). On the State Comptroller's June 2026 account, the health-fund basic layer was tightened from difficulty in 3 of 6 ADL to difficulty in 4 of 6 ADL after Circular 2023-1-11. This filing stays at permanent 3 of 6, paid as a lump sum.
2. **Functional MGA.** PHINS may perform underwriting support, billing, claims administration and actuarial support while claims reserves and final adjudication stay on a designated Israeli insurer, and while that carrier's appointed actuary signs the basis (Sections 6, 7 and 10). The designated insurer is not named in this memorandum.
3. **Savings, separately.** The filed product id is `phins_pure_risk_adjustable`. Its savings rate is 0. The platform product `phins_hybrid_savings` is a different id and is outside this filing (Section 9.2). A later savings add-on needs its own licence, entity and sequence. No investment-company counterparty is named here.
4. **Perimeter.** This pre-ruling does not appoint PHINS to operate the closed older health-fund group, the insureds' funds, or the National Insurance nursing benefit (Section 9.1).
5. **Path and clock.** The submission order, the open conditions, and a date for the next step. The Comptroller records the health-fund stabilisation as temporary until December 2026. That horizon is the reason to ask for a clock. It is not a statement that the Authority has selected this plan.

### 15.2 Public context the pre-ruling may rely on

The enclosed circular is Insurance Circular 2023-1-11, 4 December 2023, signed by Amit Gal, then acting Commissioner. It repeals the minimum 20 percent insurer risk share on the health-fund basic layer. This filing does not use that flexibility. Insurance risk on the Draft 3.1 contract stays on a licensed insurer.

The Comptroller's June 2026 special report on the long-term-care array records the consequence of that circular and of the related stabilisation: the monthly indemnity was reduced by about 10 percent, from 5,500 NIS to 5,000 NIS; 100 percent of those benefits are paid from the insureds' fund; the qualifying test moved from 3 of 6 ADL to 4 of 6; and the arrangement is temporary until December 2026. Funder's 4 October 2026 account describes a reduction from about 6,100 NIS to 5,000 NIS and calls the 2023–2024 steps temporary. Both figures are kept. They are not averaged. Clalit's book is about 2.5 million in the Comptroller's report and about 2.7 million in Globes. Both stay.

On 4 October 2026 the Authority published a permanent-solution direction, as reported the same week by Funder, Calcalist, TheMarker and Globes, and on 5 October by ICE. Those reports put the health-fund book at about 5.2 million insured people. This memorandum has not attached an Authority PDF of that publication, so 5.2 million is used only as those outlets report it. The reported direction is personal accumulation plus insurance risk borne by insurers for a younger cohort, and a closed older group kept on today's mechanism. Legislation is required.

The age cut is not 50, and it is not yet a statute. Funder, Globes and ICE say a threshold will be set and do not print the integer. Calcalist, on 4 October 2026, prints 55. A December 2025 outline reported by Bizportal discussed a band of roughly 50 to 60. That article is earlier than the 4 October publication. The filed contract is issuable below age 65. Disability attaches from age 3. There is no issue cap at 50.

The proposal is not destined, and it is not in force. TheMarker and Calcalist report that the Finance Ministry side does not share the Authority's urgency. Any pre-ruling conversation should record that disagreement.

National Insurance is a separate public layer. The Comptroller records nursing-benefit recipients of about 180,000 in 2018 and about 392,000 in 2025, and nursing expenditure of about 7 billion NIS in 2018 and about 21.1 billion NIS in the report's opening statement for 2025. The fund-zero year at the close of the audit is 2035. The 2026 budget is a deficit budget, with a forecast deficit of about 10 billion NIS. On 29 June 2026 a Finance Ministry representative told the Knesset that 2029 is a cash-flow point for statutory payment capacity. 2029 and 2035 are different statements and stay separate. The Comptroller does not record the National Insurance fund as empty on the meeting date.

### 15.3 Controls the platform can demonstrate without changing the tariff

| Control | What it does for this filing | What it does not do |
|---|---|---|
| Single pricing kernel | `price_policy()` is the only writer of the premium block (annual, monthly, mortality present value, disability present value, savings, expense, profit, and a deterministic integrity hash). The filed product id is `phins_pure_risk_adjustable`. Central tables version V2.0 are the rates in Section 5. | It does not create a second tariff for marketing, billing, or reserving. |
| Savings rate on the filed product | `savings_rate` on `phins_pure_risk_adjustable` is 0. | It does not price `phins_hybrid_savings`. That id is outside Section 40. |
| Regulation outline | `GET /api/regulator/outline` is readable by the regulator, admin, and actuary roles. It shows the active tables version, the config version, catalog integrity hashes, and basic premiums from `price_policy` on one published illustration: product `phins_pure_risk_adjustable`, coverage 100,000, term 20 years, ages 30, 40, 50 and 60, standard nonsmoker base. Versions whose price vector matches to the cent share one line. The outline is refused if it cannot be reconciled to the canonical books, or if an identifier survives redaction. | The illustration is not a customer quote. The ADL input used to produce those premiums is not published on the outline. The regulator role cannot call other APIs or write, except its own credential change and its own inquiries. |
| ADL 3 remaining-life table | A published table of remaining years after ADL 3 is stored for ages 1 through 110, with separate man, woman, and published-average columns. At age 65 the stored row is 4.41 years (man), 5.55 years (woman). At age 80 the stored row is 3.42 years (man), 5.15 years (woman). The published average is stored as loaded. It is not recomputed as (man + woman) / 2. A replacement must include every age from 20 through 85, and a rate band with no expectancy columns is rejected. The table is marked assumption-only and is not used in pricing. | The table does not price q(x), i(x), or the ADL-10 mortality multiplier. Disabled-lives mortality in Section 5.4 remains q(x) × 1.80. The risk-reference chart of these years is not the consumer premium table in Section 5.8, and it is not a closed-form remaining-life formula. |
| Evidence | Facts used in underwriting and claims carry provenance (source snippet, character offsets, page, or timestamp). A cross-document contradiction is stored as a contradiction and flags the item `SUSPICIOUS_EVIDENCE_CONTRADICTION`. | A bot does not silently pick one of the conflicting facts. |
| Identity | A customer's personal ID has one writer. Responses, audit rows and ledger anchors carry nationality, a keyed hash, and the last four characters. A pipeline payload that disagrees with the stored identity is flagged `identity_mismatch` and is not written over the master. | The plaintext ID is not a field on the policy or claim record. |
| Decision log | Every underwriting and claims recommendation can be logged with the rule score, a shadow model score, and the divergence. The shadow score does not change the decision. A threshold change is admin-only, requires a reason, writes the before-and-after record before it takes effect, and rolls back if that record cannot be written. | An evaluator's recommendation is not itself a threshold change. |
| Document seal | Application-chat, claim-chat and uploaded policy files are sealed by SHA-256 into a per-entity archive. | The seal does not change a premium, a reserve, or a claim amount. |
| Access split | A customer session cannot call admin APIs. A staff session cannot move that customer's private money from the customer dashboard. | Row scope for a customer remains that customer's own records unless the role is operational staff. |

The appointed actuary's pricing report in Section 5.9 remains the document that justifies any deviation from the Authority's December 2023 long-term-care benchmark. Section 15.3 is the operating evidence that the tariff in Section 5 is the tariff the platform will administer.

---

*Prepared on the PHINS platform. The rate tables in Section 5 (mortality, disability incidence, ADL multipliers, lapse, age curve, loadings) are the platform's central tables version V2.0, applied by its single deterministic pricing kernel. The Draft 3.1 contract features — lifelong disability with life stepping to face ÷ 4 from age 65 (D = life at the reduced sum), the ₪1,000,000 / ₪250,000 issue caps, and post-claim continuation at 0.75 × F below 65 — are implemented as the versioned product configuration of the same kernel, so every marketed premium reconciles to this filing. Section 15 (12 October 2026) records the supervision controls and the public context for the pre-ruling. Sections 1–5 are unchanged.*
