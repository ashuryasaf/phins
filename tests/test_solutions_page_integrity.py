"""Static integrity for the public /solutions.html investor page.

Guards:
  * title-case presentation of the public outline
  * enlarged theater + 11-second production-desk video for every segment
  * inquiry form field names, option values, and endpoint stay aligned
    with the server allow-lists (data integrity)
  * preview copy and theater assets stay an outline — no implementation secrets
"""

import re
import shutil
import subprocess
from pathlib import Path

import web_portal.server as portal


SOLUTIONS_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "solutions.html"
THEATER_DIR = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "previews" / "theaters"

EXPECTED_PREVIEWS = (
    "underwriting",
    "assessments",
    "billing",
    "claims",
    "actuarial_investments",
    "platform",
    "smart_contracts",
    "mga_solutions",
    "actuarial_force",
    "individuals",
    "enterprises",
)


def _html():
    return SOLUTIONS_PATH.read_text(encoding="utf-8")


def test_solutions_page_uses_title_case_where_necessary():
    html = _html()
    assert "The AI-Native Platform Where Insurance Is Underwritten" in html
    assert "One Platform. Every Stage of the Policy Lifecycle." in html
    assert "Where PHINS Goes Beyond the Market." in html
    assert "Built for Individuals. Engineered for Enterprises." in html
    assert "An Open Invitation — With the Edge Kept Sharp." in html
    assert "Start the Conversation." in html
    assert "What Happens Next" in html
    assert "Inside the Solution" in html
    assert "Individuals &amp; Enterprises" in html
    assert "AI-Assisted Underwriting" in html
    assert "Assessment Center" in html
    assert "Billing &amp; Payments" in html
    assert "Claims Management" in html
    assert "Actuarial &amp; Investments" in html
    assert "Trust, Security &amp; Auditability" in html
    assert "Smart Contracts Development" in html
    assert "MGA Solutions" in html
    assert "Actuarial Force" in html
    assert "For Individuals" in html
    assert "For Enterprises &amp; Partners" in html


def test_every_public_segment_opens_an_enlarged_theater_preview():
    html = _html()
    assert 'id="sol-theater"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert "WALKTHROUGH_MS = 11000" in html
    assert "PREVIEW_VIDEOS" in html
    assert "createElement('video')" in html
    assert "Watch 11s Preview" in html
    assert "PHINS · Visual Walkthrough" in html
    assert "sol-live-frame" in html
    assert "PREVIEW_FRAME" not in html
    assert "capability.html" not in html
    assert "sandbox" not in html
    assert 'class="sol-player-logo"' in html
    assert 'class="sol-theater-wordmark"' in html
    # Public theater must play recorded desk videos, never live authenticated desks.
    for live_desk in (
        "underwriter-dashboard.html",
        "unified-workbench.html",
        "billing.html",
        "claims-adjuster-dashboard.html",
        "actuary-dashboard.html",
        "cyber-security.html",
        "settlement-approval.html",
        "admin-supplier-dashboard.html",
        "dashboard.html",
        "customer-management.html",
        "trading-terminal.html",
    ):
        assert live_desk not in html

    found = set(re.findall(r'data-preview="([a-z_]+)"', html))
    assert set(EXPECTED_PREVIEWS) == found
    for key in EXPECTED_PREVIEWS:
        assert f"/previews/theaters/{key}.mp4" in html


def test_theater_videos_are_complete_mp4s_near_eleven_seconds():
    for key in EXPECTED_PREVIEWS:
        path = THEATER_DIR / f"{key}.mp4"
        assert path.is_file(), path
        data = path.read_bytes()
        assert len(data) > 25_000, path
        assert b"ftyp" in data[:32]
        if shutil.which("ffprobe"):
            out = subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=nw=1:nk=1",
                    str(path),
                ],
                text=True,
            ).strip()
            duration = float(out)
            assert 10.5 <= duration <= 12.5, (key, duration)
    hashes = {hash((THEATER_DIR / f"{key}.mp4").read_bytes()) for key in EXPECTED_PREVIEWS}
    assert len(hashes) == len(EXPECTED_PREVIEWS)


def test_inquiry_form_contract_matches_server_allow_lists():
    html = _html()
    assert 'id="inquiry-form"' in html
    assert "fetch('/api/business/inquiries'" in html
    for field in ("inquiry_type", "name", "email", "organization", "audience", "interest", "message"):
        assert field in html

    interest_values = set(re.findall(r'<option value="([a-z_]+)">', html.split('id="inq-interest"', 1)[1].split("</select>", 1)[0]))
    assert interest_values == set(portal.BUSINESS_INQUIRY_INTERESTS)

    audience_values = set(re.findall(r'<option value="([a-z]+)">', html.split('id="inq-audience"', 1)[1].split("</select>", 1)[0]))
    assert audience_values == set(portal.BUSINESS_INQUIRY_AUDIENCES)

    theater_interests = set(re.findall(r'data-interest="([a-z_]+)"', html))
    assert theater_interests <= set(portal.BUSINESS_INQUIRY_INTERESTS)


def test_preview_copy_does_not_expose_implementation_secrets():
    html = _html()
    preview = (
        Path(__file__).resolve().parents[1]
        / "web_portal"
        / "static"
        / "previews"
        / "capability.html"
    ).read_text(encoding="utf-8")
    blob = html + "\n" + preview
    forbidden = [
        "#keeping secrets hidden#",
        "DATABASE_URL",
        "PHINS_ENCRYPTION_KEY",
        "SESSION_SECRET_KEY",
        "api_key",
        "password",
        "Bearer ",
        "document_processing_jobs",
        "idempotency",
        "schema",
        "SQL",
        "prompt template",
        "llm_providers",
    ]
    lowered = blob.lower()
    for token in forbidden:
        assert token.lower() not in lowered, token
    assert "This page intentionally shares outlines, not implementations" not in html
    assert "SHA-256" not in preview
    assert "pricing kernel" not in preview.lower()
    assert "john.doe" not in preview.lower()
    assert "john.doe" not in html.lower()
