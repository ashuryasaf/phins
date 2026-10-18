# 21st-century insurers, reinsurers and their partners — and the PHINS "Techno Yes" plan

Research memo and long-term architecture cost plan behind the **Techno Yes** tab of the
IL pitch dashboard (`web_portal/static/pitch-dashboard.html`, section `#techno-yes-section`).
Public evidence is dated and sourced; PHINS figures are planning assumptions and are marked
as such. Nothing here changes the actuarial identity, the pricing kernel or any stored record.

Companion document: the repository-vs-recommendation review that preceded this plan
(stack census, 20-area comparison, workstreams W1–W12) is summarised in section 5.

---

## 1. What the new-age insurer looks like (evidence, 2025–2026)

### 1.1 Three operating models, three different fates

| Model | Who | 2026 evidence | Reading |
|---|---|---|---|
| Full-stack carrier, direct, AI-native | Lemonade | Q2 2026 in-force premium $1.43B (+32%), net loss $43M, adj. EBITDA −$19M, LAE ratio 5%, quota-share cession cut to ~18%; new Hannover Re "synthetic agents" growth facility up to $250M at ~9.8% from Jan 2027; 1,282 employees (YE 2025), ~$965k IFP per employee; technology development $30.0M in Q2 2026 (~8% of IFP annualised) | Automation is real (claims cost, headcount), but balance-sheet growth consumes capital and the reinsurer ends up financing both the risk and the marketing |
| Full-stack carrier, embedded distribution | Root | Q2 2026 net income $25.4M, net combined ratio 92.1%, PIF $1.43B; 1,256 employees (~$1.17M PIF/employee); Carvana embedded agreement extended Sep 2026 with milestone warrants | Profitability arrived in 2024, six years after launch, and only with partner distribution (about half of new business) |
| Carrier pivoting to platform / hybrid fronting | Hippo | Q2 2026 GWP $482M (+61%), net retention 38%, net income $10.1M, combined ratio 95.8%, technology and development $10.1M (~2% of GWP); homeowners now third line by premium | Fee and fronting income stabilise results faster than retained risk |
| Capital-light life platform (agency + TPA) | Ethos | IPO 30 Jan 2026 at $19 (~$200M offering); carriers Banner Life, Protective, Ameritas, TruStage; Munich Re reinsures Banner policies; Q2 2026 revenue $189.6M, net income $19.5M; 95% of applicants underwritten instantly | The closest public analogue to the PHINS MGA layer: owns underwriting software and distribution, leaves mortality on carrier balance sheets |
| Carrier-path insurtech that unwound | Dayforward | Became a Texas-licensed carrier (Munich Re reinsured); Sep 2026 Fortitude Re bought the platform, agency and team but **excluded the insurance entities and legacy liabilities** | The technology kept its value; the early carrier licence did not |
| Already-profitable regional carrier | Slide | IPO June 2025; Q2 2026 GWP $508M, combined ratio 57.6% | The IPO window reopened for profitable or risk-free models only |

### 1.2 The reinsurer loop

- **Munich Re / ERGO** bought NEXT Insurance (Israeli-founded, 2024 top line $548M, ~700 staff) for **$2.6B**, closed 1 July 2025 (~4.7× top line); rebranded ERGO NEXT in Jan 2026. ERGO had held 29% before the deal.
- **Munich Re / HSB** agreed to buy At-Bay (US + Israel, ~280 staff, $278M GWP) for **$575M** in Aug 2026 (~2.1× premium); HSB had been At-Bay's strategic partner since 2017.
- **Swiss Re** is winding down **iptiQ**, its B2B2C white-label digital insurer: European P&C sold to Allianz Direct (Nov 2024), Australia to Hannover Re (Apr 2025).
- **Hannover Re** funds Lemonade's customer acquisition from 2027; **Fortitude Re** (Carlyle / T&D) bought Dayforward for an origination channel and took $3.4B of Unum LTC reserves (2025).
- Reinsurers and insurers made **162 technology investments in 2025** (27 in Q2 2026) and are the buyers when the insurtech matures (Gallagher Re).

Sequence observed since 2021: venture funds the AI-labelled start-up → a reinsurer takes the risk (quota share) → the reinsurer finances growth → a reinsurer-owned primary buys the company.

### 1.3 Fronting and MGA capacity

Conning (Aug 2026): fronted premium grew 17% in 2025 to >$22B (3.5× the commercial market), but initial accident-year loss ratios have developed adversely in **each of the last seven accident years**; ~$19B was ceded to non-affiliated reinsurers; five fronts have exited and the top ten hold ~69% of MGA-dedicated premium. Programme selection, credit controls and operating depth now decide who keeps capacity.

### 1.4 Life and long-term care

- Traditional US LTC sales fell ~96% in two decades (732k policies in 2001 → ~27k in 2022); life/LTC combination products were 67% of new LTC policies in 2024 (LIMRA).
- **CareScout** (Genworth) launched a fully digital standalone LTC product (Oct 2025; ages 40–65, $50k–$250k benefit, A+ reinsurer) bundled with a vetted care network — an incumbent re-entering standalone LTC with a digital stack.
- **Assured Allies** sells carriers an LTC platform (digital underwriting, wellness-based claims reduction of ~7%, +1.1% IRR) built over a decade for ~$50M — the clearest example of an LTC *technology layer* licensed to carriers.
- LTC reinsurance is active again: $9.7B of standalone LTC reserves ceded 2024–25 (Manulife / Global Atlantic $4.4B, Manulife / RGA $1.9B, Unum / Fortitude Re $3.4B), plus Lincoln / Fortitude Re ($28B incl. MoneyGuard hybrid LTC). Capacity for severity LTC exists at the right structure.

### 1.5 Capital, distribution and regulation

- Gallagher Re Q2 2026: $2.44B insurtech funding across 107 deals, **99.1% to AI-labelled companies**; 12.1% of P&C deals went to insurtechs that are themselves licensed insurers (highest since 2014). 2025 total $5.08B vs. the $15.8B 2021 peak.
- McKinsey (Jul 2026): ~85% of US P&C and ~95% of US life premium is distributed through agents, brokers and MGAs — a direct-only model competes for the remainder.
- **EU AI Act**: AI for risk assessment and pricing of natural persons in life and health insurance is Annex III high-risk; Regulation (EU) 2026/1744 (Digital Omnibus) moved the compliance date to **2 December 2027**. NAIC's AI model bulletin is adopted in 26 US jurisdictions (Aug 2026); Colorado SB21-169 requires unfair-discrimination testing of models.
- **Israel (CMISA)**: 18 licensed insurers; two fully digital licences (Libra 2018, Wesure), both **general lines only**; eight insurers write life savings; Ayalon took the Clalit LTC initiative in 2026. There is no digital life/LTC carrier in Israel.

---

## 2. Prediction — where the move goes (2027–2031)

1. **Capital-light platforms set the valuation benchmark.** Public markets reward companies with no insurance risk (Ethos) or fees and fronting (Hippo) over full-stack growth (Lemonade). A full-stack licence is justified only after automated selection has proven itself over a cycle.
2. **The reinsurer becomes the venture partner, capacity, growth lender and eventual acquirer.** Expect more Munich Re / Hannover Re / RGA / SCOR / Fortitude Re structures: quota share from day one, data access in exchange for capacity, acquisition at 2–5× top line for AI-native platforms.
3. **Fronting consolidates on quality.** Fewer, better-capitalised fronts; MGAs must show reserving discipline, credit controls and audit trails to keep capacity.
4. **Life and LTC go digital through hybrids and severity layers.** Standalone LTC returns digitally (CareScout) and wellness / care-navigation becomes a licensable layer (Assured Allies). A permanent 3+ ADL severity product with care orchestration sits exactly in that gap.
5. **AI governance turns from cost into a sales asset.** By December 2027 any EU life/health pricing model needs conformity evidence; carriers will buy or rent governed AI rather than build it.
6. **Distribution stays intermediated.** Winning platforms serve agents and brokers with software (Ethos: 10,000 agents) rather than bypassing them.
7. **Exit and partnership logic favours Israeli-born platforms with reinsurer ties.** NEXT and At-Bay are the template: reinsurer stake early, full acquisition once profitable.

**PHINS move predicted by this evidence:** operate as an MGA / platform first (25% PHINS, 75% carrier — the Aspire pack identity), secure reinsurer-backed capacity and a data room early, license the AI-governance and ADL evidence stack to carriers, and keep the insurer option open behind explicit gates rather than a date.

---

## 3. Full-scale plan — business, partners, technology, gates

| Horizon | Business posture | Partners to sign | Technology deliverables | Gate to the next horizon |
|---|---|---|---|---|
| **H0 — Harden** (Y1 first half) | Pre-partner; demo book | Pen-test firm, fractional actuary, counsel on MGA/agency licence | Fail-closed persistence, shared operational state, ASGI strangler with OpenAPI, Alembic + tenant columns, object storage, OIDC issuer, OpenTelemetry, pytest in CI, load baseline | First carrier term sheet; pen-test findings closed |
| **H1 — Partner-ready MGA** (Y1 second half – Y2) | Agency/MGA under a licensed Israeli carrier; PHINS 25% / carrier 75% | One composite carrier (Harel / Phoenix / Menora / Clal / Ayalon class), one reinsurer quota-share (Munich Re, Hannover Re, RGA or SCOR), 1–2 distributors (agencies, employer groups), marketplace suppliers | Carrier boundary (issue vs. mirror), partner API + generated TypeScript SDK, broker/agent portal, externalised product definitions (effective-dated, carrier-keyed), consent + retention schedules, dbt read replica | ≥ 24,000 in-force, loss-ratio evidence accepted by the reinsurer, SOC 2 Type I |
| **H2 — Scale with reinsurer-backed capacity** (Y3) | Multi-carrier MGA; second market entry (Portugal / EU or US via fronting) | Second carrier or fronting partner, second reinsurer layer, care-network and VR providers, billing/payment and investment custodians | Durable workflows (Temporal or Postgres-native), multi-region AWS with IaC, warehouse + partner exports, fronting-grade controls (reserving monitors, credit controls, adverse-development alerts), EU AI Act conformity file ready before 2 Dec 2027 | ≥ 160,000 average in-force, two capacity providers, SOC 2 Type II / ISO 27001, AI conformity assessment passed |
| **H3 — Insurer option** (Y4–Y5) | Board decision: own licence vs. remain MGA/platform | Regulator (CMISA business plan, reinsurance programme), capital providers, PAS vendor if "buy" | Policy-administration decision (Python modular core vs. buy a PAS), chart of accounts and period close, multi-currency, DR, IFRS 17 / solvency reporting, technology licensing line (AI governance stack, ADL evidence pipeline) | Regulatory capital secured (outside this plan); licence granted |

---

## 4. Techno Yes — long-term technology cost plan (ILS)

Scale and opex come from the unified five-year identity in `services/aspire_scale_identity.py`
(average in-force 12,000 → 413,866; risk premium ILS 4,518). Technology costs are planning
assumptions at indicative Israeli 2026 rates; licence capital, reinsurance and distribution
commissions are **excluded**.

| Year | Avg in-force | Risk GWP | Plan opex | Tech FTE | Personnel | AI dev tokens + seats | AI runtime inference | Cloud, storage, observability, IdP | Security, compliance, audits | Actuarial + regulatory tech advisory | **Tech total** | % GWP | % opex | PAS "buy" option (not in total) | Electricity memo (MWh) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 12,000 | 54,216,000 | 32,400,000 | 2.2 | 1,452,000 | 120,000 | 60,000 | 200,000 | 250,000 | 200,000 | **2,282,000** | 4.21% | 7.04% | — | 1.5 |
| 2 | 59,040 | 266,742,720 | 66,420,000 | 5.0 | 3,300,000 | 250,000 | 150,000 | 600,000 | 400,000 | 350,000 | **5,050,000** | 1.89% | 7.60% | — | 5 |
| 3 | 162,317 | 733,348,206 | 116,868,240 | 8.0 | 5,376,000 | 350,000 | 300,000 | 1,400,000 | 600,000 | 500,000 | **8,526,000** | 1.16% | 7.30% | — | 15 |
| 4 | 293,332 | 1,325,273,976 | 169,637,783 | 11.0 | 7,524,000 | 450,000 | 350,000 | 2,200,000 | 800,000 | 700,000 | **12,024,000** | 0.91% | 7.09% | 3,000,000 | 30 |
| 5 | 413,866 | 1,869,846,588 | 202,927,845 | 14.0 | 9,744,000 | 550,000 | 400,000 | 3,000,000 | 1,000,000 | 800,000 | **15,494,000** | 0.83% | 7.64% | 3,500,000 | 50 |
| **5-yr** | | 4,249,427,490 | | | 27,396,000 | 1,720,000 | 1,260,000 | 7,400,000 | 3,050,000 | 2,550,000 | **43,376,000** | **1.02%** | | 6,500,000 | 101.5 |

Benchmarks: carrier IT spend 1.8–4.2% of GWP (VendorBenchmark 2026); Lemonade technology
development ≈ 8% of in-force premium (Q2 2026); Hippo technology and development ≈ 2% of GWP
(Q2 2026). PHINS lands at ~1% of GWP because the MGA model carries no claims-paying core and
because agents perform most implementation; a **×1.5 contingency** (≈ 65M ILS over five years,
~1.5% of GWP) is the prudent board figure.

Cost assumptions: loaded engineer 55–58k ILS/month; AI coding at a blended $4–8 per million
tokens plus seats; runtime inference 20–60k tokens per underwriting or claims case bounded by
the existing `PHINS_AI_DAILY_*` budgets; electricity 1–2 Wh per 1k tokens and 60–100 W per
always-on container, reported as a memo because it is already inside the cloud and token prices.
PAS "buy" is a Socotra/Sapiens-tier SaaS estimate ($0.5–1M per year) and applies only if H3
chooses to buy rather than build on the existing Python ledger, billing and kernel.

---

## 5. Where the current codebase stands (from the architecture review)

- ~370k lines of Python backend plus 106k lines of tests; stdlib `BaseHTTPRequestHandler` with ~534 API routes in a 63.5k-line handler; 92 hand-written HTML pages; Postgres via SQLAlchemy with an in-memory fallback; 33 legacy Business Central AL files.
- Aligned with the recommended target: Python for AI/actuarial/BI, Postgres, outbox-before-broker, hash-chained ledger, pricing kernel as single writer, AI governance (prompt provenance, schema-validated output, golden sets, audited thresholds, drift).
- Gaps closed by H0/H1: API contract, tenant/carrier boundary, object storage, observability, CI running the suite, OIDC, migrations.
- Deliberately rejected: a Java/.NET transaction core and a Next.js rewrite; the H3 question is build a Python modular core vs. buy a PAS.

---

## 6. Sources (public, dated)

- Lemonade, Q2 2026 shareholder letter (SEC 8-K exhibit), Aug 2026 — https://www.sec.gov/Archives/edgar/data/1691421/000169142126000047/lmndshareholderletterq22.htm
- Hippo Holdings, Q2 2026 earnings release and Form 10-Q, Jul–Aug 2026 — https://www.sec.gov/Archives/edgar/data/1828105/000182810526000041/q226earningsreleasefinal.htm
- Analysis Atlas, "Insurtech 2026: Lemonade, Root and AI Underwriting", Sep 2026 — https://analysis-atlas.com/research/insurtech-digital-insurance-market/
- TechCrunch, "How Sequoia-backed Ethos reached the public market", 29 Jan 2026 — https://techcrunch.com/2026/01/29/how-sequoia-backed-ethos-reached-the-public-market-while-rivals-fell-short/
- Ethos, carrier partners and trust pages, 2026 — https://www.ethos.com/carriers/
- ERGO Group, "ERGO successfully finalizes the full acquisition of NEXT Insurance", 1 Jul 2025 — https://www.ergo.com/en/newsroom/media-information/2025/20250701-ergo-acquisition-next-insurance
- Life Insurance International, "Munich Re to acquire At-Bay for $575m", 19 Aug 2026 — https://www.lifeinsuranceinternational.com/news/munich-re-acquire-at-bay-575m/
- Reinsurance News, "Swiss Re's iptiQ signs agreement to sell Australian business to Hannover Re", 10 Apr 2025 — https://www.reinsurancene.ws/swiss-res-iptiq-signs-agreement-to-sell-australian-business-to-hannover-re/
- Insurance Business, "Fortitude Re buys Dayforward", 29 Sep 2026 — https://www.insurancebusinessmag.com/reinsurance/news/breaking-news/fortitude-re-buys-dayforward-to-build-its-own-annuity-origination-platform-591544.aspx
- Insurance Business, "Conning: fronting sector's easy growth phase is ending", 31 Aug 2026 — https://www.insurancebusinessmag.com/us/news/breaking-news/conning-fronting-sectors-easy-growth-phase-is-ending-587956.aspx
- Genworth / CareScout, "CareScout Launches Care Assurance", 1 Oct 2025 — https://investor.genworth.com/news-events/press-releases/detail/1045/carescout-launches-care-assurance-first-insurance-solution
- Assured Allies, company site, 2026 — https://assuredallies.com/
- Dealer Re, "Long-Term Care Reinsurance: Key Industry Insights" (Milliman Feb 2026 analysis), 29 May 2026 — https://dealerre.com/feeds/blog/ltc-reinsurance
- LIMRA, "Meeting Industry Demand: Long-Term Care Product Innovation", 2024 — https://www.limra.com/globalassets/limra-loma/events-learning-and-networking/conferences/2024/life-insurance--annuity-conference/presentations/session-4.1-combination-and-hybrid-ltc-product-innovation---meeting-industry-and-ltc-state-program-needs.pdf
- Gallagher Re, Global InsurTech Report Q2 2026, Aug 2026 — https://www.ajg.com/gallagherre/news-and-insights/global-insurtech-report-q2-2026/
- Cloud Security Alliance, "EU AI Act's High-Risk Deadline: Deferred, Not Cancelled" (Regulation (EU) 2026/1744), Aug 2026 — https://labs.cloudsecurityalliance.org/research/csa-research-note-eu-ai-act-high-risk-deadline-omnibus-20260/
- EIOPA, letter on the AI Act and EU insurance legislation, 2026 — https://www.eiopa.europa.eu/document/download/b67ede29-8217-46df-bb46-526e004d34bb_en
- Insurers Global, "Licensed insurance companies in Israel (2026)" (CMISA register), Sep 2026 — https://insurers.global/insights/licensed-insurance-companies-israel-2026/
- Ctech / Calcalist, interview on Ayalon and the Clalit LTC initiative, 2026 — https://www.calcalistech.com/ctechnews/article/vlrnxvybl
- VendorBenchmark, "Insurance Software Pricing Benchmark 2026" — https://vendorbenchmark.com/guides/insurance-software-pricing-benchmark
- Finantrix, "Policy Administration Systems for P&C Insurance" (vendor price bands) — https://www.finantrix.com/buyer-guides/policy-administration-systems-pc-insurance

Last updated: 17 October 2026.
