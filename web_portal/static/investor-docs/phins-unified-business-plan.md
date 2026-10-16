# PHINS — Unified Business Plan, Investor Deck & Appendices

**Edition:** October 2026 · one standard · adjustable factors  
**Plan identity:** `unified-2026.10-v1` · content hash `9128223e1c2223881e0eca64ae6922654b79d52bb2eed151beb726f3c4c1589f`  
**Audience:** venture and angel investors, carriers, reinsurers, supervisors and local partners.  
**Companion:** the live, adjustable edition is `/business-plan.html`; the model is `GET /api/business-plan/model`. This file is generated from the same model by `scripts/build_business_plan.py` and must not be edited by hand.

> Planning identity only. Public market evidence stays in the Scenario Lab, locked and separate; no figure here writes the platform ledger, the actuarial store or any statistic.

## Headline figures

| Figure | Value |
|---|---|
| Annual risk premium (kernel specimen, age 42) | ₪4,518 |
| PHINS take / carrier share | 25% / 75% |
| Israel in force, end-2029 / end-2031 | 230,554 / 471,621 |
| Markets on the platform by 2031 | 10 |
| Group PHINS revenue 2031 (ILS / USD at planning FX) | ₪749.1M / $203.6M |
| Group EBITDA margin 2031 | 57% |
| Seed / pre-money / post-money | ₪6.0M / ₪24M / ₪30M |
| Series A indication (2028) | ₪18.0M |
| Actuarial appraisal (anchor book) | ₪264.6M |
| Integrity | all identities hold |

---

# Part I — Business plan

## 1. Executive summary

PHINS is an AI-operated insurance and savings platform. It writes a new regulated contract — life insurance with a lifelong severe-disability (ADL-3) mechanism — on the paper of a licensed carrier, runs the whole operation (chat intake, underwriting, claims, billing, actuarial, reinsurance reporting, marketplace, savings flow) on one platform, and enters every market through a local partnership. The platform is the company; the Israel contract is the first use of it.

The anchor plan is a single, table-driven identity: ₪4,518 annual risk premium at the age-42 specimen, 25% PHINS take / 75% carrier share, 8% churn, 25,000 / 75,000 / 150,000 new issues in 2027–2029 and 150,000 a year after. It produces 230,554 policies in force by end-2029 and 471,621 by end-2031 in Israel alone, with PHINS revenue of ₪183.3M in 2029 and ₪467.5M in 2031.

The expansion plan replicates that ramp into OECD partner markets — 10 markets on one platform by 2031. Each partner market follows the Israel path at 50% scale from its launch year; PHINS keeps 60% of the platform take and carries only platform opex. Group PHINS revenue reaches ₪749.1M ($203.6M at the planning FX) in 2031 at a 57% EBITDA margin; group risk GWP reaches ₪3.75B.

The round is ₪6.0M seed on ₪24M pre-money (₪30M post, 20% dilution). 2027 is the only loss year in the anchor book (₪18.8M burn); the group's peak cumulative need is ₪20.2M, which sets a Series A indication of ₪18.0M in 2028 to fund scale, not survival. The actuarial appraisal of the same anchor book at a 35% discount rate, 4.0× 2029 net revenue and 15% prudence is ₪264.6M; the ask is 9% of it.

Every figure in this document, the deck and the appendices regenerates from one factor register (unified-2026.10-v1) and is checked by structural identities on every render; the content hash 9128223e1c222388… reproduces them. Public evidence is never written by a planning assumption.

## 2. Company and method — one platform, local partnerships

PHINS builds technology, not balance sheet. In every market the contract is carried by a licensed insurer, reinsured through a quota-share treaty, and distributed with a local partner; PHINS supplies the product design, the pricing kernel, the AI agents and the operating platform as a one-stop shop. The method is identical everywhere — only the carrier, the supervisor and the partner change.

Four flows run on the platform: protection (life + ADL-3, long-term-care solutions), savings (a separately licensed add-on managed as part of the solution), consumption (a health marketplace with coverage-aware ranking and a wallet) and intelligence (underwriting, claims, risk-report and customer agents that recommend while humans decide). The same ledger, identity master and document standard sit under all four.

The organisation is sized to the take: the anchor book's opex is cost-per-average-life by year, so the plan grows headcount with lives rather than ahead of them. Partner markets add platform, actuarial and compliance capacity only (35% of Israel intensity); distribution and local operations are the partner's.

## 3. Market and OECD partnership map

Israel is the anchor: high home-care orientation, a large private long-term-care base, visible public spend and a supervisor already engaged (pre-ruling track, 12 October 2026). From there the plan sequences OECD members where a Solvency II or equivalent carrier can carry the contract and a local partner wants a digital severity layer beside public provision: Portugal and Western Europe, Sweden, Canada, the United States, Australia and Japan, with Bulgaria (accession candidate) and the UAE as partner-led top-up markets.

Market evidence stays in the Scenario Lab, locked and separate. This plan does not restate TAM: it plans lives. The kernel premium is the same ILS-denominated specimen in every market, converted at planning FX pins (Appendix A), so a partner market is comparable with Israel line by line.

Launch schedule: 1 partner market(s) in 2028, 2 in 2029, 3 in 2030 and 3 in 2031 (10 markets including Israel). Every launch count, the ramp scale and the platform share are adjustable factors; the regulatory pathway per market is in Appendix C.

## 4. Products and solutions

First contract — life insurance with a lifelong disability mechanism. Life face ₪1,000,000 with a disability sum of ₪250,000 below 65 (1:4) and a 1:1 mechanism from 65; the disability trigger is permanent loss of three or more activities of daily living. The kernel prices the specimen at ₪376.50 a month (₪313.75 life + ₪62.75 disability at the 1.255 age-42 factor), ₪4,518 a year, from the published risk_reference_v1 tables (0.25 / 0.20 per ₪1,000 monthly).

Long-term-care solutions. The same severity trigger funds a care benefit delivered through the marketplace (home care, residential care, equipment) with coverage-aware ranking, so the benefit buys care rather than cash alone.

Savings flow. 30% of in-force elects a 3.0× savings add-on at default, producing ₪660.0M of savings flow in Israel in 2029 and ₪3.37B across the group in 2031. Savings is a separately licensed flow managed as part of the solution; it is not insurance GWP and is not split with the carrier. Its fee economics are upside to this plan, not inside it.

Marketplace and wallet. Suppliers are invited, network-governed participants; the health wallet is the checkout and reimbursement centre; delivery bidding and supplier settlement run on the platform ledger.

## 5. Technology — the one standard

The technology section is the same in every PHINS document because it is read from the repository, not written: 136 service modules in 6 packages, 8 API modules, 20 repositories, 14 security modules and 288 test files at the time of rendering. The platform is a single Python service with a database-backed durable layer (PostgreSQL / SQLite), a generalized job queue, and a hash-chained ledger.

Ten standards define what 'PHINS technology' means in a partner market, listed in Appendix D: one pricing kernel, append-only integrity, AI governance (agents recommend, humans decide), an evidence pipeline with provenance, durable checksummed agent state, one identity writer, shared security utilities, chat intake beside classic forms, marketplace and payments on the ledger, and one document standard. A partner receives the whole set; nothing is forked per market.

## 6. Go-to-market and partnership model

Israel: direct digital intake (Phin chat and classic application) on the carrier's paper, agents and bancassurance as additional channels, the Authority's pre-ruling track for the filing. The gates are dated (Appendix G): sales 1 January 2027, 1,000 policies, 24,000 in force by year-end.

Partner markets: PHINS signs a local licensed carrier and a distribution partner, deploys the platform unchanged, and shares the take — 60% to PHINS, 40% to the partner at default. The partner carries distribution and local operations; PHINS carries platform, actuarial and compliance support. A partner market is live when its supervisor has the filing and the carrier has the treaty.

Reinsurance: a quota-share treaty (18% cession, 25% ceding commission at default) sits behind every carrier from day one; the carrier view in Appendix B is what the reinsurer sees.

## 7. Financial plan (ILS, five years)

Anchor book (Israel). Risk GWP ₪54.2M → ₪733.3M → ₪1.87B; PHINS revenue ₪13.6M → ₪183.3M → ₪467.5M; opex ₪32.4M → ₪116.9M → ₪202.9M; EBITDA −₪18.8M → ₪66.5M → ₪264.5M. 2028 is already EBITDA-positive (₪0.3M).

Partner markets. 1 market in 2028, 3 in 2029, 9 in 2031; PHINS revenue ₪28.1M in 2029 and ₪281.6M in 2031 after the partner's share of ₪187.7M.

Group. Risk GWP ₪3.75B and PHINS revenue ₪749.1M in 2031 ($203.6M at 3.68 ILS/USD), EBITDA ₪423.7M (57% margin), cumulative EBITDA ₪683.3M. Full tables are in Appendix F.

## 8. Capital plan and the round

Seed ₪6.0M on ₪24M pre-money, ₪30M post (20%). Use of funds: product and technology ₪2.4M (40%); regulatory, actuarial and reinsurance ₪1.2M (20%); distribution and local partnerships ₪1.5M (25%); operations and reserve ₪0.9M (15%).

Funding path. The anchor book's 2027 burn is ₪18.8M; the group's cumulative cash low point is ₪20.2M (2028, as the first partner market ramps). The Series A indication is that need less the seed plus a 25% buffer: ₪18.0M, rounded up to ₪0.5M. Group EBITDA turns positive in 2029 and cumulative EBITDA in 2029.

Valuation reference. The actuarial appraisal of the anchor book (PV of 2027–2029 EBITDA plus 4.0× 2029 net revenue, discounted at 35%, less 15% prudence) is ₪264.6M. The ₪24M ask is 9% of that appraisal; the same formula drives the Monte-Carlo simulator on the pitch dashboard.

## 9. Risks and mitigations

| Risk | What could go wrong | Mitigation in the plan |
|---|---|---|
| Regulatory timing | A filing slips or a jurisdiction requires a different carrier structure. | Pre-ruling track opened before sales; carrier-of-record model in every market; the pathway table in Appendix C is maintained per jurisdiction. |
| Claims experience above plan | The lifelong ADL-3 trigger runs above the 62% expected claims ratio. | Quota-share cession (18%) with ceding commission; kernel repricing through the one writer; the carrier view (Appendix B) is restated on every plan refresh. |
| Persistency below plan | Churn runs above 8%. | Persistency is an explicit factor; the plan is recomputed, never patched. Savings add-on raises retention and is outside risk GWP. |
| Partner dependence | A local partner underdelivers on distribution. | Partner ramp is set at 50% of the Israel path by default; PHINS keeps 60% of the take and carries only platform opex (35% of Israel intensity). |
| Technology and AI governance | An agent decision is wrong or unexplainable. | Agents recommend, humans decide; every decision is logged with evidence provenance; thresholds are promoted only through an audited step; golden sets gate CI. |
| Data integrity | A figure on an investor surface disagrees with another. | One factor register; integrity identities computed on every render; content hash 9128223e1c222388… reproduces the exact figures. |
| Capital | The seed does not reach cash break-even on its own. | It is not meant to: ₪6.0M funds the build and the first ₪18.8M year of sales; the peak cumulative need of ₪20.2M is covered by the Series A indication of ₪18.0M (25% buffer). |

## 10. Governance, milestones and team

Decisions that move money or risk are human: underwriting and claims agents recommend, the underwriter and adjuster apply; thresholds are proposed read-only and promoted only through an audited admin step; the regulator has a sealed read-only outline that reconciles to the financial books.

The team is sized by the opex intensity of the anchor book (platform, actuarial, underwriting, claims, customer operations, compliance) and extended per partner market by platform, actuarial and compliance support only. An Appointed Actuary reviews experience against the kernel at each gate.

| When | Gate |
|---|---|
| 12 Oct 2026 | Regulatory pre-ruling meeting with the Capital Market, Insurance and Savings Authority (Jerusalem); MGA bridge and filing scope. |
| Q4 2026 | Seed close (₪6.0M on ₪24M pre-money); carrier and reinsurance term sheets for the first contract. |
| 1 Jan 2027 | Gate 5 — sales begin on the licensed carrier's paper through the PHINS platform (Phin chat intake and classic forms). |
| H1 2027 | Gate 6 — first 1,000 policies in force; Appointed Actuary review of experience against the kernel. |
| Q4 2027 | Gate 7 — 24,000 end-of-year in-force; Series A readiness; first partner-market preparation. |
| 2028 | First partner market live under a local licensed carrier; Series A (₪18.0M indicative) funds scale, not survival. |
| 2029 | 230,554 in force in Israel; group EBITDA positive (2029); 3 partner markets live. |
| 2031 | 10 markets on one platform; 1,057,350 lives; ₪749.1M PHINS revenue at a 57% EBITDA margin. |

---

# Part II — Investor deck

## Slide 1 — PHINS
*AI insurtech platform · one-stop-shop technology · local OECD partnerships*

- Life + lifelong ADL-3 disability, long-term care, savings flow and a health marketplace — one regulated contract family, one platform.
- Carried by licensed insurers, reinsured by quota share, distributed with local partners; PHINS is the technology.
- Seed ₪6.0M on ₪24M pre-money. unified-2026.10-v1 · hash 9128223e1c222388…

## Slide 2 — The problem

- Severe disability and long-term care are the protection gap that public systems and legacy carriers leave open; savings sit in a separate silo.
- Carriers cannot ship a digital severity product: pricing, underwriting, claims and distribution live in different systems with no shared integrity.
- Partners in each OECD market want the product and the technology, not a new balance sheet.

## Slide 3 — The solution

- A life contract with a lifelong disability mechanism (1:4 below 65, 1:1 from 65) priced by one kernel: ₪4,518 a year at the age-42 specimen.
- Phin chat intake, underwriting bot, claims bot, risk reports, customer agents — all recommend, humans decide, every decision logged with evidence.
- Savings add-on (30% election × 3.0×) and a coverage-aware marketplace turn the benefit into care and wealth.

## Slide 4 — Why now

- Supervisor engaged: pre-ruling track with the Capital Market, Insurance and Savings Authority opened 12 October 2026.
- Demographics and public spend make the gap legible to regulators, partners and customers.
- AI operating model is built: 136 service modules, 288 test files, golden sets gating CI.

## Slide 5 — Product and pricing

- Kernel specimen: ₪313.75 life + ₪62.75 disability = ₪376.50 a month at the 1.255 age-42 factor.
- Risk GWP splits 25% PHINS / 75% carrier; savings flow is a separate licensed flow, never split.
- Published tables 0.25 / 0.20 per ₪1,000 monthly; same specimen in every market, converted at planning FX.

## Slide 6 — Market and expansion

- Israel anchor: 24,000 → 230,554 → 471,621 policies in force (2027 / 2029 / 2031).
- OECD partner markets: 1 in 2028, 3 in 2029, 9 by 2031 — 10 markets on one platform.
- Group lives 1,057,350 and risk GWP ₪3.75B in 2031.

## Slide 7 — Business model

- PHINS take 25% of risk GWP pays for distribution, underwriting, claims, billing and the agents.
- Partner markets: 60% of the take to PHINS, 40% to the local partner who carries distribution.
- Opex is cost per average life by year; partner markets add 35% of Israel intensity.

## Slide 8 — Technology — one standard

- 136 service modules · 8 API modules · 20 repositories · 14 security modules (live census).
- One pricing kernel, hash-chained ledger, AI governance, evidence provenance, durable checksummed agent state, one identity writer.
- One document standard: navy / gold letterhead, shield emblem, Inter + Space Grotesk — chrome never changes figures.

## Slide 9 — Milestones

- 12 Oct 2026 pre-ruling · Q4 2026 seed close · 1 Jan 2027 sales begin.
- Gate 6 first 1,000 policies · Gate 7 24,000 in force and Series A readiness (Q4 2027).
- 2028 first partner market · 2029 group EBITDA positive · 2031 10 markets.

## Slide 10 — Financials (ILS)

- PHINS revenue: ₪13.6M (2027) → ₪211.5M (2029) → ₪749.1M (2031); EBITDA −₪18.8M → ₪71.6M → ₪423.7M.
- 2031 EBITDA margin 57%; cumulative EBITDA ₪683.3M.
- Anchor book alone: ₪467.5M revenue and ₪264.5M EBITDA in 2031.

## Slide 11 — The round

- Seed ₪6.0M on ₪24M pre (₪30M post, 20%). Use of funds: tech 40% · regulatory & actuarial 20% · partnerships 25% · operations 15%.
- 2027 burn ₪18.8M; peak cumulative need ₪20.2M; Series A indication ₪18.0M (2028) funds scale, not survival.
- Actuarial appraisal ₪264.6M (35% WACC, 4.0× 2029 net revenue, 15% prudence); the ask is 9% of it.

## Slide 12 — Integrity

- Every figure regenerates from one factor register; structural identities are checked on every render: all identities hold.
- Anchor book reconciles to the Investor Meeting book and the pitch-dashboard simulator; planning never writes public evidence.
- Content hash 9128223e1c222388… — same inputs, same figures, for any party.

---

# Part III — Appendices

## Appendix A — Actuarial basis and pricing kernel

The specimen is priced by `services/pricing_kernel.py` from the published `risk_reference_v1` tables: life 0.25 and disability 0.20 per ₪1,000 monthly, times the locked age curve (factor 1.255 at age 42). Life face ₪1,000,000; disability sum ₪250,000 below 65 (1:4) and 1:1 from 65. Issue ages 3–65.

| Specimen line | Value |
|---|---|
| Age / age factor | 42 / 1.255 |
| Life sum / disability sum | ₪1,000,000 / ₪250,000 |
| Life monthly / disability monthly | ₪313.75 / ₪62.75 |
| Total monthly / annual | ₪376.50 / ₪4,518 |

Same specimen in every planning market (ILS face, local currency at the planning FX pin — never live FX, never evidence):

| Market | OECD | Currency | Planning age | Kernel premium (ILS) | Kernel premium (local) |
|---|---|---|---|---|---|
| Israel | member | ILS | 42 | ₪4,518 | 4,518 ILS |
| Portugal | member | EUR | 42 | ₪4,518 | 1,130 EUR |
| Western Europe (EUR) | member region | EUR | 42 | ₪4,518 | 1,130 EUR |
| Sweden | member | SEK | 42 | ₪4,518 | 13,321 SEK |
| Canada | member | CAD | 42 | ₪4,518 | 1,670 CAD |
| United States | member | USD | 42 | ₪4,518 | 1,228 USD |
| Australia | member | AUD | 42 | ₪4,518 | 1,878 AUD |
| Japan | member | JPY | 42 | ₪4,518 | 189,682 JPY |
| Bulgaria | accession candidate | EUR | 45 | ₪4,680 | 1,170 EUR |
| UAE / Middle East (AED) | non-member partner market | AED | 42 | ₪4,518 | 4,506 AED |

## Appendix B — Carrier and reinsurance view (Israel anchor book)

The carrier books 100% of risk GWP, pays the PHINS fee (25%), expects claims of 62% of GWP, cedes 18% by quota share, receives a 25% ceding commission on ceded premium and keeps 5% of GWP for capital, governance and compliance. Carrier margin in 2029: 5.7%. All five are adjustable factors; the table restates on every change.

| Metric | 2027 | 2028 | 2029 | 2030 | 2031 |
|---|---|---|---|---|---|
| Risk GWP | ₪54.2M | ₪266.7M | ₪733.3M | ₪1.33B | ₪1.87B |
| PHINS fee | ₪13.6M | ₪66.7M | ₪183.3M | ₪331.3M | ₪467.5M |
| Expected claims | ₪33.6M | ₪165.4M | ₪454.7M | ₪821.7M | ₪1.16B |
| Ceded premium | ₪9.8M | ₪48.0M | ₪132.0M | ₪238.5M | ₪336.6M |
| Ceded claims | ₪6.1M | ₪29.8M | ₪81.8M | ₪147.9M | ₪208.7M |
| Ceding commission | ₪2.4M | ₪12.0M | ₪33.0M | ₪59.6M | ₪84.1M |
| Carrier own expenses | ₪2.7M | ₪13.3M | ₪36.7M | ₪66.3M | ₪93.5M |
| Retained premium | ₪44.5M | ₪218.7M | ₪601.3M | ₪1.09B | ₪1.53B |
| Carrier result | ₪3.1M | ₪15.1M | ₪41.5M | ₪75.0M | ₪105.8M |
| Carrier margin | 5.7% | 5.7% | 5.7% | 5.7% | 5.7% |

## Appendix C — Regulatory pathway by market

| Market | OECD status | Supervisor | Pathway |
|---|---|---|---|
| Israel | member | Capital Market, Insurance and Savings Authority | Life insurance with lifelong disability mechanism filed through a licensed carrier; PHINS as the technology / MGA layer. Pre-ruling track opened 12 October 2026. |
| Portugal | member | ASF — Autoridade de Supervisão de Seguros e Fundos de Pensões | Solvency II carrier partner; PHINS operates as outsourced distribution and administration under EIOPA outsourcing guidelines. |
| Western Europe (EUR) | member region | National competent authorities under EIOPA (Solvency II) | One Solvency II carrier passports the product; PHINS is the technology partner in each country. |
| Sweden | member | Finansinspektionen | Top-up to vårdförsäkring through a licensed life company; PHINS platform under outsourcing agreement. |
| Canada | member | OSFI (federal) and provincial regulators | Federally regulated life insurer partner; provincial licensing for distribution. |
| United States | member | State insurance departments (NAIC framework) | State-by-state product filing through a licensed carrier; PHINS as TPA / technology provider. |
| Australia | member | APRA (prudential) and ASIC (conduct) | Life company partner; disability income sustainability governance applies to pricing. |
| Japan | member | Financial Services Agency (JFSA) | Life insurer partner beside the public LTC levy; PHINS as the digital severity layer. |
| Bulgaria | accession candidate | Financial Supervision Commission | Partner-led top-up (bancassurance or MGA); public-side lapse thesis. |
| UAE / Middle East (AED) | non-member partner market | Central Bank of the UAE (insurance supervision) | Licensed local insurer partner with visible reinsurance retention structure. |

## Appendix D — Technology architecture and security standard

| Census (live) | Count |
|---|---|
| Service modules (`services/*.py`) | 136 |
| Service packages | 6 |
| API modules (`web_portal/api_*.py`) | 8 |
| Repositories (`database/repositories/*_repository.py`) | 20 |
| Security modules (`security/*.py`) | 14 |
| Test files | 288 |
| Agents with golden sets | 2 |

| Pillar | Standard |
|---|---|
| Pricing kernel | One writer for premium decomposition (`services/pricing_kernel.py`): annual, monthly, mortality PV, disability PV, savings, expense, profit, with a deterministic integrity hash. Sandbox, simulator, IFRS 17 waterfall and the actuary dashboard reprice through it. |
| Data integrity | Append-only, hash-chained platform ledger; every balance and decision reproducible from postings. Repairs write a forensic before/after journal first and fail closed. |
| AI governance | Agents recommend, humans decide: every decision is logged, thresholds are proposed read-only and promoted only through an audited admin step, golden sets gate CI, and structured LLM output that fails validation falls back to the deterministic result. |
| Evidence pipeline | Facts carry provenance (source snippet, offsets, page, timestamp); contradictions are recorded, never silently resolved; shadow models score beside the rules and never change a decision. |
| Durable agent state | Agent artefacts are SHA-256 checksummed on load; a generalized job queue with retries, dead-letter and idempotency keys runs documents and agent routes asynchronously. |
| Identity & privacy | One writer for a customer's national ID + nationality; records carry only hash + last-4; the number lives in the vault and is never returned. |
| Security | Vault, key ring, token service, request sanitizer, intrusion detector, firewall, file scanner and confidential-access gate reused by every surface; secrets never in code. |
| Chat intake | Phin conversational policy and claim intake runs beside the classic forms and finalises through the same policy / claim pipelines, so underwriting, billing and ledger paths are unchanged. |
| Marketplace & payments | Health wallet, holds, payment intents, settlements, remittances and outbox events with coverage-aware ranking of suppliers. |
| Document standard | Every generated report carries the PHINS letterhead (navy / gold gradient, shield emblem, Inter + Space Grotesk) through one renderer; chrome never changes figures or checksums. |

## Appendix E — Data integrity and methodology

Identities computed on this render:

| Identity | Holds |
|---|---|
| Anchor book equals the Investor Meeting book (in-force path, GWP, opex, 5-year extension) | yes |
| Kernel specimen (age 42, published tables) prices at ₪4,518 | yes |
| PHINS take + carrier share = risk GWP, every year | yes |
| PHINS share + partner share = take pool, every year | yes |
| Group = anchor book + partner markets, every year | yes |
| Ceded + retained premium = risk GWP, every year | yes |
| Use-of-funds shares sum to 100% | yes |
| Savings flow is outside risk GWP and never split 25 / 75 | yes |
| Appraisal uses the pitch-dashboard simulator's formula | yes |
| No planning assumption writes public evidence, the ledger or the actuarial store | yes |
| All identities hold | yes |

Factor register (every adjustable assumption, its default and bounds):

| Group | Factor | Default | Min | Max | Note |
|---|---|---|---|---|---|
| Anchor book — Israel | Annual risk premium (ILS, kernel specimen) | ₪4,518 | ₪1,000 | ₪20,000 | Pricing-kernel quote: age 42, life ILS 1,000,000, disability ILS 250,000, published risk_reference_v1 tables (0.25 / 0.20 per 1,000 monthly). |
| Anchor book — Israel | PHINS platform take (share of risk GWP) | 25% | 5% | 60% | The carrier keeps the remainder (75% at default). Savings flow is never split 25/75. |
| Anchor book — Israel | Persistency of prior in-force | 92% | 70% | 99% | Churn = 1 − persistency (8% at default). |
| Anchor book — Israel | First-year persistency of new issues | 96% | 70% | 100% |  |
| Anchor book — Israel | New-issue path scale (× 25k / 75k / 150k / 150k / 150k) | 1× | 0.1× | 3× | 1.0 is the Investor Meeting book. |
| Anchor book — Israel | Opex intensity scale (× ILS per average life) | 1× | 0.3× | 3× | Intensity is cost ÷ average in-force by plan year, inherited from the retired small book. |
| Anchor book — Israel | Share of in-force electing the savings add-on | 30% | 0% | 100% |  |
| Anchor book — Israel | Savings add-on (× risk premium) | 3× | 0× | 10× | Savings is a separately licensed flow, not insurance GWP. |
| OECD partnership expansion | Partner markets launched in 2028 | 1 | 0 | 6 | Gate 7 (24,000 in-force, Series A readiness) precedes the first partner launch. |
| OECD partnership expansion | Partner markets launched in 2029 | 2 | 0 | 6 |  |
| OECD partnership expansion | Partner markets launched in 2030 | 3 | 0 | 6 |  |
| OECD partnership expansion | Partner markets launched in 2031 | 3 | 0 | 6 |  |
| OECD partnership expansion | Partner-market ramp (× Israel new-issue path) | 0.5× | 0.05× | 3× | Each partner market follows the Israel year-1..n ramp from its launch year, scaled. |
| OECD partnership expansion | PHINS share of the take in partner markets | 60% | 10% | 100% | The local partner keeps the rest and carries distribution and local operations. |
| OECD partnership expansion | PHINS opex intensity in partner markets (× Israel) | 0.35× | 0.05× | 1.5× | Platform, actuarial and compliance support only; distribution sits with the partner. |
| Carrier & reinsurance view | Expected claims ratio (share of risk GWP) | 62% | 20% | 95% | Scenario Lab Israel default. Planning assumption, not reported evidence. |
| Carrier & reinsurance view | Quota-share cession (share of risk GWP) | 18% | 0% | 90% | Scenario Lab Israel default. |
| Carrier & reinsurance view | Ceding commission (share of ceded premium) | 25% | 0% | 50% |  |
| Carrier & reinsurance view | Carrier own expenses (share of risk GWP) | 5% | 0% | 30% | Capital, governance and compliance kept by the carrier; distribution, underwriting, claims and billing run on PHINS inside the take. |
| Capital & round | Seed round (ILS) | ₪6,000,000 | ₪1,000,000 | ₪50,000,000 |  |
| Capital & round | Seed pre-money (ILS) | ₪24,000,000 | ₪1,000,000 | ₪500,000,000 | Manual ask; the appraisal below is the actuarial reference, not the ask. |
| Capital & round | Series A buffer over peak cumulative need | 25% | 0% | 100% |  |
| Capital & round | Use of seed — product & technology | 40% | 0% | 100% |  |
| Capital & round | Use of seed — regulatory, actuarial & reinsurance | 20% | 0% | 100% |  |
| Capital & round | Use of seed — distribution & local partnerships | 25% | 0% | 100% |  |
| Capital & round | Use of seed — operations & reserve | 15% | 0% | 100% | The four use-of-funds shares must sum to 100%. |
| Actuarial appraisal | Discount rate (WACC) | 35% | 5% | 90% |  |
| Actuarial appraisal | Exit multiple (× 2029 net revenue) | 4× | 0.5× | 30× |  |
| Actuarial appraisal | Prudence margin | 15% | 0% | 60% |  |
| Presentation | Planning FX (ILS per USD) | 3.68 | 2 | 6 | Planning pin shared with the Scenario Lab; not live FX, never written into evidence. |

Method: in-force follows `eoy = round(prior × persistency) + round(new × first-year persistency)`, average in force is the mid-point, risk GWP = average in force × premium, PHINS revenue = GWP × take, opex = intensity (ILS per average life, by plan year) × average in force. Partner cohorts follow the same recursion from their launch year at the ramp scale; group = anchor + partners. Funding is derived from the group cash curve. The appraisal is PV(EBITDA 2027–2029) + exit multiple × 2029 net revenue, discounted at WACC, less prudence.

## Appendix F — Financial tables (ILS)

### F.1 Anchor book — Israel

| Metric | 2027 | 2028 | 2029 | 2030 | 2031 |
|---|---|---|---|---|---|
| New issues | 25,000 | 75,000 | 150,000 | 150,000 | 150,000 |
| End-of-year in force | 24,000 | 94,080 | 230,554 | 356,110 | 471,621 |
| Average in force | 12,000 | 59,040 | 162,317 | 293,332 | 413,866 |
| Risk GWP | ₪54.2M | ₪266.7M | ₪733.3M | ₪1.33B | ₪1.87B |
| PHINS revenue (take) | ₪13.6M | ₪66.7M | ₪183.3M | ₪331.3M | ₪467.5M |
| Carrier share | ₪40.7M | ₪200.1M | ₪550.0M | ₪994.0M | ₪1.40B |
| Savings flow (separate) | ₪48.8M | ₪240.1M | ₪660.0M | ₪1.19B | ₪1.68B |
| Opex | ₪32.4M | ₪66.4M | ₪116.9M | ₪169.6M | ₪202.9M |
| EBITDA | −₪18.8M | ₪0.3M | ₪66.5M | ₪161.7M | ₪264.5M |
| EBITDA margin | -139% | 0% | 36% | 49% | 57% |
| Cumulative EBITDA | −₪18.8M | −₪18.6M | ₪47.9M | ₪209.6M | ₪474.1M |

### F.2 Partner markets

| Metric | 2027 | 2028 | 2029 | 2030 | 2031 |
|---|---|---|---|---|---|
| Partner markets live | 0 | 1 | 3 | 6 | 9 |
| End-of-year in force | 0 | 12,000 | 71,040 | 245,357 | 585,729 |
| Average in force | 0 | 6,000 | 41,520 | 158,198 | 415,542 |
| Risk GWP | ₪0.0M | ₪27.1M | ₪187.6M | ₪714.7M | ₪1.88B |
| Take pool | ₪0.0M | ₪6.8M | ₪46.9M | ₪178.7M | ₪469.4M |
| PHINS revenue | ₪0.0M | ₪4.1M | ₪28.1M | ₪107.2M | ₪281.6M |
| Partner revenue | ₪0.0M | ₪2.7M | ₪18.8M | ₪71.5M | ₪187.7M |
| PHINS opex | ₪0.0M | ₪5.7M | ₪23.0M | ₪60.7M | ₪122.5M |
| EBITDA | ₪0.0M | −₪1.6M | ₪5.2M | ₪46.5M | ₪159.1M |

### F.3 Group

| Metric | 2027 | 2028 | 2029 | 2030 | 2031 |
|---|---|---|---|---|---|
| Markets live (incl. Israel) | 1 | 2 | 4 | 7 | 10 |
| End-of-year in force | 24,000 | 106,080 | 301,594 | 601,467 | 1,057,350 |
| Risk GWP | ₪54.2M | ₪293.9M | ₪920.9M | ₪2.04B | ₪3.75B |
| Risk GWP (USD, planning FX) | $14.7M | $79.9M | $250.3M | $554.4M | $1.02B |
| PHINS revenue | ₪13.6M | ₪70.8M | ₪211.5M | ₪438.5M | ₪749.1M |
| PHINS revenue (USD) | $3.7M | $19.2M | $57.5M | $119.2M | $203.6M |
| Partner revenue | ₪0.0M | ₪2.7M | ₪18.8M | ₪71.5M | ₪187.7M |
| Savings flow (separate) | ₪48.8M | ₪264.5M | ₪828.8M | ₪1.84B | ₪3.37B |
| Opex | ₪32.4M | ₪72.1M | ₪139.8M | ₪230.3M | ₪325.4M |
| EBITDA | −₪18.8M | −₪1.3M | ₪71.6M | ₪208.2M | ₪423.7M |
| EBITDA margin | -139% | -2% | 34% | 47% | 57% |
| Cumulative EBITDA | −₪18.8M | −₪20.2M | ₪51.5M | ₪259.6M | ₪683.3M |

### F.4 Funding

| Line | Value |
|---|---|
| Seed / pre-money / post-money | ₪6.0M / ₪24M / ₪30M |
| Seed dilution | 20% |
| 2027 burn (anchor book EBITDA) | ₪18.8M |
| Runway on seed at the 2027 burn rate | 3.8 months |
| Peak cumulative need (group) | ₪20.2M |
| Series A indication (need − seed, + 25% buffer) | ₪18.0M |
| First EBITDA-positive year (group) | 2029 |
| Cumulative EBITDA positive (group) | 2029 |
| Use of seed — product & technology | ₪2.4M (40%) |
| Use of seed — regulatory, actuarial & reinsurance | ₪1.2M (20%) |
| Use of seed — distribution & local partnerships | ₪1.5M (25%) |
| Use of seed — operations & reserve | ₪0.9M (15%) |
| Actuarial appraisal (anchor book) | ₪264.6M at 35% WACC, 4.0× 2029 net revenue, 15% prudence |

## Appendix G — Milestone and governance calendar

| When | Gate |
|---|---|
| 12 Oct 2026 | Regulatory pre-ruling meeting with the Capital Market, Insurance and Savings Authority (Jerusalem); MGA bridge and filing scope. |
| Q4 2026 | Seed close (₪6.0M on ₪24M pre-money); carrier and reinsurance term sheets for the first contract. |
| 1 Jan 2027 | Gate 5 — sales begin on the licensed carrier's paper through the PHINS platform (Phin chat intake and classic forms). |
| H1 2027 | Gate 6 — first 1,000 policies in force; Appointed Actuary review of experience against the kernel. |
| Q4 2027 | Gate 7 — 24,000 end-of-year in-force; Series A readiness; first partner-market preparation. |
| 2028 | First partner market live under a local licensed carrier; Series A (₪18.0M indicative) funds scale, not survival. |
| 2029 | 230,554 in force in Israel; group EBITDA positive (2029); 3 partner markets live. |
| 2031 | 10 markets on one platform; 1,057,350 lives; ₪749.1M PHINS revenue at a 57% EBITDA margin. |

## Appendix H — Glossary

- **ADL-3** — Three or more activities of daily living permanently lost — the objective severity trigger of the lifelong disability mechanism.
- **Anchor book** — The Israel plan that every surface reconciles to: kernel premium, 25% / 75% split, persistency path, intensity-scaled opex.
- **Carrier of record** — The locally licensed insurer whose paper the contract is written on; PHINS is the technology / MGA layer.
- **Content hash** — SHA-256 over the factor inputs and every money line; identical inputs reproduce identical figures.
- **Kernel** — `services/pricing_kernel.py`, the single writer for premium decomposition.
- **Persistency** — Share of in-force that remains after a year (92% prior book, 96% first-year at default).
- **PHINS take** — The platform share of risk GWP (25% at default) that pays for distribution, underwriting, claims, billing and the agents.
- **Quota share** — Proportional reinsurance: the reinsurer takes the cession share of premium and claims and pays a ceding commission.
- **Savings flow** — The separately licensed savings add-on (30% election × 3.0 at default); never insurance GWP, never split with the carrier.
- **Series A indication** — Peak cumulative cash need less the seed, plus the buffer factor, rounded up to ₪0.5M — derived, not typed.

---

*asaf@phins.ai · phins.ai · Confidential — prepared for investors, carriers, reinsurers and supervisors. Generated from `services/business_plan_model.py` (unified-2026.10-v1); content hash `9128223e1c2223881e0eca64ae6922654b79d52bb2eed151beb726f3c4c1589f`.*
