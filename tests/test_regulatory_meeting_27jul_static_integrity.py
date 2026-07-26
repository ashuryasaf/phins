"""
Static-integrity tests for the 27 July 2026 regulatory meeting pack.

One meeting is pinned to the IL pitch dashboard:
- 27 July 2026 (30 minutes, hard timebox) with Herzog Fox Neeman & Co.
  Advocates — regulatory manager Mrs. Neta Dorfman Raviv. Scope: introduction
  to the platform and product regulatory posture, IP protection, B2B
  contracts, and the global view, based on the PHINS business plan and the
  published Israel regulatory application memorandum (Hebrew canonical).

These tests read the shipped static assets (no server required) and assert:
- the pitch dashboard carries the Regulatory Meeting section with a timeboxed
  30-minute run of show covering all four scope topics,
- the section links the Hebrew regulatory application PDF (and the assets it
  references actually ship with the portal),
- the meeting is seeded in the admin meeting diary defaults.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Pitch dashboard — Regulatory Meeting section
# ---------------------------------------------------------------------------

def test_pitch_dashboard_regulatory_meeting_section():
    pd = _read(STATIC / "pitch-dashboard.html")
    # section + nav link
    assert 'id="regulatory-meeting-27jul"' in pd
    assert '#regulatory-meeting-27jul' in pd
    assert "Regulatory Meeting — 27 July 2026" in pd
    # counterparty and regulatory manager
    assert "Herzog Fox Neeman" in pd
    assert "Neta Dorfman Raviv" in pd
    # 30-minute framing
    assert "30 minutes" in pd
    assert "30-minute" in pd


def test_regulatory_meeting_scope_topics():
    pd = _read(STATIC / "pitch-dashboard.html").lower()
    # all four requested scope topics present
    for topic in ("product regulatory", "ip protection", "b2b contracts",
                  "global view"):
        assert topic in pd, f"missing scope topic: {topic}"


def test_regulatory_meeting_30_minute_run_of_show():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert 'id="reg-30m-timeline"' in pd
    # productive, timeboxed segments summing to exactly 30 minutes
    for timebox in ("00–03", "03–09", "09–15", "15–21", "21–27", "27–30"):
        assert timebox in pd, f"missing timebox: {timebox}"
    assert "hard timebox" in pd
    assert "Wrap-up" in pd


def test_regulatory_meeting_prep_and_outputs():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert 'id="reg-scope-panel"' in pd
    assert 'id="reg-elevator"' in pd
    assert 'id="reg-outputs"' in pd
    assert "Elevator pitch" in pd
    assert "Decision outputs" in pd


def test_regulatory_meeting_links_source_documents():
    pd = _read(STATIC / "pitch-dashboard.html")
    # anchored to the published regulatory application (HE canonical + EN)
    assert "/investor-docs/israel-regulatory-application-he.pdf" in pd
    assert "/investor-docs/israel-regulatory-application-en.pdf" in pd
    # anchored to the PHINS business plan
    assert "/internal/phins-investor-business-plan.html" in pd
    # the referenced assets actually ship with the portal
    assert (STATIC / "investor-docs" /
            "israel-regulatory-application-he.pdf").is_file()
    assert (STATIC / "investor-docs" /
            "israel-regulatory-application-en.pdf").is_file()
    assert (STATIC / "internal" /
            "phins-investor-business-plan.html").is_file()


# ---------------------------------------------------------------------------
# Admin meeting diary — seeded defaults
# ---------------------------------------------------------------------------

def test_diary_seeds_27jul_regulatory_meeting():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert '2026-07-27' in pd
    # the diary row references the counterparty, duration, and pack
    assert ("Herzog Fox Neeman & Co. Advocates — "
            "Mrs. Neta Dorfman Raviv (Regulatory Manager)") in pd
    assert "30 min" in pd
    assert "Regulatory Meeting 27.7 section" in pd
