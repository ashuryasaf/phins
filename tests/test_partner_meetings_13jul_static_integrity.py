"""
Static-integrity tests for the 13 July 2026 co-partner meeting packs.

Two meetings are pinned to the IL pitch dashboard:
- Meeting A (11:00): chairman of an AI technology development public company —
  strategic investment / technology co-development (markets opening, tech
  orientation).
- Meeting B (14:15): CEO of a major insurance company (agents orientation) —
  build & distribute via a joint company (NewCo) or MGA on the insurer's paper.

These tests read the shipped static assets (no server required) and assert:
- the pitch dashboard carries the Partner Meetings section with an elevator
  pitch, an executive pitch, adjustable assumptions, and pinned actuarial
  simulation versions per meeting,
- both meetings are seeded in the meeting diary defaults,
- each meeting has a full business plan document with the standard sections,
  live FX (no constant rate), the deterministic valuation simulation, and a
  data-integrity notice anchored to the canonical IL model.
"""

from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"
INTERNAL = STATIC / "internal"

PLAN_A = "phins-ai-tech-partner-business-plan.html"
PLAN_B = "phins-insurer-mga-business-plan.html"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Pitch dashboard — Partner Meetings section
# ---------------------------------------------------------------------------

def test_pitch_dashboard_partner_meetings_section():
    pd = _read(STATIC / "pitch-dashboard.html")
    # section + nav link
    assert 'id="partner-meetings-13jul"' in pd
    assert '#partner-meetings-13jul' in pd
    assert "Partner Meetings — 13 July 2026" in pd
    # both meeting tracks with their counterparties and orientations
    assert 'id="pm-track-a"' in pd and 'id="pm-track-b"' in pd
    assert "AI technology development public company" in pd
    assert "CEO — major insurance company" in pd or "CEO of a major insurance company" in pd
    # meeting times: A 11:00, B 14:15
    assert "11:00" in pd
    assert "14:15" in pd
    # meeting B structures
    assert "joint company" in pd.lower()
    assert "MGA" in pd


def test_pitch_dashboard_partner_meetings_pitches():
    pd = _read(STATIC / "pitch-dashboard.html")
    # each track carries an elevator pitch and an executive pitch
    for pid in ("pm-a-elevator", "pm-a-exec", "pm-b-elevator", "pm-b-exec"):
        assert f'id="{pid}"' in pd, f"missing pitch block {pid}"
    assert "Elevator pitch" in pd
    assert "Executive pitch" in pd


def test_pitch_dashboard_partner_meetings_links_business_plans():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert f"/internal/{PLAN_A}" in pd
    assert f"/internal/{PLAN_B}" in pd


def test_pitch_dashboard_partner_meetings_adjustable_assumptions():
    pd = _read(STATIC / "pitch-dashboard.html")
    # Meeting A adjustable inputs (deal + markets-opening economics)
    for iid in ("pma-invest", "pma-pre", "pma-markets", "pma-license",
                "pma-royalty", "pma-scale"):
        assert f'id="{iid}"' in pd, f"missing Meeting A input {iid}"
    # Meeting B adjustable inputs (agent-force + structure economics)
    for iid in ("pmb-structure", "pmb-prod", "pmb-comm", "pmb-jvshare"):
        assert f'id="{iid}"' in pd, f"missing Meeting B input {iid}"
    # persisted locally so admins can adjust without redeploying;
    # shared with the linked full plans via the two plan-aligned keys
    assert "phins.partner.aitech.cfg.v1" in pd
    assert "phins.partner.insurer.cfg.v1" in pd


def test_pitch_dashboard_partner_meetings_simulation_versions():
    pd = _read(STATIC / "pitch-dashboard.html")
    # named, pinned actuarial simulation versions per meeting
    for ver in ("A·P25", "A·P50", "A·P75", "B·P25", "B·P50", "B·P75"):
        assert ver in pd, f"missing simulation version {ver}"
    assert 'class="exec-dl-btn pm-sim-btn"' in pd
    assert "/api/investor/valuation-sim" in pd
    # deterministic seed pinned to the meeting date
    assert "20260713" in pd


def test_pitch_dashboard_partner_meetings_data_integrity():
    pd = _read(STATIC / "pitch-dashboard.html")
    # integrity notice reconciles both packs to the canonical IL model
    assert 'id="pm-integrity-fx"' in pd
    # canonical anchors restated in the section
    assert "₪3,600 average premium" in pd
    # the agent plan derives FROM the policy ramp (single source of truth)
    assert "never the other way around" in pd


def test_pitch_dashboard_diary_seeds_13jul_meetings():
    pd = _read(STATIC / "pitch-dashboard.html")
    assert '2026-07-13' in pd
    # both diary rows present in the seeded defaults
    assert "Chairman — AI technology development public company" in pd
    assert "CEO — major insurance company (agents orientation)" in pd


# ---------------------------------------------------------------------------
# Full business plan documents
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fname", [PLAN_A, PLAN_B])
def test_business_plan_exists_and_is_wellformed(fname):
    p = INTERNAL / fname
    assert p.is_file(), f"missing {fname}"
    bp = _read(p)
    # confidential counterparty-facing print doc: no assistant widget injection
    assert "ui-clarity.js" in bp
    assert "noindex" in bp
    # elevator + executive pitch blocks
    assert 'id="elevator-pitch"' in bp
    assert 'id="executive-pitch"' in bp
    assert "Elevator pitch" in bp
    assert "Executive pitch" in bp
    # meeting date
    assert "13 July 2026" in bp
    # full business-plan sections
    for section in ("Company &amp; founder", "The need", "Business model",
                    "Milestone execution gates", "Risks &amp; mitigations",
                    "Next steps"):
        assert section in bp, f"{fname} missing section: {section}"
    # founder identity consistent with the investor business plan
    assert "Asaf Ashury, Adv. &amp; Insurance Broker" in bp
    # canonical financial model restated (locked base)
    assert "₪3,600" in bp and "25%" in bp
    assert "1 Jan" in bp or "1 January 2027" in bp
    # adjustable assumptions persisted locally
    assert "Adjustable" in bp
    assert "localStorage" in bp
    # print / PDF toolbar and back link to the dashboard section
    assert "window.print" in bp
    assert "/pitch-dashboard.html#partner-meetings-13jul" in bp


@pytest.mark.parametrize("fname", [PLAN_A, PLAN_B])
def test_business_plan_live_fx_no_constant_rate(fname):
    bp = _read(INTERNAL / fname)
    # live FX from the platform endpoint; no pinned constant rate in the copy
    assert "/api/fx/rates" in bp
    assert "₪3.70" not in bp
    assert "1 USD = ₪3.70" not in bp
    # currency selector driven from a single ILS base
    for cur in ('data-cur="ILS"', 'data-cur="USD"', 'data-cur="EUR"'):
        assert cur in bp, f"{fname} missing currency button {cur}"


@pytest.mark.parametrize("fname,versions", [
    (PLAN_A, ("A·P25", "A·P50", "A·P75")),
    (PLAN_B, ("B·P25", "B·P50", "B·P75")),
])
def test_business_plan_actuarial_simulation_versions(fname, versions):
    bp = _read(INTERNAL / fname)
    assert "/api/investor/valuation-sim" in bp
    for ver in versions:
        assert ver in bp, f"{fname} missing simulation version {ver}"
    # deterministic seed pinned to the meeting date + verifiable hash surfaced
    assert "20260713" in bp
    assert "content_hash" in bp
    assert "reproducible" in bp.lower()


@pytest.mark.parametrize("fname", [PLAN_A, PLAN_B])
def test_business_plan_data_integrity_notice(fname):
    bp = _read(INTERNAL / fname)
    assert 'id="integrity-note"' in bp
    assert "Data integrity notice" in bp
    # claims reserves never booked as PHINS revenue (MGA/platform model)
    assert "claims reserves" in bp.lower()
    # forward-looking assumptions disclaimer
    assert "not commitments" in bp


def test_business_plan_a_tech_partner_specifics():
    bp = _read(INTERNAL / PLAN_A)
    # tech orientation: co-development scope + markets opening
    assert "co-development" in bp.lower()
    assert "Markets opening" in bp
    assert "11:00" in bp
    # partnership structures on the table
    for structure in ("Strategic equity", "Technology co-development JV",
                      "License + royalty"):
        assert structure in bp, f"missing structure: {structure}"
    # adjustable deal inputs
    for iid in ("in-invest", "in-pre", "in-markets", "in-license",
                "in-royalty", "in-scale", "in-premium", "in-take"):
        assert f'id="{iid}"' in bp, f"missing input {iid}"
    assert "phins.partner.aitech.cfg.v1" in bp
    # integrity contract headline (AI recommends; ledger decides)
    assert "AI recommends" in bp


def test_business_plan_b_insurer_mga_specifics():
    bp = _read(INTERNAL / PLAN_B)
    # meeting time confirmed at 14:15
    assert "14:15" in bp
    # agents orientation: JV / MGA structures + agent-force plan
    assert "agent force" in bp.lower()
    assert "MGA on insurer paper" in bp
    assert "Joint company (NewCo)" in bp
    assert "Hybrid" in bp
    # adjustable agent-force inputs
    for iid in ("in-structure", "in-prod", "in-comm", "in-jvshare",
                "in-premium", "in-take", "in-churn", "in-jvpre"):
        assert f'id="{iid}"' in bp, f"missing input {iid}"
    assert "phins.partner.insurer.cfg.v1" in bp
    # the agent plan derives FROM the canonical policy ramp
    assert "derived" in bp.lower() and "policy ramp" in bp.lower()
    # canonical EoY policy counts restated
    for count in ("4,000", "12,000", "28,000"):
        assert count in bp, f"missing canonical policy count {count}"
