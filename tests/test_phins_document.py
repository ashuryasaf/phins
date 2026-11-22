"""Generated PHINS documents share one letterhead and stay downloadable HTML."""

import os
import urllib.request
from pathlib import Path

from services.claims_chat_service import render_fnol_html, render_processing_html
from services.phins_document import (
    brand_mark_script,
    document_return_markup,
    render_phins_document,
)

STATIC = Path(__file__).resolve().parents[1] / "web_portal" / "static"


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
    assert "Go back" in html
    assert "Close" in html
    assert "phinsDocGoBack" in html
    assert html.startswith("<!DOCTYPE html>")
    # chrome is outside the body block; the caller markup is unchanged
    assert html.index("<p>alpha</p>") > html.index("phins-doc-body")


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
        assert "phins-doc-back" in doc
        assert "123456782" not in doc
    assert checksum in notice
    assert "+972-50-555-0199" in notice
    assert "PUSH-1" in processing


def test_brand_mark_sets_copyright_and_rights_line_on_every_wordmark():
    script = (STATIC / "phins-brand-mark.js").read_text(encoding="utf-8")
    assert "All rights reserved" in script
    assert "\\u00A9" in script
    for host in (".phins-logo-text", ".logo-text", ".phins-doc-wordmark",
                 ".lh-name", ".brand-wordmark", ".auth-wordmark", ".brand"):
        assert f"'{host}'" in script
    # The reserved line is tracked to the wordmark width, never wider.
    assert "min-width:100%" in script and "width:0" in script
    assert 'data-phins-mark="off"' in script
    # Inlined into generated documents: a literal end tag would close the element.
    assert "</script" not in script


def test_generated_documents_inline_the_brand_mark_in_the_one_script_element():
    markup = document_return_markup()
    assert markup.count("</script>") == 1
    assert brand_mark_script() in markup
    html = render_phins_document(
        title="Mark", eyebrow="Mark", subtitle="POL-1",
        body_html="<p>figure 42.00</p>",
    )
    assert '<div class="phins-doc-wordmark">PHINS</div>' in html
    assert "All rights reserved" in html
    assert html.count("figure 42.00") == 1


def test_dashboards_and_browser_documents_load_the_brand_mark():
    clarity = (STATIC / "ui-clarity.js").read_text(encoding="utf-8")
    assert 'markScript.src = "/phins-brand-mark.js"' in clarity
    helper = (STATIC / "phins-document.js").read_text(encoding="utf-8")
    assert "fetch('/phins-brand-mark.js')" in helper
    base_url = os.environ.get("TEST_BASE_URL", "http://localhost:8000")
    with urllib.request.urlopen(f"{base_url}/phins-brand-mark.js", timeout=10) as resp:
        assert resp.status == 200
        assert "All rights reserved" in resp.read().decode("utf-8")
