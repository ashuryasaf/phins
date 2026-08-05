"""
Integration tests: Hebrew documents → Assessment Center facts → risk → records.

Pins the end-to-end loop so IL medical / insurance / savings documents drive
the same canonical English scoring model and durable assessment records as
English uploads.
"""

from __future__ import annotations

import base64

import pytest

from services.assessment_center_service import AssessmentCenterService
from services.assessment_record_service import (
    get_assessment_record_service,
    reset_assessment_record_service,
)
from services.document_processing_service import (
    DocumentProcessingService,
    reset_document_service,
)


@pytest.fixture
def doc_service(tmp_path):
    reset_document_service()
    return DocumentProcessingService(storage_root=str(tmp_path / "docs"))


@pytest.fixture
def center(tmp_path, doc_service):
    reset_assessment_record_service()
    return AssessmentCenterService(
        document_service=doc_service,
        fact_store_dir=str(tmp_path / "facts"),
    )


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


HEBREW_MEDICAL_INSURANCE = """\
דוח רפואי / ביטוח חיים
שם מלא: ישראל ישראלי
ת.ז. 123456782
אבחנות: סוכרת סוג 2, יתר לחץ דם.
תרופות: מטפורמין, אמלודיפין.
סטטוס עישון: מעשן.
מדד מסת גוף: 36.5
לחץ דם: 150/95
אחוזי נכות: 60%
מספר פוליסה: 99887766
פרמיה חודשית: ₪1,250.50
סכום ביטוח: ₪1,000,000
חברה: מגדל
הערכת סיכון: סיכון גבוה
"""


class TestHebrewDocumentAssessmentLoop:
    def test_hebrew_medical_facts_canonical_english(self, center, doc_service):
        upload = doc_service.upload_document(
            file_name="medical_he.txt",
            file_data_b64=_b64(HEBREW_MEDICAL_INSURANCE),
            mime_type="text/plain",
            customer_id="CUST-HE-MED",
        )
        result = center.assess_document(upload.document_id, customer_id="CUST-HE-MED")

        meta = next(f for f in result.facts if f.fact_type == "document_meta")
        assert meta.metadata.get("lang") == "he" or meta.value.get("language") == "he"

        conditions = {
            f.value for f in result.facts if f.fact_type == "medical_condition"
        }
        assert "diabetes" in conditions
        assert "hypertension" in conditions
        # Canonical English values — never store Hebrew as the scored value.
        assert "סוכרת" not in conditions

        meds = {f.value for f in result.facts if f.fact_type == "medication"}
        assert "metformin" in meds

        he_facts = [
            f for f in result.facts
            if (f.metadata or {}).get("extractor") == "hebrew_assessment_lexicon"
        ]
        assert he_facts
        assert any((f.metadata or {}).get("raw_match") for f in he_facts)
        assert result.summary.get("hebrew_facts", 0) >= 1

    def test_hebrew_facts_drive_risk_weights(self, center, doc_service):
        upload = doc_service.upload_document(
            file_name="risk_he.txt",
            file_data_b64=_b64(HEBREW_MEDICAL_INSURANCE),
            mime_type="text/plain",
            customer_id="CUST-HE-RISK",
        )
        center.assess_document(upload.document_id, customer_id="CUST-HE-RISK")
        risk = center.compute_risk_indicators("CUST-HE-RISK")

        factors = {c["factor"]: c for c in risk["contributors"]}
        # diabetes 0.18 + hypertension 0.15 + smoker/high risk + BMI≥35 + BP + disability
        assert risk["risk_score"] >= 0.18 + 0.15
        condition_values = {
            c["value"] for c in risk["contributors"] if c["factor"] == "condition"
        }
        assert "diabetes" in condition_values
        assert "hypertension" in condition_values

        assert any(
            c["factor"] == "risk_marker" and "smoker" in str(c["value"]).lower()
            for c in risk["contributors"]
        ) or any(
            c["factor"] == "risk_marker" and "high" in str(c["value"]).lower()
            for c in risk["contributors"]
        )
        assert any(c["factor"] == "bmi" for c in risk["contributors"])
        assert any(c["factor"] == "disability_percentage" for c in risk["contributors"])
        assert risk["risk_level"] in ("medium", "high", "very_high")

    def test_hebrew_assessment_record_snapshot(self, center, doc_service):
        upload = doc_service.upload_document(
            file_name="snap_he.txt",
            file_data_b64=_b64(HEBREW_MEDICAL_INSURANCE),
            mime_type="text/plain",
            customer_id="CUST-HE-SNAP",
        )
        center.assess_document(upload.document_id, customer_id="CUST-HE-SNAP")

        svc = get_assessment_record_service()
        page = svc.list_records(customer_id="CUST-HE-SNAP", page=1, page_size=50)
        assert page["total"] >= 1
        hebrew_recs = [
            r for r in page["items"]
            if r.get("engine") == "assessment_center+hebrew_lexicon"
            or (r.get("details") or {}).get("trigger") == "hebrew_document_assessment"
        ]
        assert hebrew_recs, "expected durable Hebrew assessment record"
        rec = hebrew_recs[0]
        assert rec["assessment_type"] == "customer_risk"
        assert rec["engine_version"] == "he-rules-1.0.0"
        assert (rec.get("details") or {}).get("document_language") == "he"
        assert svc.verify_record(rec["record_id"]) is True

    def test_negation_does_not_invent_conditions(self, center, doc_service):
        text = (
            "דוח רפואי\n"
            "אין סוכרת. ללא אסתמה. שלילי ל-HIV.\n"
            "אבחנה: יתר לחץ דם.\n"
        )
        upload = doc_service.upload_document(
            file_name="neg_he.txt",
            file_data_b64=_b64(text),
            mime_type="text/plain",
            customer_id="CUST-HE-NEG",
        )
        result = center.assess_document(upload.document_id, customer_id="CUST-HE-NEG")
        conditions = {
            str(f.value).lower()
            for f in result.facts
            if f.fact_type == "medical_condition"
        }
        assert "diabetes" not in conditions
        assert "asthma" not in conditions
        assert "hiv" not in conditions
        assert "aids" not in conditions
        assert "hypertension" in conditions

    def test_structured_insurance_amounts(self, center, doc_service):
        upload = doc_service.upload_document(
            file_name="policy_he.txt",
            file_data_b64=_b64(HEBREW_MEDICAL_INSURANCE),
            mime_type="text/plain",
            customer_id="CUST-HE-POL",
        )
        result = center.assess_document(upload.document_id, customer_id="CUST-HE-POL")
        insurance = {
            f.label: f.value
            for f in result.facts
            if f.fact_type == "insurance"
        }
        assert insurance.get("policy_number") == "99887766"
        assert float(insurance.get("premium")) == pytest.approx(1250.50)
        assert float(insurance.get("sum insured")) == pytest.approx(1_000_000.0)
        assert insurance.get("provider") == "מגדל"

    def test_english_only_document_unchanged(self, center, doc_service):
        text = "Patient has diabetes and hypertension. BMI: 31. Premium: 100 USD."
        upload = doc_service.upload_document(
            file_name="en_only.txt",
            file_data_b64=_b64(text),
            mime_type="text/plain",
            customer_id="CUST-EN-ONLY",
        )
        result = center.assess_document(upload.document_id, customer_id="CUST-EN-ONLY")
        assert result.summary.get("hebrew_facts") in (None, 0)
        he_extractors = [
            f for f in result.facts
            if (f.metadata or {}).get("extractor") == "hebrew_assessment_lexicon"
        ]
        assert he_extractors == []
        conditions = {
            f.value for f in result.facts if f.fact_type == "medical_condition"
        }
        assert "diabetes" in conditions


class TestOcrLangHint:
    def test_hebrew_hint_puts_heb_first(self):
        langs = DocumentProcessingService._ocr_langs_for_hint("דוח_רפואי_he.pdf")
        assert langs.startswith("heb")
        assert "eng" in langs.split("+")

    def test_default_keeps_configured_order(self):
        langs = DocumentProcessingService._ocr_langs_for_hint(None)
        assert "heb" in langs
        assert "eng" in langs
