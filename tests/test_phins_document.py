"""Generated PHINS documents share one letterhead and stay downloadable HTML."""

from services.claims_chat_service import render_fnol_html, render_processing_html
from services.phins_document import render_phins_document


def test_shell_includes_logo_gradient_and_wordmark():
    html = render_phins_document(
        title="PHINS sample",
        eyebrow="Sample",
        subtitle="POL-1",
        body_html="<h1>Body</h1><p>alpha</p>",
        footer="footer note",
    )
    assert "phins-doc-banner" in html
    assert "linear-gradient(135deg, #060d1f" in html
    assert "PHINS" in html
    assert "<svg" in html
    assert "alpha" in html
    assert html.startswith("<!DOCTYPE html>")


def test_claim_documents_use_the_shared_letterhead():
    facts = {
        "customer_id": "CUST-1",
        "contact_name": "Maya Cohen",
        "contact_email": "maya@example.com",
        "contact_phone": "+972-50-555-0199",
        "policy_id": "POL-1",
        "type": "accident",
        "incident_date": "2026-09-25",
        "incident_location": "Tel Aviv",
        "claimed_amount": "2400.00",
        "provider": "Ichilov",
        "description": "Fell from a bicycle.",
        "nationality": "IL",
        "national_id_last4": "6782",
        "national_id_hash": "abc123",
        "signature_name": "Maya Cohen",
        "signature_method": "drawn_canvas",
        "signature_sha256": "sigsha",
        "consent_version": "phins-claims-consent-v1",
        "media": [],
    }
    checksum = "deadbeef" * 8
    notice = render_fnol_html(facts, checksum)
    processing = render_processing_html(facts, checksum, {
        "claim_id": "CLM-1",
        "notification_id": "PUSH-1",
        "notification_status": "sent",
        "pipeline": {"recommendation": "approve_partial", "fraud_probability": 0.2,
                     "authenticity_probability": 0.8, "risk_level": "low"},
    })
    for doc in (notice, processing):
        assert "phins-doc-wordmark" in doc
        assert "<svg" in doc
        assert "123456782" not in doc
    assert checksum in notice
    assert "+972-50-555-0199" in notice
    assert "PUSH-1" in processing
