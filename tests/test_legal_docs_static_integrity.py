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
    # build budget reconciles to the round size
    assert "6,000,000" in pd and "Pre-launch build budget" in pd
    # deal structure / valuation comparison present
    assert "Deal structures &amp; valuation" in pd
    for structure in ("Priced equity", "Investment cap (SAFE)", "Credit line", "CLA", "Active co-founder + investor"):
        assert structure in pd, f"missing deal structure: {structure}"
    # links to the standalone business plan doc
    assert "/internal/phins-investor-business-plan.html" in pd


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
    for section in ("Founder", "Problem", "Solution", "Market &amp; TAM", "Business model",
                    "Use of funds", "Milestone execution gates", "Financial projection",
                    "The ask &amp; deal structures"):
        assert section in bp, f"business plan missing section: {section}"
    # integrity: round + valuation basis stated
    assert "6,000,000" in bp and "24,000,000" in bp


def test_il_pitch_links_data_room():
    il = _read(STATIC / "israel-capital-markets-pitch.html")
    assert "/corporate-legal-dashboard.html" in il
