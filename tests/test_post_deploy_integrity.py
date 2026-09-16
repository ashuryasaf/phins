"""Regressions from the Railway deploy logs after PR #603.

The identity keyring landed cleanly (no vault errors in those logs). The
deploy stream did show claim-persist, ledger-snapshot, apply-chat POST,
reinsurance collection, claims-bot re-init, and customer-id log leakage
issues. These tests pin the integrity and leakage fixes.
"""

from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path

import requests

import web_portal.server as portal


BASE_URL = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")
ADMIN_HTML = Path(__file__).resolve().parents[1] / "web_portal" / "static" / "admin.html"


def _admin_token() -> str:
    if "admin" not in portal.USERS:
        pw = portal.hash_password("admin123")
        portal.USERS["admin"] = {**pw, "role": "admin", "name": "Admin User"}
    resp = requests.post(
        f"{BASE_URL}/api/login",
        json={"username": "admin", "password": "admin123"},
        timeout=15,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def test_database_manager_exposes_session_property():
    from database.manager import DatabaseManager

    assert isinstance(DatabaseManager.session, property)


def test_persist_claim_update_uses_claims_repository(monkeypatch):
    captured = {}

    class FakeClaims:
        def update(self, claim_id, **kwargs):
            captured["id"] = claim_id
            captured["kwargs"] = kwargs
            return object()

    class FakeDB:
        def __init__(self, *args, **kwargs):
            self.claims = FakeClaims()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @property
        def session(self):
            raise AssertionError("persist path must not use db.session")

    import database.manager as db_manager

    monkeypatch.setattr(db_manager, "DatabaseManager", FakeDB)
    monkeypatch.setattr(portal, "USE_DATABASE", True)
    monkeypatch.setattr(portal, "database_enabled", True)

    buf = io.StringIO()
    with redirect_stdout(buf):
        portal.persist_claim_update_to_database(
            "CLM-20260915-3789",
            {"status": "approved", "approved_amount": 1200.0},
        )

    assert captured["id"] == "CLM-20260915-3789"
    assert captured["kwargs"]["status"] == "approved"
    assert "no attribute 'session'" not in buf.getvalue()


def test_freeze_for_json_isolates_live_mutations():
    live = {"a": 1, "nested": {"x": 1}, "items": [{"id": 1}]}
    frozen = portal._freeze_for_json(live)
    live["b"] = 2
    live["nested"]["y"] = 3
    live["items"].append({"id": 2})
    assert frozen == {"a": 1, "nested": {"x": 1}, "items": [{"id": 1}]}


def test_freeze_for_json_retries_changed_size_iteration():
    class RacingDict(dict):
        def items(self):
            if not getattr(self, "_raised", False):
                self._raised = True
                raise RuntimeError("dictionary changed size during iteration")
            return super().items()

    frozen = portal._freeze_for_json(RacingDict(nft="ok", amount=10))
    assert frozen["nft"] == "ok"
    assert frozen["amount"] == 10


def test_freeze_for_json_fail_closed_on_persistent_race():
    class AlwaysRacing(dict):
        def items(self):
            raise RuntimeError("dictionary changed size during iteration")

    try:
        portal._freeze_for_json(AlwaysRacing(nft="must-not-drop"))
        raise AssertionError("expected freeze to fail closed")
    except RuntimeError as exc:
        assert "refusing empty freeze" in str(exc)


def test_save_ledger_data_keeps_prior_file_when_freeze_fails(monkeypatch, tmp_path):
    persistence_file = tmp_path / "ledger.json"
    persistence_file.write_text('{"saved_at": "prior"}', encoding="utf-8")
    monkeypatch.setattr(portal, "LEDGER_PERSISTENCE_FILE", str(persistence_file))
    monkeypatch.setattr(portal, "PERSISTENCE_ENABLED", True)
    monkeypatch.setattr(portal, "_persistence_dirty", True)

    class AlwaysRacing(dict):
        def items(self):
            raise RuntimeError("dictionary changed size during iteration")

    monkeypatch.setattr(portal, "NFT_LEDGER", AlwaysRacing({"T1": {"id": "T1"}}))

    assert portal.save_ledger_data() is False
    assert persistence_file.read_text(encoding="utf-8") == '{"saved_at": "prior"}'


def test_save_ledger_data_survives_dict_mutation(monkeypatch, tmp_path):
    persistence_file = tmp_path / "ledger.json"
    monkeypatch.setattr(portal, "LEDGER_PERSISTENCE_FILE", str(persistence_file))
    monkeypatch.setattr(portal, "PERSISTENCE_ENABLED", True)
    monkeypatch.setattr(portal, "_persistence_dirty", True)

    class RacingLedger(dict):
        def items(self):
            if not getattr(self, "_raised", False):
                self._raised = True
                raise RuntimeError("dictionary changed size during iteration")
            return super().items()

    monkeypatch.setattr(portal, "NFT_LEDGER", RacingLedger({"T1": {"id": "T1"}}))
    monkeypatch.setattr(portal, "TRANSACTION_LEDGER", {"TX1": {"id": "TX1"}})

    assert portal.save_ledger_data() is True
    payload = json.loads(persistence_file.read_text(encoding="utf-8"))
    assert payload["nft_ledger"]["T1"]["id"] == "T1"


def test_access_log_redacts_customer_id_and_email():
    line = (
        "GET /api/risk-assessment/report?customer_id=CUST-SHOSH-001"
        "&email=shosh@phins.ai HTTP/1.1"
    )
    redacted = portal._redact_access_log_line(line)
    assert "CUST-SHOSH-001" not in redacted
    assert "shosh@phins.ai" not in redacted
    assert "customer_id=REDACTED" in redacted
    assert "email=REDACTED" in redacted


def test_init_claims_bot_reuses_singleton(monkeypatch):
    import services.claims_bot_service as claims_bot

    monkeypatch.setattr(claims_bot, "_bot_instance", None)
    first = claims_bot.init_claims_bot_service({}, {}, {"CLM-1": {}}, {})
    second = claims_bot.init_claims_bot_service({"CUST-1": {}}, {}, {"CLM-1": {}}, {})
    assert first is second
    assert first._customers == {"CUST-1": {}}
    assert first.bot_id == second.bot_id


def test_post_apply_chat_html_redirects_to_get():
    resp = requests.post(
        f"{BASE_URL}/apply-chat.html",
        data={"email": "applicant@example.com", "code": "PHINS-CHAT-TEST"},
        allow_redirects=False,
        timeout=15,
    )
    assert resp.status_code == 303
    assert resp.headers.get("Location") == "/apply-chat.html"


def test_get_reinsurance_collection_returns_partners():
    token = _admin_token()
    resp = requests.get(
        f"{BASE_URL}/api/reinsurance",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "partners" in body
    assert "providers" in body
    assert "items" in body
    assert isinstance(body["partners"], list)


def test_admin_dashboard_coalesces_customer_fetches():
    content = ADMIN_HTML.read_text(encoding="utf-8")
    assert "function fetchAdminCustomers()" in content
    assert content.count("await fetchAdminCustomers()") >= 8
    assert content.count("fetch('/api/admin/customers'") == 1
