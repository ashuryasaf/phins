"""Cross-pipeline documents keep PHINS chrome and a way back.

The return bar and letterhead are presentation only. These checks pin the
shared homes map, the generators that must keep injecting chrome after the
payload is sealed, and the pages a person can open into a new tab.
"""

import re
from pathlib import Path

from services.phins_document import (
    PIPELINE_DOCUMENT_HOMES,
    document_return_markup,
    render_phins_document,
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "web_portal" / "static"

STANDALONE_DOCS = [
    "internal/phins-investment-deck.html",
    "internal/exec-actuary-briefing.html",
    "internal/phins-insurer-mga-business-plan.html",
    "internal/phins-investor-business-plan.html",
    "internal/phins-ai-tech-partner-business-plan.html",
    "israel-isa-prospectus.html",
    "albania-afsa-prospectus.html",
    "unicorn-investor-deck.html",
    "unicorn-executive-summary.html",
    "seed-investor-deck.html",
    "capital-markets-pitch.html",
    "nda.html",
    "PHINS_Business_Plan_Presentation.html",
    "phins-risk-1pager-goldsobel.html",
    "phins-risk-1pager-fefferman.html",
    "terms-of-use.html",
    "privacy-policy.html",
    "document-viewer.html",
    "customer-ai-report.html",
    "risk-assessment-viewer.html",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_role_homes_match_between_python_and_browser():
    script = _read(STATIC / "phins-doc-return.js")
    block = re.search(r"var PHINS_DOCUMENT_HOMES = \{([^}]+)\}", script)
    assert block, "browser homes map missing"
    js_homes = dict(re.findall(r"(\w+):\s*'([^']+)'", block.group(1)))
    assert js_homes == PIPELINE_DOCUMENT_HOMES
    assert js_homes["admin"] == "/admin.html"
    assert js_homes["manager"] == "/admin.html"
    assert js_homes["supplier"] == "/supplier-dashboard.html"
    assert js_homes["regulator"] == "/regulator-dashboard.html"
    assert js_homes["customer"] == "/dashboard.html"
    assert js_homes["community"] == "/foundation-dashboard.html"
    assert js_homes["foundation"] == "/foundation-dashboard.html"


def test_return_bar_is_hidden_in_print_and_does_not_alter_body():
    css = _read(STATIC / "phins-document.css")
    assert "@media print" in css
    assert ".phins-doc-return" in css
    html = render_phins_document(
        title="Seal check",
        eyebrow="Policy",
        subtitle="POL-9",
        body_html="<p>figure 1200.50 only-here</p>",
        footer="checksum abc",
    )
    assert html.count("figure 1200.50 only-here") == 1
    assert "checksum abc" in html


def test_print_windows_use_the_shared_letterhead():
    """Ad-hoc print windows were the dead-end path. Only the shared helper writes one."""
    offenders = []
    for path in list(STATIC.rglob("*.html")) + list(STATIC.rglob("*.js")):
        text = _read(path)
        if "printWindow.document.write" in text and path.name != "phins-document.js":
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
    helper = _read(STATIC / "phins-document.js")
    assert "PhinsDocument.printReport" in helper or "printReport" in helper
    assert "phins-doc-return.js" in helper


def test_generators_add_return_chrome_at_the_top_of_the_document_body():
    contract = _read(ROOT / "services" / "underwriting_integrity_service.py")
    risk = _read(ROOT / "services" / "risk_report_generator.py")
    for source in (contract, risk):
        assert '"<body>\\n" + document_return_markup()' in source
    # the policy seal is the payload hash, computed before the HTML shell
    assert contract.index("seal = _integrity_hash(body)") < contract.index("html_doc = f")


def test_inlined_return_script_never_closes_its_script_element():
    # HTML ignores JS comments: a literal end tag anywhere in the helper would
    # close the inlined <script> and print the rest of it as page text.
    assert "</script" not in _read(STATIC / "phins-doc-return.js")
    assert document_return_markup().count("</script>") == 1


def test_standalone_documents_include_the_return_script():
    for name in STANDALONE_DOCS:
        text = _read(STATIC / name)
        assert "phins-doc-return.js" in text, name
        assert text.rfind("phins-doc-return.js") < text.rfind("</body>"), name


def test_pages_with_their_own_controls_still_call_the_shared_functions():
    for name in ("customer-ai-report.html", "risk-assessment-viewer.html"):
        text = _read(STATIC / name)
        assert 'data-phins-return="off"' in text
        assert "phinsDocGoBack" in text
        assert "phinsDocClose" in text


def test_vault_open_stays_in_the_documents_modal():
    text = _read(STATIC / "documents.html")
    assert "data-vault-open" in text
    assert "include_data=true" in text
    assert 'data-vault-open="${escHtml(d.view_url' in text
    assert ">Open</button>" in text
    assert 'target="_blank"' not in text


def test_regulator_download_uses_the_shared_renderer():
    text = _read(STATIC / "regulator-dashboard.html")
    assert "PhinsDocument.render" in text
    assert "/phins-document.js" in text


def test_same_origin_file_opens_keep_a_way_back():
    opener = _read(STATIC / "phins-doc-open.js")
    assert "document-viewer.html" in opener
    assert "hasAttribute('download')" in opener
    assert "pdf|md" in opener
    viewer = _read(STATIC / "document-viewer.html")
    assert "src.indexOf('..')" in viewer
    assert "phins-doc-return.js" in viewer
    assert "phins-doc-open.js" in _read(STATIC / "ui-clarity.js")
    assert "phins-doc-open.js" in _read(STATIC / "pitch-dashboard.html")


def test_claim_iframe_can_hide_the_framed_return_bar():
    text = _read(STATIC / "claims-chat.js")
    assert 'sandbox="allow-scripts"' in text
    assert 'sandbox=""' not in text


def test_billing_export_dropped_the_off_brand_shell():
    assert "#667eea" not in _read(STATIC / "billing.js")
    assert "#764ba2" not in _read(STATIC / "billing.js")
    assert "PhinsDocument.printReport" in _read(STATIC / "billing.js")
