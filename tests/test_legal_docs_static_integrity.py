"""
Static-integrity tests for the adjustable legal/corporate/funding document suite.

These read the shipped static assets (no server required) and assert that:
- the shared engine (CSS/JS) and hub page exist and contain the integrity features,
- all 15 document templates exist, include the engine, declare a docType,
  expose their key adjustable fields, and define at least one signatory,
- the documents are wired into the hub, the pitch dashboard's Investor Documents
  section, and the Israel (IL) pitch.
"""

from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"
LEGAL = STATIC / "legal"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# (filename, docType, [substrings that must appear])
DOCS = [
    ("term-sheet.html", "term-sheet", ["investmentAmount", "preMoney", "valuationCap", "liquidationPref"]),
    ("founder-agreement.html", "founder-agreement", ["founderAEquity", "vestingYears", "cliffMonths"]),
    ("cap-table.html", "cap-table", ["holders", "esopPool", "Fully-diluted"]),
    ("employment-agreement.html", "employment-agreement", ["salary", "accessTier", "Actuary", "Claims Adjuster"]),
    ("esop-agreement.html", "esop-agreement", ["optionsGranted", "strikePrice", "vestingYears", "exerciseWindowDays"]),
    ("financial-model.html", "financial-model", ["monthlyPremium", "lossRatio", "reserveCoverage", "{{html:projection}}"]),
    ("nda.html", "nda", ["counterpartyName", "mutual", "confidYears"]),
    ("incorporation-delaware.html", "incorporation-delaware", ["authorizedShares", "parValue", "regAgent", "Delaware"]),
    ("cofounder-exit-clause.html", "cofounder-exit-clause", ["vestedShares", "goodPrice", "badPrice", "nonCompeteMonths"]),
    ("shareholders-agreement.html", "shareholders-agreement", ["dragThreshold", "rofrDays", "shareholders"]),
    ("ip-assignment.html", "ip-assignment", ["assignorName", "priorInventions"]),
    ("trademark-ip.html", "trademark-ip", ["classes", "ipassets", "PHINS"]),
    ("offer-letter.html", "offer-letter", ["salary", "offerExpiry", "optionGrant"]),
    ("hr-policies.html", "hr-policies", ["remotePolicy", "ptoDays", "Data Security"]),
    ("legal-compliance.html", "legal-compliance", ["controls", "AML", "attest"]),
]

# Documents whose context selector must offer audience-aware variants.
CONTEXT_DOCS = {
    "term-sheet.html": ["investor", "investment"],
    "employment-agreement.html": ["employee", "contractor"],
    "nda.html": ["investor", "employee", "supplier"],
    "ip-assignment.html": ["employee", "founder", "contractor"],
}


def test_engine_and_hub_assets_exist():
    assert (LEGAL / "legal-docs.css").is_file()
    assert (LEGAL / "legal-docs.js").is_file()
    assert (STATIC / "corporate-legal-dashboard.html").is_file()


def test_engine_js_has_integrity_and_signature_features():
    js = _read(LEGAL / "legal-docs.js")
    # live signature pad (draw + typed)
    assert "ld-sig-pad" in js and "toDataURL" in js
    assert "data-sigtyped" in js
    # SHA-256 content hashing via Web Crypto
    assert "crypto.subtle" in js and "SHA-256" in js
    # ledger anchoring + verify + registry endpoints
    assert "/api/legal-docs/sign" in js
    assert "/api/legal-docs/verify" in js
    # lock-after-sign + date capture + tamper detection
    assert "lockedHash" in js
    assert "signedAt" in js
    assert "Signed on" in js
    assert "tampered" in js
    # print to PDF
    assert "window.print" in js


@pytest.mark.parametrize("fname,doctype,needles", DOCS)
def test_each_document_is_wellformed(fname, doctype, needles):
    p = LEGAL / fname
    assert p.is_file(), f"missing {fname}"
    html = _read(p)
    # includes the shared engine + css and initializes the doc
    assert '/legal/legal-docs.js' in html
    assert '/legal/legal-docs.css' in html
    assert "PhinsLegalDoc.init" in html
    assert f'docType: "{doctype}"' in html
    # declares signatories (at least one signature panel) and contexts
    assert "signatories:" in html
    assert "role:" in html
    assert "contexts:" in html
    # disclaimer is injected by the engine; doc must carry its key adjustable fields
    for needle in needles:
        assert needle in html, f"{fname} missing expected content: {needle}"


@pytest.mark.parametrize("fname,contexts", list(CONTEXT_DOCS.items()))
def test_context_variants_present(fname, contexts):
    html = _read(LEGAL / fname)
    for ctx in contexts:
        assert f'id: "{ctx}"' in html, f"{fname} missing context '{ctx}'"


def test_hub_links_every_document():
    hub = _read(STATIC / "corporate-legal-dashboard.html")
    for fname, _doctype, _ in DOCS:
        assert f"/legal/{fname}" in hub, f"hub missing link to {fname}"
    # hub advertises the integrity guarantees
    assert "live signature" in hub.lower()
    assert "ledger" in hub.lower()


def test_pitch_dashboard_surfaces_legal_center():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert "/corporate-legal-dashboard.html" in pd
    # inside the investor documents section, with quick links to key docs
    assert "Corporate, Legal &amp; Funding Documents" in pd
    assert "/legal/term-sheet.html" in pd
    assert "/legal/cap-table.html" in pd


def test_pitch_dashboard_investor_meeting_section():
    pd = _read(STATIC / "pitch-dashboard.html")
    # Meir Uzan investor meeting section + nav links
    assert 'id="investor-meeting-section"' in pd
    assert "Mr. Meir Uzan" in pd
    assert "11 June 2026" in pd and "Herzliya" in pd
    # tested business-plan assumptions and 1 Jan 2027 sales start
    assert "1 Jan 2027" in pd
    # build budget reconciles to the round size (figures are computed live from
    # the canonical ILS base, so assert the base value + the section heading)
    assert 'value="6000000"' in pd and "Pre-launch build budget" in pd
    # deal structure / valuation comparison present
    assert "Deal structures &amp; valuation" in pd
    for structure in ("Priced equity", "Investment cap (SAFE)", "Credit line", "CLA", "Active co-founder + investor"):
        assert structure in pd, f"missing deal structure: {structure}"
    # links to the standalone business plan doc
    assert "/internal/phins-investor-business-plan.html" in pd


def test_pitch_dashboard_deal_configurator():
    pd = _read(STATIC / "pitch-dashboard.html")
    # adjustable deal & valuation configurator
    assert 'id="investor-configurator"' in pd
    assert 'id="inv-deal-body"' in pd  # deal table computed live
    assert 'id="inv-round"' in pd and 'id="inv-premoney"' in pd
    assert 'id="inv-position"' in pd
    # currency selector ($ / ₪ / €) driven by live FX
    for cur in ('data-cur="ILS"', 'data-cur="USD"', 'data-cur="EUR"'):
        assert cur in pd, f"missing currency button {cur}"
    assert 'id="inv-fx-rate"' in pd
    assert "/api/fx/rates" in pd  # live FX source (Alpha Vantage)
    # canonical base + scaling cells so figures reconcile
    assert 'class="inv-money inv-scale"' in pd


def test_pitch_dashboard_investor_name_adjustable():
    pd = _read(STATIC / "pitch-dashboard.html")
    # editable investor-name input in the configurator, defaulting to Meir Uzan
    assert 'id="inv-investor-name-input"' in pd
    assert 'value="Mr. Meir Uzan"' in pd
    # every mention is driven by a dynamic span (full + courteous short form)
    assert 'class="inv-investor-name"' in pd
    assert 'class="inv-investor-name-short"' in pd
    # the configurator JS recomputes the name spans and persists it in the
    # shared config the investor documents read
    assert "investorName" in pd
    assert ".inv-investor-name" in pd and ".inv-investor-name-short" in pd


def test_pitch_dashboard_currency_is_live_not_fixed():
    pd = _read(STATIC / "pitch-dashboard.html")
    # the section must NOT advertise a hard-coded/constant FX anymore
    assert "fixed FX of 1" not in pd
    assert "₪3.70" not in pd
    # instead it states a live exchange rate, filled dynamically from /api/fx/rates
    assert "live exchange rate" in pd
    assert 'id="inv-integrity-fx"' in pd


def test_investor_business_plan_no_constant_fx():
    bp = _read(STATIC / "internal" / "phins-investor-business-plan.html")
    # the integrity notes must not pin a constant FX value; live rate is shown
    # in the FX strip and a labelled fallback is described without a number
    assert "₪3.70" not in bp
    assert "1 USD = ₪3.70" not in bp
    assert "/api/fx/rates" in bp


def test_term_sheet_prefills_shared_investor_name():
    js = _read(STATIC / "legal" / "legal-docs.js")
    # legal documents pre-fill the investor name from the shared configurator
    assert "applySharedInvestorDefaults" in js
    assert "phins.investor.cfg.v1" in js
    assert "investorName" in js
    ts = _read(STATIC / "legal" / "term-sheet.html")
    assert 'key: "investorName"' in ts


def test_pitch_dashboard_valuation_basis():
    pd = _read(STATIC / "pitch-dashboard.html")
    # valuation is versatile: manual / income multiple / actuarial simulation
    assert 'id="inv-valbasis"' in pd
    assert 'id="inv-val-multiple"' in pd
    assert 'id="inv-val-actuarial"' in pd
    assert 'id="inv-sim-run"' in pd
    assert "/api/investor/valuation-sim" in pd  # actuarial appraisal simulation
    # links out to the platform actuarial engine
    assert "/actuary-dashboard.html" in pd


def test_pitch_dashboard_nda_signature():
    pd = _read(STATIC / "pitch-dashboard.html")
    # NDA + ledger-anchored signature
    assert 'id="investor-nda"' in pd
    assert 'id="inv-sig-pad"' in pd  # draw-to-sign canvas
    assert 'id="inv-sig-commit"' in pd
    assert "/api/legal-docs/sign" in pd  # anchors to the platform ledger
    assert "/legal/nda.html" in pd  # links to the full NDA instrument


def test_pitch_dashboard_meeting_diary():
    pd = _read(STATIC / "pitch-dashboard.html")
    # adjustable admin meeting diary pinned to the IL pitch dashboard
    assert 'id="il-meeting-diary"' in pd
    assert 'id="diary-tbody"' in pd
    assert "phins.il.meeting.diary" in pd  # localStorage persistence key
    assert "diary-add-btn" in pd and "diary-reset-btn" in pd


def test_investor_business_plan_doc():
    bp = _read(STATIC / "internal" / "phins-investor-business-plan.html")
    # standard fintech angel/investor business-plan sections
    # ("Problem" was renamed to "The Need" per investor-meeting adjustments)
    for section in ("Founder", "The Need", "Solution", "Market &amp; TAM", "Business model",
                    "Use of funds", "Milestone execution gates", "Financial projection",
                    "The ask &amp; deal structures"):
        assert section in bp, f"business plan missing section: {section}"
    # integrity: round + valuation basis stated (static fallback before JS sync)
    assert "6,000,000" in bp and "24,000,000" in bp


def test_investor_business_plan_meeting_adjustments():
    bp = _read(STATIC / "internal" / "phins-investor-business-plan.html")
    # founder identity
    assert "Asaf Ashury, Adv. &amp; Insurance Broker" in bp
    assert "who has developed" in bp
    # removed texts
    assert "Prepared for:" not in bp
    assert "64+ deployed modules" not in bp
    assert "AI-native" not in bp and "AI-enhanced" in bp
    assert ">2. Problem<" not in bp
    # adjustable use-of-funds + burn pace synced to the deal configurator
    assert "phins.investor.cfg.v1" in bp
    assert 'id="bp-uof-table"' in bp
    assert 'id="bp-chart-burn"' in bp
    # 5-year (2027-2031) gantt + forecast charts/tables
    assert 'id="bp-chart-gantt"' in bp and "5-year" in bp
    assert "2031" in bp and "100,000" in bp and "55,000" in bp
    assert 'id="bp-chart-policies"' in bp and 'id="bp-chart-pnl"' in bp
    # premiums / claims / reinsurance forecast on the portfolio-simulation basis
    assert 'id="bp-carrier-table"' in bp and 'id="bp-chart-carrier"' in bp
    assert "/actuary-dashboard.html" in bp
    assert 'id="bp-q-table"' in bp
    # live FX + deal table synced from the configurator
    assert "/api/fx/rates" in bp and 'id="bp-deal-body"' in bp
    # the shared assistant widget (Admin AI Mic) must not be injected:
    # the opt-out marker keeps _inject_ui_clarity_script from adding it
    assert "ui-clarity.js" in bp
    assert "Admin AI Mic" not in bp


def test_investor_business_plan_hebrew_locale_for_ils():
    """When the investor selects ₪ ILS in the business plan, the document
    must switch to professional Hebrew (RTL). The English baseline is the
    on-page fallback so USD / EUR keep rendering in English unchanged."""
    bp = _read(STATIC / "internal" / "phins-investor-business-plan.html")
    # i18n scaffolding is wired
    assert "I18N_HE" in bp
    assert "applyStaticI18n" in bp
    assert 'data-i18n="page.title"' in bp
    assert 'data-i18n="hero.h1"' in bp
    assert 'data-i18n="integrity.note"' in bp
    # RTL/Hebrew typography CSS is present
    assert 'html[dir="rtl"]' in bp
    # locale flips when ILS is selected — the dictionary carries professional
    # Hebrew translations of the high-impact sections
    he_section_titles = [
        "פיינס — תוכנית עסקית",       # hero h1
        "המייסד",                      # section 1
        "הצורך",                        # section 2
        "הפתרון",                       # section 3
        "מודל עסקי",                    # section 5
        "הנחות תחת בחינה",              # section 6
        "שימוש בכספים",                  # section 7
        "תחזית פיננסית",                # section 9
        "מבני העסקה",                   # section 10
        "צוות וממשל תאגידי",            # section 11
        "סיכונים והפחתות",              # section 12
        "השלבים הבאים",                 # section 13
    ]
    for he in he_section_titles:
        assert he in bp, f"missing Hebrew title: {he}"
    # data-integrity notice is fully translated and preserves the ₪3,600 /
    # 25% take-rate anchor values so numeric integrity is flawless across
    # both locales
    assert "הצהרת שלמות נתונים" in bp
    assert "₪3,600" in bp and "25%" in bp


def test_il_pitch_links_data_room():
    il = _read(STATIC / "israel-capital-markets-pitch.html")
    assert "/corporate-legal-dashboard.html" in il
