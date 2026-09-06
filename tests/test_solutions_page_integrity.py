"""Static integrity for the public /solutions.html investor page.

Guards:
  * title-case presentation of the public outline
  * enlarged theater + 11-second preview contract for every segment
  * inquiry form field names, option values, and endpoint stay aligned
    with the server allow-lists (data integrity)
  * preview copy stays an outline — no implementation secrets
"""

import re
from pathlib import Path

import web_portal.server as portal


SOLUTIONS_PATH = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "solutions.html"


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
    preview = (
        Path(__file__).resolve().parents[1]
        / "web_portal"
        / "static"
        / "previews"
        / "capability.html"
    ).read_text(encoding="utf-8")
    assert 'id="sol-theater"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html
    assert "WALKTHROUGH_MS = 11000" in html
    assert "PREVIEW_FRAME = '/previews/capability.html'" in html
    assert "Watch 11s Preview" in html
    assert "PHINS · Visual Walkthrough" in html
    assert "sol-live-frame" in html
    assert 'id="stage-underwriting"' in preview
    assert 'id="uw-reject"' in preview
    assert 'id="stage-claims"' in preview
    assert "Submit Claim" in preview
    assert 'id="act-scroll"' in preview
    assert "Investments Terminal" in preview
    assert "PHINS · INVESTMENTS" in preview
    assert "PHINS TERMINAL" in preview
    assert "Customer Management" in preview
    assert "Unified Workbench" in preview
    assert "Validate Pipeline" in preview
    assert 'src="/phins-logo.svg"' in preview
    assert 'href="/solutions.html"' not in preview
    assert "act-scroll > section.on" in preview
    assert "animation: paneIn" in preview
    assert 'id="act-step"' in preview
    assert "data-tour-pane" in preview
    assert "resetStages" in preview
    assert "stage-invest').style.display" not in preview
    assert "stage-actuarial').style.display" not in preview
    assert "{ id: 'ov', t: 0" in preview
    assert "{ id: 'tb', t: 1800" in preview
    assert "{ id: 'fc', t: 3600" in preview
    assert "{ id: 'sm', t: 5400" in preview
    assert "{ id: 'pt', t: 7200" in preview
    assert "later(9000, tourInvestments)" in preview
    assert 'class="sol-player-logo"' in html
    assert 'class="sol-theater-wordmark"' in html
    assert "sandbox" in html
    assert "allow-scripts allow-same-origin" in html

    expected_previews = {
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
    }
    found = set(re.findall(r'data-preview="([a-z_]+)"', html))
    assert expected_previews == found
    for key in expected_previews:
        assert key + ":" in html  # preview catalog entry


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
