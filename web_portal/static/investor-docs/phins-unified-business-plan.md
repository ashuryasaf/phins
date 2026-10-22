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

<!-- phins-chart {"categories": ["2027", "2028", "2029", "2030", "2031"], "id": "in_force", "kind": "stacked_bars", "series": [{"color": "#0e2f63", "label": "Israel", "values": [24000.0, 94080.0, 230554.0, 356110.0, 471621.0]}, {"color": "#c9a04e", "label": "Partner markets", "values": [0.0, 12000.0, 71040.0, 245357.0, 585729.0]}], "source": "anchor_book.rows[].eoy_in_force + partner_markets.rows[].eoy_in_force = group.rows[].eoy_in_force", "subtitle": "Israel anchor book plus partner-market cohorts; the stack total is the group.", "title": "Policies in force at year end", "unit": "int"} -->
**Policies in force at year end.** Israel anchor book plus partner-market cohorts; the stack total is the group.

| Series | 2027 | 2028 | 2029 | 2030 | 2031 |
|---|---|---|---|---|---|
| Israel | 24,000 | 94,080 | 230,554 | 356,110 | 471,621 |
| Partner markets | 0 | 12,000 | 71,040 | 245,357 | 585,729 |
| Total | 24,000 | 106,080 | 301,594 | 601,467 | 1,057,350 |

*Figure in force — source: anchor_book.rows[].eoy_in_force + partner_markets.rows[].eoy_in_force = group.rows[].eoy_in_force*

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

The technology section is the same in every PHINS document because it is read from the repository, not written: 153 service modules in 6 packages, 10 API modules, 21 repositories, 14 security modules and 294 test files at the time of rendering. The platform is a single Python service with a database-backed durable layer (PostgreSQL / SQLite), a generalized job queue, and a hash-chained ledger.

Ten standards define what 'PHINS technology' means in a partner market, listed in Appendix D: one pricing kernel, append-only integrity, AI governance (agents recommend, humans decide), an evidence pipeline with provenance, durable checksummed agent state, one identity writer, shared security utilities, chat intake beside classic forms, marketplace and payments on the ledger, and one document standard. A partner receives the whole set; nothing is forked per market.

## 6. Go-to-market and partnership model

Israel: direct digital intake (Phin chat and classic application) on the carrier's paper, agents and bancassurance as additional channels, the Authority's pre-ruling track for the filing. The gates are dated (Appendix G): sales 1 January 2027, 1,000 policies, 24,000 in force by year-end.

Partner markets: PHINS signs a local licensed carrier and a distribution partner, deploys the platform unchanged, and shares the take — 60% to PHINS, 40% to the partner at default. The partner carries distribution and local operations; PHINS carries platform, actuarial and compliance support. A partner market is live when its supervisor has the filing and the carrier has the treaty.

Reinsurance: a quota-share treaty (18% cession, 25% ceding commission at default) sits behind every carrier from day one; the carrier view in Appendix B is what the reinsurer sees.

## 7. Financial plan (ILS, five years)

Anchor book (Israel). Risk GWP ₪54.2M → ₪733.3M → ₪1.87B; PHINS revenue ₪13.6M → ₪183.3M → ₪467.5M; opex ₪32.4M → ₪116.9M → ₪202.9M; EBITDA −₪18.8M → ₪66.5M → ₪264.5M. 2028 is already EBITDA-positive (₪0.3M).

Partner markets. 1 market in 2028, 3 in 2029, 9 in 2031; PHINS revenue ₪28.1M in 2029 and ₪281.6M in 2031 after the partner's share of ₪187.7M.

Group. Risk GWP ₪3.75B and PHINS revenue ₪749.1M in 2031 ($203.6M at 3.68 ILS/USD), EBITDA ₪423.7M (57% margin), cumulative EBITDA ₪683.3M. Full tables are in Appendix F.

<!-- phins-chart {"categories": ["2027", "2028", "2029", "2030", "2031"], "id": "revenue_ebitda", "kind": "grouped_bars", "series": [{"color": "#0e2f63", "label": "PHINS revenue", "values": [13554000.0, 70751880.0, 211475155.5, 438529278.6, 749074460.4]}, {"color": "#9aa8bd", "label": "Opex", "values": [32400000.0, 72090000.0, 139831740.0, 230346599.0, 325398589.0]}, {"color": "#c9a04e", "label": "EBITDA", "values": [-18846000.0, -1338120.0, 71643415.5, 208182679.60000002, 423675871.4]}], "source": "group.rows[].phins_revenue, opex, ebitda", "subtitle": "Revenue − opex = EBITDA every year; 2027 is the only loss year at default factors.", "title": "Group PHINS revenue, opex and EBITDA (ILS)", "unit": "ilsm"} -->
**Group PHINS revenue, opex and EBITDA (ILS).** Revenue − opex = EBITDA every year; 2027 is the only loss year at default factors.

| Series | 2027 | 2028 | 2029 | 2030 | 2031 |
|---|---|---|---|---|---|
| PHINS revenue | ₪13.6M | ₪70.8M | ₪211.5M | ₪438.5M | ₪749.1M |
| Opex | ₪32.4M | ₪72.1M | ₪139.8M | ₪230.3M | ₪325.4M |
| EBITDA | −₪18.8M | −₪1.3M | ₪71.6M | ₪208.2M | ₪423.7M |

*Figure revenue ebitda — source: group.rows[].phins_revenue, opex, ebitda*

<!-- phins-chart {"categories": ["2027", "2028", "2029", "2030", "2031"], "id": "gwp_split", "kind": "stacked_bars", "series": [{"color": "#123f82", "label": "Carrier share", "values": [40662000.0, 220388040.0, 690701674.5, 1530009405.0, 2810449008.0]}, {"color": "#c9a04e", "label": "PHINS revenue", "values": [13554000.0, 70751880.0, 211475155.5, 438529278.6, 749074460.4]}, {"color": "#b8893b", "label": "Partner revenue", "values": [0.0, 2710800.0, 18758736.0, 71473856.4, 187741875.6]}], "source": "group.rows[].carrier_share + phins_revenue + partner_revenue = group.rows[].risk_gwp", "subtitle": "Carrier share + PHINS revenue + partner revenue = group risk GWP; savings flow is outside this bar.", "title": "Risk GWP and who keeps it (ILS)", "unit": "ilsm"} -->
**Risk GWP and who keeps it (ILS).** Carrier share + PHINS revenue + partner revenue = group risk GWP; savings flow is outside this bar.

| Series | 2027 | 2028 | 2029 | 2030 | 2031 |
|---|---|---|---|---|---|
| Carrier share | ₪40.7M | ₪220.4M | ₪690.7M | ₪1.53B | ₪2.81B |
| PHINS revenue | ₪13.6M | ₪70.8M | ₪211.5M | ₪438.5M | ₪749.1M |
| Partner revenue | ₪0.0M | ₪2.7M | ₪18.8M | ₪71.5M | ₪187.7M |
| Total | ₪54.2M | ₪293.9M | ₪920.9M | ₪2.04B | ₪3.75B |

*Figure gwp split — source: group.rows[].carrier_share + phins_revenue + partner_revenue = group.rows[].risk_gwp*

## 8. Capital plan and the round

Seed ₪6.0M on ₪24M pre-money, ₪30M post (20%). Use of funds: product and technology ₪2.4M (40%); regulatory, actuarial and reinsurance ₪1.2M (20%); distribution and local partnerships ₪1.5M (25%); operations and reserve ₪0.9M (15%).

Funding path. The anchor book's 2027 burn is ₪18.8M; the group's cumulative cash low point is ₪20.2M (2028, as the first partner market ramps). The Series A indication is that need less the seed plus a 25% buffer: ₪18.0M, rounded up to ₪0.5M. Group EBITDA turns positive in 2029 and cumulative EBITDA in 2029.

Valuation reference. The actuarial appraisal of the anchor book (PV of 2027–2029 EBITDA plus 4.0× 2029 net revenue, discounted at 35%, less 15% prudence) is ₪264.6M. The ₪24M ask is 9% of that appraisal; the same formula drives the Monte-Carlo simulator on the pitch dashboard.

<!-- phins-chart {"categories": ["2027", "2028", "2029"], "id": "cash_curve", "kind": "line", "refs": [{"color": "#b8893b", "label": "Seed ₪6M", "value": -6000000.0}, {"color": "#b23a48", "label": "Seed + Series A ₪18.0M", "value": -24000000.0}], "series": [{"color": "#0e2f63", "label": "Cumulative EBITDA (group)", "values": [-18846000.0, -20184120.0, 51459295.5]}], "source": "group.rows[].cumulative_ebitda; funding.seed; funding.series_a_indicative", "subtitle": "The low point of the curve is the peak cumulative need; the seed and the Series A indication are the reference lines.", "title": "Cumulative group EBITDA and the funding path, 2027–2029 (ILS)", "unit": "ilsm"} -->
**Cumulative group EBITDA and the funding path, 2027–2029 (ILS).** The low point of the curve is the peak cumulative need; the seed and the Series A indication are the reference lines.

| Series | 2027 | 2028 | 2029 |
|---|---|---|---|
| Cumulative EBITDA (group) | −₪18.8M | −₪20.2M | ₪51.5M |
| Seed ₪6M (reference) | −₪6.0M | −₪6.0M | −₪6.0M |
| Seed + Series A ₪18.0M (reference) | −₪24.0M | −₪24.0M | −₪24.0M |

*Figure cash curve — source: group.rows[].cumulative_ebitda; funding.seed; funding.series_a_indicative*

<!-- phins-chart {"center": "₪6M", "id": "use_of_funds", "kind": "donut", "segments": [{"color": "#0e2f63", "label": "Product & technology", "share": 0.4, "value": 2400000.0}, {"color": "#123f82", "label": "Regulatory, actuarial & reinsurance", "share": 0.2, "value": 1200000.0}, {"color": "#c9a04e", "label": "Distribution & local partnerships", "share": 0.25, "value": 1500000.0}, {"color": "#b8893b", "label": "Operations & reserve", "share": 0.15, "value": 900000.0}], "source": "funding.use_of_funds", "subtitle": "Shares are adjustable factors and must sum to 100%.", "title": "Use of the seed round (ILS)", "unit": "ilsm"} -->
**Use of the seed round (ILS).** Shares are adjustable factors and must sum to 100%.

| Segment | Amount | Share |
|---|---|---|
| Product & technology | ₪2.4M | 40% |
| Regulatory, actuarial & reinsurance | ₪1.2M | 20% |
| Distribution & local partnerships | ₪1.5M | 25% |
| Operations & reserve | ₪0.9M | 15% |

*Figure use of funds — source: funding.use_of_funds*

<!-- phins-chart {"cols": ["3.0×", "4.0×", "5.0×"], "highlight": [2, 1], "id": "appraisal_sensitivity", "kind": "heatmap", "rows": ["25%", "30%", "35%", "40%", "45%"], "source": "appraisal.sensitivity", "subtitle": "Rows: discount rate (WACC). Columns: exit multiple on 2029 net revenue. Prudence 15% throughout; the highlighted cell is the plan.", "title": "Actuarial appraisal sensitivity (ILS pre-money)", "unit": "ilsm", "values": [[255621331.1232, 335409615.936, 415197900.7488], [226321924.67000455, 297253419.33318156, 368184913.99635863], [201236815.18061265, 264575328.1207133, 327913841.06081384], [179638008.1268222, 236429733.26348403, 293221458.4001458], [160943134.67546844, 212060111.59949157, 263177088.5235147]]} -->
**Actuarial appraisal sensitivity (ILS pre-money).** Rows: discount rate (WACC). Columns: exit multiple on 2029 net revenue. Prudence 15% throughout; the highlighted cell is the plan.

| WACC \ exit multiple | 3.0× | 4.0× | 5.0× |
|---|---|---|---|
| 25% | ₪255.6M | ₪335.4M | ₪415.2M |
| 30% | ₪226.3M | ₪297.3M | ₪368.2M |
| 35% | ₪201.2M | ₪264.6M | ₪327.9M |
| 40% | ₪179.6M | ₪236.4M | ₪293.2M |
| 45% | ₪160.9M | ₪212.1M | ₪263.2M |

*Figure appraisal sensitivity — source: appraisal.sensitivity*

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

<!-- phins-chart {"axis": {"end": 2032.0, "start": 2026.5}, "id": "roadmap", "items": [{"end": 2027.5, "group": "Regulation", "kind": "bar", "label": "Regulatory pre-ruling → filing (Israel)", "start": 2026.78}, {"end": 2027.0, "group": "Capital", "kind": "bar", "label": "Seed round ₪6M on ₪24M pre", "start": 2026.75}, {"end": 2032.0, "group": "Israel", "kind": "bar", "label": "Israel sales on the carrier's paper", "start": 2027.0}, {"end": 2027.5, "group": "Israel", "kind": "milestone", "label": "Gate 6 — first 1,000 policies", "start": 2027.5}, {"end": 2028.0, "group": "Israel", "kind": "milestone", "label": "Gate 7 — 24,000 in force · Series A readiness", "start": 2028.0}, {"end": 2028.5, "group": "Capital", "kind": "bar", "label": "Series A ₪18.0M (indicative)", "start": 2028.0}, {"end": 2032.0, "group": "Partners", "kind": "bar", "label": "Partner cohort 2028 — 1 market live", "start": 2028.0}, {"end": 2032.0, "group": "Partners", "kind": "bar", "label": "Partner cohort 2029 — 2 markets live", "start": 2029.0}, {"end": 2032.0, "group": "Partners", "kind": "bar", "label": "Partner cohort 2030 — 3 markets live", "start": 2030.0}, {"end": 2032.0, "group": "Partners", "kind": "bar", "label": "Partner cohort 2031 — 3 markets live", "start": 2031.0}, {"end": 2030.0, "group": "Cash", "kind": "milestone", "label": "Group EBITDA positive (2029)", "start": 2030.0}, {"end": 2030.0, "group": "Cash", "kind": "milestone", "label": "Cumulative EBITDA positive (2029)", "start": 2030.0}, {"end": 2032.0, "group": "Partners", "kind": "milestone", "label": "10 markets on one platform", "start": 2032.0}], "kind": "gantt", "source": "GATES; partner_markets.launches; funding", "subtitle": "Dated gates, the Israel sales clock, one bar per partner-market cohort, and the derived cash gates.", "title": "Roadmap 2026–2031", "unit": "year"} -->
**Roadmap 2026–2031.** Dated gates, the Israel sales clock, one bar per partner-market cohort, and the derived cash gates.

| Track | Item | Type | When |
|---|---|---|---|
| Regulation | Regulatory pre-ruling → filing (Israel) | phase | Q4 2026 → Q2 2027 |
| Capital | Seed round ₪6M on ₪24M pre | phase | Q4 2026 → end-2026 |
| Israel | Israel sales on the carrier's paper | phase | 2027 → end-2031 |
| Israel | Gate 6 — first 1,000 policies | milestone | Q2 2027 |
| Israel | Gate 7 — 24,000 in force · Series A readiness | milestone | end-2027 |
| Capital | Series A ₪18.0M (indicative) | phase | 2028 → Q2 2028 |
| Partners | Partner cohort 2028 — 1 market live | phase | 2028 → end-2031 |
| Partners | Partner cohort 2029 — 2 markets live | phase | 2029 → end-2031 |
| Partners | Partner cohort 2030 — 3 markets live | phase | 2030 → end-2031 |
| Partners | Partner cohort 2031 — 3 markets live | phase | 2031 → end-2031 |
| Cash | Group EBITDA positive (2029) | milestone | end-2029 |
| Cash | Cumulative EBITDA positive (2029) | milestone | end-2029 |
| Partners | 10 markets on one platform | milestone | end-2031 |

*Figure roadmap — source: GATES; partner_markets.launches; funding*

## 11. Founder credentials

Insurance broker and lawyer who designed the PHINS contract family and built the operating platform end-to-end. The first conversations that matter — supervisor, appointed actuary, carrier of record, reinsurer, distribution house — require one person who can hold insurance law, actuarial form and production software at the same time; that is the founder's role in every market PHINS enters.

![Asaf Ashury, Adv. — founder portrait](/api/business-plan/founder-portrait)

**Asaf Ashury, Adv.** — Founder & CEO · PHINS Technologies

| Credential | Detail |
|---|---|
| Licensed insurance broker | Life, disability and long-term-care distribution practice in Israel; the anchor contract's 1:4 / 1:1 disability mechanism and the ADL-3 trigger are his product design. |
| Advocate (Adv.) | Israeli Bar; drafted the regulatory application memorandum in actuarial form (Draft 3.1, EN + HE) and opened the pre-ruling track with the Capital Market, Insurance and Savings Authority (12 October 2026). |
| Platform author | Built the production platform at www.phins.ai — 153 service modules, 10 API modules, 21 repositories, 14 security modules, 294 test files at this render — including the pricing kernel, the hash-chained ledger and the AI agents that recommend while humans decide. |

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
- AI operating model is built: 153 service modules, 294 test files, golden sets gating CI.

## Slide 5 — Founder
*Asaf Ashury, Adv. · Founder & CEO · PHINS Technologies*

- Licensed insurance broker and advocate; designed the contract family (1:4 / 1:1 disability mechanism, ADL-3 trigger) and drafted the regulatory memorandum in actuarial form.
- Built the production platform end-to-end — 153 service modules, 294 test files at this render; pricing kernel, hash-chained ledger, AI agents that recommend while humans decide.
- Opened the pre-ruling track with the Capital Market, Insurance and Savings Authority on 12 October 2026.

## Slide 6 — Product and pricing

- Kernel specimen: ₪313.75 life + ₪62.75 disability = ₪376.50 a month at the 1.255 age-42 factor.
- Risk GWP splits 25% PHINS / 75% carrier; savings flow is a separate licensed flow, never split.
- Published tables 0.25 / 0.20 per ₪1,000 monthly; same specimen in every market, converted at planning FX.

## Slide 7 — Market and expansion

- Israel anchor: 24,000 → 230,554 → 471,621 policies in force (2027 / 2029 / 2031).
- OECD partner markets: 1 in 2028, 3 in 2029, 9 by 2031 — 10 markets on one platform.
- Group lives 1,057,350 and risk GWP ₪3.75B in 2031.

<!-- phins-chart {"categories": ["2027", "2028", "2029", "2030", "2031"], "id": "in_force", "kind": "stacked_bars", "series": [{"color": "#0e2f63", "label": "Israel", "values": [24000.0, 94080.0, 230554.0, 356110.0, 471621.0]}, {"color": "#c9a04e", "label": "Partner markets", "values": [0.0, 12000.0, 71040.0, 245357.0, 585729.0]}], "source": "anchor_book.rows[].eoy_in_force + partner_markets.rows[].eoy_in_force = group.rows[].eoy_in_force", "subtitle": "Israel anchor book plus partner-market cohorts; the stack total is the group.", "title": "Policies in force at year end", "unit": "int"} -->
*Chart: Policies in force at year end — data in Part I and Appendix F.*

## Slide 8 — Business model

- PHINS take 25% of risk GWP pays for distribution, underwriting, claims, billing and the agents.
- Partner markets: 60% of the take to PHINS, 40% to the local partner who carries distribution.
- Opex is cost per average life by year; partner markets add 35% of Israel intensity.

## Slide 9 — Technology — one standard

- 153 service modules · 10 API modules · 21 repositories · 14 security modules (live census).
- One pricing kernel, hash-chained ledger, AI governance, evidence provenance, durable checksummed agent state, one identity writer.
- One document standard: navy / gold letterhead, shield emblem, Inter + Space Grotesk — chrome never changes figures.

## Slide 10 — Milestones

- 12 Oct 2026 pre-ruling · Q4 2026 seed close · 1 Jan 2027 sales begin.
- Gate 6 first 1,000 policies · Gate 7 24,000 in force and Series A readiness (Q4 2027).
- 2028 first partner market · 2029 group EBITDA positive · 2031 10 markets.

<!-- phins-chart {"axis": {"end": 2032.0, "start": 2026.5}, "id": "roadmap", "items": [{"end": 2027.5, "group": "Regulation", "kind": "bar", "label": "Regulatory pre-ruling → filing (Israel)", "start": 2026.78}, {"end": 2027.0, "group": "Capital", "kind": "bar", "label": "Seed round ₪6M on ₪24M pre", "start": 2026.75}, {"end": 2032.0, "group": "Israel", "kind": "bar", "label": "Israel sales on the carrier's paper", "start": 2027.0}, {"end": 2027.5, "group": "Israel", "kind": "milestone", "label": "Gate 6 — first 1,000 policies", "start": 2027.5}, {"end": 2028.0, "group": "Israel", "kind": "milestone", "label": "Gate 7 — 24,000 in force · Series A readiness", "start": 2028.0}, {"end": 2028.5, "group": "Capital", "kind": "bar", "label": "Series A ₪18.0M (indicative)", "start": 2028.0}, {"end": 2032.0, "group": "Partners", "kind": "bar", "label": "Partner cohort 2028 — 1 market live", "start": 2028.0}, {"end": 2032.0, "group": "Partners", "kind": "bar", "label": "Partner cohort 2029 — 2 markets live", "start": 2029.0}, {"end": 2032.0, "group": "Partners", "kind": "bar", "label": "Partner cohort 2030 — 3 markets live", "start": 2030.0}, {"end": 2032.0, "group": "Partners", "kind": "bar", "label": "Partner cohort 2031 — 3 markets live", "start": 2031.0}, {"end": 2030.0, "group": "Cash", "kind": "milestone", "label": "Group EBITDA positive (2029)", "start": 2030.0}, {"end": 2030.0, "group": "Cash", "kind": "milestone", "label": "Cumulative EBITDA positive (2029)", "start": 2030.0}, {"end": 2032.0, "group": "Partners", "kind": "milestone", "label": "10 markets on one platform", "start": 2032.0}], "kind": "gantt", "source": "GATES; partner_markets.launches; funding", "subtitle": "Dated gates, the Israel sales clock, one bar per partner-market cohort, and the derived cash gates.", "title": "Roadmap 2026–2031", "unit": "year"} -->
*Chart: Roadmap 2026–2031 — data in Part I and Appendix F.*

## Slide 11 — Financials (ILS)

- PHINS revenue: ₪13.6M (2027) → ₪211.5M (2029) → ₪749.1M (2031); EBITDA −₪18.8M → ₪71.6M → ₪423.7M.
- 2031 EBITDA margin 57%; cumulative EBITDA ₪683.3M.
- Anchor book alone: ₪467.5M revenue and ₪264.5M EBITDA in 2031.

<!-- phins-chart {"categories": ["2027", "2028", "2029", "2030", "2031"], "id": "revenue_ebitda", "kind": "grouped_bars", "series": [{"color": "#0e2f63", "label": "PHINS revenue", "values": [13554000.0, 70751880.0, 211475155.5, 438529278.6, 749074460.4]}, {"color": "#9aa8bd", "label": "Opex", "values": [32400000.0, 72090000.0, 139831740.0, 230346599.0, 325398589.0]}, {"color": "#c9a04e", "label": "EBITDA", "values": [-18846000.0, -1338120.0, 71643415.5, 208182679.60000002, 423675871.4]}], "source": "group.rows[].phins_revenue, opex, ebitda", "subtitle": "Revenue − opex = EBITDA every year; 2027 is the only loss year at default factors.", "title": "Group PHINS revenue, opex and EBITDA (ILS)", "unit": "ilsm"} -->
*Chart: Group PHINS revenue, opex and EBITDA (ILS) — data in Part I and Appendix F.*

## Slide 12 — The round

- Seed ₪6.0M on ₪24M pre (₪30M post, 20%). Use of funds: tech 40% · regulatory & actuarial 20% · partnerships 25% · operations 15%.
- 2027 burn ₪18.8M; peak cumulative need ₪20.2M; Series A indication ₪18.0M (2028) funds scale, not survival.
- Actuarial appraisal ₪264.6M (35% WACC, 4.0× 2029 net revenue, 15% prudence); the ask is 9% of it.

<!-- phins-chart {"center": "₪6M", "id": "use_of_funds", "kind": "donut", "segments": [{"color": "#0e2f63", "label": "Product & technology", "share": 0.4, "value": 2400000.0}, {"color": "#123f82", "label": "Regulatory, actuarial & reinsurance", "share": 0.2, "value": 1200000.0}, {"color": "#c9a04e", "label": "Distribution & local partnerships", "share": 0.25, "value": 1500000.0}, {"color": "#b8893b", "label": "Operations & reserve", "share": 0.15, "value": 900000.0}], "source": "funding.use_of_funds", "subtitle": "Shares are adjustable factors and must sum to 100%.", "title": "Use of the seed round (ILS)", "unit": "ilsm"} -->
*Chart: Use of the seed round (ILS) — data in Part I and Appendix F.*

## Slide 13 — Integrity

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

<!-- phins-chart {"id": "carrier_view", "kind": "waterfall", "source": "carrier_view.rows[2]", "steps": [{"kind": "total", "label": "Risk GWP", "value": 733348206.0}, {"kind": "delta", "label": "PHINS fee", "value": -183337051.5}, {"kind": "delta", "label": "Expected claims", "value": -454675887.71999997}, {"kind": "delta", "label": "Ceded claims", "value": 81841659.78959998}, {"kind": "delta", "label": "Ceding commission", "value": 33000669.27}, {"kind": "delta", "label": "Ceded premium", "value": -132002677.08}, {"kind": "delta", "label": "Own expenses", "value": -36667410.300000004}, {"kind": "total", "label": "Carrier result", "value": 41507508.45960002}], "subtitle": "What the carrier of record and the quota-share reinsurer see on the same GWP.", "title": "Carrier economics 2029 — Israel anchor book (ILS)", "unit": "ilsm"} -->
**Carrier economics 2029 — Israel anchor book (ILS).** What the carrier of record and the quota-share reinsurer see on the same GWP.

| Step | Amount |
|---|---|
| Risk GWP | ₪733.3M |
| PHINS fee | −₪183.3M |
| Expected claims | −₪454.7M |
| Ceded claims | ₪81.8M |
| Ceding commission | ₪33.0M |
| Ceded premium | −₪132.0M |
| Own expenses | −₪36.7M |
| Carrier result | ₪41.5M |

*Figure carrier view — source: carrier_view.rows[2]*

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
| Service modules (`services/*.py`) | 153 |
| Service packages | 6 |
| API modules (`web_portal/api_*.py`) | 10 |
| Repositories (`database/repositories/*_repository.py`) | 21 |
| Security modules (`security/*.py`) | 14 |
| Test files | 294 |
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

### F.5 Charts

<!-- phins-chart {"categories": ["2027", "2028", "2029", "2030", "2031"], "id": "gwp_split", "kind": "stacked_bars", "series": [{"color": "#123f82", "label": "Carrier share", "values": [40662000.0, 220388040.0, 690701674.5, 1530009405.0, 2810449008.0]}, {"color": "#c9a04e", "label": "PHINS revenue", "values": [13554000.0, 70751880.0, 211475155.5, 438529278.6, 749074460.4]}, {"color": "#b8893b", "label": "Partner revenue", "values": [0.0, 2710800.0, 18758736.0, 71473856.4, 187741875.6]}], "source": "group.rows[].carrier_share + phins_revenue + partner_revenue = group.rows[].risk_gwp", "subtitle": "Carrier share + PHINS revenue + partner revenue = group risk GWP; savings flow is outside this bar.", "title": "Risk GWP and who keeps it (ILS)", "unit": "ilsm"} -->
**Risk GWP and who keeps it (ILS).** Carrier share + PHINS revenue + partner revenue = group risk GWP; savings flow is outside this bar.

| Series | 2027 | 2028 | 2029 | 2030 | 2031 |
|---|---|---|---|---|---|
| Carrier share | ₪40.7M | ₪220.4M | ₪690.7M | ₪1.53B | ₪2.81B |
| PHINS revenue | ₪13.6M | ₪70.8M | ₪211.5M | ₪438.5M | ₪749.1M |
| Partner revenue | ₪0.0M | ₪2.7M | ₪18.8M | ₪71.5M | ₪187.7M |
| Total | ₪54.2M | ₪293.9M | ₪920.9M | ₪2.04B | ₪3.75B |

*Figure gwp split — source: group.rows[].carrier_share + phins_revenue + partner_revenue = group.rows[].risk_gwp*

<!-- phins-chart {"categories": ["2027", "2028", "2029"], "id": "cash_curve", "kind": "line", "refs": [{"color": "#b8893b", "label": "Seed ₪6M", "value": -6000000.0}, {"color": "#b23a48", "label": "Seed + Series A ₪18.0M", "value": -24000000.0}], "series": [{"color": "#0e2f63", "label": "Cumulative EBITDA (group)", "values": [-18846000.0, -20184120.0, 51459295.5]}], "source": "group.rows[].cumulative_ebitda; funding.seed; funding.series_a_indicative", "subtitle": "The low point of the curve is the peak cumulative need; the seed and the Series A indication are the reference lines.", "title": "Cumulative group EBITDA and the funding path, 2027–2029 (ILS)", "unit": "ilsm"} -->
**Cumulative group EBITDA and the funding path, 2027–2029 (ILS).** The low point of the curve is the peak cumulative need; the seed and the Series A indication are the reference lines.

| Series | 2027 | 2028 | 2029 |
|---|---|---|---|
| Cumulative EBITDA (group) | −₪18.8M | −₪20.2M | ₪51.5M |
| Seed ₪6M (reference) | −₪6.0M | −₪6.0M | −₪6.0M |
| Seed + Series A ₪18.0M (reference) | −₪24.0M | −₪24.0M | −₪24.0M |

*Figure cash curve — source: group.rows[].cumulative_ebitda; funding.seed; funding.series_a_indicative*

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

<!-- phins-chart {"axis": {"end": 2032.0, "start": 2026.5}, "id": "roadmap", "items": [{"end": 2027.5, "group": "Regulation", "kind": "bar", "label": "Regulatory pre-ruling → filing (Israel)", "start": 2026.78}, {"end": 2027.0, "group": "Capital", "kind": "bar", "label": "Seed round ₪6M on ₪24M pre", "start": 2026.75}, {"end": 2032.0, "group": "Israel", "kind": "bar", "label": "Israel sales on the carrier's paper", "start": 2027.0}, {"end": 2027.5, "group": "Israel", "kind": "milestone", "label": "Gate 6 — first 1,000 policies", "start": 2027.5}, {"end": 2028.0, "group": "Israel", "kind": "milestone", "label": "Gate 7 — 24,000 in force · Series A readiness", "start": 2028.0}, {"end": 2028.5, "group": "Capital", "kind": "bar", "label": "Series A ₪18.0M (indicative)", "start": 2028.0}, {"end": 2032.0, "group": "Partners", "kind": "bar", "label": "Partner cohort 2028 — 1 market live", "start": 2028.0}, {"end": 2032.0, "group": "Partners", "kind": "bar", "label": "Partner cohort 2029 — 2 markets live", "start": 2029.0}, {"end": 2032.0, "group": "Partners", "kind": "bar", "label": "Partner cohort 2030 — 3 markets live", "start": 2030.0}, {"end": 2032.0, "group": "Partners", "kind": "bar", "label": "Partner cohort 2031 — 3 markets live", "start": 2031.0}, {"end": 2030.0, "group": "Cash", "kind": "milestone", "label": "Group EBITDA positive (2029)", "start": 2030.0}, {"end": 2030.0, "group": "Cash", "kind": "milestone", "label": "Cumulative EBITDA positive (2029)", "start": 2030.0}, {"end": 2032.0, "group": "Partners", "kind": "milestone", "label": "10 markets on one platform", "start": 2032.0}], "kind": "gantt", "source": "GATES; partner_markets.launches; funding", "subtitle": "Dated gates, the Israel sales clock, one bar per partner-market cohort, and the derived cash gates.", "title": "Roadmap 2026–2031", "unit": "year"} -->
**Roadmap 2026–2031.** Dated gates, the Israel sales clock, one bar per partner-market cohort, and the derived cash gates.

| Track | Item | Type | When |
|---|---|---|---|
| Regulation | Regulatory pre-ruling → filing (Israel) | phase | Q4 2026 → Q2 2027 |
| Capital | Seed round ₪6M on ₪24M pre | phase | Q4 2026 → end-2026 |
| Israel | Israel sales on the carrier's paper | phase | 2027 → end-2031 |
| Israel | Gate 6 — first 1,000 policies | milestone | Q2 2027 |
| Israel | Gate 7 — 24,000 in force · Series A readiness | milestone | end-2027 |
| Capital | Series A ₪18.0M (indicative) | phase | 2028 → Q2 2028 |
| Partners | Partner cohort 2028 — 1 market live | phase | 2028 → end-2031 |
| Partners | Partner cohort 2029 — 2 markets live | phase | 2029 → end-2031 |
| Partners | Partner cohort 2030 — 3 markets live | phase | 2030 → end-2031 |
| Partners | Partner cohort 2031 — 3 markets live | phase | 2031 → end-2031 |
| Cash | Group EBITDA positive (2029) | milestone | end-2029 |
| Cash | Cumulative EBITDA positive (2029) | milestone | end-2029 |
| Partners | 10 markets on one platform | milestone | end-2031 |

*Figure roadmap — source: GATES; partner_markets.launches; funding*

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

## Appendix I — Data sources and figure lineage

Every class of figure in this document, where it comes from and whether it feeds the model. External research is reference only: the plan counts lives (not market size) from the kernel premium and the persistency identity, so no statistic moves a planning figure and no planning figure rewrites a statistic.

| Figure class | Source | Kind | Feeds the model | Note |
|---|---|---|---|---|
| Kernel premium (ILS 4,518) and the specimen decomposition | `services/pricing_kernel.py` with the published `risk_reference_v1` tables (life 0.25 / disability 0.20 per ILS 1,000 monthly, locked age curve) | Platform — published table | yes | Integrity identity `kernel_specimen_is_4518` fails the render if the kernel quote moves. |
| Anchor-book path: new issues 25k / 75k / 150k, persistency 92% / 96%, 25% take, opex intensity by year | `services/aspire_scale_identity.py` — the Investor Meeting book restated on every Israel pitch surface | Planning identity (reviewed) | yes | Identity `anchor_book_reconciles_to_investor_meeting` compares every year, including the five-year extension. |
| Seed ILS 6M on ILS 24M pre-money | `ROUND_SEED_ILS` / `ROUND_PRE_MONEY_ILS` in `services/business_plan_model.py` — the one writer, imported by the portal | Round terms | yes | Dilution, post-money and use of funds are derived from these two numbers. |
| Actuarial appraisal (WACC, exit multiple on 2029 net revenue, prudence) and its sensitivity grid | Same formula as `GET /api/investor/valuation-sim` (`_inv_appraisal_pre_money`) over the anchor years 2027–2029 | Planning assumption | yes | Identity `appraisal_formula_matches_valuation_sim`; the grid is the formula evaluated at ±5 / ±10 pt WACC and ±1× exit. |
| Planning FX pins and per-market specimen quotes (local currency) | `MARKET_SPECS` in `services/aspire_scale_identity.py` — pinned planning rates, never live FX | Planning pin | yes | Used only to show the same ILS specimen in local currency; no market-size inference. |
| Insurer / reinsurer economics: expected claims 62%, cession 18%, ceding commission 25%, carrier own expenses 5% | Factor register defaults (`insurer` group) — to be replaced by the carrier's and the reinsurer's term sheets | Planning assumption | yes | Appendix B and the carrier waterfall restate on every change; identity `ceded_plus_retained_equals_gwp`. |
| OECD partnership expansion: launch counts by year, 50% ramp scale, 60% platform share, 35% opex intensity | Factor register defaults (`expansion` group) | Planning assumption | yes | Zero launches collapse the group to the anchor book exactly (identity `group_equals_anchor_plus_partners`). |
| Technology census: service modules, packages, API modules, repositories, security modules, test files | Repository census at render time (`technology_census`) and `GET /api/platform/facts` in the browser | Platform fact (live) | reference only | Displayed, never typed; rebuilding the plan after a code change refreshes it. |
| Regulatory and commercial gates: pre-ruling 12 Oct 2026, seed close Q4 2026, sales clock 1 Jan 2027, Gates 6–7 | Internal meeting records (`investor-docs/regulatory-preruling-avi-ovadia-brief.md`, `investor-docs/regulatory-meeting-27jul-brief.md`) and the Investor Meeting pack | Internal record | reference only | Dates drive the roadmap chart only; the in-force path is independent of them. |
| Market context: demographics, long-term-care spend, disability prevalence, insurance market sizes by market | External research registry below — the Scenario Lab's `sourceRegistry` on the pitch dashboard | External research (reference only) | reference only | The plan plans lives, not TAM; no statistic here moves a planning figure and no planning figure rewrites a statistic. |

External research registry behind the market section — the same registry the Scenario Lab cites on the pitch dashboard, by planning market:

| Market | Source | Type · strength | Used for | URL |
|---|---|---|---|---|
| Israel | Israel National Insurance Institute — Long-term care annual report chapter | official · direct pdf | Direct official PDF chapter for Israel long-term care program context and public-benefit framing. | http://www.btl.gov.il/Publications/Skira_shnatit/2024/Documents/chap-3-04-siud.pdf |
| Israel | Taub Center — Long Term Care in Israel (2024) | analysis · synthesis | Used for Israel private LTC insured lives, public LTC beneficiary counts, and annual public LTC spend references. | https://www.taubcenter.org.il/en/research/ltc/ |
| Israel | Israel CBS Social Survey 2023 release (2024) | official · direct pdf | Used for Israel severe functional disability prevalence among adults. | https://www.cbs.gov.il/he/mediarelease/DocLib/2024/377/19_24_377b.pdf |
| Israel | OECD Health at a Glance 2025 | official · benchmark | Used for OECD long-term care comparisons, including average LTC spending, home-care orientation, and cross-country care-system benchmarks. | https://www.oecd.org/en/publications/health-at-a-glance-2025_8f9e3f98-en.html |
| Portugal | ASF Portugal — Insurance and Pension Funds Supervisory Report 2024 | official · official report | Used for Portugal insurance market size, life and non-life premium split, penetration rate, and regulatory structure under Solvency II framework. | https://www.asf.com.pt/en/entities/insurance/statistics |
| Portugal | Banco de Portugal — Financial Stability Report 2024 | official · official report | Used for Portuguese financial sector structure, macroeconomic context, household insurance holdings, and long-term care financing outlook. | https://www.bportugal.pt/en/publications/banco-de-portugal/all/381 |
| Portugal | OECD — Long-term Care Resources and Utilisation: Portugal | official · benchmark | Used for Portuguese LTC bed capacity, home-care orientation, and public expenditure benchmarking against OECD averages. | https://www.oecd.org/en/data/indicators/long-term-care-resources-and-utilisation.html |
| Portugal | INE Portugal — Demographic and Social Statistics 2024 | official · official release | Used for Portuguese population aging profile, disability prevalence estimates, and demographic dependency ratio. | https://www.ine.pt/xportal/xmain?xpgid=ine_main&xpid=INE |
| Western Europe (EUR) | Destatis — 5.7 million people needing long-term care (end-2023) | official · official release | Used for Germany long-term care scale and home-vs-institution split. | https://www.destatis.de/DE/Presse/Pressemitteilungen/2024/12/PD24_478_224.html |
| Western Europe (EUR) | Bundesrat / Germany — Pflegebeitrag 2025 | official · official release | Used for German social LTC contribution-rate change reference. | https://www.bundesrat.de/DE/plenum/bundesrat-kompakt/24/1050/31.html?nn=5492626&view=main%5BDrucken%5D |
| Western Europe (EUR) | OECD Health at a Glance 2025 | official · benchmark | Used for OECD long-term care comparisons, including average LTC spending, home-care orientation, and cross-country care-system benchmarks. | https://www.oecd.org/en/publications/health-at-a-glance-2025_8f9e3f98-en.html |
| Sweden | Socialstyrelsen — Statistics on Care and Services for the Elderly 2024 | official · official release | Used for Sweden's official 31 October 2024 counts of people aged 65+ with municipal social-service decisions, home care, and special housing. | https://www.socialstyrelsen.se/publikationer/statistics-on-care-and-services-for-the-elderly-2024-2025-4-9537/ |
| Sweden | Socialstyrelsen — Elderly receive care later (lägesrapport press note) | official · official release | Used for Sweden municipal elderly-care cost (SEK 166 billion in 2024; 2.6% of GDP) as a public-funding pressure marker. | https://www.socialstyrelsen.se/om-socialstyrelsen/pressrum/press/aldre-far-omsorg-allt-senare/ |
| Sweden | Svensk Försäkring — Premiums, claims, and market shares (2024) | industry · industry release | Used for Sweden's 2024 total insurance premiums and the life/pension versus non-life split. | https://www.svenskforsakring.se/om-forsakring/forsakringar-i-sverige/utbetalningar-premier-och-marknadsandelar/ |
| Sweden | Svensk Försäkring — Private health insurance (vårdförsäkring) 2024 | industry · industry release | Used for year-end 2024 private health-insurance lives and premium volume as a private overlay anchor, not as a PHINS product price. | https://www.svenskforsakring.se/om-forsakring/forsakringar-i-sverige/skadeforsakring/allt-fler-har-en-vardforsakring/ |
| Sweden | OECD Health at a Glance 2025 | official · benchmark | Used for OECD long-term care comparisons, including average LTC spending, home-care orientation, and cross-country care-system benchmarks. | https://www.oecd.org/en/publications/health-at-a-glance-2025_8f9e3f98-en.html |
| Canada | Statistics Canada — Disability profile (released 2024) | official · official release | Used for Canadian disability prevalence among people aged 15+. | https://www150.statcan.gc.ca/n1/pub/89-654-x/89-654-x2024001-eng.htm |
| Canada | CLHIA — Canadian Life and Health Insurance Facts 2024 | industry · direct pdf | Direct industry PDF used for Canada premium mix, insured population, and health-insurance scale. | https://www.clhia.ca/web/CLHIA_LP4W_LND_Webstation.nsf/resources/Factbook2024/$file/CLHIA-2024Facts.pdf |
| Canada | CLHIA — 2024 benefits release | industry · news release | Used for 2024 disability benefits paid and aggregate claims flow. | https://www.clhia.ca/web/CLHIA_LP4W_LND_Webstation.nsf/page/4554DF09386ECB0985258D080051020B!OpenDocument |
| Canada | CLHIA Consumer Guide — Long-Term Care Insurance | industry · consumer guide | Used for the common 2-of-6 ADL consumer trigger reference point. | https://www.clhia.ca/web/CLHIA_LP4W_LND_Webstation.nsf/resources/Consumer+Brochures/$file/Brochure_Guide_Long_Term_Care_ENG.pdf |
| United States | U.S. SSA Disability Statistical Reports 2024 | official · direct pdf | Direct official SSA PDF used for U.S. disability beneficiary counts and disabled-worker benefit statistics. | https://www.ssa.gov/policy/docs/statcomps/di_asr/2024/di_asr24.pdf |
| United States | Milliman — LTCI industry through 2024 | analysis · industry analysis | Used for U.S. stand-alone LTC insured lives and incurred-claims anchor. | https://www.milliman.com/en/insight/ltci-2024-statistics-experience-reporting-forms |
| United States | Gen Re — 2024 U.S. Individual Disability Market Survey | industry · market survey | Used for U.S. IDI new sales premium and in-force premium reference points. | https://www.genre.com/us/knowledge/publications/2025/may/surveylhidisum25-en |
| United States | LIMRA — Workplace disability sales release (Q3 2024) | industry · market release | Used for U.S. workplace disability new premium signal. | https://www.limra.com/en/newsroom/news-releases/2024/limra-workplace-life-insurance-and-supplemental-health-product-sales-continue-to-rise-in-third-quarter-2024/ |
| Australia | AIHW — People with disability in Australia (updated 2024) | official · official summary | Used for Australia disability prevalence and severe/profound disability statistics. | https://www.aihw.gov.au/reports/disability/people-with-disability-in-australia/contents/summary |
| Australia | APRA — Private health insurance membership summary (Dec 2024) | official · official release | Used for Australia insured-pool scale and current membership benchmark. | https://www.apra.gov.au/quarterly-private-health-insurance-membership-and-benefits-summary-december-2024 |
| Australia | APRA — Thematic review of individual disability income insurance | official · regulatory letter | Used to frame Australian pricing discipline and sustainability risk in DII. | https://handbook.apra.gov.au/letter/372/letter-life-insurers-thematic-review-individual-disability-income-insurance |
| Japan | MHLW Japan — Long-term care insurance and FY2024-26 premium release | official · direct pdf | Direct official PDF used for Japan average monthly LTC premium and service planning references. | https://www.mhlw.go.jp/content/12303500/001253798.pdf |
| Japan | MHLW Japan — Long-term Care Insurance in Japan | official · official summary | Used for Japan LTC system eligibility and service-user scale. | https://www.mhlw.go.jp/english/topics/elderly/care/2.html |
| Bulgaria | NSI Bulgaria — Population and Demographic processes 2025 (final) | official · official release | Used for Bulgaria's 31 December 2025 population (6,423,207), share aged 65+ (1,557,851 / 24.3%), working-age stock (3,764,842), mean age 45.4, and the 61.6% age-dependency ratio. | https://www.nsi.bg/en/press-release/population-and-demographic-processes-9002 |
| Bulgaria | FSC Bulgaria — Insurance statistics (2025 non-life files and hub) | official · official release | Official supervisory statistics hub. FY2025 market totals used in the evidence table are the FSC figures as published through this series and relayed by XPRIMM. | https://www.fsc.bg/en/insurance-activity/statistics/ |
| Bulgaria | XPRIMM — Bulgaria FY2025 GWP (citing FSC) | industry · market release | Used for the FY2025 FSC totals: BGN 5.25 billion GWP, life BGN 870 million, non-life BGN 4.38 billion, property BGN 542.13 million, and DZI Life's 29.44% life share. | https://www.xprimm.com/life/involvement/STATISTICS--BULGARIA-FY2025-Motor-insurance-remained-the-market-driver-both-in-GWP-and-paid-claims-terms-articol-15-24665.htm |
| Bulgaria | NSSI — October 2025 social-security budget execution | official · official release | Used for the public-funded lapse layer: 2,061,409 pensioners in October 2025, average pension BGN 1,006.92, and BGN 19,859.2 million pension outlays for January–October 2025. | https://noi.bg/news-budget-october-05122025/ |
| Bulgaria | Economic.bg RATE — Largest players in Bulgaria's insurance market in 2025 | industry · industry analysis | Used for the 2025 non-life ranking (Euroins, Bulstrad VIG, DZI, Lev Ins, Armeec, Generali, OZK, Allianz, Bul Ins, Groupama) and ABZ comments on motor concentration and missing income-protection depth. Not a substitute for FSC line-level files. | https://www.economic.bg/en/a/view/rate-the-largest-players-in-bulgaria-s-insurance-market-in-2025 |
| Bulgaria | OECD Health at a Glance 2025 | official · benchmark | Used for OECD long-term care comparisons, including average LTC spending, home-care orientation, and cross-country care-system benchmarks. | https://www.oecd.org/en/publications/health-at-a-glance-2025_8f9e3f98-en.html |
| UAE / Middle East (AED) | CBUAE — Annual Statistical Report for the Insurance Sector 2024 | official · direct pdf | Used for UAE health-insurance turnover and sector mix. | https://www.centralbank.ae/media/jubnwh13/annual-statistical-report-for-the-insurance-sector-2024-en.pdf |
| UAE / Middle East (AED) | CBUAE — June 2024 Quarterly Economic Review | official · direct pdf | Used for UAE retention ratio and implied cession benchmark. | https://www.centralbank.ae/media/yxlb5sot/qer_june_2024.pdf |

---

*asaf@phins.ai · phins.ai · Confidential — prepared for investors, carriers, reinsurers and supervisors. Generated from `services/business_plan_model.py` (unified-2026.10-v1); content hash `9128223e1c2223881e0eca64ae6922654b79d52bb2eed151beb726f3c4c1589f`.*
