"""Request for legal services sent to NBA Law (22 November 2026).

The outward document carries the five practice areas as services, deliverables,
timing, and capacity, with no internal meeting-preparation notes, canonical
figures only, and a confidential gate on every edition.
"""

import importlib.util
import re
from pathlib import Path

from security import confidential_access as ca
from services.business_plan_model import compute_plan

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "web_portal" / "static"
DOCS = STATIC / "investor-docs"
STEM = "nba-law-legal-services-request-22nov2026"
MD_NAME = f"investor-docs/{STEM}.md"


def _md() -> str:
    return (DOCS / f"{STEM}.md").read_text(encoding="utf-8")


def _generator():
    spec = importlib.util.spec_from_file_location(
        "generate_investor_pdfs", REPO / "scripts" / "generate_investor_pdfs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_request_covers_the_five_areas_and_the_capacity_asked():
    md = _md()
    assert md.startswith("# PHINS — Request for Legal Services")
    for heading in ("## 1. Corporate and contracts", "## 2. Intellectual property", "## 3. Tax",
                    "## 4. Israeli and segmented regulation", "## 5. Insurance and reinsurance commercial",
                    "## Engagement capacity requested", "## Materials PHINS will provide",
                    "## Key dates", "## Notice"):
        assert heading in md, heading
    assert md.count("**Services requested**") == 5
    assert md.count("**Deliverables:**") == 5
    for needle in ("Naschitz, Brandes, Amir & Co.", "Keshet Sirota-Leviner", "22 November 2026, 12:00–13:00",
                   "coordinating partner", "named partner", "conflict check", "fee proposal per area"):
        assert needle.lower() in md.lower(), needle


def test_no_meeting_preparation_notes():
    md = _md().lower()
    for internal in ("do not open", "run of show", "talking points", "keshet's desk", "state no rate",
                     "do not state", "hard stop", "phins strength", "decision outputs", "elevator",
                     "pitch-dashboard", "pitch dashboard", "meeting diary", "point of view",
                     "/legal/", "services/", "ai_decision_log", "ledger decides"):
        assert internal not in md, internal


def test_figures_are_canonical():
    plan = compute_plan()
    funding = plan["funding"]
    factors = {f["id"]: f["default"] for f in plan["factors"]}
    assert plan["plan_version"] == "unified-2026.10-v1"
    assert (funding["seed"], funding["pre_money"], funding["post_money"], funding["series_a_indicative"]) == (
        6_000_000, 24_000_000, 30_000_000, 18_000_000)
    assert factors["cession_rate"] == 0.18 and factors["ceding_commission"] == 0.25
    assert plan["carrier_view"]["rows"][0]["ceded_premium"] == 9_758_880
    md = _md()
    for needle in ("unified-2026.10-v1", "ILS 6,000,000", "ILS 24,000,000", "ILS 30,000,000",
                   "ILS 18,000,000", "ILS 9,758,880", "18% quota share", "25% ceding commission"):
        assert needle in md, needle
    assert set(re.findall(r"\d+(?:\.\d+)?%", md)) <= {"25%", "75%", "18%"}
    assert "no insurer agreement is signed" in md
    assert "Neither round is closed." in md
    assert "is not yet approved" in md
    assert "No agreement with an insurer, a reinsurer, an investor, or the firm is recorded as signed, and no regulatory approval is recorded." in md
    for claim in ("has approved", "approved the product", "has been approved", "agreement was signed"):
        assert claim not in md.lower(), claim


def test_listed_materials_exist():
    for path in ("legal/incorporation-delaware.html", "legal/founder-agreement.html",
                 "legal/cofounder-exit-clause.html", "legal/cap-table.html",
                 "legal/shareholders-agreement.html", "legal/term-sheet.html",
                 "legal/employment-agreement.html", "legal/offer-letter.html",
                 "legal/esop-agreement.html", "legal/hr-policies.html", "terms-of-use.html",
                 "privacy-policy.html", "legal/ip-assignment.html", "legal/trademark-ip.html",
                 "legal/nda.html", "legal/financial-model.html", "business-plan.html",
                 "investor-docs/swiss-re-israel-meeting-8dec2026-deck.pdf",
                 "investor-docs/israel-regulatory-application-he.pdf"):
        assert (STATIC / path).is_file(), path


def test_registered_rendered_and_downloadable():
    mod = _generator()
    assert (MD_NAME, f"investor-docs/{STEM}.pdf",
            "PHINS — Request for Legal Services · Naschitz, Brandes, Amir & Co. (NBA Law) · 22 November 2026"
            ) in mod.DOCUMENTS
    meta = mod.DESIGNED_BRIEFS[MD_NAME]
    assert meta["html"] == f"investor-docs/{STEM}.html"
    html_doc = (DOCS / f"{STEM}.html").read_text(encoding="utf-8")
    assert "linear-gradient(135deg, #060d1f 0%, #0e2f63 46%, #123f82 100%)" in html_doc
    assert 'class="phins-doc-logo"' in html_doc and "Space Grotesk" in html_doc
    pdf = (DOCS / f"{STEM}.pdf").read_bytes()
    assert pdf[:5] == b"%PDF-" and b"%%EOF" in pdf[-2048:]
    dash = (STATIC / "pitch-dashboard.html").read_text(encoding="utf-8")
    section = dash[dash.index('<section id="nba-law-meeting-22nov"'):]
    section = section[:section.index("</section>")]
    assert f'href="/investor-docs/{STEM}.html"' in section
    assert f'href="/investor-docs/{STEM}.pdf" target="_blank" rel="noopener" class="exec-dl-btn" download' in section


def test_designed_html_is_a_fresh_render(tmp_path):
    mod = _generator()
    title = next(t for src, _pdf, t in mod.DOCUMENTS if src == MD_NAME)
    out = tmp_path / "request.html"
    mod.write_designed_brief(str(DOCS / f"{STEM}.md"), str(out), mod.DESIGNED_BRIEFS[MD_NAME], title)
    assert out.read_text(encoding="utf-8") == (DOCS / f"{STEM}.html").read_text(encoding="utf-8")


def test_every_edition_is_confidential_and_the_pdf_is_staff_only():
    for ext in ("html", "pdf", "md"):
        path = f"/investor-docs/{STEM}.{ext}"
        assert ca.is_confidential_path(path), path
        assert ca.is_confidential_path(path.upper()), path
    assert ca.is_downloadable_document(f"/investor-docs/{STEM}.pdf")
