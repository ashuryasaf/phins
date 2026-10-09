"""Each customer assesses and reads only their own Mislaka report.

Admin filings stay on the assessment path: same document archive, separate
row, shared fact store unchanged. Staff cannot open the personal tool.
"""

from __future__ import annotations

import hashlib

import pytest

from services.assessment_center_service import AssessmentCenterService
from services.document_processing_service import (
    DocumentProcessingService,
    reset_document_service,
)
from services.mislaka_api_service import (
    MislakaPerson,
    MislakaPolicy,
    MislakaQueryResult,
    MislakaStatus,
)
from services.mislaka_report_generator import (
    file_personal_mislaka_report,
    is_personal_mislaka_report,
    link_to_assessment_center,
    list_personal_mislaka_reports,
    read_personal_mislaka_report,
)
from web_portal.api_assessment_center import dispatch_get, dispatch_post


@pytest.fixture
def center(tmp_path):
    reset_document_service()
    docs = DocumentProcessingService(storage_root=str(tmp_path / "docs"))
    return AssessmentCenterService(
        document_service=docs,
        fact_store_dir=str(tmp_path / "facts"),
    )


def _result(policies=None, id_number="123456782"):
    policies = policies or [_policy()]
    return MislakaQueryResult(
        request_id="REQ-PERSONAL",
        status=MislakaStatus.SUCCESS,
        timestamp="2026-01-01T00:00:00",
        person=MislakaPerson(id_number=id_number, first_name="Ada", last_name="Levi"),
        policies=policies,
        total_policies=len(policies),
        total_accumulated=0,
        total_monthly_premium=0,
    )


def _policy(**kw):
    base = dict(
        policy_id="P-1", policy_number="POL-1", product_type="1", company_name="Migdal",
        company_code="01", start_date="2020-01-01", status="1",
        premium_monthly=100.0, accumulated_value=25000.0,
    )
    base.update(kw)
    return MislakaPolicy(**base)


def test_personal_report_is_the_customers_document_and_not_a_shared_fact(center):
    filed = file_personal_mislaka_report(_result(), customer_id="CUST-A", center=center)
    assert filed["customer_id"] == "CUST-A"
    assert filed["customer_id"] != "123456782"
    record = center.document_service.get_document(filed["document_id"], include_data=True)
    assert is_personal_mislaka_report(record)
    assert record["customer_id"] == "CUST-A"
    assert record["uploaded_by"] == "CUST-A"
    assert record["uploaded_by_role"] == "customer"
    raw = __import__("base64").b64decode(record["data"])
    assert hashlib.sha256(raw).hexdigest() == filed["document_sha256"]
    assert center.get_facts("CUST-A") == []
    assert center.get_facts("123456782") == []


def test_repeat_pull_reuses_the_personal_document(center):
    first = file_personal_mislaka_report(_result(), customer_id="CUST-A", center=center)
    second = file_personal_mislaka_report(_result(), customer_id="CUST-A", center=center)
    assert second["document_reused"] is True
    assert second["document_id"] == first["document_id"]
    listing = list_personal_mislaka_reports(center.document_service, "CUST-A")
    assert listing["total"] == 1


def test_admin_filing_stays_separate_and_out_of_the_personal_list(center):
    admin = link_to_assessment_center(_result(), customer_id="CUST-A", center=center)
    personal = file_personal_mislaka_report(_result(), customer_id="CUST-A", center=center)
    assert admin["document_id"] != personal["document_id"]
    assert admin["document_sha256"] == personal["document_sha256"]
    admin_record = center.document_service.get_document(admin["document_id"])
    assert admin_record["uploaded_by_role"] == "system"
    assert is_personal_mislaka_report(admin_record) is False
    listing = list_personal_mislaka_reports(center.document_service, "CUST-A")
    assert [item["id"] for item in listing["items"]] == [personal["document_id"]]
    facts = center.get_facts("CUST-A")
    assert len(facts) == 1
    assert facts[0]["source_document_id"] == admin["document_id"]
    opened = read_personal_mislaka_report(
        center.document_service, "CUST-A", admin["document_id"],
    )
    assert opened is None


def test_another_customer_cannot_read_the_report(center):
    filed = file_personal_mislaka_report(_result(), customer_id="CUST-A", center=center)
    other = file_personal_mislaka_report(_result(), customer_id="CUST-B", center=center)
    assert filed["document_id"] != other["document_id"]
    assert read_personal_mislaka_report(
        center.document_service, "CUST-B", filed["document_id"],
    ) is None
    own = read_personal_mislaka_report(
        center.document_service, "CUST-A", filed["document_id"],
    )
    assert own["integrity_ok"] is True
    assert own["customer_id"] == "CUST-A"
    assert "MISLAKA AFFILIATION REPORT" in own["report_text"]
    assert "id_number" not in own


def test_changed_bytes_keep_the_previous_document(center):
    first = file_personal_mislaka_report(
        _result([_policy(premium_monthly=100.0)]), customer_id="CUST-A", center=center,
    )
    second = file_personal_mislaka_report(
        _result([_policy(premium_monthly=180.0)]), customer_id="CUST-A", center=center,
    )
    assert second["document_id"] != first["document_id"]
    both = list_personal_mislaka_reports(center.document_service, "CUST-A")
    assert both["total"] == 2
    still = center.document_service.get_document(first["document_id"], include_data=True)
    assert still["sha256_checksum"] == first["document_sha256"]


def test_checksum_mismatch_does_not_return_the_report(center):
    filed = file_personal_mislaka_report(_result(), customer_id="CUST-A", center=center)
    record = center.document_service.get_document(filed["document_id"])
    with open(record["storage_path"], "wb") as handle:
        handle.write(b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        read_personal_mislaka_report(
            center.document_service, "CUST-A", filed["document_id"],
        )


def test_missing_customer_does_not_invent_a_user(center):
    with pytest.raises(ValueError, match="customer_id required"):
        file_personal_mislaka_report(_result(), customer_id="", center=center)
    assert center.document_service.list_documents(page_size=20)["total"] == 0


class _FakeMislaka:
    def __init__(self):
        self.calls = []

    def get_person_policies(self, id_number, product_type):
        self.calls.append(id_number)
        return _result(id_number=id_number)


def _session(role, customer_id):
    return {"role": role, "customer_id": customer_id, "username": role}


def test_api_customer_files_and_reads_only_their_report(center, monkeypatch):
    fake = _FakeMislaka()
    monkeypatch.setattr(
        "services.mislaka_api_service.get_mislaka_service", lambda: fake,
    )
    monkeypatch.setattr("web_portal.api_assessment_center._service", lambda: center)

    status, body = dispatch_post(
        "/api/assessment-center/mislaka/personal",
        _session("customer", "CUST-A"),
        {"id_number": "123456782", "customer_id": "CUST-B", "product_type": "all"},
        "127.0.0.1",
    )
    assert status == 403
    assert fake.calls == []

    status, body = dispatch_post(
        "/api/assessment-center/mislaka/personal",
        _session("admin", "CUST-A"),
        {"id_number": "123456782", "product_type": "all"},
        "127.0.0.1",
    )
    assert status == 403
    assert body["error"] == "Access denied"
    assert fake.calls == []

    status, body = dispatch_post(
        "/api/assessment-center/mislaka/personal",
        _session("customer", "CUST-A"),
        {"id_number": "123456782", "product_type": "pension"},
        "127.0.0.1",
    )
    assert status == 200
    assert body["customer_id"] == "CUST-A"
    assert "id_number" not in body
    assert body["document_sha256"]
    doc_id = body["document_id"]

    status, listing = dispatch_get(
        "/api/assessment-center/mislaka/personal",
        _session("customer", "CUST-A"),
        {},
        "127.0.0.1",
    )
    assert status == 200
    assert listing["total"] == 1
    assert "report_text" not in listing["items"][0]
    assert "id_number" not in listing

    status, other = dispatch_get(
        f"/api/assessment-center/mislaka/personal/{doc_id}",
        _session("customer", "CUST-B"),
        {},
        "127.0.0.1",
    )
    assert status == 404

    status, own = dispatch_get(
        f"/api/assessment-center/mislaka/personal/{doc_id}",
        _session("customer", "CUST-A"),
        {},
        "127.0.0.1",
    )
    assert status == 200
    assert own["integrity_ok"] is True
    assert own["customer_id"] == "CUST-A"
    assert "id_number" not in own

    status, hidden = dispatch_get(
        f"/api/assessment-center/mislaka/personal/{doc_id}",
        _session("admin", "CUST-A"),
        {},
        "127.0.0.1",
    )
    assert status == 403
