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


def _result(policies=None, id_number="123456782", status=MislakaStatus.SUCCESS):
    policies = policies or [_policy()]
    return MislakaQueryResult(
        request_id="REQ-PERSONAL",
        status=status,
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


def test_admin_filing_after_a_personal_report_stays_its_own_document(center):
    personal = file_personal_mislaka_report(_result(), customer_id="CUST-A", center=center)
    admin = link_to_assessment_center(_result(), customer_id="CUST-A", center=center)
    assert admin["document_reused"] is False
    assert admin["document_id"] != personal["document_id"]
    admin_record = center.document_service.get_document(admin["document_id"])
    assert is_personal_mislaka_report(admin_record) is False
    facts = center.get_facts("CUST-A")
    assert len(facts) == 1
    assert facts[0]["source_document_id"] == admin["document_id"]
    listing = list_personal_mislaka_reports(center.document_service, "CUST-A")
    assert [item["id"] for item in listing["items"]] == [personal["document_id"]]


def test_staff_listing_pages_the_archive_without_the_personal_lane(center):
    for premium in (100.0, 110.0, 120.0):
        file_personal_mislaka_report(
            _result([_policy(premium_monthly=premium)]), customer_id="CUST-A", center=center,
        )
    for premium in (200.0, 210.0, 220.0):
        link_to_assessment_center(
            _result([_policy(premium_monthly=premium)]), customer_id="CUST-A", center=center,
        )
    docs = center.document_service
    assert docs.list_documents(page=1, page_size=2)["total"] == 6
    first = docs.list_documents(page=1, page_size=2, exclude_personal_mislaka=True)
    second = docs.list_documents(page=2, page_size=2, exclude_personal_mislaka=True)
    assert first["total"] == second["total"] == 3
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    seen = first["items"] + second["items"]
    assert not any(is_personal_mislaka_report(item) for item in seen)
    assert len({item["id"] for item in seen}) == 3


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
    def __init__(self, configured=True, status=MislakaStatus.SUCCESS):
        self.calls = []
        self.configured = configured
        self.status = status

    def is_configured(self):
        return self.configured

    def get_person_policies(self, id_number, product_type):
        self.calls.append(id_number)
        return _result(id_number=id_number, status=self.status)


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

    import web_portal.server as portal
    from services import customer_identity_service as cis

    portal.CUSTOMERS["CUST-A"] = {"id": "CUST-A", "name": "Ada", "email": "ada@example.com"}
    cis.set_identity(
        portal.CUSTOMERS, "CUST-A", "123456782", "IL",
        source="registration", actor="t",
    )
    try:
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
    finally:
        portal.CUSTOMERS.pop("CUST-A", None)
        cis.reset_process_state()


def test_personal_lookup_requires_configuration_and_a_recorded_identity(center, monkeypatch):
    """A typed ID is not stored and is not sent until both gates pass."""
    import web_portal.server as portal
    from services import customer_identity_service as cis

    monkeypatch.setattr("web_portal.api_assessment_center._service", lambda: center)
    portal.CUSTOMERS.pop("CUST-GATE", None)
    unconfigured = _FakeMislaka(configured=False)
    monkeypatch.setattr(
        "services.mislaka_api_service.get_mislaka_service", lambda: unconfigured,
    )
    session = _session("customer", "CUST-GATE")
    payload = {"id_number": "123456782", "product_type": "all"}

    try:
        status, body = dispatch_post(
            "/api/assessment-center/mislaka/personal", session, payload, "127.0.0.1",
        )
        assert status == 503
        assert body["code"] == "mislaka_unconfigured"
        assert unconfigured.calls == []
        assert not cis.is_complete(portal.CUSTOMERS.get("CUST-GATE"))

        portal.CUSTOMERS["CUST-GATE"] = {
            "id": "CUST-GATE", "name": "Ada", "email": "gate@example.com",
        }
        blocked = _FakeMislaka(configured=True)
        monkeypatch.setattr(
            "services.mislaka_api_service.get_mislaka_service", lambda: blocked,
        )
        status, body = dispatch_post(
            "/api/assessment-center/mislaka/personal", session, payload, "127.0.0.1",
        )
        assert status == 409 and body["code"] == "identity_required"
        assert blocked.calls == []
        assert not cis.is_complete(portal.CUSTOMERS["CUST-GATE"])

        cis.set_identity(
            portal.CUSTOMERS, "CUST-GATE", "123456782", "IL",
            source="registration", actor="t",
        )
        failed = _FakeMislaka(configured=True, status=MislakaStatus.ERROR)
        monkeypatch.setattr(
            "services.mislaka_api_service.get_mislaka_service", lambda: failed,
        )
        status, body = dispatch_post(
            "/api/assessment-center/mislaka/personal", session, payload, "127.0.0.1",
        )
        assert status == 502 and body["error"] == "Mislaka query failed"
        assert failed.calls == ["123456782"]
        assert portal.CUSTOMERS["CUST-GATE"]["identity_source"] == "registration"
        assert center.document_service.list_documents(page_size=20)["total"] == 0

        ready = _FakeMislaka(configured=True)
        monkeypatch.setattr(
            "services.mislaka_api_service.get_mislaka_service", lambda: ready,
        )
        status, body = dispatch_post(
            "/api/assessment-center/mislaka/personal",
            session,
            {"product_type": "all"},
            "127.0.0.1",
        )
        assert status == 200, body
        assert ready.calls == ["123456782"]
        assert "123456782" not in __import__("json").dumps(body)
        assert portal.CUSTOMERS["CUST-GATE"]["identity_source"] == "registration"
    finally:
        portal.CUSTOMERS.pop("CUST-GATE", None)
        cis.reset_process_state()
