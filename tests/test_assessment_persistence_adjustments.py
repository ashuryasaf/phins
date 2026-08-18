"""
Tests for the generated-assessment persistence adjustments:

- Claims bot probability reports are appended to the durable assessment
  history when generated (previously process-memory only, erased on restart).
- POST /api/assessment-center/freeze snapshots the live Customer 360 into
  the append-only history (customer_risk), and lifecycle freezes
  (onboarding/service/termination) produce schema-validated advisory
  artifacts — enabling "what changed since the previous assessment?".
"""

import base64
import os

import pytest
import requests

from services.assessment_record_service import (
    get_assessment_record_service,
    reset_assessment_record_service,
)

BASE_URL = os.environ.get("TEST_BASE_URL", "http://localhost:8000")


@pytest.fixture(autouse=True)
def _reset_records():
    reset_assessment_record_service()
    yield
    reset_assessment_record_service()


# ── Claims bot report persistence ─────────────────────────────────────────────

def _make_bot():
    from services.claims_bot_service import ClaimsBotService
    customers = {"CUST-CB": {"id": "CUST-CB", "name": "Test Customer"}}
    policies = {"POL-CB": {"id": "POL-CB", "customer_id": "CUST-CB",
                           "start_date": "2023-01-01", "coverage_amount": 100000,
                           "type": "health"}}
    claims = {"CLM-CB": {"id": "CLM-CB", "customer_id": "CUST-CB",
                         "policy_id": "POL-CB", "type": "medical",
                         "description": "Hospitalization for surgery",
                         "claimed_amount": 5000,
                         "filed_date": "2025-06-01", "files_count": 2,
                         "files": [{"name": "invoice.pdf"}, {"name": "report.pdf"}]}}
    return ClaimsBotService(customers=customers, policies=policies, claims=claims)


def test_probability_report_persisted_to_assessment_history():
    bot = _make_bot()
    report = bot.generate_probability_report("CLM-CB")
    assert report is not None

    records = get_assessment_record_service().list_records(
        assessment_type="claims_probability_report")
    assert records["total"] == 1
    row = records["items"][0]
    assert row["subject_type"] == "claim"
    assert row["subject_id"] == "CLM-CB"
    assert row["customer_id"] == "CUST-CB"
    assert row["engine"] == "claims_bot"
    # The full report is embedded so a restart never erases the audit trail.
    assert row["details"]["id"] == report.id
    assert 0.0 <= row["score"] <= 1.0


def test_repeated_reports_append_never_overwrite():
    bot = _make_bot()
    first = bot.generate_probability_report("CLM-CB")
    second = bot.generate_probability_report("CLM-CB")
    assert first.id != second.id
    records = get_assessment_record_service().list_records(
        assessment_type="claims_probability_report")
    assert records["total"] == 2


def test_report_generation_survives_persistence_failure(monkeypatch):
    """Persistence is best-effort: a store outage must not break assessment."""
    bot = _make_bot()
    monkeypatch.setattr(
        "services.assessment_record_service.AssessmentRecordService.record_assessment",
        lambda self, **kw: (_ for _ in ()).throw(RuntimeError("store down")))
    report = bot.generate_probability_report("CLM-CB")
    assert report is not None
    assert report.id in bot.reports


# ── Freeze endpoint ───────────────────────────────────────────────────────────

def _admin_headers():
    resp = requests.post(f"{BASE_URL}/api/login", json={
        "username": "admin", "password": "admin123"})
    if resp.status_code != 200:
        pytest.skip("Admin login failed — test server may not have users seeded")
    return {"Authorization": f"Bearer {resp.json().get('token')}"}


def _seed_customer_facts(headers, customer_id):
    content = "Patient has diabetes. BMI 31.0. Premium 400"
    resp = requests.post(f"{BASE_URL}/api/assessment-center/upload", headers=headers,
                         json={
                             "file_name": "medical.txt",
                             "file_data_b64": base64.b64encode(content.encode()).decode(),
                             "mime_type": "text/plain",
                             "customer_id": customer_id,
                         })
    assert resp.status_code == 201, resp.text


def test_freeze_requires_auth():
    resp = requests.post(f"{BASE_URL}/api/assessment-center/freeze",
                         json={"customer_id": "CUST-X"})
    assert resp.status_code == 401


def test_freeze_rejects_unknown_type():
    headers = _admin_headers()
    resp = requests.post(f"{BASE_URL}/api/assessment-center/freeze", headers=headers,
                         json={"customer_id": "CUST-FRZ", "assessment_type": "weird"})
    assert resp.status_code == 400
    assert "assessment_type" in resp.json()["error"]


def test_freeze_customer_risk_snapshot():
    headers = _admin_headers()
    _seed_customer_facts(headers, "CUST-FRZ1")

    resp = requests.post(f"{BASE_URL}/api/assessment-center/freeze", headers=headers,
                         json={"customer_id": "CUST-FRZ1",
                               "note": "quarterly review"})
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    assert payload["frozen"] is True
    record = payload["record"]
    assert record["assessment_type"] == "customer_risk"
    assert record["details"]["trigger"] == "manual_freeze"
    assert record["details"]["note"] == "quarterly review"
    assert record["details"]["fact_count"] > 0

    # Frozen snapshots are queryable history (append-only).
    listing = requests.get(
        f"{BASE_URL}/api/assessment-center/records"
        "?assessment_type=customer_risk&customer_id=CUST-FRZ1",
        headers=headers)
    assert listing.status_code == 200
    items = listing.json().get("items", [])
    assert any(r["details"].get("trigger") == "manual_freeze" for r in items)


def test_freeze_lifecycle_produces_structured_artifact():
    headers = _admin_headers()
    _seed_customer_facts(headers, "CUST-FRZ2")

    resp = requests.post(f"{BASE_URL}/api/assessment-center/freeze", headers=headers,
                         json={"customer_id": "CUST-FRZ2",
                               "assessment_type": "onboarding"})
    assert resp.status_code == 201, resp.text
    artifact = resp.json()["artifact"]
    assert artifact["prompt_version"] == "onboarding-v1"
    assert artifact["advisory"] is True
    assert artifact["schema_valid"] is True
    result = artifact["result"]
    assert result["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert result["requires_human_review"] is True


def test_freeze_snapshots_accumulate_for_comparison():
    headers = _admin_headers()
    _seed_customer_facts(headers, "CUST-FRZ3")
    for _ in range(2):
        resp = requests.post(f"{BASE_URL}/api/assessment-center/freeze",
                             headers=headers,
                             json={"customer_id": "CUST-FRZ3"})
        assert resp.status_code == 201
    listing = requests.get(
        f"{BASE_URL}/api/assessment-center/records"
        "?assessment_type=customer_risk&customer_id=CUST-FRZ3",
        headers=headers)
    freezes = [r for r in listing.json().get("items", [])
               if r["details"].get("trigger") == "manual_freeze"]
    assert len(freezes) == 2
