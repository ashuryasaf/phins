"""
Tests for Phase 2 of the multimodal document intelligence pipeline:

- DOCX text extraction (stdlib OOXML parser)
- PDF per-page char-offset maps in extracted metadata
- Fact provenance (source_text snippet, char offsets, page number)
- Cross-document contradiction detection (CONFLICT facts, never silently
  resolved; format-different dates are not false conflicts)
"""

import base64
import io
import json
import zipfile

import pytest

from services.document_processing_service import DocumentProcessingService
from services.assessment_center_service import AssessmentCenterService


# ── Fixture builders ─────────────────────────────────────────────────────────

def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _make_docx(paragraphs) -> bytes:
    """Minimal valid DOCX: zip with word/document.xml."""
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(
        f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs
    )
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<w:document {ns}><w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", document)
    return buffer.getvalue()


def _make_pdf(pages) -> bytes:
    """Multi-page PDF with real text layer via reportlab."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    for page_text in pages:
        y = 700
        for line in page_text.split("\n"):
            pdf.drawString(72, y, line)
            y -= 20
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


@pytest.fixture
def doc_service(tmp_path):
    return DocumentProcessingService(storage_root=str(tmp_path / "docs"))


@pytest.fixture
def center(tmp_path, doc_service):
    return AssessmentCenterService(
        document_service=doc_service,
        fact_store_dir=str(tmp_path / "facts"),
    )


# ── DOCX extraction ───────────────────────────────────────────────────────────

def test_docx_text_extraction_on_upload(doc_service):
    raw = _make_docx([
        "Insurance Policy Agreement",
        "The insured suffers from diabetes and hypertension.",
        "Monthly premium: 450 NIS",
    ])
    result = doc_service.upload_document(
        file_name="policy.docx", file_data_b64=_b64(raw),
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    record = doc_service.get_document(result.document_id)
    text = record.get("extracted_text") or ""
    assert "Insurance Policy Agreement" in text
    assert "diabetes" in text
    assert "Monthly premium" in text


def test_docx_corrupt_returns_empty(doc_service):
    assert doc_service._extract_docx_text(b"not a zip at all") == ""


def test_docx_feeds_assessment_facts(center):
    raw = _make_docx(["Patient diagnosed with diabetes.",
                      "Contact: john@example.com"])
    result = center.upload_and_assess(
        file_name="medical.docx", file_data_b64=_b64(raw),
        customer_id="CUST-DOCX",
    )
    types = {f.fact_type for f in result.facts}
    assert "medical_condition" in types
    emails = [f for f in result.facts if f.label == "email"]
    assert emails and emails[0].value == "john@example.com"


# ── PDF page map ──────────────────────────────────────────────────────────────

def test_pdf_page_offsets_stored_in_metadata(doc_service):
    raw = _make_pdf(["First page about insurance premium 1200",
                     "Second page mentions diabetes diagnosis"])
    result = doc_service.upload_document(
        file_name="report.pdf", file_data_b64=_b64(raw),
        mime_type="application/pdf",
    )
    record = doc_service.get_document(result.document_id)
    meta = json.loads(record.get("extracted_metadata") or "{}")
    pages = meta.get("pages")
    assert pages and len(pages) == 2
    assert pages[0]["page"] == 1 and pages[0]["char_start"] == 0
    assert pages[1]["page"] == 2
    assert pages[1]["char_start"] > pages[0]["char_start"]

    text = record.get("extracted_text") or ""
    page2 = text[pages[1]["char_start"]:pages[1]["char_end"]]
    assert "diabetes" in page2
    assert "First page" not in page2


def test_facts_carry_page_number_from_pdf(center):
    raw = _make_pdf(["Cover letter with nothing medical",
                     "Patient suffers from diabetes"])
    result = center.upload_and_assess(
        file_name="medical.pdf", file_data_b64=_b64(raw),
        customer_id="CUST-PAGES",
    )
    conditions = [f for f in result.facts if f.fact_type == "medical_condition"]
    assert conditions, "diabetes fact expected"
    assert conditions[0].page == 2
    assert conditions[0].source_text and "diabetes" in conditions[0].source_text.lower()


# ── Provenance on plain text ──────────────────────────────────────────────────

def test_facts_have_source_text_and_offsets(center):
    content = ("Customer file. The patient has diabetes and takes insulin. "
               "Email: alice@example.org. BMI 31.5 recorded at last visit.")
    result = center.upload_and_assess(
        file_name="notes.txt", file_data_b64=_b64(content.encode()),
        mime_type="text/plain", customer_id="CUST-PROV",
    )
    by_label = {f.label: f for f in result.facts}

    email = by_label["email"]
    assert email.char_start is not None and email.char_end is not None
    assert content[email.char_start:email.char_end].lower() == "alice@example.org"
    assert "alice@example.org" in email.source_text.lower()

    bmi = by_label["bmi"]
    assert bmi.value == 31.5
    assert "31.5" in content[bmi.char_start:bmi.char_end]
    assert "bmi" in bmi.source_text.lower()


def test_provenance_survives_fact_store_roundtrip(tmp_path, doc_service):
    store = str(tmp_path / "facts")
    center = AssessmentCenterService(document_service=doc_service, fact_store_dir=store)
    content = "Diagnosis: diabetes. Contact bob@example.com"
    center.upload_and_assess(
        file_name="n.txt", file_data_b64=_b64(content.encode()),
        mime_type="text/plain", customer_id="CUST-RT",
    )
    # Fresh service instance loads facts from disk.
    reloaded = AssessmentCenterService(document_service=doc_service, fact_store_dir=store)
    facts = reloaded.get_facts("CUST-RT", fact_type="contact")
    assert facts
    assert facts[0]["source_text"] and "bob@example.com" in facts[0]["source_text"]
    assert facts[0]["char_start"] is not None


# ── Cross-document contradictions ─────────────────────────────────────────────

def _upload_text(center, customer_id, name, content):
    return center.upload_and_assess(
        file_name=name, file_data_b64=_b64(content.encode()),
        mime_type="text/plain", customer_id=customer_id,
    )


def test_conflicting_bmi_across_documents_flagged(center):
    _upload_text(center, "CUST-CONF", "doc_a.txt", "Medical exam. BMI 24.0 normal range.")
    result_b = _upload_text(center, "CUST-CONF", "doc_b.txt", "Second exam. BMI 33.0 obese range.")

    assert result_b.summary.get("contradictions", 0) >= 1
    contradictions = center.get_facts("CUST-CONF", fact_type="contradiction")
    assert len(contradictions) == 1
    conflict = contradictions[0]
    assert conflict["label"] == "vital_sign:bmi"
    assert conflict["value"]["status"] == "CONFLICT"
    claimed = {v["value"] for v in conflict["value"]["values"]}
    assert claimed == {24.0, 33.0}
    # Both source documents are cited — nothing silently chosen.
    all_docs = {d for v in conflict["value"]["values"] for d in v["document_ids"]}
    assert len(all_docs) == 2
    assert conflict["metadata"]["requires_review"] is True


def test_same_value_across_documents_is_not_a_conflict(center):
    _upload_text(center, "CUST-OK", "a.txt", "Checkup BMI 25.0")
    _upload_text(center, "CUST-OK", "b.txt", "Followup BMI 25.0")
    assert center.get_facts("CUST-OK", fact_type="contradiction") == []


def test_date_format_difference_is_not_a_conflict(center):
    _upload_text(center, "CUST-DOB", "a.txt", "Date of birth: 1980-05-01")
    _upload_text(center, "CUST-DOB", "b.txt", "Date of birth: 01/05/1980")
    assert center.get_facts("CUST-DOB", fact_type="contradiction") == []


def test_genuinely_different_dob_is_a_conflict(center):
    _upload_text(center, "CUST-DOB2", "a.txt", "Date of birth: 1980-05-01")
    _upload_text(center, "CUST-DOB2", "b.txt", "Date of birth: 1975-11-23")
    contradictions = center.get_facts("CUST-DOB2", fact_type="contradiction")
    assert len(contradictions) == 1
    assert contradictions[0]["label"] == "identity:date_of_birth"


def test_conflict_detection_idempotent(center):
    _upload_text(center, "CUST-IDEM", "a.txt", "BMI 24.0")
    _upload_text(center, "CUST-IDEM", "b.txt", "BMI 33.0")
    # Re-running detection must not duplicate the stored conflict.
    center.detect_and_store_conflicts("CUST-IDEM")
    center.detect_and_store_conflicts("CUST-IDEM")
    assert len(center.get_facts("CUST-IDEM", fact_type="contradiction")) == 1


def test_single_document_variation_is_not_cross_document_conflict(center):
    _upload_text(center, "CUST-ONE", "a.txt",
                 "History: BMI 24.0 in 2020. BMI 27.5 in 2024.")
    assert center.get_facts("CUST-ONE", fact_type="contradiction") == []
