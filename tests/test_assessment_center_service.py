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
