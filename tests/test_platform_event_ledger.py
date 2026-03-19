import json

from services.audit_service import AuditService
from services.pipeline_integrity_service import PipelineIntegrityService
from services.platform_event_ledger_service import PlatformEventLedgerService


def test_platform_event_ledger_builds_hash_chain():
    ledger = {}
    service = PlatformEventLedgerService(ledger, use_database=False)

    first = service.append_event(
        event_type="premium_payment",
        entity_type="policy",
        entity_id="POL-100",
        customer_id="CUST-100",
        actor="billing-engine",
        amount=100.0,
        payload={
            "policy_id": "POL-100",
            "customer_id": "CUST-100",
            "description": "Monthly premium collected",
        },
        entry_id="TX-100",
        ledger_type="transaction",
        timestamp="2026-03-01T00:00:00",
    )
    second = service.append_event(
        event_type="claim_submission",
        entity_type="claim",
        entity_id="CLM-100",
        customer_id="CUST-100",
        actor="claims",
        amount=25.0,
        payload={
            "claim_id": "CLM-100",
            "policy_id": "POL-100",
            "customer_id": "CUST-100",
        },
        entry_id="TX-101",
        ledger_type="transaction",
        timestamp="2026-03-02T00:00:00",
    )

    summary = service.get_integrity_summary()

    assert first["sequence_no"] == 1
    assert second["sequence_no"] == 2
    assert second["previous_hash"] == first["entry_hash"]
    assert summary["chain_valid"] is True
    assert summary["total_entries"] == 2


def test_platform_event_ledger_repairs_legacy_entries():
    ledger = {
        "TX-200": {
            "id": "TX-200",
            "type": "policy_approval",
            "policy_id": "POL-200",
            "customer_id": "CUST-200",
            "timestamp": "2026-02-01T00:00:00",
            "amount": 0,
        },
        "TX-201": {
            "id": "TX-201",
            "type": "bill_payment",
            "policy_id": "POL-200",
            "customer_id": "CUST-200",
            "timestamp": "2026-02-02T00:00:00",
            "amount": 150.0,
        },
    }

    service = PlatformEventLedgerService(ledger, use_database=False)
    summary = service.ensure_hash_chain()

    assert summary["repaired_entries"] == 2
    assert ledger["TX-200"]["sequence_no"] == 1
    assert ledger["TX-201"]["sequence_no"] == 2
    assert ledger["TX-201"]["previous_hash"] == ledger["TX-200"]["entry_hash"]
    assert service.get_integrity_summary()["chain_valid"] is True


def test_audit_service_persists_to_database_and_platform_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_SQLITE", "1")
    monkeypatch.setenv("SQLITE_PATH", str(tmp_path / "platform_ledger_audit.db"))
    monkeypatch.setenv("USE_DATABASE", "true")

    from database import init_database, reset_connection
    from database.manager import DatabaseManager

    reset_connection()
    init_database(drop_existing=True)

    audit = AuditService()
    audit.log(
        "admin",
        "approve",
        "policy",
        "POL-AUD-001",
        {"customer_id": "CUST-AUD-001", "coverage_amount": 100000},
    )

    with DatabaseManager() as db:
        logs = db.audit.get_by_action("approve", limit=20)
        assert any(log.entity_id == "POL-AUD-001" for log in logs)

        ledger_entries = db.platform_ledger.get_by_entity("policy", "POL-AUD-001", limit=20)
        assert any(entry.event_type == "audit.approve" for entry in ledger_entries)
        assert all(entry.entry_hash for entry in ledger_entries)
        assert all(entry.sequence_no >= 1 for entry in ledger_entries)


def test_pipeline_dashboard_reports_ledger_integrity():
    ledger = {}
    ledger_service = PlatformEventLedgerService(ledger, use_database=False)
    ledger_service.append_event(
        event_type="bill_payment",
        entity_type="policy",
        entity_id="POL-300",
        customer_id="CUST-300",
        actor="billing-engine",
        amount=100.0,
        payload={
            "policy_id": "POL-300",
            "customer_id": "CUST-300",
            "metadata": {"policy_id": "POL-300", "customer_id": "CUST-300"},
        },
        entry_id="TX-300",
        ledger_type="transaction",
        timestamp="2026-03-10T00:00:00",
    )

    service = PipelineIntegrityService(
        policies={
            "POL-300": {
                "id": "POL-300",
                "customer_id": "CUST-300",
                "coverage_amount": 100000,
                "annual_premium": 1200,
                "monthly_premium": 100,
                "status": "active",
                "health_wallet": json.dumps({"allocation_percentage": 10}),
            }
        },
        billing={
            "BILL-300": {
                "policy_id": "POL-300",
                "customer_id": "CUST-300",
                "amount": 100,
                "status": "paid",
                "premium_breakdown": json.dumps({"savings_percentage": 10}),
            }
        },
        transaction_ledger=ledger,
    )

    report = service.validate_policy_pipeline("POL-300")
    dashboard = service.get_bi_dashboard_data()

    assert report.ledger_integrity_valid is True
    assert report.ledger_integrity_summary["chain_valid"] is True
    assert dashboard["ledger_integrity"]["chain_valid"] is True
