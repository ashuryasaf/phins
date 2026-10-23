"""Crisis drop-all and the read-only cyber autopilot."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import pytest

from services.cyber_crisis import (
    CrisisCenter,
    checksum_ok,
    fingerprint_records,
    seal,
    score_pipeline,
)
from services.otp_security_service import OTPPurpose, OTPSecurityService

ROOT = Path(__file__).resolve().parents[1]


def _telemetry(**overrides):
    base = {
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
        "customers": 2,
        "policies": 2,
        "claims": 0,
        "billing": 1,
    }
    base.update(overrides)
    return base


def _otp(center: CrisisCenter, purpose=OTPPurpose.CRISIS_LOCKDOWN):
    service = OTPSecurityService()
    created = service.create_otp_verification(
        user_type="staff",
        user_id="admin",
        email="admin@phins.local",
        purpose=purpose,
        ip_address="127.0.0.1",
        delivery_channel="email",
    )
    assert created.success
    center.bind_challenge(created.verification_id, "admin", "admin@phins.local")
    return service, created.verification_id, created.data["otp_code"]


def test_fingerprint_changes_when_a_record_is_added_and_ignores_nothing_else():
    records = {"C1": {"status": "active", "name": "A"}}
    first = fingerprint_records({"customers": records})
    second = fingerprint_records({"customers": records})
    assert first == second
    records["C2"] = {"status": "active", "name": "B"}
    assert fingerprint_records({"customers": records}) != first


def test_generation_advances_persists_and_never_moves_backward(tmp_path):
    center = CrisisCenter(tmp_path)
    assert center.generation() == 0
    assert center.blocks({"session_generation": 0}) is False
    assert center.advance_generation() == 1
    assert center.blocks({"session_generation": 0}) is True
    assert center.blocks({"session_generation": 1}) is False

    reloaded = CrisisCenter(tmp_path)
    assert reloaded.generation() == 1

    low = seal({"generation": 0, "updated_at": "2000-01-01T00:00:00+00:00"})
    (tmp_path / "session_generation.json").write_text(json.dumps(low), encoding="utf-8")
    reloaded._refresh_at = 0
    assert reloaded.generation() == 1


def test_corrupt_generation_file_fails_closed_once(tmp_path):
    path = tmp_path / "session_generation.json"
    path.write_text('{"generation": 9, "checksum": "not-a-real-checksum"}', encoding="utf-8")
    center = CrisisCenter(tmp_path)
    assert center.generation() == 1
    assert checksum_ok(json.loads(path.read_text(encoding="utf-8")))
    assert center.generation() == 1
    assert center.blocks({"session_generation": 0}) is True


def test_drop_closes_every_session_and_leaves_business_records_unchanged(tmp_path):
    center = CrisisCenter(tmp_path)
    customers = {"C1": {"status": "active", "name": "A"}}
    policies = {"P1": {"status": "in_force"}}
    snapshot = (deepcopy(customers), deepcopy(policies))
    sessions = {
        "caller": {
            "username": "admin",
            "role": "admin",
            "jti": "caller-jti",
            "expires": "2099-01-01T00:00:00",
            "session_generation": 0,
        },
        "other": {
            "username": "member",
            "role": "customer",
            "jti": "other-jti",
            "expires": "2099-01-01T00:00:00",
            "session_generation": 0,
        },
    }
    revoked = []
    result = center.drop_all_sessions(
        actor="admin",
        verification_id="OTP-1",
        sessions=sessions,
        revoke_jti=lambda jti, _exp: revoked.append(jti),
        integrity_sources={"customers": customers, "policies": policies},
    )
    assert result["dropped"] is True
    assert result["requester_included"] is True
    assert result["sessions_dropped"] == 2
    assert result["integrity_intact"] is True
    assert sessions == {}
    assert sorted(revoked) == ["caller-jti", "other-jti"]
    assert (customers, policies) == snapshot
    assert center.generation() == 1
    assert center.journal_intact() is True


def test_drop_reports_a_business_record_change_without_hiding_it(tmp_path):
    center = CrisisCenter(tmp_path)
    customers = {"C1": {"status": "active"}}

    def _mutate():
        customers["C2"] = {"status": "new"}
        return 0

    result = center.drop_all_sessions(
        actor="admin",
        verification_id="OTP-1",
        sessions={"caller": {"username": "admin", "session_generation": 0}},
        delete_db_sessions=_mutate,
        integrity_sources={"customers": customers},
    )
    assert result["dropped"] is True
    assert result["integrity_intact"] is False


def test_journal_failure_does_not_close_sessions_or_advance_generation(tmp_path):
    center = CrisisCenter(tmp_path)
    center._append_journal = lambda _entry: False  # type: ignore[method-assign]
    sessions = {"caller": {"username": "admin", "session_generation": 0}}
    result = center.drop_all_sessions(
        actor="admin",
        verification_id="OTP-1",
        sessions=sessions,
        integrity_sources={},
    )
    assert result["ok"] is False
    assert result["code"] == "crisis_journal_unavailable"
    assert "caller" in sessions
    assert center.generation() == 0


def test_otp_confirm_drops_only_after_the_crisis_code(tmp_path):
    center = CrisisCenter(tmp_path)
    service, verification_id, code = _otp(center)
    sessions = {"caller": {"username": "admin", "jti": "j", "expires": "2099-01-01T00:00:00"}}
    wrong = center.confirm_drop(
        service,
        username="admin",
        email="admin@phins.local",
        verification_id=verification_id,
        otp_code="000000" if code != "000000" else "111111",
        ip_address="127.0.0.1",
        sessions=sessions,
    )
    assert wrong["ok"] is False
    assert "caller" in sessions
    assert center.generation() == 0

    dropped = center.confirm_drop(
        service,
        username="admin",
        email="admin@phins.local",
        verification_id=verification_id,
        otp_code=code,
        ip_address="127.0.0.1",
        sessions=sessions,
    )
    assert dropped["dropped"] is True
    assert dropped["requester_included"] is True
    assert sessions == {}
    generation = center.generation()

    late = {"late": {"username": "other", "session_generation": generation}}
    replay = center.confirm_drop(
        service,
        username="admin",
        email="admin@phins.local",
        verification_id=verification_id,
        otp_code=code,
        ip_address="127.0.0.1",
        sessions=late,
    )
    assert replay["ok"] is False
    assert "late" in late
    assert center.generation() == generation


def test_login_otp_cannot_confirm_a_crisis_drop(tmp_path):
    center = CrisisCenter(tmp_path)
    service, verification_id, code = _otp(center, OTPPurpose.LOGIN)
    sessions = {"caller": {"username": "admin"}}
    result = center.confirm_drop(
        service,
        username="admin",
        email="admin@phins.local",
        verification_id=verification_id,
        otp_code=code,
        ip_address="127.0.0.1",
        sessions=sessions,
    )
    assert result["ok"] is False
    assert result["code"] == "PURPOSE_MISMATCH"
    assert "caller" in sessions
    assert center.generation() == 0


def test_unbound_code_is_refused(tmp_path):
    center = CrisisCenter(tmp_path)
    service = OTPSecurityService()
    created = service.create_otp_verification(
        user_type="staff",
        user_id="admin",
        email="admin@phins.local",
        purpose=OTPPurpose.CRISIS_LOCKDOWN,
        delivery_channel="email",
    )
    sessions = {"caller": {"username": "admin"}}
    result = center.confirm_drop(
        service,
        username="admin",
        email="admin@phins.local",
        verification_id=created.verification_id,
        otp_code=created.data["otp_code"],
        ip_address="127.0.0.1",
        sessions=sessions,
    )
    assert result["code"] == "crisis_challenge_mismatch"
    assert "caller" in sessions


def test_autopilot_reuses_an_unchanged_pipeline_and_does_not_mutate_it(tmp_path, monkeypatch):
    monkeypatch.setenv("PHINS_CYBER_AUTOPILOT_CADENCE_SECONDS", "60")
    center = CrisisCenter(tmp_path)
    telemetry = _telemetry()
    original = deepcopy(telemetry)
    first = center.assess(telemetry)
    assert first["coalesced"] is False
    assert first["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert first["closes_sessions"] is not True
    assert telemetry == original
    second = center.assess(telemetry)
    assert second["coalesced"] is True
    assert second["id"] == first["id"]
    assert telemetry == original

    monkeypatch.setenv("PHINS_CYBER_AUTOPILOT_CADENCE_SECONDS", "0")
    third = center.assess(_telemetry(active_alerts=3))
    assert third["coalesced"] is False
    assert third["id"] != first["id"]
    assert third["risk_score"] > first["risk_score"]


def test_autopilot_does_not_append_when_the_chain_checksum_fails(tmp_path):
    center = CrisisCenter(tmp_path)
    first = center.assess(_telemetry())
    path = tmp_path / "autopilot_chain.json"
    path.write_text(path.read_text(encoding="utf-8").replace(first["id"], "tampered"), encoding="utf-8")
    reloaded = CrisisCenter(tmp_path)
    assert reloaded.chain_intact() is False
    paused = reloaded.assess(_telemetry(active_alerts=9))
    assert paused.get("chain_intact") is False
    assert "tampered" in path.read_text(encoding="utf-8")
    resealed = reloaded.reseal_autopilot("admin")
    assert resealed["resealed"] is True
    assert resealed["archive"]
    assert (tmp_path / resealed["archive"]).is_file()
    resumed = reloaded.assess(_telemetry())
    assert resumed["coalesced"] is False
    assert reloaded.chain_intact() is True


def test_score_recommends_the_manual_drop_and_never_claims_it_ran():
    quiet = score_pipeline(_telemetry())
    assert quiet["risk_level"] == "LOW"
    loud = score_pipeline(_telemetry(
        firewall_enabled=False,
        active_alerts=8,
        lockouts=6,
        malicious_attempts=120,
        journal_intact=False,
    ))
    assert loud["risk_level"] in ("HIGH", "CRITICAL")
    assert any("Drop all" in item for item in loud["recommendations"])
    assert any("does not close sessions" in item for item in loud["recommendations"])


def test_page_exposes_the_drop_and_the_autopilot():
    html = (ROOT / "web_portal" / "static" / "cyber-security.html").read_text(encoding="utf-8")
    assert 'id="crisis-drop"' in html
    assert "/api/security/crisis/drop-all/confirm" in html
    assert 'id="autopilot"' in html
    assert "does not close sessions" in html
    assert "signs me out as well" in html


def _login(base: str, username: str, password: str) -> str:
    import urllib.request
    data = json.dumps({"username": username, "password": password}).encode()
    req = urllib.request.Request(
        f"{base}/api/login",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read())
    token = body.get("token")
    assert token
    return token


def _call(base: str, path: str, token: str | None = None, payload: dict | None = None, method: str = "GET"):
    import urllib.error
    import urllib.request
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{base}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            body = json.loads(raw)
        except Exception:
            body = {"error": raw.decode("utf-8", "replace")}
        return exc.code, body


class TestCrisisDropHttp:
    BASE = os.environ.get("TEST_BASE_URL", "http://127.0.0.1:8000")

    def test_drop_all_requires_admin_otp_and_includes_the_requester(self):
        admin = _login(self.BASE, "admin", "admin123")
        other = _login(self.BASE, "underwriter", "under123")
        status, before = _call(self.BASE, "/api/security/dashboard", admin)
        assert status == 200
        customers_before = before["system"]["total_customers"]
        policies_before = before["system"]["total_policies"]

        status, denied = _call(
            self.BASE, "/api/security/crisis/drop-all/request", other, {}, "POST",
        )
        assert status == 403

        status, anonymous = _call(
            self.BASE, "/api/security/crisis/drop-all/request", None, {}, "POST",
        )
        assert anonymous["error"]
        assert status in (401, 403)

        status, generic = _call(
            self.BASE,
            "/api/security/otp/request",
            None,
            {"email": "admin@phins.local", "purpose": "crisis_lockdown"},
            "POST",
        )
        assert status == 400
        assert generic.get("error_code") == "UNSUPPORTED_PURPOSE"

        status, issued = _call(
            self.BASE, "/api/security/crisis/drop-all/request", admin, {}, "POST",
        )
        assert status == 200, issued
        assert issued.get("verification_id")
        assert issued.get("demo_otp_code")
        assert "otp_code" not in (issued.get("data") or {})

        wrong_code = "111111" if issued["demo_otp_code"] == "000000" else "000000"
        status, rejected = _call(
            self.BASE,
            "/api/security/crisis/drop-all/confirm",
            admin,
            {"verification_id": issued["verification_id"], "otp_code": wrong_code},
            "POST",
        )
        assert status == 400, rejected
        status, still_admin = _call(self.BASE, "/api/security/dashboard", admin)
        status_other, still_other = _call(self.BASE, "/api/session/validate", other)
        assert status == 200, still_admin
        assert status_other == 200, still_other
        assert still_other.get("valid", True) is not False

        status, dropped = _call(
            self.BASE,
            "/api/security/crisis/drop-all/confirm",
            admin,
            {
                "verification_id": issued["verification_id"],
                "otp_code": issued["demo_otp_code"],
            },
            "POST",
        )
        assert status == 200, dropped
        assert dropped["dropped"] is True
        assert dropped["requester_included"] is True
        assert dropped["sessions_dropped"] >= 2
        assert dropped["integrity_intact"] is True
        assert dropped["relogin_required"] is True

        status, _admin_after = _call(self.BASE, "/api/security/dashboard", admin)
        status_other, other_after = _call(self.BASE, "/api/session/validate", other)
        assert status in (401, 403)
        assert status_other == 401
        assert other_after.get("valid") is False

        status, replay = _call(
            self.BASE,
            "/api/security/crisis/drop-all/confirm",
            admin,
            {
                "verification_id": issued["verification_id"],
                "otp_code": issued["demo_otp_code"],
            },
            "POST",
        )
        assert status in (401, 403)
        assert replay.get("dropped") is not True

        fresh = _login(self.BASE, "admin", "admin123")
        status, after = _call(self.BASE, "/api/security/dashboard", fresh)
        assert status == 200
        assert after["system"]["total_customers"] == customers_before
        assert after["system"]["total_policies"] == policies_before
        assert after["crisis"]["generation"] >= 1
        assert after["crisis"]["journal_intact"] is True
        assert after["autopilot"]["mode"] == "assess"
        assert after["autopilot"]["chain_intact"] is True

        status, paused = _call(
            self.BASE, "/api/security/autopilot", fresh, {"mode": "off"}, "POST",
        )
        assert status == 200
        assert paused["mode"] == "off"
        assert paused["closes_sessions"] is False
        status, resumed = _call(
            self.BASE, "/api/security/autopilot", fresh, {"mode": "assess"}, "POST",
        )
        assert status == 200
        assert resumed["mode"] == "assess"

        status, outsider = _call(self.BASE, "/api/security/autopilot", other)
        assert status in (401, 403)
