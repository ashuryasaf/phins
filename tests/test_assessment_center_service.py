"""
Tests for the unified Assessment Center service.

Covers:
- Multi-country ID number extraction with checksum validation
- Medical condition / medication / vital sign extraction
- Insurance and savings indicator extraction
- Customer 360 aggregation (deterministic, deduplicated)
- Risk indicator scoring derived from the unified fact store
- Chart-data generation for dashboards
- External fact ingestion (Mislaka rows are facts, not statistics)
- Re-uploadable customer pack export/import with SHA-256 integrity
"""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import tempfile

import pytest

from services.assessment_center_service import (
    AssessmentCenterService,
    Fact,
    _ID_PATTERNS,
    _israeli_id_valid,
    _us_ssn_valid,
    _cpf_valid,
    _aadhaar_valid,
    _spain_dni_valid,
)
from services.mislaka_api_service import (
    MislakaPerson,
    MislakaPolicy,
    MislakaQueryResult,
    MislakaStatus,
)
from services.mislaka_report_generator import link_to_assessment_center
from services.document_processing_service import (
    DocumentProcessingService,
    reset_document_service,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_storage(tmp_path):
    return tmp_path


@pytest.fixture
def doc_service(tmp_storage):
    reset_document_service()
    svc = DocumentProcessingService(storage_root=str(tmp_storage / "docs"))
    return svc


@pytest.fixture
def center(tmp_storage, doc_service):
    return AssessmentCenterService(
        document_service=doc_service,
        fact_store_dir=str(tmp_storage / "facts"),
    )


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _b64_bytes(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


# ── ID validators ────────────────────────────────────────────────────────────

class TestIdValidators:
    def test_israeli_id_checksum(self):
        # 123456782 is a known valid Teudat Zehut.
        assert _israeli_id_valid("123456782") is True
        assert _israeli_id_valid("123456789") is False

    def test_us_ssn_checksum(self):
        assert _us_ssn_valid("123-45-6789") is True
        assert _us_ssn_valid("000-12-3456") is False
        assert _us_ssn_valid("666-12-3456") is False

    def test_brazil_cpf_checksum(self):
        # 529.982.247-25 is a textbook valid CPF.
        assert _cpf_valid("529.982.247-25") is True
        assert _cpf_valid("111.111.111-11") is False

    def test_india_aadhaar_checksum(self):
        # 234123412346 is a Verhoeff-valid sample.
        assert _aadhaar_valid("234123412346") is True
        assert _aadhaar_valid("234123412345") is False

    def test_spain_dni_checksum(self):
        assert _spain_dni_valid("12345678Z") is True
        assert _spain_dni_valid("12345678A") is False


# ── Document extraction ──────────────────────────────────────────────────────

class TestDocumentExtraction:
    def test_extracts_israeli_id_with_provenance(self, center, doc_service):
        text = "Customer file. Teudat Zehut: 123456782. Email: alice@example.com"
        upload = doc_service.upload_document(
            file_name="profile.txt",
            file_data_b64=_b64(text),
            mime_type="text/plain",
            customer_id="CUST-1",
            skip_processing=False,
        )
        result = center.assess_document(upload.document_id, customer_id="CUST-1")
        id_facts = [f for f in result.facts if f.fact_type == "identity" and f.label == "id_number"]
        assert id_facts, "expected an Israeli ID fact"
        fact = id_facts[0]
        assert fact.value == "123456782"
        assert fact.metadata["country"] == "IL"
        assert fact.source_document_id == upload.document_id
        assert fact.source_document_sha256 == upload.sha256
        assert fact.confidence >= 0.9

    def test_extracts_hebrew_israeli_id_with_label(self, center, doc_service):
        text = "שם מלא: אסף אשורי\nת.ז. 123456782\nכתובת: רחוב הרצל 12"
        upload = doc_service.upload_document(
            file_name="hebrew.txt",
            file_data_b64=_b64(text),
            mime_type="text/plain",
            customer_id="CUST-HEB",
        )
        result = center.assess_document(upload.document_id, customer_id="CUST-HEB")
        types = {f.fact_type for f in result.facts}
        assert "identity" in types
        # Should extract a name and an Israeli id (hebrew-prefixed pattern).
        id_facts = [f for f in result.facts
                    if f.fact_type == "identity" and f.label == "id_number"]
        name_facts = [f for f in result.facts
                      if f.fact_type == "identity" and f.label == "full_name"]
        assert any(f.value == "123456782" for f in id_facts)
        assert any(name_facts), "expected a name extracted from Hebrew label"

    def test_always_emits_metadata_fact_for_any_upload(self, center, doc_service):
        # A non-empty upload that yields no extractable identity / medical
        # / financial signal still produces at least the document_meta
        # fact, so the workbench never shows "facts: 0" for a successful
        # upload. We send a tiny binary blob that isn't a recognised
        # text format so the parsers find nothing.
        upload = doc_service.upload_document(
            file_name="opaque.txt",
            file_data_b64=_b64("zzz"),
            mime_type="text/plain",
            customer_id="CUST-BLANK",
        )
        result = center.assess_document(upload.document_id, customer_id="CUST-BLANK")
        types = {f.fact_type for f in result.facts}
        assert "document_meta" in types
        assert result.summary["facts_extracted"] >= 1

    def test_extracts_facts_from_excel_workbook(self, center, doc_service):
        # Real xlsx with cell content - openpyxl-based extraction must
        # surface the identity / medical / insurance signal so the
        # workbench can describe the data.
        try:
            from openpyxl import Workbook
        except ImportError:
            import pytest
            pytest.skip("openpyxl unavailable")
        import io as _io
        wb = Workbook(); ws = wb.active
        ws.append(['Name', 'ID', 'Premium', 'Diagnosis'])
        ws.append(['Asaf', '123456782', 1500.0, 'diabetes'])
        buf = _io.BytesIO(); wb.save(buf)
        upload = doc_service.upload_document(
            file_name='premium.xlsx',
            file_data_b64=_b64_bytes(buf.getvalue()),
            mime_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            customer_id='CUST-XLS',
        )
        result = center.assess_document(upload.document_id, customer_id='CUST-XLS')
        types = {f.fact_type for f in result.facts}
        assert 'identity' in types
        assert 'medical_condition' in types

    def test_extracts_facts_from_zip_bundle(self, center, doc_service):
        # Bundle of mixed documents inside a zip - the extractor must
        # walk every entry and surface the union of facts.
        import io as _io
        import zipfile as _zip
        buf = _io.BytesIO()
        with _zip.ZipFile(buf, 'w') as zf:
            zf.writestr('id.txt', 'Israeli ID 123456782. Full Name: Asaf')
            zf.writestr('med.txt', 'Diagnosis: diabetes. Medication: metformin. BMI: 31.')
        upload = doc_service.upload_document(
            file_name='bundle.zip',
            file_data_b64=_b64_bytes(buf.getvalue()),
            mime_type='application/zip',
            customer_id='CUST-ZIP',
        )
        result = center.assess_document(upload.document_id, customer_id='CUST-ZIP')
        types = {f.fact_type for f in result.facts}
        assert 'identity' in types
        assert 'medical_condition' in types
        assert 'medication' in types

    def test_extraction_hint_when_no_text_mined(self, center, doc_service):
        # Image upload with no embedded text triggers the hint fact so
        # the user knows why facts are sparse and can take action.
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        import base64 as _b64m
        upload = doc_service.upload_document(
            file_name="id-scan.png",
            file_data_b64=_b64m.b64encode(png_header).decode(),
            mime_type="image/png",
            customer_id="CUST-IMG",
        )
        result = center.assess_document(upload.document_id, customer_id="CUST-IMG")
        types = {f.fact_type for f in result.facts}
        assert "document_meta" in types
        assert "extraction_hint" in types

    def test_extracts_us_ssn_only_when_valid(self, center, doc_service):
        text = "SSN: 123-45-6789. Other ref 000-12-3456."
        upload = doc_service.upload_document(
            file_name="usid.txt",
            file_data_b64=_b64(text),
            mime_type="text/plain",
            customer_id="CUST-US",
        )
        result = center.assess_document(upload.document_id, customer_id="CUST-US")
        ssn_facts = [
            f for f in result.facts
            if f.fact_type == "identity" and f.metadata.get("id_type") == "us_ssn"
        ]
        assert len(ssn_facts) == 1
        assert ssn_facts[0].value == "123-45-6789"

    def test_extracts_medical_facts(self, center, doc_service):
        text = (
            "Diagnosis: Diabetes type 2 with hypertension. "
            "Patient takes metformin and insulin. BMI: 32.5. "
            "BP: 145/92. Allergic to penicillin."
        )
        upload = doc_service.upload_document(
            file_name="med.txt",
            file_data_b64=_b64(text),
            mime_type="text/plain",
            customer_id="CUST-MED",
        )
        result = center.assess_document(upload.document_id, customer_id="CUST-MED")
        types = {f.fact_type for f in result.facts}
        assert "medical_condition" in types
        assert "medication" in types
        assert "allergy" in types
        assert "vital_sign" in types

        bmi = next(f for f in result.facts if f.fact_type == "vital_sign" and f.label == "bmi")
        assert bmi.value == 32.5

    def test_extracts_insurance_and_savings_amounts(self, center, doc_service):
        text = (
            "Annual premium: 1,250.00 USD. Sum insured: 500000. "
            "Policy number: POL-12345. Pension balance: 87,500.00."
        )
        upload = doc_service.upload_document(
            file_name="policy.txt",
            file_data_b64=_b64(text),
            mime_type="text/plain",
            customer_id="CUST-PRM",
        )
        result = center.assess_document(upload.document_id, customer_id="CUST-PRM")
        ins_facts = [f for f in result.facts if f.fact_type == "insurance"]
        sav_facts = [f for f in result.facts if f.fact_type == "savings"]
        assert any(f.label == "premium" and isinstance(f.value, float) for f in ins_facts)
        assert any(f.label == "sum insured" for f in ins_facts)
        assert any(f.label == "balance" and isinstance(f.value, float) for f in sav_facts)


# ── Customer 360 aggregation ─────────────────────────────────────────────────

class TestCustomer360:
    def test_360_dedup_and_provenance(self, center, doc_service):
        text1 = "ID 123456782. Diagnosis: diabetes. Medication: metformin."
        text2 = "ID 123456782. Diagnosis: diabetes. Medication: insulin. Address: 12 Main St."

        for i, text in enumerate((text1, text2)):
            upload = doc_service.upload_document(
                file_name=f"file{i}.txt",
                file_data_b64=_b64(text),
                mime_type="text/plain",
                customer_id="CUST-360",
            )
            center.assess_document(upload.document_id, customer_id="CUST-360")

        profile = center.build_customer_360("CUST-360")
        assert profile["fact_count"] >= 4
        # ID number should not duplicate
        ids = profile["identity"]["id_numbers"]
        assert sum(1 for entry in ids if entry["value"] == "123456782") == 1
        # Conditions should not duplicate
        conds = profile["medical"]["conditions"]
        assert conds.count("diabetes") == 1
        # Provenance is tracked
        assert len(profile["data_integrity"]["documents"]) == 2
        assert len(profile["data_integrity"]["sha256_set"]) == 2

    def test_risk_indicator_scoring(self, center, doc_service):
        text = (
            "Patient has stage 4 cancer. Diagnosis: heart disease. "
            "BMI: 36. BP: 165/100. Document classification: VERY HIGH RISK."
        )
        upload = doc_service.upload_document(
            file_name="risk.txt",
            file_data_b64=_b64(text),
            mime_type="text/plain",
            customer_id="CUST-RISK",
        )
        center.assess_document(upload.document_id, customer_id="CUST-RISK")

        risk = center.compute_risk_indicators("CUST-RISK")
        assert risk["risk_score"] > 0.5
        assert risk["risk_level"] in ("high", "very_high")
        assert risk["scale"] == "0-1"
        assert risk["platform_signals_applied"] is False
        assert "fact_store" in risk["sources"]
        assert any(c["factor"] == "condition" for c in risk["contributors"])
        assert any(c["factor"] == "bmi" for c in risk["contributors"])
        assert any(c["factor"] == "blood_pressure" for c in risk["contributors"])

    def test_chart_data_shape(self, center, doc_service):
        text = (
            "Diagnosis: diabetes. Diagnosis: hypertension. "
            "Pension balance: 25000. Sum insured: 100000."
        )
        upload = doc_service.upload_document(
            file_name="dash.txt",
            file_data_b64=_b64(text),
            mime_type="text/plain",
            customer_id="CUST-CHART",
        )
        center.assess_document(upload.document_id, customer_id="CUST-CHART")
        charts = center.build_chart_data("CUST-CHART")
        assert "charts" in charts
        for series_name in (
            "risk_breakdown",
            "condition_distribution",
            "external_sources",
            "savings_distribution",
            "coverage_distribution",
        ):
            series = charts["charts"][series_name]
            assert isinstance(series, list)
            for entry in series:
                assert "label" in entry and "value" in entry
        assert charts["totals"]["risk_score"] >= 0


# ── External facts (Mislaka style) ───────────────────────────────────────────

class TestExternalFacts:
    def test_ingest_external_facts_is_not_aggregated(self, center):
        rows = [
            {"policy_id": "P1", "product_type": "pension", "accumulated_value": 25000.0},
            {"policy_id": "P2", "product_type": "life_insurance", "accumulated_value": 10000.0},
        ]
        result = center.ingest_external_facts(
            customer_id="CUST-EXT",
            source="mislaka",
            records=rows,
        )
        assert result.summary["facts_extracted"] == 2
        # Each row stored verbatim with full provenance.
        for f in result.facts:
            assert f.fact_type == "external_policy"
            assert f.source == "mislaka"
            assert f.metadata["row"]["accumulated_value"] in (25000.0, 10000.0)

        # The Customer 360 view exposes the rows but never invents totals.
        profile = center.build_customer_360("CUST-EXT")
        assert "mislaka" in profile["external_sources"]
        assert len(profile["external_sources"]["mislaka"]) == 2

    def test_external_records_increase_risk_when_many(self, center):
        rows = [{"policy_id": f"P{i}"} for i in range(7)]
        center.ingest_external_facts(
            customer_id="CUST-LOAD",
            source="mislaka",
            records=rows,
        )
        risk = center.compute_risk_indicators("CUST-LOAD")
        contributors = {c["factor"] for c in risk["contributors"]}
        assert "external_policy_count" in contributors


# ── Re-uploadable pack ───────────────────────────────────────────────────────

class TestReuploadablePack:
    def test_export_import_round_trip_preserves_integrity(self, center, doc_service, tmp_storage):
        text = "ID 123456782. Diagnosis: cancer. Premium: 1,000."
        upload = doc_service.upload_document(
            file_name="pack.txt",
            file_data_b64=_b64(text),
            mime_type="text/plain",
            customer_id="CUST-PACK",
        )
        center.assess_document(upload.document_id, customer_id="CUST-PACK")
        pack = center.export_customer_pack("CUST-PACK")
        assert pack["sha256"]
        original_facts = pack["facts"]
        assert original_facts

        # Fresh center should be empty until import is performed.
        fresh = AssessmentCenterService(
            document_service=doc_service,
            fact_store_dir=str(tmp_storage / "facts2"),
        )
        assert fresh.get_facts("CUST-PACK") == []
        report = fresh.import_customer_pack(pack)
        assert report["integrity_ok"] is True
        assert report["imported_facts"] == len(original_facts)
        assert len(fresh.get_facts("CUST-PACK")) == len(original_facts)

    def test_backfill_assesses_pre_existing_documents(self, center, doc_service):
        # Simulate a document that was uploaded before the Assessment Center
        # was wired (skip_processing means no extracted text on disk).
        upload = doc_service.upload_document(
            file_name="legacy.txt",
            file_data_b64=_b64("Customer 123456782 was diagnosed with diabetes. BMI: 31."),
            mime_type="text/plain",
            customer_id="CUST-LEGACY",
            skip_processing=True,
        )
        # Before backfill, no facts exist for the legacy customer.
        assert center.get_facts("CUST-LEGACY") == []
        status = center.backfill_status()
        assert status["without_facts"] >= 1

        result = center.backfill_documents()
        assert result["scanned"] >= 1
        assert result["assessed"] >= 1
        assert "CUST-LEGACY" in result["customers_updated"]
        assert center.get_facts("CUST-LEGACY"), "expected facts after backfill"

        # Idempotency: a second run skips the same document.
        again = center.backfill_documents()
        assert again["assessed"] == 0
        assert again["skipped"] >= 1

        # Force: re-extract even when facts exist.
        forced = center.backfill_documents(force=True, document_ids=[upload.document_id])
        assert forced["scanned"] == 1
        assert forced["assessed"] == 1

    def test_describe_data_groups_facts_by_relevance_category(self, center, doc_service):
        # Upload three different document types in the same scenario the user
        # described: ID, medical and financial together.
        doc_service.upload_document(
            file_name="id.txt",
            file_data_b64=_b64("Customer John Doe. Israeli ID 123456782. Address: 12 Main St."),
            mime_type="text/plain", customer_id="CUST-DESC", document_type="id",
        )
        doc_service.upload_document(
            file_name="med.txt",
            file_data_b64=_b64("Diagnosis: diabetes. Medication: metformin. BMI: 31."),
            mime_type="text/plain", customer_id="CUST-DESC", document_type="medical",
        )
        doc_service.upload_document(
            file_name="fin.txt",
            file_data_b64=_b64("Account balance: 25000. Pension contribution: 850. IBAN: GB82WEST12345698765432."),
            mime_type="text/plain", customer_id="CUST-DESC", document_type="financial",
        )
        # Listed docs above were already auto-processed by upload_document
        # (skip_processing defaults to False), so the assessment center facts
        # are mined directly.
        center.backfill_documents(customer_id="CUST-DESC")

        desc = center.describe_data_with_data("CUST-DESC")
        cats = {s["category"]: s["fact_count"] for s in desc["sections"]}
        assert "Identity" in cats
        assert "Medical" in cats
        assert "Financial" in cats or "Insurance" in cats
        # Provenance: every entry references a source document with a name.
        for section in desc["sections"]:
            for label, entries in section["by_label"].items():
                for entry in entries:
                    assert entry["document_id"]
                    assert entry["sha256"]

    def test_run_analysis_dispatcher_returns_each_type(self, center, doc_service):
        doc_service.upload_document(
            file_name="multi.txt",
            file_data_b64=_b64("ID 123456782. Diagnosis: diabetes. Premium: 1000. Balance: 5000."),
            mime_type="text/plain", customer_id="CUST-DISPATCH",
        )
        center.backfill_documents(customer_id="CUST-DISPATCH")
        for analysis_type in ("describe_data", "customer_360", "risk_assessment", "bi_summary", "cross_document"):
            res = center.run_analysis("CUST-DISPATCH", analysis_type)
            assert res["analysis_type"] in (analysis_type, analysis_type.split("_")[0] if analysis_type == "customer_360" else analysis_type)
            assert "download" in res
            assert "headers" in res["download"]

    def test_export_analysis_emits_csv_xlsx_pdf(self, center, doc_service):
        doc_service.upload_document(
            file_name="export.txt",
            file_data_b64=_b64("ID 123456782. Diagnosis: diabetes. Premium: 1500."),
            mime_type="text/plain", customer_id="CUST-EXPORT",
        )
        center.backfill_documents(customer_id="CUST-EXPORT")

        csv_bytes, csv_mime, csv_name = center.export_analysis("CUST-EXPORT", "describe_data", "csv")
        assert csv_mime == "text/csv"
        assert csv_name.endswith(".csv")
        assert b"category" in csv_bytes

        xlsx_bytes, xlsx_mime, xlsx_name = center.export_analysis("CUST-EXPORT", "describe_data", "xlsx")
        assert xlsx_mime.endswith("spreadsheetml.sheet")
        assert xlsx_name.endswith(".xlsx")
        # XLSX files start with the ZIP magic bytes.
        assert xlsx_bytes[:2] == b"PK"

        pdf_bytes, pdf_mime, pdf_name = center.export_analysis("CUST-EXPORT", "describe_data", "pdf")
        assert pdf_mime == "application/pdf"
        assert pdf_name.endswith(".pdf")
        assert pdf_bytes.startswith(b"%PDF")

    def test_backfill_filters_by_customer(self, center, doc_service):
        d1 = doc_service.upload_document(
            file_name="a.txt", file_data_b64=_b64("ID 123456782. Diagnosis: cancer."),
            mime_type="text/plain", customer_id="CUST-A", skip_processing=True,
        )
        d2 = doc_service.upload_document(
            file_name="b.txt", file_data_b64=_b64("ID 234567880. Diagnosis: stroke."),
            mime_type="text/plain", customer_id="CUST-B", skip_processing=True,
        )
        result = center.backfill_documents(customer_id="CUST-A")
        assert "CUST-A" in result["customers_updated"]
        assert "CUST-B" not in result["customers_updated"]
        assert center.get_facts("CUST-B") == []

    def test_backfill_caps_limit_and_reports_truncation(self, center, doc_service):
        # Seed more documents than the BACKFILL_MAX_LIMIT to make sure the
        # service caps the work it does in a single request even if a caller
        # asks for more than the maximum.
        for i in range(5):
            doc_service.upload_document(
                file_name=f"cap_{i}.txt",
                file_data_b64=_b64(f"ID 12345{(i+10):03d}. Diagnosis: diabetes."),
                mime_type="text/plain", customer_id="CUST-CAP",
                skip_processing=True,
            )
        result = center.backfill_documents(limit=99999)
        assert result["limit_applied"] <= center.BACKFILL_MAX_LIMIT
        assert "time_budget_hit" in result
        assert "truncated" in result

    def test_export_truncates_oversize_csv(self, center, doc_service, monkeypatch):
        # Force the cap down to 5 so the test data exceeds it.
        from services import assessment_center_service as ac_mod
        monkeypatch.setattr(ac_mod, "MAX_EXPORT_ROWS", 5)
        doc_service.upload_document(
            file_name="big.txt",
            file_data_b64=_b64(
                "Diagnosis: diabetes. Diagnosis: hypertension. Diagnosis: cancer. "
                "Diagnosis: stroke. Diagnosis: copd. Medication: metformin. "
                "Medication: insulin. Medication: warfarin. Medication: aspirin. "
                "Medication: omeprazole. Medication: levothyroxine."
            ),
            mime_type="text/plain", customer_id="CUST-BIG",
        )
        center.backfill_documents(customer_id="CUST-BIG")
        csv_bytes, mime, name = center.export_analysis(
            "CUST-BIG", "describe_data", "csv",
        )
        assert b"truncated" in csv_bytes

    def test_tampered_pack_flags_integrity(self, center, doc_service):
        text = "ID 123456782. Diagnosis: cancer."
        upload = doc_service.upload_document(
            file_name="pack2.txt",
            file_data_b64=_b64(text),
            mime_type="text/plain",
            customer_id="CUST-TMP",
        )
        center.assess_document(upload.document_id, customer_id="CUST-TMP")
        pack = center.export_customer_pack("CUST-TMP")
        pack["facts"].append({"fact_id": "tampered", "fact_type": "risk_indicator", "value": "fake"})
        report = center.import_customer_pack(pack)
        assert report["integrity_ok"] is False


def _mislaka_result(policies, id_number="123456782"):
    return MislakaQueryResult(
        request_id="REQ-DOC",
        status=MislakaStatus.SUCCESS,
        timestamp="2026-01-01T00:00:00",
        person=MislakaPerson(id_number=id_number, first_name="Ada", last_name="Levi"),
        policies=policies,
        total_policies=len(policies),
        total_accumulated=0,
        total_monthly_premium=0,
    )


def _mislaka_policy(**kw):
    base = dict(
        policy_id="P-1", policy_number="POL-1", product_type="1", company_name="Migdal",
        company_code="01", start_date="2020-01-01", status="1",
        premium_monthly=100.0, accumulated_value=25000.0,
    )
    base.update(kw)
    return MislakaPolicy(**base)


class TestMislakaReportDocumentHierarchy:
    def test_report_is_a_document_of_the_customer_not_a_new_user(self, center):
        result = _mislaka_result([_mislaka_policy()])
        payload = link_to_assessment_center(
            result, customer_id="CUST-MIS", center=center,
        )
        assert payload["customer_id"] == "CUST-MIS"
        assert payload["customer_id"] != result.person.id_number
        assert center.get_facts(result.person.id_number) == []

        doc_id = payload["document_id"]
        record = center.document_service.get_document(doc_id, include_data=True)
        assert record["customer_id"] == "CUST-MIS"
        assert record["entity_type"] == "customer"
        assert record["entity_id"] == "CUST-MIS"
        assert record["document_type"] == "mislaka_report"
        assert record["sha256_checksum"] == payload["document_sha256"]
        raw = base64.b64decode(record["data"])
        assert hashlib.sha256(raw).hexdigest() == payload["document_sha256"]
        assert b"MISLAKA AFFILIATION REPORT" in raw

        facts = center.get_facts("CUST-MIS")
        assert len(facts) == 1
        assert facts[0]["source_document_id"] == doc_id
        assert facts[0]["source_document_sha256"] == payload["document_sha256"]
        assert facts[0]["source"] == "mislaka"
        summaries = center.get_document_assessments([doc_id])
        assert summaries[doc_id]["facts_extracted"] == 1

    def test_repeat_pull_reuses_the_document_and_does_not_duplicate_facts(self, center):
        result = _mislaka_result([_mislaka_policy(policy_id="P-9")])
        first = link_to_assessment_center(result, customer_id="CUST-MIS", center=center)
        second = link_to_assessment_center(result, customer_id="CUST-MIS", center=center)
        assert second["document_reused"] is True
        assert second["document_id"] == first["document_id"]
        assert second["document_sha256"] == first["document_sha256"]
        assert len(center.get_facts("CUST-MIS")) == 1
        listing = center.document_service.list_documents(customer_id="CUST-MIS", page_size=50)
        reports = [d for d in listing["items"] if d.get("document_type") == "mislaka_report"]
        assert len(reports) == 1

    def test_same_bytes_for_another_customer_stay_on_that_customer(self, center):
        result = _mislaka_result([_mislaka_policy(policy_id="P-shared")])
        a = link_to_assessment_center(result, customer_id="CUST-A", center=center)
        b = link_to_assessment_center(result, customer_id="CUST-B", center=center)
        assert a["document_id"] != b["document_id"]
        assert a["document_sha256"] == b["document_sha256"]
        a_doc = center.document_service.get_document(a["document_id"])
        b_doc = center.document_service.get_document(b["document_id"])
        assert a_doc["customer_id"] == "CUST-A"
        assert b_doc["customer_id"] == "CUST-B"
        assert center.get_facts("CUST-A")[0]["source_document_id"] == a["document_id"]
        assert center.get_facts("CUST-B")[0]["source_document_id"] == b["document_id"]

    def test_changed_row_refreshes_in_place_on_the_new_report(self, center):
        first = link_to_assessment_center(
            _mislaka_result([_mislaka_policy(policy_id="P-1", premium_monthly=100.0)]),
            customer_id="CUST-MIS", center=center,
        )
        second = link_to_assessment_center(
            _mislaka_result([_mislaka_policy(policy_id="P-1", premium_monthly=180.0)]),
            customer_id="CUST-MIS", center=center,
        )
        assert second["document_id"] != first["document_id"]
        facts = center.get_facts("CUST-MIS")
        assert len(facts) == 1
        assert facts[0]["source_document_id"] == second["document_id"]
        assert facts[0]["metadata"]["row"]["premium_monthly"] == 180.0

    def test_refreshed_row_leaves_no_fact_on_the_superseded_report(self, center):
        first = link_to_assessment_center(
            _mislaka_result([_mislaka_policy(policy_id="P-1", premium_monthly=100.0)]),
            customer_id="CUST-MIS", center=center,
        )
        second = link_to_assessment_center(
            _mislaka_result([_mislaka_policy(policy_id="P-1", premium_monthly=180.0)]),
            customer_id="CUST-MIS", center=center,
        )
        assert center.facts_for_documents([first["document_id"]]) == []
        assert len(center.facts_for_documents(
            [first["document_id"], second["document_id"]])) == 1
        old_only = center.get_document_assessments([first["document_id"]])
        assert old_only[first["document_id"]]["facts_extracted"] == 0
        both = center.get_document_assessments(
            [first["document_id"], second["document_id"]])
        assert both[second["document_id"]]["facts_extracted"] == 1

    def test_missing_customer_does_not_invent_a_user_from_the_national_id(self, center):
        result = _mislaka_result([_mislaka_policy()])
        with pytest.raises(ValueError, match="customer_id required"):
            link_to_assessment_center(result, customer_id="", center=center)
        assert center.get_facts("123456782") == []
        listing = center.document_service.list_documents(page_size=50)
        assert listing["total"] == 0
