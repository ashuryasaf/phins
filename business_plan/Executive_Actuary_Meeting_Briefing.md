# Executive Briefing — Meeting with Executive Actuary

**Owner:** Asaf (Founder, PHINS)
**Counterparty:** Executive Actuary — full member, IAA-recognised (Israel / Canada / USA)
**Date:** Tomorrow
**Duration target:** 60–90 min
**Decision sought from us:** Engagement model and scope of cooperation
**Decision sought from counterparty:** Willingness to sign as Appointed Actuary / Reviewing Actuary and (separately) personal interest in equity participation

---

## 1. Why this meeting matters

PHINS is at the boundary between *built product* and *regulated entity / funded company*. Three gates must be crossed before we can run a real book of business or raise institutional capital, and all three require a credentialed actuary's signature:

1. **Technical validation** — pricing model, reserves, capital adequacy, table sourcing.
2. **Regulatory filing** — appointed actuary opinion for the regulator(s) we choose to file in.
3. **Investor diligence** — actuarial sign-off is a non-negotiable item in any insurance / insurtech term sheet above seed stage.

A single individual qualified in **IL + CA + US** is rare and disproportionately valuable: it lets us pick our first regulatory jurisdiction by *strategy* (tax, capital, distribution) instead of by *who we can get signed*.

---

## 2. What PHINS already has (we bring this to the table)

Concrete artefacts the actuary can review on day one — this is what differentiates us from a pitch deck:

- **Unified pricing model** with documented formula, age curve, risk loadings and billing-frequency discounts (`ACTUARIAL_PRICING_MODEL.md`).
- **Actuarial service layer** — ~3,800 LOC across `services/actuarial_service.py` and `services/actuarial_valuation.py`; mortality/morbidity tables; risk-scoring engine (0–100 scale, 7 risk bands).
- **Billing & accounting engines** — `billing_engine.py` (~660 LOC) and `accounting_engine.py` (~875 LOC), with reconciliation, late fees and audit trail.
- **End-to-end platform** — policy, underwriting, claims, reinsurance, customer portal, multi-currency / 20 languages, live at `www.phins.ai`.
- **Audit logging** across policy create, UW approve/reject, claims create/approve/reject/pay — important for any appointed-actuary working file.
- **Reinsurance scaffolding** — proportional, XoL, stop-loss treaties already modelled.

Translation for the meeting: *"This is not a slide deck. You can run a portfolio through it tomorrow. We need you to tell us where the numbers don't tie out."*

---

## 3. What we need from the actuary (in order)

| Phase | Deliverable | Timing | Why it matters |
|---|---|---|---|
| A. Validation | Independent review of pricing model, age/risk loadings, base rates per line of business | First | Without this, the regulator and any VC will discount our numbers to zero. |
| B. Reserving | Method statement (BF, chain-ladder, expected loss), IBNR assumption set | Next | Required for any go-live book and for any Series A. |
| C. Capital | Solvency basis (Solvency II / RBC / Israeli capital regime) and minimum capital estimate per chosen jurisdiction | Next | Drives the size of the raise. |
| D. Filing | Signed Appointed Actuary Opinion / Statement of Actuarial Opinion for chosen regulator | After A–C | Unlocks licensing path. |
| E. Ongoing | Quarterly valuation + annual SAO | Recurring | Required for as long as we hold risk. |

---

## 4. The three engagement options — structured comparison

We evaluate each on five axes: **regulatory unlock**, **speed**, **cost/dilution**, **alignment**, **optionality preserved**.

### Option 1 — Head of Actuary (employee / officer)

**Shape.** Full-time or 0.6–0.8 FTE; title "Chief Actuary" or "Appointed Actuary"; salary + standard option pool grant (typically 0.5%–1.5% over 4-year vest with 1-year cliff for a senior hire at our stage).

| Axis | Assessment |
|---|---|
| Regulatory unlock | **High** — one signatory covers IL, CA, US filings. |
| Speed | **High** — full attention, internal. |
| Cost / dilution | Medium cash burn; low-to-moderate dilution. |
| Alignment | High (officer fiduciary duty + equity). |
| Optionality | Highest — we keep all strategic choices. |

**Best when:** the actuary's primary motivation is *operating a real insurance company* and they trust the founding team.
**Risk:** cash burn before revenue; conflict if they also want founder-level influence without founder-level commitment.

### Option 2 — Junior Co-founder

**Shape.** Co-founder title, board seat or board observer, equity in the **3%–8%** range (heavily dependent on whether they bring (a) full-time commitment, (b) capital, (c) regulated-entity sponsorship, or (d) all three), 4-year vest, 1-year cliff, founder reverse-vesting on existing equity to keep alignment symmetric.

| Axis | Assessment |
|---|---|
| Regulatory unlock | **High** + credibility halo at fundraising. |
| Speed | **Highest** — co-owner urgency. |
| Cost / dilution | Low cash, **high dilution**. |
| Alignment | Highest if full-time; **dangerous** if part-time. |
| Optionality | Reduced — co-founder is a long-term, hard-to-reverse decision. |

**Best when:** the person is willing to go full-time, brings something *no employee could* (e.g. anchor regulator relationship, named-partner credibility for a Series A, or LP/angel capital), and is personally compatible at the founder level.

**Critical guardrails:**

- Equity sized to **contribution + risk taken**, not title.
- Strict vesting + good-leaver / bad-leaver clauses.
- IP assignment and non-compete from day one.
- Clear written delineation of decision rights vs the existing founder.

**Red flag heuristic:** if they ask for co-founder title *and* a salary at market rate *and* part-time hours, decline. Pick at most two.

### Option 3 — PHINS-for-Actuaries: a B2B platform

**Shape.** Productise the actuarial engine, valuation workbench, mortality/morbidity table library, reserving and reporting modules as a separate SaaS offering — sold to independent actuaries, small mutuals, captives, MGAs, and consulting firms. The actuary becomes either **design partner**, **commercial lead**, or **JV partner** on this vertical.

| Axis | Assessment |
|---|---|
| Regulatory unlock | **Low** by itself — does not replace an Appointed Actuary for our own carrier ambitions. |
| Speed to revenue | **Fastest** path to recurring revenue (SaaS) without holding insurance risk. |
| Cost / dilution | Low if structured as JV or rev-share; medium if structured as a product line under PHINS. |
| Alignment | Medium — risk of focus split between "be a carrier" and "be a tools vendor". |
| Optionality | Highest commercially — opens a market segment most insurtechs ignore. |

**Strategic note.** This is the *non-obvious* and possibly the **most valuable** option. Reasoning:

- The global actuarial software market is dominated by a handful of expensive incumbents (Prophet, AXIS, MoSes, RAFM, Polysystems). Most independent and mid-market actuaries are still on Excel + bespoke scripts.
- PHINS already has the spine: pricing engine, reserving primitives, audit trail, multi-currency, multi-jurisdiction.
- A credentialed actuary as design partner is the missing piece to make this credible to peers.
- Revenue from this vertical can **fund** the carrier ambition rather than dilute it.

**Best when:** the counterparty has a large peer network and is excited by "building the tool I always wished I had."

### Side-by-side scorecard

| Criterion (weight) | Head of Actuary | Junior Co-founder | Actuary Platform |
|---|---|---|---|
| Unlocks regulatory filing (high) | ●●● | ●●● | ● |
| Unlocks Series A diligence (high) | ●●● | ●●● | ●● |
| Speed to first revenue (medium) | ●● | ●● | ●●● |
| Founder dilution (high) | ●● | ● | ●●● |
| Cash burn (medium) | ● | ●● | ●●● |
| Reversibility if it doesn't work (medium) | ●●● | ● | ●●● |
| Strategic optionality (medium) | ●●● | ● | ●●● |

`●●●` = strongly positive, `●` = strongly negative.

---

## 5. Recommended path — **a hybrid, sequenced offer**

Do not present the three options as mutually exclusive. The honest answer is: **we want option 1 immediately, we are open to option 2 if the person earns into it, and option 3 is a shared upside we build together.**

Concretely, propose this in the meeting:

1. **Immediate (this quarter):** Engage as **Consulting / Appointed Actuary** under a paid contract (day-rate or fixed-fee per deliverable in §3). This validates fit on both sides without anyone making an irreversible decision. Deliverable 1 = independent review of `ACTUARIAL_PRICING_MODEL.md` and the actuarial service layer.
2. **Conditional (after 60–90 days of working together):** Convert to **Chief Actuary / Head of Actuary** with officer title, salary, and an option grant in the 0.75%–1.5% band (vesting from start of consulting engagement).
3. **Optional, parallel track:** Launch **PHINS-for-Actuaries** as a co-led initiative. Offer either (a) a meaningful equity uplift conditional on hitting revenue milestones for that product line, or (b) a JV / rev-share if they prefer to remain external and bring their network.
4. **Co-founder upgrade:** Left open as an *earned* outcome — if they go full-time, contribute commensurately, and we genuinely operate as partners, we revisit a co-founder grant at the next equity event (e.g. priced round). Avoid handing out the title on day one.

This structure protects the cap table, keeps the regulatory path moving, and gives a top-tier candidate a credible runway to a co-founder seat without forcing the decision before there is evidence.

---

## 6. Valuing the opportunity (the actuary's side of the table)

Anticipate how they will frame value and have answers ready.

- **What they get from us:** a working platform (not a spec), a real product surface to put their name on, a multi-jurisdiction launch optionality, and — uniquely — a second business line (actuary SaaS) where they can become a category-shaping figure.
- **What they will worry about:**
    - Professional liability on signing the SAO before the model is independently reviewed → answered by §5 step 1.
    - Capital runway → answered by the planned raise (we should know the target number before the meeting).
    - Founder dynamics → answered by clear written terms, not by charisma.
    - Whether the tech is real → answered by a live demo, ideally running a sample portfolio end-to-end.

---

## 7. Pre-meeting checklist (do today)

- [ ] Confirm which **jurisdiction we file first** (IL is fastest culturally; US state-by-state is hardest; CA is mid). The actuary's answer to "where should we file first?" is itself a strong signal.
- [ ] Have a **clean data extract** ready: pricing examples (the ASAF $500K / age 47 / moderate-risk worked example is a good one), a sample reserving dataset, and the audit-log export.
- [ ] Prepare a **one-page architecture** (we have it: `PLATFORM_ARCHITECTURE_UML.md`) and a **one-page pricing model** (we have it: `ACTUARIAL_PRICING_MODEL.md`).
- [ ] Draft a **mutual NDA** before sharing the actuarial service code and table library.
- [ ] Have a **consulting agreement template** ready to sign on the spot if there is chemistry — paid by deliverable, with explicit IP assignment, with a 30-day mutual exit.
- [ ] Decide internally on the **walk-away terms**: minimum equity we will offer for co-founder; maximum cash day-rate for consulting; any non-negotiables on board composition.

---

## 8. Suggested agenda for the meeting

1. **10 min — Context.** Where PHINS is, what's live, what's not.
2. **15 min — Live demo.** End-to-end policy → underwriting → billing → claim → reinsurance, with the audit log visible. Show the actuarial dashboard.
3. **15 min — Their diagnosis.** Open-ended: *"Given what you just saw, what would you sign today, what would you refuse to sign, and what would you want to rebuild?"* Listen carefully — this is the real interview.
4. **15 min — Regulatory path.** Discuss IL vs CA vs US first-filing, capital implications, and timing.
5. **15 min — Engagement options.** Present §5 hybrid path. Do **not** lead with co-founder equity.
6. **10 min — Personal fit & next steps.** Sign consulting NDA + scope-of-work for deliverable 1. Set the next meeting date.

---

## 9. Risks and red flags to watch for

- **Title-first ask.** Demands "co-founder" or "CIO" before any work has been done together → counter with the hybrid path; if refused, walk.
- **Reluctance to put name on a working file.** Many actuaries will not sign anything they did not personally build. Decide in advance whether you are willing to let them rebuild parts of the pricing engine — it may be the right answer.
- **Single-jurisdiction bias.** If they only want to file where their primary licence is, you lose the optionality that made them attractive.
- **Over-promising on fundraising help.** Investor introductions are nice, not a substitute for technical work. Don't trade equity for a Rolodex.
- **Conflicts of interest.** If they consult to a competing carrier or insurtech, you need explicit carve-outs in writing.

---

## 10. Decision outputs you should leave the meeting with

1. A signed (or hand-shook) **consulting engagement** for deliverable 1 — review of pricing model and actuarial service layer.
2. A shared view on the **first filing jurisdiction**.
3. A shared view on whether the **PHINS-for-Actuaries** product line is something they personally want to lead, partner on, or stay away from.
4. A **next meeting on the calendar**, ideally within two weeks, with the deliverable-1 review as the agenda.
5. An honest internal read on whether this person is a **Chief Actuary** (hire), a **co-founder** (rare, earned), or a **vendor relationship**. Write the answer down within an hour of the meeting ending, before impressions fade.

---

## Bottom line for tomorrow

Lead with the product, not the cap table. Offer paid, scoped consulting today; signal the Chief Actuary path as the default destination; keep co-founder equity as an earned upgrade; and put the actuary-SaaS opportunity on the table as a shared upside that could change the funding story entirely. That sequence maximises the chance of getting them signed *and* protects PHINS's optionality on regulator, raise size, and ownership.

---

*Prepared for internal use. Do not share with counterparty before the meeting.*
