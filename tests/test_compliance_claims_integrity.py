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


def test_pitch_pages_do_not_check_off_soc2():
    # The IT Security Audit line mentions "SOC 2 Type II in progress", so it
    # must carry the amber in-progress marker rather than a green checkmark.
    pitch_pages = sorted(STATIC.glob("*-capital-markets-pitch.html"))
    assert len(pitch_pages) >= 20, "pitch pages missing from static root"
    for page in pitch_pages:
        text = _read(page)
        for line in text.splitlines():
            if "SOC 2 Type II in progress" in line:
                assert "\u2705" not in line, f"{page.name}: {line.strip()}"
                assert "\U0001f504" in line, f"{page.name}: {line.strip()}"


def test_legal_compliance_register_still_tracks_soc2():
    register = _read(STATIC / "legal" / "legal-compliance.html")
    assert "SOC 2 Type II in progress" in register
