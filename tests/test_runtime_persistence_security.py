import json

import web_portal.server as portal


def test_append_customer_to_seeds_writes_runtime_state_only(tmp_path, monkeypatch):
    runtime_file = tmp_path / "dynamic_customers_runtime.json"
    legacy_file = tmp_path / "dynamic_customers.json"
    legacy_file.write_text("[]", encoding="utf-8")

    monkeypatch.setattr(portal, "RUNTIME_DYNAMIC_CUSTOMERS_FILE", str(runtime_file))
    monkeypatch.setattr(portal, "LEGACY_DYNAMIC_CUSTOMERS_FILE", str(legacy_file))

    portal.append_customer_to_seeds(
        "runtime@example.com",
        "a" * 64,
        "b" * 32,
        "Runtime User",
        "CUST-RUNTIME-001",
        "2026-03-17T00:00:00",
    )

    runtime_payload = json.loads(runtime_file.read_text(encoding="utf-8"))
    assert runtime_payload == [
        {
            "username": "runtime@example.com",
            "password_hash": "a" * 64,
            "password_salt": "b" * 32,
            "name": "Runtime User",
            "role": "customer",
            "customer_id": "CUST-RUNTIME-001",
            "email": "runtime@example.com",
            "registered_at": "2026-03-17T00:00:00",
            "test_only": True,
        }
    ]
    assert json.loads(legacy_file.read_text(encoding="utf-8")) == []


def test_load_dynamic_customers_prefers_runtime_state_over_legacy_seed(tmp_path, monkeypatch):
    legacy_file = tmp_path / "dynamic_customers_legacy.json"
    runtime_file = tmp_path / "dynamic_customers_runtime.json"

    legacy_file.write_text(
        json.dumps(
            [
                {
                    "username": "runtime@example.com",
                    "email": "runtime@example.com",
                    "name": "Legacy User",
                    "customer_id": "CUST-RUNTIME-001",
                    "password_hash": "1" * 64,
                    "password_salt": "2" * 32,
                    "registered_at": "2026-03-01T00:00:00",
                }
            ]
        ),
        encoding="utf-8",
    )
    runtime_file.write_text(
        json.dumps(
            [
                {
                    "username": "runtime@example.com",
                    "email": "runtime@example.com",
                    "name": "Runtime User",
                    "customer_id": "CUST-RUNTIME-001",
                    "password_hash": "a" * 64,
                    "password_salt": "b" * 32,
                    "registered_at": "2026-03-17T00:00:00",
                }
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(portal, "LEGACY_DYNAMIC_CUSTOMERS_FILE", str(legacy_file))
    monkeypatch.setattr(portal, "RUNTIME_DYNAMIC_CUSTOMERS_FILE", str(runtime_file))
    monkeypatch.setattr(portal, "USERS", {})
    monkeypatch.setattr(portal, "CUSTOMERS", {})
    monkeypatch.setattr(portal, "REGISTERED_CUSTOMERS", {})

    portal.load_dynamic_customers()

    assert portal.USERS["runtime@example.com"]["hash"] == "a" * 64
    assert portal.USERS["runtime@example.com"]["salt"] == "b" * 32
    assert portal.CUSTOMERS["CUST-RUNTIME-001"]["name"] == "Runtime User"


def test_save_invitation_codes_to_file_sanitizes_runtime_persistence(tmp_path, monkeypatch):
    runtime_file = tmp_path / "invitation_codes_runtime.json"
    legacy_file = tmp_path / "invitation_codes.json"
    legacy_file.write_text(
        json.dumps(
            {
                "version": "1.0",
                "saved_at": None,
                "admin_codes": {},
                "customer_codes": {},
                "referral_stats": {},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(portal, "RUNTIME_INVITATION_CODES_FILE", str(runtime_file))
    monkeypatch.setattr(portal, "LEGACY_INVITATION_CODES_FILE", str(legacy_file))
    monkeypatch.setattr(
        portal,
        "INVITATION_CODES",
        {
            "TESTCODE2026": {
                "code": "TESTCODE2026",
                "created_by": "system",
                "notes": "Test mode invitation code - automatically created",
                "used_by": [
                    {
                        "email": "test@example.com",
                        "customer_id": "CUST-TEST-001",
                        "used_at": "2026-03-17T00:00:00",
                    }
                ],
            },
            "REALCODE2026": {
                "code": "REALCODE2026",
                "created_by": "admin",
                "status": "used",
                "used_by": [
                    {
                        "email": "real@example.com",
                        "customer_id": "CUST-REAL-001",
                        "used_at": "2026-03-17T01:00:00",
                    }
                ],
            },
        },
    )
    monkeypatch.setattr(portal, "CUSTOMER_INVITATIONS", {})
    monkeypatch.setattr(
        portal,
        "CUSTOMER_REFERRAL_STATS",
        {
            "CUST-REF-001": {
                "codes_generated": 1,
                "successful_referrals": 1,
                "codes": [{"code": "REALCODE2026", "used_by": "CUST-REAL-001"}],
                "referred_customers": [
                    {
                        "customer_id": "CUST-REAL-001",
                        "name": "Real Referral",
                        "email": "real@example.com",
                        "referred_at": "2026-03-17T01:00:00",
                        "code_used": "REALCODE2026",
                    }
                ],
                "rewards": [],
                "total_reward_value": 0,
            }
        },
    )

    portal.save_invitation_codes_to_file()

    payload = json.loads(runtime_file.read_text(encoding="utf-8"))
    assert "TESTCODE2026" not in payload["admin_codes"]
    assert payload["admin_codes"]["REALCODE2026"]["used_by"] == [
        {
            "customer_id": "CUST-REAL-001",
            "used_at": "2026-03-17T01:00:00",
        }
    ]
    referred_customer = payload["referral_stats"]["CUST-REF-001"]["referred_customers"][0]
    assert "email" not in referred_customer
    assert json.loads(legacy_file.read_text(encoding="utf-8"))["admin_codes"] == {}
