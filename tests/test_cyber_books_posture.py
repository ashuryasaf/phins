"""Read-only ERP/MGA books posture for the cyber desk."""

from __future__ import annotations

import pytest

from services.cyber_books_posture import (
    BOOK_CONTROLS,
    collect_books_posture,
    points_for,
    score_books,
    unreadable_posture,
)
from services.cyber_crisis import score_pipeline


def _all_up_raw():
    return {
        name: {"state": "up", "note": f"{name} ok"}
        for name in BOOK_CONTROLS
    }


def test_score_books_all_green_adds_no_points():
    scored = score_books(_all_up_raw())
    assert scored["points"] == 0
    assert not scored.get("findings")
    assert any("Money Gate" in line for line in scored["protections"])


def test_score_books_money_gate_down_adds_fifteen_points():
    raw = _all_up_raw()
    raw["money_gate"] = {"state": "down", "note": "Money Gate critical checks are red."}
    scored = score_books(raw)
    assert scored["points"] == 15
    assert any("withdrawal" in r.lower() for r in scored["recommendations"])
    assert scored["stages"]["money_gate"] == "down"


def test_unreadable_posture_is_fail_closed():
    posture = unreadable_posture()
    assert posture["readable"] is False
    assert posture["points"] == 35
    assert all(posture["stages"][name] == "down" for name in BOOK_CONTROLS)


def test_collect_books_posture_uses_injected_readers():
    posture = collect_books_posture(
        policies={},
        ledger=object(),
        money_reader=lambda: {"state": "down", "note": "money red"},
        books_tied_reader=lambda _l: {"state": "up", "note": "fresh"},
        period_reader=lambda: {"state": "up", "note": "open"},
        trust_reader=lambda: {"state": "up", "note": "trust ok"},
        kernel_reader=lambda _p: {"state": "up", "note": "pins ok"},
        ledger_reader=lambda _l: {"state": "up", "note": "chain ok"},
    )
    assert posture["readable"] is True
    assert posture["stages"]["money_gate"] == "down"
    assert posture["points"] == 15


def test_kernel_pins_broken_seal_is_down():
    from services.cyber_books_posture import _kernel_note

    policies = {
        "POL-1": {
            "status": "in_force",
            "kernel_pin_intact": False,
            "kernel_pin": {"risk_premium_annual": 100},
        }
    }
    cell = _kernel_note(policies)
    assert cell["state"] == "down"
    assert "seal" in cell["note"].lower()


def test_kernel_pins_missing_on_in_force_is_watch():
    from services.cyber_books_posture import _kernel_note

    policies = {"POL-1": {"status": "active"}}
    cell = _kernel_note(policies)
    assert cell["state"] == "watch"


def test_kernel_pins_flattened_fields_on_row_is_up():
    from services.cyber_books_posture import _kernel_note

    policies = {
        "POL-1": {
            "status": "issued",
            "risk_premium_annual": 2400.0,
            "integrity_hash": "deadbeef",
        }
    }
    cell = _kernel_note(policies)
    assert cell["state"] == "up"


def test_trust_ok_without_bank_import_is_watch(monkeypatch):
    from services import cyber_books_posture as mod

    monkeypatch.setattr(
        "services.mga.trust.reconcile_trust",
        lambda: {
            "ok": True,
            "findings": [
                {
                    "code": "bank_balance_unavailable",
                    "severity": "info",
                    "detail": "no bank import",
                }
            ],
        },
    )
    cell = mod._default_trust()
    assert cell["state"] == "watch"
    assert "bank" in cell["note"].lower()


def test_score_pipeline_folds_books_without_closing_sessions():
    telemetry = {
        "firewall_enabled": True,
        "ids_enabled": True,
        "file_scanner_enabled": True,
        "request_sanitizer_enabled": True,
        "generation_intact": True,
        "journal_intact": True,
        "malicious_attempts": 0,
        "permanent_blocks": 0,
        "blocked_ips": 0,
        "active_alerts": 0,
        "lockouts": 0,
        "quarantined": 0,
        "active_sessions": 1,
        "books": unreadable_posture(),
    }
    result = score_pipeline(telemetry)
    assert "money_gate" in result["pipeline"]
    assert result["pipeline"]["money_gate"] == "down"
    assert result["risk_score"] >= 20
    assert all("Drop all" not in r or "does not close" in r for r in result["recommendations"])


def test_score_pipeline_generation_unreadable_fails_closed():
    telemetry = {
        "firewall_enabled": True,
        "ids_enabled": True,
        "file_scanner_enabled": True,
        "request_sanitizer_enabled": True,
        "generation_intact": None,
        "journal_intact": True,
        "malicious_attempts": 0,
        "permanent_blocks": 0,
        "blocked_ips": 0,
        "active_alerts": 0,
        "lockouts": 0,
        "quarantined": 0,
        "active_sessions": 1,
    }
    result = score_pipeline(telemetry)
    assert result["pipeline"]["session_generation"] == "down"
    assert any("generation" in f.lower() for f in result["findings"])


def test_points_for_caps_at_books_score_cap():
    stages = {name: "down" for name in BOOK_CONTROLS}
    assert points_for(stages) == 35