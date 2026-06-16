"""
Tests for the downloadable Business Plan (Executive) PDF surfaced on the pitch
dashboard's Investor Documents section.

Covers three layers:
- the generator (``scripts/generate_investor_pdfs.py``) lists the plan and its
  ``--check`` passes,
- the shipped PDF exists, is a valid PDF, and preserves the canonical figures
  (data integrity), and
- the dashboard card opens / offers the PDF, and the server serves it inline as
  ``application/pdf`` (the markdown source is no longer a blank octet-stream).
"""

import os
import importlib.util
from pathlib import Path
from urllib.request import urlopen, Request

import pytest

REPO = Path(__file__).resolve().parents[1]
STATIC = REPO / "web_portal" / "static"
PLAN_MD = STATIC / "PHINS_Business_Plan_Executive.md"
PLAN_PDF = STATIC / "PHINS_Business_Plan_Executive.pdf"


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_investor_pdfs", REPO / "scripts" / "generate_investor_pdfs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generator_includes_business_plan():
    mod = _load_generator()
    srcs = {src for src, _pdf, _title in mod.DOCUMENTS}
    outs = {pdf for _src, pdf, _title in mod.DOCUMENTS}
    assert "PHINS_Business_Plan_Executive.md" in srcs
    assert "PHINS_Business_Plan_Executive.pdf" in outs
    # every declared source resolves under the served static root
    for src, _pdf, _title in mod.DOCUMENTS:
        assert (Path(mod.STATIC_DIR) / src).is_file(), f"missing source {src}"


def test_generator_check_passes():
    mod = _load_generator()
    assert mod.main(["--check"]) == 0


def test_business_plan_pdf_is_valid():
    assert PLAN_PDF.is_file(), "Business Plan PDF was not generated"
    data = PLAN_PDF.read_bytes()
    assert data[:5] == b"%PDF-", "not a valid PDF header"
    assert b"%%EOF" in data[-2048:], "missing PDF EOF marker"
    assert len(data) > 4096, "PDF unexpectedly small"


def test_business_plan_pdf_preserves_canonical_figures():
    """The PDF is generated from the markdown, so the headline figures the
    investor sees must reconcile to the canonical source."""
    PdfReader = None
    for name in ("pypdf", "PyPDF2"):
        try:
            PdfReader = importlib.import_module(name).PdfReader
            break
        except Exception:
            continue
    if PdfReader is None:
        pytest.skip("no PDF text-extraction library available")

    reader = PdfReader(str(PLAN_PDF))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    md = PLAN_MD.read_text(encoding="utf-8")

    for needle in ("Executive Summary", "3.2 trillion", "1,000,000",
                   "17.7", "Series A", "asaf@phins.ai"):
        assert needle in md, f"canonical markdown drifted, missing {needle!r}"
        assert needle in text, f"PDF missing canonical figure {needle!r}"


def test_dashboard_card_opens_and_downloads_pdf():
    pd = (STATIC / "pitch-dashboard.html").read_text(encoding="utf-8")
    # the open action now points at the PDF (was a blank .md octet-stream)
    assert '/PHINS_Business_Plan_Executive.pdf" target="_blank" rel="noopener" class="exec-dl-btn">📄 Open Business Plan' in pd
    # an explicit downloadable PDF link is present
    assert '/PHINS_Business_Plan_Executive.pdf" target="_blank" rel="noopener" class="exec-dl-btn" download' in pd
    # the canonical markdown source remains linked
    assert "/PHINS_Business_Plan_Executive.md" in pd


@pytest.mark.skipif(not os.environ.get("TEST_BASE_URL"),
                    reason="embedded server base URL not available")
def test_server_serves_pdf_inline_and_md_as_text():
    base = os.environ["TEST_BASE_URL"].rstrip("/")

    with urlopen(Request(base + "/PHINS_Business_Plan_Executive.pdf")) as resp:
        assert resp.status == 200
        assert resp.headers.get("Content-Type") == "application/pdf"
        assert resp.read(5) == b"%PDF-"

    with urlopen(Request(base + "/PHINS_Business_Plan_Executive.md")) as resp:
        assert resp.status == 200
        ctype = resp.headers.get("Content-Type", "")
        assert ctype.startswith("text/plain")
