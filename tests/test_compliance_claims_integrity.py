"""
Static-integrity tests for compliance claims in investor-facing assets.

PHINS's SOC 2 Type II attestation is in progress (see the legal compliance
register at web_portal/static/legal/legal-compliance.html and the
/api/legal/stats endpoint). These tests ensure investor-facing static assets
never regress into claiming a completed SOC 2 certification.
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "web_portal" / "static"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_no_static_asset_claims_soc2_certified():
    offenders = []
    for path in STATIC.rglob("*.html"):
        text = _read(path)
        if "SOC 2" in text or "SOC2" in text:
            if "Type II Certified" in text:
                offenders.append(str(path.relative_to(REPO)))
    assert offenders == [], (
        f"SOC 2 Type II is in progress, not certified; fix: {offenders}"
    )


def test_business_plan_presentation_marks_soc2_in_progress():
    for path in (
        STATIC / "PHINS_Business_Plan_Presentation.html",
        REPO / "business_plan" / "PHINS_Business_Plan_Presentation.html",
    ):
        text = _read(path)
        assert "Type II Audit In Progress" in text, str(path)


def test_business_plan_presentation_copies_stay_in_sync():
    static_copy = _read(STATIC / "PHINS_Business_Plan_Presentation.html")
    source_copy = _read(
        REPO / "business_plan" / "PHINS_Business_Plan_Presentation.html"
    )
    assert static_copy == source_copy


AMBER_IN_PROGRESS = "#f59e0b"
COMPLETION_GLYPHS = ("\u2705", "\u2713", "\u2714")  # ✅ ✓ ✔
INVESTOR_PITCH_SURFACES = (
    "pitch-dashboard.html",
    "unicorn-investor-deck.html",
    "unicorn-executive-summary.html",
    "seed-investor-deck.html",
)


def test_pitch_pages_do_not_check_off_soc2():
    # The 26 per-jurisdiction copies were consolidated into one parameterised
    # capital-markets-pitch.html rendered from /jurisdictions.json; the glob
    # still catches any per-country copy that is (re)introduced. Decorative
    # glyphs were removed platform-wide, so the checklist's IT Security Audit
    # line ("SOC 2 Type II in progress") must carry the amber in-progress
    # marker rather than any completion checkmark.
    import json

    pitch_pages = sorted(STATIC.glob("*capital-markets-pitch.html"))
    assert STATIC / "capital-markets-pitch.html" in pitch_pages, \
        "parameterised pitch page missing from static root"
    seen_in_progress = False
    for page in pitch_pages:
        text = _read(page)
        assert "Type II Certified" not in text, page.name
        for line in text.splitlines():
            if "SOC 2 Type II in progress" in line:
                seen_in_progress = True
                for glyph in COMPLETION_GLYPHS:
                    assert glyph not in line, f"{page.name}: {line.strip()}"
                assert AMBER_IN_PROGRESS in line, f"{page.name}: {line.strip()}"
    assert seen_in_progress, "pitch page lost its SOC 2 in-progress line"

    # every jurisdiction the deleted copies used to cover must still be served
    # by the parameterised page
    jurisdictions = json.loads(_read(STATIC / "jurisdictions.json"))["jurisdictions"]
    assert len(jurisdictions) >= 26
    assert {"israel", "usa"} <= {j["id"] for j in jurisdictions}

    # the decks / pitch dashboard may describe a compliance-ready architecture
    # but must never claim the attestation is complete
    for rel in INVESTOR_PITCH_SURFACES:
        for line in _read(STATIC / rel).splitlines():
            if "SOC 2" in line or "SOC2" in line:
                assert "Certified" not in line, f"{rel}: {line.strip()}"
                for glyph in COMPLETION_GLYPHS:
                    assert glyph not in line, f"{rel}: {line.strip()}"


def test_legal_compliance_register_still_tracks_soc2():
    register = _read(STATIC / "legal" / "legal-compliance.html")
    assert "SOC 2 Type II in progress" in register
